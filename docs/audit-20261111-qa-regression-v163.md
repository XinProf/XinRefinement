# XinRefinement v1.6.3（A11 修复 + 版本升级）全量回归与 golden 复验报告（QA / 任务 #7）

| 项 | 值 |
|---|---|
| 实施对象 | `D:/XinRefinement`，git HEAD `ef27be4`（上一轮 F01–F06 已提交） |
| 任务 | #7 A11 修复 + 1.6.3 版本升级的独立验证与全量回归（对照上轮 #4 基线） |
| 环境 | `.venv/Scripts/python.exe`（Python 3.10.11 / pytest 9.2.0），同机同 venv；`-o addopts=""` + 全新 `--basetemp`（`C:/Users/ADMINI~1/AppData/Local/Temp/xinr_qa7_v163_5cf7d58u`，未复用历史 basetemp） |
| 全量命令 | `cd /d/XinRefinement && "D:/XinRefinement/.venv/Scripts/python.exe" -m pytest -o addopts="" --basetemp=<全新系统临时目录> -q` |
| 全量原始摘要 | **`547 passed, 6 skipped, 775 warnings in 224.74s (0:03:44)`，`PYTEST_EXIT=0`** |
| 上轮基线（#4） | `544 passed / 0 failed / 6 skipped / 775 warnings / 221.61s / EXIT=0`（collected 550） |
| 最终判定 | **PASS**（collected 553 / 547 passed / 0 failed / 6 skipped，与期望吻合；golden 逐位不变；A11 端到端正确；版本三处一致；工作树合规；schema 冻结） |
| 合规 | 除本报告外零写入；未改产品代码/测试；未装包；未改 COD_ROOT；未放宽断言；未 commit/push |
| 报告日期 | 2026-11-11 |

---

## 关键发现

1. **全量全绿、与期望完全吻合**：实测 `547 passed / 0 failed / 6 skipped`，collected `553 = 547 + 6`，与主理人期望 `553 → 547 passed / 0 failed / 6 skipped` 逐项一致。对照上轮 #4 `550 / 544 / 0 / 6`：collected +3、passed +3、failed/skipped 不变——增量恰好来自新增测试（`tests/test_cli_esd_report.py` 2 项 + `test_version_consistency.py` 加 `test_version_three_way_consistent` 1 项；`test_esd_geometry.py` 为**加断言**不改收集数）。
2. **golden 逐位不变**：`tests/test_golden_b.py::test_golden_5050_bit_identical` 全量与单独复验均 `PASSED`；只读脚本直连 `core.refine.nonlinear.refine` 复验 `repr(res.rf.rwp) == '3.4074156640940005'`，`BIT_IDENTICAL = True`。未改写任何 golden 文件。
3. **A11 端到端正确（独立复验，未采信工程师自报）**：真实 `solve() → estimate_esd()` 精修链上，`EsdResult.values` 与 `labels`/`esd` 同长同序（9/9/9）；`values[labels.index("global.zero")] = 0.0299134974192351` **逐位等于** `res.params.zero`；`scale[i]` 值也与 `res.phases[i].scale` 一致（防三类参数贴错位）。文本表「值」列（`0.0299135`）与「e.s.d.」列（`±6.78e-05`）**不同源**；JSON 键序 `labels → values → esd` 且等长。
4. **TCH 边界行为正确**：本批 zero/uvw 精修数据无 TCH 边界 NaN（`real_NAN_esd_labels = [] count=0`），故用**手工构造含 NaN 边界的 `EsdResult`** 做负向检查：边界行「值」列照常显示 `0`（参数真值）、「e.s.d.」列显示 `—（TCH 边界，无定义）`；JSON 中该参数 `values=0.0`、`esd=None`（NaN→None）。防"把 e.s.d. 误贴到值列"的旧 bug 复现。
5. **版本三处一致、无越界改写**：`__version__`（`__init__.py:7` = `1.6.3`）== iss `#define AppVersion`（`xinrefinement.iss:14` = `1.6.3`）== CHANGELOG 最新标题（`CHANGELOG.md:3` `## v1.6.3`）。`pyproject.toml:30` 为 `version = {attr = "xinrefinement.__version__"}`（dynamic，未硬编码）；历史 `CHANGELOG.md:35` `## v1.6.2` 条目保留未动；`1.6.3` 在全部 `.py/.iss/.toml/.cfg` 产品版本源中**仅这三处**，其余命中均为 `.workbuddy/memory` 与 `docs/audit-*` 文档（非版本源）。
6. **工作树合规**：`git status --short` 恰好 **10 行**（7 个 ` M`：`CHANGELOG.md`/`xinrefinement.iss`/`test_esd_geometry.py`/`test_version_consistency.py`/`__init__.py`/`cli/refine.py`/`esd.py` + 3 个 `??`：`a11-changes.md`/`a11-design.md`/`test_cli_esd_report.py`）；HEAD 仍 `ef27be4`，暂存区空，零新 commit。
7. **schema 冻结成立**：`core/report.py` 与 `.xinr` 的 `result/refine.json` 的写入方 `gui/project.py` **均未在改动列表**（`git diff --name-only` 不含二者），A11 只改 CLI 报表层（`cli/refine.py` 的 `_esd_section`/`_esd_json_dict`）+ `EsdResult` 数据载体；`test_micro_initial_report.py` + `test_project_zip.py` 单跑 `20 passed`。

