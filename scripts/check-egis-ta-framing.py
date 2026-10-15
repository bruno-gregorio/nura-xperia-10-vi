#!/usr/bin/env python3
"""Execute the original TA entry bytes with logging/memcpy and factory state stubbed.
This checks framing, not QTEE transport, factory initialization or hardware.
"""
from pathlib import Path
import argparse
import hashlib
import struct
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('ta', type=Path, help='assembled egisap64 ELF from this phone')
args = parser.parse_args()
image = args.ta.read_bytes()
assert hashlib.sha256(image).hexdigest() == '647c4217b6ddc1602e93e5d210dba7f4b35eccefd56e03c736139a91afc30123', 'Unexpected TA build'
blob = image[4096:]
REQ,RSP,STACK,STOP,BROKER,LOGGER=0x400000,0x402000,0x600000,0x700000,0x800000,0x802000

def run(cmd,operand,reqsize,rspsize,bix=0,version=False):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0,0x900000);u.mem_write(0,blob)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    q(0x2518f0,BROKER)
    q(BROKER+40,0xdfd8);q(BROKER+32,0xde88);q(BROKER+56,0x801000)
    q(0x801000+40,0x14e9c);q(0x801000+32,0x14dd0);q(0x801000+64,0x801000)
    q(0x801000+104,0x801000+104);q(0x801000+112,0x801000+104)
    q(0x24d268,0x803000);q(0x24d278,0x803008);q(0x803008,LOGGER)
    q(LOGGER+40,STOP+4)
    req=bytearray(0x868);struct.pack_into('<I',req,0,cmd);struct.pack_into('<Q',req,8,operand);struct.pack_into('<I',req,108,bix)
    if version:
        struct.pack_into('<I',req,120,4);struct.pack_into('<HH',req,124,0,1)
        if operand:struct.pack_into('<I',req,24,4096)
    u.mem_write(REQ,bytes(req));u.mem_write(RSP,b'\xaa'*0x814)
    u.reg_write(UC_ARM64_REG_SP,STACK);u.reg_write(UC_ARM64_REG_LR,STOP)
    for r,v in [(UC_ARM64_REG_X0,REQ),(UC_ARM64_REG_X1,reqsize),(UC_ARM64_REG_X2,RSP),(UC_ARM64_REG_X3,rspsize)]:u.reg_write(r,v)
    def hook(u,addr,size,_):
        if addr in (0x40,0x50,0x60,0x70):
            u.reg_write(UC_ARM64_REG_X0,0);u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif addr in (0x30,STOP+4):u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif addr==0x2f78:
            dst,src,n=[u.reg_read(r) for r in (UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2)];u.mem_write(dst,bytes(u.mem_read(src,n)));u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x4b0,STOP,count=10000)
    assert u.reg_read(UC_ARM64_REG_PC)==STOP
    rsp=bytes(u.mem_read(RSP,0x814))
    if version and operand:
        assert bytes(u.mem_read(operand,37))==blob[0x12d7b6:0x12d7b6+37]
        assert struct.unpack_from("<I",rsp,36)[0]==37
    return rsp
assert run(1,7,64,64)==b'\xaa'*0x814
assert struct.unpack_from('<i',run(1,7,64,0x814),16)[0]==-7
for cmd,n,expected in [(0,0,1),(1,7,70),(1,3,30)]:
    rsp=run(cmd,n,0x868,0x814);assert struct.unpack_from('<I',rsp)[0]==expected;assert struct.unpack_from('<I',rsp,16)[0]==0
rsp=run(0xe0,0,0x868,0x814,0xe0000000)
assert struct.unpack_from('<I',rsp,16)[0]==2
assert struct.unpack_from('<I',rsp,24)[0]==0xe0000000
assert struct.unpack_from('<I',rsp,36)[0]==0
print('PASS original TA bytes: short-buffer rejection, cmd0, cmd1 operands 7/3, pointer-free BIX sentinel')

rsp=run(0xe0,0,0x868,0x814,0xffffffff,True)
assert struct.unpack_from('<I',rsp,16)[0]==7
rsp=run(0xe0,0x404000,0x868,0x814,0xffffffff,True)
assert struct.unpack_from('<I',rsp,16)[0]==0
print('PASS original TA bytes: BIX get property(0,1) returns buffer error with NULL; writes 37-byte version with output buffer')
