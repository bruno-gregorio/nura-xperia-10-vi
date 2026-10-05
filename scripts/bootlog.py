#!/usr/bin/env python3
"""Give a blind boot somewhere to write its log, and read it back.

This device has no console we can reach. The UART at 0x98c000 is not brought
out to a pad, USB only enumerates in fastboot, and ramoops does not survive:
TWRP's own kernel binds the ramoops region and writes to it, yet after a clean
warm reboot /sys/fs/pstore is still empty, so something - almost certainly the
bootloader - scrubs that DRAM on every boot. Every RAM-backed log channel dies
with it.

So the log has to go to flash. The partition is 'rddata', 20 MiB of Qualcomm
ramdump staging that is all zeros on this device and is only ever written when
a debug-fused SoC collects a ramdump, which ours cannot. out/device-dump-root/
stock/rddata.img is a backup of it taken before we ever wrote there.

The trick that makes this work at all is that the kernel ring buffer is
retroactive. We cannot write to flash early - UFS is a module, loaded eighty
modules into the initramfs - but we do not have to. A single dump taken the
moment storage appears carries every message since the first line of kernel
output. So the dumper is armed early and blocks until the block device shows
up, then writes the whole history at once and keeps re-writing, which also
catches a later hang rather than only a panic.

  bootlog.py install <vendor_boot-in> <vendor_boot-out>
  bootlog.py probe   <vendor_boot-in> <vendor_boot-out>
  bootlog.py decode  <rddata-dump>

'install' only rewrites the vendor ramdisk. The dtb area is copied across
untouched, which matters: this bootloader red-states any image whose device
tree is not Sony's, so the input should already be a working image.
"""

import gzip
import io
import os
import struct
import sys

# Where the log goes, and the two numbers that prove we found the right place.
# Both come from this device's GPT, which has 4096-byte logical sectors:
# rddata is entry 96, LBA 31228923..31234042. sysfs reports start and size in
# 512-byte units, so 31228923*8 and 5120*8.
LOG_PART_START = 249831384
LOG_PART_SIZE = 40960  # 512-byte sectors, = 20 MiB
LOG_MAGIC = b"PMBOOTLOG"


# The shell half. Sourced by the initramfs init, which is a busybox ash script,
# so everything here has to be POSIX sh with busybox applets only.
BOOTLOG_SH = r'''
# Bring-up only. Written by scripts/bootlog.py - see that file for why this
# exists at all. Removing it costs nothing but the ability to debug a boot.

pmbootlog_find() {
	# Refuse to write anywhere we have not positively identified. A wrong
	# guess here would be writing over a real partition, so check the
	# geometry against rddata's own before handing the node back.
	for d in sda97 sdb97 sdc97; do
		[ -e "/sys/block/${d%??}/$d/start" ] || continue
		[ "$(cat "/sys/block/${d%??}/$d/start")" = "''' + str(LOG_PART_START) + r'''" ] || continue
		[ "$(cat "/sys/block/${d%??}/$d/size")" = "''' + str(LOG_PART_SIZE) + r'''" ] || continue
		for n in "/dev/block/$d" "/dev/$d"; do
			[ -b "$n" ] && { echo "$n"; return 0; }
		done
		# mdev may not have made a node for it. sysfs knows the
		# numbers, so make one rather than depend on hotplug having
		# been wired up by the time we get here.
		mm=$(cat "/sys/block/${d%??}/$d/dev" 2>/dev/null) || continue
		[ -n "$mm" ] || continue
		mknod "/dev/$d" b "${mm%:*}" "${mm#*:}" 2>/dev/null \
			&& { echo "/dev/$d"; return 0; }
	done
	return 1
}

pmbootlog_write() {
	# One record, rewritten in place each time. A torn write is detectable
	# because the trailer naming the same sequence number will be missing.
	{
		echo "''' + LOG_MAGIC.decode() + r''' seq=$1 uptime=$(cut -d' ' -f1 /proc/uptime)"
		echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
		echo "--- dmesg ---"
		dmesg 2>/dev/null
		echo "--- modules ---"
		cat /proc/modules 2>/dev/null
		echo "--- end seq=$1 ---"
	} > /pmbootlog.tmp 2>/dev/null
	dd if=/pmbootlog.tmp of="$2" bs=65536 conv=notrunc,fsync 2>/dev/null
}

pmbootlog_start() {
	(
		# Storage arrives in the middle of load_modules, so wait for it
		# rather than trying to run after it. Give up after two minutes:
		# if UFS never probed, no amount of waiting produces a log.
		i=0
		while :; do
			dev=$(pmbootlog_find) && break
			i=$((i + 1))
			[ "$i" -gt 120 ] && exit 0
			sleep 1
		done
		# Keep going for ten minutes. A hang leaves the last record
		# behind; a panic leaves the one before the reset.
		n=0
		while [ "$n" -lt 600 ]; do
			n=$((n + 1))
			pmbootlog_write "$n" "$dev"
			sleep 1
		done
	) &
}

pmbootlog_start
'''


