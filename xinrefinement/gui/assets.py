"""品牌资源（logo / splash / 图标）定位。

查找顺序（首个存在的文件生效）：

1. **项目目录** ``<项目根>/assets/<name>`` —— 源码模式优先读这里，
   换 logo / splash 不用动包内副本；
2. **冻结解包目录** ``sys._MEIPASS/xinrefinement/data/assets/<name>``
   —— PyInstaller onedir 产物（spec datas 已把 ``xinrefinement/data``
   整目录打入）；
3. **包内副本** ``xinrefinement/data/assets/<name>`` —— 兜底
   （pip 安装 / 直接从包目录运行）。

找不到一律返回 ``None``，调用方自行降级（不弹错、不崩）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_ASSETS = Path(__file__).resolve().parents[1] / "data" / "assets"


def asset_path(name: str) -> Path | None:
    """按查找顺序解析 assets/ 下的资源文件；缺失返回 None。"""
    candidates = [
        Path(__file__).resolve().parents[2] / "assets" / name,   # 项目根
        Path(getattr(sys, "_MEIPASS", "")) / "xinrefinement" / "data" / "assets" / name,
        _PACKAGE_ASSETS / name,
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def load_pixmap(name: str):
    """读 QPixmap；资源缺失或解码失败返回空 QPixmap（isNull()=True）。"""
    from PySide6.QtGui import QPixmap

    p = asset_path(name)
    if p is None:
        return QPixmap()
    return QPixmap(str(p))


def app_icon() -> "QtGui.QIcon | None":  # noqa: F821 - 字符串注解，避免导入环
    """应用图标：icons/logo_256.png → icons/logo_128.png → logo.png。"""
    from PySide6.QtGui import QIcon

    for name in ("icons/logo_256.png", "icons/logo_128.png", "logo.png"):
        p = asset_path(name)
        if p is not None:
            return QIcon(str(p))
    return None
