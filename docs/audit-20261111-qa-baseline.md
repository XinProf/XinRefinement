# XinRefinement v1.6.2 全量回归基线失败/跳过独立复现与定性报告（QA 视角）

| 项 | 值 |
|---|---|
| 审视对象 | `D:/XinRefinement`，git HEAD `e6ddef3`，任务开始时工作树除架构报告外干净 |
| 本机环境 | Python 3.10.11 / `.venv/Scripts/python.exe`；spglib 2.7.0、PySide6 6.11.2、pytest 9.2.0 |
| 依赖实测 | `gemmi` / `pymatgen` / `CifFile` / `xinmatch` **均缺失**；spglib / PySide6 齐全 |
| 主理人基线（不重复跑全量） | `1 failed / 525 passed / 6 skipped / 775 warnings，481.53 s，EXIT=1` |
| 文档权威基线 | `docs/RELEASE_NOTES_v1.6.2.md:79`：532 passed / 0 failed / 0 skipped，EXIT=0 |
| 审视性质 | **只读诊断**。本轮未修改任何 `.py` / 测试 / 配置 / 既有文档，未 git add/commit/push，未访问工作目录之外的数据目录，未读取其它项目；本报告是唯一新增文件 |
| 报告日期 | 2026-11-11 |

---

## 摘要

### 关键发现

1. **唯一失败是「测试用 0.15 s 墙钟假设第一步必然完成」的时序脆弱，不是产品语义缺陷。** 单独空闲跑 `tests/test_v162_cancel.py` 连续 3 次全部 **5 passed / EXIT=0**；注入 8 个 CPU 争用进程后，原样触发了与基线逐字一致的失败（`assert []`，`tests\test_v162_cancel.py:120: AssertionError`，EXIT=1）。实测第一步 `zero` 在空闲机恒为 **78 ms**，阈值 0.15 s 只有约 2 倍余量；负载下第一步被拖过 0.15 s，取消在**任何步完成之前**生效，`run_all` 返回空 `records` / `res=None`。
2. **空 `records` 在本产品语义下是合法且正确的**。`recipe.py:960-963` 明文约定「步内取消：连跑语义是『停在已完成的最后一步』，把已有结果交回去」；取消发生在第一步完成前时，「已完成的最后一步」不存在 → 空记录 + `res=None`。`recipe.py:73-81` 的 `_reraise_if_cancelled` 保证 `RefineCancelled` 透传，绝不落到 `StepRecord("failed")`。**在 7 档墙钟阈值 × 5 档计数器阈值 × 5 档 CPU 负载共 17 组观测中，`failed` 记录数恒为 0**——该用例真正要守的契约（不留假失败记录）始终成立，坏的只是 `assert records` / `assert res is not None` 这两条附加断言。
3. **6 个 skip 已逐个定位并跑出确切理由**：2 个来自 `test_cif_robust.py` 的 COD 原始 CIF 参数化用例、3 个来自 `test_joint_s1.py` 的模块级 `skipif`、1 个来自 `test_xinm_import.py` 的 XinMatch 导入失败。根因是**硬编码仓库外绝对路径 `D:/Project/XRD/sync-COD/COD`（5 项，代码设计缺陷）+ 缺兄弟项目/可选依赖 `xinmatch`/`gemmi`（1 项，环境依赖）**；本机 `-rs` 小范围实测 `56 passed, 6 skipped in 16.73s`，与全量 6 skipped 数完全吻合。
4. **`test_golden_b.py` 未被跳过，golden 活体校验在本机仍然生效**。其 `skipif`（:27-29）只检查仓库内 `tests/data/virtual_b/v50_wide.xy` 与 `tests/golden/method_b_roundtrip.json`（均已实测存在），不依赖 gemmi；小范围运行中该用例通过。不可误判为「golden 未校验」。
5. **775 warnings 已定量归因到 spglib 2.7.0 的弃用提示，且确由项目自身 API 调用方式触发**：`spglib/error.py:128-136` 的 `_set_no_error()` 在 `OLD_ERROR_HANDLING=True`（2.7.0 默认）时**无条件** `warnings.warn(DeprecationWarning)`；项目 `core/symops.py:95` 在 `_all_types()` 中枚举 530 个 hall 设置 → 单次即 530 条 `spg.py:514` 警告；`core/symops.py:187`（`get_spacegroup_type`）→ `spg.py:514`、`:198`（`get_symmetry_from_database`）→ `spg.py:602`。小范围 `tests/test_symops.py -rw` 实测 **531 + 243 = 774 条**，占全量 775 条的 99.9%；`_all_types()` 带 `lru_cache`，全量跑时首个触发模块不同会把这 530 条归到 `test_site_refine.py`（与主理人线索一致）。**属第三方弃用提示，非错误、非异常、不影响数值，本轮不需要治理动作**，但 spglib 2.8/3.0 会翻转/移除旧错误处理，应作为低优先级技术债登记。
6. **本轮明确不建议修改产品代码**。`recipe.py` / `nonlinear.py` 的取消语义已正确，改动它反而会破坏「保留已完成部分结果、不留假失败记录」的契约；也不建议装包或放宽断言来把基线「刷绿」。唯一值得做（且仅作为后续可选动作）的是把 `test_v162_cancel.py` 里的墙钟谓词换成确定性的残差检查点计数谓词——这是**测试去脆弱化**，不是放宽断言。
7. **（主理人追加指令的正式回应，见第 9 节）A15 明确判为「测试时序假设脆弱」，不是 `run_all` 产品语义缺陷**，且已独立实测**仅把谓词换成调用计数并不能让原用例通过**（`calls>=3` 仍得 `records=[]`，`assert records` 依旧 FAIL）——坏的是断言里「源码从未承诺的前置条件」，不只是墙钟。同时独立修正机制描述：`t0 → 首次残差检查点` 实测仅 **15–16 ms**（空闲与 8 burner 几乎一致），远低于 0.15 s；真正的竞争点是**第一步整步耗时 78–203 ms** 跨过/贴近 150 ms 阈值。
8. **改写方案不是「放宽断言绕过」**：真契约 `all(r.status != "failed")` 原样保留并收紧为 `all(status in {done, skipped})`，另加 `res↔records` 双向一致性、6 档取消时机参数化、「已完成 K 步部分结果保留」三条断言；缺陷注入实证（把 `_reraise_if_cancelled` 置空 → 3 条 `failed` 记录）下新用例**仍然 FAIL**，证明它拦得住真实产品缺陷。
9. **F01–F06 独立风险复核完成**：6 项在默认路径均不改变数值结果、不破坏现有测试（104 项相关用例小范围实测全绿）、文件格式向后兼容；但有两处需明确披露——F03 在 `refine_po=True` + `api.report()` 这条 opt-in 路径上**确实改变结果**（这正是修复目的），F04 会让 `.xinr` 压缩体积增加约 **16.8%**（4250 点谱图，含 manifest + 2 CIF + result 的完整 zip，19174 B → 22395 B）。逐项验收用例见第 9.3 节。

### 落地物

- 本报告：`docs/audit-20261111-qa-baseline.md`（仓库内本轮唯一新增文件）。
- **失败项完整证据链**：3 次空闲复现 + 8 进程负载下原样 pytest 失败复现 + 17 组取消时机的确定性扫描 + 第一步墙钟耗时实测，附 `文件:行号` 依据（`test_v162_cancel.py:114-123`、`recipe.py:73-81,919-970,387-395,427-429`、`nonlinear.py:110-115,583-601,687,895`）。
- **正确的验收契约**（第 2.3 节）：明确「取消发生在任何步开始前返回空 records 合法」，并给出合法/非法行为边界。
- **6 个 skip 逐个清单**（第 3 节）：nodeid、skip 原因原文、根因、环境迁移 vs 代码设计缺陷区分。
- **建议回归用例**：3 组、共 8 个确定性断言，完整 pytest 代码（第 5 节），已用只读脚本逐条执行验证全部 PASS，不依赖墙钟、不改变数值结果。
- **结构化结论表**（第 6 节）：11 行编号问题清单，含归类、建议动作、是否改变数值结果；第 9.6 节另有 6 行补充结论表。
- **（追加）第 9 节**：主理人追加指令的正式回应——A15 明确回答与「是否放宽断言」的形式化论证、F01–F06 逐项独立风险复核与可直接粘贴的 pytest 验收用例、新增观察（`run_all` 未重置 `state.records`）、追加复现命令 C11–C18。

### 下一步

1. 请主理人裁定是否把第 5 节的测试去脆弱化列入后续任务；**本轮 QA 不实施任何测试/产品改动**，基线红灯按「已知且已定性的测试时序脆弱」记录，不通过装包/放宽断言消除。
2. 任务 #3（Engineer 实施 F01–F06）与任务 #4（全量回归 + golden 复验）应与本报告的基线定性对齐：任务 #4 的对照值是同机同环境的 `1 failed / 525 passed / 6 skipped / 775 warnings`，验收目标为「无**新增**失败、无**新增** skip」，而非强求 0 failed / 0 skipped。
3. 若后续要让 6 个 skip 真正执行，属于**独立的测试可移植性改造**：把 `COD_ROOT` 改为可配置（环境变量 / conftest option）或在仓库内置最小 COD 夹具 CIF；`xinmatch` 依赖需在 CI 环境显式声明。二者都不属于数值引擎改动，但也不在本轮范围。
4. spglib 弃用警告建议单列一条低优先级技术债（不占本轮名额）：升级到 spglib ≥2.8 前，在调用侧设置 `spglib.error.OLD_ERROR_HANDLING = False` 并以 `try/except SpglibError` 收口，或局部过滤该警告；同时评估 `_all_types()` 全量枚举 530 次是否有必要。

---

## 1. 复现方法与命令清单

> 全部命令在 `D:/XinRefinement` 下执行；`-o addopts=""` 覆盖 `pytest.ini:3` 的 `-q`；每次使用新 `--basetemp`。未重跑 8 分钟全量。

| # | 目的 | 命令（核心部分） | 结果 |
|---|---|---|---|
| C1 | 失败项 3 次空闲复现 | `for i in 1 2 3; do python -m pytest -o addopts="" --basetemp=<temp>/xinr_qa_cancel_$i tests/test_v162_cancel.py -q -rs --durations=6; done` | 3 次均 `5 passed`，EXIT=0；失败用例耗时 0.15 / 0.15 / 0.14 s |
| C2 | 取消语义确定性扫描 | `python - <<'PY'` 只读脚本：立即取消 / 永不取消 / 7 档墙钟阈值 / 5 档计数器阈值 | 见第 2.2 节 |
| C3 | 第一步耗时与负载复现 | `python - <<'PY'` 只读脚本：5 次 `run_step(zero)` 计时；0/2/4/8 个 CPU burner 下跑 0.15 s 谓词 | 78.0 ms × 5；8 burner → `records=0` |
| C4 | **原样 pytest 失败复现** | `python - <<'PY'` 启动 8 个 burner 后 `subprocess.run([... pytest tests/test_v162_cancel.py::test_run_all_does_not_record_cancel_as_failure -q])` | **EXIT=1，`assert []`，与基线逐字一致** |
| C5 | 6 skip 定位 | `python -m pytest -o addopts="" --basetemp=<temp>/xinr_qa_skips -rs -q tests/test_cif_compat.py tests/test_cif_robust.py tests/test_edge_peaks.py tests/test_esd_geometry.py tests/test_golden_b.py tests/test_joint_s1.py tests/test_peaks_vectorized.py tests/test_xinm_import.py` | `56 passed, 6 skipped in 16.73s` + 6 条 SKIPPED 原因 |
| C6 | 收集顺序定位 | `python -m pytest --collect-only -q -o addopts=""` 管道统计 | 532 collected；skip 候选索引 15.2%/15.4%、29.3%~29.7%、97.4%（三簇 2/3/1，与交接线索的 13%/40%/94% 分组一致，百分比为进度条估读差异） |
| C7 | 依赖探测 | `python - <<'PY'` 逐个 `importlib.import_module` | gemmi/pymatgen/CifFile/xinmatch 缺；spglib 2.7.0 / PySide6 6.11.2 在 |
| C8 | warnings 定量 | `python -m pytest -o addopts="" --basetemp=<temp>/xinr_qa_warn tests/test_symops.py -q -rw` + 只读 `warnings.catch_warnings` 计数脚本 | 531 (spg.py:514) + 243 (spg.py:602) = 774；`_all_types()` 单次 530 条 |
| C9 | 建议用例自检 | `python - <<'PY'` 直接调用第 5 节 3 个测试函数（含 monkeypatch 替身） | 8/8 PASS |
| C10 | 仓库零改动核对 | `git status --short` / `git rev-parse --short HEAD` | 仅 `?? docs/audit-20261111-architecture.md`（架构师产出）；HEAD `e6ddef3` |

---

## 2. 唯一失败项：复现、定性、正确验收契约

### 2.1 失败原文与源码依据

```
tests/test_v162_cancel.py::test_run_all_does_not_record_cancel_as_failure
    def cancel(): return time.monotonic() - t0 > 0.15
    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
>   assert records, "应至少跑完/开始过一步"
E   AssertionError: 应至少跑完/开始过一步
E   assert []
```

