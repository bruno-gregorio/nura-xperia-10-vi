# Upstreaming

What this port carries that belongs in someone else's tree, what other people
have to land first, and the order to send it in. Nothing has been sent yet.
The landscape was checked on 2026-10-20 on lore.kernel.org, git.kernel.org,
patchwork, freedesktop GitLab and pmaports. Linux 7.3 was two days old then,
and the 7.4 merge window was open. Kernel patch numbers are positions in
[../kernel/patches/](../kernel/patches/) at kernel r51, whose `SERIES` lists
the subjects. Bring-up numbers are positions in
[../kernel/bringup/](../kernel/bringup/).

## The short version

- **Nobody else has posted SM6450** — lore and linux-next have no SM6450
  clocks, pinctrl, interconnect or device tree, and no A710 in drm/msm. This
  series would be the first.
- **The SoC's name comes first** — maintainers now want die codenames in
  compatibles and file names. They had SM7635 renamed to Milos, and asked
  for SM7435, which is also "parrot", to be called "netrani". Whether SM6450
  is the same die is reasoned, not confirmed. Every `qcom,sm6450-*`
  compatible, every file name and the board's file name depend on the answer.
- **The target is 7.5** — the 7.4 merge window opened on 2026-10-19, and
  7.4-rc1 is due around 2026-11-01, perhaps a week later. A new SoC posted
  now lands in 7.5 at the earliest.
- **Three postings by other people have to land first** — Marijn Suijten's
  SOFEF01 panel driver, Pengyu Luo's Hi-846 series and Frederic Laing's
  libcamera quad-Bayer patch. Everything else in
  [../kernel/backports/](../kernel/backports/) is merged by 7.3.
- **Three of our pieces have been overtaken** — the SMP2P sleepstate binding,
  the Rust IRQ KCFI fix and the Rust GPIO consumer each have a posting by
  someone else. Test theirs and drop ours.
- **CAMSS changed shape under us** — from 7.4, a new SoC describes its CSI2
  PHYs as separate generic PHY nodes. The CAMSS patches need reworking before
  they can be posted.
- **Most of userland can go now** — the userland patches that are generic
  can go now. The ones that use a kernel interface by name wait for that
  interface.

## Before anything is sent

These apply to every submission, in every project.

- **Settle the SoC name** — ask Bjorn Andersson or Konrad Dybcio whether
  SM6450 takes a die codename, and which one, before posting any binding.
  The Fillmore (SM7450) GCC posting of 2026-03-08 used a codename.
- **Rebase onto the target tree** — the series is written on v6.18.55, five
  releases behind 7.3. Expect conflicts in the shared tables it adds rows
  to: the drm/msm catalog, `camss.c`, `clk-rpmh.c`, `rpmhpd.c`,
  `qcom-rpmh-regulator.c` and the IPA data (reasoned). Base each series on
  7.4-rc1, or on linux-next until rc1 is tagged.
- **Disclose tool use the way each project asks** — `Co-Authored-By:` is
  not a kernel tag, and checkpatch flags it on 0098 to 0106 and on most of
  the bring-up layer.
  - 7.3's `Documentation/process/coding-assistants.rst` asks for
    `Assisted-by: LLM`.
  - A docs change applied on 2026-10-14, due in 7.4, removes that tag. It
    moves disclosure to the cover letter, as `generated-content.rst`
    describes: which tools, a summary of the prompts, which parts, and how
    the result was tested. This series lands in 7.5, so drop the trailer
    and disclose in the cover letter.
  - An assistant never adds a Signed-off-by.
  - pmaports' merge request template points at Nura's AI policy, so read it
    before the first merge request. Check libcamera's, freedesktop's,
    Qt's and KDE's too.
- **One identity** — since the history rewrite of 2026-10-20, every
  commit and patch here uses `accounts@bruno.pw`. The name still appears
  both as "Gregório", in patches and commits, and as "Gregorio", in the
  APKBUILDs' maintainer lines. Use one spelling per project.
- **Sign off everything** — these have no Signed-off-by:
  - libcamera 0019 to 0026;
  - libfprint 0002;
  - qsee-supplicant 0001;
  - the three pmbootstrap patches, which are bare diffs.
