"""离屏渲染主窗口，截参数面板右上角，看直角边框到底是谁画的。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from app.ui import style  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

app.setStyleSheet(style.build_qss())

win = MainWindow()
win.resize(1180, 820)
win.show()
app.processEvents()

# 切到视频 AI 页（和用户截图同一页）
win.tabs.setCurrentIndex(1)
app.processEvents()
app.processEvents()

panel = win.ai_panel
pr = panel.mapTo(win, panel.rect().topLeft())
print("panel rect in window:", pr.x(), pr.y(), panel.width(), panel.height())

shot = win.grab()
full = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dbg_panel_full.png")
shot.save(full)
print("full saved", full)

# 裁面板右上角外扩 30px，看清角上的双框
from PySide6.QtGui import QImage  # noqa: E402

x = max(0, pr.x() - 10)
y = max(0, pr.y() - 30)
w = min(shot.width() - x, panel.width() + 20)
h = min(shot.height() - y, panel.height() + 40)
crop = shot.copy(x, y, w, h)
cp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dbg_panel_corner.png")
crop.save(cp)
print("corner saved", cp)

# 右上角局部放大 4 倍
cx, cy, cw, ch = w - 80, 0, 80, 80
zoom = crop.copy(cx, cy, cw, ch).scaled(cw * 4, ch * 4)
zp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dbg_panel_zoom.png")
zoom.save(zp)
print("zoom saved", zp)
