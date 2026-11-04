# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本（v1.0.0）。

产物（onedir，同目录内 GUI + CLI 两个可执行文件共享依赖）::

    dist/XinRefinement/XinRefinement.exe       GUI（windowed，无控制台）
    dist/XinRefinement/XinRefinementCLI.exe    CLI（console，批处理用）

不内嵌数据库：v1.0.0 只依赖 `xinrefinement/data` 下的内置 CIF 与空间群表
（已随 datas 打入）。构建命令见 tools/build_binaries.py。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
ENTRY_GUI = str(ROOT / "xinrefinement" / "gui" / "__main__.py")
ENTRY_CLI = str(ROOT / "xinrefinement" / "cli" / "__main__.py")
ICON = str(SPEC_DIR / "xinrefinement.ico")

datas = [
    (str(ROOT / "xinrefinement" / "data"), "xinrefinement/data"),
]
# matplotlib / PySide6 的运行时数据由各自 hook 处理；此处补 mpl 字体等
datas += collect_data_files("matplotlib", includes=["mpl-data/**"])

hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "PySide6.QtSvg",
    "spglib",
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
    name="XinRefinement",
)
