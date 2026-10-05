#!/bin/sh
# Get a postmarketOS build onto a Sony Xperia 10 VI (pdx246).
#
#   scripts/flash.sh ramboot          boot from RAM - REFUSED by this bootloader
#   scripts/flash.sh flash-boot       flash just boot+vendor_boot, reversible
#   scripts/flash.sh restore-boot     put the stock boot images back
#   scripts/flash.sh flash stock/     the full install, writes userdata too
#
# Read docs/04-flashing.md first.
#
# 'ramboot' was the intended starting point and this device will not do it:
# Sony's bootloader answers 'not supported' to fastboot boot, verified
# 2026-10-05 on bootloader 6450-0001_X_Boot_SM6450_LA2.0_U_19. The image
# uploads fine, only the boot command is refused, and staging vendor_boot
# first makes no difference.
#
# 'flash-boot' is what replaces it. It writes the two boot partitions on the
# active slot and nothing else: userdata, dtbo and vbmeta are untouched, so
# the installed system keeps its data and 'restore-boot' puts the stock
# kernel back from the dumps device-collect.sh made. That makes trying a
# kernel a two-minute round trip instead of a reinstall.
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
	echo "If that printed \"not supported\", this bootloader cannot RAM boot"
	echo "at all and no amount of staging changes it. Use 'flash-boot', which"
	echo "is reversible with 'restore-boot'. See docs/04-flashing.md."
}

# Where device-collect.sh leaves the stock images it dumped as root. These are
# what makes flash-boot reversible, so flash-boot refuses to run without them.
STOCK_DIR="$ROOT/out/device-dump-root/stock"

cmd_flash_boot() {
	need_boot_images
	read_slot
	for f in "boot_$slot.img" "vendor_boot_$slot.img"; do
		[ -f "$STOCK_DIR/$f" ] || die "missing $STOCK_DIR/$f, which is the way back.
       Run scripts/device-collect.sh from recovery, where adb has root,
       before writing anything here."
	done

	echo "Writing boot and vendor_boot on slot $slot. Nothing else is touched:"
	echo "  userdata keeps its data, dtbo keeps the parrot-qrd overlay that"
	echo "  turns our base parrot.dtb into this device's tree, and vbmeta is"
	echo "  left alone because an unlocked bootloader does not enforce it."
	echo
	echo "  boot:        $BOOT_IMG"
	echo "  vendor_boot: $VENDOR_BOOT_IMG"
	echo
	echo "To undo:  scripts/flash.sh restore-boot"
	echo
	printf 'Type FLASH to continue: '
	read -r reply
	[ "$reply" = "FLASH" ] || die "aborted"

	fastboot flash boot "$BOOT_IMG" || die "flashing boot failed"
	fastboot flash vendor_boot "$VENDOR_BOOT_IMG" || die "flashing vendor_boot failed"

	echo
	echo "Done. 'fastboot reboot' to try it, with scripts/console.sh running."
	echo "If nothing comes up, 'scripts/flash.sh restore-boot' puts stock back."
}

cmd_restore_boot() {
	command -v fastboot >/dev/null || die "fastboot not found"
	fastboot devices | grep -q . || die "no device in fastboot mode"
	read_slot
	for f in "boot_$slot.img" "vendor_boot_$slot.img"; do
		[ -f "$STOCK_DIR/$f" ] || die "missing $STOCK_DIR/$f - nothing to restore from"
	done
	echo "Restoring stock boot and vendor_boot on slot $slot."
	fastboot flash boot "$STOCK_DIR/boot_$slot.img" || die "restoring boot failed"
	fastboot flash vendor_boot "$STOCK_DIR/vendor_boot_$slot.img" || die "restoring vendor_boot failed"
	echo
	echo "Done. 'fastboot reboot' should bring the installed system back."
}

cmd_flash() {
	STOCK=${1:-}
	[ -n "$STOCK" ] || die "usage: $0 flash <stock-backup-dir>   (see docs/04-flashing.md)"
	[ -d "$STOCK" ] || die "$STOCK is not a directory"
	need_boot_images
	[ -f "$ROOTFS_IMG" ] || die "missing $ROOTFS_IMG - see docs/03-build.md on the rootfs image"
	# pmbootstrap allocates this file before it loop-mounts it, so a failed
	# install leaves a correctly sized but completely empty sparse file. Check
	# that there is a filesystem in there, not just that the file exists:
	# flashing the empty one writes zeros over userdata.
	#
	# Two shapes are valid. pmbootstrap's own image has a GPT ("EFI PART" at
	# offset 512); make-rootfs-img.sh produces a bare ext4, whose superblock
	# magic 0xef53 sits at offset 1080, little endian.
	gpt=$(dd if="$ROOTFS_IMG" bs=1 skip=512 count=8 2>/dev/null)
	ext4=$(dd if="$ROOTFS_IMG" bs=1 skip=1080 count=2 2>/dev/null | od -An -tx1 | tr -d ' \n')
	if [ "$gpt" = "EFI PART" ]; then
		echo "rootfs image: partitioned (GPT)"
	elif [ "$ext4" = "53ef" ]; then
		echo "rootfs image: bare ext4"
	else
		die "$ROOTFS_IMG holds neither a GPT nor an ext4 superblock - it was
       allocated but never filled, probably by an install that failed at
       'modprobe loop'. Do not flash it: it is all zeros and would wipe
       userdata. See docs/03-build.md on the rootfs image."
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
	ramboot)      shift; cmd_ramboot "$@" ;;
	flash-boot)   shift; cmd_flash_boot "$@" ;;
	restore-boot) shift; cmd_restore_boot "$@" ;;
	flash)        shift; cmd_flash "$@" ;;
	*)            die "usage: $0 flash-boot | $0 restore-boot | $0 ramboot | $0 flash <stock-backup-dir>" ;;
esac