| 位置 | 内容 | 作用 |
|---|---|---|
| `tests/test_v162_cancel.py:114` | `t0 = time.monotonic()` | 墙钟起点 |
| `tests/test_v162_cancel.py:116-117` | `def cancel(): return time.monotonic() - t0 > 0.15` | **唯一使用墙钟的取消谓词**（同文件另 3 个取消用例都用计数谓词，见 :54-58、:100-104、:70-74） |
| `tests/test_v162_cancel.py:119` | `RecipeRunner().run_all(_inputs(cancel_cb=cancel))` | 只通过 `inputs.config.cancel_cb` 传回调；**`run_all` 的 `cancel_cb` 参数为 None** |
| `tests/test_v162_cancel.py:120` | `assert records, "应至少跑完/开始过一步"` | **失败断言**：把「至少完成一步」与 0.15 s 墙钟绑定 |
| `tests/test_v162_cancel.py:121-122` | `assert all(r.status != "failed" ...)` | **真正要守的契约**（不留假失败记录），实测恒成立 |
| `tests/test_v162_cancel.py:123` | `assert res is not None` | 与 :120 同源的时序假设 |
| `nonlinear.py:110-115` | `class RefineCancelled(Exception)` | 取消异常类型 |
| `nonlinear.py:583-601` | `_check_cancel(cfg)`：`cb()` 为真则 `raise RefineCancelled()`；`RefineCancelled` 透传，其余回调异常吞掉 | 残差评估入口检查点 |
| `nonlinear.py:687` | `residual_fn` 首行 `_check_cancel(cfg)` | **每次残差评估**检查（LM 每迭代 n+1 次） |
| `nonlinear.py:895` | 合成最终计算谱前再查一次 | 补充检查点 |
| `recipe.py:932` | `inputs = replace(inputs, config=_with_cancel(inputs.config, cancel_cb))` | 把 `run_all` 参数回调挂进 config；本例参数为 None，config 里已有回调，故原样保留 |
| `recipe.py:941-943` | `for i, step in enumerate(todo): if cancel_cb is not None and cancel_cb(): break` | **步边界检查**：本例 `cancel_cb` 参数为 None → 该分支不执行；取消完全由引擎残差检查点触发 |
| `recipe.py:958-963` | `try: result, rec = self.run_step(...) / except RefineCancelled: break`，注释「停在已完成的最后一步，把已有结果交回去」 | **连跑取消的产品语义** |
| `recipe.py:73-81` | `_reraise_if_cancelled(exc)`：`RefineCancelled` 直接 `raise exc` | 阻止配方层把取消吞成 `StepRecord("failed")` |
| `recipe.py:387-395` | `run_step` 的 `except Exception` → 先 `_reraise_if_cancelled(exc)`，再建 `StepRecord("failed")` | 只有**非取消**异常才产生 failed 记录 |
| `recipe.py:427-429` | `StepRecord("done", ...)` append | 记录**只在 `solve()` 成功返回之后**才追加；被取消的步不会追加任何记录 |
| `recipe.py:970` | `return result, self.state.records` | 返回已完成记录 |

**链路结论**：取消在首步 `solve()` 的某次 `residual_fn` 检查点触发 → `RefineCancelled` → `run_step` 的 `except Exception` 经 `_reraise_if_cancelled` 透传（不写 failed 记录）→ `run_all` 的 `except RefineCancelled: break`（不写任何记录）→ 返回 `([], None)`。这条路径**完全符合** `recipe.py:960-963` 的设计意图。

### 2.2 复现结果（全部实测）

**C1 — 空闲机连续 3 次**

| 运行 | 结果 | `test_run_all...` 耗时 |
|---|---|---|
| 1 | `5 passed in 2.67s`，EXIT=0 | 0.15 s |
| 2 | `5 passed in 2.66s`，EXIT=0 | 0.15 s |
| 3 | `5 passed in 2.10s`，EXIT=0 | 0.14 s |

**C3 — 第一步耗时与负载**

```
=== 第一步(zero)墙钟耗时 vs 测试阈值 0.15 s ===
  trial 1..5:    78.0 ms  status=done   （5 次完全一致）
=== 注入 CPU 争用，跑原测试 0.15 s 断言 ===
  burners=0  records=1 assert records -> PASS  假失败记录=[]  res=obj
  burners=2  records=1 assert records -> PASS  假失败记录=[]  res=obj
  burners=4  records=1 assert records -> PASS  假失败记录=[]  res=obj
  burners=8  records=0 assert records -> FAIL  假失败记录=[]  res=None
```

**C4 — 负载下原样 pytest 失败（与基线逐字一致）**

```
===== test_run_all_does_not_record_cancel_as_failure  EXIT=1 =====
>       assert records, "应至少跑完/开始过一步"
E       AssertionError: 应至少跑完/开始过一步
E       assert []
tests\test_v162_cancel.py:120: AssertionError
1 failed in 4.76s
```

同批 `test_cancel_lands_within_one_residual`（同样用 `> 0.05` / `< 0.5` 墙钟阈值）在 8 burner 下 **EXIT=0 / 1 passed**：本轮未观察到它失败，但属同类潜在风险（见第 6 节 Q02）。

**C2 — 取消时机确定性扫描（决定性证据）**

```
=== A. 确定性：立即取消 / 永不取消 ===
cancel=lambda: True          records=0  res=None failed=[] statuses=[]
cancel=None (永不)            records=8  res=obj  failed=[] statuses=['done','done','done','done','done','skipped','done','done']

=== B. 墙钟阈值扫描（模拟不同机器负载/慢启动）===
  thr=0.0    records=0  res=None failed=[]
  thr=0.001  records=0  res=None failed=[]
  thr=0.01   records=0  res=None failed=[]
  thr=0.05   records=0  res=None failed=[]
  thr=0.15   records=1  res=obj  failed=[]   statuses=['done']
  thr=0.5    records=4  res=obj  failed=[]   statuses=['done','done','done','done']
  thr=2.0    records=4  res=obj  failed=[]

=== C. 计数器式（不依赖墙钟）取消：第 N 次残差检查触发 ===
  N=1   检查次数=1    records=0  res=None failed=[]
  N=2   检查次数=2    records=0  res=None failed=[]
  N=3   检查次数=3    records=0  res=None failed=[]
  N=10  检查次数=10   records=0  res=None failed=[]
  N=40  检查次数=40   records=1  res=obj  failed=[]   statuses=['done']
```

`records` 数量随墙钟阈值**单调变化**（0 → 1 → 4）：这是纯粹的时序竞争，不是产品行为不确定。而 `failed=[]` 在全部 17 组里恒定——**产品契约始终满足**。

### 2.3 正确的验收契约

**结论：取消发生在任何步开始前（或第一步完成前）返回空 `records` 是合法的**，且 `res is None` 同样合法。

| 场景 | 是否合法 | 应有行为 |
|---|---|---|
| 取消在第一步完成前生效 | ✅ 合法 | `records == []`、`res is None`；**不得**出现任何 `status='failed'` 记录 |
| 取消发生在第 K+1 步执行中（前 K 步已完成） | ✅ 合法 | 恰好返回前 K 条已完成记录（status ∈ {done, skipped}），`res` = 第 K 步的 `SolveResult`；第 K+1 步**不**入记录 |
| 取消从不发生 | ✅ 合法 | 8 条记录（本配置下第 6 步 xyz 按设计 `skipped`），`res` 非空 |
| 因取消产生 `StepRecord(status='failed')` | ❌ 非法 | 这正是 v1.6.2 `_reraise_if_cancelled` 要防的「假失败告警」 |
| 把「开始过但未完成」的步记为 `done` | ❌ 非法 | 那才是真的丢失/伪造部分结果 |

**理由**：产品语义是「取消后保留**已完成**的部分结果」（`recipe.py:960-963`），不是「保留所有启动过的步」。被 `RefineCancelled` 打断的步没有完成，记成 `done` 是伪成功、记成 `failed` 是假失败，二者都违背 PRD；丢弃它、只回传已完成步是唯一自洽解。因此**这不是 `run_all` 在「取消发生于第一步前时确实丢失部分结果」的产品语义缺陷**——它丢的是「未完成」的步，保留的是「已完成」的步，语义正确。

**若（假设）要求「取消后 records 必须非空」，产品侧最小改法会是**：为被取消的步新增一种 `status='cancelled'` 记录并回传。但这会引入新的状态枚举、牵动 GUI 结果表 / CLI 部分结果打印 / 快照回退（`RecipeState.rollback` 按 index 截断 records），且与「不留假失败记录」「保留已完成部分结果」的既有承诺冲突，**不建议**。正确做法是修测试。

**测试该改成什么断言**：删掉 `assert records` 与 `assert res is not None` 这两条墙钟假设，保留并强化 `all(r.status != "failed")`；改用**残差检查点计数谓词**（与同文件 :54-58 已有的确定性写法一致）替代 `time.monotonic()`；增加「`res` 与 `records` 一致性」「已完成部分结果确实保留」两条确定性断言。完整代码见第 5 节。

**次要观察（不构成本轮缺陷）**：`recipe.py:942` 的步边界预检只在 `run_all(..., cancel_cb=...)` **参数**非空时生效；像本用例这样只设 `inputs.config.cancel_cb` 时，该分支静默，取消完全由引擎残差检查点承担（实测仍有效，只是检查点从「步边界」后移到「下一步首个残差评估」）。这是 API 双通道的不对称，属可维护性说明，不影响正确性，本轮不动。

---

## 3. 6 个 skip 逐个清单

C5 实测输出（`56 passed, 6 skipped in 16.73s`）：

```
SKIPPED [1] tests\test_cif_robust.py:52: COD 原始文件缺失: D:\Project\XRD\sync-COD\COD\1\54\88\1548811.cif
SKIPPED [1] tests\test_cif_robust.py:52: COD 原始文件缺失: D:\Project\XRD\sync-COD\COD\1\54\88\1548823.cif
SKIPPED [1] tests\test_joint_s1.py:98: 需要本机 COD 档案与合成谱样例
SKIPPED [1] tests\test_joint_s1.py:125: 需要本机 COD 档案与合成谱样例
SKIPPED [1] tests\test_joint_s1.py:179: 需要本机 COD 档案与合成谱样例
SKIPPED [1] tests\test_xinm_import.py:252: XinMatch 不在 import 路径上
```

| # | nodeid | skip 原因（原文） | 触发位置 | 根因 | 归类 |
|---|---|---|---|---|---|
| S1 | `tests/test_cif_robust.py::test_raw_cod_with_esd_parses[1548811-5-3.1268-4.606]` | `COD 原始文件缺失: D:\Project\XRD\sync-COD\COD\1\54\88\1548811.cif` | `test_cif_robust.py:51-52`（`pytest.skip`）；路径常量 `:17` | `COD_ROOT = Path("D:/Project/XRD/sync-COD/COD")` **硬编码工作目录外绝对路径**，本机无该档案（实测 `ls` 报 No such file or directory） | **代码设计缺陷（可移植性）+ 环境迁移触发** |
| S2 | `tests/test_cif_robust.py::test_raw_cod_with_esd_parses[1548823-30-4.6117-14.735]` | `COD 原始文件缺失: ...\1548823.cif` | 同上 | 同 S1（同一 `parametrize` 的第二个档案） | 同 S1 |
| S3 | `tests/test_joint_s1.py::test_s1_api_path_reproduces_golden_rwp` | `需要本机 COD 档案与合成谱样例` | `test_joint_s1.py:29-31` 模块级 `pytest.mark.skipif` | `COD_ROOT`（`:25`）同样硬编码工作目录外绝对路径；`COD_ROOT.is_dir()` 为 False | **代码设计缺陷（可移植性）+ 环境迁移触发** |
| S4 | `tests/test_joint_s1.py::test_s1_full_loop_matches_manual_import` | 同 S3 | 同 S3 | 同 S3 | 同 S3 |
| S5 | `tests/test_joint_s1.py::test_s1_manual_path_same_rwp` | 同 S3 | 同 S3 | 同 S3 | 同 S3 |
| S6 | `tests/test_xinm_import.py::test_roundtrip_with_real_xinmatch_exporter` | `XinMatch 不在 import 路径上` | `test_xinm_import.py:245-252` 的 `except ImportError: pytest.skip(...)` | 实测 `import xinmatch` → `ModuleNotFoundError: No module named 'xinmatch'`；`gemmi` 亦缺。本用例未走到 `test_joint_s1.py:37-45` 的 fixture（模块级 skipif 先命中），故 fixture 里「真因是缺 gemmi」的历史注释不适用于本机 | **环境依赖（缺兄弟项目 / 可选依赖）** |

### 3.1 环境迁移导致 vs 代码设计缺陷

