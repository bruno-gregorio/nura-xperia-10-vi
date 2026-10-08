#!/usr/bin/env python3
"""Derive an upstream DPU catalog from a sibling's, by the downstream SDE trees.

Upstream drm/msm describes each display controller in a catalog header
(drivers/gpu/drm/msm/disp/dpu1/catalog/dpu_X_Y_soc.h), written by hand from
Qualcomm's downstream SDE device tree. Downstream, the SDE node lists every
hardware block by address - pipes, mixers, ping-pongs, interfaces - with
the few properties that tell one SoC of a family from another. So a SoC
whose downstream tree we have, and whose family already has an upstream
catalog, can take the family's entries by address:

    scripts/sde-to-dpu.py prove waipio-sde-common.dtsi+waipio-sde.dtsi \\
        dpu_8_1_sm8450.h
        how a sibling's downstream tree maps onto its upstream catalog,
        field by field: the evidence that the rules below hold
    scripts/sde-to-dpu.py transplant --soc sm6450 --version 8.3 \\
        live.dts dpu_8_1_sm8450.h > dpu_8_3_sm6450.h
        keeps the sibling's entries for the blocks this tree has, and
        rewrites the fields the tree decides

Downstream offsets count from the MDSS base and upstream's from the MDP
block, `qcom,sde-off` further on. An offset of 0 or 0x0f0f is a block that
is not there (0x0f0f marks a virtual mixer and its ping-pong). Blocks are
matched on address, never on their position in a list: downstream numbers
blocks by position, so a list with a gap renames everything after it.
"""

import argparse
import re
import sys

ABSENT = (0, 0xf0f)


# --------------------------------------------------------------- the tree --

def node_bodies(text):
    """Text inside each node that is the SDE node: its definition, and any
    `&mdss_mdp` that adds to it."""
    out = []
    for m in re.finditer(r"^\s*(?:[\w-]+:\s*)?(?:[\w,.-]*mdss_mdp(?:@[0-9a-f]+)?"
                         r"|&mdss_mdp)\s*\{", text, re.M):
        depth, i = 1, m.end()
        while depth:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        out.append(text[m.end():i - 1])
    return out


def top_level(body):
    """The node's own statements, without its children's."""
    out, depth, cur = [], 0, []
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.S)
    for c in body:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                cur = []
                continue
        if depth:
            continue
        if c == ";":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    return [s for s in out if s]


def unescape(s):
    return bytes(s, "latin-1").decode("unicode_escape").encode("latin-1")


def parse_props(paths):
    """The SDE node's own properties, from one or more files in order, later
    files overriding earlier ones as dtc would."""
    stmts = []
    for path in paths:
        for body in node_bodies(open(path).read()):
            stmts += top_level(body)
    if not stmts:
        sys.exit(f"sde-to-dpu: no SDE node in {', '.join(paths)}")
    props = {}
    for st in stmts:
        m = re.match(r"([\w,#.-]+)\s*=\s*(.*)$", st, re.S)
        if not m:
            props[st] = True
            continue
        key, val = m.groups()
        cells = []
        for grp in re.findall(r"<([^>]*)>", val):
            for tok in grp.split():
                try:
                    cells.append(int(tok, 0))
                except ValueError:
                    cells.append(tok)
        strings = re.findall(r'"((?:[^"\\]|\\.)*)"', val)
        if cells:
            props[key] = cells
        elif strings:
            props[key] = strings
    return props


def cells(props, key, default=None):
    """A property as numbers; dtc prints some u32 lists as strings."""
    v = props.get(key, default)
    if v is None or v is True:
        return default
    if v and all(isinstance(x, str) for x in v):
        raw = b"".join(unescape(s) + b"\0" for s in v)
        if len(raw) % 4 == 0 and key not in STRING_PROPS:
            return [int.from_bytes(raw[i:i + 4], "big")
                    for i in range(0, len(raw), 4)]
    return v


STRING_PROPS = {"qcom,sde-sspp-type", "qcom,sde-intf-type",
                "qcom,sde-mixer-display-pref", "qcom,sde-mixer-dcwb-pref",
                "qcom,sde-ctl-display-pref"}


