#!/bin/sh
# Copy the stock firmware partition off the phone, read-only, from recovery.
#
#   scripts/collect-firmware.sh
#
# The remote processors' firmware - ADSP, CDSP, modem, WPSS - is in the
# `modem` partition of each slot: a FAT image that Android mounts at
# /vendor/firmware_mnt. It is Qualcomm's and Sony's and not redistributable,
# so it lives only in out/firmware/, which git ignores, and nothing in this
# project packages it.
#
# This reads exactly one partition, modem_a or modem_b - whichever slot
# recovery booted from - with dd, and writes nothing on the phone. It never
# opens modemst1, modemst2, fsg or persist, which hold the device's EFS and
# its identity. It needs recovery, where adb is root. A queue plan can call
# it right after a round, because try-kernel --log leaves the phone in
# recovery. Run it again and it reads nothing it already has.
#
# Out: out/firmware/modem_X.img, its listing, and the files under
# out/firmware/modem_X/, extracted with mtools in the pmport container.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/out/firmware"

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

adb devices 2>/dev/null | sed 1d | grep -qE 'recovery$' \
	|| die "the phone is not in recovery"
[ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = 0 ] \
	|| die "adb is not root here - this needs recovery"

slot=$(adb shell getprop ro.boot.slot_suffix 2>/dev/null | tr -d '\r')
case "$slot" in
_a | _b) ;;
*) die "recovery reports slot '$slot'" ;;
esac
part=modem$slot
dev=/dev/block/by-name/$part
size=$(adb shell "blockdev --getsize64 $dev" 2>/dev/null | tr -d '\r')
case "$size" in
'' | *[!0-9]*) die "could not size $dev" ;;
esac

mkdir -p "$OUT"
img="$OUT/$part.img"
if [ -f "$img" ] && [ "$(wc -c < "$img")" = "$size" ]; then
	say "$part is already in $img"
else
	say "reading $part, $size bytes"
	# Recovery's adb can drop while it settles its USB configuration;
	# try-kernel's settle_adb has the story. A short read is read again.
	for try in 1 2 3; do
		adb exec-out "dd if=$dev bs=1048576 2>/dev/null" > "$img.part" || true
		[ "$(wc -c < "$img.part")" = "$size" ] && break
		[ "$try" = 3 ] && die "$part came back $(wc -c < "$img.part") bytes of $size three times"
		say "short read; again in ten seconds"
		command sleep 10
	done
	mv -- "$img.part" "$img"
fi

# The partition is a bare FAT filesystem with no partition table, which
# mtools reads directly. MTOOLS_SKIP_CHECK because Qualcomm's FAT images
# often carry geometry mtools would otherwise refuse.
dest="$OUT/$part"
if [ ! -d "$dest" ]; then
	say "extracting to $dest"
	mkdir -p "$dest.part"
	(cd "$ROOT" && distrobox enter pmport -- env MTOOLS_SKIP_CHECK=1 sh -c \
		'mdir -/ -b -i "$1" :: > "$2" && mcopy -s -n -i "$1" "::/*" "$3/"' \
		sh "$img" "$OUT/$part.listing" "$dest.part" < /dev/null) \
		|| die "could not read the FAT image"
	mv -- "$dest.part" "$dest"
fi
say "$(wc -l < "$OUT/$part.listing") entries; the ones the remote processors load:"
grep -i -E '/(adsp|cdsp|modem|qdsp6m|wpss)[^/]*\.(mdt|mbn)$' "$OUT/$part.listing" || true
