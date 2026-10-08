#!/usr/bin/env python3
"""Run commands in the initramfs shell over telnet, each to completion.

scripts/telnet.py is for a person: it forwards a terminal, and when its input
is a pipe it stops listening two seconds after the pipe runs dry, which cuts
off anything slower than that. This waits instead. Each command is followed
by a marker that only the command finishing can print, and the next command
is not sent until it has:

    scripts/tsh.py 'cat /sys/kernel/debug/devices_deferred'
    scripts/tsh.py -t 120 -f commands.sh

With -f, every non-blank line of the file that is not a comment is one
command, and the transcript shows each under a "$ " header. A command that
resets the phone ends the connection, and with it the run; that is reported
and is not an error in itself, so a file can end with a deliberate reset.

The exit status is the last command's, 124 if one ran past its timeout, and
1 if the shell could not be reached or went away.

This is the same channel as scripts/ssh.py, one stage earlier: the telnetd
that pmos.debug-shell starts on 172.16.42.1:23, before switch_root.
"""

import argparse
import os
import re
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telnet import strip_iac  # noqa: E402

# Printed by printf from octal escapes, so the shell's echo of the command
# line, which carries the escapes and not the characters, cannot match it.
MARK_CMD = r"printf '\100\100TSH-DONE %s\n' $?"
MARK_RE = re.compile(rb"@@TSH-DONE (\d+)\r?\n")


class Gone(Exception):
    pass


def read_until_mark(sock, buf, timeout):
    deadline = time.time() + timeout
    while True:
        m = MARK_RE.search(buf)
        if m:
            return buf[:m.start()], int(m.group(1)), buf[m.end():]
        left = deadline - time.time()
        if left <= 0:
            raise TimeoutError(buf)
        sock.settimeout(min(left, 5.0))
        try:
            data = sock.recv(65536)
        except socket.timeout:
            continue
        except OSError as e:
            raise Gone(buf) from e
        if not data:
            raise Gone(buf)
        buf += strip_iac(data, sock)


# Terminal control sequences: busybox ls colours its output on a pty, and
# none of it means anything in a transcript.
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean(raw):
    text = ANSI_RE.sub("", raw.decode("utf-8", "replace").replace("\r", ""))
    lines = text.split("\n")
    # The handshake turns echo off; should stty be missing, the shell's echo
    # of the command line comes first, and it carries the marker's escapes.
    if lines and "TSH-DONE" in lines[0]:
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", nargs="?")
    ap.add_argument("-f", "--file")
    ap.add_argument("-t", "--timeout", type=float, default=60.0,
                    help="seconds each command may take (default 60)")
    ap.add_argument("--host", default=os.environ.get("PMOS_HOST", "172.16.42.1"))
    ap.add_argument("--port", type=int, default=23)
    args = ap.parse_args()

    if args.file:
        with open(args.file) as f:
            commands = [ln.rstrip("\n") for ln in f
                        if ln.strip() and not ln.lstrip().startswith("#")]
    elif args.command:
        commands = [args.command]
    else:
        ap.error("give a command or -f FILE")
    many = len(commands) > 1 or bool(args.file)

    try:
        sock = socket.create_connection((args.host, args.port), timeout=10)
    except OSError as e:
        print(f"tsh: cannot reach {args.host}:{args.port}: {e}", file=sys.stderr)
        return 1

    # Let the greeting and the first prompt arrive, so that they are not
    # taken for the first command's output, and turn off the two things
    # that would be mixed into every later one: the pty's echo of what is
    # sent, and the prompt.
    buf = b""
    try:
        sock.sendall(b"\nstty -echo 2>/dev/null; PS1=''; "
                     + MARK_CMD.encode() + b"\n")
        _, _, buf = read_until_mark(sock, buf, 30)
    except (TimeoutError, Gone):
        print("tsh: the shell did not answer", file=sys.stderr)
        return 1

    status = 0
    for command in commands:
        if many:
            print(f"$ {command}", flush=True)
        sock.sendall(command.encode() + b"\n" + MARK_CMD.encode() + b"\n")
        try:
            out, status, buf = read_until_mark(sock, buf, args.timeout)
        except TimeoutError as e:
            print(clean(e.args[0]), flush=True)
            print(f"tsh: still running after {args.timeout:.0f} s; giving up",
                  file=sys.stderr)
            return 124
        except Gone as e:
            print(clean(e.args[0]), flush=True)
            print("tsh: the connection closed - the phone reset or the shell"
                  " exited", file=sys.stderr)
            return 1
        text = clean(out)
        if text:
            print(text, flush=True)
        if many and status:
            print(f"[exit {status}]", flush=True)
    sock.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
