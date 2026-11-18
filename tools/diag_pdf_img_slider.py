# -*- coding: utf-8 -*-
"""诊断：PDF 队列里放测试图.png / 测试图.jpg，模拟拖质量条看界面预估是否变化。

分别在图片方案「保持原样 / jpg / png」下记录：
  - 拖动时每格显示的「原图→预估」字符串
  - 确认压缩后暂存件大小与原图对比
用法：python tools/diag_pdf_img_slider.py
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

IMG_DIR = ROOT.parents[1]
PNG = IMG_DIR / "测试图.png"
JPG = IMG_DIR / "测试图.jpg"


def pump(app, rounds=30, delay=0.02):
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def wait_est(win, app, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        pump(app, 5)
        pending = False
        for uid in win._pdf_compress_uids:
            pair = win._pdf_pair_cache.get(win.pdf_by_uid[uid].uid) or ""
            if "估算中" in pair:
                pending = True
                break
        if not pending:
            pump(app, 15)
            return
    print("  （等待预估超时）")


def pair_of(win, path: Path) -> str:
    for it in win.pdf_items:
        if Path(it.ref.src).name == path.name:
            return win._pdf_pair_cache.get(it.uid) or "(无)"
    return "(未找到)"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    for p in (PNG, JPG):
        assert p.exists(), f"缺测试图 {p}"

    for fmt in ("keep", "jpg", "png"):
        print(f"\n===== 图片方案格式 = {fmt} =====")
        win.img_fmt_chips.set_value(fmt)
        win._pdf_add_paths([PNG, JPG])
        pump(app, 40)
        uids = [it.uid for it in win.pdf_items]
        win._pdf_begin_compress(uids)
        wait_est(win, app)
        print(f"  初始 q=78  png:{pair_of(win, PNG)}   jpg:{pair_of(win, JPG)}")
        for q in (30, 50, 78, 95):
            win.pdf_zip_quality.setValue(q)
            win._pdf_zip_on_quality(q)
            pump(app, 8)
            print(f"  拖到 q={q:<3} png:{pair_of(win, PNG)}   jpg:{pair_of(win, JPG)}")
        # 松手等精确估算回来再看一次
        pump(app, 80)
        print(f"  精确回填后   png:{pair_of(win, PNG)}   jpg:{pair_of(win, JPG)}")

        # 确认压缩，看真实体积
        win._pdf_zip_confirm()
        t0 = time.time()
        while win._busy() and time.time() - t0 < 120:
            pump(app, 10)
        pump(app, 30)
        for it in win.pdf_items:
            if it.staged:
                new = Path(it.staged).stat().st_size
                print(f"  实际压缩 {Path(it.ref.src).name}: "
                      f"{it.size} -> {new} ({new / it.size * 100:.1f}%)  "
                      f"sub={win._pdf_pair_cache.get(it.uid)!r}")
            else:
                print(f"  未产生暂存件 {Path(it.ref.src).name}")
        win._pdf_zip_close()
        # 清空队列和缓存，准备下一轮
        win._pdf_drop_staged()
        win.pdf_items = []
        win.pdf_by_uid = {}
        win._pdf_rebuild_grid()
        win._pdf_img_est_cache.clear()
        win._pdf_stats.clear()
        win._pdf_stat_cache.clear()
        win._pdf_est_failed.clear()
        pump(app, 10)

    win.quit_app()
    pump(app, 5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