def pairs(seq):
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq) - 1, 2)]


class Tree:
    """The blocks a downstream SDE node describes, at upstream offsets."""

    def __init__(self, spec):
        p = self.props = parse_props(spec.split("+"))
        self.dp_controllers = sum(open(f).read().count('"qcom,dp-display"')
                                  for f in spec.split("+"))
        off = cells(p, "qcom,sde-off", [0x1000])[0]

        def at(key):
            return [None if x in ABSENT else x - off
                    for x in cells(p, key, [])]

        def idx(key, i, default=None):
            v = cells(p, key, [])
            return v[i] if i < len(v) else default

        self.ctl = [b for b in at("qcom,sde-ctl-off") if b is not None]
        types = p.get("qcom,sde-sspp-type", [])
        clk = pairs(cells(p, "qcom,sde-sspp-clk-ctrl", []))
        self.sspp = {}
        for i, b in enumerate(at("qcom,sde-sspp-off")):
            if b is not None:
                self.sspp[b] = {"type": types[i],
                                "xin": idx("qcom,sde-sspp-xin-id", i),
                                "clk": clk[i] if i < len(clk) else None}
        self.lm_by_index = at("qcom,sde-mixer-off")
        self.lm = {}
        for i, b in enumerate(self.lm_by_index):
            if b is not None:
                pm = idx("qcom,sde-mixer-pair-mask", i, 0)
                self.lm[b] = {"index": i, "pair": pm - 1 if pm else None}
        self.dspp = [b for b in at("qcom,sde-dspp-off") if b is not None]
        m3d = at("qcom,sde-merge-3d-off")
        self.merge_3d = [b for b in m3d if b is not None]
        self.pp = {}
        for i, b in enumerate(at("qcom,sde-pp-off")):
            if b is None:
                continue
            mi = idx("qcom,sde-pp-merge-3d-id", i)
            self.pp[b] = {"index": i,
                          "merge_3d": m3d[mi] if mi is not None
                          and mi < len(m3d) else None}
        enc = cells(p, "qcom,sde-dsc-enc", [])
        n422 = cells(p, "qcom,sde-dsc-native422-supp", [])
        self.dsc = {}
        for i, b in enumerate(at("qcom,sde-dsc-off")):
            if b is not None:
                self.dsc[(b, enc[i] if i < len(enc) else enc[0])] = {
                    "native422": bool(n422[i] if i < len(n422) else 0)}
        self.wb = {}
        for i, b in enumerate(at("qcom,sde-wb-off")):
            if b is not None:
                self.wb[b] = {"id": idx("qcom,sde-wb-id", i),
                              "xin": idx("qcom,sde-wb-xin-id", i),
                              "clk": tuple(cells(p, "qcom,sde-wb-clk-ctrl"))}
        itypes = p.get("qcom,sde-intf-type", [])
        tear = cells(p, "qcom,sde-intf-tear-irq-off", [])
        self.intf, counts = {}, {}
        for i, b in enumerate(at("qcom,sde-intf-off")):
            if b is None:
                continue
            t = itypes[i]
            self.intf[b] = {"index": i, "type": t,
                            "controller": counts.get(t, 0),
                            "tear": bool(tear[i]) if i < len(tear) else False}
            counts[t] = counts.get(t, 0) + 1
        self.cdm = [b for b in at("qcom,sde-cdm-off") if b is not None]

        def first(key, pick=min):
            v = cells(p, key, [])
            if len(v) >= 2 and len(v) % 2 == 0 and key.startswith(
                    "qcom,sde-max-bw"):
                return pick(val for _, val in pairs(v))
            return v[0] if v else None

        # A tree for an SoC that takes more than one kind of DRAM gives
        # the bandwidth per kind; the catalog is the SoC's, so it gets the
        # lower of each.
        self.perf = {"max_bw_low": first("qcom,sde-max-bw-low-kbps"),
                     "max_bw_high": first("qcom,sde-max-bw-high-kbps"),
                     "min_core_ib": first("qcom,sde-min-core-ib-kbps"),
                     "min_llcc_ib": first("qcom,sde-min-llcc-ib-kbps"),
                     "min_dram_ib": first("qcom,sde-min-dram-ib-kbps")}
        lw = [x for x in (first("qcom,sde-sspp-linewidth"),
                          first("qcom,sde-vig-sspp-linewidth")) if x]
        self.caps = {"max_mixer_blendstages":
                     first("qcom,sde-mixer-blendstages"),
                     "max_linewidth": min(lw) if lw else None,
                     "has_src_split": "qcom,sde-has-src-split" in p,
                     "has_dim_layer": "qcom,sde-has-dim-layer" in p,
                     "has_idle_pc": "qcom,sde-has-idle-pc" in p,
                     "has_3d_merge": bool(self.merge_3d)}
        self.mdp_len = first("qcom,sde-len")
        rd = cells(p, "qcom,sde-reg-dma-clk-ctrl")
        self.reg_dma_clk = tuple(rd) if rd else None


