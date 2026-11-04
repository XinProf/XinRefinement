# vendored from PolyXRD-RutAna :: rutana/core/vendor/text_formats.py
"""
复制范围: PolyXRD-Converter src/polyxrd_converter/loader.py 中 detect_format、
各 _load_* 读谱函数、格式嗅探与波长常量（源自 PolyXRD-Converter，© 2026
PolyXRD Team，dual-licensed）。解析逻辑与数值常量未改动；仅去掉 i18n 与 GUI
依赖，并把模型/RAW 解析器 import 改为本 vendor 子包相对路径。

读取层: 格式识别 + 打开谱图
===========================
- :func:`detect_format` —— 按扩展名 + 文件头嗅探, 返回 ``(key, label)``
- :func:`load_pattern`  —— 打开任意受支持的谱图文件, 返回 :class:`XRDData`

文本类格式统一走"数值行抽取 + 列选择" (能容忍表头/注释/多列);
二进制 RAW 交给 :mod:`polyxrd_converter.raw_formats` 自动分流。
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Union

import numpy as np

from .model import XRDData
from .raw_formats import parse_raw

__all__ = ["DataFormatError", "detect_format", "load_pattern", "FORMAT_LABELS"]


class DataFormatError(ValueError):
    """数据格式不支持或解析失败。"""


_ERROR_MESSAGES: dict[str, str] = {
    "err.empty_file": "文件为空: {path}",
    "err.jade_report": "该文件是 Jade 物相识别报告，不是衍射谱图: {path}",
    "err.no_numeric": "未找到可用的数值谱图数据: {path}",
    "err.mdi_too_short": "MDI 文件内容过短: {path}",
    "err.mdi_head": "MDI 文件头缺少起始角或步长: {path}",
    "err.mdi_no_data": "MDI 文件没有足够的强度数据: {path}",
    "err.q_out_of_range": "Q 值超出波长 {wavelength} Å 可换算范围（最大参数 {vmax}）",
    "err.gsas_tof": "{name} 是 GSAS TOF 数据，横轴不是 2θ，暂不支持",
    "err.gsas_no_bank": "GSAS 文件未找到 BANK 记录: {path}",
    "err.gsas_eds_alt": "{name} 是 GSAS EDS/ALT 数据，横轴不是 2θ，暂不支持",
    "err.gsas_esd_fields": "GSAS ESD 的 BANK 记录缺少起始角/步长: {line}",
    "err.gsas_std_fields": "GSAS STD 的 BANK 记录缺少起始角/步长: {line}",
    "err.gsas_too_short": "GSAS 文件有效数据点不足 2 个: {path}",
    "err.fp_no_data": "FullProf DAT 文件没有足够的谱图数据: {path}",
    "err.rasx_no_member": "RASX 容器未找到 Profile 文本成员: {path}",
    "err.rasx_bad_zip": "RASX 容器损坏或不是 ZIP: {path}（{exc}）",
    "err.ras_no_marker": "RAS 文件缺少 *RAS_DATA_START 标记: {path}",
    "err.ras_no_rows": "RAS 文件没有足够的数据行: {path}",
    "err.xye_no_wavelength": "Q 模式文件 {name} 缺少 wavelength 注释，无法换算 2θ",
    "err.xye_no_rows": "XYE 文件没有足够的数据行: {path}",
    "err.chi_not_fit2d": "CHI 文件头未标明 2-theta 或 Q 模式: {path}",
    "err.chi_no_wavelength": "Q 模式 CHI 文件 {name} 缺少波长，无法换算 2θ",
    "err.chi_no_rows": "CHI 文件没有足够的数据行: {path}",
    "err.xrdml_xml_fail": "XRDML/XML 解析失败: {path}（{exc}）",
    "err.xrdml_no_data": "XRDML/XML 中未找到 2θ 与强度数组: {path}",
    "err.brml_no_xml": "BRML 容器中未找到 XML 数据: {path}",
    "err.brml_bad_zip": "BRML 容器损坏或不是 ZIP: {path}（{exc}）",
    "err.brml_xml_fail": "BRML 内部 XML 解析失败: {path}（{exc}）",
    "err.brml_no_data": "BRML 中未找到 2θ 与强度数组: {path}",
    "err.json_parse_fail": "谱图 JSON 解析失败: {path}（{exc}）",
    "err.json_not_pattern": "JSON 不含 two_theta 谱图字段: {path}",
    "err.file_missing": "文件不存在: {path}",
    "err.read_failed": "读取 {name} 失败: {exc}",
}


def tr(key: str, **kwargs) -> str:
    """替代 Converter GUI i18n 的本地中文错误格式化。"""
    return _ERROR_MESSAGES.get(key, key).format(**kwargs)


def _L(key: str) -> str:
    """RutAna 不展示 Converter 的格式译名，直接返回稳定内部 key。"""
    return key


#: 内部 key → i18n 文案 key。展示名统一经 ``i18n.fmt_label`` 翻译, 这里只存 key,
#: 避免同一份名称在两张表里漂移 (缺译文时回退到 fallback)。
FORMAT_LABELS: dict[str, str] = {
    "xy": "fmt.xy",
    "txt": "fmt.txt",
    "dat": "fmt.dat",
    "csv": "fmt.csv",
    "smz": "fmt.smz",
    "mdi": "fmt.mdi",
    "jade_txt": "fmt.jade_txt",
    "gsas": "fmt.gsas",
    "fp_dat": "fmt.fp_dat",
    "ras": "fmt.ras",
    "xye": "fmt.xye",
    "chi": "fmt.chi",
    "xrdml": "fmt.xrdml",
    "brml": "fmt.brml",
    "json": "fmt.json",
    "shimadzu_txt": "fmt.shimadzu_txt",
    "raw": "fmt.raw",
}

#: 文本类格式
_TEXT_KEYS = {"xy", "txt", "dat", "csv", "smz"}

#: 靶材 → Kα1 波长 (Å)。头里通常只留 "Cu" 之类记号, 靠它还原波长比在数值堆里猜可靠。
ANODE_WAVELENGTHS: dict[str, float] = {
    "CU": 1.5406,
    "CO": 1.78897,
    "CR": 2.28970,
    "FE": 1.93604,
    "MN": 2.10314,
    "NI": 1.65791,
    "MO": 0.70930,
    "AG": 0.55941,
}

#: 文本里出现这些词说明是岛津 ASCII 导出 (带完整实验参数头)
_SHIMADZU_MARKERS = ("target", "voltage", "<2theta>")

#: Jade/MDI 文本导出的第 2 行头: start step mode anode wavelength stop npoints
_JADE_HEAD_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+"
    r"([A-Za-z]{1,2})\s+(\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(\d+)\s*$"
)


def _jade_head(lines: list[str]) -> Optional[dict]:
    """识别 Jade/MDI 文本导出的两行头。

    第 2 个非空行形如 ``start step mode anode wavelength stop npoints``
    (实测样本: ``15  0.025  2 CU 1.540562  70  2201``)。命中且参数自洽时
    返回参数字典, 否则 None —— 宁可漏判, 也不把普通两列文本误读成单列强度。
    """
    ne = [ln for ln in lines if ln.strip()]
    if len(ne) < 3:
        return None
    m = _JADE_HEAD_RE.match(ne[1])
    if not m:
        return None
    try:
        start = float(m.group(1))
        step = float(m.group(2))
        anode = m.group(4).upper()
        wl = float(m.group(5))
        stop = float(m.group(6))
        npts = int(m.group(7))
    except ValueError:
        return None
    if anode not in ANODE_WAVELENGTHS:
        return None
    if abs(ANODE_WAVELENGTHS[anode] - wl) > 0.02:   # 波长必须与靶材记号吻合
        return None
    if not (0.0 <= start < stop <= 180.0):
        return None
    if not (1e-4 <= step <= 5.0):
        return None
    if not (10 <= npts <= 5_000_000):
        return None
    return {"start": start, "step": step, "stop": stop, "npoints": npts,
            "anode": anode, "wavelength": wl}


def wavelength_from_text(text: str) -> Optional[float]:
    """从文件头文本里找靶材记号, 返回 Kα1 波长 (找不到返回 None)。"""
    upper = text.upper()
    for symbol, wl in ANODE_WAVELENGTHS.items():
        if re.search(rf"(?<![A-Z]){symbol}(?![A-Z])", upper):
            return wl
    return None


# ----------------------------------------------------------------------
# 格式识别
# ----------------------------------------------------------------------

def detect_format(path: Union[str, Path]) -> tuple[str, str]:
    """按扩展名 + 文件头嗅探格式。

    Returns:
        ``(key, label)`` —— ``key`` 见 :data:`FORMAT_LABELS`; ``label`` 是按当前
        UI 语言翻译后的展示名 (经 :func:`~polyxrd_converter.i18n.fmt_label`)。
    """
    p = Path(path)
    ext = p.suffix.lower()
    try:
        head = p.open("rb").read(4096)
    except OSError:
        head = b""

    if ext == ".raw":
        return "raw", _L("raw")
    # 岛津 Shimadzu 私有容器的魔数决断: 它的 .raw/.org/.rsm/.rbg/.rk1/.rax/
    # .rlz/.rfi 共用同一结构 (见 raw_formats.ShimadzuRawParser), 靠扩展名分不干净。
    # 魔数极特异, 放最前面按魔数认, 不看扩展名。
    if head[:12] == b"Shimadzu XRD":
        return "raw", _L("raw")
    if ext == ".brml":
        return "brml", _L("brml")
    if ext in (".xrdml", ".xml"):
        return "xrdml", _L("xrdml")
    if ext == ".mdi":
        return "mdi", _L("mdi")
    if ext == ".json":
        return "json", _L("json")

    text_head = head.decode("utf-8", "ignore").lower()
    if any(m in text_head for m in _SHIMADZU_MARKERS):
        return "shimadzu_txt", _L("shimadzu_txt")
    if text_head.lstrip().startswith("<"):
        return "xrdml", _L("xrdml")

    # Jade/MDI 两行头文本导出 (Jade 的 .txt/.dat 常见): 头里带 start/step/靶材。
    # 必须在"按扩展名当两列文本"之前判掉, 否则单列定宽强度会被读成两列 → 假轴。
    if _jade_head(head.decode("utf-8", "ignore").splitlines()) is not None:
        return "jade_txt", _L("jade_txt")

    # --- GSAS-II 系文本格式 (gsas / fp_dat / ras / xye / chi) ---
    if ext == ".rasx":
        return "ras", _L("ras")
    if ext == ".ras" and head.decode("latin-1", "ignore").lstrip().startswith(
            "*RAS_DATA_START"):
        return "ras", _L("ras")
    head_lines_l1 = head.decode("latin-1", "ignore").splitlines()
    if ext in (".fxye", ".gsas", ".gda", ".gsa", ".gss") and _gsas_banks(head_lines_l1):
        return "gsas", _L("gsas")
    if ext in (".xye", ".qye"):
        return "xye", _L("xye")
    if ext in (".chi", ".qchi"):
        return "chi", _L("chi")
    if ext == ".dat":
        # .dat 四义: Jade 头 (上面已判) / GSAS BANK / FullProf 头 / 普通两列文本。
        if _gsas_banks(head_lines_l1):
            return "gsas", _L("gsas")
        # FullProf 判定需要全量数据做 stop 自洽校验 (头嗅探 4KB 不够), .dat 都是小文本
        try:
            full_lines = p.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        except OSError:
            full_lines = []
        if _fp_head(full_lines) is not None:
            return "fp_dat", _L("fp_dat")

    if ext in (".xy", ".txt", ".dat", ".csv", ".smz"):
        key = ext.lstrip(".")
        return key, _L(key)

    # 未知扩展名: 有数值就当两列文本
    return "txt", _L("txt")


# ----------------------------------------------------------------------
# 文本解析
# ----------------------------------------------------------------------

def _read_numeric_rows(path: Path) -> tuple[list[list[float]], list[str]]:
    """读取纯文本 → (数值行, 原始行)。跳过注释 / 空行 / 表头。"""
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = text.splitlines()
    if not lines:
        raise DataFormatError(tr("err.empty_file", path=str(path)))

    # 防御: 拒绝 JADE/PDF 物相识别报告 (不是衍射强度数据, 误读会产生虚假峰)
    if "phase id report" in "".join(lines[:40]).lower():
        raise DataFormatError(tr("err.jade_report", path=str(path)))

    rows: list[list[float]] = []
    for raw_line in lines:
        s = raw_line.strip()
        if not s or s.startswith(("#", "%", "//", ";", "!", "<", '"', "'")):
            continue
        soft = s.replace(",", " ").replace(";", " ").replace("\t", " ")
        parts = soft.split()
        vals: list[float] = []
        ok = True
        for tok in parts:
            try:
                vals.append(float(tok))
            except ValueError:
                ok = False
                break
        if ok and len(vals) >= 2:
            rows.append(vals)
    if not rows:
        raise DataFormatError(tr("err.no_numeric", path=str(path)))
    return rows, lines


def _pick_columns(rows: list[list[float]]) -> tuple[int, int]:
    """挑 (2θ 列, 强度列)。

    两列 → (0, 1); 多列 → x 取单调首列, y 取相邻差分之和最大者 (计数率列),
    避开常量列与与首列重复的列。
    """
    ncol = len(rows[0])
    if ncol <= 2:
        return 0, 1
    arr = np.asarray(rows, dtype=float)
    diffs = np.abs(np.diff(arr, axis=0)).sum(axis=0)
    cands = [j for j in range(1, ncol) if diffs[j] > 1e-9]
    if not cands:
        cands = list(range(1, ncol))
    return 0, max(cands, key=lambda j: diffs[j])


def _load_text(path: Path, key: str) -> XRDData:
    rows, lines = _read_numeric_rows(path)
    # Jade/MDI 两行头文本: 头里有 start/step, 数据是单列定宽强度, 不能按两列读。
    if _jade_head(lines) is not None:
        return _load_mdi(path, "jade_txt")
    xc, yc = _pick_columns(rows)
    arr = np.asarray(rows, dtype=float)
    head_text = "\n".join(lines[:40])
    wl = wavelength_from_text(head_text)
    return XRDData(
        two_theta=arr[:, xc],
        intensity=arr[:, yc],
        wavelength=wl or 1.5406,
        metadata={
            "format": key,
            "x_col": xc,
            "y_col": yc,
            "num_points": int(arr.shape[0]),
            "wavelength_source": "header" if wl else "default",
        },
    )


def _load_shimadzu_txt(path: Path) -> XRDData:
    """岛津 ASCII 导出 (带 target / voltage / sampling pitch 等参数头)。"""
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    meta: dict = {"instrument": "Shimadzu"}
    patterns = {
        "target": r"target\s*[:=]\s*(\S+)",
        "voltage": r"voltage\s*[:=]\s*([\d.]+)",
        "current": r"current\s*[:=]\s*([\d.]+)",
        "scan_start": r"scan range\s*[:=]\s*([\d.]+)",
        "scan_end": r"scan range\s*[:=]\s*[\d.]+\s*-\s*([\d.]+)",
        "step": r"(?:sampling\s+pitch|sampling\s+interval|step)\s*[:=]\s*([\d.]+)",
        "preset_time": r"(?:preset\s+time|counting\s+time)\s*[:=]\s*([\d.]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                meta[key] = float(m.group(1))
            except ValueError:
                meta[key] = m.group(1)

    wl = wavelength_from_text(text)
    rows, _ = _read_numeric_rows(path)
    xc, yc = _pick_columns(rows)
    arr = np.asarray(rows, dtype=float)
    return XRDData(
        two_theta=arr[:, xc],
        intensity=arr[:, yc],
        wavelength=wl or 1.5406,
        metadata={"format": "shimadzu_txt", "num_points": int(arr.shape[0]), **meta},
    )


def _load_mdi(path: Path, key: str = "mdi") -> XRDData:
    """MDI (Jade) 文本格式: 定宽整数强度, 头含 start/step/.../stop。

    实测坑: 该格式转换时可能丢掉**第一个**通道 (如 count=7250 却带 5.000→150.000
    的区间)。若按 start 起算整条谱会平移一个步长 (峰位全错 0.02°), 故当
    ``start + step*(n-1)`` 对不上头里的 stop 时, 改以 stop 反推 start。
    """
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise DataFormatError(tr("err.mdi_too_short", path=str(path)))

    head = lines[1]
    head_nums: list[float] = []
    for tok in head.split():
        try:
            head_nums.append(float(tok))
        except ValueError:
            continue
    if len(head_nums) < 2:
        raise DataFormatError(tr("err.mdi_head", path=str(path)))
    start, step = head_nums[0], head_nums[1]

    values: list[float] = []
    for ln in lines[2:]:
        for tok in ln.split():
            try:
                values.append(float(tok))
            except ValueError:
                continue
    if len(values) < 2:
        raise DataFormatError(tr("err.mdi_no_data", path=str(path)))
    intensity = np.asarray(values, dtype=float)
    n = len(intensity)

    if step > 0:
        want = start + step * (n - 1)
        span = step * max(n - 1, 1)
        cands = [c for c in head_nums[2:] if abs(c - want) <= 0.05 * span]
        if cands:
            stop = min(cands, key=lambda c: abs(c - want))
            if abs(start + step * (n - 1) - stop) > step / 2:
                start = stop - step * (n - 1)

    two_theta = start + step * np.arange(n, dtype=float)
    wl = wavelength_from_text(head)
    return XRDData(
        two_theta=two_theta,
        intensity=intensity,
        wavelength=wl or 1.5406,
        metadata={"format": key, "num_points": n},
    )


# ----------------------------------------------------------------------
# GSAS-II 系文本格式 (gsas / fp_dat / ras / xye / chi)
# ----------------------------------------------------------------------
# 格式知识参考 GSAS-II (UChicago Argonne, LLC 开源许可) 的对应 importer:
#   imports/G2pwd_fxye.py / G2pwd_FP.py / G2pwd_rigaku.py / G2pwd_xye.py。
# 按 GSAS-II 开源许可要求在此注明来源与修改: 本实现为按本项目架构与
# "数据保真"红线的重写裁剪 —— 与 GSAS-II 的有意差异:
#   1. 不把 ≤0 的强度清零 (保留存储原值, 背底扣除后的负强度是合法数据);
#   2. Q 模式 (qye/qchi) 不做 GSAS-II 的强度 ×100 (Fit2D 标度约定), 照原值转出;
#   3. TOF (TIME_MAP) 与能量色散 (EDS) 明确报错拒绝 —— 横轴不是 2θ, 绝不硬猜。
# ----------------------------------------------------------------------


def _sfloat_blank(s: str) -> float:
    """定宽字段转 float, 全空格按 0 (GSAS 定宽格式的格式定义, 非猜测)。"""
    s = s.strip()
    return float(s) if s else 0.0


def _gsas_banks(lines: list[str]) -> list[tuple[str, int]]:
    """扫描 GSAS 文件的 BANK 记录, 返回 [(BANK 行, 数据起始行号)]。

    与 GSAS-II 一致: 首行恒为标题注释; 第二行可选 ``INST ...``; ``#`` 为注释。
    """
    banks: list[tuple[str, int]] = []
    for i, ln in enumerate(lines):
        if i == 0 or ln.startswith("#"):
            continue
        if i == 1 and ln[:4].lower() == "inst":
            continue
        if ln[:4] == "BANK":
            banks.append((ln, i + 1))
    return banks


def _fp_head(lines: list[str]) -> Optional[dict]:
    """FullProf .dat 头判定 (宁可漏判不误判)。

    命中条件: 首个非注释行是 ``start step stop`` 三个数字 (范围合理), 且其后
    等列数的数值行总数 n 满足 ``start + step*(n-1) ≈ stop`` (差 ≤ 1 步长)。
    最后一条自洽校验是防误判的关键 —— 普通三列文本的第二列是强度,
    不可能当步长通过 1e-4~5° 的范围检查后再对上 stop。
    """
    got_c = False
    header_seen = False
    start = step = stop = 0.0
    data_lines: list[list[float]] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if not header_seen:
            if got_c:
                if "*/" in s:
                    got_c = False
                continue
            if s.startswith("/*"):
                # 单行 /* ... */ 不进入块注释态 (比 GSAS-II 参考实现更稳)
                if "*/" not in s[2:]:
                    got_c = True
                continue
            if s[0] in "'#!":
                continue
            if "lambda" in s.lower():
                continue                       # 波长行在头之前, 跳过
            toks = s.replace(",", " ").split()
            if len(toks) < 3:
                return None
            try:
                start, step, stop = float(toks[0]), float(toks[1]), float(toks[2])
            except ValueError:
                return None
            if not (0.0 <= start < 180.0 and 1e-4 <= step <= 5.0
                    and start < stop <= 180.0):
                return None
            header_seen = True
            continue
        toks = s.replace(",", " ").split()
        vals: list[float] = []
        for t in toks:
            try:
                vals.append(float(t))
            except ValueError:
                break                       # 数据区里的注释/杂行, 跳过
        if vals:
            data_lines.append(vals)
    if not header_seen or not data_lines:
        return None
    ncols = len(data_lines[0])
    if not (1 <= ncols <= 10) or any(len(v) != ncols for v in data_lines):
        return None
    n = len(data_lines) * ncols
    if abs(start + step * (n - 1) - stop) > step:
        return None
    return {"start": start, "step": step, "stop": stop}


def _q_to_two_theta(q: np.ndarray, wavelength: float) -> np.ndarray:
    """Q (Å⁻¹) → 2θ (度): 2θ = 2·asin(λQ/4π)。换算式与 GSAS-II 一致。"""
    arg = wavelength * np.asarray(q, dtype=float) / (4.0 * np.pi)
    if float(arg.max()) > 1.0:
        raise DataFormatError(
            tr("err.q_out_of_range", wavelength=wavelength, vmax=f"{arg.max():.3f}")
        )
    return 2.0 * np.degrees(np.arcsin(arg))


def _load_gsas(path: Path) -> XRDData:
    """GSAS 粉末数据 (.gsas/.fxye/.gda/.gsa/.gss, BANK 记录四种数据类型)。

    - FXYE: 每行 ``x(百分度) y esd`` 三列, x/100 → 度 (显式 x 列, 最可靠);
    - FXY:  每行 ``x(百分度) y`` 两列;
    - ESD:  定宽 80 列, 每 16 字符一组 = 8 字符 y + 8 字符 esd, x 由 BANK 的
      start/step (百分度) 计算重建;
    - STD:  定宽 80 列, 每 10 字符一组 = 2 字符归一计数 + 6 字符原始计数
      + 2 空格, x 同样由 BANK 重建 (强度存原始计数字段, 与 GSAS-II 相同)。
    多 BANK 取第一块 (本工具单谱定位); TOF/EDS 明确拒绝。
    """
    # latin-1 逐字节解码: ESD/STD 是定宽格式, 字节偏移即字符偏移
    text = path.read_bytes().decode("latin-1", errors="ignore")
    if "TIME_MAP" in text:
        raise DataFormatError(tr("err.gsas_tof", name=path.name))
    lines = text.splitlines()
    banks = _gsas_banks(lines)
    if not banks:
        raise DataFormatError(tr("err.gsas_no_bank", path=str(path)))
    bank_line, di = banks[0]
    if "EDS" in bank_line or "ALT" in bank_line:
        raise DataFormatError(tr("err.gsas_eds_alt", name=path.name))
    cons = bank_line.split()
    start = step = None
    if len(cons) >= 7:
        try:
            start = float(cons[5]) / 100.0
            step = float(cons[6]) / 100.0
        except ValueError:
            start = step = None

    xs: list[float] = []
    ys: list[float] = []
    j = 0
    if "FXYE" in bank_line or "FXY" in bank_line:
        for ln in lines[di:]:
            if ln[:4] == "BANK" or ln.startswith("#"):
                break
            parts = ln.split()
            if len(parts) < 2:
                continue
            xs.append(float(parts[0]) / 100.0)   # 百分度 → 度
            ys.append(float(parts[1]))
    elif "ESD" in bank_line:
        if start is None:
            raise DataFormatError(tr("err.gsas_esd_fields", line=bank_line.rstrip()))
        for ln in lines[di:]:
            if ln[:4] == "BANK" or ln.startswith("#"):
                break
            ln = ln.replace("\x1a", "").ljust(80)
            for i in range(0, 80, 16):
                if ln[i:i + 8].strip() == "":
                    break
                xs.append(start + step * j)
                ys.append(_sfloat_blank(ln[i:i + 8]))
                j += 1
    else:  # STD (缺省类型, 与 GSAS-II 的兜底一致)
        if start is None:
            raise DataFormatError(tr("err.gsas_std_fields", line=bank_line.rstrip()))
        for ln in lines[di:]:
            if ln[:4] == "BANK" or ln.startswith("#"):
                break
            ln = ln.replace("\x1a", "").ljust(80)
            for i in range(0, 80, 8):
                if ln[i:i + 10].strip() == "":
                    break
                xs.append(start + step * j)
                ys.append(_sfloat_blank(ln[i + 2:i + 8]))
                j += 1

    if len(xs) < 2:
        raise DataFormatError(tr("err.gsas_too_short", path=str(path)))
    bank_type = next((t for t in ("FXYE", "FXY", "ESD", "STD", "ALT") if t in bank_line),
                     "STD")
    return XRDData(
        two_theta=np.asarray(xs, dtype=float),
        intensity=np.asarray(ys, dtype=float),
        wavelength=1.5406,
        metadata={
            "format": "gsas",
            "bank_type": bank_type,
            "bank_line": bank_line.strip(),
            "num_banks": len(banks),
            "num_points": len(xs),
        },
    )


def _load_fp_dat(path: Path) -> XRDData:
    """FullProf .dat (1-10 列): 注释后首行 ``start step stop``, 之后每行 1-10 个
    强度值, x = start + N*step 递增到 stop; ``lambda λ`` 行给波长。
    参考: GSAS-II imports/G2pwd_FP.py。"""
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = text.splitlines()
    got_c = False
    start = step = stop_at = None
    wl: Optional[float] = None
    xs: list[float] = []
    ys: list[float] = []
    stopped = False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if start is None:
            if got_c:
                if "*/" in s:
                    got_c = False
                continue
            if s.startswith("/*"):
                if "*/" not in s[2:]:
                    got_c = True
                continue
            if s[0] in "'#!":
                continue
            toks = s.replace(",", " ").split()
            if "lambda" in s.lower() and len(toks) >= 2:
                try:
                    wl = float(toks[1])
                except ValueError:
                    pass
                continue
            if len(toks) < 3:
                continue                       # 头前杂行 (GSAS-II 容忍)
            try:
                start, step, stop_at = float(toks[0]), float(toks[1]), float(toks[2])
            except ValueError:
                continue
            continue
        if stopped:
            break
        toks = s.replace(",", " ").split()
        row: list[float] = []
        for t in toks:
            try:
                row.append(float(t))
            except ValueError:
                break                          # 数据区混入注释行, 跳过该行
        for f in row:
            x = start + step * len(xs)
            xs.append(x)
            ys.append(f)
            if x >= stop_at:                   # 到 stop 即止 (FullProf 约定)
                stopped = True
                break
    if start is None or len(xs) < 2:
        raise DataFormatError(tr("err.fp_no_data", path=str(path)))
    return XRDData(
        two_theta=np.asarray(xs, dtype=float),
        intensity=np.asarray(ys, dtype=float),
        wavelength=wl or 1.5406,
        metadata={
            "format": "fp_dat",
            "start": start, "step": step, "stop": stop_at,
            "num_points": len(xs),
        },
    )


def _load_ras(path: Path) -> XRDData:
    """理学 Rigaku .ras (文本) / .rasx (zip 容器)。

    参考: GSAS-II imports/G2pwd_rigaku.py。.ras 以 ``*RAS_DATA_START`` 开头,
    数据在 ``*RAS_INT_START`` ... ``*RAS_INT_END`` 之间, 每行 ``2θ 强度``;
    多扫描块取第一块。.rasx 是 zip, 直接从内存读 Data*/Profile*.txt 成员
    (不像 GSAS-II 那样解压落盘), 并从测量条件 XML 里尽力找波长。
    """
    import zipfile

    wl: Optional[float] = None
    container = "ras"
    if path.suffix.lower() == ".rasx":
        container = "rasx"
        try:
            with zipfile.ZipFile(str(path)) as zf:
                names = zf.namelist()
                prof = next(
                    (n for n in names
                     if n.lower().endswith(".txt") and "profile" in n.lower()), None)
                if prof is None:
                    raise DataFormatError(tr("err.rasx_no_member", path=str(path)))
                text = zf.read(prof).decode("utf-8-sig", "ignore")
                xml_name = next((n for n in names if n.lower().endswith(".xml")), None)
                if xml_name:
                    xml_text = zf.read(xml_name).decode("utf-8-sig", "ignore")
                    m = re.search(r"(?i)wavelength\D{0,40}?(\d+\.\d+)", xml_text)
                    if m:
                        wl = float(m.group(1))
        except zipfile.BadZipFile as exc:
            raise DataFormatError(tr("err.rasx_bad_zip", path=str(path), exc=exc)) from exc
    else:
        text = path.read_bytes().decode("latin-1", errors="ignore")
        if not text.lstrip().startswith("*RAS_DATA_START"):
            raise DataFormatError(tr("err.ras_no_marker", path=str(path)))
        m = re.search(r"(?i)wavelength\D{0,40}?(\d+\.\d+)", text)
        if m:
            wl = float(m.group(1))
        in_block = False
        kept: list[str] = []
        for ln in text.splitlines():
            s = ln.strip()
            if s == "*RAS_INT_START":
                in_block = True
                continue
            if s == "*RAS_INT_END":
                break                          # 只取第一个扫描块
            if in_block:
                kept.append(ln)
        text = "\n".join(kept)

    xs: list[float] = []
    ys: list[float] = []
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) < 2:
            continue
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            continue
    if len(xs) < 2:
        raise DataFormatError(tr("err.ras_no_rows", path=str(path)))
    return XRDData(
        two_theta=np.asarray(xs, dtype=float),
        intensity=np.asarray(ys, dtype=float),
        wavelength=wl or 1.5406,
        metadata={"format": "ras", "container": container, "num_points": len(xs)},
    )


def _load_xye(path: Path) -> XRDData:
    """Topas .xye/.qye: ``#``/``!``/``'`` 注释、``/* */`` 块、``TITLE`` 行、
    首行 ``xydata`` (FullProf 头) 均跳过; 数据 2-3 列 (x y [esd], esd 忽略)。
    .qye 的 x 是 Q (Å⁻¹), 必须有 ``#wavelength λ`` 注释行才能换算 2θ。
    参考: GSAS-II imports/G2pwd_xye.py (换算式一致; 强度不 ×100, 见节注)。"""
    is_q = path.suffix.lower() == ".qye"
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = text.splitlines()
    wl: Optional[float] = None
    if is_q:
        for ln in lines[:60]:
            if "wavelength" not in ln.lower():
                continue
            toks = ln.replace(",", " ").split()
            for k, t in enumerate(toks):
                if "wavelength" in t.lower() and k + 1 < len(toks):
                    try:
                        wl = float(toks[k + 1])
                    except ValueError:
                        pass
                    break
            if wl:
                break
        if wl is None:
            raise DataFormatError(tr("err.xye_no_wavelength", name=path.name))

    got_c = False
    xs: list[float] = []
    ys: list[float] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        if got_c:
            if "*/" in s:
                got_c = False
            continue
        if s.startswith("/*"):
            if "*/" not in s[2:]:
                got_c = True
            continue
        if s[0] in "'#!":
            continue
        if i == 0 and "xydata" in s.lower():
            continue
        if s.upper().startswith("TITLE"):
            continue
        parts = s.replace(",", " ").replace(";", " ").split()
        if len(parts) < 2:
            continue
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            continue
    if len(xs) < 2:
        raise DataFormatError(tr("err.xye_no_rows", path=str(path)))
    two_theta = np.asarray(xs, dtype=float)
    intensity = np.asarray(ys, dtype=float)
    if is_q:
        two_theta = _q_to_two_theta(two_theta, wl)
    return XRDData(
        two_theta=two_theta,
        intensity=intensity,
        wavelength=wl or 1.5406,
        metadata={"format": "xye", "q_mode": is_q, "num_points": len(xs)},
    )


def _load_chi(path: Path) -> XRDData:
    """Fit2D .chi/.qchi: 头 4 行里 ``2-theta``/``chi_2theta`` 记 2θ 模式,
    ``q`` 行 (如 ``q_A^-1 1.5406``) 记 Q 模式并给波长; 数据为两列。
    pyFAI 简化头 (前几行 '#' 注释) 兼容。参考: GSAS-II imports/G2pwd_xye.py。"""
    is_q_ext = path.suffix.lower() == ".qchi"
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = text.splitlines()
    mode = None
    wl: Optional[float] = None
    for ln in lines[:6]:
        low = ln.lower()
        if "2-theta" in low or "chi_2theta" in low:
            mode = "2th"
            break
        if low.startswith("q") or " q " in low:
            for t in ln.split()[1:]:
                try:
                    wl = float(t)
                    break
                except ValueError:
                    continue
            if wl:
                mode = "q"
                break
    if mode is None:
        raise DataFormatError(tr("err.chi_not_fit2d", path=str(path)))
    if mode == "q" and wl is None:
        raise DataFormatError(tr("err.chi_no_wavelength", name=path.name))
    xs: list[float] = []
    ys: list[float] = []
    # 数据行 = 全文件里"恰好两列数值"的行: Fit2D 标准头 4 行与 pyFAI 简化头
    #'#' 注释都天然不满足两列数值, 因此头行数不必硬编码 (pyFAI 头只有 2 行,
    # 硬编码 lines[4:] 会丢前两个数据点 —— oracle 对拍时踩过)。
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) != 2:
            continue
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            continue
    if len(xs) < 2:
        raise DataFormatError(tr("err.chi_no_rows", path=str(path)))
    two_theta = np.asarray(xs, dtype=float)
    if mode == "q":
        two_theta = _q_to_two_theta(two_theta, wl)
    return XRDData(
        two_theta=two_theta,
        intensity=np.asarray(ys, dtype=float),
        wavelength=wl or 1.5406,
        metadata={"format": "chi", "mode": mode, "num_points": len(xs)},
    )


# ----------------------------------------------------------------------
# XML 解析 (xrdml / brml)
# ----------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _text_numbers(text: Optional[str]) -> list[float]:
    if not text:
        return []
    out: list[float] = []
    for tok in text.split():
        try:
            out.append(float(tok))
        except ValueError:
            return []
    return out


def _xml_arrays(root: ET.Element):
    """从 XML 树里取 (2θ, 强度)。

    兼容三种写法:
      1. ``<positions axis="2Theta"><startPosition/><endPosition/></positions>``
         + ``<intensities>`` (Bruker XRDML 标准写法, 按强度个数线性展开)
      2. ``<positions>`` 的文本直接是 2θ 列表
      3. PANalytical 风格: ``<positions>`` 下挂 ``<axis axisName="2Theta">``
    """
    two_theta = intensity = None
    start_pos = end_pos = None

    for element in root.iter():
        tag = _local(element.tag)
        if tag == "positions":
            vals = _text_numbers(element.text)
            if len(vals) >= 2:
                two_theta = np.asarray(vals, dtype=float)
                continue
            for child in element.iter():
                ctag = _local(child.tag)
                if ctag == "startPosition":
                    start_pos = _text_numbers(child.text)
                    start_pos = start_pos[0] if start_pos else None
                elif ctag == "endPosition":
                    end_pos = _text_numbers(child.text)
                    end_pos = end_pos[0] if end_pos else None
                elif ctag == "axis" and child.get("axisName") == "2Theta":
                    vals = _text_numbers(child.text)
                    if len(vals) >= 2:
                        two_theta = np.asarray(vals, dtype=float)
        elif tag in ("intensities", "counts"):
            vals = _text_numbers(element.text)
            if len(vals) >= 2:
                intensity = np.asarray(vals, dtype=float)

    # 只有 start/end + 强度个数 → 等间距展开
    if two_theta is None and intensity is not None and start_pos is not None \
            and end_pos is not None and len(intensity) >= 2:
        two_theta = np.linspace(float(start_pos), float(end_pos), len(intensity))

    return two_theta, intensity


def _load_xrdml(path: Path) -> XRDData:
    """Bruker/PANalytical XRDML (XML)。"""
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise DataFormatError(tr("err.xrdml_xml_fail", path=str(path), exc=exc)) from exc

    two_theta, intensity = _xml_arrays(root)

    # 备选: 把所有叶子文本里的数字按前后半分开 (老式/简化 XML)。
    # ⚠ 必须加"前半单调递增"的守卫 —— 2θ 轴一定单调, 否则会把强度序列劈成
    #   两半造出一条假谱 (本工具开发中就踩过: 7251 点被劈成 3626 点)。
    if two_theta is None or intensity is None:
        numbers: list[float] = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                numbers.extend(_text_numbers(elem.text))
        if len(numbers) >= 6:
            half = len(numbers) // 2
            first = numbers[:half]
            if all(b > a for a, b in zip(first, first[1:])):
                two_theta = np.array(first)
                intensity = np.array(numbers[half:half * 2])

    if two_theta is None or intensity is None:
        raise DataFormatError(tr("err.xrdml_no_data", path=str(path)))

    m = min(len(two_theta), len(intensity))
    return XRDData(
        two_theta=two_theta[:m],
        intensity=intensity[:m],
        wavelength=1.5406,
        metadata={"format": "xrdml", "num_points": int(m)},
    )


def _load_brml(path: Path) -> XRDData:
    """Bruker BRML (ZIP 容器 + XML)。"""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            names = zf.namelist()
            data_files = [f for f in names if "data" in f.lower() and f.lower().endswith(".xml")]
            if not data_files:
                data_files = [f for f in names if f.lower().endswith(".xml")]
            if not data_files:
                raise DataFormatError(tr("err.brml_no_xml", path=str(path)))
            xml_text = zf.read(data_files[0]).decode("utf-8-sig", "ignore")
    except zipfile.BadZipFile as exc:
        raise DataFormatError(tr("err.brml_bad_zip", path=str(path), exc=exc)) from exc

    try:
        root = ET.parse(io.StringIO(xml_text)).getroot()
    except ET.ParseError as exc:
        raise DataFormatError(tr("err.brml_xml_fail", path=str(path), exc=exc)) from exc

    two_theta, intensity = _xml_arrays(root)
    if two_theta is None or intensity is None:
        # BRML 常用 <Datum><Positions>/<Counts> 结构
        pos, cnt = [], []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
            txt = (elem.text or "").strip()
            if not txt:
                continue
            vals = []
            for tok in txt.split():
                try:
                    vals.append(float(tok))
                except ValueError:
                    vals = []
                    break
            if not vals:
                continue
            if "position" in tag or "2theta" in tag:
                if len(vals) > len(pos):
                    pos = vals
            elif "count" in tag or "intensit" in tag:
                if len(vals) > len(cnt):
                    cnt = vals
        two_theta = np.array(pos) if pos else None
        intensity = np.array(cnt) if cnt else None

    if two_theta is None or intensity is None:
        raise DataFormatError(tr("err.brml_no_data", path=str(path)))

    m = min(len(two_theta), len(intensity))
    return XRDData(
        two_theta=two_theta[:m],
        intensity=intensity[:m],
        wavelength=1.5406,
        metadata={"format": "brml", "num_points": int(m)},
    )


def _load_json(path: Path) -> XRDData:
    """本工具导出的谱图 JSON (含 two_theta / intensity 字段)。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataFormatError(tr("err.json_parse_fail", path=str(path), exc=exc)) from exc
    if not isinstance(payload, dict) or "two_theta" not in payload:
        raise DataFormatError(tr("err.json_not_pattern", path=str(path)))
    data = XRDData.from_dict(payload)
    data.metadata.setdefault("format", "json")
    return data


