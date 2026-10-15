#!/usr/bin/env python3
"""Give a blind boot somewhere to write its log, and read it back.

This device has no console we can reach. The UART at 0x98c000 is not brought
out to a pad, USB only enumerates in fastboot, and ramoops does not survive:
TWRP's own kernel binds the ramoops region and writes to it, yet after a clean
warm reboot /sys/fs/pstore is still empty, so something - almost certainly the
bootloader - scrubs that DRAM on every boot. Every RAM-backed log channel dies
with it.

So the log has to go to flash, and there are two places it can go.

The SD card is the first choice, because both kernels can reach it: sdhci-msm
is builtin on mainline, which has no UFS driver at all. The log lives in a
fixed raw region well past the rootfs partition, in space no partition
claims, and the hook proves that again before every write - the disk must be
this card, by exact size, and no partition on it may overlap the region. One
slot per boot attempt, so the seventh attempt does not overwrite the first,
and two alternating halves per slot, so a reset in the middle of a write
always leaves the previous complete record behind.

'rddata' on UFS is the fallback, for a downstream boot whose card is missing:
20 MiB of Qualcomm ramdump staging that is all zeros on this device and is only
ever written when a debug-fused SoC collects a ramdump, which ours cannot.
out/device-dump-root/stock/rddata.img is a backup of it taken before we ever
wrote there.

The trick that makes this work at all is that the kernel ring buffer is
retroactive. We cannot write to flash early - UFS is a module, loaded eighty
modules into the initramfs - but we do not have to. A single dump taken the
moment storage appears carries every message since the first line of kernel
output. So the dumper is armed early and blocks until the block device shows
up, then writes the whole history at once and keeps re-writing, which also
catches a later hang rather than only a panic.

  bootlog.py install <vendor_boot-in> <vendor_boot-out>
  bootlog.py probe   <vendor_boot-in> <vendor_boot-out>
  bootlog.py stage   <vendor_boot-in> <vendor_boot-out> [skip-these-modules]
  bootlog.py marks   <vendor_boot-in> <vendor_boot-out> <table-out> <base> <scale> [panic-scale]
  bootlog.py markdecode <round-total-seconds> <base> <scale> [table]
  bootlog.py stages  <vendor_boot> [seconds-to-fallback]
  bootlog.py decode  <rddata-dump | card-region-dump | card> [all]
  bootlog.py card-sh <read | clear>
  bootlog.py usbquirk <vendor_boot-in> <vendor_boot-out> [--no-watchdog]

'install' only rewrites the vendor ramdisk. The dtb area is copied across
untouched, which matters: this bootloader red-states any image whose device
tree is not Sony's, so the input should already be a working image.
"""

import gzip
import hashlib
import io
import os
import re
import struct
import sys
import textwrap

# Where the log goes, and the two numbers that prove we found the right place.
# Both come from this device's GPT, which has 4096-byte logical sectors:
# rddata is entry 96, LBA 31228923..31234042. sysfs reports start and size in
# 512-byte units, so 31228923*8 and 5120*8.
LOG_PART_START = 249831384
LOG_PART_SIZE = 40960  # 512-byte sectors, = 20 MiB
LOG_MAGIC = b"PMBOOTLOG"

# The SD card region. The card is a 477 GiB SDXC, GPT, 512-byte sectors, read
# off the phone: 1000243200 sectors, with pmOS_root as p1 from 1 MiB to
# 16385 MiB and nothing after it. The region starts at 32 GiB, half a card's
# worth of nothing away from p1, and is counted in 64 KiB blocks because that
# is the unit dd writes in: one counter block, then CARD_SLOTS attempts of two
# halves each.
CARD_SECTORS = 1000243200
CARD_REGION = 524288           # first block, = 32 GiB / 64 KiB
CARD_SLOTS = 8
CARD_HALF_BLOCKS = 128         # 8 MiB, ample for a 4 MiB ring buffer
CARD_REGION_BLOCKS = 1 + CARD_SLOTS * 2 * CARD_HALF_BLOCKS
CTR_MAGIC = b"PMBOOTCTR"

# Seconds from the top of /init to the USB watchdog's decision. Also the
# offset markdecode takes off a round's total, so the two live in one place.
WATCHDOG_S = 150
# How long a gadget a host has configured keeps the phone before the
# watchdog resets it anyway: rung 7, below.
CONFIGURED_HOLD_S = 600
# Uptime at which the log hook resets the phone itself, if the USB watchdog
# has not. Round 22 is why: the kernel and the hook were alive at 1138 s,
# and the watchdog, which should have reset the phone at about 360 s, had
# gone without a word. The latest the watchdog can go on its own is
# WATCHDOG_S + the highest mark, 308 with MARKS="4 8", + rung 6, under 470 s
# of uptime; this is far enough past that for markdecode to tell the two
# apart. A gadget a host has configured adds CONFIGURED_HOLD_S, as it does
# for the watchdog.
BACKUP_S = 500
# /pmhold is a lease, not a switch: see HOLD_SH.
HOLD_LOST_S = 90
HOLD_LEASE_S = 900

# A live shell stops every reset in here by creating /pmhold, and until
# round 37 nothing but that shell could take it away again. Round 37's
# commands held the phone, booting the ADSP then took the USB link with it,
# and the hold kept a phone nobody could reach until someone pressed the
# buttons. Someone in the shell can only be there over the gadget, so the
# hold now stands only while a host has the gadget configured, give or take
# HOLD_LOST_S, and for HOLD_LEASE_S after the file was last touched, which
# scripts/tsh.py does before every command. A lapsed hold is removed, so
# every other wait on it ends too, and /pmwd.log, which each record
# carries, says why.
HOLD_SH = """
pmhold_held() {
	# _hseen is per hold: each one gets its own HOLD_LOST_S of grace.
	if [ ! -e /pmhold ]; then
		_hseen=""
		return 1
	fi
	_hn=""
	read -r _hn _hx < /proc/uptime
	_hn=${_hn%.*}
	[ -n "${_hseen:-}" ] || _hseen=$_hn
	for _hu in /sys/class/udc/*; do
		case "${_hu##*/}" in
		dummy_udc*|'*') continue ;;
		esac
		_hs=""
		read -r _hs < "$_hu/state" 2>/dev/null
		case "$_hs" in
		configured|suspended) _hseen=$_hn ;;
		esac
	done
	_hm=$(/bin/busybox stat -c %Y /pmhold 2>/dev/null) || { _hseen=""; return 1; }
	_ha=$(( $(/bin/busybox date +%s) - _hm ))
	if [ $((_hn - _hseen)) -lt @LOST@ ] && [ "$_ha" -lt @LEASE@ ]; then
		return 0
	fi
	echo "hold lapsed at $_hn: gadget last configured at $_hseen, /pmhold touched $_ha s ago" >> /pmwd.log
	/bin/busybox rm -f /pmhold
	_hseen=""
	return 1
}
""".replace("@LOST@", str(HOLD_LOST_S)).replace("@LEASE@", str(HOLD_LEASE_S))


