#!/usr/bin/env python3
"""Execute vendor get_secure_key with synthetic wrapped messages, without hardware.

Checks the command constructor and response parser, including rejection paths.
Requires Unicorn and pyelftools inside pmport. No real key material is involved.
"""
import argparse
import hashlib
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
    UC_ARM64_REG_TPIDR_EL0, UC_ARM64_REG_CPACR_EL1)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('agent', type=Path)
args = parser.parse_args()
assert hashlib.sha256(args.agent.read_bytes()).hexdigest() == '9c0d71e46717d14ec7c315d32002419300f7232a68ad4b48d0ac4657a44bef99'


def check(status, length, capacity, transport):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    u.mem_map(0, 0x1000000)
    with args.agent.open('rb') as f:
        elf = ELFFile(f)
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                u.mem_write(segment['p_vaddr'], segment.data())
        for section in elf.iter_sections():
            if section['sh_type'] != 'SHT_RELA':
                continue
            symbols = elf.get_section(section['sh_link'])
            for rel in section.iter_relocations():
                if rel['r_info_type'] == 1027:
                    value = rel['r_addend']
                elif rel['r_info_type'] in (257, 1025, 1026):
                    value = symbols.get_symbol(rel['r_info_sym'])['st_value'] + rel['r_addend']
                else:
                    continue
                u.mem_write(rel['r_offset'], struct.pack('<Q', value))
    # Three global function-pointer slots use Android packed relocations.
    for i in range(3):
        u.mem_write(0x27940 + 8*i, struct.pack("<Q", 0x402000 + 8*i))
    output, sizep, stop = 0x400000, 0x401000, 0x900000
    u.mem_write(output, b'\xa5' * 512)
    u.mem_write(sizep, struct.pack('<I', capacity))
    u.reg_write(UC_ARM64_REG_X0, output)
    u.reg_write(UC_ARM64_REG_X1, sizep)
    u.reg_write(UC_ARM64_REG_SP, 0x800000)
    u.reg_write(UC_ARM64_REG_LR, stop)
    u.reg_write(UC_ARM64_REG_TPIDR_EL0, 0xa00000)
    u.reg_write(UC_ARM64_REG_CPACR_EL1, 3 << 20)
    calls = []
    def ret(value=0):
        u.reg_write(UC_ARM64_REG_X0, value)
        u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_LR))
    def string(p):
        return bytes(u.mem_read(p, 128)).split(b'\0')[0]
    def hook(u, address, size, _):
        v = [u.reg_read(UC_ARM64_REG_X0 + i) for i in range(5)]
        if address in (0x25710, 0x25720, 0x25c20):
            ret()
        elif address == 0x256c0:
            u.mem_write(v[0], bytes([v[1] & 255]) * v[2]); ret(v[0])
        elif address == 0x25a00:
            u.mem_write(v[0], bytes(u.mem_read(v[1], v[2]))); ret(v[0])
        elif address == 0x25bf0:
            assert string(v[0]) == b'libets_teeclient_v2.so'; ret(0xb10000)
        elif address == 0x25c10:
            ret({b'qsc_start_app': 0xb00000, b'qsc_shutdown_app': 0xb00010,
                 b'ets_keymaster_issue_send_modified_cmd_req': 0xb00020}[string(v[1])])
        elif address == 0xb00000:
            assert string(v[1]) == b'keymaster64' and v[2] == 0x2400
            u.mem_write(v[0], struct.pack('<Q', 0xb20000)); calls.append('open'); ret()
        elif address == 0xb00010:
            calls.append('close'); ret()
        elif address == 0xb00020:
            assert v[2] == 8 and bytes(u.mem_read(v[1], 8)) == struct.pack('<2I', 0x205, 2), (v[:3], bytes(u.mem_read(v[1], 8)).hex())
            assert struct.unpack('<I', u.mem_read(v[4], 4))[0] == 1036
            u.mem_write(v[3], struct.pack('<3I', status, 12, length) + b'\x3c' * min(length, 1024))
            calls.append('send'); ret(transport)
        elif address == 0x256f0:
            raise AssertionError('Stack protector failed')
        elif 0x25690 <= address < 0x26100:
            raise AssertionError(('Unexpected PLT', hex(address)))
    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x250ec, stop, count=100000)
    assert u.reg_read(UC_ARM64_REG_PC) == stop
    success = status == transport == 0 and length <= capacity
    assert u.reg_read(UC_ARM64_REG_X0) & 0xffffffff == (0 if success else 0xffffffff)
    expected = b'\x3c' * length + b'\xa5' * (512-length) if success else b'\xa5' * 512
    assert bytes(u.mem_read(output, 512)) == expected
    assert calls == ['open', 'send', 'close'], calls
    print(f'PASS status={status} length={length} capacity={capacity} transport={transport}')

for case in [(0, 152, 256, 0), (0, 256, 256, 0), (0, 257, 256, 0),
             (1, 152, 256, 0), (0, 152, 256, 1)]:
    check(*case)
