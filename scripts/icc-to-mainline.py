#!/usr/bin/env python3
"""Generate an upstream RPMh interconnect driver from a downstream one.

Downstream (msm-5.10) and upstream drivers describe the same thing: the
SoC's network-on-chip nodes, each with its width, channels, the nodes it
links to and its QoS registers, and the Bus Clock Managers that RPMh votes
on. This reads either kind of source into that model, so two drivers can be
compared as data instead of as text, and writes the model out the way
upstream's newest drivers are written (milos.c: nodes linked by pointer, no
private ID header, QoS boxes inline, dynamic IDs).

    scripts/icc-to-mainline.py compare waipio.c sm8450.c
        what upstream changed when it took the vendor's SM8450 driver
    scripts/icc-to-mainline.py generate --soc parrot --target sm6450 \\
        --header qcom,parrot.h parrot.c > sm6450.c
    scripts/icc-to-mainline.py roundtrip milos.c
        reads an upstream driver and writes it back, as a test of the writer

`compare` resolves every link to the node it names, so a driver with IDs and
one with pointers compare equal when they describe the same graph.
"""

import argparse
import re
import sys

STRUCT_RE = re.compile(
    r"^static (?:const )?struct (qcom_icc_node|qcom_icc_qosbox|qcom_icc_bcm"
    r"|qcom_icc_desc|regmap_config) (\w+) = \{\n(.*?)^\};", re.S | re.M)
ARRAY_RE = re.compile(
    r"^static (?:const )?(?:struct (qcom_icc_bcm|qcom_icc_node) |(char) |"
    r"const (char) )\*\s*(?:const )?(\w+)\[\] = \{\n?(.*?)^\};", re.S | re.M)
MATCH_RE = re.compile(r"\{\s*\.compatible = \"([\w,-]+)\",\s*\.data = &(\w+)\s*\}")


def split_top(body):
    """Split an initializer body at top-level commas."""
    out, depth, cur = [], 0, []
    for ch in body:
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return [x for x in out if x]


def fields(body):
    """{field: raw value} for a designated initializer."""
    res = {}
    for item in split_top(body):
        m = re.match(r"\.(\w+)\s*=\s*(.*)$", item, re.S)
        if m:
            res[m.group(1)] = m.group(2).strip()
    return res


def brace_list(value):
    """The items of `{ a, b }` or `(type) { a, b }`, without & or quotes."""
    m = re.search(r"\{(.*)\}", value, re.S)
    if not m:
        return []
    return [x.strip().lstrip("&").strip('"') for x in m.group(1).split(",")
            if x.strip()]


def num(value):
    value = value.strip()
    if value in ("true", "false"):
        return value == "true"
    bit = re.fullmatch(r"BIT\((\d+)\)", value)
    return 1 << int(bit.group(1)) if bit else int(value, 0)


class Model:
    """A driver: nodes, BCMs and NoCs, with every link resolved to a name."""

    def __init__(self):
        self.nodes = {}     # C name -> dict
        self.bcms = {}      # C name -> dict
        self.nocs = {}      # desc C name -> dict
        self.order = []     # node C names in definition order
        self.bcm_order = []
        self.matches = []   # (compatible, desc C name)
        self.regmaps = {}   # C name -> fields


