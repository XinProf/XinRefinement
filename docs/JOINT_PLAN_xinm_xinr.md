# 联合计划：XinMatch 3.4.0 × XinRefinement 1.1.0

> **主题**：打通「物相检索（XinMatch）→ 全谱拟合精修（XinRefinement）」家族链路。
> **格式**：XinMatch 物相分析状态文件 `.xinm`；XinRefinement 工程文件 `.xinr`。
> **状态**：计划稿（待审阅，未提交任何代码）。

---

## 0. 目标与范围

| 项 | 内容 |
|---|---|
| 目标 | 用户在 XinMatch 完成检索/物相分析后，一键导出 `.xinm`；在 XinRefinement 导入该文件，自动装载谱图 + 物相 CIF，直接进入配方精修 |
| 范围内 | `.xinm` 导出/导入、`.xinr` 升级为自包含容器、COD CIF 回取桥、PDF2 无结构相边界处理 |
| 范围外 | 反向（XinRefinement → XinMatch 回写精修结果）留到 3.5/1.2 评估；在线 COD 查询；PDF2-2004 数据本身的外发 |
| 版本 | XinMatch **3.4.0**（当前 3.3.0）、XinRefinement **1.1.0**（当前 1.0.0） |
| 分工红线 | 不变：XinMatch 做检索/物相分析，XinRefinement 只做全谱拟合；注册码家族互通不变 |

---

## 1. 现状盘点（已核实）

| 事实 | 位置 | 对计划的影响 |
|---|---|---|
| XinMatch `Project` 已有全量 JSON 序列化（patterns / peaks / candidates / selected_phases / restraints / parameters，`to_dict/from_dict/save/load` 齐全） | `xinmatch/core/model/project.py:122-161` | `.xinm` 导出可直接复用，不必新写模型 |
| `Phase = Entry + scale_factor + two_theta_shift + weight_fraction + correlations` | `xinmatch/core/model/phase.py` | 导出"已选定物相"信息充足 |
| `Entry` 只有 entry_id / formula / d-I 峰表 / cell / space_group，**无原子坐标、无 CIF 路径** | `xinmatch/core/model/entry.py:68-110` | CIF 必须另行回取（见 §3） |
| `.xinDB` 库只存**库级** `cif_source`（建库时的 CIF 目录），不存 per-entry CIF 路径或内容 | `xinmatch/core/db/schema_v3.py:179,251` | COD CIF 回取要靠 entry_id 走外部资源 |
| XinRefinement `.xrp` 是纯 JSON dict，pattern/cifs 只存**外部路径**，缺文件仅提示不中断 | `xinrefinement/gui/project.py:53,62`、`gui/main_window.py:363-445` | 升级为自包含 zip 容器，同时兼容读旧 JSON |
| XinRefinement 谱图 meta 有 wavelength；画布轴切换已按 λ 换算 d 值 | `gui/canvas.py` | `.xinm` 里 wavelength 必须带上 |

---

## 2. 文件格式设计

### 2.1 `.xinm`（XinMatch 物相分析状态）—— zip 容器

纯 JSON 装不下谱图大数组 + 多个 CIF（10 万点谱图 JSON 化体积/速度都不可接受），采用 **zip 容器 + manifest.json**：

```
sample.xinm（zip）
├── manifest.json          # 结构见下
├── pattern/
│   └── pattern.csv        # two_theta,intensity 两列（规范化文本，跨版本稳）
└── cifs/
    ├── anatase_cod_9008220.cif
    └── rutile_cod_1011100.cif
```

`manifest.json` schema（`format: "xinm"`，`version: 1`，向后兼容只加不减字段）：

