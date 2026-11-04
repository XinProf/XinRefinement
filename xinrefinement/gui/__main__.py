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


def _maybe_selftest(win, app) -> bool:
    """验收辅助：设 ``XINREFINEMENT_SELFTEST_REG_OUT=<json>`` 时导出变体
    与注册状态后退出，便于脚本校验两种二进制而不驱动 GUI。

    返回 True 表示已进入自检模式（调用方不再进入事件循环）。
    """
    out = os.environ.get("XINREFINEMENT_SELFTEST_REG_OUT")
    if not out:
        return False
    import json
    from pathlib import Path

    from xinrefinement import build_variant

    reg = getattr(win, "_registration", None)
    payload = {
        "variant": build_variant.current_variant(),
        "registration_enabled": reg is not None,
        "registered": bool(reg is not None and reg.state.registered),
        "unit": reg.state.unit if reg is not None else "",
        "status_text": win.registration_status_text(),
        "state_path": str(reg.state_path) if reg is not None else "",
    }
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    app.quit()
    return True


def main() -> int:
    from PySide6.QtCore import QTimer
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
    if _maybe_selftest(win, app):
        return 0
    # 正式版启动注册检查：QTimer 保证窗口先显示完再弹提示，不阻塞冒烟；
    # 内部评估版无注册管理器，这里直接空转。
    QTimer.singleShot(0, win.startup_registration_check)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
