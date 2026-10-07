#!/bin/sh
# Get the device into fastboot without anyone touching it.
#
#   scripts/to-fastboot.sh [rounds]
#
# try-kernel.sh needs fastboot to flash, and its own need_fastboot() handles
# the easy case: stock Android or recovery is up, adb answers, and
# 'adb reboot bootloader' does the rest. That covers a *failed* experiment,
# because a kernel that dies burns the bootloader's retry counter and lands
# back on the stock slot.
#
# It does not cover a *successful* one. A pmOS that boots and stays up has no
# adb, and the loop stops dead on its own success - which is where this port
# sat for twenty-one hours with a built mainline kernel and no way to flash it.
#
# The way out is to ask the kernel for it. 'systemctl reboot
# --reboot-argument=bootloader' reaches reboot(2) with LINUX_REBOOT_CMD_RESTART2
# and the string "bootloader", and the live tree's 'qcom,reboot-reason' node
# binds a driver that turns that into the restart reason the boot chain reads.
# This is the same mechanism 'adb reboot bootloader' uses on stock, done by the
# kernel rather than by poking the PMIC's SDAM from userspace, and it takes one
# reboot and about fifteen seconds.
#
# Two spellings do NOT work and are worth not rediscovering. 'systemctl reboot
# bootloader' is rejected with "Too many arguments" by this build, so the
# argument has to go through --reboot-argument. And writing "bootonce-bootloader"
# into the BCB at offset 0 of 'misc' does nothing on this device: that field
# already contains exactly that string and seven boots went straight past it.
#
# The fallback, if the reboot argument is ever refused, is the bootloader's own
# A/B logic: our slot never reports its boot successful, so every attempt at it
# decrements the retry counter and nothing resets it. That works - measured
# 2026-10-06, slot a went from 7 retries to 1 over a handful of reboots - it is
# just six or seven rounds slower than asking.
#
# What this does NOT fix: a kernel hung without panicking, because nothing in
# the device is running to reboot it. That is still Power+VolUp by hand.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROUNDS=${1:-10}
# A pmOS boot to sshd takes well under this; a round that exceeds it is a boot
# that failed, which is just as good an outcome here and is caught by the
# adb/fastboot checks rather than by waiting it out.
PER_ROUND=120
# Same default as scripts/ssh.py, for the same reason: a throwaway on a
# development phone, and it is in the docs already.
PASS=${PMOS_PASS:-147147}

die() { echo "error: $*" >&2; exit 1; }
say() { echo; echo "== $*"; }

have_fastboot() { fastboot devices 2>/dev/null | grep -q .; }
have_adb() { adb devices 2>/dev/null | sed 1d | grep -qE 'device$|recovery$'; }

# Whether the booted pmOS answers. ssh.py carries the throwaway password and
# its own timeout; 'true' is enough to tell reachable from not.
have_ssh() { timeout 30 "$ROOT/scripts/ssh.py" true >/dev/null 2>&1; }

# Seconds since this boot, or empty if the phone did not answer. What makes a
# round verifiable: if this has not gone down, the reboot did not happen and
# spinning nine more rounds would prove nothing.
uptime_secs() {
	timeout 30 "$ROOT/scripts/ssh.py" 'cut -d. -f1 /proc/uptime' 2>/dev/null \
		| tr -dc '0-9'
}

# Whether systemd has finished starting up. 'running' and 'degraded' are both
# settled answers - this port is permanently degraded, because nftables.service
# fails - while 'starting' and 'initializing' are not.
settled() {
	state=$(timeout 30 "$ROOT/scripts/ssh.py" 'systemctl is-system-running' \
		2>/dev/null | tr -dc 'a-z-')
	case $state in
	running | degraded | maintenance | stopping) return 0 ;;
	*) return 1 ;;
	esac
}

# Waits for that, because asking too early is silently ignored. Round 2 of the
# first working run fired its request 29 seconds into a boot, got no error and
# no reboot, and sat out the whole round; the same request by hand two minutes
# later worked immediately. sshd answers well before systemd will take a
# reboot job, so "the phone is reachable" is not the same as "the phone will
# reboot", and this is the difference.
wait_settled() {
	i=0
	while [ "$i" -lt 90 ]; do
		settled && return 0
		sleep 3
		i=$((i + 3))
	done
	return 1
}

# Asking politely does not work from here either. 'systemctl reboot' as the
# user returns silently without rebooting, because logind hands the request to
# polkit and polkit wants an active local session; the first version of this
# script burned a round on that and reported nothing. sudo is setuid root and
# the user is in wheel, but it refuses -n with "interactive authentication is
# required", so the password goes in on stdin with -S.
request_reboot() {
	timeout 40 "$ROOT/scripts/ssh.py" \
		"echo $PASS | sudo -S systemctl reboot" >/dev/null 2>&1 || true
}