- **环境迁移导致（6/6 的直接触发）**：本机没有 `D:/Project/XRD/sync-COD/COD` 档案，也没有 `xinmatch` / `gemmi`。这 6 项在文档权威基线的「全能力环境」（COD 档案 + XinMatch 可用）下会实际执行，因此 `532 passed / 0 skipped` 与本机 `525 passed / 6 skipped` 的差异是**环境档位差异，不是数值回归**。（受范围限制，本轮无法访问工作目录之外验证另一台机器，只能从代码条件自洽性判断。）
- **代码设计缺陷（5/6 的深层根因）**：`test_cif_robust.py:17` 与 `test_joint_s1.py:25` 把外部档案根路径**硬编码成绝对 Windows 路径**，且路径位于工作目录之外。这使 5 个用例在任何未挂载该档案的机器/CI 上永久跳过，且 `skip` 是静默的（无 warning），曾导致 `test_s1_api_path_reproduces_golden_rwp` 长期恒跳过、golden 漂移无人发现（`test_golden_b.py:5-10` 与 `test_joint_s1.py:104-107` 的自述）。属于应治理的测试可移植性设计问题，但**不属于产品数值缺陷**，也不在本轮「低风险修复」范围。
- **合理防护，不是缺陷**：`test_cif_robust.py:51-52`、`test_joint_s1.py:29-31`、`test_xinm_import.py:251-252` 的跳过机制本身写得没错（先判存在再 skip）；问题只在路径来源。
- **S6 的措辞**：本机实测 `xinmatch` 模块本身不存在，故 `XinMatch 不在 import 路径上` 在本机是**准确**的；但 `test_joint_s1.py:43-44` 已注明历史上真因可能是「缺 gemmi 依赖」而非路径——若将来只装了 xinmatch 而缺 gemmi，该文案会误导。属轻微文案问题。

### 3.2 已澄清：不是问题的相关项

- `tests/test_golden_b.py::test_golden_5050_bit_identical`：其 `skipif`（`:27-29`）只检查仓库内 `VIRTUAL_B/v50_wide.xy` 与 `GOLDEN/method_b_roundtrip.json`。C7 已实测两文件均存在（102044 / 2707 字节），C5 中该用例**通过**。→ **golden 活体校验在本机生效**，不可误判为「golden 未校验」。
- `tests/test_cif_compat.py:25-30`（`缺 INDEX.json`）、`test_edge_peaks.py:21-26`（`缺 NCA_80_15_05.cif`）、`test_peaks_vectorized.py:25-28`（`缺 <name>`）：C7 实测 `INDEX.json`、`NCA_80_15_05.cif`、`LiCoO2.cif`、`AlOH3_gibbsite.cif` 全部存在 → 未跳过，C5 中均通过。
- `tests/test_esd_geometry.py:183-188` 的两处条件 `pytest.skip`（配方步失败 / X/Y 未停在 TCH 边界）：C5 中该文件 12 个用例全部通过 → 条件未命中，不产生 skip。
- 因此全量 6 skipped 与 C5 小范围 6 skipped **完全同源**，不存在遗漏的第七个 skip 源。

---

## 4. 775 warnings 定性

### 4.1 确切来源（已定量复现）

| 层 | 位置 | 内容 |
|---|---|---|
| 第三方 | `.venv/Lib/site-packages/spglib/error.py:128-136` | `_set_no_error()`：当 `OLD_ERROR_HANDLING=True`（`error.py:92`，2.7.0 默认）时**无条件** `warnings.warn("Set OLD_ERROR_HANDLING to false and catch the errors directly.", DeprecationWarning, stacklevel=2)`；`error.py:113-124` 的 `_set_or_throw_error` 同文案 |
| 第三方 | `.venv/Lib/site-packages/spglib/spg.py:514` | `get_spacegroup_type()` 内 `_set_no_error(_throw)` |
| 第三方 | `.venv/Lib/site-packages/spglib/spg.py:602` | `get_symmetry_from_database()` 内 `_set_no_error()` |
| **项目** | `xinrefinement/core/symops.py:95` | `_all_types()` 中 `for h in range(1, 531): spglib.get_spacegroup_type(h)` → **一次调用即 530 条** `spg.py:514` 警告（C8 只读脚本实测 530/530） |
| **项目** | `xinrefinement/core/symops.py:187` | `symops_from_spg(hall_number=...)` 中 `spglib.get_spacegroup_type(int(hall_number))` → `spg.py:514` |
| **项目** | `xinrefinement/core/symops.py:198` | `spglib.get_symmetry_from_database(choice.hall_number)` → `spg.py:602` |

C8 实测：

```
_all_types() 警告数: 530
    530 x 'Set OLD_ERROR_HANDLING to false and catch the errors directly.' <- spg.py:514
5 次 symops_from_spg 警告数: 10   （每次 2 条：514×1 + 602×1）

tests/test_symops.py -q -rw  →  8 passed, 774 warnings in 0.23s
  tests/test_symops.py: 531 warnings  spg.py:514 DeprecationWarning: Set OLD_ERROR_HANDLING to false and catch the errors directly.
  tests/test_symops.py: 243 warnings  spg.py:602 DeprecationWarning: Set OLD_ERROR_HANDLING to false and catch the errors directly.
```

- 531 = 530（`_all_types()` 首次枚举）+ 1（`symops.py:187` 的一次显式查询）；243 = `symops.py:198` 的重复调用。合计 **774**，占全量 775 条的 99.9%。
- `_all_types()` 带 `@lru_cache(maxsize=1)`（`symops.py:90`），**每个进程只枚举一次**：全量跑时首个触发它的模块（主理人线索为 `test_site_refine.py`）会吃下 530 条，后续 `test_symops.py` 只剩 243 条 —— 这正好解释「全量里 test_site_refine.py 530 条 / test_symops.py 243 条」与「单跑 test_symops.py 531+243 条」的归属差异。
- 余 1 条未在本次小范围复现中定位（不重跑全量），不影响结论；**本轮未观察到任何非 spglib 的失败型警告**。

### 4.2 是否被项目自己的 API 调用方式触发

**是，但属于「正常调用触发的迁移提示」，不是错误用法。** `_set_no_error()` 在 spglib 2.7.0 里是**每次调用都发**的弃用公告（不是异常分支），项目调用的 `get_spacegroup_type` / `get_symmetry_from_database` 都是 spglib 官方公开 API，参数合法（hall_number ∈ 1..530，`symops.py:185-186` 有范围校验）。放大到 775 条的唯一原因是 `symops.py:95` 在单个函数里循环枚举全部 530 个 hall 设置。

### 4.3 治理评估（只给结论，不改代码）

- **不需要在本轮治理**：DeprecationWarning 默认不显示为错误、不改变任何返回值、不参与断言；`symops.py` 全部 8 个用例通过；golden 与数值链完全不受影响。归类「可忽略」。
- **应登记为低优先级技术债**：`error.py:26-34` 明确 spglib **2.8.0 起默认翻转**（改为直接抛异常）、**3.0 移除**旧错误处理。届时项目的 `get_spacegroup_type` / `get_symmetry_from_database` 调用需要 `try/except SpglibError` 收口；且 `symops.py:95-97` 目前只判 `if t is None: continue`，在抛异常版本下会直接中断 `_all_types()`。建议升级前专项评估。
- **可选降噪（非本轮）**：在导入 spglib 后设 `spglib.error.OLD_ERROR_HANDLING = False` 并补异常捕获；或在 `_all_types()` 局部 `warnings.catch_warnings()` 过滤该条；或改为按需查询而非全量枚举。三者都不改变数值结果，但都属代码改动，本轮禁止。

---

## 5. 建议新增/修改的回归用例（确定性、不依赖墙钟、不改数值）

> 以下为**建议代码，本轮未落盘、未实施**（范围铁律：只允许写本报告）。已用 C9 只读脚本把 3 个函数体逐一执行验证，**8/8 PASS**。
> 建议替换 `tests/test_v162_cancel.py:112-123` 的原用例，并在同文件追加另外两个用例。所有用例复用该文件的 `_inputs()` / `BY_KEY` / `RecipeRunner` 导入，不引入新依赖、不碰数值引擎。

```python
# ---- 建议 1：替换原 test_run_all_does_not_record_cancel_as_failure ----
def test_run_all_cancel_never_records_fake_failure():
    """确定性回归：任意取消时机都不产生 status='failed' 的假记录。

    原用例用 `time.monotonic() - t0 > 0.15` 赌「第一步一定在 0.15 s 内跑完」，
    在负载/慢机器上会拿到 records == [] 而误报（本轮已复现）。这里改用
    残差检查点计数，与墙钟完全解耦；断言的是真正的产品契约，
    而非「至少跑完一步」这一不成立的附加假设。
    """
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= 3          # 第 3 次残差检查点（首步内）请求取消

    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
    assert all(r.status != "failed" for r in records), \
        [(r.key, r.status, r.message) for r in records]
    assert (res is None) == (len(records) == 0)   # 结果与「已完成记录」一致
    assert all(r.status in ("done", "skipped") for r in records)


# ---- 建议 2：新增，覆盖取消时机的全谱 ----
@pytest.mark.parametrize("cancel_at", [1, 2, 3, 10, 40, 10**9])
def test_cancel_at_any_checkpoint_keeps_contract(cancel_at):
    """覆盖：首个检查点 / 首步内 / 步间 / 链尾 / 从不取消。

    cancel_at=10**9 等价于「不取消」，用于校验全链 8 步的基线记录形态。
    """
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] >= cancel_at

    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
    assert all(r.status != "failed" for r in records), \
        [(r.key, r.status, r.message) for r in records]
    assert (res is None) == (len(records) == 0)
    assert all(r.status in ("done", "skipped") for r in records)


# ---- 建议 3：新增，守「取消后保留已完成的部分结果」----
def test_cancel_preserves_completed_partial_results(monkeypatch):
    """确定性：取消发生在第 3 步内时，前 2 步的已完成结果必须保留。

    用 monkeypatch 包一层 run_step 计数「已完成步数」，谓词只认这个计数，
    因此完全不受迭代次数/墙钟/机器负载影响，也不依赖任何魔法数字。
    """
    orig = RecipeRunner.run_step
    completed = [0]

    def spy(self, step, inputs, prev=None):
        out = orig(self, step, inputs, prev)   # 取消异常会在此透传，不计数
        completed[0] += 1
        return out

    monkeypatch.setattr(RecipeRunner, "run_step", spy)

    def cancel():
        return completed[0] >= 2              # 已跑完 2 步；第 3 步首个检查点即取消

    res, records = RecipeRunner().run_all(_inputs(cancel_cb=cancel))
    assert len(records) == 2
    assert all(r.status == "done" for r in records)
    assert res is not None
    assert all(r.status != "failed" for r in records)
```

**设计要点**

| 要求 | 落实 |
|---|---|
| 确定性 / 不依赖墙钟 | 全部用 `calls[0] >= N` 或 `completed[0] >= K` 计数谓词；零 `time.monotonic()` |
| 不改变数值结果 | 只改取消回调的触发条件；不碰 `RefineConfig` 数值字段、`solve`、前向、golden；`cancel_at=10**9` 分支实测产出与 `cancel=None` 相同的 8 条记录 |
| 覆盖主场景 | 取消于首步前 / 首步内 / 步间 / 链尾 / 从不取消；以及「已完成 K 步的部分结果保留」 |
| 契约正确 | 明确允许 `records == []` + `res is None`，把断言集中在「无 failed 假记录」「res 与 records 一致」「已完成步保留」 |
| 与既有风格一致 | 计数谓词写法与同文件 `test_cancel_cb_aborts_inside_step`（:54-58）、`test_cell_engine_honours_cancel`（:100-104）完全一致 |

**若结论是产品缺陷时的对应最小改法**：本结论不是产品缺陷，故无产品侧改法。若强行要求「取消后 records 必须非空」，需在 `recipe.py:958-963` 为被取消步新增 `status='cancelled'` 记录并同步 GUI/CLI/回退逻辑——与既有承诺冲突，**明确不建议**（见 2.3）。

**关于同文件另一处墙钟用例**：`test_cancel_lands_within_one_residual`（:66-81）用 `> 0.05` 触发 + `latency < 0.5` 断言，属同类时序假设。本轮 8 burner 下它仍通过（C4），故**不列为已复现失败**，但建议后续一并改为计数谓词（例如「请求取消后第 2 次残差检查点内必须抛出 `RefineCancelled`」），彻底消除该文件的墙钟依赖。本轮不动。

---

## 6. 结构化结论表

