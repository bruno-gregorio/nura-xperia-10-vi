#!/usr/bin/env python3
"""Turn a downstream Qualcomm clock driver into a mainline-shaped one.

The vendor drivers for this SoC (`gcc-parrot.c` and friends) carry a decade of
out-of-tree additions that upstream does not take: the vdd_class voltage
machinery, `enable_safe_config`, `.fw_name` parent strings, a probe that logs
and a `sync_state` hook. Converting one by hand is three thousand lines of
careful transcription, which is exactly the kind of work that silently loses a
register offset.

So the conversion is a program, and the program has a proof. Qualcomm released
`gcc-ravelin.c` downstream and someone upstreamed it as `gcc-sm4450.c`; both
are on disk, so `--selftest` runs this transformer on the downstream half and
diffs the result against the upstream half. Every rule below was derived from
that pair rather than guessed, and the self-test is what keeps it honest when a
rule is added.

    scripts/downstream-to-mainline.py --selftest
    scripts/downstream-to-mainline.py --soc parrot --target sm6450 \
        --phy-mux gcc_pcie_0_pipe_clk_src --gdsc-file gdscs.json \
        in/gcc-parrot.c > out/gcc-sm6450.c

It deliberately does not invent anything. The self-test converges at about
97.5% of upstream's lines and will not reach 100%, because what is left is not
rules - it is eight places where the person who upstreamed ravelin knew
something the vendor driver does not say. They are worth listing, because the
same eight questions come up for every SoC and each one needs an answer from
the hardware rather than from this script:

- `gcc_gpll10` is declared between gpll1 and gpll4 downstream and after gpll9
  upstream. Cosmetic, and moving a declaration automatically risks a
  use-before-declare, so the generated file keeps the vendor order.
- `gcc_gpll3_config` gained a different `.user_ctl_val` and lost `.cal_l`.
  Someone retuned a PLL; nothing in the vendor file hints at why.
- `gcc_qupv3_wrap0_s1_clk_src` was given its own frequency table instead of
  sharing s0's.
- `gcc_camera_sleep_clk` stopped being a registered branch and became one more
  always-on poke in probe.
- `GCC_PCIE_PHY_BCR` was added to the resets; the vendor driver has no such
  reset.
- Two video resets gained `.udelay = 400` and the named-field spelling.
- `qcom_branch_set_force_mem_core()` was added for the UFS ICE core clock. The
  vendor driver has no flag that implies it, so it is passed in with
  --keep-call rather than generated.
- Two camera mem-core pokes (0x36010, 0x36014 bit 20) were dropped upstream.
  The generator keeps them, because dropping a write to hardware on the
  strength of a guess is the wrong default.
"""
import argparse
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The include block is rewritten wholesale rather than patched: downstream pulls
# in kernel.h/of_device.h/of.h/vdd-level.h, upstream wants mod_devicetable.h,
# platform_device.h, clk-regmap.h, clk-regmap-phy-mux.h and gdsc.h. Patching
# line by line would leave them in downstream's order.
UPSTREAM_INCLUDES = """#include <linux/clk-provider.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

#include <dt-bindings/clock/qcom,{target}-gcc.h>

#include "clk-alpha-pll.h"
#include "clk-branch.h"
#include "clk-rcg.h"
#include "clk-regmap.h"
#include "clk-regmap-divider.h"
#include "clk-regmap-mux.h"
{phy_mux_include}#include "gdsc.h"
#include "reset.h"
"""

# Downstream names its board-file parents by string; upstream indexes them into
# the clocks= property, so each distinct .fw_name becomes one DT_* enum member.
# The order is upstream's: the two board clocks first, then the phy clocks in
# the order sm4450 lists them.
DT_ORDER = [
    "bi_tcxo",
    "sleep_clk",
    "pcie_0_pipe_clk",
    "ufs_phy_rx_symbol_0_clk",
    "ufs_phy_rx_symbol_1_clk",
    "ufs_phy_tx_symbol_0_clk",
    "usb3_phy_wrapper_gcc_usb30_pipe_clk",
]

