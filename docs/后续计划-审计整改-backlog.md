# XinRefinement 审计整改后续计划（v1.6.3 之后）

> 本文件记录 2026-11-11 全局代码审计（架构师 / QA / 工程师三份报告）中已交付与已登记未修的整改项，
> 以及下一轮的工作优先级。**仅作计划追踪，不含任何构建/发布内容。**

## 一、本轮已交付（已并入 master，随 v1.6.3 推送）

| 编号 | 类别 | 内容 | 数值影响 |
|---|---|---|---|
| F01 | 正确性 | `name_mineral` 在 `structure_with_cell` / xyz 步重建时丢失 → 物相显示名退化（Quartz→SiO2） | 否（纯展示） |
| F02 | 正确性 | legacy `_unpack` 重建 `ProfileParams` 漏搬运 `size_strain` | 否（生产走 registry） |
| F03 | 正确性 | `api.report()` 的 `_solve_raw` 漏 `refine_po`，与 `api.refine()` 不一致 | opt-in 路径有意改变，默认不变 |
| F04 | 序列化 | `.xinr`/`.xinm` 谱图 `%.10g→%.17g`，保存/重开逐位保真 | 否 |
| F05 | 健壮性 | CLI `-o` 父目录缺失自动建目录；`to_report` 织构补 `model/degree/coeffs` | 否 |
| F06 | i18n | 步骤按钮语言切换后仍显中文 → 改 `tr(f'step.{key}')` | 否 |
| 取消测试 | 测试 | `test_run_all_does_not_record_cancel_as_failure` 墙钟谓词→计数谓词，断言回归真契约 | 否 |
| A11 | 正确性 | e.s.d. 报表「值」列误填 e.s.d. → `EsdResult` 增 `values`，文本/JSON 同步 | 否（仅复制已算好的 x_final/c） |

全量回归：`553 collected / 547 passed / 0 failed / 6 skipped`，golden CLI Rwp 逐位 `3.4074156640940005` 不变。

## 一之二、第三批已交付（v1.6.4，2026-11-12）

> 对应本文件 §2.1 / §2.2 中被点名的五项，全部属「可安全修、不碰数值」。

| 编号 | 类别 | 内容 | 数值影响 |
|---|---|---|---|
| A07 | 健壮性 | `.xinr` 解压会话目录由「只写不删」改为有界回收（最近 8 个 / 7 天 / 512 MB 三重上限，当次目录 `protect` 绝对保留） | 否（纯磁盘生命周期） |
| A08 | 健壮性 | 内嵌 `result/refine.json` 解码失败不再静默：新增 `warnings` 键，状态栏逐条提示（`.xrp` 旧路径同键空列表） | 否（纯提示） |
| B07 | 性能 | legacy 文本谱图读盘 2~3 次 → 1 次（`head/full_text/raw/key` 四可选入参下传）；`Pattern.meta` 与异常文案逐字不变 | 否（同一份字节少读几次） |
| B02 | 性能 | `estimate_esd` 三处各算一遍 → 一次复用（失败也缓存）；主线程不再重复跑 3 遍全谱前向 | 否（复用同一 EsdResult） |
| records | 正确性 | `run_all()` 开跑前清空 `state.records`，同一 runner 二次连跑不再累加 | 否（引擎外状态） |

全量回归：`579 collected / 579 passed / 0 failed / 0 skipped`，golden CLI Rwp 逐位 `3.4074156640940005` 不变
（验收证据见 `docs/验收-v164-审计整改第三批.md`）。

## 二、已登记未修清单（按风险分类）

### 2.1 易用性 / 健壮性（可安全修，不碰数值）
- **A07** ~~`gui/project.py` 会话解压目录建在 `tempfile.gettempdir()` 且从不清理，内嵌谱/CIF 无限累积。~~
  ——**已在 v1.6.4 交付**（有界回收：8 个 / 7 天 / 512 MB，见 §一之二）。
- **A08** ~~`.xinr` 内 `refine.json` 损坏 → `result_full=None` 且不写 missing，界面静默无提示。~~
  ——**已在 v1.6.4 交付**（新增 `warnings` 键 + 状态栏提示，见 §一之二）。
- **records 累加** ~~`recipe.py:937-940` 重置状态未清 `self.state.records`，同一 runner 二次 `run_all` 累加旧记录（`test_recipe.py` 未覆盖）。属状态语义小瑕疵，单独用例守护即可。~~
  ——**已在 v1.6.4 交付**（`records.clear()` + 守护用例，见 §一之二）。

### 2.2 性能（低风险、不碰数值）
- **B02**（推荐先做）~~：`estimate_esd` 三处重复，每次约 4p 次全谱前向，全在主线程槽函数。~~
  ——**已在 v1.6.4 交付**（`_esd_for` 单值缓存，失败也缓存，见 §一之二）。
