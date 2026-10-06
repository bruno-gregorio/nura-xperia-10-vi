#!/bin/sh
# Check the built kernel package against what the device package promises.
#
# Everything here is a question the build can answer but the APKBUILD cannot:
# whether the DTB we boot is in the package, and whether every module named in
# modules-initfs was actually built.
#
#   scripts/verify-build.sh [downstream|mainline]
#
# There are two kernels now and they promise different things, so the script
# has to be told which one it is looking at - or it works it out from whichever
# apk is there, which is right whenever only one has been built.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PKGS="$ROOT/.pmb/work/packages"
APORTS="$ROOT/aports/device/testing"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Keep these in step with deviceinfo_dtb_* and the two modules-initfs.* files
# in device-sony-pdx246; everything below is derived from them.
case "${1:-auto}" in
downstream) kernel=downstream ;;
mainline)   kernel=mainline ;;
auto)
	kernel=
	for k in downstream mainline; do
		case $k in
		downstream) pkg=linux-sony-pdx246 ;;
		mainline)   pkg=linux-postmarketos-qcom-sm6450 ;;
		esac
		if [ -n "$(find "$PKGS" -name "$pkg-*.apk" ! -name '*-dev-*' 2>/dev/null)" ]; then
			[ -z "$kernel" ] || { echo "both kernels are built - say which: $0 [downstream|mainline]" >&2; exit 1; }
			kernel=$k
		fi
	done
	[ -n "$kernel" ] || { echo "no kernel apk under $PKGS - build one first" >&2; exit 1; }
	;;
*) echo "usage: $0 [downstream|mainline]" >&2; exit 2 ;;
esac

case $kernel in
downstream)
	pkg=linux-sony-pdx246
	dtb=vendor/qcom/parrot.dtb ;;
mainline)
	pkg=linux-postmarketos-qcom-sm6450
	dtb=qcom/sm6450-sony-xperia-columbia-pdx246.dtb ;;
esac
modules_initfs="$APORTS/device-sony-pdx246/modules-initfs.$kernel"

apk=$(find "$PKGS" -name "$pkg-*.apk" ! -name '*-dev-*' | head -1)
[ -n "$apk" ] || { echo "no $pkg apk under $PKGS - build it first" >&2; exit 1; }
echo "==> $kernel: $apk"
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
echo "==> device tree (deviceinfo_dtb_$kernel=${dtb%.dtb})"
dtbpath="$WORK/boot/dtbs/$dtb"
if [ -f "$dtbpath" ]; then
	printf '    %s  %s bytes\n' "${dtbpath#$WORK/}" "$(wc -c < "$dtbpath")"
	# Downstream: a base DTB with no overlay applied still has to carry the
	# board ids the bootloader matches the stock dtbo against. Mainline: the
	# compatible is how anyone tells at a glance that this is our tree and not
	# a Qualcomm reference one.
	if command -v fdtget >/dev/null 2>&1; then
		printf '    compatible: %s\n' "$(fdtget -t s "$dtbpath" / compatible 2>/dev/null || echo '?')"
	fi
else
	echo "    MISSING $dtbpath"; fail=1
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
	# Sony's 5.10 ships plain .ko; our mainline config has
	# CONFIG_MODULE_COMPRESS_ZSTD, so the files are .ko.zst. Matching only
	# '*.ko' made this print "0 modules built" and then "all present" for a
	# package containing 427 of them - vacuously true, and exactly the kind of
	# silent pass this script exists to prevent. modules.builtin below needs no
	# such treatment: it always lists uncompressed names.
	find "$moddir" -name '*.ko' -o -name '*.ko.gz' -o -name '*.ko.xz' \
		-o -name '*.ko.zst' \
		| sed 's|.*/||; s|\.\(gz\|xz\|zst\)$||; s|\.ko$||' \
		| tr '-' '_' | sort -u > "$WORK/built.txt"
	printf '    %s modules built\n' "$(wc -l < "$WORK/built.txt")"
	grep -v '^[[:space:]]*#\|^[[:space:]]*$' \
		"$modules_initfs" \
		| tr '-' '_' | sort -u > "$WORK/wanted.txt"
	printf '    %s modules requested in the initramfs\n' "$(wc -l < "$WORK/wanted.txt")"
	# A name can be absent because it is builtin, which is fine for the kernel
	# but still breaks mkinitfs - there is no .ko for it to find. Separate the
	# two: builtin means "drop it from the list", absent means "the build is
	# wrong".
	builtin=$(dirname "$(find "$moddir" -name modules.builtin | head -1)")
	sed -n 's|.*/\([^/]*\)\.ko$|\1|p' "$builtin/modules.builtin" \
		| tr '-' '_' | sort -u > "$WORK/builtin.txt"
	missing=$(comm -23 "$WORK/wanted.txt" "$WORK/built.txt")
	if [ -n "$missing" ]; then
		echo "$missing" | sort -u > "$WORK/missing.txt"
		isbuiltin=$(comm -12 "$WORK/missing.txt" "$WORK/builtin.txt")
		absent=$(comm -23 "$WORK/missing.txt" "$WORK/builtin.txt")
		if [ -n "$isbuiltin" ]; then
			echo "    BUILTIN, so there is no .ko - remove from modules-initfs:"
			echo "$isbuiltin" | sed 's/^/      /'
			fail=1
		fi
		if [ -n "$absent" ]; then
			echo "    NOT BUILT AT ALL:"
			echo "$absent" | sed 's/^/      /'
			fail=1
		fi
	else
		echo "    all present"
	fi
fi

echo
[ "$fail" -eq 0 ] && echo "==> OK" || echo "==> problems above"
exit "$fail"
