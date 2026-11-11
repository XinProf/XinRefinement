# A11 修复 + 1.6.3 版本升级 设计（只读设计，不改代码）

| 项 | 值 |
|---|---|
| 设计对象 | A11（e.s.d. 报表「值」列误填 e.s.d.）+ 版本号 1.6.2 → 1.6.3 |
| 仓库基线 | `D:/XinRefinement`，HEAD `e6ddef3`（本轮为纯设计，未改任何 `.py`/配置/文档） |
| 数值红线 | golden CLI Rwp = **3.4074156640940005**，逐位不变 |
| 交付边界 | 只读设计：不构建安装包、不发 Release、不跑全量 pytest |
| 日期 | 2026-11-11 |

> 前置核实（本设计全部基于实测行号，非猜测）：
> - `EsdResult` 定义 `core/refine/esd.py:50-63`；**唯一**构造点 `esd.py:229-233`（全仓 Grep `EsdResult(` 仅此一处 + 一处 docs 引用），**关键字参数**构造。
> - `estimate_esd` 的 `labels` 构造 `esd.py:200-202`；`x_final` 于 `:112`、`c` 于 `:137`；`n_total = p + q`（`:176`）。
> - CLI 文本 `_esd_section` `cli/refine.py:433-445`（错在 `:437`）；CLI JSON esd 段 `:483-493`。
> - `core/report.py` esd：`_log_dict:70-74`、`_html:111-117`。
> - 版本：`xinrefinement/__init__.py:7`、`packaging/inno/xinrefinement.iss:14`；`pyproject.toml:7,30` 为 `dynamic=["version"]`（无字面版本）。
> - 已完成的前序修复（本设计不对其改动）：F01 `cell.py:170`/`recipe.py:656`、F02 `nonlinear.py:456`、F03 `api.py:83,131`、F04 `project.py:133-134,218`/`main_window.py:711`、F05 `cli/refine.py:512`、F06 `main_window.py:1459`；取消连跑测试去脆弱化见 `tests/test_v162_cancel.py:112-131`（已改为调用计数谓词）。

---

## 1. `EsdResult` 扩字段设计

### 1.1 字段定义

```python
@dataclass(frozen=True)
class EsdResult:
    labels: tuple[str, ...]
    values: tuple[float, ...]              # ← 新增：与 labels 严格同序的参数真值 θ=(x,c)
    esd: tuple[float, ...]
    covariance: np.ndarray
    correlation: np.ndarray
    scale_esd: tuple[float, ...]
    weight_esd_pct: tuple[float, ...] | None
    variance_factor: float
    schur_consistency: float
    n_points: int
    n_params: int
```

- **名称**：`values`（与 `labels`/`esd` 并列，语义为「参数真值」）。
- **类型**：`tuple[float, ...]`（frozen dataclass，用不可变序列，与 `esd`/`scale_esd` 一致）。
- **位置**：紧随 `labels` 之后、`esd` 之前（保持「标签—真值—误差」三元组可读）。

### 1.2 向后兼容性判定（已用 Grep 硬核实）

- **唯一构造点**：`esd.py:229-233`，全部走关键字参数（`labels=…, esd=…`）。新增字段只需在构造处加 `values=…`，**不需要**改动顺序或给其它字段加默认值。
- **无位置参数调用者**：全仓 `EsdResult(` 仅 `esd.py:229` 一处（另 `docs/audit-20261111-qa-baseline.md` 仅文字提及），测试一律经 `estimate_esd()` 间接构造。→ 新增一个**无默认值**的必填字段是安全的（无旧位置调用会被打断）。
- **`dataclasses.replace`**：会从实例拷贝全部 init 字段，新增必填字段不需要额外传参，安全。
- **pickling / 落盘**：`EsdResult` **不进** `.xinr`（工程内 `result/refine.json` 存的是 `core/report.py::solve_result_dict` 的 dict，不含 EsdResult 对象）；无跨版本 pickle 需求。→ 加字段无序列化回退风险。
- **备选（若想对「假设存在的外部库用户」也保位置兼容）**：把 `values` 放到**最后**并给默认 `= ()`。代价：字段不在三元组旁、且依赖构造点显式传参覆盖。**推荐按 1.1（紧随 labels、必填）**，因为仓库内零位置调用、且 `values` 必须被填值才有意义（默认空 tuple 会让漏填静默）。

