#!/usr/bin/env python3
"""A minimal telnet client, because the host has none and may not get one.

The postmarketOS initramfs debug shell is a busybox telnetd on 172.16.42.1:23.
Fedora ships no telnet, nc or socat by default, and this project is not allowed
to install anything on the host - so this is the fallback that always works,
needing nothing but python3.

Not a full RFC 854 implementation. It refuses every option the server offers,
which is what you want for a debug shell: no echo negotiation, no window-size
tracking, just bytes in and bytes out.
"""
import os
import select
import socket
import sys

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


def strip_iac(data, sock):
    """Return data with telnet commands removed, refusing any option offered."""
    out, i = bytearray(), 0
    while i < len(data):
        if data[i] != IAC:
            out.append(data[i])
            i += 1
            continue
        if i + 1 >= len(data):
            break                                    # split command, drop it
        cmd = data[i + 1]
        if cmd == IAC:                               # escaped 0xff
            out.append(IAC)
            i += 2
        elif cmd in (DO, DONT, WILL, WONT):
            if i + 2 >= len(data):
                break
            opt = data[i + 2]
            # Say no to everything: DO -> WONT, WILL -> DONT.
            reply = WONT if cmd == DO else DONT
            if cmd in (DO, WILL):
                try:
                    sock.sendall(bytes([IAC, reply, opt]))
                except OSError:
                    pass
            i += 3
        elif cmd == SB:                              # subnegotiation, skip to SE
            j = data.find(bytes([IAC, SE]), i)
            i = len(data) if j < 0 else j + 2
        else:
            i += 2
    return bytes(out)


def main(argv):
    host = argv[1] if len(argv) > 1 else "172.16.42.1"
    port = int(argv[2]) if len(argv) > 2 else 23
    try:
        sock = socket.create_connection((host, port), timeout=10)
    except OSError as e:
        print(f"telnet: cannot reach {host}:{port}: {e}", file=sys.stderr)
        return 1
    sock.settimeout(None)
    print(f"[connected to {host}:{port} - ctrl-] then ctrl-c to quit]",
          file=sys.stderr)

    # Raw mode only makes sense on a terminal; piped input must still work, so
    # that this is testable without a device on the other end.
    interactive = sys.stdin.isatty()
    saved = None
    if interactive:
        import termios
        import tty
        saved = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
    try:
        while True:
            r, _, _ = select.select([sock, sys.stdin], [], [])
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    break
                clean = strip_iac(data, sock)
                if clean:
                    sys.stdout.buffer.write(clean)
                    sys.stdout.buffer.flush()
            if sys.stdin in r:
                buf = os.read(sys.stdin.fileno(), 4096)
                if not buf:
                    # Piped input ran out. Keep reading the socket briefly so
                    # the command's output is not lost, then stop.
                    sock.shutdown(socket.SHUT_WR)
                    while True:
                        r2, _, _ = select.select([sock], [], [], 2.0)
                        if not r2:
                            break
                        data = sock.recv(4096)
                        if not data:
                            break
                        clean = strip_iac(data, sock)
                        if clean:
                            sys.stdout.buffer.write(clean)
                            sys.stdout.buffer.flush()
                    break
                if buf == b"\x1d":                   # ctrl-]
                    break
                sock.sendall(buf)
    finally:
        if saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
        sock.close()
    print("\n[connection closed]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
