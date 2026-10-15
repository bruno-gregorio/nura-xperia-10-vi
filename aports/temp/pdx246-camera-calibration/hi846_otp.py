#!/usr/bin/env python3
"""Validate/decode a pdx246 Hi846 OTP read, without exposing module identity.

Input: the 5449-byte read-only NVMEM cache from the kernel driver.
The vendor decoder supplies section layout and WB formula. Both real sensors
also satisfy sum(payload) % 255 + 1 for their LSC and WB checksum bytes.
Output contains only calibration, never the module-information section.
LSC is kept as raw response values: conversion into ISP gains requires a
separately verified interpretation, not an assumed fixed-point division.
"""
import argparse
import json
from pathlib import Path
import struct


def decode(data):
    if len(data) != 5449:
        raise ValueError('Expected exactly 5449 OTP bytes')
    groups = {0x01: 0, 0x13: 1, 0x37: 2}
    result = {}
    for name, flag_offset, start, stride, length in [
        ('lsc', 52, 53, 1769, 1768), ('wb', 5360, 5361, 13, 12),
    ]:
        # Refuse mismatched groups rather than silently ORing flags and
        # selecting an unverified bank as the proprietary decoder does.
        if data[0] != data[flag_offset] or data[flag_offset] not in groups:
            raise ValueError(f'{name}: invalid or inconsistent group flags')
        group = groups[data[flag_offset]]
        offset = start + group * stride
        payload = data[offset:offset + length]
        if sum(payload) % 255 + 1 != data[offset + length]:
            raise ValueError(f'{name}: checksum mismatch')
        values = struct.unpack('>' + str(length // 2) + 'H', payload)
        result[name] = {'group': group, 'checksum_valid': True}
        if name == 'lsc':
            if not all(0 < value <= 4095 for value in values):
                raise ValueError('LSC response outside conservative sensor range')
            # The EEPROM library reads R/Gr/Gb/B interleaved at each
            # point (8 bytes), then writes four separate float planes.
            result[name].update(width=17, height=13, order=['R', 'Gr', 'Gb', 'B'],
                                layout='planar',
                                response=[values[p * 4 + c] for c in range(4)
                                          for p in range(221)])
        else:
            if any(value <= 1 for value in values[:3]):
                raise ValueError('WB ratio is zero or invalid')
            result[name].update(illuminant_kelvin=5000,
                rg=(values[0] - 0.5) / 1024,
                bg=(values[1] - 0.5) / 1024,
                gr_over_gb=1024 / (values[2] - 0.5))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('otp', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = decode(args.otp.read_bytes())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: LSC and WB groups/checksums; calibration decoded without module identity')


if __name__ == '__main__':
    main()
