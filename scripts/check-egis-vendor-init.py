#!/usr/bin/env python3
"""Check EC617-specific defaults using the original vendor agent and serializer.

Run in pmport with Unicorn/pyelftools. No hardware or biometric data is used.
Logging/libc are stubbed; the actual family-selection branch must execute.
"""
import argparse, hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import *
from unicorn.arm64_const import *
import struct,json
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('agent',type=Path)
args=parser.parse_args()
assert hashlib.sha256(args.agent.read_bytes()).hexdigest() == '9c0d71e46717d14ec7c315d32002419300f7232a68ad4b48d0ac4657a44bef99'
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0,0x1000000)
with args.agent.open('rb') as f:
 for s in ELFFile(f).iter_segments():
  if s['p_type']=='PT_LOAD':u.mem_write(s['p_vaddr'],s.data())
CTX,STACK,STOP,TLS=0x400000,0x800000,0x900000,0xa00000
u.reg_write(UC_ARM64_REG_SP,STACK);u.reg_write(UC_ARM64_REG_LR,STOP);u.reg_write(UC_ARM64_REG_X0,CTX);u.reg_write(UC_ARM64_REG_TPIDR_EL0,TLS);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
def cstring(p):return bytes(u.mem_read(p,512)).split(b'\0')[0]
def ret(v=None):
 if v is not None:u.reg_write(UC_ARM64_REG_X0,v)
 u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
captured=[]
def hook(u,a,size,_):
 if a==0x25720:ret(0)
 elif a==0x25710:ret(0)
 elif a==0x25820:ret(len(cstring(u.reg_read(UC_ARM64_REG_X0))))
 elif a in [0x25830,0x25a00]:
  d,s,n=[u.reg_read(r) for r in [UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2]];u.mem_write(d,bytes(u.mem_read(s,n)));ret(d)
 elif a==0x256c0:
  d,v,n=[u.reg_read(r) for r in [UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2]];u.mem_write(d,bytes([v&255])*n);ret(d)
 elif a==0x25780:ret(0x500000)
 elif a==0x25840:
  p=u.reg_read(UC_ARM64_REG_X1);cmd,event,props,n,_,outsz=struct.unpack('<IIQIQI',u.mem_read(p,32));print('command',hex(cmd),'event',event,'props bytes',n)
  records=[]
  for i in range(n//24):
   rid,sz,ptr,val,pad=struct.unpack('<IIQII',u.mem_read(props+24*i,24));data=bytes(u.mem_read(ptr,sz)) if ptr else struct.pack('<I',val)[:sz]
   print(hex(rid),sz,'ptr' if ptr else 'value',(data.hex() if sz<40 else 'zero='+str(not any(data))));records.append(dict(id=rid,size=sz,data=data.hex()))
  captured.append((cmd,p,records));u.emu_stop()
 elif 0x25600<=a<0x26000:raise Exception(hex(a))
u.hook_add(UC_HOOK_CODE,hook)
u.reg_write(UC_ARM64_REG_X19,CTX);u.reg_write(UC_ARM64_REG_X15,0)
u.emu_start(0x1c44c,0x1c588,count=20000)
u.reg_write(UC_ARM64_REG_X22,CTX+564)
u.emu_start(0x1c620,0x1c70c,count=20000)
u.mem_write(CTX+584,b'TestAccount\0');u.mem_write(CTX+16,b'Linux\0')
print('common',struct.unpack('<4I',u.mem_read(CTX+528,16)))
for entry in [0x1996c]:
 u.reg_write(UC_ARM64_REG_SP,STACK);u.reg_write(UC_ARM64_REG_LR,STOP);u.reg_write(UC_ARM64_REG_X0,CTX)
 u.emu_start(entry,STOP,count=20000)

 cmd,p,records=captured[-1]
 payload=b''.join(struct.pack('<II',r['id'],r['size'])+bytes.fromhex(r['data']) for r in records)
 expected=struct.pack('<II',len(records),len(payload))+payload
 u.mem_write(0x410000,bytes(u.mem_read(p,40)))
 u.reg_write(UC_ARM64_REG_SP,0x700000);u.reg_write(UC_ARM64_REG_LR,STOP)
 u.reg_write(UC_ARM64_REG_X0,0x410000);u.reg_write(UC_ARM64_REG_X1,0x410100)
 u.emu_start(0x2075c,STOP,count=20000)
 assert u.reg_read(UC_ARM64_REG_PC)==STOP
 n=struct.unpack('<I',u.mem_read(0x410100,4))[0]
 actual=bytes(u.mem_read(u.reg_read(UC_ARM64_REG_X0),n))
 assert actual==expected,(len(actual),len(expected))
 assert cmd == 0x8001
 assert records == [dict(id=key,size=len(data),data=data.hex()) for key,data in [
  (0x46040101,struct.pack('<2I',2,7)),
  (0x62040101,struct.pack('<I',48)),
  (0x62040118,struct.pack('<I',800)),
  (0x62040119,struct.pack('<I',500)),
  (0x62040106,struct.pack('<I',50)),
  (0x23000101,struct.pack('<I',1)),
 ]], records
 print('PASS original serializer',hex(cmd),'payload bytes',n)