### 1.3 `estimate_esd` 内构造点与取值（`esd.py`）

- **构造位置**：`:229-233`（`return EsdResult(...)`）。
- **填值来源（名字与顺序）**：
  - `x_final = reg.pack(...)`（`:112`），长度 `p`，顺序 == `reg.labels()`（`registry.py:351-352` 与 `:365-371` 同一 `self._slots` 顺序，`unpack` `:400` 同序）。
  - `c` 来自 `r0, Aw, c, … = design(x_final)`（`:137`）；`solve_linear_detail` 返回 `coeffs = [S_1..S_P, b_0..b_{n_bg-1}]`（`linear.py:181` 明写；`bg_c = sol[len(keep):]` `:235`），即 `c[:n_phase]` = 各相 scale、`c[n_phase:]` = 背景系数（`esd.py:214` 亦用 `scales = c[:n_phase]` 印证）。
  - `labels`（`:200-202`）= `reg.labels()`(p) + `scale[i]`(n_phase) + `bg[j]`(n_bg)，长度 `n_total = p + n_phase + n_bg`。
  - `d`（esd）长度 `n_total`（`n_params`，`test_esd_geometry.py:49` 断言 `n_params == len(labels) == covariance.shape[0]`）。

- **对齐结论（关键，防贴错参数）**：

  ```
  θ = concat(x_final, c)          # 长度 p + q, q = n_phase + n_bg
  labels[ 0 : p ]              ↔ x_final        （reg 非线性参数，同序）
  labels[ p : p+n_phase ]      ↔ c[0 : n_phase] （scale[0..P-1]）
  labels[ p+n_phase : n_total] ↔ c[n_phase : ]  （bg[0..n_bg-1]）
  ```

  **`values = concat(x_final, c)` 与 `labels`、`esd` 三者严格同序、同长**（在 cheb/tent/interp 下 `len(c) == q`，故 `len(values) == n_total`）。
  建议在构造前加一行防御：`assert len(values) == n_total`（或 `== len(labels)`），把未来任何错位变成**显式失败**而非静默贴错。

- **建议插入点（`:200-202` 之后、`:229` 之前）**：

  ```python
  labels = (tuple(reg.labels())
            + tuple(f"scale[{i}]" for i in range(n_phase))
            + tuple(f"bg[{j}]" for j in range(n_bg)))
  values = tuple(float(v) for v in np.concatenate([x_final, c]))  # 与 labels 严格同序
  assert len(values) == n_total, (len(values), n_total)
  ```

  构造处改为：

  ```python
  return EsdResult(
      labels=labels, values=values, esd=tuple(float(v) for v in d),
      covariance=cov, correlation=corr, scale_esd=scale_esd,
      weight_esd_pct=weight_esd, variance_factor=s2,
      schur_consistency=consistency, n_points=m, n_params=n_total)
  ```

> **已知边界（预存问题，不属 A11，不扩大范围）**：`bg_mode="manual"` 时 `solve_linear_detail` 返回 `coeffs=[scales, ones(1)]`（`linear.py:201`）长度 `n_phase+1`，而 `labels` 按 `range(n_bg)` 追加 `n_bg` 个 `bg[j]`——若 `n_bg>1` 二者本就不等长（此时 `ycalc_fixed = (A @ c)` 已在 `esd.py:153` 维度不符）。即「manual 且 n_bg>1」的 esd 本就无法运行，与 A11 无关；本设计只在能正常出 esd 的模式（cheb/tent/interp，`len(c)=q`）保证对齐。

---

## 2. 三处序列化的精确改动

