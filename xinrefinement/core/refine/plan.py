"""两段式管线的「段配置翻译」：把 `PipelineOptions` 翻成各段的 `SolveOptions`。

**为什么单独成模块**：`nca/core/pipeline.py` 曾达 513 行，超「单文件 ≤400
行」的硬约束。这里放的是**纯映射**（不含任何精修状态）：输入一个管线
配置，输出某一该段的开关集合。与 `valley.py`（数值子问题）同属「可从
管线里剥离且能独立测试」的部分。

**为什么段 1b 要关掉 PO**：择优取向 r 与 TCH 尺寸项 Y 强相关（都改变
峰形），一次同开会把 r 顶到边界、U 触下界（T6.4d 实测坏解）。故段 1a
精修 PO，段 1b **固定** r（经 `init_params.po_r` 带入正向模型）只精修
TCH。注意 `refine_po=False` 时必须保留调用方的 `prm0.po_r` —— 见
`nca/core/refine/nonlinear.py::_ensure_po_r`（T8.1 修复：曾经被一律清空，
导致段 2 丢掉择优取向、真实样 Rwp 13.2→16.3 %）。
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from xinrefinement.core.refine.nonlinear import RefineCancelled

if TYPE_CHECKING:                          # 仅注解，避免与 pipeline 循环导入
    from xinrefinement.core.pipeline import PipelineOptions
    from xinrefinement.core.solve import SolveOptions, SolveResult


def check_cancel(cancel_cb) -> None:
    """取消检查（与核心层 `_check_cancel` 同语义，但用于阶段边界）。"""
    if cancel_cb is None:
        return
    try:
        if cancel_cb():
            raise RefineCancelled()
    except RefineCancelled:
        raise
    except Exception:                      # noqa: BLE001 —— 钩子异常不得中断精修
        pass


def wavelength_for(stage1: SolveResult) -> float:
    """取实际用于前向模型的 Kα1 波长（Å）。

    不能用 `shape.DEFAULT_WAVELENGTH` 一刀切 —— 阳极换了（Co/Fe 等）或
    单色光模式，波长都不同。`ProfileParams.wavelength` 在 anode 非 None 时
    存的是基准波长；此时取阳极双线里较长的那条（Kα1，强度权重 1/(1+r)）。
    """
    prm = stage1.result.params
    if prm.anode is None:
        return float(prm.wavelength)
    from xinrefinement.core.profile.shape import resolve_wavelengths

    lines = resolve_wavelengths(prm.wavelength, prm.anode, prm.ka_ratio)
    # lines 已按权重归一化；Kα1 是权重最大者（Cu: 1.5406 / 0.667）
    return float(max(lines, key=lambda t: t[1])[0])


def stage1_options(opt: PipelineOptions) -> SolveOptions:
    """把管线的 TCH 开关并入段 1 的 SolveOptions。

    注意 `SolveOptions` 是 frozen dataclass，故用 `dataclasses.replace`
    而不是构造新对象 —— 保留调用方给的所有其它开关（PO、晶胞等）。
    """
    s1 = opt.stage1
    if not opt.refine_size and not opt.refine_strain:
        return s1
    return replace(s1, refine_size=opt.refine_size,
                   refine_strain=opt.refine_strain)


def stage2_options(opt: PipelineOptions) -> SolveOptions:
    """段 1b（放开 TCH 尺寸项）的配置。

    - 择优取向**固定**在段 1a 的值上（不参与本段精修，但通过
      `init_params.po_r` 带入正向模型 —— T8.1 修复）；
    - 峰形/晶胞/TCH 尺寸**联合**精修，初值取谷扫描谷底
      （`nca/core/refine/valley.py`）—— 段 1a 把尺寸展宽吸收进 Caglioti
      项后，U/V/W 与 Y 的联合谷是弯的，普通初值的 LM 初始梯度只指向
      「Y→0 + UVW 回吸」的假盆地。
    """
    s1 = opt.stage1
    return replace(s1, refine_size=opt.refine_size,
                   refine_strain=opt.refine_strain, refine_po=False,
                   po_r=None)
