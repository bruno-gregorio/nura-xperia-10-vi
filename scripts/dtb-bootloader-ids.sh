#!/bin/sh
# Add the two properties the Qualcomm bootloader needs to select our device
# tree, without putting them in the device tree source.
#
#   scripts/dtb-bootloader-ids.sh <in.dtb> <out.dtb>
#
# Why this is a script and not two lines in the .dts:
#
# qcom,msm-id and qcom,board-id are not device tree. They are bootloader
# metadata. Qualcomm's boot chain reads the SoC id out of the fuses and the
# board id out of shared memory, then walks the dtb area of vendor_boot looking
# for a tree that advertises both, and boots the one that matches. A mainline
# device tree carries neither - no upstream qcom dtsi has ever had them, and a
# patch adding them would be rejected, correctly, because they describe the
# firmware's selection protocol and not the hardware. So they get stamped on at
# flash time and the tree that goes to the lists stays clean.
#
# The values are not invented. They are read off the tree the stock firmware
# handed the stock kernel, harvested from /proc/device-tree on the running
# device and kept under out/device-dump-root/devicetree/. The msm-id is seven
# SoC ids because one Qualcomm base tree covers a family and the bootloader
# needs only one of them to match; copying the list verbatim means whichever
# entry matched for Sony matches for us, without having to know which.
#
# This is only half of what a mainline boot needs. Having selected a base, the
# bootloader also applies a matching overlay from the dtbo partition, resolving
# the overlay's __fixups__ against the base's __symbols__ - and our tree has no
# __symbols__ at all, because upstream builds without dtc -@. A failed overlay
# is what red-states this phone: verified on 2026-10-05, when a vendor_boot
# identical to stock except for the device tree was declared corrupt over 61
# unresolvable labels. Ours would fail on all of them.
#
# The board-id cannot be used to dodge that. Base and overlay are both matched
# against the *hardware's* ids rather than against each other, so a base
# advertising a board-id no overlay asks for would not be selected either. The
# other half therefore has to be the dtbo partition itself: see
# scripts/empty-dtbo.py, which builds an image with no overlays in it for the
# spare slot to carry.
set -eu

# Read off the live tree, not guessed. Keep in step with
# out/device-dump-root/devicetree/base/qcom,{msm,board}-id.
MSM_ID="0x27a 0x10000 0x277 0x10000 0x247 0x10000 0x219 0x10000 0x265 0x10000 0x279 0x10000 0x27e 0x10000"
BOARD_ID="0x1000b 0x0"

die() { echo "error: $*" >&2; exit 1; }

[ $# -eq 2 ] || die "usage: $0 <in.dtb> <out.dtb>"
in=$1
out=$2

command -v fdtput >/dev/null || die "fdtput not found (apt install device-tree-compiler)"
[ -f "$in" ] || die "no such file: $in"

cp -- "$in" "$out"
# shellcheck disable=SC2086
fdtput -t x "$out" / qcom,msm-id $MSM_ID
# shellcheck disable=SC2086
fdtput -t x "$out" / qcom,board-id $BOARD_ID

echo "==> $out"
printf '    qcom,msm-id   = %s\n' "$(fdtget -t x "$out" / qcom,msm-id)"
printf '    qcom,board-id = %s\n' "$(fdtget -t x "$out" / qcom,board-id)"
