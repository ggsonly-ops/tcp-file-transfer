# HERMES/1.0 — multi-client TCP messaging and file transfer

A chat and file-transfer server and client over raw TCP sockets, using an application-layer protocol designed from scratch (HERMES/1.0). Python standard library only.

- **Custom wire format:** one line of JSON per message; a `bytes` field announces exactly how many raw bytes follow. That length prefix is what turns TCP's byte stream into messages, so files travel as raw bytes with no Base64.
- **One connection, two directions:** replies and server pushes (private messages, broadcasts, incoming files, join/leave notices) share a single socket, told apart by their `op`.
- **Concurrency:** a thread per client, one lock for shared state and a per-client send lock, so a pushed message never interleaves with a reply on the same socket.
- **Constant memory:** files stream in 64 KB chunks between socket and disk, so a 1 GB transfer uses 64 KB of memory.
- **Measured (loopback, `results.txt`):** 0.049 ms average round-trip over 500 requests, and 10 clients downloading a 1 GB file at once at 5.3 GB/s aggregate.

Built for the Computer Networks course at IIIT-Delhi. The full protocol, with every command, error and sequence diagram, is in `Protocol_Specification.pdf`.

## 1. Requirements

| | |
|---|---|
| **Python** | 3.7 or newer (developed and tested on 3.14) |
| **Packages** | **None.** Standard library only — nothing to `pip install` |
| **OS** | macOS, Linux or Windows |
| **Disk** | A few MB, unless you run the 1 GB benchmark (see §7) |

Check your version first:

```
python3 --version
```

**On Windows**, the command is usually `python` rather than `python3`. Every
command below works the same way — just substitute `python` for `python3`.

---

## 2. Files in this folder

| File | What it is |
|---|---|
| `protocol.py` | The wire format. Imported by both the server and the client, so the two can never disagree about it. |
| `server.py` | The multi-threaded server. |
| `client.py` | The client and its interactive command shell. |
| `benchmark.py` | Three performance experiments (latency, fan-out, concurrent throughput). |
| `results.txt` | Output of the benchmark run quoted above. |
| `Protocol_Specification.pdf` | The full HERMES/1.0 protocol specification — message format, every command and reply, all error reasons, and sequence diagrams. |
| `README.md` | This file. |

These folders are created automatically as they are needed:

- `server_files/` — files uploaded to the server live here.
- `downloads/` — files another user sends you are saved here (or wherever
  `--download-dir` points).
- `bench_downloads/` — created by `benchmark.py`. The benchmark throws away
  what it downloads, so this stays empty.

---

## 3. Quick start (30 seconds)

**Terminal 1 — start the server:**

```
python3 server.py
```

```
HERMES/1.0 server listening on 0.0.0.0:9000
```

**Terminal 2 — connect a client:**

```
python3 client.py --user virat
```

```
connected to HERMES/1.0
{'op': 'ok', 'user': 'virat'}
```

The command list prints automatically and you get a `>` prompt. `list` shows
who is online, `quit` leaves.

`--user` logs you in immediately. The first login for a name creates the
account (password defaults to `pw`; use `--password` to set your own).
Without `--user` you get a prompt and log in by hand with
`login virat pw`.

---

## 4. Full demonstration with five concurrent clients

Open **six** terminals,
all in this folder.

**Terminal 1 — the server:**

```
python3 server.py
```

**Terminals 2 to 6 — one client each:**

```
python3 client.py --host 127.0.0.1 --port 9000 --user virat  --download-dir dl_virat
python3 client.py --host 127.0.0.1 --port 9000 --user rohit  --download-dir dl_rohit
python3 client.py --host 127.0.0.1 --port 9000 --user dhoni  --download-dir dl_dhoni
python3 client.py --host 127.0.0.1 --port 9000 --user bumrah --download-dir dl_bumrah
python3 client.py --host 127.0.0.1 --port 9000 --user gill   --download-dir dl_gill
```

`--download-dir` gives each user their own folder for received files, so it
is obvious who got what. It is optional.

The server terminal counts up as they connect:

```
[+] virat logged in (1 online)
[+] rohit logged in (2 online)
[+] dhoni logged in (3 online)
[+] bumrah logged in (4 online)
[+] gill logged in (5 online)
```

**Now make a file to transfer.** In any terminal:

