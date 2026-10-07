#!/usr/bin/env python3
"""Build a dtbo image the bootloader will refuse to read.

   scripts/no-dtbo.py <out.img> [--pad BYTES]

Why: the mainline kernel's device tree is complete on its own and has no
__symbols__ node, because upstream builds device trees without dtc -@. Every
one of the 37 overlays in Sony's dtbo would fail to resolve its __fixups__
against it, and a failed overlay is what red-states this phone - verified on
2026-10-05, when a vendor_boot identical to stock except for its device tree
was declared corrupt over 61 unresolvable labels. So no overlay must be
applied at all, and this is how that is arranged.

How ABL decides, and why "no overlays" is not the same as "no dtbo"
------------------------------------------------------------------

ABL is Qualcomm's EDK2 bootloader; its sources are public, and the two
functions that matter are LoadAndValidateDtboImg in
QcomModulePkg/Library/BootLib/PartitionTableUpdate.c and the block in
BootLinux.c that branches on it. In full:

    DtboImgInvalid = LoadAndValidateDtboImg (Info, BootParamlistPtr);
    if (!DtboImgInvalid) {
      // appended device tree
      Dtb = DeviceTreeAppended (...);
    } else {
      SocDtb = GetSocDtb (...);
      BoardDtb = GetBoardDtb (Info, BootParamlistPtr->DtboImgBuffer);
      if (!BoardDtb) {
        DEBUG ((EFI_D_ERROR, "Error: Board Dtbo blob not found\n"));
        return EFI_NOT_FOUND;
      }
      ...
      Status = ApplyOverlay (BootParamlistPtr, SocDtb, DtsList);
    }

The variable is named backwards: LoadAndValidateDtboImg returns TRUE when the
image is *good*. So a dtbo ABL can parse puts it in the else branch, where it
must find a matching overlay or refuse to boot, and a dtbo it cannot parse
puts it in the first branch - DeviceTreeAppended, which selects a tree out of
the dtb area and applies nothing on top of it. That branch is the whole
objective here.

This is also what the postmarketOS wiki means by "fastboot erase dtbo", which
it gives as a step for mainline on Qualcomm devices. Erasing works for the
same reason: what is left has no magic.

Why the empty table failed
--------------------------

The first attempt at this, on 2026-10-06, built a valid Android DT table
header with dt_entry_count = 0, on the theory that a bootloader iterating an
empty table would find nothing to apply and carry on. It red-stated the phone,
and the sources say exactly why. LoadAndValidateDtboImg checks the magic, the
total size against zero, the header size, the entry size, the entry offset and
the entry count against the partition size - and a count of zero passes every
one of them. So ABL declared the image good, committed to the overlay branch,
and called GetBoardDtb:

    DtboTableEntriesCount = fdt32_to_cpu (DtboTableHdr->DtEntryCount);
    for (DtboCount = 0; DtboCount < DtboTableEntriesCount; DtboCount++) {
      ...
    }
    if (!BestDtbInfo.Dtb) {
      DEBUG ((EFI_D_ERROR, "Unable to find the Board Dtb\n"));
      return NULL;
    }

The loop ran zero times, BestDtbInfo.Dtb stayed NULL, and the caller turned
that into EFI_NOT_FOUND. An empty table is not a table with nothing to apply;
it is a table ABL trusts and then cannot satisfy, which is the one shape that
cannot work. A table full of overlays for other SoCs would have been fine, for
that matter - Sony's own has fourteen of them, for Montague and Ravelin - as
long as one of them matches.

The escape hatch that does not open
-----------------------------------

GetSocDtb has one: if a base tree matches the hardware on every field it
scores, ABL logs "Exact DTB match found. DTBO search is not required", sets
DtboNeed = FALSE, and BootLinux.c then skips GetBoardDtb entirely - no overlay
applied, stock dtbo untouched. That would be the tidier route and it is not
available here. "Every field" is CheckAllBitsSet against ALL_BITS_SET, which
includes all sixteen PMIC_MATCH_EXACT_MODEL_IDX0..F bits, and those are only
set from a qcom,pmic-id property; no base tree on this device has one, and
qcom,pmic-id-size caps the index at 0xF, one short of the sixteen required.
It cannot be satisfied, so the dtbo has to be dealt with on its own side.

What this writes
----------------

Zeros. The magic check is the first thing LoadAndValidateDtboImg does with the
image, so four zero bytes are the whole mechanism and nothing past the header
is ever read; the padding only makes the flashed region deterministic instead
of whatever overlay bytes the partition held before. Flashing zeros rather
than erasing keeps the step on the same path as every other partition in
try-kernel.sh, and makes what is on the phone a thing we chose rather than
whatever UFS leaves behind an unmap.

AVB does not object: scripts/try-kernel.sh flashes a vbmeta with the hashtree
and verification flags set, so the dtbo's hash descriptor is not checked.

Safe to try because it goes on the inactive slot,
out/device-dump-root/stock/dtbo_{a,b}.img are byte-for-byte dumps of both
slots as they shipped, and scripts/try-kernel.sh --restore puts them back.

One thing this moves rather than removes: the appended path uses the older LK
matcher, platform_dt_absolute_match, which is strict where the scoring matcher
was lenient. scripts/dtb-stamp-ids.py stamps for the strict one, and says
which of its fields comes from where.

Format, for the record, from AOSP system/libufdt/utils/src/dt_table.h, all
fields big-endian - this is the header being deliberately *not* written:

    0  magic             0xd7b7ab1e
    4  total_size        header + entries + blobs
    8  header_size       32
   12  dt_entry_size     32
   16  dt_entry_count    number of overlays
   20  dt_entries_offset 32
   24  page_size         4096
   28  version           0
"""
import sys

MAGIC = 0xD7B7AB1E
HEADER_SIZE = 32
PAGE_SIZE = 4096


def build(pad=PAGE_SIZE):
    """`pad` zero bytes, of which only the first four do any work."""
    return b"\0" * max(HEADER_SIZE, pad)


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
    assert int.from_bytes(data[:4], "big") != MAGIC
    with open(out, "wb") as f:
        f.write(data)
    print("==> %s  %d bytes, no dtbo magic (ABL will use the appended DTB)"
          % (out, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
