#!/usr/bin/env python3
"""Add Sony's decoded illuminants and shading grids to our camera tuning.

Run inside pmport. Input is out/dl-tuned, produced by its Chromatix decoder
from this phone's com.qti.tuned.*.bin files. No firmware is copied to aports.
The grids describe the whole active array, before rotation and mode cropping.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import re


def calibration(root, sensor):
    summary = json.loads((root / 'summary' / f'{sensor}.json').read_text())
    lines = ['      # Sensor-native R/G and B/G ratios from Sony Chromatix.',
             '      illuminants:']
    for point in sorted(summary['awb']['reference_points'], key=lambda p: p['cct']):
        assert all(math.isfinite(point[k]) and point[k] > 0 for k in ('cct', 'rg', 'bg'))
        lines += [f"        - {{ ct: {point['cct']}, rg: {point['rg']:.7f}, bg: {point['bg']:.7f} }}"]
    awb = '\n'.join(lines)
    lines = ['  - LensShading:',
             '      # No flash, no HDR, bright-scene TFE calibration from Sony.',
             '      # 17x13 grid, interleaved RGB; green averages Gr and Gb.',
             '      tables:']
    # The first lux band is the bright-scene table. Darker stock bands
    # attenuate shading correction along with other noise-processing stages.
    paths = sorted((root / 'lsc' / sensor / 'lsc35_tfe_v2').glob('*_lux1-*_cct*.csv'))
    if not paths:
        raise ValueError(f'No bright-scene shading grids for {sensor}')
    for path in paths:
        low, high = map(int, re.search(r'_cct(\d+)-(\d+)\.csv', path.name).groups())
        ct = (low + high) // 2
        rows = list(csv.reader(line for line in path.read_text().splitlines() if not line.startswith('#')))
        rows = [list(map(float, row)) for row in rows if row]
        assert len(rows) == 52 and all(len(row) == 17 for row in rows)
        lines += [f'        - ct: {ct}', '          gains: [']
        for y in range(13):
            values = []
            for x in range(17):
                values += [rows[y][x], (rows[13 + y][x] + rows[26 + y][x]) / 2, rows[39 + y][x]]
            assert all(math.isfinite(g) and 0.5 <= g <= 8 for g in values)
            lines.append('            ' + ', '.join(f'{v:.5f}' for v in values) + (',' if y != 12 else ''))
        lines.append('          ]')
    return awb, '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decoded', type=Path, default=Path('out/dl-tuned'))
    parser.add_argument('--tuning', type=Path, default=Path('aports/temp/libcamera'))
    args = parser.parse_args()
    for sensor, name in [('imx582', 'imx582'), ('le_hi846_back', 'hi846'),
                         ('le_hi846_front', 'hi846-front')]:
        awb, lsc = calibration(args.decoded, sensor)
        path = args.tuning / f'{name}.yaml'
        text = path.read_text()
        # Replaces only our generated blocks; preserves existing CCM/AGC/AF.
        text = re.sub(r'^  - Awb:\n.*?(?=^  - )', '  - Awb:\n' + awb + '\n', text, flags=re.S | re.M)
        text = re.sub(r'^  - LensShading:\n.*?(?=^  - |^\.\.\.)', '', text, flags=re.S | re.M)
        text = text.replace('  - Adjust:', lsc + '\n  - Adjust:')
        temporary = path.with_suffix('.yaml.tmp')
        temporary.write_text(text)
        temporary.replace(path)
        print(f'{path}: calibrated illuminants and lens shading')


if __name__ == '__main__':
    main()
