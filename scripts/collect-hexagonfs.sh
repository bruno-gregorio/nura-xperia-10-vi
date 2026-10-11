#!/bin/sh
# Copy what the ADSP's sensors process reads from Linux, read-only, from
# recovery.
#
#   scripts/collect-hexagonfs.sh
#
# The sensors run on the ADSP, in its sensors protection domain. Stock starts
# that domain with /vendor/bin/sscrpcd, which also serves it files through
# FastRPC's reverse tunnel; on postmarketOS hexagonrpcd does the same job and
# serves a directory tree instead of Android's paths. Its README maps them:
#
#   sensors/config        /vendor/etc/sensors/config
#   sensors/sns_reg.conf  /vendor/etc/sensors/sns_reg_config
#   sensors/registry      /mnt/vendor/persist/sensors/registry/registry
#   socinfo               /sys/devices/soc0
#
# The first two come from the vendor image and are already in
# out/hexagonfs/stage. This reads the other two:
#
# - The registry, from the persist partition. hexagonrpcd serves files
#   read-only, so the ADSP cannot build its registry from the JSON configs
#   the way it does on stock and has to be handed the one stock already
#   built. Persist also holds this phone's calibration and identity, so the
#   image is read to out/, only sensors/registry/registry is extracted from
#   it, and the image is deleted again. Nothing from persist goes into git.
# - Six files of the stock kernel's /sys/devices/soc0: the ones stock's
#   sns_reg_config names. Never serial_number.
#
# Like collect-firmware.sh this needs recovery, where adb is root, and writes
# nothing on the phone.
#
# Out: out/hexagonfs/stage/sensors/registry/ and out/hexagonfs/stage/socinfo/.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STAGE="$ROOT/out/hexagonfs/stage"
TMP="$ROOT/out/hexagonfs/persist.tmp"

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

adb devices 2>/dev/null | sed 1d | grep -qE 'recovery$' \
	|| die "the phone is not in recovery"
[ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = 0 ] \
	|| die "adb is not root here - this needs recovery"

mkdir -p "$STAGE"

# soc0 first: it is six small reads, and it does not depend on persist.
soc="$STAGE/socinfo"
mkdir -p "$soc.part"
for f in hw_platform platform_subtype platform_subtype_id platform_version \
	soc_id revision; do
	adb exec-out "cat /sys/devices/soc0/$f" > "$soc.part/$f" \
		|| die "could not read soc0/$f"
	[ -s "$soc.part/$f" ] || die "soc0/$f is empty"
done
rm -rf "${soc:?}"
mv -- "$soc.part" "$soc"
say "socinfo: $(for f in "$soc"/*; do printf '%s=%s ' "${f##*/}" "$(tr -d '\n' < "$f")"; done)"

dev=/dev/block/by-name/persist
size=$(adb shell "blockdev --getsize64 $dev" 2>/dev/null | tr -d '\r')
case "$size" in
'' | *[!0-9]*) die "could not size $dev" ;;
esac

reg="$STAGE/sensors/registry"
rm -rf "${TMP:?}"
mkdir -p "$TMP"
trap 'rm -rf "${TMP:?}"' EXIT
img="$TMP/persist.img"
say "reading persist, $size bytes"
for try in 1 2 3; do
	adb exec-out "dd if=$dev bs=1048576 2>/dev/null" > "$img" || true
	[ "$(wc -c < "$img")" = "$size" ] && break
	[ "$try" = 3 ] && die "persist came back $(wc -c < "$img") bytes of $size three times"
	say "short read; again in ten seconds"
	command sleep 10
done

# debugfs opens the image read-only unless told -w. rdump recreates the
# directory under the destination by its own name, so it lands in
# $TMP/out/registry.
mkdir -p "$TMP/out"
(cd "$ROOT" && distrobox enter pmport -- sh -c \
	'debugfs -R "ls -l /sensors/registry/registry" "$1" && debugfs -R "rdump /sensors/registry/registry $2" "$1"' \
	sh "$img" "$TMP/out" < /dev/null) \
	|| die "could not read sensors/registry/registry from persist"
[ -d "$TMP/out/registry" ] || die "persist has no sensors/registry/registry"
n=$(find "$TMP/out/registry" -type f | wc -l)
[ "$n" -gt 0 ] || die "persist's sensors registry is empty"
rm -rf "${reg:?}"
mkdir -p "$STAGE/sensors"
mv -- "$TMP/out/registry" "$reg"
say "registry: $n files in $reg"
