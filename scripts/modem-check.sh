#!/bin/sh
# Run as root on pdx246. Bounded control-plane test; original modem storage
# is opened read-only by rmtfs -r, with writes redirected into RAM.
# Does not place calls, enable a data connection, or change modem NV settings.
set -eu
[ "$(id -u)" = 0 ] || exit 1
grep -aq 'sony,pdx246' /proc/device-tree/compatible || exit 1
r=
for candidate in /sys/class/remoteproc/remoteproc*; do
    [ "$(cat "$candidate/name")" != modem ] || r=$candidate
done
[ -n "$r" ] && [ "$(cat "$r/state")" = offline ] || exit 1
test -c /dev/qcom_rmtfs_mem1
# Do not run alongside another filesystem server, regardless of its options.
if pidof rmtfs >/dev/null; then echo 'rmtfs already running' >&2; exit 1; fi
server=
guard=
cleanup() {
    if [ "$(cat "$r/state")" = running ]; then echo stop > "$r/state" || true; fi
    if [ -n "$server" ]; then kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true; fi
    if [ -n "$guard" ]; then kill "$guard" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
# An independent stop timer bounds this test even if a query stalls.
(sleep 100; test "$(cat "$r/state")" != running || echo stop > "$r/state") </dev/null >/tmp/pdx246-modem-stop.log 2>&1 &
guard=$!
rmtfs -P -r -v >/tmp/pdx246-rmtfs.log 2>&1 &
server=$!
sleep 1
kill -0 "$server"
timeout 25 sh -c 'echo start > "$1/state"' sh "$r"
sleep 20
echo 'Modem remote processor:'
cat "$r/state"
echo 'QRTR services:'
qrtr-lookup
echo 'ModemManager devices:'
mmcli -L
echo 'Remote filesystem protocol (no storage contents):'
tail -30 /tmp/pdx246-rmtfs.log | sed -E 's/[0-9A-Z]{12,}/<redacted>/g'
echo 'Kernel modem messages:'
dmesg | grep -Ei 'modem|mpss|rmtfs|4080000' | tail -25 | sed -E 's/[0-9A-Z]{12,}/<redacted>/g'
echo 'Stopping the bounded modem test'