| 编号 | 现象 | 复现结果 | 根因 | 归类 | 建议动作 | 是否改变数值结果 |
|---|---|---|---|---|---|---|
| **Q01** | 唯一失败 `test_v162_cancel.py::test_run_all_does_not_record_cancel_as_failure` → `assert []` | C1 空闲 3/3 PASS；C4 8 burner 下原样 EXIT=1 且报错文本与基线逐字一致；C2 17 组扫描 `failed=[]` 恒定 | 测试把「至少完成一步」绑在 `> 0.15 s` 墙钟上（`test_v162_cancel.py:114-123`）；第一步空闲仅 78 ms，负载下被拖过阈值 → 取消在任何步完成前生效 → `run_all` 按 `recipe.py:960-963` 合法返回空 records。`_reraise_if_cancelled`（:73-81）保证无假失败记录 | **测试脆弱** | 测试去脆弱化：改用计数谓词 + 保留/强化「无 failed 假记录」断言（第 5 节）；**产品代码零改动**。本轮不实施，仅设计 | **否** |
| **Q02** | 同文件 `test_cancel_lands_within_one_residual` 亦用墙钟阈值 | C4 中 8 burner 下仍 `1 passed`（未观察到失败） | `:72` `> 0.05`、`:81` `< 0.5` 与 Q01 同类时序假设，潜在 flaky | **测试脆弱（潜在风险）** | 后续一并改计数谓词；本轮不动、不列已复现失败 | **否** |
| **Q03** | skip：`test_raw_cod_with_esd_parses[1548811-...]` | C5 `SKIPPED [1] ... COD 原始文件缺失: ...\1548811.cif` | `test_cif_robust.py:17` 硬编码工作目录外绝对路径；本机档案不存在 | **环境依赖**（深层=代码设计缺陷） | 后续把 `COD_ROOT` 改可配置 / 内置最小夹具；本轮不动、不装包、不放宽断言 | **否** |
| **Q04** | skip：`test_raw_cod_with_esd_parses[1548823-...]` | C5 同上（1548823.cif） | 同 Q03（同一 parametrize 第二档） | **环境依赖**（深层=代码设计缺陷） | 同 Q03 | **否** |
| **Q05** | skip：`test_joint_s1.py::test_s1_api_path_reproduces_golden_rwp` | C5 `需要本机 COD 档案与合成谱样例` | `test_joint_s1.py:25` 硬编码工作目录外 `COD_ROOT`；`:29-31` 模块级 skipif | **环境依赖**（深层=代码设计缺陷） | 同 Q03；另注意 `test_golden_b.py` 已补上 golden 活体绊线且本机通过 | **否** |
| **Q06** | skip：`test_joint_s1.py::test_s1_full_loop_matches_manual_import` | C5 同上 | 同 Q05 | **环境依赖**（深层=代码设计缺陷） | 同 Q03 | **否** |
| **Q07** | skip：`test_joint_s1.py::test_s1_manual_path_same_rwp` | C5 同上 | 同 Q05 | **环境依赖**（深层=代码设计缺陷） | 同 Q03 | **否** |
| **Q08** | skip：`test_xinm_import.py::test_roundtrip_with_real_xinmatch_exporter` | C5 `XinMatch 不在 import 路径上`；C7 实测 `ModuleNotFoundError: No module named 'xinmatch'`，`gemmi` 亦缺 | 缺兄弟项目 / 可选依赖（`:245-252` 的 `except ImportError`） | **环境依赖** | 在 CI 环境显式声明 xinmatch + gemmi，或保留跳过；本轮不装包 | **否** |
| **Q09** | 775 warnings（spglib DeprecationWarning） | C8 小范围 `test_symops.py -rw` → 531(spg.py:514)+243(spg.py:602)=774；`_all_types()` 单次 530 条 | spglib 2.7.0 `error.py:128-136` 无条件弃用公告；项目 `core/symops.py:95/187/198` 正常公开 API 调用触发，530 次枚举放大 | **可忽略**（低优先级技术债） | 本轮不治理；登记「spglib ≥2.8 前需 `try/except SpglibError` 收口」 | **否** |
| **Q10** | 文档权威基线 `532 passed / 0 skipped` 与本机 `525 passed / 6 skipped / 1 failed` 不一致 | C6 收集 532 项；C1/C4/C5 证实 6 skip 全为环境档位、1 failed 为负载触发的测试时序 | 两档环境不同（全能力环境有 COD 档案 + XinMatch）；`(525+6+1)=532` 自洽 | **可忽略**（口径差异，非回归） | 任务 #4 用同机同环境基线对照「无新增失败/无新增 skip」，不强求 0/0 | **否** |
| **Q11** | 易误判项：`test_golden_b.py` 是否也跳过 | C5 中该用例通过；C7 实测 `v50_wide.xy` 与 `method_b_roundtrip.json` 均存在；`:27-29` skipif 只查仓库内文件、不依赖 gemmi | 无问题 | **可忽略 / 已澄清** | 记录「本机 golden 活体校验仍生效」，避免误判为 golden 未校验 | **否** |

---

## 7. 本轮是否建议修改产品代码（明确表态）

**不建议，且本轮未修改任何产品代码。**

- `recipe.py` 的 `run_all` / `_reraise_if_cancelled` / 步循环、`nonlinear.py` 的 `_check_cancel` / `RefineCancelled` 三处残差检查点接线，经 17 组取消时机验证，行为完全符合「取消后保留已完成部分结果、不留 `status='failed'` 假记录」的产品语义。改它只会把一个**正确的**实现改坏。
- 不建议为满足「全绿」而装 `gemmi` / `pymatgen` / `CifFile` / `xinmatch`、放宽或删除断言、修改 `COD_ROOT` 指向、或改 `run_all` 取消语义来「修绿」基线——这些都会掩盖真实的环境/可移植性问题，且超出本轮范围。
- 唯一建议的改动是**测试侧去脆弱化**（第 5 节），且属「把墙钟假设换成确定性谓词、同时保留并强化真实契约断言」，不是放宽断言。**是否落地、何时落地由主理人裁定；本轮 QA 只做设计与自检，不实施。**
- 与架构报告 `docs/audit-20261111-architecture.md` 摘要第 7 条、第 4 节第 12 项（「不改 `run_all` 取消语义或测试断言来『修绿』基线」）的判断一致：基线红灯的定性是「测试时序脆弱 + 环境可移植性」，不是引擎/数值缺陷。

---

## 8. 范围与合规声明

- 只读 `D:/XinRefinement` 内文件（含 `.venv` 内 spglib 源码，位于工作目录内）；未读取其它项目，未访问工作目录之外的数据目录（`D:/Project/XRD/sync-COD/COD` 仅用 `ls` 判存在性，未读取内容）。
- 未修改任何 `.py` / 测试 / 配置 / 既有文档；未 `git add` / `commit` / `push`；未改动数值引擎、未运行会改写 golden 的数值实验、未安装任何外部包。
- 所有 pytest 运行均使用 `-o addopts=""` 与新的 `--basetemp`；诊断脚本通过 `python - <<'PY'` 从 stdin 执行，不创建文件。
- C10 核对：`git status --short` 仅显示架构师产出的 `?? docs/audit-20261111-architecture.md`；本报告写入后应新增且仅新增 `?? docs/audit-20261111-qa-baseline.md`。
- 报告中每条结论均附复现命令编号（C1–C10）或 `文件:行号`；未实际观察到的现象（如 Q02 的失败、775 条中余下 1 条的归属）已显式标注为「未观察到 / 未定位」，未作推断性断言。

---

## 9. 主理人追加指令的正式回应（2026-11-11）

### 9.0 输入与独立性声明

- 以主理人 2026-11-11 的纠偏消息为**唯一正式输入**；架构师直接 DM 的证据链不作为输入、不照抄、不作为结论依据。
- 本报告第 1–8 节的复现与定性（C1–C10）在该 DM 到达**之前**已独立完成并回传：空闲 3 次全绿、8 burner 下原样 pytest 失败、17 组取消时机扫描、6 skip 的 `-rs` 实测、774/775 warnings 定量、建议用例 C9 自检。本节是在此基础上追加的独立复核，不是对 DM 的转述。
- 新增复现 C11–C18（见 9.5）均为小范围 pytest 或从 stdin 执行的只读脚本，未重跑 8 分钟全量，未写任何额外文件。

### 9.1 A15 明确回答：是「测试时序假设脆弱」，不是 `run_all` 产品语义缺陷

**支持证据（全部为我自己的实测，非架构师推断）**

| 证据 | 结果 | 指向 |
|---|---|---|
| C1 空闲连跑 `test_v162_cancel.py` 3 次 | 3/3 `5 passed`，EXIT=0 | 正确产品上会因机器状态间歇误报 |
| C4 8 个 CPU burner 下跑原单测 | EXIT=1，`assert []`，`:120` AssertionError，与基线逐字一致 | 负载可稳定复现，纯环境量 |
| C2 墙钟阈值扫描 | `records` 数随阈值单调 0→1→4；`failed=[]` 在 17 组观测中恒为 0 | 产品契约始终满足，波动的是「是否撞上完成一步」 |
| C11 取消语义边界 | 立即取消 → `records=0,res=None`；永不取消 → 8 条；中途取消 → 恰好保留已完成步 | 「停在已完成的最后一步」语义正确 |
| 源码 | `recipe.py:960-963` 明文契约；`:73-81` `_reraise_if_cancelled`；`:427-429` 记录只在 `solve()` 成功后追加 | 空 records 是设计意图，不是丢结果 |
| C13 缺陷注入 | 把 `_reraise_if_cancelled` 置空 → 3 条 `failed` 记录 | 若真有产品缺陷，取消路径会产生 failed 记录；实测从未产生 |

**同时独立修正一处机制描述（不照抄 DM）**：DM 称「t0→首次残差耗时超过 150 ms 即稳定复现」。C11a 忠实复刻测试顺序（`t0` 设在 `_inputs()` 之前，故含 `load_pattern` + 2× `parse_cif`）实测 **t0 → 首次残差检查点仅 15–16 ms**（空闲 16.0 ms / 8 burner 15.0 ms），远低于 150 ms，且负载下几乎不变。C11b 记录永不取消谓词的前 8 次调用时刻为 `15,15,15,15,31,31,31,31 ms`（Windows 15.625 ms 计时器量化），说明检查点密集落在**步内**。C11c 实测第一步 `zero` 整步耗时在 **78–203 ms** 之间（随进程缓存/负载离散度大），跨过或贴近 150 ms。→ **真正的竞争是「第一步整步耗时 vs 绝对阈值」，不是「setup / 首次残差延迟」**。该修正不改变定性，但直接决定修复方案必须改断言（见下）。

**关键反证：仅把谓词换成调用计数并不足以修复**（C12）。用 `calls[0] >= 3` 替换 `time.monotonic()-t0 > 0.15`、**保留原断言**，实测 `calls=3, records=0, res=None`，`assert records` **仍然 FAIL**，而 `all(status!='failed')` 仍为 True。→ 根因是断言里「取消后必须至少完成一步」这个 `recipe.py:960-963` 从未承诺、且与之矛盾的前置条件；墙钟只是让它在空闲机上偶然成立。因此正确改写必须**同时**换谓词**和**修正断言（第 5 节），只换谓词无效——这一点与 DM 的建议不同，是我独立实测得出。

**这是否算「放宽断言绕过」：明确不算。** 形式化：设 `P` = 产品应满足的契约集合，`Q` = 「取消后必须至少完成一步」（非契约）。旧断言集 `A_old = P ∪ {Q}`；新断言集 `A_new = P ∪ {一致性 / 状态收紧 / 多时机覆盖}`，且不含 `Q`。「放宽」的定义是 `A_new ⊂ P`；此处 `A_new ⊃ P`，不成立。逐条：

1. 真契约 `all(r.status != "failed")` **原样保留**，并收紧为 `all(r.status in ("done","skipped"))`（旧断言连 `cancelled` 等任意非 failed 状态都放过）。
2. 新增 `(res is None) == (len(records) == 0)` 的**双向**一致性断言（旧用例只单向断言 `res is not None`）。
3. 新增 6 档取消时机参数化 + 「已完成 K 步部分结果保留」的精确断言（`len(records)==2`、`all done`、`res is not None`）——覆盖度净增加。
4. **缺陷注入实证（C13）**：把 `recipe._reraise_if_cancelled` 临时置空，模拟「取消被吞成失败记录」这一真实产品缺陷 → 产出 3 条 `status='failed'` 记录 → 新用例的 `all(status!='failed')` **立即 FAIL**。新用例拦得住真实缺陷，不是放行。
5. **负载稳定性（C14）**：8 burner 下连跑 3 次，新用例断言 3/3 全通过（`records=0` 亦合法）；原用例在同样负载下 FAIL。→ 消除的是误报，不是掩盖缺陷。
6. 反向说明：若产品真有「取消记成 failed」的 bug，旧用例会因 `assert records` 先失败而给出误导性诊断；新用例反而报出准确的 `failed` 记录明细（`:121-122` 的 `[(r.key,r.status,r.message) ...]` 被保留）。

**结论**：属于「把契约写准 + 测试去脆弱化」，**不是放宽断言**；不通过装包、不删断言、不改 `COD_ROOT`、不改 `run_all` 取消语义来「修绿」。是否落地仍由主理人裁定，本轮 QA 不实施。

### 9.2 现成范式核对（主理人点名的三处）

| 位置 | 谓词 | 断言 | 是否依赖墙钟 |
|---|---|---|---|
| `tests/test_v162_cancel.py:56-58` | `calls[0] >= 3` | `pytest.raises(RefineCancelled)` + `calls[0]==3` | 否 |
| `tests/test_v162_cancel.py:102-104` | `calls[0] >= 4` | `calls[0]==4` | 否 |
| `tests/test_recipe.py:89-98` `test_cancel_stops_early` | `calls[0] >= 3`，且作为 `run_all` **形参**传入 | `len(records) < len(DEFAULT_STEPS)`——**只断言「提前停止」，不断言记录非空** | 否 |
| `tests/test_v162_cancel.py:112-123`（待改） | `time.monotonic()-t0 > 0.15` | `assert records` + `assert res is not None` | **是** |

`test_recipe.py:89-98` 的断言方向与本报告第 5 节的契约完全一致：**允许 0 条已完成记录，只要求链被提前终止**。这也是「新契约不是放宽」的旁证——仓库里早已存在同样的写法且长期通过。

### 9.3 F01–F06 独立风险复核

