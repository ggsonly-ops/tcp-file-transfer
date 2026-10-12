

import argparse
import os
import statistics
import threading
import time

from client import Client
from protocol import DEFAULT_HOST, DEFAULT_PORT, human

HOST = DEFAULT_HOST
PORT = DEFAULT_PORT
results = []          


def log(line):
    print(line)
    results.append(line)


def new_client(user, quiet=True):
    cli = Client(HOST, PORT, download_dir="bench_downloads", quiet=quiet)
    cli.connect()
    reply = cli.login(user, "pw")
    if reply.get("op") != "ok":
        raise SystemExit("login failed for %s: %s" % (user, reply))
    return cli


def make_file(path, size):
    """Create a test file of exactly 'size' bytes."""
    if os.path.exists(path) and os.path.getsize(path) == size:
        return
    block = os.urandom(1024 * 1024)
    with open(path, "wb") as f:
        written = 0
        while written < size:
            n = min(len(block), size - written)
            f.write(block[:n])
            written += n


def parse_size(text):
    text = text.strip().upper()
    for suffix, mult in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if text.endswith(suffix):
            return int(float(text[:-2]) * mult)
    return int(text)


# ---------------------------------------------------------------- Test 1

def test1(rounds=500):
    log("\n=== Test 1: one client, message and response ===")
    cli = new_client("bench1")
    for _ in range(50):                      
        cli.ping()

    times = []
    for _ in range(rounds):
        start = time.time()
        cli.ping()
        times.append((time.time() - start) * 1000)
    cli.close()

    times.sort()
    log("rounds          : %d" % rounds)
    log("average RTT     : %.3f ms" % statistics.mean(times))
    log("median RTT      : %.3f ms" % statistics.median(times))
    log("minimum RTT     : %.3f ms" % times[0])
    log("maximum RTT     : %.3f ms" % times[-1])


# ---------------------------------------------------------------- Test 2

def test2(receivers=5, rounds=100):
    log("\n=== Test 2: server sends a message to %d clients ===" % receivers)
    arrivals = []
    arrivals_lock = threading.Lock()

    def record(msg):
        if msg.get("op") == "broadcast":
            with arrivals_lock:
                arrivals.append(time.time())

    clients = []
    for i in range(receivers):
        cli = new_client("bench2_rx%d" % i)
        cli.on_push = record
        clients.append(cli)
    sender = new_client("bench2_tx")

    times = []
    for r in range(rounds + 10):             
        with arrivals_lock:
            arrivals.clear()
        start = time.time()
        sender.broadcast("test message %d" % r)
        deadline = time.time() + 5
        while time.time() < deadline:
            with arrivals_lock:
                if len(arrivals) >= receivers:
                    break
            time.sleep(0.0002)
        with arrivals_lock:
            got = list(arrivals)
        if len(got) < receivers:
            raise SystemExit("only %d of %d clients received the broadcast"
                             % (len(got), receivers))
        if r >= 10:
            times.extend((t - start) * 1000 for t in got)

    sender.close()
    for cli in clients:
        cli.close()

    log("clients         : %d" % receivers)
    log("broadcasts      : %d" % rounds)
    log("average response: %.3f ms" % statistics.mean(times))
    log("median response : %.3f ms" % statistics.median(times))
    log("slowest         : %.3f ms" % max(times))


# ---------------------------------------------------------------- Test 3

def test3(sizes, clients=10):
    log("\n=== Test 3: %d clients downloading at the same time ===" % clients)

    uploader = new_client("bench3_up")
    for text in sizes:
        size = parse_size(text)
        name = "test_%s.bin" % text
        local = "bench_%s.bin" % text
        log("\nfile size: %s" % text)
        make_file(local, size)
        reply = uploader.upload(local, name)
        if reply.get("op") != "ok":
            raise SystemExit("upload failed: %s" % reply)

        start_barrier = threading.Barrier(clients)
        elapsed = [0.0] * clients
        failed = []

        def worker(i):
            cli = new_client("bench3_c%d_%s" % (i, text.replace(".", "")))
            start_barrier.wait()
            t0 = time.time()
            
            r = cli.download(name, os.devnull)
            elapsed[i] = time.time() - t0
            if r.get("op") != "ok":
                failed.append(r)
            cli.close()

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(clients)]
        wall_start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.time() - wall_start
        if failed:
            raise SystemExit("a download failed: %s" % failed[0])

        total = size * clients
        log("total moved     : %s" % human(total))
        log("wall clock      : %.3f s" % wall)
        log("throughput      : %s/s" % human(total / wall))
        log("fastest client  : %.3f s" % min(elapsed))
        log("slowest client  : %.3f s" % max(elapsed))
        os.remove(local)

    uploader.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--sizes", default="1MB,100MB,1GB")
    ap.add_argument("--clients", type=int, default=10)
    args = ap.parse_args()

    global HOST, PORT
    HOST, PORT = args.host, args.port

    log("HERMES/1.0 performance experiments")
    log("server: %s:%d" % (HOST, PORT))

    test1()
    test2()
    test3([s for s in args.sizes.split(",") if s], args.clients)

    with open("results.txt", "w") as f:
        f.write("\n".join(results) + "\n")
    print("\nresults also written to results.txt")


if __name__ == "__main__":
    main()
