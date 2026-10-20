# postmarketOS for the Sony Xperia 10 VI (pdx246)

A postmarketOS port to the Sony Xperia 10 VI that runs mainline Linux. Upstream
Linux has no support for its SoC, the Qualcomm SM6450. This port supplies it:
106 patches written as a series for the mailing lists. On them the phone boots
into Plasma Mobile from its SD card, with display, touch, GPU, Wi-Fi,
Bluetooth, sound, sensors, all three cameras, the fingerprint reader and SMS
working.

This repository is the reference for the upstream submissions. Every patch is
here, one file per commit. [docs/05-status.md](docs/05-status.md) holds the
dated evidence behind each claim, labelled as verified, reasoned or guessed.
[docs/08-upstream.md](docs/08-upstream.md) has the submission plan this README
summarises. All of it has been tested on one unit, the owner's. Status as of
2026-10-20.

## The device

What this port targets, in the terms the rest of the docs use.

- **Device** — Sony Xperia 10 VI, `XQ-ES54` / `XQ-ES72`
- **Codename** — `pdx246`, Sony platform `columbia`
- **SoC** — Qualcomm SM6450, Snapdragon 6 Gen 1, Qualcomm codename `parrot`
- **GPU** — Adreno 710
- **Display** — 6.1" OLED, 1080x2520, Samsung SOFEF01-M driver IC
- **Kernel** — v6.18.55 with this port's SM6450 series. Sony's downstream
  5.10 is kept as a reference only.
- **pmOS device** — `sony-pdx246`

## What works

Seen working on the owner's unit unless the entry says otherwise, on kernel
package r51. [docs/05-status.md](docs/05-status.md) has a dated entry for
each.

- **Boot** — the kernel boots from the phone's spare A/B slot, with the root
  filesystem on the SD card. It runs Plasma Mobile on systemd, or Lomiri on
  OpenRC.
- **Display** — the panel through drm/msm's DPU and DSI, with Marijn
  Suijten's SOFEF01 panel driver, which is posted upstream but not merged.
  Plasma Mobile and Lomiri render on it.
- **Touch** — the FocalTech FT3519T through `edt-ft5x06`. A double tap
  wakes the screen with the panel off. Waking from suspend that way is
  untested.
- **GPU** — the Adreno 710 through drm/msm and Mesa's freedreno, which
  reports OpenGL 4.6 and ES 3.2. kmscube runs at the panel's 60 Hz.
- **Storage and USB** — UFS, the SD card, and USB at high speed as a
  peripheral. The phone's port is USB 2.0.
- **Wi-Fi and Bluetooth** — the WCN3991, through `ath10k_snoc` on the WPSS
  and through `hci_qca`.
- **Sound** — both speakers, through two Awinic AW88263 amplifiers, and the
  microphones. The amplifiers run 6 dB under stock's level, because nothing
  protects the speakers yet. The headset is untested.
- **Sensors** — 32 sensors on the ADSP, through hexagonrpcd and libssc.
  iio-sensor-proxy has all four of its sensors.
- **Modem** — it registers with a SIM and receives SMS. Mobile data is
  untested, because the network refuses this SIM data. GNSS
  does not start, and calls have not been tried.
- **Cameras** — the IMX582 main camera and both Hi-846s stream through
  libcamera's software ISP. The main camera autofocuses through its AK7374
  and has its flash LED. Colour tuning is partial.
- **Fingerprint** — enrollment and verification through the sensor's
  TrustZone application. Unlocking the lock screen with it is untested.
- **Battery** — battery and charger readings, and the Type-C port, through
  `pmic_glink`.
