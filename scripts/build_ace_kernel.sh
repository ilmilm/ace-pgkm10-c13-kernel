#!/usr/bin/env bash
# =============================================================================
# OnePlus Ace (PGKM10 / OP5565 / MT6895) builtin KernelSU + SuSFS
#
# Target : ColorOS 13 / PGKM10_13.1.0.9 (CN01), kernel
#          5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
# Source : OnePlusOSS mt6895, PINNED to the PGKM10_13.1.0.9 commits
#
# The stock config is NOT guessed: it is extracted verbatim from the gzip'd
# Image inside the factory boot.img (IKCFG_ST/IKCFG_ED).  LTO_CLANG_FULL /
# CFI_CLANG / CFI_CLANG_SHADOW / SHADOW_CALL_STACK / KASAN_HW_TAGS /
# MODVERSIONS / ARM64_4K_PAGES are all =y in it; if any of them silently
# disappears during olddefconfig every vendor module CRC changes.
#
# usage: bash build_ace_kernel.sh <OP dir>
#   env TC = path to clang-r416183b
# =============================================================================
set -euo pipefail

OP=${1:?usage: build_ace_kernel.sh <OP dir>}
K=$OP/kernel
M=$OP/modules
S=$OP/susfs510
SU=$OP/sukisu
O=$OP/kout
HERE=$(cd "$(dirname "$0")/.." && pwd)
BRANCH=${BRANCH:-mt6895_t_13.1.0_oneplus_ace}
TC=${TC:-$OP/toolchain/clang}

log() { printf '\n=== %s ===\n' "$*"; }

export PATH=$TC/bin:$PATH
export ARCH=arm64 LLVM=1 LLVM_IAS=1
export CROSS_COMPILE=aarch64-linux-gnu-
export CLANG_TRIPLE=aarch64-linux-gnu-

for t in clang ld.lld llvm-nm llvm-ar llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
  command -v "$t" >/dev/null || { echo "FATAL: $t not in PATH" >&2; exit 1; }
done
log "toolchain"; clang --version | head -2

# ------------------------------------------------------------------- sources
# KSU and susfs must be from the same generation: the susfs kernel patch adds
# call sites the KSU tree has to provide (and vice versa).  A mismatch either
# fails at vmlink (undefined symbol) or builds fine but the inline hook never
# fires, so `su` does nothing.  Bump both together, never one at a time.
#
#   KSU    builtin, synced with upstream KernelSU main 2026-10-21
#   susfs  gki-android12-5.10, KernelSU sync 2026-10-19
#   KSU_VERSION 40994 (shown as 40994-6); manager v4.2.1-r1 (41049-6) shares UAPI 6
SUSFS_SHA=f43926dc94b8ffbf9b74321313536600f69367b1
KSU_SHA=ce75122bec7423e0f1fa06e3e9a174085c5231ab

mkdir -p "$OP"
log "sources"
# ===========================================================================
# PIN THE EXACT FIRMWARE.  Target is PGKM10_13.1.0.9(CN01), kernel
# 5.10.149-android12-9-00010-gb3f24990ab22-ab9978632.
#
# The upstream repos' branches move forward with new firmware; a branch head is
# NOT guaranteed to be this build.  Building a non-matching tree against this
# device's 5.10.149 vendor modules changes exported symbol CRCs; modules whose
# CRCs moved then refuse to load.  The system still boots and KSU still works,
# so it looks fine until something is silently dead.
# ===========================================================================
KERNEL_SHA=b2ed0599ada1ba8bd4464eb687500aa905cf8268   # PGKM10_13.1.0.9 (5.10.149)
VENDOR_SHA=5f210489762653c23bc6573e72e10fc4b146d094   # PGKM10_13.1.0.9

if [ ! -d "$K/.git" ]; then
  git clone -b "$BRANCH" --depth 1 \
    https://github.com/OnePlusOSS/android_kernel_5.10_oneplus_mt6895 "$K"
fi
git -C "$K" fetch -q --depth 1 origin "$KERNEL_SHA" 2>/dev/null || \
  { echo "shallow fetch failed, doing full fetch"; git -C "$K" fetch -q origin; }
git -C "$K" checkout -q "$KERNEL_SHA"
echo "kernel: $(git -C "$K" rev-parse --short HEAD)  $(git -C "$K" log -1 --format=%s)"

if [ ! -d "$M/.git" ]; then
  git clone -b "$BRANCH" --depth 1 \
    https://github.com/OnePlusOSS/android_vendor_mediatek_kernel_modules_mt6895 "$M"
fi
git -C "$M" fetch -q --depth 1 origin "$VENDOR_SHA" 2>/dev/null || \
  { echo "shallow fetch failed, doing full fetch"; git -C "$M" fetch -q origin; }
