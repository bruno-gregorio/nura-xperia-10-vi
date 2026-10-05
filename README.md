# postmarketOS for the Sony Xperia 10 VI (pdx246)

An in-progress postmarketOS port, built from Sony's released 5.10 kernel.
Nothing here has been run on the device yet — see
[docs/05-status.md](docs/05-status.md) for exactly what is verified and what is
still a guess.

## The device

What this port targets, in the terms the rest of the docs use.

- **Device** — Sony Xperia 10 VI, `XQ-ES54` / `XQ-ES72`
- **Codename** — `pdx246`, Sony platform `columbia`
- **SoC** — Qualcomm SM6450, Snapdragon 6 Gen 1, Qualcomm codename `parrot`
- **GPU** — Adreno 710
- **Display** — 6.1" OLED, 1080x2520
- **Kernel** — Sony/Qualcomm downstream 5.10.269, Android GKI (`android12-5.10`)
- **pmOS device** — `sony-pdx246`

## Why downstream and not mainline

The kernel choice shapes everything else about this port, so it comes first.

- **SM6450 has no mainline support** — there is no `sm6450.dtsi` in
  `arch/arm64/boot/dts/qcom` and no clock, pinctrl or interconnect driver.
  Sony's own mainline contributions stop at `sm8550` (Xperia 1 V) and `sm6375`
  (Xperia 10 IV).
- **Sony's released 5.10 kernel is the fastest way to a booting device** — so
  that is what this port builds.
- **The trade is deliberate** — it gets to a shell quickly, and the kernel work
  is a maintenance dead end.
- **Mainline is not "write it all from scratch"** — every per-SoC driver exists
  as GPL source in the tarballs this port already downloads, and the sibling
  SoC SM4450 is upstream and derived from the same vendor code. The blocker is
  debuggability, not difficulty, which is why a console on the real device
  comes first.

## Layout

Everything the build touches lives under this directory. Nothing is written to
`$HOME` or to the host.

```
aports/device/testing/device-sony-pdx246/   device package (deviceinfo, initfs modules)
aports/device/testing/linux-sony-pdx246/    kernel package
patches/                                    fixes pmbootstrap needs to run rootless
scripts/                                    bootstrap, pmbootstrap wrapper, aports sync, device probe, flashing
docs/                                       device facts, design, build, flashing, status
out/                                        (gitignored) build and install logs
.pmb/                                       (gitignored) venv, pmbootstrap, pmaports, chroots
```

## Quick start

Every command runs inside the `pmport` distrobox container.

1. **Provision the container and initialise the work directory.**

   ```sh
   distrobox enter pmport -- ./scripts/bootstrap.sh
   distrobox enter pmport -- ./scripts/pmb init
   ```

2. **Build the kernel.**

   ```sh
   distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
   ```

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
- **[docs/04-flashing.md](docs/04-flashing.md)** — the flashing procedure, the
  two irreversible steps, and how to get a console on a device with no display.
- **[docs/05-status.md](docs/05-status.md)** — the confidence ledger, and the
  next steps in the order they should happen.
- **[docs/06-mainline.md](docs/06-mainline.md)** — what mainlining SM6450 would
  actually take, costed against the sources already on disk.
- **[docs/07-devloop.md](docs/07-devloop.md)** — how to test many kernels an
  hour with no hands on the device.
- **[docs/guidelines.md](docs/guidelines.md)** — the entity framework every
  document here is written to.

## Credit

Nearly every hard fact about this device — the boot image geometry, the module
load order, and above all that pdx246 runs Qualcomm's Parrot QRD reference
device tree rather than a Sony board tree — comes from Johannes Meyer zum Alten
Borgloh's unofficial LineageOS 23.2 port, which is thoroughly documented and
was verified on real hardware.

<https://github.com/johanneszab/lineageos-pdx246-releases>
