# Fast iteration on kernel builds

How to test many kernels an hour with no hands on the device. The target is a
single command an agent can run unattended, which returns a verdict and a log
for every build and recovers by itself when a kernel does not boot; the short
answer to "do I have to reboot and re-flash by hand" is **no for the common
case, and the exceptions are bounded**, and most of the win comes from three
cheap changes rather than anything exotic.

## Why the earlier estimates were the wrong unit

Timelines of "weeks" in [06-mainline.md](06-mainline.md) priced human
transcription throughput. That is the wrong unit here, and the correction
changes what to optimise.

- **Transcription is near-free and mechanically checkable.** The 119/119 clock
  offset comparison that identified SM4450 generalises into a test: for every
  clock in a hand-written `gcc-sm6450.c`, assert the register offset matches
  `gcc-parrot.c`. A whole class of typo-shaped bugs becomes impossible to ship.
- **What does not compress is wall-clock per device test**, and the number of
  tests needed for things no static check can know: regulator sequencing, panel
  timing, probe order.
- **So the metric to optimise is cycles per hour, hands-free**, not
  person-hours. Everything below serves that.

## Tiers

Each tier is a place a build can fail. A failure caught in a lower tier costs
no device time, so work is pushed down as far as it will go.

### Tier 0 — static, no device, seconds

1. **Table equivalence.** Implemented in `scripts/check-tables.sh`. Compares a
   written driver against the vendor source it was derived from, generalising
   the SM4450 proof; catches transposed digits, dropped entries, a mux function
   in the wrong slot. Clock offsets are compared exactly; pinctrl allows
   mainline's convention of collapsing downstream's per-signal names into one
   function group per slot. Its self-test is the known-good ravelin/sm4450
   pair, which must come out at 119 clocks and 136 pins, all agreeing.

   ```sh
   scripts/check-tables.sh clk     gcc-parrot.c     gcc-sm6450.c
   scripts/check-tables.sh pinctrl pinctrl-parrot.h pinctrl-sm6450.c
   ```

2. **Device tree validation.** `make dt_binding_check` and `make dtbs_check`
   against the bindings, plus `W=1` on the drivers.
3. **DTB differential.** Implemented in `scripts/check-dt.py`. Decompile the
   built DTB and check every address and interrupt in it against the tree the
   device actually boots. The reference turned out to be better than this plan
   assumed: not the stock `parrot.dtsi` but `/proc/device-tree` read off the
   running stock Android, which is the resolved tree for this exact board.
   A deliberate deviation passes only if it is named on the command line, so
   the list of them stays honest.

   ```sh
   out/kbuild/scripts/dtc/dtc -I fs -O dts \
       out/device-dump-root/devicetree/base > live.dts
   scripts/check-dt.py --allow 0xf100000=tlmm-rebase ours.dts live.dts
   ```
4. **Package shape.** Already implemented in `scripts/verify-build.sh`: the DTB
   we boot is present, and every module named in `modules-initfs` was built.

### Tier 1 — build, no device, minutes

1. **Incremental out-of-tree build.** Keep one warm kernel tree with `O=` and
   `ccache` and run `make` directly, not through `abuild`, which re-extracts
   the tarball every time.
2. **Repack only the boot images.** A kernel change never changes the rootfs.
   Rebuilding or reflashing the 16 GiB `userdata` image per iteration is the
   single largest avoidable cost in the naive loop.

### Tier 2 — device, hands-free, the normal case

1. **Known-good system is the harness.** One slot holds a system that boots
   reliably. Test kernels never touch it. When a test kernel dies, the device
   returns here, and *this* system reads the dead kernel's log.
2. **ramoops is the instrument.** `parrot.dtb` reserves 768 K at `0xffd00000`
   with 256 K of console ring, and `PSTORE_RAM` is builtin. The previous boot's
   console survives a reset, so a kernel that never reached USB still produces
   a full log, retrieved automatically by the next boot.
3. **Failures must self-heal.** A panic currently waits forever for a human.
   `panic=10` on the cmdline turns it into a reboot into the known-good system
   with the panic in ramoops. The Qualcomm APPS watchdog covers hangs that
   never reach the panic handler.
4. **A non-interactive boot profile.** `pmos.debug-shell` deliberately stops
   and waits for a person, which is correct for the first boot and wrong for
   every automated one. The automated profile collects and reboots instead.

### Tier 3 — reboot-free, if it works

1. **kexec from a running system.** Load a new kernel over the network and jump
   to it with no bootloader and no fastboot. This is the fastest possible loop
   and the least certain: arm64 kexec is upstream and has been used on
   Snapdragons, but Qualcomm's hypervisor and the remoteproc teardown are where
   it tends to fail.

