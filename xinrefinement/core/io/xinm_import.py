"""``.xinm`` 导入 —— XinMatch 物相分析状态 → XinRefinement（联合计划 R-1）。

读取 :mod:`xinmatch.core.io.xinm` 导出的 zip 容器
（``manifest.json + pattern/pattern.csv + cifs/*.cif``），产出可直接驱动
GUI 装载的 :class:`XinmPayload`。本模块**不依赖 Qt**，供 GUI / CLI / 库 API 共用。

版权边界：manifest 中 ``source="pdf2"`` / ``structural=false`` 的相不携带
CIF，导入时列为「仅参照相」，不参与精修（见 docs/JOINT_PLAN_xinm_xinr.md §3）。
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "SUPPORTED_XINM_VERSION",
    "XinmImportError",
    "XinmPayload",
    "XinmPhase",
    "extract_cifs",
    "read_xinm",
]

#: 当前支持的 manifest 版本（升级策略：只加不减字段，>本值提示升级软件）。
SUPPORTED_XINM_VERSION = 1

#: 解压内容总上限（防 zip 炸弹；与导出侧 _MAX_TOTAL_BYTES 一致）。
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024


class XinmImportError(ValueError):
    """`.xinm` 文件无效 / 版本过高 / 内容损坏。"""


@dataclass
class XinmPhase:
    """`.xinm` manifest 里的一个物相。"""

    name: str
    source: str = "unresolved"          # cod | user_cif | pdf2 | unresolved
    entry_id: str = ""
    cif_member: str | None = None       # zip 内路径
    structural: bool = False
    reason: str = ""
    fom: float | None = None
    scale_factor: float = 1.0
    two_theta_shift: float = 0.0
    weight_fraction: float | None = None
    cell: dict | None = None
    space_group: str | None = None
    formula: str = ""
    mineral_name: str | None = None


@dataclass
class XinmPayload:
    """一次 .xinm 导入的完整载荷。"""

    two_theta: np.ndarray
    intensity: np.ndarray
    meta: dict = field(default_factory=dict)      # wavelength/anode/tmin/tmax/step/source_path…
    peaks: list[dict] = field(default_factory=list)
    phases: list[XinmPhase] = field(default_factory=list)
    candidates_summary: list[dict] = field(default_factory=list)
    notes: str = ""
    created: str = ""
    app_version: str = ""
    cif_bytes: dict[str, bytes] = field(default_factory=dict)   # member → 内容
    source_path: str = ""                         # .xinm 文件自身路径

    @property
    def structural_phases(self) -> list["XinmPhase"]:
        return [p for p in self.phases if p.structural and p.cif_member]

    @property
    def reference_only_phases(self) -> list["XinmPhase"]:
        return [p for p in self.phases if not (p.structural and p.cif_member)]


# --------------------------------------------------------------------------- #
# 读取
# --------------------------------------------------------------------------- #
def _read_pattern_csv(text: str) -> tuple[np.ndarray, np.ndarray]:
    rows = csv.reader(io.StringIO(text))
    header = next(rows, None)
    if header is None or [c.strip().lower() for c in header[:2]] != [
            "two_theta", "intensity"]:
        raise XinmImportError("pattern CSV 缺少 two_theta,intensity 表头")
    tt: list[float] = []
    ii: list[float] = []
    for lineno, row in enumerate(rows, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) < 2:
            raise XinmImportError(f"pattern CSV 第 {lineno} 行缺列: {row!r}")
        try:
            tt.append(float(row[0]))
            ii.append(float(row[1]))
        except ValueError as exc:
            raise XinmImportError(
                f"pattern CSV 第 {lineno} 行无法解析为数字: {row!r}") from exc
    if len(tt) < 2:
        raise XinmImportError("pattern CSV 有效数据点不足 2 个")
    return np.asarray(tt), np.asarray(ii)


def read_xinm(
    path: str | Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> XinmPayload:
    """读取 `.xinm` zip 容器并校验。

    Raises
    ------
    XinmImportError
        不是 zip / 缺 manifest / format 或 version 不符 / manifest 损坏 /
        解压内容超上限 / CSV 损坏。
    """
    p = Path(path)
    if not p.is_file():
        raise XinmImportError(f"文件不存在: {p}")
    try:
        zf = zipfile.ZipFile(p)
    except (zipfile.BadZipFile, OSError) as exc:
        raise XinmImportError(f"不是有效的 .xinm（zip）文件: {p.name}") from exc

    with zf:
        infos = zf.infolist()
        total = sum(i.file_size for i in infos)
        if total > max_total_bytes:
            raise XinmImportError(
                f".xinm 解压内容 {total / 1e6:.0f} MB 超过上限 "
                f"{max_total_bytes // (1024 * 1024)} MB，已拒绝读取")
        names = {i.filename for i in infos}
        if "manifest.json" not in names:
            raise XinmImportError(".xinm 缺少 manifest.json")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XinmImportError(f"manifest.json 损坏: {exc}") from exc
        if manifest.get("format") != "xinm":
            raise XinmImportError(
                f"不是 xinm 格式（format={manifest.get('format')!r}）")
        version = int(manifest.get("version", 0))
        if version > SUPPORTED_XINM_VERSION:
            raise XinmImportError(
                f".xinm 版本 {version} 高于本程序支持的 "
                f"{SUPPORTED_XINM_VERSION}，请升级软件")
        pat = manifest.get("pattern") or {}
        csv_member = pat.get("file", "pattern/pattern.csv")
        if csv_member not in names:
            raise XinmImportError(f".xinm 缺少谱图数据 {csv_member}")
        try:
            tt, ii = _read_pattern_csv(
                zf.read(csv_member).decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise XinmImportError("pattern CSV 不是 UTF-8 文本") from exc

        meta = {
            "wavelength": float(pat.get("wavelength", 1.5406)),
            "anode": pat.get("anode", "Cu"),
            "tmin": pat.get("tmin"),
            "tmax": pat.get("tmax"),
            "step": pat.get("step"),
            "source_path": pat.get("source_path", ""),
            "raw_metadata": dict(pat.get("metadata") or {}),
        }

        phases = [XinmPhase(
            name=str(d.get("name", f"phase_{i + 1}")),
            source=str(d.get("source", "unresolved")),
            entry_id=str(d.get("entry_id", "")),
            cif_member=d.get("cif_file"),
            structural=bool(d.get("structural", False)),
            reason=str(d.get("reason", "")),
            fom=d.get("fom"),
            scale_factor=float(d.get("scale_factor", 1.0)),
            two_theta_shift=float(d.get("two_theta_shift", 0.0)),
            weight_fraction=d.get("weight_fraction"),
            cell=d.get("cell"),
            space_group=d.get("space_group"),
            formula=str(d.get("formula", "")),
            mineral_name=d.get("mineral_name"),
        ) for i, d in enumerate(manifest.get("phases", []))]

        cif_bytes: dict[str, bytes] = {}
        for ph in phases:
            member = ph.cif_member
            if member and member in names:
                cif_bytes[member] = zf.read(member)
            elif ph.structural:
                # S3 边界：manifest 声称有结构，但包内没有该 CIF（导出侧写入
                # 失败/被裁掉）→ 降级为「仅参照」，保留可读原因而不是静默丢弃
                ph.structural = False
                ph.reason = f"包内缺少该相的 CIF（{member or '未声明'}）"

        return XinmPayload(
            two_theta=tt, intensity=ii, meta=meta,
            peaks=list(manifest.get("peaks", [])),
            phases=phases,
            candidates_summary=list(manifest.get("candidates_summary", [])),
            notes=str(manifest.get("notes", "")),
            created=str(manifest.get("created", "")),
            app_version=str((manifest.get("app") or {}).get("version", "")),
            cif_bytes=cif_bytes,
            source_path=str(p),
        )


def extract_cifs(payload: XinmPayload, dest_dir: str | Path) -> dict[str, Path]:
    """把 payload 内嵌的 CIF 写到 *dest_dir*，返回 ``phase_name → 路径``。

    文件名取 zip member 的 stem；同名冲突时后写覆盖（导出侧 member 名
    已按 COD id 唯一）。供 GUI 走既有 ``_load_cif_paths`` 通道。
    """
    out = Path(dest_dir)
    out.mkdir(parents=True, exist_ok=True)
    name_to_path: dict[str, Path] = {}
    by_member = {ph.cif_member: ph for ph in payload.phases if ph.cif_member}
    for member, data in payload.cif_bytes.items():
        target = out / Path(member).name
        target.write_bytes(data)
        ph = by_member.get(member)
        if ph is not None:
            name_to_path[ph.name] = target
    return name_to_path
