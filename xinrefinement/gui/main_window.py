"""P3.1/P3.3 · 主窗口三区骨架 + 导航式精修。

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

import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
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
from xinrefinement import build_variant
from xinrefinement.core.patterns import load_pattern
from xinrefinement.core.profile.cif import parse_cif
from xinrefinement.core.profile.forward import ProfileParams
from xinrefinement.core.profile.naming import (
    DEFAULT_PHASE_LABEL_MODE,
    PHASE_LABEL_MODES,
    label_map,
    phase_label,
)
from xinrefinement.core.profile.struct import compute_peaks
from xinrefinement.core.refine.linear import adaptive_n_bg, background_basis
from xinrefinement.core.refine.nonlinear import RefineConfig
from xinrefinement.core.refine.recipe import DEFAULT_STEPS
from xinrefinement.core.refine.solve import RefineInputs, solve
from xinrefinement.gui.about import AboutDialog, LicenseDialog
from xinrefinement.gui.assets import app_icon
from xinrefinement.gui.canvas import PatternCanvas


def _aniso_from_edits(edits: dict, wavelength: float = 1.5406) -> dict:
    """``phase_edits`` -> ``ProfileParams.aniso``（v1.3 #15）。

    对话框只给模式；系数初值取各向同性（D≈1000 Å / ε≈0），精修从这里起步。
    """
    from xinrefinement.core.profile.forward import aniso_default

    out: dict[str, dict] = {}
    for name, s in (edits or {}).items():
        cfg = s.get("aniso")
        if not cfg:
            continue
        out[name] = aniso_default(wavelength)
    return out


def _width_basis_text(p) -> str:
    """Caglioti 宽度基的中文说明（v1.5 M5 的旋钮，默认 tanθ）。"""
    basis = getattr(p, "width_basis", "tan") if p is not None else "tan"
    return "tanθ（默认）" if basis != "d" else "1/d（实验旋钮）"


def _texture_from_edits(edits: dict, model: str = "harmonic:10") -> dict:
    """``phase_edits`` -> ``ProfileParams.texture``（v1.3 #14 / v1.5 M3）。

    只保留显式勾选织构轴的相；``model`` 形如 ``"ewimv"`` 或
    ``"harmonic:阶数"``（来自 micro 齿轮的「织构模型」下拉）。缺省初值即
    「无织构」（EWIMV 全 1 网格 / 球谐系数全 0），两者 T(χ)≡1。
    """
    from xinrefinement.core.profile.forward import (
        default_texture_coeffs, default_texture_grid, texture_degrees)

    mdl, _, deg = str(model or "harmonic:4").partition(":")
    out: dict[str, dict] = {}
    for name, s in (edits or {}).items():
        tx = s.get("texture")
        if not tx:
            continue
        entry = {"axis": tuple(int(v) for v in tx["axis"])}
        if mdl == "harmonic":
            d = int(deg or 4)
            texture_degrees(d)          # 阶数非法时早报错（偶数、≤ 8）
            entry.update({"model": "harmonic", "degree": d,
                          "coeffs": list(tx.get("coeffs")
                                         or default_texture_coeffs(d))})
        else:
            entry.update({"model": "ewimv",
                          "grid": list(tx.get("grid") or default_texture_grid())})
        out[name] = entry
    return out
from xinrefinement.gui.dialogs import (
    STEPS,
    PhaseEditDialog,
    StepDescribeDialog,
    open_settings,
)
from xinrefinement.gui.project import load_project, save_project
from xinrefinement.gui.workers import RefineWorker
from xinrefinement.i18n import (
    LANGUAGES,
    get_language,
    language_label,
    set_language,
    tr,
)

#: v1.6.1：导航式精修八个步骤的齿轮颜色（品牌色系，与图标/相色同源）
STEP_GEAR_COLORS: dict[str, str] = {
    "zero": "#1f77b4",      # 蓝
    "bg": "#ff7f0e",        # 橙
    "scale": "#2ca02c",     # 绿
    "cell": "#d62728",      # 红
    "profile": "#9467bd",   # 紫
    "xyz": "#8c564b",       # 棕
    "B": "#e377c2",         # 粉
    "micro": "#17becf",     # 青
}


class MainWindow(QMainWindow):
    """XinRefinement 主窗口。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.resize(1180, 720)
        icon = app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self._pattern = None
        self._pattern_path: str | None = None
        self._cif_paths: list[str] = []
        self._phases: list = []
        self._result = None
        #: v1.6.4：e.s.d. 单次缓存 (键, EsdResult|None)。三处结果面板各自
        #: 重算一遍要跑 3 遍全谱前向，一次精修只该算一次。
        self._esd_cache: tuple[tuple, object] | None = None
        self._settings: dict[str, dict] = {}
        self._worker: RefineWorker | None = None
        self._step_status: dict[str, str] = {}
        #: 每相 March–Dollase 择优取向 {phase_name: (h,k,l,r)}
        self._phase_po: dict[str, tuple] = {}
        #: 每相 Brindley 微吸收 {phase_name: μ·r}（v1.2.0）
        self._phase_microabs: dict[str, float] = {}
        #: v1.3 #14：每相织构配置 {相名: {"axis": (h,k,l), "grid": [...]}}
        self._phase_texture: dict[str, dict] = {}
        #: v1.3 #15：每相各向异性系数 {相名: {"size": [...], "strain": [...]}}
        self._phase_aniso: dict[str, dict] = {}
        #: v1.3 #15：各向异性精修模式（size/strain/both）
        self._aniso_mode: str = "size"
        #: 物相编辑对话框的全部设置（晶胞/择优取向/对称性元数据）
        self._phase_edits: dict[str, dict] = {}
        #: v1.6：物相显示口径（formula 化学式 / label 物相名称 / file 文件名）
        self._disp_mode: str = DEFAULT_PHASE_LABEL_MODE
        #: v1.6：每步开始精修前的参数快照，用于日志里打印「参数 → 参数」
        self._param_snapshot: dict | None = None
        #: v1.6：本步开始前的 Rwp（跑码收尾行的 "before"）
        self._rwp_before_step: float | None = None
        #: v1.6：说明弹窗已写过「开始」行时置位，避免 _on_step_started 重复
        self._skip_begin_log: bool = False
        self._menu_actions: dict[str, QAction] = {}
        self._menus: dict[str, object] = {}
        self._toolbar_buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, QLabel] = {}
        self._groups: dict[str, QGroupBox] = {}
        # 注册机制：仅正式版（release）接入；内部评估版不弹提示、不出现
        # 「输入注册码」菜单，状态栏右端固定显示「内部评估版本」。
        # 状态文件走 PolyXRD 家族统一目录（%APPDATA%/PolyXRD/Registration）。
        self._registration = None
        if build_variant.is_release():
            from xinrefinement.registration import (
                RegistrationManager,
                default_state_path,
            )

            self._registration = RegistrationManager(
                "XinRefinement", default_state_path("XinRefinement"))
        self._registration_label: QLabel | None = None
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
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
                          ("menu.import_xinm", self.import_xinm_dialog),
                          ("menu.save_project", self.save_project_dialog),
                          ("menu.open_project", self.open_project_dialog)):
            act = QAction(tr(key), self)
            act.triggered.connect(slot)
            fm.addAction(act)
            self._menu_actions[key] = act
        # 编辑 → 物相参数编辑
        em = self._menus["menu.edit"]
        for key, slot in (("menu.phase_edit", self.open_phase_editor),):
            act = QAction(tr(key), self)
            act.triggered.connect(slot)
            em.addAction(act)
            self._menu_actions[key] = act
        # 精修 → 一键连跑（默认配置）/ 停止
        rm = self._menus["menu.refine"]
        for key, slot in (("menu.run_all", self.run_recipe_all),
                          ("menu.stop", self.cancel_refine)):
            act = QAction(tr(key), self)
            act.triggered.connect(slot)
            rm.addAction(act)
            self._menu_actions[key] = act
        # 帮助 → 版权与许可 / 关于
        hm = self._menus["menu.help"]
        act_lic = QAction(tr("license.menu"), self)
        act_lic.triggered.connect(self.show_license)
        hm.addAction(act_lic)
        self._menu_actions["license.menu"] = act_lic
        hm.addSeparator()
        act = QAction(tr("menu.about"), self)
        act.triggered.connect(self.show_about)
        hm.addAction(act)
        self._menu_actions["menu.about"] = act
        # 帮助 → 输入注册码（仅正式版；加在「关于」之前）
        if self._registration is not None:
            hm.insertSeparator(act)
            self._registration.add_help_action(hm, self)
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
        # 设置 → 物相显示（v1.6：化学式 / 物相名称 / CIF 文件名）
        disp_menu = self._menus["menu.setting"].addMenu(tr("disp.mode"))
        self._menus["disp.mode"] = disp_menu
        self._disp_actions: dict[str, QAction] = {}
        for mode in PHASE_LABEL_MODES:
            act = QAction(tr(f"disp.{mode}"), self)
            act.setCheckable(True)
            act.setChecked(mode == self._disp_mode)
            act.triggered.connect(
                lambda _c=False, m=mode: self.set_display_mode(m))
            disp_menu.addAction(act)
            self._disp_actions[mode] = act

    def _build_toolbar(self) -> None:
        from xinrefinement.gui.button_icons import toolbar_icon
        from PySide6.QtCore import QSize as _QSize

        tb = QToolBar("main", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        for key, slot in (("toolbar.new", self.new_project),
                          ("toolbar.import_pattern", self.open_pattern),
                          ("toolbar.import_cif", self.open_cif),
                          ("toolbar.refine", self.run_refine),
                          ("toolbar.report", self.export_report)):
            btn = QPushButton(tr(key))
            icon = toolbar_icon(key)          # 彩色功能图标（快捷方式入口）
            if icon is not None:
                btn.setIcon(icon)
                btn.setIconSize(_QSize(20, 20))
            btn.clicked.connect(slot)
            tb.addWidget(btn)
            self._toolbar_buttons[key] = btn
        # v1.3：点选背景（checkable）——画布主轴内左键加/删锚点、右键清空
        pick_btn = QPushButton(tr("toolbar.bg_pick"))
        pick_btn.setCheckable(True)
        pick_btn.setToolTip(tr("bg.pick_hint"))
        pick_btn.toggled.connect(self._toggle_bg_pick_mode)
        tb.addWidget(pick_btn)
        self._toolbar_buttons["toolbar.bg_pick"] = pick_btn

    def _toggle_bg_pick_mode(self, on: bool) -> None:
        """开关画布背景点选模式。"""
        self.canvas.set_pick_mode(bool(on))
        if on:
            self.statusBar().showMessage(tr("bg.pick_hint"))

    def _on_bg_picks_changed(self, picks: list) -> None:
        """画布锚点变化 → 写入 bg 设置并自动切 manual 模式（下次精修生效）。"""
        bg = self._settings.setdefault("bg", {})
        bg["bg_points"] = [(float(a), float(b)) for a, b in picks]
        if picks and bg.get("bg_mode") != "manual":
            bg["bg_mode"] = "manual"
        self.statusBar().showMessage(tr("bg.pick_status").format(n=len(picks)))

    def _build_body(self) -> None:
        split = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(split)

        # 左：物相列表 + 精修日志（跑码窗口）
        left = QWidget()
        lv = QVBoxLayout(left)
        lbl_phases = QLabel(tr("panel.phases"))
        self._labels["panel.phases"] = lbl_phases
        lv.addWidget(lbl_phases)
        self.phase_list = QListWidget()
        self.phase_list.setToolTip("双击可编辑该物相的晶胞 / 择优取向 / 对称性")
        self.phase_list.itemChanged.connect(self._on_phase_toggled)
        self.phase_list.itemDoubleClicked.connect(
            lambda _item: self.open_phase_editor())
        lv.addWidget(self.phase_list, 1)

        # v1.6：左下面板改为 MAUD 式「跑码窗口」。原来这里是一个写死的
        # 两行占位列表（"全局：零点 / 背景 / 峰形"），没有任何信息量；
        # 用户在精修时看不到参数在动。现在逐步追加参数级变化。
        log_head = QHBoxLayout()
        lbl_log = QLabel(tr("panel.log"))
        self._labels["panel.log"] = lbl_log
        log_head.addWidget(lbl_log, 1)
        self.btn_clear_log = QPushButton(tr("log.clear"))
        self.btn_clear_log.setFixedWidth(84)
        self.btn_clear_log.clicked.connect(self.clear_log)
        log_head.addWidget(self.btn_clear_log)
        lv.addLayout(log_head)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setMaximumBlockCount(4000)   # 长链不无限涨内存
        self.log_view.setStyleSheet(
            "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;")
        self.log_view.setPlaceholderText(tr("log.empty"))
        lv.addWidget(self.log_view, 2)
        split.addWidget(left)

        # 中：交互图谱
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(2)
        self.canvas = PatternCanvas()
        from xinrefinement.gui.toolbar_icons import colorize_nav_toolbar
        self._nav_toolbar = NavigationToolbar2QT(self.canvas, center)
        # v1.6.1：图标缩小一号（chip 36 → 30），并移到**谱图上方**
        colorize_nav_toolbar(self._nav_toolbar, chip=30)
        self.canvas.nav_toolbar = self._nav_toolbar  # 平移/缩放时让出轴点击
        self.canvas.axisHint.connect(self.statusBar().showMessage)
        # v1.6.1：十字线读数同时给状态栏一份（工具条末尾也有一个即时读数）
        self.canvas.cursorInfo.connect(self.statusBar().showMessage)
        # v1.3：画布背景锚点 → 设置回写（manual 模式，下次精修生效）
        self.canvas.bgPointsChanged.connect(self._on_bg_picks_changed)
        # v1.6：标记条右键 → 切换物相显示口径
        self.canvas.phaseLabelMode.connect(self.set_display_mode)
        cv.addWidget(self._nav_toolbar)
        # v1.6.1：谱图操作行（复位/框选/平移/步进缩放/十字线）
        from xinrefinement.gui.plot_tools import PlotToolBar
        self.plot_toolbar = PlotToolBar(self.canvas, center)
        cv.addWidget(self.plot_toolbar)
        cv.addWidget(self.canvas, 1)
        split.addWidget(center)

        # 右：导航式精修面板 + 结果区
        right = QWidget()
        rv = QVBoxLayout(right)
        nav = QGroupBox(tr("panel.nav"))
        self._groups["panel.nav"] = nav
        nv = QVBoxLayout(nav)
        self._step_buttons: dict[str, QPushButton] = {}
        self._gear_buttons: dict[str, QPushButton] = {}
        for step, title, _cat in STEPS:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            run = QPushButton(f"▶ {tr(f'step.{step}')}")
            run.clicked.connect(lambda _c=False, s=step: self.describe_step(s))
            gear = QPushButton("⚙")
            gear.setFixedWidth(32)
            # v1.6.1：八个齿轮各一色——长条列表里靠颜色定位比读文字快
            color = STEP_GEAR_COLORS.get(step, "#5b6670")
            gear.setStyleSheet(
                f"QPushButton {{ color: {color}; font-weight: bold;"
                f" font-size: 16px; }}")
            gear.setToolTip(f"「{tr(f'step.{step}')}」参数设置")
            gear.clicked.connect(lambda _c=False, s=step, t=title:
                                 self.open_step_settings(s, t))
            hl.addWidget(run, 1)
            hl.addWidget(gear)
            nv.addWidget(row)
            self._step_buttons[step] = run
            self._gear_buttons[step] = gear
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

        # v1.6：物相定量单独一页。用户明确要求「用化学式或物相名称显示，
        # 而不是导入的 CIF 文件名」——所以这里的首列走 _disp()。
        self.quant_table = QTableWidget(0, 5)
        self.quant_table.horizontalHeader().setStretchLastSection(True)
        self.result_tabs.addTab(self.quant_table, tr("result.tab.quant"))

        # v1.6：晶胞与微结构一页（a b c α β γ / V / 晶粒尺寸 / 应变）
        self.cell_table = QTableWidget(0, 11)
        self.cell_table.horizontalHeader().setStretchLastSection(True)
        self.result_tabs.addTab(self.cell_table, tr("result.tab.cell"))

        # P3.5：收敛曲线
        self.conv_canvas = FigureCanvasQTAgg(Figure(figsize=(3.2, 1.8),
                                                    layout="constrained"))
        self.result_tabs.addTab(self.conv_canvas, tr("result.tab.convergence"))
        # P3.5：相关性矩阵
        self.corr_table = QTableWidget(0, 1)
        self.corr_table.horizontalHeader().setStretchLastSection(True)
        self.result_tabs.addTab(self.corr_table, tr("result.tab.correlation"))
        rl.addWidget(self.result_tabs)
        # v1.5 M8c：多型建议按钮。默认隐藏，只在「ΔB_iso 撞界 + 化学式 +
        # 空间群」三条件同时命中时出现（见 core/refine/polymorph.py）。
        # 用按钮而不是模态框：既不给用户「必须立刻决定」的压力，也避免
        # 离屏/自动化测试里模态框阻塞事件循环（同 _on_worker_failed 的教训）。
        self.btn_polymorph = QPushButton("")
        self.btn_polymorph.setVisible(False)
        self.btn_polymorph.clicked.connect(self._on_apply_polymorph)
        rl.addWidget(self.btn_polymorph)
        self._polymorph_suggestion = None
        rv.addWidget(res, 1)
        split.addWidget(right)
        split.setSizes([220, 660, 300])

    # -- 状态栏 -------------------------------------------------------- #
    def _build_statusbar(self) -> None:
        """状态栏：最右注册状态（正式版）/ 居中的「内部评估版本」（内部版）。"""
        bar = self.statusBar()
        if self._registration is not None:
            # stretch=1 让标签吃掉剩余空白，单位名始终贴住右端。
            self._registration_label = self._registration.attach_status_label(
                bar, self)
            return
        label = QLabel(build_variant.INTERNAL_STATUS_TEXT)
        label.setObjectName("internalBuildLabel")
        # v1.6.1：按用户要求**居中**显示（原来贴右端），字号加大一号、红色加粗。
        # 用 permanentWidget + stretch 而不是 addWidget：showMessage() 会临时
        # 隐藏普通部件，标签会在每条状态提示时闪烁消失。
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setToolTip("内部评估版：未启用注册机制，仅供内部测试与评估使用。")
        font = label.font()
        font.setPointSizeF(max(font.pointSizeF(), 9.0) + 1.0)
        font.setBold(True)
        label.setFont(font)
        # 红色加粗（与 XinMatch 内部版一致）；挂在控件上的样式优先级高于
        # 全局 QSS，换主题不会掉色。
        label.setStyleSheet("color: #d32f2f; font-weight: bold; padding: 0 6px;")
        bar.addPermanentWidget(label, 1)
        self._registration_label = label

    def registration_status_text(self) -> str:
        """状态栏右端注册文案（冒烟测试读取，不弹窗）。"""
        if self._registration is not None:
            return self._registration.state.status_text
        return build_variant.INTERNAL_STATUS_TEXT

    def startup_registration_check(self) -> None:
        """启动注册检查（窗口显示后由入口 QTimer 调用；离屏自动跳过）。"""
        if self._registration is None:
            return
        self._registration.startup_check(self)
        self._registration_label = self._registration.label(self)

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
        if hasattr(self, "btn_clear_log"):
            self.btn_clear_log.setText(tr("log.clear"))
        for lang, act in self._lang_actions.items():
            act.setChecked(lang == get_language())
        self.result_table.setHorizontalHeaderLabels(
            [tr("result.metric"), tr("result.value")])
        # v1.6：标签页数量随版本增长，用 indexOf 定位，别写死索引
        for widget, key in ((self.result_table, "result.tab.summary"),
                            (self.quant_table, "result.tab.quant"),
                            (self.cell_table, "result.tab.cell"),
                            (self.conv_canvas, "result.tab.convergence"),
                            (self.corr_table, "result.tab.correlation")):
            idx = self.result_tabs.indexOf(widget)
            if idx >= 0:
                self.result_tabs.setTabText(idx, tr(key))
        self.corr_table.setHorizontalHeaderLabels(
            [tr("result.metric"), tr("result.value")])
        # v1.6.1：齿轮 tooltip 与谱图操作行文案
        for step, btn in getattr(self, "_gear_buttons", {}).items():
            btn.setToolTip(f"「{tr(f'step.{step}')}」参数设置")
        if hasattr(self, "plot_toolbar"):
            self.plot_toolbar.retranslate()

    def switch_language(self, lang: str) -> None:
        set_language(lang)
        # 注册模块自带一套三语文案（不依赖本包 i18n），单独同步
        from xinrefinement import registration as _reg_mod
        _reg_mod.set_language(lang)
        if self._registration is not None:
            self._registration.refresh()
        self.retranslate()
        self.canvas.retranslate()
        self.statusBar().showMessage(
            f"{language_label(lang)} · {tr('panel.ready')}")

    # -- 工程文件 ------------------------------------------------------ #
    def project_state(self) -> dict:
        """收集可序列化状态（供 ``.xinr`` / ``.xrp`` 保存）。

        ``result`` 为轻量摘要（状态栏/旧格式用）；``result_full`` 为完整精修
        JSON（联合计划 R-2a，写入 ``.xinr`` 的 ``result/refine.json``，与
        CLI ``--out`` 同族 schema）。
        """
        result = None
        result_full = None
        if self._result is not None:
            r = self._result
            result = {"rwp": r.rwp, "rp": r.rp, "rexp": r.rexp,
                      "chi2": r.chi2, "iters": r.iters,
                      "phases": [{"name": p.name,
                                  "weight_pct": p.weight_pct}
                                 for p in r.phases]}
            try:
                from xinrefinement.core.report import solve_result_dict
                esd = self._esd_for(r)
                result_full = solve_result_dict(
                    r, esd=esd,
                    input_info={"pattern": self._pattern_path,
                                "cif": list(self._cif_paths),
                                "tmin": float(getattr(r.config, "tmin", 0.0)),
                                "tmax": float(getattr(r.config, "tmax", 0.0)),
                                "anode": str(getattr(r.params, "anode", ""))})
            except Exception:
                result_full = None
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
            "phase_edits": self._phase_edits,
            "result": result,
            "result_full": result_full,
            "navigation": {"step_status": self._step_status,
                           "records": records},
        }

    def save_project_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("menu.save_project"), "project.xinr",
            "XinRefinement 工程 (*.xinr *.xrp);;所有文件 (*)")
        if not path:
            return
        # .xinr → 自包含 zip 容器（内嵌谱图+CIF，默认）；.xrp → 旧 JSON 路径引用
        embed = Path(path).suffix.lower() != ".xrp"
        try:
            save_project(self.project_state(), path, embed=embed)
        except Exception as exc:
            QMessageBox.warning(self, tr("menu.save_project"), str(exc))
            return
        mode = "内嵌数据" if embed else "路径引用"
        self.statusBar().showMessage(
            f"{tr('menu.save_project')}: {path}（{mode}）")

    def import_xinm_dialog(self) -> None:
        """v1.1.0 联合计划 R-3：导入 XinMatch 物相分析（.xinm）。

        装载谱图 + 已选物相 CIF；``structural=false`` 的相列为「仅参照」，
        不参与精修（PDF2 类条目无原子坐标，见联合计划 §3）。
        """
        from xinrefinement.core.io.xinm_import import (
            XinmImportError,
            read_xinm,
        )
        path, _ = QFileDialog.getOpenFileName(
            self, tr("menu.import_xinm"), "",
            "XinMatch 物相分析 (*.xinm);;所有文件 (*)")
        if not path:
            return
        try:
            payload = read_xinm(path)
        except XinmImportError as exc:
            QMessageBox.warning(self, tr("menu.import_xinm"), str(exc))
            return
        report = self._apply_xinm_payload(payload, stem=Path(path).stem)
        if report is None:
            return

        structural = report["structural"]
        ref_only = report["reference_only"]
        msg = tr("xinm.status").format(
            n=report["n_points"],
            p=len(structural) + len(ref_only), s=len(structural))
        if ref_only:
            msg += tr("xinm.ref_suffix").format(
                names="、".join(p.name for p in ref_only))
        self.statusBar().showMessage(msg)
        if ref_only:
            QMessageBox.information(
                self, tr("menu.import_xinm"),
                tr("xinm.ref_only_head") + "\n"
                + "\n".join(f"• {p.name}（{p.reason or '无 CIF'}）"
                            for p in ref_only))
        if report["mismatch"]:
            QMessageBox.information(
                self, tr("menu.import_xinm"),
                tr("xinm.mismatch_head") + "\n"
                + "\n".join(f"• {n}：{why}" for n, why in report["mismatch"]))

    @staticmethod
    def _normalize_sg(sg: str | None) -> str:
        """空间群符号归一化（大小写/空格/下划线/设置后缀 ``:1`` 不影响比对）。"""
        s = str(sg or "").strip()
        if ":" in s:
            s = s.split(":", 1)[0]
        return s.replace(" ", "").replace("_", "").lower()

    def _apply_xinm_payload(self, payload, *, stem: str = "xinm") -> dict | None:
        """把 ``.xinm`` 载荷落到当前界面（R-3a，GUI 装配层）。

        步骤：清空工程 → 谱图（wavelength 显式传导 d 轴）→ CIF 装载 → 用
        manifest 的晶胞/空间群做一致性核对与 ``phase_edits`` 预填。
        返回 ``{n_points, structural, reference_only, mismatch}``；
        谱图装载失败返回 None。
        """
        from xinrefinement.core.io.xinm_import import extract_cifs

        self.new_project()

        # 谱图：payload 数组 → 会话 .xy → 既有装载通道（wavelength 显式传导）
        session = Path(tempfile.gettempdir()) / "xinrefinement_xinm"
        session.mkdir(parents=True, exist_ok=True)
        xy = session / f"{stem}_pattern.xy"
        with xy.open("w", encoding="utf-8", newline="\n") as fh:
            for x, y in zip(payload.two_theta.tolist(),
                            payload.intensity.tolist()):
                fh.write(f"{x:.17g} {y:.17g}\n")
        if not self._load_pattern_path(
                xy, wavelength=payload.meta.get("wavelength")):
            return None

        # CIF：仅 structural 相参与精修；装载顺序与 manifest 顺序一致
        cif_dir = session / f"{stem}_cifs"
        name_map = extract_cifs(payload, cif_dir)
        structural = [p for p in payload.structural_phases
                      if p.name in name_map]
        before = len(self._phases)
        self._load_cif_paths([name_map[p.name] for p in structural])
        loaded = self._phases[before:]

        mismatch: list[tuple[str, str]] = []
        for spec, st in zip(structural, loaded):
            cell = spec.cell or {}
            try:
                ref = [float(cell[k]) for k in
                       ("a", "b", "c", "alpha", "beta", "gamma")]
            except (KeyError, TypeError, ValueError):
                ref = None
            if ref is not None:
                dev = [abs(float(a) - b) / max(abs(b), 1e-9)
                       for a, b in zip(ref[:3], st.cell[:3])]
                ang = [abs(float(a) - b) for a, b in zip(ref[3:], st.cell[3:])]
                if max(dev) > 1e-3 or max(ang) > 0.05:
                    mismatch.append((st.name,
                                     f"晶胞偏差最大 {max(dev) * 100:.2f}%（CIF 已采用）"))
                else:
                    # 一致：预填编辑项（记录来源，不改数值）
                    self._phase_edits[st.name] = {
                        "cell": [float(v) for v in st.cell], "po": None}
            sg = self._normalize_sg(spec.space_group)
            if sg and st.spacegroup:
                if sg != self._normalize_sg(st.spacegroup):
                    mismatch.append((st.name,
                                     f"空间群 {spec.space_group} vs CIF {st.spacegroup}（CIF 已采用）"))

        return {
            "n_points": int(payload.two_theta.size),
            "structural": structural,
            "reference_only": payload.reference_only_phases,
            "mismatch": mismatch,
        }

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("menu.open_project"), "",
            "XinRefinement 工程 (*.xinr *.xrp);;所有文件 (*)")
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
        self._phase_edits = dict(data.get("phase_edits", {}))
        self._phase_po = {n: s["po"] for n, s in self._phase_edits.items()
                          if s.get("po")}
        self._phase_microabs = {n: s["microabs"]
                                for n, s in self._phase_edits.items()
                                if s.get("microabs")}
        self._phase_texture = _texture_from_edits(
            self._phase_edits,
            str((self._settings.get("micro") or {}).get(
                "texture_model", "harmonic:10")))
        self._phase_aniso = _aniso_from_edits(self._phase_edits)
        self._aniso_mode = next(
            (s["aniso"]["mode"] for s in self._phase_edits.values()
             if s.get("aniso")), "size")
        if data.get("pattern") and Path(data["pattern"]).exists():
            self._load_pattern_path(Path(data["pattern"]))
        # v1.3：恢复工程保存的背景锚点（画布标记 + manual 模式）
        bg_saved = self._settings.get("bg", {}) or {}
        if bg_saved.get("bg_points"):
            self.canvas.set_bg_picks(bg_saved["bg_points"])
        cifs = [c for c in data.get("cifs", []) if c and Path(c).exists()]
        if cifs:
            self._load_cif_paths([Path(c) for c in cifs])
            # 恢复工程里保存的晶胞 / 择优取向编辑（覆盖 CIF 原始值）
            for name, s in self._phase_edits.items():
                st = next((x for x in self._phases if x.name == name), None)
                cell = s.get("cell") if st is not None else None
                if cell and len(cell) == 6:
                    st.cell = tuple(float(v) for v in cell)
            self._refresh_sticks()
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
        # 工程内嵌数据解析失败等非致命问题：逐条挂到状态栏，不弹模态框
        for warn in data.get("warnings", []):
            msg += f" | {warn}"
        self._restore_result_panel(data)
        self.statusBar().showMessage(msg)

    def _restore_result_panel(self, data: dict) -> None:
        """从工程文件回填结果区（R-2a：``result_full`` 优先，其次旧摘要）。

        打开工程不重新精修也能看到上次的 R 因子、含量与收敛曲线；精修对象
        ``self._result`` 不伪造（``SolveResult`` 需要完整数据），故报告导出
        仍以"重新精修后"为准。
        """
        full = data.get("result_full") or {}
        brief = data.get("result") or {}
        rf = full.get("r_factors") or {}
        rwp = rf.get("rwp", brief.get("rwp"))
        if rwp is None:
            return
        rows = [(tr("result.rwp"), f"{rwp:.4f}")]
        for key, label in (("rp", "result.rp"), ("rexp", "result.rexp"),
                           ("chi2", "result.chi2")):
            val = rf.get(key, brief.get(key))
            if val is not None:
                rows.append((tr(label), f"{float(val):.4f}"))
        iters = (full.get("fit") or {}).get("iters", brief.get("iters"))
        if iters is not None:
            rows.append((tr("result.iters"), str(int(iters))))
        dw = (full.get("diagnostics") or {}).get("dw")
        if dw is not None:
            rows.append((tr("result.dw"), f"{float(dw):.4f}"))
        phases = full.get("phases") or brief.get("phases") or []
        esd_pct = ((full.get("esd") or {}).get("weight_esd_pct")) or []
        for i, p in enumerate(phases):
            wt = p.get("weight_pct")
            disp = self._disp(p.get("name", ""))    # v1.6：显示名
            rows.append((f"{tr('result.phase_weight')} · {disp} (%)",
                         "—" if wt is None else f"{float(wt):.3f}"))
            if i < len(esd_pct) and esd_pct[i] is not None:
                rows.append((f"e.s.d. · {disp} (pp)",
                             f"{float(esd_pct[i]):.4f}"))
        self.result_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.result_table.setItem(r, 0, QTableWidgetItem(k))
            self.result_table.setItem(r, 1, QTableWidgetItem(v))
        history = full.get("rwp_history") or []
        fig = self.conv_canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        h = np.asarray(history, dtype=float)
        if h.size:
            ax.plot(np.arange(h.size), h, color="#1f77b4", lw=1.0)
            ax.set_ylabel("Rwp (%)")
            ax.set_xlabel("eval")
            ax.grid(True, color="#e0e0e0", lw=0.5)
        self.conv_canvas.draw_idle()
        self.corr_table.setColumnCount(2)
        self.corr_table.setHorizontalHeaderLabels([tr("result.metric"),
                                                   tr("result.value")])
        diag = full.get("diagnostics") or {}
        info = [("Rwp 起始", diag.get("rwp_start")),
                ("Rwp 最终", diag.get("rwp_final")),
                ("残差判读", diag.get("verdict"))]
        info = [(k, v) for k, v in info if v is not None]
        self.corr_table.setRowCount(len(info))
        for r, (k, v) in enumerate(info):
            self.corr_table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.corr_table.setItem(
                r, 1, QTableWidgetItem(
                    f"{float(v):.4f}" if isinstance(v, (int, float)) else str(v)))

    # -- 交互 ---------------------------------------------------------- #
    def new_project(self) -> None:
        self._pattern = None
        self._pattern_path = None
        self._cif_paths.clear()
        self._phases.clear()
        self._result = None
        self._esd_cache = None      # 键含 id()，工程清空后旧键已无意义
        self._settings.clear()
        self._step_status.clear()
        self._phase_po.clear()
        self._phase_microabs.clear()
        self._phase_texture.clear()
        self._phase_aniso.clear()
        self._aniso_mode = "size"
        self._phase_edits.clear()
        self._param_snapshot = None
        self._rwp_before_step = None
        self.phase_list.clear()
        self.log_view.clear()
        self.canvas.clear()
        self.result_table.setRowCount(0)
        self.statusBar().showMessage("已新建工程")

    def open_pattern(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入谱图", "", "谱图 (*.xy *.txt *.dat *.csv *.xye);;所有文件 (*)")
        if path:
            self._load_pattern_path(Path(path))

    def _load_pattern_path(self, path, *, wavelength=None) -> bool:
        """加载谱图（供文件对话框、测试与 XinMatch .xinm 导入共用）。

        *wavelength* 显式传入时（.xinm/.xinr 场景）优先于谱图 meta。
        """
        try:
            self._pattern = load_pattern(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "谱图读取失败", str(exc))
            return False
        if wavelength is not None:
            self._pattern.meta["wavelength"] = float(wavelength)
        self._pattern_path = str(Path(path).resolve())
        # d 值换算波长：优先谱图 meta，其次默认 Cu Kα1
        self.canvas.set_wavelength(
            (self._pattern.meta or {}).get("wavelength"))
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
            item = QListWidgetItem(self._phase_item_text(st))
            # v1.6：界面显示名与内部键分离。画布显隐、QPA、结果表都用
            # CifStructure.name 作键，不能再靠 item.text() 反查。
            item.setData(Qt.UserRole, st.name)
            item.setToolTip(
                f"CIF: {st.name}\n"
                f"化学式: {phase_label(st, 'formula')}\n"
                f"物相名称: {phase_label(st, 'label')}\n"
                f"文件: {Path(p).resolve()}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.phase_list.addItem(item)
            added += 1
        self._refresh_sticks()
        self.statusBar().showMessage(f"已导入 {len(self._phases)} 个物相")
        return added

    def _phase_item_text(self, st) -> str:
        """物相列表的一行文案（v1.6）。

        默认口径下是 ``SiO2 · Quartz``：化学式在前（用户要求「默认优选
        化学式」），物相名称跟随；两者相同时只显示一个。切到「CIF 文件名」
        口径时才把文件名摆在前面，但仍然带上化学式，避免列表变成一串
        无法辨认的编号。
        """
        primary = phase_label(st, self._disp_mode)
        secondary = (phase_label(st, "label") if self._disp_mode == "formula"
                     else phase_label(st, "formula"))
        if not secondary or secondary == primary:
            return primary
        return f"{primary} · {secondary}"

    def _disp_labels(self) -> dict[str, str]:
        """当前显示口径下的 ``{相名: 展示名}``（结果表/标记条共用）。"""
        return label_map(self._phases, self._disp_mode)

    def _disp(self, name: str) -> str:
        """单个相名的展示文案（找不到结构时原样返回）。"""
        st = next((s for s in self._phases if s.name == name), None)
        return phase_label(st, self._disp_mode) if st is not None else name

    def _disp_unique(self) -> dict[str, str]:
        """``{相名: 展示名}``，重名时补足区分信息。

        锐钛矿 / 金红石 / 板钛矿的化学式都是 ``TiO2``——按化学式口径显示
        就会出现两行完全一样的「TiO2」，日志里 ``TiO2.a`` 也会重复，看不出
        是哪一相在动。这类同质多型恰恰是 XRD 定量最常见的场景，所以重名
        必须补物相名称（再不行补内部相名）。
        """
        base = self._disp_labels()
        counts: dict[str, int] = {}
        for val in base.values():
            counts[val] = counts.get(val, 0) + 1
        out: dict[str, str] = {}
        for st in self._phases:
            lab = base.get(st.name, st.name)
            if counts.get(lab, 0) > 1:
                detailed = self._phase_item_text(st)
                lab = detailed if detailed != lab else f"{lab} ({st.name})"
            out[st.name] = lab
        return out

    def set_display_mode(self, mode: str) -> None:
        """切换物相显示口径（化学式 / 物相名称 / CIF 文件名）。"""
        if mode not in PHASE_LABEL_MODES:
            return
        self._disp_mode = mode
        self.canvas.label_mode = mode
        # 物相列表：保持勾选状态重建文案
        for row in range(self.phase_list.count()):
            item = self.phase_list.item(row)
            key = item.data(Qt.UserRole)
            st = next((s for s in self._phases if s.name == key), None)
            if st is not None:
                old = item.checkState()
                item.setText(self._phase_item_text(st))
                item.setCheckState(old)
        self._refresh_sticks()
        if self._result is not None:
            self._fill_quant_tab(self._result)
            self._fill_cell_tab(self._result)
            self._fill_results(self._result)
        self.statusBar().showMessage(
            f"物相显示：{tr('disp.' + mode)}")
        for m, act in getattr(self, "_disp_actions", {}).items():
            act.setChecked(m == mode)

    def _refresh_sticks(self) -> None:
        """按每相结构算布拉格峰棒（含相对强度与择优取向权重）。"""
        if not self._phases:
            return
        sticks = []
        for st in self._phases:
            try:
                po = self._phase_po.get(st.name)
                peaks, _skipped = compute_peaks(st, 1.5406, 5.0, 90.0, po=po)
                # (2θ, |F|²·LP)：画布按相内最大值归一化成相对强度棒。
                # v1.6：第三元素是展示名（化学式/物相名称），内部键仍是
                # st.name —— 画布显隐与配色靠键，标签靠展示名。
                sticks.append((st.name,
                               [(float(p[0]), float(p[1])) for p in peaks],
                               phase_label(st, self._disp_mode)))
            except Exception:
                sticks.append((st.name, [], phase_label(st, self._disp_mode)))
        self.canvas.set_phase_sticks(sticks)
        self.canvas.refresh()

    def _on_phase_toggled(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole) or item.text()
        self.canvas.set_phase_visible(str(key),
                                      item.checkState() == Qt.Checked)

    # -- 跑码窗口（v1.6，MAUD 式滚动日志） ------------------------------ #
    def log_line(self, text: str = "") -> None:
        """向跑码窗口追加一行（自动滚到底）。"""
        self.log_view.appendPlainText(text)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self.log_view.clear()

    def _state_of(self, params, phases) -> dict[str, float]:
        """把「当前参数集合」摊平成 ``{名字: 数值}``，用于打印前后差异。

        只收**数值型**参数。晶胞按相展开成 ``SiO2.a`` 这类键，这样日志
        里能直接看出是哪个相的哪根轴在动。
        """
        out: dict[str, float] = {}
        if params is not None:
            for key in ("zero", "U", "V", "W", "eta", "asym", "bfactor",
                        "X", "Y"):
                val = getattr(params, key, None)
                if isinstance(val, (int, float)):
                    out[key] = float(val)
        labels = self._disp_unique()      # 重名相（多型）自动区分
        for st in (phases or ()):
            key = str(getattr(st, "name", ""))
            name = labels.get(key, key)
            cell = getattr(st, "cell", None) or ()
            for k, ax in enumerate(("a", "b", "c", "α", "β", "γ")):
                if k < len(cell):
                    out[f"{name}.{ax}"] = float(cell[k])
        return out

    def _log_diff(self, before: dict[str, float],
                  after: dict[str, float]) -> int:
        """打印两帧参数差异，返回变化条数。

        阈值取相对 1e-9：低于浮点噪声的「变化」不打印，否则连跑时日志会
        被一堆 1e-17 的抖动淹没，真正动了参数反而看不见。
        """
        if not before or not after:
            return 0
        n = 0
        for key, new in after.items():
            old = before.get(key)
            if old is None:
                continue
            if abs(new - old) <= 1e-9 * max(1.0, abs(old), abs(new)):
                continue
            self.log_line(tr("log.param").format(
                name=key, before=f"{old:.6g}", after=f"{new:.6g}"))
            n += 1
        return n

    def _on_step_snapshot(self, key: str, params, phases) -> None:
        """每步结束：打印参数变化（左下的「跑码」主体）。

        第一次快照没有「上一帧」可比，此时打出**当前值清单**——否则日志里
        只剩一行 Rwp，用户看不出这一轮实际在精修什么（这正是要求「滚动
        显示正在精修的具体参数」的场景）。
        """
        current = self._state_of(params, phases)
        if not self._param_snapshot:
            self.log_line(tr("log.initial"))
            for name, val in current.items():
                self.log_line(tr("log.param_init").format(
                    name=name, value=f"{val:.6g}"))
        else:
            self._log_diff(self._param_snapshot, current)
        self._param_snapshot = current

    def open_step_settings(self, step: str, title: str) -> None:
        cur = self._settings.get(step)
        # v1.6：物相显示名（化学式/名称）取代 CIF 文件名；晶胞弹窗还要
        # 结构本身才能按晶系决定哪些分量可精修。
        labels = self._disp_labels()
        names = [labels.get(s.name, s.name) for s in self._phases]
        keys = [s.name for s in self._phases]
        if step == "bg":
            # v1.5 M8d：弹窗首次打开时要把「自适应节点数」灌进去。否则
            # 会显示代码级兜底 3（cheb 时代遗留），用户点「确定」就把
            # 19 节点默默降成 3——背景灵活性骤降而界面上看不出来。
            cur = dict(cur or {})
            cur.setdefault("n_bg", adaptive_n_bg(*self._refine_window()))
        got = open_settings(step, title, names, cur, self,
                            phase_structs=self._phases)
        if got is not None:
            self._settings[step] = got
            self.statusBar().showMessage(f"已更新「{title}」设置")

    def open_phase_editor(self) -> None:
        """编辑→物相参数编辑：晶胞写回结构体，择优取向传导到前向模型。"""
        if not self._phases:
            QMessageBox.information(self, "物相参数编辑", "请先导入 CIF 物相")
            return
        dlg = PhaseEditDialog(self._phases, self._phase_edits, self,
                              anode="Cu")   # 与 _make_inputs 的硬编码一致
        if dlg.exec() != QDialog.Accepted:
            return
        got = dlg.settings()
        for name, s in got.items():
            st = next((x for x in self._phases if x.name == name), None)
            if st is None:
                continue
            cell = s.get("cell")
            if cell and len(cell) == 6:
                st.cell = tuple(float(v) for v in cell)
            self._phase_edits[name] = s
        self._phase_po = {n: s["po"] for n, s in self._phase_edits.items()
                          if s.get("po")}
        self._phase_microabs = {n: s["microabs"]
                                for n, s in self._phase_edits.items()
                                if s.get("microabs")}
        self._phase_texture = _texture_from_edits(
            self._phase_edits,
            str((self._settings.get("micro") or {}).get(
                "texture_model", "harmonic:10")))
        self._phase_aniso = _aniso_from_edits(self._phase_edits)
        self._aniso_mode = next(
            (s["aniso"]["mode"] for s in self._phase_edits.values()
             if s.get("aniso")), "size")
        self._refresh_sticks()
        self.statusBar().showMessage(
            "物相参数已更新（晶胞 / 择优取向用于下一次精修与标记条）")

    def show_about(self) -> None:
        """帮助→关于：家族版式（版权/许可继承 XinMatch）。"""
        AboutDialog(self).exec()

    def show_license(self) -> None:
        """帮助→版权与许可：双许可摘要 + 全文（v1.6.1）。"""
        LicenseDialog(self).exec()

    def _refine_window(self) -> tuple[float, float]:
        """当前精修窗口（micro 齿轮优先，其次 bg 齿轮，兜底 5–90°）。

        v1.5 M8d：背景节点数的自适应值、弹窗初值、`_make_inputs` 三处
        必须用同一个窗口口径，否则界面上显示的节点数与实跑的不一致。
        """
        bg = self._settings.get("bg", {}) or {}
        micro = self._settings.get("micro", {}) or {}
        tmin = float(micro.get("tmin", bg.get("tmin", 5.0)))
        tmax = float(micro.get("tmax", bg.get("tmax", 90.0)))
        if tmax <= tmin:
            return 5.0, 90.0
        return tmin, tmax

    def _make_inputs(self) -> RefineInputs | None:
        """按当前齿轮设置构造精修输入（同步与后台线程共用）。"""
        if self._pattern is None or not self._phases:
            QMessageBox.information(self, "无法精修",
                                    "请先导入谱图和至少一个 CIF")
            return None
        bg = self._settings.get("bg", {})
        micro = self._settings.get("micro", {}) or {}
        # v1.2.0 P1（实样对拍 §11.2 实测 −4 点均值）：真实数据出厂默认
        # tent，节点数随精修窗口自适应 ≈1 节点/6°；齿轮弹窗显式设置优先。
        # v1.4 #19：窗口可在 micro 齿轮里放开到谱图高角（背景节点数随之自适应）。
        tmin, tmax = self._refine_window()
        bg_points = tuple((float(x), float(v))
                          for x, v in (bg.get("bg_points") or ()))
        # v1.7：非晶宽包（物理分量），来自背景弹窗的勾选 + 中心/半高宽
        amorphous = tuple((float(c), float(f))
                          for c, f in (bg.get("amorphous") or ()))
        cfg = RefineConfig(
            refine_zero=True, refine_uvw=True,
            n_bg=int(bg.get("n_bg", adaptive_n_bg(tmin, tmax))),
            bg_mode=bg.get("bg_mode", "tent"),
            bg_points=bg_points,
            amorphous=amorphous,
            # v1.3：定权模式（MAUD getWeight + theoreticalWeights）
            weight_mode=bg.get("weight_mode", "sqrt"),
            # v1.3 #14：物相编辑里显式勾选织构轴才精修 T(χ)（默认关）
            refine_texture=bool(self._phase_texture),
            texture_lambda=float(bg.get("texture_lambda", 1.0)),
            # v1.3 #15：各向异性（物相编辑里显式勾选才精修；默认只放 size）
            refine_aniso=bool(self._phase_aniso),
            # v1.5 M4：GUI 出厂默认自动启用 Popa LB（物相编辑里逐相
            # 显式配置 aniso 时以用户配置为准，不再自动铺开）
            aniso_auto=(bool(micro.get("aniso_auto", True))
                        and not self._phase_aniso),
            aniso_mode=self._aniso_mode,
            # v1.4 #18/#19：B_iso 默认关；PO 自动试探 GUI 出厂默认开
            # （实样对拍 3 个差距样 −4.82 / −12.60 / −4.45 pt），
            # 可在 micro 齿轮关闭；CLI/API 默认关以保持 golden。
            refine_biso=bool(micro.get("refine_biso", False)),
            refine_xyz=bool(micro.get("refine_xyz", False)),
            xyz_phase_select=str(micro.get("xyz_phase_select", "largest")),
            po_probe=bool(micro.get("po_probe", True)),
            po_probe_min_gain=float(micro.get("po_probe_min_gain", 0.3)),
            po_probe_max_phases=int(micro.get("po_probe_max_phases", 2)),
            po_probe_max_iter=int(micro.get("po_probe_max_iter", 12)),
            # v1.5 M8：试探命中相改用球谐织构（MAUD Harmonic 口径），
            # 阶数沿用「织构模型」设置里的 harmonic:N（ewimv 时取 8）
            po_probe_to_texture=bool(micro.get("po_probe_to_texture", False)),
            po_probe_texture_degree=int(
                str(micro.get("texture_model", "harmonic:8")).partition(":")[2]
                or 8),
            tmin=tmin, tmax=tmax, max_iter=40,
            # v1.6：晶胞步的逐相自由分量（来自晶胞弹窗的勾选）。
            # None = 按晶系全放开，与 v1.5 行为逐位一致。
            cell_axes=self._cell_axes_map())
        # integrated=True 是 Rietveld 标度 S 的标准口径（Hill–Howard 定量也
        # 依赖它）：峰高口径下峰宽随 2θ 变化会直接扭曲相对强度。v1.1.0 及
        # 以前这里给 False（v0.1.0 旧口径，仅供对照），实样对拍实测同配置
        # 差 3.65 个百分点（样品 1：37.39% → 33.74%）。
        prm = ProfileParams(zero=0.0, U=0.0, V=0.0, W=0.02, eta=0.5,
                            anode="Cu", integrated=True,
                            po_r=self._phase_po or None,
                            microabs=self._phase_microabs or None,
                            texture=self._phase_texture or None,
                            aniso=self._phase_aniso or None)
        return RefineInputs(pattern=self._pattern, phases=self._phases,
                            profile=prm, config=cfg)

    def run_step(self, step: str) -> None:
        """导航单步：按配方只执行该步（后台线程）。"""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在精修", "请等待当前精修结束或点「停止」")
            return
        self._start_worker(single_step=step)

    # -- 步骤说明（v1.6） ---------------------------------------------- #
    #: 显示用轴名 → 内部键（CellDialog 的勾选键统一用 ASCII）
    _AX_KEY = {"a": "a", "b": "b", "c": "c",
               "α": "alpha", "β": "beta", "γ": "gamma"}

    def _cell_axes_for(self, name: str) -> tuple[str, ...]:
        """该相**实际会精修**的晶胞分量（晶系约束 ∩ 弹窗勾选）。

        v1.5 及以前 CellDialog 的勾选是装饰性的：引擎按晶系全放，界面
        却写死「只支持 a / c」。这里给出唯一口径，说明弹窗、精修引擎、
        结果表三处共用。
        """
        st = next((s for s in self._phases if s.name == name), None)
        if st is None:
            return ()
        from xinrefinement.core.refine.cell import crystal_system_of, resolve_axes

        cur = (self._settings.get("cell") or {}).get(name)
        requested = None
        if isinstance(cur, dict):
            requested = tuple(self._AX_KEY.get(k, k) for k, on in cur.items() if on)
        return resolve_axes(crystal_system_of(st), requested)

    def _cell_axes_map(self) -> dict[str, tuple[str, ...]] | None:
        """``RefineConfig.cell_axes``：每相实际精修的晶胞分量。

        未在弹窗里设置过时返回 ``None``（引擎按晶系全放开，v1.5 行为
        逐位不变）。设置过就逐相给出，**全部空集**也照传——那代表用户
        明确不想修晶胞，不该被默默改回全放。
        """
        cur = self._settings.get("cell")
        if not cur or not self._phases:
            return None
        return {st.name: self._cell_axes_for(st.name) for st in self._phases}

    def _fmt_num(self, val, digits: int = 5) -> str:
        if val is None:
            return "—"
        try:
            return f"{float(val):.{digits}g}"
        except (TypeError, ValueError):
            return "—"

    def _step_rows(self, step: str) -> list[tuple[str, str]]:
        """「该步精修什么 + 当前值」清单（说明弹窗与日志共用）。"""
        p = None if self._result is None else self._result.params
        labels = self._disp_unique()
        rows: list[tuple[str, str]] = []
        if step == "zero":
            rows.append(("零点 zero (°)", self._fmt_num(None if p is None else p.zero, 6)))
        elif step == "bg":
            bg = self._settings.get("bg") or {}
            rows.append(("背景模式", str(bg.get("bg_mode", "tent"))))
            from xinrefinement.core.refine.linear import adaptive_n_bg
            n_bg = bg.get("n_bg")
            if not isinstance(n_bg, int):
                n_bg = adaptive_n_bg(*self._refine_window())
            rows.append(("背景节点数", str(n_bg)))
            rows.append(("峰形基底", _width_basis_text(p)))
        elif step == "scale":
            if self._result is None:
                rows.append(("每相标度因子 S_p", "线性层解析求解，恒参与"))
            else:
                for ph in self._result.phases:
                    rows.append((f"{labels.get(ph.name, ph.name)} S",
                                 self._fmt_num(ph.scale)))
        elif step == "cell":
            if not self._phases:
                rows.append(("晶胞参数", "尚未导入物相"))
            for st in self._phases:
                axes = self._cell_axes_for(st.name)
                text = "、".join(axes) if axes else "不参与（未勾选）"
                rows.append((f"{labels.get(st.name, st.name)}", text))
        elif step == "profile":
            for k in ("U", "V", "W", "eta", "asym"):
                rows.append((k, self._fmt_num(None if p is None else getattr(p, k, None), 6)))
            rows.append(("宽度基", _width_basis_text(p)))
        elif step == "xyz":
            rows.append(("原子分数坐标", "Wyckoff 位约束下的自由方向"))
            rows.append(("超预算策略", str((self._settings.get("micro") or {}).get(
                "xyz_phase_select", "largest"))))
        elif step == "micro":
            rows.append(("TCH X（微观应变）", self._fmt_num(None if p is None else p.X, 6)))
            rows.append(("TCH Y（晶粒尺寸）", self._fmt_num(None if p is None else p.Y, 6)))
            micro = self._settings.get("micro") or {}
            rows.append(("Popa LB 各向异性", "自动" if micro.get("aniso_auto") else "关"))
            rows.append(("织构模型", str(micro.get("texture_model", "harmonic:10"))))
        elif step == "B":
            rows.append(("每相 ΔB_iso", "逐相整体平移，见结果表"))
            rows.append(("上界", "6 Å²（顶到即为过拟合信号）"))
        return rows

    def describe_step(self, step: str) -> None:
        """点 ▶ 先弹说明窗；确认后把同样的内容写进跑码窗口再启动。"""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在精修", "请等待当前精修结束或点「停止」")
            return
        title = next((s[1] for s in STEPS if s[0] == step), step)
        note = next((s.note for s in DEFAULT_STEPS if s.key == step), "")
        dlg = StepDescribeDialog(title, note, self._step_rows(step), self)
        if dlg.exec() != QDialog.Accepted:
            return
        # 与弹窗逐条对应地写日志（用户要求「与左下的跑码窗口对应」）
        self.log_line(tr("log.step_begin").format(title=title))
        self.log_line(f"{tr('stepdesc.params')}:")
        for line in dlg.describe_lines():
            self.log_line(f"  {line.strip()}")
        self._skip_begin_log = True     # 起始行已写过，别重复
        self._start_worker(single_step=step)

    def run_recipe_all(self) -> None:
        """一键连跑标准配方（后台线程）。"""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在精修", "请等待当前精修结束或点「停止」")
            return
        self._step_status.clear()
        # 新一轮开始，上一次的多型建议已过期（旧结果不再对应当前模型）
        self._polymorph_suggestion = None
        self.btn_polymorph.setVisible(False)
        self._start_worker(single_step=None)

    def _start_worker(self, single_step: str | None) -> None:
        inputs = self._make_inputs()
        if inputs is None:
            return
        # 新一轮开始：上一轮遗留的参数快照不能当基准，否则首步只会打差异
        # 而没有初值清单（连跑时各步之间仍按差异打印）。
        self._param_snapshot = None
        # v1.5 M9b：全链墙钟预算（micro 齿轮「精修时间预算」，分钟；
        # 0 = 不限）。防 GUI 单次精修 >1 h（样 4 实测 44.5 min 压线）。
        micro = self._settings.get("micro", {}) or {}
        budget_min = int(micro.get("time_budget_min", 45))
        worker = RefineWorker(inputs, steps=DEFAULT_STEPS,
                              single_step=single_step,
                              time_budget_s=max(0, budget_min) * 60.0)
        self._worker = worker
        worker.step_started.connect(self._on_step_started)
        worker.step_finished.connect(self._on_step_finished)
        worker.step_snapshot.connect(self._on_step_snapshot)
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
        title_zh = next((s[1] for s in STEPS if s[0] == key), title)
        # 本步开始前的 Rwp（连跑时 result 逐步刷新）
        self._rwp_before_step = (None if self._result is None
                                 else float(self._result.rwp))
        if self._skip_begin_log:
            self._skip_begin_log = False    # 说明弹窗已写过起始行
        else:
            self.log_line(tr("log.step_begin").format(title=title_zh))

    def _on_step_finished(self, key, status, rwp, message) -> None:
        self._step_status[key] = status
        btn = self._step_buttons.get(key)
        title = next((s[1] for s in STEPS if s[0] == key), key)
        if btn is not None:
            mark = {"done": "✓", "skipped": "–", "failed": "!"}.get(status, "")
            btn.setText(f"{mark} {tr(f'step.{key}')}"
                        if not btn.text().startswith(mark) else btn.text())
        # 跑码窗口的收尾行：Rwp 前后对照
        before = self._rwp_before_step
        self.log_line(tr("log.step_done").format(
            title=title, status=status,
            before="—" if before is None else f"{float(before):.4f}",
            after="—" if rwp is None else f"{float(rwp):.4f}"))
        if message:
            self.log_line(f"  {message}")

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
        self._refresh_polymorph_suggestion(res)

    def _refresh_polymorph_suggestion(self, res) -> None:
        """ΔB_iso 撞界 + 化学式 + 空间群命中时给出「试用另一多型」按钮。"""
        from xinrefinement.core.refine.polymorph import suggest

        try:
            sug = suggest(res, self._phases)
        except Exception:
            sug = []
        self._polymorph_suggestion = sug[0] if sug else None
        s = self._polymorph_suggestion
        if s is None:
            self.btn_polymorph.setVisible(False)
            return
        self.btn_polymorph.setText(f"{s.action_text} 并重新精修")
        self.btn_polymorph.setToolTip(f"{s.reason}\n{s.candidate.gain_note}")
        self.btn_polymorph.setVisible(True)

    def _on_apply_polymorph(self) -> None:
        """把命中的相换成内置多型 CIF，然后自动重跑配方。

        **只改当前会话的内存模型与 `_cif_paths`**，不回写用户磁盘上的 CIF
        文件——结构模型属于实验事实，软件不替用户改原始数据。
        """
        s = self._polymorph_suggestion
        if s is None:
            return
        from xinrefinement.core.refine.polymorph import apply_suggestion

        try:
            new_phases = apply_suggestion(self._phases, s)
        except Exception as exc:
            QMessageBox.warning(self, "多型替换失败", str(exc))
            return
        names = [st.name for st in self._phases]
        idx = names.index(s.phase_name)
        self._phases[:] = new_phases
        if 0 <= idx < len(self._cif_paths):
            self._cif_paths[idx] = str(s.candidate.path)
        # 旧相上的手工编辑（占位/坐标/择优取向轴）对新多型不再成立，必须丢弃
        self._phase_edits.pop(s.phase_name, None)
        self._phase_po.pop(s.phase_name, None)
        self._refresh_sticks()
        self.btn_polymorph.setVisible(False)
        self._polymorph_suggestion = None
        self.statusBar().showMessage(
            f"已把「{s.phase_name}」换成{s.candidate.label}，重新精修中…")
        self.run_recipe_all()

    def _on_worker_failed(self, msg: str) -> None:
        # 取消是用户主动行为，不弹模态框：离屏/自动化测试里模态框会
        # 永久阻塞事件循环（实测 test_cancel_stops_recipe 挂死 12 分钟）。
        cancelled = (self._worker is not None
                     and self._worker.is_cancelled)
        if not cancelled:
            QMessageBox.warning(self, "精修未完成", msg)
        self.lbl_progress.setText("已停止" if cancelled else msg)

    def _on_worker_done(self) -> None:
        # v1.6.2：取消后不再停在「正在执行…」——那是用户点停止时最困惑的
        # 一幕（按钮已置灰、进度条还写着某步在跑）。取消是步内生效的，
        # 结果可能已经部分回填，所以这里只改文案与日志，不动结果区。
        cancelled = self._worker is not None and self._worker.is_cancelled
        self.btn_run_all.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        for btn in self._step_buttons.values():
            btn.setEnabled(True)
        if cancelled:
            self.lbl_progress.setText("已停止")
            self.statusBar().showMessage("已停止")
            self.log_line(tr("log.cancelled"))

    def _background_curve(self, res):
        """背景系数 -> 背景曲线（失败时返回 None）。"""
        try:
            cfg = res.config
            if cfg.bg_mode == "manual":
                # 固定曲线（bg=[1.0] 占位）：由锚点重建
                pts = list(cfg.bg_points) or None
                if not pts:
                    return None
                return (background_basis(res.pattern.two_theta, 1, "manual",
                                         points=pts)
                        @ np.ones(1, dtype=float))
            if cfg.bg_mode == "interp":
                # v1.2.0 两层可加：固定插值曲线 + 其上 Chebyshev（bg 系数）
                pts = list(cfg.bg_points) or None
                if not pts:
                    return None
                fixed = (background_basis(res.pattern.two_theta, 1, "manual",
                                          points=pts)
                         @ np.ones(1, dtype=float))
                cheb = (background_basis(res.pattern.two_theta,
                                         len(res.background), "cheb")
                        @ np.asarray(res.background, dtype=float))
                return fixed + cheb
            return (background_basis(res.pattern.two_theta,
                                     len(res.background),
                                     cfg.bg_mode)
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

    def _esd_for(self, res):
        """取 e.s.d.：同一精修结果的多次请求复用同一份结果。

        一次 estimate_esd 要跑 4p 次全谱前向，全在主线程；失败路径同样昂贵，
        所以算出来的 None 也一并缓存。失效靠键（新精修=新 SolveResult）。

        键里的 ``id(res)`` 在对象被 GC 后可能被新对象复用，故并放 rwp/iters/
        相名+cell 做兜底；重开工程时 ``_esd_cache`` 直接清空。
        返回对象被多处共享（缓存命中即同一实例），调用方不得原地修改其 ndarray。
        """
        key = (id(res), getattr(res, "rwp", None), getattr(res, "iters", None),
               id(self._phases),
               tuple((getattr(p, "name", None), tuple(getattr(p, "cell", ()) or ()))
                     for p in self._phases))
        if self._esd_cache is not None and self._esd_cache[0] == key:
            return self._esd_cache[1]
        # 函数内 import：测试靠 monkeypatch 模块属性注入计数/异常实现
        from xinrefinement.core.refine.esd import estimate_esd
        try:
            value = estimate_esd(self._phases, res)
        except Exception:
            value = None
        self._esd_cache = (key, value)
        return value

    def _fill_results(self, res) -> None:
        """P3.5：摘要 + 收敛曲线 + 相关性矩阵 + DW/e.s.d.。"""
        from xinrefinement.core.refine.diagnostics import diagnose

        diag = diagnose(res)
        rows = [(tr("result.rwp"), f"{res.rwp:.4f}"),
                (tr("result.rp"), f"{res.rp:.4f}"),
                (tr("result.rexp"), f"{res.rexp:.4f}"),
                (tr("result.chi2"), f"{res.chi2:.4f}"),
                (tr("result.iters"), str(res.iters)),
                (tr("result.dw"), f"{diag.dw:.4f}")]
        weight_esd = None
        esd = self._esd_for(res)
        if esd is not None:
            weight_esd = esd.weight_esd_pct
            rows.append(("Rwp 下降 (pp)", f"{diag.rwp_drop:.4f}"))
        for i, p in enumerate(res.phases):
            wt = "—" if p.weight_pct is None else f"{p.weight_pct:.3f}"
            disp = self._disp_unique().get(p.name, p.name)   # v1.6：显示名
            rows.append((f"{tr('result.phase_weight')} · {disp} (%)", wt))
            if weight_esd:
                rows.append((f"e.s.d. · {disp} (pp)",
                             f"{weight_esd[i]:.4f}"))
        self.result_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.result_table.setItem(r, 0, QTableWidgetItem(k))
            self.result_table.setItem(r, 1, QTableWidgetItem(v))
        self._fill_quant_tab(res, weight_esd)
        self._fill_cell_tab(res)
        self._draw_convergence(res)
        self._draw_correlation(esd)

    def _fill_quant_tab(self, res, weight_esd=None) -> None:
        """物相定量页（v1.6）：显示名 / wt% / e.s.d. / Z / 晶胞体积。

        首列走 ``_disp()``，默认给化学式 —— 用户明确要求「不是 CIF 文件名」。
        末行给合计：QPA 的 wt% 理论上归一到 100，合计行是最快的一致性检查。
        """
        headers = [tr("quant.phase"), tr("quant.wt"), tr("quant.esd"),
                   tr("quant.z"), tr("quant.volume")]
        self.quant_table.setColumnCount(len(headers))
        self.quant_table.setHorizontalHeaderLabels(headers)
        phases = list(getattr(res, "phases", ()) or ())
        labels = self._disp_unique()       # 多型同化学式时带物相名区分
        total = 0.0
        quantifiable = True
        self.quant_table.setRowCount(len(phases) + 1)
        for i, ph in enumerate(phases):
            wt = None if ph.weight_pct is None else float(ph.weight_pct)
            if wt is None:
                quantifiable = False
            else:
                total += wt
            esd = "—"
            if weight_esd is not None and i < len(weight_esd):
                esd = f"{weight_esd[i]:.4f}"
            cells = [labels.get(ph.name, ph.name),
                     "—" if wt is None else f"{wt:.3f}",
                     esd,
                     "—" if ph.z is None else str(int(ph.z)),
                     f"{float(ph.volume):.3f}"]
            for c, text in enumerate(cells):
                self.quant_table.setItem(i, c, QTableWidgetItem(text))
        row = len(phases)
        total_text = f"{total:.3f}" if quantifiable else "—"
        for c, text in enumerate([tr("quant.total"), total_text, "", "", ""]):
            self.quant_table.setItem(row, c, QTableWidgetItem(text))

    def _aniso_mean(self, coeffs) -> float:
        """各向异性系数的「平均主值」（Cholesky 矩阵奇异值均值）。

        界面要给一个数（晶粒尺寸 / 应变），各向异性模型本身是张量。
        取奇异值均值等价于「体积平均」，与各向同性标量同量纲可比；
        真正的各向异性比在 ``aniso_ratios`` 里，属诊断信息。
        """
        import numpy as np

        c = list(coeffs or ())
        if len(c) < 6:
            c = c + [0.0] * (6 - len(c))
        mat = np.array([[c[0], 0.0, 0.0],
                        [c[1], c[2], 0.0],
                        [c[3], c[4], c[5]]], dtype=np.float64)
        sv = np.linalg.svd(mat, compute_uv=False)
        return float(np.mean(sv))

    def _size_strain_of(self, res, name: str) -> tuple[float, float, bool]:
        """该相的 (晶粒尺寸 Å, 微观应变 ε, 是否各向异性)。

        优先各向异性系数（micro 步开 Popa LB 后标量 X/Y 就不再精修了，
        只读 X/Y 会一直显示初值）；没有各向异性配置时退回 TCH 标量项。
        """
        from xinrefinement.core.profile.size_strain import (
            size_from_y, strain_from_x)

        p = getattr(res, "params", None)
        if p is None:
            return float("inf"), 0.0, False
        wl = float(getattr(p, "wavelength", 1.5406) or 1.5406)
        aniso = (getattr(p, "aniso", None) or {}).get(name)
        if aniso:
            inv_d = self._aniso_mean(aniso.get("size"))
            eps = self._aniso_mean(aniso.get("strain"))
            size = (1.0 / inv_d) if inv_d > 1e-12 else float("inf")
            return size, eps, True
        return size_from_y(float(getattr(p, "Y", 0.0) or 0.0), wl), \
            strain_from_x(float(getattr(p, "X", 0.0) or 0.0)), False

    def _fill_cell_tab(self, res) -> None:
        """晶胞与微结构页（v1.6）：a b c α β γ / V / D / ε / 精修分量。"""
        headers = [tr("quant.phase"), tr("cell.axes"),
                   tr("cell.a"), tr("cell.b"), tr("cell.c"),
                   tr("cell.alpha"), tr("cell.beta"), tr("cell.gamma"),
                   tr("cell.volume"), tr("cell.size"), tr("cell.strain")]
        self.cell_table.setColumnCount(len(headers))
        self.cell_table.setHorizontalHeaderLabels(headers)
        phases = list(getattr(res, "phases", ()) or ())
        labels = self._disp_unique()
        self.cell_table.setRowCount(len(phases))
        for i, ph in enumerate(phases):
            cell = list(ph.cell or []) + [float("nan")] * 6
            size, eps, aniso = self._size_strain_of(res, ph.name)
            axes = "、".join(self._cell_axes_for(ph.name)) or tr("cell.none")
            size_text = "—" if (not size or size == float("inf")
                                or size <= 0) else f"{size:.1f}"
            if aniso:
                size_text = f"{size_text} *"
            cells = [labels.get(ph.name, ph.name), axes,
                     f"{cell[0]:.5f}", f"{cell[1]:.5f}", f"{cell[2]:.5f}",
                     f"{cell[3]:.4f}", f"{cell[4]:.4f}", f"{cell[5]:.4f}",
                     f"{float(ph.volume):.3f}",
                     size_text, f"{eps:.3e}"]
            for c, text in enumerate(cells):
                self.cell_table.setItem(i, c, QTableWidgetItem(text))
        # 各向异性标记的说明（放在最后一行之外的 tooltip 里更干净，
        # 这里直接挂到表头，避免多出一个空行）
        self.cell_table.horizontalHeaderItem(9).setToolTip(tr("cell.aniso"))
        self.cell_table.resizeColumnsToContents()

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
        from xinrefinement.core.report import export_report as _export

        esd = self._esd_for(self._result)
        out = Path(path)
        try:
            paths = _export(self._result, out.parent, stem=out.stem, esd=esd)
        except Exception as exc:
            QMessageBox.warning(self, tr("toolbar.report"), str(exc))
            return
        self.statusBar().showMessage(
            f"{tr('toolbar.report')}: {', '.join(Path(p).name for p in paths.values())}")
