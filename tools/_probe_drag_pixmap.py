# -*- coding: utf-8 -*-
"""离屏探针：捕获 QueueTable 默认拖拽时 QDrag 收到的 pixmap / hotSpot。

复现「拖动时指针右侧远处跟着一个蓝色空框」：把 startDrag 会发给 QDrag 的
pixmap 存出来看看到底画了什么、热点在哪。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QDrag, QPainter, QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from app.ui.widgets import QueueTable  # noqa: E402

captured: dict = {}

_orig_set_pixmap = QDrag.setPixmap
_orig_set_hot = QDrag.setHotSpot
_orig_exec = QDrag.exec


def _spy_pixmap(self, pm):
    captured["pix"] = pm.copy()
    captured["size"] = (pm.width(), pm.height())
    return _orig_set_pixmap(self, pm)


def _spy_hot(self, pt):
    captured["hot"] = (pt.x(), pt.y())
    return _orig_set_hot(self, pt)


def _spy_exec(self, actions, default=Qt.IgnoreAction):
    captured["exec"] = (int(actions), int(default))
    return Qt.IgnoreAction


QDrag.setPixmap = _spy_pixmap
QDrag.setHotSpot = _spy_hot
QDrag.exec = _spy_exec

v = QueueTable()
v.resize(853, 300)
v.show()
app.processEvents()

cells = v.rebuild([Path("1_0006.png"), Path("1_0007.png"), Path("1_0005.png")])
for i, c in enumerate(cells):
    c.items[0].setText(f"row{i}.png")
v.selectRow(1)
app.processEvents()

idx = v.model().index(1, 0)
pos = v.visualRect(idx).center()
QTest.mousePress(v.viewport(), Qt.LeftButton, pos=pos)
v.startDrag(Qt.MoveAction)

print("captured keys:", sorted(captured.keys()))
if "size" in captured:
    print("pixmap size:", captured["size"])
if "hot" in captured:
    print("hotspot:", captured["hot"])
if "exec" in captured:
    print("exec:", captured["exec"])

pix = captured.get("pix")
if pix is not None:
    # 合成到深色背景上看效果（模拟深色 UI 里的观感）
    shot = pix.copy()
    shot.fill(QColor("#33343a"))
    p = QPainter(shot)
    p.setOpacity(0.9)
    p.drawPixmap(0, 0, pix)
    p.end()
    out = Path(__file__).parent / "_dbg_dragpix_raw.png"
    pix.save(str(out))
    shot.save(str(Path(__file__).parent / "_dbg_dragpix_dark.png"))
    print("saved:", out)

# 顺便测一下多行选中
captured.clear()
v.clearSelection()
v.selectRow(0)
sm = v.selectionModel()
sm.select(v.model().index(1, 0), sm.Select | sm.Rows)
sm.select(v.model().index(2, 0), sm.Select | sm.Rows)
app.processEvents()
idx = v.model().index(1, 0)
pos = v.visualRect(idx).center()
QTest.mousePress(v.viewport(), Qt.LeftButton, pos=pos)
v.startDrag(Qt.MoveAction)
print("multi:", captured.get("size"), "hot", captured.get("hot"))
if captured.get("pix") is not None:
    captured["pix"].save(str(Path(__file__).parent / "_dbg_dragpix_multi.png"))

QTimer.singleShot(0, app.quit)
app.exec()
print("done")