# ------------------------------------------------------------ the catalog --

def split_top(body):
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
    res = {}
    for item in split_top(body):
        m = re.match(r"\.(\w+)\s*=\s*(.*)$", item, re.S)
        if m:
            res[m.group(1)] = m.group(2).strip()
    return res


def num(v):
    try:
        return int(v, 0)
    except (TypeError, ValueError):
        return None


class Catalog:
    """An upstream catalog header: its arrays, entry by entry, as text."""

    ARRAY_RE = re.compile(r"^static const struct dpu_(\w+)_cfg (\w+)\[\] = "
                          r"\{\n(.*?)^\};\n", re.S | re.M)
    STRUCT_RE = re.compile(r"^(static )?const struct dpu_(\w+) (\w+) = "
                           r"\{\n(.*?)^\};\n", re.S | re.M)

    def __init__(self, path):
        self.text = open(path).read()
        self.arrays = {}
        for m in self.ARRAY_RE.finditer(self.text):
            entries = re.split(r"\n\t\}, \{\n", m.group(3).strip()
                               .removeprefix("{\n").removesuffix("},"))
            ents = []
            for e in entries:
                e = re.sub(r"\n\t\}$", "", e.strip("\n")).rstrip()
                ents.append({"text": e, "f": fields(e)})
            self.arrays[m.group(1)] = (m.group(2), ents)
        self.structs = {}
        for m in self.STRUCT_RE.finditer(self.text):
            self.structs[m.group(2)] = (m.group(3), m.group(4))
        mdp = self.structs.get("mdp_cfg", ("", ""))[1]
        self.clk_ctrls = {k: (int(r, 0), int(b, 0)) for k, r, b in re.findall(
            r"\[DPU_CLK_CTRL_(\w+)\] = \{ \.reg_off = (\w+), \.bit_off = (\w+) \}",
            mdp)}

    def entries(self, kind):
        return self.arrays.get(kind, ("", []))[1]

    def by_base(self, kind):
        out = {}
        for e in self.entries(kind):
            b = num(e["f"].get("base"))
            if kind == "dsc":
                enc = re.search(r"dsc_sblk_(\d)", e["f"].get("sblk", ""))
                b = (b, 0x100 * (int(enc.group(1)) + 1) if enc else None)
            out[b] = e
        return out

    def perf(self):
        body = self.structs.get("perf_cfg", ("", ""))[1]
        return {k: num(v) for k, v in fields(body).items() if num(v) is not None}

    def caps(self):
        body = self.structs.get("caps", ("", ""))[1]
        f = fields(body)
        out = {}
        for k, v in f.items():
            out[k] = True if v == "true" else num(v) if num(v) is not None else v
        return out


# ------------------------------------------------------------------ prove --

