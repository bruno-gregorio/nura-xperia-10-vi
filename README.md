# postmarketOS for the Sony Xperia 10 VI (pdx246)

An in-progress postmarketOS port. Nothing here has been run on the device yet —
see [docs/05-status.md](docs/05-status.md) for exactly what is verified and what
is still a guess.

| | |
|---|---|
| Device | Sony Xperia 10 VI, `XQ-ES54` / `XQ-ES72` |
| Codename | `pdx246` (Sony platform `columbia`) |
| SoC | Qualcomm SM6450, Snapdragon 6 Gen 1 (Qualcomm codename `parrot`) |
| GPU | Adreno 710 |
| Display | 6.1" OLED, 1080x2520 |
| Kernel | Sony/Qualcomm downstream 5.10.269, Android GKI (`android12-5.10`) |
| pmOS device | `sony-pdx246` |

## Why downstream and not mainline

SM6450 has **no mainline support at all** — there is no `sm6450.dtsi` in
`arch/arm64/boot/dts/qcom`, no clock/pinctrl/interconnect drivers, and no
patches on the lists. Sony's own mainline contributions stop at `sm8550`
(Xperia 1 V) and `sm6375` (Xperia 10 IV). Writing that enablement is a
multi-year project; this port instead builds Sony's released 5.10 kernel, which
is the only way to a booting device in a useful timeframe.

That is a deliberate trade: this gets to a shell quickly and is a maintenance
dead end. [docs/02-design.md](docs/02-design.md) spells out the consequences.

## Layout

```
aports/device/testing/device-sony-pdx246/   device package (deviceinfo, initfs modules)
aports/device/testing/linux-sony-pdx246/    kernel package
patches/                                    fixes pmbootstrap needs to run rootless
scripts/                                    bootstrap, pmbootstrap wrapper, aports sync
docs/                                       device facts, design, build, flashing, status
.pmb/                                       (gitignored) venv, pmbootstrap, pmaports, chroots
```

Everything the build touches lives under this directory. Nothing is written to
`$HOME` or to the host.

## Quick start

```sh
distrobox enter pmport -- ./scripts/bootstrap.sh
distrobox enter pmport -- ./scripts/pmb build linux-sony-pdx246
distrobox enter pmport -- ./scripts/pmb install --no-fde --split
```

Details in [docs/03-build.md](docs/03-build.md), flashing and first-boot
debugging in [docs/04-flashing.md](docs/04-flashing.md).

## Credit

Nearly every hard fact about this device — the boot image geometry, the module
load order, and above all that pdx246 runs Qualcomm's Parrot QRD reference
device tree rather than a Sony board tree — comes from Johannes Meyer zum Alten
Borgloh's unofficial LineageOS 23.2 port, which is thoroughly documented and
was verified on real hardware:
<https://github.com/johanneszab/lineageos-pdx246-releases>.
