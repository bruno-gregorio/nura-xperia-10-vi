# Mainlining SM6450

What it would actually take to run a current mainline kernel on pdx246,
answered against the sources this repo already has on disk rather than from
general reasoning about Qualcomm ports. It does not change the plan:
[02-design.md](02-design.md) picks the downstream 5.10 kernel and that is still
the right first move — the reason is now *ordering*, not impossibility, and
this file records why.

## The short version

- **Nothing needed for SM6450 SoC enablement is hidden inside a blob** — all of
  it is GPL C and device tree source, in the two tarballs the kernel aport
  already downloads.
- **The work is transcription and validation** — transcription into mainline
  idiom, validation on hardware. Not discovery, and not reverse engineering.
- **The sibling SoC SM4450 is already upstream** — and we hold Qualcomm's
  downstream driver for it *next to* parrot's in the same tree, which gives a
  worked example of the exact downstream-to-mainline transformation a
  maintainer accepted.

## What we already have

All paths below are inside the two tarballs in `.pmb/work/cache_distfiles/`,
which the kernel APKBUILD already fetches.

- **Global clock controller** — `drivers/clk/qcom/gcc-parrot.c`, 3041 lines
- **Pinctrl / TLMM** — `drivers/pinctrl/qcom/pinctrl-parrot.{c,h}`, 91 + 1798
  lines
- **Interconnect / NoC** — `drivers/interconnect/qcom/parrot.c`, 2502 lines
- **Display clocks** — `drivers/clk/qcom/dispcc-parrot.c`, 1836 lines
- **GPU clocks** — `drivers/clk/qcom/gpucc-parrot.c`, 727 lines
- **Camera and video clocks** — `camcc-parrot.c` and `videocc-parrot.c`
- **SoC device tree** — 29 `parrot*.dtsi` files, 20413 lines

### How the device tree release is split

The SoC is split across dedicated files, which maps almost one-to-one onto the
subsystems a mainline port brings up in order. There are 554 `reg` properties
across the SoC-level trees — every register base, interrupt, clock and
regulator reference, with symbolic names and comments.

```
parrot.dtsi                 parrot-pinctrl.dtsi       parrot-regulators.dtsi
parrot-qupv3.dtsi (GENI)    parrot-usb.dtsi           parrot-thermal.dtsi (tsens)
msm-arm-smmu-parrot.dtsi    parrot-gpu.dtsi           parrot-sde*.dtsi (display)
parrot-reserved-memory.dtsi parrot-camera.dtsi        parrot-vidc.dtsi
parrot-coresight.dtsi       parrot-debug.dtsi         parrot-dma-heaps.dtsi
```

## The SM4450 Rosetta Stone

Qualcomm's codename for SM4450 is `ravelin`, our kernel config enables
`CONFIG_ARCH_PARROT` and `CONFIG_ARCH_RAVELIN` together, and the vendor tree
ships both. The sibling relationship is proven, not inferred.

- **119 of 119 clocks agree on their register offset** — so upstream's SM4450
  clock driver is a direct derivation from the same vendor source we hold.
  Extracting every `(clock name, register offset)` pair from downstream
  `gcc-ravelin.c` and from upstream `drivers/clk/qcom/gcc-sm4450.c` and joining
  them:

  ```
  upstream sm4450 clocks: 119    downstream ravelin clocks: 120
  common clocks: 119             identical register offset: 119
  ```

- **Pin counts line up too** — 150 `PINGROUP`s in `pinctrl-parrot.h`, 145 in
  `pinctrl-ravelin.h`, 148 in upstream `pinctrl-sm4450.c`.
- **So we hold both sides of the diff for the sibling chip** — for the two
  largest and most mechanical pieces of work. Learn the transformation from the
  ravelin/sm4450 pair, then apply it to the parrot files.

### How far the template actually goes

Not all the way, and it matters.

- **Present upstream for SM4450** — `sm4450.dtsi` and `sm4450-qrd.dts`, the
  `gcc-`, `gpucc-`, `dispcc-` and `camcc-sm4450.c` clock drivers, and
  `pinctrl-sm4450.c`.
