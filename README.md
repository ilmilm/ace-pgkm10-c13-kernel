# 一加 Ace (PGKM10 / OP5565 / MT6895) — ColorOS 13 / PGKM10_13.1.0.190

本仓库是 [`ilmilm/ace-pgkm10-kernel`](https://github.com/ilmilm/ace-pgkm10-kernel)（ColorOS 15 / 5.10.209）的
**ColorOS 13 版本**：同一套「锁 BL 状态伪装 + 内建 KernelSU + SuSFS」思路，针对另一个固件重新做了一套 pin、
补丁点和产物。两个仓库互不通用，镜像不能混刷。

```
设备    PGKM10_13.1.0.190 (CN01)   ColorOS 13 / Android 13   ← 真机实测 build id
内核    5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
内核戳  #1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023   （原厂值，直接复用）
源码    kernel/vendor 均 pin 到 PGKM10_13.1.0.9 快照（OnePlusOSS 该机型唯一的 5.10.149 快照）
```

**已在真机验证**：`green` / `locked` / `device_state=locked` / `su -c id` 全绿，三个分区内容与本地产物
逐字节一致。验收记录见 [`docs/verify-on-device.md`](docs/verify-on-device.md)。

> 只支持这个 5.10.149 代。换固件代（5.10.110 / 5.10.168 / 5.10.209…）就重做整套 pin 和补丁点。

## 三个分区的关系

```
patched-lk.img           → 能不能启动（MTK 证书链 + AVB 门禁 + 启动状态）
patched-vendor_boot.img  → 能不能拿到 root（安全守卫模块会杀掉提权进程）
patched-boot.img         → 有没有 root 功能（KSU 内核本体）
```

**必须三个配套，刷写顺序固定 `lk` → `vendor_boot` → `boot`。**

## 原版镜像基线（本仓库全部补丁的输入）

| 文件 | 分区 | 大小 | sha256 |
|---|---|---|---|
| `boot.img` | `boot` | 67108864 | `004646320851b7f9f6da91f37837c4c212be0b1c55a3c5aca744ddaf17e49b10` |
| `vendor_boot.img` | `vendor_boot` | 67108864 | `5eafce6950c194fd493dfe39df9cac68dede6dd91eb9637db6d9a1c42d914e59` |
| `lk.img` | `lk` | 3534848 | `2a38a0beed1f523758d58bc3aaf0b3e1b4e784ddbb09a03ead775bb76f5fd04a` |

`boot.img` 里内嵌了原厂完整 `.config`（IKCFG 段，6722 行），是本仓库 `configs/stock_defconfig` 的来源，
也是判断「这份镜像到底是哪个固件」的最硬证据。

## 改了什么

### lk（4 处，16 字节）

| 地址（payload 内偏移） | 原指令 | 改成 | 作用 |
|---|---|---|---|
| `0x057eac` | `mov w0, #2` | `mov w0, wzr` | 启动状态 → 0 (green) |
| `0x057ed4` | `mov w0, #3` | `mov w0, wzr` | 启动状态 → 0 (green) |
| `0x058098` | `mov w0, #2` | `mov w0, wzr` | 启动状态 → 0 (green) |
| `0x0649f8` | `csel x2, x10, x9, eq` | `mov x2, x10` | `ro.boot.vbmeta.device_state` → `locked` |

payload 从文件偏移 `0x200` 开始，所以文件偏移 = 上述地址 + `0x200`。
只改 `lk` 本体，`bl2_ext` / `aee` / `lk_main_dtb` 逐字节不动；改完用 legacy 模式重签 CERT2，
容器内四段证书链仍然全部 `VALID`（`verify_mtk_image.py --all`）。推导过程见 [`docs/lk.md`](docs/lk.md)。

### vendor_boot（删一个模块）

删掉 `lib/modules/oplus_security_guard.ko`，以及 `modules.load` / `modules.load.recovery` /
`modules.dep` 里对它的引用：cpio 条目 984 → 983。`oplus_secure_harden.ko` 保留。

vendor_boot v4 的布局是 `header | ramdisk(lz4 legacy) | dtb | ramdisk_table | bootconfig | vbmeta | footer`，
重打包时 dtb 段原样搬运、ramdisk_table 里的 size 同步更新、**原厂 vbmeta 逐字节搬运**（只改 footer 里的偏移）。

### boot（换内核）

用 Actions 编出来的 `Image.gz` 替换原厂内核，ramdisk 逐字节保留原厂，vbmeta 原样搬运、按新
`content_end` 重写 AVB footer —— 和上游仓库的 `scripts/pack_boot.py` 完全一致（两版 boot.img 都是 64 MB，
分页/头部版本/尺寸字段都一样，脚本可直接用）。

## 构建

推 GitHub → Actions → `build-ace-c13-kernel` → Run workflow。约 60–70 分钟，产物 `ace-c13-kernel`。

钉死的源码提交（**不要用分支 HEAD**）：

```
kernel  OnePlusOSS/android_kernel_5.10_oneplus_mt6895
        b2ed0599ada1ba8bd4464eb687500aa905cf8268   PGKM10_13.1.0.9 (5.10.149)
vendor  OnePlusOSS/android_vendor_mediatek_kernel_modules_mt6895
        5f210489762653c23bc6573e72e10fc4b146d094   PGKM10_13.1.0.9
susfs   ShirkNeko/susfs4ksu          f43926dc...  gki-android12-5.10
ksu     SukiSU-Ultra/SukiSU-Ultra    ce75122...   builtin
```

CI 里有硬断言：`Makefile` 必须是 `5.10.149`、两个上游提交信息必须含 `PGKM10_13.1.0.9`、
`kernelrelease` 必须逐字等于原厂串、7 项关键 config 一个都不能掉。

## 本地打镜像

```bash
# 补丁点全部针对 PGKM10_13.1.0.9 的原厂 lk.img，换固件会直接断言失败
python scripts/patch_lk.py           --stock ../原版镜像C13 --out out
python scripts/patch_vendor_boot.py  --stock ../原版镜像C13 --out out
python scripts/verify_vendor_boot.py --stock ../原版镜像C13 --out out
# Image 是 artifact 里**解压后**的内核（不是 Image.gz），脚本自己按原厂风格 gzip
python scripts/pack_boot.py          ../原版镜像C13/boot.img Image out/patched-boot.img
python scripts/verify_boot.py        ../原版镜像C13/boot.img out/patched-boot.img Image
python scripts/crc_audit.py          Module.symvers configs/stock_module_crc.json
```

`patch_lk.py` 需要 `pwnage24mtk` 工具链（`parse-part-img.py` / `sign_mtk_cert.py` /
`build-part-img.py` / `verify_mtk_image.py`），放在 `tools/pwnage24mtk-main/` 下。

## 刷写

先查槽位：`adb shell getprop ro.boot.slot_suffix`，下面以 `_b` 为例，按实际替换。

```bash
fastboot flash lk_b           patched-lk.img
fastboot reboot
fastboot flash vendor_boot_b  patched-vendor_boot.img
fastboot reboot
fastboot flash boot_b         patched-boot.img
fastboot reboot
```

顺序不能变：lk 是让另外两个分区被接受的前提。详见 [`docs/flash.md`](docs/flash.md)。

## 验收

```bash
adb shell su -c id                              # uid=0(root) context=u:r:ksu:s0
adb shell uname -r                              # 5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
adb shell uname -v                              # #1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023
adb shell getprop ro.boot.verifiedbootstate     # green
adb shell getprop ro.boot.flash.locked          # 1
adb shell getprop ro.boot.vbmeta.device_state   # locked
```

## 状态

**已在真机刷写并验证通过**（2026-10-25，`_b` 槽，build `PGKM10_13.1.0.190(CN01)`）。
完整输出见 [`docs/verify-on-device.md`](docs/verify-on-device.md)。

| 验收项 | 实测 |
|---|---|
| `ro.boot.verifiedbootstate` | `green` |
| `ro.boot.flash.locked` | `1` |
| `ro.boot.vbmeta.device_state` | `locked` |
| SELinux | `Enforcing` |
| `uname -r` | `5.10.149-android12-9-00010-gb3f24990ab22-ab9978632` |
| `uname -v` | `#1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023` |
| `su -c id` | `uid=0(root) ... context=u:r:ksu:s0` |
| `ksud --version` | `4.2.1-r1 (uapi: 6)` |
| `ksud susfs status` | `true` |
| 三个分区内容 | 与本地产物 sha256 **逐个相同** |

构建侧（run `40122393288` / `40125068885`，两次产物逐字节一致）：

| 项 | 值 |
|---|---|
| `Image` | 48044908 字节，sha256 `ec8ae378797bf4808d95f0ace4b15ff51c9c385d9c08c4f5626b29691cd4df53` |
| `uname -r` 断言 | 逐字等于原厂串 |
| KSU/SuSFS 符号 | 331 |
| `/proc/config.gz` 里的 `CONFIG_KSU` | 0 行（设备上实测也是 0） |
| CRC 审计 | 949 个重叠符号 **drift 0**；389 个"缺失"符号全部由其它厂商模块导出，真正缺失 0 |
| 设备侧模块 | 470 个全部加载，dmesg 无 `disagrees` / `version magic` / `Unknown symbol` |

静态校验：

| 产物 | 校验 |
|---|---|
| `patched-lk.img` | 四段证书链 `VALID` ×4；payload 与 store 相比**只有 16 字节不同** |
| `patched-vendor_boot.img` | 21 项结构检查 PASS（cpio 983、dtb 逐字节、vbmeta 逐字节） |
| `patched-boot.img` | 16 项检查 PASS（ramdisk 逐字节、vbmeta 逐字节、gunzip==Image） |

**注意**：装完 SukiSU 管理器后必须在弹窗里给一次 root 授权，否则 `su` 报 `inaccessible or not found`——
那是没授权，不是内核问题。

未验证：Play Integrity / TEE、Zygisk 与模块功能、长期稳定性、OTA（升级会覆盖这三个分区）。

## 许可

本仓库脚本与文档 MIT。KernelSU / SuSFS / OnePlus 内核源码、原厂固件镜像版权归各自所有者，
仅作个人设备研究用途。
