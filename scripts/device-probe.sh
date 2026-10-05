#!/bin/sh
# Read everything useful off a stock, still-locked pdx246 over adb.
#
#   scripts/device-probe.sh
#
# Runs on the host, where adb lives. Writes nothing to the device, needs no
# root and no unlock, so it is safe to run on a phone you still care about.
# Point of the exercise: find out whether the assumptions in docs/01-device.md
# and scripts/flash.sh hold against the real hardware, *before* unlocking
# wipes it. Everything here is read-only.
#
# Deliberately does not collect the IMEI. The unlock code is tied to it, so
# you will need it, but it does not belong in a file in this repo - read it
# off the dialer with *#06# when you are on Sony's site.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
die() { echo "error: $*" >&2; exit 1; }
say() { echo; echo "==> $*"; }

command -v adb >/dev/null || die "adb not found on the host"

state=$(adb get-state 2>/dev/null || true)
case "$state" in
	device) ;;
	unauthorized) die "device is unauthorized - accept the RSA prompt on the phone" ;;
	"") die "no device over adb. Enable USB debugging in Developer options,
       plug it in, and accept the prompt on the phone." ;;
	*) die "device is in state '$state', not 'device'" ;;
esac

# adb shell getprop is cheap in bulk and expensive one at a time.
PROPS=$(adb shell getprop 2>/dev/null) || die "could not read properties"
prop() { echo "$PROPS" | sed -n "s/^\[$1\]: \[\(.*\)\]$/\1/p" | head -1; }

say "device"
for p in ro.product.model ro.product.name ro.product.device ro.board.platform \
         ro.build.version.release ro.build.version.security_patch ro.build.id \
         ro.build.display.id; do
	printf '    %-38s %s\n' "$p" "$(prop "$p")"
done

say "does this match what the port assumes?"
# docs/01-device.md claims pdx246 / SM6450 "parrot". If either of these is not
# what we built for, stop: the images are for a different phone.
dev=$(prop ro.product.device); plat=$(prop ro.board.platform)
case "$dev" in
	*pdx246*) echo "    device  $dev  (expected pdx246)" ;;
	*) echo "    MISMATCH: device is '$dev', not pdx246. These images are not for this phone." ;;
esac
case "$plat" in
	parrot|*6450*) echo "    platform $plat  (expected parrot / SM6450)" ;;
	*) echo "    MISMATCH: platform is '$plat', not parrot/SM6450." ;;
esac

say "lock and verified boot state"
# sys.oem_unlock_allowed is the one that decides whether Sony's unlock can
# even be attempted: it reflects the "OEM unlocking" toggle in Developer
# options, which has to be on *before* rebooting to the bootloader.
for p in ro.boot.flash.locked ro.boot.verifiedbootstate ro.boot.veritymode \
         sys.oem_unlock_allowed ro.oem_unlock_supported ro.boot.slot_suffix; do
	printf '    %-38s %s\n' "$p" "$(prop "$p")"
done
case "$(prop sys.oem_unlock_allowed)" in
	1) echo "    -> OEM unlocking is ENABLED. Sony's unlock can be attempted." ;;
	0) echo "    -> OEM unlocking is OFF. Turn it on in Developer options first;
       the bootloader will refuse the unlock without it." ;;
	*) echo "    -> could not read the OEM unlock state" ;;
esac

say "kernel we are replacing"
adb shell cat /proc/version 2>/dev/null | sed 's/^/    /' || echo "    unavailable"

say "partitions flash.sh will write"
# Listing by-name needs no root. Sizes do, so this only confirms the names
# exist and which slot suffixes are present.
byname=$(adb shell 'ls /dev/block/by-name/ 2>/dev/null' || true)
if [ -z "$byname" ]; then
	echo "    could not list /dev/block/by-name (restricted on this build)"
else
	for p in boot vendor_boot dtbo vbmeta vbmeta_system userdata; do
		hits=$(echo "$byname" | tr -d '\r' | grep -x "${p}\(_a\|_b\)\?" | tr '\n' ' ' || true)
		printf '    %-16s %s\n' "$p" "${hits:-MISSING}"
	done
	echo "    (total $(echo "$byname" | tr -d '\r' | grep -c . ) entries)"
fi

say "pstore / ramoops - the console of last resort"
# docs/04-flashing.md leans on this when nothing enumerates over USB. Worth
# knowing now whether stock exposes it at all.
adb shell 'ls /sys/fs/pstore/ 2>/dev/null' | tr -d '\r' | sed 's/^/    /' \
	| grep . || echo "    /sys/fs/pstore is empty or not readable (normal after a clean boot)"

say "A/B slot"
printf '    %-38s %s\n' "current slot suffix" "$(prop ro.boot.slot_suffix)"

echo
echo "Nothing was written to the device."
echo
echo "Next, in order:"
echo "  1. Back up stock firmware. You cannot dd the partitions without root,"
echo "     and you cannot get root without unlocking, which wipes - so the"
echo "     backup is a firmware *download* (XperiFirm/Newflasher), not a dump."
echo "     See docs/04-flashing.md."
echo "  2. Enable OEM unlocking in Developer options, if the check above said OFF."
echo "  3. Get the unlock code from Sony, using the IMEI from *#06#."
echo "  4. scripts/flash.sh ramboot"