- **Say where facts came from** — vendor GPL sources are fine to cite, and
  the kernel commit messages already cite them. What was recovered from
  proprietary binaries needs its method stated, and some upstreams will
  refuse it:
  - libcamera 0023's exposure-index formula, taken from the stock AEC;
  - the Chromatix shapes behind libcamera 0017 and 0023;
  - the vendor agent's 644-byte records in libfprint's egisqsee;
  - sony-modem-qmi's tables;
  - the data in pdx246-camera-calibration.
- **Fold the fixups** — the WL2868C driver is new, so its ET5907 support
  (0079, 0080) folds into 0073 and 0074. Fold 0081 into 0075 and 0097
  into 0096, and regroup the board's later increments by the wave they
  ship in.
- **Split the SoC tree** — 0049 adds 2967 lines at once: display, GPU,
  UFS, remote processors and WLAN on top of the base. Each part's bindings
  go through a different tree, so one patch would wait for all of them.
  Post a base `.dtsi` first, then one patch per wave below.
- **Clear the checks on the new base** — `checkpatch --strict` on r51 finds
  no errors in the series.
  - What it does find:
    - 0070 has no commit body.
    - 0049 has one unwrapped log line, and 0061 has six lines over 100
      columns.
    - 0063 wants `min_t()`, and 0080 has unused macro arguments.
    - The new Kconfig entries in 0013, 0037, 0053, 0069 and 0074 have
      one-line help texts.
    - The drivers that are not Qualcomm's need MAINTAINERS entries:
      WL2868C, IMX582 and AW88263.
  - After that, run `dt_binding_check`, `dtbs_check`, a `W=1` build and,
    from a 7.3 or later tree, `scripts/dtc/dt-check-style`, which 7.3's
    `maintainer-soc.rst` now asks for. Send with `b4`.
  - The container's checkpatch must run under its own Perl, because the
    shared `$HOME` leaks Homebrew's:

    ```sh
    distrobox enter pmport -- bash -c 'cd out/linux &&
        env -i PATH=/usr/bin:/bin /usr/bin/perl ./scripts/checkpatch.pl \
            --strict --terse ../../kernel/patches/*.patch'
    ```

## What others have to land first

What the port takes from postings that are not ours, as they stood on
2026-10-20.

- **Already merged, so the backports drop on rebase** — all of these are in
  by 7.3:
  - IPA's IMEM slice and IPA v5.2 (7.1);
  - the Milos IPA node (7.3);
  - the MI2S clock control 0059 needs (7.3);
  - `cx_misc_mmio` without LLCC, without which the A710's GMU faults on
    resume (7.2);
  - the FT3518 (7.0) and the FT3519 binding (7.1), which falls back to the
    FT3518;
  - the SOFEF01-M binding (7.2).