### 2.1 文本报告 `cli/refine.py:433-445` `_esd_section`

现状（`:435-439`）：

```python
rows = ["", "## 参数 e.s.d.", "| 参数 | 值 | e.s.d. |", "|---|---:|---:|"]
for lab, v, e in zip(esd.labels, esd.esd, esd.esd):      # ← :437 两列同源
    ev = "—（TCH 边界，无定义）" if not math.isfinite(e) else f"±{e:.3g}"
    rows.append(f"| {lab} | {v:.6g} | {ev} |")           # ← :439 值列=e.s.d.
```

改为：

```python
for lab, v, e in zip(esd.labels, esd.values, esd.esd):   # ← 值列取 values
    vv = "—" if not math.isfinite(v) else f"{v:.6g}"     # 值列 NaN -> 破折号
    ev = "—（TCH 边界，无定义）" if not math.isfinite(e) else f"±{e:.3g}"
    rows.append(f"| {lab} | {vv} | {ev} |")
```

- **表头** `| 参数 | 值 | e.s.d. |` 与分隔行**不变**（`:_esd_section` 用于 txt；`:501-502` 仅 txt 分支追加，非 JSON）。
- **格式化**：值列沿用 `:.6g`（6 位有效数字，与既有 `{v:.6g}` 字号一致、显示为主不改数值）；误差列沿用 `:.3g`。
- **NaN 处理（关键）**：
  - **e.s.d. 列**的 `NaN` 是 TCH 边界（X/Y 恰为 0，导数无定义）语义，保留 `—（TCH 边界，无定义）`（判据作用在 `e` 上，不变）。
  - **值列**：`values` 来自已解出的 `x_final`/`c`，正常为有限值（边界 X/Y 的值就是 0.0，正常显示）。仅作**防御**：若出现非有限值（不应发生），显示 `—`，避免 `nan` 字样污染报表。
- 其它行（`weight_esd_pct` `:440-442`、`s²/Schur` `:443-444`）**不动**。

### 2.2 JSON 报告 `cli/refine.py:483-493`（esd 段）

**建议新增 `values` 键，且与文本一致**。为便于单元测试且行为不变，建议把内联 dict 抽成小函数（行为等价重构，低风险）：

```python
def _esd_json_dict(esd) -> dict:
    return {
        "labels": list(esd.labels),
        "values": [_esd_val(v) for v in esd.values],     # ← 新增，与 labels 同序
        "esd": [_esd_val(v) for v in esd.esd],
        "scale_esd": [_esd_val(v, 8) for v in esd.scale_esd],
        "weight_esd_pct": (None if esd.weight_esd_pct is None
                           else [_esd_val(v, 4) for v in esd.weight_esd_pct]),
        "variance_factor": _round(esd.variance_factor),
        "schur_consistency": _round(esd.schur_consistency, 8),
    }
```

`_run`（`:483-493`）改为：`report["esd"] = _esd_json_dict(esd)`。

- **顺序**：`labels, values, esd, …`（与文本「参数/值/e.s.d.」同序）。
- **精度**：`values` 用 `_esd_val(v)`（默认 `n=6` → `round(v,6)`，与 `"esd"` 同档）；`_esd_val` 对非有限值返回 `None`（`cli/refine.py:427-430`），与 e.s.d. 的 NaN→`null` 口径一致。
- 其余键（`scale_esd` 8 位、`weight_esd_pct` 4 位、`variance_factor`、`schur_consistency`）**一律不变**。

### 2.3 `core/report.py`（HTML / `.xinr` 日志）

