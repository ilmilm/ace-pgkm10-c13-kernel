#!/usr/bin/env python3
"""Patch vendor_boot.img: drop oplus_security_guard.ko and rebuild the image.

ophy: `oplus_security_guard.ko` hooks execve, reads verified_bootstate and
do_exit()s anything that looks like an escalation.  As long as it loads, ksud
cannot be installed.  It lives in the vendor ramdisk, so the fix is to delete
the module at the source -- no root needed.

Layout of a vendor_boot v4 image (page size 4096):

    header | vendor_ramdisk(lz4 legacy) | dtb | ramdisk_table | bootconfig | pad
           | vbmeta (FACTORY blob, carried over verbatim) | AVB footer (last 64 B)

usage: python scripts/patch_vendor_boot.py --stock <dir with vendor_boot.img>
                                           --out <dir>
"""
import argparse
import hashlib
import os
import struct
import sys

import lz4.block

PAGE = 4096
DROP = b"oplus_security_guard.ko"


def al(x, a=PAGE):
    return (x + a - 1) // a * a


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def lz4_legacy_decompress(buf):
    if buf[:4] != b"\x02\x21\x4c\x18":
        raise SystemExit("vendor ramdisk is not lz4-legacy; aborting")
    out = bytearray()
    p = 4
    while p + 4 <= len(buf):
        (bs,) = struct.unpack_from("<I", buf, p)
        p += 4
        if bs == 0:
            break
        out += lz4.block.decompress(buf[p:p + bs], uncompressed_size=8 * 1024 * 1024)
        p += bs
    return bytes(out)


def lz4_legacy_compress(data, block=8 * 1024 * 1024):
    out = bytearray(b"\x02\x21\x4c\x18")
    for i in range(0, len(data), block):
        c = lz4.block.compress(data[i:i + block], mode="high_compression",
                               store_size=False)
        out += struct.pack("<I", len(c)) + c
    return bytes(out)


def cpio_parse(d):
    p, entries = 0, []
    while d[p:p + 6] == b"070701":
        hdr = d[p:p + 110]
        namesz = int(hdr[94:102], 16)
        fsize = int(hdr[54:62], 16)
        ns = p + 110
        name = d[ns:ns + namesz - 1]
        ds = (ns + namesz + 3) // 4 * 4
        entries.append({"hdr": hdr, "name": name, "data": d[ds:ds + fsize]})
        p = (ds + fsize + 3) // 4 * 4
        if name == b"TRAILER!!!":
            break
    return entries


