# Status

Last updated: 2026-10-05. **The device has never been booted with any of this.**

## Confidence levels

- **Verified** — read directly out of published sources, or confirmed on
  hardware by the LineageOS pdx246 port.
- **Reasoned** — follows from how the boot flow works, but nothing has
  exercised it.
- **Guess** — plausible, unconfirmed, and the first thing to suspect.

## Device facts

| Fact | Confidence | Basis |
|---|---|---|
| Codename `pdx246`, SoC SM6450, platform `parrot` | Verified | `BoardConfig.mk`, `sonyxperiadev/device-sony-pdx246` |
| SM6450 has no mainline support | Verified | No `sm6450.dtsi` and no parrot clk/pinctrl/interconnect driver in `torvalds/linux` master, re-checked 2026-10-05 |
| No SM6450 patches on the mailing lists | **Guess** | Was recorded as Verified from an earlier check. `lore.kernel.org` served an Anubis challenge on 2026-10-05, so this is stale and unconfirmed. Re-check before acting on it |
| Wi-Fi/BT part is **WCN3990** | Verified | Our overlay chain: `parrot-qrd-overlay.dts` -> `parrot-wcn3990.dtsi`. `wcn6750` appears only in `parrot-qrd-wcn6750*` board files, which stock does not use. Means ath10k/SNOC + `hci_qca`, both mature upstream |
| PMIC pair is `pm6450` (main) + `pm7250b` | Verified | `parrot-qrd-overlay.dts` includes `parrot-qrd-pm7250b.dtsi`; `pm6450` referenced in the QRD tree |
| Touchscreen comes from `blair-touch.dtsi` | Verified | `#include` in `parrot-qrd.dts`. Shared with Qualcomm's `blair` platform, not parrot-specific |
| Device runs Qualcomm's Parrot QRD reference DT | Verified | LineageOS port diffed built DTBs against stock blobs and booted it |
| Base `parrot.dtb` in `vendor_boot`, `parrot-qrd` overlay in `dtbo` | Verified | Qualcomm boot flow + LineageOS port notes |
| Boot header v4, pagesize 4096, kernel base 0 | Verified | `BoardConfig.mk` |
| AVB rollback index `1782864000` enforced in hardware | Verified | LineageOS port hit the red state and documented it |
| First-stage module list and order | Verified | `device/sony/pdx246/modules.load`, stock's own order |
| UFS 4096-byte logical blocks | Guess | Typical for the class; not confirmed for this device |
| Display 1080x2520 | Verified | Sony specs |
| Debug UART at `0x98c000`, `qcom,msm-geni-console`, `status = "ok"` | Verified | Decompiled our own `parrot.dtb` |
| `chosen/bootargs` already asks for `console=ttyMSM0,115200n8` | Verified | Same DTB; `stdout-path` points at the same node |
| ramoops at `0xffd00000`, 768K (256K console, 256K pmsg) | Verified | `ramoops_region@ffd00000`, compatible `"ramoops"`, no `no-map` |
| `qcom,msm-id = <0x219 0x10000 0x265 0x10000>`, `board-id = <0 0>` | Verified | Same DTB; this is what the bootloader matches `dtbo` against |
| `parrot-qrd-overlay.dtbo-base` lists `parrot.dtb` first | Verified | Vendor `dts/vendor/qcom/Makefile:143` |

## This port

