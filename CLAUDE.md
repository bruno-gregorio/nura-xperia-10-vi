# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Commands

Everything runs inside the `pmport` distrobox, prefixed with
`distrobox enter pmport --`. The full walkthrough is in
[docs/03-build.md](docs/03-build.md), and the device loop is in
[docs/07-devloop.md](docs/07-devloop.md).

- **Setup** — `./scripts/bootstrap.sh`, then `./scripts/pmb init` (accept the
  defaults; the config already selects `sony-pdx246`, mainline, systemd and
  plasma-mobile).
- **After editing `aports/`** — `./scripts/sync-aports.sh`, then
  `./scripts/pmb build <pkg>`. If the APKBUILD changed but `pkgrel` did not,
  add `--force`, or the stale apk gets used silently.
- **A forced rebuild does not reach the images.** `mkinitfs` reads the rootfs
  chroot, not the repo. Run `pmb -q chroot -r -- apk add --allow-untrusted
  /mnt/pmbootstrap/packages/edge/aarch64/<file>.apk` and then
  `pmb -q chroot -r -- mkinitfs`. `apk fix --reinstall` does not work for this.
- **Images** — `./scripts/pmb install --no-fde`. Never pass `--split`. Then
  run `./scripts/make-rootfs-img.sh`, because `pmb install` dies at the
  loop-device step in this rootless container. Switching kernels needs
  `pmb install --zap`.
- **Checks that need no device** — `scripts/verify-build.sh
  [downstream|mainline]`, `python3 scripts/verify-bootimg.py`,
  `scripts/sync-kernel-patches.sh --check`,
  `scripts/check-tables.sh clk|pinctrl <vendor> <ours>`, `scripts/check-dt.py`,
  and `./scripts/pmb kconfig check <kernel-pkg>`.
- **A device round** — `scripts/try-kernel.sh`, with modes chosen by env vars
  (`FULLBOOT`, `STAYUP`, `LIVE`, `CMDLINE_ADD/DEL`, `DTB`, …).
  `scripts/try-kernel.sh --log` reads the boot log back. `scripts/queue.sh
  <plan>` runs rounds back to back; start it with `setsid`. Outputs land in
  `out/try-kernel/`, `out/probe-harvest.txt` and `out/live.txt`.

## The mainline kernel workflow

The kernel package `linux-postmarketos-qcom-sm6450` builds a kernel.org 6.18
tarball plus three squashed patches (`backports.patch`,
`sm6450-mainline.patch` and `pdx246-bringup.patch`). **These patches are
generated, so never edit them.** The real work is three stacked branches in
the gitignored clone `out/linux`:

- `backports` — upstream commits the base predates, keeping their authors.
- `sm6450` — the series meant for upstream, exported to `kernel/patches/`.
- `pdx246` — device bring-up that is not for upstream, exported to
  `kernel/bringup/`. This branch is the one that gets built.

After any kernel commit, run `scripts/sync-kernel-patches.sh`. It writes each
layer both as one patch per commit under `kernel/` and as the squashed diff in
the aport. Then run `./scripts/pmb checksum linux-postmarketos-qcom-sm6450`
and `scripts/sync-aports.sh --back`. WIP topic branches (`sm6450-*`) are
exported to `kernel/wip/` with `scripts/export-wip.sh`.

`linux-sony-pdx246` (Sony's 5.10) is a reference only, and nothing new is
built on it. Per-kernel files in `device-sony-pdx246` come in pairs:
`kernel-cmdline.{mainline,downstream}.conf` and
`modules-initfs.{mainline,downstream}`. Persistent config for the downstream
kernel belongs in its `pmos.config`, not in `kconfig edit`.

## Device safety

[docs/04-flashing.md](docs/04-flashing.md) has the details. Never write the
stock slot. Only flash the active slot's own `vbmeta`, because anti-rollback
is enforced in hardware. Never write the GPT. Every device step needs a
timeout. Findings from a round go into [docs/05-status.md](docs/05-status.md),
labelled as verified, reasoned or guessed.

## Conventions

- **Docs follow [docs/guidelines.md](docs/guidelines.md).** Every section is
  one of its entity types (titled lists, sectional descriptions, snippets
  attached to what they illustrate). Prefer linking to repeating. Do not edit
  `guidelines.md` without permission.
- **Commit subjects are `<area>: <what>`**, where the area is a package, a
  directory or a doc. A package bump says so, for example
  `device-sony-pdx246: pkgrel 22, double tap to wake`.
- **Aports layout** — `aports/device/testing/` holds the device, kernel and
  firmware packages. `aports/main/` holds new packages of ours.
  `aports/temp/` holds forks of upstream packages carried until upstream
  catches up.
