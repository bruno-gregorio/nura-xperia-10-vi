#!/bin/sh
# Try a kernel on the device without needing to touch the device.
#
#   scripts/try-kernel.sh            flash our kernel to the spare slot and boot it
#   scripts/try-kernel.sh --log      read the last boot's log back off flash
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
# The other half is the log. There is no console on this device - no exposed
# UART, no USB outside fastboot, and ramoops is scrubbed by the bootloader - so
# every image flashed here carries scripts/bootlog.py's hook, which writes the
# kernel ring buffer to the unused 'rddata' partition once storage comes up.
# That makes a dead boot readable instead of merely counted.
#
# What this does NOT fix: a kernel that hangs without panicking still needs the
# button combo to get back to fastboot. It does now leave a log behind, because
# the hook rewrites it every second rather than only on the way down.
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
# Waits for the device, printing progress to stderr so the caller can still
# capture the slot from stdout.
#
# The progress matters more than it looks. A failed round is seven boot
# attempts at roughly 54 seconds, and every one of them redraws the same Sony
# logo, so a device working its way through the retry counter is visually
# identical to a device that has hung. Three separate times during bring-up
# somebody - me included - decided it was dead and reached for the buttons at
# the three minute mark, which threw the run away and taught us nothing. A
# line every fifteen seconds saying how long is left is what stops that.
wait_for_adb() {
	limit=${1:-180}
	i=0
	while [ "$i" -lt "$limit" ]; do
		sleep 2
		if adb devices | sed 1d | grep -qE 'device$|recovery$'; then
			slot=$(adb shell getprop ro.boot.slot_suffix 2>/dev/null | tr -d '\r')
			printf '\r   %-70s\n' "up after ${i}s on slot ${slot:-unknown}" >&2
			echo "${slot:-unknown}"
			return 0
		fi
		i=$((i + 2))
		if [ $((i % 15)) -lt 2 ]; then
			# ~54s an attempt, 7 attempts, then the fallback boots.
			printf '\r   %ds elapsed, about attempt %d of 7 - the logo redrawing is normal, %ds left ' \
				"$i" "$((i / 54 + 1))" "$((limit - i))" >&2
		fi
	done
	printf '\r   %-70s\n' "nothing after ${limit}s" >&2
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
	# ...and the only way to find out why a boot died. BOOTLOG=0 leaves it
	# out, which is how you tell a kernel that fails on its own from one the
	# hook broke: the hook writes to UFS from a background job while
	# load_modules is still bringing the storage stack up, and a write into a
	# half-probed controller is a plausible way to wedge the whole I/O path.
	if [ "${BOOTLOG:-1}" = "0" ]; then
		say "BOOTLOG=0: flashing without the log hook"
	else
		"$ROOT/scripts/bootlog.py" install "$WORK/vendor_boot.img" "$WORK/vendor_boot-log.img"
		mv "$WORK/vendor_boot-log.img" "$WORK/vendor_boot.img"
	fi
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

# Boot a slot into Android and wait for it to mark itself successful.
#
# Needed because --set-active clears that flag: the bootloader has no reason
# to believe a slot it was just pointed at is good, so switching back to the
# stock slot makes it unproven and the fallback check below refuses it. Only
# a completed boot sets it again, and Android does that a little after
# sys.boot_completed rather than at it.
settle_slot() {
	say "booting slot $1 once so it marks itself successful again"
	fastboot reboot >/dev/null 2>&1 || die "could not reboot into slot $1"
	wait_for_adb 300 >/dev/null || die "slot $1 did not come up - it is not a fallback"
	i=0
	while [ "$i" -lt 150 ]; do
		[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
		sleep 3
		i=$((i + 3))
	done
	sleep 25
	need_fastboot
	[ "$(getvar "slot-successful:$1")" = "yes" ] \
		|| die "slot $1 booted but never marked itself successful"
	say "slot $1 is a safe fallback again"
}

cmd_try() {
	need_fastboot
	cur=$(getvar current-slot)
	case "$cur" in a) spare=b ;; b) spare=a ;; *) die "could not read current-slot (got '${cur:-}')" ;; esac

	# A run that hung leaves the experiment slot active, so the next round
	# starts from the wrong side and the check below would refuse. If the
	# other slot is the good one, go back to it rather than making the human
	# work it out.
	ok=$(getvar "slot-successful:$cur")
	if [ "$ok" != "yes" ] && [ "$(getvar "slot-successful:$spare")" = "yes" ]; then
		say "slot $cur is not a safe fallback but slot $spare is; going back to $spare"
		fastboot --set-active="$spare" >/dev/null 2>&1 || die "could not switch to slot $spare"
		tmp=$cur; cur=$spare; spare=$tmp
		settle_slot "$cur"
		ok=$(getvar "slot-successful:$cur")
	fi
	# Still nothing? Then the flag was cleared by a --set-active somewhere and
	# no slot has booted since. Boot the one we are on: if it is the stock
	# slot it will come up and mark itself, and if it is not, settle_slot
	# fails and says so rather than flashing over the only way back.
	if [ "$ok" != "yes" ]; then
		say "no slot is marked successful; settling the current one first"
		settle_slot "$cur"
		ok=$(getvar "slot-successful:$cur")
	fi
	[ "$ok" = "yes" ] || die "neither slot is marked successful, so there is no
       safe fallback. Boot the stock slot into Android once and let it settle."

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
	# Seven attempts at roughly 54 seconds each is already six minutes, and
	# then the fallback slot still has to boot Android. 420 was not enough.
	got=$(wait_for_adb 660) || true
	echo
	if [ -z "$got" ]; then
		echo "RESULT: nothing came up in 11 minutes."
		echo "  The kernel hung rather than panicked, so nothing reset it."
		echo "  Hold Power+VolUp, then VolUp while plugging in USB, and run:"
		echo "    scripts/try-kernel.sh --log"
	elif [ "$got" = "_$spare" ]; then
		echo "RESULT: OUR KERNEL BOOTED. adb answers on slot $got."
	else
		echo "RESULT: it crashed and the bootloader fell back to slot $got."
		echo
		cmd_log
	fi
}