> 复核口径：① 是否真的不改变数值结果；② 是否会破坏现有测试或文件格式兼容；③ 可直接粘贴的 pytest 验收用例。
> 支撑：C15（F01/F02/F03 自检）、C16（F05 缺陷复现）、C17（**104 项相关用例小范围全绿**：`test_project_zip.py` / `test_cli.py` / `test_texture.py::test_cli_texture_roundtrip` / `test_p2_p46.py::test_p46_quant_and_report` / `test_registry.py` / `test_size_strain.py` / `test_size_strain_phase.py` / `test_cell_refine.py` / `test_i18n_project.py` → `104 passed in 15.07s`）、C18（F04 体积量化）。

#### 总表

| 编号 | 是否真的不改数值 | 现有测试 / 格式兼容 | 需披露的量化风险 | 复核结论 |
|---|---|---|---|---|
| **F01** | **是**（C15 实测 `compute_phase_profile` 逐位相等） | 是（`name_mineral` 仅 `naming.py:118` 读；`CifStructure.__init__:180` 已存在该属性，`setattr`/`hasattr` 搬运安全） | 无 | 可修，最低风险 |
| **F02** | **是**（生产 `refine()` 走 `_unpack_reg`，`nonlinear.py:869,894`；legacy `_unpack` 只被测试/`tools` 调用） | 是（C17 全绿；`test_registry.py:95-100` 只比 `zero,U,V,W,eta,asym,bfactor,X,Y` + cell + po_r，不含 `size_strain`） | 仅 legacy/兼容 API 路径受益 | 可修 |
| **F03** | **条件性：默认路径否；`refine_po=True` + `api.report()` 是**（这正是修复目的） | 是（`RefineRequest.refine_po` 默认 False，`test_p46_quant_and_report` 未开；golden 走 `core.refine.nonlinear.refine`，不经 `api.py`） | opt-in 行为变化，需在发布说明明确 | 可修，但**不能笼统说「零数值变化」** |
| **F04** | **是**（写盘精度；golden 为 CLI 路径，不经 `.xinr`/`.xinm`） | **是**（无任何字符串/哈希/整份快照断言；读取侧 `float()` 未改，旧 `.10g` 文件仍可读） | `.xinr` 压缩体积 **+16.8%**（4250 点：19174→22395 B）；单 pattern 成员文本 **+113%** | 可修，需披露体积；另有 1 处待回归确认（见下） |
| **F05** | **是**（只加报告字段，不改求解） | 是（无整份 JSON 快照；`test_cli.py:31-36`、`test_texture.py:219-222` 均为字段级断言） | 无 | 可修 |
| **F06** | **是**（只改按钮显示文本） | 是（`step.*` 三语 8/8 键齐全；无中文按钮文本断言；`retranslate():530-533` 早已用 `tr()`） | 无 | 可修 |

#### F01 · `name_mineral` 元数据搬运

- 实测（C15）：`parse_cif(anatase.cif).name_mineral == "Anatase"`；`structure_with_cell()` 后变 `None`、`phase_label(...,"label")` 从 `"Anatase"` 退化为 `"TiO2"`；把 `_CELL_META` 临时追加 `"name_mineral"` 后两项均恢复。全仓 `name_mineral` 只被 `core/profile/naming.py:118` 的 `phase_label` 读取（纯展示），QPA/前向/晶胞/晶系判定均不读；C15 实测改它前后 `compute_phase_profile` 的 700 点数组 `np.array_equal == True`。
- 兼容性：`CifStructure.__init__`（`cif.py:180`）已把 `name_mineral` 初始化为 `None`，故 `cell.py:182-183` 的 `setattr(out, attr, getattr(struct, attr, None))` 与 `recipe.py:657-658` 的 `if hasattr(src_st, attr)` 都能直接工作，无需改构造函数。
- 建议验收用例（**C15 已自检通过**）：

```python
import numpy as np
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.naming import phase_label
from xinrefinement.core.refine.cell import structure_with_cell
from xinrefinement.core.profile.forward import compute_phase_profile, ProfileParams

ANATASE = ROOT / "xinrefinement" / "data" / "anatase.cif"  # ROOT = Path(__file__).resolve().parents[1]

def test_structure_with_cell_preserves_name_mineral():
    st = parse_cif(ANATASE)
    assert st.name_mineral == "Anatase"
    out = structure_with_cell(st, st.cell)
    assert out.name_mineral == "Anatase"
    assert phase_label(out, "label") == "Anatase"      # 修复前为 "TiO2"

def test_name_mineral_is_display_only():
    """F01 的「不改数值」护栏：只改 name_mineral 不影响计算谱。"""
    st = parse_cif(ANATASE)
    a = structure_with_cell(st, st.cell); a.name_mineral = "Anatase"
    b = structure_with_cell(st, st.cell); b.name_mineral = None
    grid = np.arange(5.0, 40.0, 0.05)
    prm = ProfileParams()
    ya = compute_phase_profile(a, grid, prm, 5.0, 40.0)
    yb = compute_phase_profile(b, grid, prm, 5.0, 40.0)
    assert np.array_equal(ya, yb)
```

- 另建议在 `tests/test_xyz_recipe.py` 现有 xyz 步用例末尾追加 `name_mineral` 继承断言（需真实 `source_path` 的 CIF），覆盖 `recipe.py:655-658` 那一路；**本轮未执行**（需跑整步，且本机 3 个 COD 相关用例被 skip）。

#### F02 · legacy `_unpack` 补 `size_strain`

- 实测（C15）：`cfg.refine_size_strain` 默认 `False`；`legacy _unpack -> size_strain = None`，`registry.unpack -> {'foo': (0.1, 0.2)}`。生产 `refine()` 在 `nonlinear.py:869` 与 `:894` 调 `_unpack_reg(reg, ...)` → `reg.unpack`，**不经 legacy `_unpack`**，故 golden / 所有生产数值零影响。
- 兼容性：`ProfileParams` 是 frozen dataclass 且已有 `size_strain` 字段（`forward.py:249`），补一个关键字参数不抛 `TypeError`；`test_registry.py::test_unpack_matches_legacy` 只比 9 个标量字段 + cell + po_r，未含 `size_strain`；`test_size_strain.py:138-185`、`test_texture.py:96`、`test_texture_harmonic.py:197`、`test_biso.py:67` 的 legacy `_unpack` 输入 `prm` 均未设 `size_strain`（默认 None），补字段后仍是 None。C17 实测 104 项全绿。
- 建议验收用例（**C15 已确认当前 FAIL、修复后 PASS**）：

```python
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.refine.nonlinear import RefineConfig, _pack, _unpack

def test_legacy_unpack_preserves_size_strain():
    base = ProfileParams(anode="Cu", size_strain={"foo": (0.1, 0.2)})
    cfg = RefineConfig()                     # refine_size_strain 默认 False
    x = _pack(base, cfg, 1)
    prm, _ = _unpack(x, base, cfg, 1)
    assert prm.size_strain == {"foo": (0.1, 0.2)}     # 修复前为 None
```

#### F03 · `api.report()` 与 `api.refine()` 配置对齐

- 实测（C15）：`RefineRequest` 有 `refine_po` 字段，默认 `False`；`RefineConfig.refine_po` 默认 `False`；`refine():82-85` 带 `refine_po=request.refine_po`，`_solve_raw():130-131` 不带。用 monkeypatch 掉 `core.refine.solve.solve` 捕获 config，`api._solve_raw(RefineRequest(refine_po=True))` 得到 `cfg.refine_po == False`（当前 bug），修复后应为 `True`。
- **是否真的不改数值：需要如实区分**——
  - `refine_po=False`（默认、全部现有测试、golden CLI）：**完全不变**。`test_p46_refine_request_response` / `test_p46_quant_and_report` 均未开 `refine_po`；`test_golden_b.py:55` 直接 import `core.refine.nonlinear.refine`，不经 `api.py`；CLI golden 走 `cli/refine.py`。
  - `refine_po=True` + `api.report()`：**结果会变**（`_solve_raw` 从此与 `api.refine()` 用同一配置）。这是修复的**目的**，属「修正入口不一致」而非回归，但**不能笼统宣称「零数值变化」**，建议在 release note 明写。
- 建议验收用例（**C15 已自检**：当前捕获 False → 断言 FAIL；修复后 PASS；monkeypatch 掉 `solve`，无需真跑精修）：

```python
import xinrefinement.api as api
import xinrefinement.core.refine.solve as solve_mod

def test_report_and_refine_share_refine_po(monkeypatch, tmp_path):
    req = api.RefineRequest(pattern=PATTERN, cifs=(CIF_A, CIF_R), refine_po=True)
    seen, sentinel = {}, object()
    def fake_solve(inp):
        seen["refine_po"] = inp.config.refine_po
        return sentinel
    monkeypatch.setattr(solve_mod, "solve", fake_solve)
    assert api._solve_raw(req) is sentinel
    assert seen["refine_po"] is True        # 修复前为 False

def test_default_refine_po_is_zero_regression():
    req = api.RefineRequest(pattern=PATTERN, cifs=(CIF_A, CIF_R))
    assert req.refine_po is False           # 守住默认路径逐位不变
```

#### F04 · 谱图写盘 `10g → 17g`（主理人重点）

- **是否有字符串/哈希/快照断言：没有。** 逐文件核对：
  - `tests/test_project_zip.py:66` 只断言 zip magic `b"PK"`；`:70-75` 只断言 member 名称集合与 `manifest` 字段；`:85-86,130` 断言 `settings`/`result` 字典；`:88-92` 是 **`pytest.approx(..., rel=1e-9)` 的近似断言**（更精确只会更稳）；`:146-152,191-195` 是未来版本/损坏 zip 的行为断言。**无一处读 `pattern/pattern.csv` 文本做字符串或哈希比较**。
  - `tests/test_gui_smoke.py:550-558`、`tests/test_xinm_import.py:68`、`tests/test_joint_s1.py:117,200` 里的 `.10g` 都是**测试自己构造的夹具**，F04 改的是产品写入侧、不改读取侧，故这些旧夹具仍可读。
  - 全仓 Grep `== {` / `== [` / `sha256` / `hashlib` / `snapshot` / `assert ...read_text... ==` 均无 .xinr 内容快照。
  - 读取侧：`gui/project.py:211-214` 用 `csv.reader` + `float(r[0])`；`core/patterns.py:82-84` 用 `float(parts[0])`；`:96-100` 的 `is_pd_format` 只看 `loop_` 关键字。三者都与**有效数字位数无关**，见 C18 实测 `float()` 对 `.10g` 与 `.17g` 串都接受。
- **旧版 .xinr 是否仍可读：是，且是构造性保证**（读取代码一行未改）。C18 实测：`v=1.2345678901234567` 时 `.10g` → `"1.23456789"`（**不**逐位相等），`.17g` → `"1.2345678901234567"`（逐位相等）；但旧文件里存的是 `.10g` 串，`float()` 解析出的就是当时写下的那个 float64 值，读回结果不变。C17 实测现有 `test_project_zip.py` 全绿。
- **体积变化（C18 量化）**：4250 点 `v50_wide.xy`，单 `pattern.csv` 文本 `41959 → 89383 B`（**+113.0%**）；但 `.xinr` 是 deflate zip，含 `manifest.json` + 2 个 CIF + `result/refine.json` 的**完整工程** `19174 → 22395 B`（**+16.8%**，+3221 B）。→ 会有可见但非爆炸式增长，建议 release note 披露；数字串压缩率较高。
- **一处待回归确认（本机无法实测）**：`gui/main_window.py:711` 是 `.xinm` payload → 会话 `.xy` 的写入。F04 改它后，`tests/test_joint_s1.py` 的路径 A（走 `:711`，变成 `.17g`）与路径 B（测试自己在 `:200` 写 `f"{x:.10g}"`）在 payload 含 **>10 位有效数字**时会写出不同精度，`:176` 断言 `rwp_b == approx(rwp_a, rel=1e-9)`。因 C18 已证 payload 值多来自 `.10g` CSV（≤10 位有效数字）时两者 `float()` 后完全相同、且 `rel=1e-9` 有余量，判断风险低；但**这 3 个用例在本机被 skip，本轮无法实测**，请在全能力环境恢复后回归确认。不构成本轮阻塞项。
- 建议验收用例（**本轮未执行**：需写 `.xinr` 文件，超出只读范围；代码可直接粘贴）：

```python
import io, json, zipfile
import numpy as np
import pytest
from xinrefinement.gui.project import FORMAT, FORMAT_VERSION, load_project, save_project

def test_xinr_pattern_roundtrip_is_bit_exact(tmp_path):
    tt = np.linspace(5.0, 90.0, 171)
    ii = 100.0 + 30.0 * np.cos(tt / 5.0)       # 含 >10 位有效数字的值
    xy = tmp_path / "demo.xy"
    xy.write_text("\n".join(f"{x:.17g} {y:.17g}" for x, y in zip(tt, ii)),
                  encoding="utf-8")
    cif = tmp_path / "a.cif"
    cif.write_text("data_a\n_cell_length_a 3.785\n", encoding="utf-8")
    state = {"language": "zh", "pattern": str(xy), "cifs": [str(cif)],
             "settings": {}, "phase_edits": {}, "result": None, "navigation": {}}
    out = tmp_path / "proj.xinr"
    save_project(state, out, embed=True)
    got = np.loadtxt(load_project(out)["pattern"])
    assert np.array_equal(got[:, 0], tt)
    assert np.array_equal(got[:, 1], ii)

def test_old_10g_xinr_still_readable(tmp_path):
    """F04 的向后兼容护栏：手工构造旧格式 .10g 内嵌谱。"""
    tt = np.linspace(5.0, 90.0, 171)
    ii = 100.0 + 30.0 * np.cos(tt / 5.0)
    csv_text = "two_theta,intensity\n" + "\n".join(
        f"{x:.10g},{y:.10g}" for x, y in zip(tt, ii))
    p = tmp_path / "old.xinr"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": FORMAT, "format_version": FORMAT_VERSION,
            "pattern": {"member": "pattern/pattern.csv"}}))
        zf.writestr("pattern/pattern.csv", csv_text)
    got = np.loadtxt(load_project(p)["pattern"])
    assert got.shape == (171, 2)
    assert got[:, 0] == pytest.approx(tt, rel=1e-9)
```