- `_log_dict:70-74` 的 esd 段仅有 `labels / esd / weight_esd_pct / schur_consistency`，**没有「值列」**（它按 label 列 e.s.d.，不存在「值列误填 e.s.d.」的问题）。
- `_html:111-117` 的 `esd_html` 仅在 `weight_esd_pct` 非空时输出「相 / 含量% / e.s.d.(pp)」表，**没有逐参数「值 | e.s.d.」表** → 也不存在 A11。
- **结论：`core/report.py` 不改**。理由：① 无 A11 缺陷；② `solve_result_dict` 经 `.xinr` 的 `result/refine.json` 被工程恢复读取，动其 schema 属额外面；③ `tests/test_micro_initial_report.py:159` 只断言 `len(log["esd"]["labels"]) == esd.n_params`，保持即可。
- （若未来想让 `.xinr` 自带参数真值，可另立任务把 `values` 也加进 `_log_dict`，本轮不做。）

---

## 3. 不改数值的论证（哪些行绝对不能动）

**只新增「把已算好的参数值复制一份进 tuple」，不新增/不重排任何数值计算。** `x_final`（`:112`）与 `c`（`:137`）本就为构造 Jacobian 而算好，A11 只是 `np.concatenate` 后 `float()` 化，**不参与** d/cov/corr 的任何运算。

**绝对不能动的行（e.s.d. 计算路径）**：

| 区域 | 位置 | 作用 | 处置 |
|---|---|---|---|
| reduced Jacobian | `esd.py:142` `j_red=_num_jacobian(...)` | 路径 1 | 不动 |
| ycalc fixed Jacobian | `esd.py:155` `jf=_num_jacobian(...)` | 路径 2 | 不动 |
| Schur/协方差组装 | `esd.py:156-198`（`s_red/s_schur/consistency/cov_xx/cov_xc/cov_cc/cov/corr`） | 全部 e.s.d. 数值 | 不动 |
| scale e.s.d. | `esd.py:203` `scale_esd = ...d[p:p+n_phase]` | scale 误差 | 不动 |
| 物相含量误差 | `esd.py:206-227` `weight_esd`（Hill–Howard 传播） | 含量 e.s.d. | 不动 |
| `d = sqrt(diag(cov))` | `esd.py:195-198` | 全参数 e.s.d. | 不动 |
| 线性层 | `linear.py:169+` `solve_linear_detail` | scale/背景解析解 | 不动 |
| 主引擎 | `nonlinear.py::refine` | Rwp/params/golden | 不动 |
| 格式化 | `cli/refine.py:427-430` `_esd_val`、`:438` `ev`、`:440-444` | 显示 | 不动（值列新增 `vv` 仅取值不改 e.s.d. 判据） |
| core 报告 | `core/report.py` | HTML/日志 | 不动 |

**golden 为何不受影响**：
1. golden 由 `tests/test_golden_b.py::test_golden_5050_bit_identical`（`:51-74`）经 `refine()` 断言 `tests/golden/method_b_roundtrip.json`，**全程不调用 `estimate_esd`**。A11 只在 `--esd` 后处理与报表层。
2. `values` 仅读 `x_final`/`c` 现有值，不写回 `res`、不改变 `reg.pack/unpack`、不改变 `solve_linear_detail` 的输入输出。
3. 因此 `refine()` 的 Rwp/params/晶胞/QPA 与所有 golden 逐位不变。

---

## 4. 版本号升级点（1.6.2 → 1.6.3）

### 4.1 校验逻辑（`tests/test_version_consistency.py`，已读全文）

- `:26-33` `test_iss_default_version_matches_package`：`iss` 的 `#define AppVersion "x.y.z"` **必须** == `xinrefinement.__version__`。
- `:36-48` `test_iss_has_no_other_hardcoded_version`：`iss` 除 `#define` 行外**不得**再出现字面版本号（其余处用 `{#AppVersion}`）。
- `:51-57` `test_build_script_passes_version_to_iscc`：`tools/build_binaries.py` 须含 `/DAppVersion=`（已满足，不需改）。

### 4.2 需要同步的位置（精确）

