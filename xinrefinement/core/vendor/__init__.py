# vendored from PolyXRD-RutAna :: rutana/core/vendor/__init__.py
"""PolyXRD-Converter 读谱器的本地 vendor 副本。

© 2026 PolyXRD Team，dual-licensed。禁止从兄弟仓库运行时 import；更新时需与
PolyXRD-Converter 的对应源文件逐项对拍。
"""

from .model import XRDData
from .text_formats import DataFormatError, detect_format, load_pattern

__all__ = ["DataFormatError", "XRDData", "detect_format", "load_pattern"]
