#!/usr/bin/env python3
"""Execute the actual GLES chroma filter and check noise, color and edges in pmport."""
from pathlib import Path
import runpy
import numpy as np
from PIL import Image
ctx = runpy.run_path(str(Path(__file__).with_name('check-packed-bayer.py')), run_name='egl_setup')
g, compileShader, compileProgram = ctx['g'], ctx['compileShader'], ctx['compileProgram']
vertex = ctx['vertex']
fragment = Path('out/libcamera-work/src/libcamera/shaders/chroma_denoise.frag').read_text()
program = compileProgram(compileShader(vertex,g.GL_VERTEX_SHADER), compileShader('#version 100\n'+fragment,g.GL_FRAGMENT_SHADER))
g.glUseProgram(program)
position=g.glGetAttribLocation(program,'vertexIn');g.glEnableVertexAttribArray(position)
g.glVertexAttribPointer(position,2,g.GL_FLOAT,False,0,None)
g.glUniform1i(g.glGetUniformLocation(program,'image'),0)
fbo=g.glGenFramebuffers(1); target=g.glGenTextures(1)
def render(a):
 h,w,_=a.shape
 g.glActiveTexture(g.GL_TEXTURE1);g.glBindTexture(g.GL_TEXTURE_2D,target)
 g.glTexImage2D(g.GL_TEXTURE_2D,0,g.GL_RGBA,w,h,0,g.GL_RGBA,g.GL_UNSIGNED_BYTE,None)
 g.glBindFramebuffer(g.GL_FRAMEBUFFER,fbo)
 g.glFramebufferTexture2D(g.GL_FRAMEBUFFER,g.GL_COLOR_ATTACHMENT0,g.GL_TEXTURE_2D,target,0)
 assert g.glCheckFramebufferStatus(g.GL_FRAMEBUFFER)==g.GL_FRAMEBUFFER_COMPLETE
 g.glActiveTexture(g.GL_TEXTURE0);g.glBindTexture(g.GL_TEXTURE_2D,ctx['texture'])
 g.glTexImage2D(g.GL_TEXTURE_2D,0,g.GL_RGB,w,h,0,g.GL_RGB,g.GL_UNSIGNED_BYTE,np.ascontiguousarray(a))
 g.glUniform2f(g.glGetUniformLocation(program,'pixel_step'),1/w,1/h)
 g.glViewport(0,0,w,h);g.glDrawArrays(g.GL_TRIANGLE_STRIP,0,4)
 return np.frombuffer(g.glReadPixels(0,0,w,h,g.GL_RGBA,g.GL_UNSIGNED_BYTE),np.uint8).reshape(h,w,4)[:,:,:3].copy()
rng=np.random.default_rng(15)
a=np.clip(np.array([150,120,90])+rng.normal(0,[20,8,20],(128,128,3)),0,255).astype(np.uint8)
b=render(a)
chroma=lambda a: a.astype(float)-np.einsum('ijk,k->ij',a,[.25,.5,.25])[:,:,None]
before=chroma(a)[5:-5,5:-5].std((0,1));after=chroma(b)[5:-5,5:-5].std((0,1))
assert np.all(after<before*.45),(before,after)
assert np.max(abs(b.mean((0,1))-a.mean((0,1))))<1
edge=np.zeros((64,64,3),np.uint8);edge[:,:32]=[20,20,20];edge[:,32:]=[235,235,235]
r=render(edge)
assert np.max(abs(r.astype(float)-edge))<=2
for color in [[32,192,64],[192,32,128],[255,255,255],[0,0,0]]:
 a=np.tile(np.array(color,np.uint8),(32,64,1));assert np.max(abs(render(a).astype(float)-a))<=1
print('PASS GLES chroma noise std',before.round(2),'->',after.round(2),'with color mean and hard edges preserved')
for name in ['front','wide']:
 p=Path('out/try-kernel/scene117-'+name+'.png')
 if p.exists():
  a=np.asarray(Image.open(p).convert('RGB'));Image.fromarray(render(a)).save(p.with_name('chroma-preview-'+name+'.png'))