# ----------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------

def load_pattern(
    path: Union[str, Path],
    wavelength: Optional[float] = None,
    manual_axis: Optional[tuple[float, float]] = None,
) -> XRDData:
    """打开任意受支持的谱图文件。

    Args:
        path: 文件路径
        wavelength: 显式波长 (None → 从头识别或默认 Cu Kα1)
        manual_axis: ``(起始 2θ, 步长)`` —— 仅在 RAW 角度轴不可信时使用

    Raises:
        FileNotFoundError: 文件不存在
        DataFormatError: 格式不支持 / 解析失败
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(tr("err.file_missing", path=str(p)))

    key, label = detect_format(p)
    try:
        if key == "raw":
            result = parse_raw(p.read_bytes(), p)
            data = XRDData(
                two_theta=result.two_theta,
                intensity=result.intensity,
                # 波长优先级: 调用方显式指定 > 解析器从文件头读到的 > 默认 Cu Kα1
                wavelength=wavelength or result.meta.get("wavelength") or 1.5406,
                metadata={
                    "format": "raw",
                    "raw_variant": result.format_key,
                    "raw_variant_label": result.format_label,
                    "axis_confident": result.axis_confident,
                    "num_points": int(result.intensity.size),
                    **result.meta,
                },
            )
            if not result.axis_confident:
                if manual_axis is not None:
                    start, step = manual_axis
                    data.two_theta = float(start) + float(step) * np.arange(
                        len(data), dtype=float
                    )
                    data.metadata["axis_confident"] = True
                    data.metadata["axis_source"] = "manual"
                else:
                    data.metadata["axis_source"] = "unknown"
            return data

        if key in ("mdi", "jade_txt"):
            data = _load_mdi(p, key)
        elif key == "gsas":
            data = _load_gsas(p)
        elif key == "fp_dat":
            data = _load_fp_dat(p)
        elif key == "ras":
            data = _load_ras(p)
        elif key == "xye":
            data = _load_xye(p)
        elif key == "chi":
            data = _load_chi(p)
        elif key == "xrdml":
            data = _load_xrdml(p)
        elif key == "brml":
            data = _load_brml(p)
        elif key == "json":
            data = _load_json(p)
        elif key == "shimadzu_txt":
            data = _load_shimadzu_txt(p)
        else:
            data = _load_text(p, key)
    except (DataFormatError, FileNotFoundError):
        raise
    except Exception as exc:  # noqa: BLE001 - 统一成 DataFormatError 便于 GUI 展示
        raise DataFormatError(tr("err.read_failed", name=p.name, exc=exc)) from exc

    if wavelength is not None:
        data.wavelength = wavelength
    data.metadata.setdefault("format", key)
    data.metadata["format_label"] = label
    data.metadata.setdefault("source_file", str(p))
    return data
