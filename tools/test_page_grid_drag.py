"""PDF 队列拖动排序的回归测试（离屏，不需要人手动拖）。

走过的弯路，写在这里免得以后又踩：

1. `Movement.Static` 能把格子锁成整齐的网格，但它连 Qt 自己的拖动手势一起
   禁掉（`startDrag()` 不被调用），所以队列完全拖不动。
2. 换成「Static + 自己 new QDrag」：缩略图能飘，但光标一直 🚫、松手没有 drop、
   还留下一个直到下次点击才消失的框选框。根因是 QDrag 的接受权在 Qt 拖放
   协议手里，而 QDrag.exec() 吞掉 move 之后残余事件被 QListView 当成拉框选择。
3. 最终方案：纯鼠标事件自己实现（按下-移动-松手），不碰拖放协议。

这个测试就是按第 3 条的方式驱动：向 viewport 发 MouseButtonPress / MouseMove /
MouseButtonRelease，断言顺序真的变了、状态真的收干净了。

    C:/Python315/python.exe tools/test_page_grid_drag.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QListView

from app.ui.page_grid import PageGrid

PASS = 0
FAIL: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    global PASS
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


app = QApplication(sys.argv)


def make(n: int = 8, width: int = 700) -> PageGrid:
    g = PageGrid()
    g.resize(width, 460)
    g.rebuild([(f"u{i}", f"第 {i + 1} 页") for i in range(n)])
    g.show()
    app.processEvents()
    return g


def send(g: PageGrid, kind, pos: QPoint, button, buttons) -> None:
    gp = g.viewport().mapToGlobal(pos)
    ev = QMouseEvent(kind, QPointF(pos), QPointF(gp), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(g.viewport(), ev)


def press(g: PageGrid, pos: QPoint) -> None:
    send(g, QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton)
    app.processEvents()


def move(g: PageGrid, pos: QPoint) -> None:
    send(g, QEvent.MouseMove, pos, Qt.NoButton, Qt.LeftButton)
    app.processEvents()


def release(g: PageGrid, pos: QPoint) -> None:
    send(g, QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton)
    app.processEvents()


def drag(g: PageGrid, frm: QPoint, to: QPoint) -> None:
    """一次完整拖动：按下 → 中途移动几帧 → 松手。"""
    press(g, frm)
    move(g, QPoint(frm.x() + 6, frm.y() + 2))          # 阈值内，不该起拖
    move(g, QPoint((frm.x() + to.x()) // 2, (frm.y() + to.y()) // 2))
    move(g, to)
    release(g, to)


print("\n[1] 格子墙仍是整格布局（Static 不能丢）")
g = make()
check(g.movement() == QListView.Static, "movement 保持 Static")
rects = [g.visualItemRect(g.item(i)) for i in range(4)]
check(
    len({r.width() for r in rects}) == 1 and len({r.height() for r in rects}) == 1,
    "同排格子等宽等高",
    f"{rects[0].width()}x{rects[0].height()}",
)
check(rects[0].top() == rects[1].top(), "同排顶边对齐")

print("\n[2] 按下→越过阈值→进入拖动态")
g = make()
p0 = g.visualItemRect(g.item(0)).center()
press(g, p0)
check(not g._dragging, "刚按下时还没进拖动态")
move(g, QPoint(p0.x() + 4, p0.y() + 1))
check(not g._dragging, "阈值内的轻微抖动不算拖")
move(g, QPoint(p0.x() + 60, p0.y() + 40))
check(g._dragging, "越过阈值进入拖动态")
check(g._drag_uids == ["u0"], "拖的是按下的那一格", str(g._drag_uids))
check(
    g.viewport().cursor().shape() == Qt.ClosedHandCursor,
    "拖动时光标是抓手（不再是 🚫）",
)
check(g._drop_row is not None, "并算出了落点", str(g._drop_row))

print("\n[3] 拖动中不拉框、不误改选中")
g = make()
g.item(1).setSelected(True)
g.item(4).setSelected(True)
before_sel = set(g.selected_uids())
check(len(before_sel) == 2, "先摆好多选状态", str(sorted(before_sel)))
p0 = g.visualItemRect(g.item(1)).center()
press(g, p0)
check(set(g.selected_uids()) == before_sel, "按在已选中格上不清空多选", str(g.selected_uids()))
move(g, QPoint(p0.x() + 80, p0.y() + 60))
move(g, QPoint(p0.x() + 120, p0.y() + 90))
check(g._dragging, "进入拖动态")
check(
    set(g.selected_uids()) == before_sel,
    "拖动过程中选中集合不变（没有拉框改选）",
    str(g.selected_uids()),
)

print("\n[4] 松手后状态收干净（那个残留框选框的根源）")
release(g, QPoint(p0.x() + 120, p0.y() + 90))
check(not g._dragging, "松手后退出拖动态")
check(g._drop_row is None, "落点状态已清空")
check(g._drag_uids == [], "待搬运列表已清空")
check(
    g.viewport().cursor().shape() != Qt.ClosedHandCursor,
    "光标已还原（不会一直卡在抓手）",
)
check(g._press_pos is None and g._press_uid is None, "按下状态已清空")

print("\n[5] 真正拖一次：第 1 页拖到最后")
g = make()
r = [g.visualItemRect(g.item(i)) for i in range(8)]
drag(g, r[0].center(), QPoint(r[7].right() - 2, r[7].center().y()))
order = g.ordered_uids()
check(
    order == ["u1", "u2", "u3", "u4", "u5", "u6", "u7", "u0"],
    "顺序已改变",
    str(order),
)
check(g.count() == 8, "格子数没变（搬运不是复制）", str(g.count()))
check(len(set(order)) == 8, "没有重复 uid")

print("\n[6] 反向拖：最后一页拖到最前")
g = make()
r = [g.visualItemRect(g.item(i)) for i in range(8)]
drag(g, r[7].center(), QPoint(r[0].left() + 2, r[0].center().y()))
check(
    g.ordered_uids()[:2] == ["u7", "u0"],
    "末页到了最前",
    str(g.ordered_uids()),
)

print("\n[7] 多选整块搬：相对顺序不乱")
g = make()
g.item(1).setSelected(True)
g.item(3).setSelected(True)
r = [g.visualItemRect(g.item(i)) for i in range(8)]
drag(g, r[1].center(), QPoint(r[7].right() - 2, r[7].center().y()))
order = g.ordered_uids()
check(
    order == ["u0", "u2", "u4", "u5", "u6", "u7", "u1", "u3"],
    "两块一起搬到末尾",
    str(order),
)
check("u1" in g.selected_uids() and "u3" in g.selected_uids(), "搬完选中态还在")

print("\n[8] 空白处按下拖动 = 照旧拉框选择，不是搬格子")
g = make()
empty = QPoint(g.viewport().width() - 12, g.viewport().height() - 12)
press(g, empty)
move(g, QPoint(empty.x() - 90, empty.y() - 90))
check(not g._dragging, "空白处拖动不进拖动态")
release(g, QPoint(empty.x() - 90, empty.y() - 90))

print("\n[9] Esc 放弃这次拖动，顺序不变")
g = make()
base = g.ordered_uids()
r = [g.visualItemRect(g.item(i)) for i in range(8)]
press(g, r[0].center())
move(g, QPoint(r[5].center().x(), r[5].center().y()))
check(g._dragging, "已在拖动态")
esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
g.keyPressEvent(esc)
check(not g._dragging, "Esc 退出拖动态")
check(g.ordered_uids() == base, "顺序没变", str(g.ordered_uids()))
release(g, QPoint(r[5].center().x(), r[5].center().y()))
check(g.ordered_uids() == base, "随后松手也不会补一次搬运")

print("\n[10] move_uids 的边界与空操作")
g = make()
base = g.ordered_uids()
check(g.move_uids([], 3) == base, "空 uid 列表不动")
check(g.move_uids(["not-exist"], 3) == base, "不存在的 uid 不动")
check(g.move_uids(base, 0) == base, "全选拖动等于没动")
check(g.move_uids(["u0"], 0) == base, "拖到原位不动")
check(g.move_uids(["u0"], 999) == ["u1", "u2", "u3", "u4", "u5", "u6", "u7", "u0"], "越界夹到最后")
g = make()
check(g.move_uids(["u7"], -5) == ["u7", "u0", "u1", "u2", "u3", "u4", "u5", "u6"], "负数夹到最前")
g = make()
g.move_uids(["u2", "u3"], 4)
check(g.ordered_uids() == base, "丢回自己原来的空隙 = 不动")

print("\n[11] 搬运不重建 item（缩略图别丢）")
g = make()
g.item(3).setSelected(True)
label_before = g.item(3).text()
g.move_uids(["u3"], 0)
check(g.ordered_uids()[0] == "u3", "u3 到了最前")
check(g.item(0).text() == label_before, "文字原样保留", label_before)
check(not g.item(0).icon().isNull(), "缩略图/占位图还在")
check("u3" in g.selected_uids(), "搬完选中态还原", str(g.selected_uids()))

print("\n[12] order_changed 一次拖动只发一次")
calls: list[list[str]] = []
g = make()
g.order_changed.connect(lambda u: calls.append(u))
r = [g.visualItemRect(g.item(i)) for i in range(8)]
drag(g, r[0].center(), QPoint(r[4].right() - 2, r[4].center().y()))
check(len(calls) == 1, "只发一次信号", f"{len(calls)} 次")
check(calls and calls[0] == g.ordered_uids(), "信号内容与界面顺序一致")

print("\n[13] 拖动时画了插入线和幽灵图")
g = make()
r = [g.visualItemRect(g.item(i)) for i in range(8)]
base_img = g.viewport().grab().toImage()
press(g, r[0].center())
move(g, QPoint(r[3].center().x(), r[3].center().y()))
img = g.viewport().grab().toImage()
diff = 0
cols = set()
for y in range(0, img.height(), 6):
    for x in range(img.width()):
        if img.pixel(x, y) != base_img.pixel(x, y):
            diff += 1
            cols.add(x)
want = r[3].left() - g.PAD // 2
check(diff > 0, "拖动中画面有变化", f"{diff} 个像素点")
# 落在第 4 格中心线上，插到它前面还是后面都算合理，两个候选位置都认
cands = {g._drop_row}
line_x = []
for row in cands:
    if row is not None and row < g.count():
        line_x.append(max(2, g.visualItemRect(g.item(row)).left() - g.PAD // 2))
check(
    any(any(abs(x - lx) <= 6 for x in cols) for lx in line_x),
    "插入线在预期横坐标",
    f"drop_row={g._drop_row}, 候选 {line_x}, want≈{want}",
)
check(g._drag_pix is not None and not g._drag_pix.isNull(), "幽灵缩略图已生成")
release(g, QPoint(r[3].center().x(), r[3].center().y()))
check(not g._dragging, "松手后退出拖动态")

print("\n[14] 外部文件拖入一律不接（交给主窗口）")
g = make()
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile("C:/tmp/a.pdf")])
ev = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
g.dragEnterEvent(ev)
check(not ev.isAccepted(), "带 urls 的拖入被 ignore")

print("\n[15] 普通单击仍然只是选中（别把点击吃掉）")
g = make()
r = [g.visualItemRect(g.item(i)) for i in range(8)]
press(g, r[3].center())
release(g, r[3].center())
check(not g._dragging, "单击不进拖动态")
check(g.selected_uids() == ["u3"], "单击只选中这一格", str(g.selected_uids()))
check(g.ordered_uids()[3] == "u3", "顺序没被点击改动")
# 多选状态下点其中一格再松手，Qt 默认收敛成单选
g = make()
g.item(1).setSelected(True)
g.item(4).setSelected(True)
r = [g.visualItemRect(g.item(i)) for i in range(8)]
press(g, r[1].center())
release(g, r[1].center())
check(g.selected_uids() == ["u1"], "多选后单击收敛成单选", str(g.selected_uids()))

print("\n[16] 空队列拖动不炸")
g = make(0)
check(g.move_uids(["x"], 0) == [], "空队列 move 返回空")
check(g._gap_at(QPoint(5, 5)) == 0, "空队列 gap 为 0")
press(g, QPoint(5, 5))
move(g, QPoint(60, 60))
release(g, QPoint(60, 60))
check(not g._dragging, "空队列上拖不会进拖动态")

print(f"\nRESULT = {'PASS' if not FAIL else 'FAIL'}（{PASS} 项通过，{len(FAIL)} 项失败）")
if FAIL:
    for f in FAIL:
        print("  ✗", f)
sys.exit(0 if not FAIL else 1)
