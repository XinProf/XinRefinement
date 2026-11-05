# 变更记录

## v1.1.0（2026-11-05 发布）

主题：打通「物相检索（XinMatch）→ 全谱拟合精修（XinRefinement）」家族链路。
计划与格式契约见 [`docs/JOINT_PLAN_xinm_xinr.md`](docs/JOINT_PLAN_xinm_xinr.md)，
发布说明见 [`docs/RELEASE_NOTES_v1.1.0.md`](docs/RELEASE_NOTES_v1.1.0.md)，
安装包见 [Release v1.1.0](https://github.com/PolyXRD/XinRefinement/releases/tag/v1.1.0)。
配套版本：**XinMatch 3.4.0**。精修引擎、参数模型、CLI 参数与注册机制均未改动。

### 新增

- **导入 XinMatch 物相分析（`.xinm`）**：文件菜单新入口；装载谱图 + 已选物相 CIF +
  wavelength/anode 元数据；`structural=false` 的相（PDF2 类无结构条目）列为「仅参照」
  并提示手动补 CIF，不参与精修；导入内核 `core/io/xinm_import.py` 不依赖 Qt，
  GUI/CLI/库 API 共用，含 zip 炸弹防护与版本协商（version > 支持值提示升级）
- **工程文件升级 `.xinr`（自包含 zip 容器）**：默认内嵌谱图（规范 CSV，`%.10g`，
  往返相对误差 ≤ 1e-9）+ CIF + 完整精修结果（`result/refine.json`，与 CLI `--out`
  同族 schema：R 因子/参数/物相/收敛历史/diagnostics/e.s.d.），换机器/移目录后仍可
  打开精修；打开工程即回填结果摘要与收敛曲线，**无需重新精修即可复现上次结果**；
  扩展名分流——`.xinr` 走容器、`.xrp` 保持 v1.0.0 的 JSON 路径引用（**旧文件永久只读兼容**）；
  顺带修复 v1.0.0 `.xrp` 丢失 `phase_edits` 的问题
- **导入时晶胞/空间群一致性核对**：manifest 与 CIF 一致则预填 `phase_edits`（记录来源），
  显著不符（>0.1% 或 >0.05°）时以 CIF 为准并列清单提示，空间群符号做 `:1`/下划线归一化
  避免误报；`structural=true` 但包内缺 CIF 的相降级为「仅参照」并给出含文件名的原因
- **库 API**：`capabilities()` 新增 `xinm_import: "1"` 能力位

### 验证

- 新增 `tests/test_xinm_import.py`（13 项，含跨仓库 round-trip 与 S2/S3/S4 场景）、
  `tests/test_project_zip.py`（7 项，含 `result_full` 往返与缺 source 自包含打开）、
  `tests/test_joint_s1.py`（3 项，真实 COD 档案 7206075 + 9001681 全闭环）
- S1 数值保真：`.xinm` 导入后走公开 API → **Rwp 3.409617019598457（与 P0 黄金值逐位一致）**，
  定量 50.03 / 49.97 wt%；GUI 一键连跑口径下「导入路径」与「手动导入同谱图+CIF」
  Rwp 逐位相等；保存 `.xinr` 后删除临时谱图与 `.xinm` 重开，Rwp 复现（rel 1e-9）
- S2 混合来源：COD + 用户 CIF 相打包，PDF2 相仅参照且**包内无 ICDD 衍生文件**；
  S3 边界：缺 CIF / 损坏 zip / 缺谱图 / version=2 均给可读提示不崩溃
- 全量测试 259 → **286 项全绿**；i18n 三语补 `menu.import_xinm`

### 二进制与六轮验收

- 构建脚本修掉一处**假失败**：结尾 `print("⚠ …")` 在 GBK 控制台抛
  `UnicodeEncodeError`，产物已全部生成但退出码为 1（CI 会误判）。`main()` 现先
  `reconfigure(errors="replace")`。
- 六轮自动化全通过（报告 `.scratch/accept110.json`）：同源两次构建 exe **逐字节一致**
  （`a2c9fcc8…` / `7d1ed1ec…`）；两变体 CLI `--version` → `XinRefinement 1.1.0`；
  CLI 端到端 `rwp = 3.409617`；离屏 GUI 自检两变体分别报 `release/未注册` 与
  `internal/内部评估版本`；静默安装 606 文件 → 卸载 0 残留；正式版设
  `XINREFINEMENT_VARIANT=internal` 仍报 `release`（防绕过）。
- 发布件：`XinRefinement-1.1.0-setup.exe` 67,586,555 B
  （`046179e6f3ef45d6…`）、`XinRefinement-internal-1.1.0-portable.zip` 113,946,723 B
  （`a9012229b268bae3…`）。详见 `docs/RELEASE_NOTES_v1.1.0.md`。

## v1.0.0（2026-11-05 发布）

**首个正式发布版本。** 通用粉末衍射全谱拟合（Rietveld 结构精修 / Le Bail / 谱图精修）。

### 引擎

- **精修核心**：变量投影（线性 scale/背景解析消去）+ LM / scipy-trf 双后端；Pnma/R-3m 等全 230 空间群（spglib），含 H/R 设置与 Wyckoff 零空间自由坐标
- **参数模型**：声明式 `ParameterRegistry`（pack/unpack/bounds 与旧路径逐位一致），全晶胞按晶系约束（立方 1 → 三斜 6）
- **结构精修**：原子坐标（Wyckoff 约束）、各向同性 B、占位（含 `occ_anchor` 退化处理）
- **谱图精修**：零点/样品位移、背景三模式（Chebyshev/tent/手动点）、Caglioti+TCH 尺寸应变、η、asym、Kα1/Kα2、March-Dollase 多相 PO
- **定量与不确定度**：Hill-Howard QPA、Schur 补全参数 e.s.d.（含 scale/背景/含量）、DW 统计量
- **Le Bail**：无结构强度提取 + 多相定量；**CIF 写回**：晶胞/坐标/B/占位

### GUI（PySide6）

- 三区主窗口 + 8 步导航式精修（单步 / 一键连跑 / 后台线程 / 停止 / 回退）
- 交互图谱：实测/计算/残差双轴、背景曲线、每相峰位棒、框选缩放、相开关即时重绘
- **轴切换**：横轴 2θ ↔ d 值（Bragg 换算 d=λ/2sinθ，轴自动反向，标记条
  同步换算，波长取谱图 meta 缺省 Cu Kα1）；纵轴 counts ↔ 对数 ↔ √
  （FunctionScale）；轴标签左键循环、右键弹选单，悬停显示操作提示与手型
  光标，平移/框选激活时点击让位给工具栏
- **MAUD 式物相标记条**：主谱下方每相一条窄标记轴，左侧按相着色标注相名，
  布拉格棒高度 ∝ 相内相对强度（|F|²·LP 归一化）；残差面板高度收窄（1 → 0.55）
- **编辑 → 物相参数编辑**：按相编辑晶胞 a/b/c/α/β/γ（写回结构体，即时刷新
  标记条）、March–Dollase 择优取向 hkl+r（传导到前向模型与精修）、
  空间群/点群/劳厄群（显示与记录）；双击物相列表项直达；随 `.xrp` 持久化
- **精修菜单**：一键连跑（默认配置）/ 停止
- **帮助 → 关于**：家族版式（继承 XinMatch 版权主体 PolyXRD Team、联系方式
  与 Academic/Commercial 双许可，根目录 LICENSE / LICENSE-CN）
- **品牌资源**：logo / 窗口图标 / splash 启动画面来自项目 `assets/`
  （源码模式实时可换；打包时内置 `xinrefinement/data/assets/` 副本，
  三级回退：项目根 → PyInstaller `_MEIPASS` → 包内）
- **导航工具栏图标彩色化**：以 matplotlib 矢量源 SVG 按品牌色系重新着色
  （home 蓝 / back 橙 / forward 绿 / 平移紫 / 缩放青 / 子图红 / 编辑棕 /
  保存深蓝），同色系圆角浅底衬，QtSvg 高清渲染，失败静默回退原图标
- **功能按钮彩色图标**：新建（蓝文档+绿加号）/ 导入谱图（青·衍射峰形）/
  导入 CIF（紫·六边形晶格）/ ▶精修（绿·播放三角）/ 报告导出（橙·导出箭头），
  QPainter 程序化绘制（零素材依赖），16–48px 多尺寸高 DPI 清晰
- 齿轮弹窗：背景、晶胞（多物相分别勾选）、峰形、原子、温度因子、PO、微结构
- 结果区三页：摘要（R 因子/含量/DW/e.s.d.）、收敛曲线、相关性矩阵
- 三语 i18n（zh/en/ja，切换无需重启）、工程文件 `.xrp` 保存/恢复
- 报告导出：HTML + PNG + JSON 精修日志

### 命令行与 API

- `XinRefinementCLI refine <pattern> <cif...>`：`--recipe`（配方分步）、`--report`（HTML/PNG/JSON 目录）、`--quant`（WPF 定量）、`--esd`（Schur e.s.d.）、`--version`
- 公开库 API：`xinrefinement/api.py`（`RefineRequest`/`RefineResponse`、`refine`/`quant`/`report`/`capabilities`、`API_VERSION`）

### 双变体与注册（参照 XinMatch）

- **正式版（release）**：Inno Setup 安装包；接入 PolyXRD-Reg 离线注册机制
  （`xinrefinement/registration.py` 与 XinMatch 逐字同源、密钥一致，注册码互通），
  启动弹未注册版权提示，帮助菜单「输入注册码…」，状态栏右端「已注册：单位名 / 未注册」
- **内部评估版（internal）**：免安装便携 zip，不接注册；状态栏右端红字「内部评估版本」
- 变体由随包 `variant.txt` 固化（缺失按正式版处理，fail-safe）；冻结产物忽略环境变量，
  防止用 `XINREFINEMENT_VARIANT` 绕过注册提示
- 注册状态文件 `%APPDATA%\PolyXRD\Registration\XinRefinement.json`；
  开发方出码 `tools/make_reg_code.py "单位名"`
- 验收辅助：`XINREFINEMENT_SELFTEST_REG_OUT=<json>` 启动即导出变体/注册状态后退出

### 验收

- 测试 **259 项全绿**；`bench_b` 家族 golden round-trip **8/8 PASS**（Rwp 3.41–4.04%，与移植前逐位一致）
- 虚拟样全基准 **18/18 PASS**（5 晶系 × 1–3 相 × 注入旋钮）
- 真实锚点：NCM811 实样收敛（Rwp 11.25% 登记）；**GSAS-II 5.8.2 交叉验证晶胞最大相对差 0.031%（实样）/ 0.015%（双相）**
- 发布物：`XinRefinement-1.0.0-setup.exe`（Windows x64 安装包，zh/en/ja，含 PolyXRD-Reg 注册）；
  内部评估版 `XinRefinement-internal-1.0.0-portable.zip` 仅内部使用，不随 Release 分发
- **可复现构建**：构建脚本固定 `SOURCE_DATE_EPOCH`（= git HEAD 提交时间）与 `PYTHONHASHSEED=0`，
  消除 PyInstaller 的 PE 头时间戳与字符串集合哈希随机化两处非确定性——同一 commit 连续两次构建
  四个 exe 逐字节一致（安装包/zip 因内嵌时间戳仍会变，只做功能验收）

### 已知限制

- TCH 尺寸应变的 X/Y 若精修后停在 0（分支切换点），其 e.s.d. 记为空值（导数无定义）
- 占位精修需锚定位点（单相全位点绝对占位被 scale 吸收，物理不可辨识）
- 多相 QPA 的 GSAS-II 交叉验证、FullProf/MAUD/Profex 对比为人工步骤