### Tier 4 — one-time hardware, removes the last manual step

1. **UART on the USB-C SBU pins.** The port at `0x98c000` is already configured
   with `earlycon`. A breakout cable gives a permanent console that works for
   panics too early for ramoops, which is exactly the class of failure that
   otherwise costs a human debugging session.
2. **Switchable USB power.** A hub with per-port power control (`uhubctl`)
   automates re-enumeration. It does not power-cycle the phone, which has a
   battery, so it complements the watchdog rather than replacing it.

## The loop

The unattended cycle, once a known-good system is on one slot.

1. **Build.** Tier 1, incremental. Fail here and stop; no device involved.
2. **Run Tier 0 checks** on the output. Fail here and stop.
3. **Get the device to a known state.** Trigger `reboot bootloader` over the
   network from the known-good system, or a plain reboot for a kexec run.
4. **Load the test kernel.** RAM-boot if that works on this device, otherwise
   flash the test slot. Never both slots.
5. **Wait for a verdict, bounded.** Either the gadget enumerates and the
   automated profile reports in, or the timeout expires.
6. **Collect.** `dmesg` from the test kernel if it got that far; otherwise the
   known-good system's `/sys/fs/pstore/console-ramoops-0` after the reset.
7. **Classify and archive.** Write a machine-readable verdict and the logs
   under `out/`, keyed by the build. An agent needs a deterministic
   pass/fail/timeout primitive more than it needs pretty output.
8. **Return to known-good** and leave the device ready for the next cycle.

## Rules

Invariants that keep an unattended loop from destroying the device. These are
the reasons the loop is safe to run without watching it.

- **Never flash `dtbo` while iterating on the downstream kernel.** The stock
  `parrot-qrd` overlay there is what turns our base `parrot.dtb` into this
  device's tree. The mainline kernel inverts this and has to flash it: our own
  tree is complete and has no `__symbols__`, so the overlay must not be applied,
  and the only way to stop ABL applying one is to give it a dtbo it refuses to
  read. What keeps that inside the rule's intent is that it goes on the spare
  slot only, both slots are dumped byte-for-byte in
  `out/device-dump-root/stock/`, and `try-kernel.sh --restore` puts them back.
  See `scripts/no-dtbo.py`.
- **Never write a `vbmeta` that is not the device's own.** Anti-rollback is
  enforced in hardware and the disable flags do not exempt you; see
  [04-flashing.md](04-flashing.md).
- **Never touch both slots in one cycle.** The untouched slot is the only
  recovery path that needs no human.
- **Never reflash the rootfs during kernel iteration.** It did not change.
- **Every device step gets a timeout.** An unattended loop that blocks forever
  on a wedged device has turned into a manual process again.
- **Treat a RAM-booted kernel as the default and a flashed one as the
  exception.** Nothing written to flash cannot be un-written by hand.

## Exceptions

Cases that fall outside the loop, with the cheapest way out of each.

- **`fastboot boot` may not work on this device at all.** On GKI header-v4
  devices, where the DTB lives in `vendor_boot`, RAM-booting a plain `boot.img`
  gives a kernel with no device tree and no init: a black screen from an
  otherwise fine kernel. The workaround to test is a self-contained header-v2
  image carrying kernel, ramdisk and DTB together, since v2 has a `dtb` field
  the bootloader may honour in RAM-boot mode. If that fails, Tier 2 falls back
  to flashing the test slot, which is slower but still hands-free.
- **A kernel that hangs before the watchdog starts.** Nothing in software can
  recover it; the device needs a power cycle, and a phone with a battery does
  not power off when USB power is cut. This is the one genuinely physical
  exception. It is also rare, and Tier 4's UART is what diagnoses it.
- **The first boot of all.** Unlock, backups and the first interactive bring-up
  are human steps by design. [04-flashing.md](04-flashing.md) covers them, and
  the automated loop should not be built until they are done once.
- **Type-C role detection never comes up.** If no gadget ever enumerates,
  `TYPEC_QCOM_PMIC` is unset and the loop has no network path in. Fall back to
  ramoops only, which needs no USB at all.

## Confidence

What is known to work versus what the loop assumes, on the same scale as
[05-status.md](05-status.md).

- **Verified.** ramoops is reserved in the DTB we build, `PSTORE_RAM` is
  builtin, and 256 K of console ring survives a reset. A/B slots exist and
  `fastboot --set-active` switches them.
- **Reasoned.** `panic=10` converts panics into self-healing cycles. Flashing
  only `boot` and `vendor_boot` per iteration is sufficient for a kernel
  change. The known-good-system-as-harness pattern works because ramoops is
  readable from any booting system.
