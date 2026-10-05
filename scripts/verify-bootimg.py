#!/usr/bin/env python3
"""Check the boot images pmbootstrap produced against what deviceinfo promises.

Parses the Android boot image headers directly rather than shelling out to
unpack_bootimg, which is not packaged in the pmport container. That also lets
us do the one check unpack_bootimg cannot: compare the DTB embedded in
vendor_boot.img byte for byte against the parrot.dtb in the kernel package, so
a stale or truncated blob cannot pass.

    scripts/verify-bootimg.py

Exits nonzero on the first thing that is wrong.
"""
import hashlib
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The fastboot images live in the rootfs chroot's /boot, where boot-deploy
# writes them. home/pmos/rootfs holds the *partition* images instead, which is
# a different thing entirely - see docs/03-build.md.
BOOT = ROOT / ".pmb/work/chroot_rootfs_sony-pdx246/boot"
IMAGES = ROOT / ".pmb/work/chroot_native/home/pmos/rootfs"

# device/sony/columbia/PlatformConfig.mk, plus mkbootimg's defaults for the two
# offsets Sony does not override.
WANT_ADDRS = {
    "kernel_addr": 0x00008000,
    "ramdisk_addr": 0x01000000,
    "tags_addr": 0x00000100,
    "dtb_addr": 0x01F00000,
}
DEVICEINFO = ROOT / "aports/device/testing/device-sony-pdx246/deviceinfo"
CMDLINE_CONF = ROOT / "aports/device/testing/device-sony-pdx246/kernel-cmdline.conf"
KERNEL_APK = ROOT / ".pmb/work/packages/edge/aarch64"

fails = []


def check(ok, msg, detail=""):
    print(f"{'  ok  ' if ok else ' FAIL '} {msg}")
    if detail:
        print(f"        {detail}")
    if not ok:
        fails.append(msg)
    return ok


def deviceinfo():
    d = {}
    for line in DEVICEINFO.read_text().splitlines():
        line = line.strip()
        if line.startswith("deviceinfo_") and "=" in line:
            k, _, v = line.partition("=")
            d[k] = v.strip('"')
    return d


def parse_boot(path):
    """boot_img_hdr_v4: magic, kernel/ramdisk size, ..., header_version, cmdline."""
    b = path.read_bytes()
    if b[:8] != b"ANDROID!":
        return None
    (kernel_size, ramdisk_size, os_version, header_size,
     r0, r1, r2, r3, header_version) = struct.unpack_from("<9I", b, 8)
    cmdline = b[44:44 + 1536].split(b"\0", 1)[0].decode("utf-8", "replace")
    return dict(kernel_size=kernel_size, ramdisk_size=ramdisk_size,
                header_version=header_version, header_size=header_size,
                cmdline=cmdline, total=len(b))


def parse_vendor_boot(path):
    """vendor_boot_img_hdr_v4."""
    b = path.read_bytes()
    if b[:8] != b"VNDRBOOT":
        return None
    header_version, page_size, kernel_addr, ramdisk_addr, vendor_ramdisk_size = \
        struct.unpack_from("<5I", b, 8)
    off = 28
    cmdline = b[off:off + 2048].split(b"\0", 1)[0].decode("utf-8", "replace")
    off += 2048
    (tags_addr,) = struct.unpack_from("<I", b, off); off += 4
    name = b[off:off + 16].split(b"\0", 1)[0].decode("utf-8", "replace"); off += 16
    header_size, dtb_size = struct.unpack_from("<2I", b, off); off += 8
    (dtb_addr,) = struct.unpack_from("<Q", b, off); off += 8
    table_size, table_entries, entry_size, bootconfig_size = \
        struct.unpack_from("<4I", b, off)

    def pages(n):
        return (n + page_size - 1) // page_size * page_size

    # Layout: header, vendor_ramdisk, dtb, vendor_ramdisk_table, bootconfig
    dtb_off = pages(header_size) + pages(vendor_ramdisk_size)
    return dict(header_version=header_version, page_size=page_size,
                kernel_addr=kernel_addr, ramdisk_addr=ramdisk_addr,
                tags_addr=tags_addr, dtb_addr=dtb_addr,
                vendor_ramdisk_size=vendor_ramdisk_size, cmdline=cmdline,
                name=name, header_size=header_size, dtb_size=dtb_size,
                bootconfig_size=bootconfig_size,
                dtb=b[dtb_off:dtb_off + dtb_size], total=len(b))


def dtb_from_kernel_apk():
    apks = sorted(KERNEL_APK.glob("linux-sony-pdx246-*.apk"))
    if not apks:
        return None, None
    want = deviceinfo().get("deviceinfo_dtb", "") + ".dtb"
    with tarfile.open(apks[-1], "r:gz") as t:
        for m in t:
            if m.name == f"boot/dtbs/{want}":
                return t.extractfile(m).read(), apks[-1].name
    return None, apks[-1].name