```json
{
  "format": "xinm",
  "version": 1,
  "created": "2026-11-05T12:00:00",
  "app": {"name": "XinMatch", "version": "3.4.0"},
  "pattern": {
    "file": "pattern/pattern.csv",
    "source_path": "D:/data/sample5.xy",
    "wavelength": 1.5406,
    "anode": "Cu",
    "tmin": 5.0, "tmax": 90.0, "step": 0.02,
    "metadata": {"instrument": "...", "sample": "..."}
  },
  "peaks": [{"two_theta": 25.3, "d": 3.52, "intensity": 100.0, "hkl": [1,0,1]}],
  "phases": [
    {
      "name": "anatase",
      "source": "cod",                    // cod | pdf2 | user_cif
      "entry_id": "9008220",
      "cif_file": "cifs/anatase_cod_9008220.cif",   // source=pdf2 时为 null
      "structural": true,                 // false = 峰位参照相，无原子坐标
      "fom": 0.87,
      "scale_factor": 1.0,
      "two_theta_shift": 0.0,
      "weight_fraction": 0.52,            // XinMatch 侧估的，仅供参考
      "cell": {"a":3.785,"b":3.785,"c":9.5196,"alpha":90,"beta":90,"gamma":90},
      "space_group": "I41/amd",
      "formula": "O2 Ti",
      "mineral_name": null
    }
  ],
  "candidates_summary": [                 // 前 N 个未选候选，供 XinRefinement 提示"还可补相"
    {"name": "brookite", "entry_id": "...", "fom": 0.61, "source": "cod", "cif_file": null}
  ],
  "restraints": {},
  "notes": ""
}
```

设计决策：
- **只导出 `selected_phases`**（可勾选），candidates 摘要默认只带 name/id/fom（不嵌 CIF，控制体积）。
- **谱图用 CSV 而非 JSON 数组**：float 列表 JSON 化 10 万点约 4 MB+，CSV 约 2 MB 且流式读写；精度 `%.10g`（往返相对误差 ≤ 1e-9，远超原始数据物理精度）。
- **PDF2-2004 版权边界**：`source="pdf2"` 的条目**只写 id/峰表元数据，不打包任何 ICDD 衍生数据文件**，`structural=false`；峰表（d/I）属于检索结果展示需要，随 `.xinm` 走由用户自行担保授权（与 DB Manager"请确认已获得正版授权"提示同一原则）。

### 2.2 `.xinr`（XinRefinement 工程文件）—— 升级为同构 zip 容器

| 项 | 现状（1.0.0） | 1.1.0 升级后 |
|---|---|---|
| 形态 | 纯 JSON，引用外部 pattern/cif **路径** | zip 容器：`manifest.json + pattern/ + cifs/ + result/` |
| 自包含 | 否，换机器/移目录后缺文件 | **默认内嵌**谱图与 CIF；保存对话框加"内嵌数据文件"勾选（默认开） |
| 兼容 | — | `load_project()` 按魔数分流：PK 头 → zip 容器；否则按旧 JSON 读（只读兼容，不回写） |
| 扩展 | result 只存 R 因子摘要 | result/ 增存完整精修 JSON（与 CLI `--out` 同 schema）、导航记录全量 |

---

## 3. CIF 获取策略（.xinm 导出侧，XinMatch 3.4.0）

`Phase.source` 三分支：

| source | CIF 来源 | 失败降级 |
|---|---|---|
| `user_cif` | 用户当初导入的 CIF 文件（XinMatch 结构查看已在用）→ 直接打包 | 文件被移走 → 导出对话框逐条列出，允许跳过（`cif_file=null, structural=false`） |
| `cod` | **COD 回取**：按 `entry_id` 查家族 COD 资源 → 解压出 CIF 打包 | 三级回退全失败 → 同上降级为无结构相 |
| `pdf2` | ICDD 无结构数据 → **不取**，恒 `structural=false` | — |

COD 回取探测顺序（`xinm_cif_bridge.py`，见 X-2）：
1. 设置项 `xinm.cod_cif_root`（用户显式指定 COD 根目录）；
2. 自动探测常见位置（✅ 已验证：`D:/Project/XRD/sync-COD/COD/`，布局
   `COD/{id[0]}/{id[1:3]}/{id[3:5]}/{id}.cif`，实测 anatase `9008220.cif` 命中；
   无机子集 `D:/Project/XRD/sync-COD/inorg_cif/COD/` 同布局）;