# Lines upstream drops outright. Each is a vendor-only field.
DROP_LINES = (
    ".enable_safe_config = true,",
    ".flags = CLK_DONT_HOLD_STATE,",
    ".clk_regulators =",
    ".num_clk_regulators =",
)

# .ops substitutions. The two rcg2 ones also gain CLK_SET_RATE_PARENT, because
# clk_rcg2_shared_ops parks the RCG on a safe source when it is disabled and
# that only works if rate requests reach the parent.
# The registers a vendor probe keeps ungated are poked by raw address, because
# downstream does not expose them as clocks at all - so there is nothing in the
# driver to name them after. Upstream labels each one, and these labels are
# lifted from gcc-sm4450.c's probe, which pokes the identical set of offsets
# that gcc-ravelin.c and gcc-parrot.c do. A register not in this table gets no
# comment rather than a guessed one.
ALWAYS_ON_NAMES = {
    0x36004: "GCC_CAMERA_AHB_CLK",
    0x36018: "GCC_CAMERA_SLEEP_CLK",
    0x3601c: "GCC_CAMERA_XO_CLK",
    0x37004: "GCC_DISP_AHB_CLK",
    0x37014: "GCC_DISP_XO_CLK",
    0x81004: "GCC_GPU_CFG_AHB_CLK",
    0x42004: "GCC_VIDEO_AHB_CLK",
    0x42018: "GCC_VIDEO_XO_CLK",
}

OPS_MAP = {
    "clk_rcg2_ops": ("clk_rcg2_shared_ops", True),
    "clk_rcg2_floor_ops": ("clk_rcg2_shared_floor_ops", True),
    # Downstream's hw_ctl variant drives the branch's HW_CTL bit from the clock
    # framework. Upstream expresses the same thing as HW_CTRL on the GDSC that
    # owns the branch, so the branch itself becomes an ordinary one.
    "clk_branch2_hw_ctl_ops": ("clk_branch2_ops", False),
}


def natkey(name):
    """Upstream's ordering for a gcc dt-bindings header.

    It is a plain ASCII sort, with one exception. ASCII gets the awkward cases
    right by itself: GCC_USB30_PRIM_MASTER_CLK sorts before
    GCC_USB3_PRIM_PHY_AUX_CLK in every upstream header, because '0' is below
    '_'. What it gets wrong is a two-digit PLL - it puts GCC_GPLL10 ahead of
    GCC_GPLL3 - and upstream does not, so the GPLLn block is ordered by number.
    Nothing else needs the exception: sm8650, sm8550 and x1e80100 are plain
    ASCII throughout, and they have no GPLL10 to disagree about.

    This is not only style. The numbering is positional: the driver's clks[]
    array is indexed by these values, so one name out of place shifts every
    clock after it, and the header and the array have to be sorted by the same
    key or a device tree consumer gets the wrong clock with no error anywhere.
    """
    m = re.match(r"^(GCC_GPLL)(\d+)(.*)$", name)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return (name, -1, "")


