# Flashing and first boot

**Nothing in this document has been run on a device.** It is derived from
Sony's and Qualcomm's boot flow and from the LineageOS pdx246 port's notes.
Read it fully before connecting the phone, and take the backups.

## Try it from RAM first

Before any of what follows, there is a way to find out whether this kernel
boots at all that writes nothing to the device and so needs no backups, no
unlock beyond step 2, and no rootfs image.

```sh
scripts/flash.sh ramboot
```

That is `fastboot stage vendor_boot.img` followed by `fastboot boot boot.img` —
header v4 keeps the DTB and the initramfs in `vendor_boot`, so it has to be
staged before the kernel is handed over. `pmos.debug-shell` stops the boot in
the initramfs before a root filesystem is ever looked for, so everything under
["Getting in, with no display"](#getting-in-with-no-display) works from a RAM
boot. If the kernel is going to die early, this is where to find out.

Some Qualcomm bootloaders refuse `fastboot boot` even when unlocked. If this
one does, there is nothing to undo, and the flashing procedure below is the
fallback rather than the starting point.

## Before anything: two irreversible things

- **Unlocking the bootloader wipes the device and destroys Sony's DRM keys
  permanently.** They cannot be restored by relocking. On Xperias this degrades
  camera processing and some DRM playback *even after returning to stock*. This
  is Sony's design, not something this port can work around.
- **Anti-rollback is enforced in hardware.** Writing a `vbmeta` with a rollback
  index lower than what the device has recorded puts it in the AVB red state
  ("Your device is corrupt") and it will not boot. The LineageOS port hit this
  and found that the verification-disable flags do **not** exempt you. Stock
  ships rollback index `1782864000` (2026-07-01).

## Procedure

In order. Step 1 is the one that makes every later step recoverable.

1. **Back up every partition you are about to touch, on both slots.** From a
   booted stock system with root, or from the stock recovery. Without these you
   have no way back; the `vbmeta` dump for the slot you flash is what makes
   step 4 safe. Both slots, because a device that has taken an OTA does not
   have identical ones, and `scripts/flash.sh` picks the backup matching
   whichever slot is active.

   ```sh
   # with the device booted and adb root available
   for s in a b; do
       for p in boot vendor_boot dtbo vbmeta vbmeta_system; do
           adb shell su -c "dd if=/dev/block/by-name/${p}_${s} of=/sdcard/${p}_${s}.img"
           adb pull /sdcard/${p}_${s}.img stock/
       done
   done
   ```

2. **Unlock.** Sony's official unlock, which requires an unlock code from
   <https://developer.sony.com/open-devices/unlock-bootloader>.

   ```sh
   adb reboot bootloader
   fastboot oem unlock 0x<YOUR_CODE>
   ```

3. **Build the images.** See [03-build.md](03-build.md). The two fastboot
   images land in the rootfs chroot's `/boot`; the combined partition image
   lands under `.pmb/work/chroot_native/home/pmos/rootfs/`. Note that
   `pmb install` currently fails before producing that last one — 03-build.md
   explains why, and the RAM boot above does not need it.

   ```sh
   .pmb/work/chroot_rootfs_sony-pdx246/boot/boot.img
   .pmb/work/chroot_rootfs_sony-pdx246/boot/vendor_boot.img
   .pmb/work/chroot_native/home/pmos/rootfs/sony-pdx246.img
   ```

4. **Flash vbmeta the careful way.** pmbootstrap's `flasher flash_vbmeta`
   generates an *empty* vbmeta with `avbtool make_vbmeta_image --flags 2`. That
   image has rollback index 0, and `--flags 2` only disables the hashtree, not
   verification — the wrong shape twice over on this device. Flash the **stock**
   vbmeta with the flags patched instead: `fastboot` rewrites the flags byte as
   it sends it, so the rollback index and every descriptor stay exactly as the
   device already recorded them. This is the single most important deviation
   from a stock pmOS install.

   ```sh
   slot=$(fastboot getvar current-slot 2>&1 | sed -n 's/^current-slot: *//p' | head -1)
   fastboot --disable-verity --disable-verification flash vbmeta "stock/vbmeta_${slot}.img"
   ```

5. **Flash the images.** `scripts/flash.sh flash stock/` does exactly this,
   with the backup and slot checks, and refuses a rootfs image that was
   allocated but never filled.

   ```sh
   ROOTFS=.pmb/work/chroot_rootfs_sony-pdx246/boot
   fastboot flash boot        "$ROOTFS/boot.img"
   fastboot flash vendor_boot "$ROOTFS/vendor_boot.img"
   fastboot flash userdata    .pmb/work/chroot_native/home/pmos/rootfs/sony-pdx246.img
   fastboot reboot
   ```

Two rules for that last step:

- **Do not flash `dtbo`.** The stock `parrot-qrd` overlay there is what turns
  our base `parrot.dtb` into this device's device tree.
- **Only one slot is touched.** The other slot keeps whatever stock left there,
  which is the way back: `fastboot --set-active=b` (or `a`) returns you to
  Android, assuming that slot was healthy.

## Getting in, with no display

The display driver is an out-of-tree module that this port does not build yet,
so the first boots are blind. The images are built for that:
`kernel-cmdline.conf` carries `pmos.debug-shell`, so **the boot deliberately
stops in the initramfs** instead of continuing into a userspace nothing can
draw. Everything in this section applies equally to a RAM boot, because that
stop happens before any root filesystem is looked for. Expect that, and
expect the device to sit there looking dead.

### The USB-C cable you flashed with is the console

The debug shell brings the gadget up and offers three ways in at once. No
hardware modification, no UART cable.

```sh
ip addr show                 # a new usb0 / enp*u* interface should appear
telnet 172.16.42.1 23        # the initramfs debug shell
screen /dev/ttyACM0 115200   # same shell on the CDC-ACM port
```

Once inside, these are the four commands that matter.

```sh
cat /pmOS_init.log           # what the initramfs did
dmesg                        # what the kernel did
pmos_logdump                 # hand both over as a USB mass-storage volume
pmos_continue_boot           # carry on into the real rootfs
```

`pmos_logdump` is the one to reach for if the network gadget is flaky: it
writes `pmOS_init.txt`, `dmesg.txt`, `blkid.txt`, `cmdline.txt` and
`partitions.txt` to a FAT image and exposes it as a USB drive.

If `pmos_continue_boot` gets as far as a login prompt, the account is **`user`**
with password **`147147`** — set by `scripts/make-rootfs-img.sh`, overridable
with `PMOS_PASSWORD=` at build time. `root` has no password and cannot be
logged into directly; use `sudo`. The initramfs finds the rootfs by the
`pmos_root_uuid=` baked into the vendor_boot cmdline, which
`scripts/verify-bootimg.py` checks against the image's actual filesystem UUID.

This works because `USB_DWC3` is builtin and in dual-role mode and the ACM,
NCM, RNDIS and mass-storage gadget functions are all `=y`; `dwc3-msm` and the
two PHYs load from `modules-initfs`. The part that is *not* confirmed is Type-C
role detection — `TYPEC_QCOM_PMIC` is not set, so whether the port ever decides
it is a device rather than a host runs through the PMIC driver and extcon. If
nothing enumerates at all, suspect that before suspecting the gadget stack.

### pstore / ramoops — if nothing enumerates

This needs no cable and no working USB, only a reboot. `parrot.dtb` reserves
`ramoops_region@ffd00000`: 768K, of which 256K is the console ring and 256K is
pmsg. Its `compatible` is plain `"ramoops"`, so the builtin `PSTORE_RAM` binds
to it with no help from us, early in boot. The previous boot's console
therefore survives a reboot and can be read from stock, from a recovery, or
from a later boot that does work.

```sh
cat /sys/fs/pstore/console-ramoops-0
```

If the kernel died after `postcore_initcall` — which is almost anything
driver-related — the reason is in there.

### Serial, as a last resort

The port is at `0x98c000` (`qcom,msm-geni-console`), `parrot.dtb` already asks
for `console=ttyMSM0,115200n8` in `chosen/bootargs`, and
`kernel-cmdline.conf` adds a bare `earlycon` so the port is picked up from
`stdout-path` before the driver registers. That works with `msm_geni_serial` left as a module because Qualcomm
builds the early console as its own always-builtin object.

Reaching it physically is the problem: on recent Xperias the UART comes out on
the USB-C SBU pins and needs a specific resistance on CC to select it. Only
worth the trouble for a panic so early that even ramoops is empty.

### Did it even start?

Two failure shapes are worth telling apart before changing anything.

- **Sony logo, then back to the bootloader.** The bootloader rejected the
  images — that is AVB, not the kernel. Re-read step 4.
- **Black screen, no USB device, and ramoops empty after a reboot.** The kernel
  never reached `postcore_initcall`. That is a serial problem, not something
  more flashing will fix.

## Recovery

A device in the AVB red state can still reach fastboot, so this is recoverable
as long as you have the backups from step 1.

```sh
fastboot --set-active=b        # boot the untouched slot ('a' if you flashed b)
# or restore the slot you flashed, substituting its letter for $slot:
fastboot flash boot        "stock/boot_${slot}.img"
fastboot flash vendor_boot "stock/vendor_boot_${slot}.img"
fastboot flash vbmeta      "stock/vbmeta_${slot}.img"
```
