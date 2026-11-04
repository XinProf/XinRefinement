"""P3.7 · 工程文件 ``.xrp`` 保存 / 恢复。

JSON 格式，内容：谱图引用 + CIF 列表 + 齿轮设置 + 结果摘要 +
导航状态（步骤状态 / 记录 / 参数快照）+ 语言 + 版本。

**不含原始谱图数据**（只存路径引用），避免工程文件膨胀；谱图/CIF 路径
按工程文件所在目录解析为相对路径，工程目录整体移动后仍可打开。
"""
from __future__ import annotations

import json
from pathlib import Path

from xinrefinement import __version__

FORMAT = "xinrefinement-project"
FORMAT_VERSION = 1


def _rel(path, base: Path) -> str:
    """尽量写成相对路径；跨盘符时用绝对路径。"""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(base.resolve()))
    except (ValueError, OSError):
        return str(p.resolve())


def _abs(value: str | None, base: Path) -> str | None:
    if not value:
        return None
    p = Path(value)
    return str((base / p if not p.is_absolute() else p).resolve())


def serialize(state: dict, project_path: str | Path) -> dict:
    """把主窗口状态序列化为可写盘字典（路径相对化）。"""
    out = Path(project_path)
    base = out.parent
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "language": state.get("language", "zh"),
        "pattern": _rel(state["pattern"], base) if state.get("pattern") else None,
        "cifs": [_rel(p, base) for p in state.get("cifs", [])],
        "settings": state.get("settings", {}),
        "result": state.get("result"),
        "navigation": state.get("navigation", {}),
    }


def save_project(state: dict, project_path: str | Path) -> Path:
    """写工程文件，返回路径。"""
    out = Path(project_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(serialize(state, out), ensure_ascii=False,
                              indent=2), encoding="utf-8")
    return out


def load_project(project_path: str | Path) -> dict:
    """读工程文件并校验格式；路径还原为绝对路径。

    缺文件时不抛异常（返回 ``missing`` 列表），由 GUI 提示用户重新定位。
    """
    p = Path(project_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError(f"不是 {FORMAT} 工程文件: {p.name}")
    if int(data.get("format_version", 0)) > FORMAT_VERSION:
        raise ValueError(
            f"工程文件版本 {data['format_version']} 高于本程序支持的 "
            f"{FORMAT_VERSION}，请升级软件")
    base = p.parent
    pattern = _abs(data.get("pattern"), base)
    cifs = [_abs(c, base) for c in data.get("cifs", []) if c]
    missing = []
    if pattern and not Path(pattern).exists():
        missing.append(pattern)
    for c in cifs:
        if not Path(c).exists():
            missing.append(c)
    return {
        "language": data.get("language", "zh"),
        "pattern": pattern,
        "cifs": cifs,
        "settings": data.get("settings", {}),
        "result": data.get("result"),
        "navigation": data.get("navigation", {}),
        "missing": missing,
        "project_path": str(p.resolve()),
    }
