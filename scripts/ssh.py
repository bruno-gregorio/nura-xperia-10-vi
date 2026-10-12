#!/usr/bin/env python3
"""Run commands on the booted phone over ssh, answering the password prompts.

Once the port switches root, the initramfs telnetd is gone and sshd is the way
in - see scripts/tsh.py for the stage before this one. OpenSSH will not take
a password from a pipe by design, sshpass is not on the host, and this project
is not allowed to install anything there, so the password goes in over a pty.
The same answer serves sudo's prompt on the phone, which asks for the same
password.

Defaults match what scripts/make-rootfs-img.sh builds and what the USB gadget
hands out, so the common case needs no arguments:

    scripts/ssh.py 'rc-status'
    scripts/ssh.py -t 300 -f commands.sh

With -f, the file is a plan's live commands, the way scripts/tsh.py takes
them in the debug shell: every non-blank line that is not a comment is one
command, run as root, each over its own connection and under a "$ " header.
Four lines are not commands:

    @hold                     hold the phone, see below
    @release                  let it go again
    @push local remote        copy a file over, executable, as root
    @pull remote local        copy a file back, read as root

The hold is the initramfs's. Its log hook and USB watchdog outlive the switch
to the rootfs (scripts/bootlog.py, KEEP_SH), still in the initramfs's root,
and still reset the phone unless /pmhold is there and fresh. From the rootfs
that file is /proc/<pid>/root/pmhold for any process left in that root, the
kernel's own threads among them. Every command renews a hold that exists,
as tsh.py does, and each one finds that root in $J.

Overridable through PMOS_HOST, PMOS_USER, PMOS_PASS and PMOS_TIMEOUT. The
password is a throwaway on a development phone and is in the docs already; it
is a default rather than a secret.
"""
import argparse
import base64
import binascii
import hashlib
import os
import pty
import select
import shlex
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOST = os.environ.get("PMOS_HOST", "172.16.42.1")
USER = os.environ.get("PMOS_USER", "user")
PASSWORD = os.environ.get("PMOS_PASS", "147147")
TIMEOUT = float(os.environ.get("PMOS_TIMEOUT", "60"))

SSH_OPTS = [
    # The phone's host key changes on every rootfs rebuild, and the link is
    # a USB cable with one device on it, so pinning it would only ever cost
    # us a confusing failure.
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
    # Without this a wrong password turns into three prompts and a hang.
    "-o", "NumberOfPasswordPrompts=1",
]

# ssh's prompt, then at most sudo's; a third would be a wrong password.
MAX_PROMPTS = 2

# Sets J to the initramfs's root as the jobs see it, and renews a hold that
# is there. /pmkeep is a mount, so it outlives the switch, and the rootfs has
# no such directory of its own. The jobs started early and their pids are
# short; a glob sorts by name, so /proc/[0-9]* alone put round 85's 12603, a
# job's passing child, before the jobs' 129, and it was gone by the touch.
PREFIX = ('J=; for r in /proc/[0-9]/root /proc/[0-9][0-9]/root '
          '/proc/[0-9][0-9][0-9]/root /proc/[0-9]*/root; do '
          '[ -e "$r/pmkeep/bin/busybox" ] && { J=$r; break; }; done; '
          '[ -z "$J" ] || [ ! -e "$J/pmhold" ] || touch "$J/pmhold"; ')
HOLD = ('if [ -n "$J" ]; then touch "$J/pmhold" && echo "held through $J"; '
        'else echo "no initramfs root to hold"; false; fi')
RELEASE = ('if [ -n "$J" ]; then rm -f "$J/pmhold" && echo "released"; '
           'else echo "no initramfs root to release"; fi')


def run_pty(argv, timeout, stdin_path=None):
    """Run argv on a pty, answering password prompts; return (text, status).

    With stdin_path, the file is the command's standard input and the pty
    is only its controlling terminal, which is where ssh asks for the
    password anyway.
    """
    pid, fd = pty.fork()
    if pid == 0:
        if stdin_path:
            f = os.open(stdin_path, os.O_RDONLY)
            os.dup2(f, 0)
            os.close(f)
        os.execvp(argv[0], argv)

    out = b""
    answered = 0
    seen = 0
    timed_out = False
    deadline = time.time() + timeout
    while True:
        left = deadline - time.time()
        if left <= 0:
            timed_out = True
            break
        if not select.select([fd], [], [], min(left, 0.5))[0]:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        # Only a prompt that came after the last one answered counts, so
        # one prompt is never answered twice.
        at = out.find(b"assword", seen)
        if at >= 0 and answered < MAX_PROMPTS:
            os.write(fd, PASSWORD.encode() + b"\n")
            answered += 1
            seen = at + len(b"assword")
    if timed_out:
        os.kill(pid, signal.SIGTERM)
    os.close(fd)
    try:
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        code = 0
    if timed_out:
        code = 124

    text = out.decode("utf-8", "replace").replace("\r\n", "\n")
    # The prompts we answered and ssh's own goodbye are not part of the
    # output.
    keep = [ln for ln in text.split("\n")
            if "assword" not in ln and not ln.startswith("Connection to ")]
    return "\n".join(keep).strip(), code


