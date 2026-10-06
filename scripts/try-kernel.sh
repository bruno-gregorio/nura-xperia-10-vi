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
# That log is a downstream-only instrument. 'rddata' is on UFS, and the
# mainline kernel has no UFS driver - the PHY register tables are the one thing
# on this device not derivable from any source we hold, see docs/06-mainline.md
# - so under mainline the hook has nothing to write to. What is left for a
# mainline boot is the USB gadget if it comes up, and otherwise the retry
# counter as a one-bit channel: PROBE=1 reboots on purpose from inside the
# initramfs, so seven attempts and a fallback mean userspace was reached and
# one attempt and a hang mean it was not.
#
# The two kernels also need opposite handling of the device tree and the dtbo
# partition, which is read out of pmbootstrap's config rather than guessed; see
# build_vendor_boot and the flash step.
#
# What this does NOT fix: a kernel that hangs without panicking still needs the
# button combo to get back to fastboot. Downstream it does now leave a log
# behind, because the hook rewrites it every second rather than only on the way
# down.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEVICE=sony-pdx246
BOOT="$ROOT/.pmb/work/chroot_rootfs_$DEVICE/boot"
STOCK="$ROOT/out/device-dump-root/stock"
WORK="$ROOT/out/try-kernel"

# Which of the device package's two kernels is installed in the rootfs this
# will flash. pmbootstrap's own config is the right place to ask: it is what
# chose the kernel subpackage, so it is also what decided which device tree
# boot-deploy put in vendor_boot. The two need opposite handling below.
KERNEL=$(sed -n 's/^kernel *= *//p' "$ROOT/.pmb/pmbootstrap_v3.cfg" | head -1)
KERNEL=${KERNEL:-downstream}
MAINLINE_DTB="qcom/sm6450-sony-xperia-columbia-pdx246.dtb"

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
# Either half of the initramfs gadget: the network function shows up as usb0
# or under systemd's predictable name for USB ethernet, and the ACM function as
# a ttyACM port. Neither needs anything configured on the host to be visible.
usb_gadget_present() {
	[ -n "$(ls /dev/ttyACM* 2>/dev/null)" ] && return 0
	ip -o link show 2>/dev/null \
		| sed -n 's/^[0-9]*: \([^:@]*\)[:@].*/\1/p' \
		| grep -qE '^(usb[0-9]|enp[0-9]+s[0-9]+[a-z0-9]*u[0-9])' && return 0
	return 1
}

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
		# The bootloader can also give up into fastboot rather than boot
		# the fallback, and only checking adb made that look identical to
		# a dead phone - a round thrown away with the device sitting
		# there ready to be talked to.
		if fastboot devices 2>/dev/null | grep -q .; then
			printf '\r   %-70s\n' "dropped into fastboot after ${i}s" >&2
			echo "fastboot"
			return 0
		fi
		# A gadget means the initramfs got far enough to bring USB up,
		# which is worth stopping for: it is a live link into a boot
		# that would otherwise only be visible as elapsed time.
		if usb_gadget_present; then
			printf '\r   %-70s\n' "USB gadget appeared after ${i}s" >&2
			echo "gadget"
			return 0
		fi
		i=$((i + 2))
		if [ $((i % 15)) -lt 2 ]; then
			# Deliberately not a count of attempts. The retry counter
			# only advances when the bootloader begins one, so a hung
			# kernel produces exactly one - and earlier versions of
			# this line reported "attempt 4 of 7" during runs where
			# a single attempt had ever happened.
			printf '\r   %ds elapsed, %ds left - the logo redrawing is normal ' \
				"$i" "$((limit - i))" >&2
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
	if [ "$KERNEL" = mainline ]; then
		# Our own tree, which is the entire point of the mainline kernel -
		# Sony's describes downstream compatibles no mainline driver matches,
		# so carrying it here would boot a kernel that probes nothing.
		#
		# It does need the two bootloader properties stamped on, or the boot
		# chain will not select it out of the dtb area at all. They are not
		# device tree and do not belong in the source; see
		# scripts/dtb-stamp-ids.sh.
		dtb="$BOOT/dtbs/$MAINLINE_DTB"
		[ -f "$dtb" ] || die "missing $dtb - is linux-postmarketos-qcom-sm6450 installed in the rootfs?"
		say "stamping the bootloader ids onto our own device tree"
		"$ROOT/scripts/dtb-stamp-ids.sh" "$dtb" "$WORK/pdx246-stamped.dtb"
		"$ROOT/scripts/swap-vendor-dtb.py" "$BOOT/vendor_boot.img" "$WORK/vendor_boot.img" "$WORK/pdx246-stamped.dtb"
	else
		# Sony's device trees, because our downstream base does not define the
		# labels the dtbo overlays reference and the bootloader rejects the
		# result. See docs/05-status.md on what the bootloader actually
		# rejects.
		"$ROOT/scripts/swap-vendor-dtb.py" --extract "$STOCK/vendor_boot_b.img" "$WORK/sony-dtbs.bin" >/dev/null
		"$ROOT/scripts/swap-vendor-dtb.py" "$BOOT/vendor_boot.img" "$WORK/vendor_boot.img" "$WORK/sony-dtbs.bin"
	fi
	# ...and the only way to find out why a boot died. BOOTLOG=0 leaves it
	# out, which is how you tell a kernel that fails on its own from one the
	# hook broke: the hook writes to UFS from a background job while
	# load_modules is still bringing the storage stack up, and a write into a
	# half-probed controller is a plausible way to wedge the whole I/O path.
	if [ "${STAGE:-0}" = "1" ]; then
		# Answers "which module hangs?" - the question the reboot probe
		# left behind once it showed the initramfs runs. Loads the
		# modules one at a time instead of in a single modprobe -a, and
		# tries to get the USB gadget up out of its first pass so the
		# rest is visible live rather than only as elapsed time.
		say "STAGE=1: replacing /init with the staged module probe"
		"$ROOT/scripts/bootlog.py" stage "$WORK/vendor_boot.img" "$WORK/vendor_boot-stage.img"
		mv "$WORK/vendor_boot-stage.img" "$WORK/vendor_boot.img"
	elif [ "${PROBE:-0}" = "1" ]; then
		# Answers "does the initramfs run at all?" using the retry
		# counter as the only output channel: an init that reboots on
		# purpose burns all seven attempts and falls back, while a
		# kernel that never reaches userspace burns one and hangs.
		say "PROBE=1: replacing /init with the reboot probe"
		"$ROOT/scripts/bootlog.py" probe "$WORK/vendor_boot.img" "$WORK/vendor_boot-probe.img"
		mv "$WORK/vendor_boot-probe.img" "$WORK/vendor_boot.img"
	else
		# The real init needs one device quirk, and there is nowhere
		# sanctioned to put it. run_hooks /hooks does run early enough -
		# it is four lines before debug_shell and well before the rootfs
		# is touched - but it is also after setup_usb_network, which is
		# the call that needs the quirk to have happened already. So the
		# patch goes in at image-build time instead. Without it nothing
		# asks dwc3 for a role and no UDC is ever created.
		say "patching /init to ask dwc3 for peripheral mode"
		"$ROOT/scripts/bootlog.py" usbquirk "$WORK/vendor_boot.img" "$WORK/vendor_boot-q.img"
		mv "$WORK/vendor_boot-q.img" "$WORK/vendor_boot.img"
		if [ "${BOOTLOG:-1}" = "0" ]; then
			say "BOOTLOG=0: flashing without the log hook"
		else
			"$ROOT/scripts/bootlog.py" install "$WORK/vendor_boot.img" "$WORK/vendor_boot-log.img"
			mv "$WORK/vendor_boot-log.img" "$WORK/vendor_boot.img"
		fi
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

	# The dtbo the spare slot carries. Downstream wants stock's, because the
	# parrot-qrd overlay in it is where the board detail lives. Mainline wants
	# none: our tree is complete on its own and has no __symbols__ for an
	# overlay's __fixups__ to resolve against, so any overlay that matched
	# would fail to apply and a failed overlay is what red-states this phone.
	# scripts/empty-dtbo.py says more; --restore puts stock's back.
	if [ "$KERNEL" = mainline ]; then
		"$ROOT/scripts/empty-dtbo.py" "$WORK/dtbo-empty.img"
		dtbo="$WORK/dtbo-empty.img"
	else
		dtbo="$STOCK/dtbo_$cur.img"
	fi

	say "flashing slot $spare"
	fastboot flash "vbmeta_$spare"      "$WORK/vbmeta.img"
	fastboot flash "dtbo_$spare"        "$dtbo"
	fastboot flash "boot_$spare"        "$BOOT/boot.img"
	fastboot flash "vendor_boot_$spare" "$WORK/vendor_boot.img"

	say "making slot $spare active (this resets its retry counter)"
	fastboot --set-active="$spare"
	fastboot reboot

	say "waiting. our kernel answering on slot _$spare is a win;"
	echo "   slot _$cur answering means it crashed and fell back."
	# How long an attempt takes depends on which branch the staged probe's
	# watchdog is in: 15s of stall when nothing bound the gadget, 600s when
	# something did. Seven of the patient kind plus the fallback boot is
	# about 72 minutes, which is why a quiet half hour means nothing.
	waited=${WAIT:-2100}
	got=$(wait_for_adb "$waited") || true
	echo
	if [ -z "$got" ]; then
		echo "RESULT: nothing came up in $((waited / 60)) minutes."
		echo "  That is not the same as dead, and it has fooled us before."
		echo "  The bootloader only counts an attempt when it starts one, so"
		echo "  seven slow attempts plus the fallback boot run to roughly 72"
		echo "  minutes. Leave it alone and it lands on stock Android by"
		echo "  itself. To stop waiting and read what it wrote instead:"
		echo "  Hold Power+VolUp, then VolUp while plugging in USB, and run:"
		echo "    scripts/try-kernel.sh --log"
	elif [ "$got" = "fastboot" ]; then
		echo "RESULT: the bootloader gave up and dropped to fastboot."
		echo "  It did not boot the fallback slot, so read the counter:"
		echo "    fastboot getvar slot-retry-count:$spare"
	elif [ "$got" = "gadget" ]; then
		echo "RESULT: the initramfs got USB up. That is a live link into a"
		echo "  boot that would otherwise only be visible as elapsed time."
		echo
		cmd_harvest || true
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