def cpio_build(entries):
    out = bytearray()
    for e in entries:
        hdr = bytearray(e["hdr"])
        name = e["name"] + b"\x00"
        data = e["data"]
        hdr[94:102] = b"%08x" % len(name)
        hdr[54:62] = b"%08x" % len(data)
        out += bytes(hdr) + name
        out += b"\x00" * ((-len(out)) % 4)
        out += data
        out += b"\x00" * ((-len(out)) % 4)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    src = os.path.join(a.stock, "vendor_boot.img")
    os.makedirs(a.out, exist_ok=True)
    dst = os.path.join(a.out, "patched-vendor_boot.img")

    stock = open(src, "rb").read()
    if stock[:8] != b"VNDRBOOT":
        raise SystemExit("not a vendor_boot image")
    hdr_ver, page = struct.unpack_from("<II", stock, 8)
    vrs = struct.unpack_from("<I", stock, 24)[0]
    dtb_size = struct.unpack_from("<I", stock, 2100)[0]
    tbl_size, tbl_num, tbl_esz = struct.unpack_from("<III", stock, 2112)
    bc_size = struct.unpack_from("<I", stock, 2124)[0]
    print(f"stock: size={len(stock)} hdr_ver={hdr_ver} page={page} ramdisk={vrs} "
          f"dtb={dtb_size} table={tbl_size}/{tbl_num}x{tbl_esz} bootconfig={bc_size}")

    vr_off = page
    dtb_off = al(vr_off + vrs)
    tbl_off = al(dtb_off + dtb_size)
    bc_off = al(tbl_off + tbl_size)
    print(f"  ramdisk@{vr_off:#x} dtb@{dtb_off:#x} table@{tbl_off:#x} "
          f"bootconfig@{bc_off:#x}")

    foot = stock[-64:]
    if foot[:4] != b"AVBf":
        raise SystemExit("no AVB footer")
    orig, vb_off, vb_size = struct.unpack_from(">QQQ", foot, 12)
    vb = stock[vb_off:vb_off + vb_size]
    if vb[:4] != b"AVB0":
        raise SystemExit("vbmeta blob not found")
    print(f"  avb: vbmeta@{vb_off:#x} size={vb_size}")

    raw = lz4_legacy_decompress(stock[vr_off:vr_off + vrs])
    print(f"\nramdisk: {vrs} -> {len(raw)} bytes")
    entries = cpio_parse(raw)
    print(f"  cpio entries: {len(entries)}")

    keep, dropped = [], []
    for e in entries:
        if e["name"].endswith(DROP):
            dropped.append(e["name"].decode())
        else:
            keep.append(e)
    if dropped != ["lib/modules/oplus_security_guard.ko"]:
        raise SystemExit(f"unexpected drop list: {dropped}")

    for e in keep:
        nm = e["name"]
        if nm.endswith((b"modules.load", b"modules.load.recovery", b"modules.dep",
                        b"modules.alias", b"modules.softdep")):
            before = len(e["data"].splitlines())
            e["data"] = b"".join(l for l in e["data"].splitlines(keepends=True)
                                 if DROP not in l)
            after = len(e["data"].splitlines())
            if before != after:
                print(f"  {nm.decode()}: {before} -> {after} lines")

    new_raw = cpio_build(keep)
    if len(new_raw) < len(raw):
        new_raw += b"\x00" * (len(raw) - len(new_raw))
    new_vr = lz4_legacy_compress(new_raw)
    print(f"  dropped {dropped[0]}  entries {len(entries)} -> {len(keep)}")
    print(f"  recompressed ramdisk: {len(new_vr)} bytes (was {vrs})")

    hdr = bytearray(stock[:page])
    struct.pack_into("<I", hdr, 24, len(new_vr))

    table = bytearray(stock[tbl_off:tbl_off + tbl_size])
    if tbl_num >= 1 and tbl_esz >= 24:
        # vendor_ramdisk_table_entry_v4: size, offset, type, name[32], board_id
        struct.pack_into("<I", table, 0, len(new_vr))
        struct.pack_into("<I", table, 4, 0)

    body = bytearray()
    body += bytes(hdr)
    body += b"\x00" * (vr_off - len(body))
    body += new_vr
    body += b"\x00" * (al(len(body)) - len(body))
    body += stock[dtb_off:dtb_off + dtb_size]
    body += b"\x00" * (al(len(body)) - len(body))
    body += bytes(table)
    body += b"\x00" * (al(len(body)) - len(body))
    body += stock[bc_off:bc_off + bc_size]
    body += b"\x00" * (al(len(body)) - len(body))

    new_vb_off = al(len(body))
    body += b"\x00" * (new_vb_off - len(body))
    body += vb

    footer = bytearray(foot)
    struct.pack_into(">QQQ", footer, 12, new_vb_off, new_vb_off, vb_size)
    total = max(len(stock), al(len(body) + 64))
    body += b"\x00" * (total - 64 - len(body))
    body += bytes(footer)

    open(dst, "wb").write(body)
    print(f"\nwrote {dst} ({len(body)} bytes)")
    print(f"  new vbmeta@{new_vb_off:#x}  footer@0x{len(body) - 64:x}")
    print(f"  stock   sha256 {sha(src)}")
    print(f"  patched sha256 {sha(dst)}")


if __name__ == "__main__":
    main()
