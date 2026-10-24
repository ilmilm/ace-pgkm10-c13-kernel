# 怎么刷、怎么回滚

**先读完整篇再动手。`lk` 刷错 = 不亮机 + 没有 fastboot，只能靠 BROM / 工程线救。**

## 0. 先查槽位

```bash
adb shell getprop ro.boot.slot_suffix      # 输出 _a 或 _b
```

本文命令全部写成 `_b`。**你查到什么槽，就把命令里的 `_b` 换成那个。**

## 1. 准备

- 三个产物齐全：`patched-lk.img` / `patched-vendor_boot.img` / `patched-boot.img`
- 手机能进 fastboot：`adb reboot bootloader`
- 确认 fastboot 能列出分区：`fastboot getvar all`（至少能看到 `slot-count`、`current-slot`）
- **先备份当前槽的三个分区**（可选但强烈建议）：
  ```bash
  fastboot getvar current-slot
  # 没有现成 readback 时，用 GeekFlashTool / mtkclient 读回 boot_b / vendor_boot_b / lk_b
  ```

## 2. 刷写顺序（不能变）

```bash
fastboot flash lk_b           patched-lk.img
fastboot reboot
```

等进系统（或至少过第一屏）之后再刷下一个：

```bash
adb reboot bootloader
fastboot flash vendor_boot_b  patched-vendor_boot.img
fastboot reboot
```

最后：

```bash
adb reboot bootloader
fastboot flash boot_b         patched-boot.img
fastboot reboot
```

**为什么必须先 lk**：`lk` 里做了两件事——绕过 MTK 证书校验、跳过 boot/vendor_boot 的验签门禁。
没有它，直接刷另外两个分区会报「文件损坏」并卡住。

## 3. 验收

```bash
adb shell getprop ro.boot.verifiedbootstate     # green
adb shell getprop ro.boot.flash.locked          # 1
adb shell getprop ro.boot.vbmeta.device_state   # locked
adb shell uname -r                              # 5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
adb shell uname -v                              # #1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023
adb shell su -c id                              # uid=0(root) context=u:r:ksu:s0
```

## 4. 配套管理器

`SukiSU_v4.2.1-r1_41049-release.apk`。配对判据是 **UAPI 版本**（现在两边都是 6），不是 build 号：
内核 `40994-6`、管理器 `41049-6` 共存无提示。

## 5. 回滚

按相反顺序刷回原厂镜像（`boot` → `vendor_boot` → `lk`），每一步都确认能进系统再刷下一个：

```bash
fastboot flash boot_b         boot_b.img
fastboot reboot
fastboot flash vendor_boot_b  vendor_boot_b.img
fastboot reboot
fastboot flash lk_b           lk_b.img
fastboot reboot
```

（本文档里的原厂文件指 `原版镜像C13/` 里那三个 readback。）

## 6. 变砖了

`lk` 写坏的表现：**按电源键没反应、插电脑没 fastboot、只有 preloader/MTK 端口**。

- 用 MTK BROM 工具（`mtkclient` / SP Flash Tool）重新写 `lk` 分区
- 需要 preloader 阶段能被识别：关机后按住音量键插线，或短接主板测试点
- 只要 `preloader` 和 `boot` 没动，BROM 一般都能救回来

## 7. 已知限制

1. `ro.boot.vbmeta.digest` 仍是真实摘要，和出厂值不同 → Play Integrity 的强校验过不了
2. `device_state=locked` 只对「读属性」的检测生效，TEE attestation 读的是真实锁状态
3. 安全守卫模块被删 → OPPO 的提权拦截整体失效，副作用是部分检测类 App 可能有反应
