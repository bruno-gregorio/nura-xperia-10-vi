#!/usr/bin/env python3
"""Check a mainline device tree against the one the device actually boots.

docs/06-mainline.md explains why this exists: a hand-written sm6450.dtsi that
points a driver at the wrong address produces a dead phone and no message.
The stock firmware, though, hands the stock kernel a complete and correct
device tree for this exact board, and that tree can be read back:

    out/kbuild/scripts/dtc/dtc -I fs -O dts out/device-dump-root/devicetree/base

So every address and every interrupt we write down has a reference to be
checked against. That is not the same as checking the hardware - a register
block can be at the address we claim and still be driven wrong - but it does
close off the single largest class of mistake in a port like this.

    scripts/check-dt.py [--allow ADDR[=why]]... <ours.dts> <theirs.dts>

Two checks run:

- **Addresses.** Every unit address in our tree must appear somewhere in
  theirs. The two sides are read differently on purpose. Ours is taken from
  unit addresses only, because that is what we are asserting and a unit
  address is unambiguous. Theirs is taken from unit addresses *and* from every
  value a reg property could be hiding, under both the one-cell and the
  two-cell reading, because the stock tree is evidence and anything in it
  counts: its SPMI arbiter, for instance, names itself after its config block
  and carries the real core address inside reg. Addresses below 0x10000 are
  skipped on both sides: those are bus positions, not MMIO - SPMI slave ids,
  CPU MPIDRs, register offsets inside a PMIC - and the smallest real block on
  this SoC is at 0x100000.
- **Interrupts.** For every node the two trees agree on the address of, the
  interrupts property must match value for value. Nodes where one tree uses
  interrupts and the other interrupts-extended are reported separately
  instead of being compared, since the cell layouts are not comparable.

Exits nonzero if any address is unaccounted for, unless --allow names it.
A deviation that has been thought about is not a failure, but it does have to
be written down to pass, which is the point: --allow 0xf100000=tlmm-rebase
turns a silent difference into an argument someone can disagree with.
Interrupt differences are reported but never fail - the cell layouts differ
between interrupt parents often enough that a mismatch is weak evidence -
and docs/06-mainline.md says which of ours are deliberate.
"""
import re
import sys

# Below this, a unit address is a bus position, not a register block.
MMIO_MIN = 0x10000


def parse(path):
    """Read a .dts into (by_addr, all_nodes).

    by_addr maps a unit address to the node that carries it; all_nodes is
    every node, addressed or not, because a block can be described by a node
    with no unit address at all - the stock tree's EPSS is /soc/qcom,cpufreq-hw
    with both freq domains in its reg - and those still count as evidence.
    """
    by_addr, all_nodes = {}, []
    stack = []
    props = {}
    for line in open(path):
        s = line.strip()
        m = re.match(r"^(?:[\w-]+:\s*)?([\w,.+@-]+)\s*\{$", s)
        if m:
            stack.append((m.group(1), props))
            props = {}
            continue
        if s.startswith("};"):
            if not stack:
                continue
            name, outer = stack.pop()
            node = {"path": "/".join(n for n, _ in stack) + "/" + name,
                    "props": props}
            all_nodes.append(node)
            if "@" in name:
                try:
                    a = int(name.rsplit("@", 1)[1], 16)
                except ValueError:
                    a = None
                if a is not None and a >= MMIO_MIN:
                    by_addr.setdefault(a, node)
            props = outer
            continue
        m = re.match(r"^([\w,#-]+) = <([^>]*)>;$", s)
        if m:
            vals = []
            for tok in m.group(2).split():
                try:
                    vals.append(int(tok, 0))
                except ValueError:
                    vals.append(tok)
            props[m.group(1)] = vals
        elif re.match(r"^([\w,#-]+);$", s):
            props[s[:-1]] = []
    return by_addr, all_nodes


def addresses(by_addr, all_nodes):
    """Every address the tree can be read as describing."""
    seen = set(by_addr)
    for n in all_nodes:
        reg = [v for v in n["props"].get("reg", []) if isinstance(v, int)]
        if len(reg) % 2 == 0:
            seen.update(v for v in reg[0::2] if v >= MMIO_MIN)
        if len(reg) % 4 == 0:
            for i in range(0, len(reg), 4):
                v = reg[i] << 32 | reg[i + 1]
                if v >= MMIO_MIN:
                    seen.add(v)
    return seen


def main():
    argv, allowed = sys.argv[1:], {}
    while argv and argv[0] == "--allow":
        addr, _, why = argv[1].partition("=")
        allowed[int(addr, 16)] = why or "no reason given"
        argv = argv[2:]
    if len(argv) != 2:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        print("usage: %s [--allow ADDR[=why]]... <ours.dts> <theirs.dts>"
              % sys.argv[0], file=sys.stderr)
        return 2
    ours, our_nodes = parse(argv[0])
    theirs, their_nodes = parse(argv[1])
    seen = addresses(theirs, their_nodes)

    missing = sorted(a for a in ours if a not in seen and a not in allowed)
    waived = sorted(a for a in ours if a not in seen and a in allowed)
    print("==> addresses")
    print("    %d in ours, %d accounted for in theirs, %d waived, "
          "%d unaccounted for"
          % (len(ours), len(ours) - len(missing) - len(waived), len(waived),
             len(missing)))
    for a in waived:
        print("    WAIVED   0x%x  %s  (%s)" % (a, ours[a]["path"], allowed[a]))
    for a in missing:
        print("    MISSING  0x%x  %s" % (a, ours[a]["path"]))

    print("==> interrupts")
    same = diff = skipped = 0
    for a in sorted(set(ours) & set(theirs)):
        o, t = ours[a]["props"], theirs[a]["props"]
        if "interrupts" in o and "interrupts" in t:
            if o["interrupts"] == t["interrupts"]:
                same += 1
            else:
                diff += 1
                print("    DIFFERS  0x%x  %s" % (a, ours[a]["path"]))
                print("             ours   %s" % " ".join(map(str, o["interrupts"])))
                print("             theirs %s" % " ".join(map(str, t["interrupts"])))
        elif ("interrupts" in o) != ("interrupts" in t) and (
                "interrupts-extended" in o or "interrupts-extended" in t):
            skipped += 1
    print("    %d nodes agree, %d differ, %d not comparable" % (same, diff, skipped))

    print()
    print("==> %s" % ("pass" if not missing else "FAIL"))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
