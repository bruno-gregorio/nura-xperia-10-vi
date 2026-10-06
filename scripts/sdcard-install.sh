#!/bin/sh
# Put the rootfs on the phone's SD card, over the USB cable, hands-free.
#
#   ./scripts/sdcard-install.sh            # look, change nothing
#   ./scripts/sdcard-install.sh --yes      # actually write
#
# The phone must be sitting in an initramfs shell with USB up, i.e. telnet
# 172.16.42.1:23 answers. scripts/try-kernel.sh gets it there.
#
# Why the SD card and not userdata: it is the one writable bulk device on this
# phone that no Android partition claims, so a broken rootfs costs an SD write
# and not a trip through fastboot. Chosen by the owner on 2026-10-05.
#
# How the bytes get across: there is no adb and no MTP in an initramfs, but
# there is busybox wget, and the gadget already gives us an IP link. So the
# host serves the image over HTTP on the USB interface only - not on the LAN -
# and the phone pulls it straight into dd. Nothing is staged on the phone,
# which matters because the rootfs is larger than the phone's RAM.
#
# The write runs detached under setsid with its output in a file, and this
# script polls that file over short telnet connections. scripts/telnet.py
# stops reading two seconds after its piped input ends, so a command that runs
# for minutes cannot be driven from one connection - and a session that
# dropped mid-write would otherwise take dd with it.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

PHONE_IP=172.16.42.1          # the gadget, per unudhcpd in the initramfs
HOST_IP=172.16.42.2           # us, on the USB interface
NCPORT=9000                   # the phone listens here; see "send the image"
DEV=/dev/mmcblk1              # the SD card; UFS is sda/sdb/sdc, never touched
IMG="$ROOT/.pmb/work/chroot_native/home/pmos/rootfs/sony-pdx246.img"
WHOLE_DISK=0
ASSUME_YES=0
VERIFY=0
TIMEOUT=1200

say() { echo "==> $*"; }
die() { echo "error: $*" >&2; exit 1; }

usage() {
	sed -n '2,/^set -eu/p' "$0" | sed 's/^# \{0,1\}//; /^set -eu/d'
	cat <<-EOF
	Options:
	  --device PATH   block device on the phone (default $DEV)
	  --image PATH    image to write (default the pmbootstrap rootfs)
	  --port N        TCP port the phone listens on (default $NCPORT)
	  --whole-disk    write the filesystem to the whole card, no partition table
	  --verify        read the card back and compare checksums (slow)
	  --timeout N     seconds to allow for the write (default $TIMEOUT)
	  --yes           do it; without this the script only looks
	EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
	--device) DEV="$2"; shift 2 ;;
	--image) IMG="$2"; shift 2 ;;
	--port) NCPORT="$2"; shift 2 ;;
	--whole-disk) WHOLE_DISK=1; shift ;;
	--verify) VERIFY=1; shift ;;
	--timeout) TIMEOUT="$2"; shift 2 ;;
	--yes) ASSUME_YES=1; shift ;;
	-h | --help) usage; exit 0 ;;
	*) die "unknown option: $1 (try --help)" ;;
	esac
done

# --- guards ----------------------------------------------------------------
# Only the SD card. The UFS LUNs carry the bootloader, the modem and Android,
# and this script has no business naming them.
case "$DEV" in
/dev/mmcblk[0-9]) ;;
/dev/sd* | /dev/ufs* | /dev/nvme*)
	die "$DEV is not the SD card - UFS holds the bootloader and Android" ;;