- 附带：`tests/test_project_zip.py:88` 的注释「内嵌谱图数值往返（%.10g，rel ≤ 1e-9）」在 F04 后文案过时，建议同步改为 `.17g / 逐位相等`（注释改动，非数值改动）。

#### F05 · CLI 报告两处小修（主理人重点）

- **是否有整份 JSON 快照断言：没有。** `tests/test_cli.py:31-36` 只查 `r_factors.rwp` / `len(phases)` / `fit.success` / `weight_pct`；`test_texture.py:219-222` 只查 `tex["anatase"]["axis"]` 与 `len(tex["anatase"]["grid"])`；`test_aniso.py:191`、`test_optimizers.py:90`、`test_p2_p46.py:186`、`test_micro_initial_report.py:141-160` 均为字段级。全仓 Grep `assert data == {` / `assert report ==` / `assert json.loads(...) ==` 无命中；`to_report()` 在测试中**从未被直接调用**。
- **缺陷实证（C16）**：用 `--texture-model harmonic --texture-degree 4` 跑一次 `solve()` 再调 `to_report(res, args)`，引擎侧 `res.params.texture["anatase"]` 键为 `['axis','coeffs','degree','model']`，报告侧 `to_report(...)"parameters"]["texture"]["anatase"]` 只有 `['axis','grid']` → **`coeffs` / `degree` / `model` 三字段确实丢失**，报告无法还原球谐织构。字段来源已核实：`cli/refine.py:201-202`（`{"model":"harmonic","degree":...,"coeffs":...}`）、`solve.py:252-253`、`recipe.py:850-851`、`main_window.py:112-113`；`_round_list` 存在于 `cli/refine.py:318`。用 `entry.get("model")` / `entry.get("degree")` / `_round_list(entry.get("coeffs") or [])` 对 grid 型 entry 也不抛异常（缺键返回 None/[]）。
- `out.parent.mkdir(parents=True, exist_ok=True)` 是纯追加，对已存在目录无副作用；与 `core/report.py:161-162` 同口径。
- `test_texture.py::test_cli_texture_roundtrip` 断言 `axis`/`grid`，F05 **保留这两个键**（只新增 3 个），故仍通过；C17 实测全绿。
- 建议验收用例（可直接粘贴；`test_cli_out_creates_parent_dir` 与 `test_to_report_harmonic_fields` 本轮未执行，需写文件/跑 CLI；C16 已复现缺陷本身）：

```python
import json
from xinrefinement.cli.refine import main
from tests.test_cli import _common

def test_cli_out_creates_parent_dir(tmp_path):
    out = tmp_path / "nested" / "deep" / "report.json"
    assert main(["refine", *_common(tmp_path, "nested/deep/report.json")]) == 0
    assert out.is_file()

def test_to_report_harmonic_fields_present(tmp_path):
    out = tmp_path / "h.json"
    argv = _common(tmp_path, "h.json") + [
        "--texture", "anatase=0,0,1",
        "--texture-model", "harmonic", "--texture-degree", "4",
        "--max-iter", "2"]
    assert main(argv) == 0
    tex = json.loads(out.read_text(encoding="utf-8"))["parameters"]["texture"]
    assert tex["anatase"]["model"] == "harmonic"
    assert tex["anatase"]["degree"] == 4
    assert len(tex["anatase"]["coeffs"]) > 0
    # 现有 grid 型用例的字段仍保留
    assert "axis" in tex["anatase"] and "grid" in tex["anatase"]
```

#### F06 · 步骤按钮文本改走 `tr(f'step.{key}')`（主理人重点）

- **`step.*` 三语键是否齐全：8/8 全齐**（C15 实测）。`gui/dialogs.py:58-67` 的 `STEPS` keys = `['zero','bg','scale','cell','profile','xyz','B','micro']`；`i18n/catalog.py:40-43`（zh）、`:148-152`（en）、`:260-263`（ja）各含这 8 个键，`TRANSLATIONS` 三语缺失键均为 `[]`；`set_language` 后 `tr(f"step.{k}")` 在 en/ja/zh 均返回译文而非原键。
- **现有 GUI 测试有没有断言按钮中文文本：没有。** 逐项核对：`test_i18n_project.py:79-80` 断言 `win._step_buttons["cell"].text().startswith("▶") or tr("step.cell") in ...`（F06 后**更**成立）；`:140` 断言 `"–" in win._step_buttons["xyz"].text()`（F06 保留 `mark` 前缀，仍成立）；`test_gui_smoke.py:301-302` 断言的是**菜单 action** 中文文本（F06 不动菜单）；`test_v16_gui.py:96-99` 断言 `log_view` 文本内容，是测试自己 `log_line()` 写的字面串，与 `_on_step_finished` 无关，且 F06 **保留** `title`（中文）供 `log.step_done`（`main_window.py:1463-1466`）。C17 实测 `test_i18n_project.py` 全绿。
- 一致性依据：`retranslate():530-533` **早已**用 `f"{mark} {tr(f'step.{step}')}"`；F06 只是把 `_on_step_finished():1459` 从硬编码中文 `title` 对齐到同一口径，属收敛而非新行为。`title` 仍保留给跑码日志。
- 建议验收用例（可直接粘贴；GUI 用例本轮未执行，需 `win`/`qapp` fixture）：

```python
def test_step_finished_button_follows_current_language(win, qapp):
    """F06 的区分性用例：切到 en 后触发 step_finished，按钮不得退回中文。"""
    from xinrefinement.i18n import tr
    win.switch_language("en")
    qapp.processEvents()
    win._on_step_finished("cell", "done", 3.4, "")
    qapp.processEvents()
    btn_text = win._step_buttons["cell"].text()
    assert tr("step.cell", "en") in btn_text        # "Cell parameters"
    assert "晶胞参数" not in btn_text               # 修复前会出现

def test_all_step_keys_have_three_languages():
    from xinrefinement.i18n.catalog import TRANSLATIONS, LANGUAGES
    from xinrefinement.gui.dialogs import STEPS
    keys = [s[0] for s in STEPS]
    for lang in LANGUAGES:
        for k in keys:
            assert f"step.{k}" in TRANSLATIONS[lang], (lang, k)
```

### 9.4 新增观察（独立复核顺带发现，不在本轮 6 项名额内）

C11d 实测：`recipe.py:937-940` 在 `run_all` 开头重置了 `state.current` / `_phases` / `po_probe_report` / `xyz_report` / `time_report`（另有 `_start_clock()`、`_per_eval_s`），**唯独没有重置 `self.state.records`**；`:970` 返回的是 `self.state.records` 这个 **live list**。实测同一 `RecipeRunner` 连续两次 `run_all`：第 1 次快照 `len=8`、第 2 次 `len=16`，且 `rec1 is rec2 == True`（先前的返回值会被后续调用就地改变）。这不是 A15 的成因（每个测试都新建 runner），但属配方状态复用的真实缺陷，`tests/test_recipe.py:101-105` 只验证 `RecipeState` 默认 list 不共享、**未覆盖**「同一 runner 二次 run_all」。

```python
def test_run_all_resets_records_between_runs():
    runner = RecipeRunner()
    _, rec1 = runner.run_all(_inputs())
    n1 = len(rec1)                    # 立即快照：返回的是 live list
    _, rec2 = runner.run_all(_inputs())
    assert len(rec2) == n1           # 修复前为 2 * n1
```

**本轮不建议动**（会改变 `run_all` 的状态语义，超出「低风险小修」边界，且不属主理人指定的 6 项）；建议单列登记。

### 9.5 追加复现命令索引（C11–C18）

| # | 内容 | 关键结果 |
|---|---|---|
| C11 | 只读脚本：`t0→首次残差检查`计时（0/8 burner）、永不取消谓词全调用时刻、`zero` 整步耗时、二次 `run_all` records | 15–16 ms；前 8 次 15/15/15/15/31/31/31/31 ms；整步 78–203 ms；8→16 条累加 |
| C12 | 只读脚本：计数谓词 `calls>=3` + **保留原断言** | `records=0`，`assert records` 仍 FAIL；`all(status!='failed')` True |
| C13 | 只读脚本：把 `recipe._reraise_if_cancelled` 置空注入缺陷 | 3 条 `failed` 记录；建议用例 `all(status!='failed')` FAIL |
| C14 | 只读脚本：8 burner 下连跑 3 次建议用例断言 | 3/3 全通过 |
| C15 | 只读脚本：F01/F02/F03 验收用例自检 + `step.*` 三语键 + `to_report` 字段 | 见 9.3 各分项；`compute_phase_profile` 逐位相等；三语缺键 `[]` |
| C16 | 只读脚本：`--texture-model harmonic` → `solve()` → `to_report()` | 引擎 `axis/coeffs/degree/model` → 报告 `axis/grid`，丢 3 字段 |
| C17 | 小范围 pytest（9 个文件/用例，`-o addopts=""` + 新 basetemp） | `104 passed in 15.07s` |
| C18 | 只读脚本：`10g/17g` 位精确性 + 内存 zip 体积 | 一般 float64 `.10g` 不逐位、`.17g` 逐位；完整 .xinr +16.8% |

### 9.6 补充结论表（与主表第 6 节同列口径）

| 编号 | 现象 | 复现结果 | 根因 | 归类 | 建议动作 | 是否改变数值结果 |
|---|---|---|---|---|---|---|
| **Q12** | A15 的定性（主理人要求明确回答） | C1/C2/C4/C11/C12/C13/C14：`failed=[]` 恒为 0；计数谓词+原断言仍 FAIL；缺陷注入下新用例 FAIL | `test_v162_cancel.py:120,123` 把「至少完成一步」这一非契约前置条件与绝对墙钟绑定 | **测试脆弱** | 按第 5 节改写（换计数谓词 + 修正契约断言）；**不改产品代码** | **否**（测试侧） |
| **Q13** | 「改写是否算放宽断言绕过」 | C13 注入真实缺陷后新用例仍 FAIL；C14 负载下 3/3 稳定 | `A_new ⊃ P` 且不含伪前置条件 Q；真契约原样保留并收紧 | **可忽略（已论证非绕过）** | 由主理人裁定是否落地；本轮不实施 | **否** |
| **Q14** | F03 在 `refine_po=True` + `report()` 上改变结果 | C15 捕获 `_solve_raw` 的 `cfg.refine_po=False`（应为 True） | `_solve_raw():130-131` 漏传字段 | **环境依赖→不适用；属有意行为修正** | 可修；release note 明确「opt-in 路径结果变化」；默认路径逐位不变 | **条件性：默认否 / opt-in 是** |
| **Q15** | F04 使 `.xinr` 体积增长 | C18：完整 zip 19174→22395 B（+16.8%），单成员文本 +113% | `%.17g` 比 `%.10g` 多约 7 位有效数字 | **可忽略（需披露）** | 可修；release note 披露体积；补 `test_old_10g_xinr_still_readable` | **否** |
| **Q16** | CLI 报告丢球谐织构 3 字段 | C16：引擎 `axis/coeffs/degree/model` → 报告 `axis/grid` | `cli/refine.py:355-358` 只写 axis/grid | **产品缺陷（报告层，非数值）** | F05 可修；补 `test_to_report_harmonic_fields_present` | **否** |
| **Q17** | `run_all` 未重置 `state.records` | C11d：同一 runner 二次 `run_all` 8→16 条，`rec1 is rec2` | `recipe.py:937-940` 漏重置 | **产品缺陷（状态复用，非数值）** | 单列登记，**本轮不动**（超出 6 项名额且改状态语义） | **否** |

### 9.7 本轮是否建议修改产品代码（重申）

**明确「否」，且本轮未修改任何产品代码、测试、配置或既有文档。**

- A15 的 `run_all` / `_reraise_if_cancelled` / `_check_cancel` 取消语义经 17 组时机 + 缺陷注入验证完全正确，改它只会把正确实现改坏；也不通过装包、删断言、改 `COD_ROOT` 或改取消语义来「修绿」基线。
- F01–F06 是**主理人另行裁定的候选修复**，本节的定位是**独立风险复核**（结论：6 项均可修、默认路径零数值变化、不破坏现有测试与格式兼容），不是本轮 QA 的实施授权；其中 F03 的 opt-in 行为变化与 F04 的体积增长需在发布说明披露，F04 另有一处需在 COD 档案可用环境回归确认。
- Q17（`state.records` 累加）虽是真实观察，但**不建议本轮动**：它改变 `run_all` 状态语义，超出「低风险小修」边界，也不在指定 6 项内。
- 主理人禁止的「绕过」边界本轮严格遵守：未装包、未放宽/删除任何断言、未改数值引擎、未运行改写 golden 的实验；第 5 节的建议用例属「把契约写准」，且其拦截能力已由 C13 缺陷注入实证。

