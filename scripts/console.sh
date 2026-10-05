#!/bin/sh
# Wait for the pmOS initramfs USB gadget, then open the debug shell.
#
#   scripts/console.sh            wait, diagnose, connect
#   scripts/console.sh watch      wait and diagnose, do not connect
#
# Run this on the host, in a second terminal, right before or just after
# 'scripts/flash.sh ramboot'. The device has no working display yet, so this
# network gadget is the only way to see anything; docs/04-flashing.md covers
# the pstore fallback for when it never shows up.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEVICE_IP=172.16.42.1          # what unudhcpd gives the phone
SUBNET=172.16.42
TIMEOUT=${TIMEOUT:-120}

die() { echo "error: $*" >&2; exit 1; }
say() { echo; echo "==> $*"; }

# A gadget interface shows up either as usb0 or with systemd's predictable
# name for a USB ethernet device, which contains a 'u' path component.
gadget_ifaces() {
	ip -o link show 2>/dev/null \
		| sed -n 's/^[0-9]*: \([^:@]*\)[:@].*/\1/p' \
		| grep -E '^(usb[0-9]|enp[0-9]+s[0-9]+[a-z0-9]*u[0-9])' || true
}

host_ip_in_subnet() {
	ip -4 -o addr show 2>/dev/null | grep -o "$SUBNET\.[0-9]*" | head -1 || true
}

say "waiting up to ${TIMEOUT}s for the USB gadget"
echo "    (ctrl-c to give up; nothing here writes to the device)"
found=""
i=0
while [ "$i" -lt "$TIMEOUT" ]; do
	ifaces=$(gadget_ifaces)
	if [ -n "$ifaces" ]; then
		found="$ifaces"
		break
	fi
	i=$((i + 1))
	sleep 1
done

if [ -z "$found" ]; then
	say "no USB network gadget appeared"
	cat <<'EOF'
    What this means, in order of likelihood:

    1. The kernel never got far enough to bring the gadget up. Read
       /sys/fs/pstore/console-ramoops* after the next boot - see
       docs/04-flashing.md. This is the common case on a first attempt.
    2. The bootloader refused 'fastboot boot' or ignored the staged
       vendor_boot, so the stock kernel ran instead. Check 'lsusb' for a
       normal Android device, and docs/05-status.md on that risk.
    3. Type-C role detection never decided the port is a device.
       TYPEC_QCOM_PMIC is not set, so this goes through the PMIC driver and
       extcon, and is the least verified part of the chain.

    Currently attached:
EOF
	lsusb | sed 's/^/      /'
	exit 1
fi

say "gadget interface: $found"
ip -o addr show "$found" 2>/dev/null | sed 's/^/    /' || true

addr=$(host_ip_in_subnet)
if [ -z "$addr" ]; then
	say "the interface is up but the host has no address on $SUBNET.0/24"
	cat <<EOF
    unudhcpd in the initramfs serves DHCP, so NetworkManager normally picks
    this up on its own. If it has not, this will do it - note that it changes
    host network state, so it is your call, not something this script does:

      sudo nmcli device set $found managed yes
      sudo nmcli device connect $found

    Or statically, without involving NetworkManager:

      sudo ip addr add $SUBNET.2/24 dev $found && sudo ip link set $found up
EOF
	exit 1
fi
echo "    host address: $addr"

say "device reachable?"
if ping -c 1 -W 2 "$DEVICE_IP" >/dev/null 2>&1; then
	echo "    $DEVICE_IP responds to ping"
else
	echo "    $DEVICE_IP does not answer ping (telnetd may still be up; trying anyway)"
fi

[ "${1:-}" = "watch" ] && { say "watch only, not connecting"; exit 0; }

say "opening the debug shell on $DEVICE_IP:23"
cat <<'EOF'
    Once you are in, these are the four that matter:
      cat /pmOS_init.log      what the initramfs did
      dmesg                   what the kernel did
      pmos_logdump            hand both over as a USB mass-storage volume
      pmos_continue_boot      carry on into the real rootfs
EOF
echo

# Fedora ships none of telnet/nc/socat, and this project may not install onto
# the host, so scripts/telnet.py is the one that is always there. Prefer a real
# client if the host happens to have one.
if command -v telnet >/dev/null 2>&1; then
	exec telnet "$DEVICE_IP" 23
elif command -v nc >/dev/null 2>&1; then
	exec nc "$DEVICE_IP" 23
else
	exec python3 "$ROOT/scripts/telnet.py" "$DEVICE_IP" 23
fi
