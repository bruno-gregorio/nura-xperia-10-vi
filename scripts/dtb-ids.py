#!/usr/bin/env python3
"""List the ids a Qualcomm bootloader matches device trees on.

ABL walks the device trees in vendor_boot and picks the one whose
'qcom,msm-id', 'qcom,board-id' and 'qcom,pmic-id' match the hardware it read
out of the SoC. A tree that matches nothing is not booted, so these three
properties decide whether our device tree is ever used.

  scripts/dtb-ids.py <file-with-one-or-more-FDTs> ...

Accepts a bare .dtb, a concatenation of them (which is what Qualcomm ships in
vendor_boot), or a vendor_boot image, whose dtb area is found from its header.

scripts/dtb-stamp-ids.py is the other half of this pair: a mainline device tree
carries none of these properties, because they describe the firmware's
selection protocol rather than the hardware, so they are stamped on at flash
time and checked back with this.

"Match" means one of two things and the difference decides what a stamp has to
say. With a readable dtbo partition ABL scores candidates and treats a zero
field as a wildcard; without one it uses the older LK matcher, which wants
every field exactly. The mainline kernel takes the second path on purpose - see
scripts/no-dtbo.py - so values that look plausible here can still be refused.

The scan steps one byte at a time rather than four: Qualcomm's concatenated
trees are not padded to an alignment, so a 4-byte scan silently skips every
tree that happens to start at an odd offset.
"""
import struct
import sys
import os

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9


def root_props(blob):
    """Return {name: bytes} for the properties directly on the root node."""
    (magic, totalsize, off_struct, off_strings, off_rsvmap, ver, last_comp,
     boot_cpuid, size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    strings = blob[off_strings:off_strings + size_strings]
    off = off_struct
    depth = 0
    props = {}
    while off < off_struct + size_struct:
        (tok,) = struct.unpack_from(">I", blob, off)
        off += 4
        if tok == BEGIN_NODE:
            end = blob.index(b"\0", off)
            off = (end + 4) & ~3
            depth += 1
        elif tok == END_NODE:
            depth -= 1
            if depth == 0:
                break
        elif tok == PROP:
            plen, nameoff = struct.unpack_from(">2I", blob, off)
            off += 8
            val = blob[off:off + plen]
            off = (off + plen + 3) & ~3
            if depth == 1:
                name = strings[nameoff:strings.index(b"\0", nameoff)].decode()
                props[name] = val
        elif tok == NOP:
            pass
        elif tok == END:
            break
        else:
            break
    return totalsize, props


def fdts_in(path):
    """Yield (offset, blob) for every FDT in the file, following totalsize."""
    data = open(path, "rb").read()
    # A vendor_boot image: take only its dtb area, so we do not trip over an
    # FDT magic that happens to occur inside the compressed ramdisk.
    if data[:8] == b"VNDRBOOT":
        page = struct.unpack_from("<I", data, 12)[0]
        vendor_ramdisk_size = struct.unpack_from("<I", data, 24)[0]
        header_size, dtb_size = struct.unpack_from("<2I", data, 2096)
        up = lambda n: (n + page - 1) // page * page
        start = up(header_size) + up(vendor_ramdisk_size)
        data = data[start:start + dtb_size]
    off = 0
    while off + 40 <= len(data):
        if data[off:off + 4] != FDT_MAGIC:
            off += 1
            continue
        total = struct.unpack_from(">I", data, off + 4)[0]
        if total < 40 or off + total > len(data):
            break
        yield off, data[off:off + total]
        off += total


def words(v):
    return list(struct.unpack(">%dI" % (len(v) // 4), v[:len(v) // 4 * 4]))


def main():
    for path in sys.argv[1:]:
        print("%s  (%d bytes)" % (path, os.path.getsize(path)))
        n = 0
        for off, blob in fdts_in(path):
            total, p = root_props(blob)
            n += 1
            model = p.get("model", b"").rstrip(b"\0").decode("ascii", "replace")
            msm = words(p.get("qcom,msm-id", b""))
            board = words(p.get("qcom,board-id", b""))
            pmic = words(p.get("qcom,pmic-id", b""))
            print("  [%2d] @%-9d %7d bytes  %s" % (n, off, total, model))
            print("       msm-id   %s" % " ".join("0x%x" % w for w in msm))
            print("       board-id %s" % " ".join("0x%x" % w for w in board))
            if pmic:
                print("       pmic-id  %s" % " ".join("0x%x" % w for w in pmic))
        print("  %d device tree(s)" % n)
        print()


main()