3. 查 `COD_inorganics.sqlite` 内嵌 `cif_gz`（家族共享库，如有）。

> 遗留调查项：`.xinDB` 未来（3.5+）可加 per-entry `cif_path` 列避免回取；本期不做重建库。

---

## 4. 任务拆解

### 4.1 XinMatch 3.4.0（编号 X-*）

| 编号 | 模块 / 路径 | 叶子方法（签名） | I/O | 验收标准 |
|---|---|---|---|---|
| X-1 | `core/io/xinm.py`（新） | `export_xinm(project: Project, path: Path, *, include_candidates: bool = True) -> Path` | Project → .xinm | zip 结构/manifest 字段与 §2.1 逐项一致；谱图 CSV 往返逐位一致（float `%.10g` 往返误差 0） |
| X-1a | 同上 | `_pattern_to_csv(p: Pattern) -> str` / `_csv_rows(...)` | Pattern → 文本 | 10 万点导出 < 1 s，文件 < 3 MB |
| X-1b | 同上 | `_phase_entries(project) -> list[XinmPhase]`（内部 dataclass） | Phase/Entry → dict | source 判定正确：用户 CIF / COD / pdf2 三分支覆盖测试 |
| X-2 | `core/io/xinm_cif_bridge.py`（新） | `locate_cif(entry_id: str, source: str) -> Path \| None` | id → CIF 路径 | 三级回退各自有测试；**先做一次性验证：确认本机 COD 布局与 COD_inorganics.sqlite 的 cif_gz 可按 id 取出** |
| X-2a | 同上 | `cod_cif_candidates() -> list[Path]`（探测根目录） | — | 找到 ≥ 1 个含目标 id 的资源；找不到返回空而非抛错 |
| X-3 | `ui/app.py` 菜单 | `export_xinm_dialog()` | GUI | 文件对话框扩展名 `*.xinm`；导出后状态栏报"已导出 N 相（M 个含结构）"；CIF 缺失时列清单允许跳过 |
| X-4 | `tests/test_xinm.py`（新） | — | — | 往返 round-trip（Project → .xinm → 校验）；pdf2 相不产生 cifs/ 文件；损坏 zip → 明确报错 |
| X-5 | `CHANGELOG.md` / 版本号 | `__version__` → 3.4.0 | — | 单源版本号更新，`--version` 输出 3.4.0 |

### 4.2 XinRefinement 1.1.0（编号 R-*）

| 编号 | 模块 / 路径 | 叶子方法（签名） | I/O | 验收标准 |
|---|---|---|---|---|
| R-1 | `core/io/xinm_import.py`（新，不依赖 GUI） | `read_xinm(path: Path) -> XinmPayload` | .xinm → dataclass | manifest 校验（format/version）；缺 pattern/cif 列出缺失项；zip 炸弹防护（解压上限 512 MB） |
| R-1a | 同上 | `load_pattern_csv(text) -> Pattern` | 文本 → 谱图 | 与 X-1a 往返逐位一致 |
| R-1b | 同上 | `importable_phases(payload) -> list[PhaseSpec]` | — | `structural=false` 的相被标记为"仅参照"（默认不加入精修，可勾选排除提示） |
| R-2 | `gui/project.py` | `save_project()` 升级为 zip 容器；`load_project()` 魔数分流（PK → 新格式；否则旧 JSON） | — | 旧 `.xrp` 全部能读；新 `.xinr` 保存后 manifest 含 pattern/cifs/落盘文件 |
| R-2a | `gui/main_window.py` | `project_state()` 增 `embed: bool`、result 完整 JSON | — | "内嵌数据文件"勾选后，工程不依赖外部路径（移走原文件仍可打开并精修） |
| R-3 | `gui/main_window.py` | `import_xinm_dialog()`（文件→导入 XinMatch 物相分析） | GUI → 界面 | 谱图装载、CIF 逐个 `_load_cif_paths`、`phase_edits` 预填 cell/space_group、wavelength 传导画布 d 轴 |
| R-3a | 同上 | `_apply_xinm_payload(payload)` | — | 导入后状态栏摘要"谱图 N 点 · 相 X 个（Y 个含结构）"；无结构相灰色列出并给"手动指定 CIF"按钮 |
| R-4 | i18n 三语 | 菜单/对话框/提示 keys | — | zh/en/ja 齐全，切换即时生效 |
| R-5 | `tests/test_xinm_import.py`（新） | — | — | 导入→`run_recipe_all` 全流程（合成样 .xinm）；旧 .xrp 兼容读；损坏文件错误信息可读 |
| R-6 | `tests/test_project_zip.py`（新） | — | — | .xinr 往返：保存→清空外部文件→打开→精修 Rwp 与保存前一致 |
| R-7 | `api.py` | `capabilities()` 增 `xinm_import: "1"` | — | 库 API 使用方可探测能力 |
| R-8 | 版本号 / CHANGELOG | `__version__` → 1.1.0 | — | 单源更新；CHANGELOG 记录互通能力 |

