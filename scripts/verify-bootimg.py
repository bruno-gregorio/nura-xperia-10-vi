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
import gzip
import hashlib
import io
import struct
import subprocess
import sys
import tarfile
import uuid
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
DEVPKG = ROOT / "aports/device/testing/device-sony-pdx246"
DEVICEINFO = DEVPKG / "deviceinfo"
KERNEL_APK = ROOT / ".pmb/work/packages/edge/aarch64"
PMB_CFG = ROOT / ".pmb/pmbootstrap_v3.cfg"


def selected_kernel():
    """Which of the device package's kernels this boot image was built for.

    The device package offers -kernel-downstream and -kernel-mainline, and the
    two promise different device trees, initramfs module lists and command
    lines. pmbootstrap's own config is the right place to ask, because it is
    what chose the kernel subpackage that went into the rootfs this script is
    checking - not the newest apk, and not a guess from a filename.
    """
    for line in PMB_CFG.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "kernel":
            return v.strip()
    return "downstream"


KERNEL = selected_kernel()
MODULES_INITFS = DEVPKG / f"modules-initfs.{KERNEL}"
CMDLINE_CONF = DEVPKG / f"kernel-cmdline.{KERNEL}.conf"

fails = []


def check(ok, msg, detail="", hint=""):
    """detail is a fact worth printing either way; hint only explains a failure."""
    print(f"{'  ok  ' if ok else ' FAIL '} {msg}")
    if detail:
        print(f"        {detail}")
    if not ok:
        if hint:
            print(f"        {hint}")
        fails.append(msg)
    return ok


def deviceinfo():
    """deviceinfo as the selected kernel sees it.

    Keys that differ between the two kernels carry a _downstream or _mainline
    suffix in the file, and the one that applies wins under the bare name -
    the same rewrite devicepkg_subpackage_kernel does when it builds the
    subpackage, and pmb.parse.deviceinfo does when it reads one. A suffix for
    the other kernel is dropped rather than left to shadow anything.
    """
    d = {}
    for line in DEVICEINFO.read_text().splitlines():
        line = line.strip()
        if line.startswith("deviceinfo_") and "=" in line:
            k, _, v = line.partition("=")
            d[k] = v.strip('"')
    for k in list(d):
        if k.endswith(f"_{KERNEL}"):
            d[k[: -len(KERNEL) - 1]] = d.pop(k)
    for k in list(d):
        if any(k.endswith(f"_{o}") for o in ("downstream", "mainline")):
            del d[k]
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


# Which package carries the device tree to compare against. Both kernels build
# a .dtb and boot-deploy embeds whichever one deviceinfo_dtb names, so checking
# the embedded copy against the wrong package reports a missing file rather than
# a mismatch - which is what it did, every time, under the mainline kernel.
KERNEL_PKG = {
    "downstream": "linux-sony-pdx246",
    "mainline": "linux-postmarketos-qcom-sm6450",
}.get(KERNEL, "linux-sony-pdx246")


def dtb_from_kernel_apk():
    # Match the rootfs's installed version. Lexical sorting selected r9 over
    # r43 and silently compared a new image against an unrelated old kernel.
    installed = (BOOT.parent / "lib/apk/db/installed").read_text()
    version = None
    for record in installed.split("\n\n"):
        fields = dict(line.split(":", 1) for line in record.splitlines() if ":" in line)
        if fields.get("P") == KERNEL_PKG:
            version = fields.get("V")
            break
    if version is None:
        return None, None
    apk = KERNEL_APK / f"{KERNEL_PKG}-{version}.apk"
    if not apk.is_file():
        return None, apk.name
    want = deviceinfo().get("deviceinfo_dtb", "") + ".dtb"
    with tarfile.open(apk, "r:gz") as t:
        for m in t:
            if m.name == f"boot/dtbs/{want}":
                return t.extractfile(m).read(), apk.name
    return None, apk.name


def ext4_superblock(path):
    """Read the bits of an ext4 superblock we care about.

    Done by hand rather than by shelling out to dumpe2fs, so this script stays
    runnable on the host with nothing but python3.
    """
    with path.open("rb") as f:
        f.seek(1024)
        sb = f.read(1024)
    if struct.unpack_from("<H", sb, 0x38)[0] != 0xEF53:
        return None
    return {
        "uuid": str(uuid.UUID(bytes=sb[0x68:0x78])),
        "label": sb[0x78:0x88].rstrip(b"\0").decode("utf-8", "replace"),
        "block_size": 1024 << struct.unpack_from("<I", sb, 0x18)[0],
        "blocks": struct.unpack_from("<I", sb, 0x04)[0],
    }


