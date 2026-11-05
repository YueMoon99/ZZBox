"""可复用控件：卡片、分段选择、文件队列表格。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRubberBand,
    QSizePolicy,
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
    """互斥的胶囊按钮组，可附加一个尾随控件（如自定义输入框）。"""

    changed = Signal(str)

    def __init__(
        self,
        options: list[tuple[str, str]],
        parent: QWidget | None = None,
        stretch: bool = True,
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
            lay.addWidget(btn)
            self._buttons[key] = btn
        if stretch:
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

    def set_selected(self, on: bool) -> None:
        """操作列是 cellWidget，盖在单元格上面，选中色得自己画。"""
        if on == self._selected:
            return
        self._selected = on
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(
            self.rect(), QColor(style.ROW_SEL if self._selected else style.QUEUE_BG)
        )
        # 行与行之间的细线由 item 的 border 提供，这里补上同一根，别断在操作列
        painter.fillRect(0, self.height() - 1, self.width(), 1, QColor(style.ROW_LINE))

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
    """

    reordered = Signal(int, int)

    def __init__(self, parent: QWidget | None = None):
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
        # 不给焦点框：点完行内按钮后整行外面套一圈虚线很难看
        self.setFocusPolicy(Qt.NoFocus)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
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
        self.empty = QLabel("把视频文件拖到这里，或点右上角“+”添加文件", self.viewport())
        self.empty.setObjectName("emptyHint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 框选状态：在表格空白处按下左键拉出的橡皮筋
        self._rb: QRubberBand | None = None
        self._rb_origin = QPoint()
        self._rb_base: set[int] = set()
        self.itemSelectionChanged.connect(self._sync_row_bg)

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
            self.setCellWidget(i, COL_OPS, actions)
            cells.append(RowCells(items, actions))
        self.blockSignals(False)
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

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 在空白区按下：拉橡皮筋框选。Qt 自带的框选会被拖拽重排抢走鼠标，
        # 这里自己接管，行为反而更接近资源管理器。
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
    def dropEvent(self, event) -> None:  # noqa: N802
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
