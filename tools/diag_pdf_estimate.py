"""诊断：PDF 单页压缩时格子一直显示「估算中」的问题。

跑法：python tools/diag_pdf_estimate.py
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

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.pdf_images import estimate_pdf, scan_pdf  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_diag_estimate"
WORK.mkdir(parents=True, exist_ok=True)


def make_pdfs() -> tuple[Path, Path, Path]:
    text = WORK / "纯文字.pdf"
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((60, 90), "no image here", fontsize=20)
    doc.save(str(text))
    doc.close()

    scan = WORK / "扫描页.pdf"
    big = WORK / "big.jpg"
    Image.new("RGB", (2400, 3200), (200, 180, 150)).save(big, quality=95)
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)
    p.insert_image(pymupdf.Rect(40, 40, 555, 802), filename=str(big))
    doc.save(str(scan))
    doc.close()
    return text, scan, big


def sub_of(win, uid: str) -> str:
    item = win.pdf_grid._item_of(uid)
    tip = item.toolTip() if item is not None else ""
    return tip.split("\n", 1)[1] if "\n" in tip else ""


def main() -> int:
    text, scan, _big = make_pdfs()

    print("== core 扫描 ==")
    for path in (text, scan):
        t0 = time.perf_counter()
        stats = scan_pdf(path)
        dt = time.perf_counter() - t0
        print(f"  {path.name}: scan {dt:.3f}s -> {stats}")
        t0 = time.perf_counter()
        est = estimate_pdf(path, 78)
        dt = time.perf_counter() - t0
        print(f"  {path.name}: estimate {dt:.3f}s -> {est}")

    print("== 界面 ==")
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    win._pdf_add_paths([text, scan])
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)

    t_uid = next(it.uid for it in win.pdf_items if it.ref.src == str(text))
    s_uid = next(it.uid for it in win.pdf_items if it.ref.src == str(scan))
    print(f"  纯文字页初始副标题: {sub_of(win, t_uid)!r}")
    print(f"  扫描页初始副标题: {sub_of(win, s_uid)!r}")

    win._pdf_begin_compress([t_uid])
    print(f"  纯文字页刚点压缩: {sub_of(win, t_uid)!r}  hint={win.pdf_zip_hint.text()!r}")
    for i in range(150):
        app.processEvents()
        time.sleep(0.02)
        if i in (10, 50, 149):
            print(
                f"  {(i+1)*0.02:.1f}s: 副标题={sub_of(win, t_uid)!r} "
                f"stats={win._pdf_stats.get((str(text), 0))}"
            )

    win._pdf_zip_close()
    win._pdf_begin_compress([s_uid])
    for i in range(150):
        app.processEvents()
        time.sleep(0.02)
        if i in (10, 50, 149):
            print(
                f"  扫描页 {(i+1)*0.02:.1f}s: 副标题={sub_of(win, s_uid)!r} "
                f"stats={win._pdf_stats.get((str(scan), 0))}"
            )

    win._pdf_drop_staged()
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
