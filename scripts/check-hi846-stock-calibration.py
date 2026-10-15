#!/usr/bin/env python3
"""Check the OTP correction formula by executing the original CamX instructions.

Run inside pmport with Python Unicorn and pyelftools. All inputs are synthetic
calibration grids; this does not read module identity or touch a device.
"""
import argparse
import hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
import struct
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn.arm64_const import *
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('camera',type=Path,help='dumped camera.qcom.so from pdx246')
args=parser.parse_args()
assert hashlib.sha256(args.camera.read_bytes()).hexdigest() == '113f454d77c42b16a0db8d79f77c506fef776e5bc56299c0ddee5f90ec34914a', 'Unexpected CamX build'
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0,0x2000000);u.mem_map(0x3000000,0x10000)
with args.camera.open('rb') as f:
 for s in ELFFile(f).iter_segments():
  if s['p_type']=='PT_LOAD':u.mem_write(s['p_vaddr'],s.data())
def w(a,fmt,*v):u.mem_write(a,struct.pack('<'+fmt,*v))
ctx,chrom,golden,ptrs=0x3000000,0x3001000,0x3002000,0x3003000
w(ctx+8,'Q',chrom);w(ctx+112,'Q',ptrs);w(ctx+120,'I',1);w(chrom+120,'I',1);w(chrom+128,'Q',golden)
for c in range(4):
 addr=0x3004000+c*0x1000;w(ptrs+c*8,'Q',addr)
 w(addr,'221f',*[250+c*13+i for i in range(221)])
 w(golden+8+c*884,'221f',*[500+c*9+i for i in range(221)])
u.reg_write(UC_ARM64_REG_X20,ctx);u.reg_write(UC_ARM64_REG_SP,0x300f000)
u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
u.emu_start(0x1091664,0x10919e0,count=50000)
assert u.reg_read(UC_ARM64_REG_PC)==0x10919e0
for c in range(4):
 result=struct.unpack('<221f',u.mem_read(0x3004000+c*0x1000,884))
 assert max(abs(v-(500+c*9+i)/(250+c*13+i)) for i,v in enumerate(result))<1e-6
print('PASS original CamX instructions: per-channel correction is golden_response / OTP_response, all 884 entries')
