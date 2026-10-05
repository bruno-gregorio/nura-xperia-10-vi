#!/bin/sh
# Check the built kernel package against what the device package promises.
#
# Everything here is a question the build can answer but the APKBUILD cannot:
# whether the DTB we boot is in the package, and whether every module named in
# modules-initfs was actually built. Run it after `pmb build linux-sony-pdx246`.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PKGS="$ROOT/.pmb/work/packages"
APORTS="$ROOT/aports/device/testing"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

apk=$(find "$PKGS" -name 'linux-sony-pdx246-*.apk' ! -name '*-dev-*' | head -1)
[ -n "$apk" ] || { echo "no linux-sony-pdx246 apk under $PKGS - build it first" >&2; exit 1; }
echo "==> $apk"
tar -xzf "$apk" -C "$WORK" 2>/dev/null || true

fail=0

echo
echo "==> kernel image"
if [ -f "$WORK/boot/vmlinuz" ]; then
	printf '    boot/vmlinuz  %s bytes\n' "$(wc -c < "$WORK/boot/vmlinuz")"
else
	echo "    MISSING boot/vmlinuz"; fail=1
fi

echo
echo "==> device tree (deviceinfo_dtb=vendor/qcom/parrot)"
dtb="$WORK/boot/dtbs/vendor/qcom/parrot.dtb"
if [ -f "$dtb" ]; then
	printf '    %s  %s bytes\n' "${dtb#$WORK/}" "$(wc -c < "$dtb")"
	# A base DTB with no overlay applied still has to carry the board ids the
	# bootloader matches the stock dtbo against.
	if command -v fdtget >/dev/null 2>&1; then
		printf '    compatible: %s\n' "$(fdtget -t s "$dtb" / compatible 2>/dev/null || echo '?')"
	fi
else
	echo "    MISSING $dtb"; fail=1
fi

echo
echo "==> modules-initfs vs the built module tree"
moddir=$(find "$WORK" -type d -name 'modules' -path '*lib*' | head -1)
if [ -z "$moddir" ]; then
	echo "    no lib/modules in the package"; fail=1
else
	# modprobe treats '-' and '_' as the same character, and stock's module
	# list mixes the two freely (qcom-pmu-lib next to qcom_wdt_core), so
	# compare on a normalised spelling or half the list looks missing.
	find "$moddir" -name '*.ko' -exec basename {} .ko \; \
		| tr '-' '_' | sort -u > "$WORK/built.txt"
	printf '    %s modules built\n' "$(wc -l < "$WORK/built.txt")"
	grep -v '^[[:space:]]*#\|^[[:space:]]*$' \
		"$APORTS/device-sony-pdx246/modules-initfs" \
		| tr '-' '_' | sort -u > "$WORK/wanted.txt"
	printf '    %s modules requested in the initramfs\n' "$(wc -l < "$WORK/wanted.txt")"
	missing=$(comm -23 "$WORK/wanted.txt" "$WORK/built.txt")
	if [ -n "$missing" ]; then
		echo "    NOT BUILT:"
		echo "$missing" | sed 's/^/      /'
		fail=1
	else
		echo "    all present"
	fi
fi

echo
[ "$fail" -eq 0 ] && echo "==> OK" || echo "==> problems above"
exit "$fail"
