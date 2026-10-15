# postmarketOS for the Sony Xperia 10 VI (pdx246)

An in-progress postmarketOS port on our own mainline 6.18 kernel. It boots on
the device into Plasma Mobile, and much of the hardware is still untested or
guessed at — see [docs/05-status.md](docs/05-status.md) for exactly what is
verified and what is not.

## The device

What this port targets, in the terms the rest of the docs use.

- **Device** — Sony Xperia 10 VI, `XQ-ES54` / `XQ-ES72`
- **Codename** — `pdx246`, Sony platform `columbia`
- **SoC** — Qualcomm SM6450, Snapdragon 6 Gen 1, Qualcomm codename `parrot`
- **GPU** — Adreno 710
- **Display** — 6.1" OLED, 1080x2520
- **Kernel** — mainline 6.18 with our SM6450 series; Sony/Qualcomm downstream
  5.10.269 (Android GKI, `android12-5.10`) as a reference
- **pmOS device** — `sony-pdx246`

## Two kernels

The kernel choice shapes everything else about this port, so it comes first.

- **Mainline is the point** — upstream Linux has no SM6450 support: no
  `sm6450.dtsi` and no clock, pinctrl or interconnect driver. This port writes
  it, as a series meant for the mailing lists, on the 6.18 stable line, and
  uses no Android vendor modules.
- **Sony's 5.10 kernel stays as a reference** — it started the port, because
  it booted first, and it is kept as the fallback that shows how the hardware
  behaves under the vendor's own drivers. Nothing new is built on it.
- **The mainline kernel is three layers** — backports from newer kernels, the
  series for upstream, and device bring-up that never goes upstream as is.
  Each is a branch in the kernel tree and a directory under `kernel/`.

## Layout

Everything the build touches lives under this directory. Nothing is written to
`$HOME` or to the host.

```
aports/device/testing/device-sony-pdx246/   device package (deviceinfo, initfs modules)
aports/device/testing/linux-sony-pdx246/    downstream kernel package (Sony 5.10)
aports/device/testing/linux-postmarketos-qcom-sm6450/
                                            mainline kernel package (6.18 + our series)
kernel/backports/                           upstream commits 6.18 predates, one patch per commit
kernel/patches/                             the SM6450 series for upstream, one patch per commit
kernel/bringup/                             device bring-up that is not for upstream
kernel/wip/                                 WIP topic branches not yet in the series
patches/                                    fixes pmbootstrap needs to run rootless
scripts/                                    bootstrap, pmbootstrap wrapper, aports sync, device probe, flashing
docs/                                       device facts, design, build, flashing, status
out/                                        (gitignored) build and install logs, the kernel tree
.pmb/                                       (gitignored) venv, pmbootstrap, pmaports, chroots
```

## Quick start

Every command runs inside the `pmport` distrobox container.

1. **Provision the container and initialise the work directory.**

   ```sh
   distrobox enter pmport -- ./scripts/bootstrap.sh
   distrobox enter pmport -- ./scripts/pmb init
   ```

2. **Build the kernel.** There are two, chosen in `pmb init`: our own
   mainline 6.18, which is the point of the project, or Sony's 5.10, the
   reference. Build whichever one `pmb init` selected.

   ```sh
   distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
   distrobox enter pmport -- ./scripts/pmb build linux-postmarketos-qcom-sm6450
   ```

   The mainline package builds a stock kernel.org tarball plus one squashed
   patch per layer. Those patches are generated, not edited: the work lives on
   the `backports`, `sm6450` and `pdx246` branches in `out/linux`, each built
   on the one before, and `scripts/sync-kernel-patches.sh` writes every layer
   out both as that single diff and as one patch per commit under `kernel/`.
   Run it after every kernel commit, then
   `./scripts/pmb checksum linux-postmarketos-qcom-sm6450`.
   Work not yet folded into the series sits on `sm6450-*` topic branches;
   `scripts/export-wip.sh` copies their own commits to `kernel/wip/`.

3. **Build the boot images.** Do not pass `--split`; this device flashes the
   combined image.

   ```sh
   distrobox enter pmport -- ./scripts/pmb install --no-fde
   ```

4. **Build the rootfs image.** `pmb install` cannot finish inside a rootless
   container, and this replaces its last stage.

   ```sh
   distrobox enter pmport -- ./scripts/make-rootfs-img.sh
   ```

## Documentation

Each file states what it is sure of and what it is guessing.

- **[docs/01-device.md](docs/01-device.md)** — device facts: identity, the
  Parrot QRD device tree finding, boot image geometry, verified boot, and where
  the kernel config comes from.
- **[docs/02-design.md](docs/02-design.md)** — why the port is shaped this way,
  and what the downstream kernel costs.
- **[docs/03-build.md](docs/03-build.md)** — one-time setup, the everyday build
  loop, and which files come out of it.
- **[docs/04-flashing.md](docs/04-flashing.md)** — installing and booting the
  port, the two irreversible things, getting in, and recovery.
- **[docs/05-status.md](docs/05-status.md)** — the confidence ledger, and the
  next steps in the order they should happen.
- **[docs/06-mainline.md](docs/06-mainline.md)** — what mainlining SM6450 would
  actually take, costed against the sources already on disk.
- **[docs/07-devloop.md](docs/07-devloop.md)** — how a kernel round runs with
  no hands on the device, its modes, and the queue.
- **[docs/guidelines.md](docs/guidelines.md)** — the entity framework every
  document here is written to.

## Credit

Nearly every hard fact about this device — the boot image geometry, the module
load order, and above all that pdx246 runs Qualcomm's Parrot QRD reference
device tree rather than a Sony board tree — comes from Johannes Meyer zum Alten
Borgloh's unofficial LineageOS 23.2 port, which is thoroughly documented and
was verified on real hardware.

<https://github.com/johanneszab/lineageos-pdx246-releases>
