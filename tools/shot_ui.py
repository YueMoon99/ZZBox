"""开发用：四个属性页各截一张图，落到 docs/images/。

用法（项目根目录）：python tools/shot_ui.py
依赖 bin/ffmpeg 与 bin/ai（有素材信息，界面上才不是一片「读取中…」）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.style import build_qss, pick_font  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(pick_font().strip('"'), 9))
    app.setStyleSheet(build_qss())

    win = MainWindow()
    win.resize(1120, 760)
    win.show()

    def settle(seconds: float) -> None:
        # 环境探测和 ffprobe 都在别的线程里，纯 processEvents 等不到回调
        t0 = time.time()
        while time.time() - t0 < seconds:
            app.processEvents()
            time.sleep(0.03)

    sample = ROOT / "logs" / "_ai_test" / "sample.mp4"
    if sample.exists():
        win._add_paths([sample])

    # 图片队列也要有内容，否则截出来的「图片处理」页是空的
    img_dir = ROOT / "logs" / "_img_test"
    if img_dir.exists():
        pics = sorted(
            p for p in img_dir.iterdir() if p.suffix.lower() in {".jpg", ".png", ".webp"}
        )
        if pics:
            win._img_add_paths(pics)
    settle(3.0)

    out = ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    # (工作台, 页签, 文件名)
    for mode, idx, name in (
        (0, 0, "tab-video-compress.png"),
        (0, 1, "tab-video-ai.png"),
        (1, 0, "tab-image-compress.png"),
        (1, 1, "tab-image-ai.png"),
    ):
        win._set_mode(mode)
        if mode == 0:
            win.tabs.setCurrentIndex(idx)
        else:
            win.img_tabs.setCurrentIndex(idx)
        settle(0.8)
        p = out / name
        win.grab().save(str(p))
        print(f"已保存 {p}")
    win.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
