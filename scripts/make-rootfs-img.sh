#!/bin/sh
# Build the rootfs image without loop devices.
#
#   distrobox enter pmport -- ./scripts/make-rootfs-img.sh
#
# pmbootstrap builds this image by allocating a file, attaching it to a loop
# device, partitioning, formatting and copying into the mount. A rootless
# container cannot do that: /dev/loop-control is root:disk, and even with
# access to it, mounting a loop device needs CAP_SYS_ADMIN in the *initial*
# user namespace. See docs/03-build.md.
#
# mkfs.ext4 -d sidesteps the whole problem - it populates a filesystem image
# from a directory tree without ever mounting anything. Run as the container's
# mapped root, so the ownership in the chroot is read and written correctly.
#
# The result is what 'pmb install --single-partition' would produce: one ext4
# filesystem labelled pmOS_root, no partition table. The initramfs finds it by
# the UUID that this script also writes into /etc/fstab, which is where
# boot-deploy picks it up from for the kernel cmdline.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEVICE=sony-pdx246
WORK="$ROOT/.pmb/work"
CHROOT="$WORK/chroot_rootfs_$DEVICE"
OUT="$WORK/chroot_native/home/pmos/rootfs"
IMG="$OUT/$DEVICE.img"

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ -d "$CHROOT" ] || die "no rootfs chroot - run 'pmb install' first (it may fail at
       'modprobe loop'; that is expected and happens after the part we need)"
[ -f "$CHROOT/boot/boot.img" ] || die "no $CHROOT/boot/boot.img - 'pmb install' did not
       get far enough"
command -v mkfs.ext4 >/dev/null || die "mkfs.ext4 not found - 'sudo apt install e2fsprogs'
       inside the pmport container"
[ "$(id -u)" = 0 ] && die "do not run this as root - it calls pmbootstrap, which refuses
       to run as root. It uses sudo for the individual steps that need it."
sudo -n true 2>/dev/null || sudo true || die "need sudo in the container"

# The chroot is owned by the subuid that maps to root in here, so every step
# that touches it needs sudo. pmbootstrap, by contrast, must NOT be root.
as_root() { sudo "$@"; }

# A mount still live under the chroot would be copied into the image.
if mount | grep -q " ${CHROOT}/"; then
	mount | grep " ${CHROOT}/" >&2
	die "the chroot still has mounts; run './scripts/pmb shutdown' first"
fi

# ---------------------------------------------------------------------------
say "assigning a filesystem UUID"
UUID=$(cat /proc/sys/kernel/random/uuid)
echo "    $UUID"

# Matches pmb.install._install.create_fstab() with layout=None, which is the
# single-partition shape. boot-deploy reads this file in get_cmdline() and
# appends pmos_root_uuid= from it, so it has to exist before mkinitfs runs.
say "writing /etc/fstab"
printf '%s\n%s\n' \
	'# <file system> <mount point> <type> <options> <dump> <pass>' \
	"UUID=$UUID / ext4 defaults 0 0" \
	| as_root tee "$CHROOT/etc/fstab" | sed 's/^/    /'

# Must run before the qemu stub is removed below: mkinitfs executes aarch64
# binaries. This regenerates boot.img and vendor_boot.img with the UUID on the
# cmdline, which is the whole reason for doing fstab first.
say "re-running mkinitfs so the UUID reaches the kernel cmdline"
( cd "$ROOT" && ./scripts/pmb -q chroot -r -- mkinitfs ) || die "mkinitfs failed"
as_root test -f "$CHROOT/boot/vendor_boot.img" || die "vendor_boot.img vanished"

# 'pmb chroot' leaves its bind mounts in place until shutdown, and the qemu
# stub is one of them - it cannot be removed while still mounted, and anything
# still mounted would be copied into the image.
say "unmounting the chroot"
( cd "$ROOT" && ./scripts/pmb -q shutdown ) || die "pmb shutdown failed"
if mount | grep -q " ${CHROOT}/"; then
	mount | grep " ${CHROOT}/" >&2
	die "the chroot still has mounts after shutdown"
fi

