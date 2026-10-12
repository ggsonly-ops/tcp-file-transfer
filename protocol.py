

import json

VERSION = "HERMES/1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000

CHUNK = 64 * 1024

MAX_FILE = 2 * 1024 * 1024 * 1024    


class Connection:
    

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

   

    def send(self, header, body=b""):
        if body:
            header = dict(header, bytes=len(body))
        line = (json.dumps(header) + "\n").encode("utf-8")
        self.sock.sendall(line + body)

    def send_file(self, header, fileobj, size):
        header = dict(header, bytes=size)
        self.sock.sendall((json.dumps(header) + "\n").encode("utf-8"))
        left = size
        while left > 0:
            block = fileobj.read(min(CHUNK, left))
            if not block:
                raise ConnectionError("file ended before the declared size")
            self.sock.sendall(block)
            left -= len(block)

   

    def recv_header(self):
        while b"\n" not in self.buf:
            data = self.sock.recv(CHUNK)
            if not data:
                raise ConnectionError("peer closed the connection")
            self.buf += data
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def recv_chunks(self, size):
        
        left = size
        if self.buf:                       # leftovers from the header read
            take = min(len(self.buf), left)
            block, self.buf = self.buf[:take], self.buf[take:]
            left -= take
            yield block
        while left > 0:
            data = self.sock.recv(min(CHUNK, left))
            if not data:
                raise ConnectionError("peer closed during transfer")
            left -= len(data)
            yield data

    def recv_to_file(self, fileobj, size):
        for block in self.recv_chunks(size):
            fileobj.write(block)

    def drain(self, size):
        for _ in self.recv_chunks(size):
            pass

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def safe_name(name):
   
    return (isinstance(name, str) and name != "" and "/" not in name
            and "\\" not in name and name not in (".", ".."))


def human(n):
    
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
