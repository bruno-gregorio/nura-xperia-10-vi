# Design decisions

Why the port is shaped the way it is, including the alternatives that were
considered and rejected, so that nobody has to rediscover them.

## Downstream kernel, not mainline

This port builds Sony's released 5.10 GKI kernel. The real reason is ordering,
not impossibility — [06-mainline.md](06-mainline.md) works the whole question
through.

### Why not start from mainline

- **No SoC enablement exists** — no `sm6450.dtsi`, no GCC, pinctrl or
  interconnect drivers. Starting there would mean writing all of it before
  anything boots.
- **The first mainline boot has no console to debug it with** — because on a
  first mainline boot the console is part of what is being brought up. That
  ordering argument is the one that holds.
- **"From scratch" was the original reason and it was wrong** — every per-SoC
  driver exists as GPL source in the tarballs this port already downloads, and
  the sibling SoC SM4450 is upstream, which supplies a worked example of the
  downstream-to-mainline transformation.

### What the downstream kernel costs

Stated plainly so nobody is surprised later.

- **The kernel work cannot be upstreamed** — none of the 5.10 patching goes
  anywhere. The *hardware facts* do carry over: the device tree finding, the
  boot geometry, the AVB behaviour and whatever the first boots teach us are
  exactly the inputs a mainline port needs.
- **It rots** — Sony stops publishing sources when the device goes EOL, and
  5.10 leaves LTS eventually.
- **Camera is out of reach** — libcamera has no SM6450 CAMSS support, and the
  downstream path is the CamX/Chi-CDK blob stack, which needs Android
  userspace.
- **Graphics is the real fight** — Adreno 710 is a7xx, which Mesa's freedreno
  supports, but against the *mainline* `msm` DRM uAPI. A downstream 5.10 kernel
  exposes KGSL, where Mesa's support is the Turnip/Vulkan-on-Android path.
  Expect software rendering first.
- **Modem means a whole stack swap** — ModemManager plus QRTR plus `rmtfs`
  plus `pd-mapper` plus `tqftpserv`, against hardware built for Android's RIL.
  VoLTE realistically no.

### What it buys

- A device that boots a real Linux userspace
- A ~20 GB checkout instead of 450 GB
- Iteration measured in minutes

## The device tree: ship the base, keep the stock dtbo

pdx246 runs Qualcomm's Parrot QRD reference device tree
(see [01-device.md](01-device.md)), and this port reproduces stock's split
rather than inventing its own.

- **`deviceinfo_dtb="vendor/qcom/parrot"` ships the base in our
  `vendor_boot`** — the same base `parrot.dtb` that stock puts there.
- **The `dtbo` partition is never flashed** — so the stock
  `parrot-qrd-overlay.dtbo` keeps being applied onto our base. That reproduces
  stock's device tree exactly while touching the smallest number of partitions.
- **`CONFIG_BUILD_ARM64_DT_OVERLAY=y` must stay on** — already set in
  `columbia.config`, it is what makes `dtc` emit the `__symbols__` node that
  the base needs for overlay application.
- **The alternative was rejected** — building a standalone `parrot-qrd.dtb` and
  flashing a matching `dtbo` would mean shipping a tree that lacks the
  `qcom,msm-id` list the overlay carries, and overwriting a partition for no
  gain.

## Boot images: header v4, both images ours

`boot-deploy` already handles header v4: for `deviceinfo_header_version=4` it
runs `mkbootimg` with `--vendor_boot`, which produces two images that both have
to be flashed.

- **`boot.img`** — kernel only, the GKI layout
- **`vendor_boot.img`** — the DTB, our initramfs and the cmdline
- **Keeping the stock `vendor_boot` was rejected** — flashing only `boot.img`
  and letting the stock vendor ramdisk supply the DTB was considered, but then
  the Android first-stage init and a set of modules built against a different
  kernel end up concatenated with our initramfs. Owning both images removes
  Android from the picture entirely.

