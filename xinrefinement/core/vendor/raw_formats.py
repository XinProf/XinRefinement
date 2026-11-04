# vendored from PolyXRD-RutAna :: rutana/core/vendor/raw_formats.py
"""
复制范围: 完整复制 PolyXRD-Converter src/polyxrd_converter/raw_formats.py
（源自 PolyXRD-Converter，© 2026 PolyXRD Team，dual-licensed）。解析逻辑与数值
常量未改动；仅把运行时 ANODE_WAVELENGTHS import 改为本 vendor 子包相对路径。

RAW 二进制格式的自动识别与解析
===============================
不同厂商的 ``.raw`` 是**完全不同的二进制格式**, 只能靠文件头魔数 (magic) 分流。
本模块把每种变体做成一个独立的 :class:`RawParser`, 统一注册到 :data:`PARSERS`,
新增一种格式只需写一个类并追加到列表末尾 (顺序即优先级)。

目前已实现/已用真实样本验证的变体
--------------------------------
======================  ==================  ==================================
魔数 / 特征              格式                验证来源
======================  ==================  ==================================
``FI\\x00\\x00``          Rigaku RINT 二进制    XRData/csuHJW 40+ 个样本, 与同名
                                            .txt 峰位/点数逐点一致
``RAW2``                 Scintag RAW2        XRData/IUCr 40+ 个样本, 与同名
                                            .mdi/.dat 逐点一致
``RAW1.01``/``RAW ``     Bruker/Siemens v1   XRData/csuHJW/data035 (结构已逆向,
                                            角度轴需人工确认, 见 parser 注释)
``Shimadzu XRD``         岛津 XRD 私有容器     XRData/Shimadzu Data 72 个 .RAW
                                            (int32 强度 / 变长头), 与同目录
                                            Shimadzu ASCII 导出 .txt 逐点一致
======================  ==================  ==================================

新增一种格式: 写一个 :class:`RawParser` 子类并追加到 :data:`PARSERS` 末尾
(兜底 parser 必须留在最后)。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

#: 强度合理区间 (超出即认为不是强度, 用于定位数据段)
_INT_LO, _INT_HI = 0.0, 1.0e8


@dataclass
class RawParseResult:
    """一个 RAW 变体的解析结果。"""

    two_theta: np.ndarray
    intensity: np.ndarray
    format_key: str
    format_label: str
    axis_confident: bool = True        # 角度轴是否可信 (False → GUI 提示人工指定)
    truncated: bool = False            # 文件被截断 (点数少于头里声明值)
    meta: dict = field(default_factory=dict)


class RawParser:
    """RAW 变体解析器基类。"""

    key: str = "raw"
    label: str = "RAW"

    def matches(self, raw: bytes) -> bool:  # pragma: no cover - 抽象
        raise NotImplementedError

    def parse(self, raw: bytes, path: Path) -> RawParseResult:  # pragma: no cover
        raise NotImplementedError

    # -- 工具 ---------------------------------------------------------

    @staticmethod
    def _plausible(values: np.ndarray) -> bool:
        return bool(
            values.size > 0
            and np.all(np.isfinite(values))
            and np.all(values >= _INT_LO)
            and np.all(values <= _INT_HI)
        )

    @staticmethod
    def _f32(raw: bytes, off: int) -> Optional[float]:
        try:
            return struct.unpack_from("<f", raw, off)[0]
        except struct.error:
            return None

    @staticmethod
    def _i32(raw: bytes, off: int) -> Optional[int]:
        try:
            return struct.unpack_from("<i", raw, off)[0]
        except struct.error:
            return None


# ======================================================================
# 1) Rigaku RINT 二进制 (魔数 b"FI\x00\x00")
# ======================================================================
# 实测结构 (csuHJW 教学集, 多台 Rigaku 仪器输出一致):
#   0x000 : 4 字节魔数 b"FI\x00\x00"
#   0xB92 : 三个连续 little-endian float32 = (起始 2θ, 终止 2θ, 步长)
#   数据段: 文件末尾 n 个 little-endian float32 强度,
#           n = round((end - start) / step); 即"定长 3162 字节头 + 变长 float32 强度"。
#   头里还有 IncidentSlitBox / ReceivingSlitBox 之类 Rigaku 术语字符串。
#   已用同目录 .txt 交叉验证 (铜 fcc 峰 43.3/50.4/74.1/89.9/95.1° 精确命中)。
class RigakuRintParser(RawParser):
    key = "rigaku_raw"
    label = "Rigaku RAW (RINT/SmartLab, FI)"
    _MAGIC = b"FI\x00\x00"
    _AXIS_OFF = 0xB92       # start, end, step (3 × float32)
    _HDR_FIXED = 0xC5A      # 3162: 轴参数不可信时的退化兜底头长

    def matches(self, raw: bytes) -> bool:
        return raw[:4] == self._MAGIC

    def parse(self, raw: bytes, path: Path) -> RawParseResult:
        if len(raw) < self._AXIS_OFF + 12:
            raise ValueError(f"Rigaku RAW 文件过短, 无法读取轴参数: {path}")
        start = struct.unpack_from("<f", raw, self._AXIS_OFF)[0]
        end = struct.unpack_from("<f", raw, self._AXIS_OFF + 4)[0]
        step = struct.unpack_from("<f", raw, self._AXIS_OFF + 8)[0]

        # 两个互相独立的"点数"证据:
        #   n_axis —— 由头里的 (end-start)/step 推出
        #   n_fixed —— 由"定长 3162 字节头"推出
        # 两者吻合说明头里的轴参数确实描述了这段数据; 否则只能退回定长头,
        # 并明确标记角度轴不可信 (不肯猜)。
        n_fixed = (len(raw) - self._HDR_FIXED) // 4
        n_axis = int(round((end - start) / step)) if step > 0 else 0
        off_axis = len(raw) - n_axis * 4
        # 头长 3162 不是 4 的倍数 (数据段按字节切片, 不需要对齐), 故不做 4 对齐检查
        axis_readable = (
            n_axis >= 2 and 0 < step <= 2.0 and 0.0 <= start < end and off_axis >= 0
        )
        consistent = axis_readable and abs(n_axis - n_fixed) <= 1.5
        axis_normal = axis_readable and end < 180.0

        notes: list[str] = []
        if axis_readable and (consistent or axis_normal):
            n, offset = n_axis, off_axis
            if not axis_normal:
                notes.append(f"头中 2θ 上限 {end:.1f}° 超出 180°, 建议人工核对")
        else:
            n, offset = n_fixed, self._HDR_FIXED
        if n < 2:
            raise ValueError(f"Rigaku RAW 数据段过短 (n={n}): {path}")

        intensity = np.frombuffer(raw[offset:offset + n * 4], dtype="<f4").astype(float)
        # 头里的 float32 有精度噪声: 0.02 会读成 0.0199999995, 乘上几千个序号后
        # 累积漂移可达 3e-6° (末点 150.000 变 149.999997)。用 8 位有效数字归一。
        start = float(f"{start:.8g}")
        step = float(f"{step:.8g}")
        two_theta = start + step * np.arange(n, dtype=float)
        return RawParseResult(
            two_theta=two_theta,
            intensity=intensity,
            format_key=self.key,
            format_label=self.label,
            axis_confident=axis_normal,
            meta={
                "raw_header_len": offset,
                "instrument": "Rigaku",
                "axis_note": "; ".join(notes),
            },
        )


# ======================================================================
# 2) Scintag RAW2 (魔数 b"RAW2")
# ======================================================================
# 实测结构 (XRData/IUCr, test_xrd/geshi):
#   0x000 : 4 字节魔数 b"RAW2", 紧跟 4 字节 (0x01 00 00 00), 之后是样品名 ASCII
#   0x102 : int16 LE 点数 n (与文件长度互校验: 头长 = len - 4n)
#   0x10C : float32 LE 步长
#   0x110 : float32 LE 起始 2θ
#   数据段: 头之后 n 个 little-endian float32 强度
#   与同名 .mdi/.dat 交叉验证点数一致 (geshi 4-1: 7251 点 / 5.0–150.0°)
class ScintagRaw2Parser(RawParser):
    key = "scintag_raw2"
    label = "Scintag RAW2"
    _MAGIC = b"RAW2"
    _COUNT_OFF = 0x102
    _STEP_OFF = 0x10C
    _START_OFF = 0x110
    _HDR_LEN = 316

    def matches(self, raw: bytes) -> bool:
        return raw[:4] == self._MAGIC

    @classmethod
    def _axis(cls, raw: bytes):
        """取 (start, step)。定长偏移优先, 失败再扫相邻 float32 对。"""
        def _f(off: int):
            try:
                return struct.unpack_from("<f", raw, off)[0]
            except struct.error:
                return None

        step, start = _f(cls._STEP_OFF), _f(cls._START_OFF)
        ok = (
            step is not None and start is not None
            and math.isfinite(step) and math.isfinite(start)
            and 0.0 < step <= 1.0 and 0.0 <= start < 180.0
        )
        if not ok:
            step = start = None
            for off in range(64, max(72, min(len(raw) - 8, 4096)), 4):
                s, t = _f(off), _f(off + 4)
                if s is None or t is None:
                    continue
                if not (math.isfinite(s) and math.isfinite(t)):
                    continue
                if 0.001 <= s <= 0.5 and 0.1 <= t < 90.0:
                    step, start = s, t
                    break
        if step is None:
            return None, None
        # 抹掉 float32 噪声 (同 Rigaku parser 的理由)
        return float(f"{start:.8g}"), float(f"{step:.8g}")

    def parse(self, raw: bytes, path: Path) -> RawParseResult:
        offset, n = None, 0
        if len(raw) >= self._COUNT_OFF + 2:
            n_hdr = struct.unpack_from("<h", raw, self._COUNT_OFF)[0]
            cand = len(raw) - n_hdr * 4
            if n_hdr >= 16 and 64 <= cand <= 4096:
                offset, n = cand, n_hdr
        if offset is None:
            offset = self._HDR_LEN
            n = (len(raw) - offset) // 4
        if n < 2:
            raise ValueError(f"RAW2 数据段过短: {path}")

        intensity = np.frombuffer(raw[offset:offset + n * 4], dtype="<f4").astype(float)
        start, step = self._axis(raw)
        if start is None:
            raise ValueError(f"RAW2 文件头中未找到可信的起始 2θ / 步长: {path}")
        two_theta = start + step * np.arange(n, dtype=float)

        # 样品名 (魔数后 4 字节起, 定长 32 字节 ASCII)
        name = raw[8:40].split(b"\x00")[0].decode("latin-1", "ignore").strip()
        return RawParseResult(
            two_theta=two_theta,
            intensity=intensity,
            format_key=self.key,
            format_label=self.label,
            axis_confident=True,
            meta={"raw_header_len": offset, "sample_name": name},
        )


# ======================================================================
# 3) Bruker/Siemens RAW v1 (魔数 b"RAW1.01" / b"RAW ")
# ======================================================================
# 结构 (由 XRData/csuHJW/data035 逆向):
#   0x000 : ASCII "RAW1.01\\0", 其后 int32 = 区间数 / 版本, 再后是日期、时间、
#           用户名、国家等定长字符串
#   0x07C : 每个"区间记录"定长 892 字节, 连续存放 (data035 里 10 条记录内容完全
#           相同, 相当于为多区间预留的定长区), 记录内含点数、波长族、2θ 范围、
#           步长、计数时间等字段
#   末尾  : n 个 little-endian float32 强度 (n 由记录里的点数字段给出)
#
# ⚠ data035 是"残余应力/窄区间"导出: 记录里的 (10.0, 80.0, 0.494) 与本段
#   147 点推不出自洽的步长, 所以本 parser **不硬猜** —— 数据可靠地取出来,
#   角度轴不可信时把 ``axis_confident`` 置 False, 由 GUI 提示用户手工指定。
class BrukerRawV1Parser(RawParser):
    key = "bruker_raw_v1"
    label = "Bruker/Siemens RAW v1"
    _MAGICS = (b"RAW1.01", b"RAW1.00", b"RAW ")

    def matches(self, raw: bytes) -> bool:
        return any(raw.startswith(m) for m in self._MAGICS)

    # -- 数据段定位 ----------------------------------------------------

    def _data_block(self, raw: bytes):
        """返回 (offset, n)。优先用文件头声明的点数, 再用"最长可信后缀"兜底。"""
        size = len(raw)
        # 1) 头里声明的点数: 取所有 int32 候选中最大的、能使末尾 4n 字节全可信者
        best = None
        for off in range(0, min(size, 0x4000) - 4, 4):
            n = self._i32(raw, off)
            if n is None or n < 16 or n * 4 > size:
                continue
            if self._plausible(np.frombuffer(raw[size - n * 4:], dtype="<f4")):
                if best is None or n > best:
                    best = n
        if best is not None:
            return size - best * 4, best

        # 2) 兜底: 最长可信后缀, 并裁掉头部整段 0.0 (属于头部填充, 不是谱图)
        arr = np.frombuffer(raw[: size // 4 * 4], dtype="<f4")
        start = len(arr)
        while start > 0 and self._plausible(arr[start - 1:start]):
            start -= 1
        while start < len(arr) and arr[start] == 0.0:
            start += 1
        n = len(arr) - start
        if n < 16:
            raise ValueError("Bruker RAW v1: 未能定位强度数据段")
        return start * 4, n

    # -- 角度轴 --------------------------------------------------------

    def _axis(self, raw: bytes, n: int):
        """在头部扫描自洽的 (start, step)。找不到返回 None。

        判据要"紧": 步长须在 0.005~0.5 的真实衍射步长区间, 跨度至少 1°, 末端
        不得越过 180°, 且 ``start + step*(n-1)`` 要能命中头里的另一个浮点数
        (容差 <= 半个步长)。松判据会把头部噪声配成 (0.0, 0.1) 这种假轴。
        """
        cands: set[float] = set()
        for off in range(0, min(len(raw), 0x4000) - 4, 4):
            v = self._f32(raw, off)
            if v is None or not math.isfinite(v):
                continue
            if 0.0 <= v <= 180.0:
                cands.add(round(v, 8))
        uniq = sorted(cands)

        best = None
        for start in uniq:
            for step in uniq:
                if not (0.005 <= step <= 0.5):
                    continue
                span = step * (n - 1)
                if span < 1.0:
                    continue
                end = start + span
                if end > 180.0:
                    continue
                tol = max(0.005, step * 0.5)
                if any(abs(end - c) <= tol for c in uniq):
                    # 优先"跨度更大 + 步长更接近常规值"的解, 避免拾取退化组合
                    score = (span, -abs(step - 0.02))
                    if best is None or score > best[0]:
                        best = (score, start, step, end)
        if best is None:
            return None
        return best[1], best[2], best[3]

    def parse(self, raw: bytes, path: Path) -> RawParseResult:
        offset, n = self._data_block(raw)
        intensity = np.frombuffer(raw[offset:offset + n * 4], dtype="<f4").astype(float)

        axis = self._axis(raw, n)
        meta = {"raw_header_len": offset, "declared_points": n}
        if axis is not None:
            start, step, _end = axis
            two_theta = start + step * np.arange(n, dtype=float)
            confident = True
        else:
            # 数据可取但角度轴读不出来 —— 不猜, 用点序号占位并标记不可信
            two_theta = np.arange(n, dtype=float)
            confident = False

        # 定长字符串头里的日期/用户名 (仅作元数据展示)
        head = raw[:0x7C].split(b"\x00")
        text = [t.decode("latin-1", "ignore").strip() for t in head if len(t) >= 6]
        if text:
            meta["comment"] = " | ".join(text[:3])

        return RawParseResult(
            two_theta=two_theta,
            intensity=intensity,
            format_key=self.key,
            format_label=self.label,
            axis_confident=confident,
            meta=meta,
        )


# ======================================================================
# 4) 岛津 (Shimadzu) XRD 私有容器 (魔数 b"Shimadzu XRD")
# ======================================================================
# 结构 (由 XRData/Shimadzu Data 全部 352 个真机文件逆向, 2026-10-09):
#   0x000 : 12 字节魔数 b"Shimadzu XRD"
#   0x010 : ASCII "Ver 0.00" / "Ver 4.5" (软件版本)
#   0x020 : u32 记录类型 (见 _KIND_LABELS): 1=.RAW 2=.RAX 3=.RSM 4=.RBG
#           5=.RK1 6=.RLZ 7=.RFI 0=.ORG; 21~25 =.PKR/.PKK/.PKS/.PSE/.PKF (峰表)
#   0x030 : u32 头部基址; **数据起始 = 基址 + 56** (头长可变: 有的文件把链接的
#           源文件完整路径也写进头里, 故 0x030 会变, 见 ENVCAL/*.RAW)
#   0x034 : u32 **数据字节数 = 点数 × 4** —— 点数以它为准, 不信 (end-start)/step
#   0x04C : 32 字节 ASCII 标签 (常为样品名, 应力测量时写 "Psi = 0.0000")
#   0x064 : 32 字节 ASCII 注释 / 日期
#   0x0DC : 2 字节靶材记号 ("Cu"/"Cr"/…)
#   0x0E0 : u32 波长 × 1e5 (1.54056 Å → 154056)
#   0x12C : i32 起始角 × 1e4   (有符号! Theta 扫描可以是负角, 见 Stress/Theta)
#   0x130 : i32 终止角 × 1e4
#   0x134 : i32 步长 × 1e4     (实测被截断到 4 位小数, 见 Std/Search)
#   数据段: 头之后 n 个 little-endian **int32** 强度 (不是 float32!)
#
# 验证: 与同目录 Shimadzu ASCII 导出 .txt 逐点比对 —— Std/Si (5751 点),
#       Stress/std-sokkei{,1,2,3} (626 点) 共 5 组, 强度**全等**, 2θ 差 <3e-14。
class ShimadzuRawParser(RawParser):
    key = "shimadzu_raw"
    label = "Shimadzu XRD RAW"
    _MAGIC = b"Shimadzu XRD"
    _OFF_KIND = 0x20
    _OFF_HDR_BASE = 0x30
    _OFF_NBYTES = 0x34
    _OFF_LABEL = 0x4C
    _OFF_COMMENT = 0x64
    _OFF_ANODE = 0xDC
    _OFF_LAMBDA = 0xE0
    _OFF_START = 0x12C
    _OFF_END = 0x130
    _OFF_STEP = 0x134
    _HDR_TAIL = 56          # 数据起始 = u32@0x30 + 56
    _MIN_LEN = 0x138

    #: 记录类型 → 简称 (0x20)
    _KIND_LABELS = {
        0: "ORG", 1: "RAW", 2: "RAX", 3: "RSM", 4: "RBG",
        5: "RK1", 6: "RLZ", 7: "RFI",
    }
    #: 峰表类 (PKR/PKK/PKS/PSE/PKF) —— 里面是峰位/峰强清单, **不是**扫描谱,
    #: 当成谱图会造出一条完全虚假的曲线, 故明确拒绝。
    _PEAK_KINDS = frozenset({21, 22, 23, 24, 25})

    def matches(self, raw: bytes) -> bool:
        return raw[:12] == self._MAGIC

    @staticmethod
    def _text(raw: bytes, off: int, size: int) -> str:
        chunk = raw[off:off + size].split(b"\x00")[0]
        return chunk.decode("latin-1", "ignore").strip()

    def _data_block(self, raw: bytes):
        """返回 (offset, n_read, n_declared, truncated)。

        头里声明的偏移 (u32@0x30 + 56) 与数据字节数 (u32@0x34) 优先, 与
        文件长度互校。声明数据区超出文件尾 = 文件被截断: **保持声明偏移
        不动、钳到实际可用点数**并标记 truncated —— 绝不把读取窗口滑进
        头部 (旧实现用 ``len-nbytes`` 尾推, 截断文件会把头部字节当强度
        读进来且无任何标记)。
        """
        nbytes = self._u32(raw, self._OFF_NBYTES)
        if nbytes is None or nbytes <= 0 or nbytes % 4 != 0:
            raise ValueError("Shimadzu RAW: 头部数据长度字段非法")
        base = self._u32(raw, self._OFF_HDR_BASE)
        if base is None:
            raise ValueError("Shimadzu RAW: 头部基址字段缺失")
        off_decl = base + self._HDR_TAIL
        n_declared = nbytes // 4

        if off_decl + nbytes > len(raw):
            # 截断: 声明数据区装不进文件 → 钳到可用点数 (偏移仍是真实头偏移)
            n_avail = max((len(raw) - off_decl) // 4, 0)
            if n_avail < 2:
                raise ValueError(
                    f"Shimadzu RAW: 数据被截断, 可用点数不足 ({n_avail} 点, "
                    f"声明 {n_declared} 点, 声明偏移 {off_decl}, "
                    f"文件 {len(raw)} 字节)"
                )
            return off_decl, n_avail, n_declared, True

        # 非截断: 声明偏移优先; 若声明区没抵到文件尾 (尾部有多余字节),
        # 用"抵尾"候选兜底 (与既有真机样本行为一致)
        candidates = [(off_decl, off_decl + nbytes == len(raw))]
        off_tail = len(raw) - nbytes
        if off_tail >= 0 and off_tail != off_decl:
            candidates.append((off_tail, True))
        candidates.sort(key=lambda c: (not c[1], c[0]))
        return candidates[0][0], n_declared, n_declared, False

    def _axis(self, raw: bytes, n: int, truncated: bool = False):
        """返回 (起始角, 步长, 角度轴是否可信)。"""
        start = self._i32(raw, self._OFF_START)
        end = self._i32(raw, self._OFF_END)
        step = self._i32(raw, self._OFF_STEP)
        if start is None or end is None or step is None:
            return 0.0, 1.0, False
        start, end, step = start / 1e4, end / 1e4, step / 1e4
        # 抹掉 ×1e4 定点存储带来的噪声 (与 Rigaku parser 同理)
        start, end = float(f"{start:.8g}"), float(f"{end:.8g}")
        step = float(f"{step:.8g}")
        if n < 2:
            return start, 1.0, False

        good_range = -180.0 <= start <= 360.0 and end <= 720.0
        if truncated:
            # 截断文件: 头里的 end 对应**声明点数**而非实际可读点数, 此时
            # (end-start)/(n-1) 反推会把轴拉伸 (且该反推对任何 n 都自满足),
            # 两种约定都无法成立 → 轴不可信, 交人工指定, 绝不硬猜。
            return start if good_range else 0.0, step if step > 0 else 1.0, False
        if step > 0 and good_range:
            tol = max(step * 1.5, 0.01)
            if abs(start + step * (n - 1) - end) <= tol:
                return start, step, True
            # 步长字段被截断到 4 位小数时 (Std/Search) 用 (end-start)/(n-1) 反推
            alt = (end - start) / (n - 1)
            if 0 < alt <= 5.0 and abs(start + alt * (n - 1) - end) <= max(alt * 0.05, 1e-3):
                return start, float(f"{alt:.8g}"), True
        # 轴读不出来: 强度照给, 角度轴标不可信 (不猜)
        return start if good_range else 0.0, step if step > 0 else 1.0, False

    def parse(self, raw: bytes, path: Path) -> RawParseResult:
        if len(raw) < self._MIN_LEN:
            raise ValueError(f"Shimadzu RAW 文件过短 (不足 {self._MIN_LEN} 字节): {path}")
        kind = self._u32(raw, self._OFF_KIND) or 0
        kind_name = self._KIND_LABELS.get(kind)
        if kind in self._PEAK_KINDS:
            raise ValueError(
                f"{path.name} 是岛津**峰表**文件 (类型 0x{kind:02X}), 内含峰位/峰强清单, "
                "不是扫描谱图; 请改用同目录的 .RAW / .ORG / .RSM 文件。"
            )
        kind_name = kind_name or f"KIND{kind}"

        offset, n, n_declared, truncated = self._data_block(raw)
        if n < 2:
            raise ValueError(f"Shimadzu RAW 数据段过短 (n={n}): {path}")

        intensity = np.frombuffer(
            raw[offset:offset + n * 4], dtype="<i4"
        ).astype(float)
        if not self._plausible(intensity):
            raise ValueError(
                f"Shimadzu RAW: 数据段含非法强度值 (偏移 {offset}, {n} 点): {path}"
            )

        start, step, confident = self._axis(raw, n, truncated)
        two_theta = start + step * np.arange(n, dtype=float)

        # 靶材 → 波长: 优先用元素记号查表 (实测 Stress/std-sokkei 的波长字段残留
        # Cu 1.5406 而靶材已改成 Cr, 记号比那个字段可靠)
        anode = self._text(raw, self._OFF_ANODE, 2)
        lam_field = (self._u32(raw, self._OFF_LAMBDA) or 0) / 1e5
        from .text_formats import ANODE_WAVELENGTHS

        lam = ANODE_WAVELENGTHS.get(anode.upper()) or lam_field or None

        meta = {
            "raw_header_len": offset,
            "instrument": "Shimadzu",
            "shimadzu_kind": kind,
            "shimadzu_kind_name": kind_name,
            "declared_points": n_declared,
            "truncated": truncated,
            "anode": anode,
            "wavelength_field": lam_field,
            "sample_label": self._text(raw, self._OFF_LABEL, 32),
            "comment": self._text(raw, self._OFF_COMMENT, 32),
            "software_version": self._text(raw, 0x10, 8),
        }
        if abs(two_theta[-1]) > 180.0:
            meta["axis_note"] = (
                f"扫描轴 {two_theta[0]:.3f}°→{two_theta[-1]:.3f}°, 超出常规 2θ 范围 "
                "(可能是极图/摇摆曲线, 非 2θ-θ 扫描)"
            )
        if lam is not None or lam_field:
            meta["wavelength"] = lam or lam_field

        return RawParseResult(
            two_theta=two_theta,
            intensity=intensity,
            format_key=self.key,
            format_label=self.label,
            axis_confident=confident,
            truncated=truncated,
            meta=meta,
        )

    @staticmethod
    def _u32(raw: bytes, off: int) -> Optional[int]:
        try:
            return struct.unpack_from("<I", raw, off)[0]
        except struct.error:
            return None


# ======================================================================
# 5) 通用兜底 (未识别魔数)
# ======================================================================
class GenericRawParser(RawParser):
    """未知魔数的 ``.raw``: 取"最长可信 float32 后缀"当强度, 角度轴标记为待确认。

    只在所有具名 parser 都不匹配时兜底, 保证"至少能把强度救出来", 同时明确
    告知用户角度轴不可信。
    """

    key = "raw_generic"
    label = "未知 RAW 变体"

    def matches(self, raw: bytes) -> bool:
        return True

    def parse(self, raw: bytes, path: Path) -> RawParseResult:
        arr = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4")
        start = len(arr)
        while start > 0 and self._plausible(arr[start - 1:start]):
            start -= 1
        while start < len(arr) and arr[start] == 0.0:
            start += 1
        n = len(arr) - start
        if n < 16:
            raise ValueError(
                f"未识别的 RAW 变体, 且无法从尾部提取出可信的 float32 强度数据: {path}"
            )
        return RawParseResult(
            two_theta=np.arange(n, dtype=float),
            intensity=arr[start:].astype(float),
            format_key=self.key,
            format_label=self.label,
            axis_confident=False,
            meta={"raw_header_len": start * 4, "declared_points": n},
        )


#: 解析器注册表 —— **顺序即优先级**, 兜底 parser 必须放最后。
PARSERS: tuple[RawParser, ...] = (
    RigakuRintParser(),
    ScintagRaw2Parser(),
    BrukerRawV1Parser(),
    ShimadzuRawParser(),
    GenericRawParser(),
)


def detect_raw_parser(raw: bytes) -> RawParser:
    """按魔数返回第一个匹配的 parser (必然命中, 因为兜底 parser 恒真)。"""
    for parser in PARSERS:
        if parser.matches(raw):
            return parser
    return PARSERS[-1]


def parse_raw(raw: bytes, path: Path) -> RawParseResult:
    """解析 RAW 字节流, 自动识别变体。"""
    parser = detect_raw_parser(raw)
    result = parser.parse(raw, path)
    result.meta.setdefault("raw_variant", parser.key)
    return result
