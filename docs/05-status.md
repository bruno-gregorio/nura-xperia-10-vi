# Status

## Fingerprint enrollment and verification work, 2026-10-15

**The owner enrolled a finger from Plasma's own fingerprint settings, and
fprintd then verified it (`verify-match`).** This was the whole stack on the
phone: libfprint 1.94.9-r106 with the `egisqsee` driver
(`aports/temp/libfprint`), `device-sony-pdx246` r20, kernel r48's
`/dev/egisfp0` and QSEECom TEE, and `qsee-supplicant` holding egisap64.
Unlocking from the lock screen has not been exercised: no PAM or screen
locker line shows in the journal.

- **Four driver faults, found on the phone:**
  - r102. `TEE_IOC_INVOKE` wants `buf_len` to be exactly the parameters
    in use. Every two-parameter send (the echo, Keymaster) failed with
    EINVAL.
  - r103. `0x8003` (set active group) returns status 4 on its own. It is
    accepted inside a verification workflow, as `bix_set_active_group`
    sends it: `0x20` → vbt → `0x8003` → `0x2F`.
  - r105. The enrollment trigger, property `0x01084004`, must be 3, the
    agent's default. The 0 in `flows.md` came from the emulator's zeroed
    context. With 0 the sensor never raised its interrupt for a touch.
  - r105. Finger waits also capture again after a quiet second.
- **The zero auth token is accepted:** enrollment start `0x10` carries the
  72-byte Android HAT as zeros. It returns status 0, and the store
  (`0x11` event 6) succeeds. `validate_authtoken` is therefore not enforced
  on this flow; `enroll.md` 1.3 had reasoned that it would be. **Verified**
  for start and store only.
- **The TA decides when enrollment is done:** its enrollment percentage
  (property `0x01074004`, u8) rises 5% per accepted sample. Sample 20
  returns FTX DONE. A redundant touch is rejected and does not count. The
  r105 round ended at 19 accepted samples, one short. For its last 200 s
  every capture came back empty. Whether the owner was still touching then
  is not known.
- **Where the template lives:** the TA writes through the supplicant's REE
  file listener, into
  `/var/lib/qsee-supplicant/data/vendor_de/0/fpdata/`: `file_table.bin`,
  `aid` and `User-0-SUID-…_0.template` (158714 bytes, TA-encrypted).
  fprintd keeps only a device-stored print reference (group 0, fid) under
  `/var/lib/fprint/user/egisqsee/egisap64/`.
- **The finger interrupt, corrected:** GPIO 111 reads low with its pull-up
  while the powered sensor waits. R47/R48's events were the pull-up's own
  edge on arming, not a touch. With trigger 3, all 40 finger images in
  both runs followed an interrupt wake-up; the one-second fallback caught
  none. Many interrupts come without a finger (395 empty captures after a
  wake-up in r105). **Reasoned:** the sensor's own detection pulses.
- **Known faults, not yet fixed:**
  - The driver counts each accepted touch twice below stage 19.
    `MIN (++touches, …)` is a macro that evaluates the increment twice, so
    Plasma's progress jumps by two. Progress should follow the TA's
    percentage instead.
  - fprintd announces 21 stages: the driver's 20, plus its own identify.
- **Untested:**
  - unlocking from the lock screen (fprintd-pam is installed, its use by
    the locker is unchecked);
  - the template surviving a reboot (the TA has to find it through the
    supplicant again);
  - deleting a print;
  - the power cost of the one-second fallback on a lock screen that waits
    for long.

Evidence: `out/fingerprint-libfprint/`. The `live-*.txt` files are the
rounds in order (open, enroll start, interrupt level, enroll).
`journal-enroll-r105.txt` and `journal-plasma-r106.txt` are fprintd's full
debug journals. The driver's git tree is `out/libfprint-egisqsee`.

## Fingerprint sensor initialisation works, 2026-10-14

**EC617 sensor initialisation (`0x8001`) now succeeds on postmarketOS, and
the TA stays responsive afterwards.** The blocker was not SPI, clocks or the
token: during `0x8001` the TA asks the normal world for the time through
**QSEE listener 11**, Qualcomm's REE time service. With no listener
registered, QSEE failed the request internally and killed the app (the old
SCM -2 / result -23). Stock recovery had the time listener through qseecomd
but used a synthetic token, so each earlier comparison was missing a
different ingredient. Enrollment and verification are still unfinished.

- **Recovery from stock Android:** the phone was found in fastboot on
  slot B. `fastboot --set-active=a` and a reboot returned it to
  postmarketOS (kernel r48); nothing was flashed. The three-hour reconnect
  watcher from the previous session had expired without seeing the phone.
- **Real Keymaster token works:** a non-privileged session on the
  already-loaded keymaster app answers `{0x205, 2}` with status 0 and a
  152-byte wrapped message at offset 12. Forwarding it as `0x6000` property
  `0x21040105` returns status 0. The key material is never printed or
  stored. Evidence: `out/fingerprint-protocol/live-authenticated-init.txt`.
- **Listener 11 found:** `out/fingerprint-protocol/listener-probe.c`
  registers the eight listener ids stock qseecomd offers through the
  existing `/dev/teepriv0` supplicant interface and logs every request.
  During `0x8001` the TA raised exactly one: listener 11, command `0x302`.
  Answering it with failure made TZ reject the answer (-22) and the app
  died as before. Evidence: `live-listener-init.txt` in the same directory.
  RPMB (0x2000), 0x9000 and 0xC000 refused registration with -22; nothing
  asked for them.
- **Time service answered, init passes:** `0x302` is
  `TIME_GET_UTC_SEC` in Qualcomm's BSD-licensed
  [minkipc time listener](https://github.com/qualcomm/minkipc/tree/e5e4e7c/listeners/libtimeservice);
  the reply is `{cmd, tv_sec, tv_nsec, ret}` in the same buffer. With that
  answered from `CLOCK_REALTIME`, `0x8001` returned status 0 in one step
  and a following echo returned 30 for operand 3. Evidence:
  `live-time-listener-init.txt`. No RPMB, secure-storage or template
  operation was requested by the TA or sent by us.
- **Packaged supplicant serves it:** `aports/main/qsee-supplicant` is Dawid
  Wróbel's [qsee-supplicant](https://github.com/wrobelda/qsee-supplicant)
  0.1.1, which speaks our kernel's TEE UAPI unchanged, plus a patch adding
  listener 11. Installed on the phone as `qsee-supplicant.service`, it
  registers listeners 10, 0x7000 and 11, and the probe's `0x8001` returns
  status 0 with no listener of its own. Evidence:
  `live-packaged-supplicant-init.txt`.
- **A held TA re-initialises:** with `qsee-app-loader@egisap64.service`
  holding the TA, a second load through `/dev/teepriv0` is refused by TZ
  (-22), so clients must attach through `/dev/tee1`. Attached that way, two
  back-to-back runs of the whole init sequence both succeed on the same
  loaded TA. Evidence: `live-held-ta-reinit.txt`. The device package now
  depends on the supplicant and its preset enables both services.

**Next:** the remaining Android init sequence, enrollment and verification,
decoded from the vendor agent, and a libfprint driver above them.

## Fingerprint focus, 2026-10-13

**The owner tested the cameras and accepts them for the first build. Camera
optimization is stopped at their request. Fingerprint enrollment and
verification remain unfinished.** The Rust kernel hardware driver and native
signed-app transport exist; a working fprintd adapter still depends on resolving
sensor initialization, not just wiring the UI to the device node.

- **Recovered stock SPI power notification:** original agent code produces
  command `0x8004` with property `0x20070103`. Offline execution and live
  diagnostics confirm successful SPI close/reopen responses. Including this
  notification does not fix `0x8001` initialization: the app still loses echo
  responsiveness until unload/reload. These are successful service-open tests,
  not evidence of successful sensor transfers.
- **Exact secure bus configuration:** `scripts/check-egis-spi-config.py`
  executes the dumped slot-B TZ property lookup with the dumped DAL registry.
  Device 8 resolves to QUP1 S2, `0xa88000`, `gcc_qupv3_wrap1_s2_clk`, the four
  wrapper bus clocks and pin functions `qup1_se2_l0` through `l3`. Only the
  boot-time registry selector is stubbed; no MMIO is mapped. This supersedes
  the earlier unsupported `0xa90000` hypothesis. Temporarily holding the
  neighboring I2C controller active does not fix initialization; its `auto`
  power policy was restored. This does not exclude every clock/ownership issue.
- **Firmware regression checks:** the sensor-init emulator now separately
  checks SPI-open failure and SPI-transfer failure. Both return normal errors.
  Sixteen combinations pass, covering the vendor's aliased request/response
  layout, both output-pointer fields, its marker byte and the recovered SPI
  power cycle. Synthetic correct ID bytes still reach a hardware-reset
  callback. These checks do not establish where the real device fails.
- **Diagnostics:** direct access to the secure SPI service (UID 16) through
  the normal client environment returns result 11; it is not an available
  alternative transport. The app requests log mask `0x1f`, but the registered
  32 KiB log buffer remains entirely zero. Its registration ABI matches the
  downstream implementation; the absence of logs remains unexplained.
- **Original Android success:** a temporary normal slot-B Android boot logs
  successful `0x6000` token-context setup, followed by successful `0x8001`
  sensor initialization in approximately 184 ms and hardware ID 617. This is
  direct evidence that the physical sensor works under the original stack.
  Returning to postmarketOS after the first Android round did not fix our
  initialization. Android shell permission denied the attempted firmware
  hash comparison; identical version strings do not prove identical files.
- **Corrected EC617 defaults:** the earlier emulator skipped the family
  selector and incorrectly used generic values `24/4000/4000/0`.
  `scripts/check-egis-vendor-init.py` now executes the actual family-7 branch
  and original serializer, verifying `48/800/500/50`. The canonical client
  and sensor emulator use these values. Corrected live requests still fail;
  this fixes a reconstruction error, not the initialization blocker.
- **Missing wrapped token exchange:** original-agent tests in recovery used
  a synthetic 32-byte key and failed. That substitution was invalid: Egis
  command `0x6000`, property `0x21040105`, calls
  `qsee_decapsulate_inter_app_message`, then requires sender `keymaster` and
  a 32-byte unwrapped key. The original client obtains the wrapped message
  with Keymaster request `{0x205, 2}`, using 64/1088-byte aligned transport
  buffers; its parser copies at response offset 12 and limits output to 256
  bytes. `scripts/check-egis-keymaster.py` executes that original constructor
  and parser against five synthetic success/error/bounds cases, all passing.
  The sensor emulator's `--token-context` cases also verify that the original
  TA accepts the expected synthetic decapsulation reply and rejects a failed
  decapsulation, incorrect sender, or incorrect unwrapped-key length.
  Sony's [published Keymaster fingerprint client](https://github.com/sonyxperiadev/vendor-sony-oss-fingerprint/blob/master/QSEEKeymasterTrustlet.cpp)
  independently uses the same command and fingerprint auth type.
  Native and original-agent probes using the real wrapped exchange are built,
  but **not yet run**. No real key material has been obtained or logged.
- **Offline continuation:** synthetic Keymaster decapsulation makes `0x6000`
  return success. With modeled SPI registers, the original TA progresses
  through reset, register programming and OTP reads; it subsequently fails
  against the deliberately incomplete sensor model. This does not establish
  a successful live transfer or identify the actual secure-app fault site.
- **Device connection lost:** during the second normal Android comparison,
  `adb root` reported restarting adbd, after which USB disappeared. ADB,
  fastboot and both known SSH addresses are unavailable. The automatic return
  to slot A could not execute; the last known boot is **stock Android slot B**,
  not a verified postmarketOS boot. Physical reconnection was requested.
  `out/fingerprint-protocol/resume-native.py` is running a bounded three-hour
  reconnect round: on recognized `pdx246` fastboot it selects existing slot A
  and reboots, then verifies postmarketOS/Xperia identity before running one
  native initialization probe. It never flashes an image. Its log is
  `resume-native.log`; create `stop-resume` in the same directory to cancel.
  Check actual process/log state before relying on this temporary round.
- **Next live gate:** test the real wrapped exchange and corrected sensor
  initialization, then establish capture before completing libfprint
  enrollment/verification and Plasma unlock. Echo, emulated success and
  GPIO/IRQ tests are not end-to-end fingerprint support.

Evidence: `out/fingerprint-protocol/live-power-{notify,reopen}.txt`,
`live-shared-bus-awake.txt`, `live-spi-service.txt`, and `live-final-health.txt`.
Additional evidence: `normal-android-early.txt`, `live-corrected-init.txt`,
`live-after-android.txt`, `agent-stock-key-context.txt`, and
`trace-authenticated-ta.log` under the same directory.
`egisfp-tee-0.1.0-r14.apk` builds successfully with corrected EC617 defaults
and the recovered power notification. It is **not installed**; the saved
postmarketOS system remains r13. No firmware image was flashed in this
follow-up; slot selection and normal/recovery boots were performed as above.

## Camera preview performance, 2026-10-13

**Plasma Camera 2.1.1-r103 and libcamera 99990.7.2-r124 are installed on
kernel r48.** The owner confirmed the preceding camera-quality improvements.
This follow-up changes preview scheduling and processing, retaining the
existing calibration and full-resolution photo output.

- **Measured bottleneck:** Plasma Camera requested 3256x2448 Hi846 previews
  and 3992x3000 IMX582 previews. GPU ISP time was approximately 135 ms/frame
  for both Hi846 modules and 56 ms for the main camera. The sensor register
  drivers were not the image-processing bottleneck. Evidence:
  `out/try-kernel/preview-baseline.txt` and `preview-full-baseline.txt`.
- **App changes:** the downstream `aports/temp/plasma-camera` package uses
  a 1276x960 preview on these sensors, preserving aspect ratio. Photos
  temporarily use the original full-resolution configuration. Completed
  requests are recycled immediately, replacing the 16 ms polling timer.
  Two preview buffers and a single pending Qt image bound queue growth;
  older completed previews are discarded. CPU access is bracketed with
  DMA-BUF synchronization, and Qt owns copied pixels before the camera can
  reuse its buffer. The installed upstream 2.1.1 app wrapped reused DMA memory
  directly, unlike the newer research checkout's copy fix.
- **ISP changes:** patch 0024 avoids nine redundant packed-RAW samples
  (18 texture reads) and unused range calculations when downscaling.
  At 1280x960, front processing measured 26.2 -> 23.7 ms and wide
  34.0 -> 26.5 ms. All 160 actual GLES comparisons preserve output within
  one 8-bit code value (`scripts/check-preview-shader.py`). Patch 0025
  prefers matching sensor aspect ratios before minimizing capture size:
  the main camera now retains its 4000x3000 sensor mode for 4:3 preview,
  instead of selecting and further cropping the 2000x1132 video mode.
  Patch 0026 retains IPA/AF/AWB state across output-size changes only when
  sensor information and control limits are identical; frame contexts are
  cleared, and real sensor-mode changes still configure the algorithms.
- **Actual UI measurements:** with r123/r103, fresh 18-second Plasma Camera
  sessions submitted 26.7 fps front, 17.0 fps wide, and 28.4 fps main to Qt.
  Median captured-buffer timestamp-to-Qt-sink age was 47.2, 41.2, and
  30.8 ms respectively; p95 was 73.8, 55.8, and 78.3 ms. This excludes
  exposure and compositor/scanout latency, and is not an optical latency
  measurement. R124 changes only same-mode reconfiguration; fresh-start
  preview code is unchanged. Logs: `out/try-kernel/preview-ui103-*.log`,
  summarized by `scripts/camera-preview-report.py`.
- **Low-light limit:** during the wide preview, hardware controls reported
  exposure 4551 lines, analogue-gain code 240 (16x), VBLANK 2109 and test
  pattern disabled. With 3800-pixel lines at 288 MHz, exposure is about
  60 ms and frame duration 60.1 ms, limiting capture to 16.6 fps. Forcing
  30 fps here would change the exposure/noise tradeoff. This is separate
  from the former 135 ms ISP bottleneck.
- **Validation and remaining cost:** strict package builds and the existing
  packed-Bayer/geometry checks pass. All three live color-bar checks pass
  on r123, whose shaders are unchanged in r124 (`colorbars123.txt`). The
  installed `plasma-camera-pipeline-test CAMERA_ID` exercises the actual
  Worker thread, retained-image ownership, and repeated full-resolution
  photo/preview transitions. R124/r103 passes 360 preview frames and two
  full-resolution photos per camera (3256x2448 Hi846, 3992x3000 IMX582),
  twelve retained-state transitions, and clean teardown with no error logs.
  Evidence: `out/try-kernel/preview-lc124-app103-{front,wide,main}.log`.
  Full-size photos require roughly 2–4 seconds
  with the current single-output software ISP and settling interval; the
  viewfinder holds its previous frame during this transition. RAW input
  still falls back to texture upload, and Qt still uploads an owned image;
  this is not an end-to-end zero-copy pipeline.
- **Image:** `out/images/plasma-r48-preview124/` contains the rebuilt
  Plasma rootfs, boot/vendor_boot images, installed-package manifest,
  checksums and passing `verify-bootimg.py` results. The image is saved for
  reproducibility; equivalent packages were installed live without reflashing
  the SD card or modifying stock partitions.
- **Rust assessment:** camera drivers remain C; the local kernel has no
  Rust V4L2/media or I2C driver abstractions. A camera-driver port would
  require substantial bindings/wrappers and would not remove the measured
  GPU, image-ownership or queuing costs. The existing fingerprint GPIO/IRQ
  driver is already Rust. No camera-driver language rewrite is claimed.

## Live bring-up follow-up, 2026-10-13

**Kernel r48, libcamera r121 and calibration r3 are installed on the SD rootfs.**
The phone is back in Plasma after the stock-recovery fingerprint comparison.
The owner subsequently confirmed substantial camera-quality improvement; see the preview follow-up above. Fingerprint
transport works, but enrollment and verification through fprintd do not yet
work. The GPU tester is installed and verified.

- **Sensor setup reviewed against dumps:** firmware-cameras r5 supplies
  separate stock Hi846 front/back initialization and mode programs, preserving
  register order and duplicates. Only six of the generic driver's 295
  microprogram values matched stock. Kernel r45 uses stock rail ordering,
  delays, Bayer phases, line/frame timing and crop coordinates. Front full
  mode's 346.5 MHz MIPI frequency follows the upstream PLL equation; CamX
  lists nominal 340 MHz. Actual CSI capture works, but frequency is not
  independently measured. Wide preview now uses the full array rather than
  the stock 2304-wide centre crop, preserving the wide field of view.
- **Per-unit OTP recovered:** the kernel executes the stock read sequence
  at 19.2 MHz, caches 5449 bytes per sensor in read-only root-only NVMEM,
  then resets and restores the normal 24 MHz camera clock. Both sensors
  read successfully. `scripts/hi846-otp.py` verifies group selection and
  WB/LSC checksums; both copies pass. The calibration contains four 17x13
  channel response grids, not direct gains. The sensor payload is interleaved R/Gr/Gb/B, decoded to planar grids.
  `pdx246-camera-calibration` 1-r3 applies per-unit correction to module
  Chromatix at boot, with a bounded wait for deferred sensor probe. The
  correction is golden response / OTP response, verified by executing all
  884 divisions in the original CamX code (`check-hi846-stock-calibration.py`).
  Both sensors pass service activation at boot on r47 and r48; subsequent 450-frame
  captures confirm loading the generated `/etc/libcamera/ipa/simple` tuning.
  White-balance checksums pass; per-unit WB adjustment is not yet applied.
  Private raw copies remain under ignored `out/try-kernel/`.
- **ISP geometry and filtering:** r117 fixes a viewport/texture mismatch
  that cropped previews asymmetrically and metered a different image area.
  Centred aspect cropping now matches statistics, and activates the
  downsampling antialias filter. R118 adds an edge-guided GPU chroma pass.
  Actual GLES tests preserve constant colours and hard edges while reducing
  synthetic chroma noise. Live 450-frame runs retain about 30 fps front and
  15 fps wide. Matching flat scene regions have approximately 60–70% lower
  chroma variation than r117, but exposure varies between runs, so this is
  not a controlled sensor-noise comparison. Wide low-light grain remains.
  Evidence: `out/try-kernel/scene{117,118}-{front,wide}.{ppm,log}`.
  All three r118 colour-bar tests pass. The off-channel tolerance now
  accommodates the calibrated wide CCM (160 rather than 128; target channels
  still exceed 192). Exact geometry/Bayer-phase checks remain separate.
- **Fingerprint native transport now works:** the new QSEECom TEE driver
  loads the phone's original signed ELF64 egisap64, translates its shared
  output pointer inside the kernel and unloads on owner close. Live echo,
  BIX framing, absent-buffer rejection and version retrieval all pass.
  R10 also answers the recovered platform-name callback and receives
  `Linux:Hello BIX !!!`. Evidence:
  `out/try-kernel/live-egis-native45.txt` and `live-egis-hello-r10.txt`.
  The older QTEE UID122 path still fails with MAXDATA; native transport
  avoids that route. No template, RPMB or provisioning operation was run.
- **Rust hardware driver:** exclusive open, power, reset with IRQ disabled,
  validation and close cleanup pass. R46's live `/dev/kmsg` observer identifies the IRQ failure as **KCFI**:
  the C dispatcher expects enum irqreturn's hash `0xd2f00be1`, while Rust's
  bindgen-erased unsigned return has `0xdf6c194b`. This supersedes the earlier
  disarm/PDC hypothesis. A minimal Clang/Rust reproduction confirms the
  mismatch. R47 gives the callbacks the explicit C enum encoding; its hash
  now matches Clang exactly. CFI remains enforced. R47 passes real rising-edge
  IRQ delivery, eventfd notification, disarm and final-close power cleanup.
  The counter is device-wide; repeated tests must compare against the opening
  value, not assume zero. R48 also passes ten consecutive power/reset/IRQ/disarm/close cycles.
  Evidence: `out/try-kernel/live-irq47-trace.txt` and `live-irq48-repeat.txt`.
- **Fingerprint initialization remains blocked:** executing the original
  vendor initializer/serializer recovered the six-property `0x8001` request;
  `scripts/check-egis-sensor-init.py` executes the original TA and verifies
  that this request reaches `qsee_spi_open(8)`. Live r12/r13 initialization
  returns SCM -2 with result -23. R13 confirms that the TA then fails echo
  until unload/reload, with or without the hello callback. This is evidence
  of lost TA responsiveness, not successful sensor initialization. In
  emulation, normal SPI-open and SPI-transfer errors return cleanly.
  R48's opt-in root-only QSEE app log registers successfully but stays empty.
  No secure-storage listener request was observed. Enrollment, verification
  and a usable libfprint adapter remain unfinished. Evidence:
  `out/try-kernel/live-egis-{nohello,hello}-r13.txt`, `live-scm12-trace.txt`.
  Original `tz_b` and `devcfg_b` were read into ignored files for offline
  analysis; no firmware partition was changed. The secure SPI configuration
  lists engines at 0x984000, 0xa88000 and 0xa8c000. The older claim that the
  fingerprint uses missing engine 0xa90000 was an inference and is not
  established by this data. No SPI/pinctrl/clock ownership changes were made.
- **Further camera review:** stock tuning reduces exposure targets, lens
  shading and CCM amplification in dark scenes. R118 used bright-scene
  calibration throughout. The recovered exposure-index arithmetic is
  `log10(sensitivity / first exposure knee) / log10(1.03)`; executing the
  original AEC instructions verifies four synthetic light levels
  (`scripts/check-hi846-exposure-index.py`). R121 imports all no-flash
  lighting bands and uses full-histogram linear luminance for their targets.
  It uses applied exposure as the index, not Sony's complete proprietary
  scene estimator. Actual OTP correction passes across every imported grid.
  Strict builds and 450-frame RGB captures pass for both Hi846 sensors;
  all three live color-bar checks also pass (`colorbars121.txt`). R119 was
  not deployed because review caught lighting selection reading frame controls
  too early. R120 exposed unsupported YAML aliases on-device; r121 disables
  aliases in both exporters and prevents duplicate OTP correction through
  shared endpoint lists. The constant-band endpoint correction check passes.
  R121 front imagery shows the ceiling; wide imagery shows a very close desk
  scene with substantial depth blur and residual shadow noise. This is not
  sufficient to certify general camera quality, especially focus/detail.
- **Stock fingerprint comparison:** A/B secure firmware differs (TZ A
  00427-1, B 00434-3), but both devcfg copies select the same SPI engines.
  The app code segments are identical; only signed metadata differs. Testing
  the original slot-A signed app via a temporary firmware path reproduces
  the initialization failure and restores the normal firmware path afterward.
  Stock recovery's original QSEECom and et617 drivers also pass app load,
  echo and version but fail the same sensor-initialization request. This
  means the failure is not established as a mainline GPIO/transport defect.
  The original vendor QSEECom library, including its image loader and
  bandwidth vote, reproduces the failure as well.
  No enrollment, template or storage-listener operation was requested.
  Evidence: `out/fingerprint-protocol/stock-{protocol,sensor}.txt` and
  `out/try-kernel/live-egis-slot-a-r13.txt`, and
  `out/fingerprint-protocol/vendor-stock-corrected2.txt`.
  Offline emulation now traces the first three register reads (FD/FF/FE).
  Synthetic ID bytes 06/11 pass identification and reach the expected reset
  callback; zero ID bytes return a normal status 16. This does not prove
  which of these stages the live app reaches before losing responsiveness.
  The four modes in `scripts/check-egis-sensor-init.py` all pass against
  the dumped app: open, SPI error, wrong ID, and synthetic reset callback.
- **Updated image saved:** `out/images/plasma-r48-camera121/` contains
  rootfs, boot and vendor_boot images, the APK database and SHA256SUMS.
  Kernel r48, libcamera r121, calibration r3, egisfp-tee 0.1.0-r13,
  Plasma fingerprint settings and GPU Test are included. This image has
  not been written over the live SD rootfs; equivalent packages were
  installed live. `scripts/verify-bootimg.py` passes; its full report is
  saved with the artifacts. Fingerprint enrollment/verification remain unfinished.
- **Unattended recovery:** enabling NVMEM_REBOOT_MODE fixes reboot to
  bootloader; r45 deployment reached fastboot after 12 seconds. Device r18
  stops NetworkManager removing usb0's static address and restores it
  before unudhcpd. The earlier r41 SSH loss was a network-management fault
  and must not be conflated with the later IRQ-triggered resets.
- **GPU Test:** the installed launcher runs bounded displayed/offscreen
  glmark2 Wayland tests and records KWin, GPU clocks and temperatures under
  `~/.local/state/pdx246-gpu-test`. Live renderer is freedreno FD710,
  OpenGL ES 3.2, Mesa 26.2.4; KWin also uses hardware rendering at 60 Hz.
  A later check finds no environment override forcing Qt software rendering;
  both CPU clusters use schedutil. Loaded LLVM libraries alone do not prove
  software rendering because Mesa shares dependencies across drivers.
  Scores 955/484 are benchmark scores, not UI FPS. Temperatures stayed
  below 38 C. UI sluggishness has not been measured or fixed. Evidence:
  `out/try-kernel/live-gpu-r41.txt`.
- **Modem:** bounded r44 test boots the modem and discovers NAS, Voice, UIM,
  WDS and IPA QMI services. ModemManager still reports no modem. The test
  uses read-only original NV with temporary RAM writes and stops the modem
  afterward; rmtfs remains masked. Evidence: `out/try-kernel/live-modem44.txt`.
- **Build/image evidence:** strict builds for kernel r45, firmware r5,
  device r18, libcamera r118 and egisfp-tee r10 pass. Subsequent strict builds
  through kernel r48, libcamera r121, calibration r3 and egisfp-tee r13 also
  pass. The refreshed image is `out/images/plasma-r48-camera121/`;
  `out/images/plasma-camera-r45/` is retained as an older artifact.
  Camera shader, packed statistics and crop tests pass offline. Full
  fingerprint enrollment/verification is not claimed.

## Hi846, modem and Rust driver follow-up, 2026-10-13

**Latest device state:** kernel r41 and libcamera r113 were installed and
booted on the SD rootfs. The fingerprint hardware check printed
`initial: (0, 0, 0)` and `powered: (1, 1, 0)`, then the phone stopped
answering during the reset/IRQ phase. SSH timed out, the USB network peer
stopped answering ARP, and adb/fastboot did not provide a recovery transport.
The queue finished with SSH exit 255. **This is a hardware-test failure,
not working fingerprint support.** SSH subsequently recovered without host
intervention, allowing inspection of r41, but disappeared again before the
next deployment. USB later enumerated as a network gadget; its USB ID's
`lsusb` description says fastboot, but fastboot did not answer. Neither SSH
nor the initramfs telnet shell answered on that network. Do not infer the
transport from the USB product description. Do not rerun the reset/IRQ test unchanged.
The precise cause is not isolated: reset sequencing and interrupt delivery
are both still suspect. The recovered kernel had no pstore record or obvious
panic in its current log; that does not explain the preceding interruption.
The test does not access SPI, templates or RPMB.

**Access verified before the failure:** the owner's new password works for
the existing `user` account. Credentials
were passed through environment overrides, not added to tracked files.

**Hi846 r113, built and hardware-tested:** the packed-Bayer shader now
reconstructs the shared low-bit byte for RAW10 and RAW12 and samples exact
texture centres. Previously it discarded the low bits before digital gain.
An optional 5x5 spatial/range filter acts on linear Bayer data before white
balance, colour correction and gamma. Only the two Hi846 tuning files enable
it; IMX582 has no added denoising. Both Hi846s completed 360-frame captures.
The front and wide final frame rates were about 12.3 and 15.3 fps in those
runs, including file output; this is not a controlled throughput benchmark.
The wide comparison is visibly less speckled, but its exposure also changed,
so the live before/after images alone do not measure the filter's benefit.

- Evidence: `out/try-kernel/hi846-{front,wide}-{baseline,r113}.{ppm,log}`.
  These show real scenes, not only sensor colour bars. Noise and limited
  low-light detail remain; no claim of stock-camera quality is justified.
- Fixed-exposure wide-camera RAW capture used 5,000 lines, 16x analogue gain,
  1x sensor digital gain, 1632x1224 GBRG10, stride 2048. The final two frames
  are `out/try-kernel/hi846-wide-last2.bin`. In a central patch the green
  mean was about 85.9 RAW10 codes, with temporal noise about 5.6 codes;
  the blue mean was 72.3 with noise about 4.3 codes. Black pedestal is 64.
- Processing identical captured RAW patches through the actual EGL shader,
  at fixed 4x gain, reduced temporal R-G/B-G noise from 5.89/5.15 output
  codes without filtering to 3.22/2.74 at sigma 16 RAW10 codes. This controls
  for illumination and automatic exposure, but is only one small scene patch.
- `scripts/check-packed-bayer.py` executes the actual GLSL via EGL inside
  pmport. RAW10/RAW12, all four Bayer phases, quad Bayer, padded strides,
  reflected image edges and low-bit ramps pass against a scalar reference.

**Hi846 r114, built but not hardware-validated:** inspection during r113 testing found the
filter was using a frame-context gain populated only later during statistics
processing. R114 uses the active AGC gain. Its CPU statistics also
reconstruct the low bits, normalizing channel sums only after accumulation;
this avoids biasing low-light white balance with per-pixel truncation.
The new `packed-bayer-stats` test exercises the actual statistics class and
shared-memory output for both bit depths, four phases and clipping rejection.
The strict package build completed, and the actual ARM64 statistics test
passed under QEMU (0.44 s). Shader tests also passed. Packages and logs are
preserved in `out/camera-r114/`. Installation and real-scene validation of
r114 remain pending while the phone is unreachable; r113 is the last
confirmed installed camera version. `out/try-kernel/finish-r114.py` is a
bounded SSH-recovery/deployment/check helper, with its result recorded in
`out/try-kernel/finish-r114.log`; it does not reboot or repeat the fingerprint
test. Credentials are environment-only, not in the helper. The bounded
recovery wait expired with no installation performed. No retry process is
left running. At the final check the USB network peer still failed ARP and
adb/fastboot listed no device; further live tests require transport recovery.

**Additional blob disassembly:** the stock `camera.qcom.so` debug symbols
resolve `ABF211Setting::CalculateHWSetting` at 0xde8458 and
`BPCABF41Setting::CalculateHWSetting` at 0xd96b28. Disassembly is preserved in
`out/dl-tuned/hi846-tfe-abf.dis` and `hi846-noise-settings.dis`. The TFE
function converts the first three region parameters to integers and stores
reciprocals scaled by 16x4096, then converts three 16-entry tables to 16-bit
hardware fields. The Hi846 TFE tuning enables this block, with initial
parameters 100/100/100 and tables descending from 8500 to 1000. These are
hardware filter parameters, **not** portable noise standard deviations.
Our filter is independently implemented and empirically tuned. Previously
decoded stock CCMs, illuminants and shading grids remain in use.

**Modem, verified first boot:** the firmware named in the DT was absent
from the image. The existing dump's MDT/segments assemble into a 124,089,464
byte `modem.mbn`; after installing it, remoteproc1 authenticated and booted
the modem in under a second. The bounded test observed `running`, then
stopped it cleanly. ModemManager still reported no modems. Evidence:
`out/try-kernel/live-modem-first-start.txt`. This proves firmware startup,
not SIM detection, registration, calls or mobile data.

- Firmware package r4 adds an optional modem subpackage with `modem.mbn`
  and the dumped `modem_pr` read-only remote files. It was built and installed
  on the phone. Device r16 built successfully and adds the firmware dependency
  for future images; it does not enable modem services automatically.
- Kernel r41 adds a dynamically reserved low-32-bit 0x280000-byte RMTFS
  buffer plus two guard pages, client 1 and MSS_MSA sharing. Stock uses a
  dynamic 0x280000-byte buffer. After SSH recovered, the live kernel verified
  reservation at 0xff97e000 and creation of `/dev/qcom_rmtfs_mem1` (the actual
  device name, not `/dev/rmtfs1`). Protocol operation is still unverified.
- QRTR, qmi-utils and rmtfs were installed on the SD rootfs. The standard
  `rmtfs.service` was masked **before** installation to prevent automatic
  writes to original modem storage. `scripts/modem-check.sh` prepares a
  bounded test using `rmtfs -P -r`: upstream opens partitions read-only
  and redirects writes into an in-memory copy. The next push failed before
  this script could run, so it has not accessed the modem partitions yet.
- Mobile data additionally needs IPA enablement. The dumped DT has
  `qcom,ipa-hw-ver = <0x17>`; Sony's cached kernel `msm_ipa.h` identifies
  enum value 23 as **IPA 5.2**. Our mainline IPA versions include 5.0 and
  5.5 but not 5.2, and SM6450 has no IPA node. Reusing a neighbouring
  SoC's descriptor without verifying registers/endpoints would be a guess.
- Further upstream research found Luca Weiss's [IPA 5.2 support,
  commit 4bf38bac1b2e](https://github.com/torvalds/linux/commit/4bf38bac1b2e2586a14529053cf56346db8a0032).
  It applies to our base and the complete IPA object compiles in an isolated
  pmport GCC build (`out/modem-research/ipa-5.2-compile.log`), with CFI/LTO
  disabled for that compile check. It is **not** part of the packaged r41
  kernel and has not run on the phone. Stable 6.18.55 already contains the
  associated generic-command, event-ring-index and EV_PER_EE fixes.
- Sony's module source at revision `5f823f90b852edf3d8c848a270173113ff523fe9`
  confirms matching AP command/LAN/WAN and modem endpoint/channel assignments,
  QSB limits and local-memory offsets. However, SM6450's dumped DT specifies
  IMEM 0x146a8000/0x2000 and SMEM size 0x9000, versus Milos's upstream 0xb000
  SMEM. A board-specific descriptor, DT resources and IPA firmware loading
  still need integration and hardware validation. Source excerpts and the
  upstream patch are in `out/modem-research/`; do not copy the Milos DT blindly.
  The dumped `ipa_fws.mdt`/segments also assemble successfully into a
  32,664-byte MBN there; it has not been authenticated or executed.

**Rust hardware driver findings:** r40 compiled and booted, but probe failed
with -524 because Qualcomm TLMM does not expose bias via GPIO set_config.
R41 replaces that operation with owned pinctrl handles and explicit IRQ-on
and IRQ-off states. R41 created `/dev/egisfp0`; malformed-ioctl and exclusive
open checks progressed to power-on, which completed with IRQ level high.
Reset, IRQ delivery, final-close cleanup and suspend are **not verified**.
The r41 package and boot artifacts are preserved in
`out/fingerprint-rust-r41/`; r40 artifacts and the r112 Plasma image remain
available for recovery. Authentication still needs the trusted-app protocol
and libfprint adapter described below.

## Rust fingerprint hardware driver, 2026-10-13

**Architecture chosen by the owner:** implement a custom kernel driver for
EC617 hardware enablement and keep standard fprintd/libfprint above it.
The kernel owns GPIO power/reset sequencing and interrupt delivery; qcomtee
continues providing the TrustZone transport. A userspace libfprint adapter
must still implement Sony's BIX enrollment/verification protocol and its
callbacks. Moving GPIO control into the kernel does not make fprintd
understand the trusted application's protocol automatically.

**Verified, Rust feasibility:** our Linux 6.18.55 source supports Rust on
ARM64. In the project-contained native chroot, Rust 1.99.0, bindgen 0.73.2
and Clang 23 passed `make ARCH=arm64 LLVM=1 rustavailable`. The stock Rust
platform and misc-device samples compiled with the pdx246 configuration,
including CFI. The new driver and its device tree also compiled. Logs:
`out/fingerprint-rust-feasibility.log` and
`out/fingerprint-rust-driver-build.log`. These are compile checks, not
hardware verification.

**Verified, complete kernel package built:**
`out/fingerprint-rust-r40/linux-postmarketos-qcom-sm6450-6.18.55-r40.apk`,
SHA256 `2328dc74705fcad9e977ff45d619775f127e464e10693c42766837f9ea5524ff`.
The strict pmbootstrap build completed successfully; its summary log is
`out/build-kernel-r40-rust.log`. The preserved package directory includes
the ARM64 Image, DTB, extracted configuration and verification results.
The Image contains the built-in driver's identifiers, and the packaged DTB
has the expected GPIO numbers, active-low reset and both-edge interrupt.
Comparing embedded configs with the previously booted r39 image found no
removed options: changes are Rust compiler capabilities, Rust enablement
and EGISFP. CFI and BTF remain enabled.

**Initial r40 build state (superseded by the follow-up above):** USB SSH answered and completed its
handshake, but the saved development login was rejected during this session.
No boot queue was started, and the running phone was not modified. Restore
authorized SSH access before deploying r40 and running the hardware check;
do not infer GPIO, IRQ, cleanup, suspend or fingerprint functionality from
the successful build. The earlier r112 Plasma image remains the known-booted
image and still contains kernel r39.

**Implemented:** `kernel/egisfp/` holds a Rust platform driver and small
owned GPIO/eventfd wrappers. The new code uses generated kernel C bindings;
there is no handwritten C implementation. `stage.py` applies it to an
isolated kernel tree, and `export.py` produces the kernel aport's
`bringup-egisfp-rust.patch`. Kernel package r40 enables Rust and EGISFP and
adds the corresponding native build dependencies. The normal SM6450
series and its existing backports remain the kernel base.

- `/dev/egisfp0` has a single controlling opener and a provisional fixed-size
  ioctl ABI in `egisfp.h`: status, power, reset, and an eventfd subscription.
- VDD/VCC enables are GPIO 96/106, reset is active-low GPIO 108, and the
  interrupt is GPIO 111. Delays come from Sony's 70.2.A.1 driver. Input bias
  is disabled while unpowered; unlike Sony's driver, it does not actively
  drive the IRQ pin low. This difference needs hardware validation.
- A threaded IRQ handler reports both edges through an eventfd that the
  adapter can wait on with poll/epoll. Events are electrical IRQ edges,
  **not** finger detection, match results or biometric data.
- Final close powers off. Unbind serializes against file operations, drains
  IRQ handlers, drops GPIO ownership, and makes old handles return ENODEV.
- The driver is built-in only. Linux 6.18's Rust miscdevice wrapper leaves
  `file_operations.owner` unset; allowing this driver to unload while files
  remain open would be unsafe. Built-in code avoids that lifetime problem.
- Suspend/wake integration and the vendor's selectable level/debounce IRQ
  modes are not implemented. The interface is for hardware bring-up, not
  yet a complete production fingerprint driver.
- SPI remains TrustZone-owned. This driver performs no TEE commands, stores
  no templates and accesses neither RPMB nor Android's secure storage.

**Prepared hardware check:** `kernel/egisfp/check-device.py` checks exclusive
ownership, rejected malformed requests, power/reset and final-close cleanup.
It waits at most two seconds for an interrupt notification, without claiming
that a notification is a finger event. Run only on pdx246 with no fingerprint
client active. This check has not yet run on hardware.

## Current camera work and fingerprint UI target, 2026-10-12 evening

**Verified:** the port is running on hardware, despite the historical
"nothing has been run" text in AGENTS.md. This session began with Phosh,
OpenRC, kernel 6.18.55-r39, device package r13 and libcamera r110 on the SD
rootfs. The phone answered USB SSH. Host adb/fastboot and the existing
bounded queue handle recovery; builds remain inside pmport and all
pmbootstrap state remains under `.pmb`.

**Camera regression investigation:** all three sensors completed 120-frame
and 1,000-frame libcamera captures before changes. WirePlumber still mapped
deleted libcamera/IPA files from an earlier upgrade. Restarting it let all
three PipeWire camera nodes deliver 60 frames through GStreamer to EOS.
That is evidence for a stale camera session, not proof that every reported
camera failure had the same cause. Snapshot's first launch used the wrong
session bus; the corrected launch was suspended with the screen idle, so
it did not establish a working interactive viewfinder.

**Verified, libcamera r111:** patch 0017 adds the following to the software
ISP, using the decoded vendor Chromatix data in `out/dl-tuned`:

- Per-module 17x13 RGB lens-shading grids, interpolated by colour
  temperature and mapped through the sensor's analogue crop. Four tables
  for IMX582 and three for each Hi846 module. These are the bright-scene,
  non-flash/non-HDR TFE calibration; Gr and Gb are averaged. This stage is
  implemented in the packed Bayer EGL shader used by this phone, not the
  CPU debayer or every EGL format. The GL float-texture path is required.
- Sensor-native illuminant reference ratios for colour-temperature
  estimation, which selects the existing vendor CCM and the new shading
  grid. Channel white balance still uses the simple grey-world algorithm;
  this is not a port of Sony's complete AWB algorithm.
- Gain-code progress when reciprocal gain quantization would otherwise
  discard an AGC increment. On IMX582 the old implementation repeatedly
  requested a gain that rounded back to the current code, preventing the
  transition to longer exposures and digital gain.

`scripts/camera-tuning.py` regenerates the calibration additions from the
decoded summaries and CSVs. Regeneration was checked against the built APK
checksums and is idempotent. No firmware executable or module serial is
included in these tuning files.

On the phone, the confirmed r111 packages loaded all three sets of shading
tables and completed 600-frame 1280x720 captures on each sensor. The main
camera reached 64x analogue gain, 66.660 ms exposure and 4x digital gain;
the Hi846 modules reached 16x analogue gain and 66.658 ms, with digital
gain limits 4x front / 8x wide. At those long exposures the output was about
15 fps. The samples are very dark and noisy, and do **not** establish good
colour, shading uniformity, autofocus or daylight image quality. Main AF
remained scanning in that dark scene. Evidence is in
`out/try-kernel/live-camera-calibrated.txt` and `calibrated-*.ppm`.

The earlier `live-camera-r111.txt` and `live-camera-long-r111.txt` names are
misleading: the first APK install timed out at an interactive confirmation,
and ssh.py intentionally continued to the diagnostic commands. Those runs
used r110. The later install used `apk --no-interactive`, and the calibrated
run asserts r111 in the same command as capture. Do not cite the earlier
filenames as r111 validation. Restart camera session services after live
library upgrades, or reboot, before testing applications.

**Verified, r112 white-balance correction:** a short, bounded torch test
made the stationary scene visible, but r111 produced a strong green cast.
The statistics averaged saturated highlights into the illuminant estimate;
once clipped, those samples no longer retain the channel ratios. Patch
0018 adds separate unclipped channel sums/counts for AWB, preserving the
full histogram for exposure. It excludes any sampled tile with a channel
at or above 250/255, and holds the estimate when the remaining channels
are within two 8-bit levels of black or fewer than 16 samples remain.

After building and installing r112 and restarting WirePlumber, both rear
cameras completed another 360-frame torch-lit capture. In the same
main-camera rectangle (x=70..350, y=70..250), mean RGB changed from
62.4/106.6/57.2 to 113.7/112.3/110.9. In the wide camera's same rectangle,
it changed from 18.8/49.3/29.4 to 60.5/72.8/68.2. This is a visible reduction
in the green cast, not a colour-chart measurement. Exposure also changed;
do not interpret these numbers as a controlled radiometric calibration.
Evidence: `live-camera-r112.txt`, `torch-r112-*.ppm`, and the preceding
`live-torch-capture.txt` / `torch-*.ppm` under `out/try-kernel`.

**Verified, sensor test patterns:** all three cameras delivered the expected
white/yellow/cyan/green/magenta/red/blue/black bars at 1280x720. The first
attempt set the pattern before libcamera initialized the sensor, which
reset it to disabled; that run captured the dark scene instead. The
working diagnostic sets the pattern after capture starts and restores
normal mode on exit. See `camera-pattern-capture.sh`,
`live-pattern-capture.txt`, and `bars-*.ppm` under `out/try-kernel`. These
prove the CSI/Bayer/RGB path, not lens shading, focus or scene colour.

**Verified, Plasma Camera:** with r112 it configured a 3992x3000 RGB
viewfinder from IMX582's 4000x3000 sensor mode, allocated four buffers,
rendered on FD710, and reported `setReadyForCapture true`. It ran until the
diagnostic's deliberate 18-second timeout. The log is
`out/try-kernel/live-plasma-camera-r112.txt`. This mode has substantially
more processing cost than the 1280x720 tests; do not claim a 30 fps full
resolution preview from those smaller captures.

**Remaining camera quality work:** the samples are a very close,
high-contrast scene illuminated by the phone's torch. They still contain
clipped highlights and noise, especially on the wide camera, and the main
camera remained scanning in this scene. Daylight colour, useful-distance
autofocus, shading uniformity, motion and noise reduction remain to be
validated/improved. Torch brightness was read back as zero after each
bounded test; flash integration in camera applications is still separate.

**Fingerprint target: Plasma Mobile plus fprintd.** The official
[Plasma lock-screen source](https://invent.kde.org/plasma/plasma-mobile/-/blob/82a730ee4df2b9def5548f3aed910200dabdabfa/shell/contents/lockscreen/LockScreenState.qml)
explicitly handles `ScreenLocker.Authenticator.Fingerprint`. KDE's
[Users settings](https://invent.kde.org/plasma/plasma-workspace/-/tree/97f8d44d6ec4d09e546e0d1f10c2c767589f0d26/kcms/users)
has mobile form factors and enrollment through the system D-Bus service
`net.reactivated.Fprint`. KScreenLocker uses a separate `kde-fingerprint`
PAM authenticator alongside its password authenticator.

**Built and filesystem-checked:** a clean Plasma Mobile/systemd rootfs,
including KDE Users settings, fprintd, pam_fprintd, the Egis TEE probe,
Plasma Camera and libcamera r111. The image is preserved at
`out/images/plasma-fingerprint/sony-pdx246.img` with SHA256SUMS and boot
artifacts; filesystem UUID remains `07b8a001-695c-40eb-bdf7-27e11e8adb9f`.
The previous Phosh configuration is
`out/ui-research/pmbootstrap-phosh.cfg`. An attempted chroot backup under
`.pmb/work/chroot_rootfs_sony-pdx246.phosh-backup` did not survive the
pmbootstrap cleanup. It is **not** an available rollback image. Keep image
artifacts and any future backups under `out/images`, outside the disposable
pmbootstrap chroot names. Phosh can be rebuilt from its saved configuration.

The new `postmarketos-ui-plasma-mobile-fingerprint` package supplies a
Fingerprint Settings launcher and fixes `kde-fingerprint`: the upstream
systemd-edge package referenced Fedora-specific `fingerprint-auth`,
`postlogin` and SELinux modules absent from this image. The replacement
uses pam_fprintd with Alpine's base-account/base-session; KDE's password
PAM stack remains available. Device package r15 adds the systemd equivalent
of the existing early ADSP sensors-domain attach, with the device's firmware
path. It disables the unused ADSP root-domain and SDSP daemons, and ALSA
state restore that would conflict with UCM routing.

**Not yet fingerprint support:** installing this UI does not make EC617
work. Existing hardware evidence proves egisap64 load/unload over qcomtee
UID 122. Command 0/1 transport success with an unchanged response does not
prove the BIX dispatcher or sensor worked. The next backend milestones are
the embedded-buffer fixup for the 0xE0 BIX envelope, a read-only version/
hello response, the documented power/reset/IRQ interface, and the required
storage/listener services. Sensor SPI remains TrustZone-owned. Do not send
0xE0 until the pointer fixup is proven; do not provision or write RPMB.

The acceptance target is a real device returned by fprintd's GetDevices,
successful KDE enrollment, persistence across reboot, fingerprint unlock
with password fallback, cancellation and failed-match handling. A
libfprint driver or a fprintd-compatible backend could provide that API;
the implementation is still missing. No templates or enrollments were
created by this session.

The shipped fprintd systemd sandbox currently permits USB, SPI, hidraw and
cros_fp devices, not `/dev/tee0` or GPIO chips. A future in-process Egis
driver would need deliberate device access; a separate backend/broker is
another option. The image does not loosen that sandbox for an unimplemented
driver. The installed KScreenLocker binary contains `kde-fingerprint`, and
the installed mobile lock-screen QML contains the fingerprint authenticator
path, so the UI capability is not inferred only from upstream HEAD.

**Verified, SD installation:** the unattended queue wrote the image into
the existing `mmcblk0p1`, preserving the partition table and log region.
The card reported the expected UUID, `fsck_rc=0` and `resize_rc=0`. The
queue is `out/try-kernel/plan-plasma-fingerprint.sh`; its install transcript
is `out/try-kernel/live-plasma-fingerprint-install.txt`.

**Final image, built and booted:**
`out/images/plasma-fingerprint-r112/sony-pdx246.img` includes libcamera and
IPA r112, device r15, the fingerprint UI integration package, and the
camera diagnostic tools. Its SHA256 is
`b6e8c7f535f5eac1c179b375a6bfc01cd2f21a5cb3c98a81bab5b65456600813`.
The directory also preserves boot images, the exact installed APK manifest,
pmbootstrap configuration and SHA256SUMS. The detached
`out/try-kernel/plan-plasma-fingerprint-r112.sh` queue installed it into SD
p1, checked/resized the filesystem successfully, booted it and finished at
23:03 local time. The phone remains running in STAYUP mode. This final
image supersedes the earlier r111 image described above.

The final boot has PID 1 systemd, KWin and plasmashell running, zero failed
system units, and active SSH, ADSP sensors-domain and iio-sensor-proxy
services. fprintd returns `ao 0` from GetDevices, as expected without an
Egis backend. PIN unlock was exercised successfully. Screenshots confirm
that Plasma's initial welcome screen and the Users settings render on the
phone; onboarding preferences have been left for the user. Spectacle works
after this cold boot with its package already installed; earlier attempts
after a live package install were rejected by KWin's screenshot permission
check. No KWin permission bypass was applied. Evidence is in
`out/try-kernel/live-stayup-plasma-fingerprint-r112.txt`,
`plasma-final-desktop.png` and `plasma-final-fingerprint.png`.

**Repeatable unattended camera check:** run
`scripts/camera-pattern-check.sh` as root on the phone with no camera app
capturing. It uses bounded captures, enables each sensor's colour bars
after streaming starts, checks all eight RGB bars, and restores normal
sensor mode. All three cameras passed on the final r112 image; see
`out/try-kernel/live-final-camera-pattern-check.txt`. The checker allows
colour-matrix/gamma processing: the wide camera's blue bar has red=104,
which failed the initial overly strict low-channel cutoff of 100. The
final check requires high channels above 192 and low channels below 128.
This validates channel order and complete output, not photographic colour
accuracy. Image-quality limitations listed above still apply.

Plasma Camera was also retested after the final cold boot. Its 3992x3000
viewfinder streamed frames and rendered the main sensor's test bars in the
actual GUI, captured in `out/try-kernel/plasma-final-camera-bars.png`.
The log is `live-final-plasma-camera-bars.txt`. The ordinary scene appeared
black in the unlit preview; bars distinguish that from a broken GUI image
path. Both GUI runs were deliberately bounded by timeout, which returned
241 through this command stack after terminating the application. They
did not exercise the app's JPEG shutter or video recording. Sensor test
patterns were restored to disabled and torch brightness was zero.

## Historical bring-up record

Last updated: 2026-10-12. **Our own kernel boots a full system: round 83
took the 6.18 mainline kernel through OpenRC into Lomiri, and on
2026-10-12 all three cameras streamed through libcamera (see "All three
cameras stream"), and the main camera focused (see "The main camera
focuses, at 30 fps").** The downstream
5.10 kernel booted pmOS to a login on 2026-10-05 (see "The port boots"). The
mainline kernel then ran in about eighty rounds that stopped in the
initramfs' debug shell, and brought up USB, the display, touch, the GPU, the
DSPs and the sensors there. Rounds 82 and 83 put the Lomiri image on the
card, ran Mesa on the GPU, and booted it. Every claim below carries its
confidence and the basis for it, because that is the only thing standing
between this port and a bricked phone.

## Confidence levels

- **Verified** — read directly out of published sources, or confirmed on
  hardware by the LineageOS pdx246 port.
- **Reasoned** — follows from how the boot flow works, but nothing has
  exercised it.
- **Guess** — plausible, unconfirmed, and the first thing to suspect.

## Device facts

- **Codename `pdx246`, SoC SM6450, platform `parrot`** — Verified.
  `BoardConfig.mk`, `sonyxperiadev/device-sony-pdx246`.
- **Display 1080x2520** — Verified. Sony specs.
- **Device runs Qualcomm's Parrot QRD reference device tree** — Verified. The
  LineageOS port diffed built DTBs against the stock blobs and booted it.
- **Base `parrot.dtb` in `vendor_boot`, `parrot-qrd` overlay in `dtbo`** —
  Verified. Qualcomm boot flow plus the LineageOS port's notes.
- **`parrot-qrd-overlay.dtbo-base` lists `parrot.dtb` first** — Verified.
  Vendor `dts/vendor/qcom/Makefile:143`.
- **`qcom,msm-id = <0x219 0x10000 0x265 0x10000>`, `board-id = <0 0>`** —
  Verified. Decompiled from our own `parrot.dtb`; this is what the bootloader
  matches `dtbo` against.
- **Boot header v4, pagesize 4096, kernel base 0** — Verified.
  `BoardConfig.mk`.
- **AVB rollback index `1782864000` enforced in hardware** — Verified. The
  LineageOS port hit the red state and documented it.
- **First-stage module list and order** — Verified.
  `device/sony/pdx246/modules.load`, stock's own order.
- **Debug UART at `0x98c000`, `qcom,msm-geni-console`, `status = "ok"`** —
  Verified. Decompiled from our own `parrot.dtb`.
- **`chosen/bootargs` already asks for `console=ttyMSM0,115200n8`** — Verified.
  Same DTB; `stdout-path` points at the same node.
- **ramoops at `0xffd00000`, 768K (256K console, 256K pmsg)** — Verified.
  `ramoops_region@ffd00000`, compatible `"ramoops"`, no `no-map`.
- **Wi-Fi/BT part is WCN3990** — Verified. Our overlay chain is
  `parrot-qrd-overlay.dts` -> `parrot-wcn3990.dtsi`; `wcn6750` appears only in
  the `parrot-qrd-wcn6750*` board files, which stock does not use. Means
  ath10k/SNOC plus `hci_qca`, both mature upstream.
- **PMIC pair is `pm6450` (main) + `pm7250b`** — Verified.
  `parrot-qrd-overlay.dts` includes `parrot-qrd-pm7250b.dtsi`, and `pm6450` is
  referenced in the QRD tree.
- **Touchscreen comes from `blair-touch.dtsi`** — Verified. An `#include` in
  `parrot-qrd.dts`; shared with Qualcomm's `blair` platform, so not
  parrot-specific.
- **SM6450 has no mainline support** — Verified. No `sm6450.dtsi` and no parrot
  clk/pinctrl/interconnect driver in `torvalds/linux` master, re-checked
  2026-10-05.
- **UFS 4096-byte logical blocks** — Guess. Typical for the class; not
  confirmed for this device.
- **No SM6450 patches on the mailing lists** — Guess, and it was recorded as
  Verified from an earlier check. `lore.kernel.org` served an Anubis challenge
  on 2026-10-05, so this is stale and unconfirmed; re-check before acting on
  it.

## Read off the live device

First contact, 2026-10-05, over adb with the phone booted normally. The device
is not running stock: it carries LineageOS 23.2 `VANILLA-EXT4-GSI` on top of
Sony's stock pdx246 vendor and odm partitions. `scripts/device-collect.sh`
captures everything below into `out/device-dump/`, read-only.

- **It is the right phone** — Verified. `ro.product.odm.device = pdx246`,
  `ro.board.platform = parrot`, bootimage fingerprint `Sony/pdx246/pdx246`.
  `ro.product.device` reads `XQ-ES72`, which is the market model and not a
  mismatch; `scripts/device-probe.sh` read that one and cried wolf, and now
  reads the odm and vendor properties instead, which a GSI leaves alone.
- **`soc_id` 537, machine `PARROT`, `hw_platform` QRD, revision 1.0** —
  Verified. `/sys/devices/soc0`. 537 is `0x219`, which is the first word of the
  `qcom,msm-id` in the `parrot.dtb` this repo builds, so the bootloader's DTB
  matching will accept our tree.
- **8 cores, 4x Cortex-A78 plus 4x Cortex-A55, 7.2 GiB RAM** — Verified.
  `/proc/cpuinfo` CPU parts `0xd41` and `0xd05`, `/proc/meminfo`.
- **Slot `_b` is active, 110 partitions by name** — Verified.
  `ro.boot.slot_suffix`, `/dev/block/by-name`.
- **The property-based lock check cannot be trusted on this device** —
  Verified. The GSI reports `flash.locked=1`, `verifiedbootstate=green` and
  `veritymode=enforcing`, which is property spoofing to pass Play Integrity:
  `ro.keymaster.xxx.vbmeta_state` still reads `unlocked` and its
  `verifiedbootstate` `orange`, and a GSI cannot be installed on a locked
  device in the first place. `fastboot getvar unlocked` is the only authority,
  and `scripts/device-probe.sh` now says so instead of reporting a lock.
- **No root, so the live device tree and the partitions are out of reach** —
  Verified. `ro.debuggable=0`, no `su`, SELinux enforcing.
  `/sys/firmware/devicetree/base/*` and `/proc/cmdline` are denied to the
  `shell` user even though the directories list.
- **`adb root` is present on this build and gated by a toggle** — Verified.
  `adb root` answers "ADB Root access is disabled by system setting - enable in
  Settings -> System -> Developer options". Turning that on is the single
  highest-value action still available, and it is what unblocks three of the
  gaps below.
- **pstore is empty and unreadable to `shell`** — Verified. `/sys/fs/pstore`
  is denied, so reading ramoops after a failed boot needs root too. Step 5 of
  the next steps assumed otherwise and no longer does.

### What root in recovery gave us

Captured 2026-10-05 from LineageOS recovery and TWRP, both of which run adbd
as root (`uid=0`, context `u:r:su:s0`) where the installed GSI does not. This
closed every gap the unprivileged pass left open.

- **`adb root` on the booted GSI tears down the USB gadget** — Verified,
  twice. adbd reports "restarting adbd as root" and the device then leaves USB
  entirely rather than re-enumerating, so the rooted pass is not reachable from
  the running system. Recovery is, and needs no toggle.
- **The live device tree, 20589 properties, 3651 nodes** — Verified. Decompiled
  to 27892 lines of DTS. `model` is "Qualcomm Technologies, Inc. Parrot QRD",
  `compatible` is `qcom,parrot-qrd`, `qcom,parrot`, `qcom,qrd`, and
  `qcom,board-id` is `<0x1000b 0x00>`. This independently confirms the claim
  above that the device runs Qualcomm's QRD reference tree rather than a Sony
  board tree, and it is the merged base-plus-overlay result the kernel actually
  received, so it supersedes the missing board tree gap entirely.
- **The panel is `qcom,mdss_dsi_samsung_fhd_amoled_cmd`** — Verified, from both
  the kernel command line (`msm_drm.dsi_display0=`) and the node in the live
  tree, named "samsung fhd amoled cmd mode dsi panel". Command mode, not video
  mode. Its display regulators are OLEDB and IBB under `qcom,amoled` on
  `pm6150l`.
- **The real kernel command line** — Verified. `console=ttyMSM0,115200n8`,
  which matches what this port bakes into its own cmdline, plus
  `kvm-arm.mode=protected` and `bootconfig`.
- **A complete backup of both slots** — Verified. `boot`, `vendor_boot`,
  `dtbo`, `vbmeta` and `vbmeta_system` for slots a and b, in
  `out/device-dump-root/stock/`. `flash.sh flash` needs three of these and now
  has them, so the firmware download is no longer on the critical path.
- **`dtbo` holds 37 overlays** — Verified. Three carry `board-id <0x1000b
  0x00>` and all three name the same Samsung panel; extracted and decompiled
  under `out/device-dump-root/dtbo/`.
- **`fastboot fetch` works but only for `vendor_boot`** — Verified.
  `max-fetch-size` is `0x10000000`, and any other partition is refused with
  "Fetch is only allowed on [vendor_boot, vendor_boot_a, vendor_boot_b]".
- **debugfs is available in recovery** — Verified. 442 lines of `clk_summary`,
  138 of `regulator_summary` and 201 of pinmux state captured.
- **pstore is empty** — Verified. No prior crash to read; expected after clean
  boots.
- **TWRP exists for this device** — Verified. It identifies as `twrp_pdx246`,
  `device:pdx246`.
- **The bootloader itself is readable from recovery** — Verified, 2026-10-06.
  `abl_a` is `sda12` and `abl_b` is `sda27`, 1,572,864 bytes each, and
  `adb exec-out dd` reads them with root in recovery. The two slots differ,
  which is expected on a phone that has taken an OTA. They are dumped to
  `out/device-dump-root/stock/abl_{a,b}.img` and deliberately *not* in the set
  `try-kernel.sh --restore` writes back: nothing in this project ever writes to
  the bootloader chain. `scripts/abl-unpack.py` opens them - signed ELF, then
  an EDK2 firmware volume, then an LZMA section, then a second volume - and
  being able to read what the bootloader will do is worth more than most of
  what is in this file.

### What the bootloader actually rejects

Five flashes on 2026-10-05, all reversible and all reversed. The first two were
blind; the last three were single-variable experiments against a known-good
image, which is what finally separated the causes. `scripts/avb-inspect.py`
does the AVB side offline, from the dumps, without touching the phone.

- **The bootloader rejects our device tree, and that is the whole of it** —
  Verified by a single-variable flash. A `vendor_boot` identical to stock in
  every respect except the device tree area - stock kernel, stock ramdisk,
  stock command line, stock bootconfig, stock load addresses - red-states a
  phone that stock boots. The cause is overlay application: the bootloader
  applies an overlay from `dtbo` to the base tree it selects, resolving the
  overlay's `__fixups__` against the base's `__symbols__`. Sony's base defines
  1234 labels and ours 999, and all 37 stock overlays reference at least one of
  the 61 our base does not define, among them `mdss_dsi0`, `mdss_dsi_phy0`,
  `audio_gpr`, `lpass_cdc`, `bluetooth_wcn6750`, `cnss_wlan_mem`, `cpu4_pause`
  and `GOLD_CPU_OFF`. The fixups cannot resolve, the overlay cannot be applied,
  and the device is declared corrupt. Nothing about AVB, signatures or
  `os_version` was ever involved.
- **Carrying Sony's device trees gets us past the bootloader** — Verified on
  the device. Our kernel, our initramfs and our command line flashed together
  with Sony's fourteen trees produced no corrupt message for the first time;
  the phone sat on the Sony logo instead, which is what a handed-off boot with
  no display driver looks like. No USB gadget came up, so the debug shell was
  not reached, and how far the kernel got is still unknown.
- **Carrying Sony's device trees is the way round it** — Verified. `scripts/swap-vendor-dtb.py` rebuilds a
  `vendor_boot` with a different dtb area and leaves every other section and
  header field alone, so our kernel, our initramfs and our command line can
  travel with Sony's fourteen trees until our own base defines the labels the
  overlays need. The real fix is to build the base tree with the
  `sm6450-modules` includes.
- **`stdout-path` comes from the bootloader, not from `parrot.dtb`** —
  Verified, and this corrects a comment in `kernel-cmdline.conf`. Neither our
  base tree nor Sony's defines it at the root; in the live tree it sits in
  `/chosen` next to `linux,initrd-start`, which is the bootloader's own
  handiwork. It reads
  `stdout-path = "/soc/qcom,qup_uart@98c000:115200n8"`, so bare `earlycon` does
  find the GENI port - but it will do so whichever base tree we ship, because
  the property is not ours to supply.
- **The red state is not AVB** — Verified, and this reverses the earlier
  reading. `vbmeta_b` was re-flashed with the two disable flags set and a
  signature that `avb-inspect.py` proves is invalid, and the device booted
  normally. An unlocked bootloader here really does allow verification errors:
  it comes up *orange*, which `ro.keymaster.xxx.verifiedbootstate` confirms
  while the GSI spoofs `ro.boot.verifiedbootstate` to `green`.
- **Nor is it the `boot` hash descriptor** — Verified. Stock `boot_b` was
  re-flashed with a single byte of inter-image *padding* inverted, which breaks
  the hash `vbmeta` records for the partition while leaving the kernel, the
  ramdisk and the GKI boot signature byte-identical. It booted. So with the
  disable flags set, the bootloader does not check what `vbmeta` says about
  `boot`.
- **Nor is it `os_version`** — Verified, and this retracts the lead recorded
  earlier the same day. Stock `boot_b` was re-flashed with `os_version` zeroed
  and nothing else changed, and it booted. Ours reading `0x00000000` against
  stock's `0x1800063c` is real but harmless, so `--os_version` and
  `--os_patch_level` are not worth adding on this evidence.
- **Patching the disable flags cannot help but break the signature** —
  Verified, by construction rather than by experiment. `flags` sits at offset
  120 of the 256-byte vbmeta header, and libavb hashes that whole header
  followed by the auxiliary block before signing the result, so any flag change
  invalidates the hash. `fastboot --disable-verity --disable-verification` does
  not re-sign. This is why it only works on an unlocked device, and the first
  experiment above is what shows this one is unlocked enough.
- **Stock `vbmeta` and `vbmeta_system` are untouched** — Verified. Both are
  `SHA256_RSA4096` with `flags = 0x00000000`, both verify against their own
  embedded key, and both describe Sony's stock builds. The GSI install never
  patched either of them. `vbmeta_b` holds hash descriptors for `boot`
  (48316416 bytes), `dtbo`, `recovery` and `vendor_boot`, hashtree descriptors
  for `odm`, `vendor` and `vendor_dlkm`, and a chain descriptor handing
  `vbmeta_system` off to its own key at rollback location 2.
- **Stock `boot` carries a GKI boot signature and ours does not** — Verified,
  and the strongest remaining structural difference. Stock `boot_b` sets
  `signature_size = 4096` in its header-v4 footer and holds an `AVB0` structure
  at offset 48312320; that offset plus 4096 is exactly the 48316416 that
  `vbmeta` records for the partition. Ours sets `signature_size = 0` and has no
  such structure. Whether this bootloader verifies it is untested.
- **Both kernels are valid arm64 images** — Verified. Ours and stock both carry
  `ARM\x64` at offset 0x38 of the Image header with `text_offset = 0` and
  `flags = 0xa`, so nothing about the kernel binary itself is malformed.
- **Our `vendor_boot` is structurally identical to stock** — Verified. Header
  version 4, 4096-byte pages, `header_size` 2128, and the same four load
  addresses: kernel `0x00008000`, ramdisk `0x01000000`, tags `0x00000100`, dtb
  `0x01f00000`. What differs is content: one 308591-byte FDT where stock
  concatenates 4887468 bytes of them, `bootconfig_size` 0 against 119, and an
  entirely different command line.
- **`fastboot fetch` belongs to fastbootd, not the bootloader** — Verified. The
  real bootloader answers "Device does not support fetch command" for `logfs`,
  `appslog`, `xbl_sc_logs` and `rddata` alike, so the bootloader's own logs
  cannot be read back over fastboot. The earlier note that `fetch` worked for
  `vendor_boot` was from fastbootd.
- **Recovery survives a bad boot flash** — Verified. `recovery_a` and
  `recovery_b` are their own partitions on this device, so TWRP stayed intact
  throughout and remains the way back to a root shell.
- **ramoops held nothing from the attempts** — Reasoned. A bootloader refusal
  means the kernel never ran, so there was no console to capture; this is
  consistent with the complete absence of USB activity.

## Seeing what a blind boot did

This device has no console we can reach, and that - not any one bug - is what
made the first week of bring-up slow. The findings below are what closed it.

- **ramoops does not survive a reboot here** — Verified 2026-10-05, and this
  overturns what this document said before. The binding works: TWRP's own
  kernel reserves the region, prints `printk: console [ramoops-1] enabled` and
  `pstore: Registered ramoops as persistent store backend`, and writes to it.
  Recovery is what fails. Reboot TWRP into TWRP - a clean warm reboot with
  nothing of ours anywhere in it - and `/sys/fs/pstore` is empty, with the
  records from seconds earlier gone. The only thing placed to do that is the
  bootloader scrubbing DRAM, so every RAM-backed log channel dies with it.
- **No other RAM or vendor channel helps either** — Verified. `rddata` holds a
  single non-zero line in its first 4 MB, so no Qualcomm ramdump is being
  collected, which the SoC's fuses would have to permit anyway. `logfs` is a
  FAT12 filesystem whose `UEFILOG1TXT` contains the partition table as text,
  not kernel output. `fastboot fetch` is a fastbootd command; the real
  bootloader refuses it. The one channel in this list that is **not** settled
  is the GENI UART at `0x98c000`: the stock `chosen` node points
  `stdout-path` straight at it, so the SoC side is wired, and whether the pads
  come out anywhere a probe can reach on an assembled pdx246 is untested. An
  earlier version of this file asserted they do not. That was a guess written
  as a fact.
- **`pstore_blk` cannot be used on this kernel** — Verified by configuration.
  It would write pstore zones to flash rather than DRAM, which is exactly what
  is wanted, but it binds at `late_initcall` and `ufs_qcom` is a module loaded
  about eighty entries into `initramfs.load`. The block device does not exist
  when `pstore_blk` looks for it. Making UFS builtin would mean dragging the
  clock, pinctrl, regulator and SMMU chain in with it, which stock keeps
  modular on purpose.
- **The ring buffer is retroactive, which is what makes a late write enough** —
  Verified, and it is the observation the log channel rests on. We cannot write
  to flash early, but we do not need to: `dmesg` taken the moment storage
  appears still contains every message since the first line of kernel output.
  So the dumper is armed as soon as `/proc` is mounted, blocks until the block
  device shows up, and then writes the whole history in one go.
- **`rddata` is the place to put it** — Verified. 20 MiB, and all 20971520
  bytes read back as zero on this device, so nothing is being lost by using it.
  It is Qualcomm ramdump staging, written only by a debug-fused SoC collecting
  a dump, which ours cannot. `appslog` was the other candidate and is rejected:
  it is nearly full of real Android logs. Both are backed up under
  `out/device-dump-root/stock/`.
- **The GPT on this device has 4096-byte logical sectors** — Verified, and it
  is an easy half-hour to lose. The protective MBR sits at byte 0 as usual, but
  the `EFI PART` header is at byte 4096, not 512, and the entry array at 8192.
  97 entries. A parser that assumes 512 reads zeros and concludes the disk has
  no partition table.
- **The log partition is identified by geometry, not by name** — Reasoned, and
  deliberate. `rddata` is `/dev/block/sda97`, starting at LBA 31228923 and
  running 5120 LBAs, which sysfs reports in 512-byte units as start 249831384
  and size 40960. The hook refuses to write unless both match, because the cost
  of a wrong guess is overwriting a real partition.
- **The log channel works, proven on the hardware** — Verified 2026-10-05. The
  hook's own `pmbootlog_find` and `pmbootlog_write` were run under TWRP, where
  the kernel is Sony's and known good. It identified `/dev/block/sda97` by
  geometry, wrote its record, and 199649 bytes read back. So the find-and-write
  path is not in doubt, and that is what makes the negative result below mean
  something.
- **Withdrawn: "our kernel does not reach the point where UFS works"** — this
  said two boots had left `rddata` all zeros, that the hook waits two minutes
  for the block device, and so the kernel must have died before `ufs_qcom`
  probed. The inference was sound and the conclusion was wrong. The hook is
  sourced by the real init in `load_modules`, and the real init was sitting in
  the debug shell waiting for a telnet connection that could not arrive, so it
  had not got as far as arming the hook at all. UFS works. It always did:
  `scsi`, `/dev/sda`, a mounted SD card and a steady `ufshcd` interrupt count
  are all in the log of 2026-10-05. An all-zero `rddata` means the hook never
  ran, which is not the same as the kernel never getting there.
- **The log hook is not what hangs the phone** — Verified 2026-10-05, and it
  retires the guess that replaced it. A control run with `BOOTLOG=0`, the same
  image with the hook left out, hung exactly the same way: nothing in eleven
  minutes, no fallback, no USB.
- **Two images that behave differently are byte-identical** — Verified, and it
  is the most awkward fact here. The image from the run that panicked and reset
  itself five times and the image from the run that hung have the same 13
  command-line parameters, the same 478 initramfs entries with identical
  contents, and the same four load addresses. Nothing distinguishes them. So
  the failure is not a property of the image: either it is non-deterministic,
  which an early race over clock, regulator or SMMU probe order would explain,
  or the five resets were never kernel panics in the first place. Settling that
  needs `slot-retry-count` read right after a timed hang, which needs the
  button combo, so it has not been done.
- **The kernel boots and reaches userspace** — Verified 2026-10-05, and it is
  the first solid ground this port has had. A vendor_boot whose `/init` was
  replaced by nothing but `sleep 8; reboot -f` made the phone reboot seven
  times and fall back to the stock slot after 186 seconds, which is 26 seconds
  an attempt: about 18 of bootloader, 8 of sleep. So the arm64 `Image` is
  loaded and entered, Sony's device trees are accepted, the vendor ramdisk
  decompresses, and `/init` executes. None of that is in question any more.
  Where this went on to guess - that the failure must therefore be in
  `load_modules` - it guessed wrong; see the flash log further down. Module
  loading was never the problem.
- **A hang leaves exactly one attempt on the counter, not seven** — Verified.
  After eleven minutes of hanging, `slot-retry-count` had gone from 7 to 6.
  The counter advances when the bootloader begins an attempt, so a kernel that
  stops never produces a second one. There is nothing to wait for: a round
  that has hung has hung, and the eleven minute timeout only delays finding
  out. It also means `panic=5` was never reached in any of those runs.
- **The retry counter is a usable output channel** — Verified, and it is the
  only one that works before storage. An init that reboots on purpose burns
  all seven attempts and falls back, which the host sees without a console,
  without USB during boot and without anyone watching the screen; a kernel
  that dies first burns one and stops. One bit per round, four minutes a
  round, hands-free. `PROBE=1 scripts/try-kernel.sh` is the mechanism, and
  bisecting `initramfs.load` with it is the way to find what actually hangs.
- **A hang does recover without touching the phone - it takes about 72
  minutes** — Verified 2026-10-05, and it replaces a flat claim here that it
  could never happen. Qualified 2026-10-07: what came back was not a hang.
  It was the downstream staged probe, which resets on purpose after 600 idle
  seconds (the next entry), so the 620 seconds an attempt are our own timer
  and not anything in the hardware or the hypervisor. Nothing is known to
  reset a boot that is alive and waiting with no timer of ours armed; see
  "The real init on mainline". A round was left alone after the loop had given up, and
  the phone came back on its own: `slot-retry-count:a` 0, `slot-unbootable:a`
  yes, Android up on the fallback slot. Seven attempts across 4337 seconds is
  about 620 seconds each. Nothing was wrong with the reasoning that produced
  the old claim - the retry counter really does only advance when the
  bootloader begins an attempt - only with the assumption that an attempt is
  short. We had never waited more than eleven minutes before reaching for the
  buttons, so we had never seen the eighth minute of one. The loop is
  hands-free in both cases; it only has to be patient, and `WAIT=` is how.
- **The kernel boots, and has been booting for some time** — Verified by the
  flash log, which is the single most useful thing this port has produced. All
  89 modules load. UFS comes up, `/dev/sda` and friends appear, the SD card is
  found and mounted (`mmcblk1`, 477 GiB), interrupts keep flowing, and the
  system idled for 603 seconds before resetting itself on purpose. There was
  never a hang, and most of the things this file once blamed - the Qualcomm
  command line, the log hook, module loading - were never involved. The phone
  was sitting in the initramfs with no way to tell anyone.
- **The gadget was binding to an emulated controller** — Verified, and this is
  what made a healthy boot look dead. This kernel builds `dummy_hcd`, a
  software USB host and gadget emulator, which registers `dummy_udc.0`.
  `get_usb_udc()` takes the first entry in `/sys/class/udc`, the real
  controller was not in there, and so the gadget came up perfectly against the
  phone's own emulated host: `cdc_ncm` registered at `usb-dummy_hcd.0-1`,
  `cdc_acm` giving `ttyACM0`, `usb0` with a MAC and an address,
  `android_work: sent uevent USB_STATE=CONFIGURED`. All of it inches from the
  USB-C port and invisible through it. The host's own kernel log is the other
  half of the proof: between the fastboot device disconnecting and Android's
  gadget appearing 76 minutes later it recorded no enumeration attempt at all,
  not even a failed one. `deviceinfo_usb_network_udc` now names
  `a600000.dwc3`, and `pmos.config` drops `dummy_hcd` for the next kernel
  build, so a gadget either lands on the hardware or fails loudly.
- **`dwc3-msm` was deferring forever on two providers, silently** — a driver
  waiting on a provider prints nothing, which is how this hid for a day. Both
  come from `ssusb@a600000` in the live tree. Verified: it carries
  `extcon = <&eud>`, and nothing registers an extcon on
  `qcom,msm-eud@88e0000` because `eud` was missing from `modules-initfs` -
  stock loads `eud.ko`, we build `eud.ko`, and we had never loaded it. Now
  fixed. Also verified but not yet fixed: its `ddr-usb` interconnect path goes
  through `interconnect@19100000` (`qcom,parrot-gem_noc`), which logged
  `failed to register ICC provider` seventeen times, so `of_icc_get()` defers
  forever too.
- **The failing interconnect providers are exactly the ones needing the second
  bcm_voter** — Verified, and it is a clean pattern rather than a guess. Every
  provider whose `qcom,bcm-voters` lists only `rsc@17a00000`'s voter
  registered: `interconnect@0`, `1500000`, `1502000`, `1680000`, `16e0000`.
  Both that also list `rsc@af20000`'s failed: `1740000`
  (`qcom,parrot-mmss_noc`) and `19100000` (`qcom,parrot-gem_noc`). So
  `rsc@af20000`'s `bcm_voter` never registers. Guess, for the next round to
  settle: that node is `qcom,rpmh-rsc`, the same driver as the APPS RSC, and
  its children are created by that driver, so either `af20000.rsc` does not
  probe or its child device is never populated. On stock, `af20000.rsc` binds
  `rpmh` and `af20000.rsc:bcm_voter` binds `bcm_voter`.
- **The flash log now carries what a deferral needs** — the probe's own
  progress, `/sys/kernel/debug/devices_deferred`, `/sys/class/udc` and every
  platform device with the driver bound to it. `dmesg` alone cannot show a
  silent deferral, and that omission is what cost the time.
- **`wait_for_adb` was blind to fastboot** — fixed. The bootloader can give up
  into fastboot instead of booting the fallback, and a wait that only polled
  adb reported that as a dead phone, throwing the round away while the device
  sat there waiting to be talked to.
- **A reboot loop and a hang are indistinguishable on this phone** — Verified
  the hard way, three times, twice by me. Every boot attempt redraws the same
  Sony logo, so a device working through seven retries at 54 seconds each
  looks exactly like a device that has stopped. Twice somebody reached for the
  buttons around the three minute mark and threw the run away. The only tells
  are the logo visibly restarting, and `slot-retry-count` afterwards.
  `wait_for_adb` now prints elapsed time and the likely attempt number so
  nobody has to guess.
- **Always clear `rddata` between runs** — a stale record is indistinguishable
  from a fresh one, and the uptime in the header is the only hint. `--log`
  wipes it after reading for this reason.
- **Sony's own command line, read off the running recovery** — Verified
  2026-10-05, captured by the hook. 41 parameters, in
  `out/device-dump-root/reference/twrp-dmesg.txt` along with 2411 lines of a
  successful boot on this hardware, which is the only known-good reference we
  have for what probes in what order.
- **The Qualcomm parameters are not what hung the phone** — this corrects a
  conclusion drawn earlier the same day. A boot carrying `swiotlb=noforce`,
  `disable_dma32=on`, `kpti=0`, `rcu_nocbs=0-7`, `pcie_ports=compat`,
  `msm_rtb.filter=0x237`, `allow_mismatched_32bit_el0` and
  `android12_only.will_be_removed_soon.memblock_nomap_remove=on` hung where a
  shorter command line had panicked, and the parameters looked responsible.
  They are not: Sony's recovery kernel boots this device with every one of
  them. Whatever the difference is, it is not that these options are fatal.
- **Sony passes `video=vfb:640x400,bpp=32,memsize=3072000`** — Verified, and
  worth revisiting. It was deliberately left out of our command line on the
  grounds that a virtual framebuffer would claim `fb0` ahead of the real panel.
  Stock sets it anyway.
- **The real init loads all 89 modules in one `modprobe -a`** — Verified by
  reading `load_modules` out of the shipped initramfs. `STAGE=1
  scripts/try-kernel.sh` replaces `/init` with a probe that loads them one at
  a time instead. That was built to find a module that wedges, and it found
  that none of them does - every one loads. It earned its keep anyway, because
  it is what got a log onto flash and so told us the kernel was healthy.
- **The USB gadget needs eleven of those modules, and no storage** — Verified
  from `modules.dep`: the symbol closure of `dwc3-msm` and the two PHYs is
  `clk-qcom`, `debug-regulator`, `gdsc-regulator`, `minidump`,
  `proxy-consumer`, `qcom-scm`, `qcom_ipc_logging` and `smem`. That is the
  whole reason a staged probe is worth building - the gadget can come up long
  before the storage chain, so the first pass loads a curated 40 (clocks,
  pinctrl, regulators, the SMMU, rpmh, the PMIC, the PHYs, `dwc3-msm`) and
  tries to open a live link before anything can hang. Reasoned, not yet
  measured: dependencies that are runtime rather than symbol ones - clocks,
  pins, regulators, interconnect - do not appear in `modules.dep`, so the
  curated list is a judgement about what `dwc3-msm` needs to bind, and the
  probe is what tests it.
- **The UDC is `a600000.dwc3`** — Verified in recovery. There is a
  `dummy_udc.0` beside it on Sony's kernel, which `get_usb_udc` would never
  pick because it takes the first name alphabetically.
- **The gadget functions are built into our kernel, not modules** — Verified:
  `libcomposite`, `usb_f_ncm` and `usb_f_rndis` are all strings in our
  `vmlinuz`, and none of them has a `.ko` in the initramfs. So the gadget needs
  no module beyond the controller and its PHYs.
- **`CONFIG_MAGIC_SYSRQ` and `CONFIG_DETECT_HUNG_TASK` are both in** —
  Verified the same way (`sysrq-trigger`, `khungtaskd` and `blocked for more
  than` are all in the image). Two things follow. `echo b >
  /proc/sysrq-trigger` is `emergency_restart()`, which skips the orderly
  shutdown a wedged driver could block, so it is a more reliable reset than
  `reboot -f`. And `/proc/sys/kernel/hung_task_panic` turns a task stuck
  uninterruptible into a panic, which `panic=5` then turns into a reset - that
  is what a driver waiting forever on a clock, a regulator or firmware looks
  like, so it covers the most likely shape of our hang. Both are set from the
  probe rather than the command line, which avoids the rebuild entirely.
- **`hung_task_panic=` is not a boot parameter in this kernel** — Verified,
  the string is absent. The sysctl is the only way in, which is fine: the
  probe writes it straight after `/proc` is mounted.
- **Elapsed time is a usable analog channel, not just a bit** — Reasoned, and
  being measured now. The stall watchdog delays its reset by one second per
  step completed, so seven attempts multiply the difference by seven and the
  time to the fallback names the step: about `7 x (43 + n) + 35` seconds, where
  43 is the bootloader's 18 plus the watchdog's 25. `bootlog.py stages <image>
  [seconds]` prints the map in both directions. The noise is the time the probe
  spends loading the modules before the one that hung, a few seconds an index,
  which biases a reading low by a couple of steps rather than scattering it.
- **Nothing in the probe can report a hard lockup** — Reasoned. Every channel
  here needs the scheduler: the stall watchdog is a shell loop, khungtaskd is a
  kthread. A spinlock deadlock with interrupts off stops all of them, and on
  arm64 there is no NMI watchdog to catch it. That case still looks like the
  hangs we have had - one attempt burnt, then silence - and still needs the
  buttons.


## The build environment

- **pmbootstrap runs rootless with the three patches** — Verified. The native
  chroot builds and `pmb checksum` succeeds. Three, not two: `/dev` in a
  userns, `mount`/`umount` in a userns, and not unregistering a binfmt handler
  we did not register.
- **`pmb install` itself cannot run in this container** — Verified. Two
  independent blockers: `modprobe loop` needs privileges a rootless container
  has not got (cleared by running it on the host), and after that `losetup`
  still fails with `cannot find an unused loop device: Permission denied`
  because `/dev/loop-control` is `root:disk` 0660 and the container has no
  `/dev/loopN` nodes. Joining `disk` would grant raw access to every block
  device on the machine, so `make-rootfs-img.sh` sidesteps loop devices
  instead.

## The kernel package

- **Kernel aport layout (two tarballs, device trees into `dts/vendor`)** —
  Verified. `dts/Makefile` keys off `vendor/Makefile`, and the tree configures
  and compiles from it.
- **Kernel builds with Alpine clang** — Verified. Builds clean in ~4 min:
  `boot/vmlinuz` 30,497,280 bytes, 294 modules, `kernel.release`
  `5.10.269-gki`. Needed `cc-wrapper` removed, `-Werror` stripped, a list of
  `-Wno-error=` flags, and the per-directory include path made unconditional.
- **This tree expects an `O=` build and we build in tree** — Verified.
  Qualcomm's 137 tracepoint headers use `TRACE_INCLUDE_PATH .` and need
  `-I$(srctree)/$(src)`, which `scripts/Makefile.lib` adds only
  `ifdef building_out_of_srctree`. `prepare()` drops that condition. Expect
  more in-tree assumptions of this shape.
- **`pmos.config` survives `olddefconfig` intact** — Verified. Every `=y`, `=n`
  and "is not set" in it was read back out of the generated `.config`.
- **`pmos.config` satisfies `pmb kconfig check`** — Verified. "kconfig check
  succeeded!"
- **`earlycon` works with the serial driver left modular** — Verified.
  `msm_geni_serial_earlycon.o` is built by
  `CONFIG_SERIAL_MSM_GENI_EARLY_CONSOLE`, which is a *bool*, so it is always in
  `vmlinux`; it carries `OF_EARLYCON_DECLARE(..., "qcom,msm-geni-console", ...)`,
  the compatible on the port in `parrot.dtb`. Building the GENI drivers in
  instead pulls IPC logging, then minidump, then SMEM — stock keeps that
  cluster modular on purpose.
- **Only `parrot.dtb` is built, not Qualcomm's whole device tree release** —
  Verified. `make dtbs` emits exactly one `DTC` line. The stock `audio/` and
  `camera/` trees cannot build at all without headers from the out-of-tree
  `sm6450-modules` repo.
- **`deviceinfo_dtb="vendor/qcom/parrot"` resolves** — Verified. boot-deploy's
  `find_dtb` runs `find /boot -path "/boot/dtbs*/$_filename.dtb"`, and the
  package really contains `boot/dtbs/vendor/qcom/parrot.dtb` (308,591 bytes).
- **Every name in `modules-initfs` was really built** — Verified.
  `verify-build.sh` against the real package: all 89 present among the 294
  `.ko` files. 89, not 90 — `dm-mod` is builtin because pmOS wants
  `CONFIG_BLK_DEV_DM=y`; the other 89 are stock's list unmodified.
- **USB module names (`dwc3-msm`, `phy-msm-*`)** — Verified.
  `drivers/usb/{dwc3,phy}/Makefile`: `CONFIG_USB_DWC3_MSM` -> `dwc3-msm.o`,
  `CONFIG_MSM_HSUSB_PHY` -> `phy-msm-snps-hs.o`, `CONFIG_USB_MSM_SSPHY_QMP` ->
  `phy-msm-ssusb-qmp.o`. `parrot_GKI.config` enables only these two PHYs: no
  eUSB2, no QUSB.

## The mainline kernel package

Everything here is about `linux-postmarketos-qcom-sm6450`, our own 6.18 kernel.
`docs/06-mainline.md` carries the derivation; this is what has been checked.

- **The whole SM6450 series builds clean under Alpine clang** — Verified.
  `pmb build --arch aarch64 linux-postmarketos-qcom-sm6450`, 63 minutes, exit
  0, and not one warning or error in the log. clang 23.1.2 and pahole 131 in
  the build chroot, against gcc 14.2.0 and no pahole in the distrobox, which is
  why `CONFIG_CFI` and `CONFIG_DEBUG_INFO_BTF` had to be set by hand rather
  than left to `olddefconfig`.

  The 63 minutes is the cost of that particular invocation, not of building
  this kernel, and it was quoted as the rebuild cost for a day after it
  stopped being true. `--arch aarch64` builds inside the aarch64 chroot under
  QEMU user emulation, from a cold cache. The APKBUILD says
  `pmb:cross-native`, so a plain `pmb build linux-postmarketos-qcom-sm6450`
  compiles in the x86_64 chroot with a cross toolchain instead, through
  pmbootstrap's ccache (`.pmb/work/cache_ccache_x86_64`). With that cache warm,
  a one-file change rebuilt, packaged, installed into the rootfs and ran
  `mkinitfs` in under two minutes on 2026-10-07 - 1:44 of it the package
  build, which still unpacks the tarball and runs every compile through the
  cache. Never pass `--arch` for this package.
- **The package contains what a boot needs** — Verified. `boot/vmlinuz`
  28,588,544 bytes, `boot/linux.efi` 11,493,888, 427 modules, `kernel.release`
  `6.18.55`, and `boot/dtbs/qcom/sm6450-sony-xperia-columbia-pdx246.dtb` at
  30,410 bytes. The APKBUILD's own `die` on a missing device tree did not fire.
- **gcc and clang produce the same device tree** — Verified. The DTB in the apk
  is byte-identical to the one the out-of-tree gcc build emitted. Worth knowing
  because the device tree is the part most likely to be wrong, and this rules
  out the compiler as a variable in it.
- **Every address in our tree is in the tree the device boots** — Verified.
  `check-dt.py` against the live tree: 66 addresses in ours, 64 exact matches,
  two inside a block of theirs and both already argued for in
  `docs/06-mainline.md` (the USB QSCRATCH bank inside Sony's whole-peripheral
  `ssusb@a600000`, and the tlmm rebased off `0xf000000`), none unaccounted for.
  Interrupts: 14 nodes agree, 1 differs, and the difference is the watchdog
  taking only the bark interrupt, which is the upstream convention.
- **The device package really offers a choice of kernel** — Verified. Both
  `device-sony-pdx246-kernel-downstream` and `-kernel-mainline` build, and each
  resolves the suffixed deviceinfo keys correctly: the mainline subpackage ships
  `deviceinfo_dtb="qcom/sm6450-sony-xperia-columbia-pdx246"` and
  `deviceinfo_usb_network_udc="a600000.usb"`, the downstream one
  `"vendor/qcom/parrot"` and `"a600000.dwc3"`, with no `_downstream`/`_mainline`
  suffix left unresolved in either.
- **Switching kernels needs `pmb install --zap`** — Verified, the hard way.
  Both kernel packages own `/boot/vmlinuz`, so installing one into a rootfs
  chroot that still holds the other fails with "trying to overwrite
  boot/vmlinuz owned by linux-sony-pdx246". apk is right to refuse and the
  packages are right to conflict; the chroot just has to be clean.
- **`modules-initfs.mainline` can be empty because mkinitfs has its own list**
  — Verified. The file names no modules at all, and the built initramfs still
  holds fifteen: `libcomposite`, `u_ether`, `u_serial`, `usb_f_acm`,
  `usb_f_ncm`, `usb_f_rndis`, `usb_f_mass_storage`, `evdev` and the filesystem
  and raid helpers. mkinitfs takes the `usb_f_*` names from its own
  `00-default.modules` and pulls `libcomposite`, `u_ether` and `u_serial` in as
  modinfo dependencies. These are the only channel a first mainline boot has,
  so this mattered more than its size suggests.
- **`pmb install` cannot finish in the distrobox, and does not need to** —
  Verified. Stage 2 builds the rootfs and runs boot-deploy, which is everything
  `try-kernel.sh` reads; stage 3 wants a loop device and dies with "Failed to
  find loop device". It leaves a correctly sized, entirely zero
  `sony-pdx246.img` behind, which `verify-bootimg.py` refuses by design -
  flashing it would write zeros over the rootfs. `make-rootfs-img.sh` is the
  route to a real one.
- **pkgrel 5 builds in what a post-mortem needs, and pkgrel 6 keeps it** —
  Done 2026-10-07.
  - `CONFIG_MAGIC_SYSRQ=y`, so the USB watchdog can dump blocked tasks and
    reset without `device_shutdown`. `CONFIG_MAGIC_SYSRQ_DEFAULT_ENABLE=0x1`
    covers only the keyboard and serial routes; `/proc/sysrq-trigger`
    works whatever the mask.
  - `CONFIG_DETECT_HUNG_TASK=y` with a 30-second timeout, and
    `CONFIG_DETECT_HUNG_TASK_BLOCKER=y`, which names the task holding the
    mutex a hung task is waiting for. Hung-task panic stays off: a stuck
    bind should end up in the log, not in a reset that takes the log with
    it.

  pkgrel 5 also raised `CONFIG_LOG_BUF_SHIFT` from 17 to 22, a 4 MiB ring
  buffer, and pkgrel 6 takes that back. Verified in the two packages:
  `boot/vmlinuz` grew from 28,588,544 to 42,811,904 bytes, while the
  compressed `linux.efi` grew by 32 KiB. The text buffer itself is `.bss`,
  but the descriptor arrays beside it, `_printk_rb_static_descs` and
  `_infos` (`kernel/printk/printk_ringbuffer.h`), each have one entry
  initialised, so the whole of both goes into `.data`. At 112 bytes a
  record, going from 2^12 records to 2^17 predicts the growth to within
  2 KiB. The image's in-memory size went from 29.2 MB to 47.4 MB, the 4 MiB
  text buffer included. That is past the 44.6 MB of the stock kernel the
  bootloader is known to load, and nothing in our notes says where ABL's
  limit is. `log_buf_len=4M` on the command line
  gives the same 4 MiB, allocated at boot, and `try-kernel.sh` always adds
  it, so the built-in size bought nothing for that risk. pkgrel 6 also
  carries the SD rail fix below in its device tree.

  The values are the ones `olddefconfig` computes for these symbols. They
  were written into the config by hand, because `olddefconfig` in the
  distrobox, with gcc and no pahole, also drops `CONFIG_CFI` and
  `CONFIG_DEBUG_INFO_BTF`, which only clang and pahole in the build chroot
  can satisfy.
- **pkgrel 7 lets the Gunyah watchdog run from boot** — Done 2026-10-07.
  Built and installed, and the parameter and its message are in the
  installed `vmlinuz` (`#8-postmarketos`); not yet run on the device.
  `CONFIG_GUNYAH_WATCHDOG` goes from `m` to `y`, because a module would only
  load from the init, after the window this is meant to cover. A
  bring-up-only patch, `bringup-gunyah-wdt-start-at-boot.patch`, adds
  `gunyah_wdt.start_at_boot`. With it the driver starts the watchdog at
  probe instead of stopping it, and sets `WDOG_HW_RUNNING`, so the watchdog
  core's own kernel thread feeds it until something opens `/dev/watchdog0`
  (`CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED=y`, `CONFIG_WATCHDOG_OPEN_TIMEOUT=0`).
  A kernel that stops scheduling stops feeding it, and the hypervisor bites
  32 seconds later. The parameter is off by default and is not for
  upstream. Whether a bite resets this board in a way the bootloader counts
  as an attempt is what the `WDTPROBE` round tests; see "The real init on
  mainline".
- **pkgrel 8 gives the SoC tree its SCM node** — Done 2026-10-07, built and
  never installed. See "The real init on mainline" for why it matters.
- **pkgrel 9 lets `qcom_scm` find Gunyah on SMCCC v1.0 firmware** — Done
  2026-10-07, built, and installed in the rootfs by the overnight queue at
  04:02 on 2026-10-08, with fresh boot images. One more bring-up
  patch, `bringup-gunyah-wdt-smccc-1-0.patch`, with the reasoning in "The
  real init on mainline".

## The first mainline flash

Run on 2026-10-06. The kernel never got to run, so nothing here is evidence
about the kernel or the device tree's contents - only about whether the boot
chain will accept the images at all.

- **The flash itself is clean and the loop reaches it unattended** — Verified.
  `to-fastboot.sh` put a running pmOS into fastboot in fifteen seconds,
  `try-kernel.sh` moved the stock slot back to active, settled it, built the
  images and flashed `vbmeta_a`, `dtbo_a`, `boot_a` and `vendor_boot_a` without
  a single manual step. Our stamped tree went in at 30,484 bytes and the empty
  dtbo at 4,096.
- **The device red-states, and the empty dtbo is the reason** — Verified, and
  this is the experiment's answer: no. The screen says the phone is corrupt and
  will not boot, and USB never comes up. What makes the dtbo the suspect rather
  than the device tree is that the two known failure modes are now separated.
  On 2026-10-05 our tree plus *stock's* dtbo red-stated over 61 unresolvable
  labels, which is an overlay failing to apply. This time there were no overlays
  to apply at all and `dtb-stamp-ids.py` had matched the hardware's `soc_id`
  `0x219`, so a base was there to select - and it still red-stated. A dt table
  with `dt_entry_count = 0` is not something this ABL will accept. The reason is
  now read out of ABL's own sources rather than inferred from the screen; see
  the next section.
- **The control run that was planned next would have been uninformative** —
  Reasoned, and this is why reading the sources first was worth a turn. The plan
  was to flash Sony's own `vendor_boot` with nothing but the empty dtbo swapped
  in, to separate the dtbo from our device tree. With the matcher understood,
  that run is predicted to red-state for a *third* reason: an unreadable or
  unsatisfiable dtbo sends ABL to `DeviceTreeAppended`, whose strict matcher
  requires the platform type to be equal, and all fourteen of Sony's base trees
  carry `qcom,board-id = <0x0 0x0>` or `<0x0 0x600>`, so none of them matches a
  board reporting QRD. Stock's own trees cannot be appended-booted on this
  phone. The experiment would have cost a button press and told us nothing.
- **A red state leaves no USB and costs one button press** — Verified, again.
  Nothing appeared on the bus: no fastboot, no adb, no gadget. Power+VolUp then
  VolUp-while-plugging-in is the only way back, which puts a hard price on each
  failed attempt of this particular kind and is the argument for choosing the
  next one carefully rather than iterating.
- **Recovery is complete and took one command** — Verified. `try-kernel.sh
  --restore` rewrote `vbmeta_a`, `dtbo_a`, `boot_a` and `vendor_boot_a` from the
  2026-10-05 dumps and made slot b active; the phone then booted stock Android
  16 on `_b` with adb up and `ro.boot.verifiedbootstate` `orange`, which is what
  an unlocked bootloader reports and not a complaint.
- **`--restore` was restoring the wrong slot** — Verified and fixed. It targeted
  "the spare", which is correct only after the bootloader has fallen back. A run
  that red-states never boots, so it leaves the experiment slot active and
  nothing falls back: the old code would have rewritten the stock slot, which
  was already stock, and left the broken slot untouched. It now restores
  whichever slot is not marked successful and hands activity back to the one
  that is.

## How the bootloader chooses, from its own sources

Read on 2026-10-06 from the public EDK2 `QcomModulePkg` - `BootLinux.c`,
`LocateDeviceTree.c`, `PartitionTableUpdate.c`, `Board.c` and
`Include/Library/LocateDeviceTree.h` - and then checked against the bootloader
actually on this phone, which is the thing that makes the rest of this section
load-bearing rather than suggestive.

- **The published sources are this device's ABL** — Verified, against the
  binary. `abl_b` was dumped from recovery and unpacked with
  `scripts/abl-unpack.py`, and its strings carry the code paths verbatim:
  "Unable to find the Board Dtb", "Error: Board Dtbo blob not found", "Dtbo hdr
  magic mismatch %x, with %x", "DTB offset is incorrect, kernel image does not
  have appended DTB", "Single appended DTB found", "Exact DTB match found. DTBO
  search is not required", "No match found for Soc Dtb type", all five "Dtbo
  Table ... got corrupted" checks, both "DTB header is corrupted" messages, and
  the LK matcher's own "Add DTB entry", "Delete don't fit DTB entry", "Best
  match DTB tags", "ddr size does not match", "subtype-id doesnot match" and
  "soc foundry does not match". `qcom,pmic-id-size` is there too. This is the
  same implementation, down to the format strings.
- **This build has no soft-SKU term at all** — Verified, against the binary,
  and it removes the last unread field in the chain. `qcom,softsku-id` does not
  appear anywhere in the unpacked volume - the only "sku" string in it is
  `androidboot.hardware.sku=`, which is a command line argument and not a
  matcher - so `GetSoftSkuMatchDtb` and the `CurDtSkuId == BoardSoftSkuId ()`
  term of `platform_dt_absolute_match` are not in this ABL. The entry below
  about `SkuId` is therefore moot on this device.

- **There are two matchers, and the dtbo decides which one runs** — Verified
  against the sources. `BootLinux.c` calls `LoadAndValidateDtboImg`, which
  returns true when the dtbo image is *good* despite being assigned to a
  variable called `DtboImgInvalid`. A readable dtbo takes `GetSocDtb` +
  `GetBoardDtb` + `ApplyOverlay`; an unreadable one takes
  `DeviceTreeAppended`, which selects a tree out of the dtb area and applies no
  overlay at all. That second branch is the one a mainline kernel needs, and
  the way to reach it is a dtbo without the magic - which is what
  `fastboot erase dtbo` does, and what `scripts/no-dtbo.py` now writes.
- **An empty dt table is the one shape that cannot work** — Verified against
  the sources, and this is the 2026-10-06 result explained.
  `LoadAndValidateDtboImg` checks the magic, the total size against zero, the
  header size, the entry size, the entry offset and the entry count against the
  partition size; `dt_entry_count = 0` passes all six. ABL therefore trusts the
  image, commits to the overlay branch, and `GetBoardDtb` loops zero times,
  leaves `BestDtbInfo.Dtb` NULL and returns it, which `BootLinux.c` turns into
  `EFI_NOT_FOUND`. Overlays for the wrong SoC would have been harmless - Sony's
  table carries fourteen such, for Montague and Ravelin - so long as one entry
  matches.
- **The strict matcher wants four fields exactly** — Verified against the
  sources. `platform_dt_absolute_match` keeps a tree only if its SoC id equals
  `BoardPlatformRawChipId() & 0xffff`, its platform type equals
  `BoardPlatformType()`, its platform subtype equals `BoardPlatformSubType()`,
  its DDR bits equal `BoardPlatformHlosSubType() & 0x700` and its `SkuId`
  equals `BoardSoftSkuId()`; the SoC revision, the packed major/minor version
  and the PMIC revisions need only be less than or equal. Zero is not a
  wildcard. This is why the stamp moved from `<0x0 0x0>` to `<0x1000b 0x0>`.
- **Two of those fields are free** — Verified against the sources. The foundry
  id, bits 23:16 of `qcom,msm-id`, is not part of the absolute match at all and
  is handled afterwards by `platform_dt_absolute_compat_match`, which prefers an
  exact match and falls back to zero - so leaving it zero is safe even though
  this chip reports `foundry_id` 3. And for a tree with no `qcom,pmic-id`,
  `DeviceTreeCompatible` fills the entry's PMIC revisions in from
  `BoardPmicTarget()` itself, so they compare equal by construction.
- **`SkuId` is never read from the tree** — Verified against the sources, and
  moot on this device. In the published sources `DeviceTreeCompatible`
  populates `platform_id`, `variant_id`, `board_hw_subtype`, `soc_rev`,
  `pmic_rev`, `offset`, `size` and `Idx`, and never `SkuId`, so the absolute
  match's `CurDtSkuId == BoardSoftSkuId ()` would need the board to report zero.
  That was the one field nothing here could check - and the binary says the term
  does not exist in this build at all. Recorded because a newer ABL would
  reintroduce it.
- **The exact-match shortcut cannot be reached here** — Verified against the
  sources. `GetSocDtb` sets `DtboNeed = FALSE` and skips the overlay entirely
  when a base satisfies `CheckAllBitsSet`, which would have been the tidy route
  and leaves the stock dtbo alone. `ALL_BITS_SET` includes all sixteen
  `PMIC_MATCH_EXACT_MODEL_IDX0..F` bits; those are set only from
  `qcom,pmic-id`, no base tree on this device carries one, and `PmicMaxIdx` is
  capped at `0xF` by `MAX_PMIC_IDX`, one short of the sixteen needed.
- **The board's DDR type is 0** — Reasoned from the device's own selection, not
  read. It is bits 10:8 of the subtype cell and appears nowhere in
  `/sys/devices/soc0`. The overlay stock Android booted is "Parrot QRD",
  `<0x1000b 0x0>`; the table also holds "Parrot QRD 4GB DDR", `<0x1000b 0x600>`,
  identical in every scored field except the DDR type and earlier in the table,
  so it would have won an exact DDR match and also won a tie on equal scores.
  It lost. `dtb-stamp-ids.py` sweeps all eight values anyway, in one property,
  for 56 bytes.

## The second mainline flash: the kernel gets control

Run on 2026-10-06, after the section above was read. This is the first time
anything of ours has been handed the CPU, so unlike the first flash, some of
what follows *is* evidence about the kernel and the device tree.

- **ABL accepts the images and selects our own device tree** — Verified. No red
  screen. The flash was clean: `vbmeta_a` 64 KB, `dtbo_a` 4 KB, `boot_a`
  27,924 KB, `vendor_boot_a` 13,464 KB with a 30,540-byte dtb area, then
  `Setting current slot to 'a'`. The two changes that did it were the dtbo the
  bootloader cannot parse, which forces the appended-device-tree path and so
  applies no overlay, and board ids stamped for that path's strict matcher
  rather than the lenient one stock takes. Both are argued from ABL's sources
  in the previous section.
- **The kernel resets repeatedly and the bootloader falls back on its own** —
  Verified. 158 seconds after `fastboot reboot`, adb answered on slot `_b`:
  the retry counter ran down, the slot was marked unbootable and stock Android
  came back without a button press. The screen was black throughout.
- **Each attempt is on the order of fifteen seconds** — Reasoned, not measured.
  The 158 seconds covers seven failed attempts *plus* stock's own boot to adb.
  Taking stock at 45 to 60 seconds leaves roughly 14 to 16 seconds per attempt,
  a few of which are ABL itself. Nothing timed an individual attempt, so treat
  this as an order of magnitude and not a number.
- **This failure mode is hands-free, and that changes the economics** —
  Verified. A red state leaves nothing on the bus and costs a Power+VolUp by
  hand. This one returns adb by itself in under three minutes. Rounds against
  a kernel that resets are cheap in a way rounds against ABL never were.
- **The kernel produced no output of any kind** — Verified. No fastboot, no
  adb, no USB gadget at any point during the seven attempts, and
  `/sys/fs/pstore` was mounted and empty afterwards.
- **The `PMBOOTLOG` in `rddata` is stale and says nothing about this boot** —
  Verified, and worth writing down because it is a trap. The harvest prints it,
  and it reads `Linux version 5.10.269-gki`, built `Mon Oct  5 12:53:44 UTC
  2026`, `Machine model: Qualcomm Technologies, Inc. Parrot QRD`. That is
  downstream output from the day before. The mainline kernel has no UFS driver,
  so it cannot have written to `rddata` at all, and any round that appears to
  find a log there has found the previous one.

## Every output channel but one is closed

Established on 2026-10-06. This is the central constraint on mainline bring-up
here and the reason a silent reset is so expensive: there is exactly one way to
see anything, and it is downstream of the failure.

- **RAM cannot carry anything across a reset** — Verified 2026-10-05, and it
  closes a route that looks obvious. Since we control our own device tree, the
  tempting plan is to reserve ramoops at `0xffd00000`, the address downstream
  uses, let the mainline kernel panic into it, and read `/sys/fs/pstore` from
  the downstream kernel after the automatic fallback. It cannot work. The
  binding itself is fine - TWRP's own kernel reserves the region, prints
  `printk: console [ramoops-1] enabled` and writes to it - but reboot TWRP into
  TWRP, a clean warm reboot with nothing of ours involved, and the records from
  seconds earlier are gone. The bootloader scrubs DRAM, so a cross-kernel
  handoff would hand the second kernel zeros.
- **There is no UART to reach** — Verified earlier. `chosen/stdout-path` names
  `/soc/qcom,qup_uart@98c000` and the mainline cmdline sets
  `earlycon=qcom_geni,mmio32,0x98c000`, so the kernel is talking; the pads are
  simply not broken out on this board. The earlycon stays in because it costs
  nothing and would be the first thing to pay off if that ever changes.
- **The bootloader's framebuffer cannot be used as a console** — Verified
  2026-10-06, and this one took a single adb call to settle. ABL does leave a
  live framebuffer: `reserved-memory/splash_region`, labelled
  `cont_splash_region`, at `0xb8000000` for `0x2b00000` - 43 MiB, enough for
  four 1080x2520 buffers at 32bpp - and carrying no `no-map`. That invites a
  `simple-framebuffer` node under `/chosen` plus `simpledrm` and `fbcon`, which
  is how postmarketOS gets a console on a device with no display driver. It
  will not work here, because the panel is command mode:
  `/sys/class/drm/card0/card0-DSI-1/modes` reads `1080x2520x60cmd`. A
  command-mode panel does not scan out continuously; each frame has to be
  pushed over DSI by the DPU. `simpledrm` only writes memory, and nothing would
  push it, so the glass would keep showing ABL's last frame no matter what the
  kernel wrote. This is also why "black screen" is not itself informative.
- **The USB gadget in the initramfs is the only channel** — Verified by
  construction. `pmos.debug-shell` stops the boot in the initramfs and brings
  up telnet on 172.16.42.1:23 and a CDC-ACM port, and `try-kernel.sh` already
  watches for the gadget as its win condition. It is a good channel - a live
  shell on a running kernel beats any post-mortem - but it lives in userspace,
  so reaching it is exactly the thing that is failing. Until the kernel
  survives to `/init` there is nothing to read, anywhere.
- **The SD card reopens a channel that survives a reset** — Reasoned, on
  2026-10-07, once the kernel was reaching `/init`. The heading above was
  written while it was not. A kernel that runs the initramfs can write to
  storage, flash survives the bootloader's scrub, and the card is the one
  piece of storage mainline can reach. "A log that survives on the card"
  below is that channel. It is still downstream of `/init`, so it says
  nothing about a kernel that dies before userspace.

## A log that survives on the card

The log hook used to write only to `rddata`, which is on UFS. Mainline has no
UFS driver, so a mainline round ran with `BOOTLOG=0` and kept nothing. This
section is the replacement. It was written on 2026-10-07, once reliable logs
had become the priority.

- **The log goes to the SD card first, and `rddata` is the fallback** — Done
  2026-10-07, in `scripts/bootlog.py`; tested under busybox ash against a
  sparse 477 GiB stand-in with a fake sysfs, not yet run on the device. The
  card is the only storage both kernels can reach: `sdhci-msm` is builtin on
  mainline (`CONFIG_MMC_SDHCI_MSM=y`, `CONFIG_MMC_BLOCK=y`), and `sdhc_2` is
  described in our tree. The hook waits for the card and settles for `rddata`
  only once 20 seconds have passed without one. That fallback is for a
  downstream boot that is missing its card.
- **The region is raw space past the rootfs, and every write re-proves it** —
  Verified, from the card's geometry read off the phone. The card has
  1000243200 sectors, and the GPT has `pmOS_root` as p1, from 1 MiB to
  16385 MiB, with nothing after it. `resize_root_partition` never grows p1.
  The log region starts at 32 GiB, sector 67108864, and runs for 2049 blocks
  of 64 KiB, which is 128 MiB and one block. Before every write, not just the
  first, the hook checks three things: the disk is exactly 1000243200
  sectors, p1 exists, and no partition overlaps the region. The p1 check is
  there because the disk appears in sysfs a moment before its partitions do,
  and an empty partition list would pass the overlap test vacuously. If any
  check fails, nothing is written. All of these were tested:
  - a partition overlapping the region's first sector is refused;
  - so is one reaching a single sector into its last;
  - one starting just past its end is allowed;
  - a card one sector too big is refused;
  - with p1 missing, the hook waits for it;
  - when p1 appears late, the hook writes once it has.
- **One slot per attempt, so a whole round fits** — Done, tested. Block 0
  of the region holds a counter, `PMBOOTCTR n`. Each boot reads it, adds one
  and writes it back before anything else. The boot then logs to slot
  `(n - 1) mod 8`, so a round's seven attempts keep seven separate logs, and
  the decoder labels each by its attempt number. In ten simulated boots,
  attempts 9 and 10 wrapped onto slots 0 and 1, as designed.
- **A reset in the middle of a write cannot cost the log** — Done, tested.
  Each slot has two halves of 8 MiB, and the hook writes them alternately,
  once a second. The half being written is always the older one, so the
  newest complete record is always in the other. `dd conv=sync` pads each
  record's last block with zeros, so a record always ends in a zero and
  cannot run on into an older one under it. Each record ends with
  `--- end seq=N attempt=C md5=...`, the md5 of everything above that line.
  The decoder takes the newest record whose md5 checks out. Two cases were
  tested:
  - a bit flipped inside the newest record;
  - a fresh header written over an older body, which is how a torn write
    looks when the record is spliced.

  In both, the decoder fell back to the record before and still called it
  complete.
- **What a record holds** — Done. The header line, then:
  - `/proc/version`, so the two kernels cannot be confused;
  - the boot id, the command line and the last init mark from `/pmmark`;
  - `dmesg`;
  - `/pmOS_init.log`;
  - the loaded modules;
  - the deferred-probe list;
  - every UDC with its `state`, and what the gadget is bound to;
  - every platform device with its driver;
  - `/proc/interrupts`;
  - the power-domain and regulator summaries, which are software state;
  - the clock summary, only on our own tree. There the only providers are
    GCC and RPMh, whose registers are always on. Stock's tree also has GPU,
    display and camera controllers behind power domains that may be off,
    and a read from one of those can hang the bus, log and all. This is
    what will say whether the HS PHY's CLKREF gate ever came on.

  The hook is armed right after `mount_proc_sys_dev` and writes for ten
  minutes, which outlasts the USB watchdog. A boot the watchdog resets
  therefore leaves a record from the second before.
- **Since 2026-10-05 the hook had been armed in the wrong place** —
  Verified in the image round 19 flashed, and fixed. `install` put
  `. /bootlog.sh` after the first `mount_proc_sys_dev` followed by a newline.
  Since 22859f2, which moved the USB watchdog to the top of `/init`, that
  match has been a comment line in the watchdog's block. So the hook was the
  first thing `/init` ran: before `busybox --install` and before `/proc`,
  `/sys` and `/dev` were mounted. Its wait loop counts iterations and gives
  up after 120. With no `sleep` applet yet, nothing slowed it down, so it
  could spend all 120 before the applets existed and quit for good. No
  recorded log was lost to it. The last downstream logs on disk predate the
  change, and every round since has been mainline, with no UFS to write to.
  It would have cost the card channel its first round. `install` now anchors
  on the call on a line of its own, and refuses an init where that comes
  before `busybox --install`. The hook's `sleep`s now go through
  `/bin/busybox` directly.
- **The hook runs under Alpine's own busybox** — Done, tested. The suite
  above was run again under busybox 1.38.0 from the native chroot, through
  its musl loader. That is the build the initramfs ships, for x86_64 instead
  of aarch64. Every case passed, including a clear followed by a boot whose
  p1 appears late, which restarted cleanly at attempt 1.
- **The USB watchdog waits for a write in flight** — Done, tested under
  busybox. The hook holds `/pmbl.busy` for the length of each `dd`. Before
  resetting, the watchdog waits up to two seconds, in tenths, for that file
  to go. The halves already protect the log from a torn write. This protects
  the card: the reset is a warm one, nothing guarantees the card loses power
  cleanly in the middle of a write, and the rootfs is on it too. A record
  write takes a fraction of a second, so the rung timing `markdecode` reads
  moves by less than its resolution. Without the hook there is no file, and
  nothing changes.
- **`rddata` now uses two halves as well** — Done, tested. The records sit at
  0 and 8 MiB, 16 MiB of the 20, so the downstream fallback has the same
  protection against a torn write. A dump from the old single-record hook
  still decodes, labelled `old`, because it has no md5 to check.
- **Whether the card comes up on mainline is unknown** — Guess. The node has
  `cd-gpios` on GPIO 107, `vmmc` and `vqmmc` on `pm6150l` L9 and L6, the
  `sdc2` pin states and an OPP table borrowed from SM6350. It has never been
  seen to probe. The missing interconnect provider should not stop it:
  without an `interconnects` property, `sdhci-msm` has nothing to vote.
  A region left untouched after a round means one of two things: the card
  never came up, or the boot died within two minutes of `/init`. The USB
  watchdog's total tells those apart.
- **The SD card's two rails were allowed far above what stock gives them** —
  Verified against the stock tree, and fixed in the series on 2026-10-07,
  before any round had the card hook on. Our board file had copied the
  limits of stock's regulator nodes: L6, the IO rail, 1.65 to 3.3 V, and
  L9, the card's supply, 2.7 to 3.544 V. Stock never goes near the top of
  either. Its `sdhci-msm` narrows them itself, with
  `qcom,vdd-voltage-level = <2960000 2960000>` and
  `qcom,vdd-io-voltage-level = <1800000 2960000>`, and the SD controller is
  the only consumer of both rails. Mainline has no such property. The MMC
  core takes the regulator's own limits as the range it may use, so it
  would have put the card at about 3.4 V and the IO rail at about 3.1 V.
  The board file now carries stock's consumer ranges, L6 1.8 to 2.96 V and
  L9 2.7 to 2.96 V. Upstream's Fairphone 4 and Xperia 10 III use the same
  PMIC for the same two rails, and both cap them the same way, at 2.95 and
  2.96 V. The fix is squashed
  into the board commit; `out/milestone/clkref-sdvolt.dtb` is the CLKREF
  tree with it, and differs from `clkref.dtb` in those three values alone.
- **The ring buffer was only 128 KiB up to pkgrel 4** — Verified in the
  config (`CONFIG_LOG_BUF_SHIFT=17`). A mainline boot that logs every probe
  can wrap it, losing the earliest lines first, and those are the ones a
  post-mortem wants. `try-kernel.sh` adds `log_buf_len=4M` to the command
  line whenever it installs the hook, which allocates 4 MiB at boot and
  copies the early messages into it. Building the size in instead, as
  pkgrel 5 did, costs 14 MB of kernel image; see "The mainline kernel
  package".
- **`try-kernel.sh --log` reads the card back, and each round is labelled**
  — Done 2026-10-07, and run against the device the same night. In recovery it runs
  the one line that `bootlog.py card-sh read` prints, through
  `adb exec-out`. That line finds the card with the hook's own checks and
  reads nothing if none passes. It then decodes the region: the newest
  complete record of every attempt goes to the screen, and every record to
  `out/try-kernel/bootlog-card-<time>.txt`. Then it clears the counter and
  the first block of every half with `card-sh clear`, so the next round
  starts at attempt 1. `rddata` is read in full, both halves, and cleared
  the same way. When it installs the hook, `try-kernel.sh` also puts
  `pmbl.round=<time>` on the command line, which every record carries, so a
  record left over from an older round cannot pass for this one's.

  Its first run on the device stopped at 24 MB of the card's 134, and then
  lost adb before it read `rddata`. Recovery brings adb up and then, four
  seconds later, re-enumerates USB as it settles its gadget configuration:
  product `0xd001` and then `0x4ee2` in the host's log. The read had started
  in that gap. `--log` now waits until adb has answered every second for ten
  seconds in a row, and reads again if a read comes back short. Verified the
  same night: from recovery, both regions read whole, 134,283,264 and
  16,777,216 bytes.

## Why the kernel resets

Still unknown. The first candidate was reasoned out on 2026-10-06, flashed the
same day, and refuted - the entries below keep it because the reasoning was
sound and the refutation is the useful part. What it rules out is worth as much
as what it would have fixed.

- **The `late_initcall_sync` teardown is not the cause** — Verified 2026-10-06
  by flashing it. `clk_ignore_unused pd_ignore_unused regulator_ignore_unused`
  went into the cmdline and `verify-bootimg.py` confirmed all three reached the
  image. The device then behaved *identically*: adb answered on slot `_b` after
  158 seconds, the same figure as the round before, to the resolution of a
  2-second poll. The flags stay on - they are correct for a tree this young
  regardless - but they explain nothing.

  What this does *not* establish is where the kernel dies, and an earlier
  version of this entry claimed it did. The argument was that a kernel which
  got past the clock and genpd passes and died later would have shifted the
  per-attempt time. That is wrong: these flags change behaviour, not timing,
  and if the teardown was never the thing killing us then nothing about the
  timing should move no matter where the death is. The flags rule out the
  teardown as a cause. They locate nothing.
- **`rddata` is now a clean instrument** — Verified. The round read it and
  found 0 non-zero bytes in 1 MB, then cleared it. The stale downstream
  `PMBOOTLOG` that the previous round printed is gone, so a future round that
  finds something there has genuinely written it.
- **The kernel panics; it is not a hardware reset** — Verified 2026-10-06, and
  this is the first positive thing known about the failure. A panic and a
  hardware reset look identical from the host - the phone reboots - but they
  point opposite ways, so they had to be separated before anything else was
  worth trying. The cmdline does it for free: `panic_timeout` waits that many
  seconds before rebooting (`kernel/panic.c:558`) and a hardware reset waits
  for nothing, so the number is an output channel one digit wide. `panic=5`
  gave 158 seconds. `panic=60` was predicted to give about 543. It gave **540**.

  That single number settles three things. The panic path runs, so the kernel
  is alive, `printk` works and the console is merely going nowhere - this is a
  software fault, not a bad register write, the watchdog, or TZ. The retry
  count really is seven: 540 - 158 = 382, and 382/55 = 6.95. And subtracting
  the panic delays leaves `7 x (ABL + kernel) + stock = 123` seconds, so with
  stock booting to adb in 40 to 60 seconds, ABL plus kernel is 9 to 12 seconds
  per attempt. ABL alone reaches fastboot in 6, which leaves the kernel running
  for something like 3 to 6 seconds before it gives up.
- **`panic_on_oops=1` is not a kernel parameter and never did anything** —
  Verified 2026-10-06, by reading `kernel/panic.c` rather than assuming. The
  `core_param` list there covers `panic`, `pause_on_oops`, `panic_on_warn`,
  `crash_kexec_post_notifiers`, `panic_console_replay` and `panic_print`.
  `panic_on_oops` is not among them; the only cmdline route to it is
  `early_param("oops", ...)`, which accepts `oops=panic` and nothing else. So
  the `panic_on_oops=1` this project has been passing since the first mainline
  round was handed to init as an environment variable and ignored by the
  kernel. `CONFIG_PANIC_ON_OOPS` is not set either, so `panic_on_oops` has been
  0 throughout.

  That is not a harmless typo, because it changes what the panic *is*. With
  `panic_on_oops` at 0 an oops prints and the kernel carries on, so the panic
  the timing proves cannot be an oops promoted to a panic. Something is calling
  `panic()` outright. It is being removed rather than corrected to `oops=panic`:
  a non-fatal oops is strictly better for bring-up, because a kernel that
  survives one may still reach `/init`, where the only real output channel is.
- **Stock Android boots to adb in 30 seconds** — Verified 2026-10-07 by
  measuring it, which is worth doing because it is the constant in every
  equation on this page. `adb reboot` out of recovery to an `adb devices` that
  reads `device`: 30 seconds. Every total below is seven failed attempts plus
  this.
- **The timing model closes** — Verified 2026-10-07. Subtracting the 30 and
  dividing by seven gives the per-attempt cost, and taking each round's own
  deliberate delay off that gives what the boot itself costs:

      panic=5                  158s   18.3s per attempt   13.3s of boot
      panic=60                 540s   72.9s per attempt   12.9s of boot
      STAGE=1, panic=60        540s   72.9s per attempt   12.9s of boot
      PROBE sleep 1, panic=60  542s   73.1s per attempt   72.1s of boot
      PROBE sleep 8, panic=60  362s   47.4s per attempt   39.4s of boot
      PROBE sleep 8, panic=60  540s   72.9s per attempt   64.9s of boot

  The two panic rounds agree to within 0.4 seconds on a quantity neither was
  measuring, which is a real check on the whole method and on seven being the
  retry count. So ABL plus kernel to the panic is about 13 seconds.

  The last column is only meaningful for a round that reached its own delay,
  which is the point of the next entry.
- **The kernel does not reach `/init`, and an earlier version of this document
  said it did** — Verified 2026-10-07 by running the same round twice. The
  claim rested on one point in that table. `bootlog.py probe` replaces `/init`
  with `sleep 8; reboot -f`, and that round came back at 362 rather than the
  panic's 540, which would mean changing only the initramfs changed the
  outcome. Two rounds were run to test it and both refute it: at sleep 1 the
  total was 542 - and lowering the sleep cannot raise the total if the probe is
  running - and repeating sleep 8 unchanged gave 540.

  So four of the five `panic=60` rounds sit within 2 seconds of
  `7 x (12.9 + 60) + 30`, across initramfs contents that differ as much as a
  four-line reboot script differs from the real pmOS init. 362 did not
  reproduce and has no explanation; the honest reading is one bad measurement,
  and the conclusion commit 1558974 recorded is superseded by this entry.

  What follows from the four that agree is the opposite of what was claimed:
  the panic happens before `/init` and nothing in the initramfs reaches it.
  That is the worse branch - the fault is still in the kernel or the tree
  rather than in a script we can edit - but it is the one the evidence
  supports.
- **The panic is after `parse_args`, which rules out the early arch code** —
  Reasoned from the source, 2026-10-07, and it is the one thing the timing
  does establish about position. `panic` is a `core_param`, so it is parsed by
  the `parse_args("Booting kernel", ...)` call in `start_kernel` and not by
  `parse_early_param`. `panic_timeout` is therefore still 0 for the whole of
  `setup_arch`, and a panic there would reset at once rather than wait.
  `panic=5` and `panic=60` gave 158 and 540, so the value was in effect: the
  kernel got through `setup_arch` - which means the memory map it was handed
  is workable - and through `parse_args`, and died after. That leaves
  `init_IRQ`, `time_init`, the initcalls, and `kernel_init` itself.
- **The `/memory` node has size zero and the bootloader is expected to fill it
  in** — Verified 2026-10-07 against the live tree. This is a trap worth
  writing down even though the entry above exonerates it. Our tree says
  `reg = <0x0 0x80000000 0x0 0x0>`, which is the idiomatic upstream Qualcomm
  board pattern and useless on its own. The tree ABL handed the stock kernel
  has a seven-entry `reg` adding up to the 7.2 GiB the running phone reports,
  plus a `ddr_device_type` ABL put there itself, so ABL does patch memory in
  on this device; and libfdt resolves the path `/memory` against a node named
  `memory@80000000`, so our unit address is not a problem either. Had the
  panic been before `parse_args`, this is where to have looked first.
- **The initramfs is not failing to execute for want of a binfmt** — Verified
  2026-10-07 in the shipping config. Every `/init` this project has flashed is
  a `#!` script, which makes "the kernel cannot exec any of them" a hypothesis
  that fits "the initramfs contents make no difference" exactly, and it would
  end in `panic("No working init found")`. It is wrong:
  `CONFIG_BINFMT_SCRIPT=y`, `CONFIG_BINFMT_ELF=y`, `CONFIG_BLK_DEV_INITRD=y`,
  `CONFIG_DEVTMPFS=y` and `CONFIG_TMPFS=y` are all set, and
  `CONFIG_INITRAMFS_SOURCE` is empty, so nothing is competing with the
  initramfs the bootloader passes.
- **The repacked `vendor_boot` declared a self-contradicting ramdisk table,
  and that was not it either** — Verified 2026-10-07 and fixed. A v4 vendor
  ramdisk table entry begins `{ramdisk_size, ramdisk_offset}`, and
  `bootlog.py` wrote the recompressed length to offset 4 instead of 0. Every
  image this project has flashed therefore said its single ramdisk fragment
  was 13857010 bytes long and started 13739256 bytes into a section 13739256
  bytes long. Stock says `ramdisk_size=10002117, ramdisk_offset=0`.

  It cost nothing: a downstream probe round completed seven 8-second sleeps
  through exactly this image shape, so ABL does not consult the table when
  there is one entry, and it takes the length from the header field - which
  was always right. Both repack paths now go through one function and write
  offset 0, because a tool that emits a header contradicting itself is a trap
  for whoever reads it next looking for a cause.
- **`STAGE=1` did not survive either, and it came back at 540 again** —
  Verified 2026-10-07. That is the same figure as the plain panic round, which
  is the one number it could least afford to be. The staged init carries its own
  stall watchdog that resets the phone after fifteen seconds of no progress,
  and it encodes the step it reached as extra seconds before that reset, so a
  staged init that ran and stalled anywhere would have produced a total of
  `7 x (12.9 + 15 + index) + 30`. Exactly 540 corresponds to index 45. Our
  image has no index 45: `bootlog.py stages` on it lists 1 to 9, then jumps
  straight to 60, because `modules-initfs.mainline` is empty and the module
  steps in between are generated from it. So the encoding was never reached,
  and 540 is instead `7 x (12.9 + 60) + 30` - the panic again, with the staged
  init dying effectively the moment it started.
- **`bootlog.py stages` is calibrated for the downstream kernel** — Verified,
  and it will mislead anyone who reads a mainline round with it. `ATTEMPT_FIXED
  = 18 + 15` and `FALLBACK_BOOT = 35` are downstream's numbers. Mainline's are
  12.9 and 30, measured above, so the decoder reported "index about 39" for a
  round whose own arithmetic says 45 and whose real explanation is a panic.
  Nothing has been changed yet, because the constants are right for the kernel
  they were written for and a second set needs the kernel to be selectable.
- **Nothing in the initramfs runs, and the next cheap question is the device
  tree** — Reasoned 2026-10-07. An earlier entry here read "an init that does
  nothing runs; an init that does something does not", on the strength of the
  362. With that withdrawn there is no evidence any init has ever run, and the
  search moves back into the kernel and the tree.

  The tree is the cheap half of what is left. A device tree costs one `dtc`
  invocation, against a couple of minutes for a kernel (this entry said 63,
  which was a cold build under emulation - see "The whole SM6450 series
  builds clean"), and the tree is also the half that was written by hand. `scripts/dt-reduce.py` builds
  variants by giving nodes `status = "disabled"` or deleting them outright,
  working on `dtc -I dtb -O dts` output rather than on our source, so that
  neither kbuild nor the C preprocessor is involved and a variant differs from
  the shipped tree only where it was edited. That round trip is exact,
  verified 2026-10-07: decompiling and recompiling the shipped tree with no
  edits reproduces all 30410 bytes. `try-kernel.sh` takes `DTB=path` to flash
  one.

  The first variant disables every child of `/soc@0` but three - the GIC, the
  memory-mapped timer and the watchdog - along with the smp2p nodes, the
  reboot-mode nvmem and the gpio keys, and deletes the thermal zones. The
  watchdog stays because it has to: the kernel adopting and petting the
  bootloader's watchdog is what lets a `panic=60` wait run its full 60
  seconds, and that wait is the ruler every number on this page is measured
  with.
- **Nothing we wrote into `/soc@0` is the cause** — Verified 2026-10-07 by
  flashing the reduced tree above. Fifteen of the eighteen children of
  `/soc@0` were disabled, which is the clock controller, the pinctrl driver,
  the SPMI arbiter and every regulator under it, USB and its HS PHY, the
  SDHCI controller, the SMMU, the rpmh RSC, EPSS cpufreq, the PDC, the AOSS
  QMP, IPCC, the TCSR mutex, the GENI QUP and the rpmh stats; the smp2p nodes,
  the reboot-mode nvmem and the gpio keys went with them and the thermal zones
  were deleted outright. Readback of the flashed image confirms three live
  children and the bootloader ids still stamped.

  The round came back at **540 seconds**, which is the panic baseline to
  within 2. Both halves of that matter. The outcome did not change, so none of
  those nodes is what calls `panic()`; and the *timing* did not change either,
  which is the stronger half - a tree where almost nothing probes should reach
  the end of its initcalls sooner than one where everything does, and this one
  did not move at all. That is the signature of a fixed-cost path: bootloader,
  kernel init, and then a panic that does not depend on what probed.

  Taken with the initramfs making no difference, that leaves the end of the
  boot. Both panics there are reachable with no device at all:
  `panic("VFS: Unable to mount root fs on %s")` at `init/do_mounts.c:236` if
  the initramfs gave the kernel no `/init`, and `panic("No working init
  found.")` at `init/main.c:1505` if it gave it one that cannot be executed.
- **`rootdelay` separates those two without a rebuild and without risking a
  hang** — Reasoned from the source, 2026-10-07, and this is the round in
  flight. `kernel_init_freeable` calls `prepare_namespace()` only when
  `init_eaccess(ramdisk_execute_command)` fails (`init/main.c:1565`), so
  whether that function runs at all *is* the question "did the initramfs
  provide a usable `/init`". And `root_delay` is spent at the very top of it,
  `ssleep(root_delay)` before anything else (`init/do_mounts.c:466`), so it
  costs exactly N seconds per attempt if and only if that path is taken.

  `rootdelay=30` went on with the reboot probe as `/init` and `panic=60`
  unchanged. About 750 seconds - `7 x (12.9 + 30 + 60) + 30` - would mean the
  initramfs never gave the kernel an `/init`. Unlike the obvious test for the
  same thing, `root=/dev/... rootwait`, which turns the panic into an unbounded
  wait, this one needs no button press: `rootdelay` sleeps and then carries on
  to the same panic.
- **`prepare_namespace` does not run, which has two readings** — Verified
  2026-10-07. The `rootdelay=30` round came back at 540, the same figure as
  every other `panic=60` round, so those 30 seconds were never spent and that
  function was never called. Either the initramfs *did* give the kernel an
  accessible `/init` and the panic is somewhere after the check at
  `init/main.c:1565`, or the kernel never got as far as the check at all and
  the panic is before it - in `smp_init`, the initcalls, `kunit_run_all_tests`,
  `wait_for_initramfs` or `console_on_rootfs`.

  Nothing in the round distinguishes those, so the next one is a positive
  control for it: `rdinit=/nonexistent` makes `init_eaccess` fail by
  construction, since `rdinit=` is what sets `ramdisk_execute_command` and it
  defaults to `/init`. With `rootdelay=30` still on, 750 then proves the check
  is reached and 540 proves it is not - the same measurement run against a
  known answer, which is the only way a one-bit channel can be trusted.
- **The initramfs we are flashing is sound, down to the symlink the shebang
  needs** — Verified 2026-10-07 by unpacking the image that was flashed, which
  is worth doing before blaming the archive for anything. The vendor ramdisk
  gzip-decompresses to 29,959,680 bytes with a matching ISIZE trailer and
  parses as 363 cpio entries. `/init` is a 240-byte regular file, mode 0755,
  starting `#!/b`. pmOS uses the merged-`/usr` layout, so the shebang's
  `/bin/busybox` resolves through `bin -> usr/bin`, which survives our repack
  as a real symlink; `usr/bin/busybox` is mode 0755 and
  `usr/lib/ld-musl-aarch64.so.1` is present for it to interpret against.

  Worth noting for reading any "No working init found" panic: the kernel's
  fallbacks after `/init` are `/sbin/init`, `/etc/init`, `/bin/init` and
  `/bin/sh`, and this archive has none of them - `sbin` is a symlink to
  `usr/bin`, which contains no `init` and no `sh`. So an `/init` that will not
  exec goes straight to that panic with nothing in between.
- **The bootloader ignores the load addresses in the vendor_boot header** —
  Verified 2026-10-07, and it closes a hypothesis that looked alarming for
  about ten minutes. The header asks for the kernel at base+0x8000, the
  ramdisk at base+0x1000000 and the dtb at base+0x1f00000, and our kernel is
  27.3 MiB, so a bootloader taking those literally would drop 13.1 MiB of
  ramdisk into the middle of the kernel image. Stock is worse: a 44.7 MiB
  kernel that would overlap both the ramdisk and the dtb. Stock boots, so ABL
  computes its own placement and these fields are decoration. Our three
  addresses are byte-identical to stock's anyway, since both come from the
  same `deviceinfo` offsets.
- **Command line experiments no longer cost a package rebuild** — Verified
  2026-10-07. For header v3 and later the kernel command line is not in
  boot.img, whose `cmdline` field is empty here, but in the vendor_boot
  header at offset 28, 2048 bytes, of which pmbootstrap's generated line uses
  240. `scripts/patch-cmdline.py` rewrites it in place - a single overwrite,
  nothing reflows, 11 bytes changed in a 13 MiB image for a `panic=` swap -
  and `try-kernel.sh` takes `CMDLINE_ADD` and `CMDLINE_DEL`. The conf file in
  `aports/` is still where anything that matters has to end up, because a
  round flashed from a patched image is not one anyone can reproduce from the
  sources; this is for asking questions, not for keeping answers.
- **The kernel never reaches the `/init` check at all** — Verified 2026-10-07
  by the positive control described above. `rdinit=/nonexistent rootdelay=30`
  came back at 538, not 750: even with `init_eaccess` guaranteed to fail, the
  30-second sleep at the top of `prepare_namespace` was never spent. So the
  panic is between `calibrate_delay()` (`init/main.c:1037`, proven by the
  0.992 delay-loop factor) and the access check at `init/main.c:1565`. The
  candidates in that window are `smp_init`, the initcalls,
  `wait_for_initramfs` and `console_on_rootfs`, and of those the one with a
  panic of its own is secondary bring-up: `cpu_panic_kernel()`, called from a
  capability conflict (`arch/arm64/kernel/cpufeature.c:3577`) or a short ASID
  field (`arch/arm64/mm/context.c:75`), ends in
  `panic("CPU%u detected unsupported configuration")` at
  `arch/arm64/kernel/smp.c:170`.
- **`maxcpus=1` does not stop it** — Verified 2026-10-07, over three rounds,
  and the first of them said the opposite. With the probe sleeping 8 seconds,
  `maxcpus=1` came back at 138 once; with a 1-second sleep, at 540; repeated
  exactly as the 138 round, at 542. Two out of three are the ordinary
  all-panic figure, so secondary bring-up is not where the panic is, and the
  138 needs explaining on its own.
- **Every attempt ends one of two ways, and the mix varies from boot to boot**
  — Reasoned 2026-10-07, from the totals alone, and it explains every figure
  this document has called an anomaly. With the constants the `panic=5` and
  `panic=60` rounds pin down - seven attempts, 12.9 seconds of fixed cost per
  attempt, 30 seconds for the stock slot to answer - a total can be solved for
  how many attempts waited out `panic=60` and how many reset almost at once:

  - 540 is 7.00 panics and no resets, every ordinary round.
  - 362 is 4.03 panics and 2.97 resets, the round recorded above as "reaches
    userspace" and then withdrawn.
  - 138 is 0.30 panics and 6.70 resets, the `maxcpus=1` round.

  Near-integers three times out of three, with no free parameter fitted to
  them, is a model rather than a coincidence. Each reset attempt costs about
  2.6 seconds of kernel time, too short to be the probe's 8-second sleep, so a
  short round is not a sign the kernel got further. It is a second failure
  mode: something resets the SoC before the kernel reaches `panic()`, on some
  boots and not others, from a byte-identical image. Two consequences. A
  single round is no longer a measurement, because the same image can land
  anywhere from 138 to 540. And anything that changes the mix looks like a
  result when it is luck, which is exactly how the 362 and the 138 were read.
- **KASLR is the only per-boot random input, and it is on** — Guess, under
  test 2026-10-07. `CONFIG_RANDOMIZE_BASE=y`, and ABL writes a fresh
  `/chosen/kaslr-seed` on every boot: the live tree has the property, eight
  bytes, zeroed, which is what the kernel leaves after consuming a seed. So
  every attempt runs the kernel at a different virtual base, and a fault that
  depends on the layout would come and go exactly like the reset mode does.
  `nokaslr` is read by the early pre-init code from the device tree's
  bootargs, which is where our command line lands, so it is a command-line
  round. If KASLR is the variable, `nokaslr` collapses every round to one of
  the two pure figures, and it has to do so twice before it counts.

  The first `nokaslr` round came back at 540, seven clean panics. That is what
  the guess predicts, but it is also what most rounds give anyway - about 10
  of the 77 attempts so far reset rather than panicked - so it is weak
  evidence and settles nothing. It does not need settling to move on: the
  panic is the failure that happens every time, and the reset mode only
  matters because it corrupts the reading. So every instrumented round from
  here carries `nokaslr`, and a total that does not decode cleanly gets
  repeated rather than read.
- **The milestone kernel is the next instrument** — Reasoned, built
  2026-10-07. Command-line knobs have bounded the panic to
  `init/main.c:1037..1565` and cannot get closer, because nothing between
  those lines takes a parameter that costs time. `bringup-milestones.patch`,
  a separate `source=` entry in the kernel aport and never part of the
  upstream series, makes the kernel write its progress into
  `panic_timeout`, inert unless `pmos.milestone` is on the command line. Run
  with `pmos.milestone panic=44 nokaslr`, the per-attempt panic wait reads
  as:

  - 44 seconds: no milestone was reached, so the panic is before the first
    one, right after `calibrate_delay()`.
  - 2 to 42 seconds, even: the last of 21 coarse marks through
    `start_kernel`, `kernel_init` and `kernel_init_freeable` that was
    passed, at twice its number. Mark 8 is just before `smp_prepare_cpus`,
    13 just after `smp_init`, 16 after `do_basic_setup`.
  - 48 seconds and up: the panic is inside the initcalls, and
    `48 + n/16` locates initcall `n` to within sixteen, to be read against
    the build's `System.map` order.

  Each attempt is `12.9 + timeout` and the round is seven of them plus 30, so
  one step of 2 seconds moves the total by 14, well above the 2-second poll.
- **The panic is in initcall 535, `qcom_wdt`** — Verified 2026-10-07 over two
  rounds of the milestone kernel. The decode needs the delay-loop factor
  measured earlier, because `panic()` waits with `mdelay`: each attempt costs
  `13.34 + 0.992 x timeout` seconds and the round is seven of them plus 30.
  Round 14, `pmos.milestone panic=44 nokaslr`, came back at 686: a timeout of
  81.02, initcall band 81, calls 528 to 543. Round 15 zoomed in with
  `pmos.milestone=512` and came back at 976: a timeout of 122.8, so 123, so
  call 535. In the flashed kernel's own initcall table, recovered from the
  image's kallsyms with `vmlinux-to-elf` because pmbootstrap discards
  `System.map`, call 535 is `qcom_watchdog_driver_init`. A driver
  registration only does something if a device matches, and one does:
  `watchdog@17410000`, `qcom,apss-wdt-sm6450`, in our `sm6450.dtsi`.

  The decode is now `out/milestone/zoom512-decode.txt`, generated from the
  table. The same 21 coarse marks and the zoom can be pointed anywhere else
  without a rebuild.
- **That register block belongs to the hypervisor** — Verified against the
  stock system, 2026-10-07. Android on this phone runs as a Gunyah VM: the
  live tree has `qcom,gunyah-hypervisor-1.0` with `qcom,vmid = <3>`. Its own
  MMIO watchdog node, `qcom,wdt@17410000`, is `status = "disabled"`, and the
  watchdog it actually uses is `qcom,gh-watchdog` under `/hypervisor`, driven
  by `gh_virt_wdt` - which is in the stock module list as loaded. The upstream
  Gunyah watchdog series says it outright: the hypervisor "doesn't allow its
  Virtual Machines to directly access the MMIO watchdog". The reading is that
  `qcom_wdt`'s probe touches a block Gunyah never mapped into our VM, takes a
  synchronous external abort, oopses in PID 1, and the kernel panics because
  init died. The mechanism is Reasoned; that disabling the node changes the
  outcome is the next entry.
- **With the watchdog node disabled, the kernel reaches `/init`** — Verified
  2026-10-07, over two rounds. Round 16 flashed the same
  kernel and command line as round 15 with one difference, a tree from
  `scripts/dt-reduce.py -d '/soc@0/watchdog@17410000'`, and came back at 180:
  8.1 seconds per attempt above the fixed cost, which is the probe's 8-second
  sleep. A panic here would have cost at least 32 and an immediate reset 2.6.
  This is the first round in this document where the probe has run.

  Round 17 is the slope test, the one that refuted the 362 earlier: the same
  image with the probe sleeping 20 seconds instead of 8. Predicted 264, came
  back 262, so 11.7 seconds more per attempt for a 12-second change. The
  probe ran on every attempt in both rounds.
- **The watchdog node is gone from the series** — Done 2026-10-07, in
  `kernel/patches/` and the aport, pkgrel 3. `sm6450.dtsi` no longer declares
  `watchdog@17410000`, and the `qcom,apss-wdt-sm6450` compatible came out of
  the bindings patch with it, since nothing would use it. Deleted rather than
  disabled because that is what upstream does on this generation: SM4450,
  SM8550, SM8650, SM8750 and SAR2130P have no APSS watchdog node either, and
  the ones that do (SM6350, QCS8300) predate or sit outside Gunyah. Both
  commits say why in their messages. The rewrite was a cherry-pick replay
  checked to differ from the old branch by exactly those eight lines, which
  is kept as `sm6450-pre-wdt-fix` in `out/linux`; the board DTB passes
  `CHECK_DTBS=y`.
- **What upstream does about it, and so what our tree should say** — Verified
  in the lists, 2026-10-07. The Gunyah watchdog is not a device-tree node
  upstream at all: `qcom_scm` registers a `gunyah_wdt` platform device
  itself, and only when no available `qcom,kpss-wdt` or `arm,sbsa-gwdt` node
  exists, so that an MMIO watchdog where one really works keeps priority. The
  SCM half was applied to the qcom tree by Bjorn Andersson on 2026-03-30; the
  driver went to watchdog-next. So the fix that survives review is to stop
  declaring an available APSS watchdog in `sm6450.dtsi` - the block exists,
  but this VM may not touch it - and to carry those two patches as backports
  to get a working watchdog back.
- **After that, `initcall_blacklist` can test the two generated drivers** —
  Reasoned. `CONFIG_KALLSYMS=y` is set, so the blacklist works, and the two
  hand-generated drivers are the dominant risk this document has named from
  the start: `initcall_blacklist=gcc_sm6450_init` disables the clock
  controller (`subsys_initcall`, `drivers/clk/qcom/gcc-sm6450.c:2766`) and
  `sm6450_tlmm_init` the pinctrl driver (`arch_initcall`,
  `drivers/pinctrl/qcom/pinctrl-sm6450.c:1102`). A wrong register offset in
  either is exactly the kind of fault that resets this SoC with nothing
  printed. Note the asymmetry in what the outcomes cost: if blacklisting one
  makes the resets stop, the kernel most likely hangs instead - no clock
  provider means almost every probe defers - and a hang needs a button press,
  because nothing resets it. That is the good branch, and it is worth the
  press.

- **Three subsystems switch off everything no driver claimed, at
  `late_initcall_sync`** — Verified in the source, and this is why it was the
  first candidate even though it turned out to be wrong. `clk_disable_unused`
  (`drivers/clk/clk.c:1558`), `genpd_power_off_unused`
  (`drivers/pmdomain/core.c:1392`) and `regulator_init_complete`
  (`drivers/regulator/core.c:6631`) all run after every driver has probed and
  before `/init` is executed. On a SoC this young almost nothing has been
  claimed, so what they tear down is most of the chip - including clocks and
  power domains that TZ, the modem and ABL's own live display are still using.
  Losing those is not a crash the kernel can report; it is a hardware reset,
  which is precisely the shape of what the device did.
- **The timing distinguishes the three** — Verified in the source. The clock
  and genpd passes run the moment `late_initcall_sync` is reached. The
  regulator pass does not: `regulator_init_complete` queues delayed work
  `msecs_to_jiffies(30000)` out, so it fires about 30 seconds later. A death at
  roughly fifteen seconds therefore cannot be the regulator pass - but a kernel
  that survives the first two will live long enough to meet it, which is why
  all three flags go on at once rather than costing a round each.
- **All three have a documented escape hatch, and using it is upstream
  practice** — Verified. `clk_ignore_unused`, `pd_ignore_unused` and
  `regulator_ignore_unused` are each a `__setup` in the file above. Upstream
  describes the first two as the bring-up workaround in as many words: "we need
  to use these two kernel command line arguments (clk_ignore_unused &
  pd_ignore_unused) to skip disabling clocks and genpd power domains as part of
  late init for initial version". They are bring-up only and should come off one
  at a time, late, once the drivers that ought to hold these votes exist.
- **The kernel is not being handed memory the firmware still owns** — Verified,
  and this was the first hypothesis, discarded. A kernel allocating into TZ or
  modem memory would also reset in seconds with no output. But `sm6450.dtsi`
  reserves all 34 regions the live tree reserves, node for node and `no-map`
  for `no-map`, from `hypervisor@80000000` through `rdtag@ffdc0000`. The
  `memory@80000000` node carries `reg = <0x0 0x80000000 0x0 0x0>`, which is the
  upstream convention: ABL fills the size in from the UEFI memory map.
- **The watchdog is already handled and is not the cause** — Withdrawn for the
  mainline kernel on 2026-10-07: the watchdog *is* the cause there, see "The
  panic is in initcall 535, `qcom_wdt`". What follows was right about the
  config and wrong about the question, which was never whether the driver
  probes but whether this VM may touch the register block at all. Originally
  Verified, after briefly believing otherwise. Some Qualcomm bootloaders leave the APSS
  watchdog running, which resets the device in about 30 seconds unless the
  kernel pets it, and a module-only driver would never load here because
  mainline has no UFS and so never reaches a rootfs. But the shipping config
  has `CONFIG_QCOM_WDT=y` with `CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED=y`, so the
  driver is builtin, probes at boot and adopts a watchdog the bootloader
  started. The `CONFIG_QCOM_WDT=m` that prompted the scare was in
  `out/kbuild/.config`, a scratch out-of-tree build directory that nothing
  ships from.

## The real init on mainline

- **Round 18: the real init on a kernel that reaches `/init` went silent** —
  Verified 2026-10-07. pkgrel 3, the stock pmOS init with the USB quirk and
  the log hook patched in, and the command line as the package ships it:
  KASLR on, `panic=60`, `pmos.debug-shell`. Nothing answered in the 45
  minutes `WAIT=2700` allowed - no adb, no fastboot, no network gadget - and
  an hour in, the host's USB bus held no device from the phone at all.
- **That silence is not evidence of a hang** — Verified in our own scripts,
  and it withdraws the first reading, which was that the 240-second USB
  watchdog never reset the phone and so the kernel had stopped scheduling.
  The watchdog stood down whenever `/pmusbok` existed, and the quirk created
  that file as soon as any UDC other than the dummy appeared. On the
  downstream kernel that meant the controller had come up. On mainline it
  means nothing: dwc3 with `usb-role-switch` and no
  `role-switch-default-mode` puts itself in peripheral mode at probe
  (`dwc3_setup_role_switch`, `drivers/usb/dwc3/drd.c`), so `a600000.usb` is
  registered whether or not a host ever sees it. After that stage 2 waits in
  `debug_shell` for `/tmp/continue_boot`, which only a telnet session can
  create; without `pmos.debug-shell` it would wait 30 seconds for a root
  partition that mainline could not then see, and then loop in
  `fail_halt_boot`. That was round 18's kernel; mainline has driven UFS
  since round 39 and read the card, as `mmcblk0`, since round 43. Either way
  the init is alive and silent for ever, and nothing of ours resets it.

  So the likeliest reading of round 18 is Reasoned, not Verified: the init
  ran, the gadget never reached the host, and the phone sat still. A real
  hang is not excluded. The next round tells the two apart.
- **The phone never even pulled D+ up** — Verified in the host's own kernel
  log, which costs nothing to read. The phone left the bus at 15:10:53 for
  the reboot out of fastboot, and in the following hour the host logged no
  new device, no descriptor read error and no address failure - nothing.
  So whatever ran on the phone, its gadget did not fail enumeration; it
  never presented itself. That points below the gadget stack, at the
  controller or the PHY, and away from anything a USB function does.
- **The HS PHY was missing its reference clock gate** — Verified against
  the stock tree; whether it is what kept the gadget off the bus is the
  question for round 19. Stock's `hsphy@88e3000` takes two clocks, CXO as
  `ref_clk_src` and `GCC_EUSB3_0_CLKREF_EN` as `ref_clk`
  (`parrot-usb.dtsi`), and stock Android runs that gate enabled with one
  consumer. Ours named only `RPMH_CXO_CLK`, so nothing in mainline ever
  turns the gate on, and with no reference the PHY has nothing to run its
  PLL from. Upstream already has the pattern: qdu1000, lemans and
  sc8280xp all give the femto PHY its CLKREF gate as `ref`, and qdu1000's
  `gcc_usb2_clkref_en` at `0x9c008` is a register away from ours at
  `0x9c00c`. The working tree in `out/linux` makes that one-line change and
  passes `CHECK_DTBS=y`; the DTB is `out/milestone/clkref.dtb`, differing
  from pkgrel 4's in that one property. It goes into the series once a round
  says it matters - unless ABL happens to leave the gate on, in which case
  `clk_ignore_unused` already kept it on and the change is inert.
- **The gadget stack is in the initramfs and loadable** — Verified in the
  pkgrel 4 vendor ramdisk. `libcomposite`, `u_ether`, `usb_f_ncm`,
  `usb_f_rndis` and `usb_f_acm` are there as `.ko.zst` with a `modules.dep`
  beside them, `modprobe` is kmod rather than busybox, and the kernel has
  `CONFIG_MODULE_DECOMPRESS=y`. The HS PHY driver is builtin
  (`CONFIG_PHY_QCOM_USB_SNPS_FEMTO_V2=y`). The cheap explanation, a gadget
  that could not even be built, is ruled out on paper.
- **The USB watchdog now stands down only for a configured gadget, and says
  why when it resets** — Done 2026-10-07, in `scripts/bootlog.py`; tested
  under busybox ash against fake sysfs trees for every case, not yet run on
  the device. It decides at 150 seconds instead of 240, past `udevadm
  settle`'s own 120-second timeout, and stands down only if a UDC's `state`
  reads `configured` - a host has really enumerated it. Otherwise it resets
  after an extra delay that carries two numbers: the last progress mark the
  init wrote to `/pmmark`, and how far up the USB stack the boot got, as one
  rung of a seven-rung ladder. 0 is the dwc3 glue (`usb@a6f8800`) unbound,
  1 the glue bound and the HS PHY not, 2 both bound but no UDC, which means
  the dwc3 core failed, 3 a UDC that configfs never bound the gadget to, 4 a
  bound gadget whose UDC is `not attached`, so no host saw it, and 5 one
  that got partway with a host. Rung 6, added after round 19, is a bind
  that never returned, and rung 7, added after round 20, is a host that
  configured the gadget; see below for both.

  `MARKS="4 8"` on `try-kernel.sh` numbers 38 steps across both stages, with
  `debug_shell` as mark 24, eight seconds apart so the seven rungs fit between
  them, and `bootlog.py markdecode` turns a round's total back into the step
  and the rung. One round answers both "how far did the init get" and "where
  did USB stop", because the watchdog's offset is known. A round in which it never fires runs past 500 seconds an attempt,
  so a real hang still shows, as a total no mark can produce.
- **The marks feed a second channel for a kernel that dies** — Reasoned.
  pkgrel 4 builds in the soft- and buddy hard-lockup detectors, and each mark
  also writes its bare step number into `/proc/sys/kernel/panic`, so with
  `hardlockup_panic=1 softlockup_panic=1` a stalled CPU becomes a panic whose
  timeout names the step. That channel has an unknown offset, the time to the
  hang plus about 20 seconds of detection, and needs two rounds at two panic
  scales. It is kept at one second a step so that it stays under the
  watchdog's 163-second floor unless the hang comes more than a minute and a
  half into the init, and the two can be told apart by length alone.
  Half of this was wrong, found 2026-10-08 and Verified against
  `kernel/watchdog.c`: `hardlockup_panic=` is not a boot parameter - round
  23's log lists it among the unknown ones - and the hard-lockup panic is
  set by `nmi_watchdog=panic`. So rounds 19 to 23 ran with a hard-lockup
  detector that only warns; `softlockup_panic=1` was real. Plans from round
  24 on pass `nmi_watchdog=panic softlockup_panic=1`.
- **Round 19: the real init with the marks, and nothing came back at all** —
  Verified 2026-10-07. pkgrel 4, `DTB=out/milestone/clkref.dtb`,
  `MARKS="4 8"`, `BOOTLOG=0`,
  `CMDLINE_ADD="nokaslr hardlockup_panic=1 softlockup_panic=1"`, and
  `WAIT=4800`. In 80 minutes nothing answered: no adb, no fastboot, and no
  fallback to stock Android. The host's kernel log has no USB event from the
  phone after 16:47:57, when it left the bus for the reboot out of fastboot.
  The phone had to be put back into fastboot by hand.
- **No mark can make a round that long, so something stopped the watchdog**
  — Reasoned, from the timing model under "Why the kernel resets". With the
  stand-down narrowed to a configured UDC, and no host ever seeing one, every
  attempt the watchdog ends takes 13 + 150 + mark + rung seconds. The
  highest mark is 300, so that is under 470 seconds, and seven attempts and
  the fallback come to about 55 minutes. A lockup panic ends an attempt
  sooner still. Eighty minutes means at least one attempt was ended by
  neither. Round 18 cannot say as much, because its watchdog stood down as
  soon as a UDC appeared.
- **The likeliest stop is the gadget bind, and it took the watchdog with it**
  — Reasoned, from the 6.18 sources. The init binds the gadget by writing
  the UDC's name to `/sys/kernel/config/usb_gadget/g1/UDC`.
  `gadget_dev_desc_UDC_store` (`drivers/usb/gadget/configfs.c`) holds the
  gadget's `gi->lock` across the whole of `usb_gadget_register_driver`, which
  probes the gadget driver, starts the UDC and pulls D+ up. The watchdog
  read the same file to tell rung 3 from rung 4, and
  `gadget_dev_desc_UDC_show` takes the same lock. So a bind that never
  returns leaves the init and the watchdog both asleep on one mutex, for
  ever. Neither lockup detector sees that, because a task asleep is not a
  CPU stalled. It fits the host's log too: a dwc3 that never finished
  starting never pulled D+ up.

  Had the watchdog got past the read, it would still have had nothing to
  reset with. pkgrel 4 has no sysrq, so it fell back to `reboot -f`, and
  `reboot(2)` runs `device_shutdown`, which takes every device's lock in
  turn (`drivers/base/core.c`). The bind holds the gadget's device lock
  while it probes, so the reset would have waited on the same stuck call.

  A hard hang of the whole SoC fits the silence just as well, and nothing
  from these rounds tells the two apart. The changes below are built to.
- **Nothing the logging does waits on a kernel lock any more** — Done
  2026-10-07, in `scripts/bootlog.py`; tested under Alpine's busybox 1.38
  against fake sysfs trees, with a FIFO standing in for a `g1/UDC` that never
  answers. Not yet run on the device.
  - The watchdog reads `g1/UDC` from a child and gives it two seconds. One
    that has not answered by then is rung 6, "binding the gadget never
    returned". The time spent waiting comes off the delay at the end, so the
    total still names the rung, and seven rungs fit inside `MARKS="4 8"`'s
    eight-second steps.
  - Before it resets, it writes `w` to `/proc/sysrq-trigger`. That puts the
    kernel stack of every task in `D` state into the ring buffer. It then
    waits for the log hook to finish two more records, through
    `/pmbl.seq`, because the second is the first one certain to have been
    put together after the dump. It waits six seconds at most, and never
    longer than its delay has left.
  - It resets with sysrq `b`, which restarts at once and skips
    `device_shutdown`. `reboot -f -n` is only the fallback, and `-n` keeps
    `sync` out of it.
  - The hook reads every source that takes a lock through `pmbootlog_try`:
    the gadget's UDC, the module list, the deferred probes, and the
    power-domain, regulator and clock summaries. Each gets two seconds. One
    that does not answer is reported as `BLOCKED`, with the uptime, and never
    read again, so it costs two seconds once and not every record.
  - Each record now lists every task in `D` state, with its stack from
    `/proc/<pid>/stack`, so a stuck bind names its own function even
    without sysrq.

  The test caught one bug of exactly the kind it was written for. The
  hook's background reader inherited the stdout of the `$(...)` the gadget
  line runs in, so the substitution waited for the stuck reader anyway, and
  the record stopped there. The job now has all three of its descriptors
  redirected.
- **Round 20: the hook on the card, and nothing on it** — Verified
  2026-10-07. pkgrel 6, `DTB=out/milestone/clkref-sdvolt.dtb`,
  `MARKS="4 8"`, the log hook on,
  `CMDLINE_ADD="nokaslr hardlockup_panic=1 softlockup_panic=1"` and
  `WAIT=4800`. Again 80 minutes of nothing, with no fallback, and the phone
  went back into fastboot only by hand. The host's last USB event from the
  phone was at 21:06:14, when it rebooted out of fastboot. The first start
  died before flashing, because `fastboot reboot` reported an error for a
  reboot that happened. `settle_slot` and `--log` now treat that as a
  warning and let the wait for the phone decide.

  When recovery read the card's log region, it was blank, counter block
  included, and so was `rddata`. No attempt wrote a record. Either `/init`
  never ran, or the hook ran and never found the card. Round 20 cannot tell
  those apart, and nothing yet says whether the card comes up on mainline
  at all.
- **The clkref tree is the one thing rounds 19 and 20 share that earlier
  boots lacked** — Guess. Both flashed the tree that gives the HS PHY
  `GCC_EUSB3_0_CLKREF_EN`, and neither came back. Round 18 was silent too, on
  the package tree without the gate, but its watchdog stood down by design,
  so it is no control. If turning the gate on hangs the bus, the kernel
  stops before `/init`. That would explain both the silence and the empty
  card. The missing SCM node below explains both as well, and more simply,
  so the clkref round waits until the dwc3 core can probe at all.
- **A hung kernel now has something to reset it, if the Gunyah watchdog
  works** — Reasoned. It is built into pkgrel 7 (see "The mainline kernel
  package"), and a round of its own tests it before anything relies on it.
  `WDTPROBE=1` on `try-kernel.sh` replaces `/init` with a probe and adds
  `gunyah_wdt.start_at_boot=1`. The probe lets the kernel feed the watchdog
  for 50 seconds. Then it opens `/dev/watchdog0`, which stops the kernel
  feeding it, and never writes to it. The length of each attempt says what
  happened, measured from `/init`, and `bootlog.py wdtdecode <total>` reads
  a round's total back:
  - about 5 seconds: there is no `/dev/watchdog0`, so the driver never
    registered;
  - about 31 seconds: it bit while the kernel should have been feeding it,
    so `start_at_boot` is not safe;
  - about 82 seconds: it was fed, starved and bitten, so the watchdog works
    and a hung kernel resets;
  - about 150 seconds: it never bit, and the probe reset the board itself,
    so a bite does not reset this board.

  Every outcome but one ends in a reset, so the round falls back to stock
  without help. The exception is a bite that leaves the board in a
  crash-dump mode, which would need the buttons, and only this round can
  find that out.
- **No outcome of a round should wait for hands any more** — Done
  2026-10-07. Tested on the host, and the first part also on the device.
  - The `--log` fix above.
  - The USB watchdog no longer stands down for good when a host configures
    the gadget. That would have left the one boot that worked sitting in the
    initramfs all night, with every round after it waiting. It now gives
    that boot ten minutes, long enough to harvest it, and `/pmhold` still
    keeps the phone. Then it resets as rung 7, which `markdecode` knows to
    read 600 seconds lower. Tested under busybox ash against fake sysfs
    trees: a gadget that stays configured, a host that leaves during the
    window, and rungs 4 and 6 unchanged.
  - `scripts/queue.sh <plan>` runs rounds back to back. A plan is a shell
    fragment that calls `round NAME VAR=value ...` once per round, and it can
    branch on `ROUND_RESULT`, `ROUND_TOTAL` and `wdt_verdict`. After every
    round the queue waits for the phone to be reachable again. It tells a
    gadget it can reach over telnet to reset at once, rather than wait out
    the window, and it reads the card and `rddata` if try-kernel did not.
    If the phone stays silent for three hours, the queue stops, because no
    round after that one could start. Its parsing was tested against the
    logs of rounds 19 and 20 and of an earlier fallback round.
  - `try-kernel.sh` and `queue.sh` each run from an unlinked copy of
    themselves. Editing either during a round changes nothing about that
    round.
- **The Gunyah watchdog probe: no `/dev/watchdog0`** — Verified 2026-10-07,
  22:42. pkgrel 7, `WDTPROBE=1`, the package's own tree. The round came back
  on stock in 158 seconds: 18.3 seconds an attempt, 4.9 of them after
  `/init`, which is the probe finding no watchdog, waiting five seconds and
  rebooting. So this kernel on this tree reaches `/init` and reboots cleanly
  seven times running, and the Gunyah watchdog driver never registered.
- **It never registered because our tree has no SCM node** — Verified in
  the tree and the sources. `qcom_scm` is what registers the `gunyah-wdt`
  device, from its probe (the backported
  `firmware: qcom: scm: Register gunyah watchdog device`), and
  `sm6450.dtsi` had no `firmware { scm }` node, so `qcom_scm` never probed.
  Upstream's SM4450 tree, which ours started from, has no SCM node either,
  but it has no SMMU, and ours does.
- **Without SCM, USB and the SD card cannot probe at all** — Reasoned, from
  the 6.18 sources; this is the likeliest single cause of every silent
  mainline round so far. `qcom_smmu_create`
  (`drivers/iommu/arm/arm-smmu/arm-smmu-qcom.c`) defers the apps SMMU until
  `qcom_scm_is_available()`, and the generic `qcom,smmu-500` match carries an
  impl, so the check applies to ours. The dwc3 core and `sdhc_2` both name
  `apps_smmu` in `iommus`, so fw_devlink holds them until it binds. The
  deferred-probe timeout does not release them, because
  `fw_devlink_no_driver` (`drivers/base/core.c`) relaxes only links to a
  supplier no driver can match, and arm-smmu matches this one. So the dwc3
  glue and the HS PHY bind, the core never does, and there is no UDC. That
  is rung 2 on the ladder, and it fits round 18's phone never pulling D+
  up. The card never appears, so the hook has nowhere to write. That fits
  round 20's blank card, whether or not `/init` ran.
- **pkgrel 8 adds the node** — Done 2026-10-07. Built at 22:57 and never
  installed, because pkgrel 9 overtook it.
  It is the plain node upstream uses on this generation, compatible and
  `#reset-cells`, behind a binding commit that documents
  `qcom,scm-sm6450`. The binding allows no interrupt for it, and there is
  no TCSR syscon node yet for `qcom,dload-mode`. The board DTB passes
  `CHECK_DTBS=y` and differs from pkgrel 7's by that node alone; it is
  `out/milestone/scm.dtb`, which rounds use through `DTB=`. pkgrel 8's own
  DTB is byte-identical to it.
- **Round 21: silent for 45 minutes, and the card blank** — Verified
  2026-10-07. The real init on the package tree, without SCM. Nothing
  answered, and the owner put the phone into fastboot by hand at 2742
  seconds. The queue recorded that as a bootloader giving up, and its
  `markdecode` lines are noise: they assume seven attempts. The card and
  `rddata` both came back empty. That is what the missing SCM node
  predicts: no SD controller, so the hook had nowhere to write. Whether it
  hung is not known. With `MARKS="4 8"` an attempt that reaches the last
  mark, 38, lasts up to about 477 seconds before the USB watchdog resets
  it, so seven attempts can take well over 2742 seconds. A round that was
  resetting normally could still have been short of its fallback.
- **The watchdog probe with the SCM node: still no `/dev/watchdog0`** —
  Verified 2026-10-07, 23:39. pkgrel 7 with `DTB=out/milestone/scm.dtb`.
  The round fell back in 158 seconds, 4.9 of each attempt after `/init`,
  the same as without the node. So the node was not the only thing
  missing.
- **The other missing piece: this firmware speaks SMCCC v1.0** — Verified
  in the 6.18 sources and in stock's own boot log, which says
  `psci: SMC Calling Convention v1.0`. `qcom_scm` registers `gunyah-wdt`
  only after `arm_smccc_hypervisor_has_uuid()` sees Gunyah's UUID. That
  function asks through `arm_smccc_1_1_invoke()`. Below SMCCC v1.1,
  `arm_smccc_1_1_get_conduit()` returns no conduit, and the invoke fails
  without making any call. So on this board the check is false whether or
  not Gunyah is there, with or without an SCM node. Nothing else in the
  registration path can stop it: the only other bail-out is an available
  `qcom,kpss-wdt` or `arm,sbsa-gwdt` node, and our tree has neither.
- **Stock drives the same watchdog with the same four calls** — Verified by
  disassembling `gh_virt_wdt.ko` out of stock's vendor ramdisk. Stock binds
  it from a DT node, `qcom,gh-watchdog` under `hypervisor`, and asks
  nothing first. It makes the CONTROL, STATUS, PING and SET_TIME calls,
  `0x86000005` to `0x86000008`, the same IDs upstream's `gunyah_wdt` uses,
  each with an inline `smc #0`. Upstream's driver makes them with
  `arm_smccc_1_1_smc()`, which assumes the callee preserves x4 to x17, a
  v1.1 guarantee. Stock relies on the same thing on this same firmware, so
  that is not a new risk.
- **pkgrel 9 asks in a way v1.0 can answer** — Done 2026-10-07, built at
  23:53, and installed by the queue at 04:02 (see below); not yet run. The bring-up
  patch `bringup-gunyah-wdt-smccc-1-0.patch` repeats the UID query below
  v1.1 with `arm_smccc_smc()`, an SMCCC v1.0 call, over SMC, which every
  call `qcom_scm` makes already uses. The Call UID query is one of the
  original SMCCC's general service queries, so a v1.0 hypervisor may well
  answer it. Whether this one does is a guess. In case it does not,
  `qcom_scm.force_gunyah_wdt=1` registers the device without asking.
  `gunyah_wdt` still makes a STATUS call before it probes, and gives up with
  `-ENODEV` if nothing answers. Neither change is upstream material as it
  stands. The real fix belongs in `drivers/firmware/smccc`, which would
  need to record the PSCI conduit even below v1.1.
- **A probe that says how far SCM, the SMMU, USB and SD got** — Done
  2026-10-07. Tested under busybox against fake sysfs trees for every
  state. `DEVPROBE=1` on `try-kernel.sh` replaces `/init` with one that
  mounts sysfs, proc and debugfs, waits 25 seconds for probing to settle,
  then sleeps 4 seconds for every unit of 8 times the SCM state plus the
  bound devices, and reboots. `bootlog.py devdecode <total>` reads a round
  total back. The SCM states:
  - 0, no `firmware:scm` device at all;
  - 1, the device is waiting in `devices_deferred`;
  - 2, the device exists and is not deferred, but did not bind, so its
    probe failed;
  - 3, `qcom_scm` bound but registered no `gunyah-wdt`, so the UUID check
    failed;
  - 4, a `gunyah-wdt` device exists, but no `/dev/watchdog0`, so its probe
    failed;
  - 5, `/dev/watchdog0` exists.

  The bound devices add 1 for the apps SMMU (`15000000.iommu`), 2 for the
  dwc3 core (`a600000.usb`) and 4 for the SD controller (`8804000.mmc`).
- **The night of 2026-10-07** — Running. The first queue started round 21
  at 22:47, the real init on the package tree without the watchdog, since
  the probe had found none:

      MARKS="4 8" WAIT=4800 \
      CMDLINE_ADD="nokaslr hardlockup_panic=1 softlockup_panic=1" \
      scripts/try-kernel.sh

  The SCM finding came while it ran. The queue was stopped, leaving the
  round alone, and a second one adopted it, with a new plan,
  `out/try-kernel/plan-20261007b.sh` (under `out/`, so not in git):
  - `WDTPROBE=1 DTB=out/milestone/scm.dtb`, the watchdog probe again on the
    tree with SCM;
  - unless that probe fails to reach a verdict, round 22, the real init on
    `scm.dtb` with the round 21 options, plus
    `gunyah_wdt.start_at_boot=1` if the verdict is that the watchdog
    works.

  The clkref tree is off the night's list. It only makes sense to test
  once the dwc3 core can probe at all.

  The second watchdog probe ran and found nothing, and round 22 started at
  23:39. The SMCCC finding came during round 22. Two more plans were
  written and each replaced before it ran anything; the reason for the
  second change is the bullet after this one. The one queued,
  `out/try-kernel/plan-20261008e.sh`, waits for the second queue to finish
  round 22, then:
  - installs pkgrel 9 into the rootfs between rounds, and stops if it
    cannot confirm `-r9` and fresh boot images;
  - `WDTPROBE=1 DTB=out/milestone/scm.dtb`, the watchdog through the v1.0
    UUID query;
  - if that finds no watchdog that resets the board, `WDTPROBE=1` again
    with `qcom_scm.force_gunyah_wdt=1`;
  - `DEVPROBE=1` on the same tree. If a watchdog resets the board, it runs
    with the watchdog armed from boot. If not, it runs with
    `deferred_probe_timeout=-1 regulator_ignore_unused`;
  - only if the verdict is that the watchdog works, round 23: the real init
    on `scm.dtb` with `gunyah_wdt.start_at_boot=1`, the force option if it
    was needed, and the round 21 options.

  Round 22 hung, and nobody was at the phone, so the second queue gave up
  at 04:01 after its three-hour wait. The fifth plan then installed pkgrel
  9 and stopped at its first round, which found no phone. A sixth,
  `out/try-kernel/plan-20261008f.sh`, replaced it. It waits up to a day
  for the phone, logs the bootloader's counters from fastboot, reads the
  card round 22 may have written, and then runs the fifth plan's rounds
  unchanged.

  The results go here.
- **Round 22 went silent past the longest a resetting round can take** —
  Verified 2026-10-08, 00:36. The real init on `scm.dtb`, pkgrel 7, round
  21's options. At 3376 seconds nothing had answered, and nothing had by
  the end of the 4800-second wait either. Seven attempts that
  each reach the last mark and reset take about 3370 seconds with the
  fallback boot, so at least one attempt was ended by nothing.
- **Withdrawn: no mainline boot comes back from more than about 5 seconds
  after `/init`** — Withdrawn 2026-10-08. The rounds it listed are as it
  said, but the reading was wrong: round 22's kernel was still running 1138
  seconds after boot, long past both the deferred-probe timeout and the
  regulator cleanup it blamed. What the long rounds share is that nothing
  reset the phone, see below.
- **Round 22 was one attempt, alive for at least 19 minutes** — Verified
  2026-10-08, from fastboot and the card. `slot-retry-count:a` read 6.
  Set-active makes it 7 and each attempt takes one off, so the bootloader
  started our kernel once and it never reset. The card held that attempt's
  record 600, the hook's last by design, written at 1138 seconds of uptime.
  The round went silent because nothing reset the phone, not because the
  SoC hung.
- **What round 22's kernel had working** — Verified, from that record. The
  SCM firmware node bound. The SMMU probed: SMMUv2, 126 stream-match groups,
  77 context banks, coherent table walks. The SD card came up at SDR104 and
  the hook wrote to it. The init reached `debug_shell` at 17 seconds.
- **USB waited on a regulator block that could not probe** — Verified from
  the same record, and checked against stock's log. `a600000.usb` deferred
  on `88e3000.phy`, and the PHY waited on `regulators-0/ldo25`.
  `regulators-0` had failed outright: "ldo8: could not find RPMh address
  for resource ldob8". `regulators-2` failed over `ldog2`. The mainline
  driver registers a block's regulators in one probe and gives up at the
  first resource command DB does not know, so one bad child loses all of
  them. Stock's tree declares the same 45 regulators ours did, and stock's
  log has the same misses for ldob8, ldob17 and ldog2 to ldog6. Stock
  survives them because each of its regulators is a device of its own.
- **The PMR735A is not fitted** — Verified from stock's log. Stock's reads
  at SID 6 fail just as ours did ("transaction failed (0x3)"), its PMR735A
  GPIO and temperature-alarm drivers fail with -EIO, and command DB has none
  of its five LDOs.
- **The board tree no longer describes them** — Done 2026-10-08, in the
  board commit in `out/linux`. Not yet run on the device. `pm6450_l8`,
  `pm6450_l17` and the whole `regulators-2` block are gone, and so are the
  PMR735A include and its SID. Nothing referenced any of them, and 38
  regulators remain. The DTB passes `CHECK_DTBS=y`. Decompiled next to
  `scm.dtb`, it differs by those nodes, the PMR735A's thermal zone and the
  phandle numbers, and nothing else. It is `out/milestone/regs.dtb`. The
  commit that made the PMR735A's SID overridable existed only for this
  board, so it leaves the series.
- **The USB watchdog did not reset round 22** — Verified. It should have
  reset at about 360 seconds: 13 to `/init`, 150 asleep, 196 for the mark at
  `debug_shell`, and 1 for the rung. Its first act on the way out is sysrq
  `w`, which logs "sysrq: Show Blocked State", and record 600 has no such
  line; its dmesg ends at 31.9 seconds.
- **It died at birth, on every boot since 22859f2** — Verified 2026-10-08,
  under pmport's busybox in a mount namespace with an empty `/dev`. A
  non-interactive ash points a background job's stdin at `/dev/null` as it
  forks it, and when that open fails the child dies with "can't open
  '/dev/null'" before running a line of its body. 22859f2, on 2026-10-05,
  moved the watchdog to the top of `/init`, where nothing has mounted
  `/dev` yet and the only node there is the kernel's `/dev/console`. So
  from then on the watchdog never ran, rounds 19 to 22 included, and the
  error went only to the serial console. The log hook forks after
  `mount_proc_sys_dev`, which is why it lived. The same test without
  `/dev/null` kills the job; with it, the job runs.
- **The watchdog makes its own `/dev/null`** — Done 2026-10-08, in
  `scripts/bootlog.py`. One `mknod` before the fork, if the node is
  missing. devtmpfs hides it when `mount_proc_sys_dev` mounts over `/dev`,
  and the descriptor the job already holds keeps working. Checked in a
  rebuilt image, and in the namespace with `touch` standing in for
  `mknod`, which a user namespace does not allow. Not yet run on the device.
- **The log hook now backs the watchdog up, and both say what they did** —
  Done 2026-10-08, in `scripts/bootlog.py`. Tested under pmport's busybox
  1.37 against a fake card and sysfs. Not yet run on the device.
  - Past 500 seconds of uptime (`BACKUP_S`), the hook resets the phone
    itself unless `/pmhold` exists: sysrq `w`, one more record, then sysrq
    `b`. The watchdog's own latest is under 470 seconds, so a round the
    backup ended decodes differently, and `markdecode` names it. A gadget
    a host has configured adds the watchdog's 600-second hold to both.
  - The watchdog writes each step to `/pmwd.log`: armed, awake with its
    pid, its rung and mark, sysrq, resetting. Every record copies that file
    in, and lists every userspace task with its parent, state, session, the
    kernel function it sleeps in, and its command line.
  - Rung 1 also counts `usb@a600000` bound, for the flattened dwc3 binding.
- **wdtprobe3: the Gunyah watchdog registers, and does not bite** —
  Verified 2026-10-08, 08:45. pkgrel 9 on `scm.dtb`. It fell back after
  1168 seconds, 149 seconds an attempt after `/init`. That is the probe's
  own reboot after it starved `/dev/watchdog0` for its whole window. So the
  device appeared, which it never did before pkgrel 9's v1.0 UUID query,
  and starving it did not reset the board. Why the hypervisor does not
  bite is open. Until it does, nothing resets a hang that stops the CPUs.
- **The queue after wdtprobe3** — Done 2026-10-08, 08:46. The sixth plan
  would have run the forced probe and the device probe, and then stopped
  short of the real init for want of a watchdog.
  `out/try-kernel/plan-20261008g.sh` replaced it during the forced probe,
  which it adopts. It then runs round 23: the real init on `regs.dtb`,
  `MARKS="4 8"`, with `nokaslr hardlockup_panic=1 softlockup_panic=1`.
  The device probe was dropped, because round 22's card record already
  answers what it asked. Round 23 is the first round since 2026-10-05 with
  a USB watchdog that runs, and the hook's backup behind it.
- **pkgrel 10 is installed** — Verified 2026-10-08, 08:51: `apk list -I`
  says `-r10`, and the DTB in the fresh `vendor_boot.img` is byte-identical
  to `regs.dtb`.
- **cpuidle is probably what stops the Gunyah watchdog biting** —
  Reasoned, from the open Gunyah source, which may not be what this
  phone's hypervisor runs. Gunyah freezes a VM's watchdog when the whole VM
  suspends, and freezes it with a reset, giving the VM "the full bark
  period when it wakes up" (`hyp/misc/watchdog/src/watchdog.c`). The VM
  counts as suspended as soon as its last VCPU enters a PSCI CPU_SUSPEND
  (`hyp/vm/psci_osi/src/psci_osi.c`). Our tree has PSCI cpuidle with
  OS-initiated domain states. The probe starves the watchdog with a shell
  asleep, so every CPU suspends, and the count starts over at each wakeup.
  It never reaches 32 seconds. With `cpuidle.off=1` the idle loop is a
  plain WFI. For a VM that drives PSCI itself, a trapped WFI only blocks
  the VCPU, so the count should run on. If the probe still finds no bite,
  the cause is the bite itself. Gunyah resets the board only for a
  watchdog marked critical or fatal. Any other watchdog gets a virtual
  interrupt for some VM to handle.
- **The queue after round 23** — Done 2026-10-08, 09:02.
  `out/try-kernel/plan-20261008h.sh` starts by itself when queue g ends.
  It runs one watchdog probe, wdtprobe5, on `regs.dtb` with
  `cpuidle.off=1`.
- **wdtprobe4: forcing the registration changes nothing** — Verified
  2026-10-08, 09:05. It fell back after 1168 seconds, "nobite", the same
  as wdtprobe3. That was expected: pkgrel 9's UUID query already
  registers the watchdog, so forcing it has nothing to add.
- **Round 23: USB is up on the mainline kernel** — Verified 2026-10-08,
  09:06. pkgrel 10 on `regs.dtb`. The gadget appeared 18 seconds after
  the reboot, and the harvest reached the pmOS debug shell over telnet.
  `a600000.usb` is the UDC and `devices_deferred` is empty. The only
  failure in dmesg is the PMK8350 ADC with no channels, which upstream
  boards tolerate too. All 38 regulators set their ranges. The SMMU
  probed and the card came up at SDR104, all inside the first second.
  The debug shell started at 4.97 seconds of uptime. The harvest is
  `out/try-kernel/harvest-r23.txt`.
- **The loop around it works** — Verified, the same round. The queue
  reset each of the seven attempts over telnet as soon as it answered,
  between 3 and 18 seconds of uptime. Stock was back three minutes after
  the first attempt. Every attempt left its records on the card. The USB
  watchdog's log says "armed", and its `sleep 150` is in the process
  list, so it now outlives its own start.
- **Round 24 carries its own experiment** — Done 2026-10-08, 09:16.
  `try-kernel.sh` now takes `LIVE=file`. As soon as the harvest has the
  shell, `scripts/tsh.py` runs that file's commands there, one at a time.
  `out/try-kernel/plan-20261008i.sh` starts by itself after wdtprobe5. It
  repeats round 23's boot with `cmds-r24.sh`, which first reads the clock,
  regulator, power-domain, interrupt and GPIO state. It then measures the
  Gunyah watchdog from the inside. It holds `/dev/watchdog0` open without
  writing and samples `timeleft`, which is the hypervisor's count since the
  last ping. It does that first with cpuidle as configured, then with every
  idle state but WFI disabled.
- **USB on the flattened dwc3 binding** — Done 2026-10-08, and round 25
  passed with it (see "Round 25: the flattened dwc3 binding works"). New SoCs upstream are expected to use the single-node
  `qcom,snps-dwc3` binding. Ours used the legacy one, with the glue at
  `0xa6f8800` and the core as a child. `out/milestone/usbflat.dtb` has one
  node at `0xa600000` that covers both. Its core interrupt is named
  `dwc_usb3`, and the board sets `dr_mode = "peripheral"`, as pdx225 does,
  in place of `otg` with a role switch that nothing would ever drive. The
  flattened glue driver turns the VBUS override on at probe in peripheral
  mode. The DTB passes `CHECK_DTBS=y`, the binding passes
  `dt_binding_check`, and decompiled it differs from `regs.dtb` in the USB
  node alone. Round 25, the second round of plan i, boots it. The change
  waited on branch `sm6450-usbflat` in `out/linux` until that round passed.
- **wdtprobe5: with cpuidle off, the phone did not come back** — Verified
  2026-10-08, 09:41. pkgrel 10 on `regs.dtb`, with `cpuidle.off=1` and
  `gunyah_wdt.start_at_boot=1`. Nothing answered in 1800 seconds: no
  fallback, no fastboot, and nothing of the phone's on the host's USB bus,
  not even Qualcomm's dump-mode ID. wdtprobe3 and wdtprobe4, the same probe
  with cpuidle on, fell back after 1168 seconds each. The probe's `/init`
  ends in `reboot -f` whatever the watchdog does, so a kernel that kept
  running would have come back; something stopped it, and the phone needed
  hands again.
- **So the watchdog counts without cpuidle, and its bite stops the board** —
  Reasoned. This is the outcome the cpuidle bullet above predicts, and the
  one it warned about: the count ran once the CPUs stopped suspending, and
  the bite did not reset. Gunyah resets for a bite only when the watchdog
  is marked critical or fatal (`watchdog_bite()` in the open source); any
  other bite is a virtual interrupt to a handler VM, and whatever handles
  it on this phone leaves it stopped. The backported driver registers no
  bark handler, so the kernel never saw the bark coming either. A hang that
  `cpuidle.off=1` causes by itself would look the same from outside, and
  is the less likely reading: wdtprobe5's kernel is round 23's, which ran
  its whole init with cpuidle on.
- **The Gunyah watchdog is not a backstop on this board** — Reasoned, from
  the two bullets above. Arming it turns a hang into one that needs the
  power key, which is what it was meant to prevent. Next-steps item 2 is
  closed that way. No round may open `/dev/watchdog0` or pass
  `gunyah_wdt.start_at_boot=1`; round 24's two watchdog phases were taken
  out of `cmds-r24.sh` before plan i started, for that reason. A hang has to
  become a panic instead, and `panic=60` resets: the soft-lockup panic was
  always on, and the hard-lockup one is from round 24 on (see the correction
  under "The marks feed a second channel").
- **TSENS and 28 thermal zones** — Done 2026-10-08, and round 26 passed
  with it (see "Round 26: every zone reads, and each CPU zone follows its
  core"). Two TSENS v2 controllers at `0xc263000` and `0xc265000`, with
  the stock tree's uplow and critical interrupts, and every zone the stock tree reads from
  them under its stock sensor: tsens0 has two sensors per gold core,
  tsens1 one per silver core. CPU zones throttle through cpufreq at 110 C,
  the stock emergency point, and every zone is critical at 115 C, where the
  stock reset monitor sits. The node layout follows upstream sar2130p,
  which has the same addresses. `CHECK_DTBS=y` and the binding check are
  clean, and decompiled, `out/milestone/thermal.dtb` differs from
  `regs.dtb` in the thermal nodes and phandle numbering alone. Round 26,
  plan j, boots it after plan i, and `cmds-r26.sh` loads cores 4, 7 and 0
  one at a time through a cgroup cpuset to check that each zone follows its
  stock core. Branch `sm6450-thermal` in `out/linux`.
- **The USB3 PHY is SM8350's** — Verified against sources 2026-10-08. The
  stock init sequence writes exactly the registers upstream's
  `sm8350_usb3dpphy_cfg` does and agrees on 144 of 152 values. The eight
  that differ are RX and PCS tuning. See "USB3: SM8350's PHY with receiver
  tuning of its own" in [06-mainline.md](06-mainline.md);
  `scripts/qmp-score.py` is the scorer.
  - **Written** - Done 2026-10-08, not yet run on the device. Branch
    `sm6450-usb3` in `out/linux` adds `qcom,sm6450-qmp-usb3-dp-phy` with
    the eight values, and the tables it writes agree with stock on all 152
    registers. The SoC commit adds the PHY node, GCC's pipe-clock input and
    the controller's SuperSpeed wiring, while the board keeps high speed. The
    board commit then enables the PHY on stock's L16 and L7 with GPIO 100 as
    port select. `CHECK_DTBS=y` is clean and `check-dt.py` passes. The DTB
    is `out/milestone/usb3.dtb`. Since round 25 the branch sits on
    `sm6450-fold`, so the controller it wires is the flattened node; both
    round 38 DTBs were rebuilt from it, and checked again the same way.
  - **Round 38** - Verified 2026-10-08, 15:17. Pkgrel 13 has no SM6450
    entry, so the round ran `usb3-8350-vreg.dtb`, the same tree naming
    SM8350's compatible, with the raised floors. The combo PHY bound to
    `qcom-qmp-combo-phy`, and both of its PHYs are runtime-active. Its pipe
    clock runs at 125 MHz, GPIO 100 is muxed to `usb0_phy_ps`, and both of
    its rails are held. The gadget configured at `high-speed`, under a
    `maximum_speed` of `super-speed`. The transcript is
    `out/try-kernel/live-r38.txt`.
  - **Reasoned:** the PHY powers on. The combo driver's USB power-on
    polls for the PCS to come ready and fails if it does not, and dwc3
    would then not have probed. That is all round 38 can say.
  - **Reasoned:** the board is wired for USB 2.0 only. So SuperSpeed
    cannot be tested on this phone, and the high-speed link is not the
    cable's doing, as the guess here used to have it. Stock links at
    480M on the same port and cable: the host's log of every connection
    from 15:24 to 15:31, `out/try-kernel/usbspeed-20261008.log`, has
    fastboot (`0fce:0dde`) and Android (`0fce:320e`) at 480M beside the
    pmOS gadget. O2's specification page for the phone, and the
    comparison sites, list the port as USB 2.0.
  - So the SoC half of `sm6450-usb3` stands: the binding, the driver entry
    and a disabled PHY node, for a board with a SuperSpeed port. The board
    commit that enables the PHY here is not to be folded, and the board
    keeps its high-speed controller.
- **A register dump from the live shell** — Done 2026-10-08, tested off the
  device. `scripts/regdump.c` reads physical registers through `/dev/mem`,
  read-only, and builds against the kernel's nolibc to 4.9 KB.
  `scripts/tsh.py` takes `@push LOCAL REMOTE` in a command file and carries
  a binary into the shell in base64 lines. `out/try-kernel/cmds-r27.sh`
  reads the UFS PHY as the bootloader left it, if its clocks and GDSC are
  on, for `qmp-score.py` to identify its table. Pkgrel 11 builds in
  `CONFIG_DEVMEM` for it, and plan k runs it as round 27, after the UFS
  rounds below, as a check rather than the only source.
- **The UFS PHY driver was in the tarball all along** — Verified against
  sources 2026-10-08, and a correction: "Known gaps" and 06-mainline.md said
  Qualcomm had not released this chip's UFS PHY driver. Sony's kernel
  tarball has it, `drivers/phy/qualcomm/phy-qcom-ufs-qmp-v4-parrot.{c,h}`,
  in the downstream `ufs_qcom_phy_calibration` form rather than as QMP
  tables, and its header is SM8450's. Scored by `qmp-score.py`, which now
  reads such a header, it is upstream's SM8350/SM8450 table with two tx
  values changed on both lanes. "The UFS PHY" in
  [06-mainline.md](06-mainline.md) has the numbers.
- **UFS on the mainline kernel** — Done 2026-10-08. Round 28 ran it and
  timed out setting fDeviceInit (see "Round 28: UFS links up, then the
  first query times out"). Branch `sm6450-ufs` in `out/linux`: binding lines for the PHY, the
  controller and the ICE, `qcom,sm6450-qmp-ufs-phy` in the QMP UFS driver
  (agreeing with the vendor table on all 125 registers it writes), and the
  host, PHY and ICE nodes with the stock tree's clocks, reset, SMMU stream,
  interrupt and supplies. `CHECK_DTBS=y`, the three binding checks and
  `check-dt.py` are clean; the driver compiles. Plan k runs it before round
  27, on pkgrel 11 with SM8450's PHY configuration
  (`out/milestone/ufs8450.dtb`), as round 28, and again without the ICE as
  round 29 if round 28 reaches the shell and finds no disk.
- **Letting mainline see UFS writes nothing to it** — Reasoned. Nothing in
  the initramfs or `cmds-r28.sh` opens a UFS partition; the pmOS initramfs
  looks for its partitions by label, and UFS has none of them. The log hook
  writes to UFS only when the card is missing, and then only to rddata
  after matching its exact start and size. ufshcd writes the device's
  `bRefClkFreq`, a setting the device keeps and the bootloader relies on,
  only when it differs from the rate of the host's `ref_clk`. That clock is
  CXO, whose rate on our kernel is measured, not assumed: `bi_tcxo` reads
  19200000 in the clk_summary of rounds 22 and 23. The stock tree's
  `dev-ref-clk-freq` is 0, which is 19.2 MHz, so a mainline boot has nothing
  there to rewrite that a stock boot would not. What it may set is
  WriteBooster, which stock Android turns on too.
- **The display clock controller** — Done 2026-10-08, not yet run on the
  device. The driver is in the kernel package since pkgrel 12. Branch
  `sm6450-dispcc` in
  `out/linux`, generated from the vendor's `dispcc-parrot.c` by the clock
  converter, which now has the ravelin/sm4450 display pair as a second
  self-test. `check-tables.sh` agrees with the vendor on all 66 shared
  offsets, the driver compiles with W=1, and the binding check, `CHECK_DTBS=y`
  and `check-dt.py` are clean. On `out/milestone/dispcc.dtb` the node has no
  consumer, so the most it should do there is take over the display clocks
  the bootloader left running; what it does to the splash screen then is
  unknown. On `display.dtb` the MDSS consumes it.
  "The display clock controller" in [06-mainline.md](06-mainline.md) has the
  rules it applies.
- **The interconnect** — Done 2026-10-08, and rounds 30 and 31 passed
  with it (see "Rounds 30 and 31: the interconnect works").
  `scripts/icc-to-mainline.py` turns the vendor's `parrot.c` into an
  upstream driver in Milos's style, with its binding header and YAML: 136
  nodes, 17 BCMs and 33 QoS boxes over twelve NoCs, after dropping the
  display voter's seven nodes and six BCMs. Its writer reproduces upstream's
  `milos.c` to two lines, and its reader finds the vendor's and upstream's
  SM8450 graphs identical node for node. The driver is W=1 and checkpatch
  clean and the binding check passes. Branch `sm6450-icc` in `out/linux`
  added the NoC nodes and the QUP, UART, SD and USB paths, with SM6350's
  SD bandwidth; `CHECK_DTBS=y` and `check-dt.py` were clean. They are now
  folded into `sm6450-fold` (see "The interconnect is folded too"). What
  it could
  break is what it touches: if a vote or a QoS write is wrong, the UART, the
  SD card or USB - the console, the log and the shell - are the first to
  stop. "The interconnect" in [06-mainline.md](06-mainline.md) has the rules
  and the proof.
- **Pkgrel 12 carries three drivers that do nothing yet** — Built
  2026-10-08, 10:56, not yet run. It adds the GCC fixups from
  `sm6450-gccfix`, the display clock controller driver and the interconnect
  driver to the series. None of them binds without a DT node, and
  `regs.dtb` has none, so on it pkgrel 12 should boot exactly as pkgrel 11.
  Plan l installs it after plan k and runs round 30 on
  `out/milestone/icc-noqos.dtb` (votes but no QoS writes) and, only if that
  reaches the shell, round 31 on `icc.dtb` (QoS writes too). Both read
  `cmds-r30.sh`: the interconnect summary, deferred devices, and whether the
  SD card and the USB gadget survived.
- **The display** — Written 2026-10-08. Round 32 ran it, and everything
  bound (see "Round 32: the display pipeline binds, and a DCS read wedges
  it"). Rounds 41 and 42 found frames going out and the panel answering
  nothing (see "Rounds 41 and 42"). The SM6450 entries in
  drm/msm's DPU, MDSS and DSI PHY drivers and in the UBWC table, with their
  bindings, are patches 0028 to 0035 of the series. The DPU catalog is
  generated by `scripts/sde-to-dpu.py` from the stock SDE node and SM8450's
  catalog, and its rules agree with three siblings' upstream catalogs on
  129 of 129, 32 of 32 and 31 of 32 fields. The panel is a Samsung
  SOFEF01-M with an AMS605DK01, which Marijn Suijten's posted driver
  covers; the aport carries it and its binding as backports, plus our vci
  and FLM differences. The nodes are WIP commits on branch
  `sm6450-display` in `out/linux`. `CHECK_DTBS=y`, the binding checks and
  `check-dt.py` are clean.
  - **Verified:** that the DPU is 8.3. The vendor's catalog header says so,
    and round 32 read back `dpu hardware revision:0x80030000`.
  - **Reasoned:** the highest bank bit of 14, from DRAM type 7 (LPDDR4X).
    One review says LPDDR5, which would make it 15.
  - **A guess:** that the UBWC decoder version equals the encoder's (4.0).
  - **A guess:** that the FLM setting matters. The 10 VI's own value is sent.
  - **Known wrong:** brightness stops at 1023 of the panel's 4095.

  "The display" in [06-mainline.md](06-mainline.md) has the derivation.
- **Pkgrel 13 carries the display drivers and the panel** — Built
  2026-10-08, 11:53. Round 32 ran it, and it was in the rootfs for round 34 on. It adds the series' display patches, the
  panel driver and its binding as backports, our two panel changes, and
  `CONFIG_DRM_MSM_DSI_7NM_PHY`, which pkgrel 12's config had off and which
  holds SM8450's PHY code. On any earlier tree nothing new binds. Plan m
  installs it after plan l.
  - Round 32 boots `display.dtb` if round 31 reached the shell, and
    `display-noqos.dtb` (no NoC `reg`, as `icc-noqos.dtb`) if only round 30
    did.
  - Round 33 boots `dispcc.dtb`, the clock controller alone, when round 32
    did not reach the shell or did not run.
  - Both read `cmds-r32.sh`. Nobody watches the screen, so the result is
    read from the kernel: the DPU's revision, which drivers bound, the
    connector, the backlight, and the MDSS interrupt counts before and after
    a line written to the framebuffer console.
- **The remote processors** — Written 2026-10-08. Round 34 probed them
  (see "Round 34: the remote processors probe"). The ADSP,
  CDSP, modem and WPSS each name an SM6450 compatible with an existing one
  as fallback, because the vendor's PAS driver gives parrot the same values
  as SM8450 (ADSP, CDSP, modem) and SC7280 (WPSS). The fallbacks are chosen
  so that each one's power domains are the rails the stock node names.
  pkgrel 13's driver binds them unchanged. The binding changes are on
  branch `sm6450-remoteproc` in `out/linux` and the WIP nodes on
  `sm6450-remoteproc-dt`. `dt_binding_check`, `CHECK_DTBS=y` and
  `check-dt.py` are clean.
  - **Reasoned:** the interrupts, smp2p bits, IPCC clients and glink ids,
    which are the stock nodes', checked by name because `check-dt.py` does
    not compare `interrupts-extended`.
  - **Reasoned:** that leaving `shutdown-ack` off the ADSP and CDSP, as
    their bindings require, costs nothing; sysmon treats it as optional.
  - **A guess:** that probing with no firmware is harmless. Probe attaches
    the power domains without voting and requests interrupts; the firmware
    request fails and each processor stays offline.
  - **Collected 2026-10-08:** the firmware, by plan n (see "The firmware
    partition is collected"). The board names
    `qcom/sm6450/Sony/columbia/{adsp,cdsp,modem,wpss}.mbn`.
    `scripts/collect-firmware.sh` reads the stock slot's `modem` partition
    from recovery with `dd`, one partition and read-only, never `modemst*`,
    `fsg` or `persist`. It then extracts the FAT image into
    `out/firmware/`, which git ignores. Plan n runs it whenever `--log` has
    left the phone in recovery. The WPSS image is `adrastea/wpss.mdt`, as
    the downstream tree names it; the others are under `image/`, split
    into `.mdt` and `.bNN`, which upstream wants squashed into one `.mbn`.

  Plan n runs after plan m: round 34 boots `out/milestone/remoteproc.dtb`
  (`regs.dtb` plus the four nodes) on pkgrel 13. `cmds-r34.sh` pushes r13's
  `qrtr`, `qcom_pil_info`, `qcom_common`, `qcom_q6v5` and `qcom_q6v5_pas`
  into the shell and loads them, then reads `/sys/class/remoteproc`, the
  deferred devices and dmesg. `qrtr` goes first because sysmon opens a QRTR
  socket at probe and defers without one. "The remote processors" in
  [06-mainline.md](06-mainline.md) has the mapping.

  Round 37 boots the ADSP if three things hold: the firmware was
  collected, it has an ADSP image, and round 34 showed the ADSP probed and
  offline. Plan n skipped it, looking for `adsp.mdt` where the image is
  `adsp2.mdt`; plan p runs it last, finding `adsp*.mdt`. The plan squashes the image with
  `pil-squash.py`. `cmds-r37.sh` pushes it to the board's firmware name
  with round 34's modules, and auto-boot starts it at probe. The image is
  tens of megabytes and the shell takes it 768 bytes a round trip, so the
  file starts with `touch /pmhold`. The plan's branches were exercised
  against stubs: each skip, and a run with a synthetic split image in
  capitals. The image lands in `pil_adsp_mem`, which is stock's
  `adsp_region`, address and size. Stock's ADSP votes on the LCX and LMX
  levels, which are the power domains its fallback, `sm8350-adsp-pas`,
  names. Sony's PAS driver marks the parrot images `uses_elf64`. That only
  sets the class of a crash dump, so mainline's ELF32-only `mdt_loader`
  is not a concern.
- **The WLAN** — Written 2026-10-08. Round 65 ran it on 2026-10-11 and
  `wlan0` came up (see "Round 65: the WLAN comes up"). It is
  the WCN3990-class core on `ath10k_snoc`, with its firmware on the WPSS.
  06-mainline had called it WCN6750, which the live node's `qcom,icnss`
  compatible rules out. The WIP node is on branch `sm6450-wifi` in
  `out/linux`; `CHECK_DTBS=y` is clean and its interrupts equal stock's.
  It needs the WPSS running its firmware first.
  - **Verified against the sources:** the MSA size. `pil_wlan_mem` in our
    SoC dtsi is 12 MiB at `0x82a00000`, from Qualcomm's
    `parrot-reserved-memory.dtsi`, which is sized for a WCN6750. Sony's
    `parrot-wcn3990.dtsi` shrinks it to 3 MiB, and the live tree has
    3 MiB. ath10k gives the firmware that size as the MSA. A WIP commit
    on `sm6450-wifi` sets 3 MiB on the board, and the SoC keeps the map's
    12.
  - **What its round needs** — written down 2026-10-08, when the week's
    work stopped, so that nothing has to be found again.
    - **Verified against pkgrel 18:** the modules are there. Their own
      `depends=` fields give the load order: `rfkill`, `cfg80211`,
      `libarc4`, `mac80211`, `ath`, `ath10k_core`, then `ath10k_snoc`
      after `qcom_common`. The package's `modules.dep` lists no
      dependencies, so a round has to load them in that order itself.
    - **Verified against the source:** the pd-mapper's SM6450 entry
      reuses SM8550's list, which has the ADSP, CDSP and modem domains
      and nothing for the WPSS. The `.jsn` files stock keeps in
      `modem_b` have nothing for the WPSS either, so it may not need a
      domain. That is a guess until a round shows the WLAN firmware's
      QMI service coming up.
    - **Done 2026-10-11:** `adrastea/wpss.mdt` squashed into the
      board's `wpss.mbn`, linux-firmware's `firmware-5.bin`, and a
      `board-2.bin` that `scripts/ath10k-board2.py` packs from stock's
      `bdwlan` files, because linux-firmware has no board data for this
      phone. Round 65 pushed them and booted the `sm6450-wifi` tree on
      pkgrel 18. The WPSS needed no protection domain.
- **Bluetooth** — Written 2026-10-08. Round 35 ran it (see "Round 35:
  Bluetooth binds, and the version reply is a WCN3991's"). Bluetooth needs
  no remote processor. The controller is the
  WCN39xx radio on a UART, and `hci_qca` loads its firmware over that
  UART. So branch `sm6450-bt` in `out/linux` starts from `sm6450`, not
  from the remoteprocs. Its two WIP commits add QUP wrapper 1 with its
  UART at `a94000` and the board's `qcom,wcn3990-bt` child. That UART is
  stock's "se11", on pins 14 to 17, with the mainline function `qup1_se5`.
  `CHECK_DTBS=y` is clean, and `check-dt.py` finds the UART's interrupt
  equal to stock's.
  - **Reasoned:** the rails. Stock's `bt_wcn3990` names io, xtal, core
    and pa supplies, at 1.7 to 1.9, 1.7 to 1.9, 1.304 and 3.0 to 3.312 V.
    Those are WCN3990's vddio, vddxo, vddrf and vddch0, in that order.
    hci_qca sets none of these voltages, so the board's floors have to;
    round 35 found two of them too low. The switch
    control line is GPIO 61, as on stock. The pins' biases are stock's
    active state.
  - **Reasoned, from round 35:** the chip is a WCN3991. Stock's
    `qcom,wcn3990` is the compatible Qualcomm's `btpower` gives every
    WCN39xx, and the vendor stack reads the chip at runtime. Mainline takes
    the chip type from the compatible instead, and from it the firmware
    names and even the layout of the version reply. Round 35's reply was
    one byte longer than a WCN3990's, the length a WCN3991's has, so
    round 44 names a WCN3991. Its Product ID, SOC Version and ROM Version
    will settle it.
  - **The firmware is linux-firmware's, not the phone's.** `cmds-r35.sh`
    pushes every WCN39xx rampatch and NVM file in Alpine's
    `linux-firmware-qca` 20260810, 680 KB:
    - `crbtfw`/`crnv` 21 and 32, with `crnv32u`, for WCN3990, 3991 and
      3998;
    - `apbtfw`/`apnv` 10 and 11, for WCN3988;
    - `cmbtfw`/`cmnv` 12 and 13, for WCN3950.

    Setup can finish if the guess is right, and a failed request names the
    file it wanted if not. Upstream would ship these same files. Stock's
    own Bluetooth firmware has not been looked for.

  The round pushes the files, then r13's `rfkill`, `ecc`, `ecdh_generic`,
  `bluetooth`, `pwrseq-core`, `btqca` and `hci_uart`, and loads them in
  that order. Registering the controller powers it on with no userspace,
  which runs setup. The core powers it off two seconds later, because no
  management socket is open. The readings are dmesg, the serdev binding,
  the debugfs version files and the regulator summary. They leave out the
  address files: `identity`, `random_address` and `static_address`.
- **The touchscreen** — Written 2026-10-08. Round 36 ran it (see "Round
  36: the touchscreen controller answers"). The controller is a FocalTech FT3519T: Sony's driver builds
  only `focaltech_upgrade_ft3519t.c` and sets `FTS_CHIP_TYPE` to
  `_FT3519T`. Mainline drives it with `edt-ft5x06`. The FT3518 entry and
  the FT3519 binding, which falls back to the FT3518, are upstream since
  2026 and postdate 6.18. Pkgrel 14 carries the three commits as
  `backport-0005` to `backport-0007` and builds the driver as a module;
  nothing else changes. Branch `sm6450-touch` in `out/linux`, above
  `sm6450-bt`, adds I2C9 and the board's node. I2C9 is QUP wrapper 1's
  serial engine 3 at `a8c000`, stock's "se9", on GPIOs 10 and 11.
  `CHECK_DTBS=y` is clean, and `check-dt.py` finds its interrupt equal to
  stock's.
  - **Verified against the stock tree:** address `0x38`, the interrupt on
    GPIO 13, falling edge, the reset on GPIO 12, active low, and the pin
    biases. The panel is 1080 by 2520, and stock's `display-coords` agree.
  - **Reasoned:** the analog supply. Stock's node names `vdd-supply` as
    `pm6450_l28`, 2.7 to 3.544 V, and a separate `focaltech,avdd-en-gpio`
    on GPIO 103. Sony's driver has its `regulator_enable(vdd)` commented
    out and drives GPIO 103 in its place. So mainline gets a fixed
    regulator switched by GPIO 103 as `vcc-supply`, and L28 is left out.
  - **A guess:** that GPIO 103 is all the chip needs. If the round's
    probe fails with an I2C error, L28 as the switch's input is the next
    thing to try.

  `cmds-r36.sh` pushes pkgrel 14's `edt-ft5x06.ko` into pkgrel 13's shell
  and loads it. It then reads the client's `model` and `fw_version`, the
  input device and the interrupt count. Nobody touches the screen during
  the round.
- **The GPU firmware is in `vendor_b`** — Collected 2026-10-11, after
  round 64. drm/msm wants three files for the Adreno 710: the SQE
  microcode, the GMU's firmware and the zap shader. Stock keeps them in
  the `vendor` partition's `/firmware`, which is a logical partition in
  `super`.
  - **Verified:** recovery maps `vendor_b` at
    `/dev/block/mapper/vendor_b`, 1249648640 bytes. `adb exec-out "dd
    if=/dev/block/mapper/vendor_b bs=1048576"` read it into
    `out/firmware/vendor_b.img` in 39 s. It is ext4, and `debugfs` inside
    `pmport` listed its `/firmware` into
    `out/firmware/vendor_b.firmware.listing`, 138 lines, and dumped the
    GPU's files into `out/firmware/gpu/`. git ignores both. Nothing was
    written to the phone, and `super` was only read.
  - **Verified:** the files. `a710_sqe.fw`, 36308 bytes;
    `gmu_gen70000.bin`, 57272 bytes; and the zap shader both split, as
    `a710_zap.mdt` with `.b00` to `.b02`, and whole, as `a710_zap.mbn`,
    12088 bytes. Stock's reserved region for the zap shader,
    `pil_gpu_mem`, is 0x2000 bytes.
- **The GPU** — Written 2026-10-11. Round 66 panicked at boot (see
  "Round 66: the GPU at boot panics"), and round 67 goes step by step.
  The Adreno 710 is
  chip ID 0x07010000. Mesa's `freedreno_devices.py` knows it as a 7xx
  gen 1 part derived from the A730, but 6.18's drm/msm has no entry for
  it. Pkgrel 19 adds one, and the nodes are WIP on branch `sm6450-gpu`.
  - **Verified against KGSL:** Qualcomm's downstream GPU driver calls it
    `gen7_3_0`, in `adreno-gpulist.h`. It is a 7xx gen 1 part with no BV
    pipe, 512 KiB of GMEM, hang detection 0xcfffff, QoS 0x3, a 16 MiB
    UCHE GMEM base, and the A730's protect list. Its firmware names are
    `a710_sqe.fw`, `gmu_gen70000.bin` and `a710_zap`. KGSL emits the BV
    packets even on a part with no BV pipe, and its CP_ME_INIT matches
    drm/msm's, so drm/msm's submit path is used unchanged.
  - **Reasoned:** the highest bank bit is 14, as the display's is,
    because the live tree's `qcom,ddr-type` is 7, LPDDR4X. One review
    says LPDDR5, which would make it 15. Nothing reads the DDR type at
    runtime yet, and the code says so.
  - **Reasoned:** `MSM_PARAM_GMEM_BASE` returns 0 for the A710, as
    upstream does for later 6xx and the 740 family. A March 2026 thread
    on the list said the A730's 0x100000 was wrong.
  - **Left for later:** preemption, IFPC and ACD, the speed bin and the
    cooling maps.
  - The nodes on `sm6450-gpu`: the graphics clock controller at
    `3d90000`; the GPU at `3d00000` with four operating points from 295
    to 600 MHz; its GMU at `3d6a000` with two; and the GPU's SMMU at
    `3da0000`. Their addresses, interrupts and levels are the stock
    tree's. The board enables the GPU and names its zap shader
    `qcom/sm6450/Sony/columbia/a710_zap.mbn`. `CHECK_DTBS=y` reports
    only the two compatibles it always has, the touchscreen's and the
    panel's.
  - Two bindings change: `qcom,sm6450-smmu-500` joins the Adreno SMMUs,
    and `qcom,adreno-gmu-710.0` joins the GMU list beside the 730.
  - drm/msm loads the GPU on the first open of its device, not at boot.
    Without `msm.separate_gpu_kms=1` the display's DRM device waits on
    the GPU, so round 66 passes it and the display does not depend on
    the GPU's result.
  - `scripts/msm-submit.c` is the test, because the initramfs has no
    Mesa. It opens the render node, prints the GPU's IDs, and submits
    CP_MEM_WRITE jobs one at a time. A job passes when its fence
    signals and the buffer holds its value.
- **Pkgrel 14 is pkgrel 13 plus `edt-ft5x06`** — Verified 2026-10-08.
  It built in six minutes with the warm ccache, with no compiler warnings.
  All 427 of pkgrel 13's modules are byte-identical in pkgrel 14 once
  their signatures are stripped, and `edt-ft5x06.ko` is the only new one.
  That is what lets the module load into pkgrel 13's shell. The kernel is
  built with clang's kCFI and shadow call stack, so a module from any
  other compiler, or from `out/kbuild`'s defconfig build, would fail its
  first indirect call. Each build signs with its own key. Signatures are
  not enforced and lockdown is off, so the module loads with a taint.
- **Pkgrel 15 moves the series to the fold** — Done 2026-10-08, and in
  the rootfs since plan q put it there at 16:08. The series now carries
  what has run:
  - the flattened dwc3 node, the thermal zones and the interconnect,
    from rounds 25, 26, 30, 31 and 43;
  - the regulator floors, from rounds 39 and 43;
  - the four remote processors, from round 34.

  New in it are the SM6450 UFS PHY entry with the ICE and UFS host
  bindings, the ADSP, CDSP, MPSS and WPSS bindings, the pd-mapper entry,
  and the graphics clock controller's binding and driver. That driver is
  a module nothing has loaded yet. The bindings and drivers come before
  the device tree commits, so every compatible is documented by the time
  a tree names it. There are 46 patches. Branch `sm6450-r14` keeps the
  series as pkgrel 14 built it.
- **The topic branches are rebuilt on pkgrel 15's series** — Done
  2026-10-08. The branches whose work the series now carries are
  retired: `sm6450-fold`, `-gccfix`, `-vreg`, `-remoteproc`,
  `-remoteproc-dt`, `-dispcc`, `-touch`, `-ufs` and `-pdmapper`. They and
  the old versions of the rebuilt branches are kept as
  `sm6450-pre-r15-*`. What remains WIP:
  - `sm6450-next`: UFS, QUP wrapper 1 with I2C9, and the touchscreen,
    each node now with its interconnect paths;
  - `sm6450-bt`: UART11 with its paths and the WCN3991, on
    `sm6450-next`;
  - `sm6450-usb3`: the combo PHY's binding, driver entry and nodes;
  - `sm6450-wifi`: the WLAN node;
  - `sm6450-display`: the display clock controller's node, the panel and
    the display subsystem, with round 48's fix in the board commit;
  - `sm6450-gpucc`: the graphics clock controller's node.

  `CHECK_DTBS=y` is clean on each, apart from the warning for the
  backported FT3519 binding. `kernel/wip/` has each branch's export.
- **Pkgrel 16 folds the rest of what has run** — Done 2026-10-08, built
  at 16:48 and in the rootfs since plan t put it there at 16:52. The
  series now also carries:
  - UFS with its PHY and crypto engine, from round 49;
  - QUP wrapper 1 with I2C9 and the touchscreen, from round 49;
  - UART11 and the WCN3991, from round 53;
  - the display clock controller's node, the display subsystem and the
    panel with its active-low vddio switch, from round 51.

  Round 54 ran all of them together on pkgrel 15 first. The package's own
  tree decompiles to exactly what round 54 booted. The display bindings
  and drivers now come before the device tree commits, like the rest.
  The package also builds `pmic_glink`, its altmode client, `typec_ucsi`,
  `ucsi_glink` and `qcom_battmgr` as modules, for round 56. There are
  still 46 patches. Branch `sm6450-r15` keeps the series as pkgrel 15
  built it.
- **The topic branches are rebuilt on pkgrel 16's series** — Done
  2026-10-08. `sm6450-next`, `-bt` and `-display` are folded, and are
  kept as `sm6450-pre-r16-*`, with `sm6450-x`, the branch that stacked
  them for round 54. `sm6450-fold` is gone, because it is `sm6450` now.
  What remains WIP:
  - `sm6450-glink`, new: the SM6450 `pmic-glink` compatible, the
    controller as a role switch with its high-speed port, and the
    board's `pmic-glink` node with its one Type-C connector, in place
    of `dr_mode = "peripheral"`;
  - `sm6450-usb3`: the combo PHY's binding, driver entry and nodes;
  - `sm6450-wifi`: the WLAN node;
  - `sm6450-gpucc`: the graphics clock controller's node.

  `CHECK_DTBS=y` is clean on each, apart from two warnings, for the
  FT3519 and the SOFEF01-M panel. Both bindings are backports that the
  aport applies, and `out/kbuild` builds the series without them.
- **Pkgrel 18 folds what rounds 58 to 63 ran** — Done 2026-10-08, built
  at 19:05, not yet in the rootfs. Round 63 passed, so `sm6450` is now
  the fold. The series now also carries:
  - the USB GDSC in retention, in the GCC driver;
  - the SM6450 `pmic-glink` compatible, in its binding;
  - in the SoC tree, the controller as a role switch with its high-speed
    port, the PHY's reference gate, and DMA coherence for the QUP
    wrappers and USB;
  - the board's `pmic-glink` node with its Type-C connector, in place of
    `dr_mode = "peripheral"`.

  There are still 47 patches, because the GDSC change is folded and the
  binding is new. The package's own tree is byte-identical to
  `fold18.dtb`, which round 63 booted. The PHY re-init stays a bring-up
  patch, and `bringup-dwc3-qcom-phy-reinit.patch` comes out the same on
  the new series. Branch `sm6450-r17` keeps the series as pkgrel 17
  built it.
- **The topic branches are rebuilt on pkgrel 18's series** — Done
  2026-10-08. `sm6450-glink`, `-hsref`, `-coherent` and `-glinkref` are
  folded. They are kept as `sm6450-pre-r18-*`, with the old `-usb3`,
  `-wifi`, `-gpucc` and `-dwc3pm`. What remains WIP:
  - `sm6450-usb3`: the combo PHY's binding, its driver entry and a
    disabled node. The board commit that enabled the PHY is dropped,
    because the port is USB 2.0 (see "The USB3 PHY is SM8350's"). The
    board keeps the controller at high speed itself.
  - `sm6450-wifi`: the WLAN node, unchanged;
  - `sm6450-gpucc`: the graphics clock controller's node, unchanged;
  - `sm6450-dwc3pm`: the PHY re-init that the bring-up patch is made
    from.

  `CHECK_DTBS=y` is clean on each, apart from the two known warnings,
  and `dwc3-qcom.o` builds with W=1. On `sm6450-usb3` the controller's
  SuperSpeed endpoint points at the disabled PHY. fw_devlink makes no
  link to an unavailable supplier (`of_link_to_phandle`), so that cannot
  hold the controller back.
- **Round 24: the first round with commands of its own** — Verified
  2026-10-08, 14:06. pkgrel 10 on `regs.dtb`. The gadget appeared 16
  seconds after the reboot, and `tsh.py` ran all of `cmds-r24.sh` in the
  shell: 562 lines in `out/try-kernel/live-r24.txt`. The clock, regulator,
  power-domain, GPIO and interrupt state it reads is the baseline later
  rounds are compared against.
  - The CPUs reach their deepest idle states. cpu0 entered `cpu-sleep-0-1`
    249 times and cpu4 `cpu-sleep-1-1` 50 times, and the cluster domain
    entered its deeper state 38 times, with 231 refusals. So the CPUs do
    suspend through PSCI whenever the shell sleeps, which is what the
    cpuidle bullet above rests on.
  - cpufreq has both policies, `policy0` and `policy4`.
  - `/sys/class/watchdog/watchdog0` has none of the usual attributes,
    because `CONFIG_WATCHDOG_SYSFS` is off. That says nothing about the
    driver.
- **Round 25: the flattened dwc3 binding works** — Verified 2026-10-08,
  14:10. pkgrel 10 on `usbflat.dtb`. The gadget appeared 16 seconds after
  the reboot, as on `regs.dtb`. `a600000.usb` is bound to `dwc3-qcom` by
  its `qcom,sm6450-dwc3` compatible and is the UDC, and `devices_deferred`
  is empty. The transcript is `out/try-kernel/live-r25.txt`.
- **The flattened node is folded into the series, on a staging branch** —
  Done 2026-10-08. Branch `sm6450-fold` in `out/linux` is the series with
  round 25's change folded in. The binding commit now documents SM6450 in
  `qcom,snps-dwc3.yaml`, and the SoC and board commits carry the single
  node. The board DTB it built then was byte-identical to `usbflat.dtb`,
  and `CHECK_DTBS=y` and the binding check were clean. `sm6450`, and with it
  pkgrel 14, is unchanged. A package carries the fold from the next
  pkgrel, together with whatever else has passed by then, so the queued
  rounds keep the packages they were planned with.
  `scripts/export-wip.sh` exports the fold whole, from v6.18.55, into
  `kernel/wip/sm6450-fold/`. A branch cut from it, such as `sm6450-usb3`,
  is exported against it.
- **Round 26: every zone reads, and each CPU zone follows its core** —
  Verified 2026-10-08, 14:19. pkgrel 10 on `thermal.dtb`. Both TSENS
  controllers are bound, `devices_deferred` is empty, and all 28 TSENS
  zones read between 40 and 44 C at idle, beside the two PMIC zones.
  Both cpufreq policies are cooling devices. `cmds-r26.sh` loaded one core
  at a time for 30 seconds through a cgroup cpuset, and the zones that
  rose most are the ones the stock tree puts on that core:
  - cpu4: `cpu4-1` +24.7 C and `cpu4-0` +23.0 C, then `cpu0` +16.0 C.
  - cpu7: `cpu7-1` +19.3 C and `cpu7-0` +15.2 C.
  - cpu0, a Cortex-A55: `cpu0` +3.0 C, every other zone less.

  The transcript is `out/try-kernel/live-r26.txt`. Stock gives each
  controller a third, edge-triggered interrupt (SPI 500 and 501) that the
  upstream binding has no name for and the driver does not use, so it
  stays out.
- **The thermal zones are folded too** — Done 2026-10-08. On
  `sm6450-fold`, the TSENS binding sits with the other bindings, and the
  nodes are in the SoC commit, whose message now names them. The change
  to `sm6450.dtsi` is line for line round 26's. `CHECK_DTBS=y`, the
  binding check and `check-dt.py` are clean. Branches `sm6450-usbflat`
  and `sm6450-thermal` are retired, with their exports; their tips were
  `9bc6530ee` and `648d82e5b`. `sm6450-usb3` is rebased onto the new fold.
- **The interconnect is folded too** — Done 2026-10-08, after rounds 30
  and 31. On `sm6450-fold` the NoC nodes and the QUP, UART, SD and USB
  paths are in the SoC commit. Its message lists the ten NoCs and two
  virtual providers, and says the SD card's votes are SM6350's, like the
  rest of its OPP table. `CHECK_DTBS=y` and `check-dt.py` are clean on the
  board DTB it builds. Branch `sm6450-icc` is retired with its export, and
  `sm6450-pre-icc-fold` keeps the fold as it was before. Three branches
  are cut from the new fold:
  - `sm6450-usb3`, rebased onto it;
  - `sm6450-vreg`, one WIP commit that raises the fourteen regulator
    floors in the board source, line for line what `scripts/vreg-floors.py`
    did to the `-vreg` trees;
  - `sm6450-gpucc`, the graphics clock controller's binding, driver and
    WIP node, generated by `scripts/downstream-to-mainline.py`. Nothing
    has run it.

  Round 43, last in plan o, boots `fold-vreg.dtb`, built from
  `sm6450-vreg`: the fold as a whole, with the floors.

## The boot images

- **Round 28: UFS links up, then the first query times out** — Verified
  2026-10-08, 14:21. pkgrel 11 on `ufs8450.dtb`. The ICE probed (v3.2.1,
  raw keys only), and the host got through link startup and NOP OUT. Then
  setting fDeviceInit timed out three times, 1.5 seconds each, and the
  probe failed with -EAGAIN; no disk. The UFS GDSC was on and no clock
  was missing. The transcript is `out/try-kernel/live-r28.txt`.
  - The plan's disk count was wrong. `cmds-r28.sh` echoed `/sys/block/sd*`
    unexpanded when there was no disk, plan k counted that line as one,
    and so round 29, the same boot without the ICE, never ran. Its rail
    grep used `l13`-style names, where this kernel's are `ldo13`, and
    matched nothing.
- **Round 27: the UFS PHY was not dumped** — Verified 2026-10-08, 14:30.
  pkgrel 11 on `regs.dtb`. The UFS GDSC was off, so `cmds-r27.sh` left
  the PHY alone, as written. The USB3 PHY's aux clocks and GDSC were on.
- **The board leaves every RPMh rail at the bottom of its window** —
  Verified 2026-10-08, from round 24's log and live shell. The board copies
  the stock tree's windows, but few mainline consumers set a voltage: not
  ufshcd, not the QMP and Femto PHYs, not drm/msm's DSI. For a rail it
  cannot read back, the regulator core sets the window's floor, and round
  24's log has the 42 "Setting min-max" lines that say so. Stock's vendor
  driver starts each rail at its `qcom,init-voltage` instead. Fourteen
  rails differ, and among them:
  - UFS: VCCQ (L13) at 1.08 V and VCCQ2 (L19) at 1.62 V, where stock
    starts them at 1.2 V and 1.8 V. Both are under the UFS minimum. The
    PHY's L5 is at 0.83 V for 0.88 V, and its L16 at 1.14 V for 1.2 V.
  - The USB2 PHY: L25 at 2.7 V for 3.072 V and L23 at 1.65 V for 1.8 V.
    USB works regardless.
  - The USB3 PHY: L7 at 0.83 V for 0.912 V, and L16.
  - DSI: L5 as vdds and L16 as vdda.
- **So the UFS timeout was under-voltage** — Verified 2026-10-08 by
  round 39, which found every disk on round 28's tree with the floors
  raised (see "Round 39: UFS works with the floors raised"). Before that
  it was a guess, the likeliest of the candidates: a device that answers
  NOP OUT and then not a query fits a device controller running out of
  spec. `scripts/vreg-floors.py`
  rewrites a decompiled tree so every floor below the stock init voltage
  is raised to it, and changes nothing else. The `-vreg` trees in
  `out/milestone/` are built that way, and the queued rounds now use them:
  - Round 32, plan m, boots `display-vreg.dtb`, or `display-noqos-vreg.dtb`.
  - Round 38, plan o, boots `usb3-8350-vreg.dtb`.
  - Rounds 39 and 40, new in plan o after round 38, retry UFS on
    `ufs8450-vreg.dtb`, and without the ICE on `ufs8450-noice-vreg.dtb`
    if round 39 finds no disk. `cmds-r39.sh` is `cmds-r28.sh` with both
    mistakes fixed.

  The fix in the series is a board change, the floors raised in the
  source. Round 43 ran it with the rest of the fold, and pkgrel 15
  carries it.
- **Rounds 30 and 31: the interconnect works** — Verified 2026-10-08,
  14:31 and 14:36. pkgrel 12, on `icc-noqos.dtb` and then on `icc.dtb`,
  the tree as it will be submitted. In both, all ten NoC providers
  registered beside the two virtual ones and `devices_deferred` was empty.
  The UART, the SD card and USB each vote their paths: USB 240000/700000
  kBps on the DDR path, the SD card at SDR104 at 202 MHz, the gadget
  configured. Round 30's tree has no `reg` on the NoCs, so each printed an
  "invalid resource" error and skipped QoS, as intended. Round 31 wrote
  the QoS registers and printed nothing. The transcripts are
  `out/try-kernel/live-r30.txt` and `live-r31.txt`.
- **Round 32: the display pipeline binds, and a DCS read wedges it** —
  Verified 2026-10-08, 14:47. pkgrel 13 on `display-vreg.dtb`. The MDSS, the
  DPU, DSI, its PHY, the display clock controller and the SOFEF01 panel
  driver all bound, and `devices_deferred` was empty. The DPU reads back
  `dpu hardware revision:0x80030000`, 8.3. The connector is connected at
  1080x2520, and fbcon took fb0. The DSI PLL runs at 1132.18 MHz, against
  the 1132.29 MHz first in stock's `qcom,dsi-dyn-clk-list`, with the pixel
  clock at 188.7 MHz and the byte clock at 141.5 MHz. The transcript is
  `out/try-kernel/live-r32.txt`.
  - **Verified:** the first error is our own. The live commands'
    backlight line read `actual_brightness`, which the panel driver answers
    with a DCS read of 0x52 in high-speed mode. The read's transfer timed
    out (`dsi_cmds2buf_tx: cmd dma tx failed, type=0x6, data0=0x52,
    ret=-110` at 6.74 s), and every command after it timed out too. So did
    every frame: `frame done timeout`, then `kickoff timeout`, then `panel
    dead event` at 8.83 s.
  - **Reasoned:** frames went out before the read. A kickoff with no
    reply times out after five frames, 83 ms. The panel was enabled at
    about 1.6 s, and fbcon's cursor commits frames, yet there was no
    timeout until 6.6 s.
  - **Not known:** whether the panel drives TE. The DPU's tear check
    takes its vsync from the TE pin, GPIO 99. Its line counter runs on
    without TE and wraps every 0xfff0 lines, about 0.43 s, so frames may go
    out with no TE at all.
  - **Not known:** why the read fails. The panel may not answer the bus
    turnaround, or the read may collide with a frame transfer.
  - Round 41, at the head of plan o, boots the same tree with
    `cmds-r41.sh`. That script keeps the read for last. Before it, it reads
    the tear check's frame count twice a second apart and times 30 vblanks
    with `scripts/vblank.c`. On this panel a vblank is the read pointer
    interrupt, so 16.7 ms between them means TE is arriving.
  - If the vblanks are not 16.7 ms apart, round 42 runs the same commands
    on `display-timer0-vreg.dtb`. That tree adds `qcom,te-source =
    "timer0"` to the DSI endpoint, so INTF watchdog timer 0 paces frames
    instead of TE. Stock's panel node has `qcom,mdss-dsi-te-using-wd`.
- **Rounds 41 and 42: frames go out, and the panel answers nothing** —
  Verified 2026-10-08, 15:05 and 15:11. pkgrel 13 on `display-vreg.dtb`,
  then on `display-timer0-vreg.dtb`, both with `cmds-r41.sh`. Before the
  read, neither logged an error. The console write, 10 MB of noise into
  `/dev/fb0` and a brightness write of 400 all went through, and
  `INTF_FRAME_COUNT` rose with each commit. The transcripts are
  `out/try-kernel/live-r41.txt` and `live-r42.txt`.
  - **Verified:** no TE reaches the DPU. In round 41 the vsync source is
    the TE pin (`MDP_VSYNC_SEL` 0, stock's `qcom,panel-te-source` too).
    The tear check's TE count, the top half of `INTF_TEAR_INT_COUNT_VAL`,
    stayed 0. Its line counter ran to 3919, past the 2520-line frame. The
    vblanks came 33.1 ms apart, which is the counter wrapping at its sync
    height, twice vtotal: 5040 lines at 126 ticks of 19.2 MHz each.
  - **Verified:** watchdog timer 0 paces frames instead. In round 42
    `MDP_VSYNC_SEL` is 0xf, the TE count rose by 60 a second, and the
    vblanks came 16.667 ms apart.
  - **Verified:** the read fails without TE involved. In both rounds the
    DCS read of 0x52 timed out (`cmd dma tx failed, type=0x6`), and the
    host stayed wedged after it, as in round 32.
  - **Reasoned:** the panel is not running. A write needs nothing back
    from the panel, but TE and a read's bus turnaround both do. The panel
    driver sets no voltage on vci, and its comment says 3.0 V. Stock's
    panel asks for 3.0 to 3.3 V on that rail, PM6150L L4, and L4 feeds
    nothing else. Round 32's regulator summary has L4 at 2704 mV, the
    floor of its window.
  - Round 47, at the head of plan p, boots `display-vci-vreg.dtb`. That is
    `display-vreg.dtb` with L4's floor at 3.0 V, and the TE pin as the
    vsync source again. `cmds-r47.sh` is `cmds-r41.sh` plus vci's voltage
    and the mux of the TE and reset pins. Vblanks 16.7 ms apart would mean
    the panel runs.
- **Round 34: the remote processors probe** — Verified 2026-10-08, 14:50.
  pkgrel 13 on `remoteproc.dtb`. The five modules loaded, and the ADSP,
  modem, WPSS and CDSP registered as `remoteproc0` to `remoteproc3`, each
  `offline` with its board firmware name. No firmware was present yet.
  `devices_deferred` was empty and nothing crashed.
- **The firmware partition is collected** — Verified 2026-10-08, 14:48.
  Plan n read `modem_b` from recovery, read-only, into
  `out/firmware/modem_b/`. It holds the CDSP, modem and IPA images, the WPSS
  at `adrastea/wpss.mdt`, and the pd-mapper's `.jsn` files: `adspr`,
  `adsps`, `adspua`, `battmgr`, `cdspr` and `modemr`. There is no
  `adsp.mdt`. The ADSP image is `adsp2.mdt`, 16.6 MB in 43 segments,
  because stock's `qcom,adsp-loader` picks the name from a fuse, its
  `adsp_variant` nvmem cell, and the partition carries only this variant.
  Plan n looked for `adsp.mdt`, so it skipped round 37. Plan p runs round
  37 last, squashing `adsp2.mdt` into the `adsp.mbn` the board names,
  16,668,344 bytes.
- **Round 35: Bluetooth binds, and the version reply is a WCN3991's** —
  Verified 2026-10-08, 14:55. pkgrel 13 on `bt.dtb`. The UART at `a94000`
  bound as `ttyHS1` on pins 14 to 17, `hci_uart_qca` bound its serdev
  child, and setup ran as "wcn399x". It failed four times the same way:
  "Frame reassembly failed (-84)" 40 ms in, then "QCA Version size
  mismatch len 15". The transcript is `out/try-kernel/live-r35.txt`.
  - **Verified against the source:** btqca expects 14 bytes from a
    WCN3990 and 15 from a WCN3991. It is the only WCN39xx chip hci_qca
    knows that it expects 15 from.
  - **Verified:** two of the radio's rails ran below stock. hci_qca sets
    loads on its rails but no voltage, so vddrf (PM6450 L14) ran at
    1152 mV and vddxo (PM6150L L1) at 1624 mV. Stock's Bluetooth driver
    asks for 1.304 V and 1.7 to 1.9 V, and its WLAN driver for 1.304 V and
    1.8 V. Both rails feed only this chip.
  - Branch `sm6450-bt` has a third WIP commit: `qcom,wcn3991-bt`, with
    L14's floor at 1.304 V and L1's at 1.8 V. Round 44 in plan p boots it
    as `bt3991-vreg.dtb`, with the regulator floors of `sm6450-vreg`. If
    that round does not read the version, round 45 boots the same tree
    with round 35's compatible, `bt3990-vreg.dtb`. Both run `cmds-r44.sh`,
    which loads btqca with dynamic debug and starts `scripts/hcimon.c`
    before `hci_uart`. hcimon prints every HCI command and event from
    the kernel's monitor channel, the one btmon reads. It holds back the
    controller's address: the monitor's index packets and the reply to
    Read BD_ADDR print without their payload.
- **Round 36: the touchscreen controller answers** — Verified 2026-10-08,
  15:00. pkgrel 13 on `touch.dtb` with pkgrel 14's `edt-ft5x06.ko`.
  The I2C controller at `a8c000` bound on GPIOs 10 and 11, and the client
  at `0x38` probed. It turned `ts_avdd`, the GPIO 103 switch, on and read
  the chip's registers: model "generic ft5x06 (48)", report rate 12,
  threshold 55. An input device registered. The interrupt count stayed 0,
  but nobody touched the screen, so touches remain untested.
- **Touch works** — Verified at the phone 2026-10-11, by the user, who
  touched the screen while round 64 ran. The round had loaded
  `edt-ft5x06` at about 17:09, on pkgrel 18's own tree. That is the
  first touch anyone has made on the mainline kernel. Until now only
  the driver's probe had been checked.
  - Device package pkgrel 4 puts `edt-ft5x06` in the mainline
    initramfs' modules, so the initramfs' on-screen keyboard has touch
    without a round loading the driver. Plan 20261011b put it in the
    rootfs, and in round 65 the driver was loaded and bound before the
    round's commands ran.
- **Round 39: UFS works with the floors raised** — Verified 2026-10-08,
  15:21. pkgrel 13 on `ufs8450-vreg.dtb`, which is round 28's tree with
  the fourteen floors raised and nothing else changed. What pkgrel 13
  adds over pkgrel 11, the NoC and display drivers, has no node in it.
  The host linked at HS-G3 on two lanes, and the three LUNs attached as
  `sda`, `sdb` and `sdc`. VCCQ ran at 1.2 V and VCCQ2 at 1.8 V, as on
  stock. Nothing wrote to UFS. Round 40, the same boot without the ICE,
  was for a round 39 with no disk, so it did not run. The transcript is
  `out/try-kernel/live-r39.txt`.
- **Round 43: the fold runs as a whole, with the floors** — Verified
  2026-10-08, 15:26. pkgrel 13 on `fold-vreg.dtb`: the flattened dwc3
  node, the thermal zones, the ten NoCs with their paths, and the
  fourteen floors. The gadget configured, the SD card read as
  `mmcblk0`, and `devices_deferred` was empty. That is what let pkgrel 15
  carry the fold.
- **Round 47: vci was not it** — Verified 2026-10-08, 15:32. pkgrel 13
  on `display-vci-vreg.dtb`. L4 held 3.0 V and GPIO 99 was muxed to
  `mdp_vsync`, and the vblanks still came 33.1 ms apart, the line counter
  wrapping, so there was still no TE. The board keeps vci at 3.0 V,
  because stock asks for it, but it was not what kept the panel silent.
- **Round 44: Bluetooth comes up as a WCN3991** — Verified 2026-10-08,
  15:40. pkgrel 13 on `bt3991-vreg.dtb`. The version reply read Product
  ID 0x0a, SOC version 0x40014320 and ROM version 0x0302, a WCN3991.
  btqca loaded linux-firmware's `crbtfw32.tlv` and `crnv32u.bin`, and
  "QCA setup on UART is completed" came 1.03 s after setup started. One
  "Frame reassembly failed (-84)" still came 40 ms in, before the version
  request, and cost nothing. vddxo held 1.8 V. Round 45 was for a round
  44 that did not read the version, so it did not run. The transcript is
  `out/try-kernel/live-r44.txt`; its hcimon lines leave out the address.
- **Round 37: the ADSP boots, and the gadget goes with it** — Verified
  2026-10-08, 15:51. pkgrel 13 on `remoteproc.dtb`, with `adsp.mbn`
  squashed from `adsp2.mdt`. The modules loaded and auto-boot started the
  ADSP: "remote processor adsp is now up" at 94.96 s, 0.2 s after it
  powered up. 0.7 s later the host saw the gadget disconnect, cleanly,
  and nothing after it. The phone ran on for 13 minutes with the UDC in
  `default`, and its card record says so. `tsh.py` gave up after 300 s.
  The transcripts are `out/try-kernel/live-r37.txt` and `log-r37.txt`.
  - **Verified:** the loop could not recover. The live commands had
    created `/pmhold`, and with the shell gone nothing removed it, so
    neither the watchdog nor the backup reset the phone. Someone had to.
    The hold is a lease now (see "The hold is a lease").
  - **Guess:** the ADSP runs the charger and Type-C firmware, the battery
    manager's `battmgr` domain among them, and takes the port over once
    it is up. It may run charger detection on D+ and D-, or switch the
    port's role, with nothing on our side answering it over
    `pmic_glink`. Upstream boards on SM8550 and later describe that peer
    with a `pmic-glink` node, a connector and a role switch to dwc3.
    Pkgrel 15 builds neither `QCOM_PMIC_GLINK` nor `TYPEC_UCSI`.
  - **Not known:** whether the pd-mapper matters. Round 37 did not load
    it.
- **Round 48: the panel's logic supply was switched the wrong way
  round** — Verified 2026-10-08, 16:03. pkgrel 13 on `display-vddio.dtb`,
  round 47's tree with the switch's flag inverted. Stock's vddio is a
  `qti-regulator-fixed` on PM6150L GPIO 9 flagged `GPIO_ACTIVE_LOW`.
  gpiolib's quirk that lets `enable-active-high` override the flag
  covers only `regulator-fixed`, so on stock the flag stands, and the
  line is low while the supply is on. Our board drove it high. With the
  line low:
  - **Verified:** TE arrives. The tear check's TE count rose by 60 in a
    second, from 631 to 691, and the vblanks came 16.7 ms apart with the
    TE pin as the vsync source.
  - **Verified:** the panel answers. The DCS read of 0x52 behind
    `actual_brightness` returned 400, the value written before it, and
    nothing timed out.
  - **Not known:** whether the panel shows anything. Nobody has looked at
    it during a round.

  The transcript is `out/try-kernel/live-r48.txt`. Branch
  `sm6450-display` carries the fix in its board commit.
- **Round 49: pkgrel 15, with UFS, I2C9 and the touchscreen voting
  bandwidth** — Verified 2026-10-08, 16:09. Pkgrel 15 in the rootfs, on
  `next-r15.dtb`, from branch `sm6450-next`. `devices_deferred` was empty.
  The transcript is `out/try-kernel/live-r49.txt`.
  - UFS linked at HS-G3 on two lanes, and the three LUNs attached:
    `sda`, 128 GB in 97 partitions, and `sdb` and `sdc` with 5 each. The
    host votes both of its paths. They read 0 because the summary was
    read with the link in HIBERN8 and the device asleep.
  - I2C9 bound with its paths, and the touchscreen probed through pkgrel
    15's `edt-ft5x06.ko`, pushed into the shell, as in round 36.
  - The seven remoteproc modules loaded, pd-mapper among them. The ADSP
    and CDSP tried to boot and stopped at the missing firmware, `-2`, as
    they should with none in the rootfs.

  Round 50, the package's own tree, was for a round 49 that did not
  reach the shell, so it did not run.
- **Round 51: the display fix holds on pkgrel 15** — Verified 2026-10-08,
  16:16. pkgrel 15 on `display-r15.dtb`, from branch `sm6450-display`
  rebuilt on pkgrel 15's series. The TE count rose by 60 in a second,
  the vblanks came 16.7 ms apart, the DCS read returned 400, nothing
  logged an error and `devices_deferred` was empty. So the display WIP is
  ready to fold. The transcript is `out/try-kernel/live-r51.txt`.
- **Round 53: Bluetooth holds on pkgrel 15** — Verified 2026-10-08,
  16:24. pkgrel 15 on `bt-r15.dtb`, from branch `sm6450-bt` rebuilt on
  pkgrel 15's series, with UART11's interconnect paths. The version
  reply was a WCN3991's again, `crbtfw32.tlv` and `crnv32u.bin`
  downloaded, and the setup completed. The transcript is
  `out/try-kernel/live-r53.txt`.
- **Round 52: the ADSP again, and the gadget goes the same way** —
  Verified 2026-10-08, 16:34. pkgrel 15 on its own tree, with
  `out/tools/adsp-watch.sh` loading the remoteproc modules, the
  pd-mapper first, and logging to the kernel log. The card's first
  attempt carries it all; `out/try-kernel/bootlog-card-20261008-164104.txt`
  is the dump.
  - **Verified:** "remote processor adsp is now up" at 125.08 s. Within
    90 ms dwc3's link state went from On to Early Suspend (5), then
    Suspend (3), with run/stop still set. The UDC fell to `default` at
    125.86 s. It opened six glink channels: `IPCRTR`,
    `PMIC_LOGS_ADSP_APPS`, `PMIC_RTR_ADSP_APPS`, `adsp_apps`,
    `fastrpcglink-apps-dsp` and `rpmsg_ctrl`.
  - **Verified:** neither attempt to bring the host back did anything.
    A pull-up toggle through `soft_connect` at 158 s and a gadget rebind
    at 190 s both returned 0, and the link stayed in Suspend.
  - **Verified:** the hold lapsed by itself. "hold lapsed at 241: gadget
    last configured at 151, /pmhold touched 117 s ago". The phone reset,
    fell back to Android, and the queue read the card with no one at
    the phone. This is the first time the lease has run on the device.
  - **Reasoned:** the SOF number in DSTS bits 17:3 kept advancing for
    0.7 s after the link state left On, by about 1040 microframes per
    130 ms poll. It froze when the UDC fell to `default`. So frames kept
    arriving for that 0.7 s, and then the host was gone. Round 37's gap
    was also 0.7 s.
  - **Guess:** the charger firmware runs BC1.2 detection on D+ and D-
    as it starts, and takes the lines from the PHY to do it. Or it
    changes the CC terminations, and the host drops VBUS. Either way it
    does not hand the port back without a peer.
  - **Not shown:** whether the pd-mapper matters. Round 52 loaded it,
    but not `qrtr-smd`, QRTR's transport over the `IPCRTR` channel, so
    nothing from the ADSP could reach it.

  Plan r's summary line says "no ADSP". That line is wrong: the plan
  read only `log-r52.txt`, which holds the card's last attempt, and the
  ADSP came up in the first. Plan t's summary for round 56 makes the
  same mistake, so its card dump has to be read directly.
- **Round 54: the fold runs as a whole on pkgrel 15** — Verified
  2026-10-08, 16:44. pkgrel 15 on `fold16.dtb`, branch `sm6450-x`, which
  stacked the WIP of rounds 49, 51 and 53 the way pkgrel 16 folds it.
  Everything passed together:
  - the vblanks came 16.78 ms apart;
  - the backlight took 400 and read it back;
  - UFS linked at HS-G3 on two lanes, with `sda`, `sdb` and `sdc`;
  - the touchscreen bound to `edt_ft5x06`;
  - the Bluetooth setup completed.

  The transcript is `out/try-kernel/live-r54.txt`.
- **Round 55: pkgrel 16 on its own tree** — Verified 2026-10-08, 16:54,
  with round 54's checks. Everything passed again:
  - the vblanks came 16.72 ms apart;
  - the backlight read back 400;
  - `sda`, `sdb` and `sdc` were there;
  - the touchscreen bound;
  - the Bluetooth setup completed;
  - `devices_deferred` was empty, and no driver logged an error.

  The UFS gear read HS-G1 this time, on an idle link. The transcript is
  `out/try-kernel/live-r55.txt`.
- **The panel lights** — Owner-reported 2026-10-08, about 17:00. The
  owner saw a terminal and an on-screen keyboard on the phone: the pmOS
  debug shell's, drawn through drm/msm and the SOFEF01-M driver. It was
  pkgrel 16, during round 55 or the boots after it, which all carry the
  same display nodes. This is the first time anyone has seen the screen
  on the mainline kernel.
- **Round 56: `pmic_glink` with the ADSP** — Did not run, 2026-10-08,
  16:59. It was plan t's last round, gated on round 55 reaching the
  shell, which it did. The flash went through. Then `fastboot reboot`
  reported "Status read failed (No such device)" for a reboot that had
  happened, and `try-kernel.sh`, under `set -e`, stopped there. So its
  kernel booted with nothing running its commands. The queue's
  `bring_back` resets such a phone over the gadget until stock answers,
  with no one at the phone. `try-kernel.sh` now checks whether the phone
  is still in fastboot after that error, as `settle_slot` has done since
  round 20. Plan u runs the same round as round 57, with `cmds-r56.sh`,
  once plan t's queue exits. The round boots `glink-r16.dtb`: the
  package's tree with branch `sm6450-glink`'s three commits. `out/tools/glink-watch.sh` is round 52's
  watcher with four changes:
  - it loads `qrtr-smd`;
  - it loads `pmic_glink`, its altmode client, `ucsi_glink` and
    `qcom_battmgr` before the ADSP, with dynamic debug on for the three
    that talk to it;
  - it adds the role switch's role, the Type-C port's roles and partner,
    and the power supplies' state to what it logs;
  - it has one more recovery step: at 45 s it sets the role back to
    `device`, if UCSI has set anything else.

  It reads named power supply attributes only. It never reads the
  battery's `serial_number`, nor any `uevent`, which carries it.
- **Round 57: `pmic_glink` runs, and the link still goes** — Verified
  2026-10-08, 17:09 to 17:16. Round 56 again, on `glink-r16.dtb` with
  `cmds-r56.sh`. The card's first attempt carries the watcher's log;
  `out/try-kernel/bootlog-card-20261008-171718.txt` is the dump.
  - **Verified:** every module loaded, and "remote processor adsp is now
    up" came at 124.61 s. UCSI registered at 125.07 s, interface version
    1.0.0. Port 0 came up as data role device and power role sink, with a
    partner. The auxiliary bus held the altmode, power-supply and UCSI
    devices and the pd-mapper.
  - **Verified:** the first battery and charger readings on mainline,
    from `qcom_battmgr` at 138 s. The battery was Full at 99 %, 4.482 V
    and 33.0 °C. The USB input was online at 5.11 V and 235 mA, detected
    as SDP. UCSI's own supply reported a PD source offering 3 A. The
    readings at 159, 191 and 223 s matched.
  - **Verified:** the link went as in rounds 37 and 52. It was in Suspend
    by 124.73 s, 0.12 s after the ADSP came up, while the SOF number in
    DSTS kept advancing until 125.19 s. At 125.32 s the UDC read `not
    attached`, and after that the link stayed in Suspend. VBUS never
    went: the charger read 5.1 V throughout. The pull-up toggle at 159 s
    and the gadget rebind at 192 s returned 0 and changed nothing. The
    role switch has no `role` file, because dwc3 does not allow userspace
    control, so the 45 s step wrote nothing.
  - **Verified on the host:** its kernel log has one clean `USB
    disconnect`, 119 s after it enumerated the phone, and then nothing
    until the phone rebooted 336 s later. There were no reset attempts and
    no failed enumerations, so after the drop the host never saw a pull-up
    on D+. The host's port is a Type-C port with PD 3.0.
  - **Verified:** the lease worked again: "hold lapsed at 242: gadget last
    configured at 152, /pmhold touched 119 s ago". The watchdog reset the
    phone at about 441 s of uptime. The next six attempts each reset
    within 18 s, as designed. Stock came back about five minutes after
    the drop, with no one at the phone.
  - **Reasoned:** the power domains are not the cause. Until every
    consumer has probed, rpmhpd holds every domain at its highest level,
    and the boot log says its `sync_state` waits on the four remoteprocs.
    Loading `qcom_q6v5_pas` releases it. But round 34 loaded the same
    driver, all four remoteprocs bound at 97.5 s, and its shell went on
    answering. So the votes coming down do not take USB with them; the
    ADSP running does.
  - **Guess:** the charger firmware starts with BC1.2 detection on D+ and
    D-, or with a PD reset. Either one upsets the PHY while the gadget
    holds D+ up, and the PHY or the controller does not recover without a
    reset. Stock boots the ADSP long before its gadget connects. Round 59
    tests that order.
- **Round 58: the QUP wrappers and USB are DMA-coherent** — Verified
  2026-10-08, 17:19. pkgrel 16 on `out/milestone/coherent-r16.dtb`: the
  package's tree with branch `sm6450-coherent`. It marks both QUP
  wrappers and the USB controller `dma-coherent`, as stock does, and gives
  wrapper 0 stock's SMMU stream, 0x163. A coherence mismatch corrupts DMA
  silently, so the round checked both directions:
  - a 4 MiB random file pushed over the gadget hashed on the phone to the
    host's SHA-256;
  - the first 256 KiB of it, sent back as base64, decoded on the host to
    the same bytes.

  Round 54's checks passed as well. The vblanks came 16.80 ms apart, the
  backlight read back 400, `sda` to `sdc` were there, the touchscreen
  bound and the Bluetooth setup completed. No context fault was logged.
  The transcript is `out/try-kernel/live-r58.txt`.
- **Round 59: a re-probe of the controller brings the host back** —
  Verified 2026-10-08, 17:35 to 17:39. pkgrel 16's own tree, with no
  `pmic_glink` and no role switch. `out/tools/order-watch.sh` ran
  detached and logged to the kernel log, and it stopped at the first
  phase in which a host configured the gadget again:
  0. a gadget unbind and rebind with no ADSP, as a control. Nothing had
     tested that before, and without it the failed recoveries of rounds 52
     and 57 said nothing about the ADSP;
  1. the ADSP booted with the gadget unbound, so nothing held D+ up, and
     the gadget bound again 20 s after the ADSP was up;
  2. the controller's driver unbound and bound, which takes the PHY
     through its reset and init again;
  3. the ADSP stopped, and the gadget bound once more.

  The card's first attempt carries it;
  `out/try-kernel/bootlog-card-20261008-174416.txt` is the dump.
  - **Verified:** the control works. The host configured the gadget 1 s
    after the rebind, at 131.9 s.
  - **Verified:** the order is not it. The ADSP came up at 134.39 s with
    the gadget unbound. Bound again at 155.36 s, the gadget got no host:
    the UDC stayed at `default` and the link in Suspend, as in round 57.
  - **Verified:** the re-probe works. The driver unbound at 186.2 s and
    bound at 188.2 s. The gadget, bound at 191.3 s, was configured at
    192.4 s with the ADSP still running. The link stayed On, the live
    shell came back on the same connection, and the rest of the commands
    ran. The host's log has the same story: an enumeration at 17:35:38
    for phase 0, nothing for phase 1, one at 17:36:38 for phase 2, and a
    disconnect at 17:39:30 when the watchdog reset the phone. Phase 3 did
    not run.
  - **Verified:** the PHY's three supplies read the same before and after
    the ADSP: L5 at 880 mV, L23 at 1.8 V and L25 at 3.072 V, all enabled.
  - **Verified:** `GCC_EUSB3_0_CLKREF_EN` was off at 361 s, while the link
    had been up since 192 s. The card logs of rounds 37, 52 and 57, the
    three earlier rounds that booted the ADSP, also end with it off.
    Every round without the ADSP has it on, up to 1138 s of uptime.
    Something outside Linux clears it as the ADSP comes up, since nothing
    in Linux holds it and `clk_ignore_unused` is set. The stock tree hands
    that gate to this PHY as its `ref_clk`. Yet the PHY worked with it off
    once its init had run again.
  - **Reasoned:** whatever the ADSP does at start-up leaves the PHY in a
    state that a pull-up toggle and a gadget rebind cannot clear, and that
    the PHY's reset and init do clear. Its supplies are untouched, and the
    reference gate is not needed after a re-init.
  - **Guess:** the charger firmware runs its BC1.2 detection through the
    PHY's own registers, as downstream's PHY driver lets a charger take
    D+ and D- over, and leaves overrides set.

  The transcript is `out/try-kernel/live-r59.txt`.
- **Round 60: the reference gate goes after the link does** — Verified
  2026-10-08, 17:45 to 17:49. Plan x booted
  `out/milestone/hsref-r16.dtb`, in which the PHY holds
  `GCC_EUSB3_0_CLKREF_EN` as its `ref` clock, as on stock.
  `out/tools/hsref-watch.sh` booted the ADSP with the link up, read the
  gate's bit with every poll, and dumped the PHY. The transcript is
  `out/try-kernel/live-r60.txt`, and
  `out/try-kernel/bootlog-card-20261008-175352.txt` is the card dump.
  - **Verified:** the gate is not the cause. The ADSP came up at 137.10 s.
    The link was in Suspend by 137.30 s with the gate still on. The gate
    read off only at 137.85 s, as the UDC fell to `default`. The clock
    framework still counted the PHY's enable then, so something outside
    Linux cleared the bit while Linux held it.
  - **Verified:** the driver's unbind and bind brought the host back
    again. It bound at 157.1 s and the host configured the gadget at
    161.3 s, with the ADSP running. The link stayed On until the end at
    192.6 s, and the gate was back on, because the PHY's init enables it.
    The host saw one disconnect at 17:47:24 and the next enumeration 23 s
    later.
  - **Verified, but incomplete:** the PHY dumps differ only at offsets
    0x20 and 0x30. They read 0x0e and 0x65 before the ADSP, 0x06 and 0x00
    once the link had gone, and 0x03 and 0x00 after the rebind. Every
    word reads as one byte repeated four times. The watcher's `cut` kept
    only the first word of each `regdump` line, so the dumps hold offsets
    0x00, 0x10 and so on to 0xa0, and nothing else. UTMI_CTRL0 at 0x3c,
    CFG0 at 0x94 and the rest were never read.
  - **Reasoned:** 0x20 and 0x30 are not registers mainline's driver
    writes. The dump after the rebind came before the gadget bound, with
    no pull-up on D+, so it says nothing about a working link. They look
    like status that follows the lines, not settings left behind.
- **Round 61: the charger firmware leaves the PHY non-driving** —
  Verified 2026-10-08, 17:56 to 18:06. Plan y booted
  `out/milestone/hsref-r16.dtb` again with `out/tools/phy-watch.sh`.
  The transcript is `out/try-kernel/live-r61.txt`, and
  `out/try-kernel/bootlog-card-20261008-180543.txt` is the card dump.
  - **Verified:** the ADSP read `running` at 125.48 s, and the link was
    already in Suspend at that poll. The PHY's settings had not changed
    yet. At 126.18 s they had: UTMI_CTRL0 read 0x09, not 0x01, which is
    SLEEPM plus OPMODE non-driving. CFG0 read 0x01, the DATAPATH override
    on. HS_PHY_CTRL2 read 0x0e, not 0x06, with SUSPEND_N_SEL set. The
    PHY's reference gate was off in hardware while the clock framework
    still counted it on. The UDC fell to `default` at the same poll.
  - **Verified against downstream:** that is exactly what
    `msm_hsphy_put_phy_in_non_driving_mode()` in the vendor's
    `phy-msm-snps-hs.c` writes, the same three registers with the same
    bits. Downstream calls it from its `dpdm` regulator, "for PMIC
    charger detection". The stock tree has no `dpdm` consumer, so on this
    board the charger firmware on the ADSP does it itself, for its BC1.2
    detection, and never takes the PHY back out of it.
  - **Verified:** the runtime suspend worked, and its resume ran the
    PHY's init. The controller read `suspended` after six seconds, and
    after it UTMI_CTRL0 read 0x01 and CFG0 0x00 again. But the host did
    not come back. The controller logged `failed to enable ep0out` at
    137.95, 147.80 and 157.55 s, and the link read Disconnected.
  - **Verified:** QSCRATCH did not survive the runtime suspend.
    GENERAL_CFG read 0x0d before the ADSP, after the link went and after
    the rebind, and 0x04 after the runtime cycle. That 0x04 has lost
    PIPE_UTMI_CLK_SEL and PIPE3_PHYSTATUS_SW, which dwc3-qcom sets only at
    probe, for `qcom,select-utmi-as-pipe-clk`. The word at 0x24 went from
    0x1000 to 0 at the same time.
  - **Reasoned:** the USB GDSC collapsed. `gcc-sm6450` gives it
    `PWRSTS_OFF_ON`, so runtime PM really switches it off, and QSCRATCH
    sits inside it. SC7280, SM6350, SM8650 and others use
    `PWRSTS_RET_ON`, which leaves the GDSC on, for the same reason.
  - **Verified:** round 59's driver unbind and bind brought the host
    back once more. The driver bound at 165.7 s and the gadget was
    configured by 169.9 s, with the ADSP running.
- **Round 62: USB survives the ADSP** — Verified 2026-10-08, 18:32 to
  18:42. Plan z put pkgrel 17 in the rootfs and booted
  `out/milestone/glinkref-r17.dtb`, which is round 57's glink tree plus
  round 60's PHY reference gate, with `out/tools/usbfix-watch.sh`. The
  transcript is `out/try-kernel/live-r62.txt`, and
  `out/try-kernel/bootlog-card-20261008-184143.txt` is the card dump.
  - **Verified:** the ADSP came up at 126.94 s. The link was in Suspend
    by 127.06 s, with the PHY's settings unchanged. UCSI made three role
    reports: device to none at 127.61 s, none to none at 127.64 s, and
    none to device at 127.73 s. The firmware's override was already in
    place at 127.69 s, before the device report: UTMI_CTRL0 0x09, CFG0
    0x01, HS_PHY_CTRL2 0x0e and the reference gate off, as in round 61.
    The UDC read `not attached`.
  - **Verified:** the bring-up re-init ran at 129.26 s, 1.53 s after the
    device report, and logged "gadget reconnected". By 129.37 s the PHY
    read UTMI_CTRL0 0x01, CFG0 0x00, HS_PHY_CTRL2 0x06 and the gate on.
    The link was On at 129.68 s and the gadget configured at 130.34 s.
    It stayed configured, with the ADSP running, until the round ended.
    The live shell came back without a re-probe, and no lease lapsed.
  - **Verified:** `qcom_battmgr` and UCSI worked as in round 57. The USB
    input was online at 5.11 V, detected as SDP, and port 0 was a device
    and a sink with one partner.
  - **Verified:** the USB GDSC change holds. With the link up, the
    watcher unbound the gadget and allowed runtime PM. The controller
    read `suspended` after six seconds, with the gate off. The gadget
    bind resumed it, and the host had it configured within a second.
    GENERAL_CFG read 0x0d afterwards, where round 61 read 0x04, and there
    was no `failed to enable ep0out`. The only complaint was dwc3-qcom's
    usual `HS-PHY not in L2` on the way into suspend.
  - **Verified on the host:** its kernel log, in
    `out/try-kernel/queue-20261008-183229.log`, agrees. It shows a USB
    disconnect at 18:35:26 and the phone enumerated again at 18:35:29,
    which was the ADSP and the re-init. Then a disconnect at 18:35:43
    and the next enumeration at 18:35:50, which was the runtime suspend
    phase. The two are 17 s apart on the host and on the phone.
  - **Reasoned:** the device report comes after the firmware's writes,
    not before. The firmware reports the data role once its BC1.2
    detection knows the port type, and it leaves the PHY non-driving
    when it does. So a re-init on the transition into device, with no
    delay, would likely be enough. One round is a thin margin for that,
    40 ms, so pkgrel 17 keeps the 1.5 s.
- **Round 63: the fold's own tree** — Verified 2026-10-08, 18:50 to
  19:00. Branch `sm6450-fold` in `out/linux` was the series with what
  rounds 58 to 62 passed folded in:
  - the USB GDSC's retention is in the GCC driver commit;
  - the `pmic-glink` binding follows the pd-mapper commit;
  - the role switch, the PHY reference gate and DMA coherence are in the
    SoC tree commit;
  - the board's `pmic-glink` node is in the board commit.

  Its tree, `out/milestone/fold18.dtb`, decompiles to round 62's tree
  plus round 58's coherence. Those two had not booted together, so plan
  za booted it on pkgrel 17 before it became pkgrel 18's series. It ran
  round 58's checks, then round 62's watcher, then the file across the
  gadget again. The transcript is `out/try-kernel/live-r63.txt`, and
  `out/try-kernel/bootlog-card-20261008-190010.txt` is the card dump.
  - **Verified:** round 58's checks pass on it. The panel's connector
    was connected, vblanks came 16.77 ms apart, and the backlight read
    400. UFS showed its three LUNs, `sda` with 97 partitions.
    `edt-ft5x06` bound the touchscreen, and Bluetooth's QCA setup
    completed. The 4 MiB file reached the phone intact, and the first
    256 KiB read back over the shell matched.
  - **Verified:** round 62's watcher gave round 62's results. The ADSP
    was up at 192.82 s. UCSI reported device to none, none to none and
    none to device at 193.50, 193.53 and 193.61 s. The re-init ran at
    195.13 s, 1.52 s after the device report, and the link came back.
    A runtime suspend and resume kept it, with GENERAL_CFG at 0x0d
    afterwards.
  - **Verified:** the file again, after the ADSP, the re-init and the
    runtime suspend. Its hash on the phone and the read-back both
    matched.
  - **Verified:** the battery manager read the USB input online at
    5.11 V and 175 mA, as SDP. Port 0 was a device and a sink.
    `devices_deferred` was empty at the start and at the end. The CDSP
    started by itself and asked for `cdsp.mbn`. No round pushes that
    file, so the request failed with -2 and the CDSP stayed offline.
  - **Verified on the host:** a disconnect at 18:54:24 and the next
    enumeration at 18:54:27, which was the ADSP and the re-init. Then a
    disconnect at 18:54:41 and the next enumeration at 18:54:49, which
    was the runtime suspend. After the round, the boots that cycled
    until the bootloader fell back are the same as round 62's.
- **Round 64: pkgrel 18 on its own tree** — Verified 2026-10-11, 17:08
  to 17:17, the first round after a week's break. Plan 20261011a put
  pkgrel 18 in the rootfs and booted the package's own tree, which is
  byte for byte `fold18.dtb`, with round 63's checks and pkgrel 18's
  modules. The transcript is `out/try-kernel/live-r64.txt`, and
  `out/try-kernel/bootlog-card-20261011-171704.txt` is the card dump.
  - **Verified:** everything round 63 checked. The gadget came up 16 s
    after the flash. The file's hash matched on the phone both times,
    and both read-backs matched. Vblanks came 16769 us apart, the
    touchscreen read "generic ft5x06 (48)", and Bluetooth's QCA setup
    completed.
  - **Verified:** the watcher's two results. The ADSP's role reports
    came at 172.00, 172.02 and 172.09 s, the PHY was initialised again
    at 173.63 s, and the link came back. A runtime suspend and resume
    kept it, with GENERAL_CFG at 0x0d afterwards.
  - **Verified on the host:** a disconnect at 17:11:27 and the next
    enumeration at 17:11:29, then a disconnect at 17:11:44 and the next
    enumeration at 17:11:51, as in round 63.
  - The user touched the screen during this round; see "Touch works".
  - Afterwards, with the phone in recovery, the plan listed `super`'s
    logical partitions read-only. Recovery maps all of slot b's, `vendor_b`
    among them, under `/dev/block/mapper/`, each with a `-cow` device
    beside it. See "The GPU firmware is in `vendor_b`".
- **Round 65: the WLAN comes up** — Verified 2026-10-11, 17:18 to 17:25.
  Plan 20261011b put device pkgrel 4 in the rootfs and booted
  `out/milestone/wifi-r18.dtb`, branch `sm6450-wifi` on pkgrel 18. It
  pushed stock's WPSS image and the ath10k files, loaded the modules,
  and started the WPSS through sysfs. The transcript is
  `out/try-kernel/live-r65.txt`, and
  `out/try-kernel/bootlog-card-20261011-172548.txt` is the card dump.
  - **Verified:** `ath10k_snoc` bound `22800000.wifi` and waited. The
    WPSS booted `wpss.mbn`, 6205624 bytes, and was up at 93.63 s. No
    protection domain was needed. ath10k's QMI client found the firmware
    at 93.72 s: chip_id 0x4320, chip_family 0x4001, board_id 0xff,
    soc_id 0x400f0000. The firmware is WLAN.HL.3.4.3-00488, built
    2025-08-21.
  - **Verified:** ath10k took the board data from the packed
    `board-2.bin`, reported "wcn3990 hw1.0", firmware API 5, and
    registered `wlan0` at 99.4 s. The firmware has no MAC address for
    it, so ath10k chose a random one. `ip link set wlan0 up` succeeded:
    the flags read 0x1003, which is up, and the operstate stayed `down`,
    because nothing associated. Nothing scanned.
  - **Verified:** the initramfs had loaded `edt-ft5x06` by itself, and
    it was bound to `0-0038` before the round's commands ran. That is
    device pkgrel 4 working.
  - **Verified:** no SMMU context fault, and `devices_deferred` was
    empty. The ADSP and CDSP asked for their images when `qcom_q6v5_pas`
    loaded, and failed with -2 because this round pushed neither.
  - **Reasoned:** board_id 0xff is what the firmware reports when the
    OTP holds no board ID. `scripts/ath10k-board2.py` files stock's
    `bdwlan.bin`, the file stock uses in that case, under that ID, so
    the board data was stock's default. Whether stock's own firmware
    picks `bdwlan.bin` on this phone has not been checked.
- **Round 66: the GPU at boot panics** — Verified 2026-10-11, 17:54 to
  18:04. Plan 20261011c put pkgrel 19 in the rootfs and booted
  `out/milestone/gpu-r19.dtb`, branch `sm6450-gpu`, with
  `msm.separate_gpu_kms=1`. The run log is `out/try-kernel/run-r66.log`.
  - **Verified:** our kernel never reached the initramfs. The host saw
    the phone leave fastboot at 17:54:19 and nothing more until stock
    Android answered on slot b, 546 s after the reboot. The card and
    `rddata` held no record of any attempt.
  - **Reasoned:** each of the seven attempts panicked a few seconds into
    the kernel. Stock takes about 33 s from a reset to adb, which leaves
    about 513 s for seven attempts, about 73 s each. With `panic=60`
    that is 13 s of bootloader and kernel before the panic. A soft
    lockup would add 20 s to each, and a hard hang would never have
    fallen back.
  - **Reasoned:** oopses are not fatal on this kernel, so it was an
    SError, or an oops in PID 1, where built-in drivers probe. With the
    graphics clock controller built in, three things ran at boot that
    no round had run before: the clock controller's probe; the GPU
    SMMU's probe, which resets every context bank the hardware reports,
    where stock's node says `qcom,skip-init` and limits Linux to six
    banks and six stream match groups; and the GPU's bind, whose GMU
    init writes the RSCC. Which one it was is not known.
  - Pkgrel 20 makes the clock controller a module again, so the same
    tree boots with all three waiting on it. Round 67 probes them one
    at a time from the shell.
- **Round 67: the GPU SMMU's stream 1 is the abort** — Verified
  2026-10-11, 18:32 to 18:41. Plan 20261011d put pkgrel 20 in the rootfs
  and booted `out/milestone/gpu-r19.dtb` again. The shell turned the
  platform bus's autoprobe off, loaded the clock controller, and probed
  the clock controller, the GPU SMMU and the GPU one at a time through
  `drivers_probe`, each from a child shell. The transcript is
  `out/try-kernel/live-r67.txt`, and
  `out/try-kernel/bootlog-card-20261011-184144.txt` is the card dump.
  - **Verified:** the clock controller probes cleanly. Its clocks were
    all off afterwards, and both GDSCs off.
  - **Verified:** the GPU SMMU reports SMMUv2, stage 1 only, coherent
    table walks, 24 stream match groups and 22 context banks. Its reset
    went through. Then, probing the GPU as its client, it took a
    synchronous external abort, ESR 0x96000010, writing offset 0x804,
    which is SMR 1, with 0x84000001: stream 1, mask 0x400, valid. The
    SMR for stream 0 had just gone in. The child shell died, and the
    CX GDSC was left on.
  - **Verified:** the GPU's probe then blocked in `of_iommu_configure`,
    in D state, behind the dead probe. The command ran out its 240 s,
    and the phone came back on stock's slot b.
  - **Verified from stock's tree:** KGSL maps the GPU's user context at
    stream 0 and its secure context at stream 2, both with mask 0x400,
    and the GMU at stream 5. Nothing maps stream 1. Stock's driver also
    skips the SMMU's global init and limits itself to six context banks
    and six match groups.
  - **Reasoned:** the round 66 panic was this abort, taken in PID 1
    while the built-in clock controller let the SMMU probe at boot.
    Something outside Linux refuses a valid SMR for stream 1, likely
    the hypervisor, since the reset's writes of invalid SMRs to all 24
    groups went through. Why stream 1 is refused is not known.
  - `out/milestone/gpu-r20b.dtb` is `gpu-r19.dtb` with the GPU on stream
    0 alone, a fixup on branch `sm6450-gpu`. Round 69 repeats round 67
    on it.
- **Round 68: FastRPC on the ADSP answers; the CDSP does not come up** —
  Verified 2026-10-11, 18:42 to 18:50. Plan 20261011e booted
  `out/milestone/fastrpc-r20.dtb`, branch `sm6450-fastrpc` on pkgrel 20:
  the package's own tree plus a `fastrpc` node under each DSP's glink edge,
  with stock's context banks. `out/tools/dsp-watch.sh` loaded round 64's
  modules, FastRPC and the remoteproc modules, with stock's ADSP and CDSP
  images in place. Then `scripts/fastrpc-probe.c` made the smallest calls
  on each device. The transcript is `out/try-kernel/live-r68.txt`.
  - **Verified:** the ADSP was up at 130.53 s and FastRPC bound its
    channel 0.01 s later, with `/dev/fastrpc-adsp` and the three compute
    banks in IOMMU groups 6 to 8. The charger domain announced itself
    over PDR. UCSI's role reports and the bring-up re-init brought the
    link back 1.5 s after the device report, as in round 64.
  - **Verified:** the ADSP answers FastRPC. The capability query, a call
    into the DSP's utilities handle, returned, with attribute 6 at
    0xc766 and attribute 10 at 1, and attaching to the root domain
    succeeded. No context fault was logged.
  - **Reasoned:** attribute 6 is the architecture version in the
    userspace FastRPC library's numbering, which would make the ADSP a
    Hexagon v66. The numbering is from memory, not checked against a
    source.
  - **Verified:** the CDSP took its 3.7 MB image, and 5 s later
    `qcom_q6v5_pas` gave up: "start timed out", -110. So there was no
    `/dev/fastrpc-cdsp`.
  - **Verified from stock's tree:** stock's CDSP votes two interconnect
    paths, `rproc_ddr` from the NSP NoC's CDSP master to DDR and
    `crypto_ddr`; our node had none. The NSP NoC's only BCM, CO0, is not
    kept alive by our interconnect driver. The common Q6V5 code already
    makes a proxy vote, from the node's first interconnect path, from
    the start until the handover, and SM8550's CDSP names that path.
  - **Reasoned:** with nothing voting CO0 once the interconnect
    providers synced their state, the CDSP could not reach DDR. Branch
    `sm6450-fastrpc` now names the path, and round 70 repeats round 68
    on `out/milestone/fastrpc-r20b.dtb`.
- **Round 70: both DSPs run and answer FastRPC** — Verified 2026-10-11,
  18:50 to 18:58. Plan 20261011g booted `out/milestone/fastrpc-r20b.dtb`,
  which is round 68's tree with the CDSP's path to DDR named, and ran
  round 68's commands on it. The transcript is
  `out/try-kernel/live-r70.txt`, and
  `out/try-kernel/bootlog-card-20261011-185806.txt` is the card dump.
  - **Verified:** the CDSP was up 0.12 s after `qcom_q6v5_pas` loaded,
    and the ADSP 0.16 s after that. `/dev/fastrpc-cdsp`,
    `/dev/fastrpc-cdsp-secure` and `/dev/fastrpc-adsp` all appeared. The
    CDSP's twelve compute banks went into IOMMU groups 6 to 17, the
    ADSP's three into 18 to 20. No context fault was logged.
  - **Verified:** the CDSP answers FastRPC. The capability query
    returned attributes 1, 3, 4, 5, 6, 9 and 10 as 0x1, 0x2, 0x200000,
    0x1, 0x4a73, 0x1 and 0x3, and attaching to its root domain
    succeeded. The ADSP gave round 68's answers again.
  - **Verified:** the NSP NoC's two CDSP nodes read 0 in the
    interconnect summary both before the start and after it. That fits
    a proxy vote held only until the handover.
  - **Reasoned:** the missing vote was round 68's timeout, since the
    path to DDR is the only change between the two trees. It is not
    known whether the CDSP needs a vote of its own after the handover
    for heavier work. Stock's second path, `crypto_ddr`, is still not
    in our node.
  - **Verified:** the link dropped as the ADSP came up and the bring-up
    re-init brought it back at 98.84 s, 1.5 s after the device report,
    as in round 68.
- **Round 69: the GPU binds on stream 0, and its first resume faults** —
  Verified 2026-10-11, 18:58 to 19:07. Plan 20261011g booted
  `out/milestone/gpu-r20b.dtb`, round 67's tree with the GPU on stream 0
  alone, and ran round 67's steps on it. The transcript is
  `out/try-kernel/live-r69.txt`, and
  `out/try-kernel/bootlog-card-20261011-190738.txt` is the card dump.
  - **Verified:** all three steps survived. The clock controller, the
    GPU SMMU and the GPU probed one after the other, with no abort, and
    drm/msm registered the GPU as minor 1.
  - **Verified:** the first open of the render node loaded `a710_sqe.fw`
    and `gmu_gen70000.bin`, and then `msm-submit` took a kernel fault
    in `a6xx_gmu_resume()`, a level 2 translation fault at address
    0xce. The second `msm-submit` blocked behind it until the command's
    240 s ran out.
  - **Verified from the source:** on A7xx the GMU's resume reads
    `CX_MISC_TCM_RET_CNTL`, register 0x39, through the GPU's `cx_mem`
    mapping. drm/msm 6.18 replaces that mapping with `ERR_PTR(-EINVAL)`
    when the SoC has no LLCC slices for the GPU, and this SoC has no
    LLCC node, in our tree or in stock's. -22 plus 0x39 times 4 is 0xce.
  - **Verified:** the fix has been posted upstream by Alexander
    Koskovich, for Milos, which has no LLCC either: "drm/msm/adreno: set
    cx_misc_mmio regardless of if platform has LLCC", v7 of 2026-05-28,
    with two Reviewed-by tags. Pkgrel 21 carries it as backport-0008,
    renamed back to 6.18's `llc_mmio`.
- **Round 71: the shell came too late for the GPU; the DSPs run again** —
  Verified 2026-10-11, 19:09 to 19:18. Plan 20261011h put pkgrel 21 in the
  rootfs and booted the package's own tree, which now has the WLAN, GPU
  and FastRPC nodes folded in. The transcript is
  `out/try-kernel/live-r71.txt`, and
  `out/try-kernel/bootlog-card-20261011-191842.txt` is the card dump.
  - **Verified:** the GPU never bound, so backport-0008 went untested. At
    15.48 s, long before the shell loaded the clock controller at 97 s,
    the kernel logged "arm-smmu 3da0000.iommu: deferred probe timeout,
    ignoring dependency" and then the SMMU's probe failed with -110. The
    GPU logged the same timeout and "failed to load adreno gpu". Loading
    the clock controller afterwards bound only the clock controller.
  - **Verified from the source:** this is the driver core's deferred-probe
    timeout. `deferred_probe_initcall()` schedules it
    `driver_deferred_probe_timeout` seconds after late_initcall, 10 by
    default, and once it has run, `driver_deferred_probe_check_state()`
    returns -ETIMEDOUT instead of -EPROBE_DEFER. genpd's attach returns
    that when the power domain's provider is missing, which is the
    graphics clock controller's GDSC here, so the failure is final.
    Round 69 got its shell before the timeout, by luck of timing.
  - **What it means for a real boot:** with the clock controller a
    module, the GPU only works if the module loads within about ten
    seconds of late_initcall. drm/msm is built in. So the clock controller
    has to load from the initramfs, or be built in. The device package's
    `modules-initfs.mainline` is the place, as Fairphone 4 does with
    `msm`.
  - **Verified:** the DSPs gave round 70's results on the folded tree:
    both up within 0.25 s, all three FastRPC devices, both capability
    queries and both root attaches. The link dropped and came back at
    190.66 s.
  - Round 72 boots the same kernel with `deferred_probe_timeout=600`, so
    the SMMU keeps waiting for the module, as in round 69.
- **Round 72: the GPU runs jobs; the sensors domain asks for a file we do
  not serve** — Verified 2026-10-11, 19:19 to 19:32. Plan 20261011i booted
  round 71's kernel and tree with `deferred_probe_timeout=600` and
  `msm.separate_gpu_kms=1`, and ran round 71's GPU and DSP steps. Then it
  started Alpine's hexagonrpcd 0.4.0 on the ADSP's sensors domain, serving
  `out/hexagonfs/hexagonfs.tar`. The transcript is
  `out/try-kernel/live-r72.txt`, and
  `out/try-kernel/bootlog-card-20261011-193148.txt` is the card dump.
  - **Verified:** with the timeout raised, the GPU SMMU waited. The shell
    loaded `gpucc-sm6450` at about 97 s, and the SMMU, the GMU and the GPU
    probed within 0.1 s of each other, with no abort. drm/msm registered
    the GPU as minor 1.
  - **Verified:** backport-0008 works. The first open of the render node
    loaded the SQE and GMU firmware, "Loaded GMU firmware v4.0.7", and
    `msm-submit` ran 1 job and then 100. All passed, with no faults and
    exit code 0. The kernel reports chip id 0xffff07010000, 512 KiB of
    GMEM and 600 MHz at most.
  - **Verified:** devfreq offers 295, 345, 500 and 600 MHz, under
    simple_ondemand, and moved between 295 and 600 during the jobs. Both
    GPU GDSCs were off again afterwards.
  - **Verified from the source:** Mesa 26.2, which Alpine edge ships, has no
    freedreno entry for this chip. Mesa main has had one since 2026-09-23,
    4db0b15c34c1 from MR 44466, "freedreno: Add support for Adreno 710 and
    720". Its message says the registers were captured from the Android
    driver's command streams, so it has not been tried on drm/msm.
    `aports/temp/mesa` forks Alpine's 26.2.4-r1 with that entry backported.
    It was not built yet then. It has built since, as 26.2.4-r101, and has
    not run on the phone.
  - **Verified:** the DSPs gave round 70's results again. The CDSP was up at
    193.05 s and the ADSP at 193.22 s. All three FastRPC devices appeared,
    and both capability queries and both root attaches succeeded, with no
    context fault. The link came back at 197.09 s.
  - **Verified:** before hexagonrpcd started, QRTR listed 14 services. Nine
    of them were the ADSP's, node 5, and among those was service 400,
    version 1, the one libssc talks to. Four were the CDSP's, node 10.
  - **Verified:** hexagonrpcd attached to the sensors domain ("Starting
    /hexagonrpcd (INIT_ATTACH_SNS)") and kept running. In 20 s it logged
    1340 errors:
    - ten failed opens of
      `/mnt/vendor/persist/sensors/registry/registry/../sns_reg_version`;
    - ten refused attempts to open that file for writing;
    - then refused writes to `../temp.json` beside it, for the rest of the
      log as far as the transcript shows it.

    hexagonrpcd's tree has no file at that path, and it refuses every
    write. Alpine's build logs only failures, so what the domain read
    successfully is not known. QRTR listed the same 14 services afterwards.
  - **Verified:** stock's persist has that file. It is
    `sensors/registry/sns_reg_version`, beside the registry directory: 10
    bytes, "version=1" and a NUL. `scripts/collect-hexagonfs.sh` now stages
    it. Our own build of hexagonrpcd changes `rpcd_builder.c` to serve it
    next to the registry.
  - **Reasoned:** the domain reads the version file to decide whether its
    registry is current. When the file is missing, it rebuilds the
    registry from the JSON configs and writes temp.json on the way. That
    fits the order of the requests, but it is a reading of the log, not of
    any source.
  - **Verified:** persist was read again after the round.
    `sensors/registry`, `sensors/registry/registry` and 124 of the
    registry's 173 files had a modification time of 19:30, about a minute
    earlier. `sns_reg_version` did not. The registry's contents were
    byte-identical to the copy read before the round. Between the round
    and that read, the phone booted only the recovery the card read uses,
    on the stock slot with Sony's `vendor_boot`.
  - **Reasoned:** something in that recovery boot rewrote the files. Our
    kernel cannot have: no round mounts persist, and hexagonrpcd served a
    read-only copy from the ramdisk.
  - Round 73 runs our hexagonrpcd, built with verbose logging, and serves
    the version file.
- **Round 73: hexagonrpcd serves the sensors domain everything it opens** —
  Verified 2026-10-11, 19:34 to 19:44. Plan 20261011j booted round 72's
  kernel, tree and command line and ran round 72's DSP steps. It left the
  GPU alone. Then it ran our own build of hexagonrpcd 0.4.0, static,
  verbose and patched to serve `sns_reg_version`, on the new
  `hexagonfs.tar`. The transcript is `out/try-kernel/live-r73.txt`.
  - **Verified:** the DSPs came up as in rounds 70 to 72, with both probes
    passing. QRTR listed the same 14 services, service 400 among them.
  - **Verified:** in order, the domain opened:
    - `/vendor/etc/sensors/sns_reg_config`;
    - the six `/sys/devices/soc0` files;
    - `sns_reg_version`, which opened this time;
    - every file in the registry directory;
    - every JSON file in `/vendor/etc/sensors/config`.

    It also called stat on `sensors_registry`, which is in the registry
    directory, without opening it.
  - **Verified:** the error log held nothing but 1320 refused opens of
    `../temp.json` for writing. hexagonrpcd logs a failed read open there
    too, as round 72 showed, so no read open failed. The count was the
    same 20 s later, and hexagonrpcd was still running.
  - **Reasoned:** that is 132 writes at ten tries each. Round 72 also
    showed ten tries per file. The 124 registry files the recovery boot
    rewrote with identical contents are all groups from the JSON configs.
    The 49 it left alone are `sns_reg_config`, `sensors_registry` and the
    runtime calibration (`sns_gyro_cal_persist_s0*`,
    `sns_gyro_cal_table_s0*`, `sns_mag_cal_persist_s0c0*`). So the domain
    seems to rewrite every config-derived group at each boot, and the
    refused writes would only have rewritten what the registry already
    holds. Calibration that changes at run time cannot be saved this way.
    Round 74 suggests that the refusals cost more than this; see there.
  - Round 74 asks for data with libssc's `ssccli`.
- **Round 74: the sensor core answers and publishes no physical sensor** —
  Verified 2026-10-11, 19:44 to 19:55. Plan 20261011k ran round 73's
  steps. Then it ran Alpine's `ssccli` (libssc 0.4.4) from its own
  directory with Alpine's libraries, for 8 to 10 s per sensor. The
  transcript is `out/try-kernel/live-r74.txt`.
  - **Verified:** `ssccli` found the sensor core on QRTR node 5 and got
    client ID 1. Its lookup of the registry sensor succeeded.
  - **Verified:** the lookup of the `accel` data type came back within
    4 ms with "No 'accel' sensor available", and `ssccli` stopped with
    "Unable to initialize accelerometer sensor: UNKNOWN". Proximity,
    light, magnetometer, gyroscope and compass failed the same way. There
    were no measurements. In libssc 0.4.4's `libssc-sensor.c`, that
    message means the core answered the lookup with no sensor UIDs.
  - **Verified:** hexagonrpcd saw no new file access while `ssccli` ran.
    It had 1130 lines and 1320 errors both before and after.
  - **Verified:** stock's registry configures four physical sensors, all
    on the sensor core's own I2C:
    - bmi26x, accelerometer and gyroscope, bus instance 1, address 0x68,
      interrupt on chip pin 66;
    - stk3a5x, proximity and light, instance 2, address 0x46, chip pin 63;
    - mmc56x3x, magnetometer, instance 2, address 0x30;
    - af6133e, magnetometer, instance 2, address 0x0c.

    Their power rails are named `/pmic/client/sensor_vdd` and
    `sensor_vddio`. The configs apply to `hw_platform` QRD and `soc_id`
    537, which is what our soc0 files serve.
  - **Verified:** stock's `remoteproc-adsp@03000000` node declares only
    the cx and mx supplies.
  - **Reasoned:** the SM8450 port in aaronsb/sm-x800-linux PR 37 had to
    declare its two sensor rails always-on, because stock's SLPI node held
    them. Here stock's Linux holds no sensor rail, so the DSP probably
    votes for them itself. This is not certain.
  - **Reasoned:** the refused writes are the main lead. Other ports
    report the same refusals of `temp.json` and `sns_reg_version`, and a
    sensor core that stalls or crashes until those writes succeed:
    - SM8450 in aaronsb/sm-x800-linux PR 37;
    - X1E80100, where the first refusal made the firmware assert, in
      linux-msm/hexagonrpc PR 27;
    - SM8650 and SM7635, in hexagonrpc PR 21 and issue 19.

    Upstream hexagonrpc has no write support yet. PR 21 (stubs) is open
    and its design is still under discussion. PRs 26 and 27 (real writes)
    were closed by their author without review.
  - Round 75 runs upstream main 598b591 with PR 27's five commits, on a
    copy of the registry in the initramfs.
- **Round 75: the sensors domain writes its registry and still publishes no
  physical sensor** — Verified 2026-10-11, 20:03 to 20:13. Plan 20261011l
  ran round 74's steps with hexagonrpcd built from upstream main 598b591
  plus PR 27's five commits, static and verbose. It served a copy of the
  registry under `/hexagonfs/sensors/persist`. The transcript is
  `out/try-kernel/live-r75.txt`.
  - **Verified:** the domain wrote 241 times and renamed `temp.json` over
    a registry group 150 times, 22 of them over `sns_reg_config`. Nothing
    was refused: hexagonrpcd logged 1821 lines and no error, and was still
    running at the end. So was the ADSP.
  - **Verified:** afterwards 172 of the 173 registry files were
    byte-identical to their copies from before the round. Only
    `sns_reg_config` differed. `sns_reg_version` still read `version=1`.
  - **Verified:** `ssccli` still found no accelerometer, proximity, light,
    magnetometer, gyroscope or compass, and took no measurements.
  - **Verified, against round 74's lead:** the refused writes were not
    what kept the sensors away. The domain only rewrote what the registry
    already held.
  - **Reasoned:** `sns_reg_config` records the modification time of each
    JSON config, and ours differ from stock's, so the domain re-parses the
    configs at each boot. That is harmless with writes and costs only time
    without them.
- **Round 76: the sensor core has only four framework sensors** — Verified
  2026-10-11, 20:16 to 20:26. Plan 20261011m ran round 75's steps and
  `scripts/ssc-probe.c` three times: before hexagonrpcd started, once it
  had settled, and a minute later. The transcript is
  `out/try-kernel/live-r76.txt`.
  - **Verified:** before hexagonrpcd, the core published three sensors:
    `async_com_port`, `timer` and `ext_svc`. After it, and a minute later,
    it also published `registry`, four in all.
  - **Verified:** every other data type ssc-probe asked for had no
    sensor. That includes the framework's own `interrupt`,
    `remote_proc_state`, `resampler`, `data_acquisition_engine` and
    `sensor_temperature`, and every physical and virtual type.
  - **Verified:** the drivers are in the firmware. `adsp.mbn` carries the
    log strings of bmi26x, stk3a5x, mmc56x3x and af6133e, of the interrupt
    sensor, the resampler and the remote processor state sensor, and of
    `sns_fw_init.c`, among them "Register Sensor from static list %i".
  - **Reasoned:** so the framework stopped registering sensors partway
    through its static list, rather than the drivers failing to find
    their hardware. A sensor that is not even registered never gets as
    far as probing its hardware, and the resampler has no hardware to
    look for.
- **The ADSP's sensor code reads an SMP2P entry mainline does not create** —
  - **Verified:** in `adsp.mbn` the string `sleepstate` sits between
    `sns_reg_config` and `Remote_proc_state`, next to
    `sns_sig_remote_proc`. `sleepstate_see` sits next to `sns_cm`, the
    client manager. The remote processor state sensor's strings include
    "SMP2P registration failed" and "Wait for SMP2P event failed".
  - **Verified:** stock's tree has a `sleepstate-out` entry, with entry
    name `sleepstate`, on the ADSP's SMP2P edge. Beside it is an inbound
    `sleepstate_see` entry, and a `qcom,smp2p-sleepstate` node that drives
    the first and listens to the second. Downstream's
    `smp2p_sleepstate.c` sets bit 12 of the entry at probe. It clears the
    bit when the system is about to suspend and sets it again on resume.
  - **Verified:** mainline 6.18 has no such entry, binding or driver, and
    our ADSP edge had only `master-kernel` and `slave-kernel`.
  - **Reasoned:** the remote processor state sensor registers for the
    application processor's `sleepstate` entry and waits for it. If that
    wait holds up the static list, every sensor registered after it is
    missing, which is what round 76 saw. This is the hypothesis round 77
    tests. It is not yet shown.
  - Kernel pkgrel 22 adds the entry and the node to `sm6450.dtsi`, with a
    driver of our own, `drivers/soc/qcom/smp2p_sleepstate.c`. It is built
    in, so the bit is set at boot, before the ADSP starts.
- **Round 77: the sleepstate entry brings the remote processor state sensor,
  and nothing more** — Verified 2026-10-11, 20:58 to 21:10. Plan 20261011n
  booted kernel pkgrel 22 and repeated round 76's probes, then ran
  `ssccli`. The transcript is `out/try-kernel/live-r77.txt`.
  - **Verified:** `qcom-smp2p-sleepstate` bound at boot.
  - **Verified:** before hexagonrpcd the core published four sensors,
    `remote_proc_state` now among them. After hexagonrpcd, and a minute
    later, it published five, with `registry`.
  - **Verified:** still no `interrupt`, `resampler`,
    `data_acquisition_engine` or physical sensor. `ssccli` found no
    accelerometer, proximity, light, magnetometer or gyroscope, and took no
    measurements.
  - **Verified:** hexagonrpcd behaved as in rounds 75 and 76: 1821 lines,
    no error, 352 opens, 241 writes and 150 renames. It was never asked for
    a local interface it lacks.
  - **Verified, against round 77's hypothesis:** the missing entry held up
    the remote processor state sensor and nothing else. The entry and its
    driver stay, since stock has them.
- **Stock recovery, with stock's own daemons, publishes the same five
  sensors** — Verified 2026-10-11, 21:12 to 21:25, in stock recovery on
  the vendor kernel 5.10.246, right after round 77. Nothing was written to
  a partition. vendor and vendor_dlkm were mounted read-only without
  journal replay, and so was the modem partition. userdata was hidden
  under a tmpfs, and persist's sensor directory was a RAM copy of
  `out/hexagonfs/persist-sensors`. The script is
  `out/try-kernel/stock-sscrpcd.sh` and its output
  `out/try-kernel/stock-sscrpcd.txt`. strace and logcat are in
  `out/try-kernel/stock-sscrpcd/`.
  - **Verified:** without a daemon, recovery's sensor core publishes the
    four sensors ours does with pkgrel 22: `remote_proc_state`,
    `async_com_port`, `timer` and `ext_svc`. Recovery loads
    `smp2p_sleepstate`.
  - **Verified:** stock's `/vendor/bin/sscrpcd sensorspd` could not attach
    at first. Recovery runs no pd-mapper, so the vendor FastRPC driver never
    learns that `msm/adsp/sensor_pd` is up and refuses the static domain
    with ENOTCONN. sscrpcd retried about 700 times in 90 s.
  - **Verified:** once stock's `/vendor/bin/pd-mapper` ran, the kernel
    logged `msm/adsp/sensor_pd (sensors_pdr_adsprpc) is up for PDR on
    lpass`. sscrpcd attached, and the domain read its configs and rewrote
    the registry, as it does with hexagonrpcd.
  - **Verified:** 45 s later the core published five sensors, the same
    five as round 77: `registry`, `remote_proc_state`, `async_com_port`,
    `timer` and `ext_svc`. No interrupt sensor and no physical sensor.
  - **Verified:** sscrpcd loaded no skeleton library on the application
    side. `libsns_registry_skel.so` was not loaded.
  - **Verified:** recovery runs the ADSP on `adsp2.mdt`, the only ADSP
    image in the modem partition and the one our `adsp.mbn` is squashed
    from.
  - **Verified:** our in-kernel pd-mapper serves the same domains as
    stock's JSON files in the modem partition. Those are the ADSP's root,
    audio, charger and sensor domains on instance 74, with `avs/audio` on
    the audio domain, the CDSP's root domain on 76 and the modem's on 180
    with `gps/gps_service`. Mainline adds `tms/servreg` to every domain, as
    the JSON files list it.
  - **Verified:** the modules a normal boot loads from vendor_dlkm and
    recovery does not cover audio, IPA and rmnet, video, camera, WLAN and
    Sony's battery extension. None is a sensor driver.
  - **Verified:** recovery's ADSP offers no diag service over QRTR, so the
    sensor core's own log is out of reach. That log would include
    `sns_sensor.c:Initialization failed for sensor %x`.
  - **Reasoned:** so hexagonrpcd is not what keeps the physical sensors
    away. Stock's own daemon, on stock's own kernel, gets no further. The
    difference lies in something Android does that recovery and our
    rounds do not. The likeliest is timing. On Android, pd-mapper and
    sscrpcd run within moments of the ADSP booting. In recovery, and in
    every round so far, the daemon attached half a minute or more later.
    Round 78 tests this.
- **Round 78: the sensors work, when hexagonrpcd comes at once** — Verified
  2026-10-11, 21:28 to 21:38. Plan 20261011o staged hexagonrpcd and its
  tree before the DSP bring-up and started it from a detached launcher,
  `out/tools/hrpcd-early.sh`, as soon as `/dev/fastrpc-adsp` appeared.
  Kernel pkgrel 22, same command line as round 77. The transcript is
  `out/try-kernel/live-r78.txt`.
  - **Verified:** the device appeared at 104.95 s and hexagonrpcd started
    at 104.97 s. In round 76 it started 38 s after the ADSP came up.
  - **Verified:** the sensor core published 32 sensors, at once and still a
    minute later. Among them are `interrupt`, `resampler`, `diag_sensor`,
    `accel`, `gyro`, `mag`, `proximity`, `ambient_light`,
    `sensor_temperature` and `motion_detect`, and the virtual ones built on
    them, such as `game_rv`, `rotv`, `gravity`, `tilt` and `pedometer`.
  - **Verified:** hexagonrpcd's traffic was the same as before: 1821 lines,
    no error.
  - **Verified:** `ssccli` read every physical sensor it knows:
    - accelerometer, 245 samples in 15 s, about X 1.05, Y 0.15,
      Z 9.77 m/s², so gravity along the screen's normal;
    - gyroscope, 193 samples in 8 s, all within 0.008 of zero;
    - magnetometer, 79 samples in 8 s, about X −203, Y −245, Z −378 µT;
    - proximity, one event, far;
    - light, one event, 0 lux.
  - **Reasoned:** the phone lay still and face up, which fits the
    accelerometer and the gyroscope. The magnetometer's field is about ten
    times the earth's, which fits the uncalibrated `mag` sensor's hard-iron
    offset; `mag_cal` is published too. Light and proximity have not been
    checked against a hand or a lamp.
  - **Verified:** `ssccli` warns that the firmware's mount matrix is all
    zero and falls back to identity. The registry's `orient` groups already
    map each chip's axes onto the device's, bmi26x for example with x as
    +y, y as −x and z as +z.
  - **Reasoned:** so the samples come out in Android's device frame, and
    whether iio-sensor-proxy needs a mount matrix on top is best seen at
    the phone, by turning it.
  - **Verified, against the timing hypothesis:** it holds. With hexagonrpcd
    there at once, mainline gets what stock Android gets. With it half a
    minute late, neither our kernel nor stock recovery does. How wide the
    window is decides whether OpenRC's service is early enough on a real
    boot. Round 79 measures it.
- **Round 79: hexagonrpcd may come at least 25 s late, and a restart
  recovers** — Verified 2026-10-11, 21:41 to 21:53. Plan 20261011p booted
  the ADSP three times in one round. The bring-up used hexagonrpcd 10 s
  after `/dev/fastrpc-adsp`. Then `out/tools/adsp-cycle.sh` restarted the
  ADSP through its remoteproc's sysfs state twice, once with hexagonrpcd at
  once and once 25 s late. The transcript is `out/try-kernel/live-r79.txt`.
  - **Verified:** all three boots gave the 32 sensors. After the last one,
    `ssccli` read 187 accelerometer samples in 8 s.
  - **Verified:** the restart works on mainline. `stop` took the ADSP
    offline in about 0.1 s, and `start` had it running again within 0.2 s,
    with `/dev/fastrpc-adsp` back. While the ADSP was down, `ucsi_glink`
    logged one failed write. The USB link and the live shell came through
    both restarts.
  - **Verified:** right after a restart, hexagonrpcd's first start, 10 ms
    after the device appeared, failed with "No session available" in the
    kernel log and "Device or resource busy" from hexagonrpcd. The
    launcher's retry 0.5 s later attached.
  - **Reasoned:** so the window is at least 25 s. Rounds 75 to 77 started
    hexagonrpcd 87 s, 38 s and 38 s after the ADSP, but each of them had
    also run `fastrpc-probe`'s attach to the ADSP's root domain first. The
    cause is the longer delay or that attach. Round 80 separates the two.
- **Round 80: the window closes between 25 s and 40 s, and the attach is
  not the cause** — Verified 2026-10-11, 21:53 to 22:07. Plan 20261011q
  booted the ADSP three times again. The bring-up had hexagonrpcd 40 s late
  and no `fastrpc-probe` before it. The first restart ran `fastrpc-probe`'s
  attach to the root domain and hexagonrpcd 2 s later; the second had
  hexagonrpcd 90 s late. The transcript is `out/try-kernel/live-r80.txt`.
  - **Verified:** 40 s late gave the five sensors of rounds 76 and 77, and
    so did 90 s late. The attach and then hexagonrpcd 2 s later gave the
    32 sensors.
  - **Verified:** hexagonrpcd's traffic is the same whether the sensors
    come or not. Each boot of the sensors domain added 1657 lines to its
    log on top of the first boot's 1821, in rounds 79 and 80 alike. So the
    domain asks for the same files in the same order either way.
  - **Reasoned:** so the window is somewhere between 25 s and 40 s after
    the ADSP boots. It is not hexagonrpcd missing a request. Most likely
    the drivers for the physical sensors give up waiting for the registry
    before it arrives, and the core publishes what is left. The firmware
    log that would say so is out of reach, as in recovery.
  - **Reasoned, for a real boot:** OpenRC must start hexagonrpcd within
    about 25 s of the ADSP's boot, and udev boots the ADSP early in
    sysinit, when it loads `qcom_q6v5_pas`. If it is later than that, a
    restart of the ADSP through sysfs re-arms the window, as rounds 79 and
    80 showed, at the cost of a few seconds without the charger's and
    USB-C's link to the ADSP.
- **Round 81: what the image will run works, and the window closes before
  35 s** — Verified 2026-10-11, 22:16 to 22:28. Plan 20261011r ran the
  hexagonrpcd we package, temp/hexagonrpcd 0.4.0-r103, which cannot
  write, on the hexagonfs tree we package and nothing else. First it ran at
  once at the bring-up. Then a restart had it 35 s late. Then device pkgrel
  6's `hexagonrpcd-adsp-fresh` ran with hexagonrpcd right after it, as the
  service's `start_pre` will on a real boot, with the ADSP up for 102 s by
  then. The transcript is `out/try-kernel/live-r81.txt`.
  - **Verified:** at once, the packaged hexagonrpcd gave the 32 sensors,
    and `ssccli` read 187 accelerometer samples in 8 s. So write support
    is not needed. Each boot of the sensors domain does log 1320 failed
    attempts to open `temp.json` beside the registry for writing.
  - **Verified:** 35 s late gave the five sensors. So the window closes
    between 25 s and 35 s.
  - **Verified:** the helper found the ADSP up since 215 s at 317 s and
    restarted it, and the ADSP was ready again at 318 s. hexagonrpcd
    attached on its first try, and the 32 sensors came back, with 188
    accelerometer samples in 8 s. Run again 7 s after the restart, the
    helper left the ADSP alone.
  - **Verified:** the restart cost one failed UCSI write, as in rounds 79
    and 80, and the live shell came through it.
  - **Reasoned:** so device pkgrel 6 should give the sensors on a real
    boot whether OpenRC is early or late. If it is early, the helper does
    nothing. If it is late, the helper restarts the ADSP at the cost of a
    few seconds without its charger and USB-C link. That boot has not
    happened yet.
- **Round 82: the Lomiri image is on the card, and Mesa drives the GPU** —
  Verified 2026-10-11, 23:00 to 23:21. Plan 20261011s put the OpenRC image
  with `postmarketos-ui-lomiri` on the card from the debug shell, then ran
  Mesa 26.2.4-r101 from it through a read-only chroot. drm/msm was in its
  combined mode, without `msm.separate_gpu_kms=1`, so the GPU and the
  display share `card0`, with `renderD128` beside it. The transcript is
  `out/try-kernel/live-r82.txt`.
  - **Verified:** `sdcard-install.sh --keep-table` pushed the 3886 MiB
    image in 759 s, and `dd` wrote it at 5.1 MB/s with `dd_rc=0`. The card
    then read back UUID `e931386d`, `e2fsck -fy` returned 0, and
    `resize2fs` grew the filesystem to 4,194,304 blocks of 4 KiB, the whole
    16 GiB of p1. The log region past 32 GiB was not touched.
  - **Verified:** `eglinfo -B` reports vendor `freedreno`, renderer `FD710`,
    OpenGL 4.6 core and compatibility, and OpenGL ES 3.2, on the GBM,
    surfaceless and device platforms. Wayland and X11 fail, as they should
    with no compositor running, and that is why it exits 2.
  - **Verified:** the GPU loaded `a710_sqe.fw` and GMU firmware 4.0.7 on
    the first open after the test copied them in, ran at 600 MHz, and
    logged no fault, hang or recovery.
  - **Verified:** kmscube set up EGL and GLES on FD710, then stopped at its
    first frame with "user interrupted!". It reads any readable stdin as a
    key press, and `/dev/null` always is. `out/tools/gpu-test.sh` now gives
    it a FIFO that is never written. So no frame has been put on the panel
    by the GPU yet.
  - **Verified, and fixed:** `sdcard-install.sh` exited 143 after
    "done", without its cleanup's last line. `set -e` holds in an EXIT
    trap, and `wait` on the killed hold renewer returns 143. That left
    this round's hold as the round wanted, but a hold the script made
    itself would have stayed until its fifteen-minute lease ran out. The
    renewer's last `sleep 120` also kept `tsh.py`'s pipe open for up to
    two minutes after the script ended.
- **Round 83: the first full boot on our kernel reaches Lomiri** —
  Verified 2026-10-11, 23:21 to 23:27. `FULLBOOT=1`, the same kernel and
  image as round 82, and no `pmos.debug-shell`. The transcript is
  `out/try-kernel/live-r83.txt`, the card's `bootlog-card-20261011-232751.txt`.
  - **Verified:** the initramfs mounted `mmcblk0p1` by its UUID at 6.6 s
    and switched root, and sshd answered the host at about 20 s of uptime.
    `sudo` worked with the image's password.
  - **Verified:** OpenRC started everything in the boot and default
    runlevels: among them `hexagonrpcd-adsp-sensorspd`, `sensorfw`,
    `tinydm`, `elogind`, `dbus`, NetworkManager, bluetooth and sshd.
  - **Verified:** `hexagonrpcd-adsp-fresh` found the ADSP up since 10 s at
    13 s and left it alone, so hexagonrpcd came well inside the window
    rounds 78 to 81 measured. Whether sensorfw then saw the 32 sensors was
    not asked.
  - **Verified:** tinydm logged `user` in and ran `start_lomiri`. Mir 2.28
    took DSI-1 at 1080x2520, 59.99 Hz, 61x141 mm, through its KMS
    platforms, and Lomiri started in its full-greeter mode, with its
    indicators, telephony service and PipeWire. The GPU loaded its
    firmware from the rootfs at 19.0 s, at Mir's first open, and logged no
    fault. Nobody was at the phone, so what the panel showed is not known.
  - **Verified:** USB came through the ADSP's boot: the role went to none
    and back at 11.5 s, and the PHY was brought up again at 13.1 s with
    the gadget reconnected.
  - **Verified:** 7305 MiB of memory, 361 MiB of it in use, 10957 MiB of
    zram swap, and 2.8 GiB used of the 15.7 GiB root.
  - **Verified:** the keep hook ran, but logged only "kept /bin /sbin
    /proc". Its fresh sysfs and devtmpfs mounts failed with EBUSY, so the
    switch took the only `/sys` and `/dev` there were. The card log stops
    at the switch in all seven attempts, and the jobs cannot see the UDC,
    so a hold lapses 90 s after it is made. The hold itself went through
    `/proc/147/root`. The hook now binds `/sys` and `/dev` onto
    themselves instead; see "The loop past switch_root".
  - **Verified, by its timing:** the queue took the phone from the full
    boot to stock Android in 4.5 minutes, seven attempts about 40 s apart.
    Only the ssh kick resets a boot that fast; the log hook's backup is at
    500 s.
  - **Verified:** Bluetooth's WCN3991 asks for `qca/crbtfw32.tlv`, which
    the image does not have. `hfd-service`, Lomiri's haptics, makes binder
    calls for an Android HAL that is not there and fails them, which is
    harmless. The clock reads 1970, as there is no RTC driver yet.
- **Round 84: the loop holds a booted system, and the sensors reach
  iio-sensor-proxy** — Verified 2026-10-11, 23:31 to 23:40. A second full boot with the keep hook's
  binds. The transcript is `out/try-kernel/live-r84.txt`.
  - **Verified:** the hook logged "kept /bin /sbin /proc /sys /dev", and
    from the booted system the jobs' root has `sys/class/udc/a600000.usb`
    and `dev/mmcblk0`. The hold was still there at 175 s, and the USB
    watchdog had logged "configured, holding for 600 s" at 151 s. The card
    dump has seven records past 20 s of uptime, where round 83's stopped at
    the switch.
  - **Verified:** iio-sensor-proxy, started by hand, found the
    accelerometer, the light sensor, the proximity sensor and the compass
    through its libssc backend, and `monitor-sensor` read all four. No
    runlevel starts it: `postmarketos-ui-lomiri` enables sensorfw and not
    iio-sensor-proxy, while Lomiri, which is Qt 5, has only QtSensors'
    `iio-sensor-proxy`, `generic` and `linuxsys` backends, so its rotation
    has nothing to read. sensorfw here is set up for IIO sensors, which
    this phone does not have; its users are repowerd's proximity and light.
  - **Verified, and misread at the time:** at 19 s of uptime the panel
    was still scanning out the framebuffer "allocated by [fbcon]", the
    kernel console's, and Mir's DRM client had spent 1 ms on the GPU.
    This entry first took that as Lomiri not reaching the panel. It was
    only early: Lomiri's QML loads at 21 to 22 s, and Mir sets the CRTC on
    its first frame. Round 86 found Lomiri on the plane at 76 s.
  - **Verified:** `/lib/firmware/qca` does not exist, which is why
    Bluetooth has no patch.
- **Round 85: kmscube on the panel, and two lessons for the loop** —
  Verified 2026-10-11, 23:40 to 23:48. The transcript is
  `out/try-kernel/live-r85.txt`.
  - **Verified:** with tinydm stopped, kmscube from the card drew on the
    command-mode DSI panel at 59.7 fps, both through the legacy page flip
    and with `-A`, atomic.
  - **Verified, and confounded:** its first display reading was at 19 s
    again, so it saw fbcon's buffer, as round 84 did. It then restarted
    tinydm with `rc-service` from the ssh session. The Lomiri that came
    back was outside seat0's session and never became DRM master, so what
    it showed says nothing about a normal boot. tinydm is not restarted
    from ssh any more.
  - **Verified:** one hold renewal failed with "touch:
    /proc/12603/root/pmhold: No such file". `/proc/[0-9]*` sorts by name,
    and a job's short-lived child came before the jobs' own pid 129.
    `ssh.py` now tries one-, two- and three-digit pids first.
- **Round 86: Lomiri is on the panel** — Verified 2026-10-11, 23:51 to
  23:58. The same image, read at 76 s instead of 19 s. The transcript is
  `out/try-kernel/live-r86.txt`.
  - **Verified:** the primary plane scans out fb 63, "allocated by
    QSGRenderThread", which is Lomiri's Qt scene graph. It is 1080x2520
    XR24 with modifier 0, linear, pitch 4352. Read again at 84 s, it had
    moved between fb 62 and 63, so Lomiri was redrawing.
  - **Verified:** Mir is DRM master through the file elogind's
    `TakeDevice` gave it: the same `drm_file` id in `clients`, with master
    set. tty1 is in `KD_GRAPHICS` and `VT_PROCESS`, release signal 35 and
    acquire 36, so the VT is Mir's.
  - **Verified:** the backlight `ae94000.dsi.0` is at 100 of 1023, with
    `bl_power` 0.
  - **Verified:** the greeter logs TypeErrors because the
    `LightDM.IntegratedLightDM` QML module is not installed, and
    `/usr/share/backgrounds/lomiri-default-background.png` is missing.
    Neither stops the shell.
- **Round 87: the loop sees the screen** — Verified 2026-10-11, 23:58 to
  2026-10-12, 00:06. The transcript is `out/try-kernel/live-r87.txt`.
  - **Verified:** `scripts/kms-shot.py` reads the scanout buffer through
    `GETFB2` and a dma-buf, read only, and `ssh.py`'s `@pull` brought three
    PNGs back with matching checksums: `out/try-kernel/shot-r87-45s.png`,
    `shot-r87-45s-half.png` and `shot-r87-100s.png`. This reads memory, not
    registers, and needs no DRM master.
  - **Verified, by looking:** at 45 s and at 100 s Lomiri shows its top
    panel, with the network, sound, battery and clock indicators, over a
    dark background. The panel is a few pixels tall, which is the
    desktop's scale: with no device yaml, lomiri-deviceinfo falls back to
    GridUnit 8. Mir reports the panel as 61x141 mm, about 453 ppi.
- **Rounds 88 and 89: device pkgrel 7** — Verified 2026-10-12, 00:07 to
  00:23. Round 88 put make-rootfs-img.sh's image of 00:03, UUID cf20d29d,
  into the card's p1 (fsck 0, resize 0); round 89 booted it. The
  transcript is `out/try-kernel/live-r89.txt`.
  - **Verified:** Bluetooth comes up. With linux-firmware-qca installed,
    hci0 downloaded `qca/crbtfw32.tlv` at 8.4 s and `qca/crnv32u.bin` at
    11.1 s, and logged "QCA setup on UART is completed" at 11.4 s. The
    kernel reads the `.zst` files, `CONFIG_FW_LOADER_COMPRESS_ZSTD=y`.
    Pairing has not been tried.
  - **Verified:** iio-sensor-proxy starts at boot, from the default
    runlevel, about 2 s before tinydm. `monitor-sensor` found it on the
    bus, but printed nothing after that: its output went into a pipe and
    was still buffered when `timeout` killed it. Which sensors it has at
    boot is for a later round to read off its D-Bus properties.
  - **Verified:** `sony-pdx246.yaml` is in `/etc/lomiri-deviceinfo/devices`
    and Lomiri's environment has `DEVICEINFO_DEVICE_NAME=sony-pdx246`. But
    the scale did not change: Lomiri logged "min=2gu(16px)", 8 px to the
    grid unit, and the screenshots match round 87's. Lomiri, its toolkit
    and qtmir read the grid unit only from `GRID_UNIT_PX`, and in the image
    only the `device-info` tool calls lomiri-deviceinfo's `gridUnit()`.
    lomiri-session's start script exports `GRID_UNIT_PX=$(device-info get
    GridUnit)`; pmOS's `start_lomiri.sh` does not, and scales only the
    PinePhone, with `QT_SCALE_FACTOR=2`. pmaports issue 2411, open since
    2023, reports that a grid unit other than 8 crashed Lomiri then.
  - **Verified:** the wallpaper is missing for a reason that is not ours.
    Lomiri 0.6.2 takes it from AccountsService's
    `com.lomiri.shell.AccountsService` BackgroundFile, then from
    `com.lomiri.Shell`'s `background-picture-uri`, then from
    `/usr/share/backgrounds/lomiri-default-background.png`, which no Alpine
    package ships. postmarketos-ui-lomiri's override sets only GNOME's
    `org.gnome.desktop.background`, which this Lomiri does not read.
  - **Verified:** the greeter's TypeErrors come from Alpine's lomiri
    package, which is built with `0004-Disable-lightdm-integration.patch`,
    so every pmOS Lomiri logs them.
- **Rounds 90 to 92: Lomiri's scale, its wallpaper, and the sensors at
  boot** — Verified 2026-10-12, 00:24 to 00:55, on round 88's image. Each
  test restarted Lomiri with an environment file in
  `/etc/tinydm.d/env-wayland.d`, which tinydm-run-session sources, through
  `out/try-kernel/lomiri-env-try.sh`. The transcripts are
  `out/try-kernel/live-r90.txt` to `live-r92.txt`.
  - **Verified:** killing `lomiri` alone is a fair restart. supervise-daemon,
    started at boot, respawns autologin, and the new Lomiri is on seat0
    and DRM master. Round 91 restarted with no overrides first as the
    control, and it came back as boot's did, "min=2gu(16px)". Restarted
    sessions lack the indicator icons a fresh boot has.
  - **Verified:** `GRID_UNIT_PX=16` scales the shell: "min=2gu(32px)", and
    in the screenshot `out/try-kernel/shot-r91-gu16.png` the top panel is
    about 48 px tall, three grid units, where round 87's was a few pixels.
    It is empty, as restarted sessions' are. `QT_SCALE_FACTOR=3` runs but
    does not scale the shell,
    because the UI toolkit divides the grid unit by the device pixel
    ratio: "min=2gu(5.3px)". `GRID_UNIT_PX=23` (round 90) and 17 (round 92)
    crash Lomiri about 2 s after Mir starts, "Fatal signal received", and
    supervise-daemon gives up after five respawns.
  - **Verified, from a core dump:** round 92 set `core_pattern` and brought
    the first core back, `out/try-kernel/lomiri-core-r92.gz`, and gdb read it
    against the rootfs. The thread is QSGRenderThread, in
    `PlatformScreen::makeCurrent()` in qtmir, from `QOpenGLContext::makeCurrent`
    in Qt Quick's render loop. The function loads `m_outputSurface`, at
    offset 128, and it is null.
  - **Verified, against the sources:** why it is null. qtmir sets Mir's
    output scale to `GRID_UNIT_PX / 8` (`displayconfigurationpolicy.cpp`).
    With Mir 2.20 or later it then pairs each Mir display sink with a screen
    by comparing rectangles, and that pairing is what sets
    `m_outputSurface` (`ScreensModel`, `screensmodel.cpp`). The sink's size
    is Mir's `extents_of()`, `roundf(width / scale)`. The screen's is the
    mode's size divided by the scale and converted to `int`, which
    truncates. When the two differ no sink matches, the screen gets no
    surface, and the first frame dereferences null. On 1080x2520 that is
    every grid unit where 1080 or 2520 over the scale has a fraction of a
    half or more: 17, 19, 22, 23, 25, 27, 28, 29 and 31 between 14 and 32.
    14, 15, 16, 18, 20, 21, 24, 26, 30 and 32 divide cleanly enough. This is the
    Alpine qtmir, 0.7.2_git20260702, built from sunweaver's
    `debian-upstream` branch at `38f16631`; qtmir's `main` still has only
    the Mir 1 path, which compares unscaled sizes. Reasoned: the fix is
    one rounding call, and it is upstream's to take.
  - **Verified:** Lomiri shows the pmOS wallpaper when `com.lomiri.Shell`'s
    `background-picture-uri` names
    `/usr/share/wallpapers/postmarketos/contents/images/2000x2000.png`
    (round 91, `shot-r91-gu16.png`). That file is
    postmarketos-artwork-wallpapers', which postmarketos-ui-lomiri
    already recommends.
  - **Verified:** iio-sensor-proxy needs no help at boot. Polled every 3 s
    from 21 s, it had no sensors at 21 s, the proximity sensor at 27 s, and
    the accelerometer and light sensor at 32 s, without restarting; the
    compass was there when read later. Round 89 had read it too early.
    Five udev "add" events on the FastRPC devices afterwards changed
    nothing. Its `AccelerometerOrientation` stayed "undefined" the whole
    time. iio-sensor-proxy 3.9 polls a sensor only while a client has
    claimed it, and starts one claimed before it appeared as soon as it
    does, so nothing had claimed the accelerometer, Lomiri included.
  - **What went into the packages.** Both fixes needed changes in
    package form, which went into round 93's image:
    our fork of postmarketos-ui-lomiri exports `GRID_UNIT_PX` from
    `device-info get GridUnit` the way lomiri-session does, and sets
    Lomiri's wallpaper keys; and device pkgrel 8's yaml says 24. Of the
    grid units that work, 21 and 24 are the nearest to pmOS's rule of
    ppi * 0.05236, which gives 23, and to Android's density of 450 on this
    panel, a scale of 2.81. 24 is a whole scale of 3, which also suits
    Wayland clients.
- **Rounds 93 and 94: Lomiri at its own scale** — Verified 2026-10-12,
  01:04 to 01:20. Round 93 put make-rootfs-img.sh's image of 01:02, UUID
  facbb8a8, with device pkgrel 8 and postmarketos-ui-lomiri 5-r1, into the
  card's p1 (fsck 0, resize 0); round 94 booted it. The transcript is
  `out/try-kernel/live-r94.txt`.
  - **Verified:** Lomiri came up at 22 s with `GRID_UNIT_PX=24` and
    `QT_WAYLAND_FORCE_DPI=288` in its environment, from start_lomiri and
    `device-info`, with no override file. It was the same process at 46 s
    and at 100 s. The screenshots `out/try-kernel/shot-r94-45s.png` and
    `shot-r94-100s.png` show the pmOS wallpaper and a top panel at phone
    size with the network, sound and battery indicators and a clock that
    moved from 00:00 to 00:01.
  - **Verified, from qtmir's own log:** round 92's explanation holds. With
    `QT_LOGGING_RULES` turning on `qtmir.screens`, a restart at grid unit
    21 logged "Comparing sink physical geom QRect(0,0 411x960) to screen
    physical geom QRect(0,0 411x960)", set the screen's output surface and
    ran, although its scale of 2.625 is not whole. One at 22 logged
    "QRect(0,0 393x916)" against "QRect(0,0 392x916)", set none, and
    crashed. Both of tinydm's logs, the last two sessions, show the same,
    and tinydm then stopped.
  - **Verified:** rotation works in a restarted session and not in the one
    from boot. After the restart at 21, qtmir logged
    "OrientationSensor::readingChanged"; at boot it never did, and
    iio-sensor-proxy's orientation was still "undefined" at 47 s, with all
    four sensors present. Lomiri has QtSensors' `generic`,
    `iio-sensor-proxy` and `linuxsys` backends loaded and no
    `Sensors.conf`.
  - **Verified, against the sources:** why. qtmir starts its
    QOrientationSensor when the compositor starts, 19 s into this boot.
    Qt 5.15's iio-sensor-proxy backend
    (`iiosensorproxyorientationsensor.cpp`) sends `ClaimAccelerometer`
    only if `HasAccelerometer` is already true, and otherwise stops the
    sensor for good. The accelerometer reaches iio-sensor-proxy at about
    32 s. iio-sensor-proxy itself takes a claim for a sensor it does not
    have yet and starts it when it appears, so the fix is to claim anyway,
    in qt5-qtsensors. qtmir would also start the sensor again on repowerd's
    `DisplayPowerStateChange`, so turning the screen off and on again may
    bring rotation in the meantime. Reasoned, not tried.
- **Rounds 95 and 96: the orientation sensor from boot** — Verified
  2026-10-12, 01:25 to 01:41. Round 95 put make-rootfs-img.sh's image of
  01:25, UUID 69f7660e, into the card's p1 (fsck 0, resize 0): round 94's
  rootfs plus our fork of qt5-qtsensors, `temp/qt5-qtsensors`
  5.15.18_git20250330-r100, whose patch 0007 makes the iio-sensor-proxy
  backend claim the accelerometer whether or not iio-sensor-proxy has one
  yet. Round 96 booted it. The transcript is `out/try-kernel/live-r96.txt`.
  - **Verified:** the session from boot now gets readings. qtmir started
    its orientation sensor at 23.6 s, iio-sensor-proxy had the
    accelerometer by 31 s, and at 36.6 s qtmir logged
    "OrientationSensor::readingChanged", which round 94's session from
    boot never did. The reading was "undefined", which qtmir ignores
    ("unknown orientation"), and iio-sensor-proxy's
    `AccelerometerOrientation` read "undefined" to 57 s.
  - **Reasoned:** iio-sensor-proxy reports "undefined" for a phone lying
    flat, which is how it most likely lay. The timing fits a claim: with
    clients waiting, iio-sensor-proxy sends the orientation after the
    sensor's first measurement, as it did here 6 s after the sensor
    appeared, and with none it sends only the sensor's arrival, at once.
    That the shell turns when the phone does is for someone holding it.
  - **Verified, and no use as a control:** iio-sensor-proxy used no CPU
    time over 10 s with Lomiri running, and none after `rc-service tinydm
    stop`; the samples are handled on the ADSP. Lomiri was also still
    running 5 s after that stop.
  - **Verified:** KDE's `kde/5.15` branch of qtsensors and Qt 6's `dev`
    have the same check in `IIOSensorProxyOrientationSensor::start()`, so
    the patch is upstream's to take in Qt 6 first.
- **The stay-up boot: Lomiri left running for someone to hold** —
  Verified 2026-10-12, 06:16 to 06:17. `STAYUP=1 scripts/try-kernel.sh`
  flashed slot a with round 96's command line and an init with neither the
  USB watchdog nor the log hook, so nothing in the boot resets the phone,
  and left it up on the card's image 69f7660e. The transcript is
  `out/try-kernel/live-stayup.txt`.
  - **Verified:** the gadget appeared 16 s after the reboot and sshd
    answered 10 s later. Lomiri was running at 16.9 s of uptime and was the
    same process at 47 s.
  - **Verified, by looking:** at 45 s the panel shows Lomiri's first-run
    tutorial over the shell, "Long swipe from the left edge to open the
    Application Drawer", with the launcher and the top panel:
    `out/try-kernel/shot-stayup.png`. The clock reads 00:0x, because there
    is no RTC driver yet and no network to set the time from.
  - **Verified:** the input devices are `pmic_pwrkey`, `pmic_resin`,
    `gpio-keys` and "generic ft5x06 (48)": the power key, both volume keys
    and the touchscreen.
  - **Verified:** `/sys/power` has `state` and `wake_lock` and no
    `autosleep`, and the battery manager reports the battery Full at 100.
  - **Reasoned:** the phone does not suspend when the screen blanks.
    repowerd's main branch tries libsuspend first, whose backends need an
    `autosleep` file, or a `state` file with no `wake_lock`. Neither is
    there, so it falls back to logind, whose `allow_automatic_suspend` is
    empty; it suspends only on a lid closing or a critical battery.
    repowerd still turns the display off when idle, and whether the panel
    comes back on the power key has not been tried.
- **Lomiri in someone's hands: the keys, and Settings** — Verified
  2026-10-12, 06:18 to 06:40, on the stay-up boot. The owner had Lomiri on
  the phone and reported that the keys did nothing and that Settings would
  not open. The terminal and the browser did open.
  - **Verified:** the keys reach the kernel and Mir. Their interrupts
    counted presses, `pmic_pwrkey` 20 then 22, `pmic_resin` 6 and
    "Volume Down" 16, and Mir's evdev input opened all three devices and
    the touchscreen.
  - **Verified:** in this rootfs only repowerd's own binaries carry
    `com.lomiri.SystemCompositor.PowerButton`. repowerd turns the screen
    off and on when that name signals Press and Release, which on Ubuntu
    Touch lomiri-system-compositor does; it is not installed here, so a
    short press has nothing to act on. Lomiri's own `PhysicalKeysMapper`
    handles only a 2 s press, which opens the power dialog.
  - **Verified:** there is no sound card under this kernel, no
    `/proc/asound`, and PulseAudio's only sink is `auto_null`. The volume
    keys go to ayatana-indicator-sound's volume action, which has nothing
    to change.
  - **Verified:** Settings aborts as it starts, five times in the session
    and once by hand, with "basic_string: construction from null is not
    valid". The core's backtrace ends in `PrintingItem::PrintingItem` in
    `libprinting-plugin.so`, which in lomiri-system-settings 1.4.0 does
    `std::string(g_get_os_info("VARIANT_ID"))`; this rootfs's os-release
    has no `VARIANT_ID`, so GLib returns NULL. Upstream fixed it on
    2026-07-26 in 78b462ae, "Avoid undefined behavior when VARIANT_ID is
    not set", after 1.4.0, and Alpine's 1.4.0-r2 carries no patch for it,
    so every pmOS Lomiri on edge has it. The core is
    `out/try-kernel/lss-core.gz`; `core_pattern` was put back after it.
  - The owner then asked for a steadier UI to iterate on, Phosh or Plasma
    Mobile, which ends the Lomiri work for now.
- **Phosh, from a clean install, in someone's hands** — Verified
  2026-10-12, 06:32 to 06:45: round 97, then a stay-up boot.
  - **The change:** the owner wanted a steadier UI to iterate on, so the
    rootfs is a fresh `pmbootstrap install` with `ui = phosh`,
    `service_manager = openrc` and `extra_packages =
    kmscube,mesa-utils,strace,python3,libssc`, plus grim. Plasma Mobile was
    the other choice; its UI package supports only systemd. On OpenRC,
    postmarketos-ui-phosh 33 starts greetd with the phrog greeter, and its
    on-screen keyboard is stevia.
    - The install pulled newer binaries than our pmaports checkout has:
      postmarketos-base 78, postmarketos-mkinitfs 2.12.0 and boot-deploy
      0.25.0. The initramfs reports version 3.12.5-r0.
    - Our own packages are as before: kernel 6.18.55-r22, mesa
      26.2.4-r101, hexagonrpcd 0.4.0-r103 and device-sony-pdx246 0.1-r8.
      Alpine supplies phosh 0.57.0-r3, phoc 0.57.0-r1 and greetd
      0.10.3-r12.
  - **Verified, round 97:** a debug-shell round wrote the image, filesystem
    UUID 07b8a001, into the card's p1. The card read the UUID back, with
    `fsck_rc=0` and `resize_rc=0`.
  - **Verified, the stay-up boot:** it started at 06:40:41.
    - The gadget came up in the initramfs, and sshd answered about 10 s
      later.
    - At 24 s, phrog's phoc was running under the greetd user, with
      hexagonrpcd's sensors domain and iio-sensor-proxy already started.
    - At about 45 s the owner logged in through phrog: `phoc` and
      `gnome-session --session=phosh` running as `user`.
    - At 240 s, a grim screenshot of that session showed Settings open on
      its Sound page, with stevia up. The page's output device was
      "Dummy Output": there is still no sound card.
  - **Verified, the GPU:**
    - The first loads of `qcom/a710_sqe.fw`, at 2.1 s and 7.6 s, failed
      with -2, because the initramfs carries no GPU firmware.
    - It loaded from the rootfs at 18.9 s, with GMU firmware 4.0.7, before
      phoc started.
    - kms-shot.py can no longer read the screen: phoc's framebuffer has a
      non-linear modifier. Reasoned: that buffer is compressed output from
      the GPU, which means phoc renders with it. grim works when it is given
      the session's `XDG_RUNTIME_DIR`, `/run/user/10000`.
  - **Not explained:** drm/msm logs `dpu_crtc_get_vblank_counter` "no
    encoder found for crtc 0". It appeared at 22 s and then about once a
    minute, at 123 s, 181 s and 240 s. Guess: something asks for a vblank
    count on a CRTC with no encoder attached, for example while the panel
    is off.
  - **Not established:** the owner reported "the pmos debug screen with an
    error message about the gpu" during these runs. Reasoned: the debug
    screen is round 97's debug shell, on screen from 06:35 to 06:40, and
    the GPU message is the failed `a710_sqe.fw` load. But the cmdline names
    no `tty0` console, so where that message would have reached the screen
    is not shown. A photo of the screen would settle it.
  - The phone was left up on slot a, logged in. As with any stay-up boot,
    each further boot of that slot uses one of the bootloader's attempts.
- **The WLAN and Bluetooth in Phosh, and why neither worked** — Verified
  2026-10-12, 06:47 to 07:07. The owner found both dead in Phosh.
  - **Verified, the WLAN:** the WPSS sat offline, and nothing in the
    session started it.
    - SM6450's node falls back to SC7280's WPSS data, which leaves
      `auto_boot` off, because on SC7280 ath11k boots the WPSS itself
      through `qcom,rproc`. ath10k_snoc has no such link.
    - Writing `start` to the WPSS's remoteproc `state` on the running
      phone brought it up in under a second. ath10k registered `wlan0`
      6 s later, and NetworkManager took it as `disconnected`, ready to
      use. That is what round 65 had done by hand.
  - **Verified, Bluetooth:** setup on the UART finished, but `btmgmt
    info` listed no controller, and `bluetoothctl list` was empty.
    - btqca sets `HCI_QUIRK_USE_BDADDR_PROPERTY` when the controller
      reports its NVM's default address. Our tree has no
      `local-bd-address` for the bootloader to fill in, so hci0 stays
      unconfigured, and bluetoothd only sees configured controllers.
    - Running bootmac 0.7.1 on the running phone set an address with
      `btmgmt public-addr`. bluetoothctl then showed the controller,
      named "Sony Xperia 10 VI", powered.
  - **The fixes:**
    - Kernel pkgrel 23 gives `qcom,sm6450-wpss-pas` its own data, the same
      as SC7280's but with `auto_boot` on.
    - Device pkgrel 9 depends on `soc-qcom`, as other mainline Qualcomm
      devices in pmaports do. That brings bootmac, tqftpserv and
      swclock-offset. swclock-offset only reads the RTC and keeps its
      offset in a file.
    - Not `soc-qcom-qbootctl`: it marks the slot good in the UFS GPT.
  - **How it was deployed:** apk installed the packages into the rootfs
    chroot, and the same package set onto the running phone. mkinitfs
    then ran in the chroot, and its `vendor_boot` still names UUID
    07b8a001. So the card was not rewritten.
  - **Verified, the stay-up boot of pkgrel 23 (plan 20261012h):** the
    queue reset the phone back to stock, then flashed and booted it.
    - The WPSS booted on its own at 8.7 s, and `wlan0` existed by 21.7 s.
    - The controller was configured and powered, and tqftpserv was
      started.
    - The phrog greeter was on screen at about 60 s.
    - The transcript is `out/try-kernel/live-stayup-net.txt`.
  - **Not verified:** whether bootmac's WLAN address took. When NetworkManager is
    not connected it gives `wlan0` a random address for scanning. The
    address it had read `addr_assign_type` 3, with a prefix that is not
    bootmac's `02:00`, which fits either case. No log line from bootmac
    reached logread for either interface. For Bluetooth, though, the
    configured controller shows that bootmac ran.
  - **Not explained:** ath10k logs "chan info: invalid frequency 0 (idx
    41 out of bounds)" during NetworkManager's scans. It did not stop
    `wlan0` from coming up.
- **Sound, a stage at a time** — rounds of plans 20261012i to 20261012k,
  2026-10-12, 08:03 to 08:57, each a stay-up boot.
  - **The pieces:**
    - Kernel pkgrel 24 describes the audio. In `sm6450.dtsi`: QUP0's
      I2C0 for the top speaker amplifier, the GPR with q6apm and q6prm, the
      RX, TX and VA macros, both SoundWire controllers and the LPASS LPI
      pins. On the board: the WCD9370 headset codec, the amplifier, and a
      card on the sc8280xp machine driver.
    - The speaker amplifiers sit on an LPASS I2S port. The backend is
      stock's `MI2S-LPAIF_VA-RX-PRIMARY`, our quinary MI2S, on the LPI
      I2S1 pins, and the SoC drives its bit clock. backport-0009, the MI2S
      clock control from linux-next, sets that clock.
    - firmware-sony-pdx246-audioreach-topology is our own AudioReach
      graph, built from an m4 file on the upstream topology macros. Its
      streams: MultiMedia1 is the headphones, MultiMedia2 the speaker and
      MultiMedia3 the microphone.
    - firmware-sony-pdx246's audio subpackage carries stock's amplifier
      settings, `aw88261_acf.bin` and `aw88263_acf.bin`.
    - For these rounds the phone's `/etc/modprobe.d/zz-audio-bringup.conf`
      blacklists the audio modules, so that nothing loads at boot. Each
      round loads them a stage at a time, with a mark in the kernel log
      before each stage. This file is on the phone only, and must go once
      sound works.
  - **Verified, round i (pkgrel 24):** the DSP side and the headset codec
    come up.
    - The GPR registered its two services when `apr` loaded.
    - SoundWire enumerated one WCD9370 device on each controller,
      `sdw:2:0:0217:010a:00:4` and `sdw:3:0:0217:010a:00:3`. The codec
      bound both.
    - The amplifier answered on I2C0 at 0x34, but with chip ID 0x2032:
      "aw88261 0-0034: unsupported device id = 2032". So there was no
      card.
    - q6apm-lpass-dais logged "valid dai id not found:0". 6.18 sizes its
      DAI arrays at 127 entries, and the speaker's port, QUINARY_MI2S_RX,
      is number 127.
  - **The fix for round i:** chip ID 0x2032 is the AW88263, by Awinic's
    own aw882xx driver. Stock carries settings for both parts, so a unit
    may have either.
    - Kernel pkgrel 25 adds a driver for the AW88263 on the aw88395
      library, written from the register layout aw882xx gives that ID, and
      names it on the board.
    - backport-0010 is the port limit check from linux-next, d49ee8faefec.
    - firmware-sony-pdx246 pkgrel 3 adds `aw88263_acf.bin`.
  - **Verified, round j (pkgrel 25):**
    - The AW88263 driver bound 0-0034. Its ACF parsed, with checksums
      matching on both sections, and the driver chose profile 2.
    - The "valid dai id not found" line is gone.
    - The card failed: "Failed to add route ADC1_OUTPUT -> TX SWR_ADC0".
      Those are LPASS v9's tx-macro inputs. SM6450 falls back to SM8450's
      v9.2 data, whose inputs are named "TX SWR_INPUTn". Pkgrel 26 uses
      those names.
    - The amplifier's registers, idle: SYSCTRL 0x3443, so powered down;
      I2SCTRL 0x94e8, which decodes to 48 kHz, 64 fs, 32-bit Philips I2S,
      the driver's default before any stream; and SYSST 0.
  - **Verified, round k (pkgrel 26):** the card registers.
    - `0 [SonyXperia10VI ]: sm6450 - Sony-Xperia-10-VI`, with three PCMs:
      MultiMedia1 and 2 for playback and MultiMedia3 for capture.
    - The headset jack registered as an input device.
    - The LPI I2S1 pins, gpio6 to gpio9, are claimed by `sound`.
    - The amplifier's mixer controls exist. "Top PCM Playback Volume" is
      0 to 360 in quarter decibels from -90 dB, at 280 by default, and
      "Top Profile Set" offers Music and Receiver.
    - The front end refuses S32_LE, because q6apm-dai offers only S16 and
      S24.
    - An S16 tone on MultiMedia2 started. 6.2 s after its mark, the ADSP's
      audio process died: "PDM: service 'audio_process' crash:
      'EF:audio_process:0x2:PM_SERVER:0xbb:memheap.c:1198", an assertion
      on `INTEGRITY_CHECK_ON_FREE_HEADER`, a heap that was overwritten.
      remoteproc restarted the ADSP 5.4 s later.
    - Nobody was listening, so whether the speaker made a sound is not
      known.
  - **Reasoned, the crash:** pkgrel 26 forced the speaker's backend to
    S32_LE, as stock runs that port. The stream from the front end was
    16-bit, and nothing in our topology's speaker graph converts sample
    width. Guess: the 32-bit I2S endpoint ran past buffers sized for 16
    bits. Pkgrel 27 and topology pkgrel 1 keep the speaker path at 16
    bits from end to end, and the bit clock follows at rate times
    channels times 16.
  - **Not fixed: the card does not come back after an ADSP restart.**
    The GPR came back. The WCD9370 logged "IRQ sync failed to resume:
    -16" as the card came down, and on the second bind its component
    probe returned -EBUSY: "failed to instantiate card -16". That ended
    round k's headphone and microphone tests, which ran after the
    speaker. Until it is fixed, a crash on the DSP costs the round.
  - **Seen every round, and harmless so far:**
    - "qcom-apm ... CMD timeout for [1001021] opcode" when q6prm loads,
      5 s after the GPR comes up. 0x01001021 is `APM_CMD_GET_SPF_STATE`,
      q6apm asking whether the DSP's audio framework is ready. Round k's
      card came up after it.
    - "missing qcom,mbhc-buttons-vthreshold-microvolt entry" from the
      WCD9370. The headset buttons have no thresholds yet, and there are
      no verified values for this board.
    - "qcom,dmic-sample-rate dt entry missing" from the VA macro. Our
      tree routes no digital microphone through it yet.
- **The speaker plays, and the handset microphone hears it** — plan
  20261012l, 2026-10-12, a stay-up boot at 09:10 of kernel pkgrel 27 and
  topology pkgrel 1, and a second run on the same boot at about 09:21.
  The transcripts are `out/try-kernel/live-stayup-audio4.txt` and
  `out/try-kernel/live-audio-m.txt`.
  - **Verified, the speaker at 16 bits:** two tones on MultiMedia2 played
    to the end, and the ADSP did not crash.
    - Each time, the amplifier logged "started, SYSST 0x0311": PLL
      locked, clock present, switching and boost on.
    - While a tone played, SYSCTRL read 0x3440, so powered up with I2S
      on. I2SCTRL read 0x9408: 48 kHz, 32 fs, 16-bit Philips I2S, which is
      the bit clock pkgrel 27 sets.
  - **Verified, hands-free:** the second run played a 1 kHz tone on the
    speaker's left channel, 15 dB under stock's profile, and recorded the
    handset microphone, ADC1 on SoundWire input SWR_MIC0. Each recording
    was reduced on the phone to numbers, then deleted.
    - With no tone, the 1 kHz bin read 0.13.
    - With the tone, it read 27.9, against 0.08 at 1370 Hz.
    - With ADC1's analog gain at 10, it read 157.8, against 0.29.
    - So the speaker makes sound, and the handset microphone records it.
      Neither had been shown before.
  - **Verified, the headphone stream:** MultiMedia1 played to the WCD9370
    with nothing plugged in. As it stopped, the codec logged "clk already
    disabled" twice. That is upstream's WCD937x: its RX clock enable stops
    counting at one, and the HPHL and HPHR paths each disable it. It is
    harmless.
  - **Verified, the draft UCM:** with a copy of the UCM tree in `/tmp`,
    `alsaucm` lists the HiFi verb and the Speaker, Headphones, Mic1 and
    Mic2 devices. Enabling Mic1 set the controls it names.
  - **Verified, the second ADC is not heard:** ADC2, on either input,
    showed on none of SWR_MIC0, 1 or 5.
    - SWR_MIC1 and SWR_MIC5 gave the signature of a decimator fed
      nothing: values that fall steadily to 0, identical from one run to
      the next.
    - SWR_MIC0 gave no samples at all, and `arecord` failed with an I/O
      error, so the capture DMA got nothing.
    - With ADC1 and ADC2 on together, as plan l's sweep had them,
      SWR_MIC0 turned to loud broadband noise.
  - **Reasoned, why:** the WCD9370's ADC1 and ADC2 are on different slave
    ports, 1 and 2, and both use channel bit 0. The board's
    `qcom,tx-port-mapping`, `<1 1 2 3>` from qcm6490-idp, puts both on
    master port 1. In 6.18 the bus gives every slave port the parameters
    of the master port it maps to, so both ADCs send in the same slot.
    `qcom,tx-channel-mapping` also maps ADC2 to master channel 2, where
    its slave channel is 1.
    - The channel mapping never reaches the bus. Only the WCD937x's
      `get_channel_map` reads it, and on the TX link no DAI takes the map
      that `qcom_snd_sdw_startup` hands on. linux-next `next-20261009` is
      the same. The qcom master takes each port's channel mask from the
      slave port.
    - The I/O error is DAPM's doing. The sound node routes
      `TX SWR_INPUT0` from `ADC1_OUTPUT` and `TX SWR_INPUT1` from
      `ADC2_OUTPUT`. A decimator on SWR_MIC0 with ADC1 off has no complete
      path, so DAPM leaves it off and the capture DMA gets nothing. ADC1
      on SWR_MIC1 failed the same way. An input with no route, such as
      SWR_MIC4, is an endpoint of its own, so its decimator runs and reads
      an empty channel.
    - Stock's WCD937x node gives ADC2's slave port offset 0 on lane 1, and
      ADC1's offset 1 on lane 0, so in stock they cannot collide.
- **The second ADC on a master port of its own** — plan 20261012n,
  2026-10-12, a stay-up boot at 09:33 of kernel pkgrel 27 on device tree
  variant A, `out/milestone/audio-mapA.dts`. The transcript is
  `out/try-kernel/live-stayup-audio5a.txt`. Variant A maps ADC2's slave port
  to master port 2, with `qcom,tx-port-mapping = <1 2 3 3>`, and gives master
  port 2 the ADCs' sample interval. Port 2 already had offset 0 on lane 1,
  which is what stock gives that slave port. The gains were 10, against
  stock's 12.
  - **Verified, ADC2 is on SWR_MIC4 and ADC1 still works:**
    - ADC1 on SWR_MIC0 read 176.8 at 1 kHz with the tone, against 0.33
      without it.
    - ADC2 on AMIC3 gave real data on SWR_MIC4 and on no other input:
      mean 0.3, 6727 distinct values, acrms 809.
    - With both ADCs on, SWR_MIC0 still read 169.8 at 1 kHz, so the two no
      longer collide.
    - Stock does the same. Sony's stereo and endfire paths put ADC2 on
      `SWRM_TX2_CH1` and read it as SWR_MIC4, and ADC1 on `SWRM_TX1_CH1`,
      read as SWR_MIC0 (Verified: `mixer_paths_parrot_qrd_sku1.xml`, paths
      `sony-handset-mic-audiorec-stereo` and `handset-dmic-endfire`). Stock
      clocks ADC1 and ADC2 at the same 4.8 MHz (Verified: live.dts
      `qcom,tx_swr_ch_map`), which is why port 2 takes port 1's interval.
    - AMIC3 is Sony's second handset microphone, `sony-handset-mic-2nd-mono`
      (Verified: the same file).
  - **Verified, not yet the microphone:** ADC2's data carried no trace of
    the tone. Its 1 kHz bin read 0.22, while ADC1 read 176.8 in the same
    test. ADC2 ran because its own path, AMIC3 to `ADC2_OUTPUT`, is complete
    inside the codec, but the board still routed `ADC2_OUTPUT` to SWR_INPUT1.
  - Variant B was not booted. It only changed `qcom,tx-channel-mapping`,
    which nothing on the TX path reads. The queue was stopped while it was
    waiting for the phone.
- **Both handset microphones heard, and the UCM drives them** — plan
  20261012o, 2026-10-12, a stay-up boot at 09:45 of kernel pkgrel 27 on
  device tree variant C, `out/milestone/audio-mapC.dts`. That is variant A
  with ADC2's output routed to `TX SWR_INPUT4`, which is what kernel pkgrel
  28 now carries. The transcript is `out/try-kernel/live-stayup-audio6.txt`.
  The gains were stock's: ADC 12, decimator 84.
  - **Verified, AMIC3 hears the speaker:** with the tone, its 1 kHz bin read
    193.2, against 0.05 idle.
  - **Verified, AMIC1 still does:** it read 19.7 with the tone, against 0.32
    idle.
  - **Verified, both at once:** a two-channel capture, decimator 0 on
    SWR_MIC0 and decimator 1 on SWR_MIC4, read 20.3 on the first channel and
    193.6 on the second.
  - **Verified, the bias:** DAPM had MIC BIAS3, AMIC3, ADC2 and
    `TX SWR_INPUT4` on while AMIC3 recorded. Those are software states,
    read from debugfs, not from the codec.
  - **Verified, AMIC2 with nothing plugged in:** acrms 4.9, with nothing at
    1 kHz, as an open headset input should read.
  - **Reasoned, AMIC3 is the top microphone:** it hears the top amplifier's
    speaker about 20 dB louder than AMIC1 does. Stock's handset path uses
    AMIC1.
  - **Reasoned, the ADC gain control's scale is wrong:** going from 12 to 20,
    with the speaker 9 dB louder, raised the 1 kHz bin 18.4 dB on AMIC1.
    That leaves about 1.2 dB per step. In the second run on plan l's boot,
    raising it to 10 from its boot value gave about 15 dB.
    The control's TLV, shared by every WCD driver from wcd9335 on, claims
    0.25 dB per step. Nothing in this tree says what the hardware's step
    is.
  - **Verified, the UCM on the phone:** after the round, the UCM tree in
    `/tmp` held the packaged files.
    - `alsaucm` listed Speaker, Headphones, Mic1 "Main Microphone", Mic2
      "Headset Microphone" and Mic3 "Top Microphone".
    - Its boot sequence set ADC1 and ADC2 to 12, and the speaker's level to
      336.
    - Mic1 and Mic3, each enabled through `alsaucm`, recorded the tone at
      65.7 and 783.2. Both ADCs were still at 20 from the round.
    - Enabling and then disabling each microphone left its ADC, its mux and
      decimator 0 off again.
  - The ADSP did not crash in the round or after it, and nothing oopsed.
- **The card at boot, and the greeter's PulseAudio** — plan 20261012p,
  2026-10-12, a stay-up boot at 09:59 of kernel pkgrel 28 and device pkgrel
  11, with the bring-up blacklist gone. The transcript is
  `out/try-kernel/live-stayup-audio7.txt`. The checks after it were run by
  hand on the same boot.
  - **Verified, the card loads on its own:** the Sony card was there 25 s
    after boot. The package's UCM link was in `conf.d/sm6450`.
  - **Verified, nobody was logged in:** the round expected the Phosh
    session, but the phone was at phrog's lock screen. The only PulseAudio
    running was the greeter's, run as `greetd` by phrog's gnome-session. It
    was the only process holding the card, and only by its control device.
  - **Verified, PulseAudio takes the UCM:** the greeter's PulseAudio had
    the HiFi verb, with Speaker and Headphones sinks and a Mic1 source, and
    Speaker and Mic1 as its defaults. With nothing plugged in, the jacks
    marked Headphones and the headset microphone not available.
  - **Verified, sound through PulseAudio both ways:** a 1 kHz tone played
    to its Speaker sink and recorded from its Mic1 source read 12.56 at
    1 kHz, against 0.06 at 1370 Hz. Without the tone it read 0.16.
  - **Verified, the round's own sound check proved nothing:** its `pactl`
    calls as `user` started a PulseAudio for that user, which had only the
    null sink. Its tone went round through the null sink's monitor and
    never reached the speaker.
  - **Two PulseAudios at once:**
    - Verified: a user PulseAudio started by hand beside the greeter's made
      both sinks and the source, and a tone played through it was recorded
      through it, at 3.22 against 0.24.
    - Verified: killing the greeter's made its clients start another at
      once, and after that the user's PulseAudio had only the null sink.
    - Reasoned: the new one's probe of the card ran under the user's open
      stream. In plan p's round the two started together as well.
    - Reasoned: a real login ends the greeter's clients, so nothing would
      start the greeter's PulseAudio again, and it leaves after 20 s idle.
      Plan 20261012q tests that.
  - **Verified, cosmetic:** `wcd937x_codec audio-codec: clk already
    disabled` appears whenever the headphone path powers down.
    `wcd937x_rx_clk_enable` counts no higher than 1, while HPHL, HPHR and
    EAR each call `wcd937x_rx_clk_disable`. That is the upstream driver's,
    not this board's.
  - The ADSP did not crash and nothing oopsed. The accelerometer's iio
    device and iio-sensor-proxy were up.
- **Sound in the logged-in Phosh session** — plan 20261012q, 2026-10-12,
  a stay-up boot at 10:17 of kernel pkgrel 29, the headset buttons'
  thresholds added. The transcript is `out/try-kernel/live-stayup-audio8.txt`.
  The checks after it were run by hand on the same boot.
  - **Verified, the buttons' thresholds are read:** the WCD937x no longer
    logs `missing qcom,mbhc-buttons-vthreshold-microvolt entry`.
  - **Verified, a login through greetd:** `out/try-kernel/push/greet.py`
    logs the test user in over greetd's socket, as typing the password on
    phrog does, with the development password. greetd configures one
    session at a time, and phrog starts one for its user as soon as it is
    up, so the round's first try was refused with "a session is already
    being configured". The second cancels phrog's session first, then
    succeeds: phrog's session ended, and the user's Phosh session started.
  - **Verified, the greeter's PulseAudio leaves:** it was gone 27 s after
    the login. The session's PulseAudio, started with `--start` as the
    session does, then held the card alone, with Speaker and Headphones
    sinks, a Mic1 source, and Speaker and Mic1 as its defaults.
  - **Verified, sound both ways in the session:** a 1 kHz tone played to
    the default sink and recorded from the default source read 12.55 at
    1 kHz, against 0.08 at 1370 Hz. Without the tone it read 0.13.
  - **Verified, beside the greeter's:** before the login, a user
    PulseAudio kept up by hand next to the greeter's made its sinks and
    source on each of four starts, and a tone went through it both ways at
    12.43. The two failures, in plan p's round and in this one's, were
    both PulseAudios that a client started on its own between commands.
    - Guess: a second one, started while the first's card was still
      open, probed the card under it. Nothing in a real session starts
      PulseAudio that way.
  - **Verified, `amixer -c 0 cget` finds no codec control with the UCM
    installed:** `amixer -D hw:0 cget` finds them. The round's helpers
    now use `hw:`.
  - The ADSP did not crash and nothing oopsed. The accelerometer's iio
    device and iio-sensor-proxy were up.
- **The on-screen keyboard and the microphones' level** — by hand on plan
  20261012q's boot, 2026-10-12, after the user found the keyboard gone and
  the microphones silent in the session.
  - **Verified, the keyboard went with the session's environment:**
    greet.py's first version gave the session only `XDG_SESSION_TYPE`.
    Without `XDG_CURRENT_DESKTOP=Phosh:GNOME`, gnome-session skips the
    autostart entries marked `OnlyShowIn=Phosh`, phosh-osk-stevia among
    them, so no keyboard ran to be forced up. greet.py now passes what
    phrog passes, from the session's desktop file: `XDG_SESSION_TYPE`,
    `XDG_CURRENT_DESKTOP`, `XDG_SESSION_DESKTOP` and `GDMSESSION`. After
    the session was restarted (phoc killed, phrog back, a new login), the
    session's gnome-session had all four and phosh-osk-stevia ran. The
    user has not yet confirmed that the keyboard shows.
  - **Verified, an ADC step is worth 1.5 to 1.8 dB:** with the speaker's
    tone recorded straight from the PCM, AMIC1 read 25.1, 52.6 and 130.2
    at ADC1 steps 12, 16 and 20, and AMIC3 read 268 and 1103 at ADC2 steps
    12 and 20. The control claims 0.25 dB a step. The quiet floor rises
    with it, from 26.6 to 86.9 RMS on AMIC1.
  - **Verified, PulseAudio recorded the mono PCM as stereo:** the source's
    sample specification was two channels, and its downmix halves the
    level. Device pkgrel 12 gives each microphone `CaptureChannels 1` and
    its ADC as `CaptureMixerElem`. With it, the source is one channel, its
    base volume (83%, -5 dB) is the ADC's step 0, and the 93% it showed
    was step 12, the boot sequence's value then. Its full volume is step
    20, where the boot sequence now starts both ADCs.
  - The session's source had Mic3 as its active port, not Mic1.
    - Guess: the user picked it in the settings while testing; the
      sound server keeps that choice.
- **Both speakers** — plan 20261012r, 2026-10-12, a stay-up boot at 12:42
  of kernel pkgrel 30 and device pkgrel 13. The transcript is
  `out/try-kernel/live-stayup-audio9.txt`.
  - **Verified, the second amplifier is an AW88263 too:** stock's
    `aw882xx_smartpa@34` on `i2c@988000` (reset GPIO 27,
    `sound-channel = <1>`) is now described on our I2C2, and both
    `0-0034` and `1-0034` bound to the AW88263 driver, which refuses any
    other chip ID. The card formed with a Top and a Bottom volume, both at
    the boot sequence's 336.
  - **Verified, the vendor ACF covers both:** its four entries are profiles
    0 and 10 for device index 0 and again for index 1, matched by
    `awinic,audio-channel`, with no bus or address of their own.
  - **Verified, the bottom speaker plays the right channel:** with the
    ADCs at step 12 and a 1 kHz tone on one channel of the speaker PCM, the
    left channel read 314 in the top microphone (AMIC3) and 35 in the
    bottom one (AMIC1); the right channel read 267 in the bottom one and
    124 in the top one.
  - **Verified, I2C2 runs in FIFO mode:** stock marks the bus `qcom,shared`
    and logs "Multi-EE usecase" for it, driving it through GPI DMA. Pkgrel
    30 describes QUP0's GPI DMA engine (`900000.dma-controller`, the vendor
    tree's channel mask 0x3f and SMMU stream 0x176), which probed, but no
    channel was taken and I2C2's own interrupt fired 1560 times: its FIFO
    is open.
    - Reasoned: whatever else shares the bus is idle here; nothing on
      the boot logged an I2C error.
  - **Verified, the session:** greet.py's login brought up Phosh with
    phosh-osk-stevia, the user's PulseAudio took the card 9 s later and the
    greeter's left 18 s after that. Its source was Mic3, mono, at 100%,
    which is ADC step 20. A tone played to the default sink read 532.7 in
    it. Plan 20261012q's session read 12.55, through Mic1 in stereo at
    step 12 with one speaker, so the two are not one change's measure.
  - The ADSP did not crash and nothing oopsed.
- **The cameras, first light** — plans 20261012s and 20261012t,
  2026-10-12, stay-up boots of kernel pkgrels 31 and 32 with device
  pkgrel 13, then live probes on pkgrel 32. The transcripts are
  `out/try-kernel/live-stayup-cam1.txt`, `live-stayup-cam2.txt` and
  `live-cam3.txt`. No frame left the phone: `push/cap.sh` summarises each
  capture there with `push/rawstat.py` and deletes it.
  - **Verified, the camera PMIC is an ET5907 at 0x35:** pkgrel 31 looked
    for a WL2868C at 0x2f, where nothing answered, while 0x35 read 0x01 in
    its ID register. Pkgrel 32's driver takes either and logged
    "ET5907 at 0x35".
    - Guess: no ET5907 datasheet is public. Its voltage ranges are the
      vendor driver's, and its enable time is a generous guess.
  - **Verified, the CCIs need the SOC AHB clock:** in pkgrel 31 both
    controllers timed out in reset (`CCI reset timeout`, -110). With
    `soc_ahb` among their clocks, pkgrel 32 read HW version 0x10070000
    from both.
  - **Verified, all three sensors probe:** the IMX582 at 3-001a and the
    Hi-846s at 4-0021 (ultra-wide) and 6-0020 (front), both with chip ID
    0x0846. The media graph has each on its own path: the IMX582 on
    csiphy0 with four lanes, the ultra-wide on csiphy1 into CSID 1 and
    TFE 1, the front on csiphy3 into CSID 2 and TFE 2. The CSIDs report
    2.0.3 and the TFEs 2.0.0; the CSI PHY's version register reads 0.
  - **Verified, the IMX582 streams through RDI:** every 4000x3000
    capture of five frames completed, colour bars and scene alike.
  - **Verified, TFE 640 pads every line to 16 bytes:** the colour bars
    came back smeared, 45% of each frame was never written, and every
    frame faulted in the SMMU at 0xe4f000 into its buffer, the first page
    past its 15,000,000 bytes. Matching the frame against itself put the
    real line pitch at 5008 bytes (a score of 1.000) where the driver had
    asked for 5000. Pkgrel 33 aligns lines to 16 bytes on SM6450, as camss
    already does on SC7280 and the newer chips.
  - **Verified, the Hi-846s did not stream on pkgrel 32,** for two bugs in
    the upstream driver.
    - Asked for 1632x1224, the sensor settled on 640x480 and logged "this
      mode is not supported for 4 lanes": set_format checks the current
      mode's lane table before it picks the new mode, and 640x480 has no
      four-lane table.
    - No frame arrived, and stopping warned in `call_s_stream`:
      `hi846_write_reg_16` leaves a positive value in its error, so the
      controls setup returns 1, `hi846_set_stream` stops the sensor, and
      camss takes the 1 for success.
    - Pengyu Luo's v5 series of 2026-07-12 fixes both and adds the 6 and
      8 MP modes. Pkgrel 33 carries its four driver patches and one of
      ours: the series checks the device tree's link frequencies against
      the clock before it has fetched the clock, so the check passes
      against 0 Hz. The board's Hi-846 endpoints now list the series' 90,
      180 and 360 MHz. Pkgrel 36 moved to v6, which fixes that too (see
      "The main camera focuses, at 30 fps").
  - **Verified, libcamera finds the main camera:** `cam -l` on pkgrel 32
    listed it as "Internal back camera", on the simple pipeline and the
    soft ISP, but libcamera 0.7.2 has no sensor properties, gain helper or
    tuning file for the IMX582. `temp/libcamera` pkgrel 104 adds the three.
    - Verified: the black level, 64 at 10 bits, is the pedestal the
      vendor's sensor module data gives, and the dark frames of plan
      20261012u read it.
    - Reasoned: the gain code (1024 / (1024 - code)) and the delays are
      those of the other Sony sensors of its generation; the colour
      matrices are the IMX363's, borrowed as pmaports' imx519.yaml does.
  - Reasoned: the camera clock controller names no CX or MXA domain, and
    its binding, shared with SM4450, has none. Its PLLs locked here, so
    something else holds both rails up.
- **All three cameras stream** — plan 20261012u, 2026-10-12, a stay-up
  boot at 15:01 of kernel pkgrel 33 and device pkgrel 13, then live probes
  as root and as the session's user. The transcripts are
  `out/try-kernel/live-stayup-cam3.txt`, `live-cam4.txt` and
  `live-cam6.txt`. As before, every frame was summarised on the phone and
  deleted there.
  - **Verified, whole frames from the IMX582:** at 4000x3000 the driver now
    asks for 5008 bytes a line, the frame matched itself at that pitch with
    a score of 1.000, and the colour bars read as eight clean bands
    (255, 191, 191, 127.5, 127.5, 63.8, 63.8 and 0 in the high byte). The
    binned 2000x1132 mode does the same at 2512 bytes a line, on the
    412 MHz link.
  - **Verified, the Hi-846s stream:** both the ultra-wide and the front gave
    the same eight bands at 1632x1224 on a 180 MHz link and at 3264x2448 on
    360 MHz, with 2048 and 4080 bytes a line. Pengyu Luo's series dropped
    the driver's link frequency control, so camss estimates the rate from
    the pixel rate and says so.
  - **Verified, the black level is 64 at 10 bits:** with the test pattern
    off, the dark scenes all three cameras saw averaged 16 to 18 in the high
    byte at every Bayer site.
  - **Verified, nothing faulted:** no SMMU fault, no warning and no oops
    through nine raw captures and the libcamera runs.
  - **Verified, libcamera captures from all three as the session's user:**
    `cam` ran the IMX582 at 3992x3000 at 30.1 fps, both Hi-846s at
    3256x2448 at 30.0 fps, and at 1280x720 the IMX582's binned mode at
    120.9 fps and the Hi-846s at 30 fps. The soft ISP debayers on the GPU,
    through Mesa's EGL.
  - **Verified, the same runs fail as root:** root can open the dma-heaps,
    and libcamera prefers the CMA heap, which is the kernel's default
    16 MiB. A 3992x3000 RGBA frame needs 46 MiB, so the allocation fails
    and `cam` reports "Can't allocate buffers". The session's user cannot
    open the heaps, which are root's alone, and libcamera falls back to
    udmabuf, which pmOS's udev rules give the video group.
  - **Verified, PipeWire sees them:** WirePlumber lists the IMX582 and both
    Hi-846s as libcamera devices, and three sources: two "Built-in Back
    Camera" and a "Built-in Front Camera". GNOME Snapshot is installed.
  - Nobody has looked at a picture yet. The image is the user's to judge,
    on the phone, in Snapshot.
  - Reasoned: the Hi-846 helper in `temp/libcamera` pkgrel 105 takes the
    gain code as sixteenths over unity, 0 to 240 for 1x to 16x. That is
    the Hynix convention and fits the driver's range, but no Hi-846
    datasheet has been read.
- **The main camera focuses, at 30 fps** — plans 20261012v, 20261012w
  and 20261012x, 2026-10-12: stay-up boots of kernel pkgrels 34 to 36
  with device pkgrel 13, and live runs of `temp/libcamera` pkgrels 106 to
  109 as the session's user. The transcripts are
  `out/try-kernel/live-stayup-cam4.txt` to `live-stayup-cam6.txt` and
  `live-af1.txt` to `live-af3.txt`. As before, no frame left the
  phone.
  - **Verified, the AK7374 binds as the IMX582's lens:** the vendor's
    module data names the main camera's actuator "ak7374_imx582".
    Pkgrel 34 teaches `ak7375` the AK7374 (a 10-bit position in 0x00 and
    0x01, shifted by six, and no standby mode) and describes it at 0x0f
    on the main camera's CCI bus. It binds 3-000f, its `focus_absolute`
    runs 0 to 1023, and the media graph has an ancillary link from the
    IMX582 at 3-001a to it.
    - Reasoned, the lens moves: with exposure and gain held, a sweep
      from 0 to 1023 lowered the frame's mean from 29.1 to 26.1, and the
      sweep back raised it again. The camera faced the desk, too close
      and too dark to show focus.
  - **Verified, all three sensors report rotation 270,** in V4L2's
    `camera_sensor_rotation` and in libcamera's Rotation, with the
    IMX582 and the Hi-846 at 4-0021 at the back and the one at 6-0020 at
    the front.
    - Reasoned, 270 is right where stock says 90: stock's roll for the
      back cameras follows the opposite convention to the binding's, and
      its front camera reads that sensor turned 180 degrees from ours
      (GRBG against our GBRG). Nobody has looked at a picture yet.
  - **Verified, libcamera moves the lens:** `temp/libcamera` pkgrel 106
    adds lens controls between the simple pipeline and the soft IPA, a
    sharpness measure in the CPU statistics over the middle third of the
    frame each way, and a contrast detection autofocus with AfMode,
    AfTrigger, AfPause and LensPosition. `imx582.yaml` runs it
    continuously, as apps reaching the camera through PipeWire cannot
    start a scan. The kernel's `focus_absolute` followed the IPA through
    0, 204, 31, 613 and 1023, and AfState and LensPosition came back in
    the metadata.
  - **Verified, the first three versions of the autofocus did not
    focus** on that view of the desk in a dim room.
    - Pkgrel 106 scanned while the AGC was still raising the gain, and
      the rising noise read as a peak at the macro end.
    - Pkgrel 107 waits for the brightness to hold still and does not
      scan a scene under 8 out of 255 above the black level. At 120 fps
      it said "Too dark to scan" and left the lens at its default of 0.3
      dioptres. At 30 fps it started five scans while the AGC climbed,
      and dropped each when the brightness moved more than a fifth.
    - Pkgrel 108 also waits for the AGC to stop changing the exposure
      and gain. It then started scans at once, but dropped each of the
      fourteen the log's summary shows, because moving the lens alone
      changed the brightness by a fifth: 18.8 at position 0, 15.3 at
      920. Pkgrel 109 drops a scan when exposure times gain moves by half
      instead.
  - **Verified, pkgrel 109 focuses:** on kernel pkgrel 36 it scanned
    once, as soon as the AGC had settled at 60x gain and 33 ms. In the
    statistics the transcript kept, one in six, the sharpness rose
    towards the macro end (0.038 at position 31, 0.045 at 511, 0.051 at
    948, 0.052 at 1023), and it reported Focused at 1023, 10 dioptres.
    - Reasoned, that is the right answer: the desk under the lens is
      nearer than the closest focus of 10 cm.
  - **Verified, 120 fps had capped the exposure:** libcamera picks the
    IMX582's 2000x1132 mode for a 1280x720 viewfinder, and that mode
    started at 120 fps, so exposures stopped at 8 ms. In the dim room
    the AGC sat at 60x gain and the scene averaged 5 out of 255. Kernel
    pkgrel 35 starts every IMX582 mode at 30 fps, with frame lengths of
    4860 and 5055 lines for the 60 and 120 fps modes, which a shorter
    vertical blanking still reaches. On pkgrel 35 the mode streamed at
    30.2 fps, with vertical blanking 3923 and exposures up to 5007
    lines, and the same scene averaged 17.
  - **Verified, ExposureTime was wrong for every camera:**
    - The soft IPA took its line duration from the sensor information
      the software ISP reads at creation, before any mode is set, so the
      IMX582 reported 12 ms at 117 fps. `temp/libcamera` pkgrel 108
      passes the configured mode's information at configure time, and
      the IMX582 now reports 33,017 us at 30 fps: 5007 lines of 6.594 us.
    - The Hi-846s still reported 133 ms at 30 fps on pkgrel 108. Their
      driver's pixel rate read 72 MHz, the default 640x480 mode's rate,
      which the control's range holds every mode to, while every mode's
      timing needs 288 MHz: lines of 3800, and 2526 of them at 30 fps.
      The driver logged its 1632x1224 link at 180 MHz, which would give
      144 MHz and 15 fps. Kernel pkgrel 36 reports 288 MHz in every mode,
      and the Hi-846s now report 29.6 ms at 30 fps.
  - **Verified, the Hi-846s stream on v6 of Pengyu Luo's series:**
    pkgrel 36 carries v6 of 2026-08-31 in place of v5 and our own patch.
    v6 fetches the clock before it checks link frequencies, as ours did,
    and brings back the LINK_FREQ control, so camss reads the true link
    frequency instead of working it out from the pixel rate. It read
    180 MHz at 1632x1224 and 360 MHz at 3264x2448, and both cameras
    streamed at 30 fps with no fault.
- **The rear flash LED lights** — plans 20261012y and 20261012z,
  2026-10-12: stay-up boots of kernel pkgrels 37 and 38 with device
  pkgrel 13. The transcripts are `out/try-kernel/live-stayup-flash1.txt`
  and `live-stayup-flash2.txt`. The light was measured through the rear
  Hi-846 streaming as the session's user, and no frame left the phone.
  - **Verified, one LED on the PM6150L's first channel:** stock's tree
    (`out/device-dump-root/live.dts`, `qcom,leds@d300`) has the PMIC's
    three-channel flash module at 0xd300 on SPMI USID 5. Both of its
    camera flash nodes, the IMX582's and the rear Hi-846's, use
    `flash_0` and `torch_0`. Mainline's `leds-qcom-flash` counts
    sources from 1, so pkgrel 37 enables `pm6150l_flash` with one LED
    on `led-sources = <1>`, and it binds as `white:flash`.
  - **Verified, the limits:** stock allows that channel 1.5 A of flash
    for 300 ms, 1 A by default, and a torch of 500 mA, 300 mA by
    default. Pkgrel 37 sets 1.2 A, 300 ms and 300 mA, and sysfs reads
    back `max_flash_brightness` 1200000, `max_flash_timeout` 300000 and
    `max_brightness` 255.
    - Reasoned, 1.2 A and not 1.5 A: 1.5 A is a reference-board value,
      the LED's own rating is unknown, and stock's camera stack never
      asked for more than 1.2 A. Nothing on our side sets up stock's
      battery and droop protections either (`qcom,vph-droop-det`,
      `qcom,thermal-derate-en`, `qcom,use-qti-battery-interface`).
  - **Verified, the torch lights:** in round y, `brightness` 26 lit it
    at 33.4 s, and the driver logged "allowed flash current: 30mA".
    The frame's mean sample value, which sits at 1 when every pixel is
    in the darkest fifth, rose to between 1.30 and 1.44. Three seconds
    later the torch went off, and the next statistics were back at 1,
    though the AGC was still raising the gain.
  - **Verified, the flash fires and its timer ends it:** in round y, a
    strobe of 100 mA for 300 ms at 48.4 s, with the camera at 16x,
    raised the mean to 2.94 and 2.91 in the next two sets of
    statistics, 0.13 s apart. The set after that was back at 1. The LED
    then reported `flash-timeout-exceeded`, which is its safety timer
    ending the strobe as designed. The battery was full, and the script
    would not strobe under 30%.
  - **Verified in the source, two driver fixes in pkgrel 37,** both
    meant for upstream:
    - Reasoned, from the flash research: the safety timer runs one
      10 ms step longer than the value written, so 300 ms gave 310 ms.
      `set_flash_timeout()` now writes one step less.
    - Probe's error path and `remove()` released only the first V4L2
      flash device. They now release every one.
  - **Verified, the flash is the IMX582's in V4L2:** pkgrel 38 names
    it in the IMX582's `flash-leds` and builds the V4L2 flash glue,
    which makes the LED driver a module. In round z the flash appeared
    as `/dev/v4l-subdev20`, with `led_mode`, `strobe_source` (software),
    `strobe_timeout` up to 300 ms, `intensity_flash_mode` up to 1.2 A
    in 12.5 mA steps, `intensity_torch_mode` up to 300 mA in 5 mA steps,
    and `faults`. libcamera warned "Unsupported ancillary entity
    function 131074", which is `MEDIA_ENT_F_FLASH`, for the IMX582,
    so the link is there and libcamera does not use it yet. All three
    cameras streamed at 30 fps with no fault.
    - `led_mode` 2 lit the torch at the control's default of 200 mA
      for 3 s, because the round named the intensity control wrongly.
      The mean rose from 1 to between 2.17 and 2.27, against 1.30 to
      1.44 at 30 mA, and fell back to 1 when it went off.
    - Stock gives both rear cameras the same LED. On mainline only one
      sensor's notifier can bind it, so the rear Hi-846 has no flash.
- **What the vendor's camera module data holds** — 2026-10-12, read off
  `vendor_b` and decoded into `out/dl-afcal/`: JSON for each module, and
  the tools that made it. Nothing ran on the phone. The camera work
  this feeds waits for the decode of the tuning files.
  - **Verified, the two IMX582 module bins differ only in their names:**
    every register list and the flash, OIS, actuator and PDAF data are
    the same, and so is the code of the two sensor libraries.
  - **Verified, the IMX582's timing and limits:** five modes on four
    lanes of RAW10, from 8000x6000 at 10 fps to 2000x1132 at 120 fps.
    Analogue gain goes to 64x, held to 16x in the two unbinned modes,
    and digital gain to 4x. Exposure goes up to the frame length less
    48 lines. The lens is 4.71 mm at f/1.8 and focuses from 10 cm to
    10 m.
    - Reasoned: CamX writes exposure, gain and frame length in the same
      request, each with a delay of 2, so libcamera's delays for the
      IMX582 are 2, 2 and 2.
  - **Verified, the Hi-846s:** analogue gain to 16x, digital gain to 8x
    on the rear and 16x on the front, and exposure to the frame length
    less 6 lines. The rear lens is 1.65 mm at f/2.2. The front is
    2.77 mm at f/2.0 with no actuator, and its focus range is given as
    33 to 52 cm. The bins give no delays for either.
  - **Verified, the IMX582's calibration EEPROM:** CamX reads 8 KiB from
    0x50 on the main camera's CCI bus, with 16-bit addresses. It holds
    white balance ratios at 0x1a, a 17x13 lens shading grid at 0x22,
    the autofocus's macro and infinity codes at 0x70c and 0x70e, PDAF
    gain maps, and two blocks that CamX writes straight into the sensor:
    QSC to 0xc500 and SPC to 0x7b10 and 0x7c00. Nothing is checksummed.
    - Reasoned, from the code that reads them: the two focus codes are
      AK7374 DAC values, the units of our `focus_absolute`. CamX widens
      the range between them by 15% past infinity and 30% past macro,
      and scans it in 400 steps. Our autofocus scans the lens's whole
      range, 0 to 1023, in steps of about 100 and then 25.
    - This phone's EEPROM was read in plan 20261012za (see "The
      fingerprint's GPIOs and Qualcomm's TEE, on the phone"). Its bytes
      0x00 to 0x19 may hold a serial number, and stay out of git and
      logs.
  - **Verified, the Hi-846s keep their calibration in the sensor's own
    OTP:** white balance and lens shading, in three groups each, and no
    focus data.
  - **Verified, the OIS is a DW9784 at 0x72,** set up by two short lists
    and given no calibration from the EEPROM. Mainline has no driver for
    it.
  - **A correction to `out/dl-sensors/REPORT.md`:** the IMX582 library's
    writes to 0x38b4 to 0x38bb set the PDAF window. They are not a copy
    of the exposure registers.
- **What the vendor's tuning files hold** — 2026-10-12, the five
  Chromatix files (`com.qti.tuned.*.bin`) from `vendor_b`, decoded into
  `out/dl-tuned/`: every module as JSON, digests under `summary/`, every
  lens shading table as CSV under `lsc/`, and BlackLevel and Ccm blocks
  for libcamera under `libcamera/`. All five files link with no
  dangling pointer, and every claim below was checked against
  `camera.qcom.so` or other references unless it says otherwise.
  Nothing ran on the phone, and none of it is in a tuning file yet.
  - **Verified, the IMX582's two tuning files are one tuning:** 154 of
    156 modules are byte-identical, and the other two weight AWB
    statistics.
  - **Verified, colour matrices in libcamera's order:** row-major,
    RGB to RGB, after white balance, with no offsets, at 2200, 3000,
    4100, 5200 and 6300 K for the IMX582, and 2200, 3000, 3900, 4350,
    5200 and 6300 K for the Hi-846s. The two Hi-846s' matrices differ.
    Stock fades them in dim scenes, to the identity in the IMX582's
    darkest band, which the soft IPA cannot do.
  - **Reasoned, the black level is 64 at 10 bits for all three,** as our
    tuning files already say: two stages always add up to it, however
    they split it.
  - **Verified, the lens shading the soft ISP does not correct:** grids
    of 17x13 per channel. The corners need 3.4 to 4.4 times the
    centre's gain on the IMX582, 2.9 to 3.6 on the rear Hi-846 and 1.35
    to 1.65 on the front, in bright scenes. libcamera 0.7.2 has no lens
    shading correction, so the rear cameras' corners stay that much
    darker.
  - **Verified, how far stock's exposure goes:** 256x total gain on the
    IMX582, 128x on the rear Hi-846 and 64x on the front, and exposures
    up to 66.7 ms on all three. Our soft IPA stops the Hi-846s at 16x
    and 33 ms (see "What the cameras still lack").
  - **Verified, the AWB reference points:** each camera's R/G and B/G
    under its reference illuminants, from which a colour temperature
    curve for each can be built. The soft IPA's AWB is plain grey world.
  - **Verified, stock's output gamma is S-shaped,** darker than sRGB in
    the shadows. Reasoned: it follows tone mappers the soft ISP lacks,
    so copying it alone would not give stock's look.
- **The fingerprint reader, read off the firmware** — 2026-10-12.
  Nothing ran on the phone. The sources are `vendor_b` and `modem_b`
  from `out/firmware/`, the live tree, Sony's published kernel source
  for this phone, and the notes under `out/dl-fp/`: `notes-re/` on the
  vendor's libraries and trusted app, `notes-qtee/NOTES.md` on
  Qualcomm's TEE under mainline, and `notes-kdriver/NOTES.md` on Sony's
  driver.
  - **Verified, an Egis EC617, run from TrustZone:** Sony's kernel
    source for the 10 VI (kernel-copyleft, branch `70.2.A.1.xxx`) builds
    `drivers/input/fingerprint/et617/` for it, and the vendor's trusted
    app, `egisap64`, carries the EC617's tables and self-test. The app
    drives the sensor's SPI bus itself, at 9.6 MHz, so the live tree
    gives Linux only GPIOs: VDD on 96, VCC on 106 (3.0 V), reset on 108
    and the finger interrupt on 111.
  - **Verified, Sony's driver does power, reset and the interrupt and
    nothing more:** `etxxx_fp.c` is a platform driver for "fp-egistec"
    behind `/dev/esfp0`, with raw ioctl numbers and `poll()` for the
    finger. It raises VDD and VCC together, waits 3 ms, releases reset
    and waits 3 ms more. A reset pulse is 10 ms low, then 3 ms. Its SPI
    ioctls do nothing.
  - **Verified, how Android reaches the app:** the vendor's HAL loads
    `egisap64` from `modem_b` through the legacy QSEECom interface, and
    wraps every Egis message in command 0xE0. That command's buffer
    holds a pointer at offset 8, which TrustZone has to fix up, as
    QSEECom's "modified command" does. The app encrypts its own
    templates and stores them through the secure file system listener
    and through file callbacks in the HAL. It needs an RPMB listener as
    well.
  - **Verified, mainline's `qcom_qseecom` cannot carry it:** it cannot
    load an app, cannot fix up an embedded pointer, and serves no
    listeners.
  - **Reasoned, mainline's `qcomtee` may:**
    - Verified: stock reports QSEE 0x1402000 (QTEE 5.2.0) with its SHM
      bridge enabled (`out/device-dump-root/`), and our boot logs (for
      example `log-r97.txt`) list the `qcomtee` device, which
      `qcom_scm` creates only when TrustZone answers its probe.
    - Reasoned: only a QSEECom compatibility loader (UID 122) can fix
      up the pointer through `qcomtee`. Whether this QTEE lets a Linux
      client open it was the open question; plan 20261012za found that
      it does (see the next entry). The fallback is an out-of-tree
      QSEECom TEE driver that others have used with a fingerprint app of
      this kind.
  - **Rules for everything that follows:**
    - Load only `egisap64`. `fingerpr`, Qualcomm's ultrasonic app, is
      unused here and declares the same app name.
    - Use the gated read-only protocol checks described above before any
      sensor commands. Never insert an unregistered userspace pointer into
      the TA request.
    - Never provision or erase RPMB, and write nothing to it without
      the owner's word: its counters are shared with Android.
    - Leave the fingerprint's SPI engine and its pins to TrustZone.
- **The fingerprint's GPIOs and Qualcomm's TEE, on the phone** — plan
  20261012za, kernel pkgrel 39 with quic-teec 1.0.2 and libgpiod 2.3.1,
  2026-10-12. One stay-up boot; `cmds-stayup-fp1.sh` and
  `live-stayup-fp1.txt` under `out/try-kernel/` have the commands and
  what they printed.
  - **Verified, pkgrel 39 changes nothing else:** it builds `qcomtee` as
    a module, which moves TrustZone's memory onto the SHM bridge. With
    `modprobe.blacklist=qcomtee` holding the module back, the ADSP, CDSP
    and WPSS ran, Wi-Fi and Bluetooth came up, and the sound card,
    FastRPC nodes and three cameras were there. The modem stayed
    offline, as it was before. No SMMU fault, warning or oops.
  - **Verified, TrustZone answers `qcomtee`:** `modprobe qcomtee` made
    `/dev/tee0`. quic-teec's test client queried the diagnostics service
    (UID 143), which reported a 782208-byte heap with 613824 bytes free.
    Then it opened and released UIDs 143, 122, 3 and 87: the QSEECom
    compatibility loader, the app loader and the listener registration
    are all within a Linux client's reach. Nothing was loaded and no
    command was sent.
    - The driver logged "QTEE version 0.0.0". Guess: this QTEE does not
      answer the driver's version query, since stock reports 5.2.0.
  - **Verified, the sensor's GPIOs:** lines 96, 106, 108 and 111 on the
    TLMM (`gpiochip3`) were unclaimed inputs. Power and reset read low,
    and the interrupt read 0 even with its pull-up. With VDD and VCC
    raised, then reset 10 ms later, the interrupt read 1 and gave no
    edge in 5 s. Power went off in the order Sony's driver uses.
    - Reasoned: an unpowered sensor holds its interrupt pin low, and an
      idle one lets it go high. Only TrustZone can tell whether it
      answers.
  - **Verified, this phone's IMX582 EEPROM:** read through `at24` as a
    24c64 at 0x50 on `i2c-3` while the camera streamed 600 frames, from
    0x1a to the end, with nothing written. `imx582_eeprom_decode.py`
    under `out/dl-afcal/tools/` decodes it.
    - The lens focuses at infinity at AK7374 code 136 and at macro at
      698. CamX's margins make its scan range 52 to 866.
    - The white balance ratios at D50 are R/G 0.6143 and B/G 0.5313,
      the same as the golden module's in the tuning file. Reasoned: this
      unit's colour needs no correction for its module.
    - The lens shading grid's red corner is 218/1023 of the centre,
      about 4.7 times the gain.
    - The dump stays in the scratch directory, out of git, and bytes
      0x00 to 0x19 were neither printed nor kept.
- **egisap64 loads over `qcomtee` from a Linux client** — our own
  `egisfp-tee` package (binary `egisfp-load`), kernel pkgrel 39,
  2026-10-12. `out/try-kernel/run-fp-smoke.log` and `run-fp-diag.log`
  have the transcripts. This is the first time this phone's own
  fingerprint trusted app has run under mainline Linux.
  - **Verified, the image assembles:** the client reads
    `egisap64.b00`–`.b08` from `out/firmware/modem_b/image`, parses the
    ELF64 program headers in `.b00`, and lays each `.bNN` at its
    `p_offset` — the same split-MBN assembly Qualcomm's
    `__qseecom_start_app` does — producing a 2519128-byte image.
  - **Verified, QTEE loads it:** the client opens the root object,
    registers a client with a credentials object, opens `IClientEnv`
    UID 122 (the QSEEComCompat app loader), and calls `loadFromBuffer`
    (op 1) with the image and the name "egisap64". It returns
    `QCOMTEE_OK` and `distName` "fingerprint". So QTEE accepts Sony's
    OEM-only v7 chain from a plain HLOS client, and route (b) — the UID
    122 compat loader — is real on this phone, resolving the research's
    main open question. The client then unloads (op 2) cleanly, freeing
    the single-residency "fingerprint" app name for the next run.
  - **Verified, invocation round-trips:** `sendRequest` (op 0,
    `ObjectCounts(4,2,4,0)`: `reqIn`, `rspIn`, an empty
    `embeddedBufOffsets`, `is64`=1; `reqOut`, `rspOut`; four null memory
    objects) returned `QCOMTEE_OK` for top commands 0x00 and 0x01. No
    listener, no RPMB and no shared-memory object were needed for this.
  - **Corrected 2026-10-13:** the unchanged 0xAA buffers were only 64
    bytes. TA disassembly and execution in Unicorn prove they were rejected
    before dispatch; command 0x01 does write operand*10 at response offset
    0 with sufficiently sized buffers. See the framing review above.
  - **Corrected, ETS layout:** metadata and input are inline; the pointer
    at offset 8 is optional shared output storage. Pointer-free framing and
    absent-output error checks need no fix-up. A real version response
    requires registered memory through UID 122, now implemented behind
    those checks. Whether enrollment needs RPMB listeners remains to be
    demonstrated by the actual TA path; qseecomd's general startup rule
    alone does not prove that requirement for this operation.
  - No TA blob is committed: `egisfp-tee` ships only the binary, and the
    `.bNN` segments were pushed to `/tmp` on the phone for the test.
- **boot-deploy's v4 path builds the images the way this port needs** —
  Verified. boot-deploy 0.24.0 `generate_bootimg()`: for `header_version` 3 or
  4 it calls `mkbootimg --header_version 4 --dtb "$_dtb" --kernel ...
  --vendor_ramdisk ... --vendor_cmdline "$(get_cmdline)" --vendor_boot
  "$_vendor_bootimg" -o "$_bootimg"`. So the DTB really goes into
  `vendor_boot.img`, and `android-tools` really is the right provider — that
  branch hardcodes `require_package "mkbootimg" "android-tools"`.
- **Both boot images are actually produced, and are internally correct** —
  Verified. `verify-bootimg.py` on the real files: `boot.img` 30,502,912 bytes,
  `ANDROID!`, header v4, `kernel_size` 30,497,280 (exactly our `vmlinuz`),
  `ramdisk_size` 0 as v4 requires. `vendor_boot.img` 13,008,896 bytes,
  `VNDRBOOT`, header v4, `page_size` 4096, `vendor_ramdisk_size` 12,689,309,
  `dtb_size` 308,591, and that DTB byte-identical to the kernel apk's
  `parrot.dtb`.
- **Load addresses match the board, not mkbootimg's defaults** — Verified.
  `device/sony/columbia/PlatformConfig.mk` has
  `BOARD_KERNEL_BASE := 0x00000000`; mkbootimg defaults to `0x10000000` and
  boot-deploy's v4 branch passes no offsets, so the first build was 0x10000000
  high on all four. With `deviceinfo_bootimg_custom_args="--base 0x00000000"`
  the header now reads `kernel_addr 0x00008000`, `ramdisk_addr 0x01000000`,
  `tags_addr 0x00000100`, `dtb_addr 0x01f00000`. Header v3+ keeps these in
  `vendor_boot`, and AOSP documents the bootloader as reading them from there.
- **`deviceinfo_kernel_cmdline` and `kernel-cmdline.d` are alternatives, not
  merged** — Verified. `get_cmdline()` is
  `if [ -n "$deviceinfo_kernel_cmdline" ]; then _ret="$deviceinfo_kernel_cmdline ..."; else _ret="$(generate-kernel-cmdline)"; fi`.
  Setting the deviceinfo variable discards every drop-in, so this device keeps
  its whole cmdline in `kernel-cmdline.conf`.
- **The cmdline drop-in reaches the image** — Verified. Read back out of
  `vendor_boot.img`: `quiet splash plymouth.ignore-serial-consoles
  plymouth.prefer-fbcon console=ttyMSM0,115200n8 earlycon loglevel=7
  printk.devkmsg=on pmos.debug-shell`. Our `50-` options are all present and
  after `00-base.conf`'s `quiet`, so `loglevel=7` is the one that applies.
- **Boot images fit their partitions** — Verified.
  `BOARD_BOOTIMAGE_PARTITION_SIZE` and
  `BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE` are both `0x06000000` (96 MiB); ours
  are 30.5 MiB and 13.0 MiB.
- **The fastboot images come from the rootfs chroot's `/boot`** — Verified.
  `flash_kernel` is `$BOOT/boot.img` and `flash_vendorboot` is
  `$BOOT/vendor_boot.img`, where `$BOOT` is that chroot.
  `home/pmos/rootfs/sony-pdx246-boot.img` is a boot *partition* filesystem, a
  different thing.
- **`--split` is the wrong invocation for this device** — Verified.
  pmbootstrap's `flashers` dict: the plain `fastboot` flasher's `flash_rootfs`
  is `fastboot flash $PARTITION_ROOTFS $IMAGE`, the *combined* image. Only
  `fastboot-bootpart` sets `"split": True` and uses the split images.

- **Our device tree carries the ids the bootloader matches on** — Verified
  against Sony's own. `scripts/dtb-ids.py` reads `qcom,msm-id`,
  `qcom,board-id` and `qcom,pmic-id`, which is what a Qualcomm bootloader
  selects a base tree by. Stock `vendor_boot` concatenates fourteen trees;
  number eight is "Qualcomm Technologies, Inc. Parrot SoC" with
  `msm-id = <0x219 0x10000 0x265 0x10000>` and `board-id = <0x0 0x0>`, and ours
  carries exactly those, model string included. `board-id = <0x0 0x0>` is not a
  defect: every stock base tree uses it, because the board identity arrives
  later from the `dtbo` overlay, which is what rewrites the root to
  `board-id = <0x1000b 0x00>` and a merged seven-SoC `msm-id` in the live tree.
  This is the downstream kernel's tree, which keeps the stock dtbo and so is
  selected by the scoring matcher, where a zero field is a wildcard. The
  mainline kernel is routed through the strict matcher instead and needs
  different values; "How the bootloader chooses" above has both.
- **Sony's second Parrot base is not the one this unit wants** — Reasoned, and
  resolved. Tree six is "Parrot 4Gb SoC", same `msm-id` but
  `board-id = <0x0 0x600>`, and the open question was whether this unit is the
  variant that wants the `0x600` subtype, which our `vendor_boot` has no tree
  for. Those bits are the DDR type, and the overlay stock Android actually
  booted says it is 0 rather than 6 - see "The board's DDR type is 0" above. The
  `<0x0 0x0>` tree we carry is the right one of the two.
- **Our `parrot.dtb` is a strict subset of Sony's** — Verified. 2201 nodes
  against 2562: 361 nodes under `/soc` are missing and nothing is extra, which
  is the expected shape given the build compiles only the base tree without the
  `sm6450-modules` includes. What is absent is camera (`qcom,cam-*`,
  `qcom,tfe*`, `qcom,csiphy*`, `qcom,cci*`), display (`qcom,mdss_mdp@ae00000`,
  `qcom,mdss_dsi_ctrl0@ae94000`, `qcom,mdss_dsi_phy0@ae94900`,
  `qcom,sde_rscc@af20000`, both SDE SMMU contexts and `qcom,dp_display`), the
  whole ASoC machine (every `qcom,msm-dai-*` and `qcom,msm-pcm-*`,
  `qcom,msm-adsp-loader`, `spf_core_platform`), video (`qcom,vidc@aa00000`) and
  108 pin configuration children of `/soc/pinctrl@f000000`. None of it is
  needed for a serial or USB console, but the display nodes are why a black
  screen says nothing about whether the kernel ran.

## The rootfs image

- **The rootfs image is built, and the UUID chain is intact** — Verified.
  `pmb install` cannot finish here, so `scripts/make-rootfs-img.sh` builds it
  with `mkfs.ext4 -d`, which populates a filesystem from a directory tree
  without mounting it. Result: 1,020,264,448 bytes, bare ext4 (magic `0xef53`,
  no partition table), labelled `pmOS_root`, 249,088 blocks × 4,096 = exactly
  the file size, `e2fsck -fn` clean, `/sbin/init`, `/etc/fstab`,
  `/etc/apk/keys` and `/usr/lib/modules` all present, no pmbootstrap leftovers
  and `/dev` empty. `verify-bootimg.py` checks that the `pmos_root_uuid=` in
  the vendor_boot cmdline equals the filesystem's own UUID — the one thing that
  silently breaks if `/etc/fstab` is written after `mkinitfs` instead of
  before.
- **The image's login password is known** — Verified. `pmb install` sets it
  interactively, so an image built any other way inherits whatever an earlier
  run left in `/etc/shadow`. `make-rootfs-img.sh` sets it from
  `PMOS_PASSWORD`, default `147147`, and the hash read back out of the finished
  image verifies against that. `root` is `!` (locked), which is pmOS's normal
  arrangement.
- **The rootfs can be rebuilt without reflashing boot** — Verified.
  `make-rootfs-img.sh` used to mint a fresh filesystem UUID on every run,
  which forces `boot.img` and `vendor_boot.img` to be rebuilt and reflashed,
  because the command line is where the initramfs learns which filesystem to
  mount. It now honours `PMOS_ROOT_UUID`, so the image can be pinned to the
  UUID already on the flashed command line:

      PMOS_ROOT_UUID=$(strings -a .pmb/work/chroot_rootfs_sony-pdx246/boot/vendor_boot.img \
              | grep -o 'pmos_root_uuid=[0-9a-f-]*' | head -1 | cut -d= -f2)

  The current image was rebuilt that way, against
  `1e3e6bd0-9170-4c79-a34b-64ece0ad2ca6`, and `dumpe2fs` reads that UUID back
  out of it. Once the rootfs lives on an SD card this makes the whole rootfs
  half of the loop a card rewrite with no fastboot in it.
- **`make-rootfs-img.sh` needs the chroot unmounted first** — Verified. Its
  own first check refuses to run while anything is mounted under the chroot,
  because those mounts would be copied into the image, and `pmb chroot` leaves
  its bind mounts in place until shutdown. Run
  `distrobox enter pmport -- ./scripts/pmb -q shutdown` before it. The script
  then calls `shutdown` itself a second time, after `mkinitfs`, for the same
  reason.
- **The card is written from the debug shell, over the cable** — Verified
  2026-10-05; see "The card, after the write". `scripts/sdcard-install.sh`
  has `nc` on the phone listen on the USB address and pipe straight into
  `dd`, and pushes the image to it from the host, staging nothing, since the
  image is larger than the phone's RAM. It started as an HTTP pull with
  busybox `wget`, and its header comment still says so. The write runs under
  `setsid` with its output in a file and is polled over short telnet
  connections, because `scripts/telnet.py` stops reading two seconds after
  its piped input ends and a dropped session would otherwise take `dd` with
  it. It refuses any target that is not `/dev/mmcblkN`, refuses a card
  smaller than the image, and does nothing at all without `--yes`.
  `--keep-table` is in "The loop past switch_root".

## The initramfs and the debug shell

- **The initramfs carries everything the debug shell needs** — Verified. 478
  entries; all 89 `modules-initfs` names present as `.ko`; `usr/bin/busybox`,
  `usr/bin/busybox-extras` (which is where the `telnetd` applet lives),
  `usr/bin/unudhcpd`, `init` and `init_functions.sh` all in. `init` runs
  `busybox --install -s` and `busybox-extras --install -s`, which is what makes
  the bare `telnetd` call in `init_functions.sh` resolve.
- **`initramfs.load` is `modules-initfs`, order intact** — Verified. The file
  installed at `usr/lib/modules/initramfs.load` is ours verbatim; the 89 module
  names match exactly, in stock's dependency order.
- **`pmos.debug-shell` gives telnet on `172.16.42.1:23` and a CDC-ACM port** —
  Verified. `postmarketos-initramfs/init_functions.sh`:
  `telnetd -b "${HOST_IP}:23"`, `acm.usb0`, `ncm.usb0` with `rndis.usb0`
  fallback.
- **RAM boot is impossible on this device** — Verified 2026-10-05, both ways.
  Sony's bootloader (`6450-0001_X_Boot_SM6450_LA2.0_U_19`) answers `not
  supported` to `fastboot boot`, and fastbootd answers `Unrecognized command
  boot` because userspace fastboot does not implement it. The image uploads
  fine in both, 29788 KB OKAY; it is only the boot command that is refused,
  and staging `vendor_boot` first changes nothing. `scripts/flash.sh
  flash-boot` is what replaces it.
- **The debug shell works without a rootfs** — Verified 2026-10-08 by
  round 23. `pmos.debug-shell` is handled in `init_2nd.sh` before root is
  looked for. On pkgrel 10 with `regs.dtb` the harvest reached it over
  telnet, and it had started at 4.97 seconds of uptime.
- **The host side of the debug shell is ready and tested** — Verified. Fedora
  ships no `telnet`, `nc` or `socat`, and this project may not install onto the
  host, so `scripts/telnet.py` is the fallback: tested against a stub that
  opens the way busybox `telnetd` does (`IAC WILL ECHO`, `IAC WILL SGA`,
  `IAC DO NAWS`, an `SB`/`SE` subnegotiation, then a prompt), with the command
  bytes stripped from the display and the typed line arriving byte-exact.
  `scripts/console.sh` prefers a real client if one appears.
- **`tsh.py`'s `@push` works against Alpine's own busybox** — Verified
  2026-10-08, off the device. The test ran the native chroot's
  `busybox-extras telnetd` and `busybox sh` inside the pmport container,
  through the chroot's musl loader. That is the same build and config as
  the initramfs's, with a working pty, which the pmbootstrap chroot itself
  does not give telnetd. A 70 KB module and 300 KB of random data arrived
  with matching checksums, at about 370 KB a second. The question was
  busybox's line editor, which caps a line at 1024 characters; each chunk's
  command is longer than that. With `stty -echo`, which tsh's handshake
  runs, ash reads through `fgets` and joins the pieces, so the cap never
  bites. Rounds 27 and 34 are the first to push on the device.
- **The container shares the host network namespace** — Verified. `ip -o link
  show` is identical inside and out, so the gadget is reachable from either
  side once it enumerates.

## USB on the device

- **Every kernel-side prerequisite for the USB gadget is present** — Verified.
  `USB_DWC3=y` with `USB_DWC3_DUAL_ROLE=y` (not host-only), and
  `USB_CONFIGFS_{ACM,NCM,RNDIS,MASS_STORAGE}` all `=y`. The glue (`dwc3-msm`)
  and the two PHYs are modules and are in `modules-initfs`.
- **USB gadget actually enumerates on the device** — Guess. The config is
  necessary, not sufficient. The likely failure is Type-C role detection:
  `TYPEC_QCOM_PMIC` is not set, so the gadget depends on the PMIC/charger
  driver reporting over extcon.
- **The display clock controller is a USB dependency on this SoC** — Verified
  on the device, by the flash log of the 19:23 round. The chain, read
  backwards from `dwc3-msm`: it wants a `ddr-usb` interconnect path through
  `interconnect@19100000`, whose `qcom,bcm-voters = <0x13e 0x13f>` names two
  voters; `0x13f` is `/soc/rsc@af20000/bcm_voter`, a child of the display RSC;
  that RSC declares `clocks = <0x11f 0x42>`, and `0x11f` is
  `clock-controller@af00000`, `qcom,parrot-dispcc`. With fw_devlink the RSC
  cannot probe before dispcc does, so no voter is created, so the interconnect
  provider never registers, so `dwc3-msm` defers for ever. Nothing in that
  chain prints anything.
- **Our staged probe was holding dispcc back, and so breaking its own USB** —
  Verified against the source. `dispcc-parrot` sat in `STAGE_DEFER`, which
  loads after the USB bring-up step, on the reasoning that display drivers are
  a hang risk. It has been moved into the first pass. The real init never had
  this problem, because it loads every module at once.
- **With dispcc loaded, the whole deferral chain resolves** — Verified. In the
  19:23 flash log, `af20000.rsc` binds `rpmh`, `af20000.rsc:bcm_voter` binds
  `bcm_voter`, `19100000.interconnect` binds `qnoc-parrot`, and
  `a600000.ssusb` binds `msm-dwc3`. `devices_deferred` no longer mentions USB
  at all - only display GPIO regulators, `qcom,scmi`, `gpio_keys` and
  `kgsl-smmu`.
- **`eud` binds and gives us a EUD UART** — Verified.
  `88e0000.qcom,msm-eud: ttyEUD0 at MMIO 0x0 (irq = 263) is a EUD UART`, and
  the device binds `msm-eud`. That half of the fix was right.
- **dispcc was loading 200 ms too late, not far too late** — Verified from the
  timestamps. The USB bring-up ran at 2.95 s, `dispcc` at ~3.1 s and
  `msm-dwc3` finished probing at 4.33 s. The probe log shows `udc-core:
  couldn't find an available UDC or it's busy` twice, which also proves the
  pinned `deviceinfo_usb_network_udc` is being honoured - it refused to fall
  back to the emulator.
- **`dwc3-msm` probes and then stays in "none" mode** — Verified. The last
  thing it prints is `IRQ hs_phy_irq not found`, `Nominal values not found`,
  `Using default bus votes`, and then nothing. `a600000.dwc3` never appears as
  a platform device, so no real UDC is ever registered and `/sys/class/udc`
  holds only `dummy_udc.0`. The stock tree gives `ssusb@a600000` a
  `dwc3@a600000` child with `dr_mode = "otg"` and `usb-role-switch`, so the
  core is only created when something asks for a role. On Android that request
  comes from the charger and Type-C stack, none of which exists in an
  initramfs.
- **The driver has a sysfs mode override, and our build has it** — Verified in
  `dwc3-msm.ko`: `dev_attr_mode`, `mode_store`, `dwc3_otg_start_peripheral`,
  the strings `peripheral`, `host`, `none`, and `dev_attr_usb_data_enabled`.
  Neither `eud.ko` nor `dwc3-msm.ko` takes any module parameter, so sysfs is
  the only way in. The staged probe now writes `peripheral` to
  `/sys/bus/platform/devices/*.ssusb/mode` and waits up to twelve seconds for
  a non-dummy UDC.
- **Writing `peripheral` to `*.ssusb/mode` brings the controller up** —
  Verified on the device, over a live USB link. The probe log reads
  `[55] forcing peripheral mode on the ssusb wrapper`, `wrote peripheral to
  /sys/bus/platform/devices/a600000.ssusb/mode`, `udc wait ended after 1s,
  real udc: a600000.dwc3`. One second. `dmesg` shows the mechanism exactly:
  `DWC3 exited from low power mode` and then `dwc3 a600000.dwc3: Adding to
  iommu group 0` - the core child being created - followed by `usb0: HOST MAC`
  and `usb0: link becomes ready`.
- **The USB gadget enumerates to the host** — Verified. Sixteen seconds from
  reboot to a gadget the host can see: `enp0s20f0u2` at 172.16.42.2 with the
  phone on 172.16.42.1 answering ping in 2.1 ms, telnet open on port 23, and a
  `/dev/ttyACM0`. The Fedora host needs no configuration for either: it
  DHCP-configures the NCM interface by itself, and a `uaccess` ACL grants the
  logged-in user read-write on the ACM node, so neither of the two host-side
  fixes `scripts/console.sh` offers was needed.
- **A complete boot, from the live shell** — Verified. `/sys/class/udc` holds
  `a600000.dwc3` beside `dummy_udc.0`, `g1/UDC` names the real one, 90 modules
  are loaded, `/pmstage` reads 99, and `sda`, `sdb`, `sdc` and `mmcblk1` are
  all present. `out/device-dump-root/reference/pmos-boot-dmesg.txt` is the
  kernel log of that boot, taken over telnet.
- **Where that write belongs for the real init** — Settled, if not elegantly.
  `init.sh` calls `load_modules` and then `setup_usb_network` with nothing in
  between, and `run_hooks` is only reached from `init_2nd.sh`, after the
  rootfs is mounted, so there is no sanctioned place for a device quirk.
  Rather than fork `postmarketos-mkinitfs`, `bootlog.py usbquirk` patches
  `/init` as the image is built and `try-kernel.sh` applies it to every
  real-init flash. If this port is ever upstreamed the quirk needs a proper
  home.
- **The real init has two stages, and stage 1 ends at line 59** — Verified.
  `deviceinfo_create_initfs_extra` defaults to false, so mkinitfs builds one
  archive with `/init_2nd.sh` already inside it, and stage 1's
  `jump_init_2nd` - which is `exec /init_2nd.sh` when that file exists - runs
  right after `setup_firmware_path`. Everything below it in `init.sh` is dead
  code on this device: `setup_mdev`, `load_modules`, `setup_usb_network`, all
  of it. `load_modules` never runs at all, so `modules-initfs` only decides
  which `.ko` files mkinitfs puts in the archive; loading is udev's job, via
  `udevd -d`, `udevadm trigger --action=add` and `udevadm settle` at the top
  of stage 2.
- **The 19:42 round failed because the quirk was in that dead code** —
  Verified. Not a hang: `usbquirk` anchored on `setup_usb_network`, found
  stage 1's copy, and patched a line the device never reaches. Both stages now
  get the quirk, and in stage 2 it lands between `setup_udev` and
  `setup_usb_network`, with `debug_shell` fourteen lines further on. The
  watchdog stays in stage 1 only, before the jump, because a background job
  survives its parent's `exec`.
- **Withdrawn: "the real init hangs in `load_modules`"** — it does not, and
  cannot, because `load_modules` is never called. The reasoning that led there
  was sound given no USB and no log, but it was built on assuming `init.sh`
  runs to the end.
- **A hung real init needed a person, and no longer does** — Reasoned, not yet
  tested. `load_modules` wedging is the one failure mode that cannot recover
  on its own: nothing resets the phone, so the bootloader never begins another
  attempt and the retry counter never moves. `bootlog.py usbquirk` now also
  arms a watchdog after `mount_proc_sys_dev` and before `load_modules`, which
  resets the phone after 240 s unless `/pmusbok` exists - a file the quirk
  touches once a real UDC is bound. Seven hung attempts then come to about 31
  minutes before the fallback to Android, hands-free.
- **One ext4 partition on the SD card is the whole layout** — Reasoned from
  stage 2, not yet tested. Stage 2 only looks for a boot partition when the
  rootfs has no usable `/etc/fstab`:

      if [ -z "$(cat /sysroot/etc/fstab | grep -v "#" | tr -d '[:space:]')" ]; then
              wait_boot_partition
              mount_boot_partition /sysroot/boot "rw"
      fi

  `make-rootfs-img.sh` writes `/etc/fstab`, so that branch is skipped. And
  `extract_initramfs_extra` lives in stage 1 below the jump, so it never runs
  either. That removes every reason to build a boot partition, a subpartition
  image, an `initramfs-extra` archive, or to pass `pmos.stowaway`: one ext4
  partition carrying the rootfs, found by the `pmos_root_uuid=` already on the
  command line, is enough.
- **The rootfs goes on the SD card** — Decided, 2026-10-05, by the owner. The
  phone has a 477 GiB SDXC card in it, already detected as `mmcblk1`, and
  writing there leaves stock Android on slot b intact - which is what the
  recovery loop depends on. `deviceinfo_flash_fastboot_partition_rootfs` still
  says `userdata`, the conventional target; using it would wipe Android's data
  and cost us that fallback. The card can be partitioned and written from the
  initramfs debug shell over the USB network link, so this needs nobody to
  open the phone.
- **`blkid` kills the debug shell** — Verified, twice is not needed. Running
  it over telnet dropped the connection; the device stayed up and pingable, so
  it is `blkid` scanning every loop and ram device against a 4096-byte-sector
  disk, not a crash. Use `/proc/partitions` instead.
- **The real init enumerates nothing at all** — Verified, from this host's own
  kernel log rather than from the phone. Across the 20:10 round the host saw
  the bootloader (`Pdx246`), fastboot (`Android`/Google, `0fce:0dde`), Android
  on slot b (`XQ-ES72`, `0fce:320e`) and fastboot again, then a disconnect at
  20:12:02 and **not one enumeration in the fifteen minutes after it**. So the
  question is not whether the gadget is misconfigured: no USB device appears on
  the cable at all, which is what a boot that never reaches `setup_udev` looks
  like.
- **Correction: `pmos.debug-shell` is on the command line** — Verified. An
  earlier reading here said it was absent, from a grep that required `=` and
  so skipped every bare flag. It is in `kernel-cmdline.conf` and in the
  cmdline baked into the flashed image. That matters: stage 2 stops at
  `debug_shell` four lines after `run_hooks /hooks`, well before
  `wait_root_partition`, so a shell does **not** depend on there being a
  rootfs to find.
- **Nothing between the quirk and `debug_shell` can block** — Verified against
  the initramfs source, which rules out the obvious reading of the silence.
  `setup_framebuffer` polls for `/dev/fb0` a hundred times at 0.1 s and gives
  up; `setup_dynamic_partitions` returns at once when no super partitions are
  named, and this device names none; `run_hooks` returns on an empty or
  missing directory, and only `hooks-cleanup` ships; `run_getty` wraps its
  `getty` loop in `{ ... } &`, so even a getty on a console that does not
  exist cannot stall the caller. Whatever stops this boot stops it earlier
  than stage 2.
- **udev in the initramfs has everything it needs to load drivers** — Verified
  by listing the archive, and it kills a tidy hypothesis. Thirteen rules are
  present including `80-drivers.rules`, whose `ENV{MODALIAS}=="?*"
  RUN{builtin}+="kmod load"` is the line that autoloads from a modalias, and
  `modules.alias`, `modules.dep` and their `.bin` indexes are all there beside
  `initramfs.load`. "udev had no rules, so no modules loaded, so no USB and no
  log" is therefore wrong.
- **Naming the real UDC is not just tidiness** — Verified against
  `get_usb_udc()`, which is `ls /sys/class/udc | head -1` unless
  `deviceinfo_usb_network_udc` is set. With `dummy_hcd` built in there are two
  entries, and `a600000.dwc3` only wins that race because `a` sorts before
  `d`. The deviceinfo key is set, so the gadget lands on the hardware or fails
  loudly instead of depending on alphabetical luck.
- **Removed: the 20-second `hung_task_panic` in the watchdog** — my mistake,
  corrected. `bootlog.py`'s watchdog set `hung_task_panic=1` with
  `hung_task_timeout_secs=20`, which panics the kernel over any task that
  blocks for 20 s. On a bring-up boot that is ordinary - a probe waiting on
  firmware, or `udevadm settle` draining ninety modules' events - and with
  `panic=5` on the command line it would reset a boot that was merely slow.
  It also caught nothing the 240 s timer does not, since both need the kernel
  to still be scheduling userspace. Only `sysrq` and the timer remain.
- **Stage 1 jumps at line 44, not 59** — Verified by reading the archive's own
  `/init`. The count of 59 here was taken from a patched image. The live part
  of stage 1 is lines 1-44: `busybox --install`, `mount_proc_sys_dev`,
  `parse_cmdline`, `setup_log`, `setup_firmware_path`, `jump_init_2nd`.
  Everything below is dead on this device.
- **The root lookup scans every block device, and that scan can be skipped** —
  Verified against the source, and it matters because `blkid` has taken this
  phone's debug shell down. `find_partition` runs `blkid --uuid "$uuid"`,
  which probes everything; but `find_root_partition` only calls it when
  `PMOS_ROOT` is empty, so setting `PMOS_ROOT` ahead of it avoids the scan
  entirely. `get_partition_type` and `delete_old_install_partition` pass
  `blkid` a single device, which is the safe form. One full scan remains that
  presetting does not avoid: `resize_root_partition` asks
  `blkid --label pmOS_install` before deciding, and then - with no
  `pmos.force-partition-resize` and no subpartitions - prints "failed to find
  qualifying partition" and returns without touching `parted`.
- **This device has no framebuffer, and now says so** — Verified by absence:
  the display stack is dispcc plus a DPU and panel driver we do not build, so
  `/dev/fb0` cannot appear. `deviceinfo_no_framebuffer="true"` sets
  `nosplash=y` inside the initramfs, which turns both `setup_framebuffer`'s
  ten-second poll and the splash into no-ops. The console here is a serial
  port, so a framebuffer splash had nowhere to go in any case. That
  holds for the downstream kernel only: since pkgrel 16 the mainline
  kernel drives the panel, and the debug shell draws on it (see "The
  panel lights").
- **The watchdog was armed too late to catch this** — Verified by reading the
  patched image, and corrected. It went in after `mount_proc_sys_dev`, which
  is itself somewhere stage 1 can die: that function modprobes `libcomposite`
  and mounts configfs. So a wedge anywhere in the first thirty-five lines left
  nothing to reset the phone, the bootloader never began another attempt, the
  retry counter never moved, and the boot was indistinguishable from a dead
  one - which is the state the 20:10 round sat in. It is now inserted directly
  after `set -a` on line 5 and written to depend on nothing that has not
  happened yet: absolute `/bin/busybox` paths, because `busybox --install -s`
  has not run, and no `/proc`, because `mount_proc_sys_dev` has not either.
  The reboot probe already established that a bare busybox `sleep` and
  `reboot -f` work that early. This does not fix the hang; it converts a
  silent hang into a reset loop that ends in Android with a log to read.
- **A live shell can stop the reset timers** — Verified by reading the patched
  image; the on-device half is untested. Every watchdog here resets the phone
  on a timer measured in minutes, which is correct for a boot nobody is
  watching and wrong the moment something is mid-operation: a gigabyte of
  rootfs onto the SD card outlasts the staged probe's patience, and being cut
  off halfway leaves a partial filesystem. `pmstage_reset` and the real init's
  watchdog now both wait while `/pmhold` exists. Nothing creates that file on
  its own, so an unattended boot still resets itself on the same schedule;
  `sdcard-install.sh` creates it before the first write and removes it from a
  trap, so a crash or an interrupt hands the phone back.
- **The hold is a lease** — Done 2026-10-08, after round 37, and tested
  off the device. In round 37 the live commands held the phone, booting
  the ADSP took the USB link, and the phone sat in the initramfs, alive
  and out of reach, until someone reset it by hand (see "Round 37: the
  ADSP boots, and the gadget goes with it"). Nothing but the lost shell
  could have removed `/pmhold`. Now the hold stands only while a host has
  had the gadget configured within the last 90 seconds, and for 900
  seconds after the file was last touched.
  - The USB watchdog, the log hook's backup reset and the staged probe
    all ask `pmhold_held()` in `scripts/bootlog.py`. It removes a lapsed
    hold and writes why to `/pmwd.log`, which every record carries.
  - `tsh.py` touches the file before every command and every 256 lines of
    a push. `sdcard-install.sh` touches it from the host every two
    minutes while the image streams.
  - Tested in busybox ash against a fake sysfs, twelve cases. No round
    has lost the link since, so no hold has lapsed on the device yet.
- **The staged probe can hand off to the stock second stage** — Written and
  verified against the archive; untested on the device. `HANDOFF=1` puts a
  `/pmhandoff` file in the ramdisk, and the staged init `exec`s
  `/init_2nd.sh` after its last module pass instead of idling until it
  resets. The point is that it sidesteps the stage 1 hang entirely: the probe
  loads modules in an order known to work here, and stage 2 opens by having
  udev load everything, which by then has nothing left to do. It is never a
  blind step, because the handoff is below the point where the gadget is
  bound and telnet is listening. Both of the probe's watchdogs are killed
  across it - left armed they would fire minutes later into a live session,
  or into a system that had already switched root, which `init_2nd.sh`'s
  `kill $(pidof sh)` would not prevent, since this init runs as busybox `ash`
  and not as `sh`.

## Flashing

- **The procedure in [04-flashing.md](04-flashing.md)** — Reasoned. Derived
  from AVB behaviour; **not executed**.
- **The bootloader on this unit is already unlocked** — Owner-reported. Not
  yet confirmed against `ro.boot.flash.locked`; `scripts/device-probe.sh`
  reads it. This takes the wipe-and-lose-DRM decision off the critical path,
  so the irreversible-steps warning in 04-flashing.md is background for this
  unit rather than a pending choice.
- **`adb` and `fastboot` have to run on the host, not in the container** —
  Verified. `/dev/bus/usb` passes through, but the nodes are host `root:root`
  0664 and appear as `nobody:nogroup` inside, so the container cannot get
  write access and so cannot claim an interface. There are no android udev
  rules on the host and nothing tags the device `uaccess`, so no ACL is
  granted either. The host has android-tools 37.0.0 and the owner has
  authorised using it. `flash.sh` calls `fastboot` directly with
  project-relative paths, so it runs on the host unchanged.
- **This bootloader refuses `fastboot boot` outright** — Verified 2026-10-05,
  superseding the guess that it might silently ignore the staged ramdisk and
  run the stock kernel. An explicit refusal is the better of the two
  outcomes: there is no ambiguity about what ran. The consequence is that
  every kernel test costs a flash, which is why `flash-boot` and
  `restore-boot` exist and touch nothing but the two boot partitions.
- **Backing up stock by dumping partitions needs root, which a stock Xperia
  has not got** — Verified by construction: unlocking the bootloader does not
  grant root, so the `dd` recipe only applies to an already-rooted phone. The
  realistic backup is a firmware download, which is also the true recovery
  path. 04-flashing.md step 1 says so.
- **Leaving the stock `dtbo` in place gives the right device tree** —
  Reasoned. This is what stock does; untested with *our* base.

## The port boots

On 2026-10-05 at 23:15:54, `HANDOFF=1 STAGE=1 ./scripts/try-kernel.sh` ended
with postmarketOS running on the phone. Everything in this section is Verified
by logging in and asking.

The handover is legible in five seconds of polling from the host, which is
worth keeping as the signature of a good boot:

```
23:15:44 ping  -    telnet     still in the initramfs
23:15:49 ping  -    -          switch_root: telnetd gone, sshd not up yet
23:15:54 ping  SSH  -          systemd is up
```

- **`Nura edge`, kernel `5.10.269-gki #1-postmarketOS`, hostname
  `sony-pdx246`** — reached over `scripts/ssh.py` as `user`.
- **`graphical.target reached after 9.535s in userspace`**, 21.07s of that
  kernel, 30.6s in total. 159 modules loaded, all 8 CPUs online.
- **Root is the SD card** — `/dev/mmcblk1p1` on `/`, 15.7 G, 649 M used.
- **UFS is intact and untouched** — `sda` at 119.1 G with its full Android
  partition table visible. Nothing was written to it.
- **The USB gadget survived `switch_root`** — `usb0` is UP with
  `172.16.42.1/16`. This is the thing the whole handoff design turns on: the
  gadget lives in configfs, which is kernel state, so it crosses `switch_root`
  untouched and `unudhcpd@usb0.service` and `sshd.service` come up on the far
  side of it. No persistence was added to the rootfs to make this work.
- **Two units fail, both harmlessly** — `nftables.service` (no ruleset
  shipped) and `systemd-firstboot.service` (the image is already seeded). That
  is what `systemctl is-system-running` reporting `degraded` means here.
- **The touchscreen controller is alive** — FocalTech `fts_ts` on i2c
  `3-0038` is probing and polling its flow counter, so the part answers. It
  wants `focaltech_ts_fw_.bin`, which we do not ship, and a `drm_panel`, which
  cannot exist until there is a display driver.
- **No battery or thermal readings** — `/sys/class/power_supply` is empty, so
  the `pmic_glink`/`qcom_battmgr` path is not up.
- **Nothing sets the clock** — it comes up years out and nothing corrects it.
  Harmless in itself, but see the `resize2fs` trap below: on this device a
  wrong clock is not only cosmetic. An earlier version of this file said
  "there is no RTC", which was an observation about this kernel written up as
  a fact about the hardware. The hardware does have one: the live device tree
  puts an `rtc@6100` on PMK8350, and upstream has a driver for it.

### What this changes about the loop

Userspace no longer needs a reflash. A kernel or initramfs change still costs a
full `try-kernel.sh` round, but anything in the rootfs can now be edited in
place over ssh, and `scripts/sdcard-install.sh` can rewrite the whole card from
the initramfs shell when a clean slate is wanted. The sequence that gets from a
booted phone back to a flashing state is in [07-devloop.md](07-devloop.md).

## The handoff into stage 2

Run on 2026-10-05 with `HANDOFF=1 STAGE=1 ./scripts/try-kernel.sh`. The
mechanism works; the boot past it did not, for a reason worth writing down.

- **The handoff itself is sound** — Verified. `/pmstage` read 100,
  `/proc/1/comm` read `init_2nd.sh`, and `/proc/1/environ` carried
  `root_uuid=1e3e6bd0-...` and `debug_shell=y`. So the staged probe's module
  order gets the SoC up, stock stage 2 inherits it, and `/sys/block` by then
  lists `sda`, `sdb`, `sdc` and `mmcblk1` - both UFS and the card.
- **Stage 2's debug shell is what kills the boot, and it is not subtle** —
  Verified. `debug_shell` ends by unlinking the ACM function from a gadget that
  is still bound and then calling `setup_usb_configfs_udc`, which clears
  `g1/UDC` and writes it back. The rebind does not come back on this phone:
  dwc3-msm drops out of peripheral mode and nothing in an initramfs asks it for
  a role again, which is the same reason the probe has to write `peripheral` to
  `*.ssusb/mode` in the first place. The host logged `usb 3-2: USB disconnect`
  at 23:01:28, the instant the shell was released, and nothing re-enumerated.
  The probe now sets `debug_shell=n` across the handoff.
- **Nothing between the handoff and `switch_root` blocks** — Verified by
  reading each function against the live initramfs. `resize_root_partition`
  prints "Unable to resize root partition: failed to find qualifying partition"
  and returns, because there are no subpartitions, no
  `pmos.force-partition-resize` and no `deviceinfo_cgpt_kpart`.
  `delete_old_install_partition` turns `/dev/mmcblk1p1` into itself (its `sed
  s/2$/3/` finds no trailing 2) and finds no `pmOS_deleteme` label.
  `wait_partition` gives up after thirty seconds rather than hanging.
- **`setup_usb_network` is guarded by a file, not a variable** — Verified:
  `/tmp/_setup_usb_network`. Files survive an exec, so the gadget the probe
  built carries into stage 2 untouched. This is why the handoff does not need
  to rebuild it.

### The card, after the write

- **The image is on the card and verified** — Verified. 1020264448 bytes at
  2.9 MB/s, `dd_rc=0`, and `/dev/mmcblk1p1` reads back UUID
  `1e3e6bd0-9170-4c79-a34b-64ece0ad2ca6`, type `ext4`, clean `e2fsck -fn`.
- **The partition was shrunk from 476 GiB to 16 GiB on purpose** — Verified.
  Stage 2 runs `resize2fs` unconditionally, and growing a 973 MiB filesystem
  to fill the whole card would have written group metadata for ~3900 new block
  groups and then left the kernel's `ext4lazyinit` thread zeroing gigabytes of
  inode tables in the background. 16 GiB is ten times what the rootfs uses and
  keeps `e2fsck` on every boot cheap. `resize_root_partition` returns without
  touching parted, so nothing grows it back.
- **`parted -s` does not cover the shrink warning** — Verified. `parted -s -f
  ... resizepart` printed "Shrinking a partition can cause data loss, are you
  sure you want to continue?" and exited 1, changing nothing. It needs
  `---pretend-input-tty` with `yes` on stdin.
- **`resize2fs` refuses while the phone's clock is at the epoch** — Verified,
  and this one would have been baffling later. There is no RTC sync in the
  initramfs, so the clock sits around 12 January 1970, while the image carries
  2026 mount timestamps from the host that built it. `resize2fs` compares the
  filesystem's last-checked time against its last-mounted time, sees the check
  as older, and says "Please run 'e2fsck -f' first" - no matter how many times
  `e2fsck -fy` is run, because each run stamps 1970. Setting the clock first
  makes the same command resize 973 MiB to 16 GiB in one second. Stage 2 does
  not set the clock, so on a boot where the filesystem still needs growing its
  `resize2fs` will fail silently; the boot carries on, because `init_2nd.sh`
  does not check the exit status.

### Getting back to fastboot without touching the phone

The loop needs the device in fastboot, and a live pmOS shell had no way to ask
for it. This is now a two-minute step instead of an eleven-minute one.

- **There is no shell route to fastboot on this kernel** — Verified. busybox
  has no `devmem` applet and no way to call `reboot(2)` with
  `LINUX_REBOOT_CMD_RESTART2`, which is how Android's init asks for
  "bootloader". The restart reason itself was located - the `qcom,reboot-reason`
  node's nvmem cell is `sdam@7100` (`spmi_sdam2`) at byte `0x48`, bits 1 to 7,
  and that attribute is writable - but writing a PMIC register was not
  authorised, so it stays unused and is recorded here only as a fact about the
  hardware.
- **A pmOS that boots and stays up is a dead end for the loop** — Verified,
  2026-10-06, and this is the open blocker. The loop's route to fastboot
  assumed a *failed* experiment: a kernel that dies burns the retry counter,
  the bootloader falls back to stock, and adb answers. A kernel that *works*
  has no adbd and no authorised way to ask for the bootloader, so the port sat
  for twenty-one hours with a finished mainline kernel on the host and nothing
  able to flash it.
- **`systemctl reboot --reboot-argument=bootloader` reaches fastboot, and is
  the answer** — Verified, 2026-10-06. Fifteen seconds from a running pmOS to
  `fastboot devices` answering. It hands `reboot(2)`
  `LINUX_REBOOT_CMD_RESTART2` with the string "bootloader", and the
  `qcom,reboot-reason` node in the live tree binds a driver that turns that
  into the restart reason the boot chain reads - the same mechanism
  `adb reboot bootloader` uses on stock, done by the kernel rather than by
  poking the SDAM from userspace. Two spellings do not work and are worth not
  rediscovering: `systemctl reboot bootloader` is rejected with "Too many
  arguments" by this systemd, and `systemctl reboot` as `user` returns silently
  and does nothing, because logind defers to polkit and polkit wants an active
  local session.
- **Rebooting a healthy pmOS does burn the slot's retry counter** — Verified,
  and this corrects a claim written earlier the same day that it does not.
  Reading the slot state from fastboot settled it: slot a, the pmOS slot, was
  at `slot-retry-count:a 1` with `slot-successful:a no`, down from the 7 that
  slot b still shows. So the handful of reboots had been spending attempts all
  along; the counter simply had not reached zero yet, and the earlier reading
  was drawn from "no fallback happened" rather than from the counter itself.
  Burning it down is a real route to the stock slot, just six or seven rounds
  slower than asking the kernel.
- **`systemctl reboot` has to go through sudo, and not too early** — Verified.
  As `user` it returns silently and does nothing, because logind hands the
  request to polkit and polkit wants an active local session. `sudo` is setuid
  root and the user is in `wheel`, but it refuses `-n` with "interactive
  authentication is required", so the password goes in on stdin with `-S`. Even
  then a request made about 29 seconds into a boot is silently ignored while
  one made at 40 seconds is honoured, and `systemctl is-system-running` already
  says `degraded` at 29 seconds, so it is not the discriminator.
- **The BCB already asks for fastboot and the bootloader ignores it** —
  Verified, and it rules out the last software route that was not already
  refused. Offset 0 of `misc` (`/dev/sda52`) is the AOSP
  `bootloader_message.command` field, and it reads `bootonce-bootloader` right
  now - the string Android writes there to request fastboot on the next boot.
  Seven reboots went past it into pmOS. Either Sony's ABL does not read the BCB
  or it reads and clears it, and the field is still set, so on either reading
  the request is not being honoured. Writing it would not help, which is worth
  knowing because it is the obvious next thing to try.

  The restart reason is what works, and it is reached through the kernel rather
  than written by hand; see the `--reboot-argument` entry above.
- **Burning the bootloader's retry counter is the sanctioned route, and it is
  fast if you do not wait** — Verified. Our slot never marks itself booted, so
  every attempt decrements the counter; after enough of them the bootloader
  gives up and boots the stock slot, where adb is waiting. The probe's own
  patience is `sleep 600`, which makes a cycle eleven minutes - but resetting
  the moment telnet answers makes it about twenty-six seconds. Four resets took
  the phone from a probe shell to stock Android in two minutes.

### The loop past switch_root

Until 2026-10-11 every mainline round stopped in the debug shell, and the
loop was built around that: a telnet shell to run commands in, and jobs in
the initramfs to log the boot to the card and reset the phone when nobody
holds it. A boot that goes on into the rootfs loses all three, so commit
2750b73 rebuilt each for it. Round 83, the first `FULLBOOT=1` round, ran it;
each entry says how much of it held.

- **switch_root takes the jobs' tools and their /proc away** — Verified by
  reading the initramfs. Its `switch_root` is util-linux 2.42.4, not
  busybox's. It moves the mounts at `/dev`, `/proc`, `/sys` and `/run` into
  the new root, then deletes everything on the initramfs that is not a
  mount. On this merged-usr ramdisk that is busybox, the musl loader, and
  `/bin`, `/sbin` and `/lib`, which are symlinks into `/usr`. The jobs
  outlive the switch, because `init_2nd.sh` kills only `udevd`, `syslogd`,
  `unudhcpd` and every `sh`, and theirs are named `init`. But from then on
  each command they run fails, and so does each read of `/proc` or `/sys`
  and each write to the card.
- **A hook keeps them working** — Half verified by round 83, and the other
  half fixed and Reasoned. `scripts/bootlog.py` now adds
  `hooks-cleanup/99-pdx246-keep.sh`, which runs just before the switch.
  In round 83 the tools and `/proc` came through, and `/sys` and `/dev`
  did not; the third point below says why, and what replaced it.
  - It puts a static busybox and its applet links on a tmpfs at `/pmkeep`.
    The jobs' root is still the initramfs after the switch, so that tmpfs
    stays theirs.
  - It turns `/bin` and `/sbin` into directories and mounts that tmpfs on
    them. `/usr/bin` is left alone, because the rest of `init_2nd.sh` needs
    `switch_root` from it.
  - It stacks a second mount on `/proc`, `/sys` and `/dev`. `switch_root`
    moves the top one at each path, and the jobs keep the ones underneath,
    configfs and debugfs included. `/proc` gets a fresh proc. `/sys` and
    `/dev` get recursive binds of themselves, because a fresh sysfs or
    devtmpfs is the same superblock, and the kernel refuses to mount a
    superblock where it is already the top mount ("Refuse the same
    filesystem on the same mount point", `do_add_mount()`). Round 83's
    fresh ones failed that way, with EBUSY.
  - Verified off the device, in a user namespace: moving a path with two
    mounts stacked on it moves only the top one, and with recursive binds
    both sides keep their submounts.
  - The busybox is Alpine's `busybox-static-1.38.0-r7`, the initramfs' own
    version, checked against the APKINDEX's checksum. It lives in `out/`,
    which is not in git; the comment above `KEEP_SH` says where it came from.
- **The host holds a booted system through the jobs' root** — Verified
  by round 83, which held through `/proc/147/root`. Until the jobs see the
  UDC again, which the bind fix is for, such a hold lapses after 90 s.
  `/pmhold` and the jobs' other files are deleted at the switch, and the
  log hook's backup reset comes back at 500 s of uptime. The jobs still see
  the old root, and from the new one it can be reached as
  `/proc/<pid>/root`. `scripts/ssh.py` runs commands as root through sudo,
  finds the first such root that has `/pmkeep/bin/busybox`, and touches
  `pmhold` in it the way `tsh.py` touches `/pmhold`. Its `@hold` creates the
  hold, and retries six times 10 s apart, because the ADSP's boot drops the
  USB link for a few seconds.
- **`FULLBOOT=1` makes a round a full boot** — Verified by round 83.
  `try-kernel.sh` takes `pmos.debug-shell` off the command line, waits up
  to `SSH_WAIT` seconds for sshd on 172.16.42.1:22, and runs the round's
  commands over ssh with an `@hold` in front. The transcript has anything
  twelve characters or longer of digits and capitals redacted, as the
  harvest does.
- **The queue resets a booted system over ssh** — Verified by round 83's
  timing: seven full boots about 40 s apart, from the round's end to stock
  Android in 4.5 minutes. With no telnet after the switch, `kick_gadget`
  in `scripts/queue.sh` sends sysrq b through `ssh.py` and sudo when port
  22 answers and 23 does not. So each of the seven or so attempts that
  burn the retry counter down to the stock slot ends quickly.
- **A full boot writes nothing to UFS that we know of** — Reasoned, read
  out of the image before round 83.
  - The image has no rmtfs, udisks2, ModemManager or automounter.
  - Its swap file is on the root filesystem, `local.d` is empty, and no
    udev rule writes to a disk.
  - busybox's `watchdog` service is in no runlevel, so nothing opens
    `/dev/watchdog0`.
  - `mount_subpartitions` in the initramfs only reads, and looks for loop
    partitions only while the root has not been found. With
    `pmos_root_uuid=` on the command line and the card in, `blkid --uuid`
    finds the root first.
- **postmarketos-mkinitfs 2.12.0 writes a zstd ramdisk** — Verified, magic
  `28 b5 2f fd`. Earlier ones were gzip. The kernel takes both
  (`CONFIG_RD_GZIP=y`, `CONFIG_RD_ZSTD=y`), and `bootlog.py` now reads
  either and writes gzip. `verify-bootimg.py` still reads only gzip; the
  loop does not use it.
- **`sdcard-install.sh --keep-table` writes into the card's existing
  partition** — Verified by round 82.
  - It finds the card on the phone by `device/type` reading `SD`, and
    insists on exactly one.
  - It checks that p1 exists, is at least as large as the image, and ends
    before the log region at 32 GiB. A new partition table makes p1 1 MiB
    to 16 GiB.
  - After the write it sets the phone's clock from the host, runs
    `e2fsck -fy` (0 or 1 is fine, anything else stops it), and then
    `resize2fs`, which only warns if it fails. Stage 2 also runs
    `e2fsck -p` and `resize2fs` on every boot (`resize_root_filesystem`
    in `init_functions_2nd.sh`), but with the phone's clock near the epoch
    its `resize2fs` can refuse, as "The card, after the write" found. So
    the resize that counts is this one, and stage 2's has nothing left to
    do.

## Known gaps

- **Display.** On the mainline kernel it is in-tree drivers only: drm/msm's
  MDSS, DPU, DSI and DSI PHY, and the upstream Samsung SOFEF01-M panel
  driver. Drivers and nodes are all in pkgrel 16's series. Round 32
  bound all of it, and since round 48 the panel sends TE and answers a
  read, on pkgrel 16's own tree too in round 55. It lights: the owner
  saw the debug shell's terminal and keyboard on it (see "The panel
  lights"), and Lomiri on it, through Mir's KMS platform (rounds 86 and
  87). The panel driver is a backport of a
  posting that is not merged yet. The downstream kernel's panel driver is in the
  out-of-tree `sm6450-modules` repository, which this port does not build
  and the mainline kernel will never use - not depending on Android vendor
  modules is the point of the mainline kernel. First boots are blind by
  design.
- **Vendor device trees that need `sm6450-modules`** (downstream kernel only).
  The same repository also
  owns the dt-bindings headers that Qualcomm's `audio/` and `camera/` device
  trees include, so those cannot be built here at all. We sidestep it by
  building only the base `parrot.dtb`, which is the one we boot; the rest of
  the parrot family is not ours. If `sm6450-modules` is ever built, the
  three-line `vendor/qcom/Makefile` written in `prepare()` is what to revisit.
- **GPU.** Adreno 710. On the downstream kernel it is KGSL, and Mesa's a7xx
  support targets the mainline `msm` uAPI, so expect software rendering there.
  On the mainline kernel it is drm/msm's GPU side. Pkgrel 19 taught it the
  A710, the firmware is collected from `vendor_b`, and the nodes are WIP
  on `sm6450-gpu` (see "The GPU"). Round 66 panicked at boot with them.
  Rounds 67 to 72 found why and fixed it, and in round 72 the GPU ran
  `msm-submit`'s jobs. Userspace needs Mesa's A710 entry, which no Mesa
  release has; `temp/mesa` backports it. With it, freedreno reports FD710
  (round 82), kmscube draws at the panel's 60 Hz (round 85), and Lomiri
  renders through it (rounds 86 and 87).
- **Modem.** On mainline, the remote processors are in pkgrel 15's
  series, but nothing above the modem's is written. The cameras, which
  this entry used to list, probe and stream (see "The cameras, first
  light"). Wi-Fi, Bluetooth and sound, which it also listed,
  now work in Phosh (see "The WLAN and Bluetooth in Phosh, and why
  neither worked", and the sound entries from "Sound, a stage at a time"
  on). Their firmware comes from the stock partitions. It is not
  redistributable, and firmware-sony-pdx246 packages it for this phone
  only.
- **What the cameras still lack.** All three stream through libcamera
  (see "All three cameras stream"), but only as raw Bayer debayered by
  the soft ISP.
  - The owner looked at all three in GNOME Snapshot on 2026-10-12: the
    two Hi-846s are too dark, and the IMX582 is a bit blurry.
  - Gain for the Hi-846s. Verified the same day
    (`out/try-kernel/live-hi846-dark.txt`, 20 s of each through `cam`):
    both reached their 33 ms limit and 16x, the most analogue gain the
    sensor has, and stayed under the AGC's target. The wide's histogram
    stayed in its lowest fifth and the front's mean bin was 1.58 against
    2.5. Their `digital_gain` sat at 512, 1x, as the soft IPA drives
    only exposure and analogue gain. Stock's sensor libraries add the
    sensor's digital gain on top, up to 8x on the wide and 16x on the
    front, for 128x in all (`out/dl-sensors/REPORT.md`), where the
    IMX582 reaches 60x on analogue gain alone.
  - Proof of focus. The AK7374 moves the IMX582's lens under the soft
    IPA's contrast autofocus (see "The main camera focuses, at 30 fps"),
    but nobody has seen it focus on a lit scene. Where the lens puts
    infinity and 10 cm is a guess: its whole range stands for them.
  - A quick start in the dark. The soft IPA's AGC raises the exposure by
    at most 6% per set of statistics, which come every fourth frame,
    because its error stops growing once every pixel is in the lowest
    bin. From a black frame to 60x gain took nine seconds, and the
    autofocus waits for it.
  - Flash in libcamera. The LED works through sysfs and as the
    IMX582's V4L2 flash (see "The rear flash LED lights"), but
    libcamera 0.7.2 ignores flash entities, so no app can fire it
    with a picture. Reasoned: Phosh's torch toggle looks for an LED
    named `*:torch*` or `*:flash*`, so `white:flash` should serve it,
    but nobody has tried it.
  - The OIS (a DW9784, with no mainline driver) and the modules'
    calibration data, which "What the vendor's camera module data
    holds" maps but nothing reads yet.
  - Tuning. The IMX582's colour matrices are another sensor's, and the
    Hi-846 file has none. Stock's Chromatix files for all three are
    decoded (see "What the vendor's tuning files hold"), and their
    colour matrices are ready to paste. Lens shading and a calibrated
    AWB need code in the soft IPA, and one `hi846.yaml` serves two
    Hi-846s whose stock tunings differ.
  - The IMX582's full 8000x6000 quad Bayer readout. The driver offers the
    binned modes only.
  - Sensor delays for the Hi-846, which libcamera has no values for.
  - Captures as root: the CMA heap is 16 MiB. pmOS's SDM845 kernel has
    256 MiB and the system heap; raising ours would follow it.
  - Upstream, with the owner's consent: the camss SM6450 series, the
    IMX582 driver and binding, the ET5907 support, the AK7374 support,
    the Hi-846 pixel rate fix (after v6 or its successor lands), and
    the libcamera patches: the IMX582's and Hi-846's helpers, the lens
    controls, the focus statistics, the autofocus and the line duration
    fix.
- **What sound still lacks.**
  - Speaker protection. Both amplifiers run 6 dB under stock's profiles
    because nothing watches the speakers' temperature or excursion.
    - Reasoned: stock does that on the ADSP; its amplifier nodes name
      ADSP ports and topologies (`aw-rx-topo-id`, `aw-tx-topo-id`) and a
      calibration mode.
  - A headset. The headphone path, the headset microphone and the
    buttons are described, but nothing has been plugged in.
  - A true capture volume scale. Since device pkgrel 12 the sound server
    drives each microphone's ADC, but the control claims 0.25 dB a step
    where a step measures 1.5 to 1.8 dB (see "The on-screen keyboard and
    the microphones' level"), so its decibel figures are wrong. The fix
    belongs in the WCD937x driver's TLV.
  - Recovery from an ADSP crash. The card does not come back on its own
    (see "Sound, a stage at a time").
- **No `soc-qcom-sm6450` package.** pmOS has no SoC package for this chip; the
  device package carries everything.
- **`pmb install` cannot finish inside a rootless container**, because
  partitioning and formatting go through a loop device.
  `scripts/make-rootfs-img.sh` works around it with `mkfs.ext4 -d` and produces
  a bare ext4 image instead of a partitioned one, so this is no longer a
  blocker. A failed `pmb install` does still leave a correctly sized, wholly
  empty `sony-pdx246.img` behind; `flash.sh` and `verify-bootimg.py` both
  refuse an image that holds neither a GPT nor an ext4 superblock.
- **Sony's board-level device tree, which nothing on disk has.** The device
  tree release carries Qualcomm's `parrot-atp`, `-idp` and `-qrd` reference
  boards but no pdx246 tree, so panel model, battery parameters and GPIO
  assignment are unknown. Three routes to it, in order of cost: turn on
  "Rooted debugging" and read the live tree plus `dtbo` over adb; dump `dtbo`
  from the bootloader; or decompile it out of a firmware download. The first is
  a toggle and a re-run of `scripts/device-collect.sh`.
- **Mainline now has an SoC tree, three PMICs and a board, and they build.**
  Twenty-three patches against v6.18.55 when this was written - twenty-seven
  as of pkgrel 12, which adds the display clock controller and the
  interconnect, and thirty-five as of pkgrel 13, which adds the display -
  in [../kernel/patches/](../kernel/patches/): `gcc-sm6450.c` and
  `pinctrl-sm6450.c`, the RPMh clock and power-domain tables, the PM6450
  regulator data, `sm6450.dtsi` at 1320 lines, `pm6450.dtsi`, and
  `sm6450-sony-xperia-columbia-pdx246.dts` with its 38 regulators, the keys,
  the SD card and USB. The two drivers were generated by a program whose correctness is
  proved on the ravelin/sm4450 pair and then checked register-by-register
  against the parrot sources; the device trees are cross-checked by
  `scripts/check-dt.py` against `/proc/device-tree` read off the running
  stock Android, where all 66 of our addresses are accounted for and 14 of
  the 15 nodes the two trees agree on the address of carry the same
  interrupts. Everything compiles at `W=1`, the dtbs build with
  `CHECK_DTBS=y`, all seventeen touched bindings pass `dt_binding_check`, and
  `checkpatch --strict` reports no errors across the twenty-three. That is
  **verified against sources** and nothing more - no mainline kernel has been
  built for this device, let alone booted. What is missing is narrower than it
  was: UFS and USB3, both blocked on the same thing - upstream wants a
  per-SoC PHY register table and Qualcomm did not release the PHY driver for
  this chip. (Wrong for UFS, as it turned out on 2026-10-08: see "The UFS PHY
  driver was in the tarball all along", and for USB3, whose init sequence
  the stock tree carries: see "The USB3 PHY is SM8350's".) Neither blocks a shell, because the rootfs is on the SD card and
  a USB network gadget only needs high speed.
  [06-mainline.md](06-mainline.md) has the method and the proofs.
- **The live device tree is a per-board ground truth, and it is already in
  the repo.** `out/device-dump-root/devicetree/` is the full
  `/proc/device-tree` captured from stock Android - 24241 entries, 27892
  lines once decompiled. It is the *resolved* tree: base DTB plus board
  overlay plus the bootloader's own fixups, for this exact phone. That makes
  it better evidence than either the vendor sources or the `parrot.dtb` in
  the `boot` partition, and it is what every mainline address claim is now
  checked against. Facts it settles, beyond the addresses: the UFS is 128 GB
  (`Ufs_id=300 Ufs_size=128` in the stock bootargs), `pm6450_l24` is the UFS
  vcc rail and carries no DT window because the PON sets it to 2.4 or 2.96 V
  depending on the UFS mode, and the stock console is
  `console=ttyMSM0,115200n8` with `stdout-path` on
  `/soc/qcom,qup_uart@98c000`. Verified, read directly off the device.
- **The interconnect is in a package since pkgrel 15.** Closed
  2026-10-08. Pkgrel 12 built the SM6450 NoC driver, generated from
  downstream's `parrot.c` by `scripts/icc-to-mainline.py` (see "The
  interconnect" above), but no package before 15 named a NoC in its
  tree. Rounds 30, 31 and 43 ran the nodes and the QUP, SD and USB
  paths, and pkgrel 15's series carries them. UFS, I2C9 and UART11 add
  their paths as WIP, and in round 49 UFS and I2C9 voted.
- **A mainline shell must not ask for fastboot.** This entry used to say
  there was no reboot-mode node. There is one, and it was always there:
  the board includes `pmk8350.dtsi`, whose `nvmem-reboot-mode` node has
  `mode-bootloader = <0x02>` in the SDAM restart reason. Using it is the
  PMIC write that is not authorised (see "Getting back to fastboot without
  touching the phone"), so `reboot bootloader` is never run. Even a working
  boot leaves only through a plain reset into the same slot, which walks
  the retry counter down one attempt at a time. The loop leaves a mainline
  boot the sanctioned way: `scripts/queue.sh` resets it over the gadget
  with sysrq until the counter runs out and the bootloader lands in
  fastboot.
  - Verified against `drivers/power/reset/reboot-mode.c`: a plain
    `reboot` goes through the reboot-mode driver too, but with no mode
    argument it looks up `mode-normal`, which the node lacks, and writes
    nothing.
- **The dwc3 node used the deprecated split binding.** Closed
  2026-10-08. `usb@a6f8800` with a `snps,dwc3` child was `qcom,dwc3`,
  which 6.18 handles in `dwc3-qcom-legacy.c`; new SoCs upstream use the
  flattened `qcom,snps-dwc3` form. Round 25 ran the flattened node, and
  pkgrel 15's series carries it.
- **USB does not survive the ADSP.** `pmic_glink`, UCSI and the
  battery manager work: round 57 read the battery and the charger and saw
  the Type-C port (see "Round 57"). The board's `pmic-glink` node is in
  pkgrel 18's series. But in rounds 37, 52 and 57, booting the
  ADSP took the USB link within 0.2 s, and nothing on our side has brought
  the host back. Until that changes, every round that boots the ADSP ends
  with the lease, unless something resets the PHY. Round 59 found that
  something: unbinding and binding the controller's driver, which takes
  the PHY through its reset and init again, brought the host back with
  the ADSP running. That is a recovery, not a fix. Round 60 showed that
  the PHY's reference gate goes only after the link has. Round 61 found
  the cause: the charger firmware's BC1.2 detection puts the PHY in UTMI
  non-driving mode and leaves it there. The vendor kernel recovers
  because it initialises the PHY each time it starts the peripheral.
  Round 61 also found that a runtime suspend collapses the USB GDSC and
  loses QSCRATCH. pkgrel 17 has a bring-up fix for the first and an
  upstream one for the second, and so does pkgrel 18. Round 62 showed
  both working, and round 63 again on the folded tree: the
  host has the gadget back 3.4 s after the ADSP comes up. What is still
  open is the upstream form of the first. Mainline dwc3 maps a `none`
  report to its default role, so none to device is not a mode change and
  nothing re-initialises the PHY. A form upstream could take is still
  to be found.

## Next steps, in order

The old list is spent. The probe and collector have run, both slots are backed
up by `dd` under `out/device-dump/stock/`, the rootfs is on the SD card, the
handoff into the stock second stage works, and **the port boots** - see "The
port boots" above. What is left starts from there.

1. **Get USB up on the mainline kernel.** Done, the part this item used to
   be about: with the APSS watchdog node gone the kernel reaches `/init` and
   runs the initramfs, see "Why the kernel resets". Rounds 18 and 19 then
   ran the real init, and nothing reached the host. Round 19 did not even
   fall back to stock, which the watchdog should have forced; "The real init
   on mainline" has why the gadget bind is the likeliest culprit and what
   now keeps it from silencing the logging. Round 20 then ran with the log
   hook writing to the SD card, and the card came back blank. Then the
   Gunyah watchdog probe showed our tree has no SCM node, which on its own
   keeps the SMMU, and so the dwc3 core and the SD card, from ever probing.
   Round 22, on the tree with SCM, had the SMMU and the card working, and
   USB waiting on a regulator block the board described wrongly. Round 23,
   on 2026-10-08, ran the real init on the corrected tree, unattended under
   `scripts/queue.sh`, and reached the pmOS debug shell over the USB network
   gadget. This item is done. "The real init on mainline" has the rounds.
   What follows is the history of getting this far.

   The boot itself was the open question for a while: it has happened twice. The first flash on 2026-10-06 was
   refused by ABL outright, and the second - after the dtbo and the board-id
   stamp were rewritten from ABL's own sources - was accepted, selected our
   device tree and handed our kernel the CPU. See "The second mainline flash"
   above. What it then did was reset about seven times and let the bootloader
   fall back to stock, silently.

   Silent is the hard part, and it is structural rather than bad luck. "Every
   output channel but one is closed" above works through it: DRAM is scrubbed
   by the bootloader so nothing RAM-backed survives a reset, the UART is not
   broken out, and the panel is command mode so the bootloader's live
   framebuffer cannot be driven as a console either. The only instrument is the
   USB gadget the initramfs brings up - which is in userspace, downstream of
   the failure. Until the kernel reaches `/init` there is nothing to read
   anywhere, so every round has to be reasoned into rather than measured.

   Four candidates have been bought and spent, and "Why the kernel resets"
   above has each one: the `late_initcall_sync` teardowns, the watchdog,
   initramfs decompression and the CPU idle states are all refuted, and so is
   the claim that the kernel reaches `/init`. What the rounds did establish is
   narrow but real - the kernel calls `panic()` outright, about 13 seconds
   after power-on including the bootloader, after `parse_args` and before
   anything in the initramfs runs.

   The instrument now is the device tree, because it is the half of the port
   that was written by hand and the only half that can be varied without a
   kernel rebuild, though with ccache warm that costs two minutes and not the
   63 this once said: `scripts/dt-reduce.py` builds a reduced tree and
   `try-kernel.sh` takes `DTB=path` to flash it. After that, `initcall_blacklist`
   disables a named driver from the cmdline with no rebuild at all. And if both
   run out, the fallback is the one this list named before any of them: a
   kernel patched to `emergency_restart()` - or simply to set `panic_timeout` -
   at a chosen point still ends in the same hands-free fallback, but each of
   the seven attempts then takes a length of time that depends on how far it
   got, and seven attempts multiply that difference into something measurable
   from the host. That is enough to bisect a blind boot, coarsely, one number
   at a time, without touching the phone.

2. **Let a hard hang reset itself.** Rounds 19 and 20 needed hands on the
   phone, because nothing resets a kernel that has stopped. The Gunyah
   watchdog was the plan, and it is closed: it registers, it only counts
   with cpuidle off, and wdtprobe5 says its bite stops the board instead of
   resetting it. See "The real init on mainline". What is left is the
   kernel's own: the soft- and hard-lockup detectors panic with
   `softlockup_panic=1 nmi_watchdog=panic`, and `panic=60` resets. That
   covers a kernel that is still taking timer interrupts on some CPU. A
   wedge that stops every CPU at once, such as a bus access that never
   completes, still needs the power key, which is why `cmds-r27.sh` reads
   nothing whose clock is off.
3. **Find where stock stage 1 wedges.** Still unknown, and now diagnosable:
   the watchdog arms on line 5 instead of line 35, so a hang becomes a reset
   loop that ends in Android with a flash log to read. The log hook arms right
   after `mount_proc_sys_dev`, so the presence or absence of a record is
   itself the answer - the hook waits for storage, the card or UFS, and
   downstream both only appear once stage 2 has let udev load the storage
   modules.
4. **Rebuild the kernel without `dummy_hcd`.** `# CONFIG_USB_DUMMY_HCD is not
   set` is already in `pmos.config` and needs a build to take effect. Not
   urgent: `deviceinfo_usb_network_udc` names the real controller, so the
   gadget cannot land on `dummy_udc.0` by accident any more. It does mean
   rebuilding the rootfs image too, because the modules live in it.
5. **Display on the mainline kernel, from in-tree drivers only.** Round 32
   bound all of it. Rounds 41, 42 and 47 found frames going out and the
   panel answering nothing. Round 48 found why: the panel's 1.8 V logic
   supply was switched with its GPIO the wrong way round. Fixed, the
   panel sends TE and answers a read, and round 51 has the same on
   pkgrel 15's tree (see "Round 48"). The nodes are in pkgrel 16's
   series, and round 55 has the same on its own tree. The panel lights:
   the owner saw the debug shell on it. What is left: touch tested on
   the screen; the panel differences taken to
   Marijn Suijten; and `deviceinfo_no_framebuffer` retired. Building Sony's out-of-tree `sm6450-modules`
   was the plan when the downstream kernel was the destination; it is not the
   plan now, because the mainline kernel exists to stop depending on Android
   vendor modules. It stays an option only for the downstream bring-up
   kernel, and only if that ever needs a screen.
6. **The remote processors, then their firmware.** Round 34 probed all
   four without firmware, plan n collected the firmware partition, and
   rounds 37, 52 and 57 booted the ADSP. Each time it took the USB link
   within 0.2 s, and the lease ended the round without anyone at the phone
   (see "Round 57"). Round 57 had `pmic_glink`, UCSI and the battery
   manager with `qrtr-smd` under them, and they all worked: the battery,
   the charger and the Type-C port read correctly. So the peer was not
   what the link was missing. Round 59 found a recovery: a re-probe of
   the controller and its PHY after the ADSP is up brings the host back,
   so a round can now boot the ADSP and keep its shell. Round 61 found
   the cause, the charger firmware leaving the PHY non-driving, and in
   round 62 pkgrel 17's bring-up fix brought the host back by itself.
   Round 63 ran it on the folded tree, which is pkgrel 18's own.
   Charging, audio, the modem and Wi-Fi all start here. Round 65 started
   the WPSS and brought `wlan0` up (see "Round 65").
7. **Small things the live system asked for.** Nothing sets the clock, so it
   comes up years out and `resize2fs` refuses while it is at the epoch; the
   image needs a sane fallback time. `nftables.service` and
   `systemd-firstboot.service` both fail benignly and should either be fixed
   or explained. The touchscreen polls but wants `focaltech_ts_fw_.bin` and a
   `drm_panel`, so it cannot work before display does. That is the vendor
   driver on the downstream kernel. Mainline's `edt-ft5x06` needs neither,
   and in round 36 it probed the chip (see "Round 36"). Touch works:
   the user tried it at the phone on 2026-10-11 (see "Touch works").
8. **The GPU, the DSPs and the sensors, then a system that boots.** The
   owner's order, given 2026-10-11, after much of the rest was left for
   them to try in passing on the first real boot:
   - the GPU, which round 67 takes up again (see "The GPU");
   - the ADSP's audio and sensor domains, and the CDSP, which still needs
     its `cdsp.mbn` pushed;
   - the sensors, which sit behind the ADSP and reach userspace through
     `hexagonrpcd` and libssc;
   - then a pmOS image that boots past the debug shell into Lomiri, with
     the firmware packaged. `postmarketos-ui-lomiri` is OpenRC only, so
     that image is an OpenRC one.

   Where that stands on 2026-10-11, at round 80. The GPU runs jobs on the
   kernel side, and the Mesa fork builds. The ADSP and the CDSP boot, and
   their FastRPC devices attach. The sensors work: 32 of them, read through
   libssc, as long as hexagonrpcd attaches within 25 s or so of the ADSP
   booting (rounds 78 to 81). The firmware is packaged. Device pkgrel 5
   starts hexagonrpcd at boot, and pkgrel 6 restarts the ADSP first if it
   has been up too long, which round 81 tried in the debug shell.

   Round 82 put the Lomiri image on the card and ran Mesa from it:
   freedreno reports FD710 with OpenGL 4.6 and ES 3.2. Round 83 booted it,
   on our own kernel, through OpenRC to Lomiri on the panel's output, with
   the sensors services started and sshd answering at 20 s. What is left
   here: a look at the screen, the sensors as Lomiri sees them, Bluetooth's
   firmware, and a clock.

   Where that stands on 2026-10-12, at round 94. The loop takes
   screenshots (round 87). Bluetooth's firmware is packaged and hci0 comes
   up (round 89). iio-sensor-proxy starts at boot and has all four sensors
   by 32 s (round 92). Lomiri boots at its own scale, a grid unit of 24, on
   the pmOS wallpaper (round 94), through our fork of
   postmarketos-ui-lomiri and device pkgrel 8. What is left here:
   - rotation in the session from boot: our qt5-qtsensors fork has the
     session claim the accelerometer and get readings (round 96), and what
     is left is to tilt the phone and watch the shell turn;
   - a clock, which needs an RTC driver that only reads;
   - and upstream, with the owner's consent: qtmir's rounding (rounds 92
     and 94), `GRID_UNIT_PX` and the wallpaper in postmarketos-ui-lomiri
     (pmaports issue 2411), iio-sensor-proxy for Lomiri, and the
     qtsensors claim (round 96).
