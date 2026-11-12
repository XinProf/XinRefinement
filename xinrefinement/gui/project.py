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
import shutil
import tempfile
import time
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

#: 解压会话目录回收参数：最近 keep 个保底留存，其余超龄/超总量即删。
_SESSION_KEEP = 8
_SESSION_MAX_AGE_DAYS = 7.0
_SESSION_MAX_TOTAL_MB = 512.0


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
        # 与 zip 路径保持同一键集，调用方不必判键是否存在
        "warnings": [],
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
        zip((("%.17g" % v) for v in pat.two_theta.tolist()),
            (("%.17g" % v) for v in pat.intensity.tolist())))
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


def _session_root() -> Path:
    """解压会话根目录。独立成函数是为了给测试留唯一的 monkeypatch 注入点。"""
    return Path(tempfile.gettempdir()) / "xinrefinement_projects"


def _dir_bytes(d: Path) -> int:
    total = 0
    for f in d.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue          # 统计失败按 0 算，别让清理影响打开工程
    return total


def _prune_sessions(root: Path, *, protect: Path,
                    keep: int = _SESSION_KEEP,
                    max_age_days: float = _SESSION_MAX_AGE_DAYS,
                    max_total_mb: float = _SESSION_MAX_TOTAL_MB,
                    now: float | None = None) -> list[Path]:
    """回收 ``root`` 下的解压会话目录，返回「尝试删除」的路径列表。

    ``keep`` 只是「最近 N 个」的数量门槛，**不是硬保底**：排在前 ``keep`` 个
    之内但已超过 ``max_age_days`` 的目录照样删；唯一绝对保留的是 ``protect``
    （当次正在使用的目录）。最后再按总字节上限从最旧删。清理是副业，
    所有 ``OSError`` 一律吞掉。
    """
    now = time.time() if now is None else now
    try:
        entries = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return []
    dated: list[tuple[float, Path]] = []
    for d in entries:
        try:
            dated.append((d.stat().st_mtime, d))
        except OSError:
            continue
    dated.sort(key=lambda t: t[0], reverse=True)   # 新 → 旧

    removed: list[Path] = []

    def _drop(d: Path) -> None:
        removed.append(d)
        try:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass          # 兜底：rmtree 本身抛错也不能影响打开工程

    survivors: list[tuple[float, Path]] = []
    aged_cut = now - max_age_days * 86400
    for i, (mtime, d) in enumerate(dated):
        if d == protect or (i < keep and mtime >= aged_cut):
            survivors.append((mtime, d))
        else:
            _drop(d)

    total = sum(_dir_bytes(d) for _, d in survivors)
    limit = max_total_mb * 1024 * 1024
    if total > limit:
        for _, d in sorted(survivors, key=lambda t: t[0]):   # 最旧先删
            if total <= limit:
                break
            if d == protect:
                continue
            total -= _dir_bytes(d)
            _drop(d)
    return removed


def _extract_session_dir(p: Path) -> Path:
    """zip 工程的内嵌数据解压目录（会话级，重复打开复用）。"""
    root = _session_root()
    d = root / f"{p.stem}_{int(p.stat().st_mtime)}"
    d.mkdir(parents=True, exist_ok=True)
    # 每个 mtime 一个新目录且永不清理会撑爆临时目录；mkdir 之后再清理，
    # 保证 protect 目录已存在、当次文件不会被回收。
    try:
        _prune_sessions(root, protect=d)
    except OSError:
        pass
    return d


def _load_zip(p: Path) -> dict:
    import numpy as np

    session = _extract_session_dir(p)
    missing: list[str] = []
    warnings: list[str] = []
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
                    fh.write(f"{x:.17g} {y:.17g}\n")
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
                # 静默置 None 会让结果区莫名变空，必须留痕给用户
                result_full = None
                warnings.append(
                    "工程内嵌精修结果（result/refine.json）无法解析，"
                    "已忽略；结果区可能不完整")
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
        "warnings": warnings,
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
    with p.open("rb") as fh:
        head = fh.read(2)
    if head == _ZIP_MAGIC:
        try:
            return _load_zip(p)
        except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"工程文件损坏: {p.name}（{exc}）") from exc
    return _load_json_v1(p)
