#!/usr/bin/env python3
"""Pull apart an AVB vbmeta image and check it against the partitions it covers.

Written to answer one question offline, without touching the phone: when the
bootloader red-stated this device, was it rejecting our boot image, or the
vbmeta we had patched to let it through?

Everything here is parsed from the AVB on-disk format directly (external/avb,
libavb/avb_vbmeta_image.h and libavb/avb_descriptor.h). All AVB integers are
big-endian and the structs are packed, not naturally aligned.

  scripts/avb-inspect.py <vbmeta.img> [-C <dir-with-partition-images>]
"""
import hashlib
import struct
import sys
import os

ALGORITHMS = {
    0: ("NONE", None, 0),
    1: ("SHA256_RSA2048", "sha256", 256),
    2: ("SHA256_RSA4096", "sha256", 512),
    3: ("SHA256_RSA8192", "sha256", 1024),
    4: ("SHA512_RSA2048", "sha512", 256),
    5: ("SHA512_RSA4096", "sha512", 512),
    6: ("SHA512_RSA8192", "sha512", 1024),
}
TAGS = {0: "property", 1: "hashtree", 2: "hash", 3: "kernel_cmdline",
        4: "chain_partition"}

FLAG_HASHTREE_DISABLED = 1 << 0
FLAG_VERIFICATION_DISABLED = 1 << 1


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def u64(b, o):
    return struct.unpack_from(">Q", b, o)[0]


class VBMeta:
    """The 256-byte AvbVBMetaImageHeader, read field by field at its offset.

    Read by offset rather than one unpack string because the struct is packed
    and the uint64s are not aligned, which makes a single format easy to
    miscount and hard to check.
    """

    def __init__(self, data):
        if data[:4] != b"AVB0":
            raise ValueError("not a vbmeta image: magic is %r" % data[:4])
        self.data = data
        self.ver = (u32(data, 4), u32(data, 8))
        self.auth_size = u64(data, 12)
        self.aux_size = u64(data, 20)
        self.algorithm = u32(data, 28)
        self.hash_offset = u64(data, 32)
        self.hash_size = u64(data, 40)
        self.sig_offset = u64(data, 48)
        self.sig_size = u64(data, 56)
        self.pubkey_offset = u64(data, 64)
        self.pubkey_size = u64(data, 72)
        self.pkmd_offset = u64(data, 80)
        self.pkmd_size = u64(data, 88)
        self.desc_offset = u64(data, 96)
        self.desc_size = u64(data, 104)
        self.rollback_index = u64(data, 112)
        self.flags = u32(data, 120)
        self.rollback_index_location = u32(data, 124)
        self.release_string = data[128:176].rstrip(b"\0").decode("ascii", "replace")
        self.header_block = data[:256]
        self.auth_block = data[256:256 + self.auth_size]
        self.aux_block = data[256 + self.auth_size:
                              256 + self.auth_size + self.aux_size]

    @property
    def algorithm_name(self):
        return ALGORITHMS.get(self.algorithm, ("UNKNOWN", None, 0))[0]

    def descriptors(self):
        """Walk the descriptor list in the auxiliary block."""
        blob = self.aux_block[self.desc_offset:self.desc_offset + self.desc_size]
        out, off = [], 0
        while off + 16 <= len(blob):
            tag = u64(blob, off)
            nbf = u64(blob, off + 16 - 8)
            body = blob[off:off + 16 + nbf]
            out.append((tag, body))
            off += 16 + nbf
        return out

    def verify_self(self):
        """Recompute the hash libavb checks, and the RSA signature over it.

        libavb hashes the raw 256-byte header followed by the whole auxiliary
        block. The header includes 'flags' at offset 120, so patching the
        disable flags into a signed vbmeta necessarily breaks this hash - that
        is the point worth proving here rather than assuming.
        """
        name, hashfn, siglen = ALGORITHMS.get(self.algorithm,
                                              ("UNKNOWN", None, 0))
        if hashfn is None:
            return None, None
        h = hashlib.new(hashfn)
        h.update(self.header_block)
        h.update(self.aux_block)
        computed = h.digest()
        stored = self.auth_block[self.hash_offset:
                                 self.hash_offset + self.hash_size]
        hash_ok = computed == stored

        sig_ok = None
        pk = self.aux_block[self.pubkey_offset:
                            self.pubkey_offset + self.pubkey_size]
        if len(pk) > 8:
            # AvbRSAPublicKeyHeader: key_num_bits, n0inv, then n and rr, both
            # key_num_bits wide and big-endian.
            nbits = u32(pk, 0)
            nbytes = nbits // 8
            n = int.from_bytes(pk[8:8 + nbytes], "big")
            sig = self.auth_block[self.sig_offset:
                                  self.sig_offset + self.sig_size]
            if n and len(sig) == nbytes:
                # Textbook RSA verify, e=65537 as AVB always uses, then check
                # the PKCS#1 v1.5 padding by hand: no crypto dependency needed
                # to tell a good signature from a broken one.
                m = pow(int.from_bytes(sig, "big"), 65537, n)
                em = m.to_bytes(nbytes, "big")
                sig_ok = em.startswith(b"\x00\x01") and em.endswith(computed)
        return hash_ok, sig_ok