def ssh(command, timeout, tty=True, stdin_path=None):
    argv = ["ssh"] + (["-tt"] if tty else []) + SSH_OPTS \
        + [f"{USER}@{HOST}", command]
    return run_pty(argv, timeout, stdin_path)


def as_root(text):
    return "sudo sh -c " + shlex.quote(PREFIX + text)


def push(local, remote, timeout):
    path = local if os.path.isabs(local) else os.path.join(ROOT, local)
    if not os.path.isfile(path):
        return f"ssh.py: no {path}", 1
    size = os.path.getsize(path)
    tmp = "/tmp/.ssh-py-push"
    # No -tt here: the file goes over the session's standard input, which a
    # remote pty would mangle.
    out, code = ssh(f"cat > {tmp}", timeout, tty=False, stdin_path=path)
    if code:
        return out or f"ssh.py: copying {local} failed", code
    out, code = ssh(as_root(
        f"install -D -m 755 {tmp} {shlex.quote(remote)} && rm -f {tmp}"
        f" && wc -c < {shlex.quote(remote)}"), timeout)
    if code:
        return out, code
    got = out.strip().split("\n")[-1].strip()
    if got != str(size):
        return f"{remote} is {got or '?'} bytes, not {size}", 1
    return f"{local} -> {remote}, {size} bytes", 0


def pull(remote, local, timeout):
    path = local if os.path.isabs(local) else os.path.join(ROOT, local)
    tmp = "/tmp/.ssh-py-pull"
    out, code = ssh(as_root(
        f"install -m 600 -o {USER} {shlex.quote(remote)} {tmp}"
        f" && sha256sum < {tmp}"), timeout)
    if code:
        return out, code
    want = out.strip().split("\n")[-1].split(" ")[0]
    # The bytes come back as base64, because the pty that answers ssh's
    # password prompt would mangle them raw.
    out, code = ssh(f"base64 {tmp}; rc=$?; rm -f {tmp}; exit $rc", timeout,
                    tty=False)
    if code:
        return out, code
    lines = [ln.strip() for ln in out.split("\n")]
    try:
        data = base64.b64decode("".join(ln for ln in lines if ln),
                                validate=True)
    except (binascii.Error, ValueError) as e:
        return f"ssh.py: {remote} came back garbled: {e}", 1
    if hashlib.sha256(data).hexdigest() != want:
        return f"ssh.py: {remote} came back with the wrong checksum", 1
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return f"{remote} -> {local}, {len(data)} bytes", 0


def run_file(path, timeout):
    with open(path) as f:
        commands = [ln.rstrip("\n") for ln in f
                    if ln.strip() and not ln.lstrip().startswith("#")]
    code = 0
    for command in commands:
        print(f"$ {command}", flush=True)
        words = command.split()
        if words[0] == "@push" and len(words) == 3:
            out, code = push(words[1], words[2], timeout)
        elif words[0] == "@pull" and len(words) == 3:
            out, code = pull(words[1], words[2], timeout)
        elif words == ["@hold"]:
            # Early in a boot the link drops for a few seconds whenever the
            # ADSP starts or restarts, and a hold that missed leaves the
            # phone to the log hook's backup reset. So it gets a minute.
            for attempt in range(6):
                out, code = ssh(as_root(HOLD), timeout)
                if code == 0:
                    break
                time.sleep(10)
        elif words == ["@release"]:
            out, code = ssh(as_root(RELEASE), timeout)
        else:
            out, code = ssh(as_root(command), timeout)
        if out:
            print(out, flush=True)
        if code == 124:
            print(f"ssh.py: still running after {timeout:.0f} s; gave up on it",
                  flush=True)
        if code:
            print(f"[exit {code}]", flush=True)
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", nargs="?")
    ap.add_argument("-f", "--file")
    ap.add_argument("-t", "--timeout", type=float, default=TIMEOUT,
                    help=f"seconds each command may take (default {TIMEOUT:.0f})")
    args = ap.parse_args()
    if args.file:
        return run_file(args.file, args.timeout)
    out, code = ssh(args.command or "true", args.timeout)
    print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