## 落地物

- 本报告：`docs/audit-20261111-qa-regression-v163.md`（本轮唯一新增文件）。
- 全量 pytest 原始摘要、golden 只读复验输出、A11 端到端脚本输出、`-v -rs` 小范围边界验证输出、schema 冻结测试输出、`git status` 全文，均记录于下文第 1–6 节。
- 本轮**未产生**任何 `.py` / 测试 / 配置 / 既有文档 / golden 文件改动。

## 下一步

1. 任务 #7 判定 **PASS**；无需路由给工程师修源码，也无需 QA 自行修测试代码。
2. CHANGELOG v1.6.3「说明」段的基线档位表述由主理人安排工程师修正（**不影响测试**；本报告数值均为本轮实测，不依赖该句）。
3. `tests/test_joint_s1.py` 三例本机仍 skip（S3–S5），在本机无法覆盖 `.xinm` 路径 A/B 的 Rwp 一致性，需在「全能力环境」（COD 档案 + XinMatch/gemmi 齐全）恢复后回归确认；F04 相关风险任务 #2 第 9.3 节已判非阻塞。
4. 任务 #2 第 10 节登记的 A12 显示层加固与 Q17 等观察项不在本次范围，建议单列排期，不影响本轮 PASS。

---

## 1. 对照表（上轮 #4 vs 本轮 #7）

| 指标 | 上轮 #4（F01–F06） | 本轮 #7（A11 + 1.6.3） | 变化 | 判据 |
|---|---|---|---|---|
| collected | 550 | **553** | +3 | `--collect-only` 与全量均 553；增量 = 新测试 2 + 版本一致性 1 |
| passed | 544 | **547** | +3 | 与期望 547 吻合 ✓ |
| failed | 0 | **0** | 0 | 无新增失败 ✓ |
| skipped | 6 | **6** | 0 | 无新增 skip，仍为 S1–S6 ✓ |
| warnings | 775 | **775** | 0 | 量级与分布不变（site_refine 530 + symops 243 + 各 1） ✓ |
| 耗时 | 221.61s | **224.74s (0:03:44)** | +3.13s | 同量级；印证上一轮 221.61s 属正常档，481.53s 才是负载异常 |
| EXIT | 0 | **0** | — | ✓ |

**全量 pytest 原始摘要行（逐字）**：

```
[进度条 13%..100%，含 13% 附近 ss、39% 附近 sss、91% 附近 s]
============================== warnings summary ===============================
tests/test_site_refine.py: 530 warnings
tests/test_symops.py: 1 warning
  D:\XinRefinement\.venv\lib\site-packages\spglib\spg.py:514: DeprecationWarning: Set OLD_ERROR_HANDLING to false and catch the errors directly.
    _set_no_error(_throw)
tests/test_site_refine.py: 1 warning
tests/test_symops.py: 243 warnings
  D:\XinRefinement\.venv\lib\site-packages\spglib\spg.py:602: DeprecationWarning: Set OLD_ERROR_HANDLING to false and catch the errors directly.
    _set_no_error()
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
547 passed, 6 skipped, 775 warnings in 224.74s (0:03:44)
PYTEST_EXIT=0
```

起止（本机 `date`）：`2026-11-11 13:51:47 → 13:55:34`。

## 2. 判据 1：无新增失败 / 无新增 skip；6 个 skip 与 S1–S6 一致

小范围 `-v -rs`（6 个含 skip 的文件 + golden_b + 新 A11/版本测试 + esd_geometry，独立 basetemp）输出 `43 passed, 6 skipped in 8.51s, SUBSET_EXIT=0`。6 个 skip 逐条如下，与任务 #2 的 S1–S6 完全一致，无第 7 个源：

