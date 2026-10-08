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
- **Nothing on the mailing lists, and nothing in anyone's tree** — Verified
  2026-10-05, by a different route than intended. `lore.kernel.org` is still
  behind an Anubis challenge and refuses every fetch, so the lists were checked
  indirectly: mainline master's `arch/arm64/boot/dts/qcom/Makefile` names no
  sm6450 and no parrot target, and a GitHub repository search for sm6450 and
  parrot-mainline returns only vendor Android kernels — Sony's (the two this
  port already builds from), Motorola's and Oppo's. There is no mainline SM6450
  work in public anywhere, half-finished or otherwise. That makes this the
  first such port rather than a contribution to one, which is the whole reason
  the upstream-shape question matters from the first patch.

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

## The base

6.18, on the owner's instruction, and the calendar agrees with it. 6.18 was
released 2025-11-30 and is a longterm kernel maintained by Greg Kroah-Hartman
and Sasha Levin with a projected EOL of December 2028, so a port that lands on
it has three years of stable branch under it rather than a ten-week window.

The working tree is `out/linux`, a depth-1 clone of the `linux-6.18.y` stable
branch. It is gitignored and disposable; nothing in this repo depends on it
surviving.

Two things follow from basing on a stable branch rather than mainline, and both
matter for the upstream goal.

- **Patches get written against 6.18 and rebased onto `next` to submit.** No
  new driver is ever accepted into a stable branch, so 6.18 is where the device
  boots and `linux-next` is where the series goes. Keeping that split explicit
  from the first patch is cheaper than discovering it at submission time.
- **Nothing may depend on a 6.18-only backport.** Stable carries fixes that
  mainline already has, so this direction is safe — but a driver written against
  a 6.18 API that `next` has since changed is a rebase conflict, and the
  SM6450 work touches `clk`, `pinctrl` and `interconnect`, all of which see
  churn.

## What has been written so far

Twenty-three patches against v6.18.55, exported to
[../kernel/patches/](../kernel/patches/) by `scripts/sync-kernel-patches.sh`
so the work does not live only in the gitignored `out/linux`. Nothing below
has run on the device.

The two drivers that had to be written:

- **`dt-bindings: clock: Add Qualcomm SM6450 GCC clock bindings`** — the
  binding plus `include/dt-bindings/clock/qcom,sm6450-gcc.h`, 182 defines.
- **`clk: qcom: Add Global Clock Controller driver for SM6450`** —
  `gcc-sm6450.c`, 2774 lines, plus the Kconfig and Makefile entries.
- **`dt-bindings: pinctrl: Add Qualcomm SM6450 TLMM bindings`** — 87 documented
  functions, gpio0-gpio140 plus `ufs_reset` and the sdc2 pins.
- **`pinctrl: qcom: Add SM6450 pinctrl driver`** — `pinctrl-sm6450.c`, 1113
  lines: 149 pin descriptors, 141 gpio pingroups, 83 wakeirq entries.

Then four table additions, because everything else SM6450 needs at this level
was already defined upstream for some other chip and only needed a name:

- **`dt-bindings: clock: qcom,rpmhcc: Add SM6450`** and **`clk: qcom:
  clk-rpmh: Add support for SM6450`** — thirteen clocks, every one of them an
  existing upstream definition. The table differs from SM4450's only in using
  `ln_bb_clk3_a2` and in having RF_CLK2 at all.
- **`dt-bindings: power: qcom,rpmpd: Add SM6450`** and **`pmdomain: qcom:
  rpmhpd: Add SM6450 power domains`** — cx and cx_ao, ebi, gfx, lcx, lmx, mss,
  mx.

Then the PMIC side, which is one driver table and three device trees:

- **`dt-bindings: spmi: Add SM6450 SPMI PMIC arbiter`** — one enum line. The
  arbiter is a v7 with two buses and no driver change is needed, because the
  driver reads the hardware version out of a register.
- **`dt-bindings: mfd: qcom,spmi-pmic: Add PM6450`** and **`arm64: dts: qcom:
  Add PM6450 PMIC device tree`** — `pm6450.dtsi`, 63 lines: the temperature
  alarm with the device's own trip points, its thermal zone, and the nine
  GPIOs.
- **`dt-bindings: regulator: qcom,rpmh-regulator: Add PM6450`** and
  **`regulator: qcom-rpmh: Add support for PM6450`** — 25 rails. The other
  eight the PMIC has are either ARC resources that `rpmhpd` already describes
  or are not named by any RPMh resource at all.