- **B07**（推荐先做）~~：`core/patterns.py` 同一谱图文件重复 IO 2~3 次（MB 级、毫秒量级，非热路径）。~~
  ——**已在 v1.6.4 交付**（单次读盘，实测 `.xy` 2→1 / 岛津 `.txt` 5→1，见 §一之二）。
- **B03**：`gui/canvas.py` 每次 `_redraw` 整图重建 axes/sticks/峰棒；轴切换本可只改数据变换。
- **B06**：全局 `_PEAKS_CACHE` 256 项整表清空致命中率锯齿；两处 `cell_cache` 无上限。
- **B01**（需重设计）：工具栏「▶精修」同步 `solve()` 阻塞主线程，UI 冻结不可取消；注释明写保留测试契约，属重设计。
- **B04**（谨慎）：`core/profile/cif.py` `expand_symmetry` 双重循环去重，10⁵–10⁶ 次比较；向量化会改变去重顺序 → 改变 |F|²/QPA，**必须配套 CIF 语料回归**。
- **B05**（禁动）：残差热路径每相重算 `compute_phase_profile` + 大数组拷贝，数值核心，红线内禁止。

### 2.3 异常路径重构（需先建 CIF 语料回归集）
- **A13**：`core/profile/cif.py` `except Exception: pass` 静默丢弃无法解析的 symop → 展开不完整 → |F|²/QPA 静默错（异常路径改数值）。
- **C07**：晶系/对称兜底重复 4 层，层层静默降级。
- **A14**：一批 `except Exception` 静默降级；`trf→自研 LM` 回退会换优化器改 Rwp 且无提示。

### 2.4 可维护性 / 技术债（C 类，单列排期）
- **C01–C11**：死代码、悬空 i18n 键、重复样板、空 `if: pass` 块等；不含数值、不含功能缺陷，属整洁度。
- **775 条 spglib 弃用警告**：`core/symops.py:95` 枚举 530 次 hall 设置触发；spglib 2.8.0 默认翻转、3.0 移除旧错误处理，升级前需专项评估（设 `OLD_ERROR_HANDLING=False` + `try/except SpglibError` 收口）。

### 2.5 环境依赖（非代码缺陷）
- **6 个 skip**：`tests/test_joint_s1.py` / `test_cif_robust.py` 硬编码工作目录外 `COD_ROOT` 绝对路径 + 缺 `gemmi`/`xinmatch`。属能力档位差异，正确处置是 CI 能力标记 + 基线分档，**不为凑 0 skipped 装包或改路径**。
- **待全能力环境回归**：`test_joint_s1.py` 三例本机 skip，F04 的 `.17g` 对路径 A/B 的 Rwp 一致性（`rel=1e-9`）需在 COD 档案 + XinMatch/gemmi 可用后回归确认（风险评估：低，非阻塞）。

## 三、建议下一轮优先级（v1.7 方向）

> v1.6.4 已交付原第 1、2 条（A07 + A08、B02 + B07）与原第 3 条中的
> 「records 累加补用例」。剩余项如下。

1. ~~**低风险易用性**：A07 + A08（用户可感知的健壮性，且不碰数值）。~~ ✅ v1.6.4 已交付
2. ~~**低风险性能**：B02 + B07（收益实打实、风险最低，可作为「调试优化」专项）。~~ ✅ v1.6.4 已交付
3. **测试契约补全**：~~records 累加补用例~~（✅ v1.6.4 已交付）；剩 `test_joint_s1.py`
   全能力环境回归（COD 档案 + XinMatch/gemmi 可用后）。
4. **设计类（单独排期，不混入小修）**：B01 / B03 / B06、A13 / C07、C 类清理。
5. **数值攻坚（对标基准，独立专项）**：样 7 近非晶宽包起点、样 1 结构占位、样 5 gehlenite、K23 重启链、§4 计划表 BAUXITE / GRANODIO 数据集；以及 Mell 已定论的 M4 Popa LB 之外的剩余差距。
   **当前阻塞事实**：本机 `D:\Project\XRDdata` 基准集缺失，这道专项在没有基准集的环境里无法启动——先补数据，再谈攻坚。

## 四、验收红线（不可触碰）

- **golden CLI Rwp = `3.4074156640940005` 逐位不变**。
- 不碰优化器、峰形、权重、配方默认值、参数打包/解包生产路径语义、任何残差前向函数（B05、B04 改展开顺序、A13/A14 异常路径均属此边界）。
- commit/push 需显式批准；`PDF2-2004`（ICDD 版权）永不入 Git/Release；提交信息禁含禁用词。
- 提交拆「代码/测试」与「文档」两笔；push 后 `git ls-remote` 校验远程 HEAD = 本地 HEAD。
- 发布（构建 exe/安装包、打 Release 资产）单独走发布流程，不混在代码整改内。
