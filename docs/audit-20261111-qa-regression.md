# XinRefinement v1.6.2 修复后全量回归与 golden 复验报告（QA / 任务 #4）

| 项 | 值 |
|---|---|
| 实施对象 | `D:/XinRefinement`，git HEAD `e6ddef3` |
| 任务 | #4 修复后全量回归 + golden 逐位复验（对照任务 #2 修复前基线） |
| 环境 | `.venv/Scripts/python.exe`（Python 3.10.11 / pytest 9.2.0），同机同 venv；`-o addopts=""` + 全新 `--basetemp`（`C:/Users/ADMINI~1/AppData/Local/Temp/xinr_qa4_reg_hoyeay48`，**未复用**修复前基线目录 `xinr_baseline_20261111`） |
| 全量命令 | `cd /d/XinRefinement && "D:/XinRefinement/.venv/Scripts/python.exe" -m pytest -o addopts="" --basetemp=<全新系统临时目录> -q` |
| 全量原始摘要 | **`544 passed, 6 skipped, 775 warnings in 221.61s (0:03:41)`，`PYTEST_EXIT=0`** |
| 修复前基线 | `1 failed / 525 passed / 6 skipped / 775 warnings / 481.53s / EXIT=1`（主理人实测，任务 #2 已定性） |
| 最终判定 | **PASS**（无新增失败、无新增 skip、golden 逐位不变、工作树合规） |
| 合规 | 除本报告外零写入；未装包；未改 COD_ROOT；未放宽断言；未改产品代码；未改 golden 文件；未 `git add` / `commit` / `push` |
| 报告日期 | 2026-11-11 |

---

## 关键发现

1. **唯一失败项已转绿，全量全绿**：修复前唯一失败 `tests/test_v162_cancel.py::test_run_all_does_not_record_cancel_as_failure`（`assert records` 得 `[]`）经任务 #2 定性为测试墙钟时序脆弱，工程师按 QA 第 5 节方案改写为确定性计数谓词后，本轮全量 **0 failed / EXIT=0**。原 nodeid 仍保留、单独 `-v` 复验为 `PASSED`。
2. **对照基线「无新增失败、无新增 skip」成立**：`failed 1→0`、`skipped 6→6`（nodeid 与原因逐条与 S1–S6 一致，未冒出第 7 个 skip 源）、`warnings 775→775`（分布亦一致：site_refine 530 + symops 243 + 各 1 = 775，与任务 #2 的 spglib 2.7.0 定性吻合）。collected `532→550`（+18 = 改写用例净 +7 + 新验收文件 +11），passed `525→544`（+19 = collected 增量 18 + 原失败转绿 1），算术自洽。
3. **golden 逐位不变**：`tests/test_golden_b.py::test_golden_5050_bit_identical` 全量与单独复验均 `PASSED`；另用只读脚本直连 `core.refine.nonlinear.refine` 复验 `repr(res.rf.rwp) == '3.4074156640940005'`，`BIT_IDENTICAL = True`，与 golden 数据文件 `50/50` 档逐位一致。未改写任何 golden 文件。
4. **新增/改写用例边界独立验证通过**（未采信工程师 `173 passed` 自报）：六档取消时机 `[1,2,3,10,40,10**9]` 全 `PASSED`（含 `cancel_at=1` 首检查点与 `10**9` 等价不取消）；`.xinr` 逐位往返、旧 `.10g` 可读、harmonic 报告字段三项均 `PASSED`，且已读源码确认它们确实做了写盘 / 读旧格式 / 产出 `model/degree/coeffs`，非空断言。
5. **工作树合规**：`git status --short` 在写本报告前恰好 **13 行**（9 个 ` M` + 3 个 `??` 报告 + 1 个 `?? tests/test_audit_fixes_20261111.py`），HEAD 仍 `e6ddef3`，暂存区空，零新 commit。
6. **两项披露已如实写明**：工程师报告 `docs/audit-20261111-engineer-changes.md` 第 2 节（F03 opt-in）、第 3 节（F04 体积）均已单列披露，非笼统「零数值变化」。
7. **耗时差异如实记录但不作判据**：`481.53s → 221.61s`（约 -54%）。两次为不同时段、不同机器负载，耗时受 CPU 争用 / 磁盘与导入缓存影响显著，且 collected 反增 18 项，故**不将耗时缩短归因于本次改动**，也不作为验收判据；仅按主理人要求如实登记。

## 落地物