def drop_balanced_blocks(text, opener):
    """Delete each `opener`-matching line and the brace-balanced block after it."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if opener.match(lines[i]):
            depth = 0
            while i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
                if depth <= 0:
                    break
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def drop_decls(text, pattern):
    """Delete whole top-level declarations whose first line matches `pattern`."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if pattern.search(lines[i]):
            depth, started = 0, False
            while i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                if "{" in lines[i]:
                    started = True
                # A struct ends on `};`, a function on a bare `}`. Testing only
                # for the semicolon walks a function's closing brace and eats
                # whatever declaration follows it.
                done = (depth <= 0 if started
                        else lines[i].rstrip().endswith(";"))
                i += 1
                if done:
                    break
            # Swallow one blank separator so we do not leave a double gap.
            if i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def rewrite_ops(text):
    """Substitute .ops and add CLK_SET_RATE_PARENT where the new ops needs it.

    The flag goes in only if the enclosing clk_init_data has no .flags of its
    own; a few clocks (gcc_video_venus_clk_src in ravelin) already carry it.
    """
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)\.ops = &(\w+),\s*$", ln)
        if not m or m.group(2) not in OPS_MAP:
            continue
        indent, new_ops = m.group(1), OPS_MAP[m.group(2)]
        lines[i] = f"{indent}.ops = &{new_ops[0]},"
        if not new_ops[1]:
            continue
        # Walk back to the start of this init block, looking for an existing
        # .flags. `.name =` is the first field of every clk_init_data here.
        has_flags = False
        for j in range(i - 1, max(i - 40, -1), -1):
            s = lines[j].strip()
            if s.startswith(".flags ="):
                has_flags = True
                break
            if s.startswith(".name ="):
                break
        if not has_flags:
            lines[i] = f"{indent}.flags = CLK_SET_RATE_PARENT,\n{lines[i]}"
    return "\n".join(lines)


def rewrite_parents(text):
    """.fw_name = "x" -> .index = DT_X, in both the brace and field spellings."""
    text = re.sub(r'\{ \.fw_name = "([\w]+)" \}',
                  lambda m: "{ .index = DT_%s }" % m.group(1).upper(), text)
    text = re.sub(r'(\s*)\.fw_name = "([\w]+)",',
                  lambda m: "%s.index = DT_%s," % (m.group(1), m.group(2).upper()),
                  text)
    return text


def dt_enum(text):
    """Build the DT_* enum from the parents the driver actually names."""
    used = {m.group(1).lower() for m in re.finditer(r"\bDT_([A-Z0-9_]+)\b", text)}
    members = [n for n in DT_ORDER if n in used]
    unknown = sorted(used - set(DT_ORDER))
    if unknown:
        # Not fatal: a different SoC may name a parent we have never seen. Put
        # it at the end so the file still compiles, and say so.
        print("note: parent not in the known order, appended: %s"
              % ", ".join(unknown), file=sys.stderr)
        members += unknown
    body = "\n".join("\tDT_%s," % n.upper() for n in members)
    return "enum {\n%s\n};\n" % body


def to_phy_mux(text, name):
    """Rewrite one clk_regmap_mux into a clk_regmap_phy_mux.

    Upstream has a dedicated type for a pipe clock whose only job is to pick
    between the phy's output and a parked source; it needs no parent_map, no
    width and no shift, and takes its single parent from the DT index. Returns
    (text, dropped_parent_suffix) so the caller can renumber what is left.
    """
    pat = re.compile(r"^static struct clk_regmap_mux %s = \{$" % re.escape(name),
                     re.M)
    m = pat.search(text)
    if not m:
        return text, None
    end = text.index("\n};\n", m.start()) + len("\n};\n")
    block = text[m.start():end]
    suffix = re.search(r"\.parent_map = gcc_parent_map_(\d+),", block)
    suffix = suffix.group(1) if suffix else None
    dt = re.search(r"\bDT_([A-Z0-9_]+)\b", block)
    if not dt:
        # The parents come through a parent_map, so look the phy clock up by
        # name: a pipe mux's non-tcxo parent is the one DT_* entry we want.
        guess = name.replace("gcc_", "").replace("_clk_src", "_clk").upper()
        dt_name = "DT_%s" % guess
    else:
        dt_name = "DT_%s" % dt.group(1)
    reg = re.search(r"\.reg = (0x[0-9a-fA-F]+),", block).group(1).lower()
    new = (
        "static struct clk_regmap_phy_mux %s = {\n"
        "\t.reg = %s,\n"
        "\t.clkr = {\n"
        "\t\t.hw.init = &(const struct clk_init_data) {\n"
        '\t\t\t.name = "%s",\n'
        "\t\t\t.parent_data = &(const struct clk_parent_data) {\n"
        "\t\t\t\t.index = %s,\n"
        "\t\t\t},\n"
        "\t\t\t.num_parents = 1,\n"
        "\t\t\t.ops = &clk_regmap_phy_mux_ops,\n"
        "\t\t},\n"
        "\t},\n"
        "};\n" % (name, reg, name, dt_name)
    )
    return text[:m.start()] + new + text[end:], suffix