# Pull everything off a live initramfs over whichever half of the USB gadget
# came up. The staged probe holds the phone still for ten minutes and then
# resets itself, so there is a window here and nobody has to press anything.
#
# Neither path configures the host. The network half needs an address on
# 172.16.42.0/24, which NetworkManager usually takes from the initramfs' own
# DHCP server but may not; the ACM half needs read/write on a ttyACM node,
# which is normally root:dialout. Where one of those is missing this says so
# and stops, because fixing it is a change to the host and therefore the
# user's call - scripts/console.sh prints the exact commands.
HARVEST="$ROOT/out/probe-harvest.txt"

harvest_cmds() {
	printf '%s\n' \
		'cat /pmprobe.log' \
		'echo ===STAGE===; cat /pmstage' \
		'echo ===DEFERRED===; mount -t debugfs none /sys/kernel/debug 2>/dev/null; cat /sys/kernel/debug/devices_deferred' \
		'echo ===MODULES===; cat /proc/modules' \
		'echo ===BLOCK===; ls /sys/block' \
		'echo ===UDC===; cat /sys/kernel/config/usb_gadget/g1/UDC' \
		'echo ===DMESG===; dmesg' \
		'echo ===END==='
}

cmd_harvest() {
	mkdir -p "$ROOT/out"
	host_addr=$(ip -4 -o addr show 2>/dev/null | grep -o '172\.16\.42\.[0-9]*' | head -1)
	if [ -n "$host_addr" ]; then
		say "harvesting over the network gadget (host $host_addr)"
		harvest_cmds | timeout 240 python3 "$ROOT/scripts/telnet.py" 172.16.42.1 23 \
			> "$HARVEST" 2>&1 || true
		if grep -q '===END===' "$HARVEST" 2>/dev/null; then
			say "saved to $HARVEST"
			sed -n '1,40p' "$HARVEST"
			return 0
		fi
		say "the network gadget did not answer; trying the serial port"
	fi

	acm=$(ls /dev/ttyACM* 2>/dev/null | head -1)
	if [ -n "$acm" ] && [ -r "$acm" ] && [ -w "$acm" ]; then
		say "harvesting over the ACM serial port $acm"
		stty -F "$acm" raw -echo 115200 2>/dev/null || true
		timeout 90 cat "$acm" > "$HARVEST" 2>/dev/null &
		catpid=$!
		# run_getty waits for the host to send something before it
		# spawns the shell, so that the greeting is not echoed back
		# garbled. Say hello first, then ask.
		sleep 1
		printf '\n' > "$acm" 2>/dev/null || true
		sleep 3
		harvest_cmds > "$acm" 2>/dev/null || true
		wait "$catpid" 2>/dev/null || true
		say "saved to $HARVEST"
		sed -n '1,40p' "$HARVEST"
		return 0
	fi

	say "the gadget is there but this host cannot talk to it yet"
	echo "   network: $(ip -o link show 2>/dev/null | sed -n 's/^[0-9]*: \([^:@]*\)[:@].*/\1/p' | grep -E '^(usb[0-9]|enp[0-9]+s[0-9]+[a-z0-9]*u[0-9])' | tr '\n' ' ')"
	echo "   serial:  $(ls /dev/ttyACM* 2>/dev/null | tr '\n' ' ')"
	echo
	echo "   Both fixes change host state, so they are yours to make:"
	echo "     scripts/console.sh         prints the exact commands"
	return 1
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
	--harvest) shift; cmd_harvest "$@" ;;
	--restore) shift; cmd_restore "$@" ;;
	"")        cmd_try ;;
	*)         die "usage: $0 [--log | --harvest | --restore]" ;;
esac
