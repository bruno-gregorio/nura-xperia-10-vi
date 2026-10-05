#!/bin/sh
# Get a postmarketOS build onto a Sony Xperia 10 VI (pdx246).
#
#   scripts/flash.sh ramboot          boot it from RAM, writing nothing
#   scripts/flash.sh flash stock/     flash it, needs the backups from step 1
#
# Read docs/04-flashing.md first. 'ramboot' is the one to start with: it
# answers "does this kernel come up at all" without touching a partition, so
# there is nothing to undo if the answer is no.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEVICE=sony-pdx246
BOOT="$ROOT/.pmb/work/chroot_rootfs_$DEVICE/boot"
IMAGES="$ROOT/.pmb/work/chroot_native/home/pmos/rootfs"

# The fastboot images come out of the rootfs chroot's /boot, where boot-deploy
# writes them - not from home/pmos/rootfs, which holds the partition images.
# pmbootstrap's own fastboot flasher uses "$BOOT/boot.img" and
# "$BOOT/vendor_boot.img" for exactly this reason.
BOOT_IMG="$BOOT/boot.img"
VENDOR_BOOT_IMG="$BOOT/vendor_boot.img"
# The 'fastboot' flasher flashes $IMAGE, the combined image with /boot and /
# as subpartitions. The split images belong to 'fastboot-bootpart', which this
# device does not use.
ROOTFS_IMG="$IMAGES/$DEVICE.img"

die() { echo "error: $*" >&2; exit 1; }

need_boot_images() {
	for f in "$BOOT_IMG" "$VENDOR_BOOT_IMG"; do
		[ -f "$f" ] || die "missing $f - run 'pmb install' first"
	done
	command -v fastboot >/dev/null || die "fastboot not found"
	fastboot devices | grep -q . || die "no device in fastboot mode"
}

# Reads the active slot and sets $slot and $other. Refuses to guess.
read_slot() {
	slot=$(fastboot getvar current-slot 2>&1 | sed -n 's/^current-slot: *//p' | head -1)
	case "$slot" in
		a) other=b ;;
		b) other=a ;;
		*) die "could not read current-slot from fastboot (got '${slot:-}')" ;;
	esac
}

cmd_ramboot() {
	need_boot_images
	echo "Booting from RAM. Nothing is written to the device."
	echo "  vendor_boot: $VENDOR_BOOT_IMG"
	echo "  boot:        $BOOT_IMG"
	echo
	# Header v4 splits the DTB and ramdisk into vendor_boot, so it has to be
	# staged before the kernel is handed over. This is pmbootstrap's 'boot_gki'.
	fastboot stage "$VENDOR_BOOT_IMG"
	fastboot boot "$BOOT_IMG"
	echo
	echo "If the bootloader refuses this, it is locked down against RAM boot;"
	echo "use 'flash' instead. Otherwise see docs/04-flashing.md for how to"
	echo "reach the debug shell over the USB-C cable."
}

cmd_flash() {
	STOCK=${1:-}
	[ -n "$STOCK" ] || die "usage: $0 flash <stock-backup-dir>   (see docs/04-flashing.md)"
	[ -d "$STOCK" ] || die "$STOCK is not a directory"
	need_boot_images
	[ -f "$ROOTFS_IMG" ] || die "missing $ROOTFS_IMG - see docs/03-build.md on the rootfs image"
	# pmbootstrap allocates this file before it loop-mounts it, so a failed
	# install leaves a correctly sized but completely empty sparse file. Check
	# for the GPT, not just for the file: flashing the empty one writes zeros
	# over userdata.
	if [ "$(dd if="$ROOTFS_IMG" bs=1 skip=512 count=8 2>/dev/null)" != "EFI PART" ]; then
		die "$ROOTFS_IMG has no partition table - it was allocated but never
       filled, probably by an install that failed at 'modprobe loop'.
       Do not flash it. See docs/03-build.md on the rootfs image."
	fi

	# Bare 'fastboot flash boot' writes the active slot, so the backups we
	# check for and the vbmeta we send back have to be that slot's. On a device
	# that has taken an OTA the two slots are not interchangeable.
	read_slot
	echo "active slot: $slot   (fallback slot: $other)"

	# The vbmeta we patch has to be the device's own: an avbtool-generated
	# empty one carries rollback index 0 and the bootloader enforces
	# anti-rollback in hardware, red-stating the device regardless of the
	# disable flags.
	for f in "boot_$slot.img" "vendor_boot_$slot.img" "vbmeta_$slot.img"; do
		[ -f "$STOCK/$f" ] || die "missing backup $STOCK/$f - do not flash without it"
	done

	echo
	echo "About to flash boot, vendor_boot, vbmeta and userdata on slot $slot."
	echo "The dtbo partition is deliberately NOT touched: its stock parrot-qrd"
	echo "overlay is what turns our base parrot.dtb into this device's tree."
	echo
	printf 'Type FLASH to continue: '
	read -r reply
	[ "$reply" = "FLASH" ] || die "aborted"

	# Patch the flags in the device's own vbmeta rather than replacing it.
	fastboot --disable-verity --disable-verification flash vbmeta "$STOCK/vbmeta_$slot.img"
	fastboot flash boot "$BOOT_IMG"
	fastboot flash vendor_boot "$VENDOR_BOOT_IMG"
	fastboot flash userdata "$ROOTFS_IMG"

	echo
	echo "Done. 'fastboot reboot' to try it."
	echo "If it does not come up, see docs/04-flashing.md - and remember"
	echo "'fastboot --set-active=$other' boots the slot this did not touch."
}

case "${1:-}" in
	ramboot) shift; cmd_ramboot "$@" ;;
	flash)   shift; cmd_flash "$@" ;;
	*)       die "usage: $0 ramboot | $0 flash <stock-backup-dir>" ;;
esac