def parse(path, header=None):
    src = open(path).read()
    m = Model()
    qos = {}
    ids = {}
    for kind, name, body in STRUCT_RE.findall(src):
        f = fields(body)
        if kind == "qcom_icc_qosbox":
            q = {"num_ports": num(f["num_ports"])}
            offs = f.get("port_offsets") or f.get("offsets")
            q["offsets"] = [int(x, 0) for x in brace_list(offs)]
            cfg = fields(re.search(r"\{(.*)\}", f["config"], re.S).group(1)) \
                if "config" in f else f
            for k in ("prio", "urg_fwd", "prio_fwd_disable"):
                q[k] = num(cfg[k]) if k in cfg else 0
            qos[name] = q
        elif kind == "qcom_icc_node":
            n = {"name": f["name"].strip('"'),
                 "channels": num(f.get("channels", "1")),
                 "buswidth": num(f.get("buswidth", "0")),
                 "id": f.get("id"),
                 "qos": qos.get(f.get("qosbox", "").lstrip("&")),
                 "raw_links": brace_list(f.get("links") or
                                         f.get("link_nodes") or ""),
                 "pointer_links": "link_nodes" in f,
                 "extra": sorted(k for k in f if k not in (
                     "name", "channels", "buswidth", "id", "qosbox",
                     "num_links", "links", "link_nodes", "noc_ops"))}
            m.nodes[name] = n
            m.order.append(name)
            if n["id"]:
                ids[n["id"]] = name
        elif kind == "qcom_icc_bcm":
            b = {"name": f["name"].strip('"'),
                 "nodes": brace_list(f.get("nodes", "")),
                 "keepalive": num(f.get("keepalive", "false")),
                 "enable_mask": num(f["enable_mask"])
                 if "enable_mask" in f else None,
                 "voter_idx": num(f.get("voter_idx", "0")),
                 "extra": {k: f[k] for k in f if k not in (
                     "name", "nodes", "num_nodes", "keepalive",
                     "enable_mask", "voter_idx")}}
            m.bcms[name] = b
            m.bcm_order.append(name)
        elif kind == "regmap_config":
            m.regmaps[name] = f
        elif kind == "qcom_icc_desc":
            m.nocs[name] = {"fields": f}
    arrays = {}
    for k1, k2, k3, name, body in ARRAY_RE.findall(src):
        items = []
        for item in split_top(body):
            im = re.match(r"\[(\w+)\]\s*=\s*&(\w+)$", item)
            if im:
                items.append((im.group(1), im.group(2)))
            else:
                items.append(item.lstrip("&").strip('"'))
        arrays[name] = items
    for name, noc in m.nocs.items():
        f = noc.pop("fields")
        noc["nodes"] = arrays.get(f.get("nodes"), [])
        noc["bcms"] = arrays.get(f.get("bcms"), [])
        noc["voters"] = arrays.get(f.get("voters"), [])
        cfg = f.get("config", "").lstrip("&")
        noc["regmap"] = m.regmaps.get(cfg)
        noc["qos_requires_clocks"] = num(f.get("qos_requires_clocks",
                                               "false"))
        noc["extra"] = sorted(k for k in f if k not in (
            "nodes", "num_nodes", "bcms", "num_bcms", "voters",
            "num_voters", "config", "qos_requires_clocks", "alloc_dyn_id"))
    m.matches = MATCH_RE.findall(src)
    # Links name either nodes (pointer style) or IDs (an ID style driver).
    for n in m.nodes.values():
        if n["pointer_links"]:
            n["links"] = list(n["raw_links"])
        else:
            n["links"] = [ids.get(x, "?" + x) for x in n["raw_links"]]
    return m


def noc_key(compatible):
    """A compatible's NoC part, with the vendor's underscores as dashes."""
    return compatible.split("-", 1)[1].replace("_", "-")


# ---------------------------------------------------------------- compare --

