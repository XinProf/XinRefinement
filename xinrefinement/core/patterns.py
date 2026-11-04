# vendored from PolyXRD-RutAna :: rutana/core/patterns.py
"""谱图读取与基础操作 —— A/B 法共用的数据入口（T1.1 / v1.0.0 扩展）。

实现说明：参考 PolyXRD-SynthPattern 的 load_measured() 思路自行实现，
不 import 兄弟仓库（项目铁律）。

v1.0.0 新增（真实数据接入，对应 XRData/TiO2 岛津应用数据集 XRD-019）：
  1) 容忍 UTF-8 BOM（utf-8-sig）与首个非数值行（岛津导出首行为 `?`）；
  2) 支持 FullProf/GSAS 风格 pd 格式（`loop_` + `_pd_proc_2theta_corrected`
     + `_pd_meas_intensity_total` / `_pd_calc_intensity_total`）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from xinrefinement.core.dtypes import Pattern
from xinrefinement.core.vendor.text_formats import (
    ANODE_WAVELENGTHS,
    DataFormatError,
    detect_format as detect_vendor_format,
    load_pattern as load_vendor_pattern,
    wavelength_from_text,
)

# 既有四种文本格式保持 v1.5.0 黄金行为；其余格式由本地 vendored reader 读取。
_LEGACY_TEXT_EXTS = {".xy", ".txt", ".dat", ".csv"}
_RAW_EXTS = {".raw", ".org", ".rsm", ".rbg", ".rk1", ".rax", ".rlz", ".rfi"}
_BINARY_CONTAINER_EXTS = {".rasx", ".brml"}
SUPPORTED_EXTS = _LEGACY_TEXT_EXTS | _RAW_EXTS | {
    ".mdi", ".gsas", ".gss", ".gsa", ".gda", ".fxye", ".ras", ".rasx",
    ".xye", ".qye", ".chi", ".qchi", ".xrdml", ".xml", ".brml", ".json",
    ".smz",
}

# FullProf pd 格式：数据块起始标记与常见列名
PD_LOOP_TOKEN = "loop_"
PD_X_NAMES = ("_pd_proc_2theta_corrected", "_pd_meas_2theta",
              "_pd_proc_2theta", "_pd_calc_2theta")
PD_Y_NAMES = ("_pd_meas_intensity_total", "_pd_calc_intensity_total",
              "_pd_meas_intensity", "_pd_calc_intensity",
              "_pd_proc_intensity_total")

# 读取时的编码候选顺序（中文 Windows 导出常见 GBK，其次 utf-8-sig/latin-1）
_ENCODINGS = ("utf-8-sig", "gbk", "latin-1")


def _read_text(path: Path) -> str:
    """按候选编码顺序读取文本；utf-8-sig 自动吃掉 BOM。"""
    raw = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _to_float(token: str) -> float | None:
    """把 token 解析为 float；失败返回 None。"""
    try:
        return float(token)
    except ValueError:
        return None


def _parse_two_column(text: str) -> tuple[np.ndarray, np.ndarray]:
    """解析两列文本：跳过 #/ / 开头注释行，容忍首个非数据行（表头/`?`）。"""
    xs: list[float] = []
    ys: list[float] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        parts = s.replace(",", " ").split()
        if len(parts) < 2:
            if not xs:  # 尚未读到数据 -> 视为表头行，容忍
                continue
            raise ValueError(f"第 {lineno} 行列数不足（需要两列）: {raw!r}")
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            if not xs:  # 尚未读到数据 -> 视为表头行，容忍
                continue
            raise ValueError(f"第 {lineno} 行无法解析为数字: {raw!r}") from None
        xs.append(x)
        ys.append(y)
    if len(xs) < 2:
        raise ValueError("有效数据点不足 2 个，无法构成谱图")
    return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def is_pd_format(text: str) -> bool:
    """判断文本是否为 FullProf pd 格式（含 loop_ 与 2θ 列名）。"""
    if PD_LOOP_TOKEN not in text:
        return False
    return any(name in text for name in PD_X_NAMES)


