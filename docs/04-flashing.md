# Installing and booting

How a phone gets from Android to postmarketOS on this port, as it is actually
done: the kernel goes on the spare A/B slot with `scripts/try-kernel.sh`, the
rootfs goes on the SD card with `scripts/sdcard-install.sh`, and the stock slot
stays as the way back. All of it has run on the owner's unit, which came to the
port already unlocked and running LineageOS 23.2, a GSI over Sony's vendor
partitions. The unlock below is Sony's procedure and has not been run by this
project. There is no permanent install yet; see
[What this is not, yet](#what-this-is-not-yet).

## Two irreversible things

Both are properties of the phone, not of this port, and neither can be undone.

- **Unlocking wipes the phone and destroys Sony's DRM keys** — permanently;
  relocking does not bring them back. On Xperias this degrades camera
  processing and some DRM playback even after returning to stock.
- **Anti-rollback is enforced in hardware** — a `vbmeta` whose rollback index
  is below the one the device has stored puts it in the AVB red state ("Your
  device is corrupt"), and the verification-disable flags do not exempt it. A
  phone that has taken an OTA carries different indexes on its two slots, here
  1772323200 on a against 1777593600 on b, so even the spare slot's own stock
  `vbmeta` is refused. `try-kernel.sh` only ever flashes the active slot's
  `vbmeta`, with the hashtree and verification flags set.

## What the phone needs

Every round assumes all of this, and `try-kernel.sh` checks what it can.

- **An unlocked bootloader** — `fastboot getvar unlocked` is the only
  authority. A GSI rewrites the lock properties Android reports.
- **An Android that boots on one slot** — the fallback every failed round
  lands back on. It has to have marked its slot successful
  (`fastboot getvar slot-successful:b`), and `try-kernel.sh` refuses to flash
  otherwise; it boots that slot once to set the flag if it has to.
- **A recovery with root adb** — TWRP or LineageOS recovery, in their own
  `recovery_a` and `recovery_b` partitions. The backup and the boot log are
  read from there. Recovery borrows its device tree and part of its ramdisk
  from `vendor_boot`, so it only comes up on a slot that still has Sony's.
- **A backup of both slots** in `out/device-dump-root/stock/` — what
  `try-kernel.sh` takes the `vbmeta` from and what `--restore` writes back.
- **An SD card** — the rootfs lives on it, a choice the owner made on
  2026-10-05, and the boot log lives in a raw region past its first 32 GiB.
  The log hook knows the owner's card by its exact size, `CARD_SECTORS` in
  `scripts/bootlog.py`; any other card takes the rootfs but gets no boot log
  until that is changed.
- **adb and fastboot on the host** — not in the container, which cannot claim
  the phone's USB interfaces; [05-status.md](05-status.md) has why.

## The first time

The steps that happen once per phone, in order. The unlock is the one this
project has not run.

1. **Check the phone** — with Android up and USB debugging on. Read-only, and
   no root needed: it confirms the phone is a `pdx246` on `parrot`, reports
   the active slot, and says what it can about the lock.

   ```sh
   scripts/device-probe.sh
   ```

2. **Unlock** — turn on OEM unlocking in Developer options, get the code from
   <https://developer.sony.com/open-devices/unlock-bootloader> with the IMEI
   from `*#06#`, and keep the IMEI out of this repository.

   ```sh
   adb reboot bootloader
   fastboot oem unlock 0x<YOUR_CODE>
   ```

3. **Back up both slots** — from recovery, where adb is root. This `dd`s
   `boot`, `vendor_boot`, `dtbo`, `vbmeta` and `vbmeta_system` of both slots
   into `out/device-dump-root/stock/`, along with the live device tree and the
   rest of what [06-mainline.md](06-mainline.md) is written against. It writes
   nothing to the phone. The only other way back is a firmware download for
   the exact model (XperiFirm, Newflasher), which this project has never
   needed.

   ```sh
   adb reboot recovery
   OUT=out/device-dump-root scripts/device-collect.sh
   ```

4. **Build** — the kernel, the boot images and the rootfs image, as
   [03-build.md](03-build.md) describes, then `scripts/verify-bootimg.py`.

## Putting the rootfs on the card

The rootfs is written from the phone's own initramfs over the USB cable, so the
card never has to come out.

1. **Stop in the initramfs** — a round without `FULLBOOT=1` flashes the spare
   slot and stops at `pmos.debug-shell`, with telnet on `172.16.42.1`.

   ```sh
   scripts/try-kernel.sh
   ```

2. **Look** — finds the card on the phone and says what it would do. It
   refuses anything that is not the SD card, and an image with no ext4 in it.

   ```sh
   scripts/sdcard-install.sh
   ```

3. **Write** — partitions the card with a `p1` that ends at 16 GiB, below the
   log region, streams the image into it and checks the UUID it reports.
   `--keep-table` writes into the `p1` already there instead.

   ```sh
   scripts/sdcard-install.sh --yes
   ```

## Booting the system

A `STAYUP=1` round is a boot for using the phone rather than a test: the whole
system, with nothing in the initramfs left to reset it. It waits for sshd and
takes a few readings over ssh.

```sh
STAYUP=1 scripts/try-kernel.sh
```

- **The shell** — `scripts/ssh.py '<command>'` logs in as `user`, password
  `147147` unless `PMOS_PASSWORD=` was set when the image was built, and its
  `-f` mode runs commands as root.
- **The screen** — Plasma Mobile comes up on the panel.
- **Back to fastboot** — `scripts/to-fastboot.sh` asks the kernel for a
  bootloader reboot, the same mechanism `adb reboot bootloader` uses. Run it
  before the next round, which cannot reach fastboot over adb from here.

## What this is not, yet

Two things about the setup above that a real install would change.

- **Every boot is borrowed** — nothing marks the slot successful, so each boot
  of it, a reboot from the shell included, spends one of the bootloader's
  seven attempts, and once they are spent it boots the stock slot.
  `fastboot --set-active` resets the count. A permanent install needs the slot
  marked, which is the boot control HAL's job on Android, and a decision
  between the card and `userdata`; both are open.
- **The two kernels need opposite `dtbo` partitions** — on mainline the spare
  slot gets one the bootloader cannot read, from `scripts/no-dtbo.py`: our
  tree is complete and has no `__symbols__`, so any overlay that matched would
  fail to apply, a failed overlay red-states this phone, and an *empty* `dtbo`
  is not enough to stop ABL trying. On the downstream kernel the spare slot
  keeps stock's, whose `parrot-qrd` overlay is where the board detail lives.
  `try-kernel.sh` picks by the installed kernel, and `--restore` puts stock's
  back either way.

## Kernel rounds

Every kernel change is tested the same way, unattended, as a `try-kernel.sh`
round on the spare slot. [07-devloop.md](07-devloop.md) has the round, its
modes, the queue, and how to get the phone back to fastboot.

## When a round fails

What a failed round looks like from the host, and what to do about each.

- **It panics** — `panic=60` on the command line resets the phone, each reset
  spends an attempt, and after seven the bootloader boots stock. That can take
  most of an hour and looks dead throughout; leave it alone. `try-kernel.sh`
  waits and reads the log itself.
- **It hangs** — nothing resets it. Hold Power and Volume Up until it
  vibrates, then hold Volume Up while plugging in USB, and read the log.
- **"Your device is corrupt"** — the AVB red state: the bootloader refused the
  images and our kernel never ran. Either the `vbmeta` was wrong or an overlay
  failed to apply. Restore the slot, below.
- **Reading the log** — `scripts/try-kernel.sh --log` gets into recovery from
  wherever the phone is, switching to the stock slot first if it has to, and
  decodes and clears both log regions: the card's, and `rddata` on UFS, which
  the hook falls back to when no card turns up. An empty
  region means the kernel never got far enough to write; the hook runs in the
  initramfs, so a kernel that dies before `/init` leaves nothing.
- **Not ramoops** — the region binds and the kernel writes to it, but the
  bootloader scrubs that memory before the next boot;
  [05-status.md](05-status.md) has the evidence.

## Getting in

The USB-C cable is the only way in: there is no UART brought out on this phone.

- **The initramfs** — `scripts/console.sh` waits for the USB gadget, checks
  the host got an address on `172.16.42.0/24`, and opens the telnet shell
  through `scripts/telnet.py`, since the host ships no telnet. The same shell
  is on `/dev/ttyACM*`, and `scripts/tsh.py` drives it from a script.
- **The system** — `scripts/ssh.py`, once `switch_root` has replaced telnetd
  with sshd.
- **The host side** — the network needs that address and the serial port needs
  read and write on its node. Both are changes to the host and so the owner's
  to make; `scripts/console.sh` prints the commands.

## Recovery

How to put things back, from the most common case to the one never needed.

- **The spare slot** — `scripts/try-kernel.sh --restore` writes stock's
  `vbmeta`, `dtbo`, `boot` and `vendor_boot` back to whichever slot is not
  marked successful, and makes the good one active. That slot is then exactly
  as stock left it, which on this unit is an older build that anti-rollback
  refuses, so it is a parking state rather than a second Android.
- **By hand** — the same writes from fastboot, with the bad slot's letter for
  `$bad`; then `fastboot --set-active` to the good one.

  ```sh
  for p in vbmeta dtbo boot vendor_boot; do
      fastboot flash "${p}_$bad" "out/device-dump-root/stock/${p}_$bad.img"
  done
  ```

- **A red state** — the phone still reaches fastboot with the button combo, so
  either of the above fixes it.
- **Both slots broken** — reflash Sony's firmware for the exact model. Nothing
  in this project writes the stock slot, so this has never been needed.
- **What is never written** — `super`, `userdata`, the bootloader chain and the
  partition table. A round writes `boot`, `vendor_boot`, `dtbo` and `vbmeta` of
  the spare slot, and the log hook writes only the card's raw region and
  `rddata`.
