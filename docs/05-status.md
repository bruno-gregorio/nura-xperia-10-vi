# Status

Last updated: 2026-10-04. **The device has never been booted with any of this.**

## Confidence levels

- **Verified** — read directly out of published sources, or confirmed on
  hardware by the LineageOS pdx246 port.
- **Reasoned** — follows from how the boot flow works, but nothing has
  exercised it.
- **Guess** — plausible, unconfirmed, and the first thing to suspect.

## Device facts

| Fact | Confidence | Basis |
|---|---|---|
| Codename `pdx246`, SoC SM6450, platform `parrot` | Verified | `BoardConfig.mk`, `sonyxperiadev/device-sony-pdx246` |
| SM6450 has no mainline support | Verified | No `sm6450.dtsi` in mainline; nothing on lore |
| Device runs Qualcomm's Parrot QRD reference DT | Verified | LineageOS port diffed built DTBs against stock blobs and booted it |
| Base `parrot.dtb` in `vendor_boot`, `parrot-qrd` overlay in `dtbo` | Verified | Qualcomm boot flow + LineageOS port notes |
| Boot header v4, pagesize 4096, kernel base 0 | Verified | `BoardConfig.mk` |
| AVB rollback index `1782864000` enforced in hardware | Verified | LineageOS port hit the red state and documented it |
| First-stage module list and order | Verified | `device/sony/pdx246/modules.load`, stock's own order |
| UFS 4096-byte logical blocks | Guess | Typical for the class; not confirmed for this device |
| Display 1080x2520 | Verified | Sony specs |

## This port

| Item | Confidence | Notes |
|---|---|---|
| pmbootstrap runs rootless with the two patches | **Verified** | Native chroot builds; `pmb checksum` succeeds |
| Kernel aport layout (two tarballs, DT into `dts/vendor`) | Reasoned | `dts/Makefile` keys off `vendor/Makefile`; not yet built end to end |
| Kernel builds with Alpine clang | Unverified | In progress; `-Werror` stripped, LTO/CFI off |
| `pmos.config` satisfies `pmb kconfig check` | Unverified | Written against `kconfigcheck.toml`, not yet run |
| boot-deploy emits usable `boot.img` + `vendor_boot.img` | Reasoned | boot-deploy's v4 path does exactly this |
| `deviceinfo_dtb="vendor/qcom/parrot"` resolves | Reasoned | `dtbs_install` path vs boot-deploy's `find_dtb` glob |
| Leaving stock `dtbo` in place gives the right DT | Reasoned | This is what stock does; untested with *our* base |
| The 86 first-stage modules are all in-tree | Reasoned | They are in `drivers/clk/qcom`, `drivers/pinctrl/qcom` etc. |
| USB module names (`dwc3-msm`, `phy-msm-*`) | Verified | `drivers/usb/{dwc3,phy}/Makefile`: `CONFIG_USB_DWC3_MSM` -> `dwc3-msm.o`, `CONFIG_MSM_HSUSB_PHY` -> `phy-msm-snps-hs.o`, `CONFIG_USB_MSM_SSPHY_QMP` -> `phy-msm-ssusb-qmp.o`. `parrot_GKI.config` enables only these two PHYs (no eUSB2, no QUSB) |
| USB gadget comes up in the initramfs | Guess | The whole debug plan rests on this |
| Flashing procedure in `04-flashing.md` | Reasoned | Derived from AVB behaviour; **not executed** |

## Known gaps

- **Display.** The panel driver is in the out-of-tree `sm6450-modules`
  repository, which this port does not build. First boots are blind by design.
- **GPU.** Adreno 710 on a downstream KGSL kernel. Mesa's a7xx support targets
  the mainline `msm` uAPI. Expect software rendering, if anything.
- **Modem, Wi-Fi, Bluetooth, audio, camera.** None attempted. Wi-Fi and audio
  additionally need firmware from the stock `/vendor/firmware`, which is not
  redistributable and is not packaged here.
- **No `soc-qcom-sm6450` package.** pmOS has no SoC package for this chip; the
  device package carries everything.

## Next steps, in order

1. Finish the kernel build and run `pmb kconfig check`.
2. `pmb install --no-fde --split`, confirm both boot images are produced and
   that `vendor_boot.img` actually contains the DTB
   (`unpack_bootimg --boot_img ...`).
3. Take the backups in `04-flashing.md` step 1. Do not skip this.
4. Flash and look for a USB gadget. That single observation splits the problem
   in half: if it appears, the kernel booted and the work moves to userspace;
   if not, it is pstore or serial from here.
5. Cross-check every name in `modules-initfs` against
   `.pmb/work/chroot_native/.../lib/modules` once the kernel has built. The USB
   three are confirmed from the Makefiles; the 86 inherited from stock's
   `modules.load` are stock's own filenames and should match, but a built tree
   settles it.
6. Only then: build `sm6450-modules` for display.