The other two PMICs needed no new code at all: `pm6150l.dtsi` matches our
SIDs 4 and 5 as shipped, and `pmk8350.dtsi` was already parameterised.
Stock's tree also describes a PMR735A at SID 6, and the series used to carry
a patch making `pmr735a.dtsi`'s SID overridable for it. Round 22 showed the
PMR735A is not fitted, so that patch is gone; see `05-status.md`.

Then the device trees, and the binding lines they need to validate:

- **`dt-bindings: qcom: Add SM6450 compatibles for PDC, IPCC, WDT and EPSS`** —
  enum additions in four existing bindings.
- **`dt-bindings: arm: qcom: Document SM6450 and Sony Xperia 10 VI`** — the
  `sony,pdx246` / `qcom,sm6450` board compatible.
- **`arm64: dts: qcom: Add SM6450 SoC device tree`** — `sm6450.dtsi`, 1320
  lines: the eight CPUs with their caches, idle states and PMUs, the
  38-region reserved-memory map, GCC, TLMM, TCSR, the GENI UART, PDC, IPCC,
  the GIC, the watchdog, the arch timer, the RSC with rpmhcc/rpmhpd/bcm-voter
  under it, EPSS cpufreq, the SPMI arbiter with both its buses, the AOSS side
  channel and its sleep stats, SMEM with the four SMP2P edges that ride on
  it, the apps SMMU, the SD card controller, and USB with its high-speed PHY.
- **`arm64: dts: qcom: Add Sony Xperia 10 VI`** — 363 lines: the three PMICs,
  the 38 RPMh regulators command DB knows, with the windows the board's own
  firmware uses, the power and volume keys, the SD card slot with its card
  detect, USB in OTG mode with the high-speed PHY tuned the way the board's
  own firmware tunes it, and the UART as `serial0`.
- **Four more binding lines**, one SoC name each — `dt-bindings: iommu:
  arm,smmu`, `dt-bindings: mmc: sdhci-msm`, `dt-bindings: phy:
  qcom,usb-snps-femto-v2` and `dt-bindings: usb: qcom,dwc3`.

### Both drivers were generated by a program, not transcribed

The method is the one the Rosetta Stone makes possible. Qualcomm released the
vendor sources for ravelin and someone upstreamed them as sm4450, so both ends
of the transformation are on disk for a sibling SoC. That turns "convert the
vendor driver carefully" into "write the conversion, run it on the pair where
the answer is known, and score it".

- `scripts/downstream-to-mainline.py` does the clock controllers. Run on
  ravelin it reproduces upstream `gcc-sm4450.c` to 97.6%, and its header
  generator reproduces `qcom,sm4450-gcc.h` exactly, all 182 defines.
- `scripts/pinctrl-to-mainline.py` does the TLMM. Run on ravelin it reproduces
  `pinctrl-sm4450.c` to 96.6%, and a semantic comparison of the five things
  that reach the hardware — pin descriptors, function enum, pingroup rows,
  wakeirq map, function group sets — is identical. What differs is the order
  and wrapping inside the function group lists, where upstream is itself
  inconsistent.
- `scripts/check-tables.sh` compares the generated driver against the vendor
  source it came from, register by register and mux slot by mux slot. It is the
  check that matters, because it compares against parrot rather than against a
  sibling.

The residual percentages are not slop to be cleaned up later. Each one is a
listed judgement call that the self-test can never close, because it is a place
where the upstream submitter knew something the vendor source does not say.
The clk converter's docstring enumerates its eight; the pinctrl converter's
are the 21 function names parrot has that ravelin does not, resolved from
`pinctrl-milos.c` and sm4450's own sibling naming rather than guessed.

### What the proofs cover, and what they do not

For the clock controller: all 114 register offsets identical to the vendor
driver with nothing dropped or renamed; every numeric literal diffed, with the
only differences being the copyright year, the three GDSC offsets and sixteen
structural zeros each individually accounted for.

For the pinctrl driver: all 141 shared pin entries agree with
`pinctrl-parrot.h` slot for slot. That check earned its keep immediately — it
caught nine pins whose mux assignments had silently become "unused" because the
generator lower-cased the function tables but not the bare macro arguments in
the `PINGROUP` rows. Nothing else would have noticed: it compiles, it loads,
and nine mux settings quietly do nothing.

For the device trees, a cross-check against the tree the device actually
boots. The reference is not the vendor source and not the `parrot.dtb` in the
`boot` partition either, but `/proc/device-tree` read off the running stock
Android and captured by `scripts/device-collect.sh`. That is the fully
resolved tree — base DTB plus the board overlay plus whatever the bootloader
patched in — for this exact phone, which makes it strictly better evidence
than either. Rebuild it with:

    out/kbuild/scripts/dtc/dtc -I fs -O dts out/device-dump-root/devicetree/base