def expect(tree, cat):
    """(kind, base, field, from the tree, in the catalog) for every rule."""
    rows = []
    lm_base = {i: b for i, b in enumerate(tree.lm_by_index)}
    m3d_ids = {num(e["f"]["base"]): e["f"]["id"] for e in cat.entries("merge_3d")}
    dspp_ids = {num(e["f"]["base"]): e["f"]["id"] for e in cat.entries("dspp")}

    ctl = cat.by_base("ctl")
    for b in tree.ctl:
        rows.append(("ctl", b, "present", True, b in ctl))
    sspp = cat.by_base("sspp")
    for b, s in tree.sspp.items():
        e = sspp.get(b)
        rows.append(("sspp", b, "present", True, e is not None))
        if not e:
            continue
        f = e["f"]
        rows.append(("sspp", b, "xin_id", s["xin"], num(f.get("xin_id"))))
        rows.append(("sspp", b, "type", "SSPP_TYPE_" + s["type"].upper(),
                     f.get("type")))
        ck = f.get("clk_ctrl", "").removeprefix("DPU_CLK_CTRL_")
        rows.append(("sspp", b, "clk_ctrl", tuple(s["clk"]) if s["clk"] else None,
                     cat.clk_ctrls.get(ck)))
    lm = cat.by_base("lm")
    for b, l in tree.lm.items():
        e = lm.get(b)
        rows.append(("lm", b, "present", True, e is not None))
        if not e:
            continue
        f, i = e["f"], l["index"]
        pair = lm_base.get(l["pair"]) if l["pair"] is not None else None
        rows.append(("lm", b, "lm_pair",
                     lm[pair]["f"]["id"] if pair in lm else None,
                     f.get("lm_pair")))
        rows.append(("lm", b, "pingpong", f"PINGPONG_{i}", f.get("pingpong")))
        dspp = f"DSPP_{i}" if any(dspp_ids.get(d) == f"DSPP_{i}"
                                  for d in tree.dspp) else None
        rows.append(("lm", b, "dspp", dspp, f.get("dspp")))
    dspp = cat.by_base("dspp")
    for b in tree.dspp:
        rows.append(("dspp", b, "present", True, b in dspp))
    pp = cat.by_base("pingpong")
    for b, p in tree.pp.items():
        e = pp.get(b)
        rows.append(("pingpong", b, "present", True, e is not None))
        if not e:
            continue
        m = m3d_ids.get(p["merge_3d"]) if p["merge_3d"] is not None else None
        got = e["f"].get("merge_3d")
        rows.append(("pingpong", b, "merge_3d", m or "0",
                     None if got is None else got))
    m3 = cat.by_base("merge_3d")
    for b in tree.merge_3d:
        rows.append(("merge_3d", b, "present", True, b in m3))
    dsc = cat.by_base("dsc")
    for k, d in tree.dsc.items():
        e = dsc.get(k)
        rows.append(("dsc", k, "present", True, e is not None))
        if e:
            rows.append(("dsc", k, "native 4:2:x", d["native422"],
                         "DPU_DSC_NATIVE_42x_EN" in e["f"].get("features", "")))
    wb = cat.by_base("wb")
    for b, w in tree.wb.items():
        e = wb.get(b)
        rows.append(("wb", b, "present", True, e is not None))
        if not e:
            continue
        rows.append(("wb", b, "id", f"WB_{w['id']}", e["f"].get("id")))
        rows.append(("wb", b, "xin_id", w["xin"], num(e["f"].get("xin_id"))))
        ck = e["f"].get("clk_ctrl", "").removeprefix("DPU_CLK_CTRL_")
        rows.append(("wb", b, "clk_ctrl", w["clk"], cat.clk_ctrls.get(ck)))
    intf = cat.by_base("intf")
    for b, t in tree.intf.items():
        e = intf.get(b)
        rows.append(("intf", b, "present", True, e is not None))
        if not e:
            continue
        f = e["f"]
        kind = {"dsi": "DSI", "dp": "DP", "hdmi": "HDMI"}.get(t["type"], "NONE")
        rows.append(("intf", b, "type", f"INTF_{kind}", f.get("type")))
        rows.append(("intf", b, "controller_id",
                     f"MSM_{kind}_CONTROLLER_{t['controller']}",
                     f.get("controller_id")))
        rows.append(("intf", b, "tear irq", t["tear"],
                     "intr_tear_rd_ptr" in f))
        rows.append(("intf", b, "id by position", f"INTF_{t['index']}",
                     f.get("id")))
    for k, v in tree.perf.items():
        rows.append(("perf", "", k, v, cat.perf().get(k)))
    caps = cat.caps()
    for k, v in tree.caps.items():
        rows.append(("caps", "", k, v, caps.get(k, False)))
    return rows