*) die "refusing $DEV: only /dev/mmcblkN is allowed here" ;;
esac
BASE=${DEV#/dev/}

[ -f "$IMG" ] || die "no image at $IMG - run scripts/make-rootfs-img.sh first"
[ -r "$IMG" ] || die "$IMG is not readable as $(id -un)"
IMG_SIZE=$(stat -c %s "$IMG")

command -v python3 >/dev/null || die "python3 is needed for scripts/telnet.py"

# --- talking to the phone --------------------------------------------------
# What comes back is not just output. busybox telnetd echoes the input, and
# the shell replays each line after its prompt, so every command we send
# appears in the reply twice before it has even run. Nothing can be matched
# against that reply unless it is a string the command text cannot contain,
# which is why every marker below is assembled on the phone from pieces -
# "${T}SECTORS=", "$M$N" - rather than written out whole. Getting this wrong
# is not cosmetic: a literal "FINISHED" in a polling command matches on the
# first pass and the script walks away from a write that has not started.
remote() {
	printf '%s\nexit\n' "$1" \
		| python3 "$ROOT/scripts/telnet.py" "$PHONE_IP" 23 2>/dev/null \
		| tr -d '\r'
}

# Anything that touches a block device has to run detached. A foreground
# command that blocks on block I/O takes the telnet session down with it -
# parted, blkid and dd have each done it on this phone, while the same command
# under setsid returns rc=0 in a quarter of a second. The device is fine; it is
# the session that cannot survive the wait. So each such step is written to a
# file, run detached with its output in another file, and read back over a
# second connection.
#
# The job text goes across inside a quoted heredoc, so nothing in it is
# expanded on the phone, and the "sh -c" wrapper is a fixed string, so a job
# containing quotes cannot break out of it.
remote_job() {
	# $1: shell text to run. $2: seconds to allow (default 180).
	_limit=${2:-180}
	remote "rm -f /tmp/job.out /tmp/job.done /tmp/job.sh
cat > /tmp/job.sh <<'PMJOB'
$1
PMJOB
setsid /bin/sh -c 'sh /tmp/job.sh > /tmp/job.out 2>&1; echo x > /tmp/job.done' >/dev/null 2>&1 &
sleep 1" >/dev/null 2>&1
	_i=0
	while :; do
		case "$(remote 'J=JOB; [ -e /tmp/job.done ] && echo "${J}_ENDED"')" in
		*JOB_ENDED*) break ;;
		esac
		_i=$(( _i + 3 ))
		[ "$_i" -lt "$_limit" ] || { echo "JOB_TIMEOUT"; return 0; }
		sleep 3
	done
	# Tagged dump: the echo of this command cannot produce a line that starts
	# with the tag, because the tag is assembled on the phone.
	remote 'T=JOB; sed "s|^|${T}> |" /tmp/job.out 2>/dev/null' \
		| sed -n 's/^JOB> //p'
}

# Wait rather than give up. The phone resets itself on a timer whenever
# /pmhold is absent, so starting this script a few seconds into a reset window
# is normal and not an error - it comes back into the same shell in about
# sixteen seconds. A run died here once for exactly that reason.
say "waiting for a shell on $PHONE_IP"
kver=
_i=0
while [ "$_i" -lt 150 ]; do
	if ping -c 1 -W 2 "$PHONE_IP" >/dev/null 2>&1; then
		probe=$(remote 'K=PMOS; echo "${K}_SHELL_OK $(uname -r)"') || true
		kver=$(echo "$probe" | sed -n 's/^PMOS_SHELL_OK \(.*\)$/\1/p' | head -1)
		[ -n "$kver" ] && break
	fi
	_i=$(( _i + 5 )); sleep 5
done
[ -n "$kver" ] || die "no shell on $PHONE_IP:23 after 150s - is the phone in
       an initramfs shell? scripts/try-kernel.sh gets it there."
say "shell is up, kernel $kver"

# The host end of the USB link has to exist, or the phone has nothing to fetch
# from. NetworkManager configures it by DHCP from the phone's unudhcpd.
ip -o addr show | grep -q " $HOST_IP/" \
	|| die "no interface on this host holds $HOST_IP
       the USB network is not configured; see scripts/console.sh"

# --- stop the clock --------------------------------------------------------
# Both the staged probe and the patched real init reset the phone on a timer
# measured in minutes, which is right for an unattended boot and wrong while a
# gigabyte is going onto the card. /pmhold makes those resets wait. It has to
# come off again or the phone stops being hands-free, so the trap goes in at
# the same moment as the file.
HELD=0
cleanup() {
	if [ "$HELD" = 1 ]; then
		remote 'rm -f /pmhold' >/dev/null 2>&1
		echo "==> released /pmhold; the phone's reset timer is live again"
	fi
	return 0
}