`scripts/check-dt.py` compares the two and is the repeatable form of the
check:

    scripts/check-dt.py --allow 0xf100000=tlmm-rebased-off-0xf000000 \
        ours.dts live-parrot.dts

- **Every address exists.** All 66 unit addresses in our board DTB are
  accounted for in the stock tree. The two sides are read asymmetrically on
  purpose: ours from unit addresses only, because that is what we are
  asserting, and theirs from unit addresses *plus* every value a `reg` could
  be hiding, under both the one-cell and two-cell reading, because the stock
  tree is evidence and anything in it counts. That matters twice over here —
  the stock SPMI arbiter names itself after its config block and keeps the
  real core address inside `reg`, and the stock EPSS node has no unit address
  at all.
- **One deliberate difference, and it has to be declared to pass.** Our
  `tlmm` sits at `0xf100000` where stock puts it at `0xf000000` and bakes a
  `0x100000` offset into every pin register. Mainline's convention is the
  other way round, and `pinctrl-sm4450.c` does the same. `--allow` is what
  turns that from a silent difference into an argument someone can disagree
  with; without it the script fails.
- **One address is accounted for by containment, not by name.** Mainline
  points at the USB QSCRATCH bank at `0xa6f8800`; the stock tree declares the
  whole peripheral as one region from `0xa600000` for a megabyte. The script
  reports that as `WITHIN` rather than folding it into the exact hits, because
  being inside a large region is weaker evidence than matching an address.
- **Every interrupt matches.** 14 of the 15 nodes the two trees agree on the
  address of carry exactly the stock numbers. The one difference is the
  watchdog, which takes only the bark interrupt, because that is what the
  mainline `qcom,kpss-wdt` binding describes.

### The regulators are the one place with real guesswork

Every rail's voltage window is copied from the board's own
`parrot-regulators.dtsi`, so the windows are not guesses. What is not in any
vendor source is the regulator *sub-type* — `pmic5_nldo` versus `pmic5_pldo`
versus which of the four SMPS tables — because downstream does not model it:
the vendor's `qcom,regulator-type` has exactly three values, `pmic5-ldo`,
`pmic5-bob`, and the implicit SMPS default. So it has to be inferred, and the
inference is worth stating plainly.

- **The rule.** Board window max at or below 1304000 means `pmic5_nldo`;
  anything higher is one of the pldo tables; the SMPS table follows from the
  step alignment of the stock init voltage.
- **Its score.** Two PMICs in stock's tree, PM6150L and PMR735A, already
  have upstream answers, which makes them a test set. The PMR735A turned out
  not to be fitted, but its windows still test the rule. The rule puts **16 of 16**
  used rails in the right family.
- **The one distinction it cannot make** is `pmic5_pldo` against
  `pmic5_pldo_lv`, and upstream makes that one inconsistently from the same
  evidence: PM6150L's `ldo1` at 1.62–1.98 V is `pldo_lv` while its `ldo8` at
  1.62–2.00 V is `pldo`. Every rail at 1.5 V and up here gets the superset
  `pmic5_pldo`, because a superset can only ever permit a voltage the board's
  own DT window already permits.
- **Why a wrong sub-type cannot damage the phone.** The VRM register takes
  millivolts, not a selector index:
  `_rpmh_regulator_vrm_set_voltage_sel()` does
  `cmd.data = DIV_ROUND_UP(regulator_list_voltage_linear_range(rdev, selector), 1000)`.
  A mis-chosen table can therefore only restrict or over-permit the *set* of
  requestable voltages. It can never program a different voltage than the one
  asked for.

Two smaller proofs on the same increment. The arbiter really is a v7: the
vendor `spmi-pmic-arb.c` reads `qcom,bus-id` only inside
`if (hw_ver >= PMIC_ARB_VERSION_V7_MIN)`, and the stock tree sets it on both
arbiter nodes — and the register layout then turns out to match upstream
`sar2130p.dtsi` exactly, which is where the compatible fallback comes from.

Everything compiles for arm64 at `W=1` with no warnings, the device trees
build with `CHECK_DTBS=y` clean, all seventeen touched bindings pass
`dt_binding_check`, and `checkpatch --strict` reports zero errors across the
twenty-three patches. What it does report is shared with upstream's own files: 86
"blank line after struct" checks and five `PINGROUP` rows past 100 columns,
which `pinctrl-sm4450.c` and `pinctrl-milos.c` have too, and the "does
MAINTAINERS need updating" notice, which `get_maintainer.pl` shows is already
answered by the directory wildcards.

