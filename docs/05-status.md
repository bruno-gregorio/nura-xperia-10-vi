# Status

Last updated: 2026-10-05. **The device has never been booted with any of
this.** Every claim below carries its confidence and the basis for it, because
that is the only thing standing between this port and a bricked phone.

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
  partition that mainline cannot see, having no UFS, and then loop in
  `fail_halt_boot`. Either way the init is alive and silent for ever, and
  nothing of ours resets it.

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
  rung of a six-rung ladder. 0 is the dwc3 glue (`usb@a6f8800`) unbound, 1
  the glue bound and the HS PHY not, 2 both bound but no UDC, which means
  the dwc3 core failed, 3 a UDC that configfs never bound the gadget to, 4 a
  bound gadget whose UDC is `not attached`, so no host saw it, and 5 one
  that got partway with a host.

  `MARKS="4 8"` on `try-kernel.sh` numbers 38 steps across both stages, with
  `debug_shell` as mark 24, eight seconds apart so the six rungs fit between
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

## The boot images

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
- **The card is written from the debug shell, over the cable** — Written and
  guarded, not yet run against the phone. `scripts/sdcard-install.sh` serves
  the image over HTTP bound to the USB address alone - not `0.0.0.0`, which
  would also publish it to the wireless network - and has the phone pull it
  straight into `dd`, staging nothing, since the image is larger than the
  phone's RAM. The write runs under `setsid` with its output in a file and is
  polled over short telnet connections, because `scripts/telnet.py` stops
  reading two seconds after its piped input ends and a dropped session would
  otherwise take `dd` with it. It refuses any target that is not
  `/dev/mmcblkN`, refuses a card smaller than the image, and does nothing at
  all without `--yes`.

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
- **The debug shell itself is still only Reasoned.** `pmos.debug-shell` is
  handled in `init_2nd.sh` before root is looked for, so it should not need a
  rootfs, but nothing has reached it yet.
- **The host side of the debug shell is ready and tested** — Verified. Fedora
  ships no `telnet`, `nc` or `socat`, and this project may not install onto the
  host, so `scripts/telnet.py` is the fallback: tested against a stub that
  opens the way busybox `telnetd` does (`IAC WILL ECHO`, `IAC WILL SGA`,
  `IAC DO NAWS`, an `SB`/`SE` subnegotiation, then a prompt), with the command
  bytes stripped from the display and the typed line arriving byte-exact.
  `scripts/console.sh` prefers a real client if one appears.
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
  port, so a framebuffer splash had nowhere to go in any case.
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

## Known gaps

- **Display.** On the mainline kernel this has to be in-tree: the msm DRM
  driver (MDSS, DPU, DSI and the DSI PHY for this SoC generation) and an
  upstream-style panel driver for the Samsung `fhd_amoled_cmd` panel, of the
  kind `linux-mdss-dsi-panel-driver-generator` produces from the downstream
  panel node. None of it exists for SM6450 yet. The downstream kernel's panel
  driver is in the out-of-tree `sm6450-modules` repository, which this port
  does not build and the mainline kernel will never use - not depending on
  Android vendor modules is the point of the mainline kernel. First boots are
  blind by design.
- **Vendor device trees that need `sm6450-modules`** (downstream kernel only).
  The same repository also
  owns the dt-bindings headers that Qualcomm's `audio/` and `camera/` device
  trees include, so those cannot be built here at all. We sidestep it by
  building only the base `parrot.dtb`, which is the one we boot; the rest of
  the parrot family is not ours. If `sm6450-modules` is ever built, the
  three-line `vendor/qcom/Makefile` written in `prepare()` is what to revisit.
- **GPU.** Adreno 710. On the downstream kernel it is KGSL, and Mesa's a7xx
  support targets the mainline `msm` uAPI, so expect software rendering there.
  On the mainline kernel it is drm/msm's GPU side, which already knows a7xx
  parts, plus the GMU and zap-shader firmware; that is the path that leads
  anywhere.
