"""PDF 图片压缩回归测试。

验的是这一版压缩的三条硬承诺：
  1. 文字层还在 —— 压缩后仍能搜索、复制
  2. 页面尺寸不变 —— MediaBox 一个数都不动
  3. 图片像素尺寸不变 —— 只降 JPEG 质量，不缩图

素材用 PyMuPDF 生成（AGPL，仅测试用，不进产品代码）。

跑法：python tools/test_pdf_images.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app.core.pdf import PageRef  # noqa: E402
from app.core.pdf_images import (  # noqa: E402
    estimate_pdf,
    merge_pdf,
    scan_pdf,
    stage_page,
)

WORK = Path(__file__).resolve().parent / "_probe_tmp"
WORK.mkdir(parents=True, exist_ok=True)

PASS, FAIL = "PASS", "FAIL"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def noise_jpeg(path: Path, w: int = 1600, h: int = 1200, quality: int = 96) -> Path:
    """噪点图：模拟扫描件，JPEG 有得可压但不会一眼糊掉。"""
    rng = np.random.default_rng(7)
    arr = rng.integers(80, 220, (h, w, 3), dtype="uint8")
    arr[: h // 6, :, :] = 246          # 一条白边，制造低频区
    Image.fromarray(arr, "RGB").save(path, quality=quality)
    return path


def make_doc(path: Path) -> Path:
    """3 页：p0 文字+大图、p1 纯文字、p2 文字+带透明通道的图。"""
    jpg = noise_jpeg(WORK / "big.jpg")
    rgba = Image.new("RGBA", (600, 400), (255, 0, 0, 0))
    rgba.paste((20, 160, 90, 255), (100, 100, 500, 300))
    png = WORK / "alpha.png"
    rgba.save(png)

    doc = pymupdf.open()
    p0 = doc.new_page(width=595, height=842)
    p0.insert_text((72, 80), "SCAN PAGE WITH PHOTO", fontsize=18)
    p0.insert_text((72, 106), "text must survive compression", fontsize=11)
    p0.insert_image(pymupdf.Rect(50, 150, 545, 560), filename=str(jpg))

    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 90), "PAGE TWO ONLY TEXT", fontsize=18)

    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 90), "PAGE THREE ALPHA IMAGE", fontsize=18)
    p2.insert_image(pymupdf.Rect(50, 150, 445, 414), filename=str(png))

    doc.save(path)
    doc.close()
    return path


def pages_of(path: Path):
    r = PdfReader(str(path))
    return [(float(p.mediabox.width), float(p.mediabox.height)) for p in r.pages]


def text_of(path: Path) -> str:
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def image_sizes(path: Path) -> list[tuple[int, int]]:
    """读出每页图片对象的像素宽高（用来证明"没缩图"）。"""
    sizes = []
    for page in PdfReader(str(path)).pages:
        res = page.get("/Resources")
        if res is None:
            continue
        xo = res.get_object().get("/XObject")
        if xo is None:
            continue
        for _name, ref in xo.get_object().items():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Image":
                sizes.append((int(obj.get("/Width")), int(obj.get("/Height"))))
    return sizes


def render_first(path: Path):
    import pypdfium2 as pdfium

    d = pdfium.PdfDocument(str(path))
    pil = d[0].render(scale=1.0).to_pil().convert("RGB")
    d.close()
    return pil


def main() -> None:
    src = make_doc(WORK / "src.pdf")
    print(f"素材：{src.name} {src.stat().st_size / 1024:.0f} KB · 3 页")

    print("\n[1] 扫描：只统计不解码")
    stats = scan_pdf(src)
    check("三页都有体检结果", len(stats) == 3, str(sorted(stats)))
    check("第 1 页有可压图片", stats[0].compressible, stats[0].label())
    check("第 1 页统计到原始字节", stats[0].cur_bytes > 300_000,
          f"{stats[0].cur_bytes / 1024:.0f} KB")
    check("第 2 页判为无图片", stats[1].reason == "本页无图片", stats[1].reason)
    check("第 3 页的透明图被跳过",
          stats[2].skipped >= 1 and not stats[2].compressible,
          f"count={stats[2].count} skipped={stats[2].skipped}")
    check("未估算时 label 说待估算", "待估算" in stats[0].label(), stats[0].label())

    print("\n[2] 估算：真解码真编码")
    est = estimate_pdf(src, 55)
    check("估算后 est_bytes 有值", est[0].est_bytes > 0, f"{est[0].est_bytes}")
    check("估算值小于原值", est[0].est_bytes < est[0].cur_bytes,
          f"{est[0].cur_bytes / 1024:.0f}KB → {est[0].est_bytes / 1024:.0f}KB")
    check("节省超过一半", est[0].est_bytes < est[0].cur_bytes * 0.5,
          f"{(1 - est[0].est_bytes / est[0].cur_bytes) * 100:.0f}%")
    check("label 变成箭头形式", "→" in est[0].label(), est[0].label())

    print("\n[3] 单页暂存：文字层 / 页面尺寸 / 图片像素")
    stage = stage_page(
        PageRef(src=str(src), kind="pdf", index=0), WORK / "stage0.pdf", 55
    )
    check("暂存文件生成", stage.exists() and stage.stat().st_size > 0,
          f"{stage.stat().st_size / 1024:.0f} KB")
    check("暂存文件比原图页小", stage.stat().st_size < src.stat().st_size * 0.5,
          f"{stage.stat().st_size / 1024:.0f} KB vs {src.stat().st_size / 1024:.0f} KB")
    check("文字层还在", "SCAN PAGE WITH PHOTO" in text_of(stage), text_of(stage)[:40])
    check("页面尺寸不变", pages_of(stage)[0] == pages_of(src)[0],
          f"{pages_of(stage)[0]} vs {pages_of(src)[0]}")
    before_sz = image_sizes(src)[0]
    after_sz = image_sizes(stage)[0]
    check("图片像素宽高不变", before_sz == after_sz, f"{before_sz} → {after_sz}")
    check("暂存页只有 1 页", len(PdfReader(str(stage)).pages) == 1)

    print("\n[4] 渲染对比：图片仍在原位、画质可接受")
    a, b = render_first(src), render_first(stage)
    check("渲染尺寸一致", a.size == b.size, f"{a.size} vs {b.size}")
    diff = np.abs(np.asarray(a, "int16") - np.asarray(b, "int16"))
    mse = float((diff.astype("float64") ** 2).mean())
    psnr = 10 * np.log10(255 * 255 / max(mse, 1e-9))
    check("画质没有明显损失", psnr > 32,
          f"PSNR {psnr:.1f} dB 最大差 {int(diff.max())}")

    print("\n[5] 合并导出：边合边压")
    refs = [
        PageRef(src=str(src), kind="pdf", index=0),
        PageRef(src=str(src), kind="pdf", index=1),
        PageRef(src=str(src), kind="pdf", index=2),
    ]
    out = merge_pdf(refs, WORK / "merged.pdf", quality=55)
    r = PdfReader(str(out))
    check("合并出 3 页", len(r.pages) == 3, str(len(r.pages)))
    txt = text_of(out)
    for want in ("SCAN PAGE WITH PHOTO", "PAGE TWO ONLY TEXT", "PAGE THREE ALPHA IMAGE"):
        check(f"文字保留：{want[:18]}", want in txt)
    check("页面尺寸全部不变", pages_of(out) == pages_of(src))
    check("合并文件比原始小", out.stat().st_size < src.stat().st_size * 0.6,
          f"{out.stat().st_size / 1024:.0f} KB vs {src.stat().st_size / 1024:.0f} KB")

    print("\n[6] 暂存优先：导出直接用压好的单页")
    staged = {(str(src), 0, 0): str(stage)}
    out2 = merge_pdf(refs[:2], WORK / "staged.pdf", staged=staged)
    check("暂存页被用上（体积接近 stage0）",
          abs(out2.stat().st_size - stage.stat().st_size) < 40 * 1024,
          f"{out2.stat().st_size / 1024:.0f} KB vs {stage.stat().st_size / 1024:.0f} KB")
    check("暂存路径下文字也在", "SCAN PAGE WITH PHOTO" in text_of(out2))

    print("\n[7] quality=None：不压，纯搬运")
    plain = merge_pdf(refs[:2], WORK / "plain.pdf")
    # 前两页里第 1 页那张大图是 1.6 MB，不压的话体积应该几乎是压缩版的 4 倍
    check("不压时明显比压缩版大", plain.stat().st_size > stage.stat().st_size * 3,
          f"{plain.stat().st_size / 1024:.0f} KB vs {stage.stat().st_size / 1024:.0f} KB")
    check("不压时图片对象保持原样",
          image_sizes(plain)[0] == image_sizes(src)[0],
          f"{image_sizes(plain)[0]}")
    check("不压时文字也在", "SCAN PAGE WITH PHOTO" in text_of(plain))

    print("\n[8] 旋转叠加")
    rot_ref = PageRef(src=str(src), kind="pdf", index=1, rotate=90)
    rp = merge_pdf([rot_ref], WORK / "rot.pdf", quality=55)
    check("旋转写进 /Rotate", PdfReader(str(rp)).pages[0].rotation == 90,
          str(PdfReader(str(rp)).pages[0].rotation))

    print("\n[9] 取消与异常")
    ev = threading.Event()
    ev.set()
    try:
        merge_pdf(refs, WORK / "cancel.pdf", quality=55, cancel=ev)
        check("已取消的任务抛异常", False, "居然正常返回了")
    except Exception as exc:  # noqa: BLE001
        check("已取消的任务抛 PdfCancelled", type(exc).__name__ == "PdfCancelled",
              type(exc).__name__)
    bad = WORK / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot really a pdf\n")
    try:
        scan_pdf(bad)
        check("坏文件报 PdfImageError", False, "居然没报错")
    except Exception as exc:  # noqa: BLE001
        check("坏文件报 PdfImageError", "PdfImageError" in type(exc).__name__,
              type(exc).__name__)

    print()
    if _fails:
        print(f"RESULT = FAIL（{len(_fails)} 项）")
        for n in _fails:
            print("  -", n)
        sys.exit(1)
    print("RESULT = PASS")


if __name__ == "__main__":
    main()
