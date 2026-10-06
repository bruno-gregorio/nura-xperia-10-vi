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
  could never happen. A round was left alone after the loop had given up, and
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
- **Sony also ships a second Parrot base we have no equivalent for** —
  Verified, consequence untested. Tree six is "Parrot 4Gb SoC", same `msm-id`
  but `board-id = <0x0 0x600>`. If this unit is the variant that wants the
  `0x600` subtype, stock has a tree for it and our `vendor_boot` offers only
  the `<0x0 0x0>` one.
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
- **Burning the bootloader's retry counter is the sanctioned route, and it is
  fast if you do not wait** — Verified. Our slot never marks itself booted, so
  every attempt decrements the counter; after enough of them the bootloader
  gives up and boots the stock slot, where adb is waiting. The probe's own
  patience is `sleep 600`, which makes a cycle eleven minutes - but resetting
  the moment telnet answers makes it about twenty-six seconds. Four resets took
  the phone from a probe shell to stock Android in two minutes.

## Known gaps

- **Display.** The panel driver is in the out-of-tree `sm6450-modules`
  repository, which this port does not build. First boots are blind by design.
- **Vendor device trees that need `sm6450-modules`.** The same repository also
  owns the dt-bindings headers that Qualcomm's `audio/` and `camera/` device
  trees include, so those cannot be built here at all. We sidestep it by
  building only the base `parrot.dtb`, which is the one we boot; the rest of
  the parrot family is not ours. If `sm6450-modules` is ever built, the
  three-line `vendor/qcom/Makefile` written in `prepare()` is what to revisit.
- **GPU.** Adreno 710 on a downstream KGSL kernel. Mesa's a7xx support targets
  the mainline `msm` uAPI. Expect software rendering, if anything.
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

## Next steps, in order

The old list is spent. The probe and collector have run, both slots are backed
up by `dd` under `out/device-dump/stock/`, the rootfs is on the SD card, the
handoff into the stock second stage works, and **the port boots** - see "The
port boots" above. What is left starts from there.

1. **Boot the mainline kernel.** Everything up to the boot is now done.
   Phase 1 is written and the whole series builds: `arm64` `defconfig` plus
   our three symbols produced `vmlinux` and `Image` with no warning on
   2026-10-06, and `nm` finds `gcc_sm6450_probe` at `subsys_initcall` and
   `sm6450_tlmm_probe` at `arch_initcall`, so the generated drivers really
   are linked and registered rather than merely compiling.
   `linux-postmarketos-qcom-sm6450` is the aport, built from a kernel.org
   6.18.55 tarball plus the squashed series, with a config derived from
   pmaports' sm6350 one. `device-sony-pdx246` now has `-kernel-downstream`
   and `-kernel-mainline` subpackages, so `pmbootstrap init` chooses which
   kernel to install and `deviceinfo_dtb` follows the choice. See "Building
   it" in [06-mainline.md](06-mainline.md).

   What is left is the apk build itself - the first time this code meets
   Alpine's clang rather than the container's gcc - and then a boot with the
   flash-log hook on it. UFS and USB3 wait on identifying their PHY
   generations; neither is needed for a shell, because the loop boots from
   the SD card and `sdhc_2` is written.

   The honest expectation for that boot is that it does not reach userspace.
   It is the first time a hand-written device tree for this SoC has been given
   to a kernel, and a wrong register offset in a clock controller produces a
   hang with nothing printed. That is what `earlycon=qcom_geni,mmio32,0x98c000`
   and `panic=5` in `kernel-cmdline.mainline.conf` are for, and why the
   experiment goes on the inactive slot.
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
4. **Build `sm6450-modules` for display.** The last thing, as before. It also
   retires `deviceinfo_no_framebuffer`.
5. **Small things the live system asked for.** Nothing sets the clock, so it
   comes up years out and `resize2fs` refuses while it is at the epoch; the
   image needs a sane fallback time. `nftables.service` and
   `systemd-firstboot.service` both fail benignly and should either be fixed
   or explained. The touchscreen polls but wants `focaltech_ts_fw_.bin` and a
   `drm_panel`, so it cannot work before display does.
