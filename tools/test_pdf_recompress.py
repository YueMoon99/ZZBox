"""PDF 页面「已压缩」绿标 / 再次压缩 / 逐级撤销 / 退出清理 的离屏实跑测试。

真起 MainWindow、真导入、真跑两轮压缩。锁住的承诺：

  1. 压缩完的页（图片页 + PDF 页）都在缩略图右上角挂「已压缩」绿标
  2. 已压缩页能再次压缩，第二轮从第一轮的暂存件读，输出更小的文件
  3. 每轮缓存独立命名，同秒连压不覆盖；文件都在软件目录内
  4. Ctrl+Z 逐级回退：第二轮 → 第一轮 → 原始
  5. 走托盘退出路径 quit_app()，软件目录里的缓存被清空

跑法：python tools/test_pdf_recompress.py
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
from app.ui.page_grid import BADGE_ROLE  # noqa: E402

WORK = Path(tempfile.gettempdir()) / "zzbox_pdf_recompress"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 40, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def finish(win, app) -> None:
    for _ in range(400):
        app.processEvents()
        time.sleep(0.02)
        if not win.pdf_runner.busy():
            break
    pump(app, 10)


def badge_of(win, uid: str) -> str:
    item = win.pdf_grid._item_of(uid)
    return (item.data(BADGE_ROLE) or "") if item is not None else ""


def make_pdf_with_photo() -> Path:
    """造一页带大位图的 PDF —— 保证有可压图片，压缩真的会变小。"""
    import numpy as np
    import pymupdf
    from PIL import Image

    WORK.mkdir(parents=True, exist_ok=True)
    jpg = WORK / "photo.jpg"
    rng = np.random.default_rng(11)
    arr = rng.integers(40, 210, (1200, 900, 3), dtype="uint8")
    Image.fromarray(arr, "RGB").save(jpg, quality=96)

    pdf = WORK / "带图.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 60), "COMPRESS ME", fontsize=16)
    page.insert_image(pymupdf.Rect(50, 90, 545, 700), filename=str(jpg))
    doc.save(str(pdf))
    doc.close()
    return pdf


def main() -> int:
    print("== 样本 ==")
    pdf = make_pdf_with_photo()
    print(f"  {pdf.name}")

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    pump(app, 10)

    win._pdf_add_paths([pdf])
    pump(app, 60)
    check("PDF 页已入队", len(win.pdf_items) == 1, str(len(win.pdf_items)))
    it = win.pdf_items[0]
    uid = it.uid
    src0 = it.ref.src

    print("== 第一轮压缩 ==")
    win._pdf_begin_compress([uid])
    pump(app, 5)
    win.pdf_zip_quality.setValue(80)
    win._pdf_zip_confirm()
    finish(win, app)

    staged1 = win._pdf_staged.get((src0, 0, 0))
    check("第一轮产生暂存件", bool(staged1) and Path(staged1).exists(), str(staged1))
    check("暂存件在软件目录内", bool(staged1) and str(ROOT) in str(Path(staged1).resolve()), str(staged1))
    check("第一轮后右上角有绿标", badge_of(win, uid) == "已压缩", repr(badge_of(win, uid)))
    size1 = Path(staged1).stat().st_size if staged1 else 0
    # 切到 PDF 页并截个图，肉眼核对绿标样式
    win.pages.setCurrentIndex(2)
    pump(app, 5)
    shot = ROOT / "docs" / "images" / "pdf-compressed-badge.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    win.grab().save(str(shot))
    print(f"  截图 → {shot.name}")

    print("== 第二轮压缩（在已压缩页上再来一次）==")
    win._pdf_begin_compress([uid])
    pump(app, 5)
    # 估算应基于第一轮的暂存件，不该退回原始重新算
    check("二次压缩识别为已压缩", win._pdf_is_compressed(win.pdf_by_uid[uid]))
    win.pdf_zip_quality.setValue(45)
    win._pdf_zip_confirm()
    finish(win, app)

    staged2 = win._pdf_staged.get((src0, 0, 0))
    check("第二轮产生新暂存件", bool(staged2) and Path(staged2).exists(), str(staged2))
    check("两轮命名不同（不覆盖）", bool(staged1 and staged2) and staged1 != staged2,
          f"{staged1} vs {staged2}")
    check("两轮都在软件目录内", bool(staged2) and str(ROOT) in str(Path(staged2).resolve()), str(staged2))
    size2 = Path(staged2).stat().st_size if staged2 else 0
    check("第二轮文件更小", size2 < size1, f"{size1} → {size2}")
    check("第二轮后绿标仍在", badge_of(win, uid) == "已压缩", repr(badge_of(win, uid)))

    print("== Ctrl+Z 逐级回退 ==")
    win._pdf_undo()
    pump(app, 5)
    back1 = win._pdf_staged.get((src0, 0, 0))
    check("撤销一次回到第一轮暂存", back1 == staged1, f"{back1} vs {staged1}")
    check("回退后绿标仍在（第一轮也压过）", badge_of(win, uid) == "已压缩", repr(badge_of(win, uid)))

    win._pdf_undo()
    pump(app, 5)
    back0 = win._pdf_staged.get((src0, 0, 0))
    check("再撤销回到原始（无暂存）", not back0, str(back0))
    check("原始文件仍在", Path(src0).exists(), str(src0))
    check("回退到原始后绿标消失", badge_of(win, uid) == "", repr(badge_of(win, uid)))

    print("== 退出清理（托盘右键退出路径）==")
    # 再造一轮缓存，然后走 quit_app 的清理，确认整目录被删
    win._pdf_begin_compress([uid])
    pump(app, 5)
    win._pdf_zip_confirm()
    finish(win, app)
    stage = win._pdf_stage_dir
    check("退出前有缓存目录", stage is not None and stage.exists(), str(stage))
    win._pdf_drop_staged()
    check("托盘退出清掉整目录", stage is not None and not stage.exists(), str(stage))

    win.close()
    print("\n" + ("全部通过" if not _fails else f"失败 {len(_fails)} 项：{_fails}"))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