| 文件:行号 | 现值 | 改为 | 说明 |
|---|---|---|---|
| `xinrefinement/__init__.py:7` | `__version__ = "1.6.2"` | `__version__ = "1.6.3"` | 唯一真相源 |
| `packaging/inno/xinrefinement.iss:14` | `#define AppVersion "1.6.2"` | `#define AppVersion "1.6.3"` | 位于 `#ifndef AppVersion`(`:13`) 内，是 ISCC 的兜底默认值 |
| `CHANGELOG.md`（`:1` 之后、`:3` 之前插入） | — | 新增 `## v1.6.3（2026-11-11）…` | 见 4.4 结构 |

- `pyproject.toml:7` `dynamic=["version"]` + `:30` `version={attr="xinrefinement.__version__"}` → **自动取 `__init__`，无需改**。
- `tools/build_binaries.py` → 无需改（构建时读 `__version__`，本轮不打包）。

### 4.3 明确**不能改**的位置（历史/注释，Grep `1.6.2` 命中）

- 代码历史注释：`gui/workers.py:58,87`、`gui/main_window.py:1541`、`core/refine/site.py:331`、`core/refine/recipe.py:74,929`、`core/refine/cell.py:292`（均 `# v1.6.2：…` 记录**该能力何时引入**，改了就篡改历史）。
- 测试 docstring：`tests/test_v162_cancel.py:1`、`tests/test_i18n_project.py:146`。
- 文档：`docs/RELEASE_NOTES_v1.6.2.md`（整份）、`docs/立项-MAUD对标改进计划-v1.md`（§1.16 等历史）、`docs/audit-20261111-*.md`（历史审计）。
- `CHANGELOG.md:3` 的 `## v1.6.2` 条目（历史，新增 v1.6.3 置于其**上方**，旧条目不删不改）。

### 4.4 `CHANGELOG.md` 新增 v1.6.3 条目（建议结构，日期 2026-11-11，不含未做的构建/发布）

```markdown
## v1.6.3（2026-11-11）：e.s.d. 报表值列修正 + 审计低风险修复

主题：修复 A11（e.s.d. 文本/JSON 报表的「值」列误填 e.s.d.、参数真值缺失），
并收纳上一轮全局代码审计的 6 项低风险修复。**引擎与数值路径零改动**
（golden CLI Rwp 逐位不变）。

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
- 本轮仅升版本号（`xinrefinement.__version__`、Inno Setup `AppVersion`）并更新本
  CHANGELOG；**不构建安装包、不发 Release**。
- 基线档位：文档权威值 532 passed / 0 skipped 需「本机 COD 档案 + XinMatch/gemmi 齐全」；
  缺这些外部依赖的仓库自足档为 1 failed / 525 passed / 6 skipped（详见
  `docs/audit-20261111-architecture.md` 第 2.4 节 / C10）。
```

---

## 5. 验收用例设计（可直接粘贴）

### 5.1 文本报告值列正确（`tests/test_cli_esd_report.py` 新建）

```python
"""A11：e.s.d. 文本报表「值」列 = 参数真值，e.s.d. 列 = esd。"""
import math
import numpy as np
import pytest

from xinrefinement.core.refine.esd import EsdResult
from xinrefinement.cli.refine import _esd_section


def _mk_esd() -> EsdResult:
    labels = ("global.zero", "phase[A].micro.X", "scale[0]", "bg[0]")
    values = (0.0123, 0.0, 1.5e-2, 42.0)
    esd = (0.0004, float("nan"), 2.0e-3, 0.7)   # 第 2 个是 TCH 边界 NaN
    n = len(labels)
    return EsdResult(
        labels=labels, values=values, esd=esd,
        covariance=np.eye(n), correlation=np.eye(n),
        scale_esd=(2.0e-3,), weight_esd_pct=None,
        variance_factor=1.5, schur_consistency=0.01,
        n_points=1000, n_params=n)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def test_esd_section_value_column_is_parameter_value():
    esd = _mk_esd()
    rows = [r for r in _esd_section(esd)
            if r.startswith("| ") and "参数" not in r and "---" not in r]
    got = {_cells(r)[0]: _cells(r)[1:] for r in rows}

    # 值列 == 参数真值；e.s.d. 列 == esd（不是同一个数）
    assert got["global.zero"] == [f"{0.0123:.6g}", "±0.0004"]
    assert got["scale[0]"] == [f"{1.5e-2:.6g}", "±0.002"]
    assert got["bg[0]"] == [f"{42.0:.6g}", "±0.7"]
    # TCH 边界：值列显示真实值（0），e.s.d. 列显示边界标注
    assert got["phase[A].micro.X"] == [f"{0.0:.6g}", "—（TCH 边界，无定义）"]
    # 防止复现旧 bug：值列不能等于 e.s.d.
    assert got["global.zero"][0] != got["global.zero"][1].lstrip("±")
```

