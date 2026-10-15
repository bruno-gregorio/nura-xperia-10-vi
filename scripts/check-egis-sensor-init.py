#!/usr/bin/env python3
"""Validate the recovered sensor-init request against the original Egis TA.

Run inside pmport with Unicorn. Emulates TA initialization and C runtime
relocations, supplies fake RAM allocation/time, then stops before SPI access.
Optional synthetic SPI responses exercise error handling and the first reset
callback. None of these modes accesses hardware or proves live initialization.
"""
import argparse
import hashlib
from pathlib import Path
import struct,time
from unicorn import *
from unicorn.arm64_const import *
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('ta',type=Path)
parser.add_argument('--mode', choices=['open', 'spi-error', 'transfer-error', 'wrong-id', 'reset-callback'],
                    default='open')
parser.add_argument('--stock-layout', action='store_true',
                    help='alias request/response and supply both vendor pointer fields')
parser.add_argument('--power-cycle', action='store_true',
                    help='execute recovered SPI power notifications before sensor init')
parser.add_argument('--token-context', choices=['accepted', 'bad-sender', 'bad-size', 'rejected'],
                    help='check original token handler with synthetic decapsulation replies')
args=parser.parse_args()
if args.token_context and args.mode in ('open', 'spi-error'):
 parser.error('--token-context needs a mode with successful SPI open')
if args.power_cycle and args.mode in ('open', 'spi-error'):
 parser.error('--power-cycle needs a mode with successful SPI open')
image=args.ta.read_bytes()
assert hashlib.sha256(image).hexdigest() == '647c4217b6ddc1602e93e5d210dba7f4b35eccefd56e03c736139a91afc30123', 'Unexpected TA build'
b=image[4096:]
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0,0x1000000);u.mem_write(0,b)
tags=dict(struct.iter_unpack('<QQ',b[0x255000:0x255000+304]));syms=tags[6];strings=tags[5];imports={}
def symbol(i):
 no,info,other,shndx,val,sz=struct.unpack_from('<IBBHQQ',b,syms+i*24)
 return b[strings+no:].split(b'\0')[0].decode(),val
for off,info,add in struct.iter_unpack('<QQq',b[tags[23]:tags[23]+tags[2]]):
 name,val=symbol(info>>32);imports[off]=name
for off,info,add in struct.iter_unpack('<QQq',b[tags[7]:tags[7]+tags[8]]):
 typ=info&0xffffffff
 if typ==1027:u.mem_write(off,struct.pack('<Q',add))
 elif typ in [257,1025,1026]:
  name,val=symbol(info>>32)
  if val:u.mem_write(off,struct.pack('<Q',val+add))
  elif name:imports[off]=name
 else:raise AssertionError(('Unsupported relocation',typ))
hooks={}
for i,(off,name) in enumerate(imports.items()):
 addr=0xb00000+16*i;u.mem_write(off,struct.pack('<Q',addr));hooks[addr]=name
heap=0x400000;allocs={};STOP=0xc00000;hardware_call=[];transfers=[];closes=[]
registers = {0xff: 6, 0xfe: 0x11, 0xfd: 0} if args.mode == 'reset-callback' else {}
u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
def ret(v=None):
 if v is not None:u.reg_write(UC_ARM64_REG_X0,v)
 u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
def cstring(a):return bytes(u.mem_read(a,512)).split(b'\0')[0].decode(errors='replace')
def hook(u,a,size,_):
 global heap
 if a not in hooks:return
 name=hooks[a];v=[u.reg_read(UC_ARM64_REG_X0+i) for i in range(8)]
 if name=='qsee_log':ret(0)
 elif name=='qsee_decapsulate_inter_app_message':
  assert args.token_context, 'Unexpected token decapsulation'
  assert v[2] == 152 and bytes(u.mem_read(v[1],v[2])) == bytes([0x3c])*152
  assert struct.unpack('<I',u.mem_read(v[4],4))[0] == 32
  if args.token_context == 'rejected':ret(1)
  else:
   sender=b'invalid' if args.token_context == 'bad-sender' else b'keymaster'
   length=31 if args.token_context == 'bad-size' else 32
   u.mem_write(v[0],sender+b'\0'*(32-len(sender)))
   u.mem_write(v[3],bytes(length));u.mem_write(v[4],struct.pack('<I',length));ret(0)
 elif name=='qsee_malloc':
  n=v[0];p=heap;heap+=(n+15)&~15;assert heap<0x700000;allocs[p]=n;ret(p)
 elif name=='qsee_realloc':
  n=v[1];p=heap;heap+=(n+15)&~15;assert heap<0x700000
  if v[0]:u.mem_write(p,bytes(u.mem_read(v[0],min(allocs[v[0]],n))))
  allocs[p]=n;ret(p)
 elif name=='qsee_spi_close':closes.append(v[0]);ret(0)
 elif name in ['qsee_log_set_mask','qsee_free','qsee_register_shared_buffer','qsee_prepare_shared_buf_for_secure_read','qsee_deregister_shared_buffer','qsee_prepare_shared_buf_for_nosecure_read']:ret(0)
 elif name=='qsee_strlcpy':
  s=cstring(v[1]).encode();u.mem_write(v[0],s[:max(0,v[2]-1)]+b'\0');ret(len(s))
 elif name=='qsee_get_uptime':ret(123456)
 elif name=='qsee_spi_open':
  hardware_call.append(v[0])
  if args.mode == 'open':u.emu_stop()
  else:ret(1 if args.mode == 'spi-error' else 0)
 elif name=='qsee_spi_full_duplex':
  # EC617 register transactions recovered from the original code. These
  # bytes are synthetic; they are never sent to the phone.
  tx,n,_=struct.unpack('<QII',u.mem_read(v[2],16))
  rx,rn,_=struct.unpack('<QII',u.mem_read(v[3],16))
  assert n == rn == 3, 'Unexpected SPI transaction'
  request=bytes(u.mem_read(tx,n));reply=bytearray(rn)
  transfers.append(request)
  if args.mode == 'transfer-error':
   ret(1)
   return
  if request[0] == 0x20:reply[2]=registers.get(request[1],0)
  elif request[0] == 0x24:registers[request[1]]=request[2]
  else:raise AssertionError(('Unexpected SPI opcode',request[0]))
  u.mem_write(rx,bytes(reply))
  u.mem_write(v[2]+12,struct.pack('<I',n))
  u.mem_write(v[3]+12,struct.pack('<I',rn))
  ret(0)
 else:raise AssertionError(('Unexpected secure service',name))
