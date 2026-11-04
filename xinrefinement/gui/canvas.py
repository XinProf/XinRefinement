"""P3.2 · 交互式谱图画布（PySide6 + matplotlib）。

版式参照 MAUD 的 Rietveld 图：主谱（实测/计算/背景）下方为**每相一条**
布拉格标记条（相名左标、按相着色、棒高 ∝ 相内相对强度），最底部为
残差面板（高度比已收窄，给主谱让空间）。

- ``show_pattern``：导入谱图后单谱显示（已导入 CIF 时同样画标记条）；
- ``show_fit``：精修后叠加显示，支持每相标记条**显隐开关**；
- 缩放：matplotlib 内置 NavigationToolbar 提供框选放大（P3.1 挂到主窗口）；
- ``set_phase_visible``：参数改动即时预览（P3.2 的相开关 / 预览接口）；
- **轴切换**：横轴 2θ ↔ d 值、纵轴 counts ↔ log ↔ √，左键点轴循环、
  右键点轴弹选单（``set_x_mode`` / ``set_y_mode`` 亦供脚本调用）。

绘制逻辑集中在 :func:`draw_fit`，画布与离屏 PNG 导出共用，保证界面与
报告一致。
"""
from __future__ import annotations

import math

import numpy as np
import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu

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

#: 横轴模式：2θ 角度 / d 面间距
X_MODES = ("2theta", "d")
#: 纵轴模式：计数 / 对数 / 方根
Y_MODES = ("linear", "log", "sqrt")
#: 默认波长（Cu Kα1，Å）——谱图 meta 带 wavelength 时会被覆盖
DEFAULT_WAVELENGTH = 1.5406


