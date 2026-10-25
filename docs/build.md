# 怎么编译

内核由 GitHub Actions 编译，本地不需要 clang/LLVM。一次完整构建约 **60–70 分钟**。

```
仓库     ilmilm/ace-pgkm10-c13-kernel（建议私有）
工作流   .github/workflows/build-kernel.yml   name: build-ace-c13-kernel
触发     Actions → build-ace-c13-kernel → Run workflow → 选 main
```

## 工作流做什么

1. 清磁盘 + 加 16 GB swap（4C/16GB 的 runner 上全量 LTO 链接会 OOM）
2. 装构建依赖，拉 Android clang `r416183b`（走 LineageOS 镜像，AOSP gitiles 在 CI 上经常 503）
3. 跑 `scripts/build_ace_kernel.sh`
4. 上传 `Image` / `Image.gz` / `System.map` / `Module.symvers` / `config_data.gz`
5. 打 sanity 报告（7 项 config、UTS、`/proc/config.gz` 是否泄漏 `CONFIG_KSU`、`__crc_` 数量）

## 构建脚本的顺序

```
1. 克隆四个上游（全部钉 commit）
   ├─ OnePlusOSS/android_kernel_5.10_oneplus_mt6895            b2ed0599  PGKM10_13.1.0.9
   ├─ OnePlusOSS/android_vendor_mediatek_kernel_modules_mt6895 5f210489  PGKM10_13.1.0.9
   ├─ ShirkNeko/susfs4ksu                                      f43926dc  gki-android12-5.10
   └─ SukiSU-Ultra/SukiSU-Ultra                                ce75122   builtin
2. 断言源码就是 13.1.0.9：SUBLEVEL=149 + 两个提交信息含 PGKM10_13.1.0.9
3. 打 susfs 补丁（不加 --forward，打不上必须留 .rej）
4. 断言 my_setprocattr() 定义存在
5. 集成 KernelSU：链接 drivers/kernelsu、挂进 drivers/Makefile + Kconfig
6. 装手动 hook（builtin 分支不用 kprobe），校验 4/4 调用点
7. 配置：原厂 defconfig + ksu_susfs.config
8. 版本串伪装 + kernelrelease 硬断言
9. /proc/config.gz 伪装成原厂 config
10. 7 项关键 config 硬断言
11. 编译 Image
```

## 原厂 config 从哪里来

不是猜的，也不是从网上找的：从**原厂 `boot.img` 里内嵌的 IKCFG 段直接解出来**。

```python
kd = gzip.decompress(boot_img[4096:4096+kernel_size])   # 原厂 Image
s  = kd.find(b'IKCFG_ST'); e = kd.find(b'IKCFG_ED')
cfg = gzip.decompress(kd[s+8:e])                        # 6722 行完整 .config
```

`configs/stock_defconfig` 就是这份文件（181372 字节）。里面
`LTO_CLANG_FULL / CFI_CLANG / CFI_CLANG_SHADOW / SHADOW_CALL_STACK / KASAN_HW_TAGS /
MODVERSIONS / ARM64_4K_PAGES` 全是 `=y`，和上游 500 一致。

> 这份 config 带 `CONFIG_TRIM_UNUSED_KSYMS=y`，whitelist 指向 OnePlus GKI buildbot 的绝对路径
> （`/buildbot/src/android/common-android12-5.10-2022-12/...`），本地构建会因为找不到该文件
> 在 `GEN autoksyms.h` 直接失败。`configs/ksu_susfs.config` 里把它关掉：不裁剪只会多导出符号，
> 不会让任何一个厂商模块的 import 失败，也不影响任何符号 CRC。CI 有断言防止它被改回来。

## 三条不能动的硬约束

**1. 源码必须钉到 13.1.0.9 对应的提交**

分支 HEAD 会随新固件前移。用非 13.1.0.9 的源码配这台设备的 5.10.149 厂商模块，
`CONFIG_MODVERSIONS` 比对的符号 CRC 会漂移，CRC 变了的模块直接拒绝加载：
系统照常启动、KSU 照常工作，但某个硬件静默失效，从现象几乎不可能反推。

**2. 版本串伪装走 `scripts/setlocalversion`**

`CONFIG_LOCALVERSION` 不管用，kbuild 的 localversion 后缀来自脚本本身。直接整文件替换：

```sh
#!/bin/sh
echo "-android12-9-00010-gb3f24990ab22-ab9978632"
```

然后断言 `make kernelrelease` 逐字等于
`5.10.149-android12-9-00010-gb3f24990ab22-ab9978632`。

> 注：厂商模块的 vermagic 是 `5.10.149-android12-9-o-gb2bf83876efc`，和内核 UTS 不同。
> 这没问题：`CONFIG_MODVERSIONS=y` 时 `same_magic()` 会跳过第一个空格之前的内容，
> 只比对 `SMP preempt mod_unload modversions aarch64`。所以内核 UTS 可以逐字还原原厂串。

**3. 7 项 config 一个都不能掉**

```
CONFIG_LTO_CLANG_FULL=y      CONFIG_CFI_CLANG=y
CONFIG_CFI_CLANG_SHADOW=y    CONFIG_SHADOW_CALL_STACK=y
CONFIG_KASAN_HW_TAGS=y       CONFIG_MODVERSIONS=y
CONFIG_ARM64_4K_PAGES=y
```

`olddefconfig` 遇到不认识的工具链会**静默降级**（比如用 GNU binutils 会关掉 LTO）。
掉一项，所有厂商 `.ko` 的 `__versions` CRC 全部失效。CI 里有硬断言。

## 编译戳

`KBUILD_BUILD_TIMESTAMP` 直接用原厂值，所以 `uname -v` 和原厂逐字相同：

```
#1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023
```

## 拿到 artifact 之后

```bash
python scripts/pack_boot.py   ../原版镜像C13/boot.img  Image.gz  out/patched-boot.img
python scripts/verify_boot.py ../原版镜像C13/boot.img  out/patched-boot.img  Image
```

`pack_boot.py` 做四件事：

1. 用 `Image.gz` 替换原厂内核（保持 `gzip -9 -n` 风格，FLG=0x00）
2. ramdisk 逐字节保留原厂
3. vbmeta 原样搬运，按新的 `content_end` 重写 AVB footer
4. 刷之前校验：gunzip 后与 `Image` 一致、ARM64 magic、ramdisk 逐字节相同、vbmeta 逐字节相同

校验脚本打印 11 项检查，必须全 PASS。

## 常见失败

| 现象 | 原因 |
|---|---|
| 8 分钟内失败，`rejects: N`（N>0） | susfs 补丁与 5.10.149 内核树冲突，需要调整或换 `SUSFS_SHA` |
| `FATAL: susfs patch did not define my_setprocattr` | 补丁 hunk 半应用 |
| `FATAL: CONFIG_XXX was dropped` | 工具链不对，LTO/CFI 被降级 |
| `FATAL: kernelrelease is '...'` | `scripts/setlocalversion` 没生效 |
| `FATAL: kernel source commit is not PGKM10_13.1.0.9` | pin 错了或浅克隆取到了别的提交 |
| 65 分钟后 `undefined symbol: ksu_*` | KSU/susfs 版本错配 |
| 编出来能开机但 `su` 不可用 | inline hook 失效（版本错配），同上 |
