"""排查「导入后一直卡在读取中」：真起 MainWindow，真导入，看表格文案。

跑法：python tools/diag_import.py
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


def pump(app, rounds: int = 60, delay: float = 0.05) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(app, 10)

    mp4 = ROOT / "logs" / "_selftest" / "in.mp4"
    png = ROOT / "logs" / "_selftest" / "in.png"
    print("素材:", mp4.exists(), png.exists())

    # ---- 视频 ----
    win._add_paths([mp4])
    print("导入视频后 rows =", len(win.rows), " cache =", list(win.media_cache))
    pump(app, 40)
    print("  3s 后 cache 键:", list(win.media_cache))
    for k, v in win.media_cache.items():
        print("   ", k, "ok=", v.ok, "err=", (v.error or "")[:40])
    r = win.rows[0] if win.rows else None
    print("  第一行源码列:", repr(win._row_texts(mp4)[0]))

    # ---- 图片 ----
    win._img_add_paths([png])
    print("导入图片后 rows =", len(win.img_rows), " cache =", list(win.img_cache))
    pump(app, 40)
    print("  3s 后 img cache 键:", list(win.img_cache))
    for k, v in win.img_cache.items():
        print("   ", k, "ok=", v.ok, "err=", (v.error or "")[:40])
    print("  图片第一行:", repr(win._img_row_texts(png)))

    # 直接看表格上真正显示的文字
    try:
        print("视频表第一行 widget:", r.src_text() if hasattr(r, "src_text") else "n/a")
    except Exception as exc:  # noqa: BLE001
        print("  取表格文字失败:", exc)

    out = Path(tempfile.gettempdir()) / "zzbox_diag"
    out.mkdir(parents=True, exist_ok=True)
    win._set_mode(0)
    pump(app, 6)
    win.grab().save(str(out / "video.png"))
    win._set_mode(1)
    pump(app, 6)
    win.grab().save(str(out / "image.png"))
    print("截图:", out / "video.png", out / "image.png")

    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
