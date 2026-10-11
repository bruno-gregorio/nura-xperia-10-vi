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
# kernel ring buffer to flash once storage comes up: to a raw region of the SD
# card, which both kernels can reach, or failing that to the unused 'rddata'
# partition on UFS, which only the downstream one can. That makes a dead boot
# readable instead of merely counted.
#
# The card is what makes that work under mainline, which does not drive UFS
# yet (docs/06-mainline.md, "The UFS PHY"). It is still an instrument that
# runs in the initramfs, so a mainline kernel that dies before /init leaves
# nothing on it. What is left then is the USB gadget if it comes up, and
# otherwise the retry counter as a one-bit channel: PROBE=1 reboots on purpose
# from inside the initramfs, so seven attempts and a fallback mean userspace
# was reached and one attempt and a hang mean it was not.
#
# The two kernels also need opposite handling of the device tree and the dtbo
# partition, which is read out of pmbootstrap's config rather than guessed; see
# build_vendor_boot and the flash step.
#
# What this does NOT fix: a kernel that hangs without panicking still needs the
# button combo to get back to fastboot. It does now leave a log behind, on
# either kernel once the card is up, because the hook rewrites it every second
# rather than only on the way down.
set -eu

ROOT=${TRY_KERNEL_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}

# Run from a copy of this file. sh reads a script as it goes, and a round
# lasts up to an hour, so an edit saved meanwhile changes the lines the round
# has yet to read - which once made a running round do something no version
# of the file says. The copy is unlinked as soon as it starts, and sh keeps
# reading the open file, so nothing is left behind and this file is always
# free to edit.
if [ -z "${TRY_KERNEL_ROOT:-}" ]; then
	mkdir -p "$ROOT/out/try-kernel"
	snap=$(mktemp "$ROOT/out/try-kernel/.running.XXXXXX")
	cp -- "$0" "$snap"
	TRY_KERNEL_ROOT=$ROOT exec sh "$snap" "$@"
fi
case "$0" in */.running.*) rm -f -- "$0" ;; esac
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

# DTB=path overrides the tree that goes into vendor_boot, for bisection.
# The reason this is a knob and not a constant: a device tree costs one dtc
# invocation and needs no package at all, against a couple of minutes for a
# kernel rebuild through pmbootstrap's ccache, so when the question is "which
# node in our tree kills this boot" the device tree is the cheap half of the
# search space, and it is also the half we wrote by hand. Point DTB at
# a variant built from a reduced .dts and a round answers it directly. The
# default is the tree the installed kernel package built.

die() { echo "error: $*" >&2; exit 1; }
say() { echo; echo "== $*"; }

