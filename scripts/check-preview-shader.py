#!/usr/bin/env python3
"""Compare optimized GPU preview output with the previous actual GLSL.

Run inside pmport after preparing out/libcamera-work and saving the previous
shader in out/preview-shader-before. Includes downsampling threshold, all
Bayer phases, RAW10/12, quad Bayer, noisy frames and hard edges.
"""
from pathlib import Path
import numpy as np
import importlib.util
spec = importlib.util.spec_from_file_location('packed', Path(__file__).with_name('check-packed-bayer.py'))
shader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shader)
old = Path('out/preview-shader-before/bayer_1x_packed.frag').read_text()
new = shader.fragment
rng = np.random.default_rng(741)
count = 0
for bits in (10, 12):
    raw = rng.integers(0, 1 << bits, (shader.H, shader.W), dtype=np.uint16)
    raw[:, :shader.W//4] = (1 << bits)//4
    for phase in ((0,0), (1,0), (0,1), (1,1)):
        for quad in (False, True):
            for footprint in ((1,1), (1.5,1.5), (1.51,1.51), (2.55,2.55), (4,3)):
                for noise in (0, 24/1020):
                    shader.fragment = old
                    before = shader.render(raw,bits,phase,noise=noise,quad=quad,footprint=footprint)
                    shader.fragment = new
                    after = shader.render(raw,bits,phase,noise=noise,quad=quad,footprint=footprint)
                    error = abs(after.astype(int)-before.astype(int)).max()
                    assert error <= 1, (bits, phase, quad, footprint, noise, error)
                    count += 1
print(f'PASS: {count} actual GLES before/after comparisons; maximum permitted difference 1/255')
