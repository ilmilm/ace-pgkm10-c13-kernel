#!/usr/bin/env python3
"""Patch / re-sign / rebuild the PGKM10_13.1.0.9 lk.img.

The lk payload starts at file offset 0x200 inside the first MTK sub-image.  All
offsets below are *payload* offsets, verified by disassembly of the stock image
(see docs/lk.md for the derivation).

  0x057eac  mov w0, #2                 -> mov w0, wzr   boot state -> 0 (green)
  0x057ed4  mov w0, #3                 -> mov w0, wzr   boot state -> 0 (green)
  0x058098  mov w0, #2                 -> mov w0, wzr   boot state -> 0 (green)
  0x0649f8  csel x2, x10, x9, eq       -> mov x2, x10   vbmeta.device_state -> locked

Only the `lk` payload is touched; bl2_ext / aee / lk_main_dtb stay byte-identical.
After patching the container is re-signed with the legacy CERT2 injection and
all four certificate chains are re-verified.

usage: python scripts/patch_lk.py --stock <dir with lk.img> --out <dir>
       [--tools <pwnage24mtk checkout>]
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys

PAYLOAD_OFF = 0x200
PATCHES = [
    (0x57EAC, 0x52800040, 0x2A1F03E0, "boot state -> 0 (green), site A"),
    (0x57ED4, 0x52800060, 0x2A1F03E0, "boot state -> 0 (green), site A"),
    (0x58098, 0x52800040, 0x2A1F03E0, "boot state -> 0 (green), site B"),
    (0x649F8, 0x9A890142, 0xAA0A03E2, "vbmeta.device_state -> locked"),
]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run(*cmd):
    print("  $", " ".join(os.path.basename(str(c)) if i == 1 else str(c)
                          for i, c in enumerate(cmd)))
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        print("    " + line)
    if r.returncode != 0:
        raise SystemExit(f"FAILED ({r.returncode}): {' '.join(str(c) for c in cmd)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True, help="directory containing the stock lk.img")
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--tools", default=os.path.join("tools", "pwnage24mtk-main"))
    a = ap.parse_args()

    src = os.path.join(a.stock, "lk.img")
    work = os.path.join(a.out, "lk_work")
    os.makedirs(work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    py = sys.executable

    print("== split container ==")
    run(py, os.path.join(a.tools, "parse-part-img.py"), src, "--split", "-o", work)

    lk = os.path.join(work, "lk.bin")
    buf = bytearray(open(lk, "rb").read())
    print(f"\n== patch lk.bin ({len(buf)} bytes) ==")
    for off, old, new, desc in PATCHES:
        fo = PAYLOAD_OFF + off
        cur = struct.unpack_from("<I", buf, fo)[0]
        if cur != old:
            raise SystemExit(f"0x{off:x}: expected {old:08x}, found {cur:08x} "
                             f"(wrong lk.img? these offsets are for PGKM10_13.1.0.9)")
        struct.pack_into("<I", buf, fo, new)
        print(f"  0x{off:06x} (file 0x{fo:06x}): {old:08x} -> {new:08x}  {desc}")

    patched = os.path.join(work, "lk_patched.bin")
    open(patched, "wb").write(buf)

    print("\n== re-sign lk (legacy CERT2 injection) ==")
    signed = os.path.join(work, "lk_signed.bin")
    run(py, os.path.join(a.tools, "sign_mtk_cert.py"), "-w", "--legacy",
        patched, "-o", signed)

    print("\n== rebuild container ==")
    rebuilt = os.path.join(a.out, "patched-lk.img")
    run(py, os.path.join(a.tools, "build-part-img.py"), "replace", src,
        "--name", "lk", "--file", signed, "-o", rebuilt)

    # keep the stock file length so fastboot/flash tooling sees the same size
    stock_size = os.path.getsize(src)
    data = open(rebuilt, "rb").read()
    if len(data) < stock_size:
        open(rebuilt, "wb").write(data + b"\x00" * (stock_size - len(data)))
        print(f"  padded {len(data)} -> {stock_size}")

    print("\n== verify all certificate chains ==")
    run(py, os.path.join(a.tools, "verify_mtk_image.py"), rebuilt, "--all")

    print("\n== results ==")
    print(f"  stock   lk.img : {os.path.getsize(src):9d}  {sha(src)}")
    print(f"  patched lk.img : {os.path.getsize(rebuilt):9d}  {sha(rebuilt)}")
    print(f"  -> {rebuilt}")


if __name__ == "__main__":
    main()
