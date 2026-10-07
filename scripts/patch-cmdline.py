#!/usr/bin/env python3
"""Rewrite the kernel command line inside a vendor_boot image.

    scripts/patch-cmdline.py <in.img> [out.img] [-a ARG]... [-d GLOB]... [-s LINE]

    -a  append a token
    -d  delete every token matching a glob, so -d 'panic=*' -a panic=5 replaces
    -s  replace the whole line
    With no out.img and no edits, print the current line and exit.

Why the command line is patchable at all
----------------------------------------

For boot image header v3 and later the kernel's own `cmdline` field is empty -
verified on this device's boot.img, which uses all of 0 of its 1536 bytes -
and the command line lives in vendor_boot instead, at offset 28, 2048 bytes
long, of which pmbootstrap's generated line uses 240. The bootloader
concatenates it onto the bootargs it builds and the kernel sees the result.

What that is worth here
-----------------------

The sanctioned way to change this device's command line is to edit
kernel-cmdline.mainline.conf, sync it into .pmb/pmaports, re-checksum, sync
back, bump pkgrel, rebuild the device package, reindex, upgrade it in the
rootfs chroot and rebuild the initramfs. That is correct and it is what the
tree must end up containing - a round flashed from a patched image is not a
round anyone else can reproduce from the sources. But it is ten minutes per
question, and on a device whose only output channel is how long the bootloader
takes to give up, the command line is where most of the cheap questions live:
maxcpus, nokaslr, initcall_blacklist, oops=panic, a panic= sweep.

So this is for asking, and the conf file is for keeping. Anything that turns
out to matter belongs in the conf before it is believed.

Writing into the header rather than rebuilding the image
--------------------------------------------------------

The field is fixed-size and NUL-padded, so an edit is a single overwrite with
no reflow: nothing after offset 2076 moves, the ramdisk and dtb areas are
untouched, and the result differs from the input in at most 2048 bytes. The
one real constraint is length, and exceeding it is an error here rather than a
truncated line the bootloader would hand the kernel silently.
"""
import fnmatch
import sys

CMDLINE_OFF = 28
CMDLINE_LEN = 2048


def read(d):
    return d[CMDLINE_OFF:CMDLINE_OFF + CMDLINE_LEN].split(b"\0")[0].decode()


def write(d, line):
    raw = line.encode()
    if len(raw) >= CMDLINE_LEN:
        sys.exit(f"error: command line is {len(raw)} bytes, "
                 f"the field holds {CMDLINE_LEN - 1} plus a NUL")
    out = bytearray(d)
    out[CMDLINE_OFF:CMDLINE_OFF + CMDLINE_LEN] = raw.ljust(CMDLINE_LEN, b"\0")
    return bytes(out)


def main(argv):
    add, drop, setto, args = [], [], None, []
    it = iter(argv[1:])
    for a in it:
        if a in ("-a", "-d", "-s"):
            try:
                v = next(it)
            except StopIteration:
                sys.exit(f"error: {a} needs a value")
            if a == "-a":
                add.append(v)
            elif a == "-d":
                drop.append(v)
            else:
                setto = v
        else:
            args.append(a)
    if not 1 <= len(args) <= 2:
        print(__doc__.split("\n\n")[1].strip(), file=sys.stderr)
        return 2

    d = open(args[0], "rb").read()
    if d[:8] != b"VNDRBOOT":
        sys.exit(f"error: {args[0]} is not a vendor_boot image")
    before = read(d)
    if len(args) == 1 and not (add or drop or setto is not None):
        print(before)
        return 0

    toks = (setto if setto is not None else before).split()
    kept = [t for t in toks
            if not any(fnmatch.fnmatchcase(t, g) for g in drop)]
    removed = [t for t in toks if t not in kept]
    line = " ".join(kept + add)

    dst = args[1] if len(args) == 2 else args[0]
    open(dst, "wb").write(write(d, line))
    print(f"==> {dst}")
    for t in removed:
        print(f"    -  {t}")
    for t in add:
        print(f"    +  {t}")
    print(f"    {len(line)} of {CMDLINE_LEN - 1} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
