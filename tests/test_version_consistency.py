"""版本号一致性：``__version__`` ↔ Inno Setup 脚本的默认 ``AppVersion``。

背景（v1.4.0 实测缺陷）：``xinrefinement.__version__`` 已经是 1.4.0，
``packaging/inno/xinrefinement.iss`` 里仍写着 1.1.0。而
``tools/build_binaries.build_installer()`` 打完包后按 ``__version__`` 去找
``dist/installer/XinRefinement-1.4.0-setup.exe``，ISCC 实际产出的是
``...-1.1.0-setup.exe``，于是**构建必定失败在最后一步**（报「安装包未生成」），
前面十几分钟的 PyInstaller 白跑。

现在构建脚本会用 ``ISCC /DAppVersion=`` 覆盖，所以 iss 里的值只是兜底；
但兜底值也应该同步，否则手工跑 ISCC 会打出一个版本号骗人的包。
这条测试就是那道闸。
"""

from __future__ import annotations

import re
from pathlib import Path

import xinrefinement

REPO = Path(__file__).resolve().parents[1]
_ISS = REPO / "packaging" / "inno" / "xinrefinement.iss"


def test_iss_default_version_matches_package() -> None:
    text = _ISS.read_text(encoding="utf-8")
    m = re.search(r'^#define\s+AppVersion\s+"([^"]+)"', text, re.MULTILINE)
    assert m, "iss 缺 `#define AppVersion \"x.y.z\"`，构建脚本的 /D 覆盖没有兜底"
    assert m.group(1) == xinrefinement.__version__, (
        f"iss AppVersion={m.group(1)!r} 与 __version__="
        f"{xinrefinement.__version__!r} 不同步；手工跑 ISCC 会打出错版本的安装包"
    )


def test_iss_has_no_other_hardcoded_version() -> None:
    """除 ``#define`` 外不得再出现字面版本号（历史上曾散落多处）。"""
    text = _ISS.read_text(encoding="utf-8")
    version = xinrefinement.__version__
    offenders = [
        f"{no}: {line.strip()}"
        for no, line in enumerate(text.splitlines(), start=1)
        if version in line and "#define" not in line
    ]
    assert not offenders, (
        "安装脚本里除了 #define 之外不应再出现字面版本号，改用 {#AppVersion}：\n"
        + "\n".join(offenders)
    )


def test_build_script_passes_version_to_iscc() -> None:
    """少了 ``/DAppVersion=``，iss 的默认值就成了唯一真相源，回到老问题。"""
    text = (REPO / "tools" / "build_binaries.py").read_text(encoding="utf-8")
    assert "/DAppVersion=" in text, (
        "build_binaries.build_installer 没有把版本号传给 ISCC"
    )


def test_version_three_way_consistent() -> None:
    """__version__ == iss AppVersion == CHANGELOG 最新标题版本号。"""
    ver = xinrefinement.__version__
    iss = _ISS.read_text(encoding="utf-8")
    m = re.search(r'^#define\s+AppVersion\s+"([^"]+)"', iss, re.MULTILINE)
    assert m and m.group(1) == ver, (m and m.group(1), ver)

    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    head = re.search(r"^##\s+v([0-9]+\.[0-9]+\.[0-9]+)", changelog, re.MULTILINE)
    assert head and head.group(1) == ver, (
        f"CHANGELOG 最新版本 {head and head.group(1)} != __version__ {ver}")
