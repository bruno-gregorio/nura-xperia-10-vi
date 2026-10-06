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

Nineteen patches against v6.18.55, exported to
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
- **`arm64: dts: qcom: pmr735a: Allow the SID to be overridden`** — this
  phone puts PMR735A at SID 6, not the 4 the shared dtsi hardcodes, so it
  gets the same `PMR735A_SID` escape hatch `pmk8350.dtsi` already has.

The other three PMICs needed no new code at all: `pm6150l.dtsi` matches our
SIDs 4 and 5 as shipped, and `pmk8350.dtsi` was already parameterised.

Then the device trees, and the binding lines they need to validate:

- **`dt-bindings: qcom: Add SM6450 compatibles for PDC, IPCC, WDT and EPSS`** —
  enum additions in four existing bindings.
- **`dt-bindings: arm: qcom: Document SM6450 and Sony Xperia 10 VI`** — the
  `sony,pdx246` / `qcom,sm6450` board compatible.
- **`arm64: dts: qcom: Add SM6450 SoC device tree`** — `sm6450.dtsi`, 1032
  lines: the eight CPUs with their caches, idle states and PMUs, the
  38-region reserved-memory map, GCC, TLMM, TCSR, the GENI UART, PDC, IPCC,
  the GIC, the watchdog, the arch timer, the RSC with rpmhcc/rpmhpd/bcm-voter
  under it, EPSS cpufreq, the SPMI arbiter with both its buses, the AOSS side channel
  and its sleep stats, and SMEM with the four SMP2P edges that ride on it.
- **`arm64: dts: qcom: Add Sony Xperia 10 VI`** — 351 lines: the four PMICs,
  all 45 RPMh regulators with the windows the board's own firmware uses, the
  power and volume keys, and the UART as `serial0`.

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

- **Every address exists.** All 59 unit addresses in our board DTB are
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
- **Every interrupt matches.** 11 of the 12 nodes the two trees agree on the
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
- **Its score.** Two of this phone's PMICs, PM6150L and PMR735A, already have
  upstream answers, which makes them a test set. The rule puts **16 of 16**
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
And the `pmr735a.dtsi` change is a no-op for everyone else: the DTBs of all
eleven boards that include that file are byte-identical before and after,
checked by md5 across a `git stash` of just that one file.

Everything compiles for arm64 at `W=1` with no warnings, the device trees
build with `CHECK_DTBS=y` clean, all thirteen touched bindings pass
`dt_binding_check`, and `checkpatch --strict` reports zero errors across the
nineteen patches. What it does report is shared with upstream's own files: 86
"blank line after struct" checks and five `PINGROUP` rows past 100 columns,
which `pinctrl-sm4450.c` and `pinctrl-milos.c` have too, and the "does
MAINTAINERS need updating" notice, which `get_maintainer.pl` shows is already
answered by the directory wildcards.

None of this is evidence the hardware works. It is evidence that the driver
says what the vendor driver says, which is a different and much weaker claim.

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
1. **SoC base.** `sm6450.dtsi` plus dt-bindings; `gcc-sm6450.c` and
   `pinctrl-sm6450.c` transformed from the parrot sources against the
   ravelin/sm4450 template; RPMh (RSC, regulators, `pm6450.dtsi`); SMEM, SMP2P,
   glink, PDC; GENI UART. Everything here is compile- and
   `dt_binding_check`-verifiable without hardware; only the boot is not.

   Written so far: both drivers, the RPMh clock and power-domain tables,
   `sm6450.dtsi` with the RSC, PDC, IPCC, SPMI and GENI UART in it, all four
   PMICs, all 45 regulators, and the SMEM, SMP2P and AOSS glink nodes.
   Phase 1 is done.

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
