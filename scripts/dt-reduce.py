#!/usr/bin/env python3
"""Disable or remove nodes in a decompiled device tree, for bisection.

    scripts/dt-reduce.py [-d GLOB]... [-r GLOB]... [-k GLOB]... <in.dts> <out.dts>

    -d  disable: give the node status = "disabled", so the kernel creates no
        platform device for it and no driver probes it
    -r  remove: delete the node and everything under it
    -k  keep: exempt from both, applied after -d and -r, so the usual shape of
        a run is "disable everything under /soc@0, keep these three"

GLOB is fnmatch against the node's full path, as in /soc@0/usb@a6f8800. The
root node is the empty path, so -d '/soc@0/*' names exactly the direct
children of /soc@0 and -d '/soc@0/**' is not needed: fnmatch's * crosses /.

Why this exists
---------------

This port has one bit of output per boot. The device has no UART broken out,
its DRAM is scrubbed by the bootloader between boots, and its panel is command
mode so nothing pushes whatever a framebuffer console writes - docs/05-status.md
has the evidence for each. What is left is the bootloader's A/B fallback: flash
one slot, and whether the phone comes up on that slot or the other one says
whether the kernel lived. With panic=N on the command line the *time* it takes
to fall back is readable too, to about a seventh of a second, because the
bootloader makes seven attempts and they add up.

One bit per nine minutes puts a premium on which question each round asks, and
the cheapest large question is the device tree. A kernel rebuild for this
device costs 63 minutes; a device tree costs one dtc invocation, and the device
tree is also the half of the port that was written by hand. So the useful loop
is: reduce the tree, flash, see whether the death moves, and bisect on what
changed. try-kernel.sh takes DTB=path for exactly this.

Operating on the decompiled tree rather than the source
-------------------------------------------------------

The input is dtc -I dtb -O dts output, not our .dts source, for two reasons.
The source needs the C preprocessor and the kernel's include path, so editing
it means a kbuild run; and the source is what we are trying to find a bug in,
so a variant built from it would carry every macro and every override along
with it. The decompiled tree is the flat, literal thing the bootloader hands
the kernel, which is the thing a round actually tests.

That round trip is exact. Verified on 2026-10-07: decompiling
sm6450-sony-xperia-columbia-pdx246.dtb and recompiling it with no edits
reproduces the original 30410 bytes byte for byte. So a variant differs from
the shipped tree only where this script edited it.

Dangling phandles are fine
--------------------------

A removed node may be referenced by a phandle elsewhere. In a decompiled tree
every reference is already a bare integer rather than a label, so dtc compiles
the result without complaint and the kernel simply fails to find the provider -
which for a bisection variant is the intended outcome, not a problem. It does
mean dtc cannot warn about it, so -r is the sharper of the two knobs; prefer -d
where a node can be disabled, because a disabled node is a configuration the
kernel is designed to handle.
"""
import fnmatch
import re
import sys

# A node opens with an optional label, a name, and a brace. Property lines
# always carry = or end in ;, so requiring the line to end in { is enough.
OPEN = re.compile(r"^(\s*)(?:[\w-]+:\s*)?([\w,.+@-]+)\s*\{$")
ROOT = re.compile(r"^(\s*)/\s*\{$")
STATUS = re.compile(r'^\s*status = "[a-z-]*";$')


def main(argv):
    disable, remove, keep, args = [], [], [], []
    it = iter(argv[1:])
    for a in it:
        if a in ("-d", "-r", "-k"):
            try:
                v = next(it)
            except StopIteration:
                return usage(argv, f"{a} needs a pattern")
            {"-d": disable, "-r": remove, "-k": keep}[a].append(v)
        else:
            args.append(a)
    if len(args) != 2:
        return usage(argv, "need exactly one input and one output")

    def hit(pats, path):
        return any(fnmatch.fnmatchcase(path, p) for p in pats)

    out, stack, acted = [], [], []
    # Depth of the outermost node being removed, or None. Everything inside a
    # removed node goes too, and its own closing brace is what ends the skip.
    cutting = None
    for line in open(args[0]):
        s = line.rstrip("\n")
        m = ROOT.match(s) or OPEN.match(s)
        if m:
            name = "" if ROOT.match(s) else m.group(2)
            stack.append(name)
            path = "/".join(stack)
            if cutting is not None:
                continue
            if hit(remove, path) and not hit(keep, path):
                cutting = len(stack)
                acted.append(("removed ", path))
                continue
            out.append(s)
            if hit(disable, path) and not hit(keep, path):
                out.append(m.group(1) + '\tstatus = "disabled";')
                acted.append(("disabled", path))
            continue
        if s.strip().startswith("};"):
            if cutting is not None and len(stack) == cutting:
                cutting = None
                stack.pop()
                continue
            if stack:
                stack.pop()
            if cutting is None:
                out.append(s)
            continue
        if cutting is not None:
            continue
        # A node we just disabled must not also carry its original status.
        path = "/".join(stack)
        if STATUS.match(s) and hit(disable, path) and not hit(keep, path):
            continue
        out.append(s)

    if stack:
        return usage(argv, f"unbalanced braces: still inside {stack}")
    with open(args[1], "w") as fh:
        fh.write("\n".join(out) + "\n")
    for what, path in acted:
        print(f"    {what}  {path or '/'}")
    print(f"==> {args[1]}  ({len(acted)} nodes touched)")
    return 0


def usage(argv, why):
    print(f"error: {why}", file=sys.stderr)
    print(__doc__.split("\n\n")[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
