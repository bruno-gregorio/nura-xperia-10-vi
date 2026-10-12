#!/usr/bin/env python3
"""Save what a CRTC is scanning out as a PNG. Runs on the phone, as root.

    kms-shot.py [OUT.png] [--scale N] [--card /dev/dri/card0]

This is how the loop sees the screen without anyone looking at it. It asks
for the framebuffer on each CRTC's primary plane with GETFB2, which hands
out buffer handles only to the DRM master or to CAP_SYS_ADMIN, exports the
buffer as a dma-buf and reads it through mmap, the way ffmpeg's kmsgrab
does. It only reads: it needs no master, sets nothing, and the compositor
never notices.

Only linear 32-bit RGB buffers are understood. A tiled or compressed one
(a non-zero modifier) is reported and left alone. Every Nth pixel of every
Nth row is kept, 3 by default, which keeps the PNG small enough to copy
back quickly; it is a look at the screen, not a capture of it.

Standard library only, since it runs on whatever Python the image has.
"""
import ctypes
import fcntl
import mmap
import os
import struct
import sys
import zlib


def iowr(nr, size, kind=0x64):
    return (3 << 30) | (size << 16) | (kind << 8) | nr


def iow(nr, size, kind=0x64):
    return (1 << 30) | (size << 16) | (kind << 8) | nr


# struct drm_mode_card_res: four u64 array pointers, four u32 counts, four
# u32 limits.
CARD_RES = "QQQQIIIIIIII"
GETRESOURCES = iowr(0xA0, struct.calcsize(CARD_RES))
# struct drm_mode_crtc: set_connectors_ptr, count_connectors, crtc_id,
# fb_id, x, y, gamma_size, mode_valid, then a 68-byte drm_mode_modeinfo.
CRTC = "QIIIIIII68s"
GETCRTC = iowr(0xA1, struct.calcsize(CRTC))
# struct drm_mode_fb_cmd2: fb_id, width, height, pixel_format, flags,
# handles[4], pitches[4], offsets[4], 4 bytes of padding, modifier[4].
FB2 = "IIIII4I4I4I4xQQQQ"
GETFB2 = iowr(0xCE, struct.calcsize(FB2))
# struct drm_prime_handle: handle, flags, fd.
PRIME = "IIi"
PRIME_HANDLE_TO_FD = iowr(0x2D, struct.calcsize(PRIME))
GEM_CLOSE = iow(0x09, 8)
# struct dma_buf_sync: u64 flags. READ is 1, START 0 and END 4.
DMA_BUF_SYNC = iow(0, 8, kind=0x62)

FB_MODIFIERS = 1 << 1
O_CLOEXEC = 0o2000000

# fourcc -> byte offsets of red, green and blue in a little-endian pixel.
FORMATS = {
    b"XR24": (2, 1, 0), b"AR24": (2, 1, 0),
    b"XB24": (0, 1, 2), b"AB24": (0, 1, 2),
}


def ioctl(fd, request, fmt, *values):
    buf = bytearray(struct.pack(fmt, *values))
    fcntl.ioctl(fd, request, buf, True)
    return struct.unpack(fmt, buf)


def crtc_fbs(fd):
    res = ioctl(fd, GETRESOURCES, CARD_RES, *([0] * 12))
    count = res[5]
    ids = bytearray(4 * count)
    ioctl(fd, GETRESOURCES, CARD_RES, 0, address(ids), 0, 0, 0, count, 0, 0,
          0, 0, 0, 0)
    for crtc_id in struct.unpack(f"{count}I", ids):
        crtc = ioctl(fd, GETCRTC, CRTC, 0, 0, crtc_id, 0, 0, 0, 0, 0,
                     bytes(68))
        yield crtc_id, crtc[3]


def address(buf):
    return ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf))


def png(path, width, height, rows):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\0" + row for row in rows)
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data)


def shot(fd, fb_id, out, scale):
    (_, width, height, fourcc, flags, h0, _, _, _, pitch, _, _, _,
     offset, _, _, _, modifier, _, _, _) = ioctl(
        fd, GETFB2, FB2, fb_id, *([0] * 20))
    name = struct.pack("<I", fourcc)
    mod = modifier if flags & FB_MODIFIERS else 0
    print(f"fb {fb_id}: {width}x{height} {name.decode('ascii', 'replace')} "
          f"modifier {mod:#x} pitch {pitch} offset {offset}")
    if not h0:
        print("no handle: GETFB2 gives one only to the master or to root")
        return 1
    try:
        if name not in FORMATS or mod != 0:
            print("not a linear 32-bit RGB buffer; not reading it")
            return 2
        dmabuf = ioctl(fd, PRIME_HANDLE_TO_FD, PRIME, h0, O_CLOEXEC, -1)[2]
        try:
            size = offset + pitch * height
            m = mmap.mmap(dmabuf, size, mmap.MAP_SHARED, mmap.PROT_READ)
            try:
                try:
                    fcntl.ioctl(dmabuf, DMA_BUF_SYNC, struct.pack("Q", 1))
                except OSError:
                    pass
                r, g, b = FORMATS[name]
                step = 4 * scale
                rows = []
                for y in range(0, height, scale):
                    start = offset + y * pitch
                    line = m[start:start + 4 * width]
                    w = len(line[2::step])
                    row = bytearray(3 * w)
                    row[0::3] = line[r::step][:w]
                    row[1::3] = line[g::step][:w]
                    row[2::3] = line[b::step][:w]
                    rows.append(bytes(row))
                try:
                    fcntl.ioctl(dmabuf, DMA_BUF_SYNC, struct.pack("Q", 5))
                except OSError:
                    pass
            finally:
                m.close()
        finally:
            os.close(dmabuf)
        n = png(out, len(rows[0]) // 3, len(rows), rows)
        print(f"-> {out}, {len(rows[0]) // 3}x{len(rows)}, {n} bytes")
        return 0
    finally:
        fcntl.ioctl(fd, GEM_CLOSE, struct.pack("II", h0, 0))


def main(argv):
    out, scale, card = "/tmp/shot.png", 3, "/dev/dri/card0"
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--scale":
            scale = max(1, int(rest.pop(0)))
        elif a == "--card":
            card = rest.pop(0)
        else:
            out = a
    fd = os.open(card, os.O_RDWR | O_CLOEXEC)
    try:
        code = 1
        for crtc_id, fb_id in crtc_fbs(fd):
            if not fb_id:
                print(f"crtc {crtc_id}: no framebuffer")
                continue
            print(f"crtc {crtc_id}: ", end="")
            code = shot(fd, fb_id, out, scale)
            break
        return code
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
