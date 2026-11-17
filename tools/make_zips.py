"""开发用：把 ZZBox v<版本>/ 打成 full 与 lite 两个 zip。

用法（项目根目录）：python tools/make_zips.py
  full —— 原样打包，含 FFmpeg 与 AI 引擎
  lite —— 去掉 bin/ffmpeg.exe 与 bin/ffprobe.exe，其余不变
           （GPL 义务只在分发 FFmpeg 二进制时产生，详见 THIRD-PARTY-NOTICES.md）

zip 内顶层目录统一为 ZZBox v<版本>/，解压即用，不会散一地文件。
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.7.0"
SRC_DIR = f"ZZBox v{VERSION}"              # zip 里的顶层目录名，解压不散一地
SRC = ROOT.parents[1] / "zz box 0.7.0"     # 打包产物实际位置（与 build.py 默认输出一致）
STAGE = ROOT / "_stage" / "zip"
# lite 包剔除的二进制：只有这两个是 GPL，AI 引擎（ncnn）是 BSD
DROP_IN_LITE = ("bin/ffmpeg.exe", "bin/ffprobe.exe")


def _zip(src_root: Path, top: str, out: Path) -> int:
    """把 src_root 下的所有文件写进 out，条目前缀 top/。返回文件数。"""
    files = sorted(p for p in src_root.rglob("*") if p.is_file())
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files:
            zf.write(p, f"{top}/{p.relative_to(src_root).as_posix()}")
    return len(files)


def main() -> int:
    if not SRC.is_dir():
        print(f"找不到 {SRC}")
        return 1

    full = ROOT / f"ZZBox-v{VERSION}-win64-full.zip"
    lite = ROOT / f"ZZBox-v{VERSION}-win64-lite.zip"

    print(f"打包 full（{SRC_DIR}/）…")
    n = _zip(SRC, SRC_DIR, full)
    print(f"  完成 {full.name}  {full.stat().st_size / 1048576:.0f} MB  {n} 个文件")

    # lite：先复制一份到 _stage，再从副本里剔掉 GPL 二进制，源目录不动
    lite_root = STAGE / SRC_DIR
    if lite_root.exists():
        shutil.rmtree(lite_root)
    shutil.copytree(SRC, lite_root)
    for rel in DROP_IN_LITE:
        target = lite_root / rel
        if target.exists():
            target.unlink()
            print(f"  lite 剔除 {rel}")

    print("打包 lite…")
    n = _zip(lite_root, SRC_DIR, lite)
    print(f"  完成 {lite.name}  {lite.stat().st_size / 1048576:.0f} MB  {n} 个文件")

    shutil.rmtree(lite_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