def drop_parent_set(text, suffix):
    """Remove the gcc_parent_map_N / gcc_parent_data_N pair a phy mux left behind.

    The parent enum member they were the only user of goes too: a P_* with no
    parent_map entry left is dead, and upstream's enum does not carry it.
    """
    dead = set()
    for kind in ("map", "data"):
        pat = re.compile(r"^static const struct \w+ gcc_parent_%s_%s\[\]" %
                         (kind, suffix), re.M)
        m = pat.search(text)
        if m:
            dead |= {x.group(1) for x in
                     re.finditer(r"\bP_([A-Z0-9_]+)\b",
                                 text[m.start():text.index("\n};\n", m.start())])}
        text = drop_decls(text, pat)
    for name in sorted(dead):
        if not re.search(r"\bP_%s\b" % name, text):
            continue
        # Still referenced somewhere else - another map uses it, so it stays.
        if len(re.findall(r"\bP_%s\b" % name, text)) > 1:
            continue
        text = re.sub(r"\n\tP_%s,(?=\n)" % name, "", text, count=1)
    return text


def renumber_parents(text):
    """Make gcc_parent_map_N / gcc_parent_data_N contiguous again.

    Dropping a phy mux's parent set leaves a hole in the numbering. Upstream's
    files have no holes, and a reviewer reading a patch that skips _6 will stop
    to ask why, so close it.
    """
    nums = sorted({int(m.group(1)) for m in
                   re.finditer(r"\bgcc_parent_(?:map|data)_(\d+)\b", text)})
    remap = {old: new for new, old in enumerate(nums)}
    if all(o == n for o, n in remap.items()):
        return text
    # Two passes through a placeholder, so a rename never collides with a
    # number that has not been rewritten yet.
    text = re.sub(r"\bgcc_parent_(map|data)_(\d+)\b",
                  lambda m: "gcc_parent_%s_@%d@" % (m.group(1), remap[int(m.group(2))]),
                  text)
    return re.sub(r"gcc_parent_(map|data)_@(\d+)@", r"gcc_parent_\1_\2", text)


def lower_hex(text):
    return re.sub(r"\b0x([0-9A-Fa-f]+)\b", lambda m: "0x" + m.group(1).lower(), text)


def spaced_casts(text):
    """`&(const struct clk_init_data){` -> `... ) {`, upstream's spelling."""
    for cast in ("const struct clk_init_data", "const struct clk_parent_data",
                 "const struct clk_hw*[]", "struct clk_init_data",
                 "struct clk_parent_data"):
        text = text.replace("(%s){" % cast, "(%s) {" % cast)
    # Downstream writes some init data non-const; upstream makes them all const.
    text = text.replace("&(struct clk_init_data) {", "&(const struct clk_init_data) {")
    text = text.replace("&(struct clk_parent_data) {",
                        "&(const struct clk_parent_data) {")
    return text


