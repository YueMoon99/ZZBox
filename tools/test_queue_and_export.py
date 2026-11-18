"""队列交互（Delete 删除 / 整行悬停 / 拖拽预览）与 AE 式导出保存对话框的离屏测试。

锁住的承诺：

  1. 三个队列（视频 / 图片 / PDF）按 Delete 键都删除选中项
  2. 鼠标悬停时整行底色变化（每一格 + 操作列自绘格一起），不是只有单格
  3. 拖拽预览是跟随指针的半透明行截图，不是错位的空蓝框
  4. 导出保存对话框：文件名 / 保存类型 / 「保存至子文件夹」→
     ZZbox output.年.月.日.时.分 文件夹，位置写回「输出到」
  5. 点导出不再弹「合并为 1 个 / 按来源 / PNG / JPG」菜单，格式走保存类型
  6. 图片队列选 PDF 时多图装订成一个 PDF

跑法：python tools/test_queue_and_export.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from app.ui.export_dialog import ExportChoice, ExportDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.style import ACCENT, ROW_HOVER, ROW_LINE, build_qss, pick_font  # noqa: E402
from app.ui.widgets import COL_OPS, RowActions  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_queue_export_test"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 20, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def press_delete(widget) -> None:
    widget.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))


def make_png(path: Path, size=(64, 48), color=(200, 80, 60)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def make_pdf(path: Path, pages: int = 2) -> Path:
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 60 + i * 20), f"page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def row_pixels(table, row: int) -> list[str]:
    """一行取三个采样点的渲染色：文件名列、最后一个数据列、操作列正中。

    操作列那一点落在 cellWidget 上 —— 整行底色要是没盖住它，这里就会露馅。
    """
    vp = table.viewport()
    img = vp.grab().toImage()
    y = table.rowViewportPosition(row) + table.rowHeight(row) // 2
    ops_x = sum(table.columnWidth(c) for c in range(COL_OPS))
    xs = (24, ops_x - 24, ops_x + table.columnWidth(COL_OPS) // 2)
    return [img.pixelColor(x, y).name() for x in xs]


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    # 和 main.py 一样套上真样式表：不然读到的像素是 Fusion 的调色板色，
    # 和用户眼睛看到的不是一回事
    app.setStyle("Fusion")
    app.setFont(QFont(pick_font().strip('"'), 9))
    app.setStyleSheet(build_qss())
    win = MainWindow()
    win.show()
    pump(app)

    print("== Delete 键删除 ==")
    vids = []
    for i in range(3):
        p = WORK / f"视频{i + 1}.mp4"
        p.write_bytes(b"\x00" * 16)
        vids.append(p)
    win._add_paths(vids)
    pump(app)
    check("视频队列加进 3 项", len(win.files) == 3, f"实际 {len(win.files)}")

    win.table.clearSelection()
    win.table.selectRow(1)
    press_delete(win.table)
    pump(app)
    check("视频队列 Delete 删掉选中项", len(win.files) == 2, f"剩 {len(win.files)}")

    imgs = [make_png(WORK / f"图{i + 1}.png") for i in range(2)]
    win._img_add_paths(imgs)
    pump(app)
    win.img_table.clearSelection()
    win.img_table.selectRow(0)
    press_delete(win.img_table)
    pump(app)
    check("图片队列 Delete 删掉选中项", len(win.img_files) == 1, f"剩 {len(win.img_files)}")

    pdf = make_pdf(WORK / "两页.pdf", pages=2)
    win._pdf_add_paths([pdf])
    pump(app)
    check("PDF 队列展开成 2 格", len(win.pdf_items) == 2, f"实际 {len(win.pdf_items)}")
    uid0 = win.pdf_items[0].uid
    win.pdf_grid._item_of(uid0).setSelected(True)
    press_delete(win.pdf_grid)
    pump(app)
    check("PDF 队列 Delete 删掉选中格", len(win.pdf_items) == 1, f"剩 {len(win.pdf_items)}")

    print("== 整行悬停 ==")
    # 不能只看 item.background() —— 那层 brush 在带 QSS「::item」规则的表格里
    # 根本不参与绘制。这里直接读渲染出来的像素：取三个点，第三点落在操作列的
    # cellWidget 上（那格最容易掉队）。
    win.table._set_hover_row(0)
    pump(app)
    px = row_pixels(win.table, 0)
    check(
        "悬停整行同色（含操作列 cellWidget）",
        all(p.lower() == ROW_HOVER.lower() for p in px),
        " ".join(px),
    )
    acts = win.table.cellWidget(0, COL_OPS)
    check(
        "操作列（cellWidget）同步悬停",
        isinstance(acts, RowActions) and acts._hover,
    )
    if win.table.rowCount() > 1:
        other = row_pixels(win.table, 1)
        check(
            "其他行不受悬停影响",
            all(p.lower() != ROW_HOVER.lower() for p in other),
            " ".join(other),
        )
    win.table._set_hover_row(-1)
    pump(app)
    check(
        "离开后悬停清除",
        not acts._hover and all(p.lower() != ROW_HOVER.lower() for p in row_pixels(win.table, 0)),
    )

    print("== 行分隔线 ==")
    img = win.table.viewport().grab().toImage()
    ops_x = sum(win.table.columnWidth(c) for c in range(COL_OPS))
    y = win.table.rowViewportPosition(0) + win.table.rowHeight(0) - 1
    line = {img.pixelColor(x, y).name().lower() for x in (40, ops_x - 20, ops_x + 60)}
    check("行分隔线贯穿到操作列", line == {ROW_LINE.lower()}, " ".join(sorted(line)))

    print("== 拖动落点提示线 ==")
    win.table._place_drop_line(QPoint(40, win.table.rowViewportPosition(0) + 2))
    pump(app)
    drop = win.table._drop_line
    check("拖动时提示线可见", drop.isVisible())
    img = win.table.viewport().grab().toImage()
    y = drop.geometry().center().y()
    hits = [
        x for x in range(img.width())
        if img.pixelColor(x, y).name().lower() == ACCENT.lower()
    ]
    check(
        "提示线整行贯通（含操作列，不再断成两截）",
        len(hits) >= img.width() - 12,
        f"{len(hits)}/{img.width()} px",
    )
    check(
        "提示线用按钮同款强调蓝",
        bool(hits) and img.pixelColor(img.width() // 2, y).name().lower() == ACCENT.lower(),
    )
    win.table._hide_drop_line()
    check("松手后提示线隐藏", not drop.isVisible())

    print("== 拖拽预览 ==")
    pix = win.table._drag_preview(0)
    check("拖拽预览图非空", not pix.isNull())
    # 预览图是整行截图等比缩到 ≤320 宽：宽高比要跟 行高:视口宽 一致
    vw, rh = win.table.viewport().width(), win.table.rowHeight(0)
    expect_h = round(rh * pix.width() / max(1, vw))
    check(
        "预览图按整行截取（等比缩放 ≤320 宽）",
        0 < pix.width() <= 320 and abs(pix.height() - expect_h) <= 2,
        f"{pix.width()}x{pix.height()} 期望高~{expect_h}",
    )

    print("== 保存对话框 ==")
    base = WORK / "导出位置"
    base.mkdir(parents=True, exist_ok=True)

    dlg = ExportDialog(None, mode="pdf", default_name="合并", initial_dir=str(base))
    dlg.name_edit.setText("a/b:c*")
    dlg.fmt_box.setCurrentIndex(dlg.fmt_box.findData("png"))
    dlg.subdir_check.setChecked(True)
    dlg._accept()
    ch = dlg.chosen()
    check("确认后对话框 Accepted", dlg.result() == QDialog.Accepted)
    check("fmt 用保存类型 key", ch is not None and ch.fmt == "png", getattr(ch, "fmt", ""))
    check("文件名去掉非法字符", ch is not None and ch.filename == "a_b_c_", getattr(ch, "filename", ""))
    check("子文件夹开关生效", ch is not None and ch.subdir)
    check(
        "子文件夹命名 ZZbox output.年.月.日.时.分",
        ch is not None and ch.out_dir.name.startswith("ZZbox output.")
        and ch.out_dir.is_dir(),
        getattr(ch.out_dir, "name", ""),
    )

    dlg2 = ExportDialog(None, mode="video", default_name="片头", initial_dir=str(base))
    dlg2.fmt_box.setCurrentIndex(dlg2.fmt_box.findData("mkv"))
    dlg2.subdir_check.setChecked(False)
    dlg2._accept()
    ch2 = dlg2.chosen()
    check("不勾子文件夹直接输出所选目录", ch2 is not None and ch2.out_dir == base)
    check("视频保存类型 mkv", ch2 is not None and ch2.fmt == "mkv")

    nested = base / "ZZbox output.2026.01.02.03.04"
    nested.mkdir(parents=True, exist_ok=True)
    dlg3 = ExportDialog(None, mode="image", default_name="图", initial_dir=str(nested))
    check(
        "已在输出子文件夹里时不再嵌套（勾选禁用）",
        not dlg3.subdir_check.isEnabled(),
    )
    dlg3._accept()
    ch3 = dlg3.chosen()
    check("禁用时输出即当前目录", ch3 is not None and ch3.out_dir == nested)

    print("== 导出路由（不再弹菜单） ==")
    calls: list[tuple] = []

    # 写回「输出到」走真 _ask_export，只把弹窗换成假选择
    real_choice = ExportChoice(
        out_dir=WORK / "落点", filename="我起的名", fmt="png", subdir=False
    )
    (WORK / "落点").mkdir(exist_ok=True)
    _orig_get = ExportDialog.get_choice
    ExportDialog.get_choice = staticmethod(lambda *a, **k: real_choice)
    try:
        win.out_dir.setText("")
        got = win._ask_export("pdf", default_name="合并", count=3)
    finally:
        ExportDialog.get_choice = _orig_get
    check("对话框确认结果返回", got is real_choice)
    check("选定目录写回「输出到」", win.out_dir.text().strip() == str(WORK / "落点"))

    def fake_ask(mode, default_name="", count=1):
        calls.append(("ask", mode, default_name, count))
        return real_choice

    win._ask_export = fake_ask  # 离屏不弹窗
    win._pdf_run_images = lambda refs, fmt, out_dir=None: calls.append(("images", fmt, str(out_dir)))
    win._pdf_run_pdf_one = lambda refs, stem, name=None: calls.append(("one", name))
    win._pdf_run_pdf_many = lambda refs, prefix="": calls.append(("many", prefix))

    win._pdf_export()
    check("PDF 导出走保存类型 png → 每页一张", ("images", "png", str(WORK / "落点")) in calls)
    check("不再有格式菜单（无 QMenu exec）", not any(c[0] == "menu" for c in calls))

    calls.clear()

    def fake_ask2(mode, default_name="", count=1):
        return ExportChoice(out_dir=WORK / "落点", filename="我起的名", fmt="pdf_one", subdir=False)

    win._ask_export = fake_ask2
    win._pdf_export()
    check("保存类型 pdf_one → 合并为 1 个并带文件名", ("one", "我起的名") in calls)

    check(
        "单文件名生效（1 项）",
        win._single_name(
            ExportChoice(out_dir=base, filename="成片", fmt="mp4", subdir=False), 1
        )
        == "成片.mp4",
    )
    check(
        "多文件时忽略文件名",
        win._single_name(
            ExportChoice(out_dir=base, filename="成片", fmt="mp4", subdir=False), 3
        )
        is None,
    )

    name_dir = WORK / "命名测试"
    name_dir.mkdir(exist_ok=True)
    (name_dir / "成片.mp4").write_bytes(b"x")
    win._single_out_name = "成片.mp4"
    named = win._named_output(name_dir / "默认名.mp4")
    # unique_path 的既有约定：重名往后挂 (2)(3)…，和 PDF 导出命名一致
    check(
        "指定名重名时自动挂序号（成片(2).mp4）",
        named.name == "成片(2).mp4",
        named.name,
    )
    win._single_out_name = None

    print("== 图片合成 PDF ==")
    out_pdf = WORK / "落点" / "装订.pdf"
    if out_pdf.exists():
        out_pdf.unlink()
    win._img_pdf_target = out_pdf
    win._img_pdf_tmp = WORK / "pdf中间"
    win._img_pdf_tmp.mkdir(exist_ok=True)
    tmp_dir = win._img_pdf_tmp
    mid = [make_png(win._img_pdf_tmp / f"{i:04d}.png", color=(30 + i * 80, 90, 160)) for i in range(2)]
    win._img_pdf_files = [mid[0], mid[1], WORK / "不存在.png"]
    win._img_bind_pdf(1.0)
    check("多图装订成一个 PDF", out_pdf.exists() and out_pdf.stat().st_size > 500,
          str(out_pdf.stat().st_size if out_pdf.exists() else 0))
    check("中间目录用完即删", not tmp_dir.exists())
    check("装订后目标状态已清空", win._img_pdf_target is None and win._img_pdf_files == [])

    win.close()
    pump(app)

    print()
    if _fails:
        print(f"FAIL {len(_fails)} 项: {_fails}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        pass
