#!/bin/sh
# Read the previous boot's kernel console out of ramoops.
#
# This does not work on this device. It is kept because proving that took a
# while and the next person should not have to repeat it.
#
# The theory was sound. The GENI port the kernel logs to is not exposed on the
# outside of the phone, but the merged device tree reserves a ramoops region:
#
#   ramoops_region@ffd00000 { compatible = "removed-dma-pool", "ramoops";
#                             console-size = <0x40000>; reg = <0 0xffd00000 0 0xc0000>; }
#
# PSTORE_CONSOLE writes the kernel log into that DRAM, DRAM is supposed to keep
# its contents across a warm reboot, and recovery runs adbd as root and can
# read /sys/fs/pstore.
#
# Every step of that is true except the one that matters. TWRP's own kernel
# binds the region and says so - "printk: console [ramoops-1] enabled",
# "pstore: Registered ramoops as persistent store backend" - and yet reboot
# TWRP into TWRP, which is as clean and warm as a reboot gets and involves
# nothing of ours, and /sys/fs/pstore is empty. The records written seconds
# before are gone. The only thing positioned to do that is the bootloader
# scrubbing DRAM, and nothing on the kernel side can stop it.
#
# What to use instead: scripts/bootlog.py, which has the initramfs write the
# ring buffer to the unused 'rddata' partition, where it survives. Verified
# 2026-10-05.
#
#   scripts/grab-pstore.sh            from fastboot: reboot to recovery, then read
#   scripts/grab-pstore.sh --read     already in recovery: just read
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/out/pstore"
die() { echo "error: $*" >&2; exit 1; }

if [ "${1:-}" != "--read" ]; then
	command -v fastboot >/dev/null || die "fastboot not found"
	fastboot devices | grep -q . || die "no device in fastboot mode.
       Hold Power+VolUp to force off, then hold VolUp while plugging in USB."
	echo "Rebooting into recovery. Ramoops lives in DRAM and survives this."
	# 'reboot recovery' on this bootloader, not the older 'reboot-recovery'.
	fastboot reboot recovery || die "could not reboot to recovery"
fi

echo "Waiting for recovery's adb (up to 90s)..."
i=0
while [ "$i" -lt 45 ]; do
	sleep 2
	if adb devices | sed 1d | grep -qE 'recovery$|device$'; then break; fi
	i=$((i + 1))
done
adb devices | sed 1d | grep -qE 'recovery$|device$' || die "recovery's adb never appeared"

[ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = "0" ] \
	|| die "adb is not root here - this needs recovery, not the booted system"

mkdir -p "$OUT"
echo
echo "pstore contents:"
adb shell 'ls -l /sys/fs/pstore 2>/dev/null' | tr -d '\r' | sed 's/^/    /'

got=0
for f in $(adb shell 'ls /sys/fs/pstore 2>/dev/null' | tr -d '\r'); do
	adb shell "cat /sys/fs/pstore/$f" 2>/dev/null | tr -d '\r' > "$OUT/$f"
	if [ -s "$OUT/$f" ]; then
		echo "    saved $f  ($(wc -l < "$OUT/$f") lines)"
		got=$((got + 1))
	else
		rm -f "$OUT/$f"
	fi
done

if [ "$got" -eq 0 ]; then
	echo
	echo "Nothing in pstore. That is itself a result: either the kernel never"
	echo "reached the point where pstore_ram probes, or the ramoops node was"
	echo "claimed by Qualcomm's removed-dma-pool handler instead."
	exit 0
fi

echo
echo "Saved under out/pstore/. The console record is the interesting one:"
for f in "$OUT"/console-ramoops*; do
	[ -f "$f" ] || continue
	echo
	echo "=== tail of $(basename "$f") ==="
	tail -40 "$f"
done
