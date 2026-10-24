#!/usr/bin/env python3
"""Audit Module.symvers from our build against the stock vendor modules.

CONFIG_MODVERSIONS=y means every vendor .ko imports kernel symbols with a CRC
baked in at *their* build time.  If our kernel exposes a different CRC for any of
those symbols, that module refuses to load -- and the failure is silent (no
dmesg until you look, system boots fine, one piece of hardware just dies).

configs/stock_module_crc.json is the baseline: 1338 symbols extracted from 14
stock .ko files (`__versions` section) out of the factory vendor_boot ramdisk.

usage: python scripts/crc_audit.py <Module.symvers> [stock_module_crc.json]
                                    [--vendor-cpio <vendor_ramdisk.cpio>]
exit:  0 = no CRC drift and every imported symbol has an exporter, 1 = problem
"""
import io
import json
import sys


def _cpio(path):
    d = open(path, "rb").read()
    p, out = 0, []
    while d[p:p + 6] == b"070701":
        hdr = d[p:p + 110]
        namesz = int(hdr[94:102], 16)
        fsize = int(hdr[54:62], 16)
        ns = p + 110
        name = d[ns:ns + namesz - 1].decode(errors="replace")
        ds = (ns + namesz + 3) // 4 * 4
        out.append((name, d[ds:ds + fsize]))
        p = (ds + fsize + 3) // 4 * 4
        if name == "TRAILER!!!":
            break
    return out


def _exported(blob):
    """Symbols a .ko exports = names in its __ksymtab_strings section."""
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return set()
    try:
        elf = ELFFile(io.BytesIO(blob))
    except Exception:
        return set()
    sec = elf.get_section_by_name("__ksymtab_strings")
    if sec is None:
        return set()
    out = set()
    for s in sec.data().split(b"\x00"):
        if s and len(s) < 128:
            try:
                out.add(s.decode())
            except UnicodeDecodeError:
                pass
    return out


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
    args = [a for a in sys.argv[1:]]
    vendor_cpio = None
    if "--vendor-cpio" in args:
        i = args.index("--vendor-cpio")
        vendor_cpio = args[i + 1]
        del args[i:i + 2]
    symvers = args[0]
    baseline = args[1] if len(args) > 1 else "configs/stock_module_crc.json"

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

    # A vendor .ko may import a symbol exported by ANOTHER vendor .ko
    # (cfg80211 -> mac80211, aee_aed -> ..., lcm -> adapter_class ...).  Those are
    # expected to be absent from the kernel's symvers; only a symbol exported by
    # nobody at all is a real problem.
    by_module, truly = [], []
    if missing and vendor_cpio:
        exports = {}
        for name, blob in _cpio(vendor_cpio):
            if name.endswith(".ko"):
                for s in _exported(blob):
                    exports.setdefault(s, name)
        for s in missing:
            (by_module if s in exports else truly).append(s)
        print(f"  of those, exported by another vendor module: {len(by_module)}"
              f"   exported by nobody: {len(truly)}")
    else:
        truly = missing

    if truly:
        print("\n!! symbols imported by vendor modules but exported by nobody:")
        for s in truly[:30]:
            print("   ", s)
        if len(truly) > 30:
            print(f"   ... {len(truly) - 30} more")

    if drift or truly:
        print("\nRESULT: CRC MISMATCH -> config/source pin is wrong, do not flash")
        return 1
    print("\nRESULT: CRC MATCH -> every vendor module import is satisfied"
          " (kernel exports CRC-checked, module-to-module covered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