- **The SOFEF01 panel driver, Marijn Suijten** — v2 of 2025-12-22 was
  reviewed with nits and has no v3. The board only needs the binding to
  pass `dtbs_check`, but the display needs the driver. Our 0001
  (`vci-supply`) and bring-up 0003 (the 10 VI's FLM setting) are changes to
  his panel, so they go to him.
- **The Hi-846 fixes, Pengyu Luo** — v6 of 2026-08-30. Sakari Ailus asked
  for unique link frequencies and a PLL calculator, and there is no v7.
  0090 builds on it. Sebastian Krzyszkowiak's power-on sequence patch is
  pending too.
- **Quad-Bayer CFA in libcamera, Frederic Laing** — v1 of 2026-08-25, still
  "new" in patchwork. Our libcamera 0010, 0017, 0019 to 0021 and 0024 sit
  on its shader code.
- **The A710 firmware** — linux-firmware has `gmu_gen70000.bin` but no
  `a710_sqe.fw`. Only Qualcomm can submit it, so the A710 cover letter has
  to say that the firmware is not distributed.

## Who else works on the same things

The people to talk to before posting, and what each overlap means for ours.

- **Marijn Suijten, pmaports** — his draft
  [!9445](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/merge_requests/9445)
  adds ten Sony devices on one shared kernel, and lists the 10 VI among
  those he means to add later. Talk to him before the pmaports device
  package, and about the panel and the board's DTS.
- **Richard Acayan, SMP2P sleepstate** — his one-line binding was acked on
  2026-09-27, and v2 was posted on 2026-10-03. It covers our 0052. Konrad
  says a bare `sleepstate` node is enough, but round 77 needed the entry
  for the ADSP to publish `remote_proc_state`. Whether 0053's driver is
  still needed, setting the bit and clearing it across suspend, is a device
  question: run the bare node and see whether the sensor still appears.
- **Sami Tolvanen, Rust IRQ KCFI** — "rust: irq: declare cfi_encoding for
  irqreturn", posted on 2026-10-19, with Alice Ryhl's Reviewed-by. It
  replaces bring-up 0004. Test it and reply with a Tested-by.
- **Kohei Ito, Rust GPIO consumer** — v1 of 2026-09-06, under review. It
  overlaps bring-up 0006. Nobody has posted a Rust pinctrl consumer. 0007
  has no in-tree user, so it would not be taken alone (reasoned).
- **Bryan O'Donoghue, CAMSS** — the generic CSI2 PHY driver and CAMSS's
  PHY API are in linux-next for 7.4, and he asks new SoCs to use them.
  `qcom,glymur-camss.yaml` is the template: no CSIPHY registers or clocks in
  the CAMSS node.
- **j4niwzis, IMX582 in libcamera** — patchwork series 6099 (2026-08-02)
  adds IMX582 sensor properties and helpers, and has changes requested. It
  overlaps our libcamera 0007. Combine the two rather than compete.
- **Pavel Machek and Vasiliy Doylov, focus** — "software_isp: Add focus
  control" (2026-02-26) is still "new", and our 0009 follows it. Separate
  autofocus work lives on gitlab.com/tui/libcamera, branch
  `millicam_af_6`. Read both before posting 0009 to 0011.
- **Luca Weiss, IMX582** — he tested SM6350 CAMSS with a work-in-progress
  IMX582 driver he has not posted. Tell him about ours.
- **Val Packett and Vladyslav Tymoshchuk, Awinic** — both are working on
  the AW88261 driver that our AW88263 driver follows. Cc them.
- **Dawid Wróbel, QSEECOM** — the TEE driver in bring-up 0005, libfprint
  0001 and qsee-supplicant are his. Our ELF64 trusted-application loading
  and qsee-supplicant's listener 11 go to him.

## The kernel, in order

Drivers and bindings go to their own subsystem trees, so each wave's driver
patches can be reviewed in parallel. The device tree is what sets the
order. A DTS patch is applied once every compatible and header it uses is
in linux-next, or `dtbs_check` flags it (reasoned from practice: 6.18's
`maintainer-soc-clean-dts.rst` does not list Qualcomm). So each wave's
drivers go out first and its DTS follows. Within a wave, bindings come
before the drivers that use them.

0. **Coordinate, during the 7.4 merge window** — settle the SoC's name.
   Talk to Marijn. Reply with test results on Richard's, Sami's and Kohei's
   threads. Do the rebase and the checks above. Most maintainers do not
   review new work in the window, and net-next is closed.
1. **Fixes that need no SoC** — these can go now, because fixes are taken
   during the rc phase. All three are verified on the device.
   - 0094 and 0095, `leds-qcom-flash` (Lee Jones), with their `Fixes:`
     tags. Cc stable.
   - 0098, `edt-ft5x06` dropping contacts that vanish from a frame (Dmitry
     Torokhov).
2. **Drivers for parts, not for the SoC** — each binds by a compatible of
   its own and can be reviewed without the SoC.
   - AK7374 (0091, 0092), media. It moves the lens; nobody has seen it
     focus a lit scene.
   - AW88263 (0062, 0063), ASoC. Sound works; it runs 6 dB under stock's
     profiles because nothing protects the speakers.
   - WL2868C with the ET5907 folded in (0073, 0074, 0079, 0080),
     regulator. This unit carries the ET5907: nothing answered at the
     WL2868C's address, so that path has never run on hardware. The cover
     letter has to say so.
   - IMX582 (0076, 0077), media. It streams in its binned modes.
   - The double tap to wake (0099) as an RFC to the input list, first. It
     detects the gesture in the kernel and sends `KEY_POWER` from a second
     input device, which is a design question for Dmitry before it is a
     patch.
3. **SoC foundations** — GCC first (0002, 0003), because the interconnect,
   display clock, MDSS and CAMSS binding examples include its header. Then,
   in parallel:
   - TLMM (0006, 0007);
   - the RPMh clocks (0008, 0009) and power domains (0010, 0011);
   - the interconnect (0012, 0013);
   - PM6450 and its regulators (0016 to 0018);
   - pd-mapper (0034);
   - the one-line compatibles the base tree uses (0014, 0015, 0019 to 0023,
     0025, 0026).

   Expect to be asked whether GCC is another SoC's with a few changes, as
   Fillmore's was.
4. **The base tree and the board** — 0024, the base part of 0049, 0050,
   and the base part of 0051. The board's base part covers the UART, the
   PMICs, the regulators, the keys, the SD card, USB at high speed, the
   touchscreen and Bluetooth. This wave waits for wave 3's bindings.
5. **Storage** — the UFS PHY (0027, 0028, through Vinod Koul), the Inline
   Crypto Engine (0029) and the UFS host (0030), with their nodes.
   Verified: sony-modem-qmi reads the TA partition through it.
6. **Remote processors, WLAN, charger and modem** — these patches:
   - the PAS bindings (0031 to 0033) and pmic-glink (0035);
   - the WPSS booted at probe (0055);
   - the sleepstate entry, on Richard's binding;
   - the rmtfs buffer (0101);
   - IPA (0102 to 0106), with the nodes.

   0055 may be answered with "give ath10k a `qcom,rproc` phandle instead"
   (reasoned). The modem registers and receives SMS. The data path is
   untested, because the network refuses this SIM data, and the IPA cover
   letter has to say so.
7. **Display and GPU** — these patches, with the nodes and the board's
   panel:
   - the display clocks (0004, 0005) and the GPU clocks (0036, 0037);
   - the display bindings (0038 to 0041);
   - UBWC (0042);
   - DSI, MDSS and DPU (0043 to 0045);
   - the GPU's SMMU and GMU bindings (0046, 0047);
   - the A710 (0048).

   0042 goes through soc/qcom but 0044 and 0045 need it, so ask for an ack
   or a shared branch. Mesa's FD710 entry says highest bank bit 15 where
   0042 and 0048 program 14 for LPDDR4X. Check which one rendering uses
   before posting. This wave waits for the SOFEF01 driver and the
   firmware note above.
8. **Audio** — these patches, after the AW88263 from wave 2:
   - the LPI pin controller (0056), the macros (0057) and the card (0058);
   - the machine driver (0059);
   - the QUP I2C nodes (0060) and the audio nodes (0061);
   - GPI DMA (0065, 0066);
   - the board (0064, 0067).

   The headset has never been plugged in.
9. **Camera** — the camera clocks (0068 to 0070) and the CCIs (0071, 0072)
   as they are. CAMSS is redone on the 7.4 PHY API:
   - the binding (0082) on Glymur's template;
   - the CSIPHY lane table (0085) moved into `phy-qcom-mipi-csi2` with a
     binding of its own;
   - 0083, 0084, 0086 and 0087 on `CAMSS_CSIPHY_RES_PHY_API()`;
   - the nodes (0088).

   Then the board's cameras, lens and flash (0075, 0078, 0081, 0089, 0093,
   0096, 0097). The Hi-846 pixel rate (0090) goes after Pengyu Luo's series.