执行顺序建议：**X-2 验证先行**（半天级，决定 R-3 的可行性细节）→ X-1/X-3 → R-1/R-2 → R-3 → 测试收尾 → 双端同周发布。

---

## 5. 端到端验收场景

| 场景 | 步骤 | 通过标准 |
|---|---|---|
| S1 全闭环 | XinMatch 打开合成双相样 → 检索 → 选 2 个 COD 相 → 导出 `.xinm` → XinRefinement 导入 → 一键连跑 → 保存 `.xinr` | 精修 Rwp 与"手动导入同谱图+CIF"结果一致（同一代码路径）；`.xinr` 在移走原始文件后仍能打开并复现 |
| S2 混合来源相 | 选 1 个 COD 相 + 1 个用户 CIF 相 + 1 个 PDF2 相 | COD/用户 CIF 相进入精修；PDF2 相列在"仅参照"区，提示无结构；导出包里无 ICDD 衍生文件 |
| S3 异常边界 | `.xinm` 缺 CIF（源文件被移走）/ 损坏 zip / version=2（未来） | 各自给出可读提示，不崩溃；version 高于支持时提示升级软件 |
| S4 家族注册 | 两软件同机安装 | 注册码互通、状态文件各自独立（XinMatch.json / XinRefinement.json）不受影响 |

---

## 6. 风险与边界

| 风险 | 对策 |
|---|---|
| PDF2-2004 版权 | `.xinm` 不打包 ICDD 衍生数据文件；峰表元数据随导出走由用户担保授权（文档与导出对话框双提示） |
| COD 布局 / sqlite schema 与预期不符 | X-2 作为**先决调查项**先行验证，再定 R-3 细节 |
| 谱图 CSV 精度损失 | `%.10g` 往返零误差验证（X-1a/R-1a 双侧测试锁定） |
| `.xinr` 新旧格式分裂 | zip 魔数分流，旧 `.xrp` 永久只读兼容 |
| 两仓库节奏不同步 | 本文档为**单一事实源**（放 XinRefinement/docs，XinMatch 侧审阅后镜像）；格式版本号 `xinm.version` 升级需双端同步 |

---

## 7. 发布物

| 项目 | 版本 | 发布要点 |
|---|---|---|
| XinMatch | 3.4.0 | 「导出物相分析（.xinm）」菜单 + COD CIF 回取桥；沿用双变体/注册机制；安装包发布前五轮验收照旧（tools/verify_binary.py） |
| XinRefinement | 1.1.0 | 「导入 XinMatch 物相分析」+ `.xinr` 自包含容器 + 旧 `.xrp` 兼容；Release 仅 Setup，流程与 1.0.0 相同 |

---

## 8. 落地记录（2026-11-05，代码已实现，待二进制验收与发布）

