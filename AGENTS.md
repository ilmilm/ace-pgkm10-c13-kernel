# AGENTS.md — 给接手本仓库的 AI / 协作者

> 本文件优先级高于 README 与 docs 里的任何叙述。**先读这里再动代码。**

## 唯一目标

```
设备    OnePlus Ace  PGKM10 / OP5565 / MT6895
固件    PGKM10_13.1.0.190 (CN01)   ColorOS 13 / Android 13   ← 真机实测
内核    5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
源码    kernel/vendor 均 pin 到 PGKM10_13.1.0.9 快照
        （OnePlusOSS 该机型唯一的 5.10.149 快照；CRC 已按设备自带模块核对 drift 0）
```

**只支持这一个组合。** 不讨论、不支持、不引入其他固件版本或内核版本。
如果上下文里出现了 `5.10.209` / `15.0.0.500`，那是**上游另一个仓库**（ColorOS 15）的内容，
不是本项目目标，**不要照抄它的地址**——两版 lk 的指令布局完全不同。

## 硬规则（违反即构建失败或砖机）

1. **源码必须钉到 13.1.0.9 对应的提交，禁止用分支 HEAD**
   ```
   kernel  b2ed0599ada1ba8bd4464eb687500aa905cf8268   PGKM10_13.1.0.9 (5.10.149)
   vendor  5f210489762653c23bc6573e72e10fc4b146d094   PGKM10_13.1.0.9
   susfs   f43926dc94b8ffbf9b74321313536600f69367b1   gki-android12-5.10
   ksu     ce75122bec7423e0f1fa06e3e9a174085c5231ab   builtin
   ```
   KSU 与 susfs 必须**同代升级**：一次只动一个的后果是链接期 undefined symbol，
   或者编得过但 inline hook 静默失效（管理器显示"工作中"，`su` 根本不存在）。

2. **7 项 config 一个都不能丢**：`LTO_CLANG_FULL` `CFI_CLANG` `CFI_CLANG_SHADOW`
   `SHADOW_CALL_STACK` `KASAN_HW_TAGS` `MODVERSIONS` `ARM64_4K_PAGES`。
   掉一项 → 所有厂商 `.ko` 的 `__versions` CRC 失效。

3. **`configs/stock_defconfig` 是从原厂 boot.img 的 IKCFG 段解出来的**，不要手改，
   也不要拿 500 的 defconfig 顶替。

4. **版本串伪装走 `scripts/setlocalversion`**（不是 `CONFIG_LOCALVERSION`），
   必须 `make kernelrelease` 逐字等于 `5.10.149-android12-9-00010-gb3f24990ab22-ab9978632`。

5. **`/proc/config.gz` 必须从原厂 defconfig 生成**，改完断言 `CONFIG_KSU` 行数为 0。

6. **lk 只改 4 处，共 16 字节**：
   `0x057eac` / `0x057ed4` / `0x058098`（`mov w0,wzr`）、`0x0649f8`（`mov x2,x10`）。
   地址是 **payload 内偏移**，文件偏移 = 地址 + `0x200`。
   - **不要**去动 `bl2_ext` / `aee` / `lk_main_dtb` —— 它们逐字节原样，证书才算得对
   - 改完**必须**重签（`sign_mtk_cert.py -w --legacy`）并 `verify_mtk_image.py --all` 四段全 VALID
   - 容器重建后补零回原长 `3534848`，否则刷写工具看到的尺寸变了

7. **`oplus_security_guard.ko` 是 root 的拦路虎**，从 vendor_boot 的 ramdisk 删掉
   （`lib/modules/` + `modules.load` + `modules.load.recovery` + `modules.dep`）。
   `oplus_secure_harden.ko` 保留。

8. **vendor_boot v4 顺序**：`header | ramdisk(lz4 legacy) | dtb | ramdisk_table | bootconfig | vbmeta | footer`。
   dtb 段原样搬运、table 里的 size 同步改、**原厂 vbmeta 逐字节搬运**、footer 必须是最后 64 字节。

9. **三个镜像必须配套，刷写顺序固定**：`lk` → `vendor_boot` → `boot`。

## 改东西之前

- 先读 [`docs/lk.md`](docs/lk.md)（补丁点怎么推出来的）和 [`docs/build.md`](docs/build.md)
- 涉及 boot 打包：`scripts/pack_boot.py` 保持 ramdisk 逐字节原厂、vbmeta 原样搬运
- 涉及 lk：改完必须重建证书链并四段 VALID，否则不要给出刷写建议

## 验收标准

```bash
adb shell su -c id                              # uid=0(root) context=u:r:ksu:s0
adb shell uname -r                              # 5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
adb shell uname -v                              # #1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023
adb shell getprop ro.boot.verifiedbootstate     # green
adb shell getprop ro.boot.flash.locked          # 1
adb shell getprop ro.boot.vbmeta.device_state   # locked
adb shell getprop ro.boot.slot_suffix           # 刷之前必须查
```

## 当前状态（诚实记录）

- 三个镜像已生成、静态校验通过、**并已在真机（PGKM10_13.1.0.190，`_b` 槽）刷写验证**：
  `green` / `locked` / `device_state=locked` / `su -c id` = `uid=0(root) context=u:r:ksu:s0`，
  `ksud susfs status` = `true`，三个分区内容与本地产物 sha256 逐个相同。
  输出见 [`docs/verify-on-device.md`](docs/verify-on-device.md)。
- 未验证：Play Integrity / TEE、Zygisk 与模块功能、长期稳定性、OTA（升级会覆盖这三个分区）。
- 改完代码重新出镜像后，上面这些结论自然作废，必须重新实测。
