# Status

Last updated: 2026-10-05. **The device has never been booted with any of this.**

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
| Debug UART at `0x98c000`, `qcom,msm-geni-console`, `status = "ok"` | Verified | Decompiled our own `parrot.dtb` |
| `chosen/bootargs` already asks for `console=ttyMSM0,115200n8` | Verified | Same DTB; `stdout-path` points at the same node |
| ramoops at `0xffd00000`, 768K (256K console, 256K pmsg) | Verified | `ramoops_region@ffd00000`, compatible `"ramoops"`, no `no-map` |
| `qcom,msm-id = <0x219 0x10000 0x265 0x10000>`, `board-id = <0 0>` | Verified | Same DTB; this is what the bootloader matches `dtbo` against |
| `parrot-qrd-overlay.dtbo-base` lists `parrot.dtb` first | Verified | Vendor `dts/vendor/qcom/Makefile:143` |

## This port

| Item | Confidence | Notes |
|---|---|---|
| pmbootstrap runs rootless with the three patches | **Verified** | Native chroot builds; `pmb checksum` succeeds. Three, not two: `/dev` in a userns, `mount`/`umount` in a userns, and not unregistering a binfmt handler we did not register |
| Kernel aport layout (two tarballs, DT into `dts/vendor`) | **Verified** | `dts/Makefile` keys off `vendor/Makefile`, and the tree configures and compiles from it |
| Only `parrot.dtb` is built, not Qualcomm's whole DT release | **Verified** | `make dtbs` emits exactly one `DTC` line. The stock `audio/` and `camera/` trees cannot build at all without headers from the out-of-tree `sm6450-modules` repo |
| `pmos.config` survives `olddefconfig` intact | **Verified** | Every `=y`, `=n` and "is not set" in it was read back out of the generated `.config` |
| Debug UART is builtin, so `earlycon` can work | **Verified** | `MSM_GENI_SE`, `SERIAL_MSM_GENI`, `SERIAL_MSM_GENI_CONSOLE` all `=y` in the generated config |
| Kernel builds with Alpine clang | Unverified | In progress; `-Werror` stripped, LTO/CFI off |
| `pmos.config` satisfies `pmb kconfig check` | Unverified | Written against `kconfigcheck.toml`, not yet run |
| boot-deploy emits usable `boot.img` + `vendor_boot.img` | Reasoned | boot-deploy's v4 path does exactly this |
| `deviceinfo_dtb="vendor/qcom/parrot"` resolves | Reasoned | `dtbs_install` path vs boot-deploy's `find_dtb` glob |
| Leaving stock `dtbo` in place gives the right DT | Reasoned | This is what stock does; untested with *our* base |
| The 88 first-stage modules are all in-tree | **Verified** | Every name matched to an `obj-$(CONFIG_...)` target in the kernel Makefiles. 88, not 90: `msm-geni-se` and `msm_geni_serial` are builtin now and have no `.ko` |
| USB module names (`dwc3-msm`, `phy-msm-*`) | Verified | `drivers/usb/{dwc3,phy}/Makefile`: `CONFIG_USB_DWC3_MSM` -> `dwc3-msm.o`, `CONFIG_MSM_HSUSB_PHY` -> `phy-msm-snps-hs.o`, `CONFIG_USB_MSM_SSPHY_QMP` -> `phy-msm-ssusb-qmp.o`. `parrot_GKI.config` enables only these two PHYs (no eUSB2, no QUSB) |
| Every kernel-side prerequisite for the USB gadget is present | **Verified** | `USB_DWC3=y` with `USB_DWC3_DUAL_ROLE=y` (not host-only), and `USB_CONFIGFS_{ACM,NCM,RNDIS,MASS_STORAGE}` all `=y`. The glue (`dwc3-msm`) and the two PHYs are modules and are in `modules-initfs` |
| USB gadget actually enumerates on the device | Guess | Config is necessary, not sufficient. The likely failure is Type-C role detection: `TYPEC_QCOM_PMIC` is not set, so the gadget depends on the PMIC/charger driver reporting over extcon |
| `pmos.debug-shell` gives telnet on `172.16.42.1:23` and a CDC-ACM port | Verified | `postmarketos-initramfs/init_functions.sh`: `telnetd -b "${HOST_IP}:23"`, `acm.usb0`, `ncm.usb0` with `rndis.usb0` fallback |
| Flashing procedure in `04-flashing.md` | Reasoned | Derived from AVB behaviour; **not executed** |

## Known gaps

- **Display.** The panel driver is in the out-of-tree `sm6450-modules`
  repository, which this port does not build. First boots are blind by design.
- **Vendor device trees that need `sm6450-modules`.** The same repository also
  owns the dt-bindings headers that Qualcomm's `audio/` and `camera/` device
  trees include, so those cannot be built here at all. We sidestep it by
  building only the base `parrot.dtb`, which is the one we boot; the rest of
  the parrot family is not ours. If `sm6450-modules` is ever built, the
  three-line `vendor/qcom/Makefile` written in `prepare()` is what to revisit.
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
   if not, read ramoops.
5. Read `/sys/fs/pstore/console-ramoops*` after the next boot. This is the
   cheapest instrument we have and it needs no cable: the region is reserved in
   the DTB we build, `PSTORE_RAM` is builtin, and 256K of console ring survives
   a reboot. Serial on `0x98c000` is the fallback, and it needs hardware
   access to the USB-C SBU pins that nobody has yet.
6. Only then: build `sm6450-modules` for display.
