"""黄色「不可压缩」角标 / 预估缓存防卡顿 / 矢量页判定文案 的离屏实跑测试。

锁住的承诺：

  1. 压缩过程中，判定不可压缩的页挂黄色「不可压缩」角标；可压页不挂
  2. 拖质量条只查缓存做比例缩放，不在 UI 线程真编码 —— 用调用计数验证
  3. 后台精确估算回来后，预估数字精确更新
  4. 矢量页（无位图）原因写「本页无位图（矢量/文字）」；
     图片已极小的页原因写「已极小」，不再含糊写「不可压缩」
  5. 用真实的印刷设计稿 PDF（辉凌达必佳三折页）验证 3/4/5/7/8 页判定

跑法：python tools/test_pdf_badge_and_est.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

import app.core.image as _image  # noqa: E402
from app.core.pdf_images import estimate_pdf, scan_pdf  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.page_grid import BADGE_ROLE, BADGE_TONE_ROLE  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_badge_est"
USER_PDF = Path(r"D:/Workbuddy Workspace/gpu-video-encoder") / "辉凌 达必佳3.75DA封套式+插页g 出血2mm-三折页 20261104.pdf"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 40, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def wait_est(win, app, timeout: float = 60.0) -> None:
    """等到所有选中项的预估都不是「估算中」或超时。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        pump(app, 5)
        if not win._pdf_compress_uids:
            return
        pending = False
        for uid in win._pdf_compress_uids:
            it = win.pdf_by_uid.get(uid)
            if it is None:
                continue
            pair = win._pdf_pair_cache.get(it.uid) or ""
            if "估算中" in pair:
                pending = True
                break
        if not pending:
            # 再跑一轮事件，让后台线程的缓存都落地
            pump(app, 10)
            return


def badge_of(win, uid: str) -> tuple[str, str]:
    item = win.pdf_grid._item_of(uid)
    if item is None:
        return "", ""
    return (item.data(BADGE_ROLE) or ""), (item.data(BADGE_TONE_ROLE) or "")


def make_vector_pdf() -> Path:
    """造一页纯矢量图表 PDF（无任何 /Image），模拟用户看到的柱状图页。"""
    import pymupdf

    WORK.mkdir(parents=True, exist_ok=True)
    pdf = WORK / "矢量图表.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    for i in range(12):
        x = 30 + i * 28
        h = 40 + (i * 37) % 160
        page.draw_rect(pymupdf.Rect(x, 260 - h, x + 18, 260), color=(0.8, 0.3, 0.1), fill=(0.85, 0.45, 0.15))
    page.insert_text((30, 40), "vector chart page", fontsize=16)
    doc.save(str(pdf))
    doc.close()
    return pdf


def make_tiny_image_pdf() -> Path:
    """造一页只有极小位图的 PDF（几十字节级），模拟"已极小压不动"。"""
    import io

    import pymupdf
    from PIL import Image

    WORK.mkdir(parents=True, exist_ok=True)
    img = Image.new("L", (16, 16), 128)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    pdf = WORK / "极小图.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(pymupdf.Rect(10, 10, 26, 26), stream=buf.getvalue())
    doc.save(str(pdf))
    doc.close()
    return pdf