| Item | Confidence | Notes |
|---|---|---|
| pmbootstrap runs rootless with the three patches | **Verified** | Native chroot builds; `pmb checksum` succeeds. Three, not two: `/dev` in a userns, `mount`/`umount` in a userns, and not unregistering a binfmt handler we did not register |
| Kernel aport layout (two tarballs, DT into `dts/vendor`) | **Verified** | `dts/Makefile` keys off `vendor/Makefile`, and the tree configures and compiles from it |
| Only `parrot.dtb` is built, not Qualcomm's whole DT release | **Verified** | `make dtbs` emits exactly one `DTC` line. The stock `audio/` and `camera/` trees cannot build at all without headers from the out-of-tree `sm6450-modules` repo |
| `pmos.config` survives `olddefconfig` intact | **Verified** | Every `=y`, `=n` and "is not set" in it was read back out of the generated `.config` |
| `earlycon` works with the serial driver left modular | **Verified** | `msm_geni_serial_earlycon.o` is built by `CONFIG_SERIAL_MSM_GENI_EARLY_CONSOLE`, which is a *bool*, so it is always in `vmlinux`; it carries `OF_EARLYCON_DECLARE(..., "qcom,msm-geni-console", ...)`, the compatible on the port in `parrot.dtb`. Building the GENI drivers in instead pulls IPC logging, then minidump, then SMEM — stock keeps that cluster modular on purpose |
| This tree expects an `O=` build; we build in tree | **Verified** | Qualcomm's 137 tracepoint headers use `TRACE_INCLUDE_PATH .` and need `-I$(srctree)/$(src)`, which `scripts/Makefile.lib` adds only `ifdef building_out_of_srctree`. `prepare()` drops that condition. Expect more in-tree assumptions of this shape |
| Kernel builds with Alpine clang | **Verified** | Builds clean in ~4 min: `boot/vmlinuz` 30,497,280 bytes, 294 modules, `kernel.release` `5.10.269-gki`. Needed `cc-wrapper` removed, `-Werror` stripped, a list of `-Wno-error=` flags, and the per-directory include path made unconditional |
| `pmos.config` satisfies `pmb kconfig check` | **Verified** | "kconfig check succeeded!" |
| boot-deploy's v4 path builds the images the way this port needs | **Verified** | boot-deploy 0.24.0 `generate_bootimg()`: for `header_version` 3 or 4 it calls `mkbootimg --header_version 4 --dtb "$_dtb" --kernel ... --vendor_ramdisk ... --vendor_cmdline "$(get_cmdline)" --vendor_boot "$_vendor_bootimg" -o "$_bootimg"`. So the DTB really goes into `vendor_boot.img`, and `android-tools` really is the right provider — that branch hardcodes `require_package "mkbootimg" "android-tools"` |
| `deviceinfo_kernel_cmdline` and `kernel-cmdline.d` are alternatives, not merged | **Verified** | `get_cmdline()` is `if [ -n "$deviceinfo_kernel_cmdline" ]; then _ret="$deviceinfo_kernel_cmdline ..."; else _ret="$(generate-kernel-cmdline)"; fi`. Setting the deviceinfo variable discards every drop-in, so this device keeps its whole cmdline in `kernel-cmdline.conf` |
| Both boot images are actually produced, and are internally correct | **Verified** | `verify-bootimg.py` on the real files: `boot.img` 30,502,912 bytes, `ANDROID!`, header v4, `kernel_size` 30,497,280 (exactly our `vmlinuz`), `ramdisk_size` 0 as v4 requires. `vendor_boot.img` 13,008,896 bytes, `VNDRBOOT`, header v4, `page_size` 4096, `vendor_ramdisk_size` 12,689,309, `dtb_size` 308,591 and that DTB byte-identical to the kernel apk's `parrot.dtb` |
| Load addresses match the board, not mkbootimg's defaults | **Verified** | `device/sony/columbia/PlatformConfig.mk` has `BOARD_KERNEL_BASE := 0x00000000`; mkbootimg defaults to `0x10000000` and boot-deploy's v4 branch passes no offsets, so the first build was 0x10000000 high on all four. With `deviceinfo_bootimg_custom_args="--base 0x00000000"` the header now reads `kernel_addr 0x00008000`, `ramdisk_addr 0x01000000`, `tags_addr 0x00000100`, `dtb_addr 0x01f00000`. Header v3+ keeps these in `vendor_boot`, and AOSP documents the bootloader as reading them from there |
| The cmdline drop-in reaches the image | **Verified** | Read back out of `vendor_boot.img`: `quiet splash plymouth.ignore-serial-consoles plymouth.prefer-fbcon console=ttyMSM0,115200n8 earlycon loglevel=7 printk.devkmsg=on pmos.debug-shell`. Our `50-` options all present and after `00-base.conf`'s `quiet`, so `loglevel=7` is the one that applies |
| `--split` is the wrong invocation for this device | **Verified** | pmbootstrap's `flashers` dict: the plain `fastboot` flasher's `flash_rootfs` is `fastboot flash $PARTITION_ROOTFS $IMAGE`, the *combined* image. Only `fastboot-bootpart` sets `"split": True` and uses the split images |
| The fastboot images come from the rootfs chroot's `/boot` | **Verified** | `flash_kernel` is `$BOOT/boot.img` and `flash_vendorboot` is `$BOOT/vendor_boot.img`, where `$BOOT` is that chroot. `home/pmos/rootfs/sony-pdx246-boot.img` is a boot *partition* filesystem, a different thing |
| The rootfs image is built, and the UUID chain is intact | **Verified** | `pmb install` cannot finish here (see below), so `scripts/make-rootfs-img.sh` builds it with `mkfs.ext4 -d`, which populates a filesystem from a directory tree without mounting it. Result: 1,020,264,448 bytes, bare ext4 (magic `0xef53`, no partition table), labelled `pmOS_root`, 249,088 blocks × 4,096 = exactly the file size, `e2fsck -fn` clean, `/sbin/init`, `/etc/fstab`, `/etc/apk/keys` and `/usr/lib/modules` all present, no pmbootstrap leftovers and `/dev` empty. `verify-bootimg.py` checks that the `pmos_root_uuid=` in the vendor_boot cmdline equals the filesystem's own UUID — the one thing that silently breaks if `/etc/fstab` is written after `mkinitfs` instead of before |
| `pmb install` itself cannot run in this container | **Verified** | Two independent blockers. `modprobe loop` needs privileges a rootless container has not got (cleared by running it on the host), and after that `losetup` still fails with `cannot find an unused loop device: Permission denied`: `/dev/loop-control` is `root:disk` 0660 and the container has no `/dev/loopN` nodes. Joining `disk` would grant raw access to every block device on the machine, so `make-rootfs-img.sh` sidesteps loop devices instead |
| The image's login password is known | **Verified** | `pmb install` sets it interactively, so an image built any other way inherits whatever an earlier run left in `/etc/shadow`. `make-rootfs-img.sh` sets it from `PMOS_PASSWORD`, default `147147`, and the hash read back out of the finished image verifies against that. `root` is `!` (locked), which is pmOS's normal arrangement |
| The initramfs carries everything the debug shell needs | **Verified** | 478 entries; all 89 `modules-initfs` names present as `.ko`; `usr/bin/busybox`, `usr/bin/busybox-extras` (which is where the `telnetd` applet lives), `usr/bin/unudhcpd`, `init` and `init_functions.sh` all in. `init` runs `busybox --install -s` and `busybox-extras --install -s`, which is what makes the bare `telnetd` call in `init_functions.sh` resolve |
| `initramfs.load` is `modules-initfs`, order intact | **Verified** | The file installed at `usr/lib/modules/initramfs.load` is ours verbatim; the 89 module names match exactly, in stock's dependency order |
| RAM boot reaches the debug shell with no rootfs | Reasoned | `pmos.debug-shell` is handled in `init_2nd.sh` before root is looked for, and `boot_gki` (`fastboot stage vendor_boot.img` then `fastboot boot boot.img`) stages the v4 ramdisk correctly. Untested, and some Qualcomm bootloaders refuse `fastboot boot` outright |
| `deviceinfo_dtb="vendor/qcom/parrot"` resolves | **Verified** | boot-deploy's `find_dtb` runs `find /boot -path "/boot/dtbs*/$_filename.dtb"`, and the package really contains `boot/dtbs/vendor/qcom/parrot.dtb` (308,591 bytes) |
| Leaving stock `dtbo` in place gives the right DT | Reasoned | This is what stock does; untested with *our* base |
| Every name in `modules-initfs` was really built | **Verified** | `verify-build.sh` against the real package: all 89 present among the 294 `.ko` files. 89, not 90 — `dm-mod` is builtin because pmOS wants `CONFIG_BLK_DEV_DM=y`; the other 89 are stock's list unmodified |
| USB module names (`dwc3-msm`, `phy-msm-*`) | Verified | `drivers/usb/{dwc3,phy}/Makefile`: `CONFIG_USB_DWC3_MSM` -> `dwc3-msm.o`, `CONFIG_MSM_HSUSB_PHY` -> `phy-msm-snps-hs.o`, `CONFIG_USB_MSM_SSPHY_QMP` -> `phy-msm-ssusb-qmp.o`. `parrot_GKI.config` enables only these two PHYs (no eUSB2, no QUSB) |
| Every kernel-side prerequisite for the USB gadget is present | **Verified** | `USB_DWC3=y` with `USB_DWC3_DUAL_ROLE=y` (not host-only), and `USB_CONFIGFS_{ACM,NCM,RNDIS,MASS_STORAGE}` all `=y`. The glue (`dwc3-msm`) and the two PHYs are modules and are in `modules-initfs` |
| USB gadget actually enumerates on the device | Guess | Config is necessary, not sufficient. The likely failure is Type-C role detection: `TYPEC_QCOM_PMIC` is not set, so the gadget depends on the PMIC/charger driver reporting over extcon |
| `pmos.debug-shell` gives telnet on `172.16.42.1:23` and a CDC-ACM port | Verified | `postmarketos-initramfs/init_functions.sh`: `telnetd -b "${HOST_IP}:23"`, `acm.usb0`, `ncm.usb0` with `rndis.usb0` fallback |
| Flashing procedure in `04-flashing.md` | Reasoned | Derived from AVB behaviour; **not executed** |
| Boot images fit their partitions | **Verified** | `BOARD_BOOTIMAGE_PARTITION_SIZE` and `BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE` are both `0x06000000` (96 MiB); ours are 30.5 MiB and 13.0 MiB |

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
- **Mainline is not attempted, and the reason is ordering, not difficulty.**
  Every per-SoC driver exists as GPL source in the tarballs the kernel aport
  already downloads, and the sibling SoC SM4450 is upstream and derived from
  the same vendor code. What is missing is a console on the real device to
  debug against. [06-mainline.md](06-mainline.md) has the inventory and a
  phased plan.

## Next steps, in order

1. **`scripts/flash.sh ramboot`.** Needs the bootloader unlocked and nothing
   else — no backups, no rootfs image, no partition written. It answers the
   only question that matters right now, and there is nothing to undo if the
   answer is no.
2. Take the backups in [04-flashing.md](04-flashing.md) step 1, for both slots.
   Do this before anything is flashed, not before the RAM boot.
3. Look for a USB gadget. That single observation splits the problem in half:
   if it appears, the kernel booted and the work moves to userspace; if not,
   read ramoops.
4. Read `/sys/fs/pstore/console-ramoops*` after the next boot. The cheapest
   instrument available and it needs no cable: the region is reserved in the
   DTB we build, `PSTORE_RAM` is builtin, and 256K of console ring survives a
   reboot. Serial on `0x98c000` is the fallback and needs physical access to
   the USB-C SBU pins that nobody has yet.
5. Flash the rootfs and try a real boot, once steps 1-4 say the kernel runs.
   The image exists and verifies; what is untested is whether the initramfs
   finds and mounts it on the device. Steps 1-4 do not depend on it.
6. Only then: build `sm6450-modules` for display.
