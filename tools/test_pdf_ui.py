"""PDF 工作台的界面实跑测试（离屏）。

不是单测：真的起 MainWindow、真的导入文件、真的截图。因为 PDF 这一页
有大量布局和信号连线，只靠读代码判断对错太不靠谱 —— 缩略图有没有出来、
格子排得整不整齐、选中态对不对，只有画出来才知道。

跑法：python tools/test_pdf_ui.py
产出：docs/images/pdf-tab.png（README 用）+ 临时目录里的验证产物
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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFont, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.style import build_qss, pick_font  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_pdf_ui"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 40, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def make_samples() -> tuple[Path, Path, Path]:
    import pymupdf
    from PIL import Image

    WORK.mkdir(parents=True, exist_ok=True)
    a = WORK / "年度报告.pdf"
    doc = pymupdf.open()
    for i in range(5):
        page = doc.new_page()
        page.insert_text((60, 90), f"年度报告 第 {i + 1} 页", fontsize=20, fontname="china-s")
        page.insert_text((60, 130), "Body text stays selectable.", fontsize=11)
        page.draw_rect(pymupdf.Rect(60, 160, 535, 400), color=(0.2, 0.4, 0.7), width=1.2)
    doc.save(str(a))
    doc.close()

    b = WORK / "附件.pdf"
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=842, height=595)  # A4 横版
        page.insert_text((60, 90), f"附件 横向页 {i + 1}", fontsize=20, fontname="china-s")
    doc.save(str(b))
    doc.close()

    img = WORK / "票据扫描.jpg"
    Image.new("RGB", (1240, 1754), (250, 248, 244)).save(img, quality=90)
    return a, b, img


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    # 离屏平台走的是 freetype 字体库，默认拿不到微软雅黑，中文会全变成
    # 方块。手动把系统字体喂进去，截图才有法看
    from PySide6.QtGui import QFontDatabase

    family = pick_font().strip('"')
    for font in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ):
        if Path(font).exists():
            QFontDatabase.addApplicationFont(font)
    app.setFont(QFont(family, 9))
    app.setStyleSheet(build_qss())

    pdf_a, pdf_b, img = make_samples()

    win = MainWindow()
    win.resize(1180, 812)
    win.show()
    pump(app, 10)

    print("\n[1] 切到 PDF 工作台")
    win._set_mode(2)
    pump(app, 8)
    check("页面索引 = 2", win.pages.currentIndex() == 2, str(win.pages.currentIndex()))
    check("模式按钮选中", win.btn_mode_pdf.isChecked())
    check("开始按钮变导出", win.btn_start.text() == "导出", win.btn_start.text())
    check("音轨按钮隐藏", not win.btn_extract.isVisible())
    check("空态提示", "空" in win.pdf_count.text(), win.pdf_count.text())

    print("\n[2] 导入 2 个 PDF + 1 张图")
    win._pdf_add_paths([pdf_a, pdf_b, img])
    pump(app, 6)
    # 5 + 2 + 1 = 8 页
    check("展开成 8 格", len(win.pdf_items) == 8, f"{len(win.pdf_items)} 格")
    check("界面格数一致", win.pdf_grid.count() == 8, str(win.pdf_grid.count()))
    check("计数文案", "8 页" in win.pdf_count.text(), win.pdf_count.text())

    # 缩略图在后台线程渲染，等它们回来
    deadline = time.time() + 25
    while time.time() < deadline:
        pump(app, 5, 0.02)
        if all(it.thumbbed for it in win.pdf_items):
            break
    got = sum(1 for it in win.pdf_items if it.thumbbed)
    check("缩略图全部就绪", got == 8, f"{got}/8")

    print("\n[3] 页面顺序与来源")
    labels = [it.label for it in win.pdf_items]
    check("第一格是报告首页", labels[0].startswith("第 1 页"), labels[0])
    check("横版页也进来了", any("附件" in x for x in labels), labels[5])
    check("图片成为一格", any(x.startswith("图片") for x in labels), labels[-1])

    print("\n[4] 选择 / 旋转")
    win.pdf_grid.setCurrentRow(0)
    win.pdf_grid.item(1).setSelected(True)
    pump(app, 4)
    sel = win.pdf_grid.selected_uids()
    check("选中 2 格", len(sel) == 2, str(len(sel)))
    check("旋转按钮可用", win.pdf_btn_rotate.isEnabled())

    before = win.pdf_by_uid[sel[0]].ref.rotate
    win._pdf_rotate()
    pump(app, 6)
    after = win.pdf_by_uid[sel[0]].ref.rotate
    check("旋转 +90°", after == (before + 90) % 360, f"{before} → {after}")
    check("标签带角度", "90" in win.pdf_grid.item(0).text(), win.pdf_grid.item(0).text())

    print("\n[5] 压缩区默认未启用")
    check("只有「启用压缩功能」可见", win.pdf_zip_enable.isVisibleTo(win))
    check("压缩全部/部分此刻不露出", not win.pdf_zip_all.isVisibleTo(win))
    check("质量条此刻不露出", not win.pdf_zip_qwrap.isVisibleTo(win))
    check("提示语说明未启用", "未启用" in win.pdf_zip_hint.text(), win.pdf_zip_hint.text())
    check("状态机在 off", win._pdf_zip_mode == "off", win._pdf_zip_mode)

    print("\n[6] 拖动排序回读（走真实鼠标拖动）")
    uids = win.pdf_grid.ordered_uids()
    # 这里以前只改界面顺序再手调 _pdf_on_reorder，等于只测了数据侧；
    # 后来又试过直接调 dropEvent，也没覆盖"拖动能不能起来"。现在按真实
    # 操作发鼠标事件：按下最后一格 → 拖到第一格左半边 → 松手。
    grid = win.pdf_grid
    rects = [grid.visualItemRect(grid.item(i)) for i in range(grid.count())]
    frm = rects[-1].center()
    to = QPoint(rects[0].left() + 2, rects[0].center().y())

    def _mouse(kind, pos, button, buttons):
        gp = grid.viewport().mapToGlobal(pos)
        ev = QMouseEvent(kind, QPointF(pos), QPointF(gp), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(grid.viewport(), ev)

    _mouse(QEvent.MouseButtonPress, frm, Qt.LeftButton, Qt.LeftButton)
    pump(app, 2)
    _mouse(QEvent.MouseMove, QPoint(frm.x() - 40, frm.y() - 40), Qt.NoButton, Qt.LeftButton)
    pump(app, 2)
    check("拖动中被置为拖动态", grid._dragging)
    _mouse(QEvent.MouseMove, to, Qt.NoButton, Qt.LeftButton)
    pump(app, 4)
    # 留一张"正在拖"的现场图：幽灵缩略图 + 插入线都在，且不能有框选框
    win.grab().save(str(ROOT / "docs" / "images" / "pdf-drag.png"))
    _mouse(QEvent.MouseButtonRelease, to, Qt.LeftButton, Qt.NoButton)
    pump(app, 6)
    check("松手后退出拖动态", not grid._dragging)
    check("顺序跟着界面走", win.pdf_items[0].uid == uids[-1],
          f"{win.pdf_items[0].uid} vs {uids[-1]}")

    print("\n[7] 下方工作区分区：左操作 / 右压缩")
    ops = win.pdf_ops_panel
    comp = win.pdf_zip_panel
    ops_r, comp_r = ops.geometry(), comp.geometry()
    share = ops_r.width() / max(1, ops_r.width() + comp_r.width())
    check("左区比右区窄", ops_r.width() < comp_r.width(), f"{ops_r.width()}px vs {comp_r.width()}px")
    check("左区占比 12%~26%", 0.12 <= share <= 0.26, f"{share:.0%}")
    check("操作区在左边", ops_r.left() < comp_r.left(), f"{ops_r.left()} < {comp_r.left()}")
    check("两区顶边对齐", abs(ops_r.top() - comp_r.top()) <= 1, f"{ops_r.top()} vs {comp_r.top()}")
    check("两区等高", abs(ops_r.height() - comp_r.height()) <= 1, f"{ops_r.height()} vs {comp_r.height()}")
    # 关键回归：旋转/导出绝对不能又回到压缩卡片里
    inside = {w.text() for w in comp.findChildren(QPushButton)}
    check("压缩区里没有「旋转选中」", "旋转选中" not in inside, str(sorted(inside)))
    check("压缩区里没有「导出选中」", "导出选中" not in inside)
    check("压缩区里是「启用压缩功能」", "启用压缩功能" in inside, str(sorted(inside)))
    ops_btns = {w.text() for w in ops.findChildren(QPushButton)}
    check("左区正好这两个按钮", ops_btns == {"旋转选中", "导出选中"}, str(sorted(ops_btns)))
    for name, btn in (("旋转选中", win.pdf_btn_rotate), ("导出选中", win.pdf_btn_extract)):
        check(f"按钮文案是「{name}」", btn.text() == name, btn.text())
        check(f"「{name}」可见", btn.isVisible())

    print("\n[8] 截图")
    # 还原成导入时的顺序，截图要反映真实使用状态
    win._pdf_on_reorder(uids)
    win._pdf_rebuild_grid()
    pump(app, 6)
    win.pdf_grid.clearSelection()
    win.pdf_grid.setCurrentRow(0)
    win.pdf_grid.item(2).setSelected(True)
    pump(app, 8)
    shot = ROOT / "docs" / "images" / "pdf-tab.png"
    win.grab().save(str(shot))
    check("截图已保存", shot.exists(), f"{shot.stat().st_size // 1024} KB")

    # 放大一档再拍一张，确认 Ctrl+滚轮的效果是真的
    win.pdf_grid.set_zoom(220)
    pump(app, 8)
    zoomed = WORK / "缩放220.png"
    win.grab().save(str(zoomed))
    check("缩放截图", zoomed.exists() and win.pdf_grid.zoom() == 220, str(win.pdf_grid.zoom()))

    # 最小窗口（1020×660）下格墙还剩多少可看面积 —— PDF 页比另外两页多一条
    # 操作行，挤不下的话就是这个尺寸先塌
    win.pdf_grid.set_zoom(148)
    win.resize(1020, 660)
    pump(app, 10)
    small = WORK / "最小窗口.png"
    win.grab().save(str(small))
    grid_h = win.pdf_grid.viewport().height()
    check("最小窗口下格墙 ≥ 1 行", grid_h > 240, f"格墙高 {grid_h}px")
    win.resize(1180, 812)
    pump(app, 8)

    print("\n[9] 真实导出（走 core，不经 runner）")
    from app.core.pdf import PageRef, export_pdf, probe_pdf

    out = WORK / "导出验证.pdf"
    refs = [it.ref for it in win.pdf_items]
    export_pdf(refs, out)
    probe = probe_pdf(out)
    check("页数 = 8", probe.pages == 8, str(probe.pages))
    check("文字层保留", probe.text_pages >= 7, f"{probe.text_pages} 页有字")
    check("体积正常", out.stat().st_size > 5000, f"{out.stat().st_size // 1024} KB")

    print("\n[9b] 单独文件命名跟随原始文件")
    # 上一轮留下的同名文件会让命名自动挂 (2)，先清干净
    for old in WORK.glob("年度报告·*.pdf"):
        old.unlink()
    win.out_dir.setText(str(WORK))
    pump(app, 2)
    each = refs[:3]  # 年度报告 第 1/2/3 页
    win._pdf_run_pdf_each(each)
    deadline = time.time() + 30
    while time.time() < deadline and win.pdf_runner.busy():
        pump(app, 5, 0.02)
    pump(app, 10)
    names = sorted(p.name for p in WORK.glob("年度报告·*.pdf"))
    check("每页一个 PDF", names == ["年度报告·1.pdf", "年度报告·2.pdf", "年度报告·3.pdf"],
          ", ".join(names))
    check("每个文件只有 1 页", all(probe_pdf(WORK / n).pages == 1 for n in names))
    # 页号必须取自原文件：拆出来的第 2 个文件里应该是原文件的第 2 页内容
    import pypdfium2 as _pdfium

    doc = _pdfium.PdfDocument(str(WORK / "年度报告·2.pdf"))
    try:
        tp = doc[0].get_textpage()
        try:
            page_text = tp.get_text_range()
        finally:
            tp.close()
    finally:
        doc.close()
    check("页号对得上原文件", "第 2 页" in page_text, page_text.strip().replace("\n", " ")[:30])

    win._pdf_run_images([win.pdf_items[-1].ref], "png")  # 票据扫描.jpg
    deadline = time.time() + 30
    while time.time() < deadline and win.pdf_runner.busy():
        pump(app, 5, 0.02)
    pump(app, 10)
    shots = list(WORK.glob("*票据扫描*/*.png"))
    check("图片导出不带页号", any(p.name == "票据扫描.png" for p in shots),
          ", ".join(p.name for p in shots))

    print("\n[10] 取消：协作式退出")
    # 用一个明确的慢任务验证 runner 的取消链路（真导出 8 页太快，来不及点）
    import threading as _th

    gate = _th.Event()

    def slow(progress):
        for i in range(200):
            gate.wait(0.01)
            progress(i // 2)
        return "不该跑到这里"

    win.pdf_runner.start(slow, "slow")
    pump(app, 3, 0.01)
    check("任务在跑", win.pdf_runner.busy())
    win.pdf_runner.cancel()
    gate.set()
    deadline = time.time() + 10
    while time.time() < deadline and win.pdf_runner.busy():
        pump(app, 3, 0.02)
    check("取消后线程退出", not win.pdf_runner.busy())
    check("界面回到可操作", win.btn_start.isEnabled())

    win.close()
    print()
    if _fails:
        print("RESULT = FAIL ->", ", ".join(_fails))
        return 1
    print("RESULT = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