### 5.2 JSON esd 段字段一致（同文件，需配合 2.2 的 `_esd_json_dict` 抽取）

```python
def test_esd_json_has_values_matching_labels():
    from xinrefinement.cli.refine import _esd_json_dict
    esd = _mk_esd()
    d = _esd_json_dict(esd)
    assert list(d)[:3] == ["labels", "values", "esd"]
    assert len(d["values"]) == len(d["labels"]) == len(d["esd"])
    # 值列 = 参数值（round 6）；e.s.d. 列 NaN -> None
    assert d["values"][0] == round(0.0123, 6)
    assert d["esd"][1] is None
    assert d["values"][1] == round(0.0, 6)      # 边界参数的值仍是 0，不是 None
```

> 若暂不抽 `_esd_json_dict`，退化为端到端：以 `tests/data/virtual_b/v50_wide.xy` +
> `xinrefinement/data/{anatase,rutile}.cif` 走 `python -m xinrefinement refine --esd -o out.json`，
> 读 `json.load` 断言 `report["esd"]["values"]` 存在、长度 == `labels`（耗时约数秒）。

### 5.3 版本号三处一致（追加进 `tests/test_version_consistency.py`）

```python
def test_version_three_way_consistent() -> None:
    """__version__ == iss AppVersion == CHANGELOG 最新标题。"""
    import re
    import xinrefinement

    ver = xinrefinement.__version__
    iss = _ISS.read_text(encoding="utf-8")
    m = re.search(r'^#define\s+AppVersion\s+"([^"]+)"', iss, re.MULTILINE)
    assert m and m.group(1) == ver, (m and m.group(1), ver)

    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    head = re.search(r'^##\s+v([0-9]+\.[0-9]+\.[0-9]+)', changelog, re.MULTILINE)
    assert head and head.group(1) == ver, (
        f"CHANGELOG 最新版本 {head and head.group(1)} != __version__ {ver}")
```

（`_ISS`、`REPO` 已在该文件顶部 `:22-23` 定义，可直接复用。）

### 5.4 values 与 labels 对齐（防贴错参数；追加进 `tests/test_esd_geometry.py` 现有 esd 用例）

现有用例（`:47-64`）已拿到 `out`（`EsdResult`）与 `res`（`SolveResult`），直接追加：

```python
    # A11：values 与 labels/esd 同长同序，且真值等于 solve 的参数
    assert len(out.values) == len(out.labels) == out.n_params
    idx = {lab: i for i, lab in enumerate(out.labels)}
    assert out.values[idx["global.zero"]] == pytest.approx(res.params.zero, abs=1e-12)
    # scale[i] 的值 == 对应相的 scale（防 scale/bg/非线性三类贴错位）
    sidx = [i for i, lab in enumerate(out.labels) if lab.startswith("scale[")]
    for i, ph in zip(sidx, res.phases):
        assert out.values[i] == pytest.approx(ph.scale, rel=1e-6, abs=1e-9)
```

> `rel=1e-6` 容差：`values` 的 scale 来自 `solve_linear_detail` 在收敛点的解，与
> `res.phases[i].scale` 同源同点，理论应 ~1e-10 一致；给 1e-6 余量避免个别病态
> 数据集抖动。`global.zero` 用 `abs=1e-12`（`values` 直接来自 `reg.pack(res.params)`，
> 应逐位一致）。

