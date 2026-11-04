"""matplotlib 导航工具栏图标彩色化。

matplotlib 自带的 NavigationToolbar2QT 图标是单色剪影；本模块用
**矢量源 SVG**（mpl-data/images/*.svg，随 datas 打包）按品牌色系
重新着色渲染，并垫一层同色系浅色圆角底衬，观感更精致。

- 分辨率无关：QSvgRenderer 渲染，不糊边；
- 每个动作一种家族色（与 core/palette.py 的 phase_sticks 色板同源）；
- 任何一步失败（QtSvg 缺失 / 资源缺失）静默保留原图标，不影响功能。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPixmap

import matplotlib.cbook as cbook

#: 动作名（toolbar._actions 的 callback 键）→ 图标矢量源 + 品牌色
TOOL_COLORS: dict[str, tuple[str, str]] = {
    "home":               ("home.svg",                 "#1f77b4"),  # 蓝
    "back":               ("back.svg",                 "#ff7f0e"),  # 橙
    "forward":            ("forward.svg",              "#2ca02c"),  # 绿
    "pan":                ("move.svg",                 "#9467bd"),  # 紫
    "zoom":               ("zoom_to_rect.svg",         "#17becf"),  # 青
    "configure_subplots": ("subplots.svg",             "#d62728"),  # 红
    "edit_parameters":    ("qt4_editor_options.svg",   "#8c564b"),  # 棕
    "save_figure":        ("filesave.svg",             "#0D285C"),  # 品牌深蓝
}

#: 底衬与图标的绘制尺寸（逻辑像素）
_CHIP = 36
_ICON_INNER = 30      # 图标在底衬内的有效区（SVG 自带少量留白，放大铺满）
_RADIUS = 9.0
_BG_ALPHA = 34        # 底衬透明度（约 13%）


def _render_colored_icon(svg_path: str, hex_color: str) -> QPixmap | None:
    """SVG → 彩色圆角底衬图标位图；失败返回 None。"""
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        return None

    color = QColor(hex_color)

    # 1) 底衬：同色系浅色圆角矩形
    chip = QImage(_CHIP, _CHIP, QImage.Format.Format_ARGB32_Premultiplied)
    chip.fill(Qt.GlobalColor.transparent)
    p = QPainter(chip)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QColor(color)
    bg.setAlpha(_BG_ALPHA)
    p.setBrush(QBrush(bg))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(1.5, 1.5, _CHIP - 3.0, _CHIP - 3.0),
                      _RADIUS, _RADIUS)

    # 2) 图标：SVG 以 alpha 为掩膜，整体染成目标色后叠加在底衬上
    img = QImage(_ICON_INNER, _ICON_INNER,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p2 = QPainter(img)
    renderer.render(p2, QRectF(0, 0, _ICON_INNER, _ICON_INNER))
    p2.end()
    tinted = QImage(_ICON_INNER, _ICON_INNER,
                    QImage.Format.Format_ARGB32_Premultiplied)
    tinted.fill(color)
    p3 = QPainter(tinted)
    p3.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p3.drawImage(0, 0, img)
    p3.end()
    off = (_CHIP - _ICON_INNER) / 2.0
    p.drawImage(QPointF(off, off), tinted)
    p.end()
    return QPixmap.fromImage(chip)


def colorize_nav_toolbar(toolbar) -> int:
    """给 NavigationToolbar2QT 的各动作换上彩色图标；返回成功数。"""
    replaced = 0
    size = toolbar.iconSize()
    want = QSize(_CHIP, _CHIP)
    if size.width() < _CHIP - 4:
        toolbar.setIconSize(QSize(_CHIP - 6, _CHIP - 6))  # 30px，略大于原默认
    for callback, (svg_name, hex_color) in TOOL_COLORS.items():
        act = getattr(toolbar, "_actions", {}).get(callback)
        if act is None:
            continue
        try:
            svg_path = str(cbook._get_data_path("images", svg_name))
        except Exception:
            continue
        pix = _render_colored_icon(svg_path, hex_color)
        if pix is None:
            continue
        act.setIcon(QIcon(pix))
        replaced += 1
    return replaced