# --- what we are about to overwrite ----------------------------------------
say "looking at $DEV on the phone"
info=$(remote "
T=SD
echo \"\${T}SECTORS=\$(cat /sys/block/$BASE/size 2>/dev/null)\"
echo \"\${T}REMOVABLE=\$(cat /sys/block/$BASE/removable 2>/dev/null)\"
echo \"\${T}PARTS_FOLLOW\"
grep -E ' ($BASE|${BASE}p[0-9][0-9]*)\$' /proc/partitions
")
sectors=$(echo "$info" | sed -n 's/^SDSECTORS=\([0-9][0-9]*\)$/\1/p' | head -1)
removable=$(echo "$info" | sed -n 's/^SDREMOVABLE=\([0-9]\)$/\1/p' | head -1)
parts=$(echo "$info" | sed -n '/^SDPARTS_FOLLOW$/,$p' | sed '1d' \
	| grep -E "[0-9]+[[:space:]]+[0-9]+[[:space:]]+[0-9]+[[:space:]]+$BASE" || true)
[ -n "$sectors" ] || die "the phone has no $DEV - is an SD card inserted?"

# /sys/block/*/size is always in 512-byte units, whatever the device reports
# as its own logical block size.
dev_bytes=$(( sectors * 512 ))
echo "    $DEV: $dev_bytes bytes ($(( dev_bytes / 1024 / 1024 )) MiB), removable=${removable:-?}"
echo "    image:  $IMG_SIZE bytes ($(( IMG_SIZE / 1024 / 1024 )) MiB)"
echo "    /proc/partitions:"
echo "${parts:-(nothing)}" | sed 's/^/      /'
[ "$dev_bytes" -ge "$IMG_SIZE" ] || die "the card is smaller than the image"

if [ "$WHOLE_DISK" = 1 ]; then
	TARGET="$DEV"
	layout="the whole card as one ext4 filesystem, no partition table"
else
	TARGET="${DEV}p1"
	layout="a GPT with one partition, $TARGET, holding the filesystem"
fi

echo
say "plan"
echo "    $layout"
echo "    the phone listens on $PHONE_IP:$NCPORT and we push the image to it"
echo "    it writes what arrives straight to $TARGET with dd"
echo "    the initramfs then finds it by UUID and resize2fs grows it to fill"
if [ "$ASSUME_YES" != 1 ]; then
	echo
	say "stopping here: this would erase $DEV. Re-run with --yes to do it."
	exit 0
fi

# --- hold, then partition ---------------------------------------------------
trap cleanup EXIT INT TERM
say "holding off the phone's reset timer"
remote 'touch /pmhold' >/dev/null 2>&1 || true
HELD=1

if [ "$WHOLE_DISK" != 1 ]; then
	say "writing a GPT with one partition"
	# parted is a real binary in the initramfs, not a busybox applet. The
	# 1MiB start keeps the partition aligned to the card's erase block.
	out=$(remote_job "parted -s $DEV mklabel gpt
echo mklabel_rc=\$?
parted -s $DEV mkpart pmOS_root ext4 1MiB 100%
echo mkpart_rc=\$?
i=0
while [ \$i -lt 50 ]; do
	[ -b $TARGET ] && break
	i=\$((i + 1)); sleep 0.2
done
echo node=\$([ -b $TARGET ] && echo yes || echo no)
echo geom=\$(cat /sys/block/$BASE/${BASE}p1/size 2>/dev/null)
parted -s $DEV unit MiB print")
	echo "$out" | sed 's/^/    /'
	case "$(echo "$out" | sed -n 's/^node=//p' | head -1)" in
	yes) ;;
	*) die "$TARGET did not appear after partitioning" ;;
	esac
	psize=$(echo "$out" | sed -n 's/^geom=\([0-9][0-9]*\)$/\1/p' | head -1)
	[ -n "$psize" ] && [ "$psize" -ge "$(( IMG_SIZE / 512 ))" ] \
		|| die "$TARGET holds ${psize:-?} sectors, the image needs $(( IMG_SIZE / 512 ))"
fi

# --- send the image --------------------------------------------------------
# The phone listens and the host pushes. That is the opposite of the obvious
# arrangement, and the only one that works here: firewalld has the USB
# interface in the "public" zone and rejects inbound connections with
# icmp-host-prohibited, so the phone's wget said "Host is unreachable" while
# ping to the same address ran at 2 ms. Opening a port would be a change to
# the host system, which this project does not make. busybox nc -l on the
# phone needs permission from nobody.
say "starting the listener and the write on the phone"
remote "rm -f /tmp/sdwrite.log /tmp/sdwrite.done /tmp/sdwrite.sh
cat > /tmp/sdwrite.sh <<'PMWRITE'
nc -l -p $NCPORT | dd of=$TARGET bs=1M conv=fsync
echo dd_rc=\$?
sync
echo x > /tmp/sdwrite.done
PMWRITE
setsid /bin/sh -c 'sh /tmp/sdwrite.sh > /tmp/sdwrite.log 2>&1' >/dev/null 2>&1 &
sleep 1" >/dev/null 2>&1

