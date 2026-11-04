# 变更记录

## v1.0.0（2026-11-04）

首个完整版本：通用粉末衍射全谱拟合（Rietveld 结构精修 / 谱图精修）。

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

- 测试 **238 项全绿**；`bench_b` 家族 golden round-trip **8/8 PASS**（Rwp 3.41–4.04%，与移植前逐位一致）
- 虚拟样全基准 **18/18 PASS**（5 晶系 × 1–3 相 × 注入旋钮）
- 真实锚点：NCM811 实样收敛（Rwp 11.25% 登记）；**GSAS-II 5.8.2 交叉验证晶胞最大相对差 0.031%（实样）/ 0.015%（双相）**
- 本地二进制：PyInstaller onedir（GUI + CLI）+ Inno Setup 安装包（zh/en/ja）

### 已知限制

- TCH 尺寸应变的 X/Y 若精修后停在 0（分支切换点），其 e.s.d. 记为空值（导数无定义）
- 占位精修需锚定位点（单相全位点绝对占位被 scale 吸收，物理不可辨识）
- 多相 QPA 的 GSAS-II 交叉验证、FullProf/MAUD/Profex 对比为人工步骤
