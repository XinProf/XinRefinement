"""v1.0.0 本地双变体二进制构建。

参照 XinMatch 的双产物策略，一次产出两种二进制：

============  ==========================  ==============================
变体          产物                        说明
============  ==========================  ==============================
release       ``dist/XinRefinement-<ver>/``       正式版（含 PolyXRD-Reg
              ``dist/installer/XinRefinement-<ver>-setup.exe``  注册机制）
internal      ``dist/XinRefinement-internal-<ver>/``            内部评估版
              ``dist/installer/XinRefinement-internal-<ver>-portable.zip``
                                                        （免注册、免安装）
============  ==========================  ==============================

变体以随包分发的 ``variant.txt`` 固化：正式版启动弹注册提示、帮助菜单有
「输入注册码」；内部评估版状态栏红字「内部评估版本」、不接注册。

**只在本地构建**：产物写入 ``dist/``，不入库、不上传、不发布；由人工
双击验收后再决定分发。

用法::

    python tools/build_binaries.py                    # 两个变体全流程
    python tools/build_binaries.py --variant release  # 只构建正式版
    python tools/build_binaries.py --skip-installer   # 只打 exe（含 zip）
    python tools/build_binaries.py --skip-exe         # 只打安装包/zip（复用 dist）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "xinrefinement.spec"
ISS = ROOT / "packaging" / "inno" / "xinrefinement.iss"
DIST = ROOT / "dist"
INSTALLER = DIST / "installer"
VARIANT_REQUEST = ROOT / "build" / "variant.request"
ISCC_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
)

VARIANTS = ("release", "internal")

# 可复现构建：PyInstaller 6 在 Windows 上会把「当前时间」写进 PE 头
# （TimeDateStamp），两次构建的字节必然不同。设 SOURCE_DATE_EPOCH 可把它固定，
# 从而做到同一 commit 下逐字节可复现（验收第 1 轮哈希一致性依赖这一点）。
_SOURCE_DATE_FALLBACK = 1767225600  # 2026-01-01T00:00:00Z


def source_date_epoch() -> int:
    """固定时间戳：优先外部 SOURCE_DATE_EPOCH，其次 git HEAD 提交时间，最后回落到常量。"""
    override = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if override.isdigit():
        return int(override)
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=str(ROOT),
                             capture_output=True, text=True, check=True).stdout.strip()
        if out.isdigit():
            return int(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return _SOURCE_DATE_FALLBACK


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


def bundle_name(variant: str) -> str:
    """产物目录名（与 packaging/xinrefinement.spec 的 BUNDLE_NAME 一致）。"""
    if variant == "internal":
        return f"XinRefinement-internal-{_version()}"
    return f"XinRefinement-{_version()}"


def dist_dir(variant: str) -> Path:
    """版本化产物目录：避免覆盖旧构建（整目录删除会被安全策略拦截）。"""
    return DIST / bundle_name(variant)


def _write_variant_request(variant: str) -> None:
    """写 build/variant.request 并立即回读校验（spec 优先读它）。"""
    VARIANT_REQUEST.parent.mkdir(parents=True, exist_ok=True)
    VARIANT_REQUEST.write_text(variant, encoding="ascii")
    got = VARIANT_REQUEST.read_text(encoding="ascii").strip().lower()
    if got != variant:
        raise SystemExit(f"variant.request 写后读不一致：{got!r} != {variant!r}")


def _assert_marker(variant: str) -> None:
    """校验产物里的 variant.txt（漏放会让内部版退化成强制注册版）。"""
    marker = dist_dir(variant) / "_internal" / "variant.txt"
    if not marker.exists():
        marker2 = dist_dir(variant) / "variant.txt"
        if not marker2.exists():
            raise SystemExit(f"产物缺少 variant.txt：{dist_dir(variant)}")
        marker = marker2
    text = marker.read_text(encoding="utf-8").strip().lower()
    if text != variant:
        raise SystemExit(f"variant.txt 内容 {text!r} != 期望 {variant!r}（{marker}）")
    print(f"  变体标记 OK：{marker.name} = {text}")


def build_exe(variant: str, clean: bool) -> None:
    _write_variant_request(variant)
    epoch = source_date_epoch()
    env = dict(os.environ, XR_VERSION=_version(), XR_BUILD_VARIANT=variant,
               SOURCE_DATE_EPOCH=str(epoch),
               # 字符串集合的迭代顺序受哈希随机化影响，会让 PYZ 里 marshal 后的
               # 字节流随进程变化（压缩长度随之抖动）。固定种子以获得可复现产物。
               PYTHONHASHSEED="0")
    print(f"  SOURCE_DATE_EPOCH={epoch}（固定 PE 时间戳，保证可复现）")
    # 先构建到一次性暂存目录：PyInstaller 的 COLLECT 会先删目标目录，
    # 直接指向 dist/ 会在重建时被安全策略（批量删除）拦截。
    stage = ROOT / "build" / "stage" / f"{variant}-{int(time.time())}"
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

    src = stage / bundle_name(variant)
    if not src.exists():
        raise SystemExit(f"暂存产物缺失：{src}")
    dst = dist_dir(variant)
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)   # 覆盖同名文件，不删目录
    print(f"  已镜像到 {dst}")
    _assert_marker(variant)


def build_installer(variant: str) -> Path:
    iscc = next((p for p in ISCC_CANDIDATES if p.exists()), None)
    if iscc is None:
        raise SystemExit("未找到 Inno Setup 的 ISCC.exe（请安装 Inno Setup 6）")
    # 版本号与源目录都用 /D 传：iss 里只保留一份「没带参数时」的兜底默认值。
    # 曾经 iss 写死 1.1.0 而 __version__ 已是 1.4.0 —— ISCC 把产物命名成
    # 1.1.0，下面按 __version__ 找文件必然落空，报「安装包未生成」。
    _run([
        str(iscc), "/Qp",
        f"/DAppVersion={_version()}",
        f"/DDistDir={dist_dir(variant)}",
        str(ISS),
    ])
    out = INSTALLER / f"XinRefinement-{_version()}-setup.exe"
    if not out.exists():
        raise SystemExit("安装包未生成")
    return out


def build_portable_zip(variant: str) -> Path:
    """内部评估版：整目录打 zip（免安装，解压即用）。"""
    name = bundle_name(variant)
    INSTALLER.mkdir(parents=True, exist_ok=True)
    target = INSTALLER / f"{name}-portable.zip"
    tmp = shutil.make_archive(str(target.with_suffix("")), "zip",
                              root_dir=str(DIST), base_dir=name)
    produced = Path(tmp)
    if produced != target:
        produced.replace(target)
    print(f"  已打包 {target}")
    return target


def _report(path: Path) -> None:
    print(f"  {path.name}  {path.stat().st_size / 1e6:.1f} MB  "
          f"sha256={_sha256(path)[:16]}…")


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK：脚本末尾的 "⚠" 会让 print 抛 UnicodeEncodeError，
    # 于是构建明明全部成功、退出码却是 1（v1.1.0 构建时踩到，CI 会误判失败）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover - 非标准流
            pass
    ap = argparse.ArgumentParser(description="XinRefinement 本地双变体构建")
    ap.add_argument("--variant", choices=("all",) + VARIANTS, default="all",
                    help="构建哪个变体（默认 all = release + internal）")
    ap.add_argument("--skip-installer", action="store_true",
                    help="不打安装包 / 便携 zip")
    ap.add_argument("--skip-exe", action="store_true",
                    help="只打安装包 / zip（复用已构建的 dist）")
    ap.add_argument("--no-clean", action="store_true",
                    help="不清理 PyInstaller 缓存（默认每个变体都清理）")
    args = ap.parse_args(argv)

    todo = VARIANTS if args.variant == "all" else (args.variant,)
    installers: list[Path] = []

    for variant in todo:
        print(f"\n===== 构建变体：{variant}（{bundle_name(variant)}）=====")
        if not args.skip_exe:
            build_exe(variant, clean=not args.no_clean)
            print()
            _report(dist_dir(variant) / "XinRefinement.exe")
            _report(dist_dir(variant) / "XinRefinementCLI.exe")
        if not args.skip_installer:
            if variant == "release":
                installers.append(build_installer(variant))
            else:
                installers.append(build_portable_zip(variant))

    if installers:
        print()
        for p in installers:
            print(f"发布件 {p}  {p.stat().st_size / 1e6:.1f} MB")
            print(f"sha256 = {_sha256(p)}")
    print("\n⚠ 本地产物仅用于人工验收：不提交、不上传、不发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
