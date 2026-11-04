"""pytest 公共 fixture —— 项目根与 CIF 目录（P0 精简版，后续按需扩展）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 tests/ 直接 import xinrefinement（无需安装包）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CIF_DIR = ROOT / "xinrefinement" / "data" / "cif"


@pytest.fixture(scope="session")
def cif_dir() -> Path:
    """内置 CIF 目录。"""
    return CIF_DIR
