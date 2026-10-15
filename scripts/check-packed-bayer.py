#!/usr/bin/env python3
"""Exercise the actual packed-Bayer GLSL with Mesa EGL inside pmport.

Requires python3-opengl, numpy and Mesa; uses a surfaceless pbuffer.
Checks RAW10/RAW12 low bits, Bayer phases, padded strides and image edges.
"""
import os
os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('EGL_PLATFORM', 'surfaceless')
from pathlib import Path
import ctypes
import numpy as np
from OpenGL import EGL as e
from OpenGL import GL as g
from OpenGL.GL.shaders import compileShader, compileProgram

W, H = 64, 32
display = e.eglGetDisplay(e.EGL_DEFAULT_DISPLAY)
major, minor = e.EGLint(), e.EGLint()
assert e.eglInitialize(display, major, minor)
assert e.eglBindAPI(e.EGL_OPENGL_ES_API)
attrs = (e.EGLint * 13)(e.EGL_SURFACE_TYPE, e.EGL_PBUFFER_BIT,
                        e.EGL_RENDERABLE_TYPE, e.EGL_OPENGL_ES2_BIT,
                        e.EGL_RED_SIZE, 8, e.EGL_GREEN_SIZE, 8,
                        e.EGL_BLUE_SIZE, 8, e.EGL_ALPHA_SIZE, 8, e.EGL_NONE)
configs = (e.EGLConfig * 1)()
count = e.EGLint()
assert e.eglChooseConfig(display, attrs, configs, 1, count) and count.value
surface = e.eglCreatePbufferSurface(display, configs[0],
    (e.EGLint * 5)(e.EGL_WIDTH, W, e.EGL_HEIGHT, H, e.EGL_NONE))
context = e.eglCreateContext(display, configs[0], e.EGL_NO_CONTEXT,
    (e.EGLint * 3)(e.EGL_CONTEXT_CLIENT_VERSION, 2, e.EGL_NONE))
assert e.eglMakeCurrent(display, surface, surface, context)
print('Renderer:', g.glGetString(g.GL_RENDERER).decode())
g.glDisable(g.GL_DITHER)
g.glPixelStorei(g.GL_UNPACK_ALIGNMENT, 1)
g.glViewport(0, 0, W, H)
vertex = '''#version 100
attribute vec2 vertexIn;
varying vec2 textureOut;
void main() { gl_Position = vec4(vertexIn, 0.0, 1.0);
textureOut = (vertexIn + 1.0) * 0.5; }
'''
fragment = Path('out/libcamera-work/src/libcamera/shaders/bayer_1x_packed.frag').read_text()
vertices = np.array([-1,-1, 1,-1, -1,1, 1,1], dtype=np.float32)
buffer = g.glGenBuffers(1)
g.glBindBuffer(g.GL_ARRAY_BUFFER, buffer)
g.glBufferData(g.GL_ARRAY_BUFFER, vertices.nbytes, vertices, g.GL_STATIC_DRAW)
texture = g.glGenTextures(1)
g.glActiveTexture(g.GL_TEXTURE0)
g.glBindTexture(g.GL_TEXTURE_2D, texture)
for parameter, value in ((g.GL_TEXTURE_MIN_FILTER, g.GL_NEAREST),
                         (g.GL_TEXTURE_MAG_FILTER, g.GL_NEAREST),
                         (g.GL_TEXTURE_WRAP_S, g.GL_CLAMP_TO_EDGE),
                         (g.GL_TEXTURE_WRAP_T, g.GL_CLAMP_TO_EDGE)):
    g.glTexParameteri(g.GL_TEXTURE_2D, parameter, value)

