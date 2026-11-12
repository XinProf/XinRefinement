# v1.6.4 独立验收报告（审计整改第三批）

- 验收人：验得明（测试验证工程师，独立于开发）
- 被验单元：U-001/A07、U-002/A08、U-003/B07、U-004/B02、U-005（records 累加）
- 结论：**可交付（PASS）**，无必须修项
- 验收方式：**不采信开发自测结论**，自建 37 条 QA 用例 + 「HEAD 副本 vs 当前」双跑对拍 + 金标准逐位核对 + 全量回归
- 声明：本报告作者未修改任何生产代码、未 `commit`/`push`/`stash`；全部临时脚本位于 `.pytest_tmp_qa164/qa/`（已被 `.gitignore` 的 `.pytest_tmp*/` 覆盖）

## 一、被验快照

| 文件 | sha1(前 12) | 说明 |
|---|---|---|
| `xinrefinement/core/patterns.py` | `d2c5746ff7b7` | U-003 主体（含收口版注释） |
| `xinrefinement/core/vendor/text_formats.py` | `f7d9d898d234` | U-003 主体 |
| `xinrefinement/core/refine/recipe.py` | `aa8ac9a02cff` | U-005 |
| `xinrefinement/gui/project.py` | `5c0d326ccbb0` | U-001 + U-002 |
| `xinrefinement/gui/main_window.py` | `a6f75b0c0fea` | U-002 状态栏 + U-004 `_esd_for` |
| `xinrefinement/__init__.py` | 版本 `1.6.3 → 1.6.4` | 版本位 |
| `tests/conftest.py` | `77473e43fc07` | 新增 autouse `_isolate_project_sessions` |
| `tests/data/pattern_meta_golden.json` | `88804ab9197e` | U-003 meta 快照（经核实为真·改前快照） |

## 二、验收结论表

| 单元 | 结论 | 实测证据（可复现） |
|---|---|---|
| **U-001 / A07** 解压会话目录有界回收 | PASS | 自建 15 条用例全绿。HEAD 副本：无 `_prune_sessions`、连开 12 次 → 真实 TEMP 堆 12 个目录；当前版同样 12 次 → **恰好 8 个**（`_SESSION_KEEP`）。keep 数量门槛 12→8、超龄（40 天）必删、总量上限（5×1MB/限 2.5MB → 留最新 2，最旧先删）、`protect` 唯一绝对保留（最旧+超总量也不删）、`rmtree` 抛 `OSError` 时 `_drop` 兜住且 `load_project` 不受影响、`iterdir` 抛 `OSError` 时返回 `[]`、同一 `.xinr` 连开两次命中同一目录且 `pattern.xy` 恒 1 份 |
| **U-002 / A08** 内嵌结果损坏告警 | PASS | 自建 10 条用例全绿。坏 JSON `{broken` 与非 UTF-8 `\xff\xfe\x00bad` 两份 `.xinr`：`result_full is None` 且 `warnings` 含 `refine.json`；正常 `.xinr` / 旧 `.xrp`：`warnings == []`（旧格式已带该键）。HEAD 对照：`warnings` 键不存在（静默）。Qt offscreen 实测状态栏：`…bad.xinr \| 工程内嵌精修结果（result/refine.json）无法解析，已忽略；结果区可能不完整` |
| **U-003 / B07** legacy 文本单次读盘 | PASS | 三入口（`read_bytes`/`read_text`/`open`）逐路径计数，**HEAD → 当前**：`.xy 2→1`、`.dat(pd) 1→1`、Jade `.txt 4→1`、岛津 `.txt 5→1`，四类均**恰好 1 次全量读盘、0 次额外 4096B 头读**。契约不变由「HEAD 副本 vs 当前」双跑证明：4 类样本 `Pattern.meta` 逐键逐值相等、`two_theta/intensity` sha1 逐位相等；另 9 份合成语料（gsas / fp_dat / xye / chi / xrdml-in-txt / csv / jade / 岛津 / pd）detect 结果与 meta、数组、异常文案**完全一致**；GBK 编码 `.dat` 亦一致 |
| **U-004 / B02** e.s.d. 一次复用 | PASS | 自建 7 条用例全绿。真实链路（`_fill_results` + `project_state()` + `_esd_for`）`estimate_esd` **1 次**（HEAD 同场景 3 次）；新 res → 2 次、重复取 → 仍 2 次；物相 cell 改动 → 失效；`new_project()` 清缓存后重算；异常路径两请求**只抛 1 次**、均返 `None`、面板无 e.s.d./「Rwp 下降」行、`project_state()` 仍成功；数值 `np.array_equal` 全等且逐元素 `==` |
| **U-005** records 不累加 | PASS | 自建 5 条用例全绿。连跑两次 → `len(records)=8 == len(DEFAULT_STEPS)` 且 key 序列一致（HEAD 16 条）；连跑 3 次恒 8；**连续 `run_step` 仍累加**（单步语义未破坏）；手工单步后 `run_all` 回到 8；`state.rollback(1)` 截到 2 条、`current==2`、越界返 None |
| **金标准（红线）** | PASS | 直接 `refine()` 实测 `res.rf.rwp = 3.4074156640940005`，与任务卡字面量 `==` True、`diff = 0.0`；`zero/U/V/W` 与 golden 文件逐位 `==` |

## 三、回归记录

