#!/usr/bin/env python3
"""Structural verification of patched-vendor_boot.img against the stock image."""
import argparse
import hashlib
import os
import struct
import sys

import lz4.block

PAGE = 4096


def al(x, a=PAGE):
    return (x + a - 1) // a * a


def lz4_decomp(buf):
    out, p = bytearray(), 4
    while p + 4 <= len(buf):
        (bs,) = struct.unpack_from("<I", buf, p)
        p += 4
        if bs == 0:
            break
        out += lz4.block.decompress(buf[p:p + bs], uncompressed_size=8 * 1024 * 1024)
        p += bs
    return bytes(out)


def cpio(d):
    p, names = 0, []
    while d[p:p + 6] == b"070701":
        hdr = d[p:p + 110]
        namesz = int(hdr[94:102], 16)
        fsize = int(hdr[54:62], 16)
        ns = p + 110
        names.append(d[ns:ns + namesz - 1].decode(errors="replace"))
        p = ((ns + namesz + 3) // 4 * 4 + fsize + 3) // 4 * 4
        if names[-1] == "TRAILER!!!":
            break
    return names


def listed(raw, fn):
    p = 0
    while raw[p:p + 6] == b"070701":
        hdr = raw[p:p + 110]
        namesz = int(hdr[94:102], 16)
        fsize = int(hdr[54:62], 16)
        ns = p + 110
        nm = raw[ns:ns + namesz - 1].decode(errors="replace")
        ds = (ns + namesz + 3) // 4 * 4
        if nm.endswith(fn):
            return raw[ds:ds + fsize]
        p = (ds + fsize + 3) // 4 * 4
        if nm == "TRAILER!!!":
            break
    return b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    s = open(os.path.join(a.stock, "vendor_boot.img"), "rb").read()
    n = open(os.path.join(a.out, "patched-vendor_boot.img"), "rb").read()
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        ok = ok and bool(cond)

    print("== size / header ==")
    chk(len(n) == len(s), f"size == stock ({len(n)})")
    chk(n[:8] == b"VNDRBOOT", "VNDRBOOT magic")
    chk(struct.unpack_from("<II", s, 8) == struct.unpack_from("<II", n, 8),
        "header_version/page match")
    chk(n[28:28 + 2048] == s[28:28 + 2048], "cmdline identical")
    chk(n[2080:2112] == s[2080:2112], "name/dtb fields identical")

    print("== ramdisk ==")
    srs = struct.unpack_from("<I", s, 24)[0]
    nrs = struct.unpack_from("<I", n, 24)[0]
    print(f"    stock ramdisk={srs}  patched ramdisk={nrs}")
    sraw = lz4_decomp(s[PAGE:PAGE + srs])
    nraw = lz4_decomp(n[PAGE:PAGE + nrs])
    sn, nn = cpio(sraw), cpio(nraw)
    chk(len(nn) == len(sn) - 1, f"cpio entries {len(sn)} -> {len(nn)}")
    chk("lib/modules/oplus_security_guard.ko" not in nn, "security_guard.ko removed")
    chk("lib/modules/oplus_secure_harden.ko" in nn, "oplus_secure_harden.ko kept")
    chk(len(nraw) == len(sraw), f"uncompressed ramdisk length unchanged ({len(nraw)})")

    print("== module lists ==")
    for f in ("modules.load", "modules.load.recovery"):
        ab, bb = listed(sraw, f), listed(nraw, f)
        chk(b"oplus_security_guard.ko" not in bb, f"{f}: no security_guard")
        print(f"    {f}: {len(ab.splitlines())} -> {len(bb.splitlines())} lines")

    print("== dtb / table / avb ==")
    sd = struct.unpack_from("<I", s, 2100)[0]
    chk(sd == struct.unpack_from("<I", n, 2100)[0], f"dtb_size unchanged ({sd})")
    sdtb, ndtb = al(PAGE + srs), al(PAGE + nrs)
    chk(n[ndtb:ndtb + sd] == s[sdtb:sdtb + sd], "dtb section byte-identical")
    stbl, ntb = al(sdtb + sd), al(ndtb + sd)
    sts = struct.unpack_from("<I", s, 2112)[0]
    chk(n[ntb:ntb + sts][12:] == s[stbl:stbl + sts][12:],
        "ramdisk table (type/name/board_id) unchanged")
    chk(struct.unpack_from("<I", n, ntb)[0] == nrs, "table entry size == new ramdisk size")

    sf, nf = s[-64:], n[-64:]
    chk(nf[:4] == b"AVBf", "footer magic")
    svb, svs = struct.unpack_from(">QQQ", sf, 12)[1:]
    nvb, nvs = struct.unpack_from(">QQQ", nf, 12)[1:]
    chk(n[nvb:nvb + 4] == b"AVB0", "vbmeta AVB0 at footer offset")
    chk(n[nvb:nvb + nvs] == s[svb:svb + svs], "vbmeta byte-identical to stock")
    chk(nvs == svs, f"vbmeta_size {nvs} == stock {svs}")
    chk(al(ntb + sts) == nvb, f"layout consistent (vbmeta@{nvb:#x})")

    print("== sha256 ==")
    print(f"    new  : {hashlib.sha256(n).hexdigest()}")
    print(f"    stock: {hashlib.sha256(s).hexdigest()}")
    print("\nRESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