| # | nodeid | 原因（原文） |
|---|---|---|
| S1 | `test_cif_robust.py::test_raw_cod_with_esd_parses[1548811-...]` | `test_cif_robust.py:52: COD 原始文件缺失: ...1548811.cif` |
| S2 | `test_cif_robust.py::test_raw_cod_with_esd_parses[1548823-...]` | `test_cif_robust.py:52: COD 原始文件缺失: ...1548823.cif` |
| S3 | `test_joint_s1.py::test_s1_api_path_reproduces_golden_rwp` | `test_joint_s1.py:98: 需要本机 COD 档案与合成谱样例` |
| S4 | `test_joint_s1.py::test_s1_full_loop_matches_manual_import` | `test_joint_s1.py:125: 需要本机 COD 档案与合成谱样例` |
| S5 | `test_joint_s1.py::test_s1_manual_path_same_rwp` | `test_joint_s1.py:179: 需要本机 COD 档案与合成谱样例` |
| S6 | `test_xinm_import.py::test_roundtrip_with_real_xinmatch_exporter` | `test_xinm_import.py:252: XinMatch 不在 import 路径上` |

新增/改动测试在小范围均 `PASSED`：`test_cli_esd_report.py::test_esd_section_value_column_is_parameter_value`、`::test_esd_json_has_values_matching_labels`、`test_version_consistency.py::test_version_three_way_consistent`、`test_esd_geometry.py::test_esd_full_covariance_includes_linear_params`、`test_golden_b.py::test_golden_5050_bit_identical`。

**结论：判据 1 通过**。

## 3. 判据 2：golden 逐位

- 活体绊线：`tests/test_golden_b.py::test_golden_5050_bit_identical` 全量与 `-v` 单验均 `PASSED`。
- 只读脚本直连 `core.refine.nonlinear.refine`（`python -B` stdin，输入构造与 `test_golden_b.py:57-67` 逐字一致，未改 golden 文件）：

```
GOLDEN_RWP_REPR = 3.4074156640940005
BIT_IDENTICAL   = True
```

golden 数据文件 `tests/golden/method_b_roundtrip.json` 的 50/50 档 `rwp = 3.4074156640940005`，与复验值逐位相等。

**结论：判据 2 通过**。

## 4. 判据 3：A11 端到端独立验证（原始输出）

以真实精修链 `solve(RefineInputs(...)) → estimate_esd(...)` 复验（未采信工程师 76 passed 自报；`refine()` 返回 `RefineResult` 不含 `.config`，`estimate_esd` 需 `solve()` 的 `SolveResult`，故按 `tests/test_esd_geometry.py:30-46` 的正确构造）：

```
=== [judge3] A11 end-to-end (solve -> estimate_esd) ===
len(values)=9 len(labels)=9 n_params=9
values[global.zero] = 0.0299134974192351
res.params.zero     = 0.0299134974192351
EQ_zero_exact       = True
EQ_zero_approx1e-12 = True
scale_values_match_phases = True ( [(4, 0.05112761690915081), (5, 0.22437775429528617)] )
SECTION_global.zero = | global.zero | 0.0299135 | ±6.78e-05 |
  value_col='0.0299135'  esd_col='±6.78e-05'  DIFFERENT_SOURCE=True
real_NAN_esd_labels = [] count=0
JSON keys[:3] = ['labels', 'values', 'esd']
JSON len values/labels/esd = 9 9 9
JSON esd_None_count = 0
JSON values_None_count = 0
=== [judge3] negative check (hand-built EsdResult w/ NaN boundary) ===
  FAKE_ROW: | global.zero | 0.0123 | ±0.0004 |
  FAKE_ROW: | phase[A].micro.X | 0 | —（TCH 边界，无定义） |
  FAKE_ROW: | scale[0] | 0.015 | ±0.002 |
  FAKE_ROW: | bg[0] | 42 | ±0.7 |
  FAKE values[:2] = [0.0123, 0.0]  esd[:2] = [0.0004, None]
  FAKE len(values)==len(labels): True
```

逐点核对四条：

| 子项 | 证据 | 结论 |
|---|---|---|
| ① 文本「值」列 = 参数真值，与 e.s.d. 列不同源 | `| global.zero | 0.0299135 | ±6.78e-05 |`，`DIFFERENT_SOURCE=True`；`values[global.zero]` 与 `res.params.zero` 逐位相等 | 通过 |
| ② TCH 边界行值列照常、e.s.d. 列显示「—（TCH 边界，无定义）」 | 真实数据本批无边界 NaN（count=0），负向手工 `EsdResult`：`| phase[A].micro.X | 0 | —（TCH 边界，无定义） |`，值列 `0` 照常显示 | 通过 |
| ③ JSON 有 `values` 键、与 labels 等长、NaN→None | `JSON keys[:3]=['labels','values','esd']`，`9/9/9`；负向 `esd[:2]=[0.0004, None]`、`values[:2]=[0.0123, 0.0]` | 通过 |
| ④ `values[labels.index("global.zero")] == res.params.zero` | `EQ_zero_exact = True`（0.0299134974192351）；另 `scale[i]` 与 `res.phases.scale` 一致 | 通过 |

**结论：判据 3 通过**（含负向检查，确认值列不会被误贴成 e.s.d.，边界参数值列不被 NaN 污染）。