def compare(a, b, out=sys.stdout):
    """Report how b differs from a, as data."""
    p = lambda *x: print(*x, file=out)
    an, bn = set(a.nodes), set(b.nodes)
    p(f"nodes: {len(an)} and {len(bn)}, {len(an & bn)} in both")
    for x in sorted(an - bn):
        p(f"  only in first:  {x}")
    for x in sorted(bn - an):
        p(f"  only in second: {x}")
    diffs = 0
    for x in sorted(an & bn):
        na, nb = a.nodes[x], b.nodes[x]
        d = []
        for k in ("name", "channels", "buswidth"):
            if na[k] != nb[k]:
                d.append(f"{k} {na[k]} -> {nb[k]}")
        if set(na["links"]) != set(nb["links"]):
            d.append(f"links -{sorted(set(na['links']) - set(nb['links']))}"
                     f" +{sorted(set(nb['links']) - set(na['links']))}")
        elif na["links"] != nb["links"]:
            d.append("link order")
        if na["qos"] != nb["qos"]:
            d.append(f"qos {na['qos']} -> {nb['qos']}")
        if d:
            diffs += 1
            p(f"  {x}: " + "; ".join(d))
    p(f"  {diffs} common nodes differ")

    ab = {k: k for k in a.bcms}
    bb = {k: k for k in b.bcms}
    p(f"bcms: {len(ab)} and {len(bb)}")
    for x in sorted(set(ab) - set(bb)):
        p(f"  only in first:  {x}")
    for x in sorted(set(bb) - set(ab)):
        p(f"  only in second: {x}")
    for x in sorted(set(ab) & set(bb)):
        ba, bb_ = a.bcms[ab[x]], b.bcms[bb[x]]
        d = []
        for k in ("keepalive", "enable_mask"):
            if ba[k] != bb_[k]:
                d.append(f"{k} {ba[k]} -> {bb_[k]}")
        if ba["extra"] != bb_["extra"]:
            d.append(f"extra {ba['extra']} -> {bb_['extra']}")
        if set(ba["nodes"]) != set(bb_["nodes"]):
            d.append(f"nodes -{sorted(set(ba['nodes']) - set(bb_['nodes']))}"
                     f" +{sorted(set(bb_['nodes']) - set(ba['nodes']))}")
        elif ba["nodes"] != bb_["nodes"]:
            d.append("node order")
        if d:
            p(f"  {x}: " + "; ".join(d))

    am = {noc_key(c): d for c, d in a.matches}
    bm = {noc_key(c): d for c, d in b.matches}
    p(f"nocs: {sorted(am)}")
    if set(am) != set(bm):
        p(f"  second: {sorted(bm)}")
    for k in sorted(set(am) & set(bm)):
        na, nb = a.nocs[am[k]], b.nocs[bm[k]]
        d = []
        ia = [x for x in na["nodes"] if isinstance(x, tuple)]
        ib = [x for x in nb["nodes"] if isinstance(x, tuple)]
        if ia != ib:
            sa, sb = set(ia), set(ib)
            if sa == sb:
                d.append("node order")
            else:
                d.append(f"nodes -{sorted(sa - sb)} +{sorted(sb - sa)}")
        if na["bcms"] != nb["bcms"]:
            d.append(f"bcms {na['bcms']} -> {nb['bcms']}")
        if bool(na["regmap"]) != bool(nb["regmap"]):
            d.append(f"regmap {bool(na['regmap'])} -> {bool(nb['regmap'])}")
        if na["qos_requires_clocks"] != nb["qos_requires_clocks"]:
            d.append("qos_requires_clocks")
        if na["extra"] != nb["extra"]:
            d.append(f"extra {na['extra']} -> {nb['extra']}")
        if d:
            p(f"  {k}: " + "; ".join(d))


# -------------------------------------------------------------- transform --

# The clocks a NoC's QoS registers sit behind, by the master that needs them,
# as upstream's newest bindings name them (qcom,milos-rpmh.yaml).
QOS_CLOCKS = {
    "xm_usb3_0": [("GCC_AGGRE_USB3_PRIM_AXI_CLK", "gcc",
                   "aggre USB3 PRIM AXI clock")],
    "xm_ufs_mem": [("GCC_AGGRE_UFS_PHY_AXI_CLK", "gcc",
                    "aggre UFS PHY AXI clock")],
    "qxm_ipa": [("RPMH_IPA_CLK", "rpmhcc", "RPMH CC IPA clock")],
    "xm_pcie3_0": [("GCC_AGGRE_NOC_PCIE_0_AXI_CLK", "gcc",
                    "aggre-NOC PCIe AXI clock"),
                   ("GCC_CFG_NOC_PCIE_ANOC_AHB_CLK", "gcc",
                    "cfg-NOC PCIe a-NOC AHB clock")],
}


