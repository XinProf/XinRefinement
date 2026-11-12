# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本（v1.0.0）。

产物（onedir，同目录内 GUI + CLI 两个可执行文件共享依赖）::

    dist/XinRefinement/XinRefinement.exe       GUI（windowed，无控制台）
    dist/XinRefinement/XinRefinementCLI.exe    CLI（console，批处理用）

不内嵌数据库：v1.0.0 只依赖 `xinrefinement/data` 下的内置 CIF 与空间群表
（已随 datas 打入）。构建命令见 tools/build_binaries.py。
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

VERSION = os.environ.get("XR_VERSION", "dev")

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
ENTRY_GUI = str(ROOT / "xinrefinement" / "gui" / "__main__.py")
ENTRY_CLI = str(ROOT / "xinrefinement" / "cli" / "__main__.py")
ICON = str(SPEC_DIR / "xinrefinement.ico")

# ---- 构建变体：release（正式版·含注册）/ internal（内部评估版） ----
# 变体决定产物目录名与随包分发的 variant.txt（运行时由
# xinrefinement.build_variant 读取；缺失按 release 处理，fail-safe）。
#
# build/variant.request **优先于**环境变量：COLLECT 的名字决定输出目录，
# 若变体在本进程里读错，internal 构建会算出 release 的名字并覆盖掉另一个
# 已建好的变体。文件是确定性的，所以让它说话（XinMatch 同款处理）。
_VARIANT_REQUEST = SPEC_DIR.parent / "build" / "variant.request"


def _resolve_variant() -> str:
    if _VARIANT_REQUEST.is_file():
        v = _VARIANT_REQUEST.read_text(encoding="utf-8").strip().lower()
        if v in ("release", "internal"):
            return v
    v = os.environ.get("XR_BUILD_VARIANT", "release").strip().lower()
    return v if v in ("release", "internal") else "release"


BUILD_VARIANT = _resolve_variant()

# 标记文件先落到 build/，再作为 datas 打进产物（onedir 下进 _internal/）
_VARIANT_MARKER = SPEC_DIR.parent / "build" / "variant.txt"
_VARIANT_MARKER.parent.mkdir(parents=True, exist_ok=True)
_VARIANT_MARKER.write_text(BUILD_VARIANT, encoding="utf-8")

BUNDLE_NAME = (f"XinRefinement-{VERSION}" if BUILD_VARIANT == "release"
               else f"XinRefinement-internal-{VERSION}")

datas = [
    (str(ROOT / "xinrefinement" / "data"), "xinrefinement/data"),
    (str(_VARIANT_MARKER), "."),
    # v1.6.1：帮助→版权与许可要读全文。装上这两个文件，界面才不必在代码里
    # 复写一份许可文本（两处文本必然漂移）。
    (str(ROOT / "LICENSE"), "licenses"),
    (str(ROOT / "LICENSE-CN"), "licenses"),
]
# matplotlib / PySide6 的运行时数据由各自 hook 处理；此处补 mpl 字体等
datas += collect_data_files("matplotlib", includes=["mpl-data/**"])

# ---- 注册密钥构建期注入（密钥本身不入库，见 .gitignore） ----
# 正式版必须沿用原生产密钥，否则此前发出的注册码全部失效；密钥来源优先级：
# XR_REG_SECRET 指向的文件 → xinrefinement/registration_secret.txt。
# 缺文件时不打包，运行时退回社区占位密钥（源码构建/内部评估版即此路径）。
_REG_SECRET = Path(os.environ.get("XR_REG_SECRET", "").strip()
                   or ROOT / "xinrefinement" / "registration_secret.txt")
if BUILD_VARIANT == "release" and _REG_SECRET.is_file():
    datas.append((str(_REG_SECRET), "xinrefinement"))

hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "PySide6.QtSvg",
    "spglib",
    # 注册机制：只经延迟导入，显式登记避免被裁剪
    "xinrefinement.registration",
    "xinrefinement.build_variant",
]

excludes = ["tkinter", "tests", "pytest", "IPython", "notebook"]

a_gui = Analysis(
    [ENTRY_GUI],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
a_cli = Analysis(
    [ENTRY_CLI],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# 合并两份依赖，避免产物翻倍；两 EXE 共享同一批 DLL
MERGE((a_gui, "XinRefinement", "XinRefinement"),
      (a_cli, "XinRefinement", "XinRefinement"))

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

exe_gui = EXE(
    pyz_gui, a_gui.scripts, [],
    exclude_binaries=True,
    name="XinRefinement",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
)
exe_cli = EXE(
    pyz_cli, a_cli.scripts, [],
    exclude_binaries=True,
    name="XinRefinementCLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=ICON,
)

coll = COLLECT(
    exe_gui, a_gui.binaries, a_gui.datas,
    exe_cli, a_cli.binaries, a_cli.datas,
    strip=False,
    upx=False,
    name=BUNDLE_NAME,
)