# Read the log the initramfs wrote to flash. Hands-free from any state the
# device can be in: Android can be told to reboot into recovery, and recovery
# is where adb has the root needed to read a raw partition.
cmd_log() {
	if adb devices | sed 1d | grep -qE 'recovery$'; then
		say "already in recovery"
	elif adb devices | sed 1d | grep -qE 'device$'; then
		say "in Android; rebooting to recovery, where adb has root"
		adb reboot recovery || die "could not reboot to recovery"
		sleep 5
		wait_for_adb 120 >/dev/null || die "recovery never came up"
	elif fastboot devices | grep -q .; then
		cur=$(getvar current-slot)
		if [ "$(getvar "slot-successful:$cur")" != "yes" ]; then
			# Recovery borrows its device tree, command line and a
			# prepended ramdisk from vendor_boot, so it only works
			# on a slot that still has Sony's.
			for s in a b; do
				if [ "$(getvar "slot-successful:$s")" = "yes" ]; then
					say "switching to stock slot $s so recovery works"
					fastboot --set-active="$s"
					break
				fi
			done
		fi
		fastboot reboot recovery || die "could not reboot to recovery"
		sleep 5
		wait_for_adb 120 >/dev/null || die "recovery never came up"
	else
		die "no device in adb or fastboot"
	fi

	[ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = "0" ] \
		|| die "adb is not root here - this needs recovery, not Android"

	mkdir -p "$WORK"
	say "reading rddata"
	adb exec-out 'dd if=/dev/block/by-name/rddata bs=65536 count=16 2>/dev/null' \
		> "$WORK/bootlog.bin"
	echo
	"$ROOT/scripts/bootlog.py" decode "$WORK/bootlog.bin" || true

	# Wipe it, or the next run's "no log" is indistinguishable from this
	# run's log still sitting there. An all-zero rddata has to mean the
	# kernel did not get far enough to write, and nothing else.
	say "clearing rddata for the next round"
	adb shell 'dd if=/dev/zero of=/dev/block/by-name/rddata bs=65536 count=16 conv=fsync' \
		>/dev/null 2>&1 || die "could not clear rddata"
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
	--log)     shift; cmd_log "$@" ;;
	--restore) shift; cmd_restore "$@" ;;
	"")        cmd_try ;;
	*)         die "usage: $0 [--log | --restore]" ;;
esac
