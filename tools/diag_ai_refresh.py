"""验证：AI 页改倍率后，队列「预计大小」是否实时更新；超分阶段标签是否写清 4×→2×。

跑法：python tools/diag_ai_refresh.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.ai import AiSettings, build_plan, infer_scale, output_size  # noqa: E402
from app.core.media import probe_media  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def pump(app, rounds=40, delay=0.05):
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def main() -> int:
    mp4 = ROOT / "logs" / "_selftest" / "in.mp4"
    info = probe_media(mp4)

    print("== 阶段标签 ==")
    from app.core.ai import detect_engines
    from app.core.probe import _find_tool

    engines = detect_engines()
    ffmpeg = _find_tool("ffmpeg")
    work = ROOT / "logs" / "_ai_test"
    work.mkdir(parents=True, exist_ok=True)
    for k in (2, 4):
        s = AiSettings(scale=k)
        plan = build_plan(info, s, engines, ffmpeg, work)
        print(f"  scale={k}  infer={infer_scale(s)}  out={output_size(info, s)}")
        for st in plan.stages:
            print(f"    - {st.label}  weight={st.weight:.2f}")

    print("\n== 界面：改倍率后队列数字 ==")
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(app, 8)
    win._add_paths([mp4])
    pump(app, 30)
    win.tabs.setCurrentIndex(1)
    pump(app, 10)

    def row():
        return [win.table.item(0, c).text() for c in range(1, 5)]

    win.ai_scale_chips.set_value("2", emit=True)
    pump(app, 6)
    print("  2× :", row())
    win.ai_scale_chips.set_value("4", emit=True)
    pump(app, 6)
    print("  4× :", row())
    win.ai_interp_chips.set_value("2", emit=True)
    pump(app, 6)
    print("  4×+补帧 :", row())

    print("\n== 界面：压缩页改 CRF / 缩放 ==")
    win.tabs.setCurrentIndex(0)
    pump(app, 6)
    win.crf_slider.setValue(30)
    pump(app, 6)
    print("  CRF30:", row())
    win.scale_chips.set_value("50", emit=True)
    pump(app, 6)
    print("  CRF30+50%:", row())

    print("\n== 界面：图片页改质量 ==")
    win._set_mode(1)
    png = ROOT / "logs" / "_selftest" / "in.png"
    win._img_add_paths([png])
    pump(app, 30)

    def irow():
        return [win.img_table.item(0, c).text() for c in range(1, 5)]

    print("  默认82:", irow())
    win.img_quality_slider.setValue(40)
    pump(app, 6)
    print("  质量40:", irow())
    win.img_fmt_chips.set_value("webp", emit=True)
    pump(app, 6)
    print("  webp:", irow())

    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
