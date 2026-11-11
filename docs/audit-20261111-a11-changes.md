# A11 修复 + 1.6.3 版本升级 实施报告（工程师视角）

| 项 | 值 |
|---|---|
| 实施对象 | `D:/XinRefinement`，本轮起点 HEAD `ef27be4`（上一轮 F01–F06 已由主理人提交） |
| 任务 | #6 A11（e.s.d. 报表「值」列）+ 版本号 1.6.2 → 1.6.3 |
| 依据 | `docs/audit-20261111-a11-design.md`（架构师，第 7 节改动清单 + 第 4.4 节 CHANGELOG 结构 + 第 5 节验收用例） |
| 环境 | `.venv/Scripts/python.exe`（Python 3.10.11），`-o addopts=""` + 全新 `--basetemp` |
| golden 红线 | CLI Rwp = **3.4074156640940005**，实测逐位一致 |
| 范围确认 | 只升版本号 + CHANGELOG + 同步 iss；**不构建安装包、不发 Release、不 commit/push**（提交由主理人统一处理） |
| 报告日期 | 2026-11-11 |

---

## 关键发现

1. **A11 端到端修复生效且数值零风险**：`--esd` 端到端实测，`esd` 段键序为 `['labels','values','esd','scale_esd']`，`len(labels)==len(values)==len(esd)==9`；`global.zero` 的「值」列 = `0.029913`、「e.s.d.」列 = `6.8e-05`（**不再是同一个数**），`values[4]/[5]` = `0.051128 / 0.224378` 恰为两相 scale（与 solve 参数一致）。golden `repr(res.rf.rwp) == '3.4074156640940005'`、`BIT_IDENTICAL = True`。
2. **`values` 只做「复制已算好的值」，不进任何数值路径**：`values = concat(x_final, c)`，`x_final`（`esd.py:112`）与 `c`（`esd.py:137`）本就为构造 Jacobian 算好；`d/cov/corr/scale_esd/weight_esd` 的计算一行未动。`assert len(values)==n_total` 把未来任何错位变成显式失败。
3. **`EsdResult` 加必填字段安全**：全仓 `EsdResult(` 唯一构造点 `esd.py:229`，全部关键字参数，无位置调用；`dataclasses.replace` 自动拷贝新字段；`EsdResult` 不落盘（`.xinr` 存 `solve_result_dict` 的 dict），无跨版本序列化回退风险。子集 `test_esd_geometry.py` 全绿佐证。
4. **版本三处一致已由测试闭环**：`xinrefinement.__version__`=`1.6.3`、iss `#define AppVersion "1.6.3"`、`CHANGELOG.md:3` `## v1.6.3` 三者相等；新增 `test_version_three_way_consistent` 通过，既有 `test_iss_*` 三条亦通过。
5. **`core/report.py` 确认无需改**：其 esd 段（`_log_dict:70-74`、`_html:111-117`）本就没有「值 | e.s.d.」双列表（有缺陷的是 CLI `_esd_section`），故 HTML/`.xinr` 日志不涉及 A11，不动以冻结 `.xinr` schema。

## 落地物

- 源码/配置 **8 处**（6 文件）：`esd.py`（字段 + 填值 + 构造）、`cli/refine.py`（文本值列 + JSON 抽函数 + 调用）、`__init__.py`、`xinrefinement.iss`、`CHANGELOG.md`。
- 测试 **3 文件**：新建 `tests/test_cli_esd_report.py`（2 项）；`tests/test_version_consistency.py` 追加 `test_version_three_way_consistent`；`tests/test_esd_geometry.py` 追加 values 对齐断言（不改用例数）。
- 本报告：`docs/audit-20261111-a11-changes.md`。
- 自检：指定 9 文件子集 **76 passed / 0 failed / 0 skipped，40.67 s，EXIT=0**；golden 逐位不变；全仓 `--collect-only` **553**（上轮 550 + 本轮净增 3）。
- 全局一致性审查：**IS_PASS: YES**（见第 5 节）。

## 下一步

1. 主理人逐句审阅下方第 4 节 `CHANGELOG v1.6.3` 全文，随后统一提交（零 add/commit/push 由我保证）。
2. **更新 #4 的 collected 期望**：上一轮我给的是 550，本轮测试净增 3（`test_cli_esd_report.py` 2 + `test_version_three_way_consistent` 1），故全仓现为 **553**；#4 若尚未跑请按 553 校准（`test_esd_geometry.py` 只加断言、不改用例数）。
3. 本轮为旁路/报表/元数据改动，回退方式 1:1 反转（见设计 §6），不影响 golden 与引擎。

