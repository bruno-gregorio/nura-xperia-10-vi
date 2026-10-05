# Fast iteration on kernel builds

How to test many kernels per hour with no hands on the device. The target is a
single command that an agent can run unattended, which returns a verdict and a
log for every build, and which recovers by itself when a kernel does not boot.

The short answer to "do I have to reboot and re-flash by hand": **no for the
common case, and the exceptions are bounded.** Most of the win comes from three
cheap changes, not from anything exotic.

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

### Tier 0 — Static, no device, seconds

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
3. **DTB differential.** Decompile the built DTB and diff register bases,
   interrupts and clock ids against the stock `parrot.dtsi`. This is the
   technique the LineageOS port used to prove the device tree finding, pointed
   at our own output instead.
4. **Package shape.** Already implemented in `scripts/verify-build.sh`: the DTB
   we boot is present, and every module named in `modules-initfs` was built.

### Tier 1 — Build, no device, minutes

1. **Incremental out-of-tree build.** Keep one warm kernel tree with `O=` and
   `ccache` and run `make` directly, not through `abuild`, which re-extracts
   the tarball every time.
2. **Repack only the boot images.** A kernel change never changes the rootfs.
   Rebuilding or reflashing the 16 GiB `userdata` image per iteration is the
   single largest avoidable cost in the naive loop.

### Tier 2 — Device, hands-free, the normal case

1. **Known-good system is the harness.** One slot holds a system that boots
   reliably. Test kernels never touch it. When a test kernel dies, the device
   returns here, and *this* system reads the dead kernel's log.
2. **ramoops is the instrument.** `parrot.dtb` reserves 768 K at `0xffd00000`
   with 256 K of console ring, and `PSTORE_RAM` is builtin. The previous
   boot's console survives a reset, so a kernel that never reached USB still
   produces a full log, retrieved automatically by the next boot.
3. **Failures must self-heal.** A panic currently waits forever for a human.
   `panic=10` on the cmdline turns it into a reboot into the known-good system
   with the panic in ramoops. The Qualcomm APPS watchdog covers hangs that
   never reach the panic handler.
4. **A non-interactive boot profile.** `pmos.debug-shell` deliberately stops
   and waits for a person, which is correct for the first boot and wrong for
   every automated one. The automated profile collects and reboots instead.

### Tier 3 — Reboot-free, if it works

1. **kexec from a running system.** Load a new kernel over the network and jump
   to it with no bootloader and no fastboot. This is the fastest possible loop
   and the least certain: arm64 kexec is upstream and has been used on
   Snapdragons, but Qualcomm's hypervisor and the remoteproc teardown are where
   it tends to fail.

### Tier 4 — One-time hardware, removes the last manual step

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

- **Never flash `dtbo`.** The stock `parrot-qrd` overlay there is what turns
  our base `parrot.dtb` into this device's tree.
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

What is known to work versus what the loop assumes. Same scale as
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

## Next

The order to build this in, so that each step pays for itself immediately.

1. Finish the interactive first boot from [04-flashing.md](04-flashing.md).
   Everything here depends on knowing the device boots at all.
2. Add `panic=10` and an automated boot profile alongside the interactive one.
   Cheapest possible change, largest reduction in human waiting.
3. Test `fastboot boot` with a self-contained v2 image. One experiment that
   decides whether Tier 2 is fast or merely automatic.
4. Write the loop driver once the device behaviour above is known, rather than
   guessing at it now.

Already done: the Tier 0 table-equivalence check, which is what makes
agent-speed transcription safe to trust, and the package-shape check in
`scripts/verify-build.sh`. Both run with no device attached.

## Related

- [04-flashing.md](04-flashing.md) — the manual path, the AVB hazard, and every
  way into a device with no display. Read for recovery procedures.
- [06-mainline.md](06-mainline.md) — what the iteration is *for*, and the
  static-verification trick this strategy generalises.
- [05-status.md](05-status.md) — the confidence ledger these claims feed into.