| 项目 | 命令基线 | 结果 |
|---|---|---|
| 全量（收口前快照，含 conftest 隔离） | `pytest --basetemp %TEMP%/qa164_run7 -o addopts=""` | **579 collected / 579 passed / 0 failed / 0 error / 0 skipped，344.09s** |
| 关键模块定向（收口版快照，含 1.6.4 版本位） | 见下 | **73 passed / 28.79s** |
| `tests/test_project_sessions.py` 单跑 | `--basetemp %TEMP%/xinr_qa_sess_confirm` | **6 passed / 0.14s**（与主理人 3 连跑 6 passed 一致） |
| QA 自建 37 条（收口版快照） | `pytest .pytest_tmp_qa164/qa/test_u00*.py` | **37 passed / 34.48s** |

定向 73 条明细：`test_version_consistency 4`、`test_variant_registration 10`、`test_project_zip 10`、`test_i18n_project 11`、`test_project_sessions 6`、`test_patterns_single_read 8`、`test_v164_esd_cache 7`、`test_recipe 10`、`test_golden_b 1`、`test_cli 4`、`test_cli_esd_report 2`。

> 基线说明：改造前 553 collected / 553 passed；本批新增 24 条 → 577；收口版再各加 1 条（`test_xrdml_fromstring_equals_parse`、`test_new_project_clears_esd_cache`）→ 579。

## 四、缺陷清单

### 4.1 已修（v1.6.4 内，收口版代码已闭环）

| 编号 | 原问题 | 收口版状态 | 复核结论 |
|---|---|---|---|
| QA-01 | `_prune_sessions` docstring 写「所有 OSError 一律吞掉」，实现依赖 `shutil.rmtree(ignore_errors=True)`，rmtree 自身抛出会外泄 | `_drop` 恢复 `try/except OSError: pass`，docstring 成真 | **已修**，QA 用例改为正向锁定：替身「无论 `ignore_errors` 都真抛」时 `len(removed)==2`、`attempted==removed`、目录未删也不抛、`load_project` 正常 |
| QA-02 | 「keep 保底」注释与实现不符（超龄优先于数量门槛） | docstring 明确「keep 非硬保底、protect 是唯一绝对保留、超龄照样删」 | **已修**（本报告已从风险项移出） |
| QA-01b | `.dat` 之外也全量解码 `full_text` 属多余开销 | `full_text` 仅 `.dat` 生成，注释改为严格表述（`None` 时 `detect_format` 才自行读盘；非 `.dat` 不进该分支） | **已修**；实测 `.xy` 仍 1 次读盘、无性能回退 |

### 4.2 遗留（非本批次返修项，建议入 v1.7 backlog）

| 编号 | 严重度 | 问题 | 建议 |
|---|---|---|---|
| QA-03（我方编号）／对应「mtime 2s 粒度」 | 🟡 | 会话目录命名 `{stem}_{int(mtime)}`：不同目录下**同名工程 + 同一秒 mtime** 会共用同一会话目录（实测两工程命中同一 `demo_*`） | `{stem}_{mtime}_{abspath 短哈希}` |
| QA-04（我方编号） | 🟢 | manifest 声明 `result_full` 但 zip 内**缺该成员**时仍静默 `None`，无告警 | 与「损坏」同源补一条「内嵌结果缺失」告警 |
| QA-05（我方编号） | 🟢 | 合法 JSON 但非对象（如 `[1,2,3]`）→ `apply_project` 抛 `AttributeError`（`_restore_result_panel` 首行 `full.get`），HEAD 同源、非本批回归 | `if not isinstance(full, dict): full = {}` + 告警 |
| QA-06（我方编号） | 🟢 | `_esd_cache` 键含 `id(res)`/`id(self._phases)`；`tuple(getattr(p,"cell",()) or ())` 依赖 `cell` 恒为 tuple（实测恒为 tuple） | 若 cell 改 ndarray 会因布尔歧义抛错，建议 `tuple(np.ravel(cell))` |

## 五、环境性说明（避免把环境误报当缺陷）

**「504 passed / 75 errors」= 环境性误报（sandbox artifact），非缺陷、非 flaky。**
- 触发条件：`--basetemp` 落在**仓库工作区内**（`D:\XinRefinement\.pytest_tmp_*`），pytest 的 `tmp_path` 按编号复用/清理子目录，撞上本机沙箱 `sitecustomize.py` 的「每 turn 批量删除 > 50 次需人工确认」保护，在 **fixture setup** 阶段抛 `SystemExit(1)`。
- 指纹：栈帧全在 `...\shim\sitecustomize.py`（`_safe_path_unlink → _try_trash → _check_bulk_delete_guard → _exit_bulk_guard_control`），stderr 含 `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":50,"threshold":50,...}`；且 `passed + errors == collected`（504+75=579），失败从固定点位起连续出现。
- 规避：**basetemp 必须放在 `%TEMP%` 下**（shim 对 OS 临时目录直接放行）；仓库内只保留 `.pytest_tmp*/` 这类被 gitignore 的脚本目录，不作为 basetemp。
- 复核：受影响模块单独跑 61/61 全绿；basetemp 改到 `%TEMP%` 后全量恢复 579/579。

## 六、测试卫生

`tests/conftest.py` 新增的 autouse `_isolate_project_sessions` 把会话根重定向到 `tmp_path`：全套 579 用例跑完后，真实 `%TEMP%/xinrefinement_projects` 目录数 **0**（改造前实测残留 8 个）。该 fixture 有效，建议保留。

## 七、总判定

**可交付（PASS）**：5 张卡全部通过独立验证；金标准 Rwp `3.4074156640940005` 逐位未漂；全量 579/579/0 skip；收口版关键模块 73/73 + QA 自建 37/37。
无必须修项；QA-01/QA-02/QA-01b 已在本批次闭环，QA-03~QA-06 建议入 v1.7 backlog。
