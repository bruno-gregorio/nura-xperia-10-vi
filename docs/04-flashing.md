# Flashing and first boot

**Nothing in this document has been run on a device.** It is derived from
Sony's and Qualcomm's boot flow and from the LineageOS pdx246 port's notes;
read it fully before connecting the phone, and take the backups.

## Try it from RAM first

Before any of what follows, there is a way to find out whether this kernel
boots at all that writes nothing to the device, and so needs no backups and no
rootfs image.

```sh
scripts/flash.sh ramboot
```

### What a RAM boot does

- **It stages `vendor_boot.img`, then hands the kernel over** — that is
  `fastboot stage vendor_boot.img` followed by `fastboot boot boot.img`.
  Header v4 keeps the DTB and the initramfs in `vendor_boot`, so it has to be
  staged first.
- **It stops in the initramfs** — `pmos.debug-shell` stops the boot before a
  root filesystem is ever looked for, so everything under
  ["Getting in, with no display"](#getting-in-with-no-display) works from a RAM
  boot. If the kernel is going to die early, this is where to find out.
- **Some Qualcomm bootloaders refuse `fastboot boot` even when unlocked** — if
  this one does, there is nothing to undo, and the procedure below becomes the
  starting point rather than the fallback.

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

Before any of it, with the phone booted normally and USB debugging on:

```sh
scripts/device-probe.sh
```

That writes nothing and needs no root. It confirms the phone really is a
`pdx246` on `parrot` before you flash images built for one, reports which slot
is active, and says what it can about the lock state. Read that last part with
the caveat it prints: the lock properties are set by whatever is running as the
system image, and a GSI rewrites them, so `fastboot getvar unlocked` is the
only authority.

Then collect the hardware description, which is what the mainline work in
[06-mainline.md](06-mainline.md) is written against:

```sh
scripts/device-collect.sh
```

Also read-only. Without root it gets the device topology - every platform and
I2C device with its address, the remote processors, the PMICs, the regulators,
the stock kernel config and the vendor module inventory - into
`out/device-dump/`. With root, meaning the "Rooted debugging" toggle in
Developer options on a LineageOS build, it additionally gets the live device
tree, the kernel command line, the debugfs clock and regulator summaries, and
`dd` copies of the boot partitions into `out/device-dump/stock/`, which is
exactly the backup step 1 below asks for.

1. **Get a copy of stock, both slots.** `scripts/flash.sh flash` needs
   `stock/vbmeta_$slot.img` and will not run without it, because the `vbmeta`
   for the slot being written is what keeps step 4 from tripping anti-rollback.
   Both slots, because a device that has taken an OTA does not have identical
   ones, and `flash.sh` picks the backup matching whichever slot is active.

   There is a catch worth understanding before you start, because the obvious
   approach does not work: **dumping the partitions needs root, and a stock
   Xperia has none.** Unlocking the bootloader does not grant it either. So the
   recipe below only applies if the phone is *already* rooted:

   ```sh
   # only if 'adb shell su' actually works
   for s in a b; do
       for p in boot vendor_boot dtbo vbmeta vbmeta_system; do
           adb shell su -c "dd if=/dev/block/by-name/${p}_${s} of=/sdcard/${p}_${s}.img"
           adb pull /sdcard/${p}_${s}.img stock/
       done
   done
   ```

   Otherwise the backup is a **download, not a dump**: fetch the exact firmware
   for your model and region with XperiFirm, and unpack the `.sin` files to get
   `boot`, `vendor_boot`, `dtbo` and `vbmeta`. That is also the real recovery
   path if a flash goes wrong — reflashing Sony's own firmware restores the
   device regardless of what you wrote over it. Check the model string from
   `scripts/device-probe.sh` against the firmware you download; the Xperia 10
   VI ships as several variants and they are not interchangeable.

   `scripts/flash.sh ramboot` needs none of this, which is why it comes first.

2. **Unlock.** Sony's official unlock, which requires an unlock code from
   <https://developer.sony.com/open-devices/unlock-bootloader>.

   ```sh
   adb reboot bootloader
   fastboot oem unlock 0x<YOUR_CODE>
   ```

3. **Build the images.** See [03-build.md](03-build.md). The two fastboot
   images land in the rootfs chroot's `/boot`, and the rootfs image under
   `.pmb/work/chroot_native/home/pmos/rootfs/`; note that `pmb install` cannot
   produce that last one in a rootless container, which is why
   `scripts/make-rootfs-img.sh` exists — and the RAM boot above does not need
   it at all.

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

### Two rules for that last step

- **Do not flash `dtbo`.** The stock `parrot-qrd` overlay there is what turns
  our base `parrot.dtb` into this device's device tree.
- **Only one slot is touched.** The other slot keeps whatever stock left there,
  which is the way back: `fastboot --set-active=b` (or `a`) returns you to
  Android, assuming that slot was healthy.

## Iterating without touching the phone

A kernel that dies leaves this phone on a black screen with no USB, and the
only way back to fastboot by hand is holding Power and Volume Up until it
vibrates, then Volume Up while plugging the cable in. That turns every attempt
into a trip to the desk, so it is worth arranging things so the phone comes
back on its own.

The bootloader's own A/B logic is what makes that possible. It decrements a
retry counter on each attempt at the active slot, resets it only when userspace
reports the boot good, and when the counter runs out it marks the slot
unbootable and falls back to the other slot.

So the experiment goes on the **inactive** slot and the stock images stay on
the active one. A crash then lands back in stock Android, where adb is waiting
and `adb reboot bootloader` begins the next round.

```sh
scripts/try-kernel.sh             # flash to the spare slot and boot it
scripts/try-kernel.sh --log       # read the last boot's log back off flash
scripts/try-kernel.sh --harvest   # pull a live initramfs over the USB gadget
scripts/try-kernel.sh --restore   # put the spare slot back to stock
```

Three environment variables change what gets flashed, all of them bring-up
only. `BOOTLOG=0` leaves the flash-log hook out. `PROBE=1` replaces `/init`
with nothing but a sleep and a reboot, which answers whether the initramfs
runs at all. `STAGE=1` is the useful one once it does:

```sh
STAGE=1 WAIT=1300 scripts/try-kernel.sh
```

It replaces `/init` with a probe that loads the 89 modules one at a time
rather than in the single `modprobe -a` the real init uses, and opens every
channel it can before starting. The first pass is a curated 40 - clocks,
pinctrl, regulators, the SMMU, rpmh, the PMIC, the two PHYs and `dwc3-msm` -
chosen because the USB gadget needs none of the storage chain, so a live link
can come up before the boot dies. If it does, `--harvest` runs itself and the
remaining 49 load in front of you. If it does not, the time to the fallback
names the step that hung; see below.

The other half is being able to read what happened, and on this device that
took some finding. There is no console: the GENI UART is not brought out to a
pad, USB only enumerates in fastboot, and ramoops is wiped between boots - see
`05-status.md`. So the log goes to flash instead. Every image `try-kernel.sh`
builds carries the hook from `scripts/bootlog.py`, which writes the kernel ring
buffer to the unused `rddata` partition once storage comes up, and rewrites it
every second afterwards.

The ring buffer being retroactive is what makes that work. The write happens
late, well after the interesting part, but what it writes still starts at the
first line of kernel output. A `dmesg` captured the instant UFS appears
contains the whole boot.

### What makes it work, and where it stops working

- **`panic=5` and `panic_on_oops=1`** are on the command line from
  `kernel-cmdline.conf`. Without them a panic sits there forever and nothing
  ever resets the phone, so the retry counter never runs down.
- **The stock slot must be marked successful**, or it is not a fallback at all.
  `try-kernel.sh` refuses to run otherwise. Booting it into Android once and
  letting it settle is what sets the flag; `fastboot getvar slot-successful:b`
  confirms it.
- **The spare slot's own vbmeta cannot be used.** On a phone that has taken an
  OTA the two slots carry different rollback indexes - here 1772323200 on a
  against 1777593600 on b - and anti-rollback refuses the lower one. The script
  takes the *active* slot's vbmeta, patches the two disable flags into it, and
  flashes that.
- **Recovery only works from a stock slot.** It borrows its device tree, its
  command line and a prepended vendor ramdisk from `vendor_boot`, so our
  `vendor_boot` stops TWRP from coming up even though `recovery_a` and
  `recovery_b` are untouched. `--log` switches to the stock slot before
  rebooting into recovery for this reason.
- **A hang still needs the button combo, but it is no longer silent.** If the
  kernel stops without panicking, nothing resets the phone and getting back to
  fastboot is still a trip to the desk. The log is there either way, since the
  hook rewrites it every second rather than only on the way down, so the trip
  buys an answer instead of another guess. `softlockup_panic=1` turns the
  commonest kind of hang into a panic, which does reset.
- **Seven attempts is the bootloader's maximum, and fastboot cannot lower it.**
  The counter is three bits of the GPT partition attributes - bits 51 to 53,
  alongside priority at 48, active at 50, successful at 54 and unbootable at
  55 - so seven is as high as it goes, and `fastboot --set-active` always
  resets it to the maximum. Lowering it would mean writing the partition table
  by hand, and there is no firmware image here to recover a corrupt one, so it
  is left alone. At roughly 54 seconds an attempt a failed round takes about
  six minutes, unattended.
### Reading the clock, when nothing enumerates

The last channel on this device is how long the bootloader takes to give up.
It needs no storage, no USB and no console, and it is hands-free, because a
deliberate reset keeps feeding the A/B retry counter.

The staged probe starts a watchdog before anything can hang. When module
loading stops making progress for 25 seconds it delays the reset by one
second per step already completed, so seven attempts multiply that difference
by seven, and the time to the fallback names the step:

```sh
scripts/bootlog.py stages .pmb/work/chroot_rootfs_sony-pdx246/boot/vendor_boot.img
scripts/bootlog.py stages <that image> 620     # 620s to the fallback -> index
```

Underneath the watchdog are two kernel mechanisms the probe switches on, both
through `/proc` so that no command-line rebuild is needed:

- **`hung_task_panic`** makes khungtaskd panic on a task stuck
  uninterruptible, which is what a driver waiting forever on a clock, a
  regulator or firmware looks like. `panic=5` turns that into a reset.
- **`sysrq`**, so the watchdog can reset with `echo b > /proc/sysrq-trigger`.
  That is `emergency_restart()`, which skips the orderly shutdown a wedged
  driver could otherwise block.

None of it survives a hard lockup. Every channel here needs the scheduler -
the watchdog is a shell loop, khungtaskd is a kthread - and a spinlock
deadlock with interrupts off stops all of them, with no NMI watchdog on arm64
to catch it. That case looks like one attempt burnt and then silence, and
still needs Power+VolUp.


## Getting in, with no display

The display driver is an out-of-tree module that this port does not build yet,
so the first boots are blind and the images are built for that: because
`kernel-cmdline.conf` carries `pmos.debug-shell`, the boot deliberately stops
in the initramfs instead of continuing into a userspace nothing can draw.
Expect the device to sit there looking dead, and expect all of this to work
from a RAM boot too, since that stop happens before any root filesystem is
looked for.

### The USB-C cable you flashed with is the console

The debug shell brings the gadget up and offers three ways in at once. No
hardware modification, no UART cable.

```sh
scripts/console.sh
```

That waits for the gadget to enumerate, checks the host actually got an address
on `172.16.42.0/24`, and opens the shell. `scripts/console.sh watch` stops
after the diagnosis instead of connecting. When the gadget never appears it
prints the three candidate reasons in order of likelihood, which is the useful
case — see *Why the gadget should come up* below.

By hand, it is these three:

```sh
ip addr show                 # a new usb0 / enp*u* interface should appear
telnet 172.16.42.1 23        # the initramfs debug shell
screen /dev/ttyACM0 115200   # same shell on the CDC-ACM port
```

Fedora ships no `telnet`, `nc` or `socat`, and this project may not install
onto the host, so `console.sh` falls back to `scripts/telnet.py` — a small
client that needs nothing but `python3` and refuses every option the server
offers, which is what a debug shell wants. It prefers a real `telnet` if the
host has one.

### The four commands that matter once you are in

Whichever of the three ways in worked, the shell is the same one, and these are
what to run in it.

```sh
cat /pmOS_init.log           # what the initramfs did
dmesg                        # what the kernel did
pmos_logdump                 # hand both over as a USB mass-storage volume
pmos_continue_boot           # carry on into the real rootfs
```

### What to expect from those commands

- **`pmos_logdump` is the one to reach for if the network gadget is flaky** —
  it writes `pmOS_init.txt`, `dmesg.txt`, `blkid.txt`, `cmdline.txt` and
  `partitions.txt` to a FAT image and exposes it as a USB drive.
- **`pmos_continue_boot` should reach a login prompt** — the account is
  **`user`** with password **`147147`**, set by
  `scripts/make-rootfs-img.sh` and overridable with `PMOS_PASSWORD=` at build
  time. `root` has no password and cannot be logged into directly; use `sudo`.
- **The rootfs is found by UUID, not by partition name** — the initramfs uses
  the `pmos_root_uuid=` baked into the vendor_boot cmdline, which
  `scripts/verify-bootimg.py` checks against the image's actual filesystem
  UUID.

### Why the gadget should come up, and what is not confirmed

- **Everything kernel-side is in place** — `USB_DWC3` is builtin and in
  dual-role mode, the ACM, NCM, RNDIS and mass-storage gadget functions are all
  `=y`, and `dwc3-msm` plus the two PHYs load from `modules-initfs`.
- **Type-C role detection is the part that is not confirmed** —
  `TYPEC_QCOM_PMIC` is not set, so whether the port ever decides it is a device
  rather than a host runs through the PMIC driver and extcon. If nothing
  enumerates at all, suspect that before suspecting the gadget stack.

### The boot log, if nothing enumerates

This needs no cable and no working USB, only a reboot. Every image
`scripts/try-kernel.sh` flashes carries the hook from `scripts/bootlog.py`,
which writes the kernel ring buffer to the unused `rddata` partition as soon as
storage comes up and rewrites it every second after that. Reading it means
getting into recovery, where adb runs as root:

```sh
scripts/try-kernel.sh --log
```

That reboots into recovery by itself, switching to a stock slot first if it
has to, and decodes the record. An `rddata` that is still all zeros is a result
too: it means the kernel never reached the point where UFS works.

Do **not** reach for ramoops here. It looks like the obvious answer and it does
not work on this device - the region binds, the kernel writes to it, and the
contents are gone by the next boot, because the bootloader scrubs that DRAM.
`05-status.md` has the evidence. `scripts/grab-pstore.sh` is kept only so the
dead end stays documented.

### Serial, as a last resort

- **The port is already configured** — it is at `0x98c000`
  (`qcom,msm-geni-console`), `parrot.dtb` already asks for
  `console=ttyMSM0,115200n8` in `chosen/bootargs`, and `kernel-cmdline.conf`
  adds a bare `earlycon` so the port is picked up from `stdout-path` before the
  driver registers. That works with `msm_geni_serial` left as a module because
  Qualcomm builds the early console as its own always-builtin object.
- **Reaching it physically is the problem** — on recent Xperias the UART comes
  out on the USB-C SBU pins and needs a specific resistance on CC to select it.
  Only worth the trouble for a panic so early that even ramoops is empty.

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