# The direct route: hand reboot(2) the string the qcom,reboot-reason driver
# knows, and let the boot chain come up in fastboot.
request_bootloader() {
	timeout 40 "$ROOT/scripts/ssh.py" \
		"echo $PASS | sudo -S systemctl reboot --reboot-argument=bootloader" \
		>/dev/null 2>&1 || true
}

report() {
	echo "   fastboot: $(have_fastboot && echo yes || echo no)   adb: $(have_adb && echo yes || echo no)"
}

if have_fastboot; then
	say "already in fastboot"
	fastboot getvar current-slot 2>&1 | sed -n 's/^current-slot: */   current-slot: /p'
	exit 0
fi

if have_adb; then
	say "adb answers - asking for the bootloader"
	adb reboot bootloader >/dev/null 2>&1 || true
	i=0
	while [ "$i" -lt 60 ]; do
		sleep 2
		have_fastboot && { say "in fastboot after ${i}s"; exit 0; }
		i=$((i + 2))
	done
	die "adb accepted 'reboot bootloader' but fastboot never appeared"
fi

have_ssh || die "nothing reachable: no fastboot, no adb, and sshd on 172.16.42.1
       does not answer. Hold Power+VolUp until it vibrates, then hold VolUp
       while plugging in USB."

say "pmOS is up and has no adb - asking the kernel for the bootloader"
request_bootloader
i=0
while [ "$i" -lt 60 ]; do
	sleep 3
	i=$((i + 3))
	have_fastboot && { say "in fastboot after ${i}s"; exit 0; }
	if have_adb; then
		say "adb answered instead - asking it for the bootloader"
		adb reboot bootloader >/dev/null 2>&1 || true
		j=0
		while [ "$j" -lt 60 ]; do
			sleep 2
			have_fastboot && { say "in fastboot"; exit 0; }
			j=$((j + 2))
		done
		die "adb answered but fastboot never appeared"
	fi
done

say "the reboot argument did not land - burning the slot's retry counter instead"
echo "   Each round is one 'reboot', which is one boot attempt the bootloader"
echo "   does not get told succeeded. Stock Android answers when it gives up."

round=0
while [ "$round" -lt "$ROUNDS" ]; do
	round=$((round + 1))
	wait_settled || echo "   (systemd still not settled; asking anyway)"
	before=$(uptime_secs)
	printf '\n   round %d/%d: rebooting (up %ss)\n' \
		"$round" "$ROUNDS" "${before:-?}"
	# The reboot kills the connection, so ssh's own exit status says nothing
	# about whether it was accepted. Ignore it and watch the device instead.
	request_reboot

	i=0
	rebooted=0
	while [ "$i" -lt "$PER_ROUND" ]; do
		sleep 3
		i=$((i + 3))
		if have_fastboot; then
			say "dropped into fastboot after $round round(s)"
			exit 0
		fi
		if have_adb; then
			say "the bootloader fell back to the stock slot after $round round(s)"
			echo "   asking it for the bootloader"
			adb reboot bootloader >/dev/null 2>&1 || true
			j=0
			while [ "$j" -lt 60 ]; do
				sleep 2
				have_fastboot && { say "in fastboot"; exit 0; }
				j=$((j + 2))
			done
			die "stock answered but fastboot never appeared"
		fi
		# pmOS came back: this round spent an attempt, so start the next
		# one now rather than waiting out the timeout. Without this the
		# script idles for most of every round.
		now=$(uptime_secs)
		if [ -n "$now" ] && [ -n "$before" ] && [ "$now" -lt "$before" ]; then
			printf '\r      %-50s\n' "pmOS back up after ${i}s (up ${now}s)"
			rebooted=1
			break
		fi
		if [ $((i % 30)) -lt 3 ]; then
			printf '\r      %ds into this round ' "$i"
		fi
	done

	if [ "$rebooted" = 0 ]; then
		printf '\r      %-50s\n' "round $round: nothing changed"
		report
		# A round that neither rebooted the phone nor produced adb or
		# fastboot has proved the reboot is not being accepted. Nine more
		# would prove it eight more times.
		now=$(uptime_secs)
		if [ -n "$now" ] && [ -n "$before" ] && [ "$now" -ge "$before" ]; then
			die "the phone did not reboot - it has been up ${now}s and was
       up ${before}s before the request, so 'sudo systemctl reboot' is not
       being accepted. Check 'scripts/ssh.py \"echo \$PMOS_PASS | sudo -S id\"'
       before adding rounds."
		fi
	fi
done

die "$ROUNDS rounds and still no adb or fastboot.
       The phone is rebooting, so the attempts are being spent, but the slot's
       retry counter has not run out. Try more rounds."
