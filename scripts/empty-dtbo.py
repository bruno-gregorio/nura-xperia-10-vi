#!/usr/bin/env python3
"""Build a dtbo image with no overlays in it.

   scripts/empty-dtbo.py <out.img> [--pad BYTES]

Why: the Qualcomm boot chain picks a base device tree out of vendor_boot by
matching qcom,msm-id and qcom,board-id against the hardware, and then applies a
matching overlay from the dtbo partition on top, resolving the overlay's
__fixups__ against the base's __symbols__. For the downstream kernel that is
exactly what we want - stock's parrot-qrd overlay carries the board detail and
our base carries the SoC.

For the mainline kernel it is fatal. Our tree is complete on its own and has no
__symbols__ node at all, because upstream builds device trees without dtc -@.
Every one of the 37 stock overlays would fail to apply, and a failed overlay is
what red-states this phone - verified on 2026-10-05, when a vendor_boot
identical to stock except for its device tree was declared corrupt over 61
unresolvable labels. Ours would fail on all 1234.

The board-id cannot be used to dodge it, because base and overlay are matched
against the hardware's ids and not against each other: a base advertising a
board-id that no overlay asks for would not be selected either. So the overlay
has to be removed from the other side, by giving the spare slot a dtbo that has
nothing in it to match.

This writes the Android DT table header and stops: magic, sizes, and
dt_entry_count = 0. A bootloader that iterates the table finds no candidates.
Whether this phone's bootloader accepts that is the one thing here that is not
verified against anything - it is the experiment. It is safe to try because it
goes on the inactive slot, out/device-dump-root/stock/dtbo_{a,b}.img are
byte-for-byte dumps of both slots as they shipped, and
scripts/try-kernel.sh --restore puts them back.

Format, from AOSP system/libufdt/utils/src/dt_table.h, all fields big-endian:

    0  magic             0xd7b7ab1e
    4  total_size        header + entries + blobs
    8  header_size       32
   12  dt_entry_size     32
   16  dt_entry_count    number of overlays
   20  dt_entries_offset 32
   24  page_size         4096
   28  version           0
"""
import struct
import sys

MAGIC = 0xD7B7AB1E
HEADER_SIZE = 32
ENTRY_SIZE = 32
PAGE_SIZE = 4096


def build(pad=PAGE_SIZE):
    """The header alone, padded with zeros to `pad` bytes.

    total_size is the header, because there is nothing after it. The padding is
    not part of the image as far as the bootloader is concerned; it is there so
    the flashed region is deterministic rather than whatever overlay bytes the
    partition happened to hold before.
    """
    hdr = struct.pack(
        ">8I",
        MAGIC,
        HEADER_SIZE,   # total_size
        HEADER_SIZE,
        ENTRY_SIZE,
        0,             # dt_entry_count
        HEADER_SIZE,   # dt_entries_offset
        PAGE_SIZE,
        0,             # version
    )
    assert len(hdr) == HEADER_SIZE
    return hdr + b"\0" * max(0, pad - len(hdr))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    out, pad = argv[0], PAGE_SIZE
    if len(argv) >= 3 and argv[1] == "--pad":
        pad = int(argv[2], 0)
    elif len(argv) != 1:
        print("usage: %s <out.img> [--pad BYTES]" % sys.argv[0], file=sys.stderr)
        return 2
    data = build(pad)
    with open(out, "wb") as f:
        f.write(data)
    print("==> %s  %d bytes, 0 overlays" % (out, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
