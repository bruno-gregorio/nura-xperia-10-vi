#!/bin/sh
# Flash a built postmarketOS image to a Sony Xperia 10 VI (pdx246).
#
# Read docs/04-flashing.md first. This script deliberately refuses to run until
# you have backups, because the two ways to make this device unbootable are
# both recoverable only from them.
#
#   scripts/flash.sh stock/
#
# where stock/ holds the partition dumps taken in step 1 of 04-flashing.md.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/.pmb/work/chroot_native/home/pmos/rootfs"
STOCK=${1:-}

die() { echo "error: $*" >&2; exit 1; }

[ -n "$STOCK" ] || die "usage: $0 <stock-backup-dir>   (see docs/04-flashing.md)"
[ -d "$STOCK" ] || die "$STOCK is not a directory"

# The vbmeta we patch has to be the device's own: an avbtool-generated empty
# one carries rollback index 0 and the bootloader enforces anti-rollback in
# hardware, red-stating the device regardless of the disable flags.
for f in boot_a.img vendor_boot_a.img vbmeta_a.img; do
	[ -f "$STOCK/$f" ] || die "missing backup $STOCK/$f - do not flash without it"
done

BOOT="$OUT/sony-pdx246-boot.img"
VENDOR_BOOT="$OUT/sony-pdx246-vendor_boot.img"
ROOTFS="$OUT/sony-pdx246-root.img"
for f in "$BOOT" "$VENDOR_BOOT" "$ROOTFS"; do
	[ -f "$f" ] || die "missing $f - run 'pmb install --no-fde --split' first"
done

command -v fastboot >/dev/null || die "fastboot not found"
fastboot devices | grep -q . || die "no device in fastboot mode"

slot=$(fastboot getvar current-slot 2>&1 | sed -n 's/^current-slot: *//p' | head -1)
echo "active slot: ${slot:-unknown}"
echo
echo "About to flash boot, vendor_boot, vbmeta and userdata on this slot."
echo "The dtbo partition is deliberately NOT touched: its stock parrot-qrd"
echo "overlay is what turns our base parrot.dtb into this device's tree."
echo
printf 'Type FLASH to continue: '
read -r reply
[ "$reply" = "FLASH" ] || die "aborted"

# Patch the flags in the device's own vbmeta rather than replacing it.
fastboot --disable-verity --disable-verification flash vbmeta "$STOCK/vbmeta_a.img"
fastboot flash boot "$BOOT"
fastboot flash vendor_boot "$VENDOR_BOOT"
fastboot flash userdata "$ROOTFS"

echo
echo "Done. 'fastboot reboot' to try it."
echo "If it does not come up, see docs/04-flashing.md - and remember"
echo "'fastboot --set-active=${slot:-b}' gets you back to the other slot."