git -C "$M" checkout -q "$VENDOR_SHA"
echo "vendor: $(git -C "$M" rev-parse --short HEAD)  $(git -C "$M" log -1 --format=%s)"

# --- guard: refuse to build if the tree is not exactly the C13 source -------
for kv in "VERSION = 5" "PATCHLEVEL = 10" "SUBLEVEL = 149"; do
  grep -qx "$kv" "$K/Makefile" || {
    echo "FATAL: kernel Makefile is not 5.10.149 (missing '$kv')" >&2
    echo "       current: $(grep -E '^(VERSION|PATCHLEVEL|SUBLEVEL) =' "$K/Makefile" | tr '\n' ' ')" >&2
    exit 1; }
done
git -C "$K" log -1 --format=%s | grep -q 'PGKM10_13\.1\.0\.9' || {
  echo "FATAL: kernel source commit is not PGKM10_13.1.0.9" >&2; exit 1; }
git -C "$M" log -1 --format=%s | grep -q 'PGKM10_13\.1\.0\.9' || {
  echo "FATAL: vendor-modules commit is not PGKM10_13.1.0.9" >&2; exit 1; }
echo "source pin verified: kernel+vendor == PGKM10_13.1.0.9"

if [ ! -d "$S/.git" ]; then
  git clone https://github.com/ShirkNeko/susfs4ksu "$S"
fi
git -C "$S" fetch -q --depth 1 origin "$SUSFS_SHA" || true
git -C "$S" checkout -q "$SUSFS_SHA"
echo "susfs: $(git -C "$S" rev-parse --short HEAD)  $(git -C "$S" log -1 --format=%s)"
if [ ! -d "$SU/.git" ]; then
  git clone https://github.com/SukiSU-Ultra/SukiSU-Ultra "$SU"
fi
git -C "$SU" fetch -q --depth 1 origin "$KSU_SHA" || true
git -C "$SU" checkout -q "$KSU_SHA"
echo "ksu  : $(git -C "$SU" rev-parse --short HEAD)  $(git -C "$SU" log -1 --format=%s)"


# -------------------------------------------------------------- integration
cd "$K"
rm -rf "$OP/vendor"; mkdir -p "$OP/vendor"
[ -d "$M/vendor" ] && cp -a "$M/vendor/." "$OP/vendor/"

if [ -d "$M/vendor/oplus/kernel/cpu" ]; then
  rm -rf kernel/oplus_cpu
  cp -a "$M/vendor/oplus/kernel/cpu" kernel/oplus_cpu
fi

log "susfs files"
cp "$S/kernel_patches/fs/susfs.c"                 fs/susfs.c
cp "$S/kernel_patches/include/linux/susfs.h"      include/linux/susfs.h
cp "$S/kernel_patches/include/linux/susfs_def.h"  include/linux/susfs_def.h

log "susfs patch"
# No --forward: this tree is a fresh clone, so a mis-applied hunk MUST produce a
# .rej instead of being silently skipped.
patch -p1 --no-backup-if-mismatch \
  < "$S/kernel_patches/50_add_susfs_in_gki-android12-5.10.patch" || true
REJ=$(find . -name '*.rej' | wc -l)
echo "rejects: $REJ"
[ "$REJ" -eq 0 ] || { echo "FATAL: susfs patch rejected, fix before building" >&2; exit 1; }

grep -q 'my_setprocattr(const char' security/selinux/hooks.c || {
  echo "FATAL: susfs patch did not define my_setprocattr() in security/selinux/hooks.c" >&2
  exit 1; }
echo "susfs patch self-consistency: OK"

grep -q 'VMA_PAD_START' include/linux/susfs_def.h || cat >> include/linux/susfs_def.h <<'EOF'

#ifndef VMA_PAD_START
#define VMA_PAD_START(vma) ((vma)->vm_start)
#endif
EOF

log "KernelSU builtin"
rm -rf KernelSU; mkdir -p KernelSU; cp -a "$SU/kernel/." KernelSU/; rm -rf KernelSU/.git
rm -f drivers/kernelsu; ln -sf ../KernelSU drivers/kernelsu
grep -q 'obj-$(CONFIG_KSU)' drivers/Makefile || \
  printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> drivers/Makefile
grep -q 'drivers/kernelsu/Kconfig' drivers/Kconfig || \
  sed -i '/^endmenu/i source "drivers/kernelsu/Kconfig"' drivers/Kconfig

