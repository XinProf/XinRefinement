"""A07 · ``.xinr`` 解压会话目录的有界回收。

所有用例都把 ``project._session_root`` 重定向到 ``tmp_path``，绝不碰真实 TEMP。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from xinrefinement.gui import project


@pytest.fixture()
def sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "sessions"
    root.mkdir()
    monkeypatch.setattr(project, "_session_root", lambda: root)
    return root


def _mk_session(root: Path, name: str, *, age_sec: float = 0.0,
                size: int = 0) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pattern.xy").write_text("10 1\n", encoding="utf-8")
    if size:
        (d / "blob.bin").write_bytes(b"\0" * size)
    ts = time.time() - age_sec
    os.utime(d, (ts, ts))
    return d


def _make_xinr(tmp_path: Path) -> Path:
    base = tmp_path / "proj"
    base.mkdir(exist_ok=True)
    tt = np.linspace(5.0, 90.0, 21)
    xy = base / "demo.xy"
    xy.write_text("\n".join(f"{x:.10g} 100" for x in tt), encoding="utf-8")
    out = base / "demo.xinr"
    project.save_project(
        {"language": "zh", "pattern": str(xy), "cifs": [], "settings": {},
         "phase_edits": {}, "result": None, "navigation": {}},
        out, embed=True)
    return out


# --------------------------------------------------------------------------- #
# 目录命名 / 复用语义不变
# --------------------------------------------------------------------------- #
def test_session_dir_name_and_reuse(tmp_path: Path, sessions: Path) -> None:
    out = _make_xinr(tmp_path)
    d1 = project._extract_session_dir(out)
    assert d1.parent == sessions
    assert d1.name == f"{out.stem}_{int(out.stat().st_mtime)}"

    n1 = len(list(d1.iterdir()))
    data1 = project.load_project(out)
    n2 = len(list(d1.iterdir()))
    data2 = project.load_project(out)
    n3 = len(list(d1.iterdir()))
    assert data1["pattern"] == data2["pattern"]
    assert Path(data2["pattern"]).parent == d1
    assert n2 == n1 + 1, "首次打开解出 pattern.xy"
    assert n3 == n2, "同一 mtime 命中同一目录，文件数不应翻倍"


# --------------------------------------------------------------------------- #
# 数量上限
# --------------------------------------------------------------------------- #
def test_prune_keeps_recent_n(sessions: Path) -> None:
    dirs = [_mk_session(sessions, f"s{i}", age_sec=i * 600.0) for i in range(12)]
    protect = dirs[0]
    removed = project._prune_sessions(sessions, protect=protect, keep=8)
    left = {d.name for d in sessions.iterdir()}
    assert len(left) == 8
    assert {d.name for d in dirs[:8]} == left      # 最近 8 个
    assert len(removed) == 4
    assert protect.name in left


# --------------------------------------------------------------------------- #
# 超龄回收
# --------------------------------------------------------------------------- #
def test_prune_drops_aged(sessions: Path) -> None:
    old = _mk_session(sessions, "old", age_sec=30 * 86400)
    fresh = _mk_session(sessions, "fresh", age_sec=60.0)
    removed = project._prune_sessions(sessions, protect=fresh)
    assert removed == [old]
    assert [d.name for d in sessions.iterdir()] == ["fresh"]


# --------------------------------------------------------------------------- #
# 总量上限
# --------------------------------------------------------------------------- #
def test_prune_total_size_cap(sessions: Path) -> None:
    # 每个目录略小于 0.5 MB（留出 pattern.xy 的字节），两个刚好不超 1.0 MB
    half_mb = 512 * 1024 - 1024
    dirs = [_mk_session(sessions, f"b{i}", age_sec=i * 60.0, size=half_mb)
            for i in range(4)]
    newest = dirs[0]
    project._prune_sessions(sessions, protect=newest, max_total_mb=1.0)
    left = {d.name for d in sessions.iterdir()}
    assert left == {"b0", "b1"}, "从最旧删到不超上限，且保留当次目录"


# --------------------------------------------------------------------------- #
# 删除失败必须被吞掉
# --------------------------------------------------------------------------- #
def test_prune_tolerates_delete_failure(
        tmp_path: Path, sessions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempted: list[Path] = []

    def _failing_rmtree(path, *args, ignore_errors=False, **kwargs):
        attempted.append(Path(path))
        # 无论 ignore_errors 取值都真抛，模拟 rmtree 自身或前置检查就失败
        # （被替换 / 只读卷 / 路径竞态）；兜底在 _drop 里，不在 shutil 内部。
        raise OSError("boom")

    monkeypatch.setattr(project.shutil, "rmtree", _failing_rmtree)
    dirs = [_mk_session(sessions, f"s{i}", age_sec=i * 600.0) for i in range(4)]
    # 不包 pytest.raises：_drop 的 except OSError 生效时这里才走得下去
    removed = project._prune_sessions(sessions, protect=dirs[0], keep=1)
    assert len(removed) == 3
    # 用返回值 + 替身调用记录证明「尝试过删除」，不靠异常被吞掉来间接推断
    assert attempted == removed
    assert len(list(sessions.iterdir())) == 4      # 没删掉但也没抛

    out = _make_xinr(tmp_path)
    data = project.load_project(out)               # 打开工程不受影响
    assert Path(data["pattern"]).is_file()


# --------------------------------------------------------------------------- #
# 端到端：打开工程后目录有界、当次数据完好
# --------------------------------------------------------------------------- #
def test_open_project_end_to_end(tmp_path: Path, sessions: Path) -> None:
    for i in range(12):
        _mk_session(sessions, f"stale{i}", age_sec=(i + 1) * 60.0)
    out = _make_xinr(tmp_path)
    data = project.load_project(out)
    assert data["pattern"] and Path(data["pattern"]).is_file()
    dirs = [d for d in sessions.iterdir() if d.is_dir()]
    assert len(dirs) <= project._SESSION_KEEP
    assert Path(data["pattern"]).parent in dirs