X-1～X-5 / R-1～R-8 **全部落地**，双端全量测试绿。实际实现相对计划的偏差如下
（格式契约未变，仅模块拆分与枚举取值有出入）：

| 计划项 | 实际实现 | 偏差原因 |
|---|---|---|
| X-2 `core/io/xinm_cif_bridge.py` | 复用 `core/refine/cif_store.py`：`resolve_entry_cif()` + `_known_roots()` 多根回退 | 该模块已有 CIF 归档探测链（结构查看在用），再造一层属于重复实现 |
| X-3 `ui/app.py` 菜单 | `ui/main_window.py` `_export_xinm()` | 本工程菜单集中在 main_window，无独立 app.py |
| X-4 `tests/test_xinm.py` | `tests/io/test_xinm.py`（6 项，含真实档案 `96-900-8220` 锚点） | 跟随 `tests/io/` 既有布局 |
| `source` 三分支（cod/user_cif/pdf2） | 实为 **四值**：`cod` / `unresolved` / 保留 `user_cif` / `pdf2`；`structural` 由 CIF 回取成败决定，失败带 `reason` | 当前挂载库全部为 COD 家族 xinDB（`96-XXX-XXXX` ref_id），无 per-entry 用户 CIF 或 PDF2 结构；`unresolved` 让"id 形态不对"与"归档未命中"可区分 |
| 精度 `%.6g`（草稿） | `%.10g`（导出/导入双侧一致） | `%.6g` 对 float64 无法零往返；`%.10g` 相对误差 ≤1e-9，且 10 万点仍 <3 MB |
| `.xinr` 升级 | zip 容器 `format_version=2`，魔数分流；`.xrp` 永久只读兼容 | 与计划一致，另修复 v1.0.0 `.xrp` 丢失 `phase_edits` 的 bug |

已锁定的验证证据：
- XinRefinement：`tests/test_xinm_import.py`（8 项）与 `tests/test_project_zip.py`（5 项）全绿；
  跨仓库 round-trip 直接调用 XinMatch 真实导出器；S1 端到端 Rwp **3.409617** 与黄金值逐位一致。
- XinMatch：`tests/io/test_xinm.py` 6 项全绿，含真实 COD 归档 anatase 命中。
- 双端 `docs/JOINT_PLAN_xinm_xinr.md` 逐字节相同（本文件为镜像，单一事实源在 XinRefinement/docs）。

剩余（不属于代码，属于发布 —— 2026-11-05 更新）：
1. ~~XinMatch 3.4.0 版本对齐 + 双变体构建 + 五轮验收 + RELEASE-NOTES~~ ✅
   产物 `XinMatch-Setup-3.4.0.exe`（254,139,154 B）+ `XinMatch-Internal-3.4.0.zip`
   （368,486,794 B），`tools/verify_binary.py` 五轮全通过（`.scratch/binary_verify_340.json`）。
2. ~~XinRefinement 1.1.0 双变体 + Setup + 六轮验收~~ ✅
   产物 `XinRefinement-1.1.0-setup.exe`（67,586,555 B）+
   `XinRefinement-internal-1.1.0-portable.zip`（113,946,723 B），六轮自动化全通过
   （`.scratch/accept110.json`）。
3. **仍待人工**：两软件各一次双击目视验收（GUI 主流程 + 中文安装界面）；
   GitHub Release 上传需批准。
4. **仍待补**：S2 的 PDF2 混合来源相——当前挂载库全是 COD 家族，`source="pdf2"`
   只由合成 manifest 覆盖，没有真实 PDF2 条目走通全链路。接入 PDF2 数据后需补一条真实验收。
5. **已知风险（本机环境）**：COD 归档根随机器迁移从 `PolyXRD\cod\cif` 变到
   `sync-COD\COD`，`cif_store` 已加多根探测；`XINMATCH_XINDB_DIR` 用户环境变量同样过期
   （指向已删除的 `PolyXRD-DataBase\xindb`），已改指 `XinMatch-DataBase\data`。

