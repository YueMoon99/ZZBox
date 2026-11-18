"""PDF 工作台的页面缩略图网格。

队列在这里换了形态：视频和图片是「一行一个文件」，PDF 是「一格一页」。
一份 80 页的扫描件进来就是 80 个格子，用户直接对着页面排序、删页、旋转，
不用先想"这份文件包含哪几页"。

  · 多选 —— ExtendedSelection，支持 Ctrl 点选、Shift 连选、框选
  · 拖动排序 —— 纯鼠标事件自己实现，不走 Qt 的拖放协议（原因见下）
  · Ctrl + 滚轮 —— 拦截 wheelEvent 改格子尺寸

为什么拖动要自己实现
--------------------
IconMode 下想让格子排得整整齐齐，必须 setMovement(Static)，否则卡片可以被
拖到画布任意坐标，排版立刻散架。而 Static 会连带把 Qt 自己的拖动手势一起
禁掉 —— 实测（tools/_probe_drag.py）左键按住拖，startDrag() 根本不会被调用。
Snap / Free 下能触发，代价是格子自由漂移、模型顺序和视觉顺序对不上。

中间试过「Static + 自己 new QDrag」。缩略图能跟着鼠标飘，但整条路上有三个
问题，而且互相牵连：

  · 光标一直是 🚫。QDrag.exec() 的接受权在 Qt 的拖放协议手里，得靠目标控件
    的 dragEnterEvent 逐级 accept 才能变成正常光标，本控件在全窗口命中测试
    里拿到的事件路径和源码里直接调 sendEvent 完全不同，很难稳定复现；
  · 松手之后没有 drop，顺序不变；
  · QDrag.exec() 期间吞掉 move，回来之后残余的移动事件又被 QListView 当成
    "按住拖动选一块区域"，于是留下一个直到下次点击才消失的选框（截图里的
    那个蓝框就是它）。

结论：这一个控件内部的"按下-移动-松手"，根本不需要操作系统的拖放协议。
现在全走普通鼠标事件：按下记坐标，越过阈值进入拖动态，移动时算落点并画
幽灵图 + 插入线，松手就地重排。好处是没有任何协议层，事件不会丢，也不
会再冒出选框；代价是要自己在拖动时屏蔽 super 的鼠标处理（见 _dragging 注释）。

缩略图在后台线程渲染，这里只负责把 PNG 字节转成 QPixmap。
QPixmap 必须在主线程构造，所以后台线程传回来的是 bytes 而不是 QPixmap。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from app.ui import style

UID_ROLE = Qt.UserRole + 1
# 格子标题下面那行小字（当前大小 → 预估大小）。压在 item 的 data 上而不是
# 拼进文本，是因为它要单独控制字号和颜色，而且随时可能被估算结果刷新
SUB_ROLE = Qt.UserRole + 2
SUB_TONE_ROLE = Qt.UserRole + 3
# 缩略图右上角的小角标（如「已压缩」绿 / 「不可压缩」黄）。空字符串就是不画。
BADGE_ROLE = Qt.UserRole + 4
BADGE_TONE_ROLE = Qt.UserRole + 5
# 角标配色：绿底白字（成功）/ 黄底深字（警示）
_BADGE_COLORS = {
    "ok": ("#2f9e63", "#ffffff"),
    "warn": ("#e8b21c", "#3f2d00"),
}


class _PageDelegate(QStyledItemDelegate):
    """缩略图 + 标题 + 一行小字，全部自绘。

    为什么不"清空 opt.text 后交给 super"：QStyleSheetStyle 处理
    CE_ItemViewItem 时会自己从 model 取 DisplayRole 再画一遍，清 opt.text
    拦不住 —— 结果是标题出现重影，两层字错开 3~5px（放大 4 倍很明显）。
    为此把背景、图标、文字全接过来自己画，一个字节都不让样式表经手；
    颜色仍取 style 模块的常量，和全局主题保持一致。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icon_w = 148
        self.icon_h = 210
        self.text_h = 44
        self.pad_top = 4

    def paint(self, painter, option, index) -> None:  # noqa: N802
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        # ---- 底色：选中就描边，悬停给一点提亮
        if selected:
            painter.setPen(QPen(QColor(style.ACCENT), 1))
            painter.setBrush(QColor(style.ROW_SEL))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 7, 7)
        elif hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#27272d"))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 7, 7)

        # ---- 缩略图：水平居中贴顶
        icon_target: QRect | None = None
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            iw, ih = self.icon_w, self.icon_h
            target = QRect(
                rect.left() + (rect.width() - iw) // 2, rect.top() + self.pad_top, iw, ih
            )
            icon_target = target
            icon.paint(
                painter, target, Qt.AlignCenter, QIcon.Normal, QIcon.Off
            )

        # ---- 右上角小角标（「已压缩」绿 / 「不可压缩」黄）：贴着缩略图右上，压在图上
        badge = index.data(BADGE_ROLE) or ""
        if badge and icon_target is not None:
            tone = index.data(BADGE_TONE_ROLE) or "ok"
            bf = QFont(option.font)
            bf.setPixelSize(9)
            bf.setBold(True)
            painter.setFont(bf)
            bfm = painter.fontMetrics()
            tw = bfm.horizontalAdvance(str(badge))
            bw, bh = tw + 12, 16
            bx = icon_target.right() - bw + 4   # 稍微探出卡片右缘，像截图那样
            by = icon_target.top() - 2
            painter.setPen(Qt.NoPen)
            bg, fg = _BADGE_COLORS.get(tone, _BADGE_COLORS["ok"])
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(QRect(bx, by, bw, bh), 4, 4)
            painter.setPen(QColor(fg))
            painter.drawText(QRect(bx, by, bw, bh), Qt.AlignCenter, str(badge))

        # ---- 两行字
        title = index.data(Qt.DisplayRole) or ""
        sub = index.data(SUB_ROLE) or ""
        tone = index.data(SUB_TONE_ROLE) or "dim"
        top = rect.top() + self.pad_top + self.icon_h + 4
        avail = max(0, rect.bottom() - top)

        painter.setRenderHint(QPainter.TextAntialiasing, True)
        f = QFont(option.font)
        f.setPixelSize(11)
        painter.setFont(f)
        fm = painter.fontMetrics()
        f2 = QFont(option.font)
        f2.setPixelSize(9)
        painter.setFont(f2)
        fm2 = painter.fontMetrics()
        line1 = fm.height()
        line2 = fm2.height() if sub else 0
        y = top + max(0, (avail - (line1 + line2)) // 2)

        inner_w = rect.width() - 6
        painter.setFont(f)
        painter.setPen(QColor(style.TEXT if selected else style.DIM))
        painter.drawText(
            QRect(rect.left() + 3, y, inner_w, line1),
            Qt.AlignHCenter | Qt.AlignVCenter,
            fm.elidedText(str(title), Qt.ElideMiddle, inner_w),
        )
        if sub:
            painter.setFont(f2)
            painter.setPen(
                QColor(
                    {
                        "ok": style.BLUE_LIGHT,
                        "warn": style.WARN_COLOR,
                        "accent": style.BLUE_LIGHT,
                    }.get(tone, style.MUTED)
                )
            )
            painter.drawText(
                QRect(rect.left() + 3, y + line1, inner_w, line2),
                Qt.AlignHCenter | Qt.AlignVCenter,
                fm2.elidedText(str(sub), Qt.ElideRight, inner_w),
            )
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(self.icon_w + 14, self.icon_h + self.text_h)


class PageGrid(QListWidget):
    """页面格子墙。数据不在这里，这里只有 uid 和长什么样。"""

    order_changed = Signal(list)      # 排序变化后新的 uid 顺序
    zoom_changed = Signal(int)        # 当前单格宽度
    context_requested = Signal(object, object)  # (选中的 uid 列表, 全局坐标)
    delete_requested = Signal()       # Delete 键：删掉选中的格子

    ZOOM_MIN = 92
    ZOOM_MAX = 268
    ZOOM_DEFAULT = 148
    ZOOM_STEP = 16
    # A4 的宽高比。格子高度按它算，横版页面在里面留白是正常的 ——
    # 纸张本来就是这样，不该为了填满格子去裁内容
    PAPER = 1.4142
    # 标题 + 尺寸行。压缩功能一旦启用，每格下面要显示「1.6 MB → 392 KB」，
    # 一行放不下；固定两行高度，没显示副标题时看着就是稍微松一点
    TEXT_H = 44
    PAD = 14
    # 拖动时鼠标离上下边缘多近就开始自动滚动
    SCROLL_EDGE = 28
    SCROLL_STEP = 24

    def __init__(
        self,
        empty_text: str = "把 PDF 或图片拖到这里，或点右上角“+”添加",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("pageGrid")
        self._empty_text = empty_text
        self._zoom = self.ZOOM_DEFAULT
        self._delegate = _PageDelegate(self)
        self.setItemDelegate(self._delegate)

        # 拖动状态。_dragging 为 True 时鼠标事件全部由自己处理，
        # 一个都不交给 super（交给它就会画出那个讨厌的框选框）
        self._press_pos: QPoint | None = None
        self._press_uid: str | None = None
        self._dragging = False
        self._drag_uids: list[str] = []
        self._drag_pix: QPixmap | None = None
        self._cursor_pos = QPoint(0, 0)
        self._drop_row: int | None = None

        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        # Static：格子只能整格换位，不能被拖到画布任意坐标
        self.setMovement(QListWidget.Static)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True)

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # 外部文件拖进来要冒泡给主窗口，所以这里接 drop 但不处理（见 dropEvent）
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDropIndicatorShown(False)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSpacing(4)
        self.setFocusPolicy(Qt.StrongFocus)

        self._apply_zoom()

    # ------------------------------------------------------------ 尺寸
    def _apply_zoom(self) -> None:
        z = self._zoom
        icon_h = round(z * self.PAPER)
        self.setIconSize(QSize(z, icon_h))
        self.setGridSize(QSize(z + self.PAD, icon_h + self.TEXT_H))
        # delegate 自己画文本，必须知道图标多高，否则两行字会压到缩略图上
        self._delegate.icon_w = z
        self._delegate.icon_h = icon_h
        self._delegate.text_h = self.TEXT_H
        self._apply_hints()
        self.zoom_changed.emit(z)

    def set_zoom(self, value: int) -> None:
        z = max(self.ZOOM_MIN, min(self.ZOOM_MAX, int(value)))
        if z == self._zoom:
            return
        self._zoom = z
        self._apply_zoom()

    def zoom(self) -> int:
        return self._zoom

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Ctrl + 滚轮缩放格子，普通滚轮照常滚动列表。"""
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.set_zoom(self._zoom + (self.ZOOM_STEP if delta > 0 else -self.ZOOM_STEP))
            event.accept()
            return
        if self._dragging:
            # 拖着格子时滚轮不该改缩放，也不该让列表在脚下滚走
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------ 数据
    def rebuild(self, entries: list[tuple[str, str]]) -> None:
        """用 (uid, 文字) 列表重建整面墙。缩略图随后由 set_thumb 填。"""
        self.blockSignals(True)
        self.clear()
        for uid, label in entries:
            item = QListWidgetItem(label)
            item.setData(UID_ROLE, uid)
            item.setIcon(self._placeholder_icon())
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setSizeHint(self._fixed_hint())
            item.setToolTip(label)
            self.addItem(item)
        self.blockSignals(False)
        self._reset_drag()

    def _apply_hints(self) -> None:
        """缩放后每格的 sizeHint 也要跟着改，否则格子还是旧尺寸。"""
        hint = self._fixed_hint()
        for i in range(self.count()):
            self.item(i).setSizeHint(hint)

    def ordered_uids(self) -> list[str]:
        return [self.item(i).data(UID_ROLE) for i in range(self.count())]

    def set_label(self, uid: str, label: str) -> None:
        item = self._item_of(uid)
        if item is None:
            return
        item.setText(label)
        item.setToolTip(label)

    def set_sub(self, uid: str, text: str, tone: str = "dim") -> None:
        """格子标题下面那行小字。空字符串就是把副标题清掉。"""
        item = self._item_of(uid)
        if item is None:
            return
        item.setData(SUB_ROLE, text)
        item.setData(SUB_TONE_ROLE, tone)
        tip = item.toolTip().split("\n")[0]
        item.setToolTip(f"{tip}\n{text}" if text else tip)

    def set_badge(self, uid: str, text: str, tone: str = "ok") -> None:
        """缩略图右上角的角标。tone=ok 绿底（已压缩）/ warn 黄底（不可压缩）。
        空字符串清除；改动会触发重绘。"""
        item = self._item_of(uid)
        if item is None:
            return
        item.setData(BADGE_ROLE, text)
        item.setData(BADGE_TONE_ROLE, tone)
        self.viewport().update()

    def set_thumb(self, uid: str, png: bytes) -> None:
        item = self._item_of(uid)
        if item is None:
            return
        pix = QPixmap()
        if not pix.loadFromData(png, "PNG"):
            return
        item.setIcon(self._flat_icon(pix))

    @staticmethod
    def _flat_icon(pix: QPixmap) -> QIcon:
        """把同一张图塞进 QIcon 的所有状态。

        Qt 默认会给选中/悬停状态的图标做高亮染色，缩略图被染成一片蓝之后
        完全看不出页面内容。四个模式全用原图，选中态只靠底色和描边表达。
        """
        icon = QIcon()
        for mode in (
            QIcon.Normal,
            QIcon.Selected,
            QIcon.Active,
            QIcon.Disabled,
        ):
            icon.addPixmap(pix, mode)
        return icon

    def _fixed_hint(self) -> QSize:
        """固定每格尺寸。

        不固定的话，格子宽度会跟着「第 12 页 · 某某文件名」这串字的长度走，
        一列里宽宽窄窄，看着像没对齐的瓷砖。文字超出部分由 ElideMiddle 处理。
        """
        return QSize(self._zoom + self.PAD, round(self._zoom * self.PAPER) + self.TEXT_H)

    def _item_of(self, uid: str) -> QListWidgetItem | None:
        for i in range(self.count()):
            item = self.item(i)
            if item.data(UID_ROLE) == uid:
                return item
        return None

    def _placeholder_icon(self) -> QIcon:
        """占位图：一张空白的纸，右下角还带个折角。

        直接给空 QIcon 的话，item 在缩略图到达前会缩成一行文字，
        整面墙的排版会先塌一次再弹开，很晃眼。
        """
        w, h = self._zoom, round(self._zoom * self.PAPER)
        pix = QPixmap(w, h)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2a31"))
        p.drawRoundedRect(QRect(1, 1, w - 2, h - 2), 4, 4)
        p.end()
        return self._flat_icon(pix)

    # ------------------------------------------------------------ 选择
    def selected_uids(self) -> list[str]:
        return [it.data(UID_ROLE) for it in self.selectedItems()]

    def select_all_items(self) -> None:
        self.selectAll()

    # ------------------------------------------------------------ 排序
    def move_uids(self, uids: list[str], gap: int) -> list[str]:
        """把 uids 整体搬到第 gap 个空隙（0 = 最前，count = 最后）。

        纯数据操作，不碰事件系统，所以能单独测。返回最终顺序。
        """
        order = self.ordered_uids()
        moving_set = {u for u in uids if u in order}
        if not moving_set or len(moving_set) == len(order):
            # 全选后拖动等于没动，别白折腾一遍（还会把选中态抖一下）
            return order

        moving = [u for u in order if u in moving_set]   # 保持队列内的相对顺序
        gap = max(0, min(len(order), int(gap)))
        # 目标空隙是按"搬走之前"的坐标算的，得扣掉落在它左边、马上要被
        # 搬走的元素，否则往后拖会少走一格、往前拖会多走一格
        before = sum(1 for u in order[:gap] if u in moving_set)
        insert_at = gap - before
        rest = [u for u in order if u not in moving_set]
        new_order = rest[:insert_at] + moving + rest[insert_at:]
        if new_order == order:
            return order

        self._apply_order(new_order, keep_selected=moving_set)
        self.order_changed.emit(new_order)
        return new_order

    def _apply_order(self, new_order: list[str], keep_selected: set[str]) -> None:
        """按新顺序重排 item。item 对象本身搬运，不重建。

        重建会丢缩略图（必须回后台重渲染），所以这里 takeItem 出来再按序
        addItem 回去 —— 图标、文字、提示全部原地保留。
        """
        items: dict[str, QListWidgetItem] = {}
        self.blockSignals(True)
        while self.count():
            it = self.takeItem(0)
            items[it.data(UID_ROLE)] = it
        for uid in new_order:
            it = items.get(uid)
            if it is not None:
                self.addItem(it)
        # takeItem 会把选中态清掉，搬完得还原，否则用户的选中"消失"了
        for uid in keep_selected:
            it = self._item_of(uid)
            if it is not None:
                it.setSelected(True)
        self.blockSignals(False)

    # ------------------------------------------------------------ 拖动
    def _gap_at(self, pos: QPoint) -> int:
        """落点对应的插入位置：0..count。

        格子是按行从左到右排的，所以顺序扫一遍：先比行（在它的上边就插它
        前面），同一行再比左右中线（在左半边插前面，右半边继续往后看）。
        """
        for i in range(self.count()):
            r = self.visualItemRect(self.item(i))
            if not r.isValid():
                continue
            if pos.y() < r.top():
                return i
            if r.top() <= pos.y() <= r.bottom() and pos.x() < r.center().x():
                return i
        return self.count()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            it = self.itemAt(self._press_pos)
            self._press_uid = it.data(UID_ROLE) if it else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if self._dragging:
            # 拖动中：一个事件都不给 super。给了它就会当成"按住拉框选择"，
            # 松手后还会留一个直到下次点击才消失的选框
            self._cursor_pos = pos
            self._auto_scroll(pos)
            row = self._gap_at(pos)
            if row != self._drop_row:
                self._drop_row = row
            self.viewport().update()
            event.accept()
            return

        # 按在某一格上拖：整段自己处理，绝不交给 super。
        # 交给它的话，还没越过阈值的那几帧移动会被当成拉框选择，多选会被
        # 悄悄清成"只剩当前这一格" —— 用户选了 5 页准备一起拖，手一抖就
        # 只剩 1 页过去。item 视图本来也不支持"从某一格开始拉框"，
        # 所以这里完全不需要 super。
        if self._press_uid is not None and event.buttons() & Qt.LeftButton:
            if (
                self._press_pos is not None
                and (pos - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._start_drag()
                self._cursor_pos = pos
                self._drop_row = self._gap_at(pos)
                self.viewport().update()
            event.accept()
            return

        # 空白处按下 → 照旧交给 QListView 拉框选择
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging and event.button() == Qt.LeftButton:
            row = self._drop_row
            moving = self._drag_uids
            self._reset_drag()
            if row is not None and moving:
                self.move_uids(moving, row)
            event.accept()
            return
        self._press_pos = None
        self._press_uid = None
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """右键：右击未选中的格子先把它选中，再把菜单交给主窗口。

        菜单项要对着"当前选中的这一批"操作，所以控件的职责只到「告诉你
        选中了谁、鼠标在哪」，具体有哪些动作由主窗口决定 —— 否则这个
        通用控件就得反过来认识旋转、导出、压缩这些业务概念。
        """
        if self._dragging:
            return
        item = self.itemAt(event.pos())
        if item is not None and item.data(UID_ROLE) not in self.selected_uids():
            self.setCurrentItem(item)
        uids = self.selected_uids()
        if not uids:
            return
        self.context_requested.emit(uids, event.globalPos())
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._dragging and event.key() == Qt.Key_Escape:
            self._reset_drag()      # Esc 放弃这次拖动，顺序不动
            event.accept()
            return
        # Delete 删选中格子，和队列表格一致；真正删除走主窗口（要压撤销快照）
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_uids():
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # 拖动中窗口失焦（Alt+Tab、弹窗）就收手，否则松手事件可能收不到
        if self._dragging:
            self._reset_drag()
        super().focusOutEvent(event)

    def _start_drag(self) -> None:
        sel = self.selected_uids()
        if self._press_uid not in sel:
            sel = [self._press_uid]      # 拖了一个没选中的格子，就只搬它
        self._drag_uids = sel
        self._dragging = True
        self._drop_row = None

        self._drag_pix = None
        item = self._item_of(self._press_uid)
        if item is not None:
            pix = item.icon().pixmap(self.iconSize())
            if not pix.isNull():
                self._drag_pix = pix.scaledToHeight(
                    min(120, pix.height()), Qt.SmoothTransformation
                )
        # 闭手光标：让用户明确知道"现在正在搬东西"，而不是靠系统那个 🚫
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _reset_drag(self) -> None:
        self._dragging = False
        self._drag_uids = []
        self._drag_pix = None
        self._drop_row = None
        self._press_pos = None
        self._press_uid = None
        self.viewport().unsetCursor()
        self.viewport().update()

    def _auto_scroll(self, pos: QPoint) -> None:
        """拖到边缘自动滚，否则 80 页的队列没法把第 3 页拖到最后。"""
        bar = self.verticalScrollBar()
        if pos.y() < self.SCROLL_EDGE:
            bar.setValue(bar.value() - self.SCROLL_STEP)
        elif pos.y() > self.viewport().height() - self.SCROLL_EDGE:
            bar.setValue(bar.value() + self.SCROLL_STEP)

    # ------------------------------------------------------------ 外部拖入
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        # 内部排序已经不走 Qt 的拖放协议，所以这里一律不接；
        # 外部文件要靠 ignore 冒泡到主窗口去（它会自动切到 PDF 页并导入）
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() and self._drop_row is not None:
            self._paint_drop_line()
        if self._dragging and self._drag_pix is not None:
            self._paint_drag_ghost()
        if self.count() or not self._empty_text:
            return
        p = QPainter(self.viewport())
        p.setPen(QColor(style.DIM))
        p.drawText(
            self.viewport().rect(),
            Qt.AlignCenter | Qt.TextWordWrap,
            self._empty_text,
        )
        p.end()

    def _paint_drop_line(self) -> None:
        """画插入位置的竖线。没有这根线，用户完全不知道会插到第几格。"""
        if self._drop_row < self.count():
            r = self.visualItemRect(self.item(self._drop_row))
            x = r.left() - self.PAD // 2
        else:
            r = self.visualItemRect(self.item(self.count() - 1))
            x = r.right() + self.PAD // 2
        if not r.isValid():
            return
        # 插到第一格前面时 x 会算成负数、插到最后一格后面会跑出右边界，
        # 两种情况下线都画在视口外面 —— 用户看不到任何提示，所以夹回来
        x = max(2, min(self.viewport().width() - 3, x))
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(style.BLUE_LIGHT))
        pen.setWidth(3)
        p.setPen(pen)
        p.drawLine(x, r.top(), x, r.bottom())
        p.end()

    def _paint_drag_ghost(self) -> None:
        """跟着鼠标走的半透明缩略图，告诉用户"手里正拿着这几页"。"""
        pix = self._drag_pix
        x = self._cursor_pos.x() - pix.width() // 2
        y = self._cursor_pos.y() - pix.height() // 2
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(0.72)
        p.drawPixmap(x, y, pix)
        # 描一圈边。白页叠在白色格子上、或者缩略图本身就是深色时，
        # 不描边就完全看不出来"手里拿着东西"
        p.setOpacity(1.0)
        pen = QPen(QColor(style.BLUE_LIGHT))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(x, y, pix.width() - 1, pix.height() - 1)
        p.end()