def to_upstream(m, soc, target, regs):
    """Apply the rules the vendor-to-upstream pairs show, in place.

    regs maps a NoC (as noc_key gives it) to its register window's size.
    """
    disp = {n for n in m.nodes if n.endswith("_disp")}
    disp |= {b for b, v in m.bcms.items() if v["voter_idx"]}
    for n in disp:
        m.nodes.pop(n, None)
        m.bcms.pop(n, None)
    m.order = [n for n in m.order if n not in disp]
    m.bcm_order = [b for b in m.bcm_order if b not in disp]
    for n in m.nodes.values():
        bad = [x for x in n["links"] if x in disp or x.startswith("?")]
        if bad:
            sys.exit(f"icc-to-mainline: {n['name']} links to {bad}")
    for b in m.bcms.values():
        if b["extra"].pop("keepalive_early", None) == "true":
            b["keepalive"] = True
        b["extra"].pop("perf_mode_mask", None)
        b["voter_idx"] = 0
    matches = []
    for c, d in m.matches:
        noc = m.nocs[d]
        noc["nodes"] = [x for x in noc["nodes"]
                        if isinstance(x, tuple) and x[1] not in disp]
        noc["bcms"] = [b for b in noc["bcms"] if b not in disp]
        noc["voters"] = []
        key = noc_key(c)
        noc["reg"] = regs.get(key)
        noc["regmap"] = ({"max_register": hex(noc["reg"][1])}
                         if noc["reg"] else None)
        clocks = []
        for _, n in noc["nodes"]:
            if m.nodes[n]["qos"]:
                clocks += QOS_CLOCKS.get(n, [])
        noc["clocks"] = clocks
        noc["qos_requires_clocks"] = bool(clocks)
        new = f"{target}_{key.replace('-', '_')}"
        m.nocs[new] = m.nocs.pop(d)
        matches.append((f"qcom,{target}-{key}", new))
    m.matches = matches
    m.soc = target
    return m


# ------------------------------------------------------------------ write --

def wrap(items, lead):
    """`{ &a, &b,` then two per line, the way upstream wraps these lists."""
    refs = [f"&{x}" for x in items]
    lines = []
    for i in range(0, len(refs), 2):
        lines.append(", ".join(refs[i:i + 2]))
    return lead + "{ " + (",\n\t\t   ".join(lines)) + " },"


