"""谱图配色与坐标轴样式（核心层，GUI / PNG / HTML 报告共用）。

家族约定：色板定义在**核心层**，GUI 反向引用，保证「界面里长什么样，
报告里就长什么样」（规则：核心层不依赖 GUI）。

配色沿用家族 GUI v1.2.0 用户指定样式：实测=蓝色 ×、计算=黑色实线、
差值=红色实线。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaletteStyle:
    ink: str = "#2b2b2b"        # 单谱线 / 文字
    obs: str = "#1f77b4"        # 实测谱（蓝 ×）
    calc: str = "#000000"       # 计算谱（黑实线）
    diff: str = "#d62728"       # 残差（红）
    bg: str = "#7f7f7f"         # 背景曲线（灰虚线）
    grid: str = "#c8c8c8"       # 网格 / 零线
    mark: str = "#2ca02c"       # 寻峰 / 峰位标记
    #: 多相峰位棒的颜色轮转（按相下标取模）
    phase_sticks: tuple[str, ...] = (
        "#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b", "#17becf",
    )


DEFAULT_STYLE = PaletteStyle()


def phase_color(index: int, style: PaletteStyle = DEFAULT_STYLE) -> str:
    """按相下标返回峰位棒颜色（循环使用）。"""
    return style.phase_sticks[index % len(style.phase_sticks)]


def apply_axis_style(ax, style: PaletteStyle = DEFAULT_STYLE) -> None:
    """统一坐标轴外观（浅色主题、细网格、去上/右边框）。"""
    ax.set_facecolor("#ffffff")
    ax.grid(True, color=style.grid, linewidth=0.5, alpha=0.7)
    ax.tick_params(colors=style.ink, labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(style.grid)
    ax.set_xlabel(ax.get_xlabel(), color=style.ink)
    ax.set_ylabel(ax.get_ylabel(), color=style.ink)