# The shell half. Sourced by the initramfs init, which is a busybox ash script,
# so everything here has to be POSIX sh with busybox applets only.
BOOTLOG_SH = (r'''
# Bring-up only. Written by scripts/bootlog.py - see that file for why this
# exists at all. Removing it costs nothing but the ability to debug a boot.

PMBL_CARD_SECTORS=@CARD_SECTORS@
PMBL_REGION=@CARD_REGION@
PMBL_SLOTS=@CARD_SLOTS@
PMBL_HALF=@CARD_HALF_BLOCKS@
PMBL_BLOCKS=@CARD_REGION_BLOCKS@

pmbootlog_node() {
	# A /dev node for the block device whose sysfs directory is $1. mdev
	# may not have made one yet; sysfs knows the numbers, so make it rather
	# than depend on hotplug having been wired up by the time we get here.
	_n=${1##*/}
	for _p in "/dev/block/$_n" "/dev/$_n"; do
		[ -b "$_p" ] && { echo "$_p"; return 0; }
	done
	_mm=$(cat "$1/dev" 2>/dev/null) || return 1
	[ -n "$_mm" ] || return 1
	mknod "/dev/$_n" b "${_mm%:*}" "${_mm#*:}" 2>/dev/null \
		&& { echo "/dev/$_n"; return 0; }
	return 1
}

pmbootlog_find_card() {
	# The card is recognised by its exact size, and the region is only
	# used if no partition on it overlaps the region - checked before
	# every write, so a card repartitioned later is refused rather than
	# written over. The disk shows up in sysfs a moment before its
	# partitions do, and an empty partition list would pass the overlap
	# test vacuously, so wait for p1, which this card always has.
	# Numbers in 512-byte sectors, which is what sysfs speaks.
	_lo=$((PMBL_REGION * 128))
	_hi=$((_lo + PMBL_BLOCKS * 128))
	for _d in /sys/block/mmcblk*; do
		[ "$(cat "$_d/size" 2>/dev/null)" = "$PMBL_CARD_SECTORS" ] || continue
		[ -e "$_d/${_d##*/}p1/start" ] || continue
		_ok=1
		for _p in "$_d/${_d##*/}"p*; do
			[ -e "$_p/start" ] || continue
			_s=$(cat "$_p/start") _z=$(cat "$_p/size")
			[ "$_s" -lt "$_hi" ] && [ $((_s + _z)) -gt "$_lo" ] && _ok=0
		done
		[ "$_ok" = 1 ] || continue
		pmbootlog_node "$_d" && return 0
	done
	return 1
}

pmbootlog_find_rddata() {
	# Refuse to write anywhere we have not positively identified. A wrong
	# guess here would be writing over a real partition, so check the
	# geometry against rddata's own before handing the node back.
	for _d in sda97 sdb97 sdc97; do
		[ "$(cat "/sys/block/${_d%??}/$_d/start" 2>/dev/null)" = "''' + str(LOG_PART_START) + r'''" ] || continue
		[ "$(cat "/sys/block/${_d%??}/$_d/size" 2>/dev/null)" = "''' + str(LOG_PART_SIZE) + r'''" ] || continue
		pmbootlog_node "/sys/block/${_d%??}/$_d" && return 0
	done
	return 1
}

pmbootlog_try() {
	# Runs "$2..." into the record, unless it has not finished in two
	# seconds. Much of what is worth reading takes a kernel lock - the
	# configfs gadget, the clock, regulator and power-domain trees - and a
	# driver stuck holding one would otherwise stop the log for good, at
	# exactly the moment it matters. A source that blocks once is reported
	# and never read again; the stuck reader is left where it is, because
	# nothing can kill it. $1 names the source, and its files.
	_n=$1
	shift
	if [ -e "/pmbl.blocked.$_n" ]; then
		echo "(blocked since uptime $(cat "/pmbl.blocked.$_n"), not read again)"
		return 0
	fi
	rm -f "/pmbl.try.$_n" "/pmbl.done.$_n"
	# All three descriptors redirected on the job itself, not just on the
	# command inside it: a job that kept the caller's stdout would hold
	# open the pipe of any $(...) this runs in, and that would wait on a
	# stuck reader just as surely as reading the file directly.
	( "$@"; : > "/pmbl.done.$_n" ) > "/pmbl.try.$_n" 2>&1 < /dev/null &
	_k=0
	while [ ! -e "/pmbl.done.$_n" ]; do
		_k=$((_k + 1))
		if [ "$_k" -gt 20 ]; then
			cut -d' ' -f1 /proc/uptime > "/pmbl.blocked.$_n"
			echo "(BLOCKED: no answer in 2 s from: $*)"
			return 0
		fi
		/bin/busybox sleep 0.1
	done
	cat "/pmbl.try.$_n"
}

pmbootlog_tasks() {
	# Every task in uninterruptible sleep, and where in the kernel it is
	# sleeping. A hang that is a sleep - a probe or a bind waiting for
	# something that never comes - is invisible to the lockup detectors,
	# and this is where it shows.
	for _p in /proc/[0-9]*; do
		_st=""
		read -r _st < "$_p/stat" 2>/dev/null || continue
		_st=${_st##*) }
		[ "${_st%% *}" = D ] || continue
		echo "pid ${_p##*/}: $(tr '\0' ' ' < "$_p/cmdline" 2>/dev/null)[$(cat "$_p/comm" 2>/dev/null)]"
		cat "$_p/stack" 2>/dev/null
	done
}

pmbootlog_ps() {
	# Every userspace task: pid, parent, state, session, the kernel
	# function it sleeps in, and its command line. A task that is only
	# asleep - S, not D - shows in neither the blocked-task list nor sysrq
	# w, and that is what the USB watchdog was in round 22, if it was
	# anything at all. Kernel threads are left out: they are children of
	# kthreadd, pid 2, and there are hundreds of them.
	for _p in /proc/[0-9]*; do
		_st=""
		read -r _st < "$_p/stat" 2>/dev/null || continue
		_st=${_st##*) }
		set -- $_st
		[ "${_p##*/}" = 2 ] || [ "$2" = 2 ] && continue
		echo "${_p##*/} ppid $2 $1 sid $4 in $(cat "$_p/wchan" 2>/dev/null): $(tr '\0' ' ' < "$_p/cmdline" 2>/dev/null)"
	done
}

pmbootlog_record() {
	# The record itself. $1 is its sequence number and $2 the attempt.
	echo "''' + LOG_MAGIC.decode() + r''' seq=$1 attempt=$2 uptime=$(cut -d' ' -f1 /proc/uptime)"
	echo "kernel: $(cat /proc/version 2>/dev/null)"
	echo "boot_id: $(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
	echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
	echo "init mark: $(cat /pmmark 2>/dev/null)"
	echo "--- dmesg ---"
	dmesg 2>/dev/null
	echo "--- init log ---"
	cat /pmOS_init.log 2>/dev/null
	echo "--- usb watchdog ---"
	cat /pmwd.log 2>/dev/null
	echo "--- processes ---"
	pmbootlog_try ps pmbootlog_ps
	echo "--- blocked tasks ---"
	pmbootlog_try tasks pmbootlog_tasks
	echo "--- modules ---"
	pmbootlog_try modules cat /proc/modules
	# What the probe itself got up to, which dmesg does not say.
	echo "--- probe log ---"
	cat /pmprobe.log 2>/dev/null
	# The three things that answer "why did this driver never probe?".
	# A driver that is waiting on a provider prints nothing at all, so
	# without these a silent permanent deferral is invisible - which is
	# exactly how dwc3-msm hid for a day.
	echo "--- deferred probes ---"
	mount -t debugfs none /sys/kernel/debug 2>/dev/null
	pmbootlog_try deferred cat /sys/kernel/debug/devices_deferred
	echo "--- udc ---"
	for _u in /sys/class/udc/*; do
		[ -e "$_u" ] && echo "${_u##*/} $(cat "$_u/state" 2>/dev/null)"
	done
	echo "gadget g1 bound to: $(pmbootlog_try gadget cat /sys/kernel/config/usb_gadget/g1/UDC)"
	echo "--- platform devices and their drivers ---"
	for _p in /sys/bus/platform/devices/*; do
		_drv=$(readlink "$_p/driver" 2>/dev/null)
		echo "${_p##*/} ${_drv##*/}"
	done
	echo "--- interrupts ---"
	cat /proc/interrupts 2>/dev/null
	# Power state, which is software bookkeeping and safe to read anywhere.
	echo "--- power domains ---"
	pmbootlog_try genpd cat /sys/kernel/debug/pm_genpd/pm_genpd_summary
	echo "--- regulators ---"
	pmbootlog_try regulators cat /sys/kernel/debug/regulator/regulator_summary
	# The clock tree reads hardware, so only on our own device tree, whose
	# only providers are GCC and RPMh - always-on registers. Stock's tree
	# has GPU, display and camera controllers as well, behind power domains
	# that may be off, and a read there can hang the bus and take the log
	# down with it. This is what says whether a gate a driver needs, like
	# the HS PHY's CLKREF, ever came on.
	if grep -q 'sony,pdx246' /proc/device-tree/compatible 2>/dev/null; then
		echo "--- clocks ---"
		pmbootlog_try clocks cat /sys/kernel/debug/clk/clk_summary
	fi
}

@HOLD_FN@
pmbootlog_start() {
	(
		# The card comes up early on mainline, where sdhci-msm is
		# builtin, and in the middle of load_modules downstream; UFS only
		# ever downstream. So wait for either, preferring the card, and
		# give up after two minutes - if neither appeared, no amount of
		# waiting produces a log.
		i=0
		while :; do
			card=$(pmbootlog_find_card) && break
			# Give the card a head start before settling for UFS.
			if [ "$i" -ge 20 ]; then
				rdd=$(pmbootlog_find_rddata) && break
			fi
			i=$((i + 1))
			[ "$i" -gt 120 ] && exit 0
			/bin/busybox sleep 1
		done
		if [ -n "$card" ]; then
			# This boot's attempt number: one more than the counter
			# block says, written back before anything else.
			c=$(dd if="$card" bs=65536 skip=$PMBL_REGION count=1 2>/dev/null \
				| head -c 64 | sed -n 's/^''' + CTR_MAGIC.decode() + r''' \([0-9][0-9]*\)$/\1/p' | head -n 1)
			c=$(( ${c:-0} + 1 ))
			echo "''' + CTR_MAGIC.decode() + r''' $c" > /pmbootctr.tmp
			dd if=/pmbootctr.tmp of="$card" bs=65536 seek=$PMBL_REGION count=1 \
				conv=notrunc,sync,fsync 2>/dev/null
			slot=$(( (c - 1) % PMBL_SLOTS ))
		else
			c=0
		fi
		# Keep going for ten minutes or so. A hang leaves the last record
		# behind; a panic leaves the one before the reset. Longer while a
		# configured gadget holds the phone, because the backup below
		# waits that much longer too.
		n=0
		bw=""
		while [ "$n" -lt 600 ] || [ -e /pmwd.hold ]; do
			# The USB watchdog's backup. In round 22 this loop ran
			# for its whole ten minutes while the watchdog, which
			# should have reset the phone long before, never did and
			# never said why - and the phone sat there until morning.
			# So past BACKUP_S of uptime this resets it itself, the
			# same way: the stacks of blocked tasks into the ring
			# buffer, one more record, which is certain to be put
			# together after them, then sysrq b. Up here, before
			# the record, so that a card that has gone missing,
			# which skips the write, does not skip this too.
			# A standing hold stops it as it stops the watchdog.
			if [ -z "$bw" ]; then
				_up=""
				read -r _up _x < /proc/uptime 2>/dev/null
				_lim=@BACKUP_S@
				[ -e /pmwd.hold ] && _lim=$((_lim + @HOLD_S@))
				if [ -n "$_up" ] && [ "${_up%.*}" -ge "$_lim" ] && ! pmhold_held; then
					echo "backup: no reset by uptime $_up, the log hook resets after record $((n + 1))" >> /pmwd.log
					[ -w /proc/sysrq-trigger ] && echo w > /proc/sysrq-trigger
					bw=$n
				fi
			elif ! pmhold_held; then
				[ -w /proc/sysrq-trigger ] && echo b > /proc/sysrq-trigger
				/bin/busybox reboot -f -n
			fi
			n=$((n + 1))
			pmbootlog_record "$n" "$c" > /pmbootlog.tmp 2>/dev/null
			# The trailer carries the md5 of everything above it, so a
			# record that a reset tore - or spliced with an older one
			# underneath - can never pass for a complete one.
			echo "--- end seq=$n attempt=$c md5=$(md5sum < /pmbootlog.tmp | cut -d' ' -f1) ---" \
				>> /pmbootlog.tmp
			if [ -n "$card" ]; then
				# Same disk, same layout, or no write at all.
				[ "$(pmbootlog_find_card)" = "$card" ] || { /bin/busybox sleep 1; continue; }
				# Alternate halves, so the write that a reset tears
				# is never the only copy. conv=sync pads the last
				# block with zeros, so every record ends in a zero
				# and a shorter one cannot run on into the tail of
				# a longer one written there before it.
				seek=$(( PMBL_REGION + 1 + (slot * 2 + n % 2) * PMBL_HALF ))
				# The USB watchdog waits for this to go before it
				# resets the phone.
				: > /pmbl.busy
				dd if=/pmbootlog.tmp of="$card" bs=65536 seek=$seek \
					count=$PMBL_HALF conv=notrunc,sync,fsync 2>/dev/null
				rm -f /pmbl.busy
				# The watchdog waits on this for a record made
				# after its stack dump.
				echo "$n" > /pmbl.seq
			else
				# rddata has room for two halves as well.
				: > /pmbl.busy
				dd if=/pmbootlog.tmp of="$rdd" bs=65536 \
					seek=$(( n % 2 * PMBL_HALF )) count=$PMBL_HALF \
					conv=notrunc,sync,fsync 2>/dev/null
				rm -f /pmbl.busy
				echo "$n" > /pmbl.seq
			fi
			/bin/busybox sleep 1
		done
	) &
}

pmbootlog_start
''').replace("@CARD_SECTORS@", str(CARD_SECTORS)).replace(
    "@CARD_REGION@", str(CARD_REGION)).replace(
    "@CARD_SLOTS@", str(CARD_SLOTS)).replace(
    "@CARD_HALF_BLOCKS@", str(CARD_HALF_BLOCKS)).replace(
    "@CARD_REGION_BLOCKS@", str(CARD_REGION_BLOCKS)).replace(
    "@BACKUP_S@", str(BACKUP_S)).replace(
    "@HOLD_S@", str(CONFIGURED_HOLD_S)).replace(
    "@HOLD_FN@", HOLD_SH.strip("\n"))

