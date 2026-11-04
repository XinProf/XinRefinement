#!/usr/bin/env python3
"""开发方注册码生成工具（**仅开发方使用，请勿随软件分发**）。

根据用户提供的「单位部门名称」生成注册码；用户在 XinRefinement 内
「帮助 → 输入注册码(&R)…」粘贴后即完成注册，之后不再弹出未注册提示。

算法与 PolyXRD 家族完全一致（``xinmatch/utils/registration.py`` 系
``D:\\Project\\XRD\\PolyXRD-Reg\\registration.py`` 的逐字副本），也可用家族注册机
``PolyXRD-RegTool.exe`` / ``PolyXRD-RegTool-CLI.exe`` 出码，结果互通。

用法::

    python tools/make_reg_code.py "清华大学材料学院"
    python tools/make_reg_code.py "单位A" "单位B"        # 批量
    python tools/make_reg_code.py -f units.txt          # 每行一个单位名称
    python tools/make_reg_code.py --verify PXRD1-XXXX-…  # 校验并回显单位名称

依赖：仅 stdlib（无需 PySide6）。改密钥会使全部历史注册码失效。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接以脚本方式运行（不需 pip install）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xinrefinement.registration import (  # noqa: E402
    CONTACT_EMAIL,
    generate_code,
    verify_code,
)


def _read_names(path: str) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make_reg_code",
        description="XinRefinement 注册码生成工具（开发方使用）",
    )
    parser.add_argument("names", nargs="*", help="单位部门名称（可多个）")
    parser.add_argument("-f", "--file", help="从文件读取单位名称（每行一个，# 开头为注释）")
    parser.add_argument("--verify", metavar="CODE", help="校验注册码并回显对应的单位部门名称")
    args = parser.parse_args(argv)

    if args.verify:
        unit = verify_code(args.verify)
        if unit is None:
            print(f"[无效] {args.verify}")
            return 2
        print(f"[有效] 单位部门名称: {unit}")
        return 0

    names = list(args.names)
    if args.file:
        try:
            names.extend(_read_names(args.file))
        except OSError as exc:
            print(f"读取失败：{exc}", file=sys.stderr)
            return 2
    if not names:
        parser.print_help()
        print("\n错误：请提供至少一个单位部门名称（或使用 -f / --verify）。", file=sys.stderr)
        return 2

    failed = 0
    for name in names:
        try:
            code = generate_code(name)
        except ValueError as exc:
            print(f"[跳过] {name!r}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"{name}\n    {code}\n")
    if failed:
        return 2
    print(f"（注册码与单位部门名称绑定；用户如有疑问请联系 {CONTACT_EMAIL}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