---

## 1. 源码/配置改动（8 处，逐条精确到行）

| # | 文件:行号 | 改法 | 影响 | 是否改数值 |
|---|---|---|---|---|
| 1 | `core/refine/esd.py:54-55` | `EsdResult` 在 `labels` 后、`esd` 前新增 `values: tuple[float, ...]`（注释「与 labels 逐项对齐的参数真值 θ=(x,c)」） | 数据结构携带参数真值 | 否（仅字段声明） |
| 2 | `core/refine/esd.py:201-206` | `labels` 后新增 `values = tuple(float(v) for v in np.concatenate([x_final, c]))` + `assert len(values) == n_total, (len(values), n_total)` | 填值来源 = 已算好的 `x_final`(p) + `c`(q)，与 labels 同序同长；错位即显式失败 | 否（只复制，不参与 d/cov/corr） |
| 3 | `core/refine/esd.py:235-239` | 构造处补 `values=values`（`labels, values, esd = ...` 三元组邻接） | 实例带真值 | 否 |
| 4 | `cli/refine.py:437` | `zip(esd.labels, esd.esd, esd.esd)` → `zip(esd.labels, esd.values, esd.esd)` | 文本「值」列取参数真值 | 否（仅显示） |
| 5 | `cli/refine.py:438-440` | 值列 NaN 防御：`vv = "—" if not math.isfinite(v) else f"{v:.6g}"`，行模板 `f"| {lab} | {vv} | {ev} |"`；表头/分隔行/`ev` 的 TCH 判据（作用在 `e` 上）不动 | 值列非有限值显示破折号，避免 `nan` 字面污染 | 否 |
| 6 | `cli/refine.py:449-461` + `:498-499` | 抽 `_esd_json_dict(esd)`（键序 `labels, values, esd, …`，`values` 用 `_esd_val(v)` 默认 round6、NaN→None）；`_run` 改 `report["esd"] = _esd_json_dict(esd)` | JSON esd 段新增 `values`，其余键逐键与原内联 dict 等价 | 否（行为等价重构 + 新键） |
| 7 | `xinrefinement/__init__.py:7` | `__version__ = "1.6.2"` → `"1.6.3"` | 唯一真相源 | 否 |
| 8 | `packaging/inno/xinrefinement.iss:14` | `#define AppVersion "1.6.2"` → `"1.6.3"`（`#ifndef` 内兜底） | ISCC 默认版本同步 | 否 |
| 9 | `CHANGELOG.md:1` 后 | 新增 `## v1.6.3（2026-11-11）…` 条目（结构见第 4 节） | 记录 A11 + F01–F06 + 去脆弱化 + 基线档位；v1.6.2 及更早条目未动 | 否 |

> 行号为本轮改动后文件位置。`assert` 用 `n_total`（`esd.py:176` 定义，早于 `values`），无前向引用问题。

## 2. 测试改动（3 文件）

| # | 文件 | 改法 | 覆盖 |
|---|---|---|---|
| 10 | `tests/test_cli_esd_report.py`（新建） | `_mk_esd()` 手搓 4 标签（含 `esd=nan` 的 TCH 边界列）→ ① `test_esd_section_value_column_is_parameter_value` 解析文本表格：值列==真值、e.s.d. 列==`esd.esd`、边界行值列显示真值 `0`、边界行 e.s.d. 列显示「—（TCH 边界，无定义）」、值列≠e.s.d.；② `test_esd_json_has_values_matching_labels`：`list(d)[:3]==["labels","values","esd"]`、三者等长、NaN→None、值列 round6 | A11 三处序列化的值列契约 |
| 11 | `tests/test_version_consistency.py` | 追加 `test_version_three_way_consistent`：`__version__ == iss AppVersion == CHANGELOG 最新 vX.Y.Z`（复用文件顶部 `REPO`/`_ISS`；`re`、`xinrefinement` 已模块级导入） | 版本三处一致 |
| 12 | `tests/test_esd_geometry.py` | 在 `test_esd_full_covariance_includes_linear_params` 末尾追加：`len(values)==len(labels)==n_params`；`values[idx["global.zero"]] == res.params.zero`（abs 1e-12）；`scale[i]` 值 == 对应 `res.phases[i].scale`（rel 1e-6）。**未改任何既有断言** | values/labels 对齐 + 防 scale/bg/非线性三类贴错位 |

