"""P3.1 · 主窗口三区骨架（对照草图 pre-temp/0.jpg）。

布局：菜单 + 工具栏 / 左（物相列表 + 参数树占位）/ 中（交互图谱 + 缩放工具栏）
/ 右（导航式精修面板「▶执行 + ⚙设置」+ 结果区）。

本卡用 **P0/M0 已就绪的引擎**（``core.refine.solve``）跑真实精修，不依赖
P1 通用化；导航配方（P3.3）、后台线程（P3.3）、i18n（P3.6）后续接入。
当前精修在 UI 线程同步执行（虚拟样量级 < 1 s）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.profile.struct import compute_peaks
from xinrefinement.core.refine.linear import background_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.solve import RefineInputs, solve
from xinrefinement.gui.canvas import PatternCanvas
from xinrefinement.gui.dialogs import STEPS, open_settings


class MainWindow(QMainWindow):
    """XinRefinement 主窗口。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("XinRefinement · 全谱拟合（结构精修 / Rietveld）")
        self.resize(1180, 720)
        self._pattern = None
        self._phases: list = []
        self._result = None
        self._settings: dict[str, dict] = {}
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self.statusBar().showMessage("就绪：导入谱图与 CIF 后执行精修")

    # -- 构建 ---------------------------------------------------------- #
    def _build_menu(self) -> None:
        bar = self.menuBar()
        for name in ("文件(&F)", "编辑(&E)", "精修(&R)", "设置(&S)", "帮助(&H)"):
            bar.addMenu(name)
        fm = bar.actions()[0].menu()
        act = QAction("导入谱图…", self)
        act.triggered.connect(self.open_pattern)
        fm.addAction(act)
        act = QAction("导入 CIF…", self)
        act.triggered.connect(self.open_cif)
        fm.addAction(act)

    def _build_toolbar(self) -> None:
        tb = QToolBar("主工具栏", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        for label, slot in (("新建", self.new_project), ("导入谱图", self.open_pattern),
                            ("导入CIF", self.open_cif), ("▶精修", self.run_refine),
                            ("报告导出", self.export_report)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            tb.addWidget(btn)

    def _build_body(self) -> None:
        split = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(split)

        # 左：物相列表 + 参数树占位
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("物相列表"))
        self.phase_list = QListWidget()
        self.phase_list.itemChanged.connect(self._on_phase_toggled)
        lv.addWidget(self.phase_list)
        lv.addWidget(QLabel("精修参数树（P3.3 接入配方）"))
        self.param_tree = QListWidget()
        self.param_tree.addItems(["全局：零点 / 背景 / 峰形", "结构：晶胞 / 坐标 / B"])
        lv.addWidget(self.param_tree)
        split.addWidget(left)

        # 中：交互图谱
        center = QWidget()
        cv = QVBoxLayout(center)
        self.canvas = PatternCanvas()
        cv.addWidget(self.canvas, 1)
        cv.addWidget(NavigationToolbar2QT(self.canvas, center))
        split.addWidget(center)

        # 右：导航式精修面板 + 结果区
        right = QWidget()
        rv = QVBoxLayout(right)
        nav = QGroupBox("导航式精修")
        nv = QVBoxLayout(nav)
        self._step_buttons: dict[str, QPushButton] = {}
        for step, title, _cat in STEPS:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            run = QPushButton(f"▶ {title}")
            run.setToolTip("执行该步骤（当前调用统一精修入口）")
            run.clicked.connect(lambda _c=False, s=step: self.run_step(s))
            gear = QPushButton("⚙")
            gear.setFixedWidth(32)
            gear.setToolTip(f"打开「{title}」详细设置")
            gear.clicked.connect(lambda _c=False, s=step, t=title:
                                 self.open_step_settings(s, t))
            hl.addWidget(run, 1)
            hl.addWidget(gear)
            nv.addWidget(row)
            self._step_buttons[step] = run
        self.btn_run_all = QPushButton("▶ 一键连跑（配方，P3.3 接入）")
        self.btn_run_all.setEnabled(False)
        nv.addWidget(self.btn_run_all)
        rv.addWidget(nav)

        res = QGroupBox("精修结果")
        rl = QVBoxLayout(res)
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(["指标", "值"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        rl.addWidget(self.result_table)
        rv.addWidget(res, 1)
        split.addWidget(right)
        split.setSizes([220, 660, 300])

    # -- 交互 ---------------------------------------------------------- #
    def new_project(self) -> None:
        self._pattern = None
        self._phases.clear()
        self._result = None
        self.phase_list.clear()
        self.canvas.clear()
        self.result_table.setRowCount(0)
        self.statusBar().showMessage("已新建工程")

    def open_pattern(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入谱图", "", "谱图 (*.xy *.txt *.dat *.csv *.xye);;所有文件 (*)")
        if path:
            self._load_pattern_path(Path(path))

    def _load_pattern_path(self, path) -> bool:
        """加载谱图（供文件对话框、测试与未来 XinMatch 对接共用）。"""
        try:
            self._pattern = load_pattern(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "谱图读取失败", str(exc))
            return False
        self.canvas.show_pattern(self._pattern.two_theta,
                                 self._pattern.intensity)
        self.statusBar().showMessage(f"谱图：{Path(path).name} "
                                     f"({self._pattern.two_theta.size} 点)")
        return True

    def open_cif(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入 CIF（可多选）", "", "CIF (*.cif);;所有文件 (*)")
        if paths:
            self._load_cif_paths([Path(p) for p in paths])

    def _load_cif_paths(self, paths) -> int:
        """加载多个 CIF 物相，返回成功导入数。"""
        added = 0
        for p in paths:
            try:
                st = parse_cif(Path(p))
            except Exception as exc:
                QMessageBox.warning(self, "CIF 解析失败", f"{Path(p).name}: {exc}")
                continue
            if any(s.name == st.name for s in self._phases):
                continue
            self._phases.append(st)
            item = QListWidgetItem(st.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.phase_list.addItem(item)
            added += 1
        self._refresh_sticks()
        self.statusBar().showMessage(f"已导入 {len(self._phases)} 个物相")
        return added

    def _refresh_sticks(self) -> None:
        """按每相结构算布拉格峰位棒（用 core 前向模型的峰枚举）。"""
        if not self._phases:
            return
        sticks = []
        for st in self._phases:
            try:
                peaks, _skipped = compute_peaks(st, 1.5406, 5.0, 90.0)
                sticks.append((st.name, [float(p[0]) for p in peaks]))
            except Exception:
                sticks.append((st.name, []))
        self.canvas.set_phase_sticks(sticks)

    def _on_phase_toggled(self, item: QListWidgetItem) -> None:
        self.canvas.set_phase_visible(item.text(),
                                      item.checkState() == Qt.Checked)

    def open_step_settings(self, step: str, title: str) -> None:
        names = [s.name for s in self._phases]
        got = open_settings(step, title, names,
                            self._settings.get(step), self)
        if got is not None:
            self._settings[step] = got
            self.statusBar().showMessage(f"已更新「{title}」设置")

    def run_step(self, step: str) -> None:
        """单步执行：当前所有步骤共用统一精修入口（P3.3 接配方分组）。"""
        self.run_refine()

    def run_refine(self) -> None:
        if self._pattern is None or not self._phases:
            QMessageBox.information(self, "无法精修", "请先导入谱图和至少一个 CIF")
            return
        bg = self._settings.get("bg", {})
        cfg = RefineConfig(
            refine_zero=True, refine_uvw=True, n_bg=int(bg.get("n_bg", 3)),
            bg_mode=bg.get("bg_mode", "cheb"),
            tmin=5.0, tmax=90.0, max_iter=40)
        prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                            anode="Cu", integrated=False)
        try:
            res = solve(RefineInputs(pattern=self._pattern, phases=self._phases,
                                     profile=prm, config=cfg))
        except Exception as exc:
            QMessageBox.warning(self, "精修失败", str(exc))
            return
        self._result = res
        # 背景系数 -> 背景曲线（与精修同一组基函数，界面与报告口径一致）
        try:
            bg_curve = background_basis(
                res.pattern.two_theta, len(res.background), cfg.bg_mode
            ) @ np.asarray(res.background, dtype=float)
        except Exception:
            bg_curve = None
        self.canvas.show_fit(res.pattern.two_theta,
                             res.pattern.intensity, res.ycalc,
                             background=bg_curve)
        self._fill_results(res)
        self.statusBar().showMessage(
            f"精修完成：Rwp={res.rwp:.3f}%  success={res.success}")

    def _fill_results(self, res) -> None:
        rows = [("Rwp (%)", f"{res.rwp:.4f}"), ("Rp (%)", f"{res.rp:.4f}"),
                ("Rexp (%)", f"{res.rexp:.4f}"), ("χ²", f"{res.chi2:.4f}"),
                ("迭代次数", str(res.iters))]
        for p in res.phases:
            wt = "—" if p.weight_pct is None else f"{p.weight_pct:.3f}"
            rows.append((f"物相含量 · {p.name} (%)", wt))
        self.result_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.result_table.setItem(r, 0, QTableWidgetItem(k))
            self.result_table.setItem(r, 1, QTableWidgetItem(v))

    def export_report(self) -> None:
        if self._result is None:
            QMessageBox.information(self, "无结果", "请先执行精修")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出报告", "refine_report.txt", "文本 (*.txt);;所有文件 (*)")
        if not path:
            return
        res = self._result
        lines = ["# XinRefinement 精修报告", "",
                 f"Rwp = {res.rwp:.4f}%  Rp = {res.rp:.4f}%  "
                 f"Rexp = {res.rexp:.4f}%  chi2 = {res.chi2:.4f}", ""]
        for p in res.phases:
            lines.append(f"{p.name}: scale={p.scale:.6f} "
                         f"weight={p.weight_pct}")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.statusBar().showMessage(f"报告已导出：{path}")