- **Guess.** `fastboot boot` working at all on pdx246, in any packaging. kexec
  surviving Qualcomm's hypervisor on this SoC. The APPS watchdog being enabled
  early enough to catch an early hang. Each is cheap to test and each has a
  documented fallback above.

## Where the loop actually stands

Written after the port first booted, on 2026-10-05. The tiers above were
planned before any of this ran on hardware; this section is what the device
actually does, and it corrects three of the guesses.

### What is built and used every round

- **`scripts/try-kernel.sh`** — one command for a whole round: build the boot
  images, flash the test slot, wait for the gadget, and save a harvest. This is
  the loop driver that `## Next` below used to call for.
- **`scripts/bootlog.py`** — generates the staged probe initramfs. Each stage
  is a numbered mark, so a boot that dies reports *where*, and `HANDOFF=1`
  makes the last stage `exec` into the stock second stage instead of stopping.
- **`scripts/telnet.py`** — a shell in the initramfs, before `switch_root`.
- **`scripts/tsh.py`** — the same shell for a script: runs commands there one
  at a time and waits for each to finish, which `telnet.py` fed from a pipe
  does not. `try-kernel.sh` runs a file of them with `LIVE=file` as soon as a
  round reaches the shell, so a queued round can carry its own experiment.
- **`scripts/ssh.py`** — a shell in the booted system, after it.
- **`scripts/sdcard-install.sh`** — writes the rootfs to the SD card from the
  phone's own initramfs shell, so the card never has to come out.
- **`scripts/check-tables.sh`** and **`scripts/verify-build.sh`** — the two
  Tier 0 checks, unchanged and still the first thing every round runs.
- **`scripts/check-dt.py`** — the third, written once the mainline device tree
  existed to check.
- **`scripts/clkmap.py`** — translates a vendor clock id into the mainline
  define name, because the two headers share names and not numbers. Anything
  copied out of the stock device tree goes through it.
- **`scripts/sync-kernel-patches.sh`** — exports the mainline branch out of
  the gitignored `out/linux` into `kernel/patches/` and into the kernel
  aport. `--check` fails a round that would build from a stale export.

### Three corrections to the plan above

- **ramoops was never the instrument.** Tier 2 assumed the previous boot's
  console would survive a reset and be read back by the known-good system.
  Nothing we tried produced a pstore entry on this device. What replaced it is
  a probe that writes its own progress into a flash partition it is allowed to
  write (`rddata`/`appslog`) and brings up a USB gadget as early as it can, so
  the log is readable *during* the boot rather than after it. That is a better
  instrument than ramoops anyway: it reports from a live kernel.
- **There is no shell route to fastboot.** Neither `reboot bootloader` nor any
  sysfs path gets this phone into the bootloader from a running system we
  control, so step 3 of `## The loop` does not work as written. What does work
  is the A/B retry counter: our test slot never marks itself booted, so each
  attempt decrements it, and a probe that resets as soon as it is reachable
  burns a retry in about 26 seconds instead of the probe's own 11-minute
  patience. Four to six resets reach stock Android, two to two and a half
  minutes apiece, hands-free. `fastboot --set-active` puts the counter back
  to 7.
- **The stock second stage's debug shell is fatal here, not merely
  interactive.** Tier 2 called `pmos.debug-shell` "correct for the first boot";
  on this phone its *exit* path tears the USB gadget down and nothing rebinds
  it, so releasing that shell ends the boot in silence. The probe therefore
  sets `debug_shell=n` across the handoff and keeps its own shell, which came
  up forty marks earlier, as the inspection point. [05-status.md](05-status.md)
  has the mechanism.

### The round, as it is actually run

1. `./scripts/try-kernel.sh` with `HANDOFF=1 STAGE=1`. Builds, flashes the test
   slot, waits for the gadget, saves the harvest.
2. If it boots: `scripts/ssh.py '<command>'`. Userspace is now editable in
   place — no reflash, no card removal.
3. If it does not: `scripts/telnet.py` into the probe shell and read the marks.
   The last mark reached is the answer.
4. To get back to a flashing state: burn the retry counter (reset from the
   probe shell until stock Android comes up), then `fastboot --set-active` to
   restore it.

Steps 1, 3 and 4 need no hands. Step 2 is the new one, and it is the one that
makes rootfs work cheap.

### Two kernels, one loop