- **Modem, Wi-Fi, Bluetooth, audio, camera.** None attempted. Wi-Fi and audio
  additionally need firmware from the stock `/vendor/firmware`, which is not
  redistributable and is not packaged here.
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
- **Mainline now has an SoC tree, four PMICs and a board, and they build.**
  Twenty-three patches against v6.18.55 in
  [../kernel/patches/](../kernel/patches/): `gcc-sm6450.c` and
  `pinctrl-sm6450.c`, the RPMh clock and power-domain tables, the PM6450
  regulator data, `sm6450.dtsi` at 1320 lines, `pm6450.dtsi`, and
  `sm6450-sony-xperia-columbia-pdx246.dts` with all 45 regulators, the keys,
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
  this chip. Neither blocks a shell, because the rootfs is on the SD card and
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
- **No interconnect provider for SM6450.** `CONFIG_INTERCONNECT_QCOM=y` is
  set but there is no `sm6450` driver and `sm6450.dtsi` names no
  `interconnects`, so nothing votes bandwidth for any master. Stock's dwc3
  votes three paths (`usb-ddr`, `usb-ipa`, `ddr-usb`). Whatever ABL left in
  RPMh is all a mainline DMA master gets, which is enough until it is not;
  USB enumeration is the first thing that will lean on it. Downstream's
  `drivers/interconnect/qcom/parrot.c` (2502 lines) is the source, and the
  generator that produced the clock and pinctrl drivers is the way in.
- **No reboot-mode, so a mainline shell cannot ask for fastboot.** There is
  no PON node with `mode-bootloader` in `pm6450.dtsi` or the SoC tree, so
  even a working boot can only `reboot -f` into the same slot, which walks
  the retry counter down one attempt at a time. Worth adding as soon as the
  gadget works, because it is what makes a live mainline boot as cheap to
  leave as the downstream one.
- **The dwc3 node uses the deprecated split binding.** `usb@a6f8800` with a
  `snps,dwc3` child is `qcom,dwc3`, which 6.18 handles in
  `dwc3-qcom-legacy.c`; new SoCs upstream are expected to use the flattened
  `qcom,snps-dwc3` form. Not a bring-up problem, since both glues are built,
  but it has to change before the series goes to the lists.

## Next steps, in order

The old list is spent. The probe and collector have run, both slots are backed
up by `dd` under `out/device-dump/stock/`, the rootfs is on the SD card, the
handoff into the stock second stage works, and **the port boots** - see "The
port boots" above. What is left starts from there.

1. **Get USB up on the mainline kernel.** Done, the part this item used to
   be about: with the APSS watchdog node gone the kernel reaches `/init` and
   runs the initramfs, see "Why the kernel resets". Round 18 then ran the
   real init and nothing reached the host; "The real init on mainline" has
   why that says less than it first seemed to. The next round is the real
   init with `MARKS="4 8"`, `BOOTLOG=0` (the log hook needs UFS, which
   mainline does not have),
   `CMDLINE_ADD="nokaslr hardlockup_panic=1 softlockup_panic=1"` and
   `DTB=out/milestone/clkref.dtb`, and its total names the init step and the
   rung USB stopped on, in one go. What follows is
   the history of getting this far.

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

2. **Find where stock stage 1 wedges.** Still unknown, and now diagnosable:
   the watchdog arms on line 5 instead of line 35, so a hang becomes a reset
   loop that ends in Android with a flash log to read. The log hook arms right
   after `mount_proc_sys_dev`, so the presence or absence of a record is
   itself the answer - the hook waits for UFS, which only appears once stage 2
   has let udev load the storage modules.
3. **Rebuild the kernel without `dummy_hcd`.** `# CONFIG_USB_DUMMY_HCD is not
   set` is already in `pmos.config` and needs a build to take effect. Not
   urgent: `deviceinfo_usb_network_udc` names the real controller, so the
   gadget cannot land on `dummy_udc.0` by accident any more. It does mean
   rebuilding the rootfs image too, because the modules live in it.
4. **Display on the mainline kernel, from in-tree drivers only.** MDSS, DPU
   and DSI nodes in `sm6450.dtsi`, whatever DPU catalog entry and DSI PHY
   support SM6450 needs, and an upstream-style panel driver for the Samsung
   command-mode panel. It also retires `deviceinfo_no_framebuffer`. Building
   Sony's out-of-tree `sm6450-modules` was the plan when the downstream kernel
   was the destination; it is not the plan now, because the mainline kernel
   exists to stop depending on Android vendor modules. It stays an option only
   for the downstream bring-up kernel, and only if that ever needs a screen.
5. **Small things the live system asked for.** Nothing sets the clock, so it
   comes up years out and `resize2fs` refuses while it is at the epoch; the
   image needs a sane fallback time. `nftables.service` and
   `systemd-firstboot.service` both fail benignly and should either be fixed
   or explained. The touchscreen polls but wants `focaltech_ts_fw_.bin` and a
   `drm_panel`, so it cannot work before display does.
