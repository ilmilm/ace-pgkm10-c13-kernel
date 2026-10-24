# lk 补丁原理与地址表（PGKM10_13.1.0.9）

本文记录 **ColorOS 13 / 5.10.149** 这一版 `lk.img` 的补丁点、推导过程和验证结果。
和上游 500（5.10.209）的地址**完全不同**，不要混用。

## 一、镜像结构

`lk.img` 是 MTK 多镜像容器（3534848 字节，`0x35f000`）：

| 子镜像 | 偏移 | 大小 |
|---|---|---|
| `lk` | `0x0` | `0x113bc8`（数据从 `0x200` 开始） |
| `bl2_ext` | `0x114ca0` | `0xdd468` |
| `aee` | `0x1f31e0` | `0x11da20` |
| `lk_main_dtb` | `0x311cd0` | `0x4b2dc` |

每个子镜像后面跟 `cert1`（1733 字节）和 `cert2`（1011 字节）。
**只改 `lk` 本体**，另外三个 payload 逐字节原样。

`lk` 的虚拟加载基址是 `0xffff000050f00000`：`lk` 段里 `0xb8878` 处是一张
`state -> 字符串` 表，里面存的是绝对指针 `0xffff000050f b87xx`，可以直接反推基址。

## 二、启动状态：一个全局变量 + 一个 setter

payload 内 `0xd1300` 是状态全局变量（4 字节）。全镜像只有 **一个** 写入口：

```asm
0x058528: adrp x8, #0xd1000
0x05852c: ldr  w0, [x8, #0x300]     ; get_state()
0x058530: ret

0x058534: adrp x8, #0xd1000
0x058538: str  w0, [x8, #0x300]     ; set_state(int)   <-- 唯一写入点
0x05853c: ret
```

枚举值与原厂一致（与上游 500 实测相同）：`0`=green，`1`=yellow，`2`=orange，`3`=red。
`0xb8878` 处的 4 项表按 `green, yellow, orange, red` 排列，`0x9cc38/0x9cc40/0x9cc48/0x9cc50`
处另有四个指向 `oplusboot.verifiedbootstate=...` 字符串的绝对指针，也按同样顺序排列。

`set_state()` 有三个调用点，就是真正决定状态的地方：

```asm
; 调用点 A：验签结果 w21 == 0 -> 2 (orange)，否则 -> 3 (red)
0x057ea4: cbnz w21, #0x57ed0
0x057ea8: mov  w28, #1
0x057eac: mov  w0, #2          ; <-- 改 mov w0, wzr
0x057eb0: b    #0x57ed8
0x057ed0: mov  w28, wzr
0x057ed4: mov  w0, #3          ; <-- 改 mov w0, wzr
0x057ed8: bl   #0x58534

; 调用点 B：读到的状态 == 3 时补一个 2
0x058098: mov  w0, #2          ; <-- 改 mov w0, wzr
0x05809c: bl   #0x58534

; 调用点 C：本来就是 0（green），不动
0x05828c: mov  w0, wzr
0x058290: bl   #0x58534
```

三处 `mov w0, #2/#3` 全部改成 `mov w0, wzr`（`0x52800040`/`0x52800060` → `0x2a1f03e0`），
状态恒为 0。

**为什么不直接把 setter 改成 `str wzr`？** 能省一条指令，但会让恢复模式、fastboot 之类
本来靠 `orange` 走分支的流程也一起变 green，副作用面更大。按调用点改，只影响这三条路径。

## 三、`device_state` 伪装

`ro.boot.vbmeta.device_state` 由下面这段拼进 cmdline：

```asm
0x0649e0: adrp x9,  #0x98000
0x0649e4: adrp x10, #0xa8000
0x0649e8: add  x9,  x9,  #0x99f      ; 0x9899f = "unlocked"
0x0649ec: add  x10, x10, #0x5b6      ; 0xa85b6 = "locked"
0x0649f0: cmp  w8, #0
0x0649f8: csel x2, x10, x9, eq       ; w8==0 -> x10("locked")
0x0649fc: add  x1, x1, #0xe52        ; "androidboot.vbmeta.device_state"
0x064a04: bl   #0x64d10
```

改成无条件取 `x10`：

```
0x0649f8: 42 01 89 9a  →  e2 03 0a aa     (mov x2, x10)
```

改完 `ro.boot.vbmeta.device_state` 固定输出 `locked`。硬件真实锁状态（TEE）改不了，
所以 Play Integrity 的强校验仍然过不了，这一点和上游 500 一样。

## 四、地址表总览

| 地址 | 原指令 | 改成 | 作用 |
|---|---|---|---|
| `0x057eac` | `mov w0, #2` | `mov w0, wzr` | 状态 → 0 (green) |
| `0x057ed4` | `mov w0, #3` | `mov w0, wzr` | 状态 → 0 (green) |
| `0x058098` | `mov w0, #2` | `mov w0, wzr` | 状态 → 0 (green) |
| `0x0649f8` | `csel x2, x10, x9, eq` | `mov x2, x10` | `device_state` → locked |

共 4 处 × 4 字节 = **16 字节**。文件偏移 = 上表地址 + `0x200`。

## 五、重签（必须有，否则不亮机）

preloader 用 CERT1/CERT2（RSA-2048 + RSASSA-PSS）校验 `lk`。没有 OPPO 私钥，只能走 legacy
模式（`bypass_mode=1`，tag `0x20`）插入伪造的 image hash 块。工具来自
[pwnage24mtk](https://github.com/pwnage24/pwnage24mtk)：

```sh
python sign_mtk_cert.py -w --legacy lk_patched.bin -o lk_signed.bin
python build-part-img.py replace 原厂lk.img --name lk --file lk_signed.bin -o patched-lk.img
python verify_mtk_image.py patched-lk.img --all      # 四段必须全 VALID
```

期望结果（实测）：

```
Image: lk @ 0x0              cert2 @0x1146a0 size 2117   Result: VALID
Image: bl2_ext @ 0x1150f0    cert2 @0x1f3030 size 1011   Result: VALID
Image: aee @ 0x1f3630        cert2 @0x311b20 size 1011   Result: VALID
Image: lk_main_dtb @ 0x312120 cert2 @0x35ded0 size 1011  Result: VALID
```

`lk` 的 cert2 从 1011 涨到 2117 字节（legacy 块 + 新 hash 块），
所以后面的 `bl2_ext` / `aee` / `lk_main_dtb` 整体后移 **`+0x450`**。
容器重建后比原厂短 2864 字节，脚本会补零回原长 `3534848`，保证刷写工具看到同样的尺寸。

## 六、换机型/换固件怎么重新定位

1. `parse-part-img.py 原厂lk.img --split -o out` 拆出 `lk.bin`（数据从 `0x200` 起）
2. 用 capstone 线性反汇编 payload（`md.skipdata = True`，否则遇到数据就停）
3. 找 `adrp + add` 配对，目标落在 `green`/`orange`/`red`/`verifiedbootstate` 字符串上
4. 状态：搜 `str w?,[x?,#0x300]` 且 `adrp` 页为 `0xd1000`，找到唯一写入点，再看它的调用点
5. `device_state`：搜 `csel` 附近同时出现 `"locked"` / `"unlocked"` / `"androidboot.vbmeta.device_state"`
6. 改完必须 `verify_mtk_image.py --all` 四段全 VALID，否则不要刷

`scripts/lkxref.py` 是上游留下的通用 adrp+add xref 小工具，可以直接复用。
