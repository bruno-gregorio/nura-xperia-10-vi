#!/usr/bin/env python3
"""Turn a downstream Qualcomm TLMM pinctrl driver into a mainline-shaped one.

Same idea as scripts/downstream-to-mainline.py, and the same proof: Qualcomm
released pinctrl-ravelin.{c,h} downstream and someone upstreamed it as
pinctrl-sm4450.c, so --selftest converts the downstream half and diffs the
result against the upstream half.

Three things change beyond the cosmetic:

- **The file stops being two files.** Downstream puts the tables in a header
  and the driver in a .c that includes it. Upstream has one .c.
- **Register offsets become relative.** Downstream's PINGROUP macro adds
  REG_BASE (0x100000) to every offset, and the SDC and UFS rows carry absolute
  addresses. Upstream's device tree points at the TLMM base, so the offsets are
  relative to it and REG_BASE goes away.
- **Function names collapse.** This is the big one. Downstream names every
  individual signal - phase_flag_status0 through status31, qup0_se0_l0 through
  l3, cci_i2c_scl0 and cci_i2c_sda0 - and upstream groups them into one
  function per peripheral, whose group list is the concatenation of the
  per-signal lists. 190 names become 70.

That last rule is not invented here either. It is learned from the pair: for
every upstream function name, find the downstream names it is a prefix of.
On ravelin/sm4450 the longest-prefix match maps all 190 downstream names onto
all 70 upstream ones with nothing unmapped and nothing unused, which is what
makes it safe to apply to a different SoC. Names a learned prefix does not
cover are reported, not guessed; --extra-function adds one.

    scripts/pinctrl-to-mainline.py --selftest
    scripts/pinctrl-to-mainline.py --soc parrot --target sm6450 \
        --ngpios 142 --header in/pinctrl-parrot.h > out/pinctrl-sm6450.c

The register tables are the part that must not change, and scripts/check-
tables.sh is what checks that independently afterwards.
"""
import argparse
import difflib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

REG_BASE = 0x100000

