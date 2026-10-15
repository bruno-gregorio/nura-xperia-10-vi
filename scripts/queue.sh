#!/bin/sh
# Run rounds back to back with nobody at the phone.
#
#   scripts/queue.sh <plan>
#
# A plan is a shell fragment. It calls `round NAME [VAR=value ...]` once per
# round, which runs try-kernel.sh with those variables, and it can branch on
# what each round left behind:
#
#   ROUND_RESULT  fallback, gadget, fastboot, ours, nothing or failed - what
#                 try-kernel's RESULT line said, or failed for no such line
#   ROUND_TOTAL   seconds from the reboot into the round to the phone
#                 answering, the number markdecode and wdtdecode read back
#
# and `adopt NAME PID`, which does the same for a round already started by
# hand into out/try-kernel/run-NAME.log, once process PID has exited.
#
# Why this exists: until 2026-10-07 every round ended with a person reading
# its log and typing the next command, and a round that ended at 3 a.m.
# meant a phone idle until morning. Rounds run up to an hour, so a night is
# five or six of them only if nothing waits between them.
#
# What it will not do is go on after a round that left the phone silent. It
# waits for the phone to come back by itself - a hung attempt the watchdog
# resets, or a gadget whose window runs out - for up to BACK_WAIT seconds,
# three hours by default, and stops the queue if it does not, because every
# round after that one needs the phone and none of them can get it back.
# Each round also waits that long for the phone before it starts, so a
# queue chained after one that stopped this way runs its plan whole once
# someone brings the phone back, instead of failing its first round.
#
# Every round's card and rddata records are read before the next one starts,
# by try-kernel itself on a fallback and by --log otherwise, because --log
# also clears both and a record left over would be read as the next round's.
set -u

ROOT=${QUEUE_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
WORK="$ROOT/out/try-kernel"

# Run from a copy, the same way and for the same reason as try-kernel.sh:
# a night of rounds is hours of sh reading this file as it goes.
if [ -z "${QUEUE_ROOT:-}" ]; then
	mkdir -p "$WORK"
	snap=$(mktemp "$WORK/.queue.XXXXXX")
	cp -- "$0" "$snap"
	QUEUE_ROOT=$ROOT exec sh "$snap" "$@"
fi
case "$0" in */.queue.*) rm -f -- "$0" ;; esac

[ $# -eq 1 ] && [ -r "$1" ] || { echo "usage: scripts/queue.sh <plan>" >&2; exit 2; }

QLOG="$WORK/queue-$(date +%Y%m%d-%H%M%S).log"
note() { echo "$(date '+%F %T') $*" | tee -a "$QLOG"; }

phone_state() {
	if fastboot devices 2>/dev/null | grep -q .; then
		echo fastboot
	elif adb devices 2>/dev/null | sed 1d | grep -qE 'device$|recovery$'; then
		echo adb
	elif [ -n "$(ls /dev/ttyACM* 2>/dev/null)" ] \
		|| ip -o link show 2>/dev/null | grep -qE ': (usb[0-9]|enp[0-9]+s[0-9]+[a-z0-9]*u[0-9])'; then
		echo gadget
	else
		echo none
	fi
}

# Whether the phone answers on a TCP port; the host has no nc.
port_open() {
	# The initramfs telnet shell stays on USB; rootfs SSH may use Wi-Fi.
	port_host=172.16.42.1
	[ "$1" != 22 ] || port_host=${PMOS_HOST:-172.16.42.1}
	timeout 5 python3 -I -c 'import socket, sys
socket.create_connection((sys.argv[1], int(sys.argv[2])), 3).close()' \
		"$port_host" "$1" >/dev/null 2>&1
}

# Ask a boot of ours that is up on the network gadget to reset now, rather
# than wait out the watchdog's window. Each reset is an attempt the
# bootloader counts, so seven of them land on the stock slot.
#
# The debug shell answers on telnet. A boot that went on into the rootfs
# has no telnetd but has sshd, and nothing in it marks the slot good, so
# every one of its attempts boots the whole system again and needs the same
# push. Only the port that answers is tried: sshd takes a while to come up,
# and the watchdog in the initramfs covers an attempt that never gets there.
kick_gadget() {
	if port_open 23; then
		printf '%s\n' 'echo b > /proc/sysrq-trigger' 'reboot -f -n' \
			| timeout 20 python3 "$ROOT/scripts/telnet.py" 172.16.42.1 23 \
				>/dev/null 2>&1 || true
	elif port_open 22; then
		PMOS_TIMEOUT=25 timeout 30 python3 "$ROOT/scripts/ssh.py" \
			"sudo sh -c 'sync; echo b > /proc/sysrq-trigger'" \
			>/dev/null 2>&1 || true
	fi
}

# The bootloader's counters, read while the phone is in fastboot. A round
# that someone ended by hand, or that the bootloader gave up on, is only
# decodable if we know how many attempts it began: set-active resets
# slot-retry-count, and each attempt takes one off.
note_counters() {
	for s in a b; do
		note "slot $s: retry-count $(fastboot getvar "slot-retry-count:$s" 2>&1 \
			| sed -n "s/^slot-retry-count:$s: *//p" | head -1)," \
			"unbootable $(fastboot getvar "slot-unbootable:$s" 2>&1 \
			| sed -n "s/^slot-unbootable:$s: *//p" | head -1)," \
			"successful $(fastboot getvar "slot-successful:$s" 2>&1 \
			| sed -n "s/^slot-successful:$s: *//p" | head -1)"
	done
}

# Wait for the phone to be somewhere try-kernel can start from.
bring_back() {
	limit=${BACK_WAIT:-10800}
	i=0
	while [ "$i" -lt "$limit" ]; do
		case "$(phone_state)" in
		fastboot) note_counters; return 0 ;;
		adb) return 0 ;;
		gadget) kick_gadget ;;
		esac
		command sleep 15
		i=$((i + 15))
	done
	return 1
}

