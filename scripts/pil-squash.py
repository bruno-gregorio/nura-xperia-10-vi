#!/usr/bin/env python3
"""Join a split Qualcomm firmware image (.mdt + .bNN) into one .mbn.

    scripts/pil-squash.py out/firmware/modem_a/image/adsp.mdt adsp.mbn

The stock firmware partition stores each remote processor's image split: the
.mdt holds the ELF header, the program headers and the hash segment, and
segment N's bytes are in the file next to it named .bNN. Upstream's firmware
names (qcom/<soc>/<vendor>/<board>/adsp.mbn) are the image joined back
together, every segment at its own p_offset, which is what linux-msm's
pil-squasher does. This is that in Python, so it runs on the host with
nothing installed.

Where each segment comes from follows drivers/soc/qcom/mdt_loader.c. Segment
0, the headers, is the first p_filesz bytes of the .mdt. Any other segment is
its .bNN if there is one. Without one, the hash segment is taken from the
.mdt as mainline reads it: packed right after the headers when the .mdt is
exactly those two, or else at its own p_offset. A segment with p_filesz 0 has
nothing to place. Any other segment missing is an error, because a hole in a
signed image fails authentication, and that failure is reported much later
and says less.
"""

import os
import struct
import sys


QCOM_MDT_TYPE_MASK = 7 << 24
QCOM_MDT_TYPE_HASH = 2 << 24


def phdrs(mdt):
    """[(type, offset, filesz, flags)] for each program header."""
    if mdt[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    cls = mdt[4]
    if cls == 1:
        phoff, = struct.unpack_from("<I", mdt, 0x1c)
        phentsize, phnum = struct.unpack_from("<HH", mdt, 0x2a)
        fmt = "<IIIIIIII"  # type offset vaddr paddr filesz memsz flags align
        pick = (0, 1, 4, 6)
    elif cls == 2:
        phoff, = struct.unpack_from("<Q", mdt, 0x20)
        phentsize, phnum = struct.unpack_from("<HH", mdt, 0x36)
        fmt = "<IIQQQQQQ"  # type flags offset vaddr paddr filesz memsz align
        pick = (0, 2, 5, 1)
    else:
        raise ValueError("unknown ELF class %d" % cls)
    out = []
    for i in range(phnum):
        f = struct.unpack_from(fmt, mdt, phoff + i * phentsize)
        out.append(tuple(f[k] for k in pick))
    return out


def squash(mdt_path, mbn_path):
    with open(mdt_path, "rb") as f:
        mdt = f.read()
    base = mdt_path[:-4] if mdt_path.endswith(".mdt") else mdt_path
    ph = phdrs(mdt)
    if len(ph) < 2 or ph[0][0] == 1:  # PT_LOAD
        raise ValueError("segment 0 is not the headers")
    hash_seg = next((i for i, p in enumerate(ph) if i and
                     (p[3] & QCOM_MDT_TYPE_MASK) == QCOM_MDT_TYPE_HASH), None)
    ehdr_size = ph[0][2]
    image = bytearray(mdt[:ehdr_size])
    for i, (_, offset, filesz, _) in enumerate(ph):
        if not filesz or i == 0:
            continue
        seg = "%s.b%02d" % (base, i)
        if os.path.exists(seg):
            with open(seg, "rb") as f:
                data = f.read()
        elif i == hash_seg and ehdr_size + filesz == len(mdt):
            data = mdt[ehdr_size:]
        elif offset + filesz <= len(mdt):
            data = mdt[offset:offset + filesz]
        else:
            raise FileNotFoundError("segment %d: no %s" % (i, seg))
        if len(data) != filesz:
            raise ValueError("segment %d: %s is %d bytes, p_filesz says %d"
                             % (i, seg, len(data), filesz))
        end = offset + filesz
        if len(image) < end:
            image.extend(b"\0" * (end - len(image)))
        image[offset:end] = data
    with open(mbn_path + ".part", "wb") as f:
        f.write(image)
    os.replace(mbn_path + ".part", mbn_path)
    return len(image)


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    size = squash(sys.argv[1], sys.argv[2])
    print("%s -> %s, %d bytes" % (sys.argv[1], sys.argv[2], size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