need_fastboot() {
	command -v fastboot >/dev/null || die "fastboot not found"
	# On 2026-10-11, after round 66, the phone sat in recovery on the bus
	# as 18d1:4ee2 and the adb server listed nothing until it was
	# restarted. A round started then would have stopped here, so a
	# phone the bus has and adb does not gets one server restart.
	if ! fastboot devices | grep -q . \
		&& ! adb devices | sed 1d | grep -q . \
		&& lsusb 2>/dev/null | grep -qiE ' ID (18d1|0fce):'; then
		echo "   the bus has the phone and adb does not; restarting adb"
		adb kill-server >/dev/null 2>&1 || true
		sleep 2
		adb start-server >/dev/null 2>&1 || true
		sleep 3
	fi
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
		# scripts/dtb-stamp-ids.py, which stamps for the strict matcher the
		# appended path uses rather than the lenient one stock takes.
		dtb="${DTB:-$BOOT/dtbs/$MAINLINE_DTB}"
		[ -f "$dtb" ] || die "missing $dtb - is linux-postmarketos-qcom-sm6450 installed in the rootfs?"
		# An if, not a &&: under set -e a trailing && that tests false is
		# the whole statement's exit status, and the script would abort
		# every time DTB was unset, which is most of the time.
		if [ -n "${DTB:-}" ]; then
			say "using the device tree named by DTB, not the package's"
		fi
		say "stamping the bootloader ids onto our own device tree"
		"$ROOT/scripts/dtb-stamp-ids.py" "$dtb" "$WORK/pdx246-stamped.dtb"
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
	# hook broke: the hook writes to storage from a background job while the
	# storage stack is still coming up, and a write into a half-probed
	# controller is a plausible way to wedge the whole I/O path.
	if [ "${STAGE:-0}" = "1" ]; then
		# Answers "which module hangs?" - the question the reboot probe
		# left behind once it showed the initramfs runs. Loads the
		# modules one at a time instead of in a single modprobe -a, and
		# tries to get the USB gadget up out of its first pass so the
		# rest is visible live rather than only as elapsed time.
		say "STAGE=1: replacing /init with the staged module probe"
		"$ROOT/scripts/bootlog.py" stage "$WORK/vendor_boot.img" "$WORK/vendor_boot-stage.img"
		mv "$WORK/vendor_boot-stage.img" "$WORK/vendor_boot.img"
	elif [ "${DEVPROBE:-0}" = "1" ]; then
		# Answers "how far did the devices this port waits on get?":
		# whether qcom_scm bound and registered the Gunyah watchdog, and
		# whether the SMMU, the dwc3 core and the SD controller bound.
		# The same length-of-attempt channel as WDTPROBE, decoded with
		#   bootlog.py devdecode <total>
		say "DEVPROBE=1: replacing /init with the device probe"
		"$ROOT/scripts/bootlog.py" devprobe "$WORK/vendor_boot.img" "$WORK/vendor_boot-d.img"
		mv "$WORK/vendor_boot-d.img" "$WORK/vendor_boot.img"
	elif [ "${WDTPROBE:-0}" = "1" ]; then
		# Answers "does the Gunyah watchdog reset a hung kernel?", which
		# has to be yes before a round can be left to run unattended:
		# without it every hang waits for someone to hold the buttons.
		# The /init lets the kernel feed it, then starves it, and each
		# attempt's length says what happened:
		#   bootlog.py wdtdecode <total>
		say "WDTPROBE=1: replacing /init with the Gunyah watchdog probe"
		"$ROOT/scripts/bootlog.py" wdtprobe "$WORK/vendor_boot.img" "$WORK/vendor_boot-w.img"
		mv "$WORK/vendor_boot-w.img" "$WORK/vendor_boot.img"
		CMDLINE_ADD="gunyah_wdt.start_at_boot=1 ${CMDLINE_ADD:-}"
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
		# MARKS="base scale [panic-scale]" makes the init report how far
		# it got through the retry counter: before each step k it writes
		# base + scale*k where the USB watchdog adds it to its reset
		# delay, so a boot no host ever configures comes back after a time
		# that names the step, and how far up the USB stack it got with it.
		# The USB states need a scale of 8 to fit between steps, so
		# MARKS="4 8". One round is enough:
		#   bootlog.py markdecode <total> <base> <scale> marks-table.txt
		# panic-scale*k goes into kernel.panic for a boot that dies
		# instead; that needs nmi_watchdog=panic softlockup_panic=1 on
		# CMDLINE_ADD for a hang to count, and two rounds at different
		# panic scales to decode, see bootlog.py marks. The step table
		# lands next to the image.
		if [ -n "${MARKS:-}" ]; then
			say "MARKS=$MARKS: numbering the init's steps into kernel.panic"
			# shellcheck disable=SC2086 # two words on purpose
			"$ROOT/scripts/bootlog.py" marks "$WORK/vendor_boot.img" "$WORK/vendor_boot-m.img" "$WORK/marks-table.txt" $MARKS >/dev/null
			mv "$WORK/vendor_boot-m.img" "$WORK/vendor_boot.img"
		fi
		if [ "${BOOTLOG:-1}" = "0" ]; then
			say "BOOTLOG=0: flashing without the log hook"
		else
			"$ROOT/scripts/bootlog.py" install "$WORK/vendor_boot.img" "$WORK/vendor_boot-log.img"
			mv "$WORK/vendor_boot-log.img" "$WORK/vendor_boot.img"
			# The built-in ring buffer is 128 KiB, which a boot that
			# logs every probe outgrows before the hook first reads
			# it, and it is the oldest lines that go. This gets 4 MiB
			# at boot instead. Building that size in costs 14 MB of
			# kernel image, see docs/05-status.md. Each record
			# carries the command line, so a round id on it tells this
			# round's records from an older round's left on the card.
			CMDLINE_ADD="log_buf_len=4M pmbl.round=$(date +%Y%m%d-%H%M%S) ${CMDLINE_ADD:-}"
		fi
	fi
	# CMDLINE_ADD and CMDLINE_DEL rewrite the kernel command line in place,
	# which is possible because for header v3 and later the line lives in the
	# vendor_boot header and not in boot.img - whose own cmdline field is
	# empty on this device. scripts/patch-cmdline.py says why that is worth a
	# knob: the sanctioned route is the conf file in aports/ and a package
	# rebuild, which is ten minutes, and most of the cheap questions a blind
	# boot can be asked are command line questions. Both take space-separated
	# lists, and CMDLINE_DEL takes globs, so replacing a value is
	# CMDLINE_DEL='panic=*' CMDLINE_ADD='panic=5'. Anything that turns out to
	# matter goes into kernel-cmdline.mainline.conf before it is believed.
	if [ -n "${CMDLINE_ADD:-}" ] || [ -n "${CMDLINE_DEL:-}" ]; then
		say "patching the command line in the vendor_boot header"
		set --
		for t in ${CMDLINE_DEL:-}; do set -- "$@" -d "$t"; done
		for t in ${CMDLINE_ADD:-}; do set -- "$@" -a "$t"; done
		"$ROOT/scripts/patch-cmdline.py" "$WORK/vendor_boot.img" "$@"
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
	# Not || die: the phone can drop off the bus before fastboot hears its
	# OKAY, and fastboot then reports a failure for a reboot that happened.
	# Round 20 died on exactly that on 2026-10-07, with stock already
	# booting. Whether it really rebooted is wait_for_adb's question.
	fastboot reboot >/dev/null 2>&1 \
		|| say "fastboot reboot reported an error; waiting for the phone anyway"
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
	# one the bootloader cannot read: our tree is complete on its own and has
	# no __symbols__ for an overlay's __fixups__ to resolve against, so any
	# overlay that matched would fail to apply and a failed overlay is what
	# red-states this phone. An unreadable dtbo is what sends ABL down its
	# appended-device-tree path, which applies no overlay at all; an *empty*
	# one does not, which is why the first attempt failed.
	# scripts/no-dtbo.py has the sources; --restore puts stock's back.
	if [ "$KERNEL" = mainline ]; then
		"$ROOT/scripts/no-dtbo.py" "$WORK/dtbo-none.img"
		dtbo="$WORK/dtbo-none.img"
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
	echo "   slot-retry-count:$spare is now $(getvar "slot-retry-count:$spare")"
	# Not a bare reboot under set -e: the phone can drop off the bus before
	# fastboot hears its OKAY, and fastboot then reports a failure for a
	# reboot that happened. settle_slot has had the same guard since round
	# 20. Round 56 stopped here on it on 2026-10-08, with our kernel
	# already booting and nothing watching it. A phone still in fastboot a
	# few seconds later did not reboot, so it is asked once more.
	if ! fastboot reboot; then
		say "fastboot reboot reported an error; checking the phone"
		sleep 5
		if fastboot devices | grep -q .; then
			fastboot reboot || die "fastboot reboot failed twice"
		fi
	fi

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
		echo "  It did not boot the fallback slot, or someone held the"
		echo "  buttons. The counter says how many attempts it began, which"
		echo "  is what turns the elapsed time into a length per attempt:"
		for v in "slot-retry-count:$spare" "slot-unbootable:$spare" \
			"slot-successful:$spare" current-slot; do
			echo "    $v: $(getvar "$v")"
		done
	elif [ "$got" = "gadget" ]; then
		echo "RESULT: the initramfs got USB up. That is a live link into a"
		echo "  boot that would otherwise only be visible as elapsed time."
		echo
		if cmd_harvest && [ -n "${LIVE:-}" ]; then
			run_live
		fi
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
# Recovery brings adb up and then, a few seconds later, re-enumerates USB as
# it settles its own gadget configuration - product 0xd001, then 0x4ee2, seen
# on 2026-10-07. A read started in between is cut off part way: that night it
# took the card read down at 24 MB of 134, and the rddata read after it. So
# wait until adb has answered every second for ten seconds in a row.
settle_adb() {
	ok=0
	i=0
	while [ "$ok" -lt 10 ] && [ "$i" -lt 120 ]; do
		sleep 1
		i=$((i + 1))
		if adb get-state >/dev/null 2>&1; then
			ok=$((ok + 1))
		else
			ok=0
		fi
	done
	[ "$ok" -ge 10 ]
}

cmd_log() {
	if adb devices | sed 1d | grep -qE 'recovery$'; then
		say "already in recovery"
	elif adb devices | sed 1d | grep -qE 'device$'; then
		say "in Android; rebooting to recovery, where adb has root"
		adb reboot recovery || die "could not reboot to recovery"
		sleep 5
		wait_for_adb 120 >/dev/null || die "recovery never came up"
	elif fastboot devices | grep -q .; then
		# Before anything changes them: a round ended by hand, or by
		# the bootloader giving up, is only decodable if we know how
		# many attempts it began, and set-active resets the count.
		for s in a b; do
			say "slot $s: retry-count $(getvar "slot-retry-count:$s"), unbootable $(getvar "slot-unbootable:$s"), successful $(getvar "slot-successful:$s")"
		done
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
		# The same false failure settle_slot puts up with.
		fastboot reboot recovery \
			|| say "fastboot reboot reported an error; waiting for recovery anyway"
		sleep 5
		wait_for_adb 120 >/dev/null || die "recovery never came up"
	else
		die "no device in adb or fastboot"
	fi

	settle_adb || die "adb never stayed up for ten seconds"
	[ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = "0" ] \
		|| die "adb is not root here - this needs recovery, not Android"

	mkdir -p "$WORK"
	stamp=$(date +%Y%m%d-%H%M%S)
	# The card first: both kernels write there, and a mainline boot can
	# write nowhere else. card-sh finds it the way the hook does - by exact
	# size, with p1 present and nothing overlapping the region - and reads
	# or writes nothing if no card passes, which is also what happens if
	# recovery does not bring the card up at all.
	say "reading the log region on the SD card"
	# Read again if adb drops part way. Nothing about a cut-off read is
	# worth decoding when a whole one is a few seconds away.
	for try in 1 2 3; do
		if adb exec-out "$("$ROOT/scripts/bootlog.py" card-sh read)" \
			> "$WORK/bootlog-card.bin"; then
			card=$(wc -c < "$WORK/bootlog-card.bin")
			{ [ "$card" = 0 ] || [ "$card" = 134283264 ]; } && break
		fi
		card=$(wc -c < "$WORK/bootlog-card.bin")
		[ "$try" = 3 ] && break
		say "the card read stopped at $card bytes; reading again once adb settles"
		settle_adb || true
	done
	if [ "$card" -gt 0 ]; then
		# 2049 blocks of 64 KiB, bootlog.py's CARD_REGION_BLOCKS.
		[ "$card" = 134283264 ] \
			|| say "short read: $card bytes of 134283264, decoding what came"
		echo
		"$ROOT/scripts/bootlog.py" decode "$WORK/bootlog-card.bin" || true
		"$ROOT/scripts/bootlog.py" decode "$WORK/bootlog-card.bin" all \
			> "$WORK/bootlog-card-$stamp.txt" 2>&1 || true
		say "every attempt's record is in $WORK/bootlog-card-$stamp.txt"
		echo
	else
		say "no card in recovery that passes the checks, so none read"
	fi
	say "reading rddata"
	for try in 1 2 3; do
		adb exec-out 'dd if=/dev/block/by-name/rddata bs=65536 count=256 2>/dev/null' \
			> "$WORK/bootlog.bin" \
			&& [ "$(wc -c < "$WORK/bootlog.bin")" = 16777216 ] && break
		[ "$try" = 3 ] && die "could not read rddata whole"
		say "the rddata read was cut off; reading again once adb settles"
		settle_adb || true
	done
	echo
	"$ROOT/scripts/bootlog.py" decode "$WORK/bootlog.bin" || true

	# Wipe both, or the next run's "no log" is indistinguishable from this
	# run's log still sitting there. An empty region has to mean the kernel
	# did not get far enough to write, and nothing else. On the card that
	# is the counter and the first block of every half, which is where each
	# record's header is, and it restarts the attempt count at 1.
	if [ "$card" -gt 0 ]; then
		say "clearing the card's log region for the next round"
		adb shell "$("$ROOT/scripts/bootlog.py" card-sh clear)" \
			>/dev/null 2>&1 || die "could not clear the card's log region"
	fi
	say "clearing rddata for the next round"
	adb shell 'dd if=/dev/zero of=/dev/block/by-name/rddata bs=65536 count=256 conv=fsync' \
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
HARVEST="${HARVEST_OUT:-$ROOT/out/probe-harvest.txt}"

# LIVE=file runs a plan's own commands in the shell the harvest just used,
# before anything resets the phone: one per line, each to completion, through
# scripts/tsh.py. That is what turns a round that reaches the debug shell into
# an experiment of its own rather than only a fixed set of readings. The
# transcript goes to LIVE_OUT. The USB watchdog in the init resets a boot it
# has seen configured after CONFIGURED_HOLD_S (bootlog.py), so a file that
# needs longer starts with 'touch /pmhold'. LIVE_STEP bounds each command.
run_live() {
	out=${LIVE_OUT:-$ROOT/out/live.txt}
	say "running $LIVE in the live shell"
	python3 "$ROOT/scripts/tsh.py" -t "${LIVE_STEP:-120}" -f "$LIVE" \
		> "$out" 2>&1 < /dev/null
	echo "   tsh exited $? - the transcript is $out"
	tail -15 "$out"
}

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
	case "$cur" in a) other=b ;; b) other=a ;; *) die "could not read current-slot" ;; esac

	# Which slot to put back is "the one that is not known good", not "the
	# spare". Those are the same thing after the bootloader has fallen back,
	# which is what this assumed - but a run that red-states never boots at
	# all, so it leaves the experiment slot active and nothing falls back.
	# Restoring "the spare" then rewrites the stock slot, which is already
	# stock, and leaves the broken slot exactly as it was. Asking which slot
	# is marked successful covers both.
	if [ "$(getvar "slot-successful:$cur")" = "yes" ]; then
		good=$cur; bad=$other
	elif [ "$(getvar "slot-successful:$other")" = "yes" ]; then
		good=$other; bad=$cur
	else
		die "neither slot is marked successful, so there is no stock slot to
       keep. Restore both by hand from $STOCK before booting anything."
	fi

	say "restoring stock images on slot $bad (slot $good is the good one)"
	for p in vbmeta dtbo boot vendor_boot; do
		f="$STOCK/${p}_$bad.img"
		[ -f "$f" ] || die "missing $f"
		fastboot flash "${p}_$bad" "$f"
	done

	if [ "$good" != "$cur" ]; then
		say "making the good slot $good active again"
		fastboot --set-active="$good" || die "could not switch to slot $good"
	fi
	echo
	echo "Slot $bad is stock again, and slot $good is active."
}

case "${1:-}" in
	--log)     shift; cmd_log "$@" ;;
	--harvest) shift; cmd_harvest "$@" ;;
	--restore) shift; cmd_restore "$@" ;;
	"")        cmd_try ;;
	*)         die "usage: scripts/try-kernel.sh [--log | --harvest | --restore]" ;;
esac