---

## 10. 任务 #2 正式收尾复核（F01–F06 表格式风险复核 + A11 / A12 前置复核）

> 本节响应主理人「任务 #2 正式收尾、#3 启动前必须完成」两条补充指令。除追加本节外**零写入**；未重跑全量 pytest；未安装任何包；未改 `.py` / 测试 / 配置 / 既有文档；未 `git add/commit/push`。本节全部结论基于本轮 `Read` / `Grep` / `git diff`（只读）取证，以及第 1–9 节既有的 C1–C18 实测。

### 10.0 独立性声明与时间线事实（请主理人注意）

- **独立性**：本节不采用任何未经主理人中转的 DM 作为输入；A11 / A12 结论均由我本轮自行读源码与检索测试得出，与架构师报告、工程师报告交叉核对而非照抄。
- **时间线交叉（重要）**：主理人上一条明确「在收到复核前不会启动工程师写代码」。但本轮 `git status --short` / `git diff` 实测显示 **F01–F06 与配套测试改动已由工程师落地到工作树**（任务 #3 状态 `in_progress`），新增 `docs/audit-20261111-engineer-changes.md` 与 `tests/test_audit_fixes_20261111.py`。因此本节性质由「实施前门禁」变为「落地后独立核验」。我如实记录这一事实，不作流程归因；以下结论仍按只读独立评估给出。
- 已落地改动与第 9 节风险预判一致：`cell.py:170` / `recipe.py:656` 已补 `name_mineral`（F01）、`nonlinear.py:456` 已补 `size_strain=base.size_strain`（F02）、`api.py:131` 已补 `refine_po`（F03）、`project.py:133-134,218` 与 `main_window.py:711` 已是 `.17g`（F04）、`cli/refine.py:355-361,512` 已补 `model/degree/coeffs` 与 `mkdir`（F05）、`main_window.py:1459` 已把按钮文本来源改为 `tr(f'step.{key}')`（F06）。

### 10.1 F04 / F05 / F06 现有断言冲突检索（表格化，命中给「文件名:行号」，无则写「无」）

| 修复 | 检索项 | 命中（文件名:行号） | 是否构成冲突断言 | 判定 |
|---|---|---|---|---|
| **F04** | `10g` 字面量 | `test_project_zip.py:29`、`test_xinm_import.py:68`、`test_joint_s1.py:117,200`、`test_gui_smoke.py:553`（均为夹具造数）；`test_audit_fixes_20261111.py:199`（新增的旧格式兼容护栏，故意用 `.10g`）；`test_project_zip.py:88` 现为注释（工程师 T3 改为 `.17g`） | 否 | 全是**写入夹具**，无一处把 `.10g` 文本当断言目标 |
| **F04** | `10g` 断言 | **无** | — | 不存在对有效数字位数的字符串断言 |
| **F04** | `.xinr` 内嵌谱文本断言 | `test_project_zip.py:70`（成员名集合 `{"manifest.json","pattern/pattern.csv"} <= names`）、`:88-92`（`np.loadtxt` + `shape==(171,2)` + `pytest.approx(rel=1e-9)`）、`test_i18n_project.py:120-121`（`embedded is True`） | 否 | 均为**解析后数值近似**断言，非谱文本精确快照；`.17g` 只会让 `rel=1e-9` 更宽松地通过 |
| **F04** | `np.array_equal` 作用于 `.xinr` 文件 / 序列化字节 | **无** | — | 全库 `np.array_equal` 命中均在**内存数组**：`test_registry.py:61,73,74`、`test_size_strain.py:104`、`test_size_strain_phase.py:74,96,132`、`test_texture.py:91,94`、`test_texture_harmonic.py:122,151,192,195`、`test_lm_params.py:38`、`test_biso.py:62,65`、`test_aniso.py:89,92`、`test_gen_virtual.py:45,46,51,98`；新增 `test_audit_fixes_20261111.py:125,190,191` 为 F01/F04 新验收，非既有冲突 |
| **F04** | 文件字节 / 哈希断言 | `test_project_zip.py:66`（`out.open("rb").read(2) == b"PK"`，zip 魔数，非内容）；`test_gui_smoke.py:555-556`（`CIF_A.read_bytes()` 仅用于 `writestr` 造夹具）；`hashlib` / `sha256` / `hexdigest` 全库 **无** | 否 | 无任何内容字节、长度或哈希快照断言 |
| **F04** | 旧版 `.xinr` 是否仍兼容 | 读侧 `gui/project.py:211-214`（`csv.reader` + `float(r[0])` + `np.array(...,dtype=float)`）、`:204-206`（仅拒绝**高于**当前 `FORMAT_VERSION`）；新增 `test_audit_fixes_20261111.py:194-208` 手工构造 `.10g` zip 并断言可读 | 否 | **兼容成立**：`float()` / `load_pattern` 与有效数字位数无关；`.10g` 与 `.17g` 文本都能解析；`FORMAT_VERSION` 未变 |
| **F05** | 整份 JSON 深比对 `assert data == {...}` | **无** | — | `test_cli.py` 全文（85 行）无整份字典相等断言 |
| **F05** | 键集合断言 `set(...) == ...` / `data.keys()` | **无** | — | 无 `test_cli.py` / `test_texture.py` 中的键集合相等断言 |
| **F05** | 现有 CLI 报告断言（逐项） | `test_cli.py:31-36`（`rwp≈3.409617`、`len(phases)==2`、`fit.success is True`、`weight_pct is not None`）、`:43-45`（txt 含 `"Rwp"`/`"物相"`）、`:57-66`（两份 `rwp` 相等、`wa>wb`）、`test_texture.py:219-222`（`tex["anatase"]["axis"]==[0,0,1]`、`len(grid)==TEXTURE_N_GRID`）、`test_gui_smoke.py:244`（HTML 含 `Durbin-Watson`） | 否 | 全部为**字段级**断言；F05 是给 `texture` 子字典**新增** `model/degree/coeffs`（`cli/refine.py:357-360`），且保留 `axis`/`grid`（`:355-356`），故 `test_texture.py:221-222` 不受影响 |
| **F06** | GUI 测试断言步骤按钮**中文字符串** | **无** | — | 逐项排除：`test_i18n_project.py:78-80`（`tr("toolbar.new")` / `tr("step.cell")`，走译文）、`:140`（仅断言 `"–"` 标记）、`test_gui_smoke.py:51`（仅 `len(_step_buttons)==8`）、`:301-302`（菜单 `action.text()`，非步骤按钮）、`test_v16_gui.py:96-99`（测试自写的日志字面串）、`:140-143,244-250`（日志文本，标题取自 `STEPS` 元组而非按钮）、`test_gui_smoke.py:19`（仅导入 `STEPS` 计数） |
| **F06** | `catalog.py` 中 `step.*` 三语键齐全 | `catalog.py:40-43`(zh, 8 键)、`:148-152`(en, 8 键)、`:260-263`(ja, 8 键) | 否 | **8/8/8 齐全**；新增 `test_audit_fixes_20261111.py:252-258` 已守护 |
| **F06** | zh 文案与硬编码中文一致 | `dialogs.py:58-67` `STEPS` ↔ `catalog.py:40-43` | 否 | **8/8 逐字一致**：`零点 / 样品漂移`、`背景 + 峰形`、`标度因子`、`晶胞参数`、`峰形参数`、`原子坐标`、`温度因子`、`微结构 / 应力 / 择优取向` |

**结论**：F04 / F05 / F06 三项均**不存在会与之冲突的既有断言**，且各自的新增验收用例已由工程师落地（`test_audit_fixes_20261111.py:176-235,241-258`）。

### 10.2 F01 / F02 / F03「是否落在生产路径之外 / 默认配置不变」逐项确认

| 修复 | 精确改动点 | 是否生产路径之外 | 默认配置是否不变 | 现有测试文件与覆盖情况 | 独立判定 |
|---|---|---|---|---|---|
| **F01** | `core/refine/cell.py:169-170`（`_CELL_META` 追加 `name_mineral`）、`core/refine/recipe.py:655-656`（xyz 继承元组追加） | **否，需如实说明**：`structure_with_cell()`（`cell.py:173-184`）是生产函数，cell 步 / CLI / GUI 回写都走它（`:177-178` 注释明列）。但**新增字段本身**唯一读取点是 `core/profile/naming.py:118` 的 `getattr(struct,"name_mineral",None)`，仅用于 `phase_label` 展示；QPA / 前向 / 晶胞 / `crystal_system_of` 均不读 | **是**（未动任何 `RefineConfig` 字段或默认值） | 已有：`test_v16_naming_and_cell_axes.py:92-96`（断言 `st.name_mineral`）、`tests/test_cell*.py`、`tests/test_recipe.py`；新增 `test_audit_fixes_20261111.py:105-125`（含 `np.array_equal` 计算谱护栏） | 落在生产路径**内**但字段为纯展示 → **数值零影响**；此前「路径之外」的说法不够精确，此处修正 |
| **F02** | `core/refine/nonlinear.py:456`（legacy `_unpack` 补 `size_strain=base.size_strain`） | **是**：引擎主链 `refine()` 用 `_unpack_reg` → `reg.unpack`（`nonlinear.py:869,894`）；legacy `_unpack` 仅服务兼容 API 与测试 | **是**：`RefineConfig.refine_size_strain` 默认 `False`（`test_size_strain_phase.py:20-21` 明载）未动；`pack`/`bounds`/参数顺序均未动 | 覆盖很密：`test_registry.py:79-100`（`test_unpack_matches_legacy`）、`test_size_strain.py:138-174`、`test_size_strain_phase.py`、`test_aniso.py:96`、`test_texture.py:96`、`test_texture_harmonic.py:197`、`test_biso.py:67`；新增 `test_audit_fixes_20261111.py:131-137` | `test_unpack_matches_legacy` 只比对 `zero/U/V/W/eta/asym/bfactor/X/Y` + `cell` + `po_r`（`test_registry.py:95-100`），**不比对 `size_strain`**，故补字段不破坏该断言；工程师 13 文件子集 `173 passed` 佐证 |
| **F03** | `api.py:130-133`（`_solve_raw` 的 `RefineConfig` 补 `refine_po=request.refine_po`），另 `:113` 删死赋值 `pat=request` | **否**：`api.report()` → `_solve_raw()` 是公开生产入口，本次就是改它的配置 | **是**：`request.refine_po` 默认 `False`（`test_audit_fixes_20261111.py:161,170` 已守护），默认路径逐位不变 | 既有**无覆盖** `api.report()+refine_po`：`test_cli.py` 走 CLI（不经 `api.py`）、`test_p2_p46.py:82` 直接构造 `RefineConfig`、`test_dtypes_contract.py:36` 仅为字段集合；新增 `test_audit_fixes_20261111.py:143-170`（monkeypatch `solve` 捕获 config，2 项） | **唯一一项「不是生产路径之外」且会改变结果**：`refine_po=True` + `api.report()` 的 opt-in 路径**有意改变**（修复目的，非回归）；必须 release note 披露 |

### 10.3 一句总判定（红线）

> **F01–F06 全部实施后，「不改变 golden 逐位 / 默认配置路径数值结果」红线成立，六项均无需撤回**；但须把口径写清：F03 在 `refine_po=True` + `api.report()` 这条 **opt-in 路径上结果会变**（修复本身，不是回归），F04 使新写出的 `.xinr` / `.xinm` 中转文件体积可见增长（QA C18 实测完整 zip +16.8%、单 `pattern.csv` 文本 +113%），二者均须在发布说明披露，不能用笼统的「零数值变化」一笔带过。A11 / A12 不属 F 短名单，见 10.5 / 10.6。

### 10.4 本轮建议落地的测试改动方案（3 个确定性用例）与数量校准

**明确标记**：第 5 节给出的 3 个确定性用例，是本轮**唯一建议落地的测试文件改动方案**（其余 F01–F06 均为产品源码改动）。其内容为：

1. `test_run_all_cancel_never_records_fake_failure` —— 用调用计数谓词替换 `tests/test_v162_cancel.py:112-123` 的墙钟谓词，并删除源码从未承诺的 `assert records` / `assert res is not None`，换为 `all(r.status != "failed")` + `all(r.status in ("done","skipped"))` + `(res is None) == (len(records) == 0)`；
2. `test_cancel_at_any_checkpoint_keeps_contract` —— `@pytest.mark.parametrize("cancel_at",[1,2,3,10,40,10**9])`，6 档取消时机；
3. `test_cancel_preserves_completed_partial_results` —— `monkeypatch` 包 `run_step` 计数已完成步数，断言恰好保留前 2 条 `done` 记录。

**数量校准（以主理人指定的「替换 `:112-123`」为前提）**：

