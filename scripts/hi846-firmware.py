#!/usr/bin/env python3
"""Pack this phone's decoded stock Hi846 register programs, without publishing blobs.

Input: out/dl-afcal/json/hi846_{front,back}_sensor.json, decoded from the
phone's CamX sensor-module binaries. Output: firmware aport (gitignored).
The kernel validates the magic, record count and exact file length.
"""
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'aports/device/testing/firmware-sony-pdx246'

def pack(entries):
    assert 0 < len(entries) <= 2048
    result = bytearray(b'HI846R1\0' + struct.pack('<I', len(entries)))
    for e in entries:
        assert (e['operation'], e['regAddrType'], e['regDataType'], e['delayUs']) == (0, 2, 2, 0)
        assert len(e['registerData']) == 1
        addr, value = int(e['registerAddr'], 16), e['registerData'][0]
        assert 0 <= addr <= 0x3fff and 0 <= value <= 0xffff
        result += struct.pack('<HH', addr, value)
    return result

for module in ('front', 'back'):
    doc = json.loads((ROOT / f'out/dl-afcal/json/hi846_{module}_sensor.json').read_text())
    data = doc['sensorDriverData']
    lists = [('init', data['initSettings']['value'][0]['regSetting']['value']['entries'])]
    modes = data['resolutionInfo']['value'][0]['resolutionData']['value']
    for meta, mode in zip(doc['derived']['modes'], modes, strict=True):
        width, height = meta['output']
        lists.append((f'{width}x{height}', mode['resSettings']['value']['entries']))
    for suffix, entries in lists:
        path = DEST / f'hi846-{module}-{suffix}.bin'
        blob = pack(entries)
        # Verify every emitted word against the decoded source, in order,
        # including duplicate writes (they must not be reduced to a map).
        assert list(struct.iter_unpack('<HH', blob[12:])) == [
            (int(e['registerAddr'], 16), e['registerData'][0]) for e in entries]
        path.write_bytes(blob)
        print(f'{path.name}: {len(entries)} ordered writes, {len(blob)} bytes')