def render(raw, bits, phase, gain=1.0, black=0.0, noise=0.0, quad=False, footprint=(1,1)):
    program = compileProgram(compileShader(vertex, g.GL_VERTEX_SHADER),
        compileShader('#version 100\n#define RAW%dP\n' % bits +
                      ('#define QUAD_BAYER\n' if quad else '') + fragment,
                      g.GL_FRAGMENT_SHADER))
    g.glUseProgram(program)
    location = lambda name: g.glGetUniformLocation(program, name)
    g.glUniform2f(location('tex_size'), W, H)
    lanes, low_bits = (4, 2) if bits == 10 else (2, 4)
    stride = W * (lanes + 1) // lanes + 8
    packed = np.full((H, stride), 0xa5, dtype=np.uint8)
    for group in range(W // lanes):
        values = raw[:, group*lanes:(group+1)*lanes]
        packed[:, group*(lanes+1):group*(lanes+1)+lanes] = values >> low_bits
        packed[:, group*(lanes+1)+lanes] = sum(
            (values[:, i] & ((1 << low_bits)-1)) << (i*low_bits) for i in range(lanes))
    g.glTexImage2D(g.GL_TEXTURE_2D, 0, g.GL_LUMINANCE, stride, H, 0,
                   g.GL_LUMINANCE, g.GL_UNSIGNED_BYTE, packed)
    g.glUniform1i(location('tex_y'), 0)
    # Samplers of another type must use a distinct unit, even when disabled.
    g.glUniform1i(location('lens_shading'), 1)
    g.glUniform1i(location('lens_shading_enabled'), 0)
    g.glUniform2f(location('tex_step'), 1/stride, 1/H)
    g.glUniform2f(location('tex_bayer_first_red'), *phase)
    g.glUniform3f(location('awb'), gain, gain, gain)
    g.glUniform3f(location('blacklevel'), black, black, black)
    g.glUniformMatrix3fv(location('ccm'), 1, False, np.eye(3, dtype=np.float32))
    g.glUniform1f(location('gamma'), 1)
    g.glUniform1f(location('contrastExp'), 1)
    g.glUniform1f(location('bayer_denoise'), noise)
    g.glUniform2f(location('pixel_footprint'), *footprint)
    attribute = g.glGetAttribLocation(program, 'vertexIn')
    g.glEnableVertexAttribArray(attribute)
    g.glVertexAttribPointer(attribute, 2, g.GL_FLOAT, False, 0, ctypes.c_void_p(0))
    g.glDrawArrays(g.GL_TRIANGLE_STRIP, 0, 4)
    output = g.glReadPixels(0, 0, W, H, g.GL_RGBA, g.GL_UNSIGNED_BYTE)
    result = np.frombuffer(output, np.uint8).reshape(H, W, 4)[:,:,:3].copy()
    g.glDeleteProgram(program)
    return result

def reference(raw, bits, phase, quad=False):
    output = np.empty((H, W, 3))
    scale = 255 * (1 << (bits - 8))
    def sample(x, y):
        if quad:
            x, y = max(0, min(W-2, x//2*2)), max(0, min(H-2, y//2*2))
            return float(raw[y:y+2,x:x+2].mean()) / scale
        x, y = min(abs(x), 2*(W-1)-x), min(abs(y), 2*(H-1)-y)
        return float(raw[y,x]) / scale
    step = 2 if quad else 1
    for y in range(H):
        for x in range(W):
            cx, cy = x//step*step, y//step*step
            c = sample(cx,cy)
            h = (sample(cx-step,cy) + sample(cx+step,cy))/2
            v = (sample(cx,cy-step) + sample(cx,cy+step))/2
            d = sum(sample(cx+dx,cy+dy) for dx in (-step,step) for dy in (-step,step))/4
            values = ((c,(h+v)/2,d), (h,c,v), (v,c,h), (d,(h+v)/2,c))
            index = ((cx//step+phase[0])%2) + 2*((cy//step+phase[1])%2)
            output[y,x] = values[index]
    return np.rint(np.clip(output,0,1)*255)

if __name__ == '__main__':
    rng = np.random.default_rng(42)
    for bits in (10,12):
        for phase in ((0,0),(1,0),(0,1),(1,1)):
            raw = rng.integers(0, 1 << bits, (H,W), dtype=np.uint16)
            for quad in (False, True):
                actual = render(raw,bits,phase,quad=quad)
                expected = reference(raw,bits,phase,quad)
                error = np.max(np.abs(actual.astype(float)-expected))
                assert error <= 1, (bits,phase,quad,error)
        # Amplify low bits enough to distinguish them after 8-bit output conversion.
        low_bits = bits-8
        levels = (1 << low_bits)
        raw = np.full((H,W), 16 << low_bits, np.uint16)
        for i in range(levels):
            raw[:, i*W//levels:(i+1)*W//levels] += i
        actual = render(raw,bits,(0,0), gain=64, black=16/255)
        centres = actual[H//2, [int((i+.5)*W/levels) for i in range(levels)], 1]
        assert np.all(np.diff(centres.astype(int)) > 0), (bits, centres)
        print(f'RAW{bits}: four phases, quad Bayer, padding, edges and low bits PASS')

    raw = np.clip(300 + rng.normal(0,12,(H,W)), 0,1023).astype(np.uint16)
    plain = render(raw,10,(0,0))
    filtered = render(raw,10,(0,0),noise=24/1020)
    before = plain[4:-4,4:-4].astype(float).std(axis=(0,1))
    after = filtered[4:-4,4:-4].astype(float).std(axis=(0,1))
    assert np.all(after < before * .85), (before,after)
    assert abs(filtered.mean()-plain.mean()) < 1
    print('Synthetic noise standard deviation:', before.round(2), '->', after.round(2))
    integrated = render(raw,10,(0,0),footprint=(3.0,3.0))
    integrated_std = integrated[4:-4,4:-4].astype(float).std(axis=(0,1))
    assert np.all(integrated_std < before * .85), (before, integrated_std)
    assert abs(integrated.mean()-plain.mean()) < 1
    for phase in ((0,0),(1,0),(0,1),(1,1)):
        yy,xx = np.indices((H,W))
        index = ((xx+phase[0])%2) + 2*((yy+phase[1])%2)
        mosaic = np.array([600,400,400,200], dtype=np.uint16)[index]
        actual = render(mosaic,10,phase,footprint=(3.0,3.0))
        assert np.max(np.abs(actual.astype(float)-np.array([150,100,50]))) <= 1
    print('PASS: preview footprint preserves all CFA colors and reduces noise:', integrated_std.round(2))
    print('PASS: actual GLES shader output, not a reimplementation-only test')
    e.eglMakeCurrent(display,e.EGL_NO_SURFACE,e.EGL_NO_SURFACE,e.EGL_NO_CONTEXT)
    e.eglDestroyContext(display,context)
    e.eglDestroySurface(display,surface)
    e.eglTerminate(display)
