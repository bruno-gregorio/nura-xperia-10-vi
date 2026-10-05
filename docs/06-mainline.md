# Mainlining SM6450

What it would actually take to run a current mainline kernel on pdx246,
answered against the sources this repo already has on disk rather than from
general reasoning about Qualcomm ports.

This document does not change the plan. [02-design.md](02-design.md) picks the
downstream 5.10 kernel and that is still the right first move; the reason is
now *ordering*, not impossibility, and this file records why.

## The short version

Nothing needed for SM6450 SoC enablement is hidden inside a blob. All of it is
GPL C and device tree source, in the two tarballs the kernel aport already
downloads. The work is transcription into mainline idiom and validation on
hardware — not discovery, and not reverse engineering.

The sibling SoC, SM4450, is already upstream, and we hold Qualcomm's downstream
driver for it *next to* parrot's in the same tree. That gives a worked example
of the exact downstream-to-mainline transformation a maintainer accepted.

## What we already have

All paths below are inside the two tarballs in `.pmb/work/cache_distfiles/`,
which the kernel APKBUILD already fetches.

| Per-SoC component | Source we have | Lines |
|---|---|---|
| Global clock controller | `drivers/clk/qcom/gcc-parrot.c` | 3041 |
| Pinctrl / TLMM | `drivers/pinctrl/qcom/pinctrl-parrot.{c,h}` | 91 + 1798 |
| Interconnect / NoC | `drivers/interconnect/qcom/parrot.c` | 2502 |
| Display clocks | `drivers/clk/qcom/dispcc-parrot.c` | 1836 |
| GPU clocks | `drivers/clk/qcom/gpucc-parrot.c` | 727 |
| Camera / video clocks | `camcc-parrot.c`, `videocc-parrot.c` | — |
| SoC device tree | 29 `parrot*.dtsi` files (see below) | 20413 |

The device tree release carries the SoC split across dedicated files, which
maps almost one-to-one onto the subsystems a mainline port brings up in order:

```
parrot.dtsi                 parrot-pinctrl.dtsi       parrot-regulators.dtsi
parrot-qupv3.dtsi (GENI)    parrot-usb.dtsi           parrot-thermal.dtsi (tsens)
msm-arm-smmu-parrot.dtsi    parrot-gpu.dtsi           parrot-sde*.dtsi (display)
parrot-reserved-memory.dtsi parrot-camera.dtsi        parrot-vidc.dtsi
parrot-coresight.dtsi       parrot-debug.dtsi         parrot-dma-heaps.dtsi
```

554 `reg` properties across the SoC-level trees — every register base,
interrupt, clock and regulator reference, with symbolic names and comments.

## The SM4450 Rosetta Stone

Qualcomm's codename for SM4450 is `ravelin`, and our kernel config enables
`CONFIG_ARCH_PARROT` and `CONFIG_ARCH_RAVELIN` together. The two SoCs are
siblings and the vendor tree ships both.

**This is proven, not inferred.** Extracting every `(clock name, register
offset)` pair from downstream `gcc-ravelin.c` and from upstream
`drivers/clk/qcom/gcc-sm4450.c` and joining them:

```
upstream sm4450 clocks: 119    downstream ravelin clocks: 120
common clocks: 119             identical register offset: 119
```

119 of 119. Upstream's SM4450 clock driver is a direct derivation from the same
vendor source we hold. Pin counts line up too: 150 `PINGROUP`s in
`pinctrl-parrot.h`, 145 in `pinctrl-ravelin.h`, 148 in upstream
`pinctrl-sm4450.c`.

So for the two largest and most mechanical pieces of work we have **both sides
of the diff** for the sibling chip: learn the transformation from the
ravelin/sm4450 pair, apply it to the parrot files.

### How far the template actually goes

Not all the way, and it matters:

| Upstream for SM4450 | Status |
|---|---|
| `sm4450.dtsi`, `sm4450-qrd.dts` | Present |
| `gcc-`, `gpucc-`, `dispcc-`, `camcc-sm4450.c` | Present |
| `pinctrl-sm4450.c` | Present |
| Interconnect | **Absent** — `drivers/interconnect/qcom` has no sm4450 |
| thermal / remoteproc / soc-qcom | **Absent** — no sm4450 entries |