- **Absent: interconnect** — `drivers/interconnect/qcom` has no sm4450.
- **Absent: thermal, remoteproc and soc-qcom** — no sm4450 entries at all.
- **So SM4450 upstream is a *base* bring-up** — clocks, pins, a SoC skeleton.
  Everything past that is unmapped for the sibling too, so parrot's 2502-line
  interconnect driver and the whole peripheral long tail have no worked example
  to copy.

## Why disassembling the blobs is the wrong tool

The binaries exist, so the question is fair. Three reasons it leads nowhere.

1. **The blobs that matter cannot be replaced at any price.** TZ/QHEE,
   XBL/ABL, modem (MPSS), ADSP, CDSP, SLPI, Venus video firmware, WLAN firmware
   and the GPU zap shader all execute on cores other than the CPU, verified
   against a hardware root of trust in QFPROM fuses. Unlocking the bootloader
   unlocks `boot`/`vendor_boot`/`dtbo`/`super`; it does not let anything
   re-sign these. This is a key-possession problem, not a comprehension
   problem. **Mainline's answer is to keep loading them unchanged**, via
   `remoteproc` and the MDT loader, extracted from the stock partitions. Every
   mainlined Qualcomm phone works this way. It is the accepted design, not a
   compromise.
2. **For everything else we already have better than a binary.** A disassembly
   of `gcc-parrot` would yield stripped offsets with no names, no bindings and
   no structure — strictly less information than the 3041-line commented C file
   above, at vastly more effort.
3. **It would be unmergeable.** Decompiled-then-rewritten code is a derivative
   work. Upstream wants clean-room reimplementation, and a driver with a
   plausible disassembly lineage gets rejected on provenance regardless of
   quality. Sony's copyleft release is what makes this port legitimate; routing
   around it with a disassembler would throw that away.

### What gets replaced instead of translated

The genuinely proprietary *userspace* pieces are swapped out rather than
translated. Those stacks already exist; the work is SoC-specific plumbing into
them.

- **Adreno GL/Vulkan** — Mesa freedreno and turnip
- **CamX camera** — libcamera plus CAMSS
- **Audio HAL** — ALSA plus `q6apm`
- **RIL** — ModemManager over QMI

## Board-level facts, with upstream status

Read out of the device tree release this port already builds. Confidence means
the same thing as in [05-status.md](05-status.md).

- **PMIC pair is `pm6450` (main) + `pm7250b`** — Verified:
  `parrot-qrd-overlay.dts` includes `parrot-qrd-pm7250b.dtsi`, and `pm6450` is
  referenced in the QRD tree. Upstream, `pm7250b.dtsi` **is** there (the
  sm6350/sm6375 Sony devices use it) while `pm6450.dtsi` is **not** — new, but
  PMIC dtsi files are small and declarative.
- **Wi-Fi/BT is WCN3990, not WCN6750** — Verified: our overlay chain includes
  `parrot-wcn3990.dtsi`, and `wcn6750` exists only in board files we do not use
  (`parrot-qrd-wcn6750*`). Upstream, this is very good news: WCN3990 is
  **ath10k** over SNOC, mature since sdm845, and Bluetooth is `hci_qca`,
  equally mature.
- **GPU is Adreno 710 (a7xx Gen1)** — Verified: Sony specs and
  `parrot-gpu.dtsi`. Upstream, Mesa's `freedreno_devices.py` has `FD710` at
  chip_id `0x07010000`, "A7XX Gen1 derived from A730", with both KGSL and
  mainline-fallback ids.
- **Debug UART at `0x98c000`, `qcom,msm-geni-console`** — Verified, see
  [05-status.md](05-status.md). Upstream, GENI serial (`qcom-geni-serial`) is
  there and generic.
- **The device runs Qualcomm's Parrot QRD reference tree** — Verified, see
  [01-device.md](01-device.md). Unusually helpful upstream: the downstream
  board description is already close in shape to the `sm6450-qrd.dts` a
  mainline series would carry.
- **No `sm6450.dtsi` or parrot drivers in mainline** — Verified 2026-10-05
  against `torvalds/linux` master via the GitHub API.
- **Nothing on the mailing lists** — Unverified. `lore.kernel.org` was
  unreachable (Anubis challenge) when this was written, and
  [05-status.md](05-status.md) carries it as a stale guess; re-check before
  starting work.