| 项 | 数量 |
|---|---|
| `tests/test_v162_cancel.py` 原有收集数 | **5**（`:52,:66,:84,:95,:112`） |
| 替换 `:112-123` 的 1 项 → 方案 ① | 1 |
| 新增方案 ②（6 档参数化） | 6 |
| 新增方案 ③ | 1 |
| 替换后该文件收集数 | **4 + 1 + 6 + 1 = 12**（净 **+7**） |
| 对全量基线的影响 | `532 → 539`（净 **+7**） |

**与实测工作树的对照**：工程师已按此方案落地（`tests/test_v162_cancel.py` diff 显示原用例名保留、函数体改写为计数谓词，并新增上述 ② ③，净 +7 与本节校准完全一致）。工程师另新建 `tests/test_audit_fixes_20261111.py`（F01–F06 验收 **11 项**），故全仓 `--collect-only` 实测 **550 = 532 + 7 + 11**（工程师报告值，本轮未重跑全量复验）。工程师给出的期望全量 `544 passed / 0 failed / 6 skipped` 属其预测，**须由任务 #4 实测确认**，本轮不代为背书。

### 10.5 A11 前置复核（ESD 文本表「值」列，新增）

| 复核点 | 证据（文件名:行号） | 结论 |
|---|---|---|
| `cli/refine.py:433` 的 `zip(esd.labels, esd.esd, esd.esd)` | `cli/refine.py:429-441` 的 `_esd_section()`；`:433` 把 `v` 与 `e` **都绑到 `esd.esd`**；`:435` `f"| {lab} | {v:.6g} | {ev} |"`；表头 `:431` 为 `| 参数 | 值 | e.s.d. |` | **确属显示缺陷**：「值」列输出的其实是 e.s.d. 数值（`.6g`），第三列 `ev=f"±{e:.3g}"`（`:434`）是同一个数的另一写法，参数真值从未出现 |
| `EsdResult` 是否有可用参数值字段（`values`/`x`/`params`） | `core/refine/esd.py:50-63` dataclass 字段逐项为 `labels, esd, covariance, correlation, scale_esd, weight_esd_pct, variance_factor, schur_consistency, n_points, n_params` | **无**。字段名确切清单见 `esd.py:54-63`；**不存在** `values` / `x` / `params` / `x_final` 字段 |
| 参数真值是否在别处可得 | `esd.py:112` 局部 `x_final = reg.pack(prm_base, cell_scales=cell, po_r=prm_base.po_r)`；`:137` 局部 `c = design(x_final)[2]`（线性 scale+bg 系数）；`:200-202` `labels = reg.labels() + scale[i] + bg[j]`；`:229-233` `return EsdResult(...)` | 真值向量应为 `concat(x_final, c)` 且与 `labels` 对齐，但二者**都是 `estimate_esd()` 的局部变量，未导出到 `EsdResult`**；JSON 报告 `cli/refine.py:484-493` 与 `core/report.py:71` 同样只有 `labels`/`esd` 无值字段 |
| 「1 行修复是否真的不改数值」 | — | **不成立**：没有现成字段可用，填真值必须扩 `EsdResult`（改 `esd.py:50-63` 与 `:229-233`，并牵动两处序列化），是**数据结构/API 变更**，不是 1 行小修。可 1–2 行且**确实不改任何数值**的最小处置是**删掉伪「值」列**（`:431` 表头改两列、`:433` 改 `zip(esd.labels, esd.esd)`、`:435` 改 `f"| {lab} | {ev} |"`），但那会改变 TXT 报告列数（报告格式变化，非数值变化）。**本轮建议维持不动**，与工程师「已登记未修」一致 |
| `tests/` 是否断言该段文本 | `_esd_section` 全库仅 `cli/refine.py:429` 定义、`:502` 在 `fmt=="txt" and esd is not None` 时调用；`tests/` 检索 `参数 e.s.d.` / `\| 参数 \|` / `--esd` / `_esd_section` **零命中** | **无任何测试断言该段文本**。相关测试均为直测 `estimate_esd()` 对象：`test_esd_geometry.py:51-54,192`、`test_texture.py:169-182`、`test_micro_initial_report.py:150-160`（`core/report.py` 的 HTML 含 `物相含量 e.s.d.`，非 CLI 段）、`test_registry.py:131-132`（`ps.esd`，registry 字段）、`test_gui_smoke.py:213`（结果表 label）；`test_cli.py` 全文未传 `--esd` |

### 10.6 A12 / F06 前置复核（`startswith(mark)` 是否会修不好，新增）

**源码现状**：`gui/main_window.py:1453-1460`

```python
def _on_step_finished(self, key, status, rwp, message) -> None:
    self._step_status[key] = status
    btn = self._step_buttons.get(key)
    title = next((s[1] for s in STEPS if s[0] == key), key)      # :1456 硬编码中文
    if btn is not None:
        mark = {"done": "✓", "skipped": "–", "failed": "!"}.get(status, "")   # :1458
        btn.setText(f"{mark} {tr(f'step.{key}')}"                # :1459（工程师已改为 tr）
                    if not btn.text().startswith(mark) else btn.text())        # :1460 仍保留
    self.log_line(tr("log.step_done").format(title=title, ...))  # :1463-1466 日志仍用中文 title
```

**语言切换 / 重译路径全链**：

| 路径 | 证据（文件名:行号） | 行为 |
|---|---|---|
| 菜单切语言 | `main_window.py:559-567` `switch_language()` → `:566` `self.retranslate()` | 必调 `retranslate()` |
| `retranslate()` | `main_window.py:516-557`，其中 `:530-533` `for step, btn in self._step_buttons.items(): mark = text[:2] if text and text[0] in "✓–!" else ""; btn.setText(f"{mark} {tr(f'step.{step}')}".strip())` | **无条件**重建**全部**步骤按钮（含带 `✓/–/!` 前缀的已完成按钮）为当前语言 |
| 打开工程改语言 | `main_window.py:770-776` `apply_project()` → `:774` `set_language(...)` → `:775` `self.retranslate()`；另 `:810-814` 对 `_step_status` 逐项 `btn.setText(f"{mark} {tr(f'step.{step}')}".strip())` | 恢复工程时同样按当前语言重建 |
| 按钮初建 | `main_window.py:400` `QPushButton(f"▶ {tr(f'step.{step}')}")` | 初始即走 `tr()` |

**结论一（主理人问「切语言后已完成步骤按钮是否真的会更新」）：会。** 切语言那一刻由 `switch_language() → retranslate():530-533` 无条件刷新全部按钮，与 `startswith(mark)` 无关。工程师离屏实证「zh `✓ 晶胞参数` → 切 en `✓  Cell parameters` → en 再完成 `✓  Cell parameters`，残留中文=False」与本链一致，我独立读码确认该链成立。

**结论二（A12 原始触发是否被修好）：是，但仅是「刚好修好」，护栏仍脆弱。** A12 触发条件是「切到 en/ja 后**再执行一步精修**」（架构报告 `:159`）：此时未跑过的按钮经 `retranslate` 后是纯译文（无 `✓` 前缀），`_on_step_finished` 的 `not btn.text().startswith("✓")` 为 `True` → 走 `:1459` 用 `tr(f'step.{key}')` 重建为英文。把 `title` 换成 `tr()` 恰好覆盖这一分支，故工程师的 1 行改动对**现有复现路径有效**。

**但 `startswith(mark)` 有三处残留风险，主理人的关切成立**：

1. **同前缀不刷新**：按钮已带与本次 `mark` 相同的前缀时，`:1460` 条件为 `False` → `btn.setText(btn.text())` 空操作，文本**不重建**。当前之所以无中文残留，是因为 `retranslate()` 已在切语言时先行刷新；一旦未来出现「改了语言但**未**经过 `switch_language`/`apply_project` 的 `retranslate()`」的路径（例如 worker 直接发 `step_finished`、或新增的 `set_language()` 调用点），陈旧中文会被永久保留。
2. **`mark=""` 恒不刷新**：`status` 不在 `{done,skipped,failed}` 时 `mark=""`（`:1458` 兜底），而 `"任意串".startswith("")` 恒为 `True` → 该分支永不刷新按钮。
3. **三处 mark 口径不一致**：`retranslate():532` 用 `text[:2]`（含空格，产出 `✓  Cell parameters` 双空格），`apply_project():814` 与 `_on_step_finished():1458` 用单字符 `mark`（产出 `✓ Cell parameters` 单空格），`初建:400` 用 `▶`。属显示层格式漂移，非数值问题。

**精确改法建议（只给方案，不写代码实现）**：让 `_on_step_finished` **无条件**以「当前状态 mark + `tr(f'step.{key}')`」重建按钮文本，删除 `:1459-1460` 的 `if not ... startswith(mark) else btn.text()` 条件分支，与 `retranslate():530-533` 完全同口径；`:1456` 的中文 `title` **保留**，仅继续供 `:1463-1466` 的 `log.step_done` 与 `_on_step_started():1444,1451` 的 `title_zh` 使用（日志按既有设计保持中文，`test_v16_gui.py:140-143` 依赖它）。顺带把 `retranslate():532` 的 `text[:2]` 改为单字符 mark 以消除双空格。该方案仍是 1 行级、纯显示文本、**不改任何数值结果**，且能同时消掉上述 3 处风险。

**验收用例补强建议**：现有 `test_audit_fixes_20261111.py:241-249` 只覆盖「切 en → 首次 `step_finished`（无前缀分支）」；`test_i18n_project.py:73-83` 只测切语言本身、不测 `step_finished`。**建议补一条专打 `startswith(mark)` 为真分支的用例**：zh 下先完成 `cell`（得到 `✓ 晶胞参数`）→ `switch_language("en")` → 再次 `win._on_step_finished("cell","done",...)` → 断言按钮文本含 `tr("step.cell","en")` 且不含 `晶胞参数`。工程师虽做了离屏手工实证，但未把它固化为 pytest 用例，这是覆盖缺口（不属撤回项，属加固项）。

### 10.7 本节补充结论表（与主表同列口径）

| 编号 | 现象 | 复现 / 证据 | 根因 | 归类 | 建议动作 | 是否改变数值结果 |
|---|---|---|---|---|---|---|
| **Q18** | F04/F05/F06 与既有断言是否冲突 | 10.1 表逐项 `文件名:行号`；哈希/字节/深比对/中文按钮断言均「无」 | 既有测试均为数值近似 / 字段级 / `tr()` / mark 级断言 | 可忽略（无冲突） | 无需改动既有测试；新增验收已落地 | **否** |
| **Q19** | F01/F02/F03 是否真的「路径之外 / 默认不变」 | 10.2 表；`cell.py:173-184`、`api.py:130-133` | F01 在生产函数内但字段纯展示；F03 就是改生产入口且 opt-in 结果会变 | 需澄清口径（非缺陷） | 文案不得笼统写「零数值变化」；F03 release note 披露 | F01/F02 **否**；F03 **条件性** |
| **Q20** | 6 项全实施后红线是否成立 | 10.3；golden 由 `test_golden_b.py` 活体守护，不经 `api.py`/`.xinr` | 全部改动落在元数据 / 兼容路径 / 入口配置 / 序列化 / 报告字段 / 显示文本 | 可忽略（成立） | **无需撤回任何一项**；按 10.3 披露 F03/F04 两处非零影响 | 默认路径 **否** |
| **Q21** | A11 ESD「值」列显示 e.s.d. 本身 | `cli/refine.py:433,435`；`esd.py:50-63` 无 `values/x/params`；真值只在 `esd.py:112,137` 局部变量 | 数据结构未导出参数值；`tests/` 零断言 | 产品缺陷（报告显示层，非数值） | **本轮不动**（与工程师一致）；若要修，最小安全解是删伪「值」列；填真值需改 `EsdResult` API，非 1 行 | **否** |
| **Q22** | A12 `startswith(mark)` 同前缀不刷新 | `main_window.py:1453-1460` 对 `:530-533`、`:810-814`、`:400` 全链读码 | `_on_step_finished` 用按钮文本前缀猜状态，与 `retranslate` 无条件重建不同口径 | 潜在产品缺陷（显示层，非数值） | 现有复现路径已被工程师 1 行修好；建议按 10.6「无条件重建」加固并补同前缀分支用例 | **否** |
| **Q23** | 时间线交叉 | `git status --short` / `git diff` 实测 F01–F06 + 测试已落地，任务 #3 `in_progress` | 复核到达前工程师已实施 | 流程事实（非缺陷） | 请主理人知悉：本复核为「落地后核验」；任务 #4 仍需实测全量与 golden | 不适用 |

### 10.8 收尾声明

- 本节除追加 `docs/audit-20261111-qa-baseline.md` 外**零写入**：未改任何 `.py` / 测试 / 配置 / 既有文档，未装包，未重跑全量 pytest，未 `git add/commit/push`，未访问工作目录之外的数据目录。
- 本节使用的 `git status` / `git diff` 为**只读**取证命令，不产生仓库写入。
- 第 1–9 节结论（A15 属测试时序脆弱、6 skip 清单、775 warnings 定性、确定性用例方案、F01–F06 初轮风险复核）**全部维持不变**；本节仅为表格化补证、数量校准与 A11/A12 两项新增前置复核。
- 任务 #4（全量回归 + golden 复验）仍须在任务 #3 完成后由我另行执行；本节所有「工程师报告值 / 期望值」均未经本轮全量复验，不代为背书。

