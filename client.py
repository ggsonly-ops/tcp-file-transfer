

import argparse
import os
import queue
import socket
import sys
import threading
import time

from protocol import DEFAULT_HOST, DEFAULT_PORT, Connection, human

REPLIES = ("ok", "error", "hello")


class Client:

    def __init__(self, host, port, download_dir="downloads", quiet=False):
        self.host = host
        self.port = port
        self.download_dir = download_dir
        self.quiet = quiet
        self.conn = None
        self.replies = queue.Queue()
        self.running = False
        self.save_as = None          
        self.on_push = None          


    def connect(self):
        sock = socket.create_connection((self.host, self.port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.conn = Connection(sock)
        os.makedirs(self.download_dir, exist_ok=True)
        self.running = True
        t = threading.Thread(target=self.reader)
        t.daemon = True
        t.start()
        return self.replies.get(timeout=10)         

    def close(self):
        self.running = False
        if self.conn:
            self.conn.close()


    def reader(self):
        try:
            while self.running:
                msg = self.conn.recv_header()
                if msg.get("op") in REPLIES:
                    self.handle_reply(msg)
                else:
                    self.handle_push(msg)
        except (ConnectionError, OSError, ValueError) as exc:
            if self.running:
                self.running = False
                self.replies.put({"op": "error", "reason": "disconnected: %s" % exc})

    def handle_reply(self, msg):
        size = msg.get("bytes")
        if size:                                  
            path = self.save_as or os.path.join(self.download_dir, msg["name"])
            if path == os.devnull:                
                self.conn.drain(size)
            else:
                with open(path, "wb") as f:
                    self.conn.recv_to_file(f, size)
            msg["saved"] = path
        self.replies.put(msg)

    def handle_push(self, msg):
        op = msg.get("op")
        if op == "file":
            path = os.path.join(self.download_dir, msg["name"])
            with open(path, "wb") as f:
                self.conn.recv_to_file(f, msg["bytes"])
            text = "file %s (%s) saved to %s" % (msg["name"],
                                                 human(msg["bytes"]), path)
            line = "[from %s] %s" % (msg["from"], text)
        elif op == "notice":
            line = "[server] %s" % msg["text"]
        else:                                      
            tag = "to you" if op == "msg" else "to all"
            line = "[%s %s] %s" % (msg["from"], tag, msg["text"])

        if self.on_push:
            self.on_push(msg)
        if not self.quiet:
            print("\n" + line + "\n> ", end="", flush=True)


    def request(self, header, body=b""):
        self.conn.send(header, body)
        return self.replies.get(timeout=600)

    def login(self, user, password):
        return self.request({"op": "login", "user": user, "pass": password})

    def list_users(self):
        return self.request({"op": "list"})

    def msg(self, to, text):
        return self.request({"op": "msg", "to": to, "text": text})

    def broadcast(self, text):
        return self.request({"op": "broadcast", "text": text})

    def ping(self):
        return self.request({"op": "ping"})

    def upload(self, path, name=None):
        if not os.path.isfile(path):
            return {"op": "error", "reason": "no local file %s" % path}
        name = name or os.path.basename(path)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            self.conn.send_file({"op": "upload", "name": name}, f, size)
        return self.replies.get(timeout=600)

    def download(self, name, save_as=None):
        self.save_as = save_as
        try:
            return self.request({"op": "download", "name": name})
        finally:
            self.save_as = None

    def sendfile(self, to, path, name=None):
        if not os.path.isfile(path):
            return {"op": "error", "reason": "no local file %s" % path}
        name = name or os.path.basename(path)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            self.conn.send_file({"op": "sendfile", "to": to, "name": name},
                                f, size)
        return self.replies.get(timeout=600)

    def logout(self):
        return self.request({"op": "logout"})


HELP = """commands:
  login <user> <pass>            log in (first login creates the account)
  list                           who is online
  msg <user> <text...>           private message
  broadcast <text...>            message everyone else
  upload <local-file>            store a file on the server
  download <name> [save-as]      fetch a file from the server
  sendfile <user> <local-file>   send a file to another user
  ping                           measure round-trip time
  quit"""


def show(reply):
    if reply.get("op") == "error":
        print("error: %s" % reply.get("reason"))
    else:
        print(reply)


def shell(cli):
    print(HELP)
    while cli.running:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split(" ")
        cmd, args = parts[0].lower(), parts[1:]

        try:
            if cmd == "quit":
                show(cli.logout())
                break
            elif cmd == "help":
                print(HELP)
            elif cmd == "login" and len(args) == 2:
                show(cli.login(args[0], args[1]))
            elif cmd == "list":
                show(cli.list_users())
            elif cmd == "msg" and len(args) >= 2:
                show(cli.msg(args[0], " ".join(args[1:])))
            elif cmd == "broadcast" and args:
                show(cli.broadcast(" ".join(args)))
            elif cmd == "ping":
                start = time.time()
                cli.ping()
                print("round trip: %.3f ms" % ((time.time() - start) * 1000))
            elif cmd == "upload" and args:
                start = time.time()
                reply = cli.upload(args[0])
                rate(reply, os.path.getsize(args[0]), start)
            elif cmd == "download" and args:
                start = time.time()
                reply = cli.download(args[0], args[1] if len(args) > 1 else None)
                if reply.get("op") == "ok":
                    rate(reply, reply.get("bytes", 0), start)
                else:
                    show(reply)
            elif cmd == "sendfile" and len(args) >= 2:
                start = time.time()
                reply = cli.sendfile(args[0], args[1])
                rate(reply, os.path.getsize(args[1]), start)
            else:
                print("bad command -- type 'help'")
        except (ConnectionError, OSError, queue.Empty) as exc:
            print("connection problem: %s" % exc)
            break


def rate(reply, size, start):
    if reply.get("op") != "ok":
        return show(reply)
    seconds = max(time.time() - start, 1e-9)
    print("%s  (%s in %.3f s = %s/s)"
          % (reply, human(size), seconds, human(size / seconds)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--user", help="log in as this user on startup")
    ap.add_argument("--password", default="pw")
    ap.add_argument("--download-dir", default="downloads")
    args = ap.parse_args()

    cli = Client(args.host, args.port, args.download_dir)
    try:
        hello = cli.connect()
    except OSError as exc:
        print("cannot connect to %s:%d -- %s" % (args.host, args.port, exc))
        return 1
    print("connected to %s" % hello.get("version"))

    if args.user:
        reply = cli.login(args.user, args.password)
        show(reply)
        if reply.get("op") != "ok":
            cli.close()
            return 1

    shell(cli)
    cli.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
