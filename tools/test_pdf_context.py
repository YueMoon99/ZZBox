"""PDF 队列右键菜单 / 图片压缩 / Ctrl+Z 的离屏实跑测试。

真起 MainWindow、真导入文件、真跑 ffmpeg 压缩。因为这一轮改的全是
信号连线、临时文件和队列指针，只靠 py_compile 看不出对错。

跑法：python tools/test_pdf_context.py
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

from app.ui.main_window import MainWindow  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_pdf_context"
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
    import pymupdf
    from PIL import Image, ImageDraw

    WORK.mkdir(parents=True, exist_ok=True)
    pdf = WORK / "测试.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((60, 90), f"第 {i + 1} 页", fontsize=18)
        page.draw_rect(pymupdf.Rect(60, 130, 500, 400), color=(0.2, 0.4, 0.7), width=2)
    doc.save(str(pdf))
    doc.close()

    png = WORK / "照片.jpg"   # 用 JPG 才看得出质量条的效果；PNG 是无损的
    im = Image.new("RGB", (900, 600), (245, 238, 220))
    d = ImageDraw.Draw(im)
    for x in range(0, 900, 7):
        d.line((x, 0, x, 600), fill=(180 + x % 60, 150, 110), width=1)
    for y in range(0, 600, 9):
        d.line((0, y, 900, y), fill=(120, 170 + y % 60, 130), width=1)
    im.save(png, quality=95)
    return pdf, png


def main() -> int:
    print("== 样本 ==")
    pdf, png = make_samples()
    print(f"  {pdf.name}  {png.name}")

    print("== 启动 ==")
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    pump(app, 10)

    win._pdf_add_paths([pdf, png])
    pump(app, 60)
    items = list(win.pdf_items)
    check("队列条目数", len(items) == 4, f"实际 {len(items)}")
    pdf_it = next(it for it in items if it.ref.kind == "pdf")
    img_it = next(it for it in items if it.ref.kind == "image")

    print("== 问题 5：格子下方体积 ==")
    psub = sub_of(win, pdf_it.uid)
    isub = sub_of(win, img_it.uid)
    check("PDF 页显示 pdf文件", psub == "pdf文件", repr(psub))
    check("图片显示体积", "KB" in isub or "MB" in isub, repr(isub))

    print("== 问题 6：右键 → 压缩条 → 实时预估 ==")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    captured: dict[str, list[str]] = {}
    import app.ui.main_window as mw

    real_menu = mw.QMenu

    class CapturingMenu(QMenu):
        def exec(self, _pos=None):
            captured["items"] = [a.text() for a in self.actions()]
            return None

    # PySide6 包装类上直接改 QMenu.exec 不生效，菜单仍然会真弹出来卡住测试。
    # 换掉主窗口模块里的 QMenu 名字，才会走到我们的假实现。
    mw.QMenu = CapturingMenu
    try:
        win._pdf_context_menu([img_it.uid], QPoint(10, 10))
    finally:
        mw.QMenu = real_menu
    items_text = captured.get("items", [])
    for label in ("旋转选中 90°", "导出选中…", "压缩选中…", "删除选中", "撤销  Ctrl+Z"):
        check(f"右键菜单有「{label}」", label in items_text, str(items_text))

    win._pdf_begin_compress([img_it.uid, pdf_it.uid])
    pump(app, 5)
    check("压缩条出现", not win.pdf_zip_panel.isHidden())
    win.pages.setCurrentIndex(2)
    pump(app, 5)
    shot = ROOT / "docs" / "images" / "pdf-compress.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    win.grab().save(str(shot))
    print(f"  截图 → {shot.name}")
    before = sub_of(win, img_it.uid)
    win.pdf_zip_quality.setValue(50)
    pump(app, 5)
    after = sub_of(win, img_it.uid)
    check("图片预估是 88kb→66kb 形式", "→" in after and after.endswith("kb"), repr(after))
    check("拖动质量条数字变化", before != after, f"{before!r} → {after!r}")
    win.pdf_zip_quality.setValue(30)
    pump(app, 5)
    check("再拖一次仍变化", sub_of(win, img_it.uid) != after)

    print("== 问题 4：确认压缩 ==")
    original = Path(img_it.ref.src).read_bytes()
    original_path = img_it.ref.src
    win._pdf_zip_confirm()
    for _ in range(300):
        app.processEvents()
        time.sleep(0.02)
        if not win.pdf_runner.busy():
            break
    pump(app, 10)
    new_it = win.pdf_by_uid[img_it.uid]
    new_src = Path(new_it.ref.src)
    check("压缩完成", not win.pdf_runner.busy(), win.current_label.text())
    check(
        "压缩件在软件目录的临时文件夹",
        new_src.is_file() and str(new_src).startswith(str(ROOT)),
        str(new_src),
    )
    check("压缩件不是原图", new_src.resolve() != Path(original_path).resolve())
    check("原图未被覆盖", Path(original_path).read_bytes() == original)
    check("队列指针已换成压缩件", new_it.staged == str(new_src))
    check("压缩条已收起", win.pdf_zip_panel.isHidden())
    check("格子上标出已压缩", sub_of(win, img_it.uid).startswith("已压缩"), sub_of(win, img_it.uid))

    print("== 压缩后仍能导出 ==")
    from pypdf import PdfReader

    # 导出名带分钟级时间戳，同一分钟内重跑会撞名 —— 先清空旧导出，
    # 再按「本轮生成的文件 → 内容」比对，避免假失败。
    for old in WORK.glob("导出验证*.pdf"):
        try:
            old.unlink()
        except OSError:
            pass
    win._pdf_run_pdf_one([it.ref for it in win.pdf_items], stem="导出验证")
    for _ in range(300):
        app.processEvents()
        time.sleep(0.02)
        if not win.pdf_runner.busy():
            break
    pump(app, 5)
    made = list(WORK.glob("导出验证*.pdf"))
    check("混合队列导出成功", bool(made), str(win.current_label.text()))
    if made:
        check("导出页数正确", len(PdfReader(str(made[0])).pages) == 4)

    print("== 问题 7：Ctrl+Z 回退 ==")
    win._pdf_undo()
    pump(app, 10)
    back = win.pdf_by_uid[img_it.uid]
    check("撤销换回原图", back.ref.src == original_path, back.ref.src)
    check("撤销后格子恢复体积", "KB" in sub_of(win, img_it.uid) or "MB" in sub_of(win, img_it.uid))

    n0 = len(win.pdf_items)
    win._pdf_delete_selected([img_it.uid])
    pump(app, 5)
    check("删除生效", len(win.pdf_items) == n0 - 1)
    win._pdf_undo()
    pump(app, 5)
    check("删除也能撤销", len(win.pdf_items) == n0)

    print("== 退出清理 ==")
    stage = win._pdf_stage_dir
    win._pdf_drop_staged()
    check("软件目录里的临时文件夹已删除", stage is not None and not stage.exists(), str(stage))

    win.close()
    print("\n" + ("全部通过" if not _fails else f"失败 {len(_fails)} 项：{_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