## 5. 判据 4：版本三处一致 / 无越界改写

| 位置 | 值 | 结论 |
|---|---|---|
| `xinrefinement/__init__.py:7` | `__version__ = "1.6.3"` | 唯一真相源 ✓ |
| `packaging/inno/xinrefinement.iss:14` | `#define AppVersion "1.6.3"`（位于 `#ifndef` 兜底块） | 与 package 一致 ✓ |
| `CHANGELOG.md:3` | `## v1.6.3（2026-11-11）：e.s.d. 报表值列修正 + 审计低风险修复` | 最新标题一致 ✓ |
| `pyproject.toml:30` | `version = {attr = "xinrefinement.__version__"}` | dynamic 自动取，未硬编码 ✓ |
| `CHANGELOG.md:35` | `## v1.6.2（2026-11-09 发布）` | 历史条目保留、未误改 ✓ |

Grep `1.6.3`（排除 `.venv`/`.git`）：产品/配置版本源仅上表前三个；其余命中为 `.workbuddy/memory/2026-11-11.md` 与 `docs/audit-20261111-a11-{changes,design}.md`（审计文档提及，非版本源，合理）。`test_version_consistency.py::test_version_three_way_consistent` `PASSED`。

**结论：判据 4 通过**。

## 6. 判据 5 / 判据 6：git 合规 + schema 冻结

**(判据 5) `git status --short` 全文（全量跑完后实测，10 行）**：

```
 M CHANGELOG.md
 M packaging/inno/xinrefinement.iss
 M tests/test_esd_geometry.py
 M tests/test_version_consistency.py
 M xinrefinement/__init__.py
 M xinrefinement/cli/refine.py
 M xinrefinement/core/refine/esd.py
?? docs/audit-20261111-a11-changes.md
?? docs/audit-20261111-a11-design.md
?? tests/test_cli_esd_report.py
```

- 7 个 ` M` + 3 个 `??` = **10 行**，与主理人描述一致 ✓
- `git rev-parse --short HEAD` = **`ef27be4`** ✓；暂存区 `git diff --cached --stat` 空 ✓；零新 commit/push ✓
- 本报告写入后 `git status` 将变为 **11 行**（多出 `?? docs/audit-20261111-qa-regression-v163.md`，本轮唯一新增落地物），属预期内，请主理人以此为准复核。

**(判据 6) schema 冻结**：

- `git diff --name-only` = `CHANGELOG.md`、`packaging/inno/xinrefinement.iss`、`tests/test_esd_geometry.py`、`tests/test_version_consistency.py`、`xinrefinement/__init__.py`、`xinrefinement/cli/refine.py`、`xinrefinement/core/refine/esd.py` —— **不含** `core/report.py`、**不含** `gui/project.py`（`.xinr` 的 `result/refine.json` 写出方）。
- `test_micro_initial_report.py` + `test_project_zip.py` 单跑 **`20 passed in 2.86s`，EXIT=0**：核心报告 schema 与 `.xinr` zip schema 行为未变。
- 结论：A11 仅影响 CLI 文本/JSON 报表层（`cli/refine.py`）+ `EsdResult` 数据载体，`core/report.py`（HTML/PNG/JSON 三件套）与 `.xinr` 工程文件 schema **冻结未动**。

**结论：判据 5、判据 6 均通过**。

## 7. 编号问题清单

**无。**

- 本轮全量 `0 failed`，无源码 Bug 需要路由给工程师，无测试写法问题需要 QA 自行修正。
- 未以「与本次改动无关」为由跳过任何失败——本轮不存在失败项。
- `test_joint_s1.py` 三例 skip（S3–S5）与 `real_NAN_esd_labels=[]` 均为环境/数据特性，非缺陷；已在下文与「下一步」登记。

## 8. 智能路由判定

- 全量首轮即全绿（collected 553 / 547 passed / 0 failed / 6 skipped / EXIT=0），6 条判据逐条通过 → **Send To: NoOne**，报告成功。
- 未进入第 2 轮；未修改任何产品代码或测试代码；除本报告外零写入。

## 9. 合规声明

- 只读 `D:/XinRefinement` 内文件；未访问工作目录之外的数据目录；未读取其它项目。
- 未改任何 `.py` / 测试 / 配置 / 既有文档 / golden 文件；未装包；未改 COD_ROOT；未放宽 / 删除任何断言。
- 全量、小范围、schema 冻结测试均使用 `-o addopts=""` 与**全新** `--basetemp`（系统临时目录，未复用历史目录）；golden 与 A11 端到端脚本经 `python -B - <<'PY'` 从 stdin 执行，不创建仓库内文件；未改写 `tests/golden/` 下任何文件。
- 未 `git add` / `commit` / `push`；HEAD 保持 `ef27be4`，暂存区空。
- 本报告为任务 #7 唯一写入文件。