def hash_descriptor(body):
    image_size = u64(body, 16)
    algo = body[24:56].rstrip(b"\0").decode("ascii", "replace")
    name_len = u32(body, 56)
    salt_len = u32(body, 60)
    digest_len = u32(body, 64)
    flags = u32(body, 68)
    o = 132
    name = body[o:o + name_len].decode("ascii", "replace"); o += name_len
    salt = body[o:o + salt_len]; o += salt_len
    digest = body[o:o + digest_len]
    return dict(partition=name, image_size=image_size, algorithm=algo,
                salt=salt, digest=digest, flags=flags)


def hashtree_descriptor(body):
    image_size = u64(body, 20)
    algo = body[72:104].rstrip(b"\0").decode("ascii", "replace")
    name_len = u32(body, 104)
    salt_len = u32(body, 108)
    digest_len = u32(body, 112)
    o = 180
    name = body[o:o + name_len].decode("ascii", "replace"); o += name_len
    salt = body[o:o + salt_len]; o += salt_len
    digest = body[o:o + digest_len]
    return dict(partition=name, image_size=image_size, algorithm=algo,
                salt=salt, root_digest=digest)


def chain_descriptor(body):
    ril = u32(body, 16)
    name_len = u32(body, 20)
    pk_len = u32(body, 24)
    o = 92
    name = body[o:o + name_len].decode("ascii", "replace"); o += name_len
    pk = body[o:o + pk_len]
    return dict(partition=name, rollback_index_location=ril,
                public_key_sha1=hashlib.sha1(pk).hexdigest() if pk else "")


def main():
    args = sys.argv[1:]
    imgdir = None
    if "-C" in args:
        i = args.index("-C")
        imgdir = args[i + 1]
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    path = args[0]
    v = VBMeta(open(path, "rb").read())

    print("%s  (%d bytes)" % (path, os.path.getsize(path)))
    print("  libavb required      %d.%d" % v.ver)
    print("  release_string       %s" % v.release_string)
    print("  algorithm            %d  %s" % (v.algorithm, v.algorithm_name))
    print("  rollback_index       %d  (location %d)"
          % (v.rollback_index, v.rollback_index_location))
    names = []
    if v.flags & FLAG_HASHTREE_DISABLED:
        names.append("HASHTREE_DISABLED")
    if v.flags & FLAG_VERIFICATION_DISABLED:
        names.append("VERIFICATION_DISABLED")
    print("  flags                0x%08x%s"
          % (v.flags, ("  " + " | ".join(names)) if names else "  (none set)"))

    hash_ok, sig_ok = v.verify_self()
    if hash_ok is None:
        print("  self-check           unsigned, nothing to verify")
    else:
        print("  own hash             %s" % ("MATCHES" if hash_ok else "MISMATCH"))
        print("  own RSA signature    %s"
              % ("VALID" if sig_ok else "INVALID" if sig_ok is not None
                 else "could not check"))
        if not hash_ok:
            print("                       -> this vbmeta has been modified since"
                  " it was signed")

    print("  descriptors:")
    for tag, body in v.descriptors():
        kind = TAGS.get(tag, "tag %d" % tag)
        if tag == 2:
            d = hash_descriptor(body)
            print("    hash            %-14s %10d bytes  %s  digest %s"
                  % (d["partition"], d["image_size"], d["algorithm"],
                     d["digest"].hex()[:32]))
            if imgdir:
                check_hash(imgdir, d)
        elif tag == 1:
            d = hashtree_descriptor(body)
            print("    hashtree        %-14s %10d bytes  %s  root %s"
                  % (d["partition"], d["image_size"], d["algorithm"],
                     d["root_digest"].hex()[:32]))
        elif tag == 4:
            d = chain_descriptor(body)
            print("    chain           %-14s rollback location %d  key sha1 %s"
                  % (d["partition"], d["rollback_index_location"],
                     d["public_key_sha1"][:16]))
        elif tag == 3:
            n = u32(body, 20)
            print("    kernel_cmdline  %s" % body[24:24 + n].decode("ascii", "replace"))
        elif tag == 0:
            kl = u64(body, 16); vl = u64(body, 24)
            print("    property        %s = %s"
                  % (body[32:32 + kl].decode("ascii", "replace"),
                     body[32 + kl + 1:32 + kl + 1 + vl].decode("ascii", "replace")))
        else:
            print("    %s" % kind)


def check_hash(imgdir, d):
    """Hash a candidate partition image the way AVB does and compare."""
    algo = d["algorithm"].lower()
    for cand in (d["partition"] + ".img", d["partition"] + "_a.img",
                 d["partition"] + "_b.img"):
        p = os.path.join(imgdir, cand)
        if not os.path.exists(p):
            continue
        try:
            h = hashlib.new(algo)
        except ValueError:
            print("                      cannot hash with %r" % algo)
            return
        h.update(d["salt"])
        with open(p, "rb") as f:
            left = d["image_size"]
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
        ok = h.digest() == d["digest"]
        print("                      %-22s %s" % (cand, "MATCHES" if ok else "does NOT match"))


main()
