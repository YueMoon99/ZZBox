"""可复用控件：卡片、分段选择、文件队列表格。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRubberBand,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui import style

# 状态 -> (圆点颜色, 默认文字)
PHASES: dict[str, tuple[str, str]] = {
    "ready": (style.WARN_COLOR, "就绪"),
    "locked": (style.DOT_LOCKED, "已锁定"),
    "running": (style.BLUE_LIGHT, "压制中"),
    "done": (style.OK_COLOR, "已完成压制"),
    "failed": (style.ERR_COLOR, "失败"),
}


@dataclass
class RowState:
    """一个队列项的全部可变状态，列表重建时据此还原。"""

    phase: str = "ready"
    locked: bool = False
    status: str = ""        # 覆盖默认状态文字（如“压制中 42%”）
    tip: str = ""           # 悬停提示（失败原因等）
    extra: dict = field(default_factory=dict)

    @property
    def dot_color(self) -> str:
        if self.locked:
            return style.DOT_LOCKED
        return PHASES.get(self.phase, PHASES["ready"])[0]

    @property
    def status_text(self) -> str:
        if self.status:
            return self.status
        if self.locked:
            return "已锁定"
        return PHASES.get(self.phase, PHASES["ready"])[1]


class Card(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        # 竖直方向必须允许被拉伸：用 Fixed 时网格会把它居中，四张卡片顶边就参差不齐
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("hint")
        outer.addWidget(self.title)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addLayout(self.body)
        self.footer = QLabel("")
        self.footer.setObjectName("hint")
        self.footer.setWordWrap(True)
        outer.addWidget(self.footer)
        # 卡片被拉到统一高度后，多余空间留到底部，别把内容拆散（否则标题到按钮之间会出现大空隙）
        outer.addStretch(1)


class ChipGroup(QWidget):
    """互斥的胶囊按钮组，可附加一个尾随控件（如自定义输入框）。

    ``fill=True`` 用于「参数表」式的网格（OptionPanel 的单元格）：这一组
    按钮平分单元格宽度，于是同一列上下两行的按钮组总宽恒等、最右侧边缘
    严丝合缝地对齐 —— 4 个按钮的「超分」和 3 个按钮的「编码」右边缘落在
    同一条竖线上，看起来像一张表而不是两排参差不齐的胶囊。
    ``fill=False`` 时保持原来的定宽行为（按钮按最宽的那个字块统一宽度）。
    """

    changed = Signal(str)

    def __init__(
        self,
        options: list[tuple[str, str]],
        parent: QWidget | None = None,
        stretch: bool = True,
        fill: bool = False,
    ):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            self._group.addButton(btn)
            # fill 模式下每个按钮拿同样的伸缩因子，多余宽度才严格均分，
            # 不会出现「谁字多谁多占」的偏差
            lay.addWidget(btn, 1 if fill else 0)
            self._buttons[key] = btn
        # 胶囊统一尺寸：组内等宽、全局等高，看起来像一套控件而不是
        # 「谁字多谁胖」的杂牌军。宽度下限 72px，短字块（关/2×）随长板拉齐。
        if self._buttons:
            w = max(
                72, max(b.sizeHint().width() for b in self._buttons.values())
            )
            for b in self._buttons.values():
                b.setFixedHeight(28)
                if fill:
                    # 只钉下限，宽度交给布局去均分；上限放开才拉得动
                    b.setMinimumWidth(w)
                    b.setMaximumWidth(16777215)
                    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                else:
                    b.setFixedWidth(w)
        if stretch and not fill:
            # fill 模式下按钮自己吃满整格，再来个弹簧就会把按钮挤扁
            lay.addStretch(1)
        self._value = options[0][0] if options else ""
        if options:
            self._buttons[options[0][0]].setChecked(True)

    # ------------------------------------------------------------------
    def _select(self, key: str) -> None:
        self._value = key
        self.changed.emit(key)

    def set_value(self, key: str, emit: bool = False) -> None:
        btn = self._buttons.get(key)
        if not btn:
            return
        btn.setChecked(True)
        self._value = key
        if emit:
            self.changed.emit(key)

    def value(self) -> str:
        return self._value

    def button(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)

    def clear_selection(self) -> None:
        """自定义输入被启用时，取消所有胶囊的选中态。"""
        self._group.setExclusive(False)
        for b in self._buttons.values():
            b.setChecked(False)
        self._group.setExclusive(True)
        self._value = ""

    def set_available(self, key: str, ok: bool, tip: str = "") -> None:
        btn = self._buttons.get(key)
        if not btn:
            return
        btn.setEnabled(ok)
        if ok:
            btn.setToolTip("")
        else:
            btn.setToolTip(tip or "当前显卡不支持该编码器")
            if btn.isChecked():
                for k, b in self._buttons.items():
                    if b.isEnabled():
                        self.set_value(k, emit=True)
                        break


class _TabStrip(QWidget):
    """页签条：一组扁平页签按钮。

    原来这里会画一条贯穿底部、并在活动页签处断开的分隔线，让页签和内容区
    连成一体（Windows 属性对话框观感）。但内容区是一张圆角卡片 ——
    直线在圆角外面横过去，看起来就是「圆角框外多了一个直角框」。现在
    内容只保留圆角卡片这一层边框，页签改成扁平胶囊，不再画线。
    """

    TAB_H = 30

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(self.TAB_H)
        lay = QHBoxLayout(self)
        # 页签从内容区左边缘起算，和下方卡片左对齐
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self._lay = lay
        self._buttons: list[QPushButton] = []
        self._active = 0

    def add_tab(self, text: str, tip: str = "") -> QPushButton:
        btn = QPushButton(text, self)
        btn.setObjectName("ptab")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(self.TAB_H)
        if tip:
            btn.setToolTip(tip)
        # 用 0 宽度占位，真实宽度交给字体度量，避免中英文混排时页签忽宽忽窄
        fm = btn.fontMetrics()
        btn.setFixedWidth(fm.horizontalAdvance(text) + 36)
        self._lay.addWidget(btn)
        self._buttons.append(btn)
        return btn

    def finish(self) -> None:
        self._lay.addStretch(1)

    def set_active(self, index: int) -> None:
        self._active = index
        self.update()


class PropertyTabs(QWidget):
    """Windows 属性对话框风格的页签容器：页签条 + 内容面板。

    与 QTabWidget 的区别只有一个，但那一个是刚需：面板顶边必须在活动页签
    处断开，让页签和内容连成一体。QTabWidget 的 pane 是完整矩形，做不出来。
    """

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # 高度跟着内容走：让网格/外层布局不要把它拉长，否则卡片会被摊开
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.strip = _TabStrip()
        outer.addWidget(self.strip)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ptabpane")
        outer.addWidget(self.stack)

        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

    # ------------------------------------------------------------------
    def add_page(self, widget: QWidget, title: str, tip: str = "") -> int:
        btn = self.strip.add_tab(title, tip)
        btn.clicked.connect(lambda _=False, w=widget: self.setCurrentWidget(w))
        self._group.addButton(btn)
        self._buttons.append(btn)
        idx = self.stack.addWidget(widget)
        if idx == 0:
            btn.setChecked(True)
        return idx

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self.strip.set_active(index)
        self.currentChanged.emit(index)

    def finish_tabs(self) -> None:
        """所有页签都加完后调用：补一个弹性空白，把页签压在左边。"""
        self.strip.finish()

    def setCurrentWidget(self, widget: QWidget) -> None:
        self.setCurrentIndex(self.stack.indexOf(widget))

    def currentIndex(self) -> int:  # noqa: N802
        return self.stack.currentIndex()

    def button(self, index: int) -> QPushButton | None:
        if 0 <= index < len(self._buttons):
            return self._buttons[index]
        return None


class HintLine(QLabel):
    """面板底部的单行提示：高度钉死一行，放不下就横向滚动播放。

    面板高度绝不能因为提示文字出现/清空/换行而变化 —— 导入文件时黄色
    警告突然冒出来把面板撑高、队列被挤扁，就是这么来的。所以这里：
      · 高度固定一行，永远不换行；
      · 多条提示由调用方合并成一行（「 · 」连接）；
      · 超宽就整行跑马灯滚动，不撑高、不裁切。
    """

    SCROLL_SPEED = 1      # 每帧像素
    SCROLL_GAP = 48       # 首尾相接时的空隙

    def __init__(
        self,
        text: str = "",
        color: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self._full = text or ""
        self._color = color or style.DIM
        self._offset = 0
        self.setFixedHeight(18)
        self.setWordWrap(False)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._offset = 0
        super().setText(self._full)
        self._sync_timer()
        self.update()

    def _text_width(self) -> int:
        return self.fontMetrics().horizontalAdvance(self._full)

    def _overflow(self) -> bool:
        return bool(self._full) and self._text_width() > self.width() - 4

    def _sync_timer(self) -> None:
        if self._overflow():
            self._timer.start()
        else:
            self._timer.stop()
            self._offset = 0

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_timer()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._offset += self.SCROLL_SPEED
        if self._offset > self._text_width() + self.SCROLL_GAP:
            self._offset = 0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._full:
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(QColor(self._color))
        rect = QRect(0, 0, self.width(), self.height())
        if not self._overflow():
            painter.drawText(
                rect.adjusted(2, 0, -2, 0), Qt.AlignLeft | Qt.AlignVCenter, self._full
            )
            return
        # 超宽：跑马灯，两份文字首尾相接循环滚动
        step = self._text_width() + self.SCROLL_GAP
        x = -self._offset
        for i in (0, 1):
            painter.drawText(
                QRect(x + i * step, 0, self._text_width() + 4, self.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                self._full,
            )


class OptionPanel(QFrame):
    """集成化参数面板：一张扁卡片，内部按「标签 + 控件」铺成网格。

    取代原来 2×2 四张 Card 的布局。四张卡每张都有标题行和说明行，光这些
    装饰就吃掉一百多像素 —— 那是整整三条队列的高度。参数本身一行就够，
    说明挪进 tooltip，视觉上从「四个盒子」变成一个「参数表」，队列因此
    多出三四行可见区域。

    底部提示区固定两行（灰色一行 + 黄色一行），高度永远不变：文字出现、
    清空都不许把面板撑高，否则导入文件时队列突然变矮一截。
    """

    HINT_H = 18

    def __init__(self, cols: int = 2, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("optpanel")
        self._cols = max(1, cols)
        self._row = 0
        self._col = 0
        self._cells: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(18)
        self._grid.setVerticalSpacing(8)
        outer.addLayout(self._grid)
        for c in range(self._cols):
            self._grid.setColumnStretch(c, 1)

        # 提示区恒定两行：灰色一行（规格/状态）+ 黄色一行（警示）。
        # 两行始终占位 —— 空的那行留白，不让面板高度跟着文字跳。
        self.note = HintLine("", color=style.DIM)
        self.note.setObjectName("hint")
        outer.addWidget(self.note)

        self.alert = HintLine("", color=style.WARN_COLOR)
        self.alert.setObjectName("alert")
        outer.addWidget(self.alert)
        # 两个页签的参数行数不同（压缩页 2 行、AI 页 3 行），stack 会把
        # 矮的那页拉到高的那页的高度。多余空间给这个弹簧，参数就钉在上方，
        # 否则 label 会被拉开，行距看着忽宽忽窄。
        outer.addStretch(1)

    # ------------------------------------------------------------------
    def add(self, label: str, widget: QWidget, tag_w: int = 48) -> QWidget:
        """放一个「标签 + 控件」格子，按列数自动换行。"""
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        tag = QLabel(label)
        tag.setObjectName("optlabel")
        tag.setFixedWidth(tag_w)
        lay.addWidget(tag)
        lay.addWidget(widget, 1)

        if self._col >= self._cols:
            self._col = 0
            self._row += 1
        self._grid.addWidget(cell, self._row, self._col)
        self._col += 1
        self._cells.append(cell)
        return cell

    def add_row(self, widget: QWidget) -> None:
        """独占一整行（滑块、长说明这类压不进半格的控件）。"""
        if self._col:
            self._col = 0
            self._row += 1
        self._grid.addWidget(widget, self._row, 0, 1, self._cols)
        self._row += 1

    def set_note(self, text: str) -> None:
        self.note.setText(text)

    def set_alert(self, text: str) -> None:
        """设置黄色警示行；传空串只清文字 —— 行本身常驻，高度不变。"""
        self.alert.setText(text)

    def pin_height(self) -> None:
        """把面板总高钉死在当前 sizeHint 上。

        提示行已经是固定高度，这里再加一道保险：之后任何文字变化
        （哪怕未来有人忘了改回单行）都不会把面板撑高、挤扁队列。
        """
        h = self.sizeHint().height()
        if h > 0:
            self.setFixedHeight(h)


QUEUE_COLUMNS = ("文件名", "原始格式", "导出格式", "原始大小", "预计导出大小", "操作")
COL_NAME, COL_SRC, COL_OUT, COL_SIZE, COL_EST, COL_OPS = range(6)


class RowActions(QWidget):
    """操作列：状态点 · 状态文字 · 锁定 / 重提 / 删除。

    布局不交给 QHBoxLayout：那样列被拖窄时按钮会被挤出单元格右侧、连点都
    点不到。这里手工摆位——
      · 三个按钮钉死在单元格右边缘，列宽怎么变都不位移；
      · 状态点和状态文字贴左边缘，跟着列宽走；
      · 列宽不够先省略文字、再整块隐藏文字，指示点和按钮之间永远留着空隙。
    """

    lock_clicked = Signal(object)
    retry_clicked = Signal(object)
    delete_clicked = Signal(object)
    # 指针进出这一格（含格内的三个按钮）：鼠标停在操作列上时表格收不到
    # mouseMove，整行悬停得靠这里补上，否则高亮会僵在刚离开的那一行
    hover_changed = Signal(object, bool)

    PAD_L = 0           # 单元格控件的左右留白已由样式表的 item padding 提供
    PAD_R = 0
    GAP = 6
    DOT = 8
    BTN_W, BTN_H, BTN_GAP = 32, 22, 4
    # 文字再窄就没意义了，直接隐藏，免得出现半个字
    STATUS_MIN = 18
    # 单元格控件比列窄多少（样式表 item padding 左右各 10px）
    CELL_INSET = 20

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self._text = "就绪"
        self._selected = False
        self._hover = False

        self.dot = QLabel(self)
        self.dot.setFixedSize(self.DOT, self.DOT)

        self.status = QLabel(self)
        self.status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status.setStyleSheet(f"font-size: 11px; color: {style.DIM};")

        self.btn_lock = self._mini("锁定")
        self.btn_lock.setCheckable(True)
        self.btn_lock.setToolTip("锁定后本轮压制会跳过该项")
        self.btn_lock.clicked.connect(lambda: self.lock_clicked.emit(self.path))

        self.btn_retry = self._mini("重提")
        self.btn_retry.setToolTip("状态重置为就绪，可再次参与压制")
        self.btn_retry.clicked.connect(lambda: self.retry_clicked.emit(self.path))

        self.btn_del = self._mini("删除")
        self.btn_del.setToolTip("从队列中移除")
        self.btn_del.clicked.connect(lambda: self.delete_clicked.emit(self.path))

    @classmethod
    def buttons_width(cls) -> int:
        return 3 * cls.BTN_W + 2 * cls.BTN_GAP

    @classmethod
    def min_width(cls) -> int:
        """控件自身不能再窄的宽度：指示点 + 一点空隙 + 三个按钮。

        状态文字不计入——空间不够时它会被隐藏，指示灯和按钮绝不会叠在一起。
        """
        return cls.PAD_L + cls.DOT + cls.GAP + cls.GAP + cls.buttons_width() + cls.PAD_R

    @classmethod
    def min_column_width(cls) -> int:
        """换算成列宽：控件比列窄 CELL_INSET。"""
        return cls.min_width() + cls.CELL_INSET

    def _mini(self, text: str) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setObjectName("rowbtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(self.BTN_W, self.BTN_H)
        return btn

    # ------------------------------------------------------------------
    def _place(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        mid = (h - self.BTN_H) // 2
        x = w - self.PAD_R
        for btn in (self.btn_del, self.btn_retry, self.btn_lock):
            x -= self.BTN_W
            btn.setGeometry(x, mid, self.BTN_W, self.BTN_H)
            x -= self.BTN_GAP
        btn_left = x + self.BTN_GAP + self.GAP      # 文字可用区域的右端

        self.dot.move(self.PAD_L, (h - self.DOT) // 2)
        text_x = self.PAD_L + self.DOT + self.GAP
        avail = btn_left - text_x
        if avail >= self.STATUS_MIN:
            self.status.setVisible(True)
            self.status.setGeometry(text_x, 0, avail, h)
            self.status.setText(
                self.status.fontMetrics().elidedText(self._text, Qt.ElideRight, avail)
            )
        else:
            self.status.setVisible(False)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.hover_changed.emit(self.path, True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hover_changed.emit(self.path, False)
        super().leaveEvent(event)

    def set_selected(self, on: bool) -> None:
        """记下选中态。

        底色不在这里画 —— 操作列是盖在视口上的 cellWidget，自己填色只能填
        它那块（还被 QSS 的 item padding 内缩了 10px），和整行底色对不上，
        看起来就是「只有操作区中间那一小块变色」。整行底色统一由
        QueueTable 在视口里画，这里保持透明，底下的颜色直接透上来。
        """
        if on == self._selected:
            return
        self._selected = on
        self.update()

    def set_hover(self, on: bool) -> None:
        """整行悬停状态（底色同样交给视口画，这里只留状态）。"""
        if on == self._hover:
            return
        self._hover = on
        self.update()

    # ------------------------------------------------------------------
    def apply(self, st: RowState) -> None:
        color = st.dot_color
        self.dot.setStyleSheet(f"background:{color}; border-radius:4px;")
        self._text = st.status_text
        self.status.setStyleSheet(f"font-size: 11px; color: {color};")
        self.status.setToolTip(st.tip or st.status_text)
        self.btn_lock.setChecked(st.locked)
        self.btn_lock.setText("已锁" if st.locked else "锁定")
        self._place()

    def status_text(self) -> str:
        """完整状态文字（不受列宽省略影响），测试与提示用。"""
        return self._text


@dataclass
class RowCells:
    """一行的单元格引用，避免每次刷新都去 cellItem 里查。"""

    items: list[QTableWidgetItem]
    actions: RowActions


class QueueHeader(QHeaderView):
    """表头：在每两列之间画一根竖线，看起来才像资源管理器的列。

    样式表把 section 的 border 全关了（否则每格四周都会描边），所以分割线
    只能自己画：只画「列与列之间」，最右一列的右边不画，避免多出一条边框。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(Qt.Horizontal, parent)

    def paintSection(self, painter, rect, logicalIndex) -> None:  # noqa: N802
        super().paintSection(painter, rect, logicalIndex)
        if logicalIndex >= self.count() - 1:
            return
        painter.save()
        painter.fillRect(rect.right(), rect.top(), 1, rect.height(), QColor(style.BORDER_STRONG))
        painter.restore()


