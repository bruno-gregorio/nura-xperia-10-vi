#!/usr/bin/env python3
"""Score a QMP PHY's known register state against upstream's init tables.

Upstream gives each SoC's QMP PHY a configuration in phy-qcom-qmp-combo.c,
phy-qcom-qmp-ufs.c and friends: a set of init tables, each placed at an
offset inside the PHY. When the stock device tree carries the PHY's init
sequence, or a register dump shows what the bootloader left in it, placing
every upstream configuration over that state and counting agreements says
which one this PHY is, and exactly where it differs:

    scripts/qmp-score.py out/kbuild/drivers/phy/qualcomm/phy-qcom-qmp-combo.i \\
        dts:out/device-dump-root/live.dts:ssphy@88e8000
    scripts/qmp-score.py out/kbuild/drivers/phy/qualcomm/phy-qcom-qmp-ufs.i \\
        dump:out/try-kernel/live-r27.txt:0x1d87000

The first argument is the driver after the preprocessor, which turns every
register macro into a number and keeps its name (`make <file>.i` in the
kernel build tree, with CONFIG_PHY_QCOM_QMP debug names as built). The second
is the state to score: a node's `qcom,qmp-phy-init-seq` (offset, value
pairs), or scripts/regdump.c output with the PHY's base address.

A configuration's score is the entries it writes with the same value, less
those with another value and those absent from the state. A dump holds every
register, so for a dump only the first two count. UFS configurations are
scored with and without their HS-B and per-gear overlays, and the best
combination is reported.
"""

import argparse
import re
import sys

TBL_RE = re.compile(
    r"static const struct qmp_phy_init_tbl (\w+)\[\] = \{(.*?)\n\};", re.S)
ENT_RE = re.compile(
    r"\.offset = (\w+), \.val = (\w+), \.name = \"(\w+)\","
    r" \.lane_mask = (\w+)")
CFG_RE = re.compile(r"static const struct qmp_phy_cfg (\w+) = \{(.*?)\n\};",
                    re.S)

# Where each kind of table lands, by the offsets structure's field names.
# A list places the table once per lane.
COMBO = {"serdes_tbl": ["usb3_serdes"], "tx_tbl": ["txa", "txb"],
         "rx_tbl": ["rxa", "rxb"], "pcs_tbl": ["usb3_pcs"],
         "pcs_usb_tbl": ["usb3_pcs_usb"], "pcs_misc_tbl": ["usb3_pcs_misc"]}
UFS = {"serdes": ["serdes"], "tx": ["tx", "tx2"], "rx": ["rx", "rx2"],
       "pcs": ["pcs"]}


def parse_driver(path):
    src = open(path).read()
    tables = {}
    for m in TBL_RE.finditer(src):
        tables[m.group(1)] = [(int(o, 0), int(v, 0), n, int(k, 0))
                              for o, v, n, k in ENT_RE.findall(m.group(2))]
    offsets = {}
    for m in re.finditer(r"static const struct (qmp_\w*offsets\w*) (\w+) = "
                         r"\{(.*?)\};", src, re.S):
        offsets[m.group(2)] = {k: int(v, 0) for k, v in
                               re.findall(r"\.(\w+) = (\w+)", m.group(3))}
    cfgs = {}
    for m in CFG_RE.finditer(src):
        body = m.group(2)
        o = re.search(r"\.offsets = &(\w+)", body)
        if not o or o.group(1) not in offsets:
            continue
        cfgs[m.group(1)] = (offsets[o.group(1)], body)
    kind = "ufs" if "struct qmp_ufs_offsets" in src else "combo"
    return kind, tables, cfgs


def place(tables, offs, layout, picks):
    """Expected {offset: (value, name)} for {table kind: table name}."""
    exp = {}
    for kind, name in picks.items():
        if kind not in layout or name not in tables:
            continue
        for lane, field in enumerate(layout[kind]):
            if field not in offs:
                continue
            for off, val, reg, mask in tables[name]:
                if mask != 0xff and not mask & (1 << lane):
                    continue
                exp[offs[field] + off] = (val, f"{kind}:{reg}")
    return exp