# ---------------------------------------------------------------------------
# What pmbootstrap removes before copying the chroot into the image.
say "removing pmbootstrap's own artifacts"
as_root rm -f  "$CHROOT/in-pmbootstrap"
as_root rm -f  "$CHROOT/usr/bin/qemu-aarch64-static"
as_root rm -f  "$CHROOT/tmp/apk_progress_fifo"
as_root rm -rf "${CHROOT:?}/mnt/pmbootstrap"
# These are empty regular files standing in for device nodes, created as
# bind-mount targets because a rootless container cannot mknod. Shipping a
# regular file called /dev/null is worse than shipping nothing: devtmpfs is
# mounted over /dev long before anything looks in it.
as_root find "$CHROOT/dev" -mindepth 1 -delete

# apk ships no keys in the chroot, so without this the installed system cannot
# verify a single package.
say "installing apk keys and indexes"
as_root install -d -m755 "$CHROOT/etc/apk/keys" "$CHROOT/var/cache/apk"
as_root cp "$WORK/config_apk_keys"/*.pub "$CHROOT/etc/apk/keys/"
for f in "$WORK/cache_apk_aarch64"/APKINDEX.*.tar.gz; do
	[ -e "$f" ] && as_root cp "$f" "$CHROOT/var/cache/apk/"
done
echo "    $(as_root ls "$CHROOT/etc/apk/keys" | wc -l) keys, $(as_root ls "$CHROOT/var/cache/apk" | wc -l) indexes"
# pmbootstrap drops its local repository from the installed system.
as_root sed -i '/\/mnt\/pmbootstrap\/packages/d' "$CHROOT/etc/apk/repositories"

# ---------------------------------------------------------------------------
# 'pmbootstrap install' asks for this interactively. We are not running
# install, so the hash sitting in the chroot is whatever some earlier install
# run put there - not reproducible, and not written down anywhere. Set it from
# a known default instead, so the image is reproducible and the password is
# documented.
#
# This is a bring-up image whose whole point is an open debug shell on the
# serial console. The password is a convenience for getting past a login
# prompt, not a security boundary; do not reuse it anywhere that matters.
say "setting the login password for 'user'"
PASSWORD="${PMOS_PASSWORD:-147147}"
HASH=$(openssl passwd -6 "$PASSWORD") || die "openssl passwd failed"
as_root sed -i "s|^user:[^:]*:|user:$HASH:|" "$CHROOT/etc/shadow"
as_root grep -qF "user:$HASH:" "$CHROOT/etc/shadow" \
	|| die "failed to write the password hash into /etc/shadow"
echo "    user / $PASSWORD"

# ---------------------------------------------------------------------------
# pmbootstrap uses folder size * 1.20 + 50 MiB. The initramfs grows the
# filesystem to fill the partition on first boot, so this only has to be big
# enough to hold the tree with room to work.
SIZE_MB=$(( $(as_root du -sm "$CHROOT" | cut -f1) * 125 / 100 + 128 ))
say "creating a ${SIZE_MB} MiB ext4 image"
as_root mkdir -p "$OUT"
as_root rm -f "$IMG"
# -d populates from the tree, -b 4096 matches deviceinfo_rootfs_image_sector_size,
# and the label is the fallback the initramfs uses if the UUID is ever missing.
as_root mkfs.ext4 -q -F \
	-b 4096 \
	-L pmOS_root \
	-U "$UUID" \
	-d "$CHROOT" \
	"$IMG" "${SIZE_MB}m"

# ---------------------------------------------------------------------------
say "verifying"
as_root dumpe2fs -h "$IMG" 2>/dev/null | grep -E "^(Filesystem volume name|Filesystem UUID|Block size|Block count|Free blocks|Filesystem state):" | sed 's/^/    /'
echo "    ---"
as_root e2fsck -fn "$IMG" >/dev/null 2>&1 && echo "    e2fsck: clean" || echo "    e2fsck: REPORTED PROBLEMS"
for f in sbin/init etc/fstab etc/apk/keys usr/lib/modules; do
	if as_root debugfs -R "stat /$f" "$IMG" >/dev/null 2>&1; then
		echo "    present: /$f"
	else
		echo "    MISSING: /$f"
	fi
done

echo
say "done: $IMG"
echo "    $(as_root stat -c %s "$IMG" | sed ':a;s/\B[0-9]\{3\}\>/,&/;ta') bytes"
echo
echo "This image has no partition table - it is a bare ext4 filesystem, which"
echo "is what gets flashed to userdata. scripts/flash.sh checks for that."
