#!/bin/sh
# Put the rootfs on the phone's SD card, over the USB cable, hands-free.
#
#   ./scripts/sdcard-install.sh            # look, change nothing
#   ./scripts/sdcard-install.sh --yes      # actually write
#
# The phone must be sitting in the initramfs debug shell with USB up, i.e.
# telnet 172.16.42.1:23 answers. scripts/try-kernel.sh gets it there.
#
# Why the SD card and not userdata: it is the one writable bulk device on this
# phone that no Android partition claims, so a broken rootfs costs an SD write
# and not a trip through fastboot. Chosen by the owner on 2026-10-05.
#
# How the bytes get across: there is no adb and no MTP in an initramfs, but
# there is busybox wget, and the gadget already gives us an IP link. So the
# host serves the image over HTTP on the USB interface only - not on the LAN -
# and the phone pulls it straight into dd. Nothing is staged on the phone,
# which matters because the rootfs is a good deal larger than its RAM.
#
# The write runs detached under setsid with its output in a file, and this
# script polls that file over short telnet connections. scripts/telnet.py stops
# reading two seconds after its piped input ends, so a command that runs for
# minutes cannot be driven from one connection - and a session that drops
# mid-write would otherwise take dd with it.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

PHONE_IP=172.16.42.1          # the gadget, per unudhcpd in the initramfs
HOST_IP=172.16.42.2           # us, on the USB interface
PORT=8099
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
	  --port N        host HTTP port (default $PORT)
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
	--port) PORT="$2"; shift 2 ;;
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
# One short telnet connection per batch. The debug shell's telnetd runs
# /bin/sh -l with no login prompt, so commands can be piped straight in.
remote() {
	printf '%s\nexit\n' "$1" \
		| python3 "$ROOT/scripts/telnet.py" "$PHONE_IP" 23 2>/dev/null
}

say "checking the phone answers on $PHONE_IP"
ping -c 2 -W 2 "$PHONE_IP" >/dev/null 2>&1 \
	|| die "no ping to $PHONE_IP - is the phone in the initramfs debug shell?"
probe=$(remote 'echo PMOS_OK; uname -r') || true
case "$probe" in
*PMOS_OK*) ;;
*) die "telnet to $PHONE_IP:23 did not answer a shell
       got: $(echo "$probe" | tr -d '\r' | tr '\n' ' ')" ;;
esac
say "shell is up, kernel $(echo "$probe" | tr -d '\r' | sed -n 's/^\([0-9]\..*\)$/\1/p' | head -1)"

# The host end of the USB link has to exist, or the phone has nothing to fetch
# from. NetworkManager configures it by DHCP from the phone's unudhcpd.
ip -o addr show | grep -q " $HOST_IP/" \
	|| die "no interface on this host holds $HOST_IP
       the USB network is not configured; see scripts/console.sh"

# --- stop the clock --------------------------------------------------------
# Both the staged probe and the patched real init reset the phone on a timer
# measured in minutes, which is right for an unattended boot and wrong while a
# gigabyte is going onto the card. /pmhold makes those resets wait. It has to
# come off again, or the phone stops being hands-free, so the trap goes in at
# the same moment.
HELD=0
HTTP_PID=
SERVE_DIR=
cleanup() {
	[ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null
	if [ -n "$SERVE_DIR" ]; then
		rm -f "$SERVE_DIR/rootfs.img" "$SERVE_DIR/http.log"
		rmdir "$SERVE_DIR" 2>/dev/null
	fi
	if [ "$HELD" = 1 ]; then
		remote 'rm -f /pmhold' >/dev/null 2>&1
		echo "==> released /pmhold; the phone's own reset timer is live again"
	fi
	return 0
}

# --- what we are about to overwrite ----------------------------------------
say "looking at $DEV on the phone"
info=$(remote "
cat /sys/block/$BASE/size 2>/dev/null || echo MISSING
cat /sys/block/$BASE/removable 2>/dev/null || echo '?'
echo ---
grep -w '$BASE' /proc/partitions || echo '(not in /proc/partitions)'
grep '${BASE}p' /proc/partitions || true
")
sectors=$(echo "$info" | tr -d '\r' | sed -n 1p)
case "$sectors" in
'' | MISSING | *[!0-9]*)
	die "the phone has no $DEV - is an SD card inserted?
       /proc/partitions said:
$(echo "$info" | tr -d '\r' | sed -n '/^---$/,$p' | sed '1d;s/^/         /')" ;;
esac
# /sys/block/*/size is always in 512-byte units, whatever the device reports
# as its logical block size.
dev_bytes=$(( sectors * 512 ))
echo "    $DEV: $dev_bytes bytes ($(( dev_bytes / 1024 / 1024 )) MiB)"
echo "    image:  $IMG_SIZE bytes ($(( IMG_SIZE / 1024 / 1024 )) MiB)"
echo "$info" | tr -d '\r' | sed -n '/^---$/,$p' | sed '1d;s/^/    /'
[ "$dev_bytes" -ge "$IMG_SIZE" ] \
	|| die "the card is smaller than the image"

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
echo "    serve $IMG on http://$HOST_IP:$PORT/ (USB interface only)"
echo "    phone pulls it with wget and writes it to $TARGET with dd"
echo "    the initramfs then finds it by UUID and resize2fs grows it to fill"
if [ "$ASSUME_YES" != 1 ]; then
	echo
	say "stopping here: this would erase $DEV. Re-run with --yes to do it."
	exit 0
fi

# --- partition -------------------------------------------------------------
trap cleanup EXIT INT TERM
say "holding off the phone's reset timer"
remote 'touch /pmhold; echo held' >/dev/null 2>&1 || true
HELD=1

if [ "$WHOLE_DISK" != 1 ]; then
	say "writing a GPT with one partition"
	# parted is a real binary in the initramfs, not a busybox applet.
	# 1MiB start keeps the partition aligned to the erase block.
	out=$(remote "
parted -s '$DEV' mklabel gpt
parted -s '$DEV' mkpart pmOS_root ext4 1MiB 100%
i=0
while [ \$i -lt 50 ]; do
	[ -b '$TARGET' ] && break
	i=\$((i + 1)); sleep 0.2
done
echo ---
parted -s '$DEV' print 2>&1 | sed -n '1,12p'
[ -b '$TARGET' ] && echo NODE_OK || echo NODE_MISSING
")
	echo "$out" | tr -d '\r' | sed -n '/^---$/,$p' | sed '1d;s/^/    /'
	case "$out" in
	*NODE_OK*) ;;
	*) die "$TARGET did not appear after partitioning" ;;
	esac