def variants(kind, tables, offs, body):
    """Yield (label, expected map) for every way a configuration applies."""
    if kind == "combo":
        picks = dict(re.findall(r"\n\s*\.(\w+_tbl) = (\w+),", body))
        yield "", place(tables, offs, COMBO, picks)
        return
    groups = {}
    for g, inner in re.findall(r"\.(tbls\w*(?:\[\d\])?) = \{(.*?)\n \}",
                               body, re.S):
        groups[g] = dict(re.findall(r"\.(serdes|tx|rx|pcs) = (\w+),", inner))
    base = place(tables, offs, UFS, groups.get("tbls", {}))
    extras = [g for g in groups if g != "tbls"]
    hs_b = [g for g in extras if g == "tbls_hs_b"]
    gears = [g for g in extras if g.startswith("tbls_hs_overlay")]
    for b in [None] + hs_b:
        for gear in [None] + gears:
            exp = dict(base)
            for g in (b, gear):
                if g:
                    exp.update(place(tables, offs, UFS, groups[g]))
            label = "+".join(x.replace("tbls_", "") for x in (b, gear) if x)
            yield label, exp


def load_state(spec):
    how, _, rest = spec.partition(":")
    if how == "dts":
        path, _, node = rest.rpartition(":")
        text = open(path).read()
        start = text.index(node + " {")
        block = text[start:text.index("};", start)]
        cells = re.search(r"qcom,qmp-phy-init-seq = <([^>]*)>", block)
        cells = [int(x, 16) for x in cells.group(1).split()]
        return {cells[i]: cells[i + 1] for i in range(0, len(cells), 2)}, False
    if how == "dump":
        path, _, base = rest.partition(":")
        state = {}
        for line in open(path):
            m = re.match(r"([0-9a-f]{8}):((?: [0-9a-f]{8})+)\s*$", line)
            if not m:
                continue
            addr = int(m.group(1), 16)
            for i, word in enumerate(m.group(2).split()):
                state[addr + 4 * i] = int(word, 16)
        if not state:
            sys.exit(f"qmp-score: no regdump lines in {path}")
        b = int(base, 0) if base else min(state)
        # Table values are bytes in 32-bit registers.
        return {a - b: v & 0xff for a, v in state.items() if a >= b}, True
    sys.exit(f"qmp-score: state must be dts:FILE:NODE or dump:FILE[:BASE]")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("driver", help="preprocessed driver, a .i file")
    ap.add_argument("state", help="dts:FILE:NODE or dump:FILE[:BASE]")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--show", help="configuration to list differences for"
                    " (default: the best)")
    args = ap.parse_args()

    kind, tables, cfgs = parse_driver(args.driver)
    state, dump = load_state(args.state)
    print(f"{len(state)} registers in the state, {len(cfgs)} {kind}"
          " configurations")

    results = []
    for cfg, (offs, body) in cfgs.items():
        best = None
        for label, exp in variants(kind, tables, offs, body):
            if not exp:
                continue
            same = sum(1 for k, (v, _) in exp.items() if state.get(k) == v)
            other = sum(1 for k, (v, _) in exp.items()
                        if k in state and state[k] != v)
            absent = 0 if dump else sum(1 for k in exp if k not in state)
            extra = 0 if dump else sum(1 for k in state if k not in exp)
            row = (same - other - absent, cfg, label, len(exp), same, other,
                   absent, extra, exp)
            if best is None or row[0] > best[0]:
                best = row
        if best:
            results.append(best)
    results.sort(key=lambda r: (-r[0], r[1]))

    print("score  configuration  written  same  other  absent  unwritten")
    for r in results[:args.top]:
        name = r[1] + (f" ({r[2]})" if r[2] else "")
        print(f"{r[0]:5d}  {name}  {r[3]}  {r[4]}  {r[5]}  {r[6]}  {r[7]}")

    # Upstream shares tables between SoCs, so a tie is an answer too.
    tied = [r[1] for r in results if r[0] == results[0][0]]
    if len(tied) > 1:
        print(f"\n{len(tied)} configurations tie at the top, sharing their"
              f" tables: {', '.join(tied)}")

    pick = [r for r in results if r[1] == (args.show or results[0][1])]
    if not pick:
        sys.exit(f"qmp-score: no configuration {args.show}")
    r = pick[0]
    print(f"\n{r[1]}: registers it writes with another value")
    for k in sorted(r[8]):
        v, name = r[8][k]
        if k in state and state[k] != v:
            print(f"  {k:#06x} {name:45s} upstream {v:#04x}  here {state[k]:#04x}")


if __name__ == "__main__":
    main()