- 本报告：`docs/audit-20261111-qa-regression.md`（本轮唯一新增文件）。
- 全量 pytest 原始输出、golden 只读复验脚本输出、`-v -rs` 小范围边界验证输出、`git status` 全文，均记录于下文第 2–5 节。
- 本轮**未产生**任何 `.py` / 测试 / 配置 / 既有文档 / golden 文件改动。

## 下一步

1. 任务 #4 判定 **PASS**；无需路由给工程师修源码，也无需 QA 自行修测试代码。
2. 判据 6 标注项（不阻塞）：`tests/test_joint_s1.py` 三例本机仍 skip，F04 对路径 A/B Rwp 一致性的影响需在「全能力环境」（COD 档案 + XinMatch/gemmi 齐全）恢复后回归确认。
3. 任务 #2 第 10.6 节已登记的 A12 显示层加固建议（`_on_step_finished` 无条件 `tr()` 重建 + 补同前缀分支用例）与 A11 伪「值」列，均不在本轮 F01–F06 范围，建议单列排期，不影响本轮 PASS 判定。

---

## 1. 对照表（修复前 vs 修复后）

| 指标 | 修复前基线（任务 #2 / 主理人实测） | 修复后（任务 #4 本轮全量） | 变化 | 判据 |
|---|---|---|---|---|
| collected | 532 | **550** | +18 | 与工程师 collect-only 550 一致（本轮独立复验 `550 tests collected in 1.94s`） |
| passed | 525 | **544** | +19 | 期望 544 ✓ |
| failed | 1 | **0** | -1 | 唯一失败项转绿，无新增失败 ✓ |
| skipped | 6 | **6** | 0 | 无新增 skip ✓ |
| warnings | 775 | **775** | 0 | 量级与分布均不变 ✓ |
| 耗时 | 481.53s | **221.61s (0:03:41)** | -259.92s | 不作判据，见关键发现 7 |
| EXIT | 1 | **0** | — | ✓ |

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
544 passed, 6 skipped, 775 warnings in 221.61s (0:03:41)
PYTEST_EXIT=0
```

起止时间（本机 `date`）：`2026-11-11 09:32:19` → `2026-11-11 09:36:03`。

**passed 增量自洽核算**：`544 - 525 = 19 = (550-532) + 1`（收集数 +18，其中原 1 个 failed 转为 passed）。`skipped 6 + passed 544 = 550`，`failed 0`。与修复前 `525 + 6 + 1 = 532` 口径一致。

## 2. 判据 1：无新增失败 / 无新增 skip；6 个 skip 与 S1–S6 一致

小范围 `-v -rs` 复验（6 个含 skip 的文件，独立 basetemp）输出 `47 passed, 6 skipped in 8.20s, SUBSET_EXIT=0`。6 个 skip 的 nodeid 与原因逐条如下，与任务 #2 的 S1–S6 清单**完全一致**，无第 7 个 skip 源：

| # | nodeid | 原因（`SKIPPED` 摘要原文） | 归类 |
|---|---|---|---|
| S1 | `test_cif_robust.py::test_raw_cod_with_esd_parses[1548811-...]` | `test_cif_robust.py:52: COD 原始文件缺失: D:\Project\XRD\sync-COD\COD\1\54\88\1548811.cif` | 缺外部 COD 档案（硬编码工作目录外绝对路径） |
| S2 | `test_cif_robust.py::test_raw_cod_with_esd_parses[1548823-...]` | `test_cif_robust.py:52: COD 原始文件缺失: ...1548823.cif` | 同上 |
| S3 | `test_joint_s1.py::test_s1_api_path_reproduces_golden_rwp` | `test_joint_s1.py:98: 需要本机 COD 档案与合成谱样例` | 模块级 skipif（COD_ROOT 不存在） |
| S4 | `test_joint_s1.py::test_s1_full_loop_matches_manual_import` | `test_joint_s1.py:125: 需要本机 COD 档案与合成谱样例` | 同上 |
| S5 | `test_joint_s1.py::test_s1_manual_path_same_rwp` | `test_joint_s1.py:179: 需要本机 COD 档案与合成谱样例` | 同上 |
| S6 | `test_xinm_import.py::test_roundtrip_with_real_xinmatch_exporter` | `test_xinm_import.py:252: XinMatch 不在 import 路径上` | 缺可选依赖 xinmatch/gemmi |

**结论：判据 1 通过**。0 failed、6 skipped 且不增不减，nodeid/原因与基线一致。

## 3. 判据 2：golden 逐位

**(a) 活体绊线**：`tests/test_golden_b.py::test_golden_5050_bit_identical` 在全量（`544 passed` 内含）与 `-v` 小范围复验中均为 `PASSED`。

**(b) 只读脚本直连 `core.refine.nonlinear.refine`**（`python -B - <<'PY'`，从 stdin 执行，不创建仓库内文件、不改写 golden）：

```
GOLDEN_RWP_REPR = 3.4074156640940005
BIT_IDENTICAL   = True
ZERO_REPR       = 0.0299134974192351
U_V_W_REPR      = 0.021570399375435357 -0.0024143263148879023 0.020628537581553457
```

输入构造与 `tests/test_golden_b.py:57-67` 逐字一致（`v50_wide.xy` + 内置 anatase/rutile CIF，`RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=False, n_bg=3, max_iter=40, tmin=5.0, tmax=90.0)`）。golden 数据文件 `tests/golden/method_b_roundtrip.json` 的 50/50 档 `rwp = 3.4074156640940005`，与复验值逐位相等。

**结论：判据 2 通过**，golden 逐位不变。

## 4. 判据 3：新增/改写用例边界独立验证

`-v` 逐项输出（见第 2 节小范围复验），全部 `PASSED`，并已先读源码确认「确实做了对应动作」而非空断言：

| 用例 | 独立验证结果 | 源码级确认（确实做了边界动作） |
|---|---|---|
| `test_run_all_does_not_record_cancel_as_failure`（改写） | `PASSED` | `test_v162_cancel.py:121-131`：计数谓词 `calls[0] >= 3`；断言 `all(status != "failed")` + `all(status in ("done","skipped"))` + `(res is None)==(len(records)==0)`；无墙钟 |
| `test_cancel_at_any_checkpoint_keeps_contract[1]` | `PASSED` | `test_v162_cancel.py:135-151`：`@parametrize("cancel_at",[1,2,3,10,40,10**9])`，首检查点即取消 |
| `[2]` / `[3]` / `[10]` / `[40]` | 全部 `PASSED` | 同上，覆盖步内 / 步间 / 链尾 |
| `[1000000000]`（即 `10**9`） | `PASSED` | 等价「从不取消」，校验全链 8 步基线记录形态 |
| `test_cancel_preserves_completed_partial_results` | `PASSED` | `test_v162_cancel.py:153-175`：monkeypatch 包 `run_step` 计数已完成步数，`len(records)==2` / 全 `done` / `res is not None` |
| `test_xinr_pattern_roundtrip_is_bit_exact` | `PASSED` | `test_audit_fixes_20261111.py:176-191`：写 `demo.xy` → `save_project(embed=True)` 真实写盘 → `load_project` → `np.loadtxt` → `np.array_equal` 逐位断言（含 >10 位有效数字的强度值） |
| `test_old_10g_xinr_still_readable` | `PASSED` | `test_audit_fixes_20261111.py:194-208`：`zipfile.ZipFile(...,"w")` 手工构造含 `%.10g` CSV 的旧 `.xinr` → `load_project` 读回 → `pytest.approx(rel=1e-9)` |
| `test_to_report_harmonic_fields_present` | `PASSED` | `test_audit_fixes_20261111.py:222-235`：CLI 带 `--texture-model harmonic --texture-degree 4` 真实跑报告 → 断言 `model=="harmonic"` / `degree==4` / `len(coeffs)>0` 且 `axis`、`grid` 保留 |
| 其余 F01–F06 验收（共 11 项） | 全部 `PASSED` | `test_audit_fixes_20261111.py` 全文件单跑独立通过 |

**结论：判据 3 通过**。六档（含 `1` 与 `10**9`）、写盘/读旧格式、harmonic 字段三项边界均已独立验证。

## 5. 判据 4：git status 全文 / HEAD / 暂存区

写本报告**前**实测 `git status --short`（恰好 13 行）：

```
 M tests/test_project_zip.py
 M tests/test_v162_cancel.py
 M xinrefinement/api.py
 M xinrefinement/cli/refine.py
 M xinrefinement/core/refine/cell.py
 M xinrefinement/core/refine/nonlinear.py
 M xinrefinement/core/refine/recipe.py
 M xinrefinement/gui/main_window.py
 M xinrefinement/gui/project.py