def main():
    di = deviceinfo()
    print(f"deviceinfo: header v{di.get('deviceinfo_header_version')}, "
          f"pagesize {di.get('deviceinfo_flash_pagesize')}, "
          f"dtb {di.get('deviceinfo_dtb')}\n")

    boot_p = BOOT / "boot.img"
    vb_p = BOOT / "vendor_boot.img"

    for p in (boot_p, vb_p):
        if not check(p.is_file(), f"{p.name} exists",
                     "" if p.is_file() else f"not at {p}"):
            print("\nNothing to check. Run 'pmb install' first.")
            return 1
        print(f"        {p.stat().st_size:,} bytes")

    rootfs = IMAGES / "sony-pdx246.img"
    if rootfs.is_file():
        # blockdevice.create() allocates this file *before* the loop mount, so
        # a failed install leaves a correctly sized, completely empty sparse
        # file behind. Flashing that would write zeros over userdata, so insist
        # on a GPT rather than merely on the file existing.
        with rootfs.open("rb") as fh:
            fh.seek(512)
            gpt = fh.read(8)
        if gpt == b"EFI PART":
            print(f"  ok   {rootfs.name} has a GPT"
                  f"\n        {rootfs.stat().st_size:,} bytes")
        else:
            check(False, f"{rootfs.name} is partitioned",
                  f"{rootfs.stat().st_size:,} bytes but no GPT at offset 512 - "
                  "allocated and never filled, do not flash it")
    else:
        print(f"  --   {rootfs.name} absent - ramboot does not need it, "
              f"'flash.sh flash' does")

    print("\n-- boot.img --")
    b = parse_boot(boot_p)
    if not check(b is not None, "ANDROID! magic"):
        return 1
    check(b["header_version"] == int(di["deviceinfo_header_version"]),
          f"header_version == {di['deviceinfo_header_version']}",
          f"got {b['header_version']}")
    check(b["kernel_size"] > 8 * 1024 * 1024,
          "carries a kernel", f"kernel_size {b['kernel_size']:,}")
    check(b["ramdisk_size"] == 0,
          "ramdisk is empty (v4 puts it in vendor_boot)",
          f"ramdisk_size {b['ramdisk_size']}")

    print("\n-- vendor_boot.img --")
    v = parse_vendor_boot(vb_p)
    if not check(v is not None, "VNDRBOOT magic"):
        return 1
    check(v["header_version"] == int(di["deviceinfo_header_version"]),
          f"header_version == {di['deviceinfo_header_version']}",
          f"got {v['header_version']}")
    check(v["page_size"] == int(di["deviceinfo_flash_pagesize"]),
          f"page_size == {di['deviceinfo_flash_pagesize']}",
          f"got {v['page_size']}")
    check(v["vendor_ramdisk_size"] > 1024 * 1024,
          "carries the initramfs",
          f"vendor_ramdisk_size {v['vendor_ramdisk_size']:,}")
    check(v["dtb_size"] > 0, "carries a DTB", f"dtb_size {v['dtb_size']:,}")
    check(v["dtb"][:4] == b"\xd0\x0d\xfe\xed",
          "DTB at the computed offset starts with the FDT magic",
          f"got {v['dtb'][:4].hex()}")

    want, apk = dtb_from_kernel_apk()
    if want is None:
        check(False, "parrot.dtb found in the kernel apk", f"looked in {apk}")
    else:
        check(hashlib.sha256(want).hexdigest() == hashlib.sha256(v["dtb"]).hexdigest(),
              "embedded DTB is byte-identical to the kernel package's",
              f"{len(want):,} bytes, sha256 {hashlib.sha256(want).hexdigest()[:16]}")

    print("\n-- load addresses (header v3+ keeps them here, not in boot.img) --")
    for name, addr in WANT_ADDRS.items():
        check(v[name] == addr, f"{name} == 0x{addr:08x}",
              f"got 0x{v[name]:08x}"
              + ("  <- mkbootimg's default base is 0x10000000; set"
                 " deviceinfo_bootimg_custom_args" if v[name] != addr else ""))

    print("\n-- cmdline --")
    cmdline = v["cmdline"]
    print(f"        {cmdline}")
    wanted = [w for ln in CMDLINE_CONF.read_text().splitlines()
              if (w := ln.strip()) and not w.startswith("#")]
    for w in wanted:
        check(w in cmdline.split(), f"cmdline has {w}")
    check("quiet" not in cmdline.split() or "loglevel=7" in cmdline.split(),
          "loglevel=7 is there to override base's quiet")

    print()
    if fails:
        print(f"==> {len(fails)} PROBLEM(S):")
        for f in fails:
            print(f"      - {f}")
        return 1
    print("==> OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