- **Suspend** — the phone enters deep suspend and resumes.
- **Not yet** — a permanent install (see
  [Living with it](#living-with-it)), call audio, GNSS, and the image
  stabiliser.

## Upstream status

Nothing of this port's own has been posted yet. The first postings wait for
three things:
- 7.4-rc1, due around 2026-11-01;
- the maintainers' answer on what the SoC is called, because recent
  Qualcomm SoCs take die codenames in their compatibles;
- the rework [docs/08-upstream.md](docs/08-upstream.md) lists.

The targets below are plans. Each is the release whose merge window a series
aims at, assuming two review rounds. At the usual nine to ten weeks a
release, 7.5's merge window opens around the turn of the year, 7.6's around
March 2027 and 7.7's around May 2027 (reasoned from the cadence).

Kernel patch numbers are positions in [kernel/patches/](kernel/patches/),
whose `SERIES` file gives the subjects. "Bring-up" numbers are positions in
[kernel/bringup/](kernel/bringup/).

✅ merged · ⬜ not posted yet · ↪ someone else's posting covers it · ✖ not
for upstream as is

### The kernel

| | Series | Patches | Goes through | State | Target |
|---|---|---|---|---|---|
| ⬜ | Qualcomm flash LED fixes | 0094–0095 | leds | Ready | 7.4, as fixes |
| ⬜ | `edt-ft5x06`: release contacts missing from a frame | 0098 | input | Ready | 7.4, as fixes |
| ⬜ | AK7374 lens driver | 0091–0092 | media | Ready | 7.5 |
| ⬜ | Awinic AW88263 amplifier | 0062–0063 | ASoC | Ready | 7.5 |
| ⬜ | WL2868C and ET5907 camera PMIC | 0073–0074, 0079–0080 | regulator | Fold into one driver | 7.5 |
| ⬜ | Sony IMX582 sensor | 0076–0077 | media | Ready | 7.5 |
| ⬜ | SM6450 global clocks | 0002–0003 | clk | Name to settle | 7.5 |
| ⬜ | SM6450 pin controller | 0006–0007 | pinctrl | Name to settle | 7.5 |
| ⬜ | RPMh clocks and power domains, PM6450 regulators | 0008–0011, 0016–0018 | clk, pmdomain, regulator | Name to settle | 7.5 |
| ⬜ | SM6450 interconnect | 0012–0013 | interconnect | Name to settle | 7.5 |
| ⬜ | One-line compatibles, pd-mapper | 0014–0015, 0019–0023, 0025–0026, 0034 | each subsystem | Name to settle | 7.5 |
| ⬜ | SM6450 base tree and the Xperia 10 VI | 0024, 0049–0051 | qcom arm64 | Split 0049 by wave | 7.6 |
| ⬜ | UFS | 0027–0030 | phy, crypto, scsi | Ready | 7.6 |
| ⬜ | Remote processors, WLAN, charger, rmtfs | 0031–0033, 0035, 0055, 0101 | remoteproc, soc | Ready | 7.6 |
| ⬜ | IPA, the modem's data path | 0102–0106 | net-next | Data path untested | 7.6 |
| ⬜ | Display: clocks, MDSS, DPU, DSI, UBWC | 0004–0005, 0038–0045 | clk, drm/msm, soc | Ready | 7.6 |
| ⬜ | GPU: clocks and the Adreno 710 | 0036–0037, 0046–0048 | clk, drm/msm, iommu | Firmware not in linux-firmware | 7.6 |
| ⬜ | Audio | 0056–0061, 0064–0067 | ASoC, pinctrl, dma | Ready | 7.6 |
| ⬜ | `edt-ft5x06` double tap to wake | 0099–0100 | input | RFC first | 7.6 |
| ⬜ | Camera: clocks, CCI, CAMSS | 0068–0072, 0082–0089 | clk, i2c, media, phy | Rework for the CSI2 PHY API | 7.7 |
| ⬜ | The board's cameras, lens and flash | 0075, 0078, 0081, 0093, 0096–0097 | qcom arm64 | After the camera series | 7.7 |
| ⬜ | Hi-846 pixel rate | 0090 | media | After Pengyu Luo's series | After it |
| ⬜ | SOFEF01 `vci-supply` and the 10 VI's FLM setting | 0001, bring-up 0003 | via Marijn Suijten | With his driver | With it |
| ↪ | SMP2P sleepstate | 0052–0054 | soc | Richard Acayan's binding covers it | — |
| ↪ | Rust IRQ handlers under KCFI | bring-up 0004 | rust | Sami Tolvanen's fix covers it | — |
| ↪ | Rust GPIO consumer | bring-up 0006 | rust | Kohei Ito's posting overlaps it | — |
| ⬜ | USB3 and DisplayPort combo PHY | [kernel/wip/sm6450-usb3](kernel/wip/sm6450-usb3/) | phy | Untestable here: the port is USB 2.0 | — |
| ✖ | Bootloader ids, HS PHY re-init, QSEECOM TEE, egisfp, Rust pinctrl, Hi-846 stock programs | bring-up 0001–0002, 0005, 0007–0009 | — | Each patch says why | — |

### Userland and packaging

| | Change | Goes to | State | When |
|---|---|---|---|---|
| ✅ | Adreno 710 in freedreno (Hugo223's, not ours) | Mesa | Merged 2026-09-23 | Mesa 26.3.0 |
| ⬜ | Rootless chroot and binfmt fixes | pmbootstrap | Needs commit messages and a sign-off | Now |
| ⬜ | Claim the accelerometer before iio-sensor-proxy has one | Qt (qtsensors) | Ready | Now |
| ⬜ | QSEE time listener (listener 11) | qsee-supplicant | Ready | Now |
| ⬜ | Line duration at configure time, Hi-846 helper | libcamera | Ready | Now |
| ⬜ | Simple pipeline: preview aspect ratio, 3A state | libcamera | Needs commit messages | Now |
| ⬜ | `GRID_UNIT_PX` and the wallpaper | pmaports (postmarketos-ui-lomiri) | Ready | Now |
| ⬜ | Soft IPA exposure: VBLANK, longer frames, digital gain | libcamera | Needs splitting | After review |
| ⬜ | Soft IPA contrast autofocus and lens controls | libcamera | Coordinate with two other focus efforts | After review |
| ⬜ | IMX582 helper | libcamera | Merge with j4niwzis's series | With the IMX582 driver |
| ⬜ | Lens shading, AWB, denoise, preview shaders | libcamera | Needs splitting and a rebase | After quad-Bayer support lands |
| ⬜ | Responsive preview | plasma-camera | Needs splitting | After review |
| ⬜ | UCM files and AudioReach topology | alsa-ucm-conf, audioreach-topology | Ready | After the kernel's audio |
| ⬜ | Sony's modem QMI services | its own repository, then pmaports | Needs a repository | After publishing |
| ⬜ | Device, kernel and firmware packages | pmaports | Flashing flow to fix; coordinate with Marijn Suijten | After both |
| ✖ | Egis EC617 driver | libfprint | Depends on the out-of-tree TEE and egisfp | — |

### What this port takes from others

Postings the port carries as [backports](kernel/backports/) until it is
rebased.

| | Change | Author | Upstream |
|---|---|---|---|
| ✅ | IPA's IMEM slice from DT | Konrad Dybcio | 7.1 |
| ✅ | IPA v5.2 | Luca Weiss | 7.1 |
| ✅ | FocalTech FT3518, and FT3519 as its fallback | Yedaya Katsman, Bhushan Shah | 7.0, 7.1 |
| ✅ | `cx_misc_mmio` without LLCC | Alexander Koskovich | 7.2 |
| ✅ | SOFEF01-M binding | Marijn Suijten | 7.2 |
| ✅ | MI2S clock control | Mohammad Rafi Shaik | 7.3 |
| ✅ | Validate the CPU DAI id while parsing | Srinivas Kandagatla | In mainline |
| ⬜ | SOFEF01 panel driver | Marijn Suijten | v2, 2025-12-22 |
| ⬜ | Hi-846 link frequencies and modes | Pengyu Luo | v6, 2026-08-30, changes requested |
| ⬜ | Quad-Bayer CFA in libcamera's software ISP | Frederic Laing | v1, 2026-08-25 |

## Installing on your own Xperia 10 VI

This is how the owner's phone runs the port, written out for a second one.
It has never been done on a second unit, and the parts that a second unit
would hit first are listed under
[What a second phone hits](#what-a-second-phone-hits).

### Before you start

These follow from the phone, not from this port.

- **Unlocking wipes the phone and destroys Sony's DRM keys** — relocking does
  not bring them back, and camera processing and some DRM playback stay
  degraded even back on stock. This project has not run the unlock itself:
  the owner's unit came already unlocked.
- **Anti-rollback is enforced in hardware** — a `vbmeta` with a lower
  rollback index than the phone has stored puts it in the AVB red state,
  whatever its flags say. The tools here only ever flash the stock slot's
  own `vbmeta` with verification turned off, to the other slot.
- **Your Android stays where it is** — the port goes on the spare A/B slot
  and the SD card. Nothing here writes the stock slot, `super`, `userdata`,
  the bootloader chain or the partition table.
- **Nothing is permanent yet** — every boot of the port spends one of the
  bootloader's seven attempts, and after the last one the phone boots stock
  again. See [Living with it](#living-with-it).

### What you need

- **An Xperia 10 VI with an unlockable bootloader**
- **An Android that boots on one slot and has marked it successful** — the
  fallback every boot of the port lands back on. The owner's unit runs
  Johannes Meyer zum Alten Borgloh's unofficial LineageOS 23.2.
- **A recovery with root adb** — LineageOS recovery or TWRP. The backup and
  the firmware are read from it.
- **An SD card of 32 GB or more** — the root filesystem takes the first
  16 GiB. A raw region past 32 GiB holds the boot log, but only on a card of
  the owner's exact size until
  [that is generalised](#what-a-second-phone-hits).
- **A Linux host** with distrobox and with `qemu-aarch64` registered in
  binfmt_misc, which Fedora's `qemu-user-static` does. adb and fastboot go
  on the host itself, because the container cannot claim the phone's USB
  interfaces. Nothing else is installed on the host.
- **The host's side of the USB network** — an address on `172.16.42.0/24`
  for the phone's gadget. `scripts/console.sh` prints the commands.

### Steps

Each step links to the document that has its detail.

1. **Read the phone** — with Android up and USB debugging on. It is
   read-only and needs no root: it confirms a `pdx246` on `parrot` and
   reports the active slot.

   ```sh
   scripts/device-probe.sh
   ```

2. **Unlock** — Sony's procedure. Turn on OEM unlocking in Developer
   options, and get the code from
   <https://developer.sony.com/open-devices/unlock-bootloader> with the
   IMEI from `*#06#`. Keep the IMEI out of this repository.

   ```sh
   adb reboot bootloader
   fastboot oem unlock 0x<YOUR_CODE>
   ```

3. **Set up the build container** — this creates a Debian container,
   provisions it with pmbootstrap pinned to 3.11.1, and initialises the
   work directory. Accept `pmb init`'s defaults: the config selects
   `sony-pdx246`, the mainline kernel, systemd and Plasma Mobile.
   [docs/03-build.md](docs/03-build.md) has the detail.

   ```sh
   distrobox create --name pmport --image docker.io/library/debian:trixie --yes
   distrobox enter pmport -- ./scripts/bootstrap.sh
   distrobox enter pmport -- ./scripts/pmb init
   ```

4. **Back up both slots** — from recovery. This reads `boot`, `vendor_boot`,
   `dtbo`, `vbmeta` and `vbmeta_system` of both slots into `out/`, which git
   ignores. It writes nothing on the phone.

   ```sh
   adb reboot recovery
   OUT=out/device-dump-root scripts/device-collect.sh
   ```

5. **Collect your phone's firmware** — none of it may be redistributed, so
   every phone supplies its own. It all goes under `out/`. In recovery, set
   `SLOT` to the slot recovery booted from, then read the `modem`, `vendor`
   and `persist` contents:

   ```sh
   SLOT=b
   scripts/collect-firmware.sh      # DSPs, modem, WPSS, IPA, the Egis app
   scripts/collect-hexagonfs.sh     # sensor registry and socinfo
   adb exec-out "dd if=/dev/block/mapper/vendor_$SLOT bs=1048576" \
       > "out/firmware/vendor_$SLOT.img"
   ```

   Then unpack what the package builds from, inside the container. The
   ledger never recorded where in the `modem` partition the split images
   and the WLAN board data sit, so `find` locates them.

   ```sh
   distrobox enter pmport -- sh -c '
   S='"$SLOT"'; V=out/firmware/vendor_$S.img; M=out/firmware/modem_$S
   mkdir -p out/firmware/gpu out/firmware/audio out/firmware/mbn \
       out/hexagonfs/stage/sensors out/tools/ath10k
   for f in a710_sqe.fw gmu_gen70000.bin a710_zap.mbn; do
       debugfs -R "dump /firmware/$f out/firmware/gpu/$f" "$V"; done
   for f in aw88261_acf.bin aw88263_acf.bin; do
       debugfs -R "dump /firmware/$f out/firmware/audio/$f" "$V"; done
   debugfs -R "rdump /etc/sensors/config out/hexagonfs/stage/sensors" "$V"
   debugfs -R "dump /etc/sensors/sns_reg_config out/hexagonfs/stage/sensors/sns_reg_config" "$V"
   for p in adsp cdsp modem wpss ipa_fws; do
       python3 scripts/pil-squash.py "$(find "$M" -name "$p.mdt")" "out/firmware/mbn/$p.mbn"; done
   python3 scripts/ath10k-board2.py out/tools/ath10k/board-2-pdx246.bin \
       "$(dirname "$(find "$M" -name bdwlan.bin)")"
   [ "$S" = b ] || ln -sfn "modem_$S" out/firmware/modem_b
   ./scripts/stage-firmware.sh'
   ```

   `stage-firmware.sh` reads `modem_b` by name, which the last line works
   around on a phone whose stock slot is a.

6. **Build** — `pmb install` builds every package and the boot images, and
   then stops at the loop-device step, as it always does in a rootless
   container. `make-rootfs-img.sh` finishes the job. Choose your own
   password; the default is `147147`.

   ```sh
   distrobox enter pmport -- ./scripts/sync-aports.sh
   distrobox enter pmport -- ./scripts/pmb install --no-fde
   distrobox enter pmport -- env PMOS_PASSWORD='<yours>' ./scripts/make-rootfs-img.sh
   python3 scripts/verify-bootimg.py
   ```

7. **Write the root filesystem to the card** — the first command flashes
   the spare slot and stops in the initramfs, with a shell over USB. The
   second looks at the card and changes nothing. The third partitions the
   card and writes the image over the cable, so the card never comes out.
   [docs/04-flashing.md](docs/04-flashing.md) has the detail.

   ```sh
   scripts/try-kernel.sh
   scripts/sdcard-install.sh
   scripts/sdcard-install.sh --yes
   ```

8. **Boot the system** — back to fastboot, then the whole system. sshd
   answers about 20 s after the gadget appears, and Plasma Mobile comes up
   on the panel. Log in as `user` with your password.

   ```sh
   scripts/to-fastboot.sh
   STAYUP=1 scripts/try-kernel.sh
   scripts/ssh.py 'uname -a'
   ```

### Living with it

- **Every boot is borrowed** — nothing marks the port's slot successful. So
  each boot, a reboot from the shell included, spends one of seven attempts.
  After the last one, the phone boots stock. `fastboot --set-active=<slot>`
  resets the count.
- **Back to Android** — `scripts/try-kernel.sh --restore` writes stock's
  images back to the spare slot and makes the stock slot active.
- **When something goes wrong** — [docs/04-flashing.md](docs/04-flashing.md)
  covers panics, hangs, the red state and reading the boot log.

### What a second phone hits

These are known gaps between the owner's unit and anyone else's, not yet
fixed.

- **The front and ultra-wide cameras' programs** — the firmware package
  wants the stock Hi-846 sensor programs. `scripts/hi846-firmware.py` packs
  them from JSON decoded out of the camera libraries, by tools that were in
  the owner's lost `out/` and are not in this repository. Without that JSON,
  `stage-firmware.sh` stops at that step, before it copies the Egis app, and
  the package does not build. Until the tools are back, skip that line of
  `stage-firmware.sh` and drop `firmware-sony-pdx246-cameras` and the six
  `hi846-*.bin` sources locally. That should leave everything else working,
  without those two cameras (reasoned).
- **The camera tuning** — `pdx246-camera-calibration` builds from tuning
  files decoded out of the phone's own Chromatix files. They are Sony's, so
  git keeps them out, and the decoder is not in this repository either.
  Until it is, drop that package from the device package's dependencies
  locally. libcamera then runs the cameras on its generic tuning
  (reasoned).
- **The boot log** — `CARD_SECTORS` in `scripts/bootlog.py` is the owner's
  card's size. On any other card the root filesystem works, but a failed
  boot leaves no log on the card until the value is changed.
- **The unlock and stock Android as the fallback** — the owner's unit came
  unlocked and running LineageOS. Neither the unlock nor a stock Sony
  Android as the fallback has been tried here.
- **The firmware step** — three of its lines are workarounds: the `find`
  calls and the `modem_b` link. One collection script should replace
  them.

## How the kernel is organised

The mainline kernel is three layers, each a branch in the kernel tree, which
is gitignored at `out/linux`, and a directory here.

- **[kernel/backports/](kernel/backports/)** — upstream commits and postings
  that v6.18.55 predates, under their original authors.
- **[kernel/patches/](kernel/patches/)** — the SM6450 series meant for
  upstream, one patch per commit.
- **[kernel/bringup/](kernel/bringup/)** — what the device needs that is not
  for upstream as is. Each commit message says why.
- **[kernel/wip/](kernel/wip/)** — topic branches not yet folded into the
  series.

The kernel package
[linux-postmarketos-qcom-sm6450](aports/device/testing/linux-postmarketos-qcom-sm6450/)
builds a kernel.org tarball plus one squashed patch per layer, which
`scripts/sync-kernel-patches.sh` generates.

Sony's 5.10 kernel,
[linux-sony-pdx246](aports/device/testing/linux-sony-pdx246/), booted
first. It is kept as a reference for how the hardware behaves under the
vendor's own drivers, and nothing new is built on it.

## Layout

Everything the build touches lives under this directory. Nothing is written to
`$HOME` or to the host.

```
aports/device/testing/   the device, kernel and firmware packages
aports/main/             new packages of this port's own
aports/temp/             forks of upstream packages, until upstream catches up
kernel/                  the kernel's three layers and its WIP branches, as patches
patches/                 fixes pmbootstrap needs to run rootless
scripts/                 setup, the pmbootstrap wrapper, collection, flashing, checks
docs/                    device facts, design, build, flashing, status, upstreaming
out/                     (gitignored) the kernel tree, dumps, firmware, logs
.pmb/                    (gitignored) pmbootstrap, pmaports, chroots, caches
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
- **[docs/08-upstream.md](docs/08-upstream.md)** — what goes upstream, what
  others must land first, and the order to submit it in.
- **[docs/guidelines.md](docs/guidelines.md)** — the entity framework every
  document here is written to.

## Credit

Nearly every hard fact about this device — the boot image geometry, the module
load order, and above all that pdx246 runs Qualcomm's Parrot QRD reference
device tree rather than a Sony board tree — comes from Johannes Meyer zum Alten
Borgloh's unofficial LineageOS 23.2 port, which is thoroughly documented and
was verified on real hardware.

<https://github.com/johanneszab/lineageos-pdx246-releases>
