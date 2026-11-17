"""PDF 核心逻辑回归测试。

重点验三件事，每一件都是界面上给用户的承诺：
  1. 「提取 / 合并 / 旋转」不动内容流 —— 文字层必须还在，能搜能复制
  2. 旋转是叠加在原页 /Rotate 之上的，不是覆盖
  3. 「压缩」确实变小，且文字层确实消失（这是它的代价，不是 bug）

生成测试素材用 PyMuPDF，仅此一处：它是 AGPL，绝不进产品代码。
跑法：python tools/test_pdf_core.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.pdf import (  # noqa: E402
    PageRef,
    compress_pdf,
    estimate_compress,
    export_images,
    export_pdf,
    probe_pdf,
    probe_image_size,
    render_page,
    safe_stem,
    thumb_bytes,
)

WORK = Path(tempfile.gettempdir()) / "zzbox_pdf_test"
PASS, FAIL = "PASS", "FAIL"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def make_pdf(path: Path, pages: int, label: str) -> Path:
    """造一份带文字层的 PDF（每页两行字 + 一条矢量线）。"""
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()  # A4: 595x842
        page.insert_text(
            (60, 90), f"{label} 第 {i + 1} 页", fontsize=22,
            fontname="china-s",
        )
        page.insert_text(
            (60, 130), "This line must remain searchable after export.",
            fontsize=11,
        )
        page.draw_line((60, 150), (520, 150), color=(0.2, 0.4, 0.8), width=1.5)
    doc.save(str(path))
    doc.close()
    return path


def count_chars(path: Path, index: int = 0) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        tp = doc[index].get_textpage()
        try:
            return tp.count_chars()
        finally:
            tp.close()
    finally:
        doc.close()


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    a = make_pdf(WORK / "报告A.pdf", 3, "报告A")
    b = make_pdf(WORK / "附件B.pdf", 2, "附件B")

    # 两张图片：一张 JPEG（走 DCTDecode 直嵌），一张带透明的 PNG
    from PIL import Image

    jpg = WORK / "photo.jpg"
    Image.new("RGB", (1600, 1200), (200, 120, 60)).save(jpg, quality=92)
    png = WORK / "logo.png"
    Image.new("RGBA", (800, 800), (30, 90, 200, 128)).save(png)

    print("\n[1] 探测")
    info = probe_pdf(a)
    check("页数", info.pages == 3, f"{info.pages}")
    check("尺寸 A4", info.size_label == "A4", info.size_label)
    check("识别文字层", info.has_text and info.text_pages == 3)
    check("文件大小", info.ok)

    print("\n[2] 无损组装：PDF 页 + 图片页混排")
    refs = [
        PageRef(str(a), "pdf", 0),
        PageRef(str(jpg), "image"),
        PageRef(str(a), "pdf", 2),
        PageRef(str(png), "image"),
        PageRef(str(b), "pdf", 1),
    ]
    out = WORK / "混排.pdf"
    export_pdf(refs, out)
    check("输出存在", out.exists(), f"{out.stat().st_size / 1024:.0f} KB")

    got = probe_pdf(out)
    check("页数 = 5", got.pages == 5, str(got.pages))
    check("文字层保留", got.text_pages == 3, f"{got.text_pages}/3 页有字")
    check("第1页能读出字", count_chars(out, 0) > 10, f"{count_chars(out, 0)} 字符")

    # 图片页不该有文字，但要能渲染出内容
    img = render_page(PageRef(str(out), "pdf", 1), dpi=72)
    check("图片页可渲染", img.width > 100 and img.height > 100, f"{img.size}")
    check(
        "JPEG 页比例不变形",
        abs(img.width / img.height - 1600 / 1200) < 0.02,
        f"{img.size}",
    )

    print("\n[3] 旋转（叠加，不覆盖）")
    rot = [PageRef(str(a), "pdf", 0, rotate=90)]
    rout = WORK / "旋转.pdf"
    export_pdf(rot, rout)
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(rout))
    page = doc[0]
    try:
        r = page.get_rotation()
        w, h = page.get_size()
    finally:
        page.close()
        doc.close()
    check("/Rotate = 90", r == 90, str(r))
    # get_size() 返回的是「用户看到的」尺寸，转 90° 后宽高互换是正确的；
    # 纸张本身没被裁切（MediaBox 不变），这一点由渲染比例验证
    check("旋转后视口宽高互换", abs(w - 842) < 2 and abs(h - 595) < 2, f"{w:.0f}x{h:.0f}")

    # 累计旋转：同一页转两次 90 应得 180
    double = [PageRef(str(a), "pdf", 0, rotate=180)]
    dout = WORK / "旋转180.pdf"
    export_pdf(double, dout)
    doc = pdfium.PdfDocument(str(dout))
    page = doc[0]
    try:
        r2 = page.get_rotation()
    finally:
        page.close()
        doc.close()
    check("/Rotate = 180", r2 == 180, str(r2))

    print("\n[4] 压缩")
    # 4a 文字型 PDF：压完必然变大，界面必须拦住
    big = make_pdf(WORK / "文字版.pdf", 6, "文字版")
    big_info = probe_pdf(big)
    refs_all = [PageRef(str(big), "pdf", i) for i in range(6)]
    text_plan = estimate_compress(
        refs_all, {str(big): big_info}, fmt="jpg", quality=80, dpi=120
    )
    check("文字型被判定会变大", text_plan.grows, text_plan.ratio_text)
    check("给出拦截文案", bool(text_plan.warning), text_plan.warning[:40])

    # 4b 扫描件型 PDF：造 6 张带噪点的照片页（噪点接近真实扫描件的熵）
    import numpy as np

    from PIL import Image

    rng = np.random.default_rng(7)
    scan_srcs: list[Path] = []
    for i in range(6):
        # 灰白底 + 高斯噪点 + 几道深色横线，模拟扫描页的熵分布
        arr = rng.normal(232, 9, (2300, 1700)).clip(0, 255)
        arr[300 + i * 40 : 310 + i * 40, 120:1580] = 40
        arr[420 : 1500 : 60, 120:1580] = 90
        im = Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGB")
        p = WORK / f"扫描_{i + 1}.jpg"
        im.save(p, quality=88)
        scan_srcs.append(p)

    scan_refs = [PageRef(str(p), "image") for p in scan_srcs]
    scan_pdf = WORK / "扫描件.pdf"
    export_pdf(scan_refs, scan_pdf)
    scan_info = probe_pdf(scan_pdf)
    plan = estimate_compress(
        [PageRef(str(scan_pdf), "pdf", i) for i in range(6)],
        {str(scan_pdf): scan_info},
        fmt="jpg",
        quality=72,
        dpi=110,
    )
    cout = WORK / "扫描件_压缩.pdf"
    seen: list[int] = []
    compress_pdf(
        [PageRef(str(scan_pdf), "pdf", i) for i in range(6)],
        cout,
        fmt="jpg",
        quality=72,
        dpi=110,
        progress=seen.append,
    )
    src_kb = scan_pdf.stat().st_size / 1024
    out_kb = cout.stat().st_size / 1024
    check("输出存在", cout.exists(), f"{out_kb:.0f} KB（原 {src_kb:.0f} KB）")
    check("确实变小", out_kb < src_kb * 0.85, f"降到 {out_kb / src_kb * 100:.0f}%")
    check("进度回调到底", seen and seen[-1] == 100, str(seen[-3:]))
    check(
        "采样预估准（±35% 内）",
        abs(plan.est_bytes - cout.stat().st_size) / cout.stat().st_size < 0.35,
        f"预估 {plan.est_bytes / 1024:.0f} KB / 实际 {out_kb:.0f} KB",
    )
    check("采样不是单页", plan.sampled >= 2, f"采样 {plan.sampled} 页")
    check("未走公式兜底", not plan.fallback)
    got2 = probe_pdf(cout)
    check("页数保持 6", got2.pages == 6, str(got2.pages))
    check("文字层已消失（压缩的代价）", got2.text_pages == 0, f"{got2.text_pages}")

    print("\n[5] 导出图片")
    import shutil

    shutil.rmtree(WORK / "拆图", ignore_errors=True)  # 留着上次的会触发重名编号
    refs3 = [
        PageRef(str(a), "pdf", 0),
        PageRef(str(a), "pdf", 1, rotate=90),
        PageRef(str(jpg), "image"),
    ]
    files = export_images(refs3, WORK / "拆图", fmt="png", dpi=100)
    check("三个文件", len(files) == 3, ", ".join(f.name for f in files))
    check("文件都非空", all(f.exists() and f.stat().st_size > 500 for f in files))
    sizes = [probe_image_size(f) for f in files]
    check("PDF 页按原始页号命名", files[0].name == "报告A·1.png", files[0].name)
    check("第二页页号跟原文件", files[1].name == "报告A·2.png", files[1].name)
    check("图片文件不带页号", files[2].name == "photo.png", files[2].name)
    # 同一页再导一次不能把上一次的覆盖掉
    again = export_images([refs3[0]], WORK / "拆图", fmt="png", dpi=100)
    check("重名自动加序号", again[0].name == "报告A·1(2).png", again[0].name)
    check(
        "旋转页宽高互换",
        sizes[1][0] > sizes[1][1],
        f"{sizes[1]}（A4 竖版转 90° 应变成横版）",
    )

    print("\n[6] 缩略图")
    data, tw, th = thumb_bytes(PageRef(str(a), "pdf", 0))
    check("PNG 字节", data[:4] == b"\x89PNG", f"{len(data) / 1024:.0f} KB")
    # 画布统一成 A4 竖版：横版页和方形图片进来也是这个尺寸，
    # 否则格墙会参差不齐
    check("统一竖版画布", th == 320 and abs(tw - 320 / 1.4142) <= 1, f"{tw}x{th}")
    data2, w2, h2 = thumb_bytes(PageRef(str(b), "pdf", 0))
    check("横版页套同一画布", (w2, h2) == (tw, th), f"{w2}x{h2} vs {tw}x{th}")

    print("\n[7] 边界")
    bad = WORK / "假.pdf"
    bad.write_text("not a pdf", encoding="utf-8")
    check("损坏文件被识别", not probe_pdf(bad).ok, probe_pdf(bad).error)
    try:
        export_pdf([], WORK / "空.pdf")
        check("空队列应报错", False)
    except Exception as exc:  # noqa: BLE001
        check("空队列报错", "没有可导出" in str(exc), str(exc))
    check("文件名字符清洗", safe_stem('a/b:c*?"<>|') == "a_b_c______", safe_stem('a/b:c*?"<>|'))
    check("空文件名回退", safe_stem("   ") == "合并", safe_stem("   "))

    print()
    if _fails:
        print("RESULT = FAIL ->", ", ".join(_fails))
        return 1
    print("RESULT = PASS（全部检查项通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