Since 2026-10-06 the device package offers a choice: `-kernel-downstream`,
Sony's 5.10 tree, which boots and has UFS and display drivers, and
`-kernel-mainline`, our own 6.18, which has neither and is the point of the
project. `pmbootstrap init` picks one, and `deviceinfo_dtb`, the initramfs
module list, the USB controller name and the kernel command line all follow
the choice; "Building it" in [06-mainline.md](06-mainline.md) says why each
one differs.

Nothing about the loop changes. The same `try-kernel.sh` round flashes
whichever kernel is installed, to the same inactive slot, and recovers the
same way, because the recovery path is the bootloader's A/B retry counter and
knows nothing about what it is booting. That was the point of building the
loop before the kernel.

Two things do change:

- Switching between them needs `pmb install --zap`. Both kernel packages own
  `/boot/vmlinuz`, so installing one into a rootfs chroot that still holds the
  other stops with "trying to overwrite boot/vmlinuz owned by
  linux-sony-pdx246". That is apk behaving correctly, and it costs a rootfs
  rebuild - about two minutes - on the rounds that change kernel, and nothing
  on the rounds that do not.
- `scripts/verify-build.sh` now takes `downstream` or `mainline`, and works
  it out on its own when only one is built. Each kernel promises a different
  DTB path and a different initramfs module list, and the script checks the
  one that applies.
- The kernel source of truth moved. Downstream builds from a GitHub tarball
  with no patches of ours; mainline builds from a kernel.org tarball plus
  `sm6450-mainline.patch`, which `scripts/sync-kernel-patches.sh` writes out
  of `out/linux`. A round that changes the kernel therefore runs that script
  and then `scripts/pmb checksum linux-postmarketos-qcom-sm6450` before
  anything else, and `sync-kernel-patches.sh --check` is a Tier 0 check: it
  fails if the aport would build from a series that does not match the tree
  the work was done in.

### Reaching fastboot from a pmOS that works

The loop's route to fastboot had a hole in it that only opened once the port
started succeeding. `try-kernel.sh`'s `need_fastboot()` assumes adb: either
stock Android is up, or the experiment failed, burned the retry counter and
fell back to stock, where adb is waiting. Both cases end in
`adb reboot bootloader`.

A pmOS that boots and stays up is neither. It has no adbd, and there is no
sanctioned way to ask this kernel for the bootloader - the restart reason lives
in a PMIC SDAM register, which was located and is writable but which this
project is not authorised to poke. So the loop stalled on its own success: the
phone sat up for twenty-one hours with a finished mainline kernel on the host
and nothing able to flash it.

`scripts/to-fastboot.sh` closes it. It tries fastboot, then adb, then asks the
kernel: `systemctl reboot --reboot-argument=bootloader` hands `reboot(2)` the
string `bootloader`, and the `qcom,reboot-reason` driver bound to the live tree
turns that into the restart reason the boot chain reads. Fifteen seconds from a
running pmOS to `fastboot devices` answering, which is the same mechanism
`adb reboot bootloader` uses on stock. The script is safe to call at the top of
any round whatever the device is doing.

If that is ever refused it falls back to burning the slot's retry counter, which
also works - our slot never reports its boot successful, so every attempt at it
decrements the counter and nothing resets it, and slot a was measured dropping
from 7 retries to 1 over a handful of reboots - it is just six or seven rounds
slower. Two spellings that do not work are recorded in
[05-status.md](05-status.md) so nobody spends an afternoon on them again:
`systemctl reboot bootloader`, and writing `bootonce-bootloader` into the BCB
at offset 0 of `misc`.

With this the loop no longer has a hand in it on the rounds that *succeed*,
which is the half that was missing. The rounds that fail were already
hands-free, through the fallback to stock.

### What is still missing

- **Self-healing on panic.** `panic=5` is on the command line, but a kernel
  that hangs without panicking still waits out a timeout. The in-memory
  watchdog in the probe covers the stages it spans and nothing before them.
- **Reboot-free iteration.** kexec is untested; see Tier 3.
- **A verdict file.** Rounds are read by a human (or an agent) looking at the
  harvest, not by a program. A machine-readable pass/fail/timeout per build is
  still worth writing, and step 7 of `## The loop` describes it.
- **UART.** Still the only thing that would diagnose a hang before the probe's
  first mark — and on this SoC the console pins are not brought out at all, so
  Tier 4 is harder here than it looks. See [06-mainline.md](06-mainline.md).

## Related

- [04-flashing.md](04-flashing.md) — the manual path, the AVB hazard, and every
  way into a device with no display. Read for recovery procedures.
- [06-mainline.md](06-mainline.md) — what the iteration is *for*, and the
  static-verification trick this strategy generalises.
- [05-status.md](05-status.md) — the confidence ledger these claims feed into.