# ---------------------------------------------------------------- cpio newc

def cpio_parse(buf):
    """Split a newc archive into (header_fields, name, data) tuples."""
    out, off = [], 0
    while off + 110 <= len(buf):
        if buf[off:off + 6] != b"070701":
            raise ValueError(f"not a newc header at {off}: {buf[off:off+6]!r}")
        f = [int(buf[off + 6 + i * 8: off + 14 + i * 8], 16) for i in range(13)]
        namesize, filesize = f[11], f[6]
        name = buf[off + 110: off + 110 + namesize - 1].decode("utf-8", "surrogateescape")
        dstart = (off + 110 + namesize + 3) & ~3
        data = buf[dstart: dstart + filesize]
        off = (dstart + filesize + 3) & ~3
        if name == "TRAILER!!!":
            break
        out.append([f, name, data])
    return out


def cpio_build(entries):
    """Write a newc archive back out, trailer included."""
    o = io.BytesIO()

    def put(f, name, data):
        nb = name.encode() + b"\0"
        f = list(f)
        f[6], f[11] = len(data), len(nb)
        o.write(b"070701" + b"".join(b"%08X" % v for v in f))
        o.write(nb)
        o.write(b"\0" * (-o.tell() & 3))
        o.write(data)
        o.write(b"\0" * (-o.tell() & 3))

    for f, name, data in entries:
        put(f, name, data)
    put([0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], "TRAILER!!!", b"")
    o.write(b"\0" * (-o.tell() & 511))
    return o.getvalue()


# ---------------------------------------------------------- vendor_boot v4

def sections(d):
    assert d[:8] == b"VNDRBOOT", "not a vendor_boot image"
    page, = struct.unpack_from("<I", d, 12)
    vr, = struct.unpack_from("<I", d, 24)
    hs, ds = struct.unpack_from("<2I", d, 2096)
    vrt_size, vrt_num, vrt_entry, bc = struct.unpack_from("<4I", d, 2112)
    up = lambda n: (n + page - 1) // page * page
    o_rd = up(hs)
    o_dtb = o_rd + up(vr)
    o_vrt = o_dtb + up(ds)
    o_bc = o_vrt + up(vrt_size)
    return dict(page=page, up=up, hs=hs, ramdisk=(o_rd, vr), dtb=(o_dtb, ds),
                vrt=(o_vrt, vrt_size), vrt_num=vrt_num, vrt_entry=vrt_entry,
                bc=(o_bc, bc))


