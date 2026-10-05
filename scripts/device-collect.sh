#!/bin/sh
# Harvest what a mainline kernel port needs from the device, over adb.
#
#   scripts/device-collect.sh            collect whatever the current adb user can read
#   OUT=somewhere scripts/device-collect.sh
#
# Read-only: it runs no command that writes to the device. Everything lands
# under out/device-dump/ (gitignored), because some of it is Sony's firmware
# and none of it is ours to redistribute.
#
# Two passes. The unprivileged one works as the 'shell' user and gets the
# device topology: which platform and i2c devices exist, at which addresses,
# which remote processors, which regulators, the stock kernel config and the
# vendor module inventory. That is most of what writing mainline DT nodes
# needs.
#
# The privileged pass needs 'adb root', which on this LineageOS build is a
# toggle in Developer options ("Rooted debugging"), not a missing feature. It
# adds the four things the shell user is refused and that nothing else can
# substitute for: the live device tree, /proc/cmdline, the debugfs clock and
# regulator summaries, and dd of the boot partitions - which is also the only
# way to get a real backup without downloading firmware.
#
# Deliberately does not collect the IMEI, the serial, or anything under
# /data: none of it helps the port.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${OUT:-$ROOT/out/device-dump}

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

command -v adb >/dev/null || die "adb not found"
adb get-state >/dev/null 2>&1 || die "no device over adb (check 'adb devices')"

mkdir -p "$OUT"

# Run a command on the device, save stdout. A capture that comes back empty is
# reported rather than silently left as a zero-byte file, because on this
# device "empty" is what SELinux denial looks like from the shell user.
cap() {
	name=$1; shift
	if adb shell "$@" > "$OUT/$name" 2>"$OUT/$name.err"; then :; fi
	tr -d '\r' < "$OUT/$name" > "$OUT/$name.tmp" && mv "$OUT/$name.tmp" "$OUT/$name"
	if [ -s "$OUT/$name" ]; then
		printf '    %-28s %s\n' "$name" "$(wc -l < "$OUT/$name") lines"
		rm -f "$OUT/$name.err"
	else
		printf '    %-28s EMPTY (%s)\n' "$name" "$(tr -d '\r' < "$OUT/$name.err" | head -1 | cut -c1-48)"
		rm -f "$OUT/$name"
	fi
}

is_root() { [ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = "0" ]; }

say "device"
adb shell getprop ro.product.odm.device 2>/dev/null | tr -d '\r' | sed 's/^/    codename: /'
if is_root; then
	echo "    adb user: root - both passes will run"
else
	echo "    adb user: shell - the privileged pass will be skipped"
fi

say "identity and build"
cap getprop                 'getprop'
cap version                 'cat /proc/version'
cap soc0                    'for f in /sys/devices/soc0/*; do [ -f "$f" ] && echo "$(basename $f)=$(cat $f 2>/dev/null)"; done'

say "kernel"
# config.gz is the running kernel's own config. On this device that is a GKI
# kernel, so it is the Android baseline rather than Sony's - still the list of
# what the vendor tree expects to be enabled.
adb shell 'cat /proc/config.gz' > "$OUT/config.gz" 2>/dev/null || true
if [ -s "$OUT/config.gz" ] && gzip -t "$OUT/config.gz" 2>/dev/null; then
	gzip -dc "$OUT/config.gz" > "$OUT/config"
	printf '    %-28s %s options\n' "config" "$(grep -c '^CONFIG_' "$OUT/config" || true)"
else
	rm -f "$OUT/config.gz"
	echo "    config.gz                    EMPTY or not gzip"
fi
cap interrupts              'cat /proc/interrupts'
cap cpuinfo                 'cat /proc/cpuinfo'
cap meminfo                 'cat /proc/meminfo'
cap modules-loaded          'cat /proc/modules'
cap devices-char-block      'cat /proc/devices'
cap input-devices           'cat /proc/bus/input/devices'

say "device topology"
# The node name and register address of every platform device, which is the
# DT hierarchy by another route: /sys/firmware/devicetree is unreadable to the
# shell user but the device directory names carry the same addresses, and the
# driver symlink says what bound to each.
cap platform-devices        'for d in /sys/bus/platform/devices/*; do n=$(basename $d); drv=$(readlink $d/driver 2>/dev/null); echo "$n	${drv##*/}"; done'
cap platform-soc-tree       'find /sys/devices/platform/soc -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sed "s|.*/||" | sort'
cap i2c-devices             'for d in /sys/bus/i2c/devices/*; do n=$(basename $d); drv=$(readlink $d/driver 2>/dev/null); echo "$n	${drv##*/}	$(cat $d/name 2>/dev/null)"; done'
cap spi-devices             'for d in /sys/bus/spi/devices/*; do n=$(basename $d); drv=$(readlink $d/driver 2>/dev/null); echo "$n	${drv##*/}"; done'
cap remoteproc              'for d in /sys/class/remoteproc/*; do echo "$(basename $d)	$(cat $d/name 2>/dev/null)	$(cat $d/state 2>/dev/null)"; done'
cap regulators              'for d in /sys/class/regulator/*; do echo "$(basename $d)	$(cat $d/name 2>/dev/null)	$(cat $d/type 2>/dev/null)"; done'
cap thermal-zones           'for d in /sys/class/thermal/thermal_zone*; do echo "$(basename $d)	$(cat $d/type 2>/dev/null)"; done'
cap power-supply            'for d in /sys/class/power_supply/*; do echo "### $(basename $d)"; cat $d/uevent 2>/dev/null; done'
cap drm                     'for d in /sys/class/drm/*; do echo "$(basename $d)	$(cat $d/status 2>/dev/null)	$(cat $d/modes 2>/dev/null | head -1)"; done'
cap iio-devices             'for d in /sys/bus/iio/devices/*; do echo "$(basename $d)	$(cat $d/name 2>/dev/null)"; done'
cap net-interfaces          'ls /sys/class/net'
cap sound-cards             'cat /proc/asound/cards'
cap class-listing           'ls /sys/class'
cap bus-listing             'ls /sys/bus'