PREAMBLE = '''// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) @YEAR@ Qualcomm Innovation Center, Inc. All rights reserved.
 */

#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

#include "pinctrl-msm.h"

#define REG_SIZE 0x1000

#define PINGROUP(id, f1, f2, f3, f4, f5, f6, f7, f8, f9)\t\\
\t{\t\t\t\t\t        \\
\t\t.grp = PINCTRL_PINGROUP("gpio" #id,     \\
\t\t\tgpio##id##_pins,                \\
\t\t\tARRAY_SIZE(gpio##id##_pins)),   \\
\t\t.funcs = (int[]){\t\t\t\\
\t\t\tmsm_mux_gpio, /* gpio mode */\t\\
\t\t\tmsm_mux_##f1,\t\t\t\\
\t\t\tmsm_mux_##f2,\t\t\t\\
\t\t\tmsm_mux_##f3,\t\t\t\\
\t\t\tmsm_mux_##f4,\t\t\t\\
\t\t\tmsm_mux_##f5,\t\t\t\\
\t\t\tmsm_mux_##f6,\t\t\t\\
\t\t\tmsm_mux_##f7,\t\t\t\\
\t\t\tmsm_mux_##f8,\t\t\t\\
\t\t\tmsm_mux_##f9\t\t\t\\
\t\t},\t\t\t\t        \\
\t\t.nfuncs = 10,\t\t\t\t\\
\t\t.ctl_reg = REG_SIZE * id,\t\t\t\\
\t\t.io_reg = 0x4 + REG_SIZE * id,\t\t\\
\t\t.intr_cfg_reg = 0x8 + REG_SIZE * id,\t\t\\
\t\t.intr_status_reg = 0xc + REG_SIZE * id,\t\\
\t\t.intr_target_reg = 0x8 + REG_SIZE * id,\t\\
\t\t.mux_bit = 2,\t\t\t\\
\t\t.pull_bit = 0,\t\t\t\\
\t\t.drv_bit = 6,\t\t\t\\
\t\t.egpio_enable = 12,\t\t\\
\t\t.egpio_present = 11,\t\t\\
\t\t.oe_bit = 9,\t\t\t\\
\t\t.in_bit = 0,\t\t\t\\
\t\t.out_bit = 1,\t\t\t\\
\t\t.intr_enable_bit = 0,\t\t\\
\t\t.intr_status_bit = 0,\t\t\\
\t\t.intr_target_bit = 5,\t\t\\
\t\t.intr_target_kpss_val = 3,\t\\
\t\t.intr_raw_status_bit = 4,\t\\
\t\t.intr_polarity_bit = 1,\t\t\\
\t\t.intr_detection_bit = 2,\t\\
\t\t.intr_detection_width = 2,\t\\
\t}

#define SDC_QDSD_PINGROUP(pg_name, ctl, pull, drv)\t\\
\t{\t\t\t\t\t        \\
\t\t.grp = PINCTRL_PINGROUP(#pg_name,       \\
\t\t\tpg_name##_pins,                 \\
\t\t\tARRAY_SIZE(pg_name##_pins)),    \\
\t\t.ctl_reg = ctl,\t\t\t\t\\
\t\t.io_reg = 0,\t\t\t\t\\
\t\t.intr_cfg_reg = 0,\t\t\t\\
\t\t.intr_status_reg = 0,\t\t\t\\
\t\t.intr_target_reg = 0,\t\t\t\\
\t\t.mux_bit = -1,\t\t\t\t\\
\t\t.pull_bit = pull,\t\t\t\\
\t\t.drv_bit = drv,\t\t\t\t\\
\t\t.oe_bit = -1,\t\t\t\t\\
\t\t.in_bit = -1,\t\t\t\t\\
\t\t.out_bit = -1,\t\t\t\t\\
\t\t.intr_enable_bit = -1,\t\t\t\\
\t\t.intr_status_bit = -1,\t\t\t\\
\t\t.intr_target_bit = -1,\t\t\t\\
\t\t.intr_raw_status_bit = -1,\t\t\\
\t\t.intr_polarity_bit = -1,\t\t\\
\t\t.intr_detection_bit = -1,\t\t\\
\t\t.intr_detection_width = -1,\t\t\\
\t}

#define UFS_RESET(pg_name, offset)\t\t\t\t\\
\t{\t\t\t\t\t        \\
\t\t.grp = PINCTRL_PINGROUP(#pg_name,       \\
\t\t\tpg_name##_pins,                 \\
\t\t\tARRAY_SIZE(pg_name##_pins)),    \\
\t\t.ctl_reg = offset,\t\t\t\\
\t\t.io_reg = offset + 0x4,\t\t\t\\
\t\t.intr_cfg_reg = 0,\t\t\t\\
\t\t.intr_status_reg = 0,\t\t\t\\
\t\t.intr_target_reg = 0,\t\t\t\\
\t\t.mux_bit = -1,\t\t\t\t\\
\t\t.pull_bit = 3,\t\t\t\t\\
\t\t.drv_bit = 0,\t\t\t\t\\
\t\t.oe_bit = -1,\t\t\t\t\\
\t\t.in_bit = -1,\t\t\t\t\\
\t\t.out_bit = 0,\t\t\t\t\\
\t\t.intr_enable_bit = -1,\t\t\t\\
\t\t.intr_status_bit = -1,\t\t\t\\
\t\t.intr_target_bit = -1,\t\t\t\\
\t\t.intr_raw_status_bit = -1,\t\t\\
\t\t.intr_polarity_bit = -1,\t\t\\
\t\t.intr_detection_bit = -1,\t\t\\
\t\t.intr_detection_width = -1,\t\t\\
\t}

#define QUP_I3C(qup_mode, qup_offset)\t\t\t\\
\t{\t\t\t\t\t\t\\
\t\t.mode = qup_mode,\t\t\t\\
\t\t.offset = qup_offset,\t\t\t\\
\t}


'''