None of this is evidence the hardware works. It is evidence that the driver
says what the vendor driver says, which is a different and much weaker claim.

### Three more derivations on the storage and USB side

None of these is a guess, and each one is a different kind of argument.

- **The vendor's clock ids are not ours, so nothing is copied by number.**
  Both headers carry the same names and different numbers, because ours is
  generated in upstream's order. Everything taken out of the live tree goes
  through `clkmap.py`, which translates a vendor id into a name and then
  checks the name exists in our header, exiting nonzero if it does not. Every USB, SD and UFS clock resolved
  that way, and the *resets* turned out to match by number as well -
  `GCC_USB30_PRIM_BCR` is 18 in both, `GCC_UFS_PHY_BCR` 17, and
  `GCC_QUSB2PHY_PRIM_BCR` 14 - which is a free cross-check on the generated
  driver.
- **The HS PHY's raw register tuning inverts exactly.** The stock tree tunes
  the PHY by writing four registers through `qcom,param-override-seq`:
  `0x83` to `HS_PHY_OVERRIDE_X0`, `0xc6` to X1, `0x1e` to X2 and `0x03` to
  X3. Mainline expresses the same thing as named properties in physical
  units, and the offsets in `phy-qcom-snps-femto-v2.c` are the same four. All
  nine bitfields invert cleanly through that driver's tables, which is not
  automatic: `hs-crossover-voltage` has three table entries for a two-bit
  field and `ls-fs-output-impedance` five for a four-bit field, so a
  different PHY generation would likely have produced a value with no entry.
  Both landed on the nominal entry, which is what an untuned field should do.
- **One interrupt is inferred, and it is marked in the source.** The stock
  tree names four of dwc3's five interrupts; it has no `hs_phy_irq`, which
  the mainline binding requires in second position. SPI 130 for `pwr_event`
  and SPI 133 for the core are exactly SM6350's, which puts `hs_phy_irq` at
  131 - and a sweep of every GIC line the stock tree claims shows 131 and 132
  free. That is the single inferred number in the storage and USB work.

### What is deliberately not written yet

**The UFS PHY.** The controller is straightforward - every clock, reset,
supply and interrupt resolves - but upstream has no generic UFS PHY
compatible. Each SoC gets its own entry in `phy-qcom-qmp-ufs.c` carrying the
PHY's register init sequence, and that sequence is the one thing on this
device that is not derivable from anything on disk: Qualcomm released the
clock, pinctrl, regulator and SPMI sources for parrot but not the PHY driver,
and the init tables are not in the device tree the way the USB combo PHY's
are. The stock compatible says `qcom,ufs-phy-qmp-v4-parrot`, so it is a QMP
v4, but picking a v4 table from another SoC and calling it this one's would
be a guess of exactly the kind this file exists to avoid. It costs nothing
for now: the loop boots from the SD card, which is written.

**The USB3 + DP combo PHY**, for the same reason, and with one extra lead
worth following - unlike UFS, the stock tree *does* carry its init sequence,
as a 400-entry `qcom,qmp-phy-init-seq` on the PHY node. Scoring that against
each upstream combo-phy table would identify the generation the same way the
ravelin/sm4450 pair identified the clock and pinctrl conversions. Until then
the controller runs at high speed, which is all a console needs.

### Four upstream inconsistencies found on the way

All four are in SM4450, the sibling this port leans on hardest, and all four
are reasons not to copy a sibling blindly. None is copied here.

- **`qcom,sm4450-tlmm.yaml` documents a function its driver does not
  implement.** The binding lists `qup1_se2_l2`, `pinctrl-sm4450.c` has no such
  function, and `sm4450.dtsi` uses it for `qup_uart7_rx`. That pinctrl state
  cannot apply.
- **`qcom,sm4450-gcc.yaml` omits the PCIe pipe clock.** Its `DT_` enum has
  seven entries and the binding lists six. The SM6450 binding lists all seven.
- **`sm4450.dtsi` points all eight CPUs at one power domain.** It defines
  `cpu_pd0` through `cpu_pd7` and then gives every CPU `power-domains =
  <&cpu_pd0>`. Every other upstream qcom dtsi wires them 1:1, and so does
  ours.
- **`sm4450.dtsi` hands cpufreq a 9.6 MHz "xo".** Its `RPMH_CXO_CLK` is
  already divided by four, and it then passes `bi_tcxo_div2` to the EPSS node,
  halving it again. SM8450, which also has a div4 CXO, passes `RPMH_CXO_CLK`
  straight through; so does ours. The clue is that SM8550's div2 CXO makes the
  identical-looking node come out at 19.2 MHz.

