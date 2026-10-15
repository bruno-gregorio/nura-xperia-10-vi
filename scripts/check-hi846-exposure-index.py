#!/usr/bin/env python3
"""Check the stock AEC exposure-index arithmetic against the original blob.

Run inside pmport with Unicorn/pyelftools. Synthetic inputs only; libm log10
is supplied by the host, while normalization and scaling execute stock code.
"""
import argparse
import hashlib
import math
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('aec', type=Path)
a = p.parse_args()
assert hashlib.sha256(a.aec.read_bytes()).hexdigest() == '51753e2b3dded80d70304f4747303bcc4a37430ef53191db7dcc483d6822401e'
u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
u.mem_map(0, 0x200000)
with a.aec.open('rb') as f:
    for segment in ELFFile(f).iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            u.mem_write(segment['p_vaddr'], segment.data())
u.reg_write(UC_ARM64_REG_CPACR_EL1, 3 << 20)
u.reg_write(UC_ARM64_REG_X25, 0x100000)
u.reg_write(UC_ARM64_REG_SP, 0x1fff00)
u.mem_write(0x100020, struct.pack('<f', 0))
u.mem_write(0x100030, struct.pack('<Q', 0x101000))
u.mem_write(0x101004, struct.pack('<fQ', 1, 13195))


def hook(u, address, size, data):
    if address == 0x5e110:  # log10 PLT
        x = struct.unpack('<d', struct.pack('<Q', u.reg_read(UC_ARM64_REG_D0)))[0]
        u.reg_write(UC_ARM64_REG_D0, struct.unpack('<Q', struct.pack('<d', math.log10(x)))[0])
        u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_LR))


u.hook_add(UC_HOOK_CODE, hook)
for time_us, gain in [(13.195, 1), (20000, 1), (20000, 16), (66666, 32)]:
    sensitivity = time_us * 1000 * gain
    u.reg_write(UC_ARM64_REG_S9, struct.unpack('<I', struct.pack('<f', sensitivity))[0])
    u.emu_start(0x5a17c, 0x5a1d8, count=100)
    assert u.reg_read(UC_ARM64_REG_PC) == 0x5a1d8
    actual = struct.unpack('<f', struct.pack('<I', u.reg_read(UC_ARM64_REG_S9)))[0]
    expected = math.log10(time_us * gain / 13.195) * 77.89852905273438
    assert abs(actual-expected) < 0.0001, (actual, expected)
print('PASS stock AEC: log10(applied sensitivity / first exposure knee) / log10(1.03), four light levels')