?? docs/audit-20261111-architecture.md
?? docs/audit-20261111-engineer-changes.md
?? docs/audit-20261111-qa-baseline.md
?? tests/test_audit_fixes_20261111.py
```

- `git status --short | wc -l` = **13**（9 个 ` M` + 3 个 `??` 报告 + 1 个 `?? tests/test_audit_fixes_20261111.py`）✓
- `git rev-parse --short HEAD` = **`e6ddef3`** ✓；`git log -1` 仍为原始提交「更新文档：1.6.2 发布说明改记为提交后构建的资产哈希…」，零新 commit ✓
- `git diff --cached --stat` 为空 → **暂存区空** ✓
- `git diff --stat` = `9 files changed, 80 insertions(+), 18 deletions(-)`，与工程师交付一致 ✓
- 全量跑完后再次复核，状态仍为上述 13 行（`.gitignore` 已含 `__pycache__/`、`.pytest_cache/`，pytest 未污染工作树）✓
- 本报告写入后，`git status --short` 将变为 **14 行**（多出 `?? docs/audit-20261111-qa-regression.md` 这一本轮自身落地物）；这是预期内的唯一新增文件，如主理人复核请以此为准。

**结论：判据 4 通过**。

## 6. 判据 5：两项披露复核（工程师报告）

`docs/audit-20261111-engineer-changes.md`：

| 披露项 | 位置 | 原文要点 | 结论 |
|---|---|---|---|
| F03 opt-in 行为变化 | `:18`（关键发现 2）、`:48`（P4 行）、`:57-64`（第 2 节专表） | `refine_po=False` 默认逐位不变；`refine_po=True + api.report()` opt-in 路径「**结果会变**，属修正入口不一致的有意行为变更，不是回归；建议在发布说明明确」 | **如实写明** ✓ |
| F04 体积 + 旧 `.10g` 兼容 | `:18`、`:66-77`（第 3 节专表）、`:21`、`:50`(P6)、`:76` | 完整 `.xinr` `19174 B → 22395 B`（**+16.8%**）、单 `pattern.csv` `41959 B → 89383 B`（**+113.0%**）；读取侧 `float()`/`csv.reader` 未改，旧 `.10g` **向后兼容**（`test_old_10g_xinr_still_readable` 守护） | **如实写明** ✓ |

**结论：判据 5 通过**，两项均非笼统「零数值变化」，已单列披露。

## 7. 判据 6：标注项（不阻塞）

- `tests/test_joint_s1.py` 三例（`test_s1_api_path_reproduces_golden_rwp` / `test_s1_full_loop_matches_manual_import` / `test_s1_manual_path_same_rwp`）本机仍 `SKIPPED`，原因「需要本机 COD 档案与合成谱样例」，与修复前一致。
- F04 将 `.xinm` 中转谱写出精度由 `%.10g` 改为 `%.17g`；`test_joint_s1.py` 路径 A/B 的 `rel=1e-9` Rwp 一致性断言在 payload ≤10 位有效数字时不受影响，但**该 3 例在本机被 skip，未经本轮实测**。需在「全能力环境」（COD 档案 + XinMatch/gemmi 齐全）恢复后回归确认。QA 任务 #2 第 9.3 节已判 F04 风险低、非阻塞。
- 此项为**标注**，不计入失败、不影响本轮 PASS。

## 8. 编号问题清单

**无。**

- 本轮全量 `0 failed`，无任何源码 Bug 需要路由给工程师，无任何测试代码写法问题需要 QA 自行修正。
- 未以「与本次改动无关」为由跳过任何失败——本轮不存在失败项。
- 上述判据 6 及任务 #2 第 10 节登记的 A11 / A12 / Q17 均为**观察与后续排期项**，非本轮回归发现的问题，不改写本清单结论。

## 9. 智能路由判定

- 全量首轮即全绿（0 failed / EXIT=0），六条判据逐条通过 → **Send To: NoOne**，报告成功。
- 未进入第 2 轮；未修改任何产品代码或测试代码；除本报告外零写入。

## 10. 合规声明

- 只读 `D:/XinRefinement` 内文件；未访问工作目录之外的数据目录；未读取其它项目。
- 未改任何 `.py` / 测试 / 配置 / 既有文档 / golden 文件；未装包；未改 COD_ROOT；未放宽 / 删除任何断言。
- 全量、小范围、`--collect-only` 均使用 `-o addopts=""` 与**全新** `--basetemp`（系统临时目录，未复用 `xinr_baseline_20261111`）；golden 复验经 `python -B - <<'PY'` 从 stdin 执行，不创建仓库内文件；未改写 `tests/golden/` 下任何文件。
- 未 `git add` / `commit` / `push`；HEAD 保持 `e6ddef3`，暂存区空。
- 本报告为任务 #4 唯一写入文件。
