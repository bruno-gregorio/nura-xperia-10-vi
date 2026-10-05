#!/bin/sh
# Read the previous boot's kernel console out of ramoops.
#
# This device has no usable serial console - the GENI port the kernel logs to
# is not exposed on the outside of the phone - but it does reserve a ramoops
# region, and the merged device tree declares it:
#
#   ramoops_region@ffd00000 { compatible = "removed-dma-pool", "ramoops";
#                             console-size = <0x40000>; reg = <0 0xffd00000 0 0xc0000>; }
#
# PSTORE_CONSOLE writes the kernel log into that DRAM, and DRAM keeps its
# contents across a warm reboot. So a kernel that dies silently still leaves
# its console behind, and the way to read it is to reboot into recovery -
# which is its own partition and runs adbd as root - and look in
# /sys/fs/pstore. Nothing else on this device gives a first boot a voice.
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
