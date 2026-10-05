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
# docs/01-device.md claims pdx246 / SM6450 "parrot". Take the codename from the
# odm and vendor properties rather than ro.product.device: that one carries the
# market model (XQ-ES72 and its siblings), and when a GSI is installed the
# system properties are replaced wholesale while odm and vendor stay Sony's.
dev=$(prop ro.product.odm.device)
[ -n "$dev" ] || dev=$(prop ro.product.vendor.device)
[ -n "$dev" ] || dev=$(prop ro.product.device)
model=$(prop ro.product.device); plat=$(prop ro.board.platform)
case "$dev$(prop ro.bootimage.build.fingerprint)" in
	*pdx246*) echo "    codename $dev  (expected pdx246), market model $model" ;;
	*) echo "    MISMATCH: codename is '$dev', not pdx246. These images are not for this phone." ;;
esac
case "$plat" in
	parrot|*6450*) echo "    platform $plat  (expected parrot / SM6450)" ;;
	*) echo "    MISMATCH: platform is '$plat', not parrot/SM6450." ;;
esac

say "lock and verified boot state"
# Read this section as a claim, not as the state. Every property here is set by
# whatever is running as the system image, and GSIs rewrite exactly these to
# pass Play Integrity: a phh-based GSI reports flash.locked=1,
# verifiedbootstate=green and veritymode=enforcing on a device that is in fact
# unlocked. The only authority is the bootloader, via 'fastboot getvar
# unlocked' - which is why flash.sh reads the slot from fastboot and not here.
for p in ro.boot.flash.locked ro.boot.verifiedbootstate ro.boot.veritymode \
         ro.boot.vbmeta.device_state sys.oem_unlock_allowed \
         ro.oem_unlock_supported ro.boot.slot_suffix; do
	printf '    %-38s %s\n' "$p" "$(prop "$p")"
done
# The keymaster HAL publishes its own copy from the real values, and property
# spoofing tends to miss it, so a disagreement between the two is itself the
# tell that the ro.boot.* ones have been rewritten.
for p in ro.keymaster.xxx.vbmeta_state ro.keymaster.xxx.verifiedbootstate; do
	v=$(prop "$p"); [ -n "$v" ] && printf '    %-38s %s\n' "$p" "$v"
done

gsi="$(prop ro.lineage.version) $(prop ro.build.flavor) $(prop ro.product.bootimage.name)"
case "$gsi" in
	*GSI*|*gsi*|*generic*)
		echo "    -> a GSI is running ($(echo $gsi)), so the properties above"
		echo "       describe the GSI, not the bootloader. A GSI cannot be"
		echo "       installed on a locked device, so this device is unlocked"
		echo "       whatever flash.locked says. Confirm in the bootloader:"
		echo "       fastboot getvar unlocked" ;;
	*)
		case "$(prop sys.oem_unlock_allowed)" in
			1) echo "    -> OEM unlocking is ENABLED. Sony's unlock can be attempted." ;;
			0) echo "    -> OEM unlocking is OFF. If the device is still locked, turn
       it on in Developer options first; the bootloader will refuse
       the unlock without it." ;;
			*) echo "    -> could not read the OEM unlock state" ;;
		esac ;;
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