SM4450 upstream is a *base* bring-up: clocks, pins, a SoC skeleton. Everything
past that is unmapped for the sibling too, so parrot's 2502-line interconnect
driver and the whole peripheral long tail have no worked example to copy.

## Why disassembling the blobs is the wrong tool

The binaries exist, so the question is fair. Three reasons it leads nowhere.

**1. The blobs that matter cannot be replaced at any price.** TZ/QHEE, XBL/ABL,
modem (MPSS), ADSP, CDSP, SLPI, Venus video firmware, WLAN firmware and the GPU
zap shader all execute on cores other than the CPU, verified against a hardware
root of trust in QFPROM fuses. Unlocking the bootloader unlocks
`boot`/`vendor_boot`/`dtbo`/`super`; it does not let anything re-sign these.
This is a key-possession problem, not a comprehension problem. **Mainline's
answer is to keep loading them unchanged**, via `remoteproc` and the MDT
loader, extracted from the stock partitions. Every mainlined Qualcomm phone
works this way. It is the accepted design, not a compromise.

**2. For everything else we already have better than a binary.** A disassembly
of `gcc-parrot` would yield stripped offsets with no names, no bindings and no
structure — strictly less information than the 3041-line commented C file
above, at vastly more effort.

**3. It would be unmergeable.** Decompiled-then-rewritten code is a derivative
work. Upstream wants clean-room reimplementation, and a driver with a plausible
disassembly lineage gets rejected on provenance regardless of quality. Sony's
copyleft release is what makes this port legitimate; routing around it with a
disassembler would throw that away.

The genuinely proprietary *userspace* pieces — Adreno GL/Vulkan, CamX camera,
audio and RIL HALs — are replaced rather than translated: Mesa
freedreno/turnip, libcamera + CAMSS, ALSA + `q6apm`, ModemManager over QMI.
Those stacks exist; the work is SoC-specific plumbing into them.

## Board-level facts, with upstream status

Read out of the device tree release this port already builds.

| Fact | Confidence | Upstream status |
|---|---|---|
| PMIC pair is `pm6450` (main) + `pm7250b` | Verified — `parrot-qrd-overlay.dts` includes `parrot-qrd-pm7250b.dtsi`; `pm6450` referenced in the QRD tree | `pm7250b.dtsi` **is** upstream (sm6350/sm6375 Sony devices use it). `pm6450.dtsi` is **not** — new, but PMIC dtsi files are small and declarative |
| Wi-Fi/BT is **WCN3990**, not WCN6750 | Verified — our overlay chain includes `parrot-wcn3990.dtsi`. `wcn6750` exists only in board files we do not use (`parrot-qrd-wcn6750*`) | Very good news: WCN3990 is **ath10k** over SNOC, mature upstream since sdm845. Bluetooth is `hci_qca`, equally mature |
| GPU is Adreno 710 (a7xx Gen1) | Verified — Sony specs, `parrot-gpu.dtsi` | Mesa `freedreno_devices.py` has `FD710` at chip_id `0x07010000`, "A7XX Gen1 derived from A730", with both KGSL and mainline-fallback ids |
| Debug UART at `0x98c000`, `qcom,msm-geni-console` | Verified — see [05-status.md](05-status.md) | GENI serial (`qcom-geni-serial`) is upstream and generic |
| Device runs Qualcomm's Parrot **QRD reference** tree | Verified — [01-device.md](01-device.md) | Unusually helpful: the downstream board description is already close in shape to the `sm6450-qrd.dts` a mainline series would carry |
| No `sm6450.dtsi` or parrot drivers in mainline | Verified 2026-10-05 against `torvalds/linux` master via the GitHub API | — |
| Nothing on the mailing lists | **Unverified** | `lore.kernel.org` was unreachable (Anubis challenge) when this was written. [05-status.md](05-status.md) carries this as Verified from an earlier check; treat it as stale and re-check before starting work |