def initramfs_entries(path):
    """Names in the gzip or zstd cpio initramfs, without extracting it."""
    names = []
    compressed = path.read_bytes()
    if compressed.startswith(b"\x1f\x8b"):
        data = gzip.decompress(compressed)
    elif compressed.startswith(b"\x28\xb5\x2f\xfd"):
        data = subprocess.check_output(["zstd", "-dc", str(path)])
    else:
        raise ValueError("Unknown initramfs compression")
    off = 0
    while off + 110 <= len(data):
        if data[off:off + 6] != b"070701":
            break
        f = [int(data[off + 6 + i * 8: off + 14 + i * 8], 16) for i in range(13)]
        namesize, filesize = f[11], f[6]
        name = data[off + 110: off + 110 + namesize - 1].decode("utf-8", "replace")
        if name == "TRAILER!!!":
            break
        names.append(name)
        off += (110 + namesize + 3) & ~3
        off += (filesize + 3) & ~3
    return names


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
        # Two shapes are valid: pmbootstrap's own image carries a GPT, while
        # make-rootfs-img.sh writes a bare ext4 (superblock magic 0xef53 at
        # offset 1080).
        with rootfs.open("rb") as fh:
            fh.seek(512)
            gpt = fh.read(8)
            fh.seek(1080)
            ext4 = fh.read(2)
        shape = ("a GPT" if gpt == b"EFI PART"
                 else "a bare ext4 filesystem" if ext4 == b"\x53\xef"
                 else None)
        if shape:
            print(f"  ok   {rootfs.name} holds {shape}"
                  f"\n        {rootfs.stat().st_size:,} bytes")
        else:
            check(False, f"{rootfs.name} holds a filesystem",
                  f"{rootfs.stat().st_size:,} bytes, but neither a GPT at 512 nor "
                  "an ext4 superblock at 1080 - allocated and never filled, "
                  "do not flash it")
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
    dtb_name = Path(deviceinfo().get("deviceinfo_dtb", "?")).name + ".dtb"
    if want is None:
        check(False, f"{dtb_name} found in the kernel apk", f"looked in {apk}")
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

    print("\n-- initramfs --")
    initramfs = BOOT / "initramfs"
    if not initramfs.is_file():
        check(False, "initramfs exists", f"not at {initramfs}")
    else:
        entries = initramfs_entries(initramfs)
        check(len(entries) > 100, f"{len(entries)} entries")

        # Every name in modules-initfs should be in there. modprobe treats '-'
        # and '_' alike and stock's list mixes them, so normalise.
        want = {ln.strip().replace("-", "_")
                for ln in MODULES_INITFS.read_text().splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")}
        # Our mainline config has CONFIG_MODULE_COMPRESS_ZSTD, so these are
        # .ko.zst. Matching only ".ko" reported "0 .ko in the image" for an
        # initramfs holding fifteen of them, and then passed anyway because
        # modules-initfs.mainline asks for none - a check that cannot fail.
        got = set()
        for e in entries:
            name = Path(e).name
            for ext in (".ko", ".ko.gz", ".ko.xz", ".ko.zst"):
                if name.endswith(ext):
                    got.add(name[: -len(ext)].replace("-", "_"))
                    break
        missing = sorted(want - got)
        check(not missing, f"all {len(want)} modules-initfs names present",
              f"{len(got)} modules in the image"
              + (f"; missing {', '.join(missing)}" if missing else ""))

        # The debug shell is only reachable if these are present. telnetd is an
        # applet of busybox-extras, and 'init' does 'busybox-extras --install
        # -s' at boot to create its symlink, so the binary is what to check.
        for f, why in (("usr/bin/busybox", "the shell itself"),
                       ("usr/bin/busybox-extras", "carries the telnetd applet"),
                       ("usr/bin/unudhcpd", "hands the host an IP over USB"),
                       ("init", "parses pmos.debug-shell"),
                       ("init_functions.sh", "defines debug_shell()")):

            check(f in entries, f"{f} ({why})")

    print("\n-- cmdline --")
    cmdline = v["cmdline"]
    print(f"        {cmdline}")
    wanted = [w for ln in CMDLINE_CONF.read_text().splitlines()
              if (w := ln.strip()) and not w.startswith("#")]
    for w in wanted:
        check(w in cmdline.split(), f"cmdline has {w}")
    check("quiet" not in cmdline.split() or "loglevel=7" in cmdline.split(),
          "loglevel=7 is there to override base's quiet")

    print("\n-- rootfs image --")
    img = IMAGES / "sony-pdx246.img"
    if not img.exists():
        check(False, f"{img.name} exists",
              hint="run scripts/make-rootfs-img.sh")
    else:
        # An image of the right size that is all zeros is the dangerous case:
        # flashing it would wipe userdata and boot nothing. Check for a real
        # filesystem, not just for a file.
        sb = ext4_superblock(img)
        check(sb is not None, "is a bare ext4 filesystem (no partition table)",
              hint="no ext4 superblock at offset 1024 - is the image all zeros?")
        if sb:
            check(sb["label"] == "pmOS_root", "labelled pmOS_root",
                  f"got {sb['label']!r}")
            # The whole reason /etc/fstab is written before mkinitfs runs: the
            # UUID has to reach the vendor_boot cmdline, or the initramfs will
            # not know which partition to mount.
            want = next((a.split("=", 1)[1] for a in cmdline.split()
                         if a.startswith("pmos_root_uuid=")), None)
            check(want is not None, "cmdline carries pmos_root_uuid",
                  hint="/etc/fstab must exist before mkinitfs runs")
            check(want == sb["uuid"],
                  "cmdline pmos_root_uuid matches the filesystem UUID",
                  f"cmdline {want}, filesystem {sb['uuid']}")
            size = sb["blocks"] * sb["block_size"]
            check(size <= img.stat().st_size,
                  "the filesystem fits inside the file",
                  f"fs {size:,} bytes, file {img.stat().st_size:,} bytes")

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