say "partitions"
cap by-name                 'for l in /dev/block/by-name/*; do echo "$(basename $l)	$(readlink $l 2>/dev/null | sed "s|.*/||")"; done'

say "vendor"
# The vendor module inventory is the single best list of what this SoC needs a
# driver for. modules.alias maps each one to the compatible strings it probes,
# which is exactly the mapping a mainline DT has to reproduce.
cap vendor-modules          'ls /vendor/lib/modules'
cap vendor-modules-alias    'cat /vendor/lib/modules/modules.alias'
cap vendor-modules-dep      'cat /vendor/lib/modules/modules.dep'
cap vendor-build-prop       'cat /vendor/build.prop'
cap vendor-init-rc          'for f in /vendor/etc/init/*.rc; do echo "### $f"; cat "$f" 2>/dev/null; done'
cap vendor-etc-listing      'ls -R /vendor/etc 2>/dev/null'
cap firmware-listing        'ls -l /vendor/firmware /vendor/firmware_mnt/image /vendor/lib/firmware 2>&1'

if is_root; then
	say "privileged pass"
	cap cmdline             'cat /proc/cmdline'
	cap iomem               'cat /proc/iomem'
	cap clk-summary         'cat /sys/kernel/debug/clk/clk_summary'
	cap regulator-summary   'cat /sys/kernel/debug/regulator/regulator_summary'
	cap pinctrl-pins        'cat /sys/kernel/debug/pinctrl/*/pins'
	cap pinctrl-mux         'cat /sys/kernel/debug/pinctrl/*/pinmux-pins'
	cap pstore-console      'cat /sys/fs/pstore/console-ramoops-0'

	say "live device tree"
	# The authoritative tree: what the bootloader actually handed the kernel,
	# base DTB plus whatever the dtbo overlay changed. Decompile with
	#   dtc -I fs -O dts out/device-dump/devicetree/base
	if adb exec-out 'tar -c -C /sys/firmware devicetree 2>/dev/null' > "$OUT/devicetree.tar" 2>/dev/null \
		&& [ -s "$OUT/devicetree.tar" ]; then
		( cd "$OUT" && rm -rf devicetree && tar -xf devicetree.tar ) \
			&& echo "    devicetree/                  $(find "$OUT/devicetree" -type f | wc -l) properties"
	else
		rm -f "$OUT/devicetree.tar"
		echo "    devicetree                   FAILED"
	fi

	say "boot partition backup"
	# This is the backup docs/04-flashing.md says needs root. Both slots, so a
	# bad flash on either can be put back.
	mkdir -p "$OUT/stock"
	slot=$(adb shell getprop ro.boot.slot_suffix 2>/dev/null | tr -d '\r_')
	echo "    active slot: ${slot:-unknown}"
	for p in boot vendor_boot dtbo vbmeta vbmeta_system; do
		for s in a b; do
			src=$(adb shell "readlink -f /dev/block/by-name/${p}_${s}" 2>/dev/null | tr -d '\r')
			[ -n "$src" ] || continue
			if adb exec-out "dd if=$src 2>/dev/null" > "$OUT/stock/${p}_${s}.img" 2>/dev/null \
				&& [ -s "$OUT/stock/${p}_${s}.img" ]; then
				printf '    %-28s %s bytes\n' "stock/${p}_${s}.img" "$(stat -c %s "$OUT/stock/${p}_${s}.img")"
			else
				rm -f "$OUT/stock/${p}_${s}.img"
				printf '    %-28s FAILED\n' "stock/${p}_${s}.img"
			fi
		done
	done
else
	say "privileged pass SKIPPED"
	cat <<'EOF'
    These need root, and nothing else substitutes for them:
      - the live device tree, the authoritative base DTB + dtbo overlay
      - /proc/cmdline, what the bootloader actually passes
      - the debugfs clock, regulator and pinctrl summaries
      - dd of boot/vendor_boot/dtbo/vbmeta, the real backup

    This build has adb root; it is off by default. On the device:
      Settings -> System -> Developer options -> Rooted debugging
    then re-run this script. 'adb root' prints what is missing if not.
EOF
fi

say "done"
echo "    $OUT"
du -sh "$OUT" 2>/dev/null | sed 's/^/    /'
echo
echo "Nothing was written to the device."
