"""谱图操作行（v1.6.1）：一排直接作用于谱图的按钮。

与 matplotlib 自带的 NavigationToolbar2QT 分工：

- **导航工具条**（上方）= 图形级操作（回退/前进历史、平移、框选、保存）；
- **谱图操作行**（紧贴谱图上方）= 针对衍射谱的常用动作（复位、按轴框选、
  平移、步进缩放、十字线读数）。

用户要求「这一行放在快捷图标下方、谱图上方」，且十字线必须能**灵活移动**
并显示角度与强度、右键标注峰位、取消选择后消失。

按钮 → 动作：

============  ==================================================
按钮          动作
============  ==================================================
原始谱图      恢复默认视场（横轴全量 + 纵轴贴合全谱）
横向框选      拖出角度区间，只改横轴（纵轴自动贴合该区间）
纵向框选      拖出强度区间，只改纵轴
区域放大      拖出矩形，横纵轴一起改
左移 / 右移   视场整体平移 25%（纵轴随之贴合）
放大 / 缩小   以视场中心为锚点步进缩放（纵轴随之贴合）
十字竖线      红色竖线跟随鼠标，状态栏报角度与强度；
              右键在该处添加手动峰位（再次右键同位置即删除）
============  ==================================================
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from xinrefinement.gui.button_icons import plot_icon
from xinrefinement.i18n import tr

#: 按钮顺序（分组之间插分隔线）
TOOL_GROUPS: tuple[tuple[str, ...], ...] = (
    ("reset",),
    ("zoom_x", "zoom_y", "zoom_rect"),
    ("pan_left", "pan_right"),
    ("zoom_in", "zoom_out"),
    ("crosshair",),
)

#: 可保持选中状态的工具（其余是「点一下就执行」的瞬时按钮）
MODE_TOOLS = ("zoom_x", "zoom_y", "zoom_rect", "crosshair")

#: 平移步长（视场宽度的比例）与缩放系数
PAN_FRAC = 0.25
ZOOM_STEP = 0.8          # <1 为放大

_ICON_PX = 22


class PlotToolBar(QWidget):
    """谱图操作按钮行（贴着谱图上方显示）。"""

    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.buttons: dict[str, QToolButton] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(2)

        # 互斥由代码保证（不用 QButtonGroup 的 exclusive：用户要求再点一次
        # 能取消，exclusive 组不允许取消勾选）
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)

        for i, group in enumerate(TOOL_GROUPS):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.VLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                lay.addWidget(line)
            for key in group:
                btn = QToolButton()
                btn.setCheckable(key in MODE_TOOLS)
                btn.setAutoRaise(True)
                btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
                icon = plot_icon(key)
                if icon is not None:
                    btn.setIcon(icon)
                else:                       # 图标绘制失败时退化为文字
                    btn.setText(key)
                btn.setToolTip(tr(f"plot.{key}"))
                btn.clicked.connect(
                    lambda _c=False, k=key: self._on_click(k))
                lay.addWidget(btn)
                self._group.addButton(btn)
                self.buttons[key] = btn

        lay.addStretch(1)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color: #6b6b6b;")
        lay.addWidget(self.lbl_hint)
        canvas.cursorInfo.connect(self._on_cursor_info)

        self.retranslate()

    # -- 交互 ---------------------------------------------------------- #
    def _on_click(self, key: str) -> None:
        """按钮点击：模式类切换选中态，动作类立即执行。"""
        if key in MODE_TOOLS:
            btn = self.buttons[key]
            active = btn.isChecked()
            for other in MODE_TOOLS:        # 单选：先清掉其它工具
                if other != key:
                    self.buttons[other].setChecked(False)
            self.canvas.set_plot_tool(key if active else None)
            if not active:
                self.lbl_hint.setText("")
            return
        btn = self.buttons[key]
        if btn.isChecked():                 # 瞬时按钮不该保持选中
            btn.setChecked(False)
        if key == "reset":
            self.canvas.reset_view()
        elif key == "pan_left":
            self.canvas.pan_x(-PAN_FRAC)
        elif key == "pan_right":
            self.canvas.pan_x(PAN_FRAC)
        elif key == "zoom_in":
            self.canvas.zoom_scale(ZOOM_STEP)
        elif key == "zoom_out":
            self.canvas.zoom_scale(1.0 / ZOOM_STEP)

    def _on_cursor_info(self, text: str) -> None:
        """十字线读数：贴着谱图也显示一份（状态栏可能被其它消息占用）。"""
        self.lbl_hint.setText(text if self.canvas.tool == "crosshair" else "")

    def set_tool(self, tool: str | None) -> None:
        """程序化切换工具（测试与快捷键用），保持按钮状态一致。"""
        self.canvas.set_plot_tool(tool)
        for key in MODE_TOOLS:
            self.buttons[key].setChecked(key == tool)
        if tool is None:
            self.lbl_hint.setText("")

    @property
    def mode(self) -> str | None:
        return self.canvas.tool

    def retranslate(self) -> None:
        for key, btn in self.buttons.items():
            btn.setToolTip(tr(f"plot.{key}"))
