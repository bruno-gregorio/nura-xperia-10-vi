# Building

## One-time setup

Everything runs inside the `pmport` distrobox container (Debian trixie);
nothing is installed on the host. Run these once, in order.

1. **Provision the container.** Installs the apt packages, clones pmbootstrap
   (pinned to 3.11.1) and pmaports into `.pmb/`, creates the venv, writes
   `.pmb/pmbootstrap_v3.cfg` from `scripts/pmbootstrap_v3.cfg.in`, applies
   `patches/`, and syncs `aports/` into the pmaports checkout.

   ```sh
   distrobox enter pmport -- ./scripts/bootstrap.sh
   ```

2. **Initialise the work directory.** Accept the defaults; the config already
   selects `sony-pdx246`, the `systemd-edge` channel and the `console` UI.

   ```sh
   distrobox enter pmport -- ./scripts/pmb init
   ```

## Everyday loop

`aports/` is the source of truth; `.pmb/pmaports` is a disposable upstream
checkout that pmbootstrap actually reads.

1. **Sync and build after editing anything under `aports/`.**

   ```sh
   distrobox enter pmport -- ./scripts/sync-aports.sh
   distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
   ```

2. **Pull rewritten APKBUILDs back before committing.** `pmb checksum` edits
   the copy inside the pmaports checkout, not ours.

   ```sh
   distrobox enter pmport -- ./scripts/pmb checksum linux-sony-pdx246
   distrobox enter pmport -- ./scripts/sync-aports.sh --back
   ```

3. **Force a rebuild after changing an APKBUILD without bumping `pkgrel`.**
   pmbootstrap decides a package is up to date from its `pkgver-pkgrel`, so an
   edited `depends=` or `package()` is silently ignored and the stale apk in
   `.pmb/work/packages/` is installed instead. `--force` is cheaper than
   bumping `pkgrel` on every iteration of a port that has no users yet.

   ```sh
   distrobox enter pmport -- ./scripts/pmb build --force device-sony-pdx246
   ```

   To check what a built apk actually declares:

   ```sh
   tar -xzOf .pmb/work/packages/edge/aarch64/device-sony-pdx246-0.1-r0.apk \
       .PKGINFO | grep ^depend
   ```

## Kernel

The aport fetches two tarballs — the kernel and Sony's device tree release —
drops the device trees at `arch/arm64/boot/dts/vendor` (replacing a symlink
that only resolves inside an Android repo tree), merges the four config
fragments, and builds `Image`, `dtbs` and `modules` with `LLVM=1`.

1. **Build it.**

   ```sh
   distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
   ```

2. **Check the package against what the device package promises.** Confirms the
   DTB named by `deviceinfo_dtb` is present and that every module in
   `modules-initfs` was built.

   ```sh
   ./scripts/verify-build.sh
   ```

3. **Check the config against pmOS's requirements.**

   ```sh
   distrobox enter pmport -- ./scripts/pmb kconfig check linux-sony-pdx246
   ```

4. **Edit the config by hand only to experiment.**

   ```sh
   distrobox enter pmport -- ./scripts/pmb kconfig edit linux-sony-pdx246
   ```

Things worth knowing before changing any of it:

- Clang is used rather than GCC because that is what Android builds this tree
  with. Alpine's clang is far newer than Google's pinned one, so `prepare()`
  removes Qualcomm's `cc-wrapper`, strips `-Werror` from every Makefile, and
  passes a list of `-Wno-error=` flags for diagnostics that did not exist in
  Clang 12.
- `prepare()` also makes Kbuild's per-directory include path unconditional.
  Qualcomm's tracepoint headers need it and Kbuild only adds it for `O=`
  builds, which is how Google builds this kernel and we do not.
- Only the base `parrot.dtb` is built. Qualcomm's other device trees are not
  ours, and two of their subdirectories cannot build without headers from the
  out-of-tree `sm6450-modules` repository.
- `kconfig edit` edits the *generated* config. Anything that should persist
  belongs in `aports/device/testing/linux-sony-pdx246/pmos.config`.

## Images

Build the flashable images. `--no-fde` skips full-disk encryption, one less
thing to go wrong on a device that has never booted. Do **not** pass `--split`:
that produces separate boot and root partition images, which only the
`fastboot-bootpart` flasher uses. This device is plain `fastboot`, which flashes
the combined image.

```sh
distrobox enter pmport -- ./scripts/pmb install --no-fde
```