# Fill ROUND_RESULT and ROUND_TOTAL in from a round's log.
parse_round() {
	log=$1
	ROUND_TOTAL=$(awk '
		/^== waiting\. our kernel answering/ { w = 1; next }
		w && match($0, /(up after|dropped into fastboot after|USB gadget appeared after|nothing after) [0-9]+s/) {
			s = substr($0, RSTART, RLENGTH); sub(/s$/, "", s)
			n = split(s, a, " "); print a[n]; exit
		}' "$log")
	case "$(grep -m1 '^RESULT:' "$log")" in
	"RESULT: nothing came up"*)        ROUND_RESULT=nothing ;;
	"RESULT: the bootloader gave up"*) ROUND_RESULT=fastboot ;;
	"RESULT: the initramfs got USB"*)  ROUND_RESULT=gadget ;;
	"RESULT: OUR KERNEL BOOTED"*)      ROUND_RESULT=ours ;;
	"RESULT: it crashed"*)             ROUND_RESULT=fallback ;;
	*)                                 ROUND_RESULT=failed ;;
	esac
}

# Everything after the round itself: get the phone back, read its logs.
finish_round() {
	name=$1
	log="$WORK/run-$name.log"
	parse_round "$log"
	note "round $name: $ROUND_RESULT after ${ROUND_TOTAL:-?} s"
	if [ "$ROUND_RESULT" = failed ]; then
		note "round $name: try-kernel stopped before a result; its last lines:"
		tail -5 "$log" | tee -a "$QLOG"
	fi
	if ! bring_back; then
		note "the phone has not come back in ${BACK_WAIT:-10800} s; stopping the queue"
		exit 1
	fi
	# A fallback already ran --log inside try-kernel; the other results
	# did not, and a --log that died part way did not finish either.
	if ! grep -q 'clearing rddata for the next round' "$log"; then
		note "round $name: reading the card and rddata"
		"$ROOT/scripts/try-kernel.sh" --log > "$WORK/log-$name.txt" 2>&1 \
			|| note "round $name: --log failed, see $WORK/log-$name.txt"
	fi
	[ "$ROUND_RESULT" = failed ] && { note "stopping the queue"; exit 1; }
	return 0
}

round() {
	name=$1
	shift
	# A queue that starts after one which gave up on the phone, or a plan
	# that goes on after a round left it elsewhere, would otherwise spend
	# this round on try-kernel failing to find it, and stop.
	case "$(phone_state)" in
	fastboot | adb) ;;
	*)
		note "round $name: waiting for the phone"
		if ! bring_back; then
			note "round $name: no phone in ${BACK_WAIT:-10800} s; stopping the queue"
			exit 1
		fi
		;;
	esac
	note "round $name: $*"
	# Each round keeps its own harvest and live transcript, which a shared
	# path would leave to the next round to overwrite. A plan's own
	# HARVEST_OUT or LIVE_OUT, coming later, wins.
	env HARVEST_OUT="$WORK/harvest-$name.txt" LIVE_OUT="$WORK/live-$name.txt" \
		"$@" "$ROOT/scripts/try-kernel.sh" > "$WORK/run-$name.log" 2>&1 < /dev/null
	finish_round "$name"
}

adopt() {
	name=$1
	note "round $name: adopted, waiting for process $2 to end"
	while kill -0 "$2" 2>/dev/null; do
		command sleep 30
	done
	finish_round "$name"
}

# Branch helpers for plans.
wdt_verdict() {
	"$ROOT/scripts/bootlog.py" wdtdecode "$ROUND_TOTAL" 2>/dev/null \
		| sed -n 's/^verdict: //p'
}

# "<scm state> <bound bits>" for a DEVPROBE round, or "other"; see
# bootlog.py devdecode for what the numbers mean.
dev_verdict() {
	"$ROOT/scripts/bootlog.py" devdecode "$ROUND_TOTAL" 2>/dev/null \
		| sed -n 's/^verdict: //p'
}

plan=$(mktemp "$WORK/.plan.XXXXXX")
cp -- "$1" "$plan"
note "queue starting from $1"
. "$plan"
rm -f -- "$plan"
note "queue done"
