# Fast iteration on kernel builds

How this port tests many kernels a day with no hands on the phone. Writing the
code was never the expensive part; device time is, and what a static check can
never know (regulator sequencing, panel timing, probe order) still has to be
asked of the hardware. So the measure is rounds per hour, unattended, and every
failure that can be caught before the phone is caught there.

## Before the phone

Checks that cost no device time, in the order a round runs them.

- **Register tables** — `scripts/check-tables.sh` compares a written clock or
  pinctrl driver against the vendor source it came from, offset by offset.
  Its self-test is the ravelin/sm4450 pair, which has to agree on 119 clocks
  and 136 pins.

  ```sh
  scripts/check-tables.sh clk     gcc-parrot.c     gcc-sm6450.c
  scripts/check-tables.sh pinctrl pinctrl-parrot.h pinctrl-sm6450.c
  ```

- **The device tree against the live one** — `scripts/check-dt.py` checks
  every address and interrupt in our tree against `/proc/device-tree` as stock
  Android booted it, the resolved tree for this exact board. A deliberate
  difference passes only when it is named on the command line.

  ```sh
  out/kbuild/scripts/dtc/dtc -I fs -O dts \
      out/device-dump-root/devicetree/base > live.dts
  scripts/check-dt.py --allow 0xf100000=tlmm-rebase ours.dts live.dts
  ```

- **Bindings** — `make dt_binding_check` and `make dtbs_check`, plus `W=1` on
  the drivers.
- **The patch export** — `scripts/sync-kernel-patches.sh --check` fails when
  the kernel aport would build from patches that no longer match the branches
  in `out/linux`.
- **The package** — `scripts/verify-build.sh [downstream|mainline]`: the DTB
  we boot is in the package, and every module `modules-initfs` names was
  built.

## A round

`scripts/try-kernel.sh` is a whole round in one command, and it runs from a
copy of itself, so the script can be edited while a round is going.

1. **Reach fastboot** — over adb from Android or recovery, by itself. From a
   running postmarketOS that is `scripts/to-fastboot.sh`'s job.
2. **Make sure there is a way back** — the active slot has to be marked
   successful. If it is not and the other one is, the round switches to it and
   boots it once first.
3. **Build the images** — the installed kernel's `vendor_boot` with the right
   device tree for it, `/init` patched for this phone's USB, the log hook from
   `scripts/bootlog.py`, and the command line edited in the header; the active
   slot's `vbmeta` with the disable flags; and the `dtbo` the kernel needs.
4. **Flash the spare slot and boot it** — `--set-active` resets its retry
   counter to seven.
5. **Wait, and say what happened** — the `RESULT` line is one of: our kernel
   on adb, the USB gadget up, a fallback to the stock slot, the bootloader
   dropping to fastboot, or nothing in the time allowed. A gadget gets
   harvested or, on a full boot, the round's commands over ssh; a fallback gets
   its log read straight away.

### Modes

Environment variables pick what a round flashes and does. The comments next to
the code that reads each one say more.

- **No mode** — stops at `pmos.debug-shell` in the initramfs and harvests over
  telnet into `out/probe-harvest.txt`. `LIVE=file` then runs a plan's own
  commands there through `scripts/tsh.py`, into `out/live.txt`.
- **`FULLBOOT=1`** — boots the whole system and runs `LIVE` over ssh through
  `scripts/ssh.py` instead. The initramfs's log hook and USB watchdog keep
  running past `switch_root` and reset the phone unless a host holds it, so
  the round holds it while its commands run.
- **`STAYUP=1`** — the whole system with no hook and no watchdog, for using
  the phone rather than testing it; see [04-flashing.md](04-flashing.md).
- **`CMDLINE_ADD` and `CMDLINE_DEL`** — edit the kernel command line in the
  `vendor_boot` header rather than rebuilding the package; deletions go first,
  and `CMDLINE_DEL` takes globs. What turns out to matter goes into
  `kernel-cmdline.mainline.conf` before it is believed.
- **`DTB=path`** — another device tree, for bisecting the one we wrote: a
  `dtc` run, against minutes for a kernel build.
- **`STAGE=1`, `PROBE=1`, `MARKS`, `BOOTLOG=0`** — bring-up probes for a kernel
  that dies before anything else can report. `STAGE=1` loads the modules one
  at a time; `PROBE=1` only reboots, so the retry counter says whether
  userspace was reached; `MARKS` numbers the init's steps into the reset
  timing; `BOOTLOG=0` leaves the log hook out, to tell a kernel that fails on
  its own from one the hook broke.
- **`WAIT`** — seconds to wait for a result, 2100 by default.

### Reading a round

What a round leaves behind, and where.

