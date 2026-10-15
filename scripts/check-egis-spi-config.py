#!/usr/bin/env python3
"""Resolve Egis SPI device 8 using the phone's dumped TZ/DAL lookup code.

Run inside pmport with Unicorn and pyelftools. This is an offline check of
the slot-B firmware, not a live bus probe. Only the boot-time DAL registry
selector is stubbed; the original property lookup executes. No MMIO is mapped.
"""
import argparse
import hashlib
import io

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (
    UC_ARM64_REG_CPACR_EL1, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
    UC_ARM64_REG_SP, UC_ARM64_REG_X0,
)
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('tz', type=Path)
parser.add_argument('devcfg', type=Path)
args = parser.parse_args()
u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
for address, size in ((0x14680000, 0x40000), (0x1c000000, 0x600000),
                      (0x805fd000, 0x2000), (0x40000000, 0x20000)):
    u.mem_map(address, size)
for path, digest in (
    (args.tz, '264465b10032daa18a8c184bc16093dcc6b42adb088299c3c563a4a349014243'),
    (args.devcfg, '45ccc9922927c8cca2a627d4d679914eaf4846601aed1f0825bc5dacfac8a3df'),
):
    image = path.read_bytes()
    assert hashlib.sha256(image).hexdigest() == digest, f'Unexpected build: {path}'
    for segment in ELFFile(io.BytesIO(image)).iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr']:
            u.mem_write(segment['p_vaddr'], segment.data())

def registry(uc, address, size, context):
    if address == 0x1c0afb34:
        uc.reg_write(UC_ARM64_REG_X0, 0x1c003040)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

def word(address, width=8):
    return int.from_bytes(u.mem_read(address, width), 'little')

def string(address):
    return bytes(u.mem_read(address, 80)).split(b'\0')[0].decode('ascii')

stop = 0x40018000
u.reg_write(UC_ARM64_REG_SP, 0x40010000)
u.reg_write(UC_ARM64_REG_LR, stop)
u.reg_write(UC_ARM64_REG_X0, 8)
u.reg_write(UC_ARM64_REG_CPACR_EL1, 3 << 20)
u.hook_add(UC_HOOK_CODE, registry)
u.emu_start(0x1c0a8210, stop, count=200000)
assert u.reg_read(UC_ARM64_REG_PC) == stop, 'Lookup did not return'
descriptor = u.reg_read(UC_ARM64_REG_X0)
assert descriptor == 0x1c00a708
assert word(descriptor + 12, 1) == 8
base = word(descriptor) + word(descriptor + 8, 4)
assert base == 0xa88000
clock = string(word(descriptor + 0x20))
assert clock == 'gcc_qupv3_wrap1_s2_clk'
bus_clocks = word(descriptor + 0x28)
names = [string(word(bus_clocks + 8 * i)) for i in range(4)]
assert word(bus_clocks + 32) == 0
assert names == ['gcc_qupv3_wrap1_core_2x_clk', 'gcc_qupv3_wrap1_core_clk',
                 'gcc_qupv3_wrap_1_s_ahb_clk', 'gcc_qupv3_wrap_1_m_ahb_clk']
pins = [string(word(word(descriptor + off))) for off in (0x30, 0x38, 0x40, 0x48)]
assert pins == [f'qup1_se2_l{i}' for i in range(4)]
print(f'PASS original TZ lookup: SPI device 8 -> {base:#x}, {clock}')
print('Shared clocks:', ', '.join(names))
print('Pin functions:', ', '.join(pins))
print('Offline descriptor evidence only; no hardware transfer was tested.')