def install(src, dst):
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    raw = gzip.decompress(d[o_rd:o_rd + vr])
    entries = cpio_parse(raw)

    names = {e[1] for e in entries}
    if "init" not in names:
        sys.exit("error: no /init in the vendor ramdisk - wrong image?")

    # Drop any previous install so this is idempotent.
    entries = [e for e in entries if e[1] != "bootlog.sh"]

    init = next(e for e in entries if e[1] == "init")
    text = init[2].decode()
    marker = "\n. /bootlog.sh\n"
    if marker in text:
        text = text.replace(marker, "\n")
    # Arm it as soon as /dev exists. It blocks on the block device itself, so
    # being this early costs nothing and covers a death during load_modules.
    anchor = "mount_proc_sys_dev\n"
    if anchor not in text:
        sys.exit("error: could not find mount_proc_sys_dev in init")
    text = text.replace(anchor, anchor + marker.lstrip("\n"), 1)
    init[2] = text.encode()

    mode = 0o100755
    entries.append([[0, mode, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                    "bootlog.sh", BOOTLOG_SH.encode()])

    newrd = gzip.compress(cpio_build(entries), 6)

    hdr = bytearray(d[:s["up"](s["hs"])])
    struct.pack_into("<I", hdr, 24, len(newrd))  # vendor_ramdisk_size
    # A single-entry ramdisk table has to agree about the size, or the
    # bootloader hands the kernel a truncated archive.
    o_vrt, vrt_size = s["vrt"]
    vrt = bytearray(d[o_vrt:o_vrt + vrt_size])
    if s["vrt_num"] == 1 and vrt_size >= 8:
        struct.pack_into("<I", vrt, 4, len(newrd))  # entry ramdisk_size

    up = s["up"]
    o_dtb, ds = s["dtb"]
    o_bc, bc = s["bc"]
    out = bytearray()
    out += hdr
    out += newrd + b"\0" * (up(len(newrd)) - len(newrd))
    out += d[o_dtb:o_dtb + ds] + b"\0" * (up(ds) - ds)
    out += bytes(vrt) + b"\0" * (up(vrt_size) - vrt_size)
    out += d[o_bc:o_bc + bc] + b"\0" * (up(bc) - bc)
    open(dst, "wb").write(out)

    print(f"  in   {src}")
    print(f"  out  {dst}")
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes ({len(entries)} entries)")
    print(f"  dtb area {ds} bytes, copied across untouched")


# A throwaway /init that does nothing but reboot, used to answer one question:
# does the initramfs run at all?
#
# It is the only channel left when the kernel dies before storage. The A/B
# retry counter advances every time the bootloader begins an attempt, so an
# init that deliberately resets the phone burns the counter down and falls back
# to the stock slot, which is visible from the host without a console, without
# USB during boot, and without anyone watching the screen. A kernel that never
# reaches userspace burns one attempt and then hangs, which looks completely
# different: one decrement instead of seven.
#
# Everything is spelled /bin/busybox explicitly because 'busybox --install -s'
# has not run, so none of the usual applet names resolve yet.
PROBE_INIT = """#!/bin/busybox ash
# Bring-up probe, written by scripts/bootlog.py. Not a real init.
/bin/busybox sleep 8
/bin/busybox reboot -f
# If reboot(2) was refused, do not sit here looking like a hang.
/bin/busybox sleep 120
/bin/busybox reboot -f
"""


def probe(src, dst):
    """Rebuild a vendor_boot whose /init only reboots."""
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(gzip.decompress(d[o_rd:o_rd + vr]))

    init = next((e for e in entries if e[1] == "init"), None)
    if init is None:
        sys.exit("error: no /init in the vendor ramdisk - wrong image?")
    init[2] = PROBE_INIT.encode()
    entries = [e for e in entries if e[1] != "bootlog.sh"]

    newrd = gzip.compress(cpio_build(entries), 6)
    out = _rebuild(d, s, newrd)
    open(dst, "wb").write(out)
    print(f"  in   {src}")
    print(f"  out  {dst}")
    print(f"  /init replaced with the reboot probe ({len(PROBE_INIT)} bytes)")
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes")
    print(f"  dtb area {s['dtb'][1]} bytes, copied across untouched")


def _rebuild(d, s, newrd):
    """Reassemble a vendor_boot around a new vendor ramdisk."""
    up = s["up"]
    hdr = bytearray(d[:up(s["hs"])])
    struct.pack_into("<I", hdr, 24, len(newrd))
    o_vrt, vrt_size = s["vrt"]
    vrt = bytearray(d[o_vrt:o_vrt + vrt_size])
    if s["vrt_num"] == 1 and vrt_size >= 8:
        struct.pack_into("<I", vrt, 4, len(newrd))
    o_dtb, ds = s["dtb"]
    o_bc, bc = s["bc"]
    out = bytearray()
    out += hdr
    out += newrd + b"\0" * (up(len(newrd)) - len(newrd))
    out += d[o_dtb:o_dtb + ds] + b"\0" * (up(ds) - ds)
    out += bytes(vrt) + b"\0" * (up(vrt_size) - vrt_size)
    out += d[o_bc:o_bc + bc] + b"\0" * (up(bc) - bc)
    return bytes(out)


def decode(path):
    d = open(path, "rb").read()
    if not d.startswith(LOG_MAGIC):
        nz = len(d) - d.count(0)
        sys.exit(f"error: no log here - {nz} non-zero bytes in {len(d)}.\n"
                 "       The kernel never reached the point where storage works.")
    end = d.find(b"\0")
    text = d[:end if end > 0 else len(d)].decode("utf-8", "replace")
    first = text.split("\n", 1)[0]
    seq = first.split("seq=")[1].split()[0]
    print(text)
    if f"--- end seq={seq} ---" not in text:
        print(f"\n  (record {seq} is torn - the device died while writing it)",
              file=sys.stderr)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "install":
        install(a[1], a[2])
    elif len(a) == 3 and a[0] == "probe":
        probe(a[1], a[2])
    elif len(a) == 2 and a[0] == "decode":
        decode(a[1])
    else:
        sys.exit(__doc__.strip().split("\n\n")[-2])
