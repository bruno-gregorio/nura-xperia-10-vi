#!/usr/bin/env python3
"""Turn a downstream Qualcomm clock driver into a mainline-shaped one.

The vendor drivers for this SoC (`gcc-parrot.c` and friends) carry a decade of
out-of-tree additions that upstream does not take: the vdd_class voltage
machinery, `enable_safe_config`, `.fw_name` parent strings, a probe that logs
and a `sync_state` hook. Converting one by hand is three thousand lines of
careful transcription, which is exactly the kind of work that silently loses a
register offset.

So the conversion is a program, and the program has a proof. Qualcomm released
`gcc-ravelin.c`, `dispcc-ravelin.c` and `gpucc-ravelin.c` downstream and all
three were upstreamed, as `gcc-sm4450.c`, `dispcc-sm4450.c` and
`gpucc-sm4450.c`; all six files are on disk, so `--selftest` runs this
transformer on each downstream half and diffs the result, and the dt-bindings
header generated from it, against the upstream half. Every rule below was
derived from those pairs or from the upstream code that makes a vendor field
meaningless, rather than guessed, and the self-test is what keeps it honest
when a rule is added.

    scripts/downstream-to-mainline.py --selftest
    scripts/downstream-to-mainline.py --soc parrot --target sm6450 \
        --phy-mux gcc_pcie_0_pipe_clk_src --gdsc-file gdscs.json \
        in/gcc-parrot.c > out/gcc-sm6450.c
    scripts/downstream-to-mainline.py --block disp_cc --soc parrot \
        --target sm6450 --gdsc-file dispcc-gdscs.json \
        --always-on disp_cc_sleep_clk --driver-data \
        in/dispcc-parrot.c > out/dispcc-sm6450.c
    scripts/downstream-to-mainline.py --block disp_cc --target sm6450 \
        --header out/dispcc-sm6450.c > out/qcom,sm6450-dispcc.h
    scripts/downstream-to-mainline.py --block gpu_cc --soc parrot \
        --target sm6450 --gdsc-file gpucc-gdscs.json \
        --always-on gpu_cc_cxo_aon_clk --always-on gpu_cc_demet_clk \
        --driver-data in/gpucc-parrot.c > out/gpucc-sm6450.c

--driver-data writes the probe the way controllers added since 6.17 are
written (PLLs, always-on branches and register setup in qcom_cc_driver_data,
the probe a single qcom_cc_probe()); the self-test pairs predate it, so it is
a rearrangement applied last and checked by compiling.

It deliberately does not invent anything. The self-test converges at about 98%
of upstream's gcc lines, 96% of its dispcc lines and 94% of its gpucc lines,
and will not reach 100%, because what is left is not rules - it is places where
the person who upstreamed ravelin knew something the vendor driver does not
say. They are worth listing, because the same questions come up for every SoC
and each one needs an answer from the hardware rather than from this script:

- `gcc_gpll10` is declared between gpll1 and gpll4 downstream and after gpll9
  upstream. Cosmetic, and moving a declaration automatically risks a
  use-before-declare, so the generated file keeps the vendor order.
- `gcc_qupv3_wrap0_s1_clk_src` was given its own frequency table instead of
  sharing s0's.
- `GCC_PCIE_PHY_BCR` was added to the resets; the vendor driver has no such
  reset.
- Two video resets gained `.udelay = 400` and the named-field spelling.
- `qcom_branch_set_force_mem_core()` was added for the UFS ICE core clock. The
  vendor driver has no flag that implies it, so it is passed in with
  --keep-call rather than generated.
- Two camera mem-core pokes (0x36010, 0x36014 bit 20) were dropped upstream,
  and so was dispcc's MDP clock-gating write to DISP_CC_MISC_CMD. The
  generator keeps them, because dropping a write to hardware on the strength
  of a guess is the wrong default - and most upstream display controllers
  (sm8550, milos, glymur) do make that write.
- `gcc_camera_sleep_clk` and `disp_cc_sleep_clk` stopped being registered
  branches and became always-on pokes. That is a reviewer's call, so it is
  passed in with --always-on.
- dispcc-sm4450 gave the DSI byte and pixel clock sources a frequency table
  with only XO in it, which their ops never read. Not generated.
- dispcc-sm4450 parents disp_cc_xo_clk_src on the active-only XO and halts
  disp_cc_mdss_mdp_lut1_clk without voting; ravelin does neither, but
  parrot's vendor driver already does both, so for SM6450 they carry over.
- gpucc-sm4450 checks the halt bit of gpu_cc_cx_gfx3d_clk and
  gpu_cc_cx_gfx3d_slv_clk where ravelin only waits (BRANCH_HALT_DELAY), and
  gives gpu_cc_gx_cxo_clk ordinary branch ops where ravelin has the aon ones.
  Parrot has none of the three clocks.
- gpucc-sm4450 adds gpu_cc_gx_vsense_clk (0x90b0) and GPU_CC_CB_BCR (0x93a0),
  neither of which ravelin has, and keeps GPU_CC_CB_CLK (0x93a4) on - that
  one is passed in, with --always-on-reg, so the header numbering can be
  checked past it.
- gpucc-sm4450 drops gpu_cc_hlos1_vote_gpu_smmu_clk. The generator keeps it:
  sm8450, sm8550 and sm8650 register it, their adreno_smmu nodes consume it,
  and parrot's vendor SMMU, GMU and GPU nodes all do.
- gpucc-sm4450 drops the vendor probe's `regmap_write(regmap, 0x9534, 0x0)`.
  Nothing in the vendor tree says what 0x9534 is, and no upstream graphics
  controller writes it; it is kept, for the reason given above.
- The graphics reset map and its header numbering are in no order a rule
  could produce (CB, CX, GX, FAST_HUB, ACD, ... in the array; ACD, CB, CX,
  ..., XO, GX_ACD_IROOT, RBCPR in the header). The generator sorts both.

The questions that used to be on this list and are now rules: the Lucid EVO
`.cal_l` and `.user_ctl_val` (pll_configs), and the always-on pokes' order.
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

# The display clock controller's, as dispcc-sm4450.c has it. It differs from
# gcc's in more than the header name: module.h comes before mod_devicetable.h,
# and it pulls in clk-pll.h and common.h.
DISPCC_INCLUDES = """#include <linux/clk-provider.h>
#include <linux/module.h>
#include <linux/mod_devicetable.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

#include <dt-bindings/clock/qcom,{target}-dispcc.h>