Two different kinds of file come out of this, in two different places, and
conflating them is the easiest mistake to make here.

- **The fastboot images**, written by boot-deploy into the rootfs chroot's
  `/boot`. These are what the bootloader consumes.

  ```sh
  .pmb/work/chroot_rootfs_sony-pdx246/boot/boot.img          # kernel
  .pmb/work/chroot_rootfs_sony-pdx246/boot/vendor_boot.img   # dtb + initramfs + cmdline
  ```

- **The partition images**, under `.pmb/work/chroot_native/home/pmos/rootfs/`.
  `sony-pdx246.img` is the combined one, with `/boot` and `/` as subpartitions,
  and it is what gets flashed to `userdata`. A `sony-pdx246-boot.img` here is a
  512M *filesystem* for the boot partition, not a kernel.

Both boot images matter: header v4 splits the kernel from the DTB and
initramfs. Check them before going near the device — this parses both headers,
compares the embedded DTB against the kernel package's, checks the four load
addresses and every option in `kernel-cmdline.conf`, and looks inside the
initramfs for the modules and the binaries the debug shell needs.

```sh
python3 scripts/verify-bootimg.py
```

### The rootfs image, without loop devices

`pmb install` cannot finish in this container. It gets as far as building the
rootfs and both fastboot images, then dies at step 3:

```
*** (3/4) PREPARE INSTALL BLOCKDEVICE ***
losetup: cannot find an unused loop device: Permission denied
```

pmbootstrap builds the image by allocating a file, attaching it to a loop
device, partitioning, formatting and copying into the mount. Two separate
things stop that here, and fixing the first does not fix the second:

- `modprobe loop` needs privileges a rootless container has not got. Running
  it on the host clears this one.
- `/dev/loop-control` is `root:disk` mode 0660, and the container has no
  `/dev/loopN` nodes at all. Attaching a loop device would mean adding the
  owner to `disk`, which grants raw read/write to every block device on the
  machine — not a reasonable price for building a phone image.

`scripts/make-rootfs-img.sh` avoids loop devices entirely:

```sh
distrobox enter pmport -- ./scripts/make-rootfs-img.sh
```

`mkfs.ext4 -d <dir>` populates a filesystem from a directory tree without
mounting anything, so the rootfs chroot can be turned into an image directly.
The script:

1. Generates a UUID and writes `/etc/fstab` with it, then re-runs `mkinitfs`
   **before** making the image, so boot-deploy bakes `pmos_root_uuid=` into
   the vendor_boot cmdline. Get this order wrong and the initramfs will not
   know which partition to mount.
2. Runs `pmb shutdown`, because `pmb chroot` leaves bind mounts behind — one of
   them over `usr/bin/qemu-aarch64-static`, which otherwise cannot be removed
   and would end up inside the image.
3. Removes pmbootstrap's own artifacts (`/in-pmbootstrap`, the qemu stub, the
   `/mnt/pmbootstrap` bind mounts, `/dev`), installs the apk keys and drops the
   local build repo from `/etc/apk/repositories`.
4. Sets the password for `user`, which `pmb install` would otherwise have asked
   for interactively. Default `147147`; override with `PMOS_PASSWORD=`.
5. Formats at 125% of the tree size plus 128 MiB, then checks the result with
   `dumpe2fs`, `e2fsck -fn` and `debugfs`.

The result is a **bare ext4 filesystem with no partition table**, which is what
gets flashed to `userdata`. `pmb install`'s own image would have had a GPT;
both shapes are accepted by `flash.sh` and `verify-bootimg.py`, and both refuse
an image that holds neither, since a failed install leaves behind a correctly
sized file full of zeros that would wipe `userdata` if flashed.

Note that `flash.sh ramboot` needs none of this: it boots from RAM, and
`pmos.debug-shell` stops inside the initramfs before any root filesystem is
looked for, so the first round of debugging works without a rootfs image at all.

## Housekeeping

All state lives under `.pmb/`, so cleaning up is local to this folder.

```sh
./scripts/pmb shutdown              # unmount the chroots
./scripts/pmb log                   # tail the build log
./scripts/pmb zap                   # drop chroots and built packages
du -sh .pmb                         # all state lives here
```

`pmb shutdown` matters more than usual here: the device-node bind mounts from
`patches/` live inside the chroots, and leaving them mounted will confuse a
later `rm -rf`.

## Flashing

What to do with the images once they exist, and the two irreversible steps to
understand before connecting the phone.

See [04-flashing.md](04-flashing.md).
