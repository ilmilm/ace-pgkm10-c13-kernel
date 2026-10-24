# OnePlus Ace (PGKM10 / OP5565 / MT6895) — ColorOS 13 / PGKM10_13.1.0.9 内核方案

目标固件：`PGKM10_13.1.0.9(CN01)`，内核 `5.10.149-android12-9-00010-gb3f24990ab22-ab9978632`。

- 内核由 GitHub Actions 编译（`build-kernel` 工作流）
- 源码钉死：kernel `b2ed0599ada1` / vendor `5f2104897626`（均为 PGKM10_13.1.0.9）
- 原厂 config 从原厂 boot.img 内嵌的 IKCFG 段提取，不是猜的

