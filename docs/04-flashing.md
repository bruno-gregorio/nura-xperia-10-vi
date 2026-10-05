# Flashing and first boot

**Nothing in this document has been run on a device.** It is derived from
Sony's and Qualcomm's boot flow and from the LineageOS pdx246 port's notes.
Read it fully before connecting the phone, and take the backups.

## Before anything: two irreversible things

1. **Unlocking the bootloader wipes the device and destroys Sony's DRM keys
   permanently.** They cannot be restored by relocking. On Xperias this
   degrades camera processing and some DRM playback *even after returning to
   stock*. This is Sony's design, not something this port can work around.
2. **Anti-rollback is enforced in hardware.** Writing a `vbmeta` with a
   rollback index lower than what the device has recorded puts it in the AVB
   red state ("Your device is corrupt") and it will not boot. The LineageOS
   port hit this and found that the verification-disable flags do **not**
   exempt you. Stock ships rollback index `1782864000` (2026-07-01).

## Step 1 — back up every partition you are about to touch

Do this first, from a booted stock system with root, or from the stock
recovery. Without these you have no way back.

```sh
# with the device booted and adb root available
for p in boot vendor_boot dtbo vbmeta vbmeta_system; do
    adb shell su -c "dd if=/dev/block/by-name/${p}_a of=/sdcard/${p}_a.img"
    adb pull /sdcard/${p}_a.img stock/
done
```

Keep `stock/` somewhere safe. `stock/vbmeta_a.img` in particular is what makes
Step 4 safe.

## Step 2 — unlock

Sony's official unlock, which requires an unlock code from
<https://developer.sony.com/open-devices/unlock-bootloader>:

```sh
adb reboot bootloader
fastboot oem unlock 0x<YOUR_CODE>
```

## Step 3 — build the images

See [03-build.md](03-build.md). You end up with, under
`.pmb/work/chroot_native/home/pmos/rootfs/`:

- `sony-pdx246-boot.img`
- `sony-pdx246-vendor_boot.img`  (DTB + initramfs — **must** be flashed)
- `sony-pdx246-root.img`

## Step 4 — vbmeta, the careful way

pmbootstrap's `flasher flash_vbmeta` generates an *empty* vbmeta with
`avbtool make_vbmeta_image --flags 2`. That image has rollback index 0, and
`--flags 2` only disables the hashtree, not verification. On this device that
is the wrong shape twice over.

Flash the **stock** vbmeta with the flags patched instead. `fastboot` rewrites
the flags byte in the image as it sends it, so the rollback index and every
descriptor stay exactly as the device already recorded them:

```sh
fastboot --disable-verity --disable-verification flash vbmeta stock/vbmeta_a.img
```

This is the single most important deviation from a stock pmOS install.

## Step 5 — flash

```sh
fastboot flash boot        .pmb/work/chroot_native/home/pmos/rootfs/sony-pdx246-boot.img
fastboot flash vendor_boot .pmb/work/chroot_native/home/pmos/rootfs/sony-pdx246-vendor_boot.img
fastboot flash userdata    .pmb/work/chroot_native/home/pmos/rootfs/sony-pdx246-root.img
fastboot reboot
```

`scripts/flash.sh` does exactly this with the backup checks; see below.

**Do not flash `dtbo`.** The stock `parrot-qrd` overlay there is what turns our
base `parrot.dtb` into this device's device tree.

**Only one slot is touched.** The other slot keeps whatever stock left there,
which is the way back: `fastboot --set-active=b` (or `a`) returns you to
Android, assuming that slot was healthy.

## Step 6 — getting in, with no display

The display driver is an out-of-tree module that this port does not build yet,
so the first boots are blind. The images are built for that: `deviceinfo`
carries `pmos.debug-shell`, so **the boot deliberately stops in the initramfs**
instead of continuing into a userspace nothing can draw. Expect that, and
expect the device to sit there looking dead.

### The USB-C cable you flashed with is the console

The debug shell brings the gadget up and offers three ways in at once. No
hardware modification, no UART cable:

```sh
ip addr show                 # a new usb0 / enp*u* interface should appear
telnet 172.16.42.1 23        # the initramfs debug shell
screen /dev/ttyACM0 115200   # same shell on the CDC-ACM port
```

Inside that shell:

```sh
cat /pmOS_init.log           # what the initramfs did
dmesg                        # what the kernel did
pmos_logdump                 # hand both over as a USB mass-storage volume
pmos_continue_boot           # carry on into the real rootfs
```

`pmos_logdump` is the one to reach for if the network gadget is flaky: it
writes `pmOS_init.txt`, `dmesg.txt`, `blkid.txt`, `cmdline.txt` and
`partitions.txt` to a FAT image and exposes it as a USB drive.

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
from a later boot that does work:

```
/sys/fs/pstore/console-ramoops-0
```

If the kernel died after `postcore_initcall` — which is almost anything
driver-related — the reason is in there.

### Serial, as a last resort

The port is at `0x98c000` (`qcom,msm-geni-console`), `parrot.dtb` already asks
for `console=ttyMSM0,115200n8` in `chosen/bootargs`, and `deviceinfo` adds a
bare `earlycon` so the port is picked up from `stdout-path` before the driver
registers. All of this is builtin, not modular, which is what makes `earlycon`
possible at all.

Reaching it physically is the problem: on recent Xperias the UART comes out on
the USB-C SBU pins and needs a specific resistance on CC to select it. Only
worth the trouble for a panic so early that even ramoops is empty.

### Did it even start?

If the device shows the Sony logo and reboots to the bootloader, the bootloader
rejected the images — that is AVB, not the kernel. Re-read Step 4.

If it hangs on a black screen with no USB device appearing *and* ramoops comes
back empty after a reboot, the kernel never reached `postcore_initcall`. That
is a serial problem, not something more flashing will fix.

## Recovery

```sh
fastboot --set-active=b        # boot the untouched slot
# or restore the slot you flashed:
fastboot flash boot        stock/boot_a.img
fastboot flash vendor_boot stock/vendor_boot_a.img
fastboot flash vbmeta      stock/vbmeta_a.img
```

A device that is in the AVB red state can still reach fastboot, so this is
recoverable as long as you have the backups from Step 1.