## 3. 自检结果

| 项目 | 命令 / 口径 | 结果 |
|---|---|---|
| 指定 9 文件子集 | `-o addopts="" --basetemp=<系统临时新目录> -q --tb=short` + `test_cli_esd_report.py`、`test_version_consistency.py`、`test_esd_geometry.py`、`test_cli.py`、`test_golden_b.py`、`test_audit_fixes_20261111.py`、`test_micro_initial_report.py`、`test_p2_p46.py`、`test_texture.py` | **76 passed，0 failed，0 skipped，40.67 s，EXIT=0** |
| golden 活体绊线 | 子集内 `test_golden_b.py::test_golden_5050_bit_identical` | **通过** |
| golden 逐位复验 | 只读脚本直连 `core.refine.nonlinear.refine`（不调 `estimate_esd`） | `GOLDEN_RWP_REPR = 3.4074156640940005`；`BIT_IDENTICAL = True` |
| A11 端到端 | `python -m ...refine --esd -o r.json`（v50 双相） | `CLI_EXIT=0`；`ESD_KEYS=['labels','values','esd','scale_esd']`；`LEN=9/9/9`；`global.zero value/esd=0.029913/6.8e-05`；`VALUES_NE_ESD=True` |
| 全仓 collected | `--collect-only -q` | **553 tests collected**（上轮 550 + 净增 3） |
| 版本分布 | Grep `1\.6\.3` 全仓 | 仅 `__init__.py:7`、`CHANGELOG.md:3`、`iss:14` 三处（+架构师设计文档描述）；无多余/遗漏 |

## 4. CHANGELOG v1.6.3 条目全文（供逐句审）

```markdown
## v1.6.3（2026-11-11）：e.s.d. 报表值列修正 + 审计低风险修复

主题：修复 A11（e.s.d. 文本/JSON 报表的「值」列误填 e.s.d.、参数真值缺失），
并收纳上一轮全局代码审计的 6 项低风险修复。**引擎与数值路径零改动**
（golden CLI Rwp 3.4074156640940005 逐位不变）。

### 修复 A11：e.s.d. 报表「值」列
- 根因：`cli/refine.py` 的 e.s.d. 表格用 `zip(esd.labels, esd.esd, esd.esd)`，
  「值」列与「e.s.d.」列同源；`EsdResult` 未保存参数真值。
- 修法：`EsdResult` 新增 `values`（`estimate_esd` 以 `concat(x_final, c)` 填好，
  与 `labels` 严格同序）；文本报告改 `zip(labels, values, esd)`，JSON esd 段新增
  `values`。e.s.d./协方差/相关性/scale/含量 e.s.d. 计算路径一律不动。
- TCH 边界（X/Y=0）参数的 e.s.d. 仍记 NaN → 文本显示「—（TCH 边界，无定义）」，
  值列照常显示真实值。

### 修复（上一轮全局审计 F01–F06）
- F01：`name_mineral` 在 `structure_with_cell` / xyz 步重建时丢失 → 显示名退化（Quartz→SiO2）。
- F02：legacy `_unpack` 重建 `ProfileParams` 漏搬运 `size_strain`。
- F03：`api.report()` 的 `_solve_raw` 漏 `refine_po`，与 `api.refine()` 不一致。
- F04：`.xinr`/`.xinm` 谱图序列化 `10g→17g`，保存/重开逐位一致。
- F05：CLI `-o` 父目录缺失时自动建目录；`to_report` 织构补 `model/degree/coeffs`。
- F06：步骤按钮语言切换后仍显示中文 title → 改用 `tr(f'step.{key}')`。

### 测试
- 取消连跑测试去脆弱化：`test_run_all_does_not_record_cancel_as_failure` 的取消谓词
  由「绝对墙钟 `> 0.15s`」改为「残差检查点调用计数」，消除慢机/重负载下的时序假失败；
  断言回归真正的产品契约（取消不记成 failed），不再附加「至少完成一步」这一
  `run_all` 从未承诺的前置条件。

### 说明
- 基线档位：文档权威值 532 passed / 0 skipped 需「本机 COD 档案 + XinMatch/gemmi 齐全」；
  缺这些外部依赖的仓库自足档为 1 failed / 525 passed / 6 skipped，golden 逐位不变
  （详见 `docs/audit-20261111-architecture.md` 第 2 节）。
```

