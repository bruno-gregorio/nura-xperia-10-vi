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

Which of the bootloader's two matchers these values are for
-----------------------------------------------------------

ABL has two, and they are not equally strict. docs/05-status.md cites the
source for both; the short version decides every number below.

With a dtbo partition it can read, ABL calls GetSocDtb to pick a base out of
the dtb area and GetBoardDtb to pick an overlay out of dtbo, and both use a
*scoring* matcher: a property that is zero in the tree counts as "default" and
still scores, so a base advertising qcom,board-id = <0x0 0x0> is selected
quite happily. That is the path stock Android takes and the path our
downstream kernel takes.

With a dtbo it cannot read, ABL calls DeviceTreeAppended instead, which uses
the older LK matcher - and that one is all-or-nothing. platform_dt_absolute_match
requires the tree's SoC id, platform type, platform subtype and DDR type to
equal the board's exactly, and discards the tree outright otherwise. Zero is
not a wildcard there; zero is just a value that does not match.

The mainline kernel takes the appended path on purpose, because it is the only
one that applies no overlay - see scripts/no-dtbo.py. So these values are
written for the strict matcher, which is why they are no longer the <0x0 0x0>
that the scoring matcher was happy with.

Where the values come from
--------------------------

Every one of them is something the device reports about itself, read off the
running phone from /sys/devices/soc0 rather than inferred:

    soc_id 537 = 0x219         hw_platform QRD
    platform_version 65536     platform_subtype_id 0
      = 0x10000                foundry_id 3

qcom,msm-id is <soc-id soc-revision>. 0x219 is soc_id and 0x10000 is the
revision the device calls 1.0. 0x265 comes along because the stock base tree
for this SoC groups the two and only one entry has to match.

Bits 23:16 of the first cell are the foundry id, and they are deliberately
left at zero even though this chip was fused at foundry 3. ABL treats a zero
foundry as the default match and keeps the tree; a foundry that is set and
wrong is thrown away. Zero is the safe value, and it is what all fourteen of
Sony's base trees use.

qcom,board-id is <variant subtype>, and the variant is three fields packed
into one cell:

    0x00_01_00_0b
         |  |  +-- platform type: 0x0b is QRD, which is what hw_platform says
         |  +----- platform minor version: 0 (low byte of platform_version)
         +-------- platform major version: 1 (0x10000 >> 16)

The subtype cell is the platform subtype in its low byte - 0, from
platform_subtype_id - and the DDR type in bits 10:8. The DDR type is the one
number the device does not publish, so it is swept: this writes eight
<variant subtype> pairs, one per possible DDR type, and the strict matcher
keeps whichever of the eight is the board's and discards the other seven. A
tree may carry as many pairs as it likes, so the sweep costs 56 bytes and
removes the last guess from the chain.

The evidence says that value is 0, for what it is worth. The overlay stock
Android booted is "Parrot QRD", qcom,board-id = <0x1000b 0x0>; the table also
holds "Parrot QRD 4GB DDR", <0x1000b 0x600>, which is identical in every field
the matcher scores except the DDR type and comes *earlier* in the table, so it
would have won both an exact DDR match and a tie. It lost, which leaves only
one reading: the board's DDR type is 0 and the plain QRD overlay beat it on
that bit. The sweep is there because that is an inference about firmware and
the stamp is cheap, not because the inference is weak.

ABL matches on a third property as well, qcom,pmic-id, and this does not set
it. Leaving it out is better than setting it: for a tree without one the
appended matcher fills the pmic revisions in from the board itself, so they
compare equal by construction.

The other half
--------------

Having selected a base, the scoring path also applies a matching overlay from
the dtbo partition, resolving the overlay's __fixups__ against the base's
__symbols__ - and our tree has no __symbols__ at all, because upstream builds
without dtc -@. A failed overlay is what red-states this phone: verified on
2026-10-05, when a vendor_boot identical to stock except for the device tree
was declared corrupt over 61 unresolvable labels. Ours would fail on all of
them.

So the overlay has to be taken off the table, and the way to do that is to
give ABL a dtbo it refuses to parse, which sends it down the appended path
instead. scripts/no-dtbo.py builds one and says why an *empty* dtbo - which is
what this project tried first, on 2026-10-06 - is the one shape that cannot
work.
"""
import struct
import sys

# From the running device's own /sys/devices/soc0; see above for each field.
# Check what a tree ended up advertising with:
#   scripts/dtb-ids.py out/try-kernel/pdx246-stamped.dtb
MSM_ID = [0x219, 0x10000, 0x265, 0x10000]

# QRD, platform version 1.0, subtype 0 - once per DDR type, because that is
# the field the device does not report and the strict matcher wants exactly.
BOARD_ID = [cell
            for ddr in range(8)
            for cell in (0x0001000B, ddr << 8)]

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
    pairs = [f"<{BOARD_ID[i]:#x} {BOARD_ID[i + 1]:#x}>"
             for i in range(0, len(BOARD_ID), 2)]
    print(f"    qcom,board-id = {pairs[0]}"
          + (f" and {len(pairs) - 1} more, one per DDR type"
             if len(pairs) > 1 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
