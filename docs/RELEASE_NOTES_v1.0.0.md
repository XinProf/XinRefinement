**首个正式发布版本。**

XinRefinement 是通用粉末衍射全谱拟合桌面软件（Rietveld 结构精修 / Le Bail / 谱图精修），
提供 Qt6 图形界面、命令行与 Python 库 API 三入口，覆盖「导入谱图 + 物相 CIF → 全谱拟合 →
定量与不确定度 → 报告」的完整工作流。与家族项目 XinMatch 分工：XinMatch 做峰形处理与物相分析，
XinRefinement 只做全谱拟合。

## 下载

| 文件 | 适用 | 说明 |
|---|---|---|
| `XinRefinement-1.0.0-setup.exe` | Windows x64 | 正式版安装包（简体中文 / English / 日本語），含 PolyXRD-Reg 离线注册 |

内部评估版（免安装便携 zip）仅内部测试使用，不在本 Release 分发。

## 主要能力

### 精修引擎

- 变量投影（标度因子与背景解析消去）+ LM / scipy-trf 双后端，带边界约束与多起点重启
- spglib 全 230 空间群，含 H/R 设置与 Wyckoff 位对称零空间自由坐标
- 峰形：Caglioti FWHM、TCH 尺寸/应变分离、η（pseudo-Voigt）、低角不对称、Kα1/Kα2 双线
- 结构：原子坐标、各向同性 B、占位；March–Dollase 择优取向
- 定量与不确定度：Hill–Howard QPA、Schur 补全参数 e.s.d.、Durbin–Watson
- Le Bail 强度提取 + 多相定量；CIF 写回（晶胞 / 坐标 / B / 占位）

### 图形界面

- 三区主窗口 + 8 步导航式精修（单步 ▶ / 齿轮设置 / 一键连跑 / 停止）
- MAUD 式物相标记条：每相一条，按相着色，棒高 ∝ 相内相对强度；残差面板收窄
- 轴切换：横轴 2θ ↔ d 值（Bragg 换算、自动反向），纵轴 counts ↔ log ↔ √；
  左键点轴循环、右键选单
- 编辑 → 物相参数编辑：晶胞六参数、March–Dollase 择优取向、空间群 / 点群 / 劳厄群
- 结果区三页：摘要（R 因子 / 含量 / DW / e.s.d.）、收敛曲线、相关性矩阵
- 三语界面（zh / en / ja，切换无需重启）、工程文件 `.xrp`、HTML+PNG+JSON 报告导出

### 命令行

```bash
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif -o out.json
XinRefinementCLI refine pattern.xy phase_a.cif phase_b.cif --recipe --report out_dir --quant --esd
```

## 验证数据

| 项目 | 结果 |
|---|---|
| 单元/集成测试 | 259 项全绿（引擎、GUI 离屏冒烟、CLI、i18n、注册与变体） |
| 合成基准 `bench_b`（家族 golden） | 8/8 PASS，Rwp 3.41–4.04%，与移植前逐位一致 |
| 全基准 `bench_full`（5 晶系 × 1–3 相） | 18/18 PASS |
| 真实样品 NCM811 | 收敛，Rwp 11.25% |
| 与 GSAS-II 交叉验证 | 晶胞最大相对差 0.031%（实样）/ 0.015%（双相） |

## 安装与注册

1. 运行 `XinRefinement-1.0.0-setup.exe`，可选安装语言；
2. 首次启动提示「本软件未注册，版权所有，禁止用于商业用途」——
   「确定」继续试用，或「输入注册码」完成注册；
3. 安装后开始菜单含 **XinRefinement**（GUI）与 **XinRefinementCLI**（命令行）。

注册码按「单位 / 部门名称」签发，离线校验、无需联网、同单位多机通用；
申请与技术支持：**sshztx@outlook.com**。

## 已知提示

- 未做代码签名，首次运行 Windows SmartScreen 可能提示「未知发布者」，选「仍要运行」。
- 注册码为离线 HMAC 校验（密钥随软件分发，属混淆级强度）。
- 安装包约 67 MB（含 Qt / matplotlib 运行时）；GUI 冷启动约 2–4 s。

## 许可

双许可：学术许可（非商业研究与教学）或另行申请商业许可。
版权所有 (c) 2026 PolyXRD Team。详见仓库 `LICENSE` / `LICENSE-CN`。