- **The run log** — `out/try-kernel/run-NAME.log` for a queued round.
- **The boot log** — `scripts/try-kernel.sh --log` reads the kernel's ring
  buffer back from the SD card's log region, or from `rddata` when no card
  turned up, and clears both. It gets into recovery from wherever the phone
  is. Every attempt's record lands in `out/try-kernel/bootlog-card-*.txt`, and
  each carries the round's id on its command line, so an old record cannot be
  mistaken for a new one.
- **The live session** — `out/probe-harvest.txt` and `out/live.txt`.

## Queues

`scripts/queue.sh <plan>` runs rounds back to back. A plan is a shell fragment
that calls `round NAME VAR=value ...` per round and can branch on
`ROUND_RESULT` and `ROUND_TOTAL`. It reads each round's logs before starting
the next, waits up to three hours for a phone that went quiet, and stops
rather than go on without it. It logs to `out/try-kernel/queue-*.log`. Start
it detached, or it dies with the session that started it:

```sh
setsid scripts/queue.sh plan.sh > /dev/null 2>&1 < /dev/null &
```

## Getting the phone back

Every round needs fastboot, and there are three ways the phone can be sitting.

- **In Android or recovery** — `adb reboot bootloader`, which `try-kernel.sh`
  does itself.
- **In a running postmarketOS** — `scripts/to-fastboot.sh` asks the kernel:
  `systemctl reboot --reboot-argument=bootloader` reaches the restart-reason
  driver the boot chain reads, about fifteen seconds in all. If that is ever
  refused, it falls back to rebooting until the retry counter runs out.
- **Hung** — nothing in software reaches it. Hold Power and Volume Up until it
  vibrates, then Volume Up while plugging in USB.

The retry counter is what makes failures hands-free. Our slot never marks
itself successful, so each attempt at it spends one of seven, and when they are
gone the bootloader boots the stock slot, where adb is waiting. Seven is the
most the counter holds: it is three bits of the partition attributes in the
GPT, and lowering it would mean writing the partition table, which this project
never does.

## Rules

What keeps an unattended loop from damaging the phone.

- **One slot per round** — the stock slot is the only way back that needs no
  hands, so nothing writes it.
- **Only the device's own `vbmeta`** — the active slot's, with the flags set;
  anti-rollback refuses anything older, see [04-flashing.md](04-flashing.md).
- **The `dtbo` follows the kernel** — a `dtbo` the bootloader cannot read on
  mainline, stock's on downstream; [04-flashing.md](04-flashing.md) has why.
  Both slots are backed up byte for byte, and `--restore` puts stock's back.
- **The rootfs is not reflashed for a kernel round** — it did not change.
  Anything in it is edited over ssh, and `scripts/sdcard-install.sh` rewrites
  the card when a clean slate is wanted.
- **Every device step has a timeout** — a loop that blocks on a wedged phone
  has turned back into a manual process.

## What the hardware ruled out

Four things the plan assumed before anything ran, each tried on the device and
each recorded in [05-status.md](05-status.md).

- **RAM boot** — the bootloader refuses `fastboot boot` outright, so every
  round costs a flash.
- **ramoops** — the region binds and the kernel writes to it, but the
  bootloader scrubs that memory before the next boot. The log hook and the
  card replaced it.
- **A UART** — none is brought out on this phone.
- **Continuing out of the debug shell** — releasing `pmos.debug-shell` tears
  down the USB gadget and nothing rebinds it, so the boot goes on in silence.
  That is why a full boot leaves the debug shell off rather than going through
  it.

## Two kernels, one loop

The device package offers Sony's 5.10 kernel as a reference and our own 6.18
as the point of the project; `pmbootstrap init` picks one. The loop does not
care which: the same round flashes whichever is installed and recovers the same
way. Three things do differ.

- **Switching needs `pmb install --zap`** — both kernel packages own
  `/boot/vmlinuz`, so apk refuses to put one over the other in the same rootfs
  chroot.
- **Different promises** — each kernel has its own DTB path, initramfs module
  list and command line, and `scripts/verify-build.sh` checks the one that
  applies.
- **Different sources** — downstream builds from Sony's tarball unchanged.
  Mainline builds from a kernel.org tarball plus one squashed patch per layer,
  which `scripts/sync-kernel-patches.sh` writes out of `out/linux`; a round
  that changes the kernel runs that and
  `scripts/pmb checksum linux-postmarketos-qcom-sm6450` first.

## What is still missing

Gaps in the loop, none of them blocking.

- **A hang before the log hook** — needs the buttons and leaves nothing behind.
  Only a console would diagnose it, and there is none.
- **A verdict a program can read** — `queue.sh` branches on the `RESULT` line,
  but what a round found is still read by a person or an agent.
- **Reboot-free rounds** — kexec from a running system is untested, and
  Qualcomm's hypervisor and remoteproc teardown are where it tends to fail.

## Related

- [04-flashing.md](04-flashing.md) — installing, booting the system, getting
  in, and recovery.
- [06-mainline.md](06-mainline.md) — what the rounds are for.
- [05-status.md](05-status.md) — the record each round's findings go into.