def write_driver(m, style="6.18", copyright=(), description=None):
    soc = m.soc
    o = []
    o.append("// SPDX-License-Identifier: GPL-2.0-only")
    o.append("/*")
    o += [f" * {c}" for c in copyright]
    o.append(" */")
    o.append("")
    o += ["#include <linux/device.h>",
          "#include <linux/interconnect-provider.h>",
          "#include <linux/interconnect.h>",
          "#include <linux/io.h>",
          "#include <linux/module.h>",
          "#include <linux/of_device.h>",
          "#include <linux/of_platform.h>",
          "#include <linux/platform_device.h>",
          f"#include <dt-bindings/interconnect/qcom,{soc}-rpmh.h>",
          "",
          '#include "bcm-voter.h"',
          '#include "icc-common.h"',
          '#include "icc-rpmh.h"',
          ""]
    o += [f"static struct qcom_icc_node {n};" for n in m.order]
    o.append("")
    for name in m.order:
        n = m.nodes[name]
        q = n["qos"]
        if q:
            o.append(f"static struct qcom_icc_qosbox {name}_qos = {{")
            o.append(f"\t.num_ports = {q['num_ports']},")
            offs = ", ".join(f"{x:#x}" for x in q["offsets"])
            o.append(f"\t.port_offsets = {{ {offs} }},")
            o.append(f"\t.prio = {q['prio']},")
            o.append(f"\t.urg_fwd = {q['urg_fwd']},")
            o.append(f"\t.prio_fwd_disable = {int(q['prio_fwd_disable'])},")
            o.append("};")
            o.append("")
        o.append(f"static struct qcom_icc_node {name} = {{")
        o.append(f"\t.name = \"{n['name']}\",")
        o.append(f"\t.channels = {n['channels']},")
        o.append(f"\t.buswidth = {n['buswidth']},")
        if q:
            o.append(f"\t.qosbox = &{name}_qos,")
        o.append(f"\t.num_links = {len(n['links'])},")
        if n["links"]:
            lead = "\t.link_nodes = " + (
                "(struct qcom_icc_node *[]) " if style == "6.18" else "")
            o.append(wrap(n["links"], lead))
        o.append("};")
        o.append("")
    for name in m.bcm_order:
        b = m.bcms[name]
        o.append(f"static struct qcom_icc_bcm {name} = {{")
        o.append(f"\t.name = \"{b['name']}\",")
        if b["enable_mask"] is not None:
            o.append(f"\t.enable_mask = {b['enable_mask']:#x},")
        if b["keepalive"]:
            o.append("\t.keepalive = true,")
        if "vote_scale" in b["extra"]:
            o.append(f"\t.vote_scale = {b['extra']['vote_scale']},")
        o.append(f"\t.num_nodes = {len(b['nodes'])},")
        o.append(wrap(b["nodes"], "\t.nodes = "))
        o.append("};")
        o.append("")
    for compat, d in m.matches:
        noc = m.nocs[d]
        base = noc_key(compat).replace("-", "_")
        if noc["bcms"]:
            o.append(f"static struct qcom_icc_bcm * const {base}_bcms[] = {{")
            o += [f"\t&{b}," for b in noc["bcms"]]
            o.append("};")
            o.append("")
        o.append(f"static struct qcom_icc_node * const {base}_nodes[] = {{")
        o += [f"\t[{i}] = &{n}," for i, n in noc["nodes"]]
        o.append("};")
        o.append("")
        if noc["regmap"]:
            o.append(f"static const struct regmap_config {d}_regmap_config = {{")
            o += ["\t.reg_bits = 32,", "\t.reg_stride = 4,",
                  "\t.val_bits = 32,",
                  f"\t.max_register = {noc['regmap']['max_register']},",
                  "\t.fast_io = true,", "};", ""]
        o.append(f"static const struct qcom_icc_desc {d} = {{")
        if noc["regmap"]:
            o.append(f"\t.config = &{d}_regmap_config,")
        o.append(f"\t.nodes = {base}_nodes,")
        o.append(f"\t.num_nodes = ARRAY_SIZE({base}_nodes),")
        if noc["bcms"]:
            o.append(f"\t.bcms = {base}_bcms,")
            o.append(f"\t.num_bcms = ARRAY_SIZE({base}_bcms),")
        if noc["qos_requires_clocks"]:
            o.append("\t.qos_requires_clocks = true,")
        if style == "6.18":
            o.append("\t.alloc_dyn_id = true,")
        o.append("};")
        o.append("")
    o.append("static const struct of_device_id qnoc_of_match[] = {")
    o += [f"\t{{ .compatible = \"{c}\", .data = &{d} }}," for c, d in m.matches]
    o += ["\t{ }", "};", "MODULE_DEVICE_TABLE(of, qnoc_of_match);", ""]
    o += ["static struct platform_driver qnoc_driver = {",
          "\t.probe = qcom_icc_rpmh_probe,",
          "\t.remove = qcom_icc_rpmh_remove,",
          "\t.driver = {",
          f"\t\t.name = \"qnoc-{soc}\",",
          "\t\t.of_match_table = qnoc_of_match,",
          "\t\t.sync_state = icc_sync_state,",
          "\t},", "};", "",
          "static int __init qnoc_driver_init(void)", "{",
          "\treturn platform_driver_register(&qnoc_driver);", "}",
          "core_initcall(qnoc_driver_init);", "",
          "static void __exit qnoc_driver_exit(void)", "{",
          "\tplatform_driver_unregister(&qnoc_driver);", "}",
          "module_exit(qnoc_driver_exit);", "",
          f"MODULE_DESCRIPTION(\"{description or soc.upper()} NoC driver\");",
          "MODULE_LICENSE(\"GPL\");"]
    return "\n".join(o) + "\n"


