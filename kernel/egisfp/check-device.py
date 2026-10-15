#!/usr/bin/env python3
"""Bounded EC617 hardware ABI check. Run as root on pdx246; no TEE calls.

Run with no fingerprint client active. Does not test matching/enrollment.
"""
import errno
import argparse
import fcntl
import os
from pathlib import Path
import select
import struct

assert os.geteuid() == 0
assert b'sony,pdx246\0' in Path('/proc/device-tree/compatible').read_bytes()
STATUS, POWER, RESET, EVENTFD = 0x80104580, 0x40044581, 0x4582, 0x40044583
IRQ_ARM = 0x40044584
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--irq-edge', action='store_true', help='arm rising edge briefly; does not require a finger or assert a level')
args = parser.parse_args()

def status(fd):
    value = bytearray(16)
    fcntl.ioctl(fd, STATUS, value)
    version, powered, level, sequence = struct.unpack('=4I', value)
    assert version == 1 and powered in (0, 1) and level in (0, 1)
    return powered, level, sequence

def expect_errno(error, action):
    try:
        action()
    except OSError as exc:
        assert exc.errno == error, (exc.errno, error)
    else:
        raise AssertionError(f'Expected errno {error}')

fd = os.open('/dev/egisfp0', os.O_RDWR | os.O_CLOEXEC)
event = os.eventfd(0, os.EFD_CLOEXEC | os.EFD_NONBLOCK)
try:
    initial = status(fd)
    sequence = initial[2]  # Device-wide sequence persists across opens.
    print('initial:', initial, flush=True)
    assert status(fd)[0] == 0
    expect_errno(errno.EBUSY, lambda: os.close(os.open('/dev/egisfp0', os.O_RDWR)))
    expect_errno(errno.EINVAL, lambda: fcntl.ioctl(fd, POWER, struct.pack('=I', 2)))
    expect_errno(errno.EFAULT, lambda: fcntl.ioctl(fd, POWER, 0))
    expect_errno(errno.ENOTTY, lambda: fcntl.ioctl(fd, 0x45ff, 0))
    expect_errno(errno.EHOSTDOWN, lambda: fcntl.ioctl(fd, RESET, 0))
    expect_errno(errno.EINVAL, lambda: fcntl.ioctl(fd, IRQ_ARM, struct.pack('=I', 3)))
    expect_errno(errno.EHOSTDOWN, lambda: fcntl.ioctl(fd, IRQ_ARM, struct.pack('=I', 1)))
    expect_errno(errno.EBADF, lambda: fcntl.ioctl(fd, EVENTFD, struct.pack('=i', -2)))
    fcntl.ioctl(fd, EVENTFD, struct.pack('=i', event))
    fcntl.ioctl(fd, POWER, struct.pack('=I', 1))
    print('powered:', status(fd), flush=True)
    assert status(fd)[0] == 1
    print('reset with IRQ disabled:', flush=True)
    fcntl.ioctl(fd, RESET, 0)
    print('after reset:', status(fd), flush=True)
    assert status(fd)[2] == sequence, 'Unarmed IRQ generated an event'
    wait = select.poll()
    wait.register(event, select.POLLIN)
    assert not wait.poll(50), 'Unarmed eventfd was signalled'
    if args.irq_edge:
        # The old forced asserted-level test resets r45. Do not rerun it.
        # Validate only arming/disarming the actual rising-edge configuration.
        print('arming rising edge IRQ:', status(fd), flush=True)
        fcntl.ioctl(fd, IRQ_ARM, struct.pack('=I', 1))
        print('rising edge armed:', status(fd), flush=True)
        readable = wait.poll(2000)
        print('poll completed; disarming:', bool(readable), flush=True)
        fcntl.ioctl(fd, IRQ_ARM, struct.pack('=I', 0))
        if readable:
            assert os.eventfd_read(event) == 1, 'IRQ was not one-shot'
            assert status(fd)[2] == (sequence + 1) & 0xffffffff
        print('PASS: rising edge arm/disarm; event observed:', bool(readable), flush=True)
finally:
    # Final close must power off even if the client crashes without POWER=0.
    os.close(fd)
    os.close(event)

fd = os.open('/dev/egisfp0', os.O_RDWR | os.O_CLOEXEC)
try:
    assert status(fd)[0] == 0, 'Final close did not power off'
    print('PASS: ABI validation, exclusive ownership, power/reset, close cleanup', flush=True)
finally:
    os.close(fd)
