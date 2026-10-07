#!/usr/bin/env python3
"""Unpack the device's own bootloader so its behaviour can be read, not guessed.

    scripts/abl-unpack.py <abl.img> [out.fv]
    scripts/abl-unpack.py <abl.img> --grep PATTERN

ABL is the part of the Qualcomm boot chain that chooses a device tree, and
getting that choice wrong is what red-states this phone. Qualcomm publishes the
sources - QcomModulePkg, in the EDK2 tree - but published sources are not the
same as the binary on the device, and the difference is exactly the kind of
thing that costs a flash cycle to find out. This reads the binary instead.

What it buys, concretely: on 2026-10-06 the published sources said an empty
dtbo could not work and said which strings ABL would log on the way down.
Unpacking slot b's abl and finding "Unable to find the Board Dtb" and "Dtbo hdr
magic mismatch %x, with %x" verbatim turned "the sources probably apply" into
"the sources apply", and finding no mention of qcom,softsku-id at all removed
the one field in the matcher we could not otherwise check. See
docs/05-status.md, "How the bootloader chooses".

Three layers, none of them obvious from the outside
---------------------------------------------------

1. A Qualcomm signed ELF. 32-bit ARM, no section headers, three program
   headers: a header segment, the payload, and a hash/signature table. Only
   the payload matters and it is the one with p_filesz large and p_flags 0x7.
   The whole file looks like noise to `strings` because of what is inside it,
   not because it is encrypted.

2. An EDK2 firmware volume. The payload opens with a 16-byte zero vector, a
   GUID, the length, and then the signature `_FVH`.

3. A GUIDed section holding an LZMA stream. The GUID is
   ee4e5898-3914-4259-9d6e-dc7bd79403cf, EDK2's LzmaCustomDecompress, and the
   data begins at the section header plus its DataOffset. Inside that is a
   FIRMWARE_VOLUME_IMAGE section - type 0x17, with its 24-bit size field
   saturated at 0xffffff so the real size is the 4-byte extended one - and
   then a second firmware volume, which is the one with the code in it.

The decompression ratio looks like a bug and is not. 322 KB of LZMA expands to
201 MiB, because the inner firmware volume declares itself that large and is
almost entirely empty: the last hundred megabytes are 99.996% zero. The
declared size, the extended section size and the FV header's FvLength all
agree, so nothing here is trimmed or second-guessed. It does mean writing the
volume out costs 201 MiB on disk, which is why --grep exists and works in
memory.

Getting an abl image in the first place needs root, which on this device means
recovery: see scripts/device-collect.sh and "What root in recovery gave us" in
docs/05-status.md. It is not in the dump set that scripts/try-kernel.sh
restores from, because nothing here ever writes to the bootloader chain.
"""
import lzma
import re
import struct
import sys

LZMA_GUID = bytes.fromhex("98584eee143959429d6edc7bd79403cf")
FV_SIGNATURE = b"_FVH"
SECTION_GUID_DEFINED = 0x02
SECTION_FIRMWARE_VOLUME_IMAGE = 0x17


def payload(blob):
    """The one program header that holds the firmware volume."""
    if blob[:4] != b"\x7fELF":
        raise ValueError("not an ELF - is this really an abl partition?")
    e_phoff, = struct.unpack_from("<I", blob, 28)
    e_phentsize, e_phnum = struct.unpack_from("<HH", blob, 42)
    best = None
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, _, _, p_filesz, _, p_flags, _ = struct.unpack_from(
            "<8I", blob, off)
        # The payload is the loadable one; the other two are the ELF header
        # copy and the hash table, which carry vendor-specific p_type values.
        if p_type == 1 and p_flags & 0x7 == 0x7:
            if best is None or p_filesz > best[1]:
                best = (p_offset, p_filesz)
    if best is None:
        raise ValueError("no loadable segment in this ELF")
    return blob[best[0]:best[0] + best[1]]


def unpack(blob):
    """Return the decompressed firmware volume from an abl image."""
    seg = payload(blob)
    if FV_SIGNATURE not in seg:
        raise ValueError("no EDK2 firmware volume in the payload")
    # Rather than walk the FFS file list, find the LZMA GUID directly: there is
    # exactly one in an abl, and its section header is the 4 bytes before it.
    g = seg.find(LZMA_GUID)
    if g < 0:
        raise ValueError("no LzmaCustomDecompress section")
    hdr = g - 4
    size = int.from_bytes(seg[hdr:hdr + 3], "little")
    stype = seg[hdr + 3]
    if stype != SECTION_GUID_DEFINED:
        raise ValueError(f"section type {stype:#x}, expected GUID_DEFINED")
    data_offset, _ = struct.unpack_from("<HH", seg, g + 16)
    stream = seg[hdr + data_offset:hdr + size]
    out = lzma.decompress(stream, format=lzma.FORMAT_ALONE)
    # Strip the FIRMWARE_VOLUME_IMAGE section wrapper so what comes back
    # starts at the inner volume's zero vector and _FVH lands where the
    # format says it does.
    if len(out) > 8 and out[3] == SECTION_FIRMWARE_VOLUME_IMAGE:
        out = out[8:] if int.from_bytes(out[:3], "little") == 0xFFFFFF \
            else out[4:]
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    with open(argv[0], "rb") as fh:
        fv = unpack(fh.read())

    if len(argv) >= 3 and argv[1] == "--grep":
        pat = re.compile(argv[2].encode(), re.I)
        found = sorted({m.group(0).decode("latin-1")
                        for m in re.finditer(rb"[ -~]{6,}", fv)
                        if pat.search(m.group(0))})
        for s in found:
            print(s)
        print(f"==> {len(found)} matching string(s) in {len(fv)} bytes",
              file=sys.stderr)
        return 0 if found else 1

    out = argv[1] if len(argv) > 1 else None
    if out:
        with open(out, "wb") as fh:
            fh.write(fv)
        print(f"==> {out}  {len(fv)} bytes")
    else:
        print(f"==> firmware volume is {len(fv)} bytes; "
              f"pass an output path to write it, or --grep PATTERN")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
