"""P3.2 · 交互式谱图画布（PySide6 + matplotlib）。

- 双轴：上（实测 / 计算 / 背景 / 每相峰位棒）、下（残差 + 零线）；
- ``show_pattern``：导入谱图后单谱显示；
- ``show_fit``：精修后叠加显示，支持每相峰位棒**显隐开关**；
- 缩放：matplotlib 内置 NavigationToolbar 提供框选放大（P3.1 挂到主窗口）；
- ``set_phase_visible``：参数改动即时预览（P3.2 的相开关 / 预览接口）。

绘制逻辑集中在 :func:`draw_fit`，画布与离屏 PNG 导出共用，保证界面与报告一致。
"""
from __future__ import annotations

import numpy as np
import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

matplotlib.rcParams["font.sans-serif"] = [
    "Source Han Sans CN", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
    "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

from xinrefinement.core.palette import (  # noqa: E402
    DEFAULT_STYLE,
    apply_axis_style,
    phase_color,
)
from xinrefinement.i18n import tr  # noqa: E402

STYLE = DEFAULT_STYLE


def draw_fit(ax_main, ax_diff, two_theta, yobs, ycalc,
             background=None, phase_sticks=None, visible_phases=None) -> None:
    """在上下双轴绘制拟合谱（画布与离屏导出共用）。

    ``phase_sticks``: ``[(phase_name, [2θ, ...]), ...]``；
    ``visible_phases``: 可迭代的相名集合，None = 全部显示。
    """
    tt = np.asarray(two_theta, dtype=float)
    h_obs, = ax_main.plot(tt, np.asarray(yobs, dtype=float), linestyle="none",
                          marker="x", color=STYLE.obs, markersize=3.0,
                          markeredgewidth=0.6, label=tr("canvas.obs"))
    h_calc, = ax_main.plot(tt, np.asarray(ycalc, dtype=float), color=STYLE.calc,
                           lw=1.0, label=tr("canvas.calc"))
    handles = [h_obs, h_calc]
    labels = [tr("canvas.obs"), tr("canvas.calc")]
    if background is not None:
        ax_main.plot(tt, np.asarray(background, dtype=float), color=STYLE.bg,
                     lw=0.8, ls=":", label=tr("canvas.bg"))
    if phase_sticks:
        shown = set(visible_phases) if visible_phases is not None else None
        for i, (name, positions) in enumerate(phase_sticks):
            if shown is not None and name not in shown:
                continue
            for pos in np.asarray(positions, dtype=float):
                ax_main.axvline(pos, ymin=0.0, ymax=0.035,
                                color=phase_color(i), lw=1.2, alpha=0.85)
    ax_main.set_ylabel(tr("canvas.y_label"))
    apply_axis_style(ax_main)
    ax_main.tick_params(labelbottom=False)
    ax_main.legend(handles, labels, loc="upper right", fontsize=8, frameon=False)

    diff = np.asarray(yobs, dtype=float) - np.asarray(ycalc, dtype=float)
    ax_diff.plot(tt, diff, color=STYLE.diff, lw=0.8, label=tr("canvas.diff"))
    ax_diff.axhline(0.0, color=STYLE.grid, lw=0.6)
    ax_diff.set_xlabel(tr("canvas.x_label"))
    ax_diff.set_ylabel(tr("canvas.diff"))
    apply_axis_style(ax_diff)
    ax_diff.tick_params(labelbottom=True)


class PatternCanvas(FigureCanvasQTAgg):
    """谱图显示画布（QWidget）。"""

    def __init__(self, parent=None) -> None:
        # GridSpec 双轴与 tight_layout 不兼容（会产生 UserWarning）；
        # 用 constrained 布局让 matplotlib 自动处理上下轴间距。
        self.figure = Figure(figsize=(6.4, 4.8), dpi=100, layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.ax_main = self.figure.add_subplot(111)
        self.ax_diff = None
        self._two_theta: np.ndarray | None = None
        self._yobs: np.ndarray | None = None
        self._ycalc: np.ndarray | None = None
        self._background: np.ndarray | None = None
        self._phase_sticks: list[tuple[str, list[float]]] = []
        self._visible: set[str] = set()
        self._show_empty()

    # -- 状态 ---------------------------------------------------------- #
    @property
    def has_fit(self) -> bool:
        return self._ycalc is not None

    @property
    def phase_names(self) -> list[str]:
        return [n for n, _ in self._phase_sticks]

    def set_phase_sticks(self, sticks: list[tuple[str, list[float]]]) -> None:
        """登记每相的布拉格峰位（由 core 前向模型给出）。"""
        self._phase_sticks = list(sticks)
        self._visible = {n for n, _ in self._phase_sticks}

    def set_phase_visible(self, name: str, visible: bool) -> None:
        """相开关：即时重绘，不重新精修（参数改动即时预览的第一步）。"""
        if visible:
            self._visible.add(name)
        else:
            self._visible.discard(name)
        if self.has_fit:
            self._draw_fit()
        elif self._yobs is not None:
            self.show_pattern(self._two_theta, self._yobs)

    def clear(self) -> None:
        self._two_theta = self._yobs = self._ycalc = self._background = None
        self._phase_sticks = []
        self._visible = set()
        self._show_empty()

    # -- 绘制 ---------------------------------------------------------- #
    def _reset_axes(self) -> None:
        self.figure.clear()
        if self._ycalc is not None:
            gs = self.figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)
            self.ax_main = self.figure.add_subplot(gs[0])
            self.ax_diff = self.figure.add_subplot(gs[1], sharex=self.ax_main)
        else:
            self.ax_main = self.figure.add_subplot(111)
            self.ax_diff = None

    def _show_empty(self) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, tr("canvas.empty"), ha="center", va="center",
                color=STYLE.grid, fontsize=12, transform=ax.transAxes)
        ax.set_axis_off()
        self.draw_idle()

    def retranslate(self) -> None:
        """语言切换后按当前数据重绘（文案/图例/轴标签）。"""
        if self.has_fit:
            self._draw_fit()
        elif self._yobs is not None:
            self.show_pattern(self._two_theta, self._yobs)
        else:
            self._show_empty()

    def show_pattern(self, two_theta, intensity) -> None:
        """单谱显示（导入谱图后）。"""
        self._two_theta = np.asarray(two_theta, dtype=float)
        self._yobs = np.asarray(intensity, dtype=float)
        self._ycalc = None
        self._reset_axes()
        self.ax_main.plot(self._two_theta, self._yobs, color=STYLE.ink, lw=0.9)
        self.ax_main.set_ylabel(tr("canvas.y_label"))
        self.ax_main.set_xlabel(tr("canvas.x_label"))
        apply_axis_style(self.ax_main)
        self.draw_idle()

    def show_fit(self, two_theta, yobs, ycalc, background=None) -> None:
        """精修结果叠加显示（含残差）。"""
        self._two_theta = np.asarray(two_theta, dtype=float)
        self._yobs = np.asarray(yobs, dtype=float)
        self._ycalc = np.asarray(ycalc, dtype=float)
        self._background = (None if background is None
                            else np.asarray(background, dtype=float))
        self._draw_fit()

    def _draw_fit(self) -> None:
        self._reset_axes()
        draw_fit(self.ax_main, self.ax_diff, self._two_theta, self._yobs,
                 self._ycalc, background=self._background,
                 phase_sticks=self._phase_sticks,
                 visible_phases=self._visible)
        self.draw_idle()
