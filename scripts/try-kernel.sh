#!/bin/sh
# Try a kernel on the device without needing to touch the device.
#
#   scripts/try-kernel.sh            flash our kernel to the spare slot and boot it
#   scripts/try-kernel.sh --pstore   read the last boot's console out of ramoops
#   scripts/try-kernel.sh --restore  put the spare slot back to stock
#
# The problem this solves: a kernel that dies leaves the phone on a black
# screen with no USB, and the only way back to fastboot is holding Power and
# Volume Up by hand. That makes every iteration cost a trip to the desk.
#
# The way out is the bootloader's own A/B logic. It decrements a retry counter
# on each attempt at the active slot and resets it only when userspace reports
# the boot good; when the counter runs out it marks the slot unbootable and
# falls back to the other slot. So the experiment goes on the *inactive* slot
# while the stock images stay on the active one, and a crash lands us back in
# stock Android - where adb is waiting and 'adb reboot bootloader' starts the
# next round. kernel-cmdline.conf carries panic=5 to make a panic reset rather
# than hang, which is what feeds the counter.
#
# What this does NOT fix: a kernel that hangs without panicking. Nothing
# resets that, and it still needs the button combo. Verified 2026-10-05.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEVICE=sony-pdx246
BOOT="$ROOT/.pmb/work/chroot_rootfs_$DEVICE/boot"
STOCK="$ROOT/out/device-dump-root/stock"
WORK="$ROOT/out/try-kernel"

die() { echo "error: $*" >&2; exit 1; }
say() { echo; echo "== $*"; }

need_fastboot() {
	command -v fastboot >/dev/null || die "fastboot not found"
	if ! fastboot devices | grep -q .; then
		# Already booted? Then we can get there ourselves, which is the
		# whole point of this script.
		if adb devices | sed 1d | grep -qE 'device$|recovery$'; then
			echo "   rebooting to the bootloader over adb"
			adb reboot bootloader >/dev/null 2>&1 || true
			i=0
			while [ "$i" -lt 30 ]; do
				sleep 1
				fastboot devices | grep -q . && break
				i=$((i + 1))
			done
		fi
	fi
	fastboot devices | grep -q . \
		|| die "no device in fastboot and none reachable over adb.
       Hold Power+VolUp until it vibrates, then hold VolUp while plugging in USB."
}

getvar() { fastboot getvar "$1" 2>&1 | sed -n "s/^$1: *//p" | head -1; }

# Waits for adb and says which slot answered, so a successful boot of our
# kernel can be told apart from a fallback to the stock slot.
wait_for_adb() {
	limit=${1:-180}
	i=0
	while [ "$i" -lt "$limit" ]; do
		sleep 2
		if adb devices | sed 1d | grep -qE 'device$|recovery$'; then
			slot=$(adb shell getprop ro.boot.slot_suffix 2>/dev/null | tr -d '\r')
			echo "${slot:-unknown}"
			return 0
		fi
		i=$((i + 2))
	done
	echo ""
	return 1
}

build_vendor_boot() {
	mkdir -p "$WORK"
	[ -f "$BOOT/vendor_boot.img" ] || die "missing $BOOT/vendor_boot.img - run 'pmb install' first"
	[ -f "$STOCK/vendor_boot_b.img" ] || die "missing $STOCK/vendor_boot_b.img - run scripts/device-collect.sh from recovery"
	# Sony's device trees, because ours does not define the labels the dtbo
	# overlays reference and the bootloader rejects the result. See
	# docs/05-status.md on what the bootloader actually rejects.
	"$ROOT/scripts/swap-vendor-dtb.py" --extract "$STOCK/vendor_boot_b.img" "$WORK/sony-dtbs.bin" >/dev/null
	"$ROOT/scripts/swap-vendor-dtb.py" "$BOOT/vendor_boot.img" "$WORK/vendor_boot.img" "$WORK/sony-dtbs.bin"
}

