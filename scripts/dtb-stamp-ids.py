#!/usr/bin/env python3
"""Add the two properties the Qualcomm bootloader needs to select our tree.

    scripts/dtb-stamp-ids.py <in.dtb> <out.dtb>

scripts/dtb-ids.py is the other half of this pair and reads the same three
properties back out of a .dtb, a concatenation of them or a whole vendor_boot
image. Use it to check the result, here or after a flash.

Why this is a script and not two lines in the .dts
--------------------------------------------------

qcom,msm-id and qcom,board-id are not device tree. They are bootloader
metadata. Qualcomm's boot chain reads the SoC id out of the fuses and the board
id out of shared memory, then walks the dtb area of vendor_boot looking for a
tree that advertises both, and boots the one that matches. A mainline device
tree carries neither - no upstream qcom dtsi has ever had them, and a patch
adding them would be rejected, correctly, because they describe the firmware's
selection protocol and not the hardware. So they get stamped on at flash time
and the tree that goes to the lists stays clean.

Why Python and not fdtput
-------------------------

This started as a shell script around fdtput and that put it on the wrong side
of a fence. fdtput and dtc live in the pmport container; fastboot and adb live
on the host, and this project may not install anything on the host. So
try-kernel.sh, which needs both, could not run anywhere: it got as far as
"stamping the bootloader ids" and died on "fdtput not found". Doing the
surgery here instead costs about eighty lines and makes the loop runnable from
one side, which is worth more than the brevity.

Where the values come from
--------------------------

Not invented, and - the one trap here - not the ones the live tree shows.

/proc/device-tree on the running device has qcom,board-id = <0x1000b 0x0> at
its root, but that is the *overlay's* id, not the base's: the resolved tree's
root says model = "Qualcomm Technologies, Inc. Parrot QRD", which is
parrot-qrd-overlay, applied on top. Stamping that would have given our base an
id no base is selected on.

What the bootloader selects a base on is visible in the stock vendor_boot, read
with scripts/dtb-ids.py: all fourteen of Sony's base trees carry
qcom,board-id = <0x0 0x0> or <0x0 0x600> - generic, SoC-level - and are
distinguished from each other by qcom,msm-id alone. The overlays are the ones
that carry a board id.

So these are "Qualcomm Technologies, Inc. Parrot SoC", the generic base for
this SoC. That it is the right one is settled by the device rather than
inferred: /sys/devices/soc0 on the running phone reports soc_id 537 = 0x219,
platform_version 65536 = 0x10000, hw_platform QRD and platform_subtype_id 0,
and 0x219 0x10000 is exactly what that base advertises. 0x265 comes along
because Qualcomm groups the two in one tree and only one entry has to match.

ABL matches on a third property as well, qcom,pmic-id, and this does not set
it: no base tree in the stock vendor_boot carries one, so it is not part of
what this board is matched on.

The other half
--------------

Having selected a base, the bootloader also applies a matching overlay from the
dtbo partition, resolving the overlay's __fixups__ against the base's
__symbols__ - and our tree has no __symbols__ at all, because upstream builds
without dtc -@. A failed overlay is what red-states this phone: verified on
2026-10-05, when a vendor_boot identical to stock except for the device tree
was declared corrupt over 61 unresolvable labels. Ours would fail on all of
them.

The board-id cannot be used to dodge that. Base and overlay are both matched
against the *hardware's* ids rather than against each other, so a base
advertising a board-id no overlay asks for would not be selected either. The
other half therefore has to be the dtbo partition itself: see
scripts/empty-dtbo.py, which builds an image with no overlays in it for the
spare slot to carry.
"""
import struct
import sys

# From "Parrot SoC" in the stock vendor_boot, confirmed against the running
# device's own soc_id. Check with:
#   scripts/dtb-ids.py out/device-dump-root/stock/vendor_boot_b.img
MSM_ID = [0x219, 0x10000, 0x265, 0x10000]
BOARD_ID = [0x0, 0x0]

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
HEADER_FMT = ">10I"
HEADER_SIZE = 40


def pad4(b):
    return b + b"\0" * (-len(b) % 4)


