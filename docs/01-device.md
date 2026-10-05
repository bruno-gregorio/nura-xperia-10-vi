# Device facts

Everything below is either read out of Sony's published sources or taken from
the LineageOS pdx246 port, which verified it on hardware. Nothing here is
inferred from the device by this project — it has never been run on one.

## Identity

| | |
|---|---|
| Marketing name | Sony Xperia 10 VI |
| Models | `XQ-ES54` (EEA), `XQ-ES72` (HK/TW/SG/MY/TH/VN/MO) |
| Sony codename | `pdx246`, platform `columbia` |
| SoC | Qualcomm SM6450 "Snapdragon 6 Gen 1" |
| Qualcomm codename | `parrot` (`TARGET_BOARD_PLATFORM`, `TARGET_BOOTLOADER_BOARD_NAME`) |
| CPU | 4x Cortex-A78 @ 2.2 GHz + 4x Cortex-A55 @ 1.8 GHz |
| GPU | Adreno 710 |
| Display | 6.1" OLED, 1080x2520, density 450 |
| Storage | UFS, 4096-byte logical blocks |
| Launch Android | 14, kernel 5.10 |

The two models are the same hardware. Comparing Sony's `70.2.A.4.168` firmware
for each, 3207 of 3208 blobs are byte-identical; the single difference is the
NFC RF tuning table, which the NFC HAL picks at runtime from
`/sys/devices/platform/HardwareInfo/modem_id`.

## The device tree — the important finding

Sony's copyleft device tree release (`sm6450-devicetrees`) contains **no Sony
board device tree**. It carries only Qualcomm's reference boards: `parrot-idp`,
`parrot-atp`, `parrot-qrd`, `parrot-rumi` and their variants.

That is not an omission. The Xperia 10 VI genuinely runs Qualcomm's **Parrot
QRD reference device tree**. It boots reporting

```
Machine model: Qualcomm Technologies, Inc. Parrot QRD
```

Sony did not fork the board tree; they carry driver changes keyed off a
`hardware_info` driver instead. The LineageOS port verified this by building
the device trees from source and diffing against the stock blobs: the merged
base `parrot.dtb` matches stock on all 275 compatibles, 1414 node names and
7787 properties, and the `parrot-qrd` overlay on all 79 compatibles, 703 node
names, 658 fragments and 5092 properties. The only differences are phandle
numbers and fragment ordering, which `dtc` allocates.

Stock splits it the way Qualcomm intends:

- `vendor_boot` carries `dtb.img` → base `parrot.dtb`
- the `dtbo` partition carries `parrot-qrd-overlay.dtbo`
- the bootloader applies the overlay onto the base at boot

`parrot-qrd.dts` also exists as a standalone, pre-merged tree, but it lacks the
`qcom,msm-id` list that the overlay carries, so it is not a drop-in
replacement. This port therefore ships the base and leaves the stock `dtbo`
partition alone.

## Boot image geometry

From the LineageOS `BoardConfig.mk`:

| | |
|---|---|
| Header version | 4 |
| Page size | 4096 |
| Kernel base | `0x00000000` |
| Kernel image | `Image` (uncompressed) |
| Ramdisk compression | LZ4 (stock) |
| GKI | `BOARD_USES_GENERIC_KERNEL_IMAGE := true` |
| DTB location | inside `vendor_boot` |
| `boot` partition | 100663296 B (96 MiB) |
| `vendor_boot` partition | 100663296 B (96 MiB) |
| `dtbo` partition | 25165824 B (24 MiB) |
| Super partition | 17179869184 B (16 GiB), A/B, dynamic |

The device is A/B with a `super` partition holding `system`, `vendor`,
`vendor_dlkm`, `system_ext`, `odm`, `product` as dynamic partitions. There is a
real `metadata` partition.

## Verified boot

Stock enables AVB with a chained `vbmeta_system` at rollback index location 2;
`boot`, `dtbo`, `recovery` and `vendor_boot` are plain hash descriptors in the
main `vbmeta`.

The rollback index matters: stock ships `1782864000` (2026-07-01), and the
LineageOS port found that the bootloader rejects images whose rollback index is
lower than what the device has already recorded, with the AVB red state
("Your device is corrupt"), **regardless of the verification-disable flags**.
See [04-flashing.md](04-flashing.md) — this is the single most likely way to get
a device that will not boot.

## Kernel

- 5.10.269, Android GKI `android12-5.10`
- Built from `gki_defconfig` + `vendor/parrot_GKI.config` + `vendor/sony/columbia.config`
- `gki_defconfig` enables full LTO, CFI and the shadow call stack, and has
  neither `CONFIG_VT` nor any fbdev
- `columbia.config` makes `USB_DWC3_QCOM` and `USB_DWC3_OF_SIMPLE` built-in,
  and turns on `CONFIG_BUILD_ARM64_DT_OVERLAY`
- `parrot_GKI.config` sets `CONFIG_ARCH_PARROT=y` and `CONFIG_ARCH_RAVELIN=y`,
  and builds `dwc3-msm` and both USB PHYs as modules

`arch/arm64/boot/dts/Makefile` keys off `vendor/Makefile`: when the vendor
device tree directory exists, *only* it is built and the stock `qcom/`
directory is skipped. That is what makes dropping Sony's release into
`arch/arm64/boot/dts/vendor` sufficient.

## Sources

- LineageOS port: <https://github.com/johanneszab/lineageos-pdx246-releases>
- Device tree: <https://github.com/johanneszab/android_device_sony_pdx246>
- Kernel: <https://github.com/johanneszab/android_kernel_sony_sm6450>
- Device trees: <https://github.com/johanneszab/android_kernel_sony_sm6450-devicetrees>
- Vendor modules: <https://github.com/johanneszab/android_kernel_sony_sm6450-modules>
- Sony Open Devices: <https://github.com/sonyxperiadev/device-sony-pdx246>