TAIL = '''
static const struct msm_pinctrl_soc_data {target}_tlmm = {{
\t.pins = {target}_pins,
\t.npins = ARRAY_SIZE({target}_pins),
\t.functions = {target}_functions,
\t.nfunctions = ARRAY_SIZE({target}_functions),
\t.groups = {target}_groups,
\t.ngroups = ARRAY_SIZE({target}_groups),
\t.ngpios = {ngpios},
\t.wakeirq_map = {target}_pdc_map,
\t.nwakeirq_map = ARRAY_SIZE({target}_pdc_map),
}};

static int {target}_tlmm_probe(struct platform_device *pdev)
{{
\treturn msm_pinctrl_probe(pdev, &{target}_tlmm);
}}

static const struct of_device_id {target}_tlmm_of_match[] = {{
\t{{ .compatible = "qcom,{target}-tlmm", }},
\t{{ }}
}};

static struct platform_driver {target}_tlmm_driver = {{
\t.driver = {{
\t\t.name = "{target}-tlmm",
\t\t.of_match_table = {target}_tlmm_of_match,
\t}},
\t.probe = {target}_tlmm_probe,
}};
MODULE_DEVICE_TABLE(of, {target}_tlmm_of_match);

static int __init {target}_tlmm_init(void)
{{
\treturn platform_driver_register(&{target}_tlmm_driver);
}}
arch_initcall({target}_tlmm_init);

static void __exit {target}_tlmm_exit(void)
{{
\tplatform_driver_unregister(&{target}_tlmm_driver);
}}
module_exit({target}_tlmm_exit);

MODULE_DESCRIPTION("QTI {TARGET} TLMM driver");
MODULE_LICENSE("GPL");
'''


def block(text, first_line_re, end="\n};\n"):
    """Return the text of a declaration, from its opening line to `end`."""
    m = re.search(first_line_re, text, re.M)
    if not m:
        return None
    return text[m.start():text.index(end, m.start()) + len(end)]


def parse_downstream(header, soc):
    """Pull every table out of the vendor header."""
    t = open(header).read()
    d = {}
    d["pins"] = block(t, r"^static const struct pinctrl_pin_desc %s_pins\[\] = \{$" % soc)
    d["gpio_decl"] = block(t, r"^#define DECLARE_MSM_GPIO_PINS\(pin\)",
                           end=");\n\n")
    d["special_pins"] = re.findall(
        r"^static const unsigned int \w+_pins\[\] = \{ \d+ \};$", t, re.M)
    # Vendor headers are inconsistent about case - parrot writes QSPI0 and
    # PCIE0_CLK_REQ in capitals and everything else in lower case - while every
    # upstream driver is lower case throughout. The name is what a device tree
    # writes in qcom,function, so it has to be settled here and settled the
    # same way in the enum, the group arrays and the pingroup rows.
    d["enum"] = [m.group(1) for m in
                 re.finditer(r"^\tmsm_mux_([A-Za-z0-9_]+),$", t, re.M)]
    d["enum"] = [n if n == "NA" else n.lower() for n in d["enum"]]
    t = re.sub(r"\b(msm_mux_|FUNCTION\()([A-Z][A-Z0-9_]*)\b",
               lambda m: m.group(1) + m.group(2).lower()
               if m.group(2) != "NA" else m.group(0), t)
    t = re.sub(r"\b([A-Z][A-Z0-9_]*)_groups\b",
               lambda m: m.group(1).lower() + "_groups", t)
    d["groups"] = {}
    for m in re.finditer(r"^static const char \* const (\w+)_groups\[\] = \{\n(.*?)\n\};$",
                         t, re.M | re.S):
        items = re.findall(r'"([^"]+)"', m.group(2))
        d["groups"][m.group(1)] = items
    d["functions"] = re.findall(r"^\tFUNCTION\((\w+)\),$", t, re.M)
    rows = block(t, r"^static const struct msm_pingroup %s_groups\[\] = \{$" % soc)
    d["rows"] = rows
    d["pdc"] = block(t, r"^static const struct msm_gpio_wakeirq_map %s_pdc_map\[\] = \{$" % soc)
    return d


