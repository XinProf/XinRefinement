"""P3.1/P3.3 · 主窗口三区骨架 + 导航式精修（对照草图 pre-temp/0.jpg）。

布局：菜单 + 工具栏 / 左（物相列表 + 参数树占位）/ 中（交互图谱 + 缩放工具栏）
/ 右（导航式精修面板「▶执行 + ⚙设置」+ 结果区）。

- 工具栏「▶精修」= 单次统一精修（同步，便于脚本/测试复现）；
- 导航每行的 ▶ = 按配方**单步**执行（后台线程 P3.3）；
- 「一键连跑」= 按标准配方顺序连跑，逐步回报 Rwp（后台线程 P3.3）；
- 齿轮 ⚙ = 打开该步骤详细设置，设置传导到下一次精修。

后台线程由 ``gui.workers.RefineWorker`` 承担，主线程只更新控件；
``closeEvent`` 会请求取消并等待线程收尾，避免 QThread 被销毁时 abort。
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure

from xinrefinement import __version__
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.profile.struct import compute_peaks
from xinrefinement.core.refine.linear import background_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import DEFAULT_STEPS
from xinrefinement.core.refine.solve import RefineInputs, solve
from xinrefinement.gui.canvas import PatternCanvas
from xinrefinement.gui.dialogs import STEPS, open_settings
from xinrefinement.gui.project import load_project, save_project
from xinrefinement.gui.workers import RefineWorker
from xinrefinement.i18n import (
    LANGUAGES,
    get_language,
    language_label,
    set_language,
    tr,
)


class MainWindow(QMainWindow):
    """XinRefinement 主窗口。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.resize(1180, 720)
        self._pattern = None
        self._pattern_path: str | None = None
        self._cif_paths: list[str] = []
        self._phases: list = []
        self._result = None
        self._settings: dict[str, dict] = {}
        self._worker: RefineWorker | None = None
        self._step_status: dict[str, str] = {}
        self._menu_actions: dict[str, QAction] = {}
        self._menus: dict[str, object] = {}
        self._toolbar_buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, QLabel] = {}
        self._groups: dict[str, QGroupBox] = {}
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self.retranslate()
        self.statusBar().showMessage(tr("msg.ready"))

    # -- 构建 ---------------------------------------------------------- #
    def _build_menu(self) -> None:
        bar = self.menuBar()
        for key in ("menu.file", "menu.edit", "menu.refine",
                    "menu.setting", "menu.help"):
            m = bar.addMenu(tr(key))
            self._menus[key] = m
        fm = self._menus["menu.file"]
        for key, slot in (("menu.import_pattern", self.open_pattern),
                          ("menu.import_cif", self.open_cif),
                          ("menu.save_project", self.save_project_dialog),
                          ("menu.open_project", self.open_project_dialog)):
            act = QAction(tr(key), self)
            act.triggered.connect(slot)
            fm.addAction(act)
            self._menu_actions[key] = act
        # 设置 → 语言子菜单
        lang_menu = self._menus["menu.setting"].addMenu(tr("menu.language"))
        self._menus["menu.language"] = lang_menu
        self._lang_actions: dict[str, QAction] = {}
        for lang in LANGUAGES:
            act = QAction(language_label(lang), self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, l=lang: self.switch_language(l))
            lang_menu.addAction(act)
            self._lang_actions[lang] = act

    def _build_toolbar(self) -> None:
        tb = QToolBar("main", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        for key, slot in (("toolbar.new", self.new_project),
                          ("toolbar.import_pattern", self.open_pattern),
                          ("toolbar.import_cif", self.open_cif),
                          ("toolbar.refine", self.run_refine),
                          ("toolbar.report", self.export_report)):
            btn = QPushButton(tr(key))
            btn.clicked.connect(slot)
            tb.addWidget(btn)
            self._toolbar_buttons[key] = btn

    def _build_body(self) -> None:
        split = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(split)

        # 左：物相列表 + 参数树占位
        left = QWidget()
        lv = QVBoxLayout(left)
        lbl_phases = QLabel(tr("panel.phases"))
        self._labels["panel.phases"] = lbl_phases
        lv.addWidget(lbl_phases)
        self.phase_list = QListWidget()
        self.phase_list.itemChanged.connect(self._on_phase_toggled)
        lv.addWidget(self.phase_list)
        lbl_tree = QLabel(tr("panel.param_tree"))
        self._labels["panel.param_tree"] = lbl_tree
        lv.addWidget(lbl_tree)
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
        nav = QGroupBox(tr("panel.nav"))
        self._groups["panel.nav"] = nav
        nv = QVBoxLayout(nav)
        self._step_buttons: dict[str, QPushButton] = {}
        for step, title, _cat in STEPS:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            run = QPushButton(f"▶ {tr(f'step.{step}')}")
            run.clicked.connect(lambda _c=False, s=step: self.run_step(s))
            gear = QPushButton("⚙")
            gear.setFixedWidth(32)
            gear.clicked.connect(lambda _c=False, s=step, t=title:
                                 self.open_step_settings(s, t))
            hl.addWidget(run, 1)
            hl.addWidget(gear)
            nv.addWidget(row)
            self._step_buttons[step] = run
        self.btn_run_all = QPushButton(tr("panel.run_all"))
        self.btn_run_all.setToolTip("按 8 步标准配方顺序精修，逐步回报 Rwp")
        self.btn_run_all.clicked.connect(self.run_recipe_all)
        self.btn_cancel = QPushButton(tr("panel.cancel"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_refine)
        row_all = QWidget()
        hl_all = QHBoxLayout(row_all)
        hl_all.setContentsMargins(0, 0, 0, 0)
        hl_all.addWidget(self.btn_run_all, 1)
        hl_all.addWidget(self.btn_cancel)
        nv.addWidget(row_all)
        self.lbl_progress = QLabel(tr("panel.ready"))
        self.lbl_progress.setWordWrap(True)
        nv.addWidget(self.lbl_progress)
        rv.addWidget(nav)

        res = QGroupBox(tr("panel.results"))
        self._groups["panel.results"] = res
        rl = QVBoxLayout(res)
        self.result_tabs = QTabWidget()
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(["指标", "值"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_tabs.addTab(self.result_table, tr("result.tab.summary"))
        # P3.5：收敛曲线
        self.conv_canvas = FigureCanvasQTAgg(Figure(figsize=(3.2, 1.8),
                                                    layout="constrained"))
        self.result_tabs.addTab(self.conv_canvas, tr("result.tab.convergence"))
        # P3.5：相关性矩阵
        self.corr_table = QTableWidget(0, 1)
        self.corr_table.horizontalHeader().setStretchLastSection(True)
        self.result_tabs.addTab(self.corr_table, tr("result.tab.correlation"))
        rl.addWidget(self.result_tabs)
        rv.addWidget(res, 1)
        split.addWidget(right)
        split.setSizes([220, 660, 300])

    # -- 国际化 -------------------------------------------------------- #
    def retranslate(self) -> None:
        """按当前语言刷新全部静态文案（语言切换无需重启）。"""
        self.setWindowTitle(f"{tr('app.title')} · v{__version__}")
        for key, menu in self._menus.items():
            if hasattr(menu, "setTitle"):
                menu.setTitle(tr(key))
        for key, act in self._menu_actions.items():
            act.setText(tr(key))
        for key, btn in self._toolbar_buttons.items():
            btn.setText(tr(key))
        for key, lbl in self._labels.items():
            lbl.setText(tr(key))
        for key, grp in self._groups.items():
            grp.setTitle(tr(key))
        for step, btn in self._step_buttons.items():
            text = btn.text()
            mark = text[:2] if text and text[0] in "✓–!" else ""
            btn.setText(f"{mark} {tr(f'step.{step}')}".strip())
        self.btn_run_all.setText(tr("panel.run_all"))
        self.btn_cancel.setText(tr("panel.cancel"))
        for lang, act in self._lang_actions.items():
            act.setChecked(lang == get_language())
        self.result_table.setHorizontalHeaderLabels(
            [tr("result.metric"), tr("result.value")])
        self.result_tabs.setTabText(0, tr("result.tab.summary"))
        self.result_tabs.setTabText(1, tr("result.tab.convergence"))
        self.result_tabs.setTabText(2, tr("result.tab.correlation"))
        self.corr_table.setHorizontalHeaderLabels(
            [tr("result.metric"), tr("result.value")])

    def switch_language(self, lang: str) -> None:
        set_language(lang)
        self.retranslate()
        self.canvas.retranslate()
        self.statusBar().showMessage(
            f"{language_label(lang)} · {tr('panel.ready')}")

    # -- 工程文件 ------------------------------------------------------ #
    def project_state(self) -> dict:
        """收集可序列化状态（供 .xrp 保存）。"""
        result = None
        if self._result is not None:
            r = self._result
            result = {"rwp": r.rwp, "rp": r.rp, "rexp": r.rexp,
                      "chi2": r.chi2, "iters": r.iters,
                      "phases": [{"name": p.name,
                                  "weight_pct": p.weight_pct}
                                 for p in r.phases]}
        records = []
        if self._worker is not None:
            records = [{"key": rec.key, "status": rec.status,
                        "rwp_after": rec.rwp_after}
                       for rec in self._worker.runner.records]
        return {
            "language": get_language(),
            "pattern": self._pattern_path,
            "cifs": list(self._cif_paths),
            "settings": self._settings,
            "result": result,
            "navigation": {"step_status": self._step_status,
                           "records": records},
        }

    def save_project_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("menu.save_project"), "project.xrp",
            "XinRefinement 工程 (*.xrp);;所有文件 (*)")
        if not path:
            return
        save_project(self.project_state(), path)
        self.statusBar().showMessage(f"{tr('menu.save_project')}: {path}")

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("menu.open_project"), "",
            "XinRefinement 工程 (*.xrp);;所有文件 (*)")
        if not path:
            return
        try:
            data = load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, tr("menu.open_project"), str(exc))
            return
        self.apply_project(data)

    def apply_project(self, data: dict) -> None:
        """把 .xrp 状态恢复到界面（缺文件时只提示，不中断）。"""
        self.new_project()
        if data.get("language") in LANGUAGES:
            set_language(data["language"])
            self.retranslate()
            self.canvas.retranslate()
        self._settings = dict(data.get("settings", {}))
        if data.get("pattern") and Path(data["pattern"]).exists():
            self._load_pattern_path(Path(data["pattern"]))
        cifs = [c for c in data.get("cifs", []) if c and Path(c).exists()]
        if cifs:
            self._load_cif_paths([Path(c) for c in cifs])
        nav = data.get("navigation", {})
        self._step_status = dict(nav.get("step_status", {}))
        for step, status in self._step_status.items():
            btn = self._step_buttons.get(step)
            if btn is not None:
                mark = {"done": "✓", "skipped": "–", "failed": "!"}.get(status, "")
                btn.setText(f"{mark} {tr(f'step.{step}')}".strip())
        missing = data.get("missing", [])
        msg = f"{tr('menu.open_project')}: {data.get('project_path', '')}"
        if missing:
            msg += f" | 缺失 {len(missing)} 个引用文件"
        self.statusBar().showMessage(msg)

    # -- 交互 ---------------------------------------------------------- #
    def new_project(self) -> None:
        self._pattern = None
        self._pattern_path = None
        self._cif_paths.clear()
        self._phases.clear()
        self._result = None
        self._settings.clear()
        self._step_status.clear()
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
        self._pattern_path = str(Path(path).resolve())
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
            self._cif_paths.append(str(Path(p).resolve()))
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

    def _make_inputs(self) -> RefineInputs | None:
        """按当前齿轮设置构造精修输入（同步与后台线程共用）。"""
        if self._pattern is None or not self._phases:
            QMessageBox.information(self, "无法精修",
                                    "请先导入谱图和至少一个 CIF")
            return None
        bg = self._settings.get("bg", {})
        cfg = RefineConfig(
            refine_zero=True, refine_uvw=True, n_bg=int(bg.get("n_bg", 3)),
            bg_mode=bg.get("bg_mode", "cheb"),
            tmin=5.0, tmax=90.0, max_iter=40)
        prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                            anode="Cu", integrated=False)
        return RefineInputs(pattern=self._pattern, phases=self._phases,
                            profile=prm, config=cfg)

    def run_step(self, step: str) -> None:
        """导航单步：按配方只执行该步（后台线程）。"""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在精修", "请等待当前精修结束或点「停止」")
            return
        self._start_worker(single_step=step)

    def run_recipe_all(self) -> None:
        """一键连跑标准配方（后台线程）。"""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在精修", "请等待当前精修结束或点「停止」")
            return
        self._step_status.clear()
        self._start_worker(single_step=None)

    def _start_worker(self, single_step: str | None) -> None:
        inputs = self._make_inputs()
        if inputs is None:
            return
        worker = RefineWorker(inputs, steps=DEFAULT_STEPS,
                              single_step=single_step)
        self._worker = worker
        worker.step_started.connect(self._on_step_started)
        worker.step_finished.connect(self._on_step_finished)
        worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(self._on_worker_ok)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_done)
        self.btn_run_all.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        for btn in self._step_buttons.values():
            btn.setEnabled(False)
        worker.start()

    def cancel_refine(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.lbl_progress.setText("正在停止…")

    def _on_step_started(self, key: str, title: str) -> None:
        self._step_status[key] = "running"
        self.statusBar().showMessage(f"执行中：{title}")

    def _on_step_finished(self, key, status, rwp, message) -> None:
        self._step_status[key] = status
        btn = self._step_buttons.get(key)
        if btn is not None:
            mark = {"done": "✓", "skipped": "–", "failed": "!"}.get(status, "")
            title = next((s[1] for s in STEPS if s[0] == key), key)
            btn.setText(f"{mark} {title}" if not btn.text().startswith(mark)
                        else btn.text())

    def _on_progress(self, msg: str, pct) -> None:
        self.lbl_progress.setText(msg)
        self.statusBar().showMessage(msg)

    def _on_worker_ok(self, res) -> None:
        self._result = res
        bg_curve = self._background_curve(res)
        self.canvas.show_fit(res.pattern.two_theta,
                             res.pattern.intensity, res.ycalc,
                             background=bg_curve)
        self._fill_results(res)

    def _on_worker_failed(self, msg: str) -> None:
        # 取消是用户主动行为，不弹模态框：离屏/自动化测试里模态框会
        # 永久阻塞事件循环（实测 test_cancel_stops_recipe 挂死 12 分钟）。
        cancelled = (self._worker is not None
                     and self._worker.is_cancelled)
        if not cancelled:
            QMessageBox.warning(self, "精修未完成", msg)
        self.lbl_progress.setText("已停止" if cancelled else msg)

    def _on_worker_done(self) -> None:
        self.btn_run_all.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        for btn in self._step_buttons.values():
            btn.setEnabled(True)

    def _background_curve(self, res):
        """背景系数 -> 背景曲线（失败时返回 None）。"""
        try:
            return (background_basis(res.pattern.two_theta,
                                     len(res.background),
                                     res.config.bg_mode)
                    @ np.asarray(res.background, dtype=float))
        except Exception:
            return None

    def wait_for_worker(self, timeout_ms: int = 30000) -> bool:
        """测试辅助：等待后台线程收尾并派发信号（供离屏冒烟用）。"""
        w = self._worker
        if w is None:
            return False
        ok = w.wait(timeout_ms)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        return ok

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 约定
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(30000)
        super().closeEvent(event)

    def run_refine(self) -> None:
        """工具栏「▶精修」：单次统一精修（同步，保留脚本/测试契约）。"""
        inputs = self._make_inputs()
        if inputs is None:
            return
        try:
            res = solve(inputs)
        except Exception as exc:
            QMessageBox.warning(self, "精修失败", str(exc))
            return
        self._result = res
        # 背景系数 -> 背景曲线（与精修同一组基函数，界面与报告口径一致）
        self.canvas.show_fit(res.pattern.two_theta,
                             res.pattern.intensity, res.ycalc,
                             background=self._background_curve(res))
        self._fill_results(res)
        self.statusBar().showMessage(
            f"精修完成：Rwp={res.rwp:.3f}%  success={res.success}")

    def _fill_results(self, res) -> None:
        """P3.5：摘要 + 收敛曲线 + 相关性矩阵 + DW/e.s.d.。"""
        from xinrefinement.core.refine.diagnostics import diagnose
        from xinrefinement.core.refine.esd import estimate_esd

        diag = diagnose(res)
        rows = [(tr("result.rwp"), f"{res.rwp:.4f}"),
                (tr("result.rp"), f"{res.rp:.4f}"),
                (tr("result.rexp"), f"{res.rexp:.4f}"),
                (tr("result.chi2"), f"{res.chi2:.4f}"),
                (tr("result.iters"), str(res.iters)),
                (tr("result.dw"), f"{diag.dw:.4f}")]
        weight_esd = None
        try:
            esd = estimate_esd(self._phases, res)
            weight_esd = esd.weight_esd_pct
            rows.append(("Rwp 下降 (pp)", f"{diag.rwp_drop:.4f}"))
        except Exception:
            esd = None
        for i, p in enumerate(res.phases):
            wt = "—" if p.weight_pct is None else f"{p.weight_pct:.3f}"
            rows.append((f"{tr('result.phase_weight')} · {p.name} (%)", wt))
            if weight_esd:
                rows.append((f"e.s.d. · {p.name} (pp)",
                             f"{weight_esd[i]:.4f}"))
        self.result_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.result_table.setItem(r, 0, QTableWidgetItem(k))
            self.result_table.setItem(r, 1, QTableWidgetItem(v))
        self._draw_convergence(res)
        self._draw_correlation(esd)

    def _draw_convergence(self, res) -> None:
        """收敛曲线（Rwp 历史）。"""
        fig = self.conv_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        h = np.asarray(res.history, dtype=float)
        if h.size:
            ax.plot(np.arange(h.size), h, color="#1f77b4", lw=1.0)
            ax.set_ylabel("Rwp (%)")
            ax.set_xlabel("eval")
            ax.grid(True, color="#e0e0e0", lw=0.5)
        self.conv_canvas.draw_idle()

    def _draw_correlation(self, esd) -> None:
        """高相关参数对（|r| ≥ 0.7）+ e.s.d. 摘要。"""
        rows = []
        if esd is not None:
            C, labels = esd.correlation, esd.labels
            n_x = len([l for l in labels if not l.startswith(("scale[", "bg["))])
            for i in range(n_x):
                rows.append((labels[i], f"e.s.d.={esd.esd[i]:.5g}"))
                for j in range(i + 1, n_x):
                    if abs(C[i, j]) >= 0.7:
                        rows.append((f"⚠ {labels[i]} ↔ {labels[j]}",
                                     f"r={C[i, j]:+.3f}"))
        else:
            rows.append(("—", "e.s.d. 不可用"))
        self.corr_table.setColumnCount(2)
        self.corr_table.setHorizontalHeaderLabels([tr("result.metric"),
                                                   tr("result.value")])
        self.corr_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.corr_table.setItem(r, 0, QTableWidgetItem(k))
            self.corr_table.setItem(r, 1, QTableWidgetItem(v))

    def export_report(self) -> None:
        """P4.1：HTML + PNG + JSON 精修日志三件套（core/report.py）。"""
        if self._result is None:
            QMessageBox.information(self, "无结果", "请先执行精修")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("toolbar.report"), "refine_report.html",
            "HTML 报告 (*.html);;所有文件 (*)")
        if not path:
            return
        from xinrefinement.core.refine.esd import estimate_esd
        from xinrefinement.core.report import export_report as _export

        try:
            esd = estimate_esd(self._phases, self._result)
        except Exception:
            esd = None
        out = Path(path)
        try:
            paths = _export(self._result, out.parent, stem=out.stem, esd=esd)
        except Exception as exc:
            QMessageBox.warning(self, tr("toolbar.report"), str(exc))
            return
        self.statusBar().showMessage(
            f"{tr('toolbar.report')}: {', '.join(Path(p).name for p in paths.values())}")
