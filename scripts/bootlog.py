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
  bootlog.py stage   <vendor_boot-in> <vendor_boot-out> [skip-these-modules]
  bootlog.py stages  <vendor_boot> [seconds-to-fallback]
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
		# What the probe itself got up to, which dmesg does not say.
		echo "--- probe log ---"
		cat /pmprobe.log 2>/dev/null
		# The three things that answer "why did this driver never probe?".
		# A driver that is waiting on a provider prints nothing at all, so
		# without these a silent permanent deferral is invisible - which is
		# exactly how dwc3-msm hid for a day.
		echo "--- deferred probes ---"
		mount -t debugfs none /sys/kernel/debug 2>/dev/null
		cat /sys/kernel/debug/devices_deferred 2>/dev/null
		echo "--- udc ---"
		ls /sys/class/udc 2>/dev/null
		echo "--- platform devices and their drivers ---"
		for d in /sys/bus/platform/devices/*; do
			drv=$(readlink "$d/driver" 2>/dev/null)
			echo "${d##*/} ${drv##*/}"
		done 2>/dev/null
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

pmstage_reset() {
	# A live shell can stop the clock. Every reset in here is on a timer
	# measured in minutes, which is right for a boot nobody is watching and
	# wrong for one where something is mid-operation - writing a rootfs to
	# the SD card takes longer than the probe's own patience. Nothing
	# creates /pmhold on its own, so an unattended boot still resets.
	while [ -e /pmhold ]; do $B sleep 5; done
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
(
	# A working boot has USB up in about sixteen seconds, so four minutes is
	# far longer than this needs and far shorter than waiting for a person.
	/bin/busybox sleep 240
	[ -e /pmusbok ] && exit 0
	# Same hold file as the staged probe: a shell that got in can stop this.
	while [ -e /pmhold ]; do /bin/busybox sleep 5; done
	[ -w /proc/sysrq-trigger ] && /bin/busybox echo b > /proc/sysrq-trigger
	/bin/busybox reboot -f
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
# Tell the watchdog to stand down: from here a person can get in and look.
[ -n "$_real" ] && touch /pmusbok
# ---------------------------------------------------------------------------
"""


def usbquirk(src, dst):
    """Rebuild a vendor_boot whose real /init asks dwc3 for peripheral mode."""
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(gzip.decompress(d[o_rd:o_rd + vr]))

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
        if name == "init":
            # As early as the file allows: after the shebang, before anything
            # that could wedge. "set -a" is line 5 and appears once.
            wd = "set -a\n"
            if wd not in text:
                sys.exit("error: could not find 'set -a' in init")
            text = text.replace(wd, wd + USB_WATCHDOG.lstrip("\n"), 1)
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
    print("  and /init arms a 240s watchdog, so a hang resets itself")
    print(f"  vendor ramdisk {vr} -> {len(newrd)} bytes")
    print(f"  dtb area {s['dtb'][1]} bytes, copied across untouched")


def stage(src, dst, skip=""):
    """Rebuild a vendor_boot whose /init is the staged module probe."""
    d = open(src, "rb").read()
    s = sections(d)
    o_rd, vr = s["ramdisk"]
    entries = cpio_parse(gzip.decompress(d[o_rd:o_rd + vr]))

    init = next((e for e in entries if e[1] == "init"), None)
    if init is None:
        sys.exit("error: no /init in the vendor ramdisk - wrong image?")

    defer = " ".join(STAGE_DEFER.split())
    skip = " ".join(skip.split())
    init[2] = (STAGE_INIT.replace("@DEFER@", defer)
                         .replace("@SKIP@", skip)).encode()

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
    names = {e[1]: e[2] for e in cpio_parse(gzip.decompress(d[o_rd:o_rd + vr]))}
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
    elif len(a) == 3 and a[0] == "usbquirk":
        usbquirk(a[1], a[2])
    elif a[:1] == ["stage"] and len(a) in (3, 4):
        stage(a[1], a[2], a[3] if len(a) == 4 else "")
    elif a[:1] == ["stages"] and len(a) in (2, 3):
        stages(a[1], a[2] if len(a) == 3 else None)
    elif len(a) == 2 and a[0] == "decode":
        decode(a[1])
    else:
        sys.exit(__doc__.strip().split("\n\n")[-2])
