"""临时探针：Movement 各模式下，左键按住并移动时 startDrag() 会不会被调用。

用来定位「PDF 队列拖不动」的根因：
QListWidget 在 IconMode 下，Movement.Static 会连带把拖动手势一起禁掉。
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QListView

from app.ui.page_grid import PageGrid

app = QApplication(sys.argv)


class Probe(PageGrid):
    def __init__(self):
        super().__init__()
        self.drag_started = False

    def startDrag(self, actions):  # noqa: N802
        # 不调 super：真的 QDrag.exec 会进嵌套事件循环，把测试挂死
        self.drag_started = True


def trial(movement, mode_name: str) -> None:
    grid = Probe()
    grid.resize(700, 500)
    grid.rebuild([(f"u{i}", f"第 {i + 1} 页") for i in range(8)])
    grid.show()
    grid.setMovement(movement)
    app.processEvents()

    def send(kind, pos, button, buttons):
        gp = grid.viewport().mapToGlobal(pos)
        ev = QMouseEvent(kind, QPointF(pos), QPointF(gp), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(grid.viewport(), ev)

    p0 = grid.visualItemRect(grid.item(0)).center()
    p1 = grid.visualItemRect(grid.item(5)).center()
    send(QEvent.MouseButtonPress, p0, Qt.LeftButton, Qt.LeftButton)
    app.processEvents()
    send(QEvent.MouseMove, p0 + (p1 - p0) / 2, Qt.NoButton, Qt.LeftButton)
    app.processEvents()
    send(QEvent.MouseMove, p1, Qt.NoButton, Qt.LeftButton)
    app.processEvents()
    send(QEvent.MouseButtonRelease, p1, Qt.LeftButton, Qt.NoButton)
    app.processEvents()

    print(f"{mode_name:<8} startDrag={grid.drag_started}  顺序={grid.ordered_uids()}")
    grid.close()


for mv, name in (
    (QListView.Static, "Static"),
    (QListView.Snap, "Snap"),
    (QListView.Free, "Free"),
):
    trial(mv, name)