# The log hook and the USB watchdog are background jobs of /init, and on a
# boot that goes on into the rootfs they outlive it: init_2nd.sh kills only
# udevd, syslogd, unudhcpd and every "sh", and they are "init". Their root
# stays the initramfs, and switch_root, util-linux's, takes two things away
# from it. It moves /dev, /proc and /sys into the new root, and it deletes
# everything on the initramfs that is not a mount of its own: busybox, the
# musl loader, and /bin, /sbin and /lib, which are symlinks into /usr on
# this initramfs. From then on every command the jobs run that is not an
# ash builtin fails, and so does every read of /proc or /sys and every write
# to the card. The log stops at the switch, the watchdog can no longer
# reset, and the log hook's backup resets when its counting happens to run
# out.
#
# So, last thing before the switch, this hook:
# - puts a static busybox and a link for each applet on a tmpfs, and turns
#   /bin and /sbin into directories with that mounted on them. The jobs name
#   /bin/busybox, and /bin is on their PATH after /usr/bin, which the switch
#   deletes. /usr/bin itself is left alone: the rest of init_2nd.sh needs
#   its tools, switch_root among them. A static busybox needs no loader, so
#   /lib can go; the image's own busybox is dynamic. This one is Alpine's
#   busybox-static, the same version as the initramfs' own, and goes into
#   the ramdisk as KEEP_BB. out/ is not in git: it is bin/busybox.static
#   from edge/main/aarch64/busybox-static-1.38.0-r7.apk on
#   dl-cdn.alpinelinux.org, checked against that APKINDEX's checksum, saved
#   as out/tools/busybox.static.
# - stacks a second mount on /proc, /sys and /dev. switch_root moves the
#   mount it finds at each path, which is the top one, and the jobs keep the
#   one underneath with everything mounted inside it, configfs and debugfs
#   included. /proc gets a fresh proc, which is a superblock of its own, so
#   the new root's is bare and OpenRC mounts the rest. sysfs and devtmpfs
#   have one superblock each, and the kernel will not mount a superblock
#   where it is already the top mount ("Refuse the same filesystem on the
#   same mount point", do_add_mount() in fs/namespace.c): round 83's fresh
#   ones failed with EBUSY, the switch took the only ones there were, and
#   the jobs lost the card and the UDC with them. A bind has no such rule,
#   so /sys and /dev get recursive binds of themselves, and the new root the
#   same trees it would have had without this hook.
#
# The jobs' own files at the top of the initramfs, /pmwd.log, /pmwd.hold and
# /pmhold among them, still go with the switch. Losing /pmwd.hold puts the
# log hook's backup back at BACKUP_S of uptime, so a host that wants the
# booted system for longer holds it as it would the initramfs, through the
# jobs' root: /proc/<pid>/root/pmhold, for a pid whose root has /pmkeep.
KEEP_HOOK = "hooks-cleanup/99-pdx246-keep.sh"
KEEP_BB = "pmkeep-busybox"
KEEP_BB_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "out", "tools", "busybox.static")
KEEP_SH = r"""#!/bin/sh
# pdx246: keep the log hook's and the USB watchdog's tools, /proc, /sys and
# /dev across switch_root; see scripts/bootlog.py, KEEP_SH.
k=/pmkeep
log() {
	echo "pdx246 keep: $*" > /dev/kmsg
	echo "keep: $*" >> /pmwd.log
}
[ -x /@KEEP_BB@ ] || { log "no /@KEEP_BB@"; exit 0; }
mkdir -p "$k" && mount -t tmpfs -o mode=0755,size=8m pmkeep "$k" \
	|| { log "no tmpfs"; exit 0; }
mkdir -p "$k/bin"
cp /@KEEP_BB@ "$k/bin/busybox" || { log "no copy"; exit 0; }
b="$k/bin/busybox"
"$b" --install -s "$k/bin" || { log "no applets"; exit 0; }
done=""
for d in /bin /sbin; do
	# A symlink is a file, which switch_root deletes; a directory with a
	# mount on it stays. For the moment in between, the jobs find their
	# commands through /usr/bin, all but /bin/busybox itself.
	if [ -L "$d" ]; then
		"$b" rm "$d" && "$b" mkdir "$d" || continue
	fi
	"$b" mount --bind "$k/bin" "$d" && done="$done $d"
done
"$b" mount -t proc proc /proc && done="$done /proc"
"$b" mount --rbind /sys /sys && done="$done /sys"
"$b" mount --rbind /dev /dev && done="$done /dev"
log "kept$done"
"""

# ---------------------------------------------------------------- cpio newc