## Kernel config

`pmos.config` is applied last, after `gki_defconfig`, `parrot_GKI.config` and
`columbia.config`. It does four things.

1. **Turns off LTO, CFI and the shadow call stack.** These cost a lot of build
   time and RAM. They exist in GKI to keep a stable ABI against prebuilt vendor
   modules; here the kernel and every module are built together in one go, so
   there is no ABI to preserve.
2. **Adds what a Linux userspace needs and Android does not.**
   `gki_defconfig` has no `CONFIG_VT` and no fbdev at all, because Android
   draws through SurfaceFlinger. pmbootstrap's `kconfig check` requires `VT`,
   `FB`, `DRM_FBDEV_EMULATION`, `DEVTMPFS`, `BINFMT_SCRIPT` and friends.
3. **Keeps every logging path open.** The first boots are blind, so
   `PSTORE_RAM`, `PSTORE_CONSOLE`, `SERIAL_MSM_GENI_CONSOLE` and
   `printk.devkmsg=on` are all on.
4. **Keeps `CONFIG_FB_VIRTUAL` explicitly off.** The stock cmdline asks for
   `video=vfb:640x400,bpp=32`, which would register a virtual framebuffer that
   claims `/dev/fb0` ahead of the real panel; pmbootstrap rejects `USE_VFB`
   outright.

## Initramfs modules

`modules-initfs` follows stock's first-stage order, taken from
`device/sony/pdx246/modules.load`, rather than alphabetical order.

- **Order is load-bearing** — clocks, pinctrl, regulators and the SMMU have to
  probe before the dynamic partitions, and UFS, can come up. Stock ships that
  order because the default one does not work.
- **USB is added to stock's list** — `phy-msm-snps-hs`, `phy-msm-ssusb-qmp`
  and `dwc3-msm`. Android brings these up in second stage, but with no display
  driver yet, USB networking is the only way into the device, so they have to
  be in the initramfs.
- **`dm-mod` is added too** — pmOS's own requirement.
- **Everything listed is built from the kernel tree itself** — the out-of-tree
  `sm6450-modules` repository (display, audio, camera, video, dataipa, rmnet,
  WLAN) is not built yet, because nothing in the boot path needs it. Display is
  the first thing that will.

## Environment

pmbootstrap runs from a git checkout in `.pmb/`, with `-c` pointing at a config
in the project and `work` set inside it too, because distrobox shares `$HOME`
with the host and pmbootstrap's defaults (`~/.config`, `~/.local/var`) would
write outside the project.

Three upstream patches in `patches/` are needed to run rootless. None is
device-specific, and all three are worth sending upstream.

- **Device nodes in a user namespace** — `mknod(2)` is refused inside a
  non-initial user namespace whatever capabilities are held, so the nodes are
  bind-mounted from the container's own `/dev` instead; `stat()` reports the
  same major and minor through the bind, so pmbootstrap's verification still
  passes. The chroot's `/dev` also stays a plain directory rather than a
  tmpfs, because the kernel sets `SB_I_NODEV` on any superblock mounted from
  such a namespace and then refuses `open(O_CREAT)` on a device node under it
  — which a plain `> /dev/null` performs.
- **`mount` and `umount` in a user namespace** — a plain `mount --bind /proc`
  fails with `EINVAL` because podman masks parts of `/proc` with its own
  mounts, so `bind()` retries with `--rbind`. Unmounting has the mirror
  problem: the submounts under `/proc` and `/sys` are locked to the namespace
  and can only go away together with the mount they hang off, so `umount_all()`
  falls back to a lazy detach and only insists everything is gone once the
  whole list has been walked.
- **Only unregister our own binfmt** — `binfmt_misc` is global to the host
  rather than per container, and inside a rootless container
  `/proc/sys/fs/binfmt_misc` is not writable, so tearing down a handler that
  pmbootstrap did not register fails and takes the whole shutdown with it.
