"""GUI 入口：``python -m xinrefinement.gui``。"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from xinrefinement.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
