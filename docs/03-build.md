# Building

## One-time setup

The container is `pmport` (Debian trixie). Everything below runs inside it;
nothing is installed on the host.

```sh
distrobox enter pmport -- ./scripts/bootstrap.sh
```

That installs the apt packages, clones pmbootstrap (pinned to 3.11.1) and
pmaports into `.pmb/`, creates the venv, writes `.pmb/pmbootstrap_v3.cfg` from
`scripts/pmbootstrap_v3.cfg.in`, applies `patches/`, and syncs `aports/` into
the pmaports checkout.

Then initialise the work directory once:

```sh
distrobox enter pmport -- ./scripts/pmb init
```

Accept the defaults; the config already selects `sony-pdx246`, channel `edge`
and the `console` UI.

## Everyday loop

`aports/` is the source of truth. After editing anything there:

```sh
distrobox enter pmport -- ./scripts/sync-aports.sh
distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
```

`pmb checksum` rewrites APKBUILDs inside the pmaports checkout, so pull the
result back before committing:

```sh
distrobox enter pmport -- ./scripts/pmb checksum linux-sony-pdx246
./scripts/sync-aports.sh --back
```

## Kernel

```sh
distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
```

The aport fetches two tarballs — the kernel and Sony's device tree release —
drops the device trees at `arch/arm64/boot/dts/vendor` (replacing a symlink
that only resolves inside an Android repo tree), merges the four config
fragments, and builds `Image`, `dtbs` and `modules` with `LLVM=1`.

Clang is used rather than GCC because that is what Android builds this tree
with; `prepare()` strips `-Werror` from every Makefile, since Alpine's clang is
newer than Google's pinned one and warns about things theirs did not.

Check the config against pmOS's requirements:

```sh
distrobox enter pmport -- ./scripts/pmb kconfig check linux-sony-pdx246
```

Edit the config by hand if needed:

```sh
distrobox enter pmport -- ./scripts/pmb kconfig edit linux-sony-pdx246
```

Note that this edits the *generated* config. Anything that should persist
belongs in `aports/device/testing/linux-sony-pdx246/pmos.config`.

## Images

```sh
distrobox enter pmport -- ./scripts/pmb install --no-fde --split
```

`--split` keeps boot and root as separate images, which is what a fastboot
device wants. `--no-fde` skips full-disk encryption; it is one less thing to go
wrong on a device that has never booted.

Output lands in `.pmb/work/chroot_native/home/pmos/rootfs/`:

- `sony-pdx246-boot.img` — kernel
- `sony-pdx246-vendor_boot.img` — DTB + initramfs + cmdline
- `sony-pdx246-root.img` — root filesystem

Both boot images matter: header v4 splits the kernel from the DTB and
initramfs. See [04-flashing.md](04-flashing.md).

## Housekeeping

```sh
./scripts/pmb shutdown              # unmount the chroots
./scripts/pmb log                   # tail the build log
./scripts/pmb zap                   # drop chroots and built packages
du -sh .pmb                         # all state lives here
```

`pmb shutdown` matters more than usual here: the device-node bind mounts from
`patches/` live inside the chroots, and leaving them mounted will confuse a
later `rm -rf`.
