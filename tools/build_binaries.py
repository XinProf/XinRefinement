"""v1.0.0 本地二进制构建（PyInstaller onedir + Inno Setup 安装包）。

**只在本地构建**：产物写入 ``dist/``，不入库、不上传、不发布；由人工
双击验收后再决定分发。

用法::

    python tools/build_binaries.py                 # 全流程（exe + 安装包）
    python tools/build_binaries.py --skip-installer # 只打 exe
    python tools/build_binaries.py --skip-exe       # 只打安装包（复用已构建 dist）
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "xinrefinement.spec"
ISS = ROOT / "packaging" / "inno" / "xinrefinement.iss"
DIST = ROOT / "dist"
ISCC_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT))
    if proc.returncode != 0:
        raise SystemExit(f"命令失败（exit={proc.returncode}）：{cmd[0]}")
    print(f"  完成，用时 {time.time() - t0:.0f}s")


def _version() -> str:
    sys.path.insert(0, str(ROOT))
    from xinrefinement import __version__
    return __version__


def dist_dir() -> Path:
    """版本化产物目录：避免覆盖旧构建（整目录删除会被安全策略拦截）。"""
    return DIST / f"XinRefinement-{_version()}"


def build_exe(clean: bool) -> None:
    import os
    import shutil

    env = dict(os.environ, XR_VERSION=_version())
    # 先构建到一次性暂存目录：PyInstaller 的 COLLECT 会先删目标目录，
    # 直接指向 dist/ 会在重建时被安全策略（批量删除）拦截。
    stage = ROOT / "build" / "stage" / f"run-{int(time.time())}"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           "--distpath", str(stage), "--workpath", str(ROOT / "build"),
           str(SPEC)]
    if clean:
        cmd.insert(3, "--clean")
    print()
    print("$ " + " ".join(str(c) for c in cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller 失败（exit={proc.returncode}）")
    print(f"  完成，用时 {time.time() - t0:.0f}s")

    src = stage / f"XinRefinement-{_version()}"
    if not src.exists():
        raise SystemExit(f"暂存产物缺失：{src}")
    dst = dist_dir()
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)   # 覆盖同名文件，不删目录
    print(f"  已镜像到 {dst}")


def build_installer() -> Path:
    iscc = next((p for p in ISCC_CANDIDATES if p.exists()), None)
    if iscc is None:
        raise SystemExit("未找到 Inno Setup 的 ISCC.exe（请安装 Inno Setup 6）")
    _run([str(iscc), "/Qp", f"/DDistDir={dist_dir()}", str(ISS)])
    out = DIST / "installer" / f"XinRefinement-{_version()}-setup.exe"
    if not out.exists():
        cands = sorted((DIST / "installer").glob("*.exe"))
        if not cands:
            raise SystemExit("安装包未生成")
        out = cands[-1]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="XinRefinement 本地二进制构建")
    ap.add_argument("--skip-installer", action="store_true")
    ap.add_argument("--skip-exe", action="store_true")
    ap.add_argument("--no-clean", action="store_true",
                    help="不清理 PyInstaller 缓存（默认清理）")
    args = ap.parse_args(argv)

    if not args.skip_exe:
        # 注意：不整目录删除 dist/（沙箱对批量删除有保护，且 PyInstaller
        # 的 --noconfirm 会自行覆盖旧产物）
        build_exe(clean=not args.no_clean)
        gui = dist_dir() / "XinRefinement.exe"
        cli = dist_dir() / "XinRefinementCLI.exe"
        for p in (gui, cli):
            if not p.exists():
                raise SystemExit(f"缺少产物：{p}")
        print(f"\nGUI  {gui}  {gui.stat().st_size / 1e6:.1f} MB  "
              f"sha256={_sha256(gui)[:16]}…")
        print(f"CLI  {cli}  {cli.stat().st_size / 1e6:.1f} MB  "
              f"sha256={_sha256(cli)[:16]}…")

    if not args.skip_installer:
        inst = build_installer()
        print(f"\n安装包 {inst}  {inst.stat().st_size / 1e6:.1f} MB")
        print(f"sha256 = {_sha256(inst)}")
        print("\n⚠ 本地产物仅用于人工验收：不提交、不上传、不发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
