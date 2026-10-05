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
- **Wi-Fi/BT is WCN6750, not WCN3990** — Verified on the device 2026-10-05,
  and this reverses what this file said before. The live hardware has
  `22800000.qcom,icnss` bound to `icnss2`, a dedicated WPSS remote processor at
  `0x8a00000` on `qcom_q6v5_pas`, and `qcom,smp2p-wpss` beside it. WCN3990 has
  no WPSS at all: it runs on SNOC under plain `icnss`. The earlier reading came
  from Qualcomm's QRD board files, which describe reference boards and not
  Sony's, and Sony's own board tree turns out not to be in the device tree
  release. Upstream it is still good news, just a different driver:
  `qcom,wcn6750-wifi` is in `ath11k` as `ATH11K_HW_WCN6750_HW10`, AHB and WPSS
  based, and documented in `qcom,ath11k.yaml`. Bluetooth is still `hci_qca`.
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
  against `torvalds/linux` master, and absent from Qualcomm's own CLO `ark-6`
  6.12 kernel too: 454 files under its `arch/arm64/boot/dts/qcom` and not one
  `sm6450` or `parrot` among them. The family upstream stops at sm4250,
  sm4450, sm6115, sm6125, sm6350 and sm6375. So there is no tree to rebase
  onto and no half-finished series to pick up, from Qualcomm or anyone else.
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

## The SoC memory map, confirmed against the sibling

Read off the live device on 2026-10-05 with `scripts/device-collect.sh`, which
needs no root, and compared against upstream `sm4450.dtsi`. This upgrades the
sibling claim from matching clock register offsets to matching register bases,
and marks where the resemblance stops.

- **Eight core blocks sit at identical addresses in both** — Verified. GCC at
  `0x100000`, dispcc at `0xaf00000`, gpucc at `0x3d90000`, cpufreq-hw at
  `0x17d91000`, RPMh RSC at `0x17a00000`, the arch timer at `0x17420000`, the
  TCSR hwlock at `0x1f40000`, and GENI QUP_1 at `0xac0000`.
- **TLMM does not match** — Verified. `0xf000000` here against `0xf100000`
  upstream, so the pin controller base is per-SoC and `pinctrl-sm6450.c`
  cannot inherit the sibling's.
- **The cluster split does not match either** — Verified. 4+4 A78/A55 here
  against upstream sm4450's 2 A78 plus 6 A55, so the CPU nodes, OPP tables and
  cpufreq data are ours to write rather than to copy.
- **Upstream sm4450 stops well short of the peripherals** — Verified. Its
  `sm4450.dtsi` is 686 lines with no display, no UFS, no SMMU and no
  remoteproc. The blocks it omits are exactly the ones listed next, so the
  template covers phase 1 and runs out before phase 2.

### Peripherals, with addresses and upstream status

All Verified on the live device unless marked otherwise. The addresses are what
an `sm6450.dtsi` has to declare, and they were obtained without root, so this
list is cheap to re-derive and worth trusting.

- **Four remote processors, all on `qcom_q6v5_pas`** — ADSP at `0x3000000`,
  CDSP at `0x32300000`, MSS at `0x4080000`, WPSS at `0x8a00000`. The PAS loader
  is the same driver mainline uses, so these want DT nodes and firmware names
  rather than new code.
- **A PMIC trio over SPMI at `0xc42d000`** — `pm6450` at SID 1, `pm7250b` at
  SID 3 and `pm6150l` at SIDs 4 and 5, under `spmi_pmic_arb`. This corrects the
  pair named earlier in this file: there are three. Upstream already has
  `pm6150l.dtsi` and `pm7250b.dtsi`, so only `pm6450.dtsi` is new, and PMIC
  trees are small and declarative.
- **Display at `0xae00000`** — MDSS, DSI controller 0 at `0xae94000`, DSI PHY 0
  at `0xae94400`, DisplayPort at `0xae90000`, three SDE CRTCs live. One DSI
  link, so one panel.
- **GPU at `0x3d00000`** — GMU at `0x3d68000`, its own SMMU at `0x3da0000`,
  consistent with the Adreno 710 recorded above.
- **UFS at `0x1d84000`**, PHY at `0x1d87000`.
- **Two GENI QUP wrappers** — QUP_0 at `0x9c0000` with I2C at `0x980000` and
  `0x988000`; QUP_1 at `0xac0000` with I2C at `0xa80000` and `0xa8c000`. The
  debug UART at `0x98c000` in [05-status.md](05-status.md) is QUP_0's, whereas
  upstream sm4450's only serial is QUP_1's at `0xa88000`.
- **Touchscreen is FocalTech on I2C bus 3 at `0x38`** — downstream driver
  `fts_ts`. Mainline has no driver for this part, so it joins the display long
  pole rather than being free.
- **Charging is firmware-mediated rather than register-level** — the battery
  and USB power supplies come from `qcom,pmic_glink` with a UCSI endpoint
  (`ucsi-source-psy-...:qcom,ucsi1`). Upstream that is `qcom_battmgr` plus
  `ucsi_glink`, both already there, which deletes a whole class of charger
  work from the long tail.
- **NFC, LEDs and vibrator are conventional** — NXP NFC on I2C bus 2 at `0x28`
  (`ro.hardware.nfc_nci = SNxxx`), tri-LED and LPG PWM on `pm6150l`, flash LED
  likewise, vibrator on `pm7250b` through `qpnp-vibrator-ldo`. Mainline's
  `leds-qcom-lpg` covers the first two.
- **The board tree is no longer missing, and there was never a Sony one** —
  Verified 2026-10-05 by capturing the live device tree from recovery, where
  adbd runs as root. It decompiles to 27892 lines and its `model` is
  "Qualcomm Technologies, Inc. Parrot QRD", `compatible` `qcom,parrot-qrd`,
  board-id `<0x1000b 0x00>`. Sony did not write a board tree: they ship
  Qualcomm's QRD reference tree, which is why the device tree release has no
  pdx246 files. The captured tree is the merged base-plus-dtbo result the
  kernel actually received, so it is better than either input on its own, and
  it is what `sm6450-sony-xperia-pdx246.dts` gets transcribed from.
- **The panel is a Samsung FHD AMOLED in command mode** — Verified.
  `qcom,mdss_dsi_samsung_fhd_amoled_cmd`, named "samsung fhd amoled cmd mode
  dsi panel", selected by `msm_drm.dsi_display0=` on the kernel command line
  and present as a node with its timings in the live tree. Its display rails
  are OLEDB and IBB under `qcom,amoled` on `pm6150l`. Command mode matters: a
  mainline panel driver for it needs `MIPI_DSI_MODE_` flags and a TE line, not
  the simpler video-mode path.

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