def learn_prefixes(down_names, up_names):
    """Map each downstream function name to the upstream name it collapses into.

    Longest prefix wins: cci_i2c_scl0 goes to cci_i2c rather than to cci. The
    caller supplies the upstream name set, either learned from the reference
    pair or extended with --extra-function.
    """
    mapping, loose = {}, []
    for n in down_names:
        cands = [f for f in up_names if n == f or n.startswith(f)]
        if cands:
            mapping[n] = max(cands, key=len)
        else:
            loose.append(n)
    return mapping, loose


def wrap_items(items, indent="\t", width=80):
    """Lay out a quoted list the way the upstream files do: fill to 80 columns."""
    lines, cur = [], indent
    for it in items:
        piece = '"%s",' % it
        # A tab counts as eight columns when measuring the line.
        used = len(cur.replace("\t", " " * 8))
        if cur != indent and used + 1 + len(piece) > width:
            lines.append(cur.rstrip())
            cur = indent
        cur += ("" if cur == indent else " ") + piece
    if cur != indent:
        lines.append(cur.rstrip())
    return "\n".join(lines)


def rewrite_rows(rows, mapping, soc, target):
    """Rewrite the pingroup table: collapse functions, drop the wake columns.

    Upstream's PINGROUP takes nine function slots and no wake register, because
    the wakeirq mapping lives in the pdc_map table instead. Downstream passes
    two extra arguments for it, which have to come off every row.
    """
    rows = rows.replace("%s_groups[]" % soc, "%s_groups[]" % target)
    out = []
    for line in rows.split("\n"):
        out.append(line)
    text = "\n".join(out)

    def fix_pingroup(m):
        args = [a.strip() for a in m.group(2).replace("\n", " ").split(",")]
        gpio, funcs = args[0], args[1:-2]   # the last two are wake_off and bit
        # Look the name up case-insensitively. The mapping is keyed on the
        # settled lower-case names, but these are bare macro arguments, so a
        # vendor header that capitalises QSPI0 would otherwise miss and fall
        # through to "_" - which is not an error, it is a silently dropped mux
        # assignment. check-tables.sh caught exactly that.
        funcs = ["_" if f == "NA" else mapping.get(f.lower(), "_") for f in funcs]
        body = ", ".join([gpio] + funcs)
        # Never wrapped: upstream's own tables run to 119 columns here, and a
        # one-row-per-line table is what makes the register map readable.
        return "%s = PINGROUP(%s)," % (m.group(1), body)

    text = re.sub(r"(\t\[\d+\]) = PINGROUP\(((?:[^()]|\n)*?)\),",
                  fix_pingroup, text)

    # The SDC and UFS rows carry absolute addresses; upstream's are relative to
    # the TLMM base.
    def rebase(m):
        return "0x%x" % (int(m.group(1), 16) - REG_BASE)
    text = re.sub(r"(?<=[(,] )(0x1[0-9a-fA-F]{5})(?=[,)])", lambda m: rebase(m), text)
    return text


