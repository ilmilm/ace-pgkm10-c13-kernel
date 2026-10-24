#!/usr/bin/env python3
"""Audit Module.symvers from our build against the stock vendor modules.

CONFIG_MODVERSIONS=y means every vendor .ko imports kernel symbols with a CRC
baked in at *their* build time.  If our kernel exposes a different CRC for any of
those symbols, that module refuses to load -- and the failure is silent (no
dmesg until you look, system boots fine, one piece of hardware just dies).

configs/stock_module_crc.json is the baseline: 1338 symbols extracted from 14
stock .ko files (`__versions` section) out of the factory vendor_boot ramdisk.

usage: python scripts/crc_audit.py <Module.symvers> [stock_module_crc.json]
exit:  0 = all overlapping symbols match, 1 = drift found
"""
import json
import sys


def parse_symvers(path):
    out = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            crc, sym, mod, export = parts[0], parts[1], parts[2], parts[3]
            if not crc.startswith("0x"):
                continue
            if export == "EXPORT_SYMBOL_GPL" or export.startswith("EXPORT_SYMBOL"):
                out[sym] = int(crc, 16)
    return out


def main():
    symvers = sys.argv[1]
    baseline = sys.argv[2] if len(sys.argv) > 2 else "configs/stock_module_crc.json"

    ours = parse_symvers(symvers)
    base = json.load(open(baseline))["crc"]
    print(f"Module.symvers: {len(ours)} exported symbols")
    print(f"stock baseline: {len(base)} symbols (from factory vendor modules)")

    common = sorted(set(ours) & set(base))
    drift = [(s, base[s], ours[s]) for s in common if base[s] != ours[s]]
    missing = sorted(set(base) - set(ours))

    print(f"overlap: {len(common)}   drift: {len(drift)}   "
          f"missing-from-ours: {len(missing)}")

    if drift:
        print("\n!! CRC DRIFT (vendor module would be rejected):")
        for s, b, o in drift[:40]:
            print(f"   {s:44s} stock={b:08x} ours={o:08x}")
        if len(drift) > 40:
            print(f"   ... {len(drift) - 40} more")
    if missing:
        print("\n!! symbols the stock modules import but our kernel does not export:")
        for s in missing[:20]:
            print("   ", s)
        if len(missing) > 20:
            print(f"   ... {len(missing) - 20} more")

    if drift or missing:
        print("\nRESULT: CRC MISMATCH -> config/source pin is wrong, do not flash")
        return 1
    print("\nRESULT: CRC MATCH -> vendor modules will load")
    return 0


if __name__ == "__main__":
    sys.exit(main())