def _parse_pd(text: str) -> tuple[np.ndarray, np.ndarray]:
    """解析 pd 格式：定位 loop_ 数据块，按列名行之后的两列取数。

    数据块内的行规则：
      - 以 `_` 开头 -> 列名行（收集）；
      - 空行 / 再次出现 `loop_` -> 数据块结束；
      - 其余必须解析出至少两个 float，否则抛 ValueError。
    """
    lines = text.splitlines()
    start = next(i for i, s in enumerate(lines)
                 if s.strip().lower() == PD_LOOP_TOKEN)
    xs: list[float] = []
    ys: list[float] = []
    names: list[str] = []
    for lineno, raw in enumerate(lines[start + 1:], start=start + 2):
        s = raw.strip()
        if not s:
            if xs:  # 数据已开始 -> 空行视为块结束
                break
            continue
        if s.lower() == PD_LOOP_TOKEN:
            break
        if s.startswith("_"):
            if xs:  # 新列名行出现在数据之后 -> 块结束
                break
            names.append(s.split()[0])
            continue
        parts = s.replace(",", " ").split()
        if len(parts) < 2:
            if not xs:
                continue
            raise ValueError(f"pd 格式第 {lineno} 行列数不足: {raw!r}")
        x = _to_float(parts[0])
        y = _to_float(parts[1])
        if x is None or y is None:
            if not xs:
                continue
            raise ValueError(f"pd 格式第 {lineno} 行无法解析为数字: {raw!r}")
        xs.append(x)
        ys.append(y)
    if len(xs) < 2:
        raise ValueError("pd 格式有效数据点不足 2 个，无法构成谱图")
    if not any(n in PD_X_NAMES for n in names):
        raise ValueError(f"pd 格式未找到 2θ 列名，实际列名: {names}")
    return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def load_pattern(path: str | Path) -> Pattern:
    """读取受支持谱图，保留既有文本黄金行为并调度 vendored reader。

    ``.xy/.txt/.dat/.csv`` 仍优先使用 v1.5.0 的 pd/两列解析器；只有文件头
    明确命中新格式，或旧解析器确认没有数据点时，才交给 vendored reader。
    未知扩展名仍抛固定文案的 :class:`NotImplementedError`。
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise NotImplementedError(f"暂不支持的格式: {ext}")

    if ext in _LEGACY_TEXT_EXTS:
        text = _read_text(p)
        if is_pd_format(text):
            tt, ii = _parse_pd(text)
            return _legacy_pattern(p, ext, text, tt, ii, "pd")

        vendor_key, _label = detect_vendor_format(p)
        if vendor_key in {"shimadzu_txt", "jade_txt", "gsas", "fp_dat", "xrdml"}:
            return _load_vendored(p, text=text, detected_key=vendor_key)

        try:
            tt, ii = _parse_two_column(text)
        except ValueError as exc:
            # 数据区损坏（例如中途缺列）保持旧异常；只有旧解析器确认根本没有
            # 数据点时才允许更宽容/定宽的 vendored reader 再识别一次。
            if "有效数据点不足 2 个" not in str(exc):
                raise
            return _load_vendored(p, text=text, detected_key=vendor_key)
        return _legacy_pattern(p, ext, text, tt, ii, "two_column")

    return _load_vendored(p)


def _legacy_pattern(
    path: Path,
    ext: str,
    text: str,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    layout: str,
) -> Pattern:
    """构造旧四格式 Pattern；字段和值保持 v1.5.0 契约。"""
    meta = {
        "path": str(path),
        "source_format": ext.lstrip("."),
        "layout": layout,
        "wavelength_anode": _guess_anode(text),
    }
    return Pattern(two_theta=two_theta, intensity=intensity, meta=meta)


def _load_vendored(
    path: Path,
    *,
    text: str | None = None,
    detected_key: str | None = None,
) -> Pattern:
    """读取新格式的 XRDData，并转换成 RutAna 的不可变 Pattern。"""
    try:
        key = detected_key or detect_vendor_format(path)[0]
        data = load_vendor_pattern(path)
    except MemoryError as exc:
        raise ValueError(f"谱图文件过大，内存不足，无法读取: {path}") from exc
    except (OSError, DataFormatError, ValueError):
        raise
    except Exception as exc:  # 边界统一成 GUI 可汇总展示的中文错误
        raise ValueError(f"谱图格式解析失败: {path.name}（{exc}）") from exc

    vendor_meta = dict(data.metadata)
    if key == "raw" and not bool(vendor_meta.get("axis_confident", True)):
        variant = vendor_meta.get("raw_variant", "未知 RAW 变体")
        raise ValueError(
            f"RAW 角度轴不可信（{variant}）：请先在仪器软件中导出为文本格式后再打开"
        )

    if text is None and path.suffix.lower() not in (_RAW_EXTS | _BINARY_CONTAINER_EXTS):
        try:
            text = _read_text(path)
        except (OSError, UnicodeError):
            text = ""
    anode = _vendor_anode(text or "", data.wavelength, vendor_meta)
    format_key = str(vendor_meta.get("format") or key)
    meta = dict(vendor_meta)
    meta.update({
        "path": str(path),
        "source_format": path.suffix.lower().lstrip("."),
        "layout": format_key,
        "wavelength_anode": anode,
        "format_key": format_key,
        "raw_variant": vendor_meta.get("raw_variant"),
        "num_points": int(data.two_theta.size),
    })
    if data.wavelength is not None:
        meta.setdefault("wavelength", float(data.wavelength))
    return Pattern(two_theta=data.two_theta, intensity=data.intensity, meta=meta)


def _vendor_anode(text: str, wavelength: float | None, meta: dict) -> str | None:
    """优先按 vendor 头信息推断靶材，失败后沿用旧文本猜测。"""
    raw_anode = str(meta.get("anode") or "").strip()
    if raw_anode:
        return raw_anode.title()

    inferred_wavelength = wavelength_from_text(text) if text else None
    if inferred_wavelength is not None:
        for symbol, candidate in ANODE_WAVELENGTHS.items():
            if abs(candidate - inferred_wavelength) <= 1e-5:
                return symbol.title()

    guessed = _guess_anode(text)
    if guessed is not None:
        return guessed

    # 二进制 RAW/显式 JSON 没有可查文本头时，才用解析器返回的波长反查。
    if wavelength is not None and (
        meta.get("wavelength") is not None or meta.get("format") == "json"
    ):
        for symbol, candidate in ANODE_WAVELENGTHS.items():
            if abs(candidate - float(wavelength)) <= 1e-4:
                return symbol.title()
    return None


def _guess_anode(text: str) -> str | None:
    """从文本头部猜测靶材（Cu/Fe/Co/Mo），猜不到返回 None。"""
    head = text[:4000].lower()
    for key, name in (("cuka", "Cu"), ("cu ka", "Cu"), ("fe ka", "Fe"),
                      ("co ka", "Co"), ("mo ka", "Mo")):
        if key in head:
            return name
    if "lambda=1.54" in head or "1.5406" in head:
        return "Cu"
    return None


def clip(p: Pattern, tmin: float, tmax: float) -> Pattern:
    """按 2θ 区间 [tmin, tmax] 布尔掩码裁剪（不含端外插值）。"""
    if tmin > tmax:
        raise ValueError(f"裁剪区间非法: tmin={tmin} > tmax={tmax}")
    mask = (p.two_theta >= tmin) & (p.two_theta <= tmax)
    if not bool(mask.any()):
        raise ValueError(f"裁剪区间 [{tmin}, {tmax}] 内无数据点")
    return Pattern(two_theta=p.two_theta[mask].copy(),
                   intensity=p.intensity[mask].copy(),
                   meta=dict(p.meta))


def estimate_step(p: Pattern) -> float:
    """中位数步长（度）。"""
    return p.step
