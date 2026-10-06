#!/usr/bin/env python3
"""Run a command on the booted phone over ssh, answering the password prompt.

Once the port switches root, the initramfs telnetd is gone and sshd is the way
in - see scripts/telnet.py for the stage before this one. OpenSSH will not take
a password from a pipe by design, sshpass is not on the host, and this project
is not allowed to install anything there, so the password goes in over a pty.

Defaults match what scripts/make-rootfs-img.sh builds and what the USB gadget
hands out, so the common case needs no arguments:

    scripts/ssh.py 'systemctl is-system-running'

Overridable through PMOS_HOST, PMOS_USER, PMOS_PASS and PMOS_TIMEOUT. The
password is a throwaway on a development phone and is in the docs already; it
is a default rather than a secret.
"""
import os
import pty
import select
import sys
import time

HOST = os.environ.get("PMOS_HOST", "172.16.42.1")
USER = os.environ.get("PMOS_USER", "user")
PASSWORD = os.environ.get("PMOS_PASS", "147147")
TIMEOUT = float(os.environ.get("PMOS_TIMEOUT", "60"))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "true"
    argv = [
        "ssh", "-tt",
        # The phone's host key changes on every rootfs rebuild, and the link is
        # a USB cable with one device on it, so pinning it would only ever cost
        # us a confusing failure.
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "ConnectTimeout=10",
        # Without this a wrong password turns into three prompts and a hang.
        "-o", "NumberOfPasswordPrompts=1",
        f"{USER}@{HOST}", command,
    ]

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(argv[0], argv)

    out = b""
    sent = False
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if not select.select([fd], [], [], 0.5)[0]:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if not sent and b"assword" in out:
            os.write(fd, PASSWORD.encode() + b"\n")
            sent = True
    os.close(fd)
    try:
        _, status = os.waitpid(pid, 0)
    except ChildProcessError:
        status = 0

    text = out.decode("utf-8", "replace").replace("\r\n", "\n")
    # The prompt we answered and ssh's own goodbye are not part of the output.
    keep = [ln for ln in text.split("\n")
            if "assword" not in ln and not ln.startswith("Connection to ")]
    print("\n".join(keep).strip())
    return os.waitstatus_to_exitcode(status) if status else 0


if __name__ == "__main__":
    sys.exit(main())