10. **Double tap to wake** — 0099 as the RFC leaves it, then 0100.

The USB3 work in [../kernel/wip/sm6450-usb3/](../kernel/wip/sm6450-usb3/) is
not on this list. This phone's port is USB 2.0, so here the combo PHY can
only probe, never carry traffic.

## The bring-up layer

What each bring-up patch would need before it could go upstream.

- **0001, the bootloader's ids** — never. The binding allows `qcom,msm-id`
  and `qcom,board-id` on older SoCs only, and the patch lasts as long as
  this bootloader does.
- **0002, the HS PHY after an attach** — no upstream form yet. One would
  hand the PHY back from the firmware's side, or know when BC1.2 detection
  is over instead of waiting for it.
- **0003, the FLM setting** — to Marijn, with 0001 of the series.
- **0004, Rust IRQ KCFI** — dropped once Sami Tolvanen's fix is merged.
- **0005, the QSEECOM TEE driver** — Dawid Wróbel's to upstream.
  `TEE_IMPL_ID_QSEECOM` takes 5, the next free id after `QTEE`, so it
  collides with whatever mainline adds next (reasoned).
- **0006 and 0007, the Rust consumers** — GPIO overlaps Kohei Ito's
  posting. Pinctrl has no user upstream.
- **0008, egisfp** — not for upstream. Linux only powers the sensor and
  reports its interrupt, and TrustZone owns its bus. Nobody knows yet what
  an upstream interface for that would look like.