def rewrite_probe(text, soc, target, keep_calls):
    """Replace the vendor probe with upstream's, preserving the always-on pokes.

    Downstream writes `regmap_update_bits(regmap, X, BIT(0), BIT(0))` to keep a
    branch ungated; upstream has `qcom_branch_set_clk_en(regmap, X)` for exactly
    that, so each one is translated and labelled with the clock it belongs to.
    Everything else in the vendor probe - the dev_info, the dev_err, the
    sync_state - goes.
    """
    pat = re.compile(r"^static int gcc_%s_probe\(struct platform_device \*pdev\)\n\{"
                     % soc, re.M)
    m = pat.search(text)
    if not m:
        return text, []
    # The probe runs to the closing brace of its own body.
    i, depth = m.end() - 1, 0
    while i < len(text):
        depth += 1 if text[i] == "{" else (-1 if text[i] == "}" else 0)
        i += 1
        if depth == 0:
            break
    body = text[m.start():i]

    always_on = [(a.group(1).lower(), None) for a in
                 re.finditer(r"regmap_update_bits\(regmap, (0x[0-9a-fA-F]+), "
                             r"BIT\(0\), BIT\(0\)\);", body)]
    # Name each poke after the clock at that halt register, so the comment in
    # the generated probe is a fact and not a guess.
    names = {}
    for b in re.finditer(r"^static struct clk_branch (\w+) = \{\n"
                         r"(?:\t\.[\w]+ = [^\n]*\n)*?\t\.clkr = \{\n"
                         r"\t\t\.enable_reg = (0x[0-9a-fA-F]+),", text, re.M):
        names.setdefault(b.group(2).lower(), b.group(1))
    lines = []
    for reg, _ in always_on:
        nm = names.get(reg) or ALWAYS_ON_NAMES.get(int(reg, 16))
        label = (" /* %s */" % nm.upper()) if nm else ""
        lines.append("\tqcom_branch_set_clk_en(regmap, %s);%s" % (reg, label))

    # Any other regmap_update_bits is SoC-specific and kept verbatim, because
    # we do not know what it does well enough to drop it.
    others = [o.group(0) for o in
              re.finditer(r"regmap_update_bits\(regmap, [^\n]*\);", body)
              if "BIT(0), BIT(0)" not in o.group(0)]
    pll = re.findall(r"clk_lucid_evo_pll_configure\([^\n]*\);", body)
    dfs = "qcom_cc_register_rcg_dfs" in body

    new = ["static int gcc_%s_probe(struct platform_device *pdev)" % target,
           "{", "\tstruct regmap *regmap;"]
    if dfs:
        new.append("\tint ret;")
    new += ["", "\tregmap = qcom_cc_map(pdev, &gcc_%s_desc);" % target,
            "\tif (IS_ERR(regmap))", "\t\treturn PTR_ERR(regmap);", ""]
    for p in pll:
        new.append("\t" + p)
    if pll:
        new.append("")
    if dfs:
        new += ["\tret = qcom_cc_register_rcg_dfs(regmap, gcc_dfs_clocks,",
                "\t\t\t\t       ARRAY_SIZE(gcc_dfs_clocks));",
                "\tif (ret)", "\t\treturn ret;", ""]
    for c in keep_calls:
        new.append("\t" + c)
    if keep_calls:
        new.append("")
    if lines:
        new += ["\t/* Keep some clocks always-on */"] + lines + [""]
    for o in others:
        new.append("\t" + o)
    if others:
        new.append("")
    new += ["\treturn qcom_cc_really_probe(&pdev->dev, &gcc_%s_desc, regmap);" % target,
            "}"]
    return text[:m.start()] + "\n".join(new) + text[i:], others


def drop_sync_state(text, soc):
    text = drop_decls(text, re.compile(
        r"^static void gcc_%s_sync_state\(struct device \*dev\)" % soc))
    return re.sub(r"\n\t\t\.sync_state = gcc_%s_sync_state,\n" % soc, "\n", text)


