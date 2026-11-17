"""PDF 压缩区（四态）界面实跑测试。

压缩区有四个状态，每个状态显示的控件不同，靠信号和后台估算串起来 ——
这种东西只读代码没法确认，必须真起窗口点一遍：

  off  未启用   → 【启用压缩功能】+ "压缩功能未启用"
  pick 选方式   → 【压缩部分】【压缩全部】
  all  压缩全部 → 质量条 + 每页「当前 → 预估」，导出时才真压
  part 压缩部分 → 质量条 + 【压缩选中】，压完自动回 off

跑法：python tools/test_pdf_zip_ui.py
产出：docs/images/pdf-zip.png
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

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.style import build_qss, pick_font  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_pdf_zip_ui"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 20, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def wait_for(app, cond, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        pump(app, 3, 0.02)
        if cond():
            return True
    return False


def make_scan(path: Path, pages: int = 2) -> Path:
    """扫描件风格：每页一张大噪点图 + 一行真文字。"""
    rng = np.random.default_rng(11)
    arr = rng.integers(85, 215, (1200, 1600, 3), dtype="uint8")
    arr[:200, :, :] = 245
    jpg = WORK / "scan.jpg"
    Image.fromarray(arr, "RGB").save(jpg, quality=95)

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 80), f"扫描页 {i + 1} 的文字层", fontsize=16, fontname="china-s")
        page.insert_image(pymupdf.Rect(50, 120, 545, 700), filename=str(jpg))
    doc.save(str(path))
    doc.close()
    return path


def make_text(path: Path) -> Path:
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 90), f"纯文字页 {i + 1}", fontsize=18, fontname="china-s")
        page.insert_text((60, 130), "no images on this page", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def sub_of(win, uid: str) -> str:
    """读格子的副标题（尺寸行）。"""
    from app.ui.page_grid import SUB_ROLE

    item = win.pdf_grid._item_of(uid)
    return (item.data(SUB_ROLE) if item is not None else "") or ""


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    family = pick_font().strip('"')
    for font in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if Path(font).exists():
            QFontDatabase.addApplicationFont(font)
    app.setFont(QFont(family, 9))
    app.setStyleSheet(build_qss())

    WORK.mkdir(parents=True, exist_ok=True)
    scan = make_scan(WORK / "扫描件.pdf", 2)
    text = make_text(WORK / "文字版.pdf")

    win = MainWindow()
    win.resize(1180, 812)
    win.show()
    pump(app, 10)
    win._set_mode(2)
    pump(app, 6)

    print("\n[1] 导入扫描件 + 文字版（共 4 页）")
    win._pdf_add_paths([scan, text])
    pump(app, 6)
    check("展开成 4 格", len(win.pdf_items) == 4, f"{len(win.pdf_items)} 格")
    wait_for(app, lambda: all(it.thumbbed for it in win.pdf_items), 30)
    check("缩略图就绪", all(it.thumbbed for it in win.pdf_items))

    print("\n[2] 默认态：压缩功能关着")
    check("状态 off", win._pdf_zip_mode == "off", win._pdf_zip_mode)
    check("只有启用按钮露出", win.pdf_zip_enable.isVisibleTo(win))
    check("压缩全部不露出", not win.pdf_zip_all.isVisibleTo(win))
    check("压缩部分不露出", not win.pdf_zip_part.isVisibleTo(win))
    check("质量条不露出", not win.pdf_zip_qwrap.isVisibleTo(win))
    check("提示语", "未启用" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())
    check("格子上没有尺寸行", all(not sub_of(win, it.uid) for it in win.pdf_items))

    print("\n[3] 点【启用压缩功能】→ 出两个按钮")
    win.pdf_zip_enable.click()
    pump(app, 6)
    check("状态 pick", win._pdf_zip_mode == "pick", win._pdf_zip_mode)
    check("压缩全部露出", win.pdf_zip_all.isVisibleTo(win))
    check("压缩部分露出", win.pdf_zip_part.isVisibleTo(win))
    check("启用按钮收回", not win.pdf_zip_enable.isVisibleTo(win))
    check("压缩选中此刻不露出", not win.pdf_zip_run.isVisibleTo(win))
    check("提示改为选范围", "选择" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())

    print("\n[4] 点【压缩全部】→ 逐页预估")
    win.pdf_zip_all.click()
    pump(app, 6)
    check("状态 all", win._pdf_zip_mode == "all", win._pdf_zip_mode)
    check("质量条露出", win.pdf_zip_qwrap.isVisibleTo(win))
    check("质量默认 78", win.pdf_zip_quality.value() == 78, str(win.pdf_zip_quality.value()))
    check("没有格式/长边选项", not hasattr(win, "pdf_fmt_chips"))
    ok = wait_for(app, lambda: "省" in win.pdf_zip_hint.text(), 60)
    check("估算跑完", ok, win.pdf_zip_hint.text())

    # 别用 index 当 key：两份 PDF 都有第 0/1 页，会互相覆盖
    subs = {it.uid: sub_of(win, it.uid) for it in win.pdf_items if it.ref.kind == "pdf"}
    scan_subs = [it for it in win.pdf_items if it.ref.src == str(scan)]
    text_subs = [it for it in win.pdf_items if it.ref.src == str(text)]
    check(
        "扫描页显示 当前 → 预估",
        all("→" in sub_of(win, it.uid) for it in scan_subs),
        sub_of(win, scan_subs[0].uid),
    )
    check(
        "纯文字页标注无图片",
        all("无图片" in sub_of(win, it.uid) for it in text_subs),
        sub_of(win, text_subs[0].uid),
    )
    check("提示行给出总账", "→" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())
    check("场景截图前先记下状态", len(subs) == 4, str(len(subs)))

    print("\n[5] 拖质量条 → 预估重算")
    old = sub_of(win, scan_subs[0].uid)
    win.pdf_zip_quality.setValue(40)
    pump(app, 4)
    check("质量标签跟着变", win.pdf_zip_qv.text() == "40", win.pdf_zip_qv.text())
    ok = wait_for(app, lambda: sub_of(win, scan_subs[0].uid) != old, 60)
    check("质量 40 时预估变小（数字变了）", ok, sub_of(win, scan_subs[0].uid))
    check("提示行仍完整", "省" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())
    win.pdf_zip_quality.setValue(70)
    pump(app, 4)
    wait_for(app, lambda: "省" in win.pdf_zip_hint.text(), 60)

    print("\n[6] 点【压缩部分】→ 只算选中页")
    win.pdf_grid.clearSelection()
    win.pdf_grid.setCurrentRow(0)
    pump(app, 4)
    win.pdf_zip_part.click()
    pump(app, 6)
    check("状态 part", win._pdf_zip_mode == "part", win._pdf_zip_mode)
    check("压缩选中露出", win.pdf_zip_run.isVisibleTo(win))
    check("压缩全部收回", not win.pdf_zip_all.isVisibleTo(win))
    ok = wait_for(app, lambda: "省" in win.pdf_zip_hint.text(), 60)
    check("选中页预估完成", ok, win.pdf_zip_hint.text())
    check("提示行写「选中 1 页」", "选中 1 页" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())
    others = [it for it in win.pdf_items if it.uid != win.pdf_items[0].uid]
    check("未选中的格子没有数字", all(not sub_of(win, it.uid) for it in others))

    print("\n[7] 点【压缩选中】→ 压完自动回 off，结果暂存")
    size_before = sub_of(win, win.pdf_items[0].uid)
    win.pdf_zip_run.click()
    ok = wait_for(app, lambda: not win.pdf_runner.busy(), 120)
    # runner 先把 _running 置 False 再 emit finished，信号还是排队投递的 ——
    # busy 变 False 的那一刻 finished 可能还在队列里，得再转几圈事件循环
    pump(app, 12)
    check("压缩任务结束", ok)
    check("状态回到 off", win._pdf_zip_mode == "off", win._pdf_zip_mode)
    check("启用按钮又出现", win.pdf_zip_enable.isVisibleTo(win))
    check("暂存表有 1 条", len(win._pdf_staged) == 1, str(len(win._pdf_staged)))
    staged_path = next(iter(win._pdf_staged.values()), "")
    check("暂存文件落盘", bool(staged_path) and Path(staged_path).exists(), staged_path)
    check(
        "格子上标了已压缩",
        "已压缩" in sub_of(win, win.pdf_items[0].uid),
        sub_of(win, win.pdf_items[0].uid),
    )
    check("压缩前那行数字记过", "→" in size_before, size_before)

    print("\n[8] 导出：暂存页直接用压缩版，文字层还在")
    out = WORK / "导出结果.pdf"
    from app.core.pdf_images import merge_pdf

    refs = [it.ref for it in win.pdf_items]
    merge_pdf(refs, out, quality=None, staged=win._pdf_staged)
    r = PdfReader(str(out))
    check("导出 4 页", len(r.pages) == 4, str(len(r.pages)))
    txt = " ".join((p.extract_text() or "") for p in r.pages)
    check("文字层保留", "扫描页 1 的文字层" in txt)
    check("纯文字页也在", "纯文字页 1" in txt)
    sizes = []
    for page in r.pages:
        res = page.get("/Resources")
        if res is None:
            continue
        xo = res.get_object().get("/XObject")
        if xo is None:
            continue
        for _n, ref in xo.get_object().items():
            o = ref.get_object()
            if o.get("/Subtype") == "/Image":
                sizes.append((int(o.get("/Width")), int(o.get("/Height"))))
    check("图片像素没被缩", sizes and all(w == 1600 and h == 1200 for w, h in sizes),
          str(sizes))

    print("\n[9] 压缩态导出（走界面按钮那条路）")
    win.pdf_zip_enable.click()
    pump(app, 4)
    win.pdf_zip_all.click()
    pump(app, 6)
    wait_for(app, lambda: "省" in win.pdf_zip_hint.text(), 60)
    check("回到 all", win._pdf_zip_mode == "all", win._pdf_zip_mode)
    check("导出时会走 pypdf 管线", win._pdf_zip_active())
    # 直接把 runner 里那条 work 跑一遍（比点菜单更可控，菜单是阻塞 exec）
    got = {}
    orig = win._pdf_start_zip

    def fake(jobs, label):
        got["jobs"] = jobs
        got["label"] = label

    win._pdf_start_zip = fake
    win._pdf_run_pdf_one(refs, stem="压缩合并")
    check("走的是 zip 管线", "jobs" in got, str(got.get("label")))
    win._pdf_start_zip = orig

    print("\n[10] 截图（压缩全部进行中的样子）")
    pump(app, 8)
    shot = ROOT / "docs" / "images" / "pdf-zip.png"
    win.grab().save(str(shot))
    check("截图已保存", shot.exists(), f"{shot.stat().st_size // 1024} KB")

    print("\n[11] 取消压缩回到未启用")
    win.pdf_zip_cancel.click()
    pump(app, 4)
    check("状态回 off", win._pdf_zip_mode == "off", win._pdf_zip_mode)
    check("尺寸行被清掉", not sub_of(win, scan_subs[0].uid) or "已压缩" in sub_of(win, scan_subs[0].uid),
          sub_of(win, scan_subs[0].uid))

    win.quit_app()
    pump(app, 6)
    check("暂存目录被清理", not win._pdf_stage_dir or not Path(win._pdf_stage_dir).exists(),
          str(win._pdf_stage_dir))

    print()
    if _fails:
        print("RESULT = FAIL ->", ", ".join(_fails))
        return 1
    print("RESULT = PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
