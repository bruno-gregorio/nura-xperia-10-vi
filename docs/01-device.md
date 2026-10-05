# Device facts

Everything below is read out of Sony's published sources or taken from the
LineageOS pdx246 port, which verified it on hardware; nothing here was inferred
from the device by this project, which has never run on one.

## Identity

The two models are the same hardware, and the codenames matter because
different layers of the stack use different ones.

- **Marketing name** — Sony Xperia 10 VI
- **Models** — `XQ-ES54` (EEA) and `XQ-ES72` (HK/TW/SG/MY/TH/VN/MO). Comparing
  Sony's `70.2.A.4.168` firmware for each, 3207 of 3208 blobs are
  byte-identical; the single difference is the NFC RF tuning table, which the
  NFC HAL picks at runtime from
  `/sys/devices/platform/HardwareInfo/modem_id`.
- **Sony codename** — `pdx246`, platform `columbia`
- **SoC** — Qualcomm SM6450, "Snapdragon 6 Gen 1"
- **Qualcomm codename** — `parrot`, as `TARGET_BOARD_PLATFORM` and
  `TARGET_BOOTLOADER_BOARD_NAME`
- **CPU** — 4x Cortex-A78 @ 2.2 GHz + 4x Cortex-A55 @ 1.8 GHz
- **GPU** — Adreno 710
- **Display** — 6.1" OLED, 1080x2520, density 450
- **Storage** — UFS, 4096-byte logical blocks
- **Launch Android** — 14, kernel 5.10

## The device tree, and why it is the important finding

Sony's copyleft device tree release (`sm6450-devicetrees`) contains no Sony
board device tree, and that is not an omission.

- **The release carries only Qualcomm's reference boards** — `parrot-idp`,
  `parrot-atp`, `parrot-qrd`, `parrot-rumi` and their variants.
- **The Xperia 10 VI genuinely runs Qualcomm's Parrot QRD reference device
  tree** — it boots reporting

  ```
  Machine model: Qualcomm Technologies, Inc. Parrot QRD
  ```

- **Sony did not fork the board tree** — they carry driver changes keyed off a
  `hardware_info` driver instead.
- **The LineageOS port proved this by building the device trees from source and
  diffing against the stock blobs** — the merged base `parrot.dtb` matches
  stock on all 275 compatibles, 1414 node names and 7787 properties, and the
  `parrot-qrd` overlay on all 79 compatibles, 703 node names, 658 fragments and
  5092 properties. The only differences are phandle numbers and fragment
  ordering, which `dtc` allocates.
- **`parrot-qrd.dts` is not a drop-in replacement** — it exists as a
  standalone, pre-merged tree, but lacks the `qcom,msm-id` list that the
  overlay carries.

### How stock splits it

Qualcomm's intended split, which this port reproduces by shipping the base and
leaving the stock `dtbo` partition alone.

- **`vendor_boot` carries `dtb.img`** — the base `parrot.dtb`
- **The `dtbo` partition carries `parrot-qrd-overlay.dtbo`**
- **The bootloader applies the overlay onto the base at boot**

## Boot image geometry

From the LineageOS `BoardConfig.mk`.

- **Header version** — 4
- **Page size** — 4096
- **Kernel base** — `0x00000000`
- **Kernel image** — `Image`, uncompressed
- **Ramdisk compression** — LZ4, as stock
- **GKI** — `BOARD_USES_GENERIC_KERNEL_IMAGE := true`
- **DTB location** — inside `vendor_boot`
- **`boot` partition** — 100663296 B (96 MiB)
- **`vendor_boot` partition** — 100663296 B (96 MiB)
- **`dtbo` partition** — 25165824 B (24 MiB)
- **`super` partition** — 17179869184 B (16 GiB). The device is A/B, and
  `super` holds `system`, `vendor`, `vendor_dlkm`, `system_ext`, `odm` and
  `product` as dynamic partitions. There is also a real `metadata` partition.

## Verified boot

Stock enables AVB, and one of its properties is the most likely way to end up
with a device that will not boot.

- **A chained `vbmeta_system` sits at rollback index location 2** — while
  `boot`, `dtbo`, `recovery` and `vendor_boot` are plain hash descriptors in
  the main `vbmeta`.
- **The rollback index is enforced in hardware** — stock ships `1782864000`
  (2026-07-01), and the LineageOS port found that the bootloader rejects images
  whose rollback index is lower than what the device has already recorded, with
  the AVB red state ("Your device is corrupt"), regardless of the
  verification-disable flags. [04-flashing.md](04-flashing.md) carries the
  procedure that avoids it.

## Kernel

Sony's released kernel, and the four config fragments that describe this board.

- **Version** — 5.10.269, Android GKI `android12-5.10`
- **Config** — `gki_defconfig` plus `vendor/parrot_GKI.config` plus
  `vendor/sony/columbia.config`
- **`gki_defconfig`** — enables full LTO, CFI and the shadow call stack, and
  has neither `CONFIG_VT` nor any fbdev
- **`columbia.config`** — makes `USB_DWC3_QCOM` and `USB_DWC3_OF_SIMPLE`
  built-in, and turns on `CONFIG_BUILD_ARM64_DT_OVERLAY`
- **`parrot_GKI.config`** — sets `CONFIG_ARCH_PARROT=y` and
  `CONFIG_ARCH_RAVELIN=y`, and builds `dwc3-msm` and both USB PHYs as modules
- **`arch/arm64/boot/dts/Makefile` keys off `vendor/Makefile`** — when the
  vendor device tree directory exists, only it is built and the stock `qcom/`
  directory is skipped. That is what makes dropping Sony's release into
  `arch/arm64/boot/dts/vendor` sufficient.

## Sources

- LineageOS port: <https://github.com/johanneszab/lineageos-pdx246-releases>
- Device tree: <https://github.com/johanneszab/android_device_sony_pdx246>
- Kernel: <https://github.com/johanneszab/android_kernel_sony_sm6450>
- Device trees: <https://github.com/johanneszab/android_kernel_sony_sm6450-devicetrees>
- Vendor modules: <https://github.com/johanneszab/android_kernel_sony_sm6450-modules>
- Sony Open Devices: <https://github.com/sonyxperiadev/device-sony-pdx246>
