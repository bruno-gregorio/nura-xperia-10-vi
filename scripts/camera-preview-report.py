#!/usr/bin/env python3
"""Summarize PLASMA_CAMERA_TRACE=1 logs without conflating capture and display.

Reports completed preview frames and V4L2 timestamp-to-owned-QImage age.
This excludes compositor/scanout time and is not a glass-to-glass measurement.
The first 30 frames after each camera reconfiguration are excluded.
"""
import argparse
from pathlib import Path
import re
import statistics
from collections import deque

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('logs', nargs='+', type=Path)
args = parser.parse_args()
pattern = re.compile(r'PreviewTrace (preview|still) (\d+) (\d+) (\d+) QSize\((\d+), (\d+)\)')
for log in args.logs:
    segments, current = [], []
    pending, sink_ages, sink_times = deque(), [], []
    for line in log.read_text().splitlines():
        sink = re.search(r'PreviewSinkTrace (\d+)', line)
        if sink and pending:
            sensor = pending.popleft()
            now = int(sink.group(1))
            sink_ages.append((now - sensor)/1e6)
            sink_times.append(now)
        match = pattern.search(line)
        if not match:
            continue
        kind, sequence, now, sensor, width, height = match.groups()
        row = tuple(map(int, (sequence, now, sensor, width, height)))
        if kind == 'still' or (current and row[0] <= current[-1][0]):
            if current:
                segments.append(current)
                current = []
        if kind == 'preview':
            current.append(row)
            pending.append(row[2])
    if current:
        segments.append(current)
    print(log)
    if not segments:
        print('  No preview trace records')
    for i, segment in enumerate(segments):
        rows = segment[30:]
        if len(rows) < 2:
            print(f'  Segment {i+1}: insufficient frames after warmup')
            continue
        ages = sorted((r[1]-r[2])/1e6 for r in rows)
        elapsed = (rows[-1][1]-rows[0][1])/1e9
        fps = (len(rows)-1)/elapsed
        p95 = ages[min(len(ages)-1, int(.95*len(ages)))]
        print(f'  Segment {i+1}: {rows[0][3]}x{rows[0][4]}, {len(rows)} frames, '
              f'{fps:.1f} completed fps; buffer age median {statistics.median(ages):.1f} ms, '
              f'p95 {p95:.1f} ms')
    if len(sink_ages) > 31:
        ages = sorted(sink_ages[30:])
        fps = (len(sink_times)-31)*1e9/(sink_times[-1]-sink_times[30])
        print(f'  Qt sink: {fps:.1f} submitted fps; timestamp-to-sink median '
              f'{statistics.median(ages):.1f} ms, p95 {ages[int(.95*len(ages))]:.1f} ms '
              '(excludes compositor/scanout)')
