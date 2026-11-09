"""工具栏功能按钮的彩色图标（QPainter 程序化绘制，零素材依赖）。

设计语言与导航工具栏一致：家族色系 + 浅色圆角底衬 + 同色图形。
每个图标按 32×32 设计坐标绘制，多尺寸（16–48px）各渲染一份位图，
保证高 DPI 下清晰。

按钮 → 图标语义：

============  ========================  ==================
按钮          图形                      颜色
============  ========================  ==================
新建          文档（折角）+ 绿色加号    蓝 #1f77b4
导入谱图      坐标轴 + 衍射峰形曲线     青 #17becf
导入CIF       晶体（六边形晶格）        紫 #9467bd
▶精修         圆角播放三角              绿 #2ca02c
报告导出      文档 + 橙色导出箭头       橙 #ff7f0e
============  ========================  ==================
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

_SIZES = (16, 20, 24, 32, 48)

_NEW = "#1f77b4"       # 蓝
_PATTERN = "#17becf"   # 青
_CIF = "#9467bd"       # 紫
_REFINE = "#2ca02c"    # 绿
_REPORT = "#ff7f0e"    # 橙


def _tint(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def _page(p: QPainter, hex_color: str, x: float = 7.0, y: float = 3.0,
          w: float = 18.0, h: float = 26.0) -> None:
    """圆角文档页 + 折角（很多图标复用）。"""
    p.setPen(QPen(QColor(hex_color), 2.0))
    p.setBrush(_tint(hex_color, 26))
    p.drawRoundedRect(QRectF(x, y, w, h), 3.0, 3.0)
    p.setBrush(_tint(hex_color, 70))
    fold = 6.0
    p.drawPolygon(QPolygonF([
        QPointF(x + w - fold, y),
        QPointF(x + w, y + fold),
        QPointF(x + w - fold, y + fold),
    ]))


def _draw_new(p: QPainter) -> None:
    """新建：空白文档 + 绿色加号。"""
    _page(p, _NEW)
    p.setPen(QPen(QColor(_REFINE), 3.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(16.0, 14.5), QPointF(16.0, 23.5))
    p.drawLine(QPointF(11.5, 19.0), QPointF(20.5, 19.0))


def _draw_pattern(p: QPainter) -> None:
    """导入谱图：坐标轴 + 衍射峰形折线。"""
    p.setPen(QPen(QColor(_PATTERN), 2.0))
    p.setBrush(_tint(_PATTERN, 24))
    p.drawRoundedRect(QRectF(4.0, 4.0, 24.0, 24.0), 3.0, 3.0)
    # 坐标轴（浅灰 L 形）
    p.setPen(QPen(QColor("#9aa4ae"), 1.6))
    p.drawLine(QPointF(8.5, 8.0), QPointF(8.5, 23.5))
    p.drawLine(QPointF(8.5, 23.5), QPointF(24.0, 23.5))
    # 峰形：基线—峰—基线（主峰 + 次峰）
    p.setPen(QPen(QColor(_PATTERN), 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    path = QPainterPath(QPointF(10.0, 22.5))
    path.lineTo(12.5, 22.5)
    path.lineTo(14.0, 11.0)
    path.lineTo(15.5, 22.5)
    path.lineTo(18.0, 22.5)
    path.lineTo(19.5, 15.0)
    path.lineTo(21.0, 22.5)
    path.lineTo(23.5, 22.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _draw_cif(p: QPainter) -> None:
    """导入 CIF：六边形晶体 + 内部晶格点。"""
    import math

    cx, cy, r = 16.0, 16.0, 11.0
    poly = QPolygonF([
        QPointF(cx + r * math.cos(math.radians(60 * k - 30)),
                cy + r * math.sin(math.radians(60 * k - 30)))
        for k in range(6)
    ])
    p.setPen(QPen(QColor(_CIF), 2.2))
    p.setBrush(_tint(_CIF, 30))
    p.drawPolygon(poly)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(_CIF))
    for dx, dy in ((-3.5, 0.0), (0.0, -4.0), (3.5, 0.0), (0.0, 4.0)):
        p.drawEllipse(QPointF(cx + dx, cy + dy), 1.6, 1.6)
    # 晶格连线（浅色）
    p.setPen(QPen(_tint(_CIF, 150), 1.2))
    p.drawLine(QPointF(cx - 3.5, cy), QPointF(cx + 3.5, cy))
    p.drawLine(QPointF(cx, cy - 4.0), QPointF(cx, cy + 4.0))


def _draw_refine(p: QPainter) -> None:
    """▶精修：圆角播放三角。"""
    path = QPainterPath()
    path.moveTo(11.0, 7.5)
    path.lineTo(25.0, 16.0)
    path.lineTo(11.0, 24.5)
    path.closeSubpath()
    p.setPen(QPen(QColor(_REFINE), 2.0))
    p.setBrush(QColor(_REFINE))
    p.drawPath(path)
    # 高光
    p.setPen(QPen(_tint("#ffffff", 130), 1.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(14.0, 11.5), QPointF(14.0, 20.5))


def _draw_report(p: QPainter) -> None:
    """报告导出：文档 + 橙色导出箭头。"""
    _page(p, "#5b6670", x=6.0, y=3.0, w=17.0, h=26.0)
    # 文本行（浅灰）
    p.setPen(QPen(QColor("#9aa4ae"), 1.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    for yy in (9.0, 13.0, 17.0):
        p.drawLine(QPointF(9.5, yy), QPointF(19.5, yy))
    # 导出箭头（橙，右下出页）
    p.setPen(QPen(QColor(_REPORT), 3.0, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(18.0, 17.0), QPointF(18.0, 26.0))
    arrow = QPainterPath()
    arrow.moveTo(14.2, 22.6)
    arrow.lineTo(18.0, 26.8)
    arrow.lineTo(21.8, 22.6)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(arrow)


_DRAWERS = {
    "toolbar.new": _draw_new,
    "toolbar.import_pattern": _draw_pattern,
    "toolbar.import_cif": _draw_cif,
    "toolbar.refine": _draw_refine,
    "toolbar.report": _draw_report,
}

# ---------------------------------------------------------------- v1.6.1 --
# 谱图操作行的图标。风格与上面一致：32×32 设计坐标、家族色描边 + 浅色填充。

_PLOT_ZOOM = "#17becf"   # 青：缩放
_PLOT_PAN = "#9467bd"    # 紫：平移
_PLOT_RESET = "#1f77b4"  # 蓝：复位
_PLOT_CURSOR = "#d32f2f"  # 红：十字线（与画布上的红线同色）


def _frame(p: QPainter, color: str, alpha: int = 24) -> None:
    """浅色方框（谱图视场的示意底）。"""
    p.setPen(QPen(_tint(color, 110), 1.4))
    p.setBrush(_tint(color, alpha))
    p.drawRoundedRect(QRectF(4.5, 6.0, 23.0, 20.0), 3.0, 3.0)


def _curve(p: QPainter, color: str) -> None:
    """框内一条衍射峰折线（纯示意）。"""
    p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(7.0, 22.0))
    path.lineTo(12.0, 22.0)
    path.lineTo(14.0, 12.5)
    path.lineTo(16.5, 22.0)
    path.lineTo(19.5, 22.0)
    path.lineTo(21.0, 17.0)
    path.lineTo(22.5, 22.0)
    p.drawPath(path)


def _double_arrow(p: QPainter, color: str, horizontal: bool) -> None:
    """双向箭头（横向/纵向），两端带箭头头。"""
    pen = QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if horizontal:
        p.drawLine(QPointF(9.0, 16.0), QPointF(23.0, 16.0))
        for x, s in ((9.0, 1.0), (23.0, -1.0)):
            p.drawLine(QPointF(x, 16.0), QPointF(x + 3.2 * s, 13.0))
            p.drawLine(QPointF(x, 16.0), QPointF(x + 3.2 * s, 19.0))
    else:
        p.drawLine(QPointF(16.0, 8.0), QPointF(16.0, 24.0))
        for y, s in ((8.0, 1.0), (24.0, -1.0)):
            p.drawLine(QPointF(16.0, y), QPointF(13.0, y + 3.2 * s))
            p.drawLine(QPointF(16.0, y), QPointF(19.0, y + 3.2 * s))


def _draw_plot_reset(p: QPainter) -> None:
    """原始谱图：完整视场框 + 谱线 + 回到原点的弧形箭头。"""
    _frame(p, _PLOT_RESET)
    _curve(p, _PLOT_RESET)
    p.setPen(QPen(QColor(_PLOT_RESET), 1.8, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(20.0, 2.0, 9.0, 9.0), 40 * 16, 250 * 16)
    p.setBrush(QColor(_PLOT_RESET))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(20.6, 4.2), QPointF(25.2, 5.4),
                             QPointF(21.8, 8.2)]))


def _draw_plot_zoom_x(p: QPainter) -> None:
    """横向框选：视场框 + 中间横向双向箭头。"""
    _frame(p, _PLOT_ZOOM)
    _double_arrow(p, _PLOT_ZOOM, horizontal=True)


def _draw_plot_zoom_y(p: QPainter) -> None:
    """纵向框选：视场框 + 纵向双向箭头。"""
    _frame(p, _PLOT_ZOOM)
    _double_arrow(p, _PLOT_ZOOM, horizontal=False)


def _draw_plot_zoom_rect(p: QPainter) -> None:
    """区域放大：虚线矩形框（框选动作的通用符号）。"""
    p.setPen(QPen(QColor(_PLOT_ZOOM), 2.0, Qt.PenStyle.DashLine))
    p.setBrush(_tint(_PLOT_ZOOM, 22))
    p.drawRect(QRectF(6.0, 7.0, 20.0, 18.0))
    p.setPen(QPen(_tint(_PLOT_ZOOM, 150), 1.2))
    p.drawLine(QPointF(6.0, 16.0), QPointF(26.0, 16.0))
    p.drawLine(QPointF(16.0, 7.0), QPointF(16.0, 25.0))


def _pan_icon(p: QPainter, to_right: bool) -> None:
    """平移：视场框 + 单向粗箭头（+ 尾部的运动线）。"""
    _frame(p, _PLOT_PAN, alpha=18)
    y = 16.0
    pen = QPen(QColor(_PLOT_PAN), 2.6, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    if to_right:
        p.drawLine(QPointF(10.0, y), QPointF(22.0, y))
        p.drawLine(QPointF(22.0, y), QPointF(18.0, y - 3.6))
        p.drawLine(QPointF(22.0, y), QPointF(18.0, y + 3.6))
        for dy in (-5.0, 5.0):
            p.drawLine(QPointF(7.5, y + dy), QPointF(13.0, y + dy))
    else:
        p.drawLine(QPointF(22.0, y), QPointF(10.0, y))
        p.drawLine(QPointF(10.0, y), QPointF(14.0, y - 3.6))
        p.drawLine(QPointF(10.0, y), QPointF(14.0, y + 3.6))
        for dy in (-5.0, 5.0):
            p.drawLine(QPointF(24.5, y + dy), QPointF(19.0, y + dy))


def _draw_plot_pan_left(p: QPainter) -> None:
    _pan_icon(p, to_right=False)


def _draw_plot_pan_right(p: QPainter) -> None:
    _pan_icon(p, to_right=True)


def _magnifier(p: QPainter, color: str, plus: bool) -> None:
    """放大镜（+ / −）。"""
    p.setPen(QPen(QColor(color), 2.4))
    p.setBrush(_tint(color, 26))
    p.drawEllipse(QPointF(14.0, 13.5), 8.0, 8.0)
    p.drawLine(QPointF(20.0, 19.5), QPointF(26.0, 25.5))
    p.setPen(QPen(QColor(color), 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(10.5, 13.5), QPointF(17.5, 13.5))
    if plus:
        p.drawLine(QPointF(14.0, 10.0), QPointF(14.0, 17.0))


def _draw_plot_zoom_in(p: QPainter) -> None:
    _magnifier(p, _PLOT_ZOOM, plus=True)


def _draw_plot_zoom_out(p: QPainter) -> None:
    _magnifier(p, _PLOT_ZOOM, plus=False)


def _draw_plot_crosshair(p: QPainter) -> None:
    """十字竖线：红色竖线 + 顶部横标 + 峰位三角。"""
    _frame(p, _PLOT_CURSOR, alpha=16)
    p.setPen(QPen(QColor(_PLOT_CURSOR), 2.0))
    p.drawLine(QPointF(16.0, 4.5), QPointF(16.0, 27.0))
    p.drawLine(QPointF(10.5, 9.0), QPointF(21.5, 9.0))
    p.setPen(QPen(QColor(_PLOT_CURSOR), 1.2, Qt.PenStyle.DashLine))
    p.drawLine(QPointF(6.0, 22.0), QPointF(26.0, 22.0))
    p.setBrush(QColor(_PLOT_CURSOR))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(13.0, 22.0), QPointF(19.0, 22.0),
                             QPointF(16.0, 16.0)]))


_PLOT_DRAWERS = {
    "reset": _draw_plot_reset,
    "zoom_x": _draw_plot_zoom_x,
    "zoom_y": _draw_plot_zoom_y,
    "zoom_rect": _draw_plot_zoom_rect,
    "pan_left": _draw_plot_pan_left,
    "pan_right": _draw_plot_pan_right,
    "zoom_in": _draw_plot_zoom_in,
    "zoom_out": _draw_plot_zoom_out,
    "crosshair": _draw_plot_crosshair,
}


def plot_icon(key: str) -> QIcon | None:
    """谱图操作按钮图标（v1.6.1）；未知键返回 None。"""
    draw = _PLOT_DRAWERS.get(key)
    if draw is None:
        return None
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(QSize(size, size))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 32.0, size / 32.0)
        draw(p)
        p.end()
        icon.addPixmap(pm)
    return icon


def toolbar_icon(key: str) -> QIcon | None:
    """按键名返回彩色图标；未知键返回 None（按钮保持纯文字）。"""
    draw = _DRAWERS.get(key)
    if draw is None:
        return None
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(QSize(size, size))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 32.0, size / 32.0)
        draw(p)
        p.end()
        icon.addPixmap(pm)
    return icon