def make_photo_pdf() -> Path:
    """造一页带大位图的 PDF —— 有可压图片，预估数字应随质量变化。"""
    import numpy as np
    import pymupdf
    from PIL import Image

    WORK.mkdir(parents=True, exist_ok=True)
    jpg = WORK / "photo_src.jpg"
    rng = np.random.default_rng(23)
    arr = rng.integers(30, 220, (1000, 800, 3), dtype="uint8")
    Image.fromarray(arr, "RGB").save(jpg, quality=95)
    pdf = WORK / "带照片.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=320)
    page.insert_image(pymupdf.Rect(10, 10, 390, 310), filename=str(jpg))
    doc.save(str(pdf))
    doc.close()
    return pdf


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()

    # ---------------------------------------------------------------- 1-4：合成 PDF
    print("\n[1] 合成 PDF：矢量页与极小图页的判定文案")
    vec = make_vector_pdf()
    tiny = make_tiny_image_pdf()
    photo = make_photo_pdf()

    vs = scan_pdf(vec)[0]
    check("矢量页原因说明是矢量/文字", "矢量" in vs.reason or "无位图" in vs.reason, vs.reason)
    check("矢量页不可压缩", not vs.compressible, vs.label())

    te = estimate_pdf(tiny, 78)[0]
    check(
        "极小图页原因写「已极小」",
        "已极小" in te.reason or "无可压缩" in te.reason,
        te.reason,
    )
    check("极小图页不可压缩", not te.compressible, te.label())

    pe = estimate_pdf(photo, 78)[0]
    check("照片页可压缩", pe.compressible, pe.label())

    # ---------------------------------------------------------------- 黄色角标
    print("\n[2] 黄色「不可压缩」角标")
    # 再加一张独立 JPG —— PDF 队列也收图片文件，走图片预估缓存路径
    import numpy as np
    from PIL import Image as _PIL

    WORK.mkdir(parents=True, exist_ok=True)
    jpg = WORK / "队列图片.jpg"
    rng = np.random.default_rng(31)
    arr = rng.integers(20, 230, (900, 700, 3), dtype="uint8")
    _PIL.fromarray(arr, "RGB").save(jpg, quality=94)

    win._pdf_add_paths([vec, tiny, photo, jpg])
    pump(app, 60)
    check("导入 4 页", len(win.pdf_items) == 4, str(len(win.pdf_items)))
    uids = [it.uid for it in win.pdf_items]
    win._pdf_begin_compress(uids)
    wait_est(win, app, 60.0)
    pump(app, 10)

    for uid in uids:
        text, tone = badge_of(win, uid)
        it = win.pdf_by_uid[uid]
        st = win._pdf_stats.get((it.ref.src, it.ref.index))
        label = it.ref.src.split("/")[-1][:10]
        if st is not None and not st.compressible:
            check(
                f"不可压缩页挂黄标（{label}）",
                text == "不可压缩" and tone == "warn",
                f"text={text!r} tone={tone!r} reason={st.reason!r}",
            )
        else:
            check(
                f"可压页不挂黄标（{label}）",
                text == "",
                f"text={text!r} tone={tone!r}",
            )

    # ---------------------------------------------------------------- 预估缓存防卡顿
    print("\n[3] 拖质量条不在 UI 线程真编码")
    # 记录 preview_compress_bytes 被调用的次数 —— 只应由后台线程调用
    calls: list[int] = []
    real_preview = _image.preview_compress_bytes

    def counting_preview(*a, **kw):
        calls.append(1)
        return real_preview(*a, **kw)

    _image.preview_compress_bytes = counting_preview
    # 同时把 main_window 里的引用也换掉（它 from ... import 了一份）
    import app.ui.main_window as mw

    mw.preview_compress_bytes = counting_preview

    before = len(calls)
    # 模拟拖动质量条：连改 20 档，每档都触发 valueChanged。
    # 此时缓存里已有 q=78 的精确值，拖动全程只做比例缩放，不该真编码
    for q in range(40, 60, 1):
        win.pdf_zip_quality.setValue(q)
        win._pdf_zip_on_quality(q)
    drag_calls = len(calls) - before
    check(
        "拖动 20 档的质量条 UI 线程零编码",
        drag_calls == 0,
        f"UI 线程触发了 {drag_calls} 次真编码",
    )

    # 清掉缓存，模拟"新质量没有精确值"，松手后的后台估算应该真编码。
    # 注意：图片缓存只管队列里的图片文件（kind=image），PDF 内嵌图走 PageStat
    win._pdf_img_est_cache.clear()
    win.pdf_zip_quality.setValue(77)
    win._pdf_zip_estimate()
    t0 = time.time()
    while len(calls) <= before and time.time() - t0 < 60:
        pump(app, 5)
    check(
        "后台线程完成精确预估",
        len(calls) > before,
        f"后台编码 {len(calls) - before} 次",
    )
    # 后台结果必须进缓存
    pump(app, 20)
    img_its = [it for it in win.pdf_items if it.ref.kind == "image"]
    if img_its:
        src = win._pdf_effective_ref(img_its[0]).src
        check(
            "后台结果写入预估缓存",
            (src, 77) in win._pdf_img_est_cache or any(
                s == src for (s, _q) in win._pdf_img_est_cache
            ),
            f"cache keys={list(win._pdf_img_est_cache)[:4]}",
        )
    wait_est(win, app, 30.0)

    # 拖到别的质量，队列图片的预估数字应该立即变化（比例缩放）
    photo_uid = img_its[0].uid if img_its else uids[0]
    win.pdf_zip_quality.setValue(90)
    win._pdf_zip_on_quality(90)
    pump(app, 5)
    pair90 = win._pdf_pair_cache.get(photo_uid) or ""
    win.pdf_zip_quality.setValue(50)
    win._pdf_zip_on_quality(50)
    pump(app, 5)
    pair50 = win._pdf_pair_cache.get(photo_uid) or ""
    check(
        "拖动时照片页预估数字跟着变",
        pair90 != pair50 and "→" in pair50,
        f"q90={pair90!r} q50={pair50!r}",
    )

    _image.preview_compress_bytes = real_preview
    mw.preview_compress_bytes = real_preview

    # ---------------------------------------------------------------- 5：真实用户 PDF
    print("\n[4] 真实印刷设计稿 PDF（辉凌达必佳三折页）")
    if not USER_PDF.exists():
        check("找到用户 PDF", False, str(USER_PDF))
    else:
        stats = estimate_pdf(USER_PDF, 78)
        # 用户说 3/4/5/7/8 页不可压缩 —— 1-indexed → 0-indexed 2/3/4/6/7
        for p1 in (3, 4, 5, 7, 8):
            st = stats[p1 - 1]
            check(
                f"第 {p1} 页判定为不可压缩",
                not st.compressible,
                f"count={st.count} reason={st.reason!r}",
            )
        st3 = stats[2]
        check(
            "第 3 页原因写「已极小」而非含糊的不可压缩",
            "已极小" in st3.reason or "无可压缩" in st3.reason,
            st3.reason,
        )
        for p1 in (4, 5, 7, 8):
            st = stats[p1 - 1]
            check(
                f"第 {p1} 页原因写「无位图」",
                "无位图" in st.reason or "矢量" in st.reason,
                st.reason,
            )
        # 可压的页必须仍然可压（不能被误伤）
        check("第 1 页仍可压", stats[0].compressible, stats[0].label())
        check("第 2 页仍可压", stats[1].compressible, stats[1].label())
        check("第 6 页仍可压", stats[5].compressible, stats[5].label())

    # ---------------------------------------------------------------- 收尾
    print("\n[5] 清理")
    win._pdf_zip_close()
    win.quit_app()
    pump(app, 10)
    import shutil

    shutil.rmtree(WORK, ignore_errors=True)

    print(f"\n{'=' * 50}")
    if _fails:
        print(f"RESULT = FAIL（{len(_fails)} 项失败）")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("RESULT = PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
