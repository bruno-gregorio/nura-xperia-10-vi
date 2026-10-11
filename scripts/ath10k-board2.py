#!/usr/bin/env python3
"""Pack stock WLAN board data into an ath10k board-2.bin, or list one.

    scripts/ath10k-board2.py OUT DIR     pack DIR/bdwlan.<id> into OUT
    scripts/ath10k-board2.py --list FILE list the board names in FILE

Stock keeps one board data file per board ID, bdwlan.<id> with the ID in
hex, and the WLAN firmware picks one itself. ath10k instead fetches the
board data on the host and hands it to the firmware over QMI, looking it up
in board-2.bin by name once the firmware has reported its board ID. Its last
fallback name is "bus=snoc,qmi-board-id=<id>", the ID in lowercase hex with
no leading zeros, so that is the name each file gets here. bdwlan.bin, the
file stock uses when the OTP holds no board ID, becomes board ID ff, which
is what ath10k reports in that case.

The format is ath10k's own (drivers/net/wireless/ath/ath10k/core.c,
ath10k_core_fetch_board_data_api_n): the magic "QCA-ATH10K-BOARD" with its
NUL, padded to four bytes, then one ATH10K_BD_IE_BOARD element per board,
each holding a NAME and a DATA element. Every element is a little-endian
u32 id and u32 length, its payload padded to four bytes. The name is
compared without a NUL.
"""
import os
import re
import struct
import sys

MAGIC = b"QCA-ATH10K-BOARD\0"
IE_BOARD = 0
IE_NAME = 0
IE_DATA = 1


def pad4(b):
    return b + b"\0" * (-len(b) % 4)


def ie(ie_id, payload):
    return struct.pack("<II", ie_id, len(payload)) + pad4(payload)


def pack(out, src):
    boards = []
    for name in sorted(os.listdir(src)):
        m = re.fullmatch(r"bdwlan\.([0-9a-fA-F]+)", name)
        if m:
            bid = "%x" % int(m.group(1), 16)
        elif name == "bdwlan.bin":
            bid = "ff"
        else:
            continue
        with open(os.path.join(src, name), "rb") as f:
            data = f.read()
        boards.append(("bus=snoc,qmi-board-id=" + bid, data, name))
    if not boards:
        sys.exit("no bdwlan files in " + src)
    names = [b[0] for b in boards]
    if len(set(names)) != len(names):
        sys.exit("two files map to the same board ID")
    blob = pad4(MAGIC)
    for bname, data, _ in boards:
        blob += ie(IE_BOARD, ie(IE_NAME, bname.encode()) + ie(IE_DATA, data))
    with open(out + ".new", "wb") as f:
        f.write(blob)
    os.replace(out + ".new", out)
    print("%s: %d boards, %d bytes" % (out, len(boards), len(blob)))


def elements(buf):
    while len(buf) > 8:
        ie_id, ie_len = struct.unpack_from("<II", buf)
        payload = buf[8:8 + ie_len]
        if len(payload) != ie_len:
            sys.exit("truncated element")
        yield ie_id, payload
        buf = buf[8 + ie_len + (-ie_len % 4):]


def list_(path):
    with open(path, "rb") as f:
        buf = f.read()
    if not buf.startswith(MAGIC):
        sys.exit("not a board-2.bin")
    for ie_id, payload in elements(buf[len(pad4(MAGIC)):]):
        if ie_id != IE_BOARD:
            continue
        name, size = None, None
        for sub_id, sub in elements(payload):
            if sub_id == IE_NAME:
                name = sub.decode(errors="replace")
            elif sub_id == IE_DATA:
                size = len(sub)
        print("%s %s" % (name, size))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--list":
        list_(sys.argv[2])
    elif len(sys.argv) == 3:
        pack(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
