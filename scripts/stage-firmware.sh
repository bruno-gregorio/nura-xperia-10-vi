#!/bin/sh
# Put the phone's own firmware where the firmware-sony-pdx246 aport builds
# from.
#
#   scripts/stage-firmware.sh
#
# None of it is redistributable and none of it goes into git: the aport's
# .gitignore keeps everything but its APKBUILD out. What it copies, all
# already under out/ and gitignored:
#
# - out/firmware/gpu/: the Adreno 710's SQE and GMU firmware, and the zap
#   shader squashed into one .mbn;
# - out/firmware/mbn/: the ADSP, CDSP, modem and WPSS images, squashed by
#   scripts/pil-squash.py out of stock's modem partition;
# - out/firmware/audio/aw88261_acf.bin and aw88263_acf.bin: the speaker
#   amplifier's settings for either chip, stock's /vendor/firmware files of
#   those names, dumped from the vendor image with
#   debugfs -R "dump /firmware/aw88261_acf.bin ...";
# - out/tools/ath10k/board-2-pdx246.bin: the WLAN board data that
#   scripts/ath10k-board2.py packs from stock's bdwlan files, as board-2.bin;
# - out/hexagonfs/stage/: what hexagonrpcd serves the ADSP's sensors
#   process, packed into hexagonfs.tar in the layout its README gives:
#   sensors/config, sensors/registry, sensors/sns_reg.conf and socinfo.
#   scripts/collect-hexagonfs.sh reads the registry and socinfo from the
#   phone, and also persist's sensors/registry/sns_reg_version, which goes
#   in as sensors/sns_reg_version when there is one. Stock hexagonrpcd does
#   not serve that file; ours is patched to.
#
# The tar is deterministic, so its checksum only changes when its contents
# do. It is also what a round pushes to try hexagonrpcd from the initramfs
# shell, so it is written to out/hexagonfs/hexagonfs.tar as well.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DST="$ROOT/aports/device/testing/firmware-sony-pdx246"
HFS="$ROOT/out/hexagonfs"

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ -f "$DST/APKBUILD" ] || die "no $DST/APKBUILD"

for f in gpu/a710_sqe.fw gpu/gmu_gen70000.bin gpu/a710_zap.mbn \
	mbn/adsp.mbn mbn/cdsp.mbn mbn/modem.mbn mbn/wpss.mbn audio/aw88261_acf.bin \
	audio/aw88263_acf.bin; do
	[ -s "$ROOT/out/firmware/$f" ] || die "no out/firmware/$f"
	cp -- "$ROOT/out/firmware/$f" "$DST/${f#*/}"
done

# Firmware-only remote files served by tqftpserv; no EFS, persist or NV data.
[ -d "$ROOT/out/firmware/modem_b/image/modem_pr" ] || die "no modem_pr dump"
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
	-C "$ROOT/out/firmware/modem_b/image" -cf "$DST/modem-pr.tar" modem_pr
[ -s "$ROOT/out/tools/ath10k/board-2-pdx246.bin" ] \
	|| die "no out/tools/ath10k/board-2-pdx246.bin"
cp -- "$ROOT/out/tools/ath10k/board-2-pdx246.bin" "$DST/board-2.bin"

for d in sensors/config sensors/registry socinfo; do
	[ -d "$HFS/stage/$d" ] || die "no out/hexagonfs/stage/$d"
done
[ -s "$HFS/stage/sensors/sns_reg_config" ] \
	|| die "no out/hexagonfs/stage/sensors/sns_reg_config"

tree="$HFS/tree"
rm -rf "${tree:?}"
mkdir -p "$tree/sensors"
cp -R -- "$HFS/stage/sensors/config" "$HFS/stage/sensors/registry" \
	"$tree/sensors/"
cp -- "$HFS/stage/sensors/sns_reg_config" "$tree/sensors/sns_reg.conf"
if [ -f "$HFS/stage/sensors/sns_reg_version" ]; then
	cp -- "$HFS/stage/sensors/sns_reg_version" "$tree/sensors/"
fi
cp -R -- "$HFS/stage/socinfo" "$tree/"
find "$tree" -type d -exec chmod 0755 {} +
find "$tree" -type f -exec chmod 0644 {} +
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
	-C "$tree" -cf "$HFS/hexagonfs.tar" sensors socinfo
cp -- "$HFS/hexagonfs.tar" "$DST/hexagonfs.tar"

python3 "$ROOT/scripts/hi846-firmware.py"

# Native QSEECom loads the original signed split ELF64 image without
# modifying any segment. No template, user data or secure storage is copied.
for segment in mdt b00 b01 b02 b03 b04 b05 b06 b07 b08; do
	cp -- "$ROOT/out/firmware/modem_b/image/egisap64.$segment" "$DST/"
done

say "staged in $DST:"
(cd "$DST" && ls -l -- *.fw *.bin *.mbn *.tar)
say "hexagonfs.tar: $(tar -tf "$HFS/hexagonfs.tar" | grep -c -v '/$') files"