```
python3 -c "open('demo.bin','wb').write(b'x'*5000000)"
```

**Then, in virat's terminal:**

```
list
broadcast good morning everyone
msg rohit are you batting first
upload demo.bin
sendfile dhoni demo.bin
```

**In rohit's terminal:**

```
download demo.bin copy.bin
```

What you should see:

- `list` returns all five names.
- The broadcast appears in the four other terminals as `[virat to all] …`
- The private message appears **only** in rohit's terminal as
  `[virat to you] …`
- `upload` reports `stored: demo.bin` and the file appears in
  `server_files/`.
- `download` writes `copy.bin` and reports the transfer rate.
- dhoni's terminal shows `[from virat] file demo.bin (4.8 MB) saved to
  dl_dhoni/demo.bin`.
- The server terminal logs each operation.

Type `quit` in any client and the others are told `[server] <name> left`.

**To prove a transfer arrived intact**, compare checksums:

```
python3 -c "import hashlib;print(hashlib.sha256(open('demo.bin','rb').read()).hexdigest())"
python3 -c "import hashlib;print(hashlib.sha256(open('copy.bin','rb').read()).hexdigest())"
```

The two hashes must match.

---

## 5. Command reference

Type these at the client's `>` prompt.

| Command | What it does |
|---|---|
| `login <user> <pass>` | Log in. First login for a name creates the account. |
| `list` | Show all users currently online. |
| `msg <user> <text…>` | Private message to one online user. |
| `broadcast <text…>` | Message every other online user. |
| `upload <local-file>` | Store a file on the server. |
| `download <name> [save-as]` | Fetch a file from the server. |
| `sendfile <user> <local-file>` | Send a file straight to another user. |
| `ping` | Measure the round-trip time to the server. |
| `help` | Print this list. |
| `quit` | Log out and exit. |

**Error replies you may see** — these are intentional, not crashes:

| Reply | Meaning |
|---|---|
| `USER_ALREADY_ONLINE` | Somebody is already logged in with that name. |
| `BAD_PASSWORD` | The account exists but the password is wrong. |
| `NOT_LOGGED_IN` | That command needs you to log in first. |
| `NO_SUCH_USER` | The recipient is not online. |
| `NO_SUCH_FILE` | The server has no file with that name. |
| `BAD_NAME` | Illegal filename — one containing `/` or `\`. |
| `BAD_REQUEST` | A field is missing or has a bad value. |
| `UNKNOWN_OP` | The server does not recognise that command. |

---

## 6. How it works

**Transport.** Each client opens one TCP connection to the server on port
9000 and keeps it open for the whole session. Commands go up it, and both
replies and pushed messages come back down the same one.

**Message format.** Every message is one line of JSON ending in a newline.
If that JSON has a `"bytes"` field, exactly that many raw bytes follow the
newline:

```
{"op": "msg", "to": "rohit", "text": "hello"}
{"op": "upload", "name": "demo.bin", "bytes": 5000000}   <5000000 raw bytes>
```

TCP is a stream of bytes with no message boundaries in it — one `recv()`
can return half a message or two messages joined together — so the receiver
has to be told where each message ends. Declaring the length does that, and
it means file data travels as raw bytes with no Base64 encoding and nothing
to escape.

**Replies and pushes.** The server sends exactly one reply per command
(`{"op":"ok",…}` or `{"op":"error","reason":…}`). It also *pushes* messages
the client never asked for: an incoming private message, a broadcast, a file
from another user, or a notice that somebody joined or left. A message from
the server is a reply if its `op` is `ok`, `error` or `hello`; anything else
is a push. That one check is why a single connection can carry both.

**Server concurrency.** One thread per connected client. The main thread
only accepts connections and starts threads, so a client uploading a large
file can never stop another client from connecting. Shared state (the
account table and the online-user table) is guarded by one lock, and each
client has a second lock on its own socket so that a message pushed from
another user's thread cannot interleave with a reply being written by that
client's own thread.

**Client concurrency.** Two threads. A reader thread owns the receiving side
and handles whatever arrives; the main thread reads what you type. That is
why a message from another user can appear on your screen while you are
halfway through typing a command.

**Large files.** Everything moves in 64 KB pieces straight between the
socket and the disk, so transferring a 1 GB file never uses more than 64 KB
of memory.

Full details — every command, every error, sequence diagrams — are in
`Protocol_Specification.pdf` in this folder.

---

## 7. Performance experiments

Start the server, then in a separate terminal:

```
python3 benchmark.py
```

This runs three experiments and writes `results.txt`:

1. **Test 1** — one client sends a message and waits for the reply, 500
   times. Reports round-trip time.
2. **Test 2** — the server sends one message out to 5 clients, 100 times.
   Reports average response time.
3. **Test 3** — 10 clients download the same file simultaneously, at 1 MB,
   100 MB and 1 GB. Reports server throughput.

Takes under a minute on a modern laptop, most of it the 1 GB case.

**The 1 GB case needs roughly 1.1 GB of free disk** and moves 10 GB in
total. To skip it:

```
python3 benchmark.py --sizes 1MB,100MB
```

Close any interactive clients first — idle clients still occupy a server
thread and add a little noise to the measurements.

Note that running the benchmark overwrites `results.txt`, so the numbers in
the file will no longer be the ones quoted above.

---

## 8. Options

```
python3 server.py --host 0.0.0.0 --port 9000
python3 client.py --host 127.0.0.1 --port 9000 --user virat --password pw --download-dir dl_virat
python3 benchmark.py --host 127.0.0.1 --port 9000 --sizes 1MB,100MB,1GB --clients 10
```

| Flag | Default | Meaning |
|---|---|---|
| `--host` (server) | `0.0.0.0` | Which address to listen on. `0.0.0.0` accepts connections from other machines. |
| `--port` | `9000` | TCP port. Change it on both server and client if 9000 is taken. |
| `--user`, `--password` | — / `pw` | Log in at startup instead of typing `login`. |
| `--download-dir` | `downloads` | Where files sent to you by other users are saved. |
| `--sizes`, `--clients` | `1MB,100MB,1GB` / `10` | Benchmark configuration. |

---

## 9. Running across two computers

The server already listens on all interfaces. First find the server
machine's IP address.

On macOS:

```
ipconfig getifaddr en0
```

On Linux:

```
hostname -I
```

On Windows, run `ipconfig` and look for the IPv4 Address.

Then from the other machine:

```
python3 client.py --host 192.168.1.42 --port 9000 --user virat
```

Both machines must be on the same network, and the server's firewall must
allow inbound connections on port 9000. On macOS you may get a prompt asking
whether to allow incoming connections for Python — click Allow.

---

## 10. Troubleshooting

**`OSError: [Errno 48] Address already in use`** (or `10048` on Windows)
An old server is still running on port 9000. Stop it with Ctrl-C in its
terminal, or kill it.

On macOS or Linux:

```
lsof -ti :9000 | xargs kill
```

On Windows, find the PID and then kill it:

```
netstat -ano | findstr :9000
taskkill /PID <pid> /F
```

Or just use another port: `python3 server.py --port 9500`, and pass
`--port 9500` to the clients too.

**`cannot connect to 127.0.0.1:9000`**
The server is not running, or it is on a different port. Start it first.

**`error: USER_ALREADY_ONLINE`**
Somebody is already logged in with that name. This is the duplicate-username
rejection working. Use a different name, or quit the other client. Accounts
are held in memory, so restarting the server clears them all.

**`ModuleNotFoundError: No module named 'protocol'`**
Run the commands from inside this folder — the client imports `protocol.py`
from the working directory.

**`python3: command not found` on Windows**
Use `python` instead. If that also fails, Python is not on your PATH;
reinstall it with the "Add Python to PATH" box ticked.

**Commands with `#` behave oddly in zsh**
zsh does not treat `#` as a comment in an interactive shell, so never paste
a command with a trailing `# comment` — it becomes an argument.

**A transfer seems to hang**
Large transfers take time; 1 GB over loopback takes about two seconds, and
much longer between two machines. The client prints the rate when it
finishes.

---

## 11. Notes and limitations

- Passwords are sent and stored **in plain text**, which assumes a trusted network. Adding TLS and hashed
  passwords is the obvious next step.
- Accounts live in memory only. Restarting the server forgets every account;
  uploaded files in `server_files/` survive.
- `sendfile` requires the recipient to be online. If they are not, the
  sender gets `NO_SUCH_USER`.
- One user may be logged in from one connection at a time.
- A single file is limited to 2 GB.