---

## 6. 风险与回退

| 风险 | 评估 | 缓解 |
|---|---|---|
| 加必填字段破坏调用方 | **低**：全仓唯一构造点 `esd.py:229` 为关键字调用，无位置调用者（Grep 证实） | 只改该处；测试全走 `estimate_esd()` |
| pickling / 落盘不兼容 | **无**：`EsdResult` 不落盘（`.xinr` 存 `solve_result_dict` 的 dict），无跨版本 pickle | — |
| `dataclasses.replace` | **无影响**：replace 拷贝全部 init 字段 | — |
| values/labels 错位 | **中→降为低**：靠 `assert len(values)==n_total` + 5.4 对齐用例兜底 | 已在 1.3 加防御断言 |
| manual 背景模式 `len(c)!=q` | **预存问题，非本轮引入**（该模式 esd 本就跑不通，`esd.py:153` 维度不符） | 本设计仅在可用模式保证对齐，文档标注 |
| 报表数值被误改 | **低**：只读 `x_final`/`c` 复制，不动 d/cov/corr/scale/weight 计算 | 第 3 节红线清单 + 5.4 对齐用例 |
| 测试套运行时 | **低**：5.1/5.2/5.3 纯构造、毫秒级；5.4 复用现有 refine 夹具，不新增精修 | 无新增重计算 |
| 版本漏同步 | **低** | 5.3 三处一致用例 + 既有 `test_version_consistency.py` |

**回退方式（任何一项出问题）**：

1. **A11 回退**：恢复 `esd.py:229-233` 构造（去 `values=`）、删 `esd.py:200-202` 后新增的 `values=`/`assert` 两行、`_esd_section` 的 `zip` 第三参改回 `esd.esd`、删 `_esd_json_dict` 的 `"values"` 键（或还原内联 dict）。均为 1:1 反转，无连锁。
2. **版本回退**：`__init__.py:7`、`iss:14` 改回 `1.6.2`；删除 `CHANGELOG.md` 的 v1.6.3 条目。
3. 因所有改动均**旁路/报表/元数据**，回退后 golden 与全量纯源码用例逐位回到改动前状态。

---

## 7. 改动清单（给 Engineer 的最小面）

| # | 文件:行号 | 改动 | 行数 |
|---|---|---|---|
| 1 | `core/refine/esd.py:50-63` | `EsdResult` 在 `labels` 后加 `values: tuple[float, ...]` | +1 |
| 2 | `core/refine/esd.py:200-202` 后 | 新增 `values = tuple(float(v) for v in np.concatenate([x_final, c]))` + `assert` | +2 |
| 3 | `core/refine/esd.py:229-233` | 构造加 `values=values` | +1 |
| 4 | `cli/refine.py:437,439` | `zip(...,esd.values,esd.esd)` + 值列 `vv` 格式化 | 改 2 |
| 5 | `cli/refine.py:483-493` | 抽 `_esd_json_dict`（含 `"values"`）并 `report["esd"]=_esd_json_dict(esd)` | 重构 |
| 6 | `xinrefinement/__init__.py:7` | `"1.6.2"`→`"1.6.3"` | 1 |
| 7 | `packaging/inno/xinrefinement.iss:14` | `"1.6.2"`→`"1.6.3"` | 1 |
| 8 | `CHANGELOG.md`（`:1` 后） | 插入 v1.6.3 条目（4.4 结构） | 新增 |
| 9 | `tests/test_cli_esd_report.py` | 5.1/5.2 用例 | 新建 |
| 10 | `tests/test_version_consistency.py` | 5.3 用例 | +1 函数 |
| 11 | `tests/test_esd_geometry.py` | 5.4 追加 4~6 行断言 | +6 |

**不改**：`core/report.py`、`linear.py`、`nonlinear.py`、`solve.py`、`project.py`、`main_window.py`（除已完成的 F 项）、`pyproject.toml`、`tools/build_binaries.py`、任何历史注释/文档。
