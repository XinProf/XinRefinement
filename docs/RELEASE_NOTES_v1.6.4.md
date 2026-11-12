# XinRefinement v1.6.4 — 审计整改第三批（工程健壮性 + 读取性能）

> 基线 `v1.6.3`｜主题：收纳 2026-11-11 全局审计中「可安全修、不碰数值」的五项——
> 工程解压目录的有界回收、内嵌结果损坏不再静默、谱图读取从 2~3 次收敛为 1 次、
> e.s.d. 重复求值收敛为一次、配方 records 二次连跑累加。
>
> **数值零变化**：引擎与数值路径零改动，golden 50/50 档仍是 `3.4074156640940005`，
> CLI/API 逐位不变。

## 下载

| 文件 | 大小 | SHA256 |
|---|---|---|
| `XinRefinement-1.6.4-setup.exe` | 75.3 MB | `258afa309558adfc18ca4a9bed3193213c2982b56006460291fae0a6f5b90701` |

> 正式版安装包（含注册机制，zh/en/ja 三语安装界面）。
> 内部评估版便携包仅用于内部验收，不随本 Release 发布。

## 一句话看变化

| | v1.6.3 | v1.6.4 |
|---|---|---|
| 临时目录 | 每个工程版本在 `%TEMP%\xinrefinement_projects` 新建一个目录，**从不清理** | 有界回收：保留最近 8 个 / 7 天 / 512 MB，当次正在用的目录绝不删 |
| 内嵌精修结果损坏 | 结果区**悄悄变空**，无任何提示 | 状态栏逐条提示「result/refine.json 无法解析，已忽略」 |
| 打开大谱图 | 同一文件读盘 2~3 次 | **1 次**（岛津 `.txt` 实测 5 次 → 1 次，FullProf `.dat` 3 次 → 1 次） |
| 保存工程 / 导出报告 | 各自重算一遍 e.s.d.（每次约 4p 次全谱前向，主线程） | 一次精修只算一次，失败结果也缓存 |
| 同一 runner 二次连跑 | `state.records` 累加，记录数翻倍 | 开跑前清空，记录数恒等于步数 |

## 逐项说明

### A07 · `.xinr` 解压会话目录有界回收
解压目录仍按 `<stem>_<mtime>` 命名、同 mtime 复用，语义不变；新增回收在每次解压后
顺手执行，三重上限：最近 8 个、7 天、集合总量 512 MB。
**`protect`（当次正在使用的目录）是唯一绝对保底**；`keep` 只是数量门槛，排在前 8
但已超 7 天的目录照样清掉。清理过程所有 `OSError` 一律吞掉——清理是副业，绝不能
影响打开工程。超龄被清掉的工程下次打开会重新解压一次内嵌数据（预期行为）。

### A08 · 内嵌 `result/refine.json` 解码失败不再静默
`load_project()` 返回值新增 `warnings` 列表（旧 `.xrp` 路径同键、空列表），
`apply_project()` 把每条告警拼进状态栏消息，不弹模态框。捕获范围仍是
`UnicodeDecodeError` / `JSONDecodeError`，没有放宽成 `Exception`。

### B07 · legacy 文本谱图单次读盘
`.xy/.txt/.dat/.csv` 原本被读 2~3 次（文本解码一次、格式嗅探读 4096 B 头、vendored
reader 再全量读一次）。现在只读一次原始字节，通过 `head=` / `full_text=` / `raw=` /
`key=` 四个**带默认值的可选入参**往下传，默认调用行为逐字不变。
`Pattern.meta` 的键与取值、各类解析异常的**类型与文案逐字未变**（用 HEAD 版本
overlay 双跑对拍验证，不是靠测试自证）。

### B02 · e.s.d. 三处重复求值收敛为一次
`MainWindow._esd_for()` 以 `id(res)` + `rwp` + `iters` + `id(_phases)` + 相名与 cell
为键缓存。失败的 `None` 也缓存（异常路径同样要跑满 4p 次前向，重试没有意义）。
`new_project()` 清空缓存。`estimate_esd()` 的入参与数值完全未变。

### records · `run_all()` 开跑前清空 `state.records`
同一 `RecipeRunner` 复用跑第二轮时会把上一轮 `StepRecord` 累加进来（记录数翻倍、
回退下标错位）。改为原地 `clear()`，保持 `run_all` 返回值与 `rollback()` 切片共享
同一 list 的既有语义。

## 升级注意

- **工程文件**：`.xinr` 格式未变，可直接打开 v1.6.3 的工程；`warnings` 是新增键，
  旧版本读到多余键会忽略。
- **长期使用**：`%TEMP%\xinrefinement_projects` 里 7 天以上或超出 8 个的旧会话目录
  会被自动清掉；工程源文件（`.xinr`）不受影响。
- **已知边界**：多进程同时打开同一工程时，B 进程的回收可能把 A 进程的会话目录当作
  「第 9 个旧目录」清掉（当次目录的 `protect` 只在本进程内有效）；工程重存不会保留
  上次打开时的 `warnings`（告警是「本次加载」的事实）。

## 构建与可复现性

- 构建环境：Python 3.10.11 + PyInstaller 6.22.3，`SOURCE_DATE_EPOCH` 取提交
  `7973d98` 的提交时间（`1794479509`）。
- **exe 层可复现**：同 epoch + 同源码，`XinRefinement.exe` / `XinRefinementCLI.exe`
  两次构建逐字节相同。
- **安装包层不可复现**：ISCC 的内嵌文件时间受 `SOURCE_DATE_EPOCH` 约束，但 PE 头取
  编译器 stub 时间，同输入两次打包尺寸相同、字节不同。**因此发布哈希以实际上传
  资产为准**，不要为「对齐 HEAD 时间戳」重传资产。
- 注册密钥不入库，正式版构建从 `XR_REG_SECRET` 或 `xinrefinement/registration_secret.txt`
  注入（该文件已 gitignore），以保证此前发出的注册码继续有效；缺文件时退回社区
  占位密钥（源码构建/内部评估版即此路径）。

## 校验

```bash
sha256sum XinRefinement-1.6.4-setup.exe
# 258afa309558adfc18ca4a9bed3193213c2982b56006460291fae0a6f5b90701
```

全量回归：**579 passed / 0 failed / 0 skipped**（v1.6.3 基线 553，本版新增 26 个用例）。

> 开发者注意：pytest 的 `--basetemp` 不要放在仓库工作区内。pytest 的 `tmp_path`
> 会按编号复用/清理子目录，在受限环境里可能撞上批量删除保护而在 fixture setup
> 阶段抛 `SystemExit: 1`，表现为成片假 ERROR；统一用 `--basetemp="$TEMP/xinr_..."`。