# vbmeta for the spare slot has to come from the slot the device last ran: its
# own is an older build whose rollback index is below the one the hardware has
# stored, and anti-rollback would refuse it.
build_vbmeta() {
	src="$STOCK/vbmeta_$1.img"
	[ -f "$src" ] || die "missing $src"
	mkdir -p "$WORK"
	python3 - "$src" "$WORK/vbmeta.img" <<'PY'
import struct, sys, shutil
shutil.copyfile(sys.argv[1], sys.argv[2])
with open(sys.argv[2], 'r+b') as f:
    f.seek(120); old = struct.unpack('>I', f.read(4))[0]
    f.seek(120); f.write(struct.pack('>I', old | 0x3))
print("   vbmeta flags 0x%08x -> 0x%08x (hashtree+verification disabled)" % (old, old | 0x3))
PY
}

cmd_try() {
	need_fastboot
	cur=$(getvar current-slot)
	case "$cur" in a) spare=b ;; b) spare=a ;; *) die "could not read current-slot (got '${cur:-}')" ;; esac

	ok=$(getvar "slot-successful:$cur")
	[ "$ok" = "yes" ] || die "slot $cur is not marked successful, so it is not a
       safe fallback. Boot it into Android once and let it settle first."

	say "experiment goes on slot $spare; stock slot $cur stays as the way back"
	build_vendor_boot
	build_vbmeta "$cur"

	say "flashing slot $spare"
	fastboot flash "vbmeta_$spare"      "$WORK/vbmeta.img"
	fastboot flash "dtbo_$spare"        "$STOCK/dtbo_$cur.img"
	fastboot flash "boot_$spare"        "$BOOT/boot.img"
	fastboot flash "vendor_boot_$spare" "$WORK/vendor_boot.img"

	say "making slot $spare active (this resets its retry counter)"
	fastboot --set-active="$spare"
	fastboot reboot

	say "waiting. our kernel answering on slot _$spare is a win;"
	echo "   slot _$cur answering means it crashed and fell back."
	got=$(wait_for_adb 420) || true
	echo
	if [ -z "$got" ]; then
		echo "RESULT: nothing came up in 7 minutes."
		echo "  The kernel hung rather than panicked, so nothing reset it."
		echo "  Hold Power+VolUp, then VolUp while plugging in USB, and run:"
		echo "    scripts/try-kernel.sh --pstore"
	elif [ "$got" = "_$spare" ]; then
		echo "RESULT: OUR KERNEL BOOTED. adb answers on slot $got."
	else
		echo "RESULT: it crashed and the bootloader fell back to slot $got."
		echo "  Read what happened, no hands needed:"
		echo "    scripts/try-kernel.sh --pstore"
	fi
}

cmd_pstore() {
	need_fastboot
	cur=$(getvar current-slot)
	ok=$(getvar "slot-successful:$cur")
	if [ "$ok" != "yes" ]; then
		# Recovery borrows its device tree, command line and a prepended
		# ramdisk from vendor_boot, so it only works on a stock slot.
		for s in a b; do
			if [ "$(getvar "slot-successful:$s")" = "yes" ]; then
				say "switching to stock slot $s so recovery works"
				fastboot --set-active="$s"
				break
			fi
		done
	fi
	exec "$ROOT/scripts/grab-pstore.sh"
}

cmd_restore() {
	need_fastboot
	cur=$(getvar current-slot)
	case "$cur" in a) spare=b ;; b) spare=a ;; *) die "could not read current-slot" ;; esac
	say "restoring stock images on slot $spare"
	for p in vbmeta dtbo boot vendor_boot; do
		f="$STOCK/${p}_$spare.img"
		[ -f "$f" ] || die "missing $f"
		fastboot flash "${p}_$spare" "$f"
	done
	echo
	echo "Slot $spare is stock again. Slot $cur is still active."
}

case "${1:-}" in
	--pstore)  shift; cmd_pstore "$@" ;;
	--restore) shift; cmd_restore "$@" ;;
	"")        cmd_try ;;
	*)         die "usage: $0 [--pstore | --restore]" ;;
esac