## Building it

### The whole series links into a kernel

The first real build ran on 2026-10-06: `arm64` `defconfig` plus
`SM_GCC_6450`, `PINCTRL_SM6450` and `PHY_QCOM_USB_SNPS_FEMTO_V2`, built with
the container's `aarch64-linux-gnu-gcc` 14.2.0 out of tree into `out/kbuild`.
It produced `vmlinux` and `Image` with no warning and no error, in four and a
quarter hours of wall clock.

That is worth stating plainly because up to that point the generated drivers
had only ever been compiled as individual object files. `defconfig` is also a
harsher test than the config we ship: it turns on every unrelated subsystem,
so anything our patches did to a shared header or a Kconfig would have shown
up as a failure somewhere else in the tree. Nothing did.

What the link proves, from `nm vmlinux`:

- `gcc_sm6450_probe`, `gcc_sm6450_desc`, `gcc_sm6450_clocks`,
  `gcc_sm6450_resets`, `gcc_sm6450_gdscs` and the regmap config are all
  present, registered through `__initcall__kmod_gcc_sm6450__..._init4` -
  `subsys_initcall`, which is where a clock controller has to run.
- `sm6450_tlmm_probe` and `sm6450_tlmm_of_match` likewise, at `init3`.
- `pm6450_vreg_data` is linked into `qcom-rpmh-regulator`.

It does not prove any of it is *correct*. A driver that registers 119 clocks
at the wrong offsets links exactly as cleanly as one that does not. What it
rules out is the whole class of mistake that would have made the next step
impossible to interpret.

### The kernel aport

`aports/device/testing/linux-postmarketos-qcom-sm6450` is the package.
Modelled on `linux-postmarketos-qcom-milos`, the newest mainline Qualcomm
kernel in pmaports, with two deliberate differences.

- **The source is a kernel.org tarball, not a fork.** milos and sm6350 both
  point at a GitHub fork and a tag. There is no fork here; the work only
  exists as patches in this repository. Keeping the base a released tarball,
  `linux-6.18.55.tar.xz`, is what makes "based on 6.18.55" something a
  stranger can check.
- **One squashed patch, not twenty-three.** `scripts/sync-kernel-patches.sh`
  now writes the branch out twice from the same range on the same run:
  `kernel/patches/` as one patch per commit, which is the form the work is
  reviewed and posted in, and `sm6450-mainline.patch` in the aport as a single
  diff. An APKBUILD listing twenty-odd patch files would need its `source=`
  and twenty-odd checksums rewritten on every kernel commit, and abuild does
  not care how the diff is divided. The squashed file carries a header saying
  which copy to read.

Both forms were checked to apply to a pristine tree before the first build:
`git apply -R --check` and `patch -p1 -R --dry-run` both accept the squashed
diff against `HEAD`, which is the same question as applying it forward onto
`v6.18.55`.

The shipped config is not `defconfig`. It is
`config-postmarketos-qcom-sm6350.aarch64` from pmaports - the pmOS-maintained
config for the closest sibling SoC, already carrying everything postmarketOS
needs and already passing its own `kconfigcheck` - with its eight
SoC-specific symbols retargeted and then normalised by `olddefconfig` against
6.18:

- `PINCTRL_SM6350` and `SM_GCC_6350` became `PINCTRL_SM6450` and
  `SM_GCC_6450`.
- `SM_CAMCC_6350`, `SM_DISPCC_6350`, `SM_GPUCC_6350`, `SM_VIDEOCC_6350`,
  `INTERCONNECT_QCOM_SM6350` and `PINCTRL_SM6350_LPASS_LPI` were dropped. We
  have written no equivalent of any of them.
- `PHY_QCOM_USB_SNPS_FEMTO_V2` was added, because SM6350 uses the older QUSB2
  HS PHY and our `usb_1_hsphy` is `qcom,usb-snps-hs-7nm-phy`.

Everything else the board needs was already on: the SPMI arbiter, the RPMh
clocks, power domains and regulators, the SMMU, `sdhci-msm`, `dwc3-qcom`, the
GENI serial console, `qcom-pon`, `nvmem-spmi-sdam` and `rtc-pm8xxx`. Notably
`USB_DUMMY_HCD` is off, which removes the trap that cost a day on the
downstream kernel.

### The device package now offers a choice of kernel