### Sony's own mainline history

Directly relevant, because pdx246 would slot into an established
four-generation convention, and `pdx225` is the structural model for its board
dts.

- **Xperia 10 II** — `sm6125-sony-xperia-seine-pdx201`
- **Xperia 10 III** — `sm6350-sony-xperia-lena-pdx213`
- **Xperia 10 IV** — `sm6375-sony-xperia-murray-pdx225`
- **Xperia 1 V** — `sm8550-sony-xperia-yodo-pdx234`

## Ordered plan

Each phase gates the next; the ordering is the whole point.

0. **A console on the real device.** Not mainline work at all. Boot the
   downstream 5.10 kernel this repo builds, confirm the flashing path and the
   AVB rollback hazard in [04-flashing.md](04-flashing.md), and get ramoops or
   UART output. The rationale is under "Effort and risk" below.
1. **SoC base.** `sm6450.dtsi` plus dt-bindings; `gcc-sm6450.c` and
   `pinctrl-sm6450.c` transformed from the parrot sources against the
   ravelin/sm4450 template; RPMh (RSC, regulators, `pm6450.dtsi`); SMEM, SMP2P,
   glink, PDC; GENI UART. Target: mainline boots to a serial console.
   Everything here is compile- and `dt_binding_check`-verifiable without
   hardware; only the boot is not.
2. **Storage and a shell.** SMMU, UFS plus phy, dwc3 plus the HS/SS phys. At
   this point there is a networked shell and the project has a real feedback
   loop.
3. **Board dts.** `sm6450-sony-xperia-*-pdx246.dts`, following pdx225's
   conventions.
4. **The long tail**, roughly in order of payoff: interconnect and cpufreq-EPSS
   (no sibling template), tsens, Wi-Fi/BT via ath10k plus `hci_qca` (cheap,
   given WCN3990), display (DSI host plus a per-device panel driver derived
   from the downstream panel code — the hardest single item), GPU (an a7xx
   match in `drm/msm` plus the zap shader from the vendor partition), audio via
   ADSP, modem (remoteproc MPSS plus `rmtfs`/`pd-mapper`/`tqftpserv`), sensors,
   touchscreen (`blair-touch.dtsi` in the QRD chain), charger via `pmic_glink`.

### What is out of scope

- **Camera, realistically never** — per-SoC CAMSS plus per-sensor drivers plus
  tuning, and libcamera has no SM6450 support.
- **Rust, for process reasons rather than technical ones** — Rust-for-Linux is
  real upstream (Nova, Tyr, binder, the DRM panic handler), but it exists only
  where maintainers have built abstractions, and `clk`, `pinctrl`, `regulator`,
  `interconnect`, `remoteproc` and `drm/msm` have none. An SM6450 port written
  in Rust would be rejected before the logic was read. The leverage for this
  device is in C, and most of it is transcribing facts out of Sony's GPL tree.

## Effort and risk

- **Phase 1 is weeks of careful transcription** — and the mechanical majority
  of it has a worked example.
- **"Mainline boots to a shell" is plausible in a couple of months** — phases
  1 and 2, *with device access*. Display and GPU are the long poles after that,
  and a usable daily-driver phone is the same one-to-two-person-year project
  the sm6375 and sm8550 ports were.
- **The dominant risk is debuggability, not difficulty** — mainline SoC
  bring-up is debugged through the serial console, and on a first mainline boot
  the console is part of what is being brought up. A hand-written `sm6450.dtsi`
  that does not boot produces a black screen and no signal. The downstream
  kernel has a console Sony ships working, plus the 256K ramoops ring already
  reserved in the DTB we build. That asymmetry is the entire argument for doing
  Phase 0 first, and it is why this document does not change the plan.

## Sources

- Inventory and the 119/119 clock comparison: the two tarballs in
  `.pmb/work/cache_distfiles/`, as fetched by
  [the kernel APKBUILD](../aports/device/testing/linux-sony-pdx246/APKBUILD)
- Upstream tree, checked 2026-10-05:
  <https://github.com/torvalds/linux/tree/master/arch/arm64/boot/dts/qcom>
- Mesa device table:
  <https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/freedreno/common/freedreno_devices.py>