def parse_header(blob):
    (magic, totalsize, off_struct, off_strings, off_rsvmap, version,
     last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack_from(
        HEADER_FMT, blob, 0)
    if magic != FDT_MAGIC:
        raise ValueError(f"not a device tree: magic {magic:#x}")
    return dict(totalsize=totalsize, off_struct=off_struct,
                off_strings=off_strings, off_rsvmap=off_rsvmap,
                version=version, last_comp=last_comp, boot_cpuid=boot_cpuid,
                size_strings=size_strings, size_struct=size_struct)


def root_prop_start(struct_blob):
    """Offset of the root node's first property.

    New properties go in at the front, which is where fdtput puts them. Order
    is meaningless to anything that reads a device tree - the bootloader and
    the kernel both look properties up by name - but matching fdtput byte for
    byte turns "does this agree with the reference implementation" into a one
    line test, and on a phone that red-states over a malformed tree that test
    is worth having.
    """
    off = 0
    tag, = struct.unpack_from(">I", struct_blob, off)
    if tag != FDT_BEGIN_NODE:
        raise ValueError("struct block does not start with a node")
    off += 4
    # The root's name is the empty string, padded out to a four byte boundary.
    end = struct_blob.index(b"\0", off)
    return end + (-(end - off + 1) % 4) + 1


def drop_root_props(struct_blob, strings, names):
    """Remove the named properties from the root node, if present.

    Replacing rather than duplicating matters: a tree stamped twice would
    otherwise carry two qcom,msm-id properties, and which one the bootloader
    reads is not something to find out on a phone.
    """
    out = bytearray()
    off = 0
    tag, = struct.unpack_from(">I", struct_blob, off)
    out += struct_blob[off:off + 4]
    off += 4
    end = struct_blob.index(b"\0", off)
    name_end = end + (-(end - off + 1) % 4) + 1
    out += struct_blob[off:name_end]
    off = name_end

    while True:
        tag, = struct.unpack_from(">I", struct_blob, off)
        if tag == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", struct_blob, off + 4)
            size = 12 + length + (-length % 4)
            name = strings[nameoff:strings.index(b"\0", nameoff)].decode()
            if name not in names:
                out += struct_blob[off:off + size]
            off += size
        elif tag == FDT_NOP:
            out += struct_blob[off:off + 4]
            off += 4
        else:
            out += struct_blob[off:]
            return bytes(out)


def intern(strings, name):
    """Offset of name in the strings block, appending it if it is not there."""
    want = name.encode() + b"\0"
    at = strings.find(want)
    # A suffix match would be wrong: "id" must not resolve inside "board-id".
    while at > 0 and strings[at - 1:at] != b"\0":
        at = strings.find(want, at + 1)
    if at >= 0:
        return strings, at
    return strings + want, len(strings)


def stamp(blob, props):
    h = parse_header(blob)
    struct_blob = blob[h["off_struct"]:h["off_struct"] + h["size_struct"]]
    strings = blob[h["off_strings"]:h["off_strings"] + h["size_strings"]]
    rsvmap = blob[h["off_rsvmap"]:h["off_struct"]]

    struct_blob = drop_root_props(struct_blob, strings, set(props))

    # Interned in the order given, so the strings block grows the way fdtput
    # grows it, but emitted in reverse: prepending one at a time leaves the
    # first one asked for last, and that is what the shell version did.
    entries = []
    for name, cells in props.items():
        strings, nameoff = intern(strings, name)
        value = pad4(struct.pack(f">{len(cells)}I", *cells))
        entries.append(struct.pack(">III", FDT_PROP, len(cells) * 4, nameoff)
                       + value)
    at = root_prop_start(struct_blob)
    added = b"".join(reversed(entries))
    struct_blob = struct_blob[:at] + added + struct_blob[at:]

    off_rsvmap = HEADER_SIZE
    off_struct = off_rsvmap + len(rsvmap)
    off_strings = off_struct + len(struct_blob)
    total = off_strings + len(strings)
    header = struct.pack(HEADER_FMT, FDT_MAGIC, total, off_struct, off_strings,
                         off_rsvmap, h["version"], h["last_comp"],
                         h["boot_cpuid"], len(strings), len(struct_blob))
    return header + rsvmap + struct_blob + strings


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        print(f"usage: {argv[0]} <in.dtb> <out.dtb>", file=sys.stderr)
        return 2
    with open(argv[1], "rb") as fh:
        blob = fh.read()
    out = stamp(blob, {"qcom,msm-id": MSM_ID, "qcom,board-id": BOARD_ID})
    # Cheapest possible guard against having produced rubbish: read it back
    # with the same parser before anything writes it to a phone.
    parse_header(out)
    with open(argv[2], "wb") as fh:
        fh.write(out)
    print(f"==> {argv[2]}")
    print("    qcom,msm-id   = " + " ".join(f"{v:#x}" for v in MSM_ID))
    print("    qcom,board-id = " + " ".join(f"{v:#x}" for v in BOARD_ID))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