def convert(header, soc, target, ngpios, up_names, year, extra=()):
    d = parse_downstream(header, soc)
    down = [n for n in d["enum"] if n not in ("gpio", "NA")]
    mapping, loose = learn_prefixes(down, set(up_names) | set(extra))
    if loose:
        print("note: %d function names no learned prefix covers; they are kept "
              "as they are:\n  %s" % (len(loose), ", ".join(loose)), file=sys.stderr)
        for n in loose:
            mapping[n] = n
    mapping["gpio"] = "gpio"

    # Collapsed names in order of first appearance, which is the order upstream
    # keeps - note cci_i2c lands before cci there, not alphabetically.
    collapsed, seen = [], set()
    for n in down:
        c = mapping[n]
        if c not in seen:
            seen.add(c)
            collapsed.append(c)

    # Each collapsed function's group list is the concatenation of the lists of
    # the downstream names that fed into it, in downstream order, with repeats
    # removed: two signals can share a pin.
    # Sorted by pin number. The order has no effect on behaviour - this is the
    # list of groups that may select the function - and upstream's own files
    # are inconsistent about it, because they were merged by hand: sm4450 has
    # qdss_gpio in pin order and cci_i2c in signal order. Sorting is
    # deterministic, which matters more here than matching either one.
    merged = {}
    for n in down:
        c = mapping[n]
        for g in d["groups"].get(n, []):
            merged.setdefault(c, set()).add(g)
    merged = {c: sorted(gs, key=lambda g: int(re.sub(r"\D", "", g) or -1))
              for c, gs in merged.items()}

    out = [PREAMBLE.replace("@YEAR@", year)]
    out.append(d["pins"].replace("%s_pins[]" % soc, "%s_pins[]" % target))
    out.append("")
    out.append(d["gpio_decl"].rstrip("\n"))
    out.append("")
    out.append("\n".join(d["special_pins"]))
    out.append("")
    out.append("enum %s_functions {\n\tmsm_mux_gpio,\n%s\n\tmsm_mux__,\n};\n"
               % (target, "\n".join("\tmsm_mux_%s," % c for c in collapsed)))
    out.append('static const char * const gpio_groups[] = {\n%s\n};'
               % wrap_items(d["groups"]["gpio"]))
    for c in collapsed:
        out.append('static const char * const %s_groups[] = {\n%s\n};'
                   % (c, wrap_items(merged.get(c, []))))
    out.append("")
    out.append("static const struct pinfunction %s_functions[] = {\n"
               "\tMSM_GPIO_PIN_FUNCTION(gpio),\n%s\n};\n"
               % (target, "\n".join("\tMSM_PIN_FUNCTION(%s)," % c for c in collapsed)))
    out.append("/*\n"
               " * Every pin is maintained as a single group, and missing or "
               "non-existing pin\n"
               " * would be maintained as dummy group to synchronize pin group "
               "index with\n"
               " * pin descriptor registered with pinctrl core.\n"
               " * Clients would not be able to request these dummy pin "
               "groups.\n"
               " */")
    out.append(rewrite_rows(d["rows"], mapping, soc, target).rstrip("\n"))
    out.append("")
    out.append(d["pdc"].replace("%s_pdc_map[]" % soc,
                                "%s_pdc_map[]" % target).rstrip("\n"))
    out.append(TAIL.format(target=target, TARGET=target.upper(), ngpios=ngpios))
    # Collapse runs of blank lines, but keep the double blank the upstream
    # files have between the macro block and the first table.
    text = "\n".join(out)
    head, sep, rest = text.partition("static const struct pinctrl_pin_desc")
    return head + sep + re.sub(r"\n{3,}", "\n\n", rest), loose


def up_function_names(path):
    t = open(path).read()
    m = re.search(r"^enum \w+_functions \{\n(.*?)\n\};", t, re.S | re.M)
    names = [x.group(1) for x in re.finditer(r"^\tmsm_mux_([A-Za-z0-9_]+),$",
                                             m.group(1), re.M)]
    return [n for n in names if n not in ("gpio", "_")]