# ---------------------------------------------------------------------------
# SukiSU `builtin` does NOT use kprobes/tracepoints: the kernel source must call
# its hook entry points itself.  Without them supercalls still answer (manager
# shows "working" + a version) but execve is never intercepted -> no root.
log "manual hooks"
python3 "$HERE/scripts/add_manual_hooks.py" "$K"
for spec in "fs/exec.c:ksu_handle_execveat" "fs/open.c:ksu_handle_faccessat" \
            "fs/stat.c:ksu_handle_stat" "kernel/reboot.c:ksu_handle_sys_reboot"; do
  f=${spec%%:*}; sym=${spec#*:}
  grep -q "$sym" "$f" || { echo "FATAL: $sym missing from $f" >&2; exit 1; }
done
echo "hook call sites verified: 4/4"

MF=KernelSU/Makefile
sed -i 's|^\$(shell cd \$(KSU_SRC).*unshallow.*|# offline|' "$MF" 2>/dev/null || true
sed -i 's|^CURL_BIN.*|CURL_BIN := true|' "$MF" 2>/dev/null || true
sed -i 's|^KSU_GITHUB_VER.*|KSU_GITHUB_VER := |' "$MF" 2>/dev/null || true
sed -i 's|^GITHUB_COMMITS.*|GITHUB_COMMITS := |' "$MF" 2>/dev/null || true

# ------------------------------------------------------------------- config
# stock_defconfig == the factory .config lifted out of the stock boot.img
log "config"
cp "$HERE/configs/stock_defconfig" arch/arm64/configs/ace_defconfig
mkdir -p "$O"
make -C "$K" O="$O" ace_defconfig
cat "$HERE/configs/ksu_susfs.config" >> "$O/.config"
make -C "$K" O="$O" olddefconfig

# kbuild takes the localversion suffix from scripts/setlocalversion, NOT from
# CONFIG_LOCALVERSION, so the script must emit it verbatim.
# Factory UTS of the stock boot.img:
#   5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
sed -i 's/^SUBLEVEL = .*/SUBLEVEL = 149/' Makefile
printf '#!/bin/sh\necho "-android12-9-00010-gb3f24990ab22-ab9978632"\n' > scripts/setlocalversion
chmod +x scripts/setlocalversion
cat scripts/setlocalversion
grep -E '^(VERSION|PATCHLEVEL|SUBLEVEL) ' Makefile
make -C "$K" O="$O" olddefconfig
rm -f "$O/include/config/kernel.release" "$O/include/generated/utsrelease.h"
KR=$(make -s -C "$K" O="$O" kernelrelease)
echo "kernelrelease: $KR"
[ "$KR" = "5.10.149-android12-9-00010-gb3f24990ab22-ab9978632" ] || {
  echo "FATAL: kernelrelease is '$KR', expected factory string" >&2; exit 1; }

# /proc/config.gz must show the factory config, not ours
cp "$HERE/configs/stock_defconfig" arch/arm64/configs/stock_defconfig
if grep -q '^\$(obj)/config_data: \$(KCONFIG_CONFIG) FORCE$' kernel/Makefile; then
  sed -i 's|^\$(obj)/config_data: \$(KCONFIG_CONFIG) FORCE$|$(obj)/config_data: arch/arm64/configs/stock_defconfig FORCE|' kernel/Makefile
fi
grep -n -A1 'config_data:' kernel/Makefile | head -4

log "config guard"
for c in LTO_CLANG_FULL CFI_CLANG CFI_CLANG_SHADOW SHADOW_CALL_STACK \
         KASAN_HW_TAGS MODVERSIONS ARM64_4K_PAGES; do
  grep -q "^CONFIG_${c}=y$" "$O/.config" || {
    echo "FATAL: CONFIG_${c} was dropped -> vendor module CRCs will not match" >&2
    exit 1; }
done
echo "all critical configs present"

# -------------------------------------------------------------------- build
# KBUILD_BUILD_TIMESTAMP is the factory one, so `uname -v` is identical to
# stock (#1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023).
log "build"
export KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_USER=build-user
export KBUILD_BUILD_HOST=build-host
export KBUILD_BUILD_TIMESTAMP="Thu Apr 20 08:45:45 UTC 2023"
rm -f "$O/include/generated/compile.h" "$O/init/version.o" "$O/.version" || true
echo 1 > "$O/.version"

make -C "$K" O="$O" -j"$(nproc)" KSU_VERSION=${KSU_VERSION:-40994} Image

log "verify UTS"
strings "$O/vmlinux" | grep -m1 '^Linux version' || true
echo "KSU/SuSFS symbols: $(nm "$O/vmlinux" | grep -cE ' (T|t|D|d|B|b) (ksu_|susfs_|kernelsu_)' || true)"
echo "config.gz KSU/SUSFS lines: $(zcat "$O/kernel/config_data.gz" 2>/dev/null | grep -cE 'CONFIG_KSU' || true)"
echo "exported __crc_ symbols : $(nm "$O/vmlinux" | grep -c '^__crc_' || true)"

log "DONE: $O/arch/arm64/boot/Image"