say "pushing $(( IMG_SIZE / 1024 / 1024 )) MiB to $PHONE_IP:$NCPORT"
if ! python3 - "$IMG" "$PHONE_IP" "$NCPORT" <<'PYEOF'
import socket, sys, time
img, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
sock = None
for attempt in range(20):
    try:
        sock = socket.create_connection((host, port), timeout=10)
        break
    except OSError as err:
        if attempt == 19:
            sys.exit(f"could not reach {host}:{port}: {err}")
        time.sleep(1)
# The connect timeout stays on the socket and applies to sendall as well, and
# that killed a push at 166 MiB: whenever the phone's dd stops reading to
# flush a megabyte to the card, the window closes and the send blocks for
# longer than ten seconds. Generous but not infinite, so a dead cable still
# ends the run rather than hanging it.
sock.settimeout(300)
total = 0
started = time.time()
spoke = 0.0
with open(img, "rb") as fh:
    while True:
        chunk = fh.read(1 << 20)
        if not chunk:
            break
        sock.sendall(chunk)
        total += len(chunk)
        now = time.time()
        if now - spoke > 5:
            spoke = now
            rate = total / (now - started) / (1 << 20)
            print(f"    {total >> 20} MiB sent, {rate:.1f} MiB/s", flush=True)
sock.shutdown(socket.SHUT_WR)
sock.close()
print(f"    {total} bytes pushed in {time.time() - started:.0f}s", flush=True)
PYEOF
then
	die "pushing the image failed"
fi

say "waiting for the phone to finish writing (up to $TIMEOUT s)"
start=$(date +%s)
while :; do
	elapsed=$(( $(date +%s) - start ))
	[ "$elapsed" -lt "$TIMEOUT" ] || die "the write did not finish in $TIMEOUT s
       look at /tmp/sdwrite.log on the phone"
	case "$(remote 'M=WRITE; [ -e /tmp/sdwrite.done ] && echo "${M}_FINISHED"')" in
	*WRITE_FINISHED*) break ;;
	esac
	sleep 3
done

say "the phone's own account of it"
log=$(remote 'T=LOG; sed "s|^|${T}> |" /tmp/sdwrite.log 2>/dev/null' | sed -n 's/^LOG> //p')
echo "$log" | sed 's/^/    /'
echo "$log" | grep -q '^dd_rc=0$' \
	|| die "dd did not exit cleanly; the card holds a partial image"
written=$(echo "$log" | sed -n 's/^\([0-9][0-9]*\) bytes.*/\1/p' | head -1)
if [ -n "$written" ] && [ "$written" != "$IMG_SIZE" ]; then
	die "the phone wrote $written bytes, the image is $IMG_SIZE"
fi

# --- check it ---------------------------------------------------------------
say "checking the filesystem on the card"
# blkid is given one device to look at. A bare 'blkid' scans every block
# device on this phone and has taken the shell down with it - and even the
# single-device form runs detached, for the reason above remote_job.
out=$(remote_job "blkid -s UUID -o value $TARGET
echo uuid_rc=\$?
blkid -s TYPE -o value $TARGET
e2fsck -fn $TARGET 2>&1 | tail -3" 300)
echo "$out" | sed 's/^/    /'
got_uuid=$(echo "$out" | grep -Eo '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' | head -1)

want_uuid=$(dumpe2fs -h "$IMG" 2>/dev/null | sed -n 's/^Filesystem UUID: *//p' || true)
if [ -n "$want_uuid" ]; then
	if [ "$got_uuid" = "$want_uuid" ]; then
		say "the card reports the image's UUID: $want_uuid"
	else
		die "the card reports '$got_uuid', the image is '$want_uuid'"
	fi
fi

if [ "$VERIFY" = 1 ]; then
	say "reading the card back to compare (this takes a while)"
	host_sum=$(md5sum < "$IMG" | cut -d' ' -f1)
	dev_sum=$(remote "dd if=$TARGET bs=1M count=$(( IMG_SIZE / 1048576 )) 2>/dev/null | md5sum" \
		| grep -Eo '^[0-9a-f]{32}' | head -1)
	echo "    image: $host_sum"
	echo "    card:  ${dev_sum:-<no answer>}"
	[ "$host_sum" = "$dev_sum" ] || die "the card does not match the image"
	say "byte-for-byte identical"
fi

echo
say "done. The flashed command line already carries this filesystem's UUID,"
echo "    so stage 2 has a root to find. HANDOFF=1 STAGE=1 is the round that"
echo "    gets there; from a stock debug shell, 'pmos_continue_boot'."