def run(entry,arguments,expect_spi=False):
 u.reg_write(UC_ARM64_REG_SP,0x800000);u.reg_write(UC_ARM64_REG_LR,STOP)
 for i,v in enumerate(arguments):u.reg_write(UC_ARM64_REG_X0+i,v)
 u.emu_start(entry,STOP,count=2000000)
 if expect_spi:assert hardware_call and all(device == 8 for device in hardware_call)
 if not expect_spi or args.mode != 'open':assert u.reg_read(UC_ARM64_REG_PC)==STOP
u.hook_add(UC_HOOK_CODE,hook)
run(0x380,[]);print('PASS original TA initialization with C runtime relocations')
REQ,RSP,DATA=0x900000,0x901000,0x902000
if args.stock_layout:RSP=REQ
def send(req):
 # libets_teeclient_v2.so 0x2c68..0x2c9c and 0x2d6c..0x2d8c:
 # same shared output at offsets 8/16, marker 0x5a, aliased req/rsp.
 if args.stock_layout:
  struct.pack_into('<Q',req,16,DATA);req[40]=0x5a
 u.mem_write(REQ,bytes(req));run(0x4b0,[REQ,0x880,RSP,0x840],expect_spi=True)
if args.power_cycle:
 for enabled in (1,0,1):
  power=bytearray(0x880)
  struct.pack_into('<I',power,0,0xe0);struct.pack_into('<Q',power,8,DATA)
  struct.pack_into('<I',power,24,4096);struct.pack_into('<I',power,108,0x8004)
  struct.pack_into('<I',power,120,20)
  power[124:144]=struct.pack('<5I',1,12,0x20070103,4,enabled)
  send(power)
  assert struct.unpack('<I',u.mem_read(RSP+16,4))[0] == 0
 assert hardware_call == [8,8] and closes == [8], (hardware_call,closes)
 print('PASS original TA SPI power notification: open, close, reopen device 8')
if args.token_context:
 # This is a synthetic service reply, not real key material or authentication.
 token=bytearray(0x880)
 struct.pack_into('<I',token,0,0xe0);struct.pack_into('<Q',token,8,DATA)
 struct.pack_into('<I',token,24,4096);struct.pack_into('<I',token,108,0x6000)
 body=struct.pack('<4I',1,160,0x21040105,152)+bytes([0x3c])*152
 struct.pack_into('<I',token,120,len(body));token[124:124+len(body)]=body
 send(token)
 status=struct.unpack('<I',u.mem_read(RSP+16,4))[0]
 assert status == (0 if args.token_context == 'accepted' else 1), status
 assert struct.unpack('<I',u.mem_read(RSP+36,4))[0] == 0
 print('PASS original TA token handler: synthetic '+args.token_context)
req=bytearray(0x880);struct.pack_into('<I',req,0,0xe0);struct.pack_into('<Q',req,8,DATA);struct.pack_into('<I',req,24,4096);struct.pack_into('<I',req,108,0x8001)
properties=[(0x46040101,[2,7]),(0x62040101,[48]),(0x62040118,[800]),(0x62040119,[500]),(0x62040106,[50]),(0x23000101,[1])]
records=b''.join(struct.pack('<II'+'I'*len(v),key,len(v)*4,*v) for key,v in properties)
payload=struct.pack('<II',len(properties),len(records))+records
assert len(payload)==84
struct.pack_into('<I',req,120,len(payload));req[124:124+len(payload)]=payload
send(req)
if args.mode == 'open':
 print('PASS original TA parses sensor-init properties and reaches qsee_spi_open(8); stopped before hardware access')
else:
 status=struct.unpack('<I',u.mem_read(RSP+16,4))[0]
 expected={'spi-error':0xffffffff,'transfer-error':16,'wrong-id':16,'reset-callback':10}[args.mode]
 assert status == expected, (args.mode,status,expected)
 if args.mode == 'spi-error':assert not transfers
 else:assert transfers and transfers[0] == bytes([0x20,0xfd,0])
 if args.mode == 'reset-callback':
  length=struct.unpack('<I',u.mem_read(RSP+36,4))[0]
  words=struct.unpack('<11I',u.mem_read(DATA,44))
  assert length == 44 and words[0] == words[4] == 1
  assert words[5] == 20 and words[7:10] == (8,4,4) and words[10] in (1,2)
 print('PASS original TA synthetic '+args.mode+' response; no real sensor tested')