class QueueTable(QTableWidget):
    """文件资源管理器风格的队列表格。

    表格只负责“长成表格的样子”和拖拽落点解析；每一格显示什么由主窗口
    算好后 setText，避免把业务规则塞进控件。

    视频和图片共用一个实现：列数和列语义完全一样（文件名 / 原始格式 /
    导出格式 / 原始大小 / 预计导出大小 / 操作），差别只有空态提示那句话。
    """

    reordered = Signal(int, int)
    # 按下 Delete 键：由主窗口接去执行真正的删除（含确认/撤销等业务规则）
    delete_pressed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        empty_text: str = "把视频文件拖到这里，或点右上角“+”添加文件",
    ):
        super().__init__(0, len(QUEUE_COLUMNS), parent)
        self.setObjectName("queueTable")
        self.setHorizontalHeaderLabels(list(QUEUE_COLUMNS))
        # 表头和单元格统统左对齐，而且都靠左分割线 10px（样式表的 padding），
        # 这样每一列的文字和表头在同一条竖线上；数字列右对齐时，列一被拖宽
        # 文字就跟着滑动，看起来像「拖动这一列，隔壁那列也在动」。
        for col in range(len(QUEUE_COLUMNS)):
            self.horizontalHeaderItem(col).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.horizontalHeaderItem(COL_EST).setToolTip(
            "按编码器 / CRF / 码率与分辨率估算，\n"
            "实际成片通常有 ±25% 浮动，码率模式最准。"
        )

        vh = self.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(36)

        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        # 支持 Ctrl 加选、Shift 连选；框选由下面的鼠标事件自己实现
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # 横向永远不滚动：列宽总和不许超过视口，否则最右边的操作按钮会被
        # 推到看不见的地方（拖回来之前一直是残的）。拖不动就顶住，别溢出。
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 点进来就能用 Delete 删选中项 —— NoFocus 收不到键盘。焦点框靠样式表
        # 的 outline:none 压掉，不会再出现「点完行按钮套一圈虚线」
        self.setFocusPolicy(Qt.ClickFocus)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        # 默认的落点提示线是系统画的一条 1px 黑线，既看不见又会被操作列的
        # cellWidget 盖掉半截。改成自己画：整行宽、2px 强调色蓝。
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropOverwriteMode(False)

        hh = QueueHeader(self)
        self.setHorizontalHeader(hh)
        hh.setHighlightSections(False)
        hh.setSectionsMovable(False)
        hh.setFixedHeight(30)
        # 列宽策略＝资源管理器：
        #   每列都是固定宽度，拖分割线只改「这根线左边那一列」，它右边的列
        #   整体平移。关键是不能给任何一列设 Stretch —— 那样 Qt 会拿那一列
        #   补偿总宽，结果就是「拖第三根线，最左边的文件名变宽变窄，而被拖
        #   的那根线原地不动」，看起来像拖错了列。
        hh.setMinimumSectionSize(56)
        hh.setStretchLastSection(False)
        for col in range(len(QUEUE_COLUMNS)):
            hh.setSectionResizeMode(col, QHeaderView.Interactive)
        for col, width in (
            (COL_NAME, 222),
            (COL_SRC, 200),
            (COL_OUT, 200),
            (COL_SIZE, 84),
            (COL_EST, 96),
            (COL_OPS, self.OPS_BASE),
        ):
            self.setColumnWidth(col, width)
        hh.sectionResized.connect(self._on_section_resized)

        self.setMinimumHeight(158)

        # 空队列时表格只剩一条表头，看着像坏了；给一行提示文字
        self.empty = QLabel(empty_text, self.viewport())
        self.empty.setObjectName("emptyHint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 框选状态：在表格空白处按下左键拉出的橡皮筋
        self._rb: QRubberBand | None = None
        self._rb_origin = QPoint()
        self._rb_base: set[int] = set()
        self.itemSelectionChanged.connect(self._sync_row_bg)
        # 整行悬停：QSS 的 :hover 只亮鼠标下那一格，自己跟踪行号统一刷底色
        self._hover_row = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # 拖拽预览的热点：按下时指针在视口里的横坐标
        self._drag_press_x = -1

        # 拖动排序的落点提示线：单独一个薄条压在视口最上层。
        # 不能靠视口自绘 —— 操作列的 cellWidget 是视口的子控件，子控件永远
        # 画在父控件之后，线到了那一列就会被盖掉，只剩两侧各 10px 的碎点。
        self._drop_line = QFrame(self.viewport())
        self._drop_line.setObjectName("dropline")
        self._drop_line.setFixedHeight(2)
        self._drop_line.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drop_line.hide()

    # 各列的伸缩底线：拖到这里就顶住，不许再窄
    MIN_NAME = 150
    MIN_W = {COL_SRC: 140, COL_OUT: 140, COL_SIZE: 84, COL_EST: 96}
    # 操作列：BASE=正常宽度，MIN=指示灯 + 三个按钮都放得下的极限（随按钮尺寸算）
    OPS_BASE = 240
    OPS_MIN = RowActions.min_column_width()

    # 上一轮的视口宽度，用来算窗口自身变宽变窄了多少
    _vw = 0
    # 自己改列宽时置位，避免把「我的调整」当成「用户拖动」再触发一次吸收
    _adjusting = False

    # ------------------------------------------------------------------ 列宽
    def _min_of(self, col: int) -> int:
        if col == COL_NAME:
            return self.MIN_NAME
        if col == COL_OPS:
            return self.OPS_MIN
        return self.MIN_W[col]

    def _total(self) -> int:
        return sum(self.columnWidth(i) for i in range(len(QUEUE_COLUMNS)))

    def _set_width(self, col: int, width: int) -> None:
        if self.columnWidth(col) == width:
            return
        self._adjusting = True
        try:
            self.setColumnWidth(col, width)
        finally:
            self._adjusting = False

    def _on_section_resized(self, index: int, old: int, new: int) -> None:
        """拖分割线：被拖那一列按鼠标走，「操作」列同额反向让出，总宽不变。

        操作列让到 OPS_MIN（指示灯 + 三个按钮刚好放得下）就顶住不再让，此时
        整根分割线也拖不动了——横向滚动条没有意义，按钮一旦被推出视口就
        再也点不到。能拖多远取决于窗口有多宽，窗口越宽可拖的余量越大。
        """
        if self._adjusting or index >= COL_OPS or new == old:
            return
        ops = self.columnWidth(COL_OPS)
        # 先算出「这一列实际能变成多少」：下限顶住，剩下的差额交给操作列反向
        target = max(new, self._min_of(index)) if new < old else new
        if new > old:
            room = max(0, ops - self.OPS_MIN)
            if target - old > room:
                target = old + room          # 操作列到底了：分割线也跟着顶住
            if target != new:
                self._set_width(index, target)
            if target != old:
                self._set_width(COL_OPS, ops - (target - old))
        else:
            # Qt 自己会把列压到 minimumSectionSize，比各列下限还窄，拉回来
            if target != new:
                self._set_width(index, target)
            if target != old:
                self._set_width(COL_OPS, ops + (old - target))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_extra_width()
        self.empty.setGeometry(0, 0, self.viewport().width(), self.viewport().height())

    def _fit_extra_width(self) -> None:
        """窗口变宽/变窄时把列宽总和重新对齐到视口宽度（差多少补多少）。

        拖分割线本身不改变总宽，所以这里按「视口宽 - 列宽总和」算差额是安全
        的：拖完不会有零碎变化，窗口一变就一次性补齐，绝不会越算越偏。
        """
        vw = self.viewport().width()
        if vw <= 0:
            return
        self._vw = vw
        delta = vw - self._total()
        if delta == 0:
            return
        if delta > 0:
            self._grow(delta)
        else:
            self._shrink(-delta)

    def _grow(self, extra: int) -> None:
        """变宽：先把被拖瘦的操作列补回常宽，剩下的全给文件名列。"""
        ops = self.columnWidth(COL_OPS)
        if ops < self.OPS_BASE:
            give = min(extra, self.OPS_BASE - ops)
            self._set_width(COL_OPS, ops + give)
            extra -= give
        if extra > 0:
            self._set_width(COL_NAME, self.columnWidth(COL_NAME) + extra)

    def _shrink(self, need: int) -> None:
        """变窄：按优先级从有余量的列里扣，扣不满就大家一起顶在下限。"""
        for col in (COL_NAME, COL_OPS, COL_SRC, COL_OUT, COL_EST, COL_SIZE):
            if need <= 0:
                return
            spare = self.columnWidth(col) - self._min_of(col)
            take = min(need, max(0, spare))
            if take:
                self._set_width(col, self.columnWidth(col) - take)
                need -= take

    # ------------------------------------------------------------------
    def rebuild(self, paths: list[Path]) -> list[RowCells]:
        """按文件顺序重建整张表，返回每行的单元格引用。

        拖拽排序会打乱行与数据的对应关系，所以统一按「数据是唯一真相」处理：
        结构性变化一律整表重建。
        """
        self.empty.setVisible(not paths)
        if not paths:
            self.empty.setGeometry(
                0, 0, self.viewport().width(), self.viewport().height()
            )
            self.empty.raise_()
        self.blockSignals(True)
        self.setRowCount(0)
        self.setRowCount(len(paths))
        cells: list[RowCells] = []
        for i, path in enumerate(paths):
            items: list[QTableWidgetItem] = []
            for col in range(COL_OPS):
                item = QTableWidgetItem("")
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if col == COL_NAME:
                    item.setText(path.name)
                    item.setData(Qt.UserRole, str(path))
                self.setItem(i, col, item)
                items.append(item)
            actions = RowActions(path)
            actions.hover_changed.connect(
                lambda _p, on, r=i: self._set_hover_row(r if on else -1)
            )
            self.setCellWidget(i, COL_OPS, actions)
            cells.append(RowCells(items, actions))
        self.blockSignals(False)
        self._hover_row = -1
        self._sync_row_bg()
        return cells

    def render(self, cells: RowCells, st: RowState, *, src: str, out: str,
               src_size: str, est: str) -> None:
        items = cells.items
        dim = st.locked

        items[COL_SRC].setText(src)
        items[COL_OUT].setText(out)
        items[COL_SIZE].setText(src_size)
        items[COL_EST].setText(est)

        items[COL_NAME].setForeground(QBrush(QColor(style.DIM if dim else style.TEXT)))
        for col in (COL_SRC, COL_OUT):
            items[col].setForeground(QBrush(QColor(style.DIM if dim else style.MUTED)))
        items[COL_SIZE].setForeground(QBrush(QColor(style.DIM if dim else style.MUTED)))
        items[COL_EST].setForeground(QBrush(QColor(style.DIM if dim else style.TEXT)))

        tip = st.tip or items[COL_NAME].data(Qt.UserRole) or ""
        for col in range(COL_OPS):
            items[col].setToolTip(tip)
        cells.actions.apply(st)

    # ------------------------------------------------------------------ 选择
    def selected_rows(self) -> list[int]:
        """当前选中的行号（升序）。整行选择模式下每行只算一次。"""
        sm = self.selectionModel()
        if sm is None:
            return []
        return sorted({i.row() for i in sm.selectedRows()})

    def _sync_row_bg(self) -> None:
        rows = set(self.selected_rows())
        for r in range(self.rowCount()):
            w = self.cellWidget(r, COL_OPS)
            if isinstance(w, RowActions):
                w.set_selected(r in rows)
                w.set_hover(r == self._hover_row)
        self.viewport().update()

    # ------------------------------------------------------------------ 悬停
    def _set_hover_row(self, row: int) -> None:
        """整行悬停：底色由视口一次画满整行。

        以前是逐格 item.setBackground()，在带 QSS「::item」规则的表格里那层
        brush 根本不参与绘制（样式表接管了格子的绘制），只有操作列的
        cellWidget 自己填了色 —— 于是悬停看过去就是「操作区中间亮了一条」。
        现在统一改成视口自绘 + 操作列保持透明，整行同色，一格不少。
        """
        if row == self._hover_row:
            return
        old, self._hover_row = self._hover_row, row
        for r in {old, row}:
            if not (0 <= r < self.rowCount()):
                continue
            w = self.cellWidget(r, COL_OPS)
            if isinstance(w, RowActions):
                w.set_hover(r == row)
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        # 底色画在下层（否则字被盖住），行分隔线画在上层（否则被选中格的
        # 底色吃掉最后 1px，整行看过去就是断在中间）
        self._paint_row_bg()
        super().paintEvent(event)
        self._paint_row_lines()

    def _rows_on_screen(self) -> list[tuple[int, int, int]]:
        """(行号, 视口内顶边, 行高)，只返回当前可视范围内的行。"""
        out: list[tuple[int, int, int]] = []
        vh = self.viewport().height()
        for r in range(self.rowCount()):
            top = self.rowViewportPosition(r)
            h = self.rowHeight(r)
            if top + h < 0:
                continue
            if top > vh:
                break
            out.append((r, top, h))
        return out

    def _paint_row_bg(self) -> None:
        """整行底色：选中 > 悬停。

        自己画而不是交给 QSS 的 ::item，有两个原因：
          · 「操作」列没有 item，只有 cellWidget，QSS 画不到那一格；
          · cellWidget 被 item padding 内缩了 10px，底色自己填就会和内缩
            边界对不齐，露出两截不同颜色的缝。
        """
        rows = set(self.selected_rows())
        if not rows and self._hover_row < 0:
            return
        painter = QPainter(self.viewport())
        try:
            width = self.viewport().width()
            for r, top, h in self._rows_on_screen():
                if r in rows:
                    bg = style.ROW_SEL
                elif r == self._hover_row:
                    bg = style.ROW_HOVER
                else:
                    continue
                painter.fillRect(0, top, width, h, QColor(bg))
        finally:
            painter.end()

    def _paint_row_lines(self) -> None:
        """行分隔线：贯穿整行（含操作列），不在列边界处断开。"""
        if self.rowCount() == 0:
            return
        painter = QPainter(self.viewport())
        try:
            width = self.viewport().width()
            for _r, top, h in self._rows_on_screen():
                painter.fillRect(0, top + h - 1, width, 1, QColor(style.ROW_LINE))
        finally:
            painter.end()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover_row(-1)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Delete 删除选中行；具体怎么删（跳过正在处理的、刷新计数）归主窗口
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_rows():
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ 拖拽
    def startDrag(self, supportedActions) -> None:  # noqa: N802
        """自己造拖拽预览，别用 Qt 默认那个。

        默认 startDrag 会把选中格子 renderToPixmap —— 在这套样式表 + cellWidget
        的表格上渲出来是个错位的蓝色空框，挂在指针右边一大截。这里改成把被拖的
        那一行截下来做成半透明小预览卡，热点钉在按下位置，稳稳跟在指针下。
        """
        rows = self.selected_rows()
        if not rows:
            return
        row = rows[0]
        indexes = [
            self.model().index(r, c)
            for r in rows
            for c in range(self.columnCount())
        ]
        mime = self.model().mimeData(indexes)
        if mime is None:
            mime = QMimeData()

        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = self._drag_preview(row)
        if not pix.isNull():
            drag.setPixmap(pix)
            # 热点：按下列内位置（横坐标缩放到预览图上），松手前预览一直贴着指针
            press_x = self._drag_press_x if self._drag_press_x >= 0 else pix.width() // 2
            scale = pix.width() / max(1, self.viewport().width())
            drag.setHotSpot(QPoint(int(press_x * scale), pix.height() // 2))
        drag.exec(Qt.MoveAction)

    def _drag_preview(self, row: int) -> QPixmap:
        """把整行截成一张半透明预览图；太宽就等比缩小，免得遮住半屏。"""
        top = self.rowViewportPosition(row)
        rect = QRect(0, top, self.viewport().width(), self.rowHeight(row))
        grab = self.viewport().grab(rect)
        if grab.isNull():
            return grab
        max_w = 320
        if grab.width() > max_w:
            grab = grab.scaledToWidth(max_w, Qt.SmoothTransformation)
        out = QPixmap(grab.size())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setOpacity(0.92)
        p.drawPixmap(0, 0, grab)
        p.end()
        return out

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 在空白区按下：拉橡皮筋框选。Qt 自带的框选会被拖拽重排抢走鼠标，
        # 这里自己接管，行为反而更接近资源管理器。
        self._drag_press_x = int(event.position().x())
        if event.button() == Qt.LeftButton and not self.indexAt(
            event.position().toPoint()
        ).isValid():
            self._rb_origin = event.position().toPoint()
            keep = bool(event.modifiers() & Qt.ControlModifier)
            self._rb_base = set(self.selected_rows()) if keep else set()
            if not keep:
                self.clearSelection()
            self._rb = QRubberBand(QRubberBand.Rectangle, self.viewport())
            self._rb.setGeometry(QRect(self._rb_origin, QSize()))
            self._rb.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._rb is not None:
            rect = QRect(self._rb_origin, event.position().toPoint()).normalized()
            self._rb.setGeometry(rect)
            self._rubber_select(rect)
            event.accept()
            return
        self._set_hover_row(self.rowAt(event.position().toPoint().y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._rb is not None:
            self._rb.hide()
            self._rb.deleteLater()
            self._rb = None
            self._rb_base.clear()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _rubber_select(self, rect: QRect) -> None:
        rows = set(self._rb_base)
        for r in range(self.rowCount()):
            top = self.rowViewportPosition(r)
            if top + self.rowHeight(r) > rect.top() and top < rect.bottom():
                rows.add(r)

        sm = self.selectionModel()
        if sm is None:
            return
        sm.clearSelection()
        if not rows:
            return
        sel = QItemSelection()
        for r in sorted(rows):
            sel.select(
                self.model().index(r, 0), self.model().index(r, self.columnCount() - 1)
            )
        sm.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        if sm.currentIndex().row() not in rows:
            sm.setCurrentIndex(self.model().index(min(rows), 0), QItemSelectionModel.NoUpdate)

    # ------------------------------------------------------------------
    def dragMoveEvent(self, event) -> None:  # noqa: N802
        super().dragMoveEvent(event)
        if event.source() is not self:
            self._hide_drop_line()
            return
        pos = event.position()
        if hasattr(pos, "toPoint"):
            pos = pos.toPoint()
        self._place_drop_line(pos)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._hide_drop_line()
        super().dragLeaveEvent(event)

    def _hide_drop_line(self) -> None:
        if self._drop_line.isVisible():
            self._drop_line.hide()

    def _place_drop_line(self, pos: QPoint) -> None:
        """把蓝色提示线放到「松手后会落在哪一行的哪一侧」。

        指针在上半行 → 线压在这一行的上边缘，下半行 → 压在下一行上边缘，
        和 dropEvent 里 indexAt() 得出的落点行一致。
        """
        if self.rowCount() == 0:
            self._hide_drop_line()
            return
        index = self.indexAt(pos)
        if index.isValid():
            r = index.row()
            top = self.rowViewportPosition(r)
            h = self.rowHeight(r)
            y = top if pos.y() < top + h // 2 else top + h
        else:
            # 落在空白区：接在最后一行之后
            last = self.rowCount() - 1
            y = self.rowViewportPosition(last) + self.rowHeight(last)
        vp = self.viewport()
        # 2px 的线骑在行边界上，上下各占 1px，不遮挡任何一行文字
        y = max(0, min(y - 1, vp.height() - self._drop_line.height()))
        self._drop_line.setGeometry(0, y, vp.width(), self._drop_line.height())
        # cellWidget 也是视口的子控件，必须显式抬到最上层才不会被盖住
        self._drop_line.raise_()
        self._drop_line.show()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._hide_drop_line()
        # 从资源管理器拖文件进来时，交给主窗口统一处理，别被表格吞掉
        if event.source() is not self:
            event.ignore()
            return
        if self.rowCount() < 2:
            event.setDropAction(Qt.IgnoreAction)
            event.accept()
            return
        src = self.currentRow()
        pos = event.position()
        if hasattr(pos, "toPoint"):  # QPointF -> QPoint；老版本 Qt 直接给 QPoint
            pos = pos.toPoint()
        index = self.indexAt(pos)
        dst = index.row() if index.isValid() else self.rowCount() - 1
        if 0 <= src < self.rowCount() and 0 <= dst < self.rowCount() and src != dst:
            self.reordered.emit(src, dst)
        # 一律不交给 Qt 自己移动行：setCellWidget 挂的按钮会被搬走/销毁
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
