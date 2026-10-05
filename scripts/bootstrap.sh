#!/bin/sh
# Provision the build environment. Run this INSIDE the pmport distrobox:
#   distrobox enter pmport -- ./scripts/bootstrap.sh
#
# Touches only the container's /usr (apt) and this project folder. Nothing is
# written to the host system or to $HOME.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PMB="$ROOT/.pmb"
PMBOOTSTRAP_REF=${PMBOOTSTRAP_REF:-3.11.1}

if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
	:
else
	echo "refusing to run outside a container (would modify the host)" >&2
	exit 1
fi

echo "==> apt packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
	git python3 python3-venv openssl procps xz-utils ca-certificates \
	device-tree-compiler util-linux file android-sdk-libsparse-utils \
	multipath-tools

mkdir -p "$PMB"

echo "==> pmbootstrap ($PMBOOTSTRAP_REF)"
if [ ! -d "$PMB/pmbootstrap" ]; then
	git clone -q https://gitlab.postmarketos.org/postmarketOS/pmbootstrap.git "$PMB/pmbootstrap"
fi
git -C "$PMB/pmbootstrap" fetch -q --tags origin
git -C "$PMB/pmbootstrap" checkout -q "$PMBOOTSTRAP_REF"

echo "==> pmaports (edge)"
if [ ! -d "$PMB/pmaports" ]; then
	git clone -q --depth 1 https://gitlab.postmarketos.org/postmarketOS/pmaports.git "$PMB/pmaports"
fi

echo "==> python venv"
[ -d "$PMB/venv" ] || python3 -m venv "$PMB/venv"
"$PMB/venv/bin/pip" install -q --upgrade pip

echo "==> pmbootstrap config"
sed -e "s|@ROOT@|$ROOT|g" "$ROOT/scripts/pmbootstrap_v3.cfg.in" > "$PMB/pmbootstrap_v3.cfg"

echo "==> sync aports"
"$ROOT/scripts/sync-aports.sh"

echo
echo "done. Next: ./scripts/pmb status"
