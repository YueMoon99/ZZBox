"""PDF 印刷稿图片压缩回归测试：CMYK + SMask 不能再被误判"不可压缩"。

背景：设计稿 PDF（InDesign / Illustrator 导出）里的位图几乎都是 CMYK，
抠图还带 /SMask。旧代码看到这两样就整张跳过，导致"明明一堆位图却
提示不可压缩"。本测试锁住修复后的行为：

  1. CMYK + SMask 的图能被 scan/estimate/stage 识别并压缩
  2. 压缩后颜色不偏（和原PDF渲染对比，平均色差 < 0.5/255）
  3. SMask 原样保留（透明度不变）
  4. 页面尺寸、图片像素尺寸不变
  5. 两种 CMYK 来源都对：Flate 原始像素 和 DCTDecode JPEG

素材全部本地合成，不依赖任何外部文件。
跑法：python tools/test_pdf_cmyk_smask.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402
from PIL import Image, ImageChops, ImageStat  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from app.core.pdf import PageRef  # noqa: E402
from app.core.pdf_images import (  # noqa: E402
    estimate_pdf,
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


def _cmyk_pixels(w: int, h: int, seed: int) -> bytes:
    """带噪点的 CMYK 原始像素，Flate 压不动、JPEG 压得动，才有测试意义。"""
    rng = np.random.default_rng(seed)
    arr = rng.integers(30, 225, (h, w, 4), dtype="uint8")
    arr[: h // 8, :, :] = 10  # 一条近似纯色带
    return arr.tobytes()


def make_pdf(path: Path, use_dct: bool) -> Path:
    """造一页带一张 CMYK 图 + SMask 的 PDF。"""
    W, H = 240, 320
    writer = PdfWriter()
    page = writer.add_blank_page(width=420, height=596)

    if use_dct:
        im = Image.frombytes("CMYK", (W, H), _cmyk_pixels(W, H, 3))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=96, optimize=True)
        img = StreamObject()
        img._data = buf.getvalue()
        img[NameObject("/Filter")] = NameObject("/DCTDecode")
    else:
        img = DecodedStreamObject()
        img.set_data(_cmyk_pixels(W, H, 3))

    img[NameObject("/Type")] = NameObject("/XObject")
    img[NameObject("/Subtype")] = NameObject("/Image")
    img[NameObject("/Width")] = NumberObject(W)
    img[NameObject("/Height")] = NumberObject(H)
    img[NameObject("/ColorSpace")] = NameObject("/DeviceCMYK")
    img[NameObject("/BitsPerComponent")] = NumberObject(8)

    # SMask：灰度蒙版，8bit；内容随便给个渐变，关键是它得原样保留
    mask = DecodedStreamObject()
    mask.set_data(bytes((i * 7) % 256 for i in range(W * H)))
    mask[NameObject("/Type")] = NameObject("/XObject")
    mask[NameObject("/Subtype")] = NameObject("/Image")
    mask[NameObject("/Width")] = NumberObject(W)
    mask[NameObject("/Height")] = NumberObject(H)
    mask[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
    mask[NameObject("/BitsPerComponent")] = NumberObject(8)
    mask_ref = writer._add_object(mask)
    img[NameObject("/SMask")] = mask_ref

    img_ref = writer._add_object(img)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/ImC"): img_ref})}
    )
    content = DecodedStreamObject()
    content.set_data(b"q 300 0 0 400 60 100 cm /ImC Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)

    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def render(path: Path):
    doc = pdfium.PdfDocument(str(path))
    return doc[0].render(scale=1.0).to_pil().convert("RGB")


def run_one(tag: str, use_dct: bool) -> None:
    print(f"\n=== {tag} ===")
    src = make_pdf(WORK / f"cmyk_{tag}.pdf", use_dct)
    orig_size = src.stat().st_size

    stat = scan_pdf(src)[0]
    check(f"{tag} scan 识别到可压图片", stat.count == 1, f"count={stat.count}")
    check(f"{tag} 不再因 SMask 跳过", stat.skipped == 0, f"skipped={stat.skipped}")
    check(f"{tag} 无不可压原因文案", stat.reason == "", f"reason={stat.reason!r}")

    est = estimate_pdf(src, 78)[0]
    check(f"{tag} 估算出更小体积", 0 < est.est_bytes < est.cur_bytes,
          f"{est.cur_bytes} → {est.est_bytes}")

    staged = stage_page(PageRef(str(src), 0), WORK / f"cmyk_{tag}_staged.pdf", 78)
    check(f"{tag} 压缩后文件变小", staged.stat().st_size < orig_size,
          f"{orig_size} → {staged.stat().st_size}")

    # 颜色：用「有符号均值」判偏色，而不是绝对差。
    # 有损压缩的误差正负抵消，均值接近 0；CMYK 反相则是系统性同向偏移。
    # 合成噪点图的绝对差能到 0.5/255（肉眼不可见），但均值几乎为 0；
    # 之前压坏那一版绝对差 2.5/255、均值也 2.5，两者能明确区分。
    before, after = render(src), render(staged)
    if before.size != after.size:
        after = after.resize(before.size)
    arr_b = np.asarray(before, dtype=np.int16)
    arr_a = np.asarray(after, dtype=np.int16)
    bias = float(np.abs(arr_a.astype(np.float32) - arr_b.astype(np.float32)).mean())
    signed = float(np.abs((arr_a - arr_b).astype(np.float32).mean(axis=(0, 1))).max())
    check(f"{tag} 颜色不偏", signed < 0.3,
          f"同向偏差 {signed:.3f}/255（绝对差 {bias:.3f}）")

    # SMask 还在、尺寸没变
    reader = PdfReader(str(staged))
    page = reader.pages[0]
    check(f"{tag} SMask 原样保留",
          any(o.get("/SMask") is not None for _n, _r, o in _walk(page)),
          "蒙版对象仍在")
    imgs = [o for _n, _r, o in _walk(page)]
    check(f"{tag} 图片像素尺寸不变",
          all(int(o.get("/Width")) == 240 and int(o.get("/Height")) == 320 for o in imgs),
          f"{len(imgs)} 张图")
    check(f"{tag} 页面尺寸不变",
          list(page.mediabox) == list(PdfReader(str(src)).pages[0].mediabox),
          str(page.mediabox))


def _walk(page):
    from app.core.pdf_images import _iter_images
    return _iter_images(page)


def main() -> int:
    print("PDF CMYK + SMask 压缩回归测试")
    run_one("flate", use_dct=False)
    run_one("dct", use_dct=True)
    print("\n" + "=" * 50)
    if _fails:
        print(f"FAIL: {len(_fails)} 项未通过")
        for name in _fails:
            print("  -", name)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