`device-sony-pdx246` grew two subpackages, `-kernel-downstream` and
`-kernel-mainline`, selected in `pmbootstrap init`. They are not
interchangeable, and every key that differs carries the suffix the mechanism
keys off:

- `deviceinfo_dtb_downstream` is `vendor/qcom/parrot`, the Qualcomm reference
  tree that expects the stock dtbo overlay on top.
  `deviceinfo_dtb_mainline` is `qcom/sm6450-sony-xperia-columbia-pdx246`, one
  complete tree that wants nothing from the dtbo partition.
- `deviceinfo_usb_network_udc_downstream` is `a600000.dwc3` and the mainline
  one is `a600000.usb`, because a platform device is named after its device
  tree node and the two trees name the dwc3 core differently.
- `modules-initfs.downstream` is a hundred lines in probe order;
  `modules-initfs.mainline` names nothing. Not because everything is builtin -
  `sdhci-msm`, `mmc_block`, `ext4`, `dwc3`, `gcc-sm6450` and `pinctrl-sm6450`
  are, but the USB gadget functions are not. It names nothing because mkinitfs
  already asks for them: its own `00-default.modules` lists `usb_f_acm`,
  `usb_f_ncm`, `usb_f_rndis` and `usb_f_mass_storage`, and it follows modinfo
  dependencies, so `libcomposite`, `u_ether` and `u_serial` come along. The
  built initramfs holds fifteen modules on the strength of a file that names
  none, which was worth checking rather than assuming: they are the only
  channel a first boot has.
- `kernel-cmdline.mainline.conf` asks for `earlycon=qcom_geni,mmio32,0x98c000`
  rather than a bare `earlycon`. The bare form relies on `/chosen`'s
  `stdout-path`, and the one the bootloader writes points at
  `/soc/qcom,qup_uart@98c000`, a path that exists in the stock tree and not in
  ours. If it overwrites the one our board file sets, `of_stdout` comes back
  NULL and a bare `earlycon` does nothing, silently - the worst possible
  failure for the only thing we can watch a first boot with.

A deviceinfo key that has a suffixed form must not also exist unsuffixed;
`devicepkg_subpackage_kernel` fails the build if it does, which is how the
unsupported half-converted state is caught.

### The two properties the bootloader selects a tree on

A mainline device tree is not selectable by this bootloader as it stands, and
the reason has nothing to do with the tree being wrong.

Qualcomm's boot chain reads the SoC id out of the fuses and the board id out of
shared memory, walks the dtb area of `vendor_boot`, and boots the tree that
advertises both in `qcom,msm-id` and `qcom,board-id`. Every mainline tree
advertises neither - no upstream qcom dtsi has ever carried those properties,
and a patch adding them should be rejected, because they describe the
firmware's selection protocol rather than the hardware. `dtb-ids.py` on the
`vendor_boot.img` boot-deploy builds confirms ours comes out with both empty.

So `scripts/dtb-stamp-ids.py` adds them on the way into the image, and the
`.dts` that goes to the lists stays clean. A `dtc` round-trip shows the stamp
adds exactly two lines and changes nothing else.

It does the FDT surgery itself rather than calling `fdtput`, and that is not
gratuitous. `fdtput` and `dtc` are in the pmport container; `fastboot` and
`adb` are on the host, and this project may not install anything there. So
`try-kernel.sh`, which needs both, could not run on either side - it got as far
as "stamping the bootloader ids" and died on "fdtput not found". Eighty lines of
Python buys a loop that runs from one place. It is checked against the
implementation it replaced: byte-identical output, and stamping an
already-stamped tree is a no-op rather than a tree with two `qcom,msm-id`
properties in it.

Getting the values right needed one correction, because the obvious source is
the wrong one. `/proc/device-tree` on the running phone has
`qcom,board-id = <0x1000b 0x0>` at its root, and that is what the script
stamped first. But the live tree's root is the *resolved* tree, and its `model`
reads "Parrot QRD" - so those are `parrot-qrd-overlay`'s properties, which
overrode the base's. Read Sony's own `vendor_boot` instead and all fourteen
base trees carry `<0x0 0x0>` or `<0x0 0x600>`: bases are generic and separated
by `qcom,msm-id` alone, and it is the overlays that carry a board id.

That correction was right about where to look and wrong about what to conclude,
and it took the rest of this section to find out why. Imitating the generic
bases is correct for the matcher Sony's firmware actually uses on the way to
Android, and that matcher is not the one our kernel is routed through, so the
board id ends up back at `0x1000b` by a different argument.

