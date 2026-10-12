

import argparse
import os
import socket
import threading

from protocol import (VERSION, DEFAULT_PORT, MAX_FILE, Connection,
                      safe_name, human)

FILES_DIR = "server_files"          

accounts = {}                       
online = {}                        
lock = threading.Lock()            


class Client:
    

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.name = None
        self.send_lock = threading.Lock()

    def send(self, header, body=b""):
        with self.send_lock:
            self.conn.send(header, body)

    def push(self, header, body=b""):
       
        try:
            self.send(header, body)
        except OSError:
            pass


def error(client, reason):
    client.send({"op": "error", "reason": reason})


def handle_login(client, msg):
    user = msg.get("user")
    password = msg.get("pass", "")
    if not user or not isinstance(user, str) or " " in user:
        return error(client, "BAD_REQUEST")
    with lock:
        if user in online:                     
            return error(client, "USER_ALREADY_ONLINE")
        if user in accounts and accounts[user] != password:
            return error(client, "BAD_PASSWORD")
        accounts.setdefault(user, password)   
        client.name = user
        online[user] = client
        others = [c for c in online.values() if c is not client]
    print("[+] %s logged in (%d online)" % (user, len(online)))
    client.send({"op": "ok", "user": user})
    for other in others:
        other.push({"op": "notice", "text": "%s joined" % user})


def handle_msg(client, msg):
    to = msg.get("to")
    with lock:
        target = online.get(to)
    if target is None:
        return error(client, "NO_SUCH_USER")
    target.push({"op": "msg", "from": client.name, "text": msg.get("text", "")})
    client.send({"op": "ok", "sent_to": to})


def handle_broadcast(client, msg):
    with lock:
        others = [c for c in online.values() if c is not client]
    for other in others:
        other.push({"op": "broadcast", "from": client.name,
                    "text": msg.get("text", "")})
    client.send({"op": "ok", "recipients": len(others)})


def handle_list(client, msg):
    with lock:
        users = sorted(online.keys())
    client.send({"op": "ok", "users": users})


def handle_upload(client, msg):
    name = msg.get("name")
    size = msg.get("bytes", 0)
    if not safe_name(name) or not isinstance(size, int) or not 0 <= size <= MAX_FILE:
        client.conn.drain(size if isinstance(size, int) and size > 0 else 0)
        return error(client, "BAD_NAME")
    path = os.path.join(FILES_DIR, name)
    with open(path, "wb") as f:
        client.conn.recv_to_file(f, size)
    print("[>] %s uploaded %s (%s)" % (client.name, name, human(size)))
    client.send({"op": "ok", "stored": name, "size": size})


def handle_download(client, msg):
    name = msg.get("name")
    if not safe_name(name):
        return error(client, "BAD_NAME")
    path = os.path.join(FILES_DIR, name)
    if not os.path.isfile(path):
        return error(client, "NO_SUCH_FILE")
    size = os.path.getsize(path)
   
    with client.send_lock, open(path, "rb") as f:
        client.conn.send_file({"op": "ok", "name": name}, f, size)
    print("[<] %s downloaded %s (%s)" % (client.name, name, human(size)))


def handle_sendfile(client, msg):
    to = msg.get("to")
    name = msg.get("name")
    size = msg.get("bytes", 0)
    with lock:
        target = online.get(to)
    if target is None or not safe_name(name):
        client.conn.drain(size if isinstance(size, int) and size > 0 else 0)
        return error(client, "NO_SUCH_USER" if target is None else "BAD_NAME")

  
    delivered = True
    with target.send_lock:
        try:
            target.conn.send({"op": "file", "from": client.name,
                              "name": name, "bytes": size})
        except OSError:
            delivered = False
        for block in client.conn.recv_chunks(size):
            if delivered:
                try:
                    target.conn.sock.sendall(block)
                except OSError:
                    delivered = False
    if not delivered:
        return error(client, "NO_SUCH_USER")
    print("[=] %s sent %s (%s) to %s" % (client.name, name, human(size), to))
    client.send({"op": "ok", "sent_to": to})


HANDLERS = {
    "msg": handle_msg,
    "broadcast": handle_broadcast,
    "list": handle_list,
    "upload": handle_upload,
    "download": handle_download,
    "sendfile": handle_sendfile,
}


def serve_client(sock, addr):
    client = Client(Connection(sock), addr)
    try:
        client.send({"op": "hello", "version": VERSION})
        while True:
            msg = client.conn.recv_header()
            op = msg.get("op")

            if op == "login":
                handle_login(client, msg)
            elif op == "ping":
                client.send({"op": "ok"})
            elif op == "logout":
                client.send({"op": "ok", "bye": True})
                break
            elif client.name is None:
                
                client.conn.drain(msg.get("bytes", 0))
                error(client, "NOT_LOGGED_IN")
            elif op in HANDLERS:
                HANDLERS[op](client, msg)
            else:
                client.conn.drain(msg.get("bytes", 0))
                error(client, "UNKNOWN_OP")

    except (ConnectionError, OSError, ValueError):
       
        pass
    finally:
        with lock:
            if client.name and online.get(client.name) is client:
                del online[client.name]
                left = client.name
                others = list(online.values())
            else:
                left, others = None, []
        client.conn.close()
        if left:
            print("[-] %s left (%d online)" % (left, len(others)))
            for other in others:
                other.push({"op": "notice", "text": "%s left" % left})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    os.makedirs(FILES_DIR, exist_ok=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(20)
    print("%s server listening on %s:%d" % (VERSION, args.host, args.port))

    try:
        while True:
            sock, addr = server.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            t = threading.Thread(target=serve_client, args=(sock, addr))
            t.daemon = True
            t.start()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.close()


if __name__ == "__main__":
    main()
