"""PDF 单页压缩估算状态的离屏测试。

专测「纯文字页一直显示估算中」这个坑，以及估算抛错时能不能给出明确提示。

跑法：python tools/test_pdf_estimate_status.py
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

from app.ui.main_window import MainWindow  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_estimate_status"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 40, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def sub_of(win, uid: str) -> str:
    item = win.pdf_grid._item_of(uid)
    tip = item.toolTip() if item is not None else ""
    return tip.split("\n", 1)[1] if "\n" in tip else ""


def make_samples() -> tuple[Path, Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    text = WORK / "纯文字.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((60, 90), "no image", fontsize=20)
    doc.save(str(text))
    doc.close()

    scan = WORK / "扫描页.pdf"
    big = WORK / "big.jpg"
    Image.new("RGB", (1200, 1600), (210, 190, 160)).save(big, quality=92)
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_image(
        pymupdf.Rect(40, 40, 555, 802), filename=str(big)
    )
    doc.save(str(scan))
    doc.close()
    return text, scan


def main() -> int:
    text, scan = make_samples()
    app = QApplication.instance() or QApplication([])

    print("== 纯文字页：不再永远显示估算中 ==")
    win = MainWindow()
    win.show()
    win._pdf_add_paths([text, scan])
    pump(app, 40)
    t_uid = next(it.uid for it in win.pdf_items if it.ref.src == str(text))
    s_uid = next(it.uid for it in win.pdf_items if it.ref.src == str(scan))

    win._pdf_begin_compress([t_uid])
    pump(app, 40)
    check("副标题给出原因", sub_of(win, t_uid) == "本页无图片", sub_of(win, t_uid))
    check("不再写估算中", "估算中" not in sub_of(win, t_uid))
    check(
        "提示行说明保持原样",
        "没有可压缩" in win.pdf_zip_hint.text(),
        win.pdf_zip_hint.text(),
    )

    import app.ui.main_window as mw

    real_info = mw.QMessageBox.information
    shown: list[str] = []

    def fake_info(_parent, _title, text, *_args):
        shown.append(text)

    mw.QMessageBox.information = fake_info
    try:
        win._pdf_zip_confirm()
    finally:
        mw.QMessageBox.information = real_info
    pump(app, 10)
    check("纯文字页不启动压缩", not win.pdf_runner.busy())
    check("给出解释弹窗", bool(shown), str(shown))

    print("== 扫描页：仍能正常估算并压缩 ==")
    win._pdf_begin_compress([s_uid])
    pump(app, 40)
    check("副标题显示体积对照", "→" in sub_of(win, s_uid), sub_of(win, s_uid))
    check("提示行给出省量", "省" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())

    print("== 估算抛错：显示估算失败 ==")
    real_est = mw.estimate_pdf

    def boom(*_args, **_kwargs):
        raise RuntimeError("测试注入的估算失败")

    mw.estimate_pdf = boom
    try:
        win2 = MainWindow()
        win2.show()
        win2._pdf_add_paths([scan])
        pump(app, 40)
        uid = win2.pdf_items[0].uid
        # 清掉上一窗口缓存不到的那份，强制重算
        win2._pdf_begin_compress([uid])
        pump(app, 40)
        check("失败后不再挂估算中", "估算中" not in sub_of(win2, uid), sub_of(win2, uid))
        check("明确标出失败", "失败" in sub_of(win2, uid), sub_of(win2, uid))
        win2._pdf_drop_staged()
        win2.close()
    finally:
        mw.estimate_pdf = real_est

    win._pdf_drop_staged()
    win.close()
    print("\n" + ("全部通过" if not _fails else f"失败 {len(_fails)} 项：{_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
