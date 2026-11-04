"""P3.2 · 交互式谱图画布（PySide6 + matplotlib）。

版式参照 MAUD 的 Rietveld 图：主谱（实测/计算/背景）下方为**每相一条**
布拉格标记条（相名左标、按相着色、棒高 ∝ 相内相对强度），最底部为
残差面板（高度比已收窄，给主谱让空间）。

- ``show_pattern``：导入谱图后单谱显示（已导入 CIF 时同样画标记条）；
- ``show_fit``：精修后叠加显示，支持每相标记条**显隐开关**；
- 缩放：matplotlib 内置 NavigationToolbar 提供框选放大（P3.1 挂到主窗口）；
- ``set_phase_visible``：参数改动即时预览（P3.2 的相开关 / 预览接口）。

绘制逻辑集中在 :func:`draw_fit`，画布与离屏 PNG 导出共用，保证界面与
报告一致。
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

# 面板高度比：主谱 / 每相标记条 / 残差
_H_MAIN = 3.2
_H_TICK = 0.38
_H_DIFF = 0.55


def normalize_sticks(entries):
    """把峰位列表规整为 (positions, rel_intensity)。

    兼容两种输入：``[2θ, ...]``（等高棒）与 ``[(2θ, I), ...]``
    （按 I/Imax 归一化的相对强度棒）。空列表返回两个空数组。
    """
    if entries is None or len(entries) == 0:
        return np.array([]), np.array([])
    arr = np.asarray(entries, dtype=float)
    if arr.ndim == 1:                       # 只有峰位
        pos, rel = arr, np.ones(arr.size)
    else:                                   # (2θ, I) 对
        pos, inten = arr[:, 0], arr[:, 1]
        peak = float(inten.max()) if inten.size else 0.0
        rel = inten / peak if peak > 0 else np.ones_like(inten)
    return pos, rel


def draw_fit(ax_main, ax_diff, two_theta, yobs, ycalc,
             background=None, phase_sticks=None, tick_axes=None,
             show_legend=True) -> None:
    """在主/残差双轴（+ 每相标记条轴）绘制拟合谱（画布与离屏导出共用）。

    ``phase_sticks``: ``[(phase_name, peaks, color_idx), ...]``，
    ``peaks`` 为 ``[2θ,...]`` 或 ``[(2θ, I),...]``，``color_idx`` 为该相
    在完整相列表中的下标（保证显隐切换时颜色不漂移）；
    ``tick_axes``: 与 ``phase_sticks`` 等长的标记条轴列表（None = 不画）。
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
    ax_main.set_ylabel(tr("canvas.y_label"))
    apply_axis_style(ax_main)
    ax_main.tick_params(labelbottom=False)
    if show_legend:
        ax_main.legend(handles, labels, loc="upper right", fontsize=8,
                       frameon=False)

    # -- 每相一条标记条（MAUD 式：左标相名，棒高 ∝ 相内相对强度） ------ #
    if phase_sticks and tick_axes is not None and len(tick_axes) == len(phase_sticks):
        for i, (name, entries, color_idx) in enumerate(phase_sticks):
            ax_t = tick_axes[i]
            pos, rel = normalize_sticks(entries)
            if pos.size:
                ax_t.vlines(pos, 0.0, rel, color=phase_color(color_idx),
                            lw=0.9, alpha=0.9)
            ax_t.set_xlim(tt[0], tt[-1])
            ax_t.set_ylim(0.0, 1.05)
            ax_t.set_yticks([])
            ax_t.tick_params(labelbottom=False, length=2)
            for sp in ("top", "right", "left"):
                ax_t.spines[sp].set_visible(False)
            ax_t.spines["bottom"].set_color(STYLE.grid)
            ax_t.grid(False)
            ax_t.text(-0.012, 0.5, name, transform=ax_t.transAxes,
                      ha="right", va="center", color=phase_color(color_idx),
                      fontsize=7.5, clip_on=False)

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
        # 用 constrained 布局让 matplotlib 自动处理多轴间距。
        self.figure = Figure(figsize=(6.4, 4.8), dpi=100, layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.ax_main = self.figure.add_subplot(111)
        self.ax_diff = None
        self.ax_ticks: list = []
        self._two_theta: np.ndarray | None = None
        self._yobs: np.ndarray | None = None
        self._ycalc: np.ndarray | None = None
        self._background: np.ndarray | None = None
        self._phase_sticks: list[tuple[str, list]] = []
        self._visible: set[str] = set()
        self._show_empty()

    # -- 状态 ---------------------------------------------------------- #
    @property
    def has_fit(self) -> bool:
        return self._ycalc is not None

    @property
    def phase_names(self) -> list[str]:
        return [n for n, _ in self._phase_sticks]

    def set_phase_sticks(self, sticks: list[tuple[str, list]]) -> None:
        """登记每相的布拉格峰（(2θ,) 或 (2θ, I) 对，由 core 前向模型给出）。"""
        self._phase_sticks = list(sticks)
        self._visible = {n for n, _ in self._phase_sticks}

    def set_phase_visible(self, name: str, visible: bool) -> None:
        """相开关：即时重绘，不重新精修（参数改动即时预览的第一步）。"""
        if visible:
            self._visible.add(name)
        else:
            self._visible.discard(name)
        if self._yobs is not None:
            self._redraw()
        else:
            self._show_empty()

    def clear(self) -> None:
        self._two_theta = self._yobs = self._ycalc = self._background = None
        self._phase_sticks = []
        self._visible = set()
        self._show_empty()

    # -- 绘制 ---------------------------------------------------------- #
    def _visible_sticks(self) -> list[tuple[str, list, int]]:
        """按相开关过滤后的标记条 ``(name, peaks, 原始相下标)``。

        保留原始下标是为了显隐切换时颜色不漂移。"""
        return [(n, e, i) for i, (n, e) in enumerate(self._phase_sticks)
                if n in self._visible]

    def _reset_axes(self) -> None:
        self.figure.clear()
        n_tick = len(self._visible_sticks())
        gs = self.figure.add_gridspec(
            2 + n_tick, 1,
            height_ratios=[_H_MAIN] + [_H_TICK] * n_tick + [_H_DIFF],
            hspace=0.06)
        self.ax_main = self.figure.add_subplot(gs[0])
        self.ax_ticks = []
        for k in range(n_tick):
            self.ax_ticks.append(
                self.figure.add_subplot(gs[1 + k], sharex=self.ax_main))
        self.ax_diff = self.figure.add_subplot(gs[-1], sharex=self.ax_main)

    def _show_empty(self) -> None:
        self.figure.clear()
        self.ax_ticks = []
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, tr("canvas.empty"), ha="center", va="center",
                color=STYLE.grid, fontsize=12, transform=ax.transAxes)
        ax.set_axis_off()
        self.draw_idle()

    def retranslate(self) -> None:
        """语言切换后按当前数据重绘（文案/图例/轴标签）。"""
        self.refresh()

    def refresh(self) -> None:
        """数据未变时的重绘入口（标记条 / 相开关 / 参数预览共用）。"""
        if self._yobs is not None:
            self._redraw()
        else:
            self._show_empty()

    def show_pattern(self, two_theta, intensity) -> None:
        """单谱显示（导入谱图后；已导入 CIF 时同样画每相标记条）。"""
        self._two_theta = np.asarray(two_theta, dtype=float)
        self._yobs = np.asarray(intensity, dtype=float)
        self._ycalc = None
        self._redraw()

    def show_fit(self, two_theta, yobs, ycalc, background=None) -> None:
        """精修结果叠加显示（含残差）。"""
        self._two_theta = np.asarray(two_theta, dtype=float)
        self._yobs = np.asarray(yobs, dtype=float)
        self._ycalc = np.asarray(ycalc, dtype=float)
        self._background = (None if background is None
                            else np.asarray(background, dtype=float))
        self._redraw()

    def _redraw(self) -> None:
        """按当前数据重绘（单谱 / 拟合共用入口）。"""
        self._reset_axes()
        tt, yobs = self._two_theta, self._yobs
        sticks = self._visible_sticks()
        if self._ycalc is not None:
            draw_fit(self.ax_main, self.ax_diff, tt, yobs, self._ycalc,
                     background=self._background,
                     phase_sticks=sticks,
                     tick_axes=self.ax_ticks)
        else:
            # 单谱模式：主轴画实测谱；标记条复用 draw_fit 的相棒逻辑
            #（传 ycalc=yobs，计算线与实测线重合，视觉上只有实测谱）。
            self.ax_main.plot(tt, yobs, color=STYLE.ink, lw=0.9)
            self.ax_main.set_ylabel(tr("canvas.y_label"))
            apply_axis_style(self.ax_main)
            self.ax_main.tick_params(labelbottom=False)
            draw_fit(self.ax_main, self.ax_diff, tt, yobs, yobs,
                     phase_sticks=sticks, tick_axes=self.ax_ticks,
                     show_legend=False)
            # 残差轴清空为占位面板（单谱无残差），保留 2θ 轴标签。
            self.ax_diff.clear()
            self.ax_diff.set_xlabel(tr("canvas.x_label"))
            apply_axis_style(self.ax_diff)
            self.ax_diff.set_yticks([])
            self.ax_diff.set_ylim(-0.5, 0.5)
            for sp in ("top", "right", "left"):
                self.ax_diff.spines[sp].set_visible(False)
        self.draw_idle()