def add_gdscs(text, soc, target, gdscs):
    """Insert GDSC definitions and the desc entries that register them.

    The vendor gcc driver has no GDSCs at all: downstream describes them in the
    device tree as `qcom,gdsc` nodes with an absolute register address, and a
    separate regulator driver binds them. Upstream puts them in the clock
    driver, so the addresses come from the DT and are passed in here.
    """
    if not gdscs:
        return text
    blocks = []
    for g in gdscs:
        flags = " | ".join(g["flags"])
        blocks.append(
            "static struct gdsc %s = {\n"
            "\t.gdscr = 0x%x,\n"
            "\t.en_rest_wait_val = 0x2,\n"
            "\t.en_few_wait_val = 0x2,\n"
            "\t.clk_dis_wait_val = 0xf,\n"
            "\t.pd = {\n"
            '\t\t.name = "%s",\n'
            "\t},\n"
            "\t.pwrsts = PWRSTS_OFF_ON,\n"
            "\t.flags = %s,\n"
            "};\n" % (g["name"], g["offset"], g["name"], flags))
    arr = ("static struct gdsc *gcc_%s_gdscs[] = {\n%s\n};\n"
           % (target, "\n".join("\t[%s] = &%s," % (g["index"], g["name"])
                                for g in gdscs)))
    anchor = "static struct clk_regmap *gcc_%s_clocks[] = {" % soc
    text = text.replace(anchor, "\n".join(blocks) + "\n" + anchor, 1)
    anchor2 = "static const struct qcom_reset_map gcc_%s_resets[] = {" % soc
    text = text.replace(anchor2, arr + "\n" + anchor2, 1)
    return text.replace(
        "\t.num_resets = ARRAY_SIZE(gcc_%s_resets),\n" % soc,
        "\t.num_resets = ARRAY_SIZE(gcc_%s_resets),\n"
        "\t.gdscs = gcc_%s_gdscs,\n"
        "\t.num_gdscs = ARRAY_SIZE(gcc_%s_gdscs),\n" % (soc, target, target), 1)


def gen_header(driver_text, target, year):
    """Emit the dt-bindings header the generated driver indexes into.

    Upstream's numbering is not the vendor header's. Downstream puts the PLLs
    first at 0-6 and then sorts the rest; upstream sorts everything together,
    so GCC_GPLL0 lands in the middle. The numbering therefore has to be derived
    from the driver rather than carried over, and the driver is the only thing
    that can be the source of truth: its clks[] array is indexed by these
    numbers, so a header that disagrees hands device tree consumers the wrong
    clock silently.

    The clock group also contains names that clks[] never registers - the
    always-on branches the probe only ungates. They occupy numbers and leave
    NULL holes in clks[], which qcom_cc_really_probe skips.
    """
    def designators(array):
        m = re.search(r"%s\[\] = \{\n(.*?)\n\};" % re.escape(array),
                      driver_text, re.S)
        return [x.group(1) for x in re.finditer(r"\[(\w+)\]", m.group(1))] if m else []

    clks = designators("*gcc_%s_clocks" % target)
    resets = designators("gcc_%s_resets" % target)
    gdscs = designators("*gcc_%s_gdscs" % target)
    always = re.findall(r"qcom_branch_set_clk_en\(regmap, 0x[0-9a-f]+\); "
                        r"/\* (\w+) \*/", driver_text)
    clocks = sorted(set(clks) | set(always), key=natkey)

    guard = "_DT_BINDINGS_CLK_QCOM_GCC_%s_H" % target.upper()
    out = ["/* SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause) */",
           "/*",
           " * Copyright (c) %s, Qualcomm Innovation Center, Inc. "
           "All rights reserved." % year,
           " */", "",
           "#ifndef %s" % guard,
           "#define %s" % guard, ""]
    for group, names in (("", clocks), ("GCC power domains", gdscs),
                         ("GCC resets", resets)):
        if not names:
            continue
        if group:
            out += ["", "/* %s */" % group]
        width = max(len(n) for n in names) + 1
        for i, n in enumerate(names):
            out.append("#define %-*s %d" % (width, n, i))
    out += ["", "#endif"]
    return "\n".join(out) + "\n"