- **0009, the Hi-846 stock programs** — split out the generic parts, the
  power order and the OTP through nvmem, once Pengyu Luo's series lands.
  Running the stock programs as firmware is unlikely to be taken.

## Userland, in order

Grouped by what each piece waits for. The survey behind it checked every
patch file under [../aports/](../aports/) and [../patches/](../patches/).

1. **Now, with no kernel gate**
   - pmbootstrap: 0003, which only unregisters its own binfmt handlers,
     first. Then 0001 and 0002, the rootless chroot, with the messages of
     commits `3a8bdc5` and `b6f5e87`.
   - qtsensors 0007, the iio-sensor-proxy accelerometer claim: to Qt Gerrit's
     `dev` branch first, which has the same check, then to Qt 5.
   - qsee-supplicant's listener 11, as a pull request to Dawid Wróbel.
   - libcamera 0012 (line duration) and 0008 (Hi-846 helper). Then 0025 and
     0026, the simple pipeline's aspect ratio and 3A state, once they have
     messages.
   - postmarketos-ui-lomiri: `GRID_UNIT_PX`, which fixes pmaports issue 2411,
     and the wallpaper. Move the iio-sensor-proxy dependency over from the
     device package into the same merge request.
   - Bug reports, with no patch:
     - qtmir's grid-unit rounding, which crashes Lomiri at 1080x2520;
     - KWin's missing `touchCancel`;
     - hexagonrpcd's unit, which has `Conflicts=suspend.target` and a
       `ConditionPathExists` race with udev;
     - crossdirect's `rustc` without `--target`.
2. **Now, after splitting or a conversation**
   - libcamera, soft IPA exposure: 0013, 0014, and the gain hunk split out
     of 0017.
   - libcamera, autofocus: 0009 to 0011 with 0015 folded in, after reading
     the two efforts above.
   - plasma-camera 0001, split into its six changes and rebased.
   - hexagonrpc 0001 (`sns_reg_version`), only once it is shown to be
     needed: round 75 suggests it is not. It overlaps upstream's write
     support pull requests 21 and 27.
3. **After the kernel names it**
   - libcamera 0007, the IMX582 helper, after the IMX582 driver is posted,
     combined with j4niwzis's series.
   - The UCM files and the AudioReach topology, to alsa-ucm-conf and
     linux-msm/audioreach-topology, after wave 8 is merged, because they
     use the card's control names.
   - libfprint's egisqsee, after the TEE driver and egisfp have an upstream
     shape. It hard-codes Android's `/data/vendor_de/0/fpdata`, shares one
     template group between all users, and increments its touch count
     twice inside glib's `MIN()`.
4. **After rework**
   - libcamera 0016 to 0024: messages, splits, and a rebase onto Laing's
     quad-Bayer patch or onto master. 0023 needs a design conversation.
   - pdx246-camera-calibration: it is device data in `main/`, and systemd
     only. Its tuning is Sony's, so since 2026-10-20 it stays out of git,
     and the package builds only from a phone's own decoded files.
   - sony-modem-qmi: a repository and a release of its own, in place of
     sources inside the aport.
   - postmarketos-ui-plasma-mobile-fingerprint: pmbootstrap offers every
     `main/postmarketos-ui-*` as a UI. The real fix is kscreenlocker's PAM
     file.
