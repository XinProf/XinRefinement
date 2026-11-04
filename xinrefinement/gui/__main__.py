"""GUI 入口：``python -m xinrefinement.gui``。

启动流程：QApplication → 应用图标（assets）→ QSplashScreen 启动画面
（assets/splash.png，offscreen 测试环境跳过）→ 主窗口就绪后关闭画面。
"""
from __future__ import annotations

import os
import sys


def _maybe_show_splash(app) -> "QtWidgets.QSplashScreen | None":  # noqa: F821
    """显示启动画面；资源缺失或 offscreen（离屏测试）时返回 None。

    offscreen 下 QSplashScreen.show() 会吞掉预排的 QTimer.singleShot(0,
    quit)，导致事件循环空转——这是外观特性，无头环境直接跳过。
    """
    del app  # QSplashScreen 无需额外设置
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    from PySide6.QtWidgets import QSplashScreen

    from xinrefinement.gui.assets import load_pixmap

    pix = load_pixmap("splash.png")
    if pix.isNull():
        return None
    splash = QSplashScreen(pix)
    splash.show()
    return splash


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from xinrefinement.gui.assets import app_icon
    from xinrefinement.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    icon = app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    splash = _maybe_show_splash(app)

    win = MainWindow()
    win.show()
    if splash is not None:
        splash.finish(win)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
