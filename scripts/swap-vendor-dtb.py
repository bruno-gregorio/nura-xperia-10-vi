#!/usr/bin/env python3
"""Rebuild a vendor_boot image with a different device tree area.

Why this exists: the bootloader applies an overlay from the dtbo partition to
whichever base tree it picks out of vendor_boot, and overlay application
resolves the overlay's __fixups__ against the base's __symbols__. Our
parrot.dtb is built without the sm6450-modules includes, so it defines 235
fewer labels than Sony's and all 37 stock overlays reference at least one it
has not got. The bootloader then reports the device as corrupt. Verified on
2026-10-05 by flashing a vendor_boot identical to stock except for the device
tree, which red-stated a phone that stock boots.

Until our own tree defines those labels, the way to a first boot is to carry
Sony's device trees with our kernel and our initramfs.

  scripts/swap-vendor-dtb.py <in.img> <out.img> <dtb> [<dtb> ...]
  scripts/swap-vendor-dtb.py --extract <in.img> <out.dtb>

vendor_boot v4 lays its sections out page-aligned in this order: header,
vendor ramdisk, dtb, vendor ramdisk table, bootconfig. Everything except the
dtb area and the dtb_size field is copied through untouched.
"""
import struct
import sys


def sections(d):
    assert d[:8] == b"VNDRBOOT", "not a vendor_boot image"
    page = struct.unpack_from("<I", d, 12)[0]
    vendor_ramdisk_size = struct.unpack_from("<I", d, 24)[0]
    header_size, dtb_size = struct.unpack_from("<2I", d, 2096)
    vrt_size, vrt_num, vrt_entry, bc_size = struct.unpack_from("<4I", d, 2112)
    up = lambda n: (n + page - 1) // page * page
    o_rd = up(header_size)
    o_dtb = o_rd + up(vendor_ramdisk_size)
    o_vrt = o_dtb + up(dtb_size)
    o_bc = o_vrt + up(vrt_size)
    return dict(page=page, up=up, header_size=header_size,
                ramdisk=(o_rd, vendor_ramdisk_size), dtb=(o_dtb, dtb_size),
                vrt=(o_vrt, vrt_size), vrt_num=vrt_num, bc=(o_bc, bc_size))


def main():
    if sys.argv[1:2] == ["--extract"]:
        d = open(sys.argv[2], "rb").read()
        s = sections(d)
        off, size = s["dtb"]
        open(sys.argv[3], "wb").write(d[off:off + size])
        print("%s  %d bytes" % (sys.argv[3], size))
        return

    if len(sys.argv) < 4:
        sys.exit(__doc__)
    src, out, dtbs = sys.argv[1], sys.argv[2], sys.argv[3:]
    d = open(src, "rb").read()
    s = sections(d)
    up = s["up"]

    # Concatenated, in the order given and with no padding between them: that
    # is how Qualcomm ships a multi-SoC set, and dtb-ids.py reads it back.
    newdtb = b"".join(open(p, "rb").read() for p in dtbs)

    hdr = bytearray(d[:s["header_size"]])
    struct.pack_into("<I", hdr, 2100, len(newdtb))      # dtb_size

    o_rd, rd_size = s["ramdisk"]
    o_vrt, vrt_size = s["vrt"]
    o_bc, bc_size = s["bc"]
    parts = [
        bytes(hdr).ljust(up(s["header_size"]), b"\0"),
        d[o_rd:o_rd + rd_size].ljust(up(rd_size), b"\0"),
        newdtb.ljust(up(len(newdtb)), b"\0"),
        d[o_vrt:o_vrt + vrt_size].ljust(up(vrt_size), b"\0"),
        d[o_bc:o_bc + bc_size].ljust(up(bc_size), b"\0"),
    ]
    open(out, "wb").write(b"".join(parts))
    print("%s" % out)
    print("  ramdisk   %d bytes (from %s)" % (rd_size, src))
    print("  dtb       %d -> %d bytes (%d file(s))"
          % (s["dtb"][1], len(newdtb), len(dtbs)))
    print("  vrt       %d bytes, %d entries" % (vrt_size, s["vrt_num"]))
    print("  bootcfg   %d bytes" % bc_size)
    print("  total     %d bytes" % sum(len(p) for p in parts))


main()
