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

Build the flashable images. `--split` keeps boot and root separate, which is
what a fastboot device wants; `--no-fde` skips full-disk encryption, one less
thing to go wrong on a device that has never booted.

```sh
distrobox enter pmport -- ./scripts/pmb install --no-fde --split
```

Output lands in `.pmb/work/chroot_native/home/pmos/rootfs/`:

- `sony-pdx246-boot.img` — kernel
- `sony-pdx246-vendor_boot.img` — DTB + initramfs + cmdline
- `sony-pdx246-root.img` — root filesystem

Both boot images matter: header v4 splits the kernel from the DTB and
initramfs.

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