5. **Nothing of ours to send**
   - Mesa: the A710 entry is Hugo223's, merged on 2026-09-23, and 26.3.0 is
     the first release with it. Drop the fork when Alpine ships 26.3.
   - libfprint 0001 (Wróbel's) and Alpine's udev rules hack.
   - Alpine's patches in the mesa, qtsensors and hexagonrpcd forks.
   - pmaports' libcamera 0001 to 0006, the sensor files and `qcam.desktop`.

## pmaports, alongside

The device does not have to wait for the kernel to be merged. pmaports'
testing category accepts a patched kernel, as `linux-postmarketos-qcom-sm7635`
does for Milos, as long as it is built with LLVM, which ours is, and the
device boots. What it waits for is this port's own state. postmarketOS has
been called Nura since 2026-09-27, and pmaports is still at
gitlab.postmarketos.org.

- **A flashing flow that cannot brick** — this blocks the merge request.
  - `deviceinfo_flash_fastboot_partition_vbmeta="vbmeta"` lets
    `pmbootstrap flasher flash_vbmeta` write a vbmeta with rollback index 0,
    and anti-rollback refuses that whatever its flags are (see
    [04-flashing.md](04-flashing.md)).
  - Mainline also needs the zeroed dtbo from `scripts/no-dtbo.py`, which
    nothing in pmOS's flow produces.
  - deviceinfo's comment still calls the overlay failure harmless.
  - `rootfs="userdata"` is never written.
  - Nothing marks the slot successful, so every boot uses up one of the
    bootloader's seven attempts.
- **The kernel from a forge tree** — every other Qualcomm kernel in
  pmaports sources a tag from a published tree. Ours carries about 900 KB of
  generated patches. Publish `pdx246` from `out/linux`.
- **Firmware with a public source** — the blobs come off the phone and are
  not redistributable. `hexagonfs.tar` holds this unit's factory sensor
  calibration.
- **A clean kernel command line** — the mainline command line still has
  `clk_ignore_unused`, `pd_ignore_unused`, `regulator_ignore_unused`,
  `loglevel=7` and `earlycon`.
- **No forks underneath** — the device depends on the hexagonrpcd fork,
  and through its features on the libfprint and Mesa forks.
- **The topology package's architecture** — it uses
  `pmb:cross-native2`, which pmaports CI rejects unless exempted, as
  `firmware-ayn-audioreach-topology` is.

## How the pieces depend on each other

The chains that cross from the kernel into userland. Each arrow means the
right side cannot be merged, or cannot be tested, before the left side is
posted.

```
IMX582 driver (0076-0077) ──────────▶ libcamera 0007 ──▶ pdx246-camera-calibration
any VCM, e.g. AK7374 (0091-0092) ───▶ libcamera autofocus (0009-0011, 0015)
camera clocks, CCI, CAMSS ──────────▶ every camera, every libcamera patch on device
A710 (0046-0048) + a710_sqe.fw ─────▶ Mesa 26.3 (merged), GL on the device
sound card (0056-0064) ─────────────▶ alsa-ucm-conf, audioreach-topology
remote processors + IPA (0102-0106) ▶ sony-modem-qmi, mobile data
edt-ft5x06 double tap (0099) ───────▶ the device package's wake-gesture files
QSEECOM TEE + egisfp (bring-up) ────▶ qsee-supplicant listener 11 ──▶ libfprint egisqsee
```

## Sources

- Linux 7.3 release and the 7.4 merge window:
  <https://lore.kernel.org/lkml/CAHk-=wgwnBm2zDdRM7u016NVHkv9KqbZW7AZ=8wZrqGyv_V+5A@mail.gmail.com/>
- Die codenames, "netrani" for SM7435:
  <https://lore.kernel.org/all/c379aad4-96f6-4134-8b90-0f1eec8001a3@oss.qualcomm.com/>
- Fillmore clocks, the codename precedent:
  <https://lore.kernel.org/linux-arm-msm/20260308-fillmore-clks-v1-0-976d9a6bebe7@mainlining.org/>
- Removing `Assisted-by`, applied 2026-10-14:
  <https://lore.kernel.org/all/20261013121501.3738437-1-sashal@kernel.org/>
- Richard Acayan's SMP2P sleepstate binding, v2:
  <https://lore.kernel.org/all/20261003175659.23536-2-mailingradian@gmail.com/>
- Konrad on the bare sleepstate node:
  <https://lore.kernel.org/all/9d5d45aa-2678-4453-b18f-16efd4316732@oss.qualcomm.com/>
- Pengyu Luo's Hi-846 series, v6:
  <https://lore.kernel.org/linux-media/20260830160025.211384-1-mitltlatltl@gmail.com/>
- The MI2S clock control, applied for 7.3:
  <https://lore.kernel.org/all/178508747839.10630.10650914663923353739.b4-ty@b4/>
- Mesa's A710 and A720 entries:
  <https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/44466>
- pmaports' device categories:
  <https://docs.nura.eco/pmaports/main/packaging/device-categorization.html>
