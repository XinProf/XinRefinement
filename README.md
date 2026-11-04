# XinRefinement

**通用粉末衍射全谱拟合（Rietveld 结构精修 / 谱图精修）桌面软件。**

承接 XinMatch 的数据精修职责：XinMatch 做峰形处理 + 物相分析，本项目只做全谱拟合。

- 方案：`docs/PROJECT_PLAN.md`
- 任务手册：`docs/TASKS.md`
- 验收清单：`docs/RELEASE_1.0.0.md`

## 运行

```bash
D:/Project/XRD/python310/python.exe -m pytest -q          # 测试
D:/Project/XRD/python310/python.exe -m xinrefinement.gui   # 界面（P3 后可用）
```

## 命令行精修（M0 已可用）

```bash
D:/Project/XRD/python310/python.exe -m xinrefinement.cli refine ^
  tests/data/virtual_b/v50_wide.xy ^
  xinrefinement/data/anatase.cif xinrefinement/data/rutile.cif ^
  -o report.json --peak-height
```

输出 JSON/TXT 报告（R 因子、峰形参数、物相含量、背景系数、收敛历史）。
API 入口：`from xinrefinement.core.refine.solve import RefineInputs, solve`。