> 与设计 §4.4 的一处刻意差异：**删去了「本轮仅升版本号…不构建安装包、不发 Release」一句**，以严格满足主理人「CHANGELOG 不得写任何构建/发布内容」的要求——本轮未发版，条目只记录变更本身。

## 5. 全局一致性审查（IS_PASS: YES）

| 检查项 | 结论 |
|---|---|
| values 与 labels 对齐 | 强一致。`values=concat(x_final,c)`，`assert len(values)==n_total`；端到端 9==9==9；`values[global.zero]==res.params.zero`（abs 1e-12）、`values[scale[i]]≈res.phases[i].scale`（rel 1e-6）由 `test_esd_geometry.py` 守护 |
| 三处序列化一致 | 文本 `_esd_section`、JSON `_esd_json_dict` 均按 `labels→values→esd` 同序；`core/report.py` 无「值列」缺陷、本轮不改（冻结 `.xinr` schema）。`test_cli_esd_report.py` 两用例分别守护文本/JSON |
| 版本三处一致 | `__version__`==iss `#define`==CHANGELOG 最新标题，`test_version_three_way_consistent` + 既有 `test_iss_*` 全部通过 |
| CHANGELOG 无虚构内容 | 条目内容均与本轮真实改动/上一轮已提交修复一一对应；无构建/发布描述；v1.6.2 及更早条目未改 |
| 无遗漏 1.6.2 / 无多余 1.6.3 | Grep `1.6.3` 仅三处产品/配置；历史代码注释（`# v1.6.2：`）、`docs/RELEASE_NOTES_v1.6.2.md`、`docs/audit-*`、`CHANGELOG` 旧条目按设计保留未动；`pyproject.toml` 为 `dynamic` 自动取版本、未改 |

**IS_PASS: YES**

## 6. 需披露 / 已知边界

- **A11 语义变化（预期）**：CLI e.s.d. 文本/JSON 的「值」列由「误填的 e.s.d.」变为「参数真值」；这是缺陷修复，对既有机读 JSON 消费者是**新增 `values` 键**（向后兼容，未删改既有键）。
- **TCH 边界**：X/Y 恰为 0 的参数 `esd=NaN`，文本「值」列照常显示真实值（0），「e.s.d.」列显示「—（TCH 边界，无定义）」；JSON 侧 `values` 正常 round6、`esd` 为 `null`。
- **预存边界（非本轮引入）**：`bg_mode="manual"` 且 `n_bg>1` 时 `estimate_esd` 本就维度不符无法运行（设计 §1.3）；本轮只在可正常出 esd 的模式（cheb/tent/interp）保证 `len(values)==n_total`，`assert` 会把任何越界错位变显式失败。
- **`core/report.py` / `.xinr` 未改**：`result/refine.json` 的 esd 段 schema 不变；本轮不向 `.xinr` 携带参数真值（若未来需要另立任务）。
- **版本升级不打包**：`tools/build_binaries.py`、`pyproject.toml` 未改（前者构建期读 `__version__`，后者 `dynamic`）；本轮不构建安装包、不发 Release。

## 7. `git status --short`（写本报告后实测预期）

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

共 10 行：7 个已跟踪修改 + 本变更报告 + 架构师设计文档（上游产出，非我所建）+ 新验收测试。无暂存项、零 add/commit/push。`git diff --stat`（7 个已跟踪文件）：86 insertions(+), 18 deletions(-)。

## 8. 合规声明

- 未改任何数值计算路径（`d/cov/corr/scale_esd/weight_esd` 与引擎一行未动）；golden 逐位不变。
- 未装包、未改 COD_ROOT、未放宽/删除任何既有断言、未改 `run_all` 取消语义。
- 未 `git add`/`commit`/`push`；未改 `core/report.py`、`linear.py`、`nonlinear.py`、`solve.py`、`gui/*`、`pyproject.toml`、`tools/build_binaries.py`；未改任何 `1.6.2` 历史注释与 `docs/RELEASE_NOTES_v1.6.2.md`、`docs/audit-*.md`。
- 所有 pytest 均 `-o addopts=""` + 全新系统临时 `--basetemp`；诊断脚本经 stdin `python -B` 执行，未改写 `tests/golden/`。
