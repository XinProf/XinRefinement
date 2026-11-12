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


@pytest.fixture(autouse=True)
def _isolate_project_sessions(tmp_path, monkeypatch):
    """把 .xinr 解压会话根重定向到临时目录：测试绝不读写真实 %TEMP%。

    ``_extract_session_dir`` 会顺手回收旧会话（既写又删），所以任何走
    ``load_project`` 的用例都必须隔离；否则会删掉真实 %TEMP% 里别人的目录。
    """
    monkeypatch.setattr("xinrefinement.gui.project._session_root",
                        lambda: tmp_path / "sessions")