fi

# --- serve the image -------------------------------------------------------
# Bound to the USB address alone. On 0.0.0.0 this would also be reachable from
# the wireless network, which is not something a build script should do.
SERVE_DIR=$(mktemp -d)
ln -s "$IMG" "$SERVE_DIR/rootfs.img"
say "serving on http://$HOST_IP:$PORT/rootfs.img"
python3 -m http.server "$PORT" --bind "$HOST_IP" --directory "$SERVE_DIR" \
	>"$SERVE_DIR/http.log" 2>&1 &
HTTP_PID=$!
sleep 1
kill -0 "$HTTP_PID" 2>/dev/null || die "the HTTP server did not start:
$(cat "$SERVE_DIR/http.log")"

# --- write -----------------------------------------------------------------
# setsid detaches the pipeline from the telnet session, so dd keeps going when
# this connection closes a moment from now. The exit status of wget matters as
# much as dd's: a truncated download would otherwise look like a short write,
# so both are recorded.
say "starting the write on the phone"
remote "
rm -f /tmp/sdwrite.log /tmp/sdwrite.done
setsid sh -c '
	{ wget -O - http://$HOST_IP:$PORT/rootfs.img || echo WGET_FAILED=\$?; } \
		| dd of=$TARGET bs=1M conv=fsync
	echo \"dd_exit=\$?\"
	sync
	echo done > /tmp/sdwrite.done
' > /tmp/sdwrite.log 2>&1 &
sleep 1
echo started
" >/dev/null

say "waiting for it to finish (up to $TIMEOUT s)"
start=$(date +%s)
last=""
while :; do
	now=$(date +%s)
	elapsed=$(( now - start ))
	[ "$elapsed" -lt "$TIMEOUT" ] || die "the write did not finish in $TIMEOUT s
       look at /tmp/sdwrite.log on the phone"

	# Progress comes from the host side: the HTTP server logs nothing useful
	# mid-transfer, but the card's own sector counter does move.
	st=$(remote "
[ -e /tmp/sdwrite.done ] && echo FINISHED
cat /sys/block/$BASE/stat 2>/dev/null | awk '{print \$7}'
" 2>/dev/null) || st=""
	wrote=$(echo "$st" | tr -d '\r' | grep -E '^[0-9]+$' | head -1)
	if [ -n "$wrote" ]; then
		mib=$(( wrote / 2048 ))
		if [ "$mib" != "$last" ]; then
			printf '\r    %s s, %s MiB written   ' "$elapsed" "$mib"
			last="$mib"
		fi
	fi
	case "$st" in
	*FINISHED*) echo; break ;;
	esac
	sleep 5
done

say "the phone's own account of it"
remote 'cat /tmp/sdwrite.log' | tr -d '\r' | sed 's/^/    /'

log=$(remote 'cat /tmp/sdwrite.log')
case "$log" in
*WGET_FAILED*) die "the download failed; the card holds a partial image" ;;
esac
case "$log" in
*dd_exit=0*) ;;
*) die "dd did not exit cleanly; the card holds a partial image" ;;
esac

# --- check it ---------------------------------------------------------------
say "checking the filesystem on the card"
# blkid is given one device to look at. A bare 'blkid' scans every block
# device on this phone and has taken the debug shell down with it.
out=$(remote "
blkid $TARGET
e2fsck -fn $TARGET 2>&1 | tail -4
")
echo "$out" | tr -d '\r' | sed 's/^/    /'

want_uuid=$(dumpe2fs -h "$IMG" 2>/dev/null | sed -n 's/^Filesystem UUID: *//p' || true)
if [ -n "$want_uuid" ]; then
	case "$out" in
	*"$want_uuid"*) say "UUID on the card matches the image: $want_uuid" ;;
	*) echo "    WARNING: the card does not report the image's UUID ($want_uuid)" ;;
	esac
fi

if [ "$VERIFY" = 1 ]; then
	say "reading the card back to compare (this takes a while)"
	host_sum=$(md5sum < "$IMG" | cut -d' ' -f1)
	dev_sum=$(remote "dd if=$TARGET bs=1M count=$(( IMG_SIZE / 1048576 )) 2>/dev/null | md5sum" \
		| tr -d '\r' | grep -Eo '^[0-9a-f]{32}' | head -1)
	echo "    image: $host_sum"
	echo "    card:  ${dev_sum:-<no answer>}"
	[ "$host_sum" = "$dev_sum" ] || die "the card does not match the image"
	say "byte-for-byte identical"
fi

echo
say "done. The cmdline already carries this filesystem's UUID, so a reboot"
echo "    into our kernel should now find a root to switch into. From the"
echo "    debug shell, 'pmos_continue_boot' carries on without a reflash."
