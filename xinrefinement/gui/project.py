"""P3.7 · 工程文件 ``.xinr`` 保存 / 恢复（v1.1.0 升级为自包含 zip 容器）。

两种形态（按文件头魔数自动分流，旧 ``.xrp`` 永久只读兼容）：

* **zip 容器（format_version=2，扩展名建议 ``.xinr``）**——内嵌谱图 CSV、
  CIF 与完整精修结果，换机器 / 移目录后仍可打开精修；
  与 ``.xinm``（XinMatch 物相分析）同构，见 docs/JOINT_PLAN_xinm_xinr.md。
* **纯 JSON（format_version=1，扩展名 ``.xrp``）**——v1.0.0 行为：只存路径
  引用（相对工程目录解析），缺文件仅提示不中断。
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path

from xinrefinement import __version__

FORMAT = "xinrefinement-project"
FORMAT_VERSION = 2
_ZIP_MAGIC = b"PK"

_PATTERN_MEMBER = "pattern/pattern.csv"
_CIF_DIR = "cifs"
_RESULT_MEMBER = "result/refine.json"

#: zip 容器解压内容上限（防 zip 炸弹）。
_MAX_TOTAL_BYTES = 512 * 1024 * 1024


def _jsonable(obj):
    """把 numpy 标量/数组转成 JSON 可序列化对象（``result_full`` 用）。"""
    import numpy as np

    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    raise TypeError(f"无法序列化为 JSON: {type(obj).__name__}")


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


# --------------------------------------------------------------------------- #
# 旧 JSON（format_version=1，.xrp）——保留 v1.0.0 行为
# --------------------------------------------------------------------------- #
def serialize(state: dict, project_path: str | Path) -> dict:
    """把主窗口状态序列化为可写盘字典（路径相对化）。"""
    out = Path(project_path)
    base = out.parent
    return {
        "format": FORMAT,
        "format_version": 1,
        "app_version": __version__,
        "language": state.get("language", "zh"),
        "pattern": _rel(state["pattern"], base) if state.get("pattern") else None,
        "cifs": [_rel(p, base) for p in state.get("cifs", [])],
        "settings": state.get("settings", {}),
        "phase_edits": state.get("phase_edits", {}),
        "result": state.get("result"),
        "navigation": state.get("navigation", {}),
    }


def _load_json_v1(p: Path) -> dict:
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
        "phase_edits": data.get("phase_edits", {}),
        "result": data.get("result"),
        "result_full": None,
        "navigation": data.get("navigation", {}),
        "missing": missing,
        "project_path": str(p.resolve()),
        "embedded": False,
    }


# --------------------------------------------------------------------------- #
# zip 容器（format_version=2，.xinr）
# --------------------------------------------------------------------------- #
def _pattern_csv_text(pattern_path: str | Path) -> str:
    """读入既有谱图文件的两列数值，重新以规范 CSV 落盘。

    直接复用 core 的 load_pattern 解析（支持全部受支持格式），再统一写出，
    避免 .xinr 内嵌格式随原始格式发散。
    """
    from xinrefinement.core.patterns import load_pattern
    pat = load_pattern(str(pattern_path))
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["two_theta", "intensity"])
    writer.writerows(
        zip((("%.10g" % v) for v in pat.two_theta.tolist()),
            (("%.10g" % v) for v in pat.intensity.tolist())))
    return buf.getvalue()


def _save_zip(state: dict, out: Path) -> Path:
    base = out.parent
    cif_members: list[dict] = []
    for i, cif in enumerate(state.get("cifs", [])):
        src = Path(cif)
        if not src.is_file():
            continue
        member = f"{_CIF_DIR}/{i:02d}_{src.stem}.cif"
        cif_members.append({"name": src.stem, "member": member,
                            "source_path": str(src.resolve())})
    pattern_rel = _rel(state["pattern"], base) if state.get("pattern") else None
    result_full = state.get("result_full")
    manifest = {
        "format": FORMAT,
        "format_version": 2,
        "app_version": __version__,
        "language": state.get("language", "zh"),
        "settings": state.get("settings", {}),
        "phase_edits": state.get("phase_edits", {}),
        "result": state.get("result"),
        "result_full": _RESULT_MEMBER if result_full else None,
        "navigation": state.get("navigation", {}),
        "pattern": {"member": _PATTERN_MEMBER,
                    "source_path": pattern_rel or ""},
        "cifs": cif_members,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        if state.get("pattern") and Path(state["pattern"]).is_file():
            zf.writestr(_PATTERN_MEMBER,
                        _pattern_csv_text(state["pattern"]))
        for cm in cif_members:
            zf.write(cm["source_path"], cm["member"])
        if result_full:
            zf.writestr(_RESULT_MEMBER, json.dumps(
                result_full, ensure_ascii=False, indent=2, default=_jsonable))
        zf.writestr("manifest.json", json.dumps(
            manifest, ensure_ascii=False, indent=2, default=_jsonable))
    return out


def _extract_session_dir(p: Path) -> Path:
    """zip 工程的内嵌数据解压目录（会话级，重复打开复用）。"""
    d = Path(tempfile.gettempdir()) / "xinrefinement_projects" / (
        f"{p.stem}_{int(p.stat().st_mtime)}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_zip(p: Path) -> dict:
    import numpy as np

    session = _extract_session_dir(p)
    missing: list[str] = []
    pattern_path: str | None = None
    cif_paths: list[str] = []
    with zipfile.ZipFile(p) as zf:
        total = sum(i.file_size for i in zf.infolist())
        if total > _MAX_TOTAL_BYTES:
            raise ValueError(
                f"工程解压内容 {total / 1e6:.0f} MB 超过上限 "
                f"{_MAX_TOTAL_BYTES // (1024 * 1024)} MB，已拒绝读取")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != FORMAT:
            raise ValueError(f"不是 {FORMAT} 工程文件: {p.name}")
        fv = int(manifest.get("format_version", 0))
        if fv > FORMAT_VERSION:
            raise ValueError(
                f"工程文件版本 {fv} 高于本程序支持的 {FORMAT_VERSION}，请升级软件")
        pm = manifest.get("pattern") or {}
        member = pm.get("member")
        if member and member in zf.namelist():
            # 写成 .xy 两列文本，走既有 load_pattern 通道
            rows = list(csv.reader(
                io.StringIO(zf.read(member).decode("utf-8"))))[1:]
            arr = np.array(
                [[float(r[0]), float(r[1])] for r in rows if r], dtype=float)
            xy = session / "pattern.xy"
            with xy.open("w", encoding="utf-8", newline="\n") as fh:
                for x, y in arr:
                    fh.write(f"{x:.10g} {y:.10g}\n")
            pattern_path = str(xy)
        elif pm.get("source_path"):
            src = _abs(pm.get("source_path"), p.parent)
            if src and Path(src).exists():
                pattern_path = src
            else:
                missing.append(str(src))
        for cm in manifest.get("cifs", []):
            member = cm.get("member")
            if member and member in zf.namelist():
                dst = session / Path(member).name
                dst.write_bytes(zf.read(member))
                cif_paths.append(str(dst))
            elif cm.get("source_path"):
                src = _abs(cm.get("source_path"), p.parent)
                if src and Path(src).exists():
                    cif_paths.append(src)
                else:
                    missing.append(str(src))
        result_full = None
        rm = manifest.get("result_full")
        if rm and rm in zf.namelist():
            try:
                result_full = json.loads(zf.read(rm).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                result_full = None
    return {
        "language": manifest.get("language", "zh"),
        "pattern": pattern_path,
        "cifs": cif_paths,
        "settings": manifest.get("settings", {}),
        "phase_edits": manifest.get("phase_edits", {}),
        "result": manifest.get("result"),
        "result_full": result_full,
        "navigation": manifest.get("navigation", {}),
        "missing": missing,
        "project_path": str(p.resolve()),
        "embedded": True,
    }


# --------------------------------------------------------------------------- #
# 公共入口
# --------------------------------------------------------------------------- #
def save_project(state: dict, project_path: str | Path,
                 *, embed: bool = True) -> Path:
    """写工程文件（默认自包含 zip 容器；``embed=False`` 退回旧 JSON）。

    返回路径。``embed=True`` 时谱图经 load_pattern 统一解析后内嵌，
    原始谱图缺失会抛异常，由调用方提示。
    """
    out = Path(project_path)
    if embed:
        return _save_zip(state, out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(serialize(state, out), ensure_ascii=False,
                              indent=2), encoding="utf-8")
    return out


def load_project(project_path: str | Path) -> dict:
    """读工程文件并校验格式；zip 容器先解压内嵌数据到会话目录。

    缺文件时不抛异常（返回 ``missing`` 列表），由 GUI 提示用户重新定位。
    """
    p = Path(project_path)
    if not p.is_file():
        raise ValueError(f"工程文件不存在: {p}")
    head = p.open("rb").read(2)
    if head == _ZIP_MAGIC:
        try:
            return _load_zip(p)
        except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"工程文件损坏: {p.name}（{exc}）") from exc
    return _load_json_v1(p)