def sort_clocks_array(text, soc):
    """Put the clks[] designated initialisers in the header's order.

    They are designated, so the order is cosmetic to the compiler - but a
    reviewer reads the array against the header, and the vendor array is sorted
    as strings where upstream sorts numerically.
    """
    m = re.search(r"(static struct clk_regmap \*gcc_%s_clocks\[\] = \{\n)"
                  r"(.*?)(\n\};)" % soc, text, re.S)
    if not m:
        return text
    entries = [l for l in m.group(2).split("\n") if l.strip()]
    keyed = []
    for l in entries:
        d = re.search(r"\[(\w+)\]", l)
        keyed.append((natkey(d.group(1)) if d else (l, -1, ""), l))
    body = "\n".join(l for _, l in sorted(keyed, key=lambda kv: kv[0]))
    return text[:m.start()] + m.group(1) + body + m.group(3) + text[m.end():]


def convert(src, soc, target, phy_mux=None, gdscs=None, keep_calls=(),
            copyright_year=None):
    text = src

    # 1. The vendor voltage-scaling machinery, which upstream has no equivalent
    #    for: the regulator classes, the array of them, and the per-clock
    #    rate_max tables that reference them.
    text = drop_decls(text, re.compile(r"^static DEFINE_VDD_REGULATORS\("))
    text = drop_decls(text, re.compile(r"^static struct clk_vdd_class \*gcc_\w+_regulators\[\]"))
    text = drop_balanced_blocks(text, re.compile(r"^\s*\.(?:clkr\.)?vdd_data = \{\s*$"))

    # 2. Per-line vendor fields.
    text = "\n".join(l for l in text.split("\n")
                     if not any(d in l for d in DROP_LINES))

    # 3. Parent naming, ops, and the pipe mux - in that order, because the mux
    #    rewrite wants the DT_* names to already exist.
    text = rewrite_parents(text)
    text = rewrite_ops(text)
    if phy_mux:
        text, suffix = to_phy_mux(text, phy_mux)
        if suffix:
            text = drop_parent_set(text, suffix)
            text = renumber_parents(text)

    # 4. The driver's own boilerplate.
    text, _ = rewrite_probe(text, soc, target, keep_calls)
    text = drop_sync_state(text, soc)
    text = add_gdscs(text, soc, target, gdscs)
    text = sort_clocks_array(text, soc)
    text = text.replace('MODULE_LICENSE("GPL v2")', 'MODULE_LICENSE("GPL")')

    # 5. Names. `qcom,gcc-parrot.h` is handled by the include rewrite below, so
    #    only the identifiers and the compatible are renamed here.
    text = text.replace(soc, target).replace(soc.upper(), target.upper())

    # 6. The include block, and the DT_* enum that replaces the fw_names.
    inc = UPSTREAM_INCLUDES.format(
        target=target,
        phy_mux_include='#include "clk-regmap-phy-mux.h"\n' if phy_mux else "")
    start = text.index("#include <linux/clk-provider.h>")
    end = text.index("\n\n", text.index('#include "reset.h"'))
    text = text[:start] + inc + text[end + 1:]
    text = re.sub(r"\n(enum \{\n\tP_)", "\n%s\n\\1" % dt_enum(text), text, count=1)

    # 7. Spelling.
    text = spaced_casts(text)
    text = lower_hex(text)
    if copyright_year:
        text = re.sub(r"Copyright \(c\) [\d\-, ]+, Qualcomm",
                      "Copyright (c) %s, Qualcomm" % copyright_year, text, count=1)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def selftest():
    """Convert ravelin and diff against the real upstream sm4450 driver."""
    scratch = os.environ.get("D2M_DOWNSTREAM")
    if not scratch:
        print("set D2M_DOWNSTREAM to the directory holding gcc-ravelin.c",
              file=sys.stderr)
        return 2
    src = os.path.join(scratch, "gcc-ravelin.c")
    ref = os.path.join(ROOT, "out/linux/drivers/clk/qcom/gcc-sm4450.c")
    for p in (src, ref):
        if not os.path.exists(p):
            print("missing %s" % p, file=sys.stderr)
            return 2
    gdscs = [
        {"name": "gcc_pcie_0_gdsc", "offset": 0x7b004,
         "index": "GCC_PCIE_0_GDSC",
         "flags": ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE", "VOTABLE"]},
        {"name": "gcc_ufs_phy_gdsc", "offset": 0x87004,
         "index": "GCC_UFS_PHY_GDSC",
         "flags": ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]},
        {"name": "gcc_usb30_prim_gdsc", "offset": 0x49004,
         "index": "GCC_USB30_PRIM_GDSC",
         "flags": ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]},
        {"name": "gcc_vcodec0_gdsc", "offset": 0xb6044,
         "index": "GCC_VCODEC0_GDSC",
         "flags": ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE", "HW_CTRL"]},
        {"name": "gcc_venus_gdsc", "offset": 0xb6020,
         "index": "GCC_VENUS_GDSC",
         "flags": ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]},
    ]
    got = convert(open(src).read(), "ravelin", "sm4450",
                  phy_mux="gcc_pcie_0_pipe_clk_src", gdscs=gdscs,
                  keep_calls=["qcom_branch_set_force_mem_core(regmap, "
                              "gcc_ufs_phy_ice_core_clk, true);"],
                  copyright_year="2023")
    want = open(ref).read()
    a, b = got.split("\n"), want.split("\n")

    # Upstream's own sm4450 writes `clk_init_data){` in eight places and
    # `clk_init_data) {` in the other ninety-eight, and forty of the fifty-five
    # upstream gcc drivers contain both spellings. It is noise, not a rule, so
    # the generator picks one and the self-test scores on a normalised copy -
    # otherwise a hundred cosmetic lines bury the handful that mean something.
    def norm(ls):
        return [re.sub(r"\s+", " ", l).replace(") {", "){").strip() for l in ls]

    diff = [l for l in difflib.unified_diff(a, b, "generated", "upstream",
                                            n=0, lineterm="")]
    raw = len([l for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---")])
    ndiff = [l for l in difflib.unified_diff(norm(a), norm(b), n=0, lineterm="")
             if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    print("generated %d lines, upstream has %d" % (len(a), len(b)))
    print("differing lines: %d raw, %d ignoring whitespace "
          "(%.2f%% of upstream matches)"
          % (raw, len(ndiff), (1 - len(ndiff) / max(len(b), 1)) * 100))
    if diff:
        print("\n".join(diff))
    return 0 if len(ndiff) == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", nargs="?", help="downstream driver")
    ap.add_argument("--soc", help="downstream codename, e.g. parrot")
    ap.add_argument("--target", help="upstream name, e.g. sm6450")
    ap.add_argument("--phy-mux", action="append", default=[],
                    help="a clk_regmap_mux to rewrite as a clk_regmap_phy_mux")
    ap.add_argument("--gdsc-file", help="JSON list of GDSCs to add")
    ap.add_argument("--keep-call", action="append", default=[],
                    help="an extra probe statement to emit verbatim")
    ap.add_argument("--year", help="copyright year for the new file")
    ap.add_argument("--header", metavar="DRIVER",
                    help="emit the dt-bindings header for an already-generated "
                         "driver instead of converting one")
    ap.add_argument("--selftest", action="store_true",
                    help="convert ravelin and diff against upstream sm4450")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.header:
        if not args.target:
            ap.error("--header needs --target")
        sys.stdout.write(gen_header(open(args.header).read(), args.target,
                                    args.year or "2026"))
        return 0
    if not (args.source and args.soc and args.target):
        ap.error("source, --soc and --target are required")
    gdscs = json.load(open(args.gdsc_file)) if args.gdsc_file else None
    sys.stdout.write(convert(open(args.source).read(), args.soc, args.target,
                             phy_mux=args.phy_mux[0] if args.phy_mux else None,
                             gdscs=gdscs, keep_calls=args.keep_call,
                             copyright_year=args.year))
    return 0


if __name__ == "__main__":
    sys.exit(main())