#include "clk-alpha-pll.h"
#include "clk-branch.h"
#include "clk-pll.h"
#include "clk-rcg.h"
#include "clk-regmap.h"
#include "clk-regmap-divider.h"
{phy_mux_include}#include "common.h"
#include "gdsc.h"
#include "reset.h"
"""

# The graphics clock controller's is the display one's with the other header:
# gpucc-sm4450.c includes exactly the same files in the same order.
GPUCC_INCLUDES = DISPCC_INCLUDES.replace("-dispcc.h>", "-gpucc.h>")
CAMCC_INCLUDES = DISPCC_INCLUDES.replace("-dispcc.h>", "-camcc.h>")

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

# What differs between clock controllers. `dt` is the DT_* enum in groups, each
# group separated by a blank line as upstream writes it; a name in `dt_always`
# is emitted even if no parent uses it, because the binding lists it - the
# display controller's AHB clock is an input the driver never parents on.
# Outside gcc, `dt` is the binding's whole clocks list, so a vendor parent
# that is not in it cannot be expressed (drop_foreign_parents). `fold_case`
# picks natkey's lower-case ordering for the header and clks[].
BLOCKS = {
    "gcc": {
        "includes": UPSTREAM_INCLUDES,
        "dt": [DT_ORDER],
        "dt_always": (),
        "always_on_comment": "Keep some clocks always-on",
        "module_driver": False,
    },
    "disp_cc": {
        "includes": DISPCC_INCLUDES,
        "dt": [
            ["bi_tcxo", "bi_tcxo_ao", "ahb_clk", "sleep_clk"],
            ["dsi%d_phy_pll_out_%s" % (n, k)
             for n in (0, 1) for k in ("byteclk", "dsiclk")],
            ["dp%d_phy_pll_%s" % (n, k)
             for n in range(4) for k in ("link_clk", "vco_div_clk")],
        ],
        "dt_always": ("bi_tcxo", "bi_tcxo_ao", "ahb_clk", "sleep_clk"),
        "always_on_comment": "Keep some clocks always enabled",
        "module_driver": True,
    },
    # The binding (qcom,sm8450-gpucc.yaml, shared by sm4450 and its
    # siblings) takes exactly these three inputs, in this order.
    "gpu_cc": {
        "includes": GPUCC_INCLUDES,
        "dt": [["bi_tcxo", "gpll0_out_main", "gpll0_out_main_div"]],
        "dt_always": ("bi_tcxo", "gpll0_out_main", "gpll0_out_main_div"),
        "always_on_comment": "Keep some clocks always enabled",
        "module_driver": True,
        "fold_case": True,
    },
    # The camera controller's only board clock is the XO; its bus clock from
    # GCC is in the binding but nothing in the driver parents to it.
    "cam_cc": {
        "includes": CAMCC_INCLUDES,
        "dt": [["bi_tcxo"]],
        "dt_always": ("bi_tcxo",),
        "always_on_comment": "Keep some clocks always enabled",
        "module_driver": True,
        "merge_pll_configs": False,
    },
}

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


def natkey(name, fold=False):
    """Upstream's ordering for a gcc dt-bindings header.

    It is a plain ASCII sort, with one exception. ASCII gets the awkward cases
    right by itself: GCC_USB30_PRIM_MASTER_CLK sorts before
    GCC_USB3_PRIM_PHY_AUX_CLK in every upstream header, because '0' is below
    '_'. What it gets wrong is a two-digit PLL - it puts GCC_GPLL10 ahead of
    GCC_GPLL3 - and upstream does not, so the GPLLn block is ordered by number.
    Nothing else needs the exception: sm8650, sm8550 and x1e80100 are plain
    ASCII throughout, and they have no GPLL10 to disagree about.

    `fold` sorts the lower-case spelling instead - the clock's C name - which
    puts '_' above the digits but below every letter. The graphics headers are
    sorted that way: sm4450's has GPU_CC_CX_SNOC_DVM_CLK before
    GPU_CC_CXO_AON_CLK, which upper-case ASCII would swap, and every upstream
    gpucc header whose order tells the two apart (sdm845, sm8150, sm8350,
    sm8450, sm8550, sm8650, sar2130p, sm4450) agrees, as do the vendor's.

    This is not only style. The numbering is positional: the driver's clks[]
    array is indexed by these values, so one name out of place shifts every
    clock after it, and the header and the array have to be sorted by the same
    key or a device tree consumer gets the wrong clock with no error anywhere.
    """
    if fold:
        name = name.lower()
    m = re.match(r"^((?:GCC_G|DISP_CC_|GPU_CC_)PLL)(\d+)(.*)$", name, re.I)
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
    """.fw_name = "x" -> .index = DT_X, in both the brace and field spellings.

    The display controller's phy parents carry a global `.name` as well, the
    fallback for a DT without clock-names. Upstream has neither, so it goes.
    """
    text = re.sub(r'\{ \.fw_name = "([\w]+)"(?:, \.name = "[\w]+")? \}',
                  lambda m: "{ .index = DT_%s }" % m.group(1).upper(), text)
    text = re.sub(r'(\s*)\.fw_name = "([\w]+)",',
                  lambda m: "%s.index = DT_%s," % (m.group(1), m.group(2).upper()),
                  text)
    return text


def drop_foreign_parents(text, pfx, block):
    """Unparent a branch whose only parent is not one of the binding's inputs.

    gpu_cc_cx_snoc_dvm_clk names gcc_gpu_snoc_dvm_gfx_clk as its parent by
    string. The graphics binding takes three clocks and that is not one of
    them, so there is no index to give it; gpucc-sm4450 (and sm8450, sm8550)
    register the branch with no parent at all, and so does this. gcc is
    exempt: its DT_ORDER is a known order, not the whole of any binding.
    """
    if pfx == "gcc":
        return text
    known = {n for g in block["dt"] for n in g}

    def fix(m):
        if m.group(2) in known:
            return m.group(0)
        print("note: dropped parent %s, which is not an input of the "
              "binding" % m.group(2), file=sys.stderr)
        return ""
    return re.sub(r'(\n[ \t]*\.parent_data = &\((?:const )?struct '
                  r'clk_parent_data\) ?\{\n[ \t]*\.fw_name = "(\w+)",\n'
                  r'[ \t]*\},\n[ \t]*\.num_parents = 1,)(?=\n)', fix, text)


def dt_enum(text, block):
    """Build the DT_* enum from the parents the driver actually names."""
    used = {m.group(1).lower() for m in re.finditer(r"\bDT_([A-Z0-9_]+)\b", text)}
    used |= set(block["dt_always"])
    groups = [[n for n in g if n in used] for g in block["dt"]]
    unknown = sorted(used - {n for g in block["dt"] for n in g})
    if unknown:
        # Not fatal: a different SoC may name a parent we have never seen. Put
        # it at the end so the file still compiles, and say so.
        print("note: parent not in the known order, appended: %s"
              % ", ".join(unknown), file=sys.stderr)
        groups.append(unknown)
    body = "\n\n".join("\n".join("\tDT_%s," % n.upper() for n in g)
                       for g in groups if g)
    return "enum {\n%s\n};\n" % body


def dp_link(text):
    """Give each DisplayPort link clock source upstream's byte2 ops.

    The vendor runs dptxN_link_clk_src as an ordinary RCG over a frequency
    table in kHz (270000 for a 2.7 Gb/s link), which only its own DP driver
    understands. drm/msm sets the link rate on this clock and expects it to
    pass straight through to the PHY's link clock, which is clk_byte2_ops
    with CLK_SET_RATE_PARENT and no table: every upstream display controller
    with DP since sdm845 spells it that way. The table it leaves unused goes.
    """
    def fix(m):
        b = re.sub(r"\n\t\.freq_tbl = \w+,", "", m.group(0))
        b = b.replace("&clk_rcg2_ops,", "&clk_byte2_ops,")
        if "CLK_SET_RATE_PARENT" not in b:
            b = b.replace("\t\t.ops = &clk_byte2_ops,",
                          "\t\t.flags = CLK_SET_RATE_PARENT,\n"
                          "\t\t.ops = &clk_byte2_ops,")
        return b
    text = re.sub(r"(?ms)^static struct clk_rcg2 \w+_dptx\d_link_clk_src = "
                  r"\{\n.*?^\};\n", fix, text)
    for t in re.findall(r"^static const struct freq_tbl (\w+)\[\]", text, re.M):
        if len(re.findall(r"\b%s\b" % t, text)) == 1:
            text = re.sub(r"(?ms)^static const struct freq_tbl %s\[\] = "
                          r"\{\n.*?^\};\n\n?" % t, "", text)
    return text


def byte_div(text):
    """Make the DSI byte clock's divider writable, and stop it reaching up.

    drm/msm sets byte_intf_clk itself, to half the byte clock on most PHYs
    (dsi_link_clk_set_rate_6g). That needs a divider it can program - the
    vendor's ravelin has the read-only ops - and one without
    CLK_SET_RATE_PARENT, or asking for half the rate retunes byte0_clk_src
    and the DSI PLL behind it instead of dividing. Sixteen of nineteen
    upstream display controllers, sm4450 among them, spell it this way.
    """
    def fix(m):
        b = m.group(0).replace("clk_regmap_div_ro_ops", "clk_regmap_div_ops")
        return re.sub(r"\n\t*\.flags = CLK_SET_RATE_PARENT,", "", b)
    return re.sub(r"(?ms)^static struct clk_regmap_div disp_cc_mdss_byte\d_div_clk_src"
                  r" = \{\n.*?^\};\n", fix, text)


def pll_configs(text, merge=True):
    """Bring the alpha_pll_config blocks to upstream's spelling.

    Two fields are rewritten for a Lucid EVO PLL, and both are no-ops on
    upstream: clk_lucid_evo_pll_configure() writes TRION_PLL_CAL_VAL (0x44)
    as the calibration L whatever .cal_l says, and alpha_pll_lucid_evo_enable()
    sets PLL_OUT_MASK (bits 0-2) in USER_CTL on every enable. So upstream
    drops `.cal_l = 0x44` and clears those bits in .user_ctl_val, which both
    pairs on disk show (gcc_gpll3 in sm4450, disp_cc_pll0 in dispcc-sm4450).
    A .cal_l other than 0x44 is kept and reported, because upstream would
    silently write something else.

    A Rivian EVO PLL takes the same two: clk_rivian_evo_pll_configure() never
    writes a calibration L at all, and its enable is the Lucid 5LPE one, which
    sets PLL_OUT_MASK the same way (cam_cc_pll2 in camcc-sm4450).

    Then two configs that are now identical become one, where the block's
    upstream drivers do that: dispcc-sm4450 configures both of its PLLs from
    disp_cc_pll0_config, but camcc-sm4450 keeps a cam_cc_pll3_config equal to
    cam_cc_pll1_config.
    """
    evo = set(re.findall(r"clk_lucid_evo_pll_configure\(&\w+, regmap, &(\w+)\);",
                         text))
    rivian = set(re.findall(r"clk_rivian_evo_pll_configure\(&\w+, regmap, "
                            r"&(\w+)\);", text))
    evo |= rivian
    blocks = {}
    for m in re.finditer(r"^static const struct alpha_pll_config (\w+) = \{\n"
                         r"(.*?)\n\};\n", text, re.M | re.S):
        if m.group(1) not in evo:
            continue
        body = m.group(2)
        cal = re.search(r"\t\.cal_l = (0x[0-9a-fA-F]+),\n", body)
        if cal and (m.group(1) in rivian or int(cal.group(1), 16) == 0x44):
            body = body.replace(cal.group(0), "")
        elif cal:
            print("note: %s has .cal_l = %s, which upstream's Lucid EVO "
                  "configure ignores" % (m.group(1), cal.group(1)),
                  file=sys.stderr)
        body = re.sub(r"(\t\.user_ctl_val = )(0x[0-9a-fA-F]+),",
                      lambda u: "%s0x%08x," % (u.group(1), int(u.group(2), 16) & ~7),
                      body)
        blocks[m.group(1)] = body
        text = text.replace(m.group(0), m.group(0).replace(m.group(2), body), 1)

    seen = {}
    for name, body in (blocks.items() if merge else ()):
        first = seen.setdefault(body.lower(), name)
        if first == name:
            continue
        # Its frequency comment goes with it; the survivor's describes both.
        text = re.sub(r"(?m)^(?:/\* [^\n]* \*/\n)?static const struct "
                      r"alpha_pll_config %s = \{\n.*?\n\};\n\n?" % name,
                      "", text, count=1, flags=re.S)
        text = re.sub(r"\b%s\b" % name, first, text)
    return text


def to_phy_mux(text, name, pfx):
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
    suffix = re.search(r"\.parent_map = %s_parent_map_(\d+)," % pfx, block)
    suffix = suffix.group(1) if suffix else None
    dt = re.search(r"\bDT_([A-Z0-9_]+)\b", block)
    if not dt:
        # The parents come through a parent_map, so look the phy clock up by
        # name: a pipe mux's non-tcxo parent is the one DT_* entry we want.
        guess = name.replace(pfx + "_", "").replace("_clk_src", "_clk").upper()
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


def drop_parent_set(text, suffix, pfx):
    """Remove the gcc_parent_map_N / gcc_parent_data_N pair a phy mux left behind.

    The parent enum member they were the only user of goes too: a P_* with no
    parent_map entry left is dead, and upstream's enum does not carry it.
    """
    dead = set()
    for kind in ("map", "data"):
        pat = re.compile(r"^static const struct \w+ %s_parent_%s_%s\[\]" %
                         (pfx, kind, suffix), re.M)
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


def renumber_parents(text, pfx):
    """Make gcc_parent_map_N / gcc_parent_data_N contiguous again.

    Dropping a phy mux's parent set leaves a hole in the numbering. Upstream's
    files have no holes, and a reviewer reading a patch that skips _6 will stop
    to ask why, so close it.
    """
    nums = sorted({int(m.group(1)) for m in
                   re.finditer(r"\b%s_parent_(?:map|data)_(\d+)\b" % pfx, text)})
    remap = {old: new for new, old in enumerate(nums)}
    if all(o == n for o, n in remap.items()):
        return text
    # Two passes through a placeholder, so a rename never collides with a
    # number that has not been rewritten yet.
    text = re.sub(r"\b%s_parent_(map|data)_(\d+)\b" % pfx,
                  lambda m: "%s_parent_%s_@%d@" % (pfx, m.group(1),
                                                   remap[int(m.group(2))]),
                  text)
    return re.sub(r"%s_parent_(map|data)_@(\d+)@" % pfx,
                  r"%s_parent_\1_\2" % pfx, text)


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


def find_func(text, pattern):
    """(start, end) of the function whose header matches, braces balanced."""
    m = re.compile(pattern, re.M).search(text)
    if not m:
        return None
    i, depth = m.end() - 1, 0
    while i < len(text):
        depth += 1 if text[i] == "{" else (-1 if text[i] == "}" else 0)
        i += 1
        if depth == 0:
            break
    return m.start(), i


def poke_names(text, body):
    """Name every always-on register the vendor probe pokes.

    The vendor comment above the pokes usually lists them - `GCC_CAMERA_AHB_CLK,
    GCC_CAMERA_XO_CLK, ...` or `disp_cc_xo_clk` - in the order they are poked,
    and that is the vendor saying what each address is. When it does not, a
    branch at that address in the same driver names it, and failing that the
    sm4450 table. A register none of them names gets no label.
    """
    pokes = [a.group(1).lower() for a in
             re.finditer(r"regmap_update_bits\(regmap, (0x[0-9a-fA-F]+), "
                         r"BIT\(0\), BIT\(0\)\);", body)]
    listed = []
    for c in re.finditer(r"/\*((?:[^*]|\*(?!/))*?always[- ](?:on|enabled)"
                         r"(?:[^*]|\*(?!/))*)\*/", body, re.I | re.S):
        listed += re.findall(r"\b(?:gcc|disp_cc)_\w+_clk\b", c.group(1), re.I)
    names = {}
    if len(listed) == len(pokes):
        names = {reg: nm.upper() for reg, nm in zip(pokes, listed)}
    for b in re.finditer(r"^static struct clk_branch (\w+) = \{\n"
                         r"(?:\t\.[\w]+ = [^\n]*\n)*?\t\.clkr = \{\n"
                         r"\t\t\.enable_reg = (0x[0-9a-fA-F]+),", text, re.M):
        names.setdefault(b.group(2).lower(), b.group(1).upper())
    for reg in pokes:
        if reg not in names and int(reg, 16) in ALWAYS_ON_NAMES:
            names[reg] = ALWAYS_ON_NAMES[int(reg, 16)]
    return pokes, names


def move_always_on(text, soc, pfx, names):
    """Turn registered branches into always-on pokes, as upstream sometimes does.

    gcc_camera_sleep_clk in sm4450 and disp_cc_sleep_clk in dispcc-sm4450 are
    branches downstream and one more qcom_branch_set_clk_en() upstream: nothing
    consumes them, and the clock framework would gate them as unused. Which
    clocks get this is a reviewer's call, not something the vendor driver
    says, so they are named on the command line (--always-on).
    """
    moved = []
    for name in names:
        m = re.search(r"^static struct clk_branch %s = \{\n.*?"
                      r"\t\t\.enable_reg = (0x[0-9a-fA-F]+),.*?\n\};\n\n?"
                      % re.escape(name), text, re.M | re.S)
        if not m:
            sys.exit("--always-on: no branch %s" % name)
        moved.append((m.group(1).lower(), name.upper()))
        text = text.replace(m.group(0), "", 1)
        text = re.sub(r"\n\t\[%s\] = &%s\.clkr," % (name.upper(), name), "",
                      text, count=1)
    return text, moved


def branch_field(text, stmt):
    """`regmap_update_bits(regmap, X.clkr.enable_reg, 0xf0, 0xf0)` -> upstream's.

    The vendor sets a branch's sleep or wakeup delay by masking its CBCR by
    hand; upstream has qcom_branch_set_sleep() and qcom_branch_set_wakeup()
    for exactly those fields (CBCR_SLEEP is bits 7:4, CBCR_WAKEUP 11:8), and
    gpucc-sm6115 and -sm6125 use them for the same GMU clock. The helpers
    write the branch's halt_reg, so the rewrite is only made when that is the
    register the vendor wrote.
    """
    m = re.search(r"regmap_update_bits\(regmap, (\w+)\.clkr\.enable_reg, "
                  r"(0x[0-9a-fA-F]+), (0x[0-9a-fA-F]+)\);", stmt)
    if not m:
        return stmt
    mask, val = int(m.group(2), 16), int(m.group(3), 16)
    helper = {0xf0: ("sleep", 4), 0xf00: ("wakeup", 8)}.get(mask)
    b = re.search(r"^static struct clk_branch %s = \{\n\t\.halt_reg = "
                  r"(0x[0-9a-fA-F]+),\n.*?\t\t\.enable_reg = (0x[0-9a-fA-F]+),"
                  % re.escape(m.group(1)), text, re.M | re.S)
    if (not helper or val & ~mask or not b
            or int(b.group(1), 16) != int(b.group(2), 16)):
        return stmt
    return stmt.replace(m.group(0), "qcom_branch_set_%s(regmap, %s, 0x%x);"
                        % (helper[0], m.group(1), val >> helper[1]))


def rewrite_probe(text, soc, target, keep_calls, pfx, block, moved=()):
    """Replace the vendor probe with upstream's, preserving the always-on pokes.

    Downstream writes `regmap_update_bits(regmap, X, BIT(0), BIT(0))` to keep a
    branch ungated; upstream has `qcom_branch_set_clk_en(regmap, X)` for exactly
    that, so each one is translated and labelled with the clock it belongs to,
    in the order of those labels - both sm4450 drivers sort them by name.
    Everything else in the vendor probe - the dev_info, the dev_err, the
    runtime PM calls, the sync_state - goes.
    """
    span = find_func(text, r"^static int %s_%s_probe\(struct platform_device "
                           r"\*pdev\)\n\{" % (pfx, soc))
    if not span:
        return text, []
    body = text[span[0]:span[1]]

    pokes, names = poke_names(text, body)
    labelled = sorted([(names[r], r) for r in pokes if r in names] +
                      [(n, r) for r, n in moved])
    lines = ["\tqcom_branch_set_clk_en(regmap, %s); /* %s */" % (r, n)
             for n, r in labelled]
    lines += ["\tqcom_branch_set_clk_en(regmap, %s);" % r
              for r in pokes if r not in names]

    # Any other regmap_update_bits or regmap_write is SoC-specific and kept
    # verbatim, because we do not know what it does well enough to drop it -
    # and whatever comment the vendor put above it comes along, since that
    # comment is often the only record of what the bit means. One that sits
    # after the vendor's really_probe moves before upstream's, which is the
    # last statement; registering clocks does not touch these registers.
    others = []
    for o in re.finditer(r"(?:[ \t]*/\*(?:[^*]|\*(?!/))*\*/\n)?"
                         r"[ \t]*regmap_(?:update_bits|write)\(regmap, "
                         r"[^\n]*\);", body):
        stmt = branch_field(text, o.group(0))
        if "BIT(0), BIT(0)" in stmt:
            continue
        # A block comment's continuation lines keep their one-space indent.
        stmt = "\n".join(l.strip() and "\t" + " " * l.strip().startswith("*")
                         + l.strip() or l for l in stmt.split("\n"))
        others.append(stmt.lstrip("\t"))
    pll = re.findall(r"clk_(?:lucid|rivian)_evo_pll_configure\([^\n]*\);",
                     body)
    dfs = "qcom_cc_register_rcg_dfs" in body

    new = ["static int %s_%s_probe(struct platform_device *pdev)" % (pfx, target),
           "{", "\tstruct regmap *regmap;"]
    if dfs:
        new.append("\tint ret;")
    new += ["", "\tregmap = qcom_cc_map(pdev, &%s_%s_desc);" % (pfx, target),
            "\tif (IS_ERR(regmap))", "\t\treturn PTR_ERR(regmap);", ""]
    for p in pll:
        new.append("\t" + p)
    if pll:
        new.append("")
    if dfs:
        new += ["\tret = qcom_cc_register_rcg_dfs(regmap, %s_dfs_clocks," % pfx,
                "\t\t\t\t       ARRAY_SIZE(%s_dfs_clocks));" % pfx,
                "\tif (ret)", "\t\treturn ret;", ""]
    for c in keep_calls:
        new.append("\t" + c)
    if keep_calls:
        new.append("")
    if lines:
        new += ["\t/* %s */" % block["always_on_comment"]] + lines + [""]
    for i, o in enumerate(others):
        # As anywhere in the kernel, a blank line goes before a block comment.
        if i and o.count("\n") > 1:
            new.append("")
        new.append("\t" + o)
    if others:
        new.append("")
    new += ["\treturn qcom_cc_really_probe(&pdev->dev, &%s_%s_desc, regmap);"
            % (pfx, target), "}"]
    return text[:span[0]] + "\n".join(new) + text[span[1]:], others


def drop_sync_state(text, soc, pfx):
    text = drop_decls(text, re.compile(
        r"^static void %s_%s_sync_state\(struct device \*dev\)" % (pfx, soc)))
    return re.sub(r"\n\t\t\.sync_state = %s_%s_sync_state,\n" % (pfx, soc),
                  "\n", text)


def fix_resets(text, pfx):
    """Bring the reset map to upstream's names, and drop what is not a reset.

    The vendor graphics header doubles the prefix on its resets
    (GPUCC_GPU_CC_CX_BCR); upstream spells them GPU_CC_CX_BCR, like the
    clocks. And GPUCC_GPU_CC_FREQUENCY_LIMITER_IRQ_CLEAR is not a block reset:
    it is bit 0 of the GPU frequency limiter's interrupt-clear register,
    handed to kgsl through the reset API (parrot-gpu.dtsi has reset-names =
    "freq_limiter_irq_clear" next to a freq_limiter_irq interrupt). drm/msm
    has no frequency limiter support and gpucc-sm4450 does not carry it, so
    an *_IRQ_CLEAR entry goes.
    """
    tag = pfx.upper()
    text = re.sub(r"\b%s_%s_" % (tag.replace("_", ""), tag), tag + "_", text)
    return re.sub(r"\n\t\[\w+_IRQ_CLEAR\] = \{[^}\n]*\},", "", text)


def gdsc_resets(text, soc, pfx, gdscs):
    """Make sure every reset a GDSC pulses is in the reset map too.

    A GDSC with SW_RESET asserts its .resets around power-on, by index into
    the controller's reset map. Downstream lists them in the DT (`sw-reset`
    phandles to syscon nodes), and the vendor driver's reset map need not
    have them: ravelin's has neither GPU_CC_ACD_BCR nor
    GPU_CC_GX_ACD_IROOT_BCR, which gpucc-sm4450 adds. A missing one is
    inserted at its sorted place; one already there must agree on the offset.
    """
    m = re.search(r"(static const struct qcom_reset_map %s_%s_resets\[\] = "
                  r"\{\n)(.*?)(\n\};)" % (pfx, soc), text, re.S)
    want = [r for g in gdscs or () for r in g.get("resets", ())]
    if not want:
        return text
    if not m:
        sys.exit("a GDSC has resets but the driver has no reset map")
    fold = BLOCKS[pfx].get("fold_case", False)
    entries = m.group(2).split("\n")
    have = {}
    for e in entries:
        r = re.match(r"\t\[(\w+)\] = \{ (0x[0-9a-fA-F]+)", e)
        if r:
            have[r.group(1)] = int(r.group(2), 16)
    for r in want:
        if r["name"] in have:
            if have[r["name"]] != r["offset"]:
                sys.exit("GDSC reset %s: 0x%x in the GDSC list, 0x%x in the "
                         "reset map" % (r["name"], r["offset"], have[r["name"]]))
            continue
        line = "\t[%s] = { 0x%x }," % (r["name"], r["offset"])
        at = len(entries)
        for i, e in enumerate(entries):
            d = re.match(r"\t\[(\w+)\]", e)
            if d and natkey(d.group(1), fold) > natkey(r["name"], fold):
                at = i
                break
        entries.insert(at, line)
        have[r["name"]] = r["offset"]
        print("note: added GDSC reset %s at 0x%x to the reset map"
              % (r["name"], r["offset"]), file=sys.stderr)
    return text[:m.start(2)] + "\n".join(entries) + text[m.end(2):]


def add_gdscs(text, soc, target, gdscs, pfx):
    """Insert GDSC definitions and the desc entries that register them.

    The vendor gcc driver has no GDSCs at all: downstream describes them in the
    device tree as `qcom,gdsc` nodes with an absolute register address, and a
    separate regulator driver binds them. Upstream puts them in the clock
    driver, so the addresses come from the DT and are passed in here.

    The fields a GDSC may need beyond its register are passed the same way,
    and each maps from one property of the vendor node (the vendor's
    gdsc-regulator.txt binding against upstream's gdsc.c):

    - `gds_hw_ctrl`: `hw-ctrl-addr`, a separate status register;
    - `clamp_io_ctrl`: `domain-addr`, with the CLAMP_IO flag;
    - `resets`: `sw-reset`, with SW_RESET (and AON_RESET for
      `qcom,reset-aon-logic`);
    - `wait`: `qcom,clk-dis-wait-val` and friends, as (field, value) pairs.
      Without it the gcc defaults below are written, which is what every
      gcc and dispcc GDSC in the self-test pairs has;
    - `pd_name` and `power_on`: upstream's choices, not the vendor's - the
      GX GDSC of a GMU-based GPU is switched by the GMU, so the CPU side
      only pretends (gdsc_gx_do_nothing_enable).
    """
    if not gdscs:
        return text
    text = gdsc_resets(text, soc, pfx, gdscs)
    blocks = []
    for g in gdscs:
        f = ["\t.gdscr = 0x%x," % g["offset"]]
        for key in ("gds_hw_ctrl", "clamp_io_ctrl"):
            if key in g:
                f.append("\t.%s = 0x%x," % (key, g[key]))
        wait = g.get("wait", [["en_rest_wait_val", "0x2"],
                              ["en_few_wait_val", "0x2"],
                              ["clk_dis_wait_val", "0xf"]])
        f += ["\t.%s = %s," % (k, v) for k, v in wait]
        if g.get("resets"):
            lead = "\t.resets = (unsigned int []){ "
            col = 8 + len(lead) - 1
            pad = "\t" * (col // 8) + " " * (col % 8)
            names = [r["name"] for r in g["resets"]]
            f.append(lead + (",\n" + pad).join(names) + " },")
            f.append("\t.reset_count = %d," % len(names))
        f += ["\t.pd = {", '\t\t.name = "%s",' % g.get("pd_name", g["name"])]
        if g.get("power_on"):
            f.append("\t\t.power_on = %s," % g["power_on"])
        f += ["\t},", "\t.pwrsts = %s," % g.get("pwrsts", "PWRSTS_OFF_ON"),
              "\t.flags = %s," % " | ".join(g["flags"])]
        blocks.append("static struct gdsc %s = {\n%s\n};\n"
                      % (g["name"], "\n".join(f)))
    arr = ("static struct gdsc *%s_%s_gdscs[] = {\n%s\n};\n"
           % (pfx, target, "\n".join("\t[%s] = &%s," % (g.get("index",
                                                            g["name"].upper()),
                                                     g["name"])
                                for g in gdscs)))
    anchor = "static struct clk_regmap *%s_%s_clocks[] = {" % (pfx, soc)
    text = text.replace(anchor, "\n".join(blocks) + "\n" + anchor, 1)
    anchor2 = "static const struct qcom_reset_map %s_%s_resets[] = {" % (pfx, soc)
    text = text.replace(anchor2, arr + "\n" + anchor2, 1)
    return text.replace(
        "\t.num_resets = ARRAY_SIZE(%s_%s_resets),\n" % (pfx, soc),
        "\t.num_resets = ARRAY_SIZE(%s_%s_resets),\n"
        "\t.gdscs = %s_%s_gdscs,\n"
        "\t.num_gdscs = ARRAY_SIZE(%s_%s_gdscs),\n"
        % (pfx, soc, pfx, target, pfx, target), 1)


def gen_header(driver_text, target, year, pfx="gcc"):
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

    clks = designators("*%s_%s_clocks" % (pfx, target))
    resets = designators("%s_%s_resets" % (pfx, target))
    gdscs = designators("*%s_%s_gdscs" % (pfx, target))
    always = re.findall(r"(?:qcom_branch_set_clk_en\(regmap, |\t)0x[0-9a-f]+"
                        r"\)?[;,] /\* (\w+) \*/", driver_text)
    fold = BLOCKS[pfx].get("fold_case", False)
    clocks = sorted(set(clks) | set(always), key=lambda n: natkey(n, fold))

    tag = pfx.upper()
    guard = "_DT_BINDINGS_CLK_QCOM_%s_%s_H" % (tag, target.upper())
    out = ["/* SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause) */",
           "/*",
           " * Copyright (c) %s, Qualcomm Innovation Center, Inc. "
           "All rights reserved." % year,
           " */", "",
           "#ifndef %s" % guard,
           "#define %s" % guard, ""]
    # Upstream's spelling: a comment over every group, and the numbers in
    # one column, tab-aligned at 64 unless a name is too long for that.
    groups = [(tag + " clocks", clocks), (tag + " power domains", gdscs),
              (tag + " resets", resets)]
    names = [n for _, g in groups for n in g]
    col = max(64, (len("#define ") + max(map(len, names)) + 8) // 8 * 8)
    first = True
    for group, names in groups:
        if not names:
            continue
        out += ([] if first else [""]) + ["/* %s */" % group]
        first = False
        for i, n in enumerate(names):
            d = "#define " + n
            out.append(d + "\t" * ((col - len(d) + 7) // 8) + str(i))
    out += ["", "#endif"]
    return "\n".join(out) + "\n"


def sort_clocks_array(text, soc, pfx):
    """Put the clks[] designated initialisers in the header's order.

    They are designated, so the order is cosmetic to the compiler - but a
    reviewer reads the array against the header, and the vendor array is sorted
    as strings where upstream sorts numerically.
    """
    m = re.search(r"(static struct clk_regmap \*%s_%s_clocks\[\] = \{\n)"
                  r"(.*?)(\n\};)" % (pfx, soc), text, re.S)
    if not m:
        return text
    # An entry too long for one line continues on the next, as upstream
    # writes it too; the pair sorts as one.
    entries = []
    for l in m.group(2).split("\n"):
        if l.strip() and entries and not l.startswith("\t["):
            entries[-1] += "\n" + l
        elif l.strip():
            entries.append(l)
    keyed = []
    fold = BLOCKS[pfx].get("fold_case", False)
    for l in entries:
        d = re.search(r"\[(\w+)\]", l)
        keyed.append((natkey(d.group(1), fold) if d else (l, -1, ""), l))
    body = "\n".join(l for _, l in sorted(keyed, key=lambda kv: kv[0]))
    return text[:m.start()] + m.group(1) + body + m.group(3) + text[m.end():]


def module_driver(text, soc, pfx):
    """The init/exit pair becomes module_platform_driver(), as for every
    upstream clock controller but the GCCs, which register early on purpose."""
    pat = (r"static int __init %(p)s_%(s)s_init\(void\)\n\{\n.*?\n\}\n"
           r"\w+_initcall\(%(p)s_%(s)s_init\);\n\n"
           r"static void __exit %(p)s_%(s)s_exit\(void\)\n\{\n.*?\n\}\n"
           r"module_exit\(%(p)s_%(s)s_exit\);\n" % {"p": pfx, "s": soc})
    return re.sub(pat, "module_platform_driver(%s_%s_driver);\n" % (pfx, soc),
                  text, count=1, flags=re.S)


def to_driver_data(text, pfx, target, use_rpm):
    """Restate an upstream-shaped legacy probe as qcom_cc_driver_data.

    Since 6.17 a clock controller can hand its PLL configurations, its
    always-on branches and any other register setup to qcom_cc_really_probe()
    through desc->driver_data, and runtime PM through desc->use_rpm; the probe
    shrinks to qcom_cc_probe(). New controllers (dispcc-milos, dispcc-glymur,
    videocc-sm8550) are written that way. This is the same content moved, so
    it runs after everything else and only rearranges what the legacy probe
    already says.
    """
    name = "%s_%s" % (pfx, target)
    span = find_func(text, r"^static int %s_probe\(struct platform_device "
                           r"\*pdev\)\n\{" % name)
    body = text[span[0]:span[1]]
    # qcom_clk_alpha_pll_configure() picks the PLL's own configure by its
    # type, so a Rivian EVO goes in the same list as the Lucid EVOs.
    plls = re.findall(r"clk_(?:lucid|rivian)_evo_pll_configure\(&(\w+), "
                      r"regmap, &(\w+)\);", body)
    for pll, cfg in plls:
        text = re.sub(r"(static struct clk_alpha_pll %s = \{\n\t\.offset = "
                      r"[^\n]*\n)" % pll, r"\1\t.config = &%s,\n" % cfg, text,
                      count=1)
    cbcrs = re.findall(r"\tqcom_branch_set_clk_en\(regmap, (0x[0-9a-f]+)\);"
                       r"( /\* \w+ \*/)?", body)
    # What is left between the pokes and the return is register setup the
    # vendor needed: it moves into clk_regs_configure() as it stands.
    rest = []
    for chunk in body.split("\n\n")[1:]:
        lines = [l for l in chunk.split("\n")
                 if l.strip() and "qcom_branch_set_clk_en" not in l
                 and "pll_configure" not in l and "Keep some clocks" not in l
                 and "qcom_cc_map" not in l and "IS_ERR" not in l
                 and "PTR_ERR" not in l and "really_probe" not in l
                 and l.strip() != "}"]
        if lines:
            rest.append("\n".join(lines))
    if "register_rcg_dfs" in body:
        sys.exit("--driver-data: a DFS probe is not handled yet")

    decls = []
    if plls:
        decls.append("static struct clk_alpha_pll *%s_plls[] = {\n%s\n};\n"
                     % (name, "\n".join("\t&%s," % p for p, _ in plls)))
    if cbcrs:
        decls.append("static u32 %s_critical_cbcrs[] = {\n%s\n};\n"
                     % (name, "\n".join("\t%s,%s" % c for c in cbcrs)))
    regcfg = re.search(r"static const struct regmap_config %s_regmap_config = "
                       r"\{\n.*?\n\};\n" % name, text, re.S)
    after = [regcfg.group(0)]
    if rest:
        after.append("static void %s_clk_regs_configure(struct device *dev, "
                     "struct regmap *regmap)\n{\n%s\n}\n"
                     % (name, "\n\n".join(rest)))
    fields = []
    if plls:
        fields += ["\t.alpha_plls = %s_plls," % name,
                   "\t.num_alpha_plls = ARRAY_SIZE(%s_plls)," % name]
    if cbcrs:
        fields += ["\t.clk_cbcrs = %s_critical_cbcrs," % name,
                   "\t.num_clk_cbcrs = ARRAY_SIZE(%s_critical_cbcrs)," % name]
    if rest:
        fields.append("\t.clk_regs_configure = %s_clk_regs_configure," % name)
    after.append("static struct qcom_cc_driver_data %s_driver_data = {\n%s\n};\n"
                 % (name, "\n".join(fields)))
    text = text.replace(regcfg.group(0),
                        "\n".join(decls + after), 1)

    extra = ("\t.use_rpm = true,\n" if use_rpm else "") + \
        "\t.driver_data = &%s_driver_data,\n" % name
    text = re.sub(r"(static const struct qcom_cc_desc %s_desc = \{\n.*?)(\n\};)"
                  % name, lambda m: m.group(1) + "\n" + extra.rstrip("\n")
                  + m.group(2), text, count=1, flags=re.S)
    span = find_func(text, r"^static int %s_probe\(struct platform_device "
                           r"\*pdev\)\n\{" % name)
    return (text[:span[0]] +
            "static int %s_probe(struct platform_device *pdev)\n{\n"
            "\treturn qcom_cc_probe(pdev, &%s_desc);\n}" % (name, name) +
            text[span[1]:])


def convert(src, soc, target, phy_mux=None, gdscs=None, keep_calls=(),
            copyright_year=None, block="gcc", always_on=(), driver_data=False,
            use_rpm=False, always_on_regs=()):
    pfx, prof = block, BLOCKS[block]
    text = src

    # 1. The vendor voltage-scaling machinery, which upstream has no equivalent
    #    for: the regulator classes, the array of them, and the per-clock
    #    rate_max tables that reference them.
    text = drop_decls(text, re.compile(r"^static DEFINE_VDD_REGULATORS\("))
    text = drop_decls(text, re.compile(r"^static struct clk_vdd_class \*\w+_regulators\[\]"))
    text = drop_balanced_blocks(text, re.compile(r"^\s*\.(?:clkr\.)?vdd_data = \{\s*$"))

    # 2. Per-line vendor fields, and CLK_DONT_HOLD_STATE where it shares a
    #    .flags line with a flag upstream keeps.
    text = "\n".join(l for l in text.split("\n")
                     if not any(d in l for d in DROP_LINES))
    text = re.sub(r"CLK_DONT_HOLD_STATE \| | ?\| CLK_DONT_HOLD_STATE\b", "",
                  text)
    # The camera front ends' RCGs ask for their rate to be read back from the
    # hardware every time, for a vendor firmware that changes it behind the
    # kernel's back. camcc-sm4450 drops the flag.
    text = re.sub(r" \| CLK_GET_RATE_NOCACHE\b", "", text)

    # 3. Parent naming, ops, PLL configurations and the pipe mux - in that
    #    order, because the mux rewrite wants the DT_* names to already exist.
    text = drop_foreign_parents(text, pfx, prof)
    text = rewrite_parents(text)
    text = dp_link(text)
    text = rewrite_ops(text)
    text = byte_div(text)
    text = pll_configs(text, prof.get("merge_pll_configs", True))
    if phy_mux:
        text, suffix = to_phy_mux(text, phy_mux, pfx)
        if suffix:
            text = drop_parent_set(text, suffix, pfx)
            text = renumber_parents(text, pfx)

    # 4. The driver's own boilerplate.
    text, moved = move_always_on(text, soc, pfx, always_on)
    # A register the vendor never names at all - gpucc-sm4450 keeps its
    # GPU_CC_CB_CLK on, which ravelin neither registers nor pokes - is the
    # same reviewer's call, given by address and name (--always-on-reg).
    moved += [("0x%x" % r, n) for r, n in always_on_regs]
    text, _ = rewrite_probe(text, soc, target, keep_calls, pfx, prof, moved)
    text = drop_sync_state(text, soc, pfx)
    text = fix_resets(text, pfx)
    text = add_gdscs(text, soc, target, gdscs, pfx)
    text = sort_clocks_array(text, soc, pfx)
    if prof["module_driver"]:
        text = module_driver(text, soc, pfx)
    # The vendor's runtime PM callbacks are qcom_cc_runtime_suspend/resume,
    # which upstream does not have: there the clock controller's power domains
    # are runtime-managed by genpd, and desc->use_rpm or the probe keeps them
    # up while it touches registers. The descriptor is const upstream.
    text = re.sub(r"(?ms)^static const struct dev_pm_ops %s_%s_pm_ops = "
                  r"\{\n.*?^\};\n\n?" % (pfx, soc), "", text)
    text = re.sub(r"\n\t\t\.pm = &%s_%s_pm_ops," % (pfx, soc), "", text)
    text = text.replace("static struct qcom_cc_desc ",
                        "static const struct qcom_cc_desc ")
    text = text.replace('MODULE_LICENSE("GPL v2")', 'MODULE_LICENSE("GPL")')

    # 5. Names. `qcom,gcc-parrot.h` is handled by the include rewrite below, so
    #    only the identifiers and the compatible are renamed here. The display
    #    and graphics controllers' driver names and descriptions are spelled
    #    `dispcc` and `gpucc` upstream where the vendor writes `disp_cc` and
    #    `gpu_cc`.
    text = text.replace(soc, target).replace(soc.upper(), target.upper())
    if pfx != "gcc":
        short = pfx.replace("_", "")
        text = text.replace('.name = "%s-%s"' % (pfx, target),
                            '.name = "%s-%s"' % (short, target))
        text = text.replace('MODULE_DESCRIPTION("QTI %s ' % pfx.upper(),
                            'MODULE_DESCRIPTION("QTI %s ' % short.upper())

    # 6. The include block, and the DT_* enum that replaces the fw_names. A
    #    register #define the vendor put above the parent enum (DISP_CC_MISC_CMD)
    #    goes below the DT_* enum, where upstream keeps it.
    inc = prof["includes"].format(
        target=target,
        phy_mux_include='#include "clk-regmap-phy-mux.h"\n' if phy_mux else "")
    start = text.index("#include <linux/")
    end = text.index("\n\n", text.index('#include "reset.h"'))
    text = text[:start] + inc + text[end + 1:]
    # The divider header goes with the last divider: camcc-sm4450 has none.
    if "clk_regmap_div " not in text:
        text = text.replace('#include "clk-regmap-divider.h"\n', "")
    text = re.sub(r"\n((?:#define [^\n]*\n\n)?enum \{\n\tP_)",
                  lambda m: "\n%s\n%s" % (dt_enum(text, prof), m.group(1)),
                  text, count=1)

    if driver_data:
        text = to_driver_data(text, pfx, target, use_rpm)

    # 7. Spelling.
    text = spaced_casts(text)
    text = lower_hex(text)
    text = re.sub(r"/\* (\d+)MHz [Cc]onfiguration \*/",
                  r"/* \1.0 MHz Configuration */", text)
    if copyright_year:
        text = re.sub(r"Copyright \(c\) [\d\-, ]+, Qualcomm",
                      "Copyright (c) %s, Qualcomm" % copyright_year, text, count=1)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def gdsc(name, offset, flags, index=None, **extra):
    """One GDSC; `extra` takes add_gdscs' optional fields."""
    return dict({"name": name, "offset": offset, "flags": flags,
                 "index": index or name.upper()}, **extra)


# The pairs on disk: a vendor driver, its upstream counterpart, and what the
# person who upstreamed it decided that the vendor file does not say.
PAIRS = [
    ("gcc-ravelin.c", "gcc-sm4450.c", "qcom,sm4450-gcc.h", {
        "block": "gcc",
        "phy_mux": "gcc_pcie_0_pipe_clk_src",
        "gdscs": [
            gdsc("gcc_pcie_0_gdsc", 0x7b004,
                 ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE", "VOTABLE"]),
            gdsc("gcc_ufs_phy_gdsc", 0x87004,
                 ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]),
            gdsc("gcc_usb30_prim_gdsc", 0x49004,
                 ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]),
            gdsc("gcc_vcodec0_gdsc", 0xb6044,
                 ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE", "HW_CTRL"]),
            gdsc("gcc_venus_gdsc", 0xb6020,
                 ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]),
        ],
        "keep_calls": ["qcom_branch_set_force_mem_core(regmap, "
                       "gcc_ufs_phy_ice_core_clk, true);"],
        "always_on": ["gcc_camera_sleep_clk"],
        "copyright_year": "2023",
    }),
    ("dispcc-ravelin.c", "dispcc-sm4450.c", "qcom,sm4450-dispcc.h", {
        "block": "disp_cc",
        "gdscs": [
            gdsc("disp_cc_mdss_core_gdsc", 0x9000,
                 ["HW_CTRL", "POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]),
            gdsc("disp_cc_mdss_core_int2_gdsc", 0xb000,
                 ["HW_CTRL", "POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]),
        ],
        "always_on": ["disp_cc_sleep_clk"],
        "copyright_year": "2024",
    }),
    ("gpucc-ravelin.c", "gpucc-sm4450.c", "qcom,sm4450-gpucc.h", {
        "block": "gpu_cc",
        "gdscs": [
            gdsc("gpu_cc_cx_gdsc", 0x9108, ["VOTABLE", "RETAIN_FF_ENABLE"],
                 gds_hw_ctrl=0x953c, wait=[["clk_dis_wait_val", "8"]],
                 pd_name="gpu_cx_gdsc"),
            gdsc("gpu_cc_gx_gdsc", 0x905c,
                 ["CLAMP_IO", "AON_RESET", "SW_RESET", "POLL_CFG_GDSCR"],
                 clamp_io_ctrl=0x9504, wait=[],
                 resets=[{"name": "GPU_CC_GX_BCR", "offset": 0x9058},
                         {"name": "GPU_CC_ACD_BCR", "offset": 0x9358},
                         {"name": "GPU_CC_GX_ACD_IROOT_BCR", "offset": 0x958c}],
                 pd_name="gpu_gx_gdsc",
                 power_on="gdsc_gx_do_nothing_enable"),
        ],
        "always_on": ["gpu_cc_cxo_aon_clk", "gpu_cc_demet_clk"],
        "always_on_regs": [(0x93a4, "GPU_CC_CB_CLK")],
        "copyright_year": "2024",
    }),
    ("camcc-ravelin.c", "camcc-sm4450.c", "qcom,sm4450-camcc.h", {
        "block": "cam_cc",
        "gdscs": [
            gdsc("cam_cc_camss_top_gdsc", 0x14004,
                 ["POLL_CFG_GDSCR", "RETAIN_FF_ENABLE"]),
        ],
        "copyright_year": "2024",
    }),
]


def score(got, want, label):
    """Print how far `got` is from `want`; return the significant line count."""
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
    print("%s: generated %d lines, upstream has %d" % (label, len(a), len(b)))
    print("%s: differing lines: %d raw, %d ignoring whitespace "
          "(%.2f%% of upstream matches)"
          % (label, raw, len(ndiff), (1 - len(ndiff) / max(len(b), 1)) * 100))
    if diff:
        print("\n".join(diff))
    return len(ndiff)


def selftest():
    """Convert each vendor driver of a pair and diff against upstream's."""
    scratch = os.environ.get("D2M_DOWNSTREAM")
    if not scratch:
        print("set D2M_DOWNSTREAM to the directory holding %s"
              % " and ".join(p[0] for p in PAIRS), file=sys.stderr)
        return 2
    bad = 0
    for down, up, header, opts in PAIRS:
        src = os.path.join(scratch, down)
        ref = os.path.join(ROOT, "out/linux/drivers/clk/qcom", up)
        href = os.path.join(ROOT, "out/linux/include/dt-bindings/clock", header)
        for p in (src, ref, href):
            if not os.path.exists(p):
                print("missing %s" % p, file=sys.stderr)
                return 2
        got = convert(open(src).read(), down.split("-")[1][:-2], "sm4450",
                      **opts)
        bad += score(got, open(ref).read(), up)
        hdr = gen_header(got, "sm4450", opts["copyright_year"],
                         pfx=opts["block"])
        bad += score(hdr, open(href).read(), header)
    return 0 if bad == 0 else 1


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
    ap.add_argument("--block", choices=sorted(BLOCKS), default="gcc",
                    help="which clock controller the source is (default gcc)")
    ap.add_argument("--always-on", action="append", default=[],
                    help="a branch to poke always-on in probe instead of "
                         "registering it")
    ap.add_argument("--always-on-reg", action="append", default=[],
                    metavar="OFFSET=NAME",
                    help="a branch the vendor driver does not have, to poke "
                         "always-on in probe, e.g. 0x93a4=GPU_CC_CB_CLK")
    ap.add_argument("--driver-data", action="store_true",
                    help="emit the qcom_cc_driver_data probe of newer drivers")
    ap.add_argument("--use-rpm", action="store_true",
                    help="with --driver-data: set desc->use_rpm")
    ap.add_argument("--year", help="copyright year for the new file (default:"
                    " the vendor file's)")
    ap.add_argument("--header", metavar="DRIVER",
                    help="emit the dt-bindings header for an already-generated "
                         "driver instead of converting one")
    ap.add_argument("--selftest", action="store_true",
                    help="convert the ravelin drivers and diff against "
                         "upstream's sm4450 ones")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.header:
        if not args.target:
            ap.error("--header needs --target")
        drv = open(args.header).read()
        year = args.year or re.search(r"Copyright \(c\) ([\d\-, ]+?),",
                                      drv).group(1)
        sys.stdout.write(gen_header(drv, args.target, year, pfx=args.block))
        return 0
    if not (args.source and args.soc and args.target):
        ap.error("source, --soc and --target are required")
    gdscs = json.load(open(args.gdsc_file)) if args.gdsc_file else None
    sys.stdout.write(convert(open(args.source).read(), args.soc, args.target,
                             phy_mux=args.phy_mux[0] if args.phy_mux else None,
                             gdscs=gdscs, keep_calls=args.keep_call,
                             copyright_year=args.year, block=args.block,
                             always_on=args.always_on,
                             always_on_regs=[
                                 (int(r.split("=")[0], 16), r.split("=")[1])
                                 for r in args.always_on_reg],
                             driver_data=args.driver_data,
                             use_rpm=args.use_rpm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
