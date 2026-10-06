#!/usr/bin/env python3
"""Translate a vendor gcc clock id into the mainline define name.

Anything copied out of the stock device tree names its clocks by number, and
those numbers are not ours. Both headers carry the same names; the vendor's is
numbered in the vendor's order and ours is generated in upstream's, so an id
means nothing until it has been through the name. Getting this wrong is silent
- the dtb compiles and the driver gets the wrong clock - so it is done by
program.

    scripts/clkmap.py <id>...            # ids in any base, e.g. 0x6a or 106

Each line prints the id, the vendor name it resolves to, and whether that name
exists in our header. A name missing from ours is the interesting case: it
means the block needs a clock the generated driver does not define.

The vendor header is taken from $DS_GCC_HEADER, which must point at the
vendor's qcom,gcc-<soc>.h; ours from $MAINLINE_GCC_HEADER, defaulting to the
SM6450 one in out/linux. The vendor header restarts numbering for resets and
GDSCs, so names ending in _BCR or _GDSC are skipped and an id can still
resolve to more than one clock, in which case all of them are printed.
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
OURS = os.environ.get(
    "MAINLINE_GCC_HEADER",
    os.path.join(ROOT, "out/linux/include/dt-bindings/clock/qcom,sm6450-gcc.h"))
THEIRS = os.environ.get("DS_GCC_HEADER")


def defines(path):
    with open(path) as f:
        return {m.group(1): int(m.group(2)) for m in
                re.finditer(r"^#define\s+(\w+)\s+(\d+)\s*$", f.read(), re.M)}


def main():
    if not sys.argv[1:]:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        print("usage: %s <id>..." % sys.argv[0], file=sys.stderr)
        return 2
    if not THEIRS:
        print("set DS_GCC_HEADER to the vendor's qcom,gcc-<soc>.h",
              file=sys.stderr)
        return 2

    ours, theirs = defines(OURS), defines(THEIRS)
    by_id = {}
    for name, n in theirs.items():
        if name.endswith("_BCR") or name.endswith("_GDSC"):
            continue
        by_id.setdefault(n, []).append(name)

    missing = 0
    for arg in sys.argv[1:]:
        names = by_id.get(int(arg, 0))
        if not names:
            print("%-8s no vendor clock has this id" % arg)
            missing += 1
            continue
        for name in sorted(names):
            if name in ours:
                print("%-8s %s" % (arg, name))
            else:
                print("%-8s %s   NOT IN OURS" % (arg, name))
                missing += 1
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
