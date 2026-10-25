# 真机验收记录

**日期** 2026-10-25　**设备** OnePlus Ace `PGKM10` / `OP5565`（序列号 DQE65LW8R84H4DQ4）
**槽位** `_b`　**build id** `PGKM10_13.1.0.190(CN01)`　**Android** 13

刷写顺序：`lk_b` → `vendor_boot_b` → `boot_b`，每步之间重启一次。

## 1. 三个分区内容 = 本地产物（逐字节）

```
lk_b          (前 3534848 字节) 821e81717b408dd19413e9d95bb335692051357826fca3e1574d214eb16732d4
boot_b        (67108864)        fafd669cf21d1d5620b13a618671b91b609fa678c8985e1929fc71096907f187
vendor_boot_b (67108864)        166be91e5a7388ce6b168a2931509d74a510850ebb43905ae00ac651434a91eb
```

与本仓库 `out/` 里三个产物的 sha256 完全一致，说明设备上跑的就是这几个文件。

`lk_b` 分区真实大小是 `5242880`，我们只写了前 `3534848` 字节（与原厂 readback 等长）。
preloader 按头部链解析、遇到 `img_list_end` 即停，尾部残留的旧数据不参与解析，实测不影响启动。

## 2. 启动状态

```
$ adb shell getprop ro.boot.slot_suffix           → _b
$ adb shell getprop ro.boot.verifiedbootstate     → green
$ adb shell getprop ro.boot.flash.locked          → 1
$ adb shell getprop ro.boot.vbmeta.device_state   → locked
$ adb shell getenforce                            → Enforcing
```

## 3. 内核

```
$ adb shell uname -r
5.10.149-android12-9-00010-gb3f24990ab22-ab9978632
$ adb shell uname -v
#1 SMP PREEMPT Thu Apr 20 08:45:45 UTC 2023
```

`uname -v` 与原厂编译戳逐字相同（`KBUILD_BUILD_TIMESTAMP` 直接复用了原厂值）。

## 4. root

```
$ adb shell su -c id
uid=0(root) gid=0(root) groups=0(root) context=u:r:ksu:s0

$ adb shell su -c "ksud --version"
ksud 4.2.1-r1 (uapi: 6)

$ adb shell su -c "ksud susfs status"
true
```

管理器 `com.sukisu.ultra`（SukiSU v4.2.1-r1 / build 41049）。**装完管理器后必须在弹窗里给 root 授权**，
否则 `su` 会报 `inaccessible or not found`——这不是内核问题，只是没授权。

## 5. 隐藏项

```
$ adb shell zcat /proc/config.gz | grep -c CONFIG_KSU
0                                    # /proc/config.gz 是原厂 config

$ adb shell grep -c ksu_ /proc/kallsyms
grep: /proc/kallsyms: Permission denied      # 非 root 读不到

$ adb shell su -c "grep -c ksu_ /proc/kallsyms"
10
$ adb shell su -c "grep ksu_ /proc/kallsyms | head -3"
0000000000000000 t anon_ksu_ioctl
0000000000000000 t anon_ksu_release
0000000000000000 T setup_ksu_cred
```

root 下能看到 10 个 `ksu_` 名字但地址全是 `0`；`susfs_` 因为
`CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y` 完全不可见（计数 0）。

## 6. 厂商模块

```
$ adb shell cat /proc/modules | grep security_guard      → 无输出（已删掉，符合预期）
$ adb shell cat /proc/modules | grep secure_harden
oplus_secure_harden 16384 0 - Live ... (O)               # 保留，正常加载
$ adb shell wc -l /proc/modules                          → 470
$ adb shell dmesg | grep -iE 'disagrees|version magic|Unknown symbol'   → 无输出
```

470 个模块全部加载、没有任何 CRC / vermagic 报错，说明 `CONFIG_MODVERSIONS` 这关过了。
这和构建前的静态审计一致（949 个重叠符号 drift 0）。

## 7. 未验证的项

- Play Integrity / TEE attestation：`ro.boot.vbmeta.digest` 仍是真实摘要，强校验不可能过
- Zygisk / 模块安装、隐藏类 App 的实际表现
- 长期稳定性、OTA 升级（升级会覆盖这三个分区）

## 复现命令

```bash
adb shell getprop ro.boot.slot_suffix
adb shell getprop ro.boot.verifiedbootstate
adb shell su -c id
adb shell su -c 'ksud susfs status'
adb shell 'su -c "dd if=/dev/block/by-name/boot_b bs=1M count=64 2>/dev/null | sha256sum"'
```