Sony's own mainline history is directly relevant: the Xperia 10 II, 10 III and
10 IV are all upstream (`sm6125-sony-xperia-seine-pdx201`,
`sm6350-sony-xperia-lena-pdx213`, `sm6375-sony-xperia-murray-pdx225`), as is
the Xperia 1 V (`sm8550-sony-xperia-yodo-pdx234`). pdx246 would slot into an
established four-generation convention, and `pdx225` is the structural model
for its board dts.

## Ordered plan

Each phase gates the next; the ordering is the whole point.

**Phase 0 — a console on the real device.** Not mainline work at all. Boot the
downstream 5.10 kernel this repo builds, confirm the flashing path and the AVB
rollback hazard in [04-flashing.md](04-flashing.md), and get ramoops or UART
output. Rationale under "Risk" below.

**Phase 1 — SoC base.** `sm6450.dtsi` plus dt-bindings; `gcc-sm6450.c` and
`pinctrl-sm6450.c` transformed from the parrot sources against the
ravelin/sm4450 template; RPMh (RSC, regulators, `pm6450.dtsi`); SMEM, SMP2P,
glink, PDC; GENI UART. Target: mainline boots to a serial console. Everything
here is compile- and `dt_binding_check`-verifiable without hardware; only the
boot is not.

**Phase 2 — storage and a shell.** SMMU, UFS + phy, dwc3 + HS/SS phys. At this
point there is a networked shell and the project has a real feedback loop.

**Phase 3 — board dts.** `sm6450-sony-xperia-*-pdx246.dts`, following pdx225's
conventions.

**Phase 4 — the long tail**, roughly in order of payoff: interconnect and
cpufreq-EPSS (no sibling template), tsens, Wi-Fi/BT via ath10k + `hci_qca`
(cheap, given WCN3990), display (DSI host plus a per-device panel driver
derived from the downstream panel code — the hardest single item), GPU (a7xx
match in `drm/msm` plus the zap shader from the vendor partition), audio via
ADSP, modem (remoteproc MPSS + `rmtfs`/`pd-mapper`/`tqftpserv`), sensors,
touchscreen (`blair-touch.dtsi` in the QRD chain), charger via `pmic_glink`.

**Camera: realistically never.** Per-SoC CAMSS plus per-sensor drivers plus
tuning, and libcamera has no SM6450 support.

## Effort and risk

Phase 1 is weeks of careful transcription, and the mechanical majority of it
has a worked example. Phases 1–2 — "mainline boots to a shell" — is plausible
in a couple of months *with device access*. Display and GPU are the long poles
after that. A usable daily-driver phone is the same one-to-two-person-year
project the sm6375 and sm8550 ports were.

The dominant risk is not difficulty, it is **debuggability**. Mainline SoC
bring-up is debugged through the serial console, and on a first mainline boot
the console is part of what is being brought up. A hand-written `sm6450.dtsi`
that does not boot produces a black screen and no signal. The downstream kernel
has a console Sony ships working, plus the 256K ramoops ring already reserved
in the DTB we build. That asymmetry is the entire argument for doing Phase 0
first, and it is why this document does not change the plan.

## Rust

Not viable, for process reasons rather than technical ones. Rust-for-Linux is
real upstream — Nova, Tyr, binder, the DRM panic handler — but it exists only
where maintainers have built abstractions. `clk`, `pinctrl`, `regulator`,
`interconnect`, `remoteproc` and `drm/msm` have none. An SM6450 port written in
Rust would be rejected before the logic was read. The leverage for this device
is in C, and most of it is transcribing facts out of Sony's GPL tree.

## Sources

- Inventory and the 119/119 clock comparison: the two tarballs in
  `.pmb/work/cache_distfiles/`, as fetched by
  [the kernel APKBUILD](../aports/device/testing/linux-sony-pdx246/APKBUILD)
- Upstream tree, checked 2026-10-05:
  <https://github.com/torvalds/linux/tree/master/arch/arm64/boot/dts/qcom>
- Mesa device table:
  <https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/freedreno/common/freedreno_devices.py>