def rd_unpack(blob):
    """The vendor ramdisk's cpio, from gzip or from zstd.

    postmarketos-mkinitfs 2.12 writes zstd where the versions before it
    wrote gzip. Both kernels take either, and what this writes back is
    always gzip.
    """
    if blob[:2] == b"\x1f\x8b":
        return gzip.decompress(blob)
    if blob[:4] == b"\x28\xb5\x2f\xfd":
        from compression import zstd  # Python 3.14
        return zstd.decompress(blob)
    sys.exit(f"error: the vendor ramdisk is neither gzip nor zstd ({blob[:4].hex()})")


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
    raw = rd_unpack(d[o_rd:o_rd + vr])
    entries = cpio_parse(raw)

    names = {e[1] for e in entries}
    if "init" not in names:
        sys.exit("error: no /init in the vendor ramdisk - wrong image?")

    # Drop any previous install so this is idempotent.
    entries = [e for e in entries
               if e[1] not in ("bootlog.sh", KEEP_HOOK, KEEP_BB)]

    init = next(e for e in entries if e[1] == "init")
    text = init[2].decode()
    marker = "\n. /bootlog.sh\n"
    if marker in text:
        text = text.replace(marker, "\n")
    # Arm it as soon as /dev exists. It blocks on the block device itself, so
    # being this early costs nothing and covers a death during load_modules.
    #
    # The anchor is the call on a line of its own, not the first place the
    # words appear: USB_WATCHDOG's comment has a line ending in them too, and
    # from 2026-10-05 until this was fixed the hook went in there - the first
    # thing /init ran, before the applets were installed or /proc and /sys
    # were mounted. Nothing in the hook works that early, and its wait loop,
    # which counts iterations, could spend all of them before sleep existed.
    anchor = re.search(r"^mount_proc_sys_dev\n", text, re.M)
    if not anchor:
        sys.exit("error: could not find the mount_proc_sys_dev call in init")
    if text.find("busybox --install") > anchor.start():
        sys.exit("error: mount_proc_sys_dev comes before busybox --install"
                 " in this init, so the hook would run without its applets")
    text = text[:anchor.end()] + marker.lstrip("\n") + text[anchor.end():]
    init[2] = text.encode()

    mode = 0o100755
    entries.append([[0, mode, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                    "bootlog.sh", BOOTLOG_SH.encode()])
    # The same mode, under the directory init_2nd.sh runs last of all before
    # switch_root. It is only reached on a boot that goes on into the rootfs.
    if not any(e[1] == KEEP_HOOK.split("/")[0] for e in entries):
        sys.exit("error: no /hooks-cleanup in the vendor ramdisk")
    if os.path.isfile(KEEP_BB_SRC):
        entries.append([[0, mode, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                        KEEP_HOOK,
                        KEEP_SH.replace("@KEEP_BB@", KEEP_BB).encode()])
        entries.append([[0, mode, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                        KEEP_BB, open(KEEP_BB_SRC, "rb").read()])
    else:
        print(f"  warning: no {KEEP_BB_SRC}, so the log hook and the"
              " watchdog stop at switch_root")

    newrd = gzip.compress(cpio_build(entries), 6)

    # Reassembly is _rebuild's job. This used to carry its own copy of it,
    # and the copy had the vendor ramdisk table bug described there while the
    # original did not, which is the usual fate of duplicated header surgery.
    open(dst, "wb").write(_rebuild(d, s, newrd))
    ds = s["dtb"][1]

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
# How long the probe sleeps before rebooting, overridable with PROBE_SLEEP.
#
# It is a parameter and not a constant because it is the slope of the only
# measurement this device allows. A round's total is
# ATTEMPTS * (boot + sleep + reboot) + FALLBACK_BOOT, so running the same
# probe at two different sleeps and differencing cancels every unknown in
# that expression except ATTEMPTS - which is how we know the probe ran at
# all, rather than inferring it from one number and an assumed constant.
PROBE_SLEEP = int(os.environ.get("PROBE_SLEEP", "8"))

PROBE_INIT = """#!/bin/busybox ash
# Bring-up probe, written by scripts/bootlog.py. Not a real init.
/bin/busybox sleep %d
/bin/busybox reboot -f
# If reboot(2) was refused, do not sit here looking like a hang.
/bin/busybox sleep 120
/bin/busybox reboot -f
""" % PROBE_SLEEP


def _replace_init(src, dst, text, what):
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(rd_unpack(d[o_rd:o_rd + vr]))

    init = next((e for e in entries if e[1] == "init"), None)
    if init is None:
        sys.exit("error: no /init in the vendor ramdisk - wrong image?")
    init[2] = text.encode()
    entries = [e for e in entries if e[1] != "bootlog.sh"]

    newrd = gzip.compress(cpio_build(entries), 6)
    out = _rebuild(d, s, newrd)
    open(dst, "wb").write(out)
    print(f"  in   {src}")
    print(f"  out  {dst}")
    print(f"  /init replaced with the {what} ({len(text)} bytes)")
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes")
    print(f"  dtb area {s['dtb'][1]} bytes, copied across untouched")


def probe(src, dst):
    """Rebuild a vendor_boot whose /init only reboots."""
    _replace_init(src, dst, PROBE_INIT, "reboot probe")


# Modules held back from the first pass. The first pass exists to get the USB
# gadget up before anything has had a chance to hang, so it leaves out
# everything the gadget cannot need: the whole storage chain, thermal and DCVS,
# the Gunyah hypervisor drivers, crypto, display, and the SM4450 ("ravelin")
# controllers this SoC has its own copy of. None of them is dropped - the
# second pass loads them in exactly the order the real list has them.
# Held back from the first pass. dispcc-parrot used to be in here, which was a
# mistake that cost most of a day: the display RSC at af20000 declares
# "clocks = <&dispcc 0x42>", so fw_devlink will not let it probe until the
# display clock controller has. No RSC means no bcm_voter child, and gem_noc
# lists that voter in qcom,bcm-voters, so interconnect@19100000 never
# registers - and dwc3-msm, which wants a ddr-usb path through it, defers for
# ever without printing a line. The display clock controller is a USB
# dependency on this SoC, by way of two nodes that have nothing to do with
# either.
STAGE_DEFER = """
gh_virt_wdt qcom-pmu-lib qcom_wdt_core dcvs_fp qcom-dcvs
dispcc-ravelin gcc-ravelin pinctrl-ravelin qnoc-ravelin
qcom-cpufreq-hw sched-walt qcom_tsens thermal_pause cpu_hotplug bcl_pmic5
gh_msgq gh_rm_drv gh_arm_drv gh_ctrl gh_dbl
icc-debug mem_buf_dev mem_buf mem-hooks memory_dump_v2
msm_dma_iommu_mapping msm_geni_serial msm-geni-se qcom_cpu_vendor_hooks
qcom-dload-mode qcom_dma_heaps qrtr msm_qmp qti-regmap-debugfs
nvmem_qcom-spmi-sdam rtc-pm8xxx tmecom-intf
sdhci-msm-scaling cqhci sdhci-msm
phy-qcom-ufs phy-qcom-ufs-qrbtc-sdm845 ufs_qcom phy-qcom-ufs-qmp-v4-parrot
crypto-qti-common crypto-qti-hwkm hwkm ufshcd-crypto-qti
"""

# A /init that loads the modules one at a time and opens every channel it can
# before doing so. Not a real init: it stops well short of a root filesystem.
#
# The real init loads all 89 modules with a single "modprobe -a", so one module
# that wedges stops the boot with nothing to show for it - which is exactly the
# state this port has been stuck in. This opens two channels first, in order of
# usefulness:
#
#   USB.  By symbol dependency the gadget needs eleven of those modules and
#         none of the storage ones, so loading a subset first can get a live
#         link up before the boot dies. Then everything is visible as it
#         happens, over the network gadget and the ACM serial port.
#   Time. A watchdog notices when module loading stops making progress and
#         delays the reset by one second per step already done, so the time the
#         bootloader takes to run its retry counter down names the step that
#         hung. It needs no storage, no USB and no console, which is all that
#         is left when the gadget does not come up - and it is hands-free,
#         because a deliberate reset keeps feeding the retry counter.
STAGE_INIT = r"""#!/bin/busybox ash
# Staged bring-up probe, written by scripts/bootlog.py. Not a real init.
#
# Nothing in here may run before the watchdog. The first version of this probe
# armed it after mount_proc_sys_dev, which meant the handful of steps before
# that - sourcing init_functions.sh, installing the busybox applets, mounting
# /proc itself - had no net under them at all. The phone hung in exactly that
# window and sat there for 22 minutes. So the watchdog goes first, and it is
# written to need nothing: no applet links, no /proc, no storage. The reboot
# probe already proved that a bare busybox sleep and reboot -f work this early.
B=/bin/busybox
$B echo 0 > /pmstage

@HOLD_FN@

pmstage_reset() {
	# A live shell can stop the clock. Every reset in here is on a timer
	# measured in minutes, which is right for a boot nobody is watching and
	# wrong for one where something is mid-operation - writing a rootfs to
	# the SD card takes longer than the probe's own patience. Nothing
	# creates /pmhold on its own, so an unattended boot still resets, and
	# a hold lapses once nobody can be holding it (HOLD_SH).
	while pmhold_held; do $B sleep 5; done
	# sysrq-b is emergency_restart(), which skips the orderly shutdown a
	# wedged driver can block, so prefer it - but it needs /proc, which may
	# be exactly what did not happen yet.
	[ -w /proc/sysrq-trigger ] && $B echo b > /proc/sysrq-trigger
	$B reboot -f
	# reboot(2) refused. Do not sit here looking like a hang.
	$B sleep 90
	$B reboot -f
}

# The stall watchdog. Fifteen seconds is generous: on Sony's own kernel this
# hardware brings UFS up 0.67s into the boot and the largest gap anywhere in
# its log is 2.3s, so nothing here legitimately takes that long.
(
	last=-1
	stall=0
	while :; do
		cur=$($B cat /pmstage 2>/dev/null) || cur=-1
		if [ "$cur" = "$last" ]; then
			stall=$((stall + 1))
		else
			stall=0
			last=$cur
		fi
		# Once the gadget is up the step no longer has to be read off
		# the clock, so stop hurrying and leave time to look.
		if [ -e /pmusb ]; then
			[ "$stall" -ge 600 ] && break
		else
			[ "$stall" -ge 15 ] && break
		fi
		$B sleep 1
	done
	n=$last
	[ "$n" -ge 0 ] 2>/dev/null || n=0
	[ "$n" -gt 99 ] && n=99
	# One second per step completed. Seven attempts multiply that by seven,
	# so the time the bootloader takes to give up names the step.
	$B sleep "$n"
	pmstage_reset
) &
PMWD1=$!

# A backstop under the backstop, in case the watchdog above cannot run - if a
# wedged driver holds something the shell needs to fork, every loop in this
# file stops with it. 240s is well clear of the watchdog's own worst case of
# 15 + 99, so this firing at all is itself the finding. It defers to the live
# link for the same reason the watchdog does: once there is something to look
# at, resetting the phone is the last thing anyone wants.
(
	$B sleep 240
	[ -e /pmusb ] || pmstage_reset
	$B sleep 600
	pmstage_reset
) &
PMWD2=$!

LOG=/pmprobe.log
mark() {
	$B echo "$1" > /pmstage
	$B echo "[$1] $2" >> "$LOG"
	$B echo "[pmprobe $1] $2"
}

mark 1 "busybox --install"
$B --install -s
mark 2 "busybox-extras --install"
$B-extras --install -s 2>/dev/null

# Everything below is exported, because the stock second stage expects it.
# init.sh does this on its line 5 and init_2nd.sh's own comment relies on it:
# nothing in init_2nd.sh parses the command line or reads deviceinfo, it just
# uses root_uuid, debug_shell, nosplash and the deviceinfo_* keys as if they
# were already there. They are plain shell variables unless something exports
# them, and a plain variable does not survive the exec in the handoff below -
# so without this, stage 2 would look for the rootfs with no UUID to look for
# and skip the debug shell that is its only way back in.
set -a
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
IN_CI=false
LOG_PREFIX="[pmOS-rd]"
mark 3 "sourcing init_functions.sh"
. /init_functions.sh
mark 4 "sourcing deviceinfo"
. /usr/share/misc/source_deviceinfo 2>/dev/null

mark 5 mount_proc_sys_dev
mount_proc_sys_dev
mkdir -p /tmp

# Make a wedged modprobe recoverable by the kernel as well as by the shell.
# khungtaskd panics on a task stuck uninterruptible, which is what a driver
# waiting forever on a clock, a regulator or firmware looks like, and panic=5
# on the command line turns that into a reset.
mark 6 "sysrq and hung_task knobs"
echo 1  > /proc/sys/kernel/sysrq
echo 1  > /proc/sys/kernel/hung_task_panic
echo 20 > /proc/sys/kernel/hung_task_timeout_secs

mark 7 parse_cmdline
parse_cmdline < /proc/cmdline
mark 8 setup_firmware_path
setup_firmware_path
mark 9 setup_mdev
setup_mdev

# Split the real list in two, keeping its order in both halves.
LIST=/lib/modules/initramfs.load
ALL=$(grep -v '^[[:space:]]*#' "$LIST" | tr -s ' \t\n' ' ')
PASS1=""
PASS2=""
SKIPPED=""
for m in $ALL; do
	# A module named in the skip list is left out of the boot entirely.
	# Once the probe has found one that hangs, that is how you find out
	# whether the boot gets any further without it.
	case " @SKIP@ " in
	*" $m "*) SKIPPED="$SKIPPED $m" ; continue ;;
	esac
	case " @DEFER@ " in
	*" $m "*) PASS2="$PASS2 $m" ;;
	*)        PASS1="$PASS1 $m" ;;
	esac
done
[ -n "$SKIPPED" ] && echo "skipping:$SKIPPED" >> "$LOG"

i=9
for m in $PASS1; do
	i=$((i + 1))
	mark "$i" "pass1 modprobe $m"
	modprobe "$m" >> "$LOG" 2>&1
done

# dwc3-msm probes, registers a role switch, and then sits in "none" mode: it
# never creates its dwc3@a600000 core child, so no real UDC is ever registered
# and the gadget has nothing to bind to but dummy_udc.0. The DT says
# dr_mode = "otg" with usb-role-switch, so something has to ask for a role.
# Nothing in an initramfs does - on Android that comes from the charger stack.
# The driver's own "mode" attribute is the short way to ask.
mark 55 "forcing peripheral mode on the ssusb wrapper"
for d in /sys/bus/platform/devices/*.ssusb; do
	[ -w "$d/mode" ] || continue
	echo peripheral > "$d/mode" 2>>"$LOG"
	echo "wrote peripheral to $d/mode" >> "$LOG"
	[ -w "$d/usb_data_enabled" ] && echo 1 > "$d/usb_data_enabled" 2>>"$LOG"
done
# The core comes up from a work queue, so the UDC appears a moment later.
# Re-mark on every pass: the stall watchdog resets the phone after fifteen
# seconds of no progress, and a wait that looks like a hang would be reset.
w=0
while [ "$w" -lt 12 ]; do
	real=""
	for u in /sys/class/udc/*; do
		case "${u##*/}" in
		dummy_udc*|'*') ;;
		*) real="${u##*/}" ;;
		esac
	done
	[ -n "$real" ] && break
	w=$((w + 1))
	mark 56 "waiting for a real UDC, ${w}s"
	sleep 1
done
echo "udc wait ended after ${w}s, real udc: ${real:-none}" >> "$LOG"

mark 60 "udc: $(ls /sys/class/udc 2>/dev/null | tr '\n' ' ')"
mark 61 setup_usb_network
setup_usb_network >> "$LOG" 2>&1
mark 62 setup_usb_acm_configfs
setup_usb_acm_configfs >> "$LOG" 2>&1
mark 63 setup_usb_configfs_udc
setup_usb_configfs_udc >> "$LOG" 2>&1
mark 64 start_unudhcpd
start_unudhcpd >> "$LOG" 2>&1

if [ -n "$(cat /sys/kernel/config/usb_gadget/g1/UDC 2>/dev/null)" ]; then
	# A live link. Tell both watchdogs to stop hurrying, then put a shell
	# on every way in and stream progress at whoever is listening.
	touch /pmusb
	mark 65 "gadget bound, opening shells"
	cat > /sbin/pmos_getty <<-'EOF'
	#!/bin/sh
	exec /bin/sh -l
	EOF
	chmod +x /sbin/pmos_getty
	telnetd -b "${HOST_IP}:23" -l /sbin/pmos_getty &
	run_getty ttyGS0
	( tail -f "$LOG" > /dev/ttyGS0 2>/dev/null ) &
else
	mark 66 "no gadget - falling back to the retry-counter channel"
fi

mark 70 "arming the flash log"
. /bootlog.sh

i=70
for m in $PASS2; do
	i=$((i + 1))
	mark "$i" "pass2 modprobe $m"
	modprobe "$m" >> "$LOG" 2>&1
done

mark 99 "all modules loaded"
{
	echo "--- deferred probes ---"
	mount -t debugfs none /sys/kernel/debug 2>/dev/null
	cat /sys/kernel/debug/devices_deferred 2>/dev/null
	echo "--- block devices ---"
	ls /sys/block 2>/dev/null
} >> "$LOG" 2>&1

# Hand the boot back to the stock second stage, if asked to.
#
# This probe exists because loading ninety modules at once was a hang risk,
# and the order in here is the one that is known to work on this phone. Stock
# stage 2 starts by having udev load everything, which by now has nothing left
# to do, and then goes on to the debug shell and switch_root. So handing over
# here is the shortest route to a real boot that does not depend on knowing
# where stock stage 1 wedges - and it is only reached after the gadget is
# bound and telnet is listening, so it is never a step taken blind.
#
# The watchdogs are retired rather than left running. Both would fire minutes
# from now into a session somebody is using, or worse, into a system that has
# already switched root - init_2nd.sh's "kill $(pidof sh)" will not find them,
# because this script runs as busybox ash and not as sh. Nothing is armed in
# their place on purpose: by this point there is a live link in, which is the
# thing a watchdog exists to recover.
if [ -e /pmhandoff ] && [ -e /init_2nd.sh ]; then
	mark 100 "handing off to the stock second stage"
	kill $PMWD1 $PMWD2 2>/dev/null
	# The 20s hung_task tripwire set above is right for modprobe, which
	# should never block that long, and wrong for what comes next: e2fsck,
	# resize2fs and switch_root all queue real I/O against an SD card that
	# writes at 2.9 MB/s, and a task sitting in D state for twenty seconds
	# there is ordinary. With panic=5 on the command line it would reset a
	# boot that was merely slow.
	echo 0 > /proc/sys/kernel/hung_task_panic
	# setup_usb_network and start_unudhcpd refuse to run twice - their guard
	# is /tmp/_setup_usb_network, a file, which survives the exec - so the
	# gadget this probe brought up carries into stage 2 untouched.
	#
	# Stage 2's own debug shell is the one thing that does touch it, and on
	# this phone it is fatal. Its exit path unlinks the ACM function from a
	# still-bound gadget and then calls setup_usb_configfs_udc, which clears
	# g1/UDC and writes it again - and the rebind does not come back here,
	# because dwc3-msm falls out of peripheral mode and nothing in an
	# initramfs asks it for a role again. Observed: the gadget vanished the
	# moment the shell was released and never re-enumerated, which on a phone
	# with no working display is a boot nobody can reach.
	#
	# Nothing is lost by refusing it. The probe opened its own shell forty
	# marks earlier, before any of this, so the inspection point that
	# pmos.debug-shell exists to provide is already there and already used.
	debug_shell=n
	exec /init_2nd.sh
fi

# Nothing left to find out on its own. Hold still while anyone connected has
# a look, then hand the phone back to the loop by resetting it.
sleep 600
pmstage_reset
"""


# The one device quirk the real init cannot do without. postmarketos-mkinitfs
# calls load_modules and then setup_usb_network with nothing in between, and
# run_hooks is only called from init_2nd.sh, after the rootfs is mounted - so
# there is no sanctioned place to put this. Patching /init as the image is
# built is honest about what it is and keeps it in our tree rather than in a
# fork of someone else's package.
# Armed before load_modules, because that is where the real init can die. It
# has no watchdog of its own: load_modules is a single modprobe -a, and a
# module that never returns takes the whole boot with it, in silence, for
# ever. Nothing resets the phone, so the bootloader never begins another
# attempt and the retry counter never moves - the one failure mode that cannot
# be recovered without someone pressing buttons.
# WATCHDOG_S and CONFIGURED_HOLD_S are at the top of the file, next to the
# log hook's BACKUP_S, which is built around them.

USB_WATCHDOG = """
# --- pdx246: make a hung boot recoverable ----------------------------------
# First thing in the file, and written to need nothing: no applet symlinks,
# because "busybox --install -s" has not run yet, and no /proc, because
# mount_proc_sys_dev has not either. That matters - mount_proc_sys_dev
# modprobes libcomposite, so there is module loading above the old position of
# this block, and a hang there left the phone silent for ever: nothing resets
# it, so the bootloader never starts another attempt and the A/B retry counter
# never moves. Armed here, a hang becomes a reset loop instead, and seven of
# those end in Android, which we can read.
#
# hung_task_panic is deliberately not set. It was, with a 20 second timeout,
# which panics the kernel over any task that blocks for 20 seconds - ordinary
# on a bring-up boot, where a probe waits on firmware and udevadm settle
# drains ninety modules' events. It caught nothing this timer does not, since
# both need the kernel to still be scheduling userspace, and with panic=5 on
# the command line it reset boots that were only slow.
#
# It stands down only for a gadget that a host has configured. It used to
# stand down as soon as a real UDC existed, and on mainline that is at once:
# dwc3 with usb-role-switch registers its UDC in peripheral mode at probe,
# before anything is known about the cable. A boot whose gadget never reached
# the host then sat in debug_shell waiting for a login that could not come,
# and nothing reset it.
#
# When it does reset, it says why, through the one channel a blind boot has:
# how long it takes. The delay before the reset is the last progress mark the
# init wrote to /pmmark - none without bootlog.py marks - plus how far up the
# USB stack the boot got, one rung of the ladder below at a time. The names
# are mainline's; on the downstream kernel the first rungs never match and
# the ladder starts at the UDC. bootlog.py markdecode reads both numbers back
# out of a round's total.
#
# Before any of that, /dev/null. A non-interactive ash points a background
# job's stdin at /dev/null as it forks it, and when that open fails the child
# dies with "can't open '/dev/null'" before running a line of its body. At
# this point nothing has mounted /dev: the only node there is the kernel's
# own /dev/console. So from 22859f2 on, which moved this block up here, the
# watchdog died at birth on every boot, rounds 19 to 22 included, and said so
# only on the serial console, which nobody reads. The node made here is
# hidden, not removed, when mount_proc_sys_dev mounts devtmpfs over /dev, and
# the descriptor the job already holds keeps working.
[ -e /dev/null ] || /bin/busybox mknod -m 666 /dev/null c 1 3
(
	# Everything it does from here on goes into /pmwd.log as well, which
	# the log hook copies into every record. Round 22 is why: this never
	# reset the phone, and nothing said whether it was dead, asleep or
	# stuck. The root is the initramfs, writable from the start.
	echo "armed" > /pmwd.log
	# A working boot has USB up in about sixteen seconds, so this is far
	# longer than it needs and far shorter than waiting for a person. It is
	# also past udevadm settle's own 120-second timeout, so a settle that
	# never finishes still lets the init get on before this looks.
	/bin/busybox sleep @WAIT@
	_up=""
	read -r _up _x < /proc/uptime
	read -r _me _x < /proc/self/stat
	echo "awake at $_up, pid $_me" >> /pmwd.log
	# 0  no dwc3 node has a driver: neither the glue, usb@a6f8800, nor the
	#    core, usb@a600000, which the flattened binding makes the only one
	# 1  the glue is bound, the HS PHY (phy@88e3000) is not
	# 2  glue and PHY are bound, but there is no UDC - the dwc3 core failed
	# 3  a UDC exists, but configfs never bound the gadget to it
	# 4  the gadget is bound and the UDC is "not attached": no host saw it
	# 5  the gadget is bound and the UDC got partway with a host
	# 6  binding the gadget never returned, see below
	# 7  a host configured the gadget, and the window below ran out
	# _t counts the tenths of a second spent waiting in here, which come off
	# the delay at the end, so the total still names the rung exactly.
	_t=0
	_u=0
	for _g in a6f8800 a600000; do
		[ -e /sys/bus/platform/devices/$_g.usb/driver ] && _u=1
	done
	[ "$_u" -eq 1 ] && [ -e /sys/bus/platform/devices/88e3000.phy/driver ] && _u=2
	_udc=""
	for _s in /sys/class/udc/*; do
		case "${_s##*/}" in
		dummy_udc*|'*') ;;
		*) _udc="$_s" ;;
		esac
	done
	if [ -n "$_udc" ]; then
		_u=3
		_st=""
		read -r _st < "$_udc/state" 2>/dev/null
		# A host enumerated us, which is what all this is for. This
		# used to stand down for good here, and on a night with nobody
		# at the phone that is a trap: the boot that worked sits in the
		# initramfs until someone holds the buttons, and every round
		# queued after it waits too. So the host gets ten minutes to
		# read what it wants - or to create /pmhold, below, and keep
		# the phone - and then this resets as for any other rung, the
		# attempts run out and stock comes back by itself.
		if [ "$_st" = configured ]; then
			# The log hook's backup waits this much longer too.
			: > /pmwd.hold
			echo "configured, holding for @HOLD@ s" >> /pmwd.log
			/bin/busybox sleep @HOLD@
			_st=""
			read -r _st < "$_udc/state" 2>/dev/null
			[ "$_st" = configured ] && _u=7
		fi
	fi
	if [ "$_u" = 3 ]; then
		# Read from a child, with a time limit. configfs takes the
		# gadget's lock to answer, and the init's write to the same file
		# holds that lock for the whole bind - so a bind that never
		# returns used to take this watchdog down with it, silently,
		# which is the likeliest reading of rounds 18 and 19.
		/bin/busybox rm -f /pmwd.g /pmwd.g.done
		(
			read -r _x < /sys/kernel/config/usb_gadget/g1/UDC 2>/dev/null
			echo "$_x" > /pmwd.g
			: > /pmwd.g.done
		) &
		while [ ! -e /pmwd.g.done ] && [ "$_t" -lt 20 ]; do
			/bin/busybox sleep 0.1
			_t=$((_t + 1))
		done
		if [ -e /pmwd.g.done ]; then
			_g=""
			read -r _g < /pmwd.g
			if [ -n "$_g" ]; then
				case "$_st" in
				"not attached") _u=4 ;;
				*) _u=5 ;;
				esac
			fi
		else
			_u=6
		fi
	fi
	_m=0
	[ -r /pmmark ] && read -r _m < /pmmark
	case "$_m" in ''|*[!0-9]*) _m=0 ;; esac
	read -r _up _x < /proc/uptime
	echo "rung $_u, mark $_m, at $_up" >> /pmwd.log
	# Same hold as the staged probe: a shell that got in can stop this,
	# for as long as it is still there (HOLD_SH).
@HOLD_FN@
	while pmhold_held; do /bin/busybox sleep 5; done
	# On the way out, put the kernel stack of every blocked task into the
	# ring buffer, and give the log hook time to write two more records -
	# the second is the first one certain to have been put together after
	# the dump. Up to six seconds, and never more than the delay has left,
	# so the timing still holds. Neither exists without sysrq and the hook.
	_lim=$(( (_m + _u) * 10 ))
	[ "$_lim" -gt 60 ] && _lim=60
	if [ -w /proc/sysrq-trigger ]; then
		echo "sysrq w" >> /pmwd.log
		/bin/busybox echo w > /proc/sysrq-trigger
		_s0=""
		[ -r /pmbl.seq ] && read -r _s0 < /pmbl.seq
		case "$_s0" in ''|*[!0-9]*) _s0="" ;; esac
		while [ -n "$_s0" ] && [ "$_t" -lt "$_lim" ]; do
			_s1=0
			read -r _s1 < /pmbl.seq
			case "$_s1" in ''|*[!0-9]*) _s1=0 ;; esac
			[ "$_s1" -ge $((_s0 + 2)) ] && break
			/bin/busybox sleep 0.1
			_t=$((_t + 1))
		done
	fi
	_d=$(( (_m + _u) * 10 - _t ))
	[ "$_d" -lt 0 ] && _d=0
	/bin/busybox sleep $((_d / 10)).$((_d % 10))
	# Let a log write that is under way finish first, so the reset never
	# lands in the middle of one - the card it goes to also holds the
	# rootfs. Two seconds at most, and nothing at all without the hook.
	_w=0
	while [ -e /pmbl.busy ] && [ "$_w" -lt 20 ]; do
		/bin/busybox sleep 0.1
		_w=$((_w + 1))
	done
	read -r _up _x < /proc/uptime
	echo "resetting at $_up" >> /pmwd.log
	# sysrq b restarts at once. reboot(2) is the fallback without sysrq, and
	# a poor one: it runs every driver's shutdown under that device's lock,
	# so a bind stuck holding one can stop it too. -n at least keeps sync
	# out of it, which a stuck block device would hold up the same way.
	[ -w /proc/sysrq-trigger ] && /bin/busybox echo b > /proc/sysrq-trigger
	/bin/busybox reboot -f -n
	# reboot(2) refused. Do not sit here looking like a hang.
	/bin/busybox sleep 90
	/bin/busybox reboot -f
) &
# ---------------------------------------------------------------------------
"""

USB_QUIRK = """
# --- pdx246: ask dwc3 for a role, or no UDC is ever created ----------------
# msm-dwc3 probes a600000.ssusb, registers a role switch, and then stays in
# "none" mode: it only builds its dwc3@a600000 core child once something asks
# for a role. The device tree says dr_mode = "otg" with usb-role-switch, and
# on a stock boot the request comes from the charger and Type-C stack, which
# an initramfs does not have. Without it /sys/class/udc holds nothing but
# dummy_udc.0 - the emulator this kernel also builds - so the gadget binds to
# that, enumerates perfectly inside the phone, and is invisible from outside.
# Writing the driver's own "mode" attribute is the short way to ask. Measured
# on the device: the UDC appears one second later.
for _ssusb in /sys/bus/platform/devices/*.ssusb; do
	[ -w "$_ssusb/mode" ] || continue
	echo peripheral > "$_ssusb/mode" 2>/dev/null
	[ -w "$_ssusb/usb_data_enabled" ] && echo 1 > "$_ssusb/usb_data_enabled"
done
_w=0
while [ "$_w" -lt 12 ]; do
	_real=""
	for _u in /sys/class/udc/*; do
		case "${_u##*/}" in
		dummy_udc*|'*') ;;
		*) _real="${_u##*/}" ;;
		esac
	done
	[ -n "$_real" ] && break
	_w=$((_w + 1))
	sleep 1
done
echo "[pdx246] udc after ${_w}s: ${_real:-none}"
# ---------------------------------------------------------------------------
"""


def usbquirk(src, dst, watchdog=True):
    """Rebuild a vendor_boot whose real /init asks dwc3 for peripheral mode.

    watchdog=False leaves USB_WATCHDOG out, for a boot that is meant to stay
    up with someone using the phone: try-kernel.sh's STAYUP=1.
    """
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(rd_unpack(d[o_rd:o_rd + vr]))

    # Both stages get the quirk, because which one runs depends on
    # deviceinfo_create_initfs_extra. With it false - the default - mkinitfs
    # builds one archive, /init_2nd.sh is already in it, and stage 1 execs
    # straight into it well before its own setup_usb_network. Everything after
    # that jump in stage 1 is dead code, which is where the first version of
    # this patch put the quirk.
    patched = []
    for name in ("init", "init_2nd.sh"):
        e = next((x for x in entries if x[1] == name), None)
        if e is None:
            continue
        text = e[2].decode()
        if "pdx246: ask dwc3 for a role" in text:
            sys.exit(f"error: /{name} already carries the quirk - rebuild "
                     "from a clean image rather than stacking patches")
        anchor = "\nsetup_usb_network\n"
        if anchor not in text:
            continue
        text = text.replace(anchor, "\n" + USB_QUIRK + anchor, 1)
        # The watchdog belongs in stage 1 only, and before the jump: a
        # background job survives its parent's exec, so one is enough.
        if name == "init" and watchdog:
            # As early as the file allows: after the shebang, before anything
            # that could wedge. "set -a" is line 5 and appears once.
            wd = "set -a\n"
            if wd not in text:
                sys.exit("error: could not find 'set -a' in init")
            text = text.replace(wd, wd + USB_WATCHDOG.lstrip("\n").replace(
                "@WAIT@", str(WATCHDOG_S)).replace(
                "@HOLD@", str(CONFIGURED_HOLD_S)).replace(
                "@HOLD_FN@", textwrap.indent(HOLD_SH.strip("\n"), "\t")), 1)
        e[2] = text.encode()
        patched.append(name)

    if "init_2nd.sh" not in patched:
        sys.exit("error: no init_2nd.sh with a setup_usb_network call - the "
                 "stage that actually brings USB up is missing")

    newrd = gzip.compress(cpio_build(entries), 6)
    open(dst, "wb").write(_rebuild(d, s, newrd))
    print(f"  in   {src}")
    print(f"  out  {dst}")
    print(f"  patched: {', '.join('/' + n for n in patched)}")
    print("  each now writes peripheral to *.ssusb/mode before"
          " setup_usb_network")
    if watchdog:
        print(f"  and /init arms a {WATCHDOG_S}s watchdog, so a boot the host"
              " never sees resets itself")
    else:
        print("  and no watchdog: nothing in /init resets the phone")
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes")
    print(f"  dtb area {s['dtb'][1]} bytes, copied across untouched")


# Top-level steps of the pmOS init scripts that get a mark in front of them.
# Matched on the start of the line, indented or not, so a step inside an "if"
# is marked too. Stage 1 is only marked after mount_proc_sys_dev, because
# before that there is no /proc to write to.
MARK_STEPS = re.compile(
    r"^(\s*)(parse_cmdline|setup_\w+|start_\w+|mount_\w+|jump_init_2nd|"
    r"load_modules|run_hooks|debug_shell|check_keys|wait_\w+|splash_start|"
    r"extract_initramfs_extra|delete_old_install_partition|resize_\w+|"
    r"unlock_root_partition)\b")


def marks(src, dst, table, base, scale, pscale=1):
    """Rebuild a vendor_boot whose real init reports its progress.

    Before each top-level step the init writes its step number k, counted
    across both stages, into two channels:

    /pmmark gets base + scale * k, which the USB watchdog adds to its delay
    before resetting a boot no host has configured. That covers an init that
    is alive but stuck - in debug_shell, or waiting for a root partition -
    and one round is enough, because the watchdog's own offset is known:
    markdecode reads the step straight off the round's total.

    /proc/sys/kernel/panic gets pscale * k, for a kernel that dies instead
    of an init that hangs. With
    nmi_watchdog=panic softlockup_panic=1 on the command line a lockup
    becomes a panic, and the timeout says which step was running. A lockup
    panic comes some unknown time after the hang, and that offset lands in
    every attempt, so this channel takes two rounds at two panic scales; it
    cancels in the difference, 7 * 0.992 * (pscale2 - pscale1) * k.

    The panic channel is kept small on purpose. A watchdog reset costs at
    least ATTEMPT_S + WATCHDOG_S an attempt; a panic costs ATTEMPT_S plus the
    time to the hang, about 20 seconds of detection and pscale * k. At one
    second a step that stays under the watchdog's floor unless the hang
    comes more than a minute and a half into the init, so the two channels
    can be told apart by length alone.
    """
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(rd_unpack(d[o_rd:o_rd + vr]))

    k = 0
    rows = []
    for name in ("init", "init_2nd.sh"):
        e = next((x for x in entries if x[1] == name), None)
        if e is None:
            sys.exit(f"error: no /{name} in the ramdisk")
        text = e[2].decode()
        if "pdx246: progress mark" in text:
            sys.exit(f"error: /{name} already carries marks - rebuild from a "
                     "clean image rather than stacking patches")
        out = []
        live = name != "init"
        for line in text.split("\n"):
            m = MARK_STEPS.match(line)
            # The USB quirk is a block of its own ahead of setup_usb_network
            # and worth a mark: it is the first thing that touches dwc3.
            quirk = line.startswith("# --- pdx246: ask dwc3 for a role")
            if live and (m or quirk):
                k += 1
                ind = m.group(1) if m else ""
                what = m.group(2) if m else "usb quirk"
                v = base + scale * k
                out.append(f"{ind}echo {v} > /pmmark; echo {pscale * k} >"
                           f" /proc/sys/kernel/panic 2>/dev/null"
                           f"  # pdx246: progress mark {k}, {what}")
                rows.append((k, v, pscale * k, name, what))
            out.append(line)
            if name == "init" and line.strip() == "mount_proc_sys_dev":
                live = True
        e[2] = "\n".join(out).encode()

    newrd = gzip.compress(cpio_build(entries), 6)
    open(dst, "wb").write(_rebuild(d, s, newrd))
    lines = [f"  mark {k:2d}  v={v:<4d} panic={t:<4d} /{n}: {w}"
             for k, v, t, n, w in rows]
    head = (f"base {base}, scale {scale}, panic scale {pscale}: mark k writes"
            f" v = {base} + {scale}k for the watchdog and {pscale}k to"
            " kernel.panic; before the first, the watchdog adds 0 and a panic"
            " waits the command line's panic=")
    open(table, "w").write(head + "\n" + "\n".join(lines) + "\n")
    print(f"  in   {src}")
    print(f"  out  {dst}")
    print(f"  {len(rows)} marks; {head}")
    print("\n".join(lines))
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes")


# The retry counter as a clock. Measured over the probe rounds: an attempt
# costs ATTEMPT_S on top of whatever the boot itself waits, and the fallback
# into Android adds FALLBACK_S before adb answers.
ATTEMPTS = 7
ATTEMPT_S = 13.34
FALLBACK_S = 30


def markdecode(total, base, scale, table=None):
    """Read a watchdog round's total back into (mark, UDC state)."""
    per = (total - FALLBACK_S) / ATTEMPTS
    extra = per - ATTEMPT_S - WATCHDOG_S
    print(f"  {total} s over {ATTEMPTS} attempts: {per:.2f} s each,"
          f" {extra:+.2f} s past the watchdog's {WATCHDOG_S} s")
    if extra < -2:
        print("  shorter than the watchdog: every attempt ended some other"
              " way, most likely a panic. Decode it as panic marks instead:"
              " a second round at another panic scale, then"
              " k = (total2 - total1) / (7 * 0.992 * (pscale2 - pscale1)).")
        return
    held = extra > CONFIGURED_HOLD_S - 2
    if held:
        print(f"  {CONFIGURED_HOLD_S} s of that is the window a configured"
              " gadget gets, so a host enumerated the phone (rung 7)")
        extra -= CONFIGURED_HOLD_S
    # The log hook's backup goes at BACKUP_S of uptime, which starts about
    # 1.1 s before /init does, and then writes one more record, about 2.5 s.
    backup = BACKUP_S - WATCHDOG_S + 1.4
    if abs(extra - backup) < 8:
        print(f"  the log hook's backup, at {BACKUP_S} s of uptime: the USB"
              " watchdog never reset the phone. The records' \"usb"
              " watchdog\" section says how far it got, and \"processes\""
              " what it was waiting in.")
        return
    if extra > 500 - ATTEMPT_S - WATCHDOG_S:
        print("  longer than any mark can make it: the watchdog never fired,"
              " or its reset never finished, and something else reset the"
              " phone.")
        return
    names = {}
    if table:
        for line in open(table):
            f = line.split()
            if f[:1] == ["mark"]:
                names[int(f[1])] = " ".join(f[4:])
    kmax = max(names) if names else 64
    # The rungs of USB_WATCHDOG's ladder, in its order.
    udc = ["dwc3 glue unbound", "glue bound, HS PHY unbound",
           "glue and PHY bound, no UDC (dwc3 core failed)",
           "UDC exists, gadget not bound to it",
           "gadget bound, UDC not attached (no host saw it)",
           "gadget bound, UDC partway with a host",
           "binding the gadget never returned (configfs lock held)",
           "a host configured the gadget"]
    # Rung 7 sits CONFIGURED_HOLD_S above the others, so only the first
    # seven have to fit between two marks.
    rungs = [7] if held else range(7)
    if scale <= 7:
        print(f"  warning: scale {scale} is too small to keep 7"
              " USB states apart; use 8")
    cands = []
    for k in range(kmax + 1):
        v = 0 if k == 0 else base + scale * k
        for u in rungs:
            cands.append((abs(extra - v - u), k, u, v))
    cands.sort()
    for err, k, u, v in cands[:3]:
        what = "no mark yet" if k == 0 else names.get(k, f"mark {k}")
        print(f"  {err * ATTEMPTS:5.1f} s off:  mark {k:2d} ({what}),"
              f" {udc[u]}")


def stage(src, dst, skip=""):
    """Rebuild a vendor_boot whose /init is the staged module probe."""
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(rd_unpack(d[o_rd:o_rd + vr]))

    init = next((e for e in entries if e[1] == "init"), None)
    if init is None:
        sys.exit("error: no /init in the vendor ramdisk - wrong image?")

    defer = " ".join(STAGE_DEFER.split())
    skip = " ".join(skip.split())
    init[2] = (STAGE_INIT.replace("@DEFER@", defer)
                         .replace("@SKIP@", skip)
                         .replace("@HOLD_FN@", HOLD_SH.strip("\n"))).encode()

    # The staged init sources /bootlog.sh itself, once the storage chain is
    # about to be loaded, so the file still has to be there.
    entries = [e for e in entries if e[1] != "bootlog.sh"]
    entries.append([[0, 0o100755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                    "bootlog.sh", BOOTLOG_SH.encode()])

    # A file rather than a baked-in variable, so the staged init reads the
    # same on every build and the choice is visible by listing the archive.
    entries = [e for e in entries if e[1] != "pmhandoff"]
    handoff = os.environ.get("HANDOFF", "0") == "1"
    if handoff:
        entries.append([[0, 0o100644, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                        "pmhandoff", b"1\n"])

    newrd = gzip.compress(cpio_build(entries), 6)
    open(dst, "wb").write(_rebuild(d, s, newrd))

    held = len(defer.split())
    print(f"  in   {src}")
    if skip:
        print(f"  skipping entirely: {skip}")
    print(f"  out  {dst}")
    print(f"  /init replaced with the staged probe ({len(init[2])} bytes)")
    print(f"  {held} modules held back for the second pass")
    if handoff:
        print("  HANDOFF=1: execs /init_2nd.sh once the gadget is up")
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes")
    print(f"  dtb area {s['dtb'][1]} bytes, copied across untouched")


def _rebuild(d, s, newrd):
    """Reassemble a vendor_boot around a new vendor ramdisk."""
    up = s["up"]
    hdr = bytearray(d[:up(s["hs"])])
    struct.pack_into("<I", hdr, 24, len(newrd))
    o_vrt, vrt_size = s["vrt"]
    vrt = bytearray(d[o_vrt:o_vrt + vrt_size])
    # A v4 vendor ramdisk table entry starts {ramdisk_size, ramdisk_offset},
    # so the new length goes at 0 and the offset stays 0 - there is one
    # fragment and it begins at the start of the section. Writing the length
    # to 4 instead, as this did until 2026-10-07, left ramdisk_size at the
    # pre-recompression value and put the length in ramdisk_offset, which
    # described a fragment starting at the end of the section. ABL ignores
    # the table when there is a single entry - a downstream probe round ran
    # seven times through exactly this - so it cost nothing, but a tool that
    # writes a self-contradicting header is a trap for the next reader.
    if s["vrt_num"] == 1 and vrt_size >= 8:
        struct.pack_into("<2I", vrt, 0, len(newrd), 0)
    o_dtb, ds = s["dtb"]
    o_bc, bc = s["bc"]
    out = bytearray()
    out += hdr
    out += newrd + b"\0" * (up(len(newrd)) - len(newrd))
    out += d[o_dtb:o_dtb + ds] + b"\0" * (up(ds) - ds)
    out += bytes(vrt) + b"\0" * (up(vrt_size) - vrt_size)
    out += d[o_bc:o_bc + bc] + b"\0" * (up(bc) - bc)
    return bytes(out)


# How long one attempt costs, in seconds, apart from the encoded delay: the
# bootloader's own ~18 before it enters the kernel, plus the 15 the stall
# watchdog waits before deciding progress has stopped. Measured on this
# device: the reboot probe did seven attempts in 186s with an 8s sleep in
# them, so 186/7 - 8 = 18.6.
ATTEMPT_FIXED = 18 + 15
ATTEMPTS = 7
FALLBACK_BOOT = 35      # the stock slot getting as far as answering adb


def stage_map(src, skip=""):
    """Index -> what the staged probe was doing, in load order."""
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    names = {e[1]: e[2] for e in cpio_parse(rd_unpack(d[o_rd:o_rd + vr]))}
    key = next((k for k in names if k.endswith("modules/initramfs.load")), None)
    if key is None:
        sys.exit("error: no initramfs.load in that image")
    mods = [l.strip() for l in names[key].decode().splitlines()
            if l.strip() and not l.strip().startswith("#")]
    defer = set(STAGE_DEFER.split())
    skipped = set(skip.split())
    mods = [m for m in mods if m not in skipped]
    p1 = [m for m in mods if m not in defer]
    p2 = [m for m in mods if m in defer]

    m = {1: "busybox --install", 2: "busybox-extras --install",
         3: "sourcing init_functions.sh", 4: "sourcing deviceinfo",
         5: "mount_proc_sys_dev", 6: "sysrq and hung_task knobs",
         7: "parse_cmdline", 8: "setup_firmware_path", 9: "setup_mdev"}
    for i, mod in enumerate(p1, 10):
        m[i] = f"pass1 modprobe {mod}"
    m[60] = "reading /sys/class/udc"
    m[61] = "setup_usb_network"
    m[62] = "setup_usb_acm_configfs"
    m[63] = "setup_usb_configfs_udc"
    m[64] = "start_unudhcpd"
    m[65] = "gadget bound, opening shells"
    m[66] = "no gadget, falling back to the clock"
    m[70] = "arming the flash log"
    for i, mod in enumerate(p2, 71):
        m[i] = f"pass2 modprobe {mod}"
    m[99] = m.get(99, "") + "  (and everything past 99, which encodes the same)"
    return m


def stages(src, seconds=None, skip=""):
    m = stage_map(src, skip)
    if seconds is None:
        print("  index  expected fallback  step")
        for i in sorted(m):
            t = ATTEMPTS * (ATTEMPT_FIXED + min(i, 99)) + FALLBACK_BOOT
            print(f"  {i:5}  {t // 60}m{t % 60:02d}s             {m[i]}")
        print("\n  Expected times ignore the time the probe spends loading the")
        print("  modules before the one that hung, which adds a few seconds an")
        print("  index, so a measured time lands a little above its row.")
        return
    t = int(seconds)
    n = round((t - FALLBACK_BOOT) / ATTEMPTS - ATTEMPT_FIXED)
    print(f"  {t}s to the fallback -> index about {n}")
    for i in range(max(1, n - 2), n + 3):
        if i in m:
            print(f"    {i:3}{'  <-' if i == n else '    '} {m[i]}")
    if n >= 99:
        print("\n  99 is the cap, so this only says it got past the USB bring-up.")
    elif n < 1:
        print("\n  Below the first step: it never ran the probe at all.")

LOG_HDR = re.compile(re.escape(LOG_MAGIC) + rb" seq=(\d+)(?: attempt=(\d+))?")
LOG_END = re.compile(rb"--- end seq=(\d+) attempt=(\d+) md5=([0-9a-f]{32}) ---\n")


def _record(buf):
    """The record at the start of buf, as (seq, attempt, status, text).

    status is "complete" when the trailer's md5 matches everything above it,
    "torn" when it does not or there is no trailer, and "old" for a record
    from the hook before trailers existed, which cannot be checked.
    """
    m = LOG_HDR.match(buf)
    if not m:
        return None
    seq, att = int(m.group(1)), int(m.group(2) or 0)
    status = "old" if m.group(2) is None else "torn"
    for e in LOG_END.finditer(buf):
        if (int(e.group(1)) == seq
                and hashlib.md5(buf[:e.start()]).hexdigest() == e.group(3).decode()):
            buf, status = buf[:e.end()], "complete"
            break
    else:
        z = buf.find(b"\0")
        buf = buf[:z] if z >= 0 else buf
    return seq, att, status, buf.decode("utf-8", "replace")


def card_sh(what):
    """One line of shell for recovery's adb that finds the card the way the
    hook does - exact size, p1 present, nothing overlapping the region - and
    then reads the region out, or zeroes its counter and every half's first
    block so the next round starts from attempt 1 with nothing stale to
    mistake for its own. It exits 3 without touching anything if no card
    passes."""
    lo = CARD_REGION * 128
    hi = lo + CARD_REGION_BLOCKS * 128
    find = ("c=; for d in /sys/block/mmcblk*; do"
            f" [ \"$(cat $d/size 2>/dev/null)\" = {CARD_SECTORS} ] || continue;"
            " [ -e $d/${d##*/}p1/start ] || continue; ok=1;"
            " for p in $d/${d##*/}p*; do [ -e $p/start ] || continue;"
            " s=$(cat $p/start); z=$(cat $p/size);"
            f" [ $s -lt {hi} ] && [ $((s + z)) -gt {lo} ] && ok=0; done;"
            " [ $ok = 1 ] || continue; c=/dev/block/${d##*/};"
            " [ -b $c ] || c=/dev/${d##*/}; break; done;"
            " [ -n \"$c\" ] && [ -b $c ] || exit 3;")
    if what == "read":
        return (f"{find} dd if=$c bs=65536 skip={CARD_REGION}"
                f" count={CARD_REGION_BLOCKS} 2>/dev/null")
    heads = [CARD_REGION] + [CARD_REGION + 1 + i * CARD_HALF_BLOCKS
                             for i in range(CARD_SLOTS * 2)]
    return (f"{find} for b in {' '.join(map(str, heads))}; do"
            " dd if=/dev/zero of=$c bs=65536 seek=$b count=1 conv=notrunc"
            " 2>/dev/null || exit 4; done; sync")


def decode(path, show_all=False):
    with open(path, "rb") as f:
        size = f.seek(0, 2)
        f.seek(0)
        if size == CARD_SECTORS * 512:
            # The whole card, or an image of it: just the region, then.
            f.seek(CARD_REGION * 65536)
            d = f.read(CARD_REGION_BLOCKS * 65536)
        elif size > CARD_REGION_BLOCKS * 65536:
            sys.exit(f"error: {path} is {size} bytes - neither the card, nor"
                     " a dump of the log region or of rddata")
        else:
            d = f.read()
    half = CARD_HALF_BLOCKS * 65536
    if d.startswith(CTR_MAGIC) or len(d) == CARD_REGION_BLOCKS * 65536:
        # A cleared region has a zero counter block, so go by size as well.
        ctr = d[:64].split(b"\n")[0].rstrip(b"\0").decode("ascii", "replace")
        print(f"  card region: counter block reads {ctr!r}")
        starts = [65536 + i * half for i in range(CARD_SLOTS * 2)]
    else:
        # rddata: two halves at the front of the partition.
        starts = [0, half]
    recs = [r for r in (_record(d[a:a + half]) for a in starts) if r]
    if not recs:
        nz = len(d) - d.count(0)
        sys.exit(f"error: no log here - {nz} non-zero bytes in {len(d)}.\n"
                 "       Nothing reached storage: the card never appeared, or"
                 " the boot died first.")
    # The newest complete record of each attempt; a torn one only if the
    # attempt has nothing better.
    best = {}
    for seq, att, status, text in recs:
        key = (status != "torn", seq)
        if att not in best or key > best[att][0]:
            best[att] = (key, seq, status, text)
    atts = sorted(best)
    for att in atts:
        _, seq, status, text = best[att]
        up = re.search(r"uptime=(\S+)", text)
        mark = re.search(r"^init mark: (.*)$", text, re.M)
        mark = mark.group(1).strip() if mark else ""
        kver = re.search(r"^kernel: Linux version (\S+)", text, re.M)
        rnd = re.search(r"^cmdline: .*\bpmbl\.round=(\S+)", text, re.M)
        print(f"  attempt {att}: record {seq}"
              f"{'' if status == 'complete' else f' ({status})'},"
              f" uptime {up.group(1) if up else '?'} s,"
              f" init mark {mark or 'none'}"
              + (f", {kver.group(1)}" if kver else "")
              + (f", round {rnd.group(1)}" if rnd else ""))
    for att in (atts if show_all else atts[-1:]):
        _, seq, status, text = best[att]
        print()
        print(text)
        if status == "torn":
            print(f"\n  (record {seq} of attempt {att} is torn - the device died"
                  " while writing it, and no complete one exists)", file=sys.stderr)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "install":
        install(a[1], a[2])
    elif len(a) == 3 and a[0] == "probe":
        probe(a[1], a[2])
    elif len(a) == 3 and a[0] == "usbquirk":
        usbquirk(a[1], a[2])
    elif len(a) == 4 and a[0] == "usbquirk" and a[3] == "--no-watchdog":
        usbquirk(a[1], a[2], watchdog=False)
    elif a[:1] == ["marks"] and len(a) in (6, 7):
        marks(a[1], a[2], a[3], *map(int, a[4:]))
    elif a[:1] == ["markdecode"] and len(a) in (4, 5):
        markdecode(float(a[1]), int(a[2]), int(a[3]),
                   a[4] if len(a) == 5 else None)
    elif a[:1] == ["stage"] and len(a) in (3, 4):
        stage(a[1], a[2], a[3] if len(a) == 4 else "")
    elif a[:1] == ["stages"] and len(a) in (2, 3):
        stages(a[1], a[2] if len(a) == 3 else None)
    elif a[:1] == ["decode"] and len(a) in (2, 3):
        decode(a[1], a[2:] == ["all"])
    elif len(a) == 2 and a[0] == "card-sh" and a[1] in ("read", "clear"):
        print(card_sh(a[1]))
    else:
        sys.exit(__doc__.strip().split("\n\n")[-2])