def selftest():
    scratch = os.environ.get("P2M_DOWNSTREAM")
    if not scratch:
        print("set P2M_DOWNSTREAM to the directory holding pinctrl-ravelin.h",
              file=sys.stderr)
        return 2
    src = os.path.join(scratch, "pinctrl-ravelin.h")
    ref = os.path.join(ROOT, "out/linux/drivers/pinctrl/qcom/pinctrl-sm4450.c")
    for p in (src, ref):
        if not os.path.exists(p):
            print("missing %s" % p, file=sys.stderr)
            return 2
    up = up_function_names(ref)
    got, loose = convert(src, "ravelin", "sm4450", 137, up, "2023")
    want = open(ref).read()
    a, b = got.split("\n"), want.split("\n")

    def norm(ls):
        return [re.sub(r"\s+", " ", l).strip() for l in ls if l.strip()]

    diff = [l for l in difflib.unified_diff(a, b, "generated", "upstream",
                                            n=0, lineterm="")]
    raw = len([l for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---")])
    nd = [l for l in difflib.unified_diff(norm(a), norm(b), n=0, lineterm="")
          if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    print("generated %d lines, upstream has %d" % (len(a), len(b)))
    print("differing lines: %d raw, %d ignoring whitespace "
          "(%.2f%% of upstream matches)" % (raw, len(nd), (1 - len(nd) / len(b)) * 100))

    # The line diff is not the real test. What has to be identical is the
    # content: the pin descriptors, the function enum, the pingroup rows, the
    # wakeirq map, and which groups each function can be muxed onto. The order
    # of names inside a function's group list has no effect on behaviour, and
    # upstream's own files are inconsistent about it, so it is compared as a
    # set.
    def pin_descs(t):
        return re.findall(r'PINCTRL_PIN\((\d+), "([^"]+)"\)', t)

    def func_enum(t):
        m = re.search(r"^enum \w+_functions \{\n(.*?)\n\};", t, re.S | re.M)
        return re.findall(r"msm_mux_(\w+),", m.group(1)) if m else []

    def pingroups(t):
        return [l.strip() for l in re.findall(
            r"^\t\[\d+\] = (?:PINGROUP|UFS_RESET|SDC_QDSD_PINGROUP)\([^\n]*$",
            t, re.M)]

    def wakeirqs(t):
        m = re.search(r"pdc_map\[\] = \{\n(.*?)\n\};", t, re.S)
        return re.findall(r"\{\s*(\d+),\s*(\d+)\s*\}", m.group(1)) if m else []

    def func_groups(t):
        return {x.group(1): set(re.findall(r'"([^"]+)"', x.group(2)))
                for x in re.finditer(
                    r"^static const char \* const (\w+)_groups\[\] = \{\n(.*?)\n\};$",
                    t, re.M | re.S)}

    checks = [("pin descriptors", pin_descs(got) == pin_descs(want), len(pin_descs(got))),
              ("function enum", func_enum(got) == func_enum(want), len(func_enum(got))),
              ("pingroup rows", pingroups(got) == pingroups(want), len(pingroups(got))),
              ("wakeirq map", wakeirqs(got) == wakeirqs(want), len(wakeirqs(got))),
              ("function group sets", func_groups(got) == func_groups(want),
               len(func_groups(got)))]
    print()
    failed = False
    for label, ok, n in checks:
        print("    %-22s %-4s  %d entries" % (label, "OK" if ok else "FAIL", n))
        failed = failed or not ok
    if failed:
        print("\n".join(diff))
        return 1
    print("\n==> identical in every respect that reaches the hardware; what is "
          "left\n    is the order and wrapping inside the group lists.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--header", help="downstream pinctrl-<soc>.h")
    ap.add_argument("--soc", help="downstream codename, e.g. parrot")
    ap.add_argument("--target", help="upstream name, e.g. sm6450")
    ap.add_argument("--ngpios", type=int, help="from the downstream .c")
    ap.add_argument("--template",
                    default="out/linux/drivers/pinctrl/qcom/pinctrl-sm4450.c",
                    help="upstream driver to learn the function names from")
    ap.add_argument("--extra-function", action="append", default=[],
                    help="an upstream function name the template does not have")
    ap.add_argument("--year", default="2026")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not (args.header and args.soc and args.target and args.ngpios):
        ap.error("--header, --soc, --target and --ngpios are required")
    tmpl = args.template if os.path.isabs(args.template) \
        else os.path.join(ROOT, args.template)
    text, loose = convert(args.header, args.soc, args.target, args.ngpios,
                          up_function_names(tmpl), args.year,
                          extra=args.extra_function)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
