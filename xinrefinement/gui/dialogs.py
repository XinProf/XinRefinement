"""P3.4 · 齿轮状设置弹窗（按导航步骤分组）。

草图要求：每个功能旁边一个齿轮图标，打开弹出窗口做详细设置。
本模块提供参数组设置对话框；其中「背景曲线」与「多物相晶胞参数」是
草图明确点名的两个重点，做了实质控件，其余组用通用开关表。

所有弹窗只产出**设置字典**（``settings()``），不直接调用 core，
由主窗口把设置翻译成 ``RefineConfig`` / ``ParameterRegistry`` 开关。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: 导航步骤 → (标题, 组名)
STEPS: tuple[tuple[str, str, str], ...] = (
    ("zero", "零点 / 样品漂移", "谱参数"),
    ("bg", "背景 + 峰形", "谱参数"),
    ("scale", "标度因子", "谱参数"),
    ("cell", "晶胞参数", "结构"),
    ("profile", "峰形参数", "谱参数"),
    ("xyz", "原子坐标", "结构"),
    ("B", "温度因子", "结构"),
    ("micro", "微结构 / 应力 / 择优取向", "高级"),
)


class _BaseDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"设置 · {title}")
        self.setMinimumWidth(360)
        self._root = QVBoxLayout(self)

    def _add_buttons(self) -> None:
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._root.addWidget(box)

    def settings(self) -> dict:
        raise NotImplementedError


class BackgroundDialog(_BaseDialog):
    """精修背景曲线：函数类型 / 项数 / 手动插值点。"""

    def __init__(self, current: dict | None = None, parent=None) -> None:
        super().__init__("背景曲线", parent)
        cur = current or {}
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["cheb（Chebyshev 多项式）", "tent（分片线性帽）",
                            "interp（自动提取·固定曲线）",
                            "manual（手动插值点）"])
        self.mode.setCurrentIndex({"cheb": 0, "tent": 1, "interp": 2,
                                   "manual": 3}.get(cur.get("bg_mode", "cheb"),
                                                    0))
        self.n_terms = QSpinBox()
        # v1.5 M8d：上限从 30 放到 60。tent 节点走线性层解析求解，
        # **加节点不增加残差评估次数**（几乎免费），而 5–120° 每 2.5°
        # 一节点需要 46 个（实测 5/6 样 Rwp −0.35…−1.07，见立项书
        # §1.9）；旧上限 30 等于把这条路堵死（30 节点 ≈ 每 3.8°）。
        self.n_terms.setRange(1, 60)
        self.n_terms.setValue(int(cur.get("n_bg", 3)))
        self.n_terms.setToolTip(
            "tent/interp 的节点数（≈ 1 节点 / 6° 是出厂自适应值，"
            "背景起伏明显或荧光本底重时可试 1.5–2 倍）")
        form.addRow("背景函数", self.mode)
        form.addRow("阶数 / 节点数", self.n_terms)
        # v1.3：定权模式（MAUD getWeight + theoreticalWeights）
        self.weight = QComboBox()
        self.weight.addItems(["sqrt（计数统计·默认）", "file（谱图自带 σ）",
                              "unit（常数权）", "1/y（σ∝y）",
                              "theoretical（σ 取计算值·抗弱峰噪声）"])
        self.weight.setCurrentIndex(
            {"sqrt": 0, "file": 1, "unit": 2, "1/y": 3,
             "theoretical": 4}.get(cur.get("weight_mode", "sqrt"), 0))
        self.weight.setToolTip(
            "theoreticalWeights：用计算强度代替观测强度定权，"
            "弱峰/低信噪比数据更稳健")
        form.addRow("定权模式", self.weight)
        self._root.addLayout(form)

        grp = QGroupBox("手动插值点（仅 manual 模式生效）")
        lay = QVBoxLayout(grp)
        lay.addWidget(QLabel("在下方填入 2θ 与强度；留空行忽略。"))
        self.table = QTableWidget(6, 2)
        self.table.setHorizontalHeaderLabels(["2θ (°)", "强度 (cts)"])
        for r, (x, y) in enumerate(cur.get("bg_points", [])):
            if r >= self.table.rowCount():
                break
            self.table.setItem(r, 0, QTableWidgetItem(f"{x:g}"))
            self.table.setItem(r, 1, QTableWidgetItem(f"{y:g}"))
        lay.addWidget(self.table)
        self._root.addWidget(grp)
        self._add_buttons()

    def settings(self) -> dict:
        mode = ("cheb", "tent", "interp", "manual")[self.mode.currentIndex()]
        pts = []
        for r in range(self.table.rowCount()):
            a, b = self.table.item(r, 0), self.table.item(r, 1)
            if a and b and a.text().strip() and b.text().strip():
                try:
                    pts.append((float(a.text()), float(b.text())))
                except ValueError:
                    pass
        # v1.2.0：manual 不再降级为 cheb —— bg_points 已接进引擎
        # （solve_linear_detail 固定背景分支）；interp 由 solve() 自动提取。
        return {"bg_mode": mode,
                "n_bg": int(self.n_terms.value()),
                "bg_points": pts, "manual_points": mode == "manual",
                "weight_mode": ("sqrt", "file", "unit", "1/y",
                                "theoretical")[self.weight.currentIndex()]}


class CellDialog(_BaseDialog):
    """晶胞参数修正：按导入 CIF 列出**多个物相分别设置**（草图重点）。"""

    AXES = ("a", "b", "c", "α", "β", "γ")

    def __init__(self, phase_names: list[str], current: dict | None = None,
                 parent=None) -> None:
        super().__init__("晶胞参数（多物相）", parent)
        cur = current or {}
        self._boxes: dict[tuple[str, str], QCheckBox] = {}
        if not phase_names:
            self._root.addWidget(QLabel("尚未导入 CIF；请先导入物相。"))
        for name in phase_names:
            grp = QGroupBox(name)
            lay = QVBoxLayout(grp)
            lay.addWidget(QLabel("勾选要精修的晶胞分量（当前引擎支持 a / c 缩放，"
                                "全 6 参数由 P1.2 开放）"))
            for ax in self.AXES:
                cb = QCheckBox(ax)
                cb.setChecked(bool(cur.get(name, {}).get(ax, ax in ("a", "c"))))
                if ax not in ("a", "c"):
                    cb.setEnabled(False)
                    cb.setToolTip("P1.2 全晶胞精修开放")
                self._boxes[(name, ax)] = cb
                lay.addWidget(cb)
            self._root.addWidget(grp)
        self._add_buttons()

    def settings(self) -> dict:
        return {name: {ax: self._boxes[(name, ax)].isChecked()
                       for ax in self.AXES
                       if (name, ax) in self._boxes}
                for name in {n for n, _ in self._boxes}}


class GenericDialog(_BaseDialog):
    """通用参数组设置：开关表（供 P3.3 配方引擎接具体参数）。"""

    OPTIONS: dict[str, tuple[str, ...]] = {
        "zero": ("零点偏移", "样品位移 (S·cosθ)"),
        "scale": ("每相标度因子 S_p",),
        "profile": ("U", "V", "W", "η (pseudo-Voigt 混合)", "低角不对称 asym",
                    "Kα1/Kα2 比", "TCH 尺寸项 Y", "TCH 应变项 X"),
        "xyz": ("原子分数坐标 x/y/z（Wyckoff 位约束）",),
        "B": ("各向同性温度因子 B_iso",),
        "micro": ("晶粒尺寸 D (Scherrer)", "微观应变 ε",
                  "March–Dollase 择优取向 r", "惯习面 (hkl)"),
    }

    def __init__(self, step: str, title: str,
                 current: dict | None = None, parent=None) -> None:
        super().__init__(title, parent)
        cur = current or {}
        self._checks: dict[str, QCheckBox] = {}
        grp = QGroupBox("可精修参数")
        lay = QVBoxLayout(grp)
        for opt in self.OPTIONS.get(step, ()):  # 无选项时给空态提示
            cb = QCheckBox(opt)
            cb.setChecked(bool(cur.get(opt, True)))
            self._checks[opt] = cb
            lay.addWidget(cb)
        if not self._checks:
            lay.addWidget(QLabel("该步骤参数由配方引擎自动管理。"))
        self._root.addWidget(grp)
        self._add_buttons()

    def settings(self) -> dict:
        return {opt: cb.isChecked() for opt, cb in self._checks.items()}


class PhaseEditDialog(_BaseDialog):
    """编辑→物相参数编辑：按相编辑晶胞 / 择优取向 / 对称性描述。

    只产出**设置字典**，写回结构体与 ProfileParams 由主窗口负责：

    - ``cell``：直接写回 ``struct.cell``（影响下一次精修与标记条）；
    - ``po``： ``(h,k,l,r)`` 或 None，写回 ``ProfileParams.po_r`` 并用于
      ``compute_peaks(po=...)``；
    - ``symmetry``：空间群 / 点群 / 劳厄群的显示与记录（元数据，暂不
      参与精修约束）。
    """

    AXES = ("a", "b", "c", "α", "β", "γ")
    #: 常用点群（可编辑下拉，覆盖 7 大晶系的典型选择）
    POINT_GROUPS = ("", "1", "2", "m", "2/m", "222", "mm2", "mmm",
                    "4", "4/m", "4/mmm", "-4", "422",
                    "3", "-3", "32", "3m", "-3m",
                    "6", "6/m", "6/mmm", "-6", "622",
                    "23", "m-3", "m-3m", "432", "-43m")
    #: 11 种劳厄群
    LAUE_GROUPS = ("", "-1", "2/m", "mmm", "4/m", "4/mmm",
                   "-3", "-3m", "6/m", "6/mmm", "m-3", "m-3m")

    def __init__(self, phase_structs: list, current: dict | None = None,
                 parent=None, anode: str = "Cu") -> None:
        """``phase_structs``: CifStructure 列表；``current``: 既往设置。"""
        super().__init__("物相参数编辑", parent)
        cur = current or {}
        self._structs = list(phase_structs)
        self._anode = (anode or "Cu").strip() or "Cu"
        self.setMinimumWidth(430)

        if not self._structs:
            self._root.addWidget(QLabel("尚未导入 CIF；请先导入物相。"))
            self._add_buttons()
            return

        top = QHBoxLayout()
        top.addWidget(QLabel("物相"))
        self.combo = QComboBox()
        for st in self._structs:
            self.combo.addItem(st.name)
        top.addWidget(self.combo, 1)
        self._root.addLayout(top)

        self._stack = QStackedWidget()
        self._root.addWidget(self._stack)

        self._cell_boxes: dict[str, list[QDoubleSpinBox]] = {}
        self._po_enable: dict[str, QCheckBox] = {}
        self._po_hkl: dict[str, list[QSpinBox]] = {}
        self._po_r: dict[str, QDoubleSpinBox] = {}
        self._ma_enable: dict[str, QCheckBox] = {}
        self._ma_value: dict[str, QDoubleSpinBox] = {}
        self._tx_enable: dict[str, QCheckBox] = {}
        self._tx_hkl: dict[str, list[QSpinBox]] = {}
        self._an_enable: dict[str, QCheckBox] = {}
        self._an_mode: dict[str, QComboBox] = {}
        self._sg_edit: dict[str, QLineEdit] = {}
        self._pg_edit: dict[str, QComboBox] = {}
        self._laue_edit: dict[str, QComboBox] = {}

        for st in self._structs:
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 0, 0, 0)
            saved = cur.get(st.name, {})

            # -- 晶胞参数 ---------------------------------------------- #
            grp_cell = QGroupBox("晶胞参数 (Å / °)")
            cf = QFormLayout(grp_cell)
            boxes: list[QDoubleSpinBox] = []
            saved_cell = saved.get("cell")
            for k, ax in enumerate(self.AXES):
                sb = QDoubleSpinBox()
                if k < 3:
                    sb.setRange(0.5, 200.0)
                    sb.setDecimals(5)
                    sb.setSingleStep(0.001)
                else:
                    sb.setRange(5.0, 175.0)
                    sb.setDecimals(3)
                    sb.setSingleStep(0.01)
                val = (saved_cell[k] if saved_cell else st.cell[k])
                sb.setValue(float(val))
                boxes.append(sb)
                cf.addRow(ax, sb)
            self._cell_boxes[st.name] = boxes
            pv.addWidget(grp_cell)

            # -- 择优取向（March–Dollase） ------------------------------ #
            grp_po = QGroupBox("择优取向 (March–Dollase)")
            pf = QFormLayout(grp_po)
            en = QCheckBox("启用")
            en.setChecked(bool(saved.get("po")))
            pf.addRow(en)
            hkl_row = QHBoxLayout()
            hkl_boxes: list[QSpinBox] = []
            saved_po = saved.get("po")
            for k in range(3):
                sb = QSpinBox()
                sb.setRange(-9, 9)
                sb.setValue(int(saved_po[k]) if saved_po else 0)
                hkl_boxes.append(sb)
                hkl_row.addWidget(sb)
            pf.addRow("择优面 (h k l)", hkl_row)
            r_sb = QDoubleSpinBox()
            r_sb.setRange(0.1, 5.0)
            r_sb.setDecimals(3)
            r_sb.setSingleStep(0.05)
            r_sb.setValue(float(saved_po[3]) if saved_po else 1.0)
            pf.addRow("r (1 = 无取向)", r_sb)
            en.toggled.connect(r_sb.setEnabled)
            for sb in hkl_boxes:
                en.toggled.connect(sb.setEnabled)
            r_sb.setEnabled(en.isChecked())
            for sb in hkl_boxes:
                sb.setEnabled(en.isChecked())
            self._po_enable[st.name] = en
            self._po_hkl[st.name] = hkl_boxes
            self._po_r[st.name] = r_sb
            pv.addWidget(grp_po)

            # -- 微吸收（Brindley，v1.2.0） ------------------------------ #
            grp_ma = QGroupBox("微吸收校正 (Brindley)")
            mf = QFormLayout(grp_ma)
            ma_en = QCheckBox("启用（高吸收相：Fe 相 / 萤石等）")
            saved_ma = saved.get("microabs")
            ma_en.setChecked(saved_ma is not None and saved_ma > 0)
            mf.addRow(ma_en)
            ma_sb = QDoubleSpinBox()
            ma_sb.setRange(0.01, 20.0)
            ma_sb.setDecimals(3)
            ma_sb.setSingleStep(0.1)
            ma_sb.setValue(float(saved_ma) if saved_ma else 1.0)
            mf.addRow("μ·r（吸收系数×晶粒半径）", ma_sb)
            ma_en.toggled.connect(ma_sb.setEnabled)
            ma_sb.setEnabled(ma_en.isChecked())
            # v1.3: μ·r 自动计算（CIF 化学成分 + 晶粒尺寸，core.absorption）。
            # μ·r 不可精修（与每相 scale 简并），正确来源就是按成分计算。
            grain_sb = QDoubleSpinBox()
            grain_sb.setRange(0.01, 500.0)
            grain_sb.setDecimals(2)
            grain_sb.setSingleStep(0.5)
            grain_sb.setValue(5.0)
            grain_sb.setToolTip(
                "平均晶粒半径 r（球半径，μm）；μ 按该相化学成分与理论密度自动计算")
            ma_auto = QPushButton("按成分计算 μ·r")

            def _auto_calc(name=st.name, sb=ma_sb, gsb=grain_sb,
                           struct=st, box=ma_en):
                try:
                    from xinrefinement.core.absorption import calc_mu_r
                    r = calc_mu_r(struct, gsb.value(), anode=self._anode)
                except Exception as exc:
                    QMessageBox.warning(self, "μ·r 计算失败", str(exc))
                    return
                box.setChecked(True)
                sb.setValue(min(max(r["mur"], 0.01), 20.0))
                sb.setEnabled(True)
                QMessageBox.information(
                    self, f"μ·r 已计算（{name}）",
                    f"阳极: {r['anode']} Kα1\n"
                    f"μ/ρ = {r['mu_rho']:.2f} cm²/g\n"
                    f"ρ   = {r['density']:.3f} g/cm³\n"
                    f"μ   = {r['mu_cm']:.1f} cm⁻¹\n"
                    f"μ·r = {r['mur']:.3f}  (r = {gsb.value():.2f} μm)")

            ma_auto.clicked.connect(_auto_calc)
            mf.addRow("晶粒半径 r (μm)", grain_sb)
            mf.addRow(ma_auto)
            self._ma_enable[st.name] = ma_en
            self._ma_value[st.name] = ma_sb
            pv.addWidget(grp_ma)

            # -- 织构（EWIMV 离散 ODF，v1.3 任务 #14） ------------------- #
            grp_tx = QGroupBox("织构 (EWIMV 离散 ODF)")
            tf = QFormLayout(grp_tx)
            tx_en = QCheckBox("启用（每反射 T(χ)，19 点 0–90° 网格）")
            saved_tx = saved.get("texture") or {}
            tx_en.setChecked(bool(saved_tx))
            tf.addRow(tx_en)
            tx_row = QHBoxLayout()
            tx_boxes: list[QSpinBox] = []
            saved_axis = saved_tx.get("axis") or (0, 0, 1)
            for k in range(3):
                sb = QSpinBox()
                sb.setRange(-12, 12)
                sb.setValue(int(saved_axis[k]))
                tx_boxes.append(sb)
                tx_row.addWidget(sb)
            tf.addRow("织构轴 (h k l)", tx_row)
            hint = QLabel("与 March–Dollase 互斥：开织构后该相 r 被忽略")
            hint.setWordWrap(True)
            tf.addRow(hint)

            def _tx_toggle(on, en_po=en, r_po=r_sb, hkl_po=hkl_boxes):
                for sb in tx_boxes:
                    sb.setEnabled(on)
                # 互斥：开织构时停用本相 March–Dollase（不给同一自由度两套模型）
                if on:
                    en_po.setChecked(False)
                en_po.setEnabled(not on)

            tx_en.toggled.connect(_tx_toggle)
            for sb in tx_boxes:
                sb.setEnabled(tx_en.isChecked())
            en.setEnabled(not tx_en.isChecked())
            self._tx_enable[st.name] = tx_en
            self._tx_hkl[st.name] = tx_boxes
            pv.addWidget(grp_tx)

            # -- 各向异性尺寸/应变（Popa LB，v1.3 任务 #15） -------------- #
            grp_an = QGroupBox("各向异性尺寸 / 应变 (Popa LB)")
            af = QFormLayout(grp_an)
            an_en = QCheckBox("启用（按晶向取 D 与 ε，替代标量 X/Y）")
            saved_an = saved.get("aniso") or {}
            an_en.setChecked(bool(saved_an))
            af.addRow(an_en)
            an_mode = QComboBox()
            an_mode.addItems(("size", "strain", "both"))
            an_mode.setCurrentText(str(saved_an.get("mode", "size")))
            an_mode.setToolTip(
                "size=只精修尺寸（推荐，6 参）\nstrain=只精修应变（6 参）\n"
                "both=两族同时（12 参，可能互相吸收，谨慎）")
            af.addRow("精修模式", an_mode)
            an_hint = QLabel(
                "各向同性起点 D≈1000 Å；方向依赖由 6 个 Cholesky 系数描述")
            an_hint.setWordWrap(True)
            af.addRow(an_hint)
            an_en.toggled.connect(an_mode.setEnabled)
            an_mode.setEnabled(an_en.isChecked())
            self._an_enable[st.name] = an_en
            self._an_mode[st.name] = an_mode
            pv.addWidget(grp_an)

            # -- 对称性（空间群 / 点群 / 劳厄群） ----------------------- #
            grp_sym = QGroupBox("对称性")
            sf = QFormLayout(grp_sym)
            sg = QLineEdit(st.spacegroup or "")
            sg.setPlaceholderText("来自 CIF 的 H-M 符号")
            sf.addRow("空间群", sg)
            pg = QComboBox()
            pg.setEditable(True)
            pg.addItems(self.POINT_GROUPS)
            pg.setCurrentText(str(saved.get("point_group", "")))
            sf.addRow("点群", pg)
            laue = QComboBox()
            laue.setEditable(True)
            laue.addItems(self.LAUE_GROUPS)
            laue.setCurrentText(str(saved.get("laue_group", "")))
            sf.addRow("劳厄群", laue)
            if st.sg_number:
                sf.addRow("国际表号", QLabel(str(st.sg_number)))
            self._sg_edit[st.name] = sg
            self._pg_edit[st.name] = pg
            self._laue_edit[st.name] = laue
            pv.addWidget(grp_sym)

            self._stack.addWidget(page)

        self.combo.currentIndexChanged.connect(self._stack.setCurrentIndex)
        self._add_buttons()

    def settings(self) -> dict:
        out: dict = {}
        for st in self._structs:
            cell = [float(sb.value()) for sb in self._cell_boxes.get(
                st.name, [])]
            po = None
            if st.name in self._po_enable and self._po_enable[st.name].isChecked():
                hkl = [int(sb.value()) for sb in self._po_hkl[st.name]]
                po = (hkl[0], hkl[1], hkl[2], float(self._po_r[st.name].value()))
            out[st.name] = {
                "cell": cell,
                "po": po,
                "microabs": (float(self._ma_value[st.name].value())
                             if st.name in self._ma_enable
                             and self._ma_enable[st.name].isChecked() else None),
                "texture": ({"axis": tuple(int(sb.value())
                                           for sb in self._tx_hkl[st.name])}
                            if st.name in self._tx_enable
                            and self._tx_enable[st.name].isChecked() else None),
                "aniso": ({"mode": self._an_mode[st.name].currentText()}
                          if st.name in self._an_enable
                          and self._an_enable[st.name].isChecked() else None),
                "spacegroup": self._sg_edit[st.name].text().strip(),
                "point_group": self._pg_edit[st.name].currentText().strip(),
                "laue_group": self._laue_edit[st.name].currentText().strip(),
            }
        return out


class MicroDialog(_BaseDialog):
    """v1.4 #19：micro 步策略（PO 自动试探）+ 全局精修窗口。"""

    def __init__(self, current: dict | None = None, parent=None) -> None:
        super().__init__("微结构与精修窗口", parent)
        cur = current or {}
        form = QFormLayout()

        self.probe = QCheckBox("micro 步自动试探择优取向惯习面 (hkl)")
        # v1.4 #20 实测：7 样对拍中 3 个差距样分别 −4.82 / −12.60 /
        # −4.45 pt（样品 3 精确选中 CaF₂(111)，与 MAUD 报告一致），
        # 故 GUI 出厂默认开启；CLI/API 仍默认关，保证 golden 零回归。
        self.probe.setChecked(bool(cur.get("po_probe", True)))
        self.probe.setToolTip(
            "逐相 × 低指数候选轴短精修 March–Dollase r，按 Rwp 增益自动选轴；"
            "用户已设置的 PO 相与开 EWIMV 织构的相不参与试探")
        form.addRow(self.probe)

        self.min_gain = QDoubleSpinBox()
        self.min_gain.setRange(0.0, 20.0)
        self.min_gain.setDecimals(2)
        self.min_gain.setSingleStep(0.1)
        self.min_gain.setValue(float(cur.get("po_probe_min_gain", 0.3)))
        self.min_gain.setToolTip("Rwp 至少下降这么多百分点才纳入该相（挡噪声）")
        form.addRow("PO 试探阈值 (Rwp pt)", self.min_gain)

        self.max_phases = QSpinBox()
        self.max_phases.setRange(1, 10)
        self.max_phases.setValue(int(cur.get("po_probe_max_phases", 2)))
        form.addRow("最多纳入相数", self.max_phases)

        self.max_iter = QSpinBox()
        self.max_iter.setRange(2, 40)
        self.max_iter.setValue(int(cur.get("po_probe_max_iter", 12)))
        form.addRow("每候选迭代上限", self.max_iter)

        self.aniso_auto = QCheckBox("micro 步自动启用 Popa LB 各向异性展宽")
        # v1.5 M4 实测：样 1 Rwp 16.085→12.596、样 7 21.001→17.193
        # （逐相 6 参各向异性尺寸二次型，ΔB_iso 撞界同时消失），
        # 故 GUI 出厂默认开启；CLI/API 仍默认关，保证 golden 零回归。
        self.aniso_auto.setChecked(bool(cur.get("aniso_auto", True)))
        self.aniso_auto.setToolTip(
            "为每个未单独配置的相补一个各向同性起点后精修（size 6 参/相）；"
            "窗口内独立晶向不足的相自动跳过；"
            "物相编辑里已显式勾选/取消各向异性的相优先")
        form.addRow(self.aniso_auto)

        # v1.5 M3：织构模型选择（对「物相编辑」里勾选了织构轴的相统一生效）
        self.texture_model = QComboBox()
        self.texture_model.addItem("EWIMV 离散网格（19 点 T(χ)）", "ewimv")
        self.texture_model.addItem("球谐 Legendre 阶 4（2 参）", "harmonic:4")
        self.texture_model.addItem("球谐 Legendre 阶 6（3 参）", "harmonic:6")
        self.texture_model.addItem("球谐 Legendre 阶 8（4 参）", "harmonic:8")
        self.texture_model.addItem("球谐 Legendre 阶 10（5 参）", "harmonic:10")
        _tm = str(cur.get("texture_model", "harmonic:10"))
        for _i in range(self.texture_model.count()):
            if self.texture_model.itemData(_i) == _tm:
                self.texture_model.setCurrentIndex(_i)
                break
        self.texture_model.setToolTip(
            "球谐＝MAUD Harmonic 模型在纤维对称下的精确子空间"
            "（Legendre 偶数阶展开，基正交、球面平均恒为 1、无需光滑罚）；"
            "EWIMV 是 v1.3 的 19 点离散网格，自由度高但相邻 bin 常不可辨识。"
            "出厂默认阶 10（5 参）：7 样实测阶 4（2 参）在强织构样上明显不足"
            "（样 3 差 5.96 pt），阶 10 在同一数据上仅比 19 参 EWIMV 差 0.18 pt；"
            "弱织构样可降到阶 4/6。CLI/库 API 仍默认 ewimv，零回归")
        form.addRow("织构模型", self.texture_model)

        self.refine_biso = QCheckBox("B 步精修每相 ΔB_iso（高角衰减）")
        self.refine_biso.setChecked(bool(cur.get("refine_biso", False)))
        self.refine_biso.setToolTip(
            "COD 导出 CIF 的 B_iso 恒为 0，会系统性高估高角强度；"
            "开启后配方 B 步逐相精修一个 0–6 Å² 的温度因子增量")
        form.addRow(self.refine_biso)

        self.refine_xyz = QCheckBox("xyz 步精修原子坐标（Wyckoff 位约束）")
        self.refine_xyz.setChecked(bool(cur.get("refine_xyz", False)))
        self.refine_xyz.setToolTip(
            "重读 CIF 未展开的不对称单位，等价原子联动；"
            "自由坐标过多或精修后 Rwp 未改善会自动跳过/回退。"
            "内置结构（无 CIF 源路径）不参与")
        form.addRow(self.refine_xyz)

        # v1.5 M9：xyz 步欠定时不再整步放弃，按相降级
        self.xyz_phase_select = QComboBox()
        self.xyz_phase_select.addItem("超限按相降级：保留自由坐标最多的相", "largest")
        self.xyz_phase_select.addItem("超限按相降级：保留自由坐标最少的相", "small")
        self.xyz_phase_select.addItem("超限整步判失败（v1.4 行为）", "off")
        _xs = str(cur.get("xyz_phase_select", "largest"))
        for _i in range(self.xyz_phase_select.count()):
            if self.xyz_phase_select.itemData(_i) == _xs:
                self.xyz_phase_select.setCurrentIndex(_i)
                break
        self.xyz_phase_select.setToolTip(
            "旧护栏把所有相的自由坐标求和，超限就把 xyz 整步判失败。"
            "样 7 的 48 = 高岭石 39 + 其余 9 > 40，于是 5 相一个都没精修；"
            "而单独精修高岭石（39 ≤ 40）增量口径有 −1.87 pt，排除它只有 −0.27 pt。"
            "默认 largest 会跳过次要相、保留最值得精修的相，"
            "被跳过的相作为常量基参与变量投影，并在配方消息里列名")
        form.addRow("xyz 欠定策略", self.xyz_phase_select)

        # v1.5 M8：试探命中相改用球谐织构（MAUD Harmonic 口径）
        self.probe_tex = QCheckBox(
            "PO 试探命中相改用球谐织构（MAUD Harmonic 口径）")
        self.probe_tex.setChecked(bool(cur.get("po_probe_to_texture", False)))
        self.probe_tex.setToolTip(
            "开启后试探选中的相不再精修 March–Dollase r，而是按选中的纤维轴"
            "播种球谐（Legendre）织构，阶数取上方「织构模型」设置；"
            "MAUD 对高岭石/萤石/白云石正是逐相 Harmonic 8 阶。"
            "MD 单轴 r 只能表达一维分布、且与标度强相关（样 7 萤石 r 撞上界 5.0）")
        form.addRow(self.probe_tex)

        self.tmin = QDoubleSpinBox()
        self.tmin.setRange(0.0, 179.0)
        self.tmin.setDecimals(1)
        self.tmin.setValue(float(cur.get("tmin", 5.0)))
        self.tmax = QDoubleSpinBox()
        self.tmax.setRange(1.0, 180.0)
        self.tmax.setDecimals(1)
        self.tmax.setValue(float(cur.get("tmax", 90.0)))
        self.tmax.setToolTip("放开到谱图全范围可纳入高角弱峰；背景节点数按窗口自适应")
        form.addRow("精修窗口 2θ 下限 (°)", self.tmin)
        form.addRow("精修窗口 2θ 上限 (°)", self.tmax)

        # v1.5 M9b：全链墙钟预算（性能护栏，防 GUI 单次精修 >1 h）
        self.time_budget = QSpinBox()
        self.time_budget.setRange(0, 720)
        self.time_budget.setValue(int(cur.get("time_budget_min", 45)))
        self.time_budget.setToolTip(
            "全链墙钟预算（分钟），0 = 不限。超预算时慢步（原子坐标/微结构）"
            "按实测单次评估耗时自适应降迭代，剩余预算不足的可选步直接跳过，"
            "保证一键精修总时长可控（样 4 实测 44.5 min，出厂默认 45 min）")
        form.addRow("精修时间预算 (分钟，0=不限)", self.time_budget)
        self._root.addLayout(form)
        self._add_buttons()

    def settings(self) -> dict:
        return {"po_probe": bool(self.probe.isChecked()),
                "po_probe_min_gain": float(self.min_gain.value()),
                "po_probe_max_phases": int(self.max_phases.value()),
                "po_probe_max_iter": int(self.max_iter.value()),
                "aniso_auto": bool(self.aniso_auto.isChecked()),
                "texture_model": str(self.texture_model.currentData()),
                "refine_biso": bool(self.refine_biso.isChecked()),
                "refine_xyz": bool(self.refine_xyz.isChecked()),
                "xyz_phase_select": str(self.xyz_phase_select.currentData()),
                "po_probe_to_texture": bool(self.probe_tex.isChecked()),
                "tmin": float(self.tmin.value()),
                "tmax": float(self.tmax.value()),
                "time_budget_min": int(self.time_budget.value())}


def open_settings(step: str, title: str, phase_names: list[str],
                  current: dict | None = None,
                  parent: QWidget | None = None) -> dict | None:
    """按步骤打开对应齿轮弹窗；返回设置字典或 None（取消）。"""
    if step == "bg":
        dlg = BackgroundDialog(current, parent)
    elif step == "cell":
        dlg = CellDialog(phase_names, current, parent)
    elif step == "micro":
        dlg = MicroDialog(current, parent)
    else:
        dlg = GenericDialog(step, title, current, parent)
    return dlg.settings() if dlg.exec() == QDialog.Accepted else None
