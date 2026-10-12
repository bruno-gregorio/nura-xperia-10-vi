#!/bin/sh
# Copy this project's aports into the upstream pmaports checkout, or back.
#
# pmbootstrap takes exactly one aports directory (Config.aports), so our
# packages have to live inside the upstream tree. They are authored here, under
# aports/, so they stay in this repository's history; .pmb/pmaports is a
# disposable upstream checkout that sync drops them into.
#
#   sync-aports.sh          aports/ -> .pmb/pmaports/
#   sync-aports.sh --back   .pmb/pmaports/ -> aports/   (after 'pmb checksum',
#                                                        which rewrites APKBUILDs)
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/aports"
DST="$ROOT/.pmb/pmaports"

[ -d "$DST" ] || { echo "error: $DST missing - run scripts/bootstrap.sh first" >&2; exit 1; }

if [ "${1:-}" = "--back" ]; then
	a="$DST"; b="$SRC"; dir="<-"
else
	a="$SRC"; b="$DST"; dir="->"
fi

# Device packages are three levels down (device/testing/<pkg>), forks of
# Alpine packages in temp/ two (temp/<pkg>), as in pmaports. Forks of
# pmaports' own packages sit where those do, in main/<pkg>, and replace the
# upstream copy in the checkout; packages of our own that neither has sit
# in main/<pkg> too.
{
	find "$SRC/device" -mindepth 2 -maxdepth 2 -type d
	[ ! -d "$SRC/temp" ] || find "$SRC/temp" -mindepth 1 -maxdepth 1 -type d
	[ ! -d "$SRC/main" ] || find "$SRC/main" -mindepth 1 -maxdepth 1 -type d
} | while read -r pkgdir; do
	rel=${pkgdir#"$SRC"/}
	[ -d "$a/$rel" ] || continue
	rm -rf "$b/$rel"
	mkdir -p "$(dirname "$b/$rel")"
	cp -a "$a/$rel" "$b/$rel"
	echo "synced $dir $rel"
done