def fmt_base(b):
    if isinstance(b, tuple):
        return f"{b[0]:#x}+{b[1]:#x}"
    return f"{b:#x}" if isinstance(b, int) else str(b)


def prove(args):
    tree, cat = Tree(args.tree), Catalog(args.catalog)
    rows = expect(tree, cat)
    agree = [r for r in rows if r[3] == r[4]]
    print(f"{len(agree)} of {len(rows)} fields agree")
    for kind, b, field, mine, theirs in rows:
        if mine != theirs:
            print(f"  {kind} {fmt_base(b)} {field}: tree {mine}, catalog {theirs}")
    have = {k: set(cat.by_base(k)) for k in
            ("ctl", "sspp", "lm", "dspp", "pingpong", "merge_3d", "dsc", "wb",
             "intf")}
    mine = {"ctl": set(tree.ctl), "sspp": set(tree.sspp), "lm": set(tree.lm),
            "dspp": set(tree.dspp), "pingpong": set(tree.pp),
            "merge_3d": set(tree.merge_3d), "dsc": set(tree.dsc),
            "wb": set(tree.wb), "intf": set(tree.intf)}
    for k in have:
        extra = have[k] - mine[k]
        if extra:
            print(f"  {k}: in the catalog only: "
                  + ", ".join(fmt_base(x) for x in sorted(extra, key=str)))


# ------------------------------------------------------------- transplant --

def set_field(text, field, value):
    """Set, add (after the last field it follows) or drop one field."""
    pat = re.compile(r"^(\t\t)\.%s = [^\n]*,\n" % field, re.M)
    if value is None:
        return pat.sub("", text + "\n").rstrip("\n")
    if pat.search(text + "\n"):
        return pat.sub(lambda m: f"{m.group(1)}.{field} = {value},\n",
                       text + "\n").rstrip("\n")
    order = ["features", "sblk", "lm_pair", "pingpong", "dspp"]
    lines = text.split("\n")
    pos = None
    for i, ln in enumerate(lines):
        m = re.match(r"\t\t\.(\w+) =", ln)
        if m and m.group(1) in order and order.index(m.group(1)) < order.index(field):
            pos = i + 1
    if pos is None:
        # Nothing it follows: straight after the address, as upstream has it.
        pos = next((i + 1 for i, ln in enumerate(lines) if "\t.base = " in ln),
                   len(lines))
    lines.insert(pos, f"\t\t.{field} = {value},")
    return "\n".join(lines)


