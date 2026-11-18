# -*- coding: utf-8 -*-
"""诊断：PDF 队列里压缩图片时，质量条拖动预估不变 / 压完比原图大。

对两张测试图按 PDF 面板的同一套设置（_pdf_image_settings）分别做：
  1. preview_compress_bytes  —— 预估用的 PIL 真编一次
  2. build_compress_steps + ffmpeg —— 确认压缩时真正走的编码
对比各质量下的体积，看预估是否随质量变化、实际输出是否比原图大。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.image import (  # noqa: E402
    ImageSettings, build_compress_steps, out_format, preview_compress_bytes,
    probe_image,
)
from app.core.probe import _find_tool  # noqa: E402

IMAGES = [
    ROOT.parents[1] / "测试图.png",
    ROOT.parents[1] / "测试图.jpg",
]
QUALITIES = [30, 50, 78, 95]


def run(fmt_mode: str) -> None:
    ffmpeg = _find_tool("ffmpeg")
    print(f"\n===== 图片方案格式: {fmt_mode} =====")
    for src in IMAGES:
        if not src.exists():
            print(f"缺文件: {src}")
            continue
        info = probe_image(src)
        orig = src.stat().st_size
        print(f"\n--- {src.name}  {info.width}x{info.height} {info.fmt} "
              f"alpha={info.alpha} 原图 {orig} bytes ---")
        for q in QUALITIES:
            s = ImageSettings(fmt=fmt_mode, quality=q, max_side=0, strip_meta=False)
            of = out_format(info, s)
            est = preview_compress_bytes(src, s, info)
            with tempfile.TemporaryDirectory() as td:
                out = Path(td) / f"out.{of}"
                cmds, made, err = build_compress_steps(
                    ffmpeg, src, s, info, out_path=out)
                if err:
                    print(f"  q={q:>3} out={of:>4}  构建失败: {err}")
                    continue
                for cmd in cmds:
                    subprocess.run(cmd, check=True, capture_output=True)
                real = made.stat().st_size
            ratio_e = est / orig * 100
            ratio_r = real / orig * 100
            print(f"  q={q:>3} out={of:>4}  预估 {est:>9} ({ratio_e:5.1f}% 原图)"
                  f"  实际 {real:>9} ({ratio_r:5.1f}% 原图)")


if __name__ == "__main__":
    for mode in ("keep", "jpg", "png", "webp"):
        run(mode)