def two_theta_to_d(two_theta, wavelength: float = DEFAULT_WAVELENGTH):
    """2θ(°) → d(Å)：Bragg 定律 d = λ / (2 sinθ)。"""
    tt = np.asarray(two_theta, dtype=float)
    s = np.sin(np.radians(tt / 2.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = wavelength / (2.0 * s)
    return d


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

    #: 悬停轴区时的提示文案（主窗口接到状态栏；离开轴区发空串）
    axisHint = Signal(str)

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
        #: 轴模式与换算波长（谱图 meta 可覆盖）
        self.x_mode: str = "2theta"
        self.y_mode: str = "linear"
        self.wavelength: float = DEFAULT_WAVELENGTH
        #: 由主窗口注入，用于判断平移/缩放模式（此时点击轴不切换）
        self.nav_toolbar = None
        self._hover_axis: str | None = None
        self._show_empty()
        self.mpl_connect("button_press_event", self._on_button_press)
        self.mpl_connect("motion_notify_event", self._on_motion)

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

    # -- 轴模式（2θ/d、counts/log/√） ---------------------------------- #
    def set_wavelength(self, wavelength: float | None) -> None:
        """设置 d 值换算波长（Å）；None/非法值保持默认 Cu Kα1。"""
        try:
            wl = float(wavelength) if wavelength else DEFAULT_WAVELENGTH
        except (TypeError, ValueError):
            wl = DEFAULT_WAVELENGTH
        self.wavelength = wl if wl > 0 else DEFAULT_WAVELENGTH
        if self.x_mode == "d" and self._yobs is not None:
            self._redraw()

    def set_x_mode(self, mode: str) -> None:
        """横轴：``"2theta"`` ↔ ``"d"``。"""
        if mode not in X_MODES or mode == self.x_mode:
            return
        self.x_mode = mode
        self.refresh()

    def set_y_mode(self, mode: str) -> None:
        """纵轴：``"linear"``（cts）/ ``"log"`` / ``"sqrt"``。"""
        if mode not in Y_MODES or mode == self.y_mode:
            return
        self.y_mode = mode
        self.refresh()

    def cycle_x_mode(self) -> str:
        """左键点横轴：2θ → d → 2θ。"""
        i = X_MODES.index(self.x_mode)
        self.set_x_mode(X_MODES[(i + 1) % len(X_MODES)])
        return self.x_mode

    def cycle_y_mode(self) -> str:
        """左键点纵轴：cts → log → √ → cts。"""
        i = Y_MODES.index(self.y_mode)
        self.set_y_mode(Y_MODES[(i + 1) % len(Y_MODES)])
        return self.y_mode

    def _x_values(self, two_theta):
        """按横轴模式返回绘图横坐标（d 模式为递减数组）。"""
        if self.x_mode == "d":
            return two_theta_to_d(two_theta, self.wavelength)
        return np.asarray(two_theta, dtype=float)

    def _x_label(self) -> str:
        base = (tr("canvas.x_label_d") if self.x_mode == "d"
                else tr("canvas.x_label"))
        return f"{base} ▼"

    def _y_label(self) -> str:
        key = {"linear": "canvas.y_label",
               "log": "canvas.y_label_log",
               "sqrt": "canvas.y_label_sqrt"}[self.y_mode]
        return f"{tr(key)} ▼"

    def _apply_axis_modes(self, x) -> None:
        """按模式设置横轴范围（d 模式自动反向）、纵轴标度与轴标签。"""
        if x is None or len(x) == 0:
            return
        # d 随 2θ 递减：直接按数据首末给出，matplotlib 会自动成反向轴
        for ax in [self.ax_main] + list(self.ax_ticks):
            ax.set_xlim(x[0], x[-1])
        if self.ax_diff is not None:
            self.ax_diff.set_xlim(x[0], x[-1])
            self.ax_diff.set_xlabel(self._x_label())
        self.ax_main.set_xlabel(self._x_label())
        self.ax_main.set_ylabel(self._y_label())

        ys = [np.asarray(v, dtype=float) for v in
              (self._yobs, self._ycalc, self._background) if v is not None]
        ymax = max((float(np.nanmax(v)) for v in ys if v.size), default=1.0)
        if self.y_mode == "log":
            self.ax_main.set_yscale("log")
            pos = np.concatenate([v[v > 0] for v in ys if np.any(v > 0)]) \
                if any(np.any(v > 0) for v in ys) else np.array([1.0])
            ymin = max(float(np.nanmin(pos)) * 0.8, 1e-3)
            self.ax_main.set_ylim(ymin, ymax * 1.08)
        elif self.y_mode == "sqrt":
            self.ax_main.set_yscale(
                "function", functions=(np.sqrt, np.square))
            self.ax_main.set_ylim(0.0, ymax * 1.08)
        else:
            self.ax_main.set_yscale("linear")
            self.ax_main.set_ylim(0.0, ymax * 1.08)

    # -- 轴点击交互 ---------------------------------------------------- #
    def _in_pan_or_zoom(self) -> bool:
        """平移/框选模式下点击留给 matplotlib 工具栏，不抢轴切换。"""
        tb = self.nav_toolbar
        acts = getattr(tb, "_actions", {}) if tb is not None else {}
        return any(acts.get(k) is not None and acts[k].isChecked()
                   for k in ("pan", "zoom"))

    def _hit_axis(self, event) -> str | None:
        """判断点击落在 纵轴标签区（"y"）/ 横轴标签区（"x"）/ 都不是。

        纵轴区 = 主谱左侧、主谱上下沿之间；横轴区 = **最底部**轴（残差轴）
        下沿以下的整条边距，避免点在各标记条之间的缝隙里误触发。
        """
        if event.x is None or event.y is None or self.ax_main is None:
            return None
        if getattr(event, "inaxes", None) is not None:
            return None
        try:
            mb = self.ax_main.get_window_extent()
            bottom = (self.ax_diff or self.ax_main).get_window_extent()
        except Exception:
            return None
        if event.x < mb.x0 - 2 and mb.y0 <= event.y <= mb.y1 + 8:
            return "y"
        if event.y < bottom.y0 - 2 and mb.x0 - 12 <= event.x <= mb.x1 + 12:
            return "x"
        return None

    def _on_button_press(self, event) -> None:
        """左键循环切换该轴模式；右键弹出可选切换菜单。"""
        if self._yobs is None or self._in_pan_or_zoom():
            return
        axis = self._hit_axis(event)
        if axis is None:
            return
        if event.button == 1:
            if axis == "x":
                self.cycle_x_mode()
            else:
                self.cycle_y_mode()
            return
        if event.button == 3:
            self._popup_axis_menu(axis, event)

    def _on_motion(self, event) -> None:
        """悬停到轴区时发状态栏提示并换手型光标（提示可点）。"""
        if self._yobs is None:
            return
        axis = self._hit_axis(event)
        if axis == self._hover_axis:
            return
        self._hover_axis = axis
        if axis == "x":
            self.axisHint.emit(tr("axis.hint_x"))
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif axis == "y":
            self.axisHint.emit(tr("axis.hint_y"))
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.axisHint.emit("")
            self.unsetCursor()

    def _popup_axis_menu(self, axis: str, event) -> None:
        """右键菜单：勾选当前项，点选即切换。"""
        gui = getattr(event, "guiEvent", None)
        menu = QMenu(self)
        if axis == "x":
            menu.setTitle(tr("axis.menu_x"))
            current = self.x_mode
            for mode in X_MODES:
                act = menu.addAction(tr(f"axis.x_{mode}"))
                act.setCheckable(True)
                act.setChecked(mode == current)
                act.triggered.connect(
                    lambda _c=False, m=mode: self.set_x_mode(m))
        else:
            menu.setTitle(tr("axis.menu_y"))
            current = self.y_mode
            for mode in Y_MODES:
                act = menu.addAction(tr(f"axis.y_{mode}"))
                act.setCheckable(True)
                act.setChecked(mode == current)
                act.triggered.connect(
                    lambda _c=False, m=mode: self.set_y_mode(m))
        if gui is not None and hasattr(gui, "globalPos"):
            menu.exec(gui.globalPos())
        else:                                   # 无 GUI 事件（脚本/测试）
            menu.exec(self.mapToGlobal(self.rect().center()))

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
        x = self._x_values(tt)        # 2θ 或 d（d 模式为递减数组）
        sticks = self._sticks_in_units(self._visible_sticks())
        if self._ycalc is not None:
            draw_fit(self.ax_main, self.ax_diff, x, yobs, self._ycalc,
                     background=self._background,
                     phase_sticks=sticks,
                     tick_axes=self.ax_ticks)
        else:
            # 单谱模式：主轴画实测谱；标记条复用 draw_fit 的相棒逻辑
            #（传 ycalc=yobs，计算线与实测线重合，视觉上只有实测谱）。
            self.ax_main.plot(x, yobs, color=STYLE.ink, lw=0.9)
            draw_fit(self.ax_main, self.ax_diff, x, yobs, yobs,
                     phase_sticks=sticks, tick_axes=self.ax_ticks,
                     show_legend=False)
            # 残差轴清空为占位面板（单谱无残差），保留横轴标签。
            self.ax_diff.clear()
            self.ax_diff.set_xlabel(self._x_label())
            apply_axis_style(self.ax_diff)
            self.ax_diff.set_yticks([])
            self.ax_diff.set_ylim(-0.5, 0.5)
            for sp in ("top", "right", "left"):
                self.ax_diff.spines[sp].set_visible(False)
        self._apply_axis_modes(x)
        self.draw_idle()

    def _sticks_in_units(self, sticks):
        """标记条峰位按横轴模式换算（d 模式转 d 值）。"""
        if self.x_mode != "d":
            return sticks
        out = []
        for name, entries, idx in sticks:
            if entries is None or len(entries) == 0:
                out.append((name, entries, idx))
                continue
            arr = np.asarray(entries, dtype=float)
            if arr.ndim == 1:
                new = two_theta_to_d(arr, self.wavelength).tolist()
            else:
                d = two_theta_to_d(arr[:, 0], self.wavelength)
                new = np.column_stack([d, arr[:, 1]]).tolist()
            out.append((name, new, idx))
        return out