def transplant(args):
    tree, cat = Tree(args.tree), Catalog(args.catalog)
    sib = re.match(r"dpu_\d+_\d+_(\w+)\.h", args.catalog.split("/")[-1]).group(1)
    soc = args.soc
    major, minor = args.version.split(".")
    notes = []
    m3d_ids = {num(e["f"]["base"]): e["f"]["id"] for e in cat.entries("merge_3d")}
    lm_cat = cat.by_base("lm")
    lm_base = {i: b for i, b in enumerate(tree.lm_by_index)}

    def pick(kind, keys):
        """The sibling's entries for these blocks, in the sibling's order."""
        got = cat.by_base(kind)
        for k in keys:
            if k not in got:
                notes.append(f"{kind} at {fmt_base(k)}: {sib} has no such block")
        return [(k, dict(e)) for k, e in got.items() if k in keys]

    blocks = {}
    blocks["ctl"] = pick("ctl", tree.ctl)
    blocks["sspp"] = pick("sspp", tree.sspp)
    lms = []
    dspp_cat = {num(e["f"]["base"]): e["f"]["id"] for e in cat.entries("dspp")}
    have_dspp = {dspp_cat.get(b) for b in tree.dspp}
    for b, e in pick("lm", tree.lm):
        l = tree.lm[b]
        t = e["text"]
        pair = lm_base.get(l["pair"]) if l["pair"] is not None else None
        t = set_field(t, "lm_pair", lm_cat[pair]["f"]["id"] if pair in lm_cat
                      else None)
        d = e["f"].get("dspp")
        if d and d not in have_dspp:
            t = set_field(t, "dspp", None)
        e["text"] = t
        lms.append((b, e))
    blocks["lm"] = lms
    blocks["dspp"] = pick("dspp", tree.dspp)
    pps = []
    for b, e in pick("pingpong", tree.pp):
        m = tree.pp[b]["merge_3d"]
        e["text"] = set_field(e["text"], "merge_3d",
                              m3d_ids.get(m, "0") if m is not None else "0")
        pps.append((b, e))
    blocks["pingpong"] = pps
    blocks["merge_3d"] = pick("merge_3d", tree.merge_3d)
    dscs = []
    for k, e in pick("dsc", tree.dsc):
        e["text"] = set_field(e["text"], "features",
                              "BIT(DPU_DSC_NATIVE_42x_EN)"
                              if tree.dsc[k]["native422"] else None)
        dscs.append((k, e))
    blocks["dsc"] = dscs
    blocks["wb"] = pick("wb", tree.wb)
    intfs = []
    for b, e in pick("intf", tree.intf):
        t = tree.intf[b]
        kind = {"dsi": "DSI", "dp": "DP", "hdmi": "HDMI"}.get(t["type"], "NONE")
        e["text"] = set_field(e["text"], "type", f"INTF_{kind}")
        ctrl = t["controller"]
        # Downstream counts DP interfaces, upstream DP controllers: a DP
        # interface past the last controller is another controller's second
        # MST stream, which mainline writes as that controller's, with a
        # note (msm-next 469df8c2b571, 2026-04-01).
        n = tree.dp_controllers
        if kind == "DP" and n and ctrl >= n:
            first = next(x for x in sorted(tree.intf)
                         if tree.intf[x]["type"] == "dp"
                         and tree.intf[x]["controller"] == ctrl % n)
            pair = cat.by_base("intf")[first]["f"]["name"].strip('"')
            ctrl %= n
            e["text"] = set_field(e["text"], "controller_id",
                                  f"MSM_{kind}_CONTROLLER_{ctrl}")
            e["text"] = e["text"].replace(
                f".controller_id = MSM_{kind}_CONTROLLER_{ctrl},",
                f".controller_id = MSM_{kind}_CONTROLLER_{ctrl},"
                f"\t/* pair with {pair} for DP MST */")
        else:
            e["text"] = set_field(e["text"], "controller_id",
                                  f"MSM_{kind}_CONTROLLER_{ctrl}")
        if e["f"].get("id") != f"INTF_{t['index']}":
            notes.append(f"intf at {b:#x} is {e['f'].get('id')} by address,"
                         f" INTF_{t['index']} by its place in the tree")
        if not t["tear"]:
            e["text"] = set_field(e["text"], "intr_tear_rd_ptr", None)
        intfs.append((b, e))
    blocks["intf"] = intfs

    # The MDP's clock controls, for the pipes and engines that remain.
    used = {e["f"].get("clk_ctrl", "").removeprefix("DPU_CLK_CTRL_")
            for k in ("sspp", "wb") for _, e in blocks[k]}
    if tree.reg_dma_clk:
        used.add("REG_DMA")
    for k in ("sspp", "wb"):
        src = tree.sspp if k == "sspp" else tree.wb
        for b, e in blocks[k]:
            ck = e["f"].get("clk_ctrl", "").removeprefix("DPU_CLK_CTRL_")
            if tuple(src[b]["clk"] or ()) != cat.clk_ctrls.get(ck):
                notes.append(f"{k} at {b:#x}: clock control {src[b]['clk']}"
                             f" here, {cat.clk_ctrls.get(ck)} in {sib}")

    def ren(s):
        return s.replace(f"{sib}_", f"{soc}_")

    o = []
    hdr = cat.text[:cat.text.index("#ifndef")]
    o.append(hdr.rstrip("\n"))
    guard = f"_DPU_{major}_{minor}_{soc.upper()}_H"
    o += ["", f"#ifndef {guard}", f"#define {guard}", ""]

    name, body = cat.structs["caps"]
    caps = tree.caps
    lines = []
    for ln in body.rstrip("\n").split("\n"):
        m = re.match(r"\t\.(\w+) = (.*),$", ln)
        if m and m.group(1) in caps:
            v = caps[m.group(1)]
            if v is False:
                continue
            if v is True:
                lines.append(f"\t.{m.group(1)} = true,")
            elif m.group(1) == "max_mixer_blendstages":
                lines.append(f"\t.{m.group(1)} = {v:#x},")
            else:
                lines.append(f"\t.{m.group(1)} = {v},")
        else:
            lines.append(ln)
    o += [f"static const struct dpu_caps {ren(name)} = {{"] + lines + ["};", ""]

    name, body = cat.structs["mdp_cfg"]
    lines = []
    for ln in body.rstrip("\n").split("\n"):
        m = re.match(r"\t\t\[DPU_CLK_CTRL_(\w+)\]", ln)
        if m and m.group(1) not in used:
            continue
        if re.match(r"\t\.base = 0x0, \.len = ", ln) and tree.mdp_len:
            ln = f"\t.base = 0x0, .len = {tree.mdp_len:#x},"
        lines.append(ln)
    o += [f"static const struct dpu_mdp_cfg {ren(name)} = {{"] + lines + ["};", ""]

    order = ["ctl", "sspp", "lm", "dspp", "pingpong", "merge_3d", "dsc", "wb",
             "intf"]
    present = {}
    for kind in order:
        if not blocks[kind]:
            continue
        arr = cat.arrays[kind][0]
        present[kind] = ren(arr)
        if kind == "dsc":
            o += ["/*", " * NOTE: Each display compression engine (DCE) contains"
                  " dual hard", " * slice DSC encoders so both share same base"
                  " address but with", " * its own different sub block address.",
                  " */"]
        o.append(f"static const struct dpu_{kind}_cfg {ren(arr)}[] = {{")
        o.append("\t{")
        o.append("\n\t}, {\n".join(e["text"] for _, e in blocks[kind]))
        o += ["\t},", "};", ""]

    name, body = cat.structs["perf_cfg"]
    lines = []
    for ln in body.rstrip("\n").split("\n"):
        m = re.match(r"\t\.(\w+) = (\w+),$", ln)
        if m and m.group(1) in tree.perf and tree.perf[m.group(1)] is not None:
            ln = f"\t.{m.group(1)} = {tree.perf[m.group(1)]},"
        lines.append(ln)
    o += [f"static const struct dpu_perf_cfg {ren(name)} = {{"] + lines + ["};", ""]

    o += [f"static const struct dpu_mdss_version {soc}_mdss_ver = {{",
          f"\t.core_major_ver = {major},", f"\t.core_minor_ver = {minor},",
          "};", ""]

    name, body = cat.structs["mdss_cfg"]
    lines = []
    keymap = {"ctl": "ctl", "sspp": "sspp", "mixer": "lm", "dspp": "dspp",
              "pingpong": "pingpong", "dsc": "dsc", "merge_3d": "merge_3d",
              "wb": "wb", "intf": "intf"}
    for ln in body.rstrip("\n").split("\n"):
        m = re.match(r"\t\.(\w+?)(_count)? = ", ln)
        if m and m.group(1) in keymap and keymap[m.group(1)] not in present:
            continue
        if m and m.group(1) == "cdm":
            cdm = re.search(r"&(\w+)", ln).group(1)
            if not tree.cdm:
                continue
        lines.append(ren(ln).replace(f"{sib}_mdss_ver", f"{soc}_mdss_ver"))
    o += [f"const struct dpu_mdss_cfg dpu_{soc}_cfg = {{"] + lines + ["};", ""]
    o += ["#endif"]
    sys.stdout.write("\n".join(o) + "\n")
    for n in notes:
        print(f"sde-to-dpu: {n}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prove")
    p.add_argument("tree", help="downstream tree holding the SDE node;"
                   " several files joined with +, in include order")
    p.add_argument("catalog", help="the same SoC's upstream catalog header")
    t = sub.add_parser("transplant")
    t.add_argument("tree", help="downstream tree holding the SDE node;"
                   " several files joined with +, in include order")
    t.add_argument("catalog", help="the family's upstream catalog header")
    t.add_argument("--soc", required=True)
    t.add_argument("--version", required=True, help="DPU major.minor")
    args = ap.parse_args()
    {"prove": prove, "transplant": transplant}[args.cmd](args)


if __name__ == "__main__":
    main()
