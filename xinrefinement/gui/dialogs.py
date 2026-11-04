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
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
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
                            "manual（手动插值点）"])
        self.mode.setCurrentIndex({"cheb": 0, "tent": 1, "manual": 2}.get(
            cur.get("bg_mode", "cheb"), 0))
        self.n_terms = QSpinBox()
        self.n_terms.setRange(1, 30)
        self.n_terms.setValue(int(cur.get("n_bg", 3)))
        form.addRow("背景函数", self.mode)
        form.addRow("阶数 / 节点数", self.n_terms)
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
        mode = ("cheb", "tent", "manual")[self.mode.currentIndex()]
        pts = []
        for r in range(self.table.rowCount()):
            a, b = self.table.item(r, 0), self.table.item(r, 1)
            if a and b and a.text().strip() and b.text().strip():
                try:
                    pts.append((float(a.text()), float(b.text())))
                except ValueError:
                    pass
        return {"bg_mode": "cheb" if mode == "manual" else mode,
                "n_bg": int(self.n_terms.value()),
                "bg_points": pts, "manual_points": mode == "manual"}


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


def open_settings(step: str, title: str, phase_names: list[str],
                  current: dict | None = None,
                  parent: QWidget | None = None) -> dict | None:
    """按步骤打开对应齿轮弹窗；返回设置字典或 None（取消）。"""
    if step == "bg":
        dlg = BackgroundDialog(current, parent)
    elif step == "cell":
        dlg = CellDialog(phase_names, current, parent)
    else:
        dlg = GenericDialog(step, title, current, parent)
    return dlg.settings() if dlg.exec() == QDialog.Accepted else None