Which base to imitate is settled by the device rather than inferred.
`/sys/devices/soc0` reports `soc_id` 537 = `0x219` and `platform_version`
`0x10000`, which is exactly what "Qualcomm Technologies, Inc. Parrot SoC"
advertises, so `qcom,msm-id = <0x219 0x10000 0x265 0x10000>` is what we claim
to be. `qcom,pmic-id` is left unset, because no base tree in the stock image
carries one.

The board id took a second correction, and the reason is that ABL does not
have one matcher. It has two, and which one runs depends on the dtbo
partition. `BootLinux.c` branches like this:

    DtboImgInvalid = LoadAndValidateDtboImg (Info, BootParamlistPtr);
    if (!DtboImgInvalid) {
      // appended device tree
      Dtb = DeviceTreeAppended (...);
    } else {
      SocDtb = GetSocDtb (...);
      BoardDtb = GetBoardDtb (Info, BootParamlistPtr->DtboImgBuffer);
      if (!BoardDtb) {
        DEBUG ((EFI_D_ERROR, "Error: Board Dtbo blob not found\n"));
        return EFI_NOT_FOUND;
      }
      ...
      Status = ApplyOverlay (BootParamlistPtr, SocDtb, DtsList);
    }

The name is inverted - `LoadAndValidateDtboImg` returns true when the image is
*good* - so a dtbo ABL can parse takes the `else` branch and a dtbo it cannot
parse takes `DeviceTreeAppended`, which selects a tree and applies nothing on
top of it. The two branches score candidates differently. `GetSocDtb` and
`GetBoardDtb` use a scoring matcher where a zero field counts as a default and
still scores, which is why Sony's generic bases pass with `<0x0 0x0>`.
`DeviceTreeAppended` uses the older LK matcher, and `platform_dt_absolute_match`
there wants the SoC id, the platform type, the platform subtype and the DDR
type to be *equal* to the board's, discarding the tree outright otherwise.
Zero is not a wildcard on that path; it is a value that does not match.

Which matters because the mainline kernel has to take the appended path. It is
the only one of the two that applies no overlay, and no overlay is a hard
requirement: our tree has no `__symbols__`, because upstream builds without
`dtc -@`, so every one of the 37 stock overlays would fail to resolve its
`__fixups__` against it, and a failed overlay is what red-states this phone. On
2026-10-05 a `vendor_boot` identical to stock except for the device tree was
declared corrupt over 61 unresolvable labels; ours would fail on all 1234.

The first attempt to arrange that was `empty-dtbo.py`, an Android DT table with
`dt_entry_count = 0`, on the theory that a bootloader iterating an empty table
would find nothing to apply and carry on. It was run on 2026-10-06 and the
device red-stated. The sources say why, and it is the one shape that could not
have worked: `LoadAndValidateDtboImg` checks the magic, the total size against
zero, the header size, the entry size, the entry offset and the entry count
against the partition size, and a count of zero passes every one of them. ABL
declared the image good, committed to the overlay branch, and then `GetBoardDtb`
looped zero times, left `BestDtbInfo.Dtb` NULL and returned `EFI_NOT_FOUND`. An
empty table is not a table with nothing to apply; it is a table ABL trusts and
then cannot satisfy. A table full of overlays for *other* SoCs would have been
fine - Sony's own carries fourteen, for Montague and Ravelin - so long as one
entry matches.

So the dtbo is now made unreadable rather than empty, which is also what the
postmarketOS wiki means when it tells you to `fastboot erase dtbo` for mainline
on Qualcomm. `scripts/no-dtbo.py` writes zeros: the magic check is the first
thing done with the image, so four zero bytes are the whole mechanism.

There was a tidier route and it is closed. `GetSocDtb` logs "Exact DTB match
found. DTBO search is not required" and sets `DtboNeed = FALSE` when a base
matches on every field it scores, and `BootLinux.c` then skips `GetBoardDtb`
entirely, leaving the stock dtbo in place. "Every field" is `ALL_BITS_SET`,
which includes all sixteen `PMIC_MATCH_EXACT_MODEL_IDX0..F` bits; those come
only from a `qcom,pmic-id`, no base tree here has one, and `qcom,pmic-id-size`
caps the index at `0xF`, one short of the sixteen required. It cannot be
satisfied on this device.

Taking the appended path means the stamp has to satisfy the strict matcher, so
`qcom,board-id` is no longer `<0x0 0x0>` but `<0x1000b 0x0>`: `0x0b` is QRD,
which is what `hw_platform` says, and the `0x01_00` above it is platform
version 1.0 from `platform_version`. Every field there is something the device
reports about itself except one. The DDR type, bits 10:8 of the subtype cell,
is not published anywhere in sysfs, so the stamp sweeps it - eight
`<variant subtype>` pairs in one property, one per DDR type, of which the
strict matcher keeps the board's and discards the other seven. That costs 56
bytes.

