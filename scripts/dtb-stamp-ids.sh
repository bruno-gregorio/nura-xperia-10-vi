#!/bin/sh
# Add the two properties the Qualcomm bootloader needs to select our device
# tree, without putting them in the device tree source.
#
#   scripts/dtb-stamp-ids.sh <in.dtb> <out.dtb>
#
# scripts/dtb-ids.py is the other half of this pair and reads the same three
# properties back out of a .dtb, a concatenation of them or a whole
# vendor_boot image. Use it to check the result, here or after a flash.
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
# The values are not invented, and - the one trap here - they are not the ones
# the live tree shows.
#
# /proc/device-tree on the running device has qcom,board-id = <0x1000b 0x0> at
# its root, but that is the *overlay's* id, not the base's: the resolved tree's
# root says model = "Qualcomm Technologies, Inc. Parrot QRD", which is
# parrot-qrd-overlay, applied on top. Copying it would have stamped our base
# with an id no base is selected on.
#
# What the bootloader selects a base on is visible in the stock vendor_boot,
# read with scripts/dtb-ids.py: all fourteen of Sony's base trees carry
# qcom,board-id = <0x0 0x0> or <0x0 0x600> - generic, SoC-level - and are
# distinguished from each other by qcom,msm-id alone. The overlays are the ones
# that carry a board id.
#
# So these are "Qualcomm Technologies, Inc. Parrot SoC", entry 8, the generic
# base for this SoC. That it is the right one is settled by the device rather
# than inferred: /sys/devices/soc0 on the running phone reports soc_id 537 =
# 0x219, platform_version 65536 = 0x10000, hw_platform QRD and
# platform_subtype_id 0, and 0x219 0x10000 is exactly what that base
# advertises. 0x265 comes along because Qualcomm groups the two in one tree and
# only one entry has to match.
#
# ABL matches on a third property as well, qcom,pmic-id, and this does not set
# it: no base tree in the stock vendor_boot carries one, so it is not part of
# what this board is matched on.
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

# From "Parrot SoC" in the stock vendor_boot, confirmed against the running
# device's own soc_id. Check with: scripts/dtb-ids.py out/device-dump-root/stock/vendor_boot_b.img
MSM_ID="0x219 0x10000 0x265 0x10000"
BOARD_ID="0x0 0x0"

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