def write_header(m, copyright=()):
    guard = f"__DT_BINDINGS_INTERCONNECT_QCOM_{m.soc.upper()}_H"
    o = ["/* SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause) */",
         "/*"] + [f" * {c}" for c in copyright] + [" */", "",
                                                     f"#ifndef {guard}",
                                                     f"#define {guard}", ""]
    for _, d in m.matches:
        for i, (bid, _) in enumerate(m.nocs[d]["nodes"]):
            s = f"#define {bid}"
            o.append(s + "\t" * max(1, (48 - len(s) + 7) // 8) + str(i))
        o.append("")
    o.append("#endif")
    return "\n".join(o) + "\n"


def write_binding(m, maintainer, gcc_header):
    """The binding YAML, in qcom,milos-rpmh.yaml's shape."""
    soc = m.soc
    compats = [c for c, _ in m.matches]
    noreg = [c for c, d in m.matches if not m.nocs[d]["regmap"]]
    clocked = [(c, m.nocs[d]["clocks"]) for c, d in m.matches
               if m.nocs[d]["clocks"]]
    most = max((len(x) for _, x in clocked), default=0)
    o = ["# SPDX-License-Identifier: (GPL-2.0 OR BSD-2-Clause)",
         "%YAML 1.2", "---",
         f"$id: http://devicetree.org/schemas/interconnect/qcom,{soc}-rpmh.yaml#",
         "$schema: http://devicetree.org/meta-schemas/core.yaml#", "",
         "title: Qualcomm RPMh Network-On-Chip Interconnect on "
         f"{soc.upper()}", "",
         "maintainers:", f"  - {maintainer}", "",
         "description: |",
         "  RPMh interconnect providers support system bandwidth requirements through",
         "  RPMh hardware accelerators known as Bus Clock Manager (BCM). The provider is",
         "  able to communicate with the BCM through the Resource State Coordinator (RSC)",
         "  associated with each execution environment. Provider nodes must point to at",
         "  least one RPMh device child node pertaining to their RSC and each provider",
         "  can map to multiple RPMh resources.", "",
         f"  See also: include/dt-bindings/interconnect/qcom,{soc}-rpmh.h", "",
         "properties:", "  compatible:", "    enum:"]
    o += [f"      - {c}" for c in compats]
    o += ["", "  reg:", "    maxItems: 1", ""]
    if clocked:
        o += ["  clocks:", "    minItems: 1", f"    maxItems: {most}", ""]
    o += ["required:", "  - compatible", "", "allOf:",
          "  - $ref: qcom,rpmh-common.yaml#",
          "  - if:", "      properties:", "        compatible:",
          "          contains:", "            enum:"]
    o += [f"              - {c}" for c in noreg]
    o += ["    then:", "      properties:", "        reg: false",
          "    else:", "      required:", "        - reg", ""]
    for c, clks in clocked:
        o += ["  - if:", "      properties:", "        compatible:",
              "          contains:", "            enum:",
              f"              - {c}", "    then:", "      properties:",
              "        clocks:", "          items:"]
        o += [f"            - description: {desc}" for _, _, desc in clks]
        o.append("")
    if clocked:
        o += ["  - if:", "      properties:", "        compatible:",
              "          contains:", "            enum:"]
        o += [f"              - {c}" for c, _ in clocked]
        o += ["    then:", "      required:", "        - clocks",
              "    else:", "      properties:", "        clocks: false", ""]
    o += ["unevaluatedProperties: false", "", "examples:", "  - |"]
    virt = next(c for c in noreg)
    ex = clocked[0] if clocked else None
    if ex:
        o.append(f"    #include <dt-bindings/clock/{gcc_header}>")
        o.append("")
    o += ["    interconnect-0 {", f"        compatible = \"{virt}\";",
          "        #interconnect-cells = <2>;",
          "        qcom,bcm-voters = <&apps_bcm_voter>;", "    };"]
    if ex:
        c, clks = ex
        d = dict(m.matches)[c]
        reg = m.nocs[d]["reg"]
        o += ["", f"    interconnect@{reg[0]:x} {{",
              f"        compatible = \"{c}\";",
              f"        reg = <{reg[0]:#010x} {reg[1]:#x}>;",
              "        #interconnect-cells = <2>;"]
        refs = [f"<&{prov} {name}>" for name, prov, _ in clks]
        o.append("        clocks = " + (",\n                 ".join(refs)) + ";")
        o += ["        qcom,bcm-voters = <&apps_bcm_voter>;", "    };"]
    return "\n".join(o) + "\n"


def copyright_of(path):
    src = open(path).read()
    return re.findall(r"^ \* (Copyright .*?)\s*$", src, re.M)


def similarity(a, b):
    import difflib
    sm = difflib.SequenceMatcher(None, a.splitlines(), b.splitlines(),
                                 autojunk=False)
    return sm.ratio(), sm


def report(name, ours, theirs, show):
    ratio, sm = similarity(ours, theirs)
    diff = [x for x in __import__("difflib").unified_diff(
        theirs.splitlines(), ours.splitlines(), "upstream", "generated",
        lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    print(f"{name}: {ratio:.2%} of lines in common, {len(diff)} differ")
    if show:
        print("\n".join(diff))


def dts_regs(path, soc):
    """{noc: register window size} from a device tree source."""
    text = open(path).read()
    regs = {}
    for m in re.finditer(r'compatible = "qcom,%s-([\w-]+)";\s*\n\s*reg = '
                         r'<(0x[0-9a-f]+) (0x[0-9a-f]+)>' % re.escape(soc),
                         text):
        regs[m.group(1).replace("_", "-")] = (int(m.group(2), 16),
                                              int(m.group(3), 16))
    return regs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("first")
    c.add_argument("second")
    r = sub.add_parser("roundtrip")
    r.add_argument("driver")
    r.add_argument("--header")
    r.add_argument("--style", choices=("6.18", "mainline"), default="6.18")
    r.add_argument("--show", action="store_true")
    g = sub.add_parser("generate")
    g.add_argument("driver")
    g.add_argument("--soc", required=True)
    g.add_argument("--target", required=True)
    g.add_argument("--dts", required=True,
                   help="the stock device tree, for the NoCs' register sizes")
    g.add_argument("--style", choices=("6.18", "mainline"), default="6.18")
    g.add_argument("--header", help="also write the binding header here")
    g.add_argument("--binding", help="also write the binding YAML here")
    g.add_argument("--maintainer", default="Bruno Gregório <accounts@bruno.pw>")
    args = ap.parse_args()
    if args.cmd == "compare":
        compare(parse(args.first), parse(args.second))
    elif args.cmd == "roundtrip":
        m = parse(args.driver)
        m.soc = m.matches[0][0].split(",")[1].split("-")[0]
        cr = copyright_of(args.driver)
        src = open(args.driver).read()
        desc = re.search(r'MODULE_DESCRIPTION\("(.*) NoC driver"\)', src)
        report(args.driver, write_driver(m, args.style, cr, desc.group(1)),
               src, args.show)
        if args.header:
            report(args.header, write_header(m, copyright_of(args.header)),
                   open(args.header).read(), args.show)
    elif args.cmd == "generate":
        m = to_upstream(parse(args.driver), args.soc, args.target,
                        dts_regs(args.dts, args.soc))
        cr = copyright_of(args.driver)
        sys.stdout.write(write_driver(m, args.style, cr))
        if args.header:
            with open(args.header, "w") as f:
                f.write(write_header(m, cr))
        if args.binding:
            with open(args.binding, "w") as f:
                f.write(write_binding(m, args.maintainer,
                                      f"qcom,{args.target}-gcc.h"))


if __name__ == "__main__":
    main()