The evidence says the value is 0. The overlay stock Android booted is "Parrot
QRD", `<0x1000b 0x0>`; the table also holds "Parrot QRD 4GB DDR",
`<0x1000b 0x600>`, identical in every scored field except the DDR type and
*earlier* in the table, so it would have won both an exact DDR match and a tie
on equal scores. It lost, which leaves one reading: the board's DDR type is 0.
The sweep stays because that is an inference about firmware rather than a
reading off the device, and because 56 bytes is cheaper than a button press.

Sony's ABL *is* this ABL, which was the one thing worth checking before
spending another flash cycle. `abl_b` was dumped from recovery and unpacked
with `scripts/abl-unpack.py`, and every string the code paths above would log
is in it verbatim - "Unable to find the Board Dtb", "Dtbo hdr magic mismatch",
"DTB offset is incorrect, kernel image does not have appended DTB", "Exact DTB
match found. DTBO search is not required", and the LK matcher's "Add DTB
entry", "ddr size does not match" and "subtype-id doesnot match". The same read
closed the last open field: `qcom,softsku-id` appears nowhere in the volume, so
the `SkuId` equality term is not in this build and cannot refuse our tree. What
remains unread is the DDR type, which the sweep covers by construction.

## Ordered plan

Each phase gates the next; the ordering is the whole point.

0. **A console on the real device.** Done, 2026-10-05, and not by the route
   this list expected. Ramoops turned out to be scrubbed by the bootloader and
   the debug UART is not broken out, so the channel became a log written
   straight to a flash partition plus — once modules load in a known order — a
   USB network gadget with a shell on it. See [07-devloop.md](07-devloop.md).
   What this buys phase 1 is the thing "Effort and risk" below says is the
   dominant risk: a hand-written `sm6450.dtsi` that does not boot can now say
   so in writing.

   Only half of that carries over to the mainline kernel, which is worth
   stating plainly because this list implies otherwise. The flash-partition
   log needs UFS, and mainline has no UFS driver for this SoC, so it cannot
   write one; the `PMBOOTLOG` a mainline round appears to find in `rddata` is
   the previous downstream boot's. What is left is the USB gadget, and that is
   in userspace. So for mainline, phase 0 is not done: a device tree that
   wedges before `/init` still cannot say so, and 05-status.md's "Every output
   channel but one is closed" works through why RAM, the UART and the
   bootloader's framebuffer are all unavailable here.
1. **SoC base.** `sm6450.dtsi` plus dt-bindings; `gcc-sm6450.c` and
   `pinctrl-sm6450.c` transformed from the parrot sources against the
   ravelin/sm4450 template; RPMh (RSC, regulators, `pm6450.dtsi`); SMEM, SMP2P,
   glink, PDC; GENI UART. Everything here is compile- and
   `dt_binding_check`-verifiable without hardware; only the boot is not.

   Written so far: both drivers, the RPMh clock and power-domain tables,
   `sm6450.dtsi` with the RSC, PDC, IPCC, SPMI and GENI UART in it, the three
   PMICs, the 38 regulators, the SMEM, SMP2P and AOSS glink nodes, and - from
   phase 2, taken early because it is what a shell needs - the apps SMMU, the
   SD card controller and USB at high speed. Phase 1 is done, and so is the
   part of phase 2 that does not wait on a PHY table.

   Target: **mainline writes a log to flash**, not "boots to a serial console".
   The usual phase-1 milestone assumes a UART, and whether this phone gives us
   one is untested. `qupv3_se3_2uart` at `0x98c000` is `status = "disabled"`
   downstream, but the stock `chosen` node sets
   `stdout-path = "/soc/qcom,qup_uart@98c000:115200n8"`, so the SoC's own view
   of the board does wire a console there; the open question is only whether
   the pads are reachable on an assembled handset. Until someone has looked,
   the first mainline kernel has to carry the same flash-log channel the
   downstream one does, and the first question it answers is how far it got,
   not what it printed.
2. **Storage and a shell.** SMMU, UFS plus phy, dwc3 plus the HS/SS phys. At
   this point there is a networked shell and the project has a real feedback
   loop.
3. **Board dts.** Done out of order, because a dtsi does not build without a
   board to include it: `sm6450-sony-xperia-columbia-pdx246.dts`, following
   pdx225's naming. It will grow as phases 1 and 2 land; right now it is a
   model string and a console.
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
