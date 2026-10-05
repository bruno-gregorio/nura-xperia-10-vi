# Design decisions

## Downstream kernel, not mainline

SM6450 has no mainline support: no `sm6450.dtsi`, no GCC/pinctrl/interconnect
drivers. Starting there would mean writing SoC enablement before anything
boots — and, critically, debugging it with no console, because on a first
mainline boot the console is part of what is being brought up.

That ordering argument is the real reason, and it is the one that holds.
"From scratch" was the original reason and it was wrong: every per-SoC driver
exists as GPL source in the tarballs this port already downloads, and the
sibling SoC SM4450 is upstream, which supplies a worked example of the
downstream-to-mainline transformation. See [06-mainline.md](06-mainline.md).

This port builds Sony's released 5.10 GKI kernel instead. Consequences, stated
plainly so nobody is surprised later:

- **The kernel work cannot be upstreamed.** None of the 5.10 patching goes
  anywhere. The *hardware facts* do carry over — the device tree finding, the
  boot geometry, the AVB behaviour and whatever the first boots teach us are
  exactly the inputs a mainline port needs.
- **It rots.** Sony stops publishing sources when the device goes EOL, and 5.10
  leaves LTS eventually.
- **Camera is out of reach.** libcamera has no SM6450 CAMSS support and the
  downstream path is the CamX/Chi-CDK blob stack, which needs Android userspace.
- **Graphics is the real fight.** Adreno 710 is a7xx, which Mesa's freedreno
  supports — but against the *mainline* `msm` DRM uAPI. A downstream 5.10
  kernel exposes KGSL, where Mesa's support is the Turnip/Vulkan-on-Android
  path. Expect software rendering first.
- **Modem means ModemManager + QRTR + `rmtfs` + `pd-mapper` + `tqftpserv`**,
  against a stack built for Android's RIL. VoLTE realistically no.

What it does buy: a device that boots a real Linux userspace, on a ~20 GB
checkout instead of 450 GB, with iteration measured in minutes.

## The device tree: ship the base, keep the stock dtbo

pdx246 runs Qualcomm's Parrot QRD reference device tree
(see [01-device.md](01-device.md)). Stock puts base `parrot.dtb` in
`vendor_boot` and `parrot-qrd-overlay.dtbo` in the `dtbo` partition, and the
bootloader applies one onto the other.

This port does the same: `deviceinfo_dtb="vendor/qcom/parrot"` ships the base
in our `vendor_boot`, and **the `dtbo` partition is never flashed**, so the
stock overlay keeps being applied. That reproduces stock's device tree exactly
while touching the smallest number of partitions.

`CONFIG_BUILD_ARM64_DT_OVERLAY=y` (already in `columbia.config`) is what makes
`dtc` emit the `__symbols__` node the base needs for overlay application. Do
not turn it off.

The alternative — building standalone `parrot-qrd.dtb` and flashing a matching
`dtbo` — was rejected: that tree lacks the `qcom,msm-id` list the overlay
carries, and it would mean overwriting a partition for no gain.

## Boot images: header v4, both images ours

`boot-deploy` already handles header v4. For `deviceinfo_header_version=4` it
runs `mkbootimg` with `--vendor_boot`, producing **two** images:

- `boot.img` — kernel only (GKI layout)
- `vendor_boot.img` — DTB, our initramfs, and the cmdline

Both must be flashed. Keeping the *stock* `vendor_boot` and flashing only
`boot.img` was considered — the stock vendor ramdisk would supply the DTB — but
then the Android first-stage init and a set of modules built against a
different kernel end up concatenated with our initramfs. Owning both images
removes Android from the picture entirely.

## Kernel config

`pmos.config` is applied last, after `gki_defconfig`, `parrot_GKI.config` and
`columbia.config`. It does three things:

1. **Turns off LTO, CFI and the shadow call stack.** These cost a lot of build
   time and RAM. They exist in GKI to keep a stable ABI against prebuilt vendor
   modules; here the kernel and every module are built together in one go, so
   there is no ABI to preserve.
2. **Adds what a Linux userspace needs and Android does not.** `gki_defconfig`
   has no `CONFIG_VT` and no fbdev at all, because Android draws through
   SurfaceFlinger. pmbootstrap's `kconfig check` requires `VT`, `FB`,
   `DRM_FBDEV_EMULATION`, `DEVTMPFS`, `BINFMT_SCRIPT` and friends.
3. **Keeps every logging path open.** The first boots are blind, so
   `PSTORE_RAM`, `PSTORE_CONSOLE`, `SERIAL_MSM_GENI_CONSOLE` and
   `printk.devkmsg=on` are all on.

`CONFIG_FB_VIRTUAL` is explicitly off. The stock cmdline asks for
`video=vfb:640x400,bpp=32`, which would register a virtual framebuffer that
claims `/dev/fb0` ahead of the real panel; pmbootstrap rejects `USE_VFB`
outright.

## Initramfs modules

`modules-initfs` follows **stock's first-stage order**, taken from
`device/sony/pdx246/modules.load`, not alphabetical order. Clocks, pinctrl,
regulators and the SMMU have to probe before the dynamic partitions — and UFS —
can come up. Stock ships that order because the default one does not work.

Two additions to stock's list:

- `phy-msm-snps-hs`, `phy-msm-ssusb-qmp`, `dwc3-msm` — USB. Android brings
  these up in second stage, but with no display driver yet, USB networking is
  the only way into the device, so they have to be in the initramfs.
- `dm-mod` — pmOS's own requirement.

All of these are built from the kernel tree itself. The out-of-tree
`sm6450-modules` repository (display, audio, camera, video, dataipa, rmnet,
WLAN) is **not** built yet; nothing in the boot path needs it. Display is the
first thing that will.

## Environment

pmbootstrap is run from a git checkout in `.pmb/`, with `-c` pointing at a
config in the project and `work` set inside it too. distrobox shares `$HOME`
with the host, so pmbootstrap's defaults (`~/.config`, `~/.local/var`) would
write outside the project.

Two upstream patches in `patches/` are needed to run rootless:

- **Device nodes.** `mknod(2)` is refused inside a non-initial user namespace
  whatever capabilities are held, so pmbootstrap cannot create `/dev/null` and
  friends in its chroots. They are bind-mounted from the container's `/dev`
  instead; `stat()` reports the same major and minor, so pmbootstrap's own
  verification still passes.
- **`--rbind` fallback.** A plain `mount --bind /proc` fails with `EINVAL`
  inside the container because podman masks parts of `/proc` with its own
  mounts. `bind()` retries with `--rbind`.

Neither is device-specific; both are worth sending upstream.
