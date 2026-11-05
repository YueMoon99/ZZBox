"""系统托盘：后台驻留入口。

关闭主窗口只隐藏界面，进程和压制任务继续跑；真正退出只走托盘右键菜单。
托盘图标同时承担状态显示——鼠标悬停能看到当前进度，右键菜单第一行也能看到。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

APP_TITLE = "舟舟视频工具箱（ZZBox）"


class Tray(QObject):
    """托盘图标 + 右键菜单。只负责“发信号”，业务逻辑留在主窗口。"""

    show_requested = Signal()
    start_requested = Signal()
    cancel_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon = QSystemTrayIcon(icon, self)
        self._icon.setToolTip(APP_TITLE)
        self._icon.activated.connect(self._on_activated)

        menu = QMenu()
        # 第一行是状态（不可点），省得用户为了看进度把窗口叫回来
        self._status = menu.addAction("就绪")
        self._status.setEnabled(False)
        menu.addSeparator()

        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self.show_requested)
        self._act_start = menu.addAction("开始压制")
        self._act_start.triggered.connect(self.start_requested)
        self._act_cancel = menu.addAction("取消当前任务")
        self._act_cancel.triggered.connect(self.cancel_requested)
        menu.addSeparator()

        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_requested)

        self._menu = menu  # 必须留引用，否则被回收后右键点不出菜单
        self._icon.setContextMenu(menu)

    # ------------------------------------------------------------ 生命周期
    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    def notify(self, title: str, body: str, msec: int = 5000) -> None:
        if not self._icon.isVisible() or not QSystemTrayIcon.supportsMessages():
            return
        self._icon.showMessage(title, body, self._icon.icon(), msec)

    # ------------------------------------------------------------ 状态
    def set_state(
        self,
        status: str,
        tooltip: str,
        *,
        can_start: bool,
        can_cancel: bool,
    ) -> None:
        self._status.setText(status)
        # Windows 托盘提示最多 128 个字符，超了会被截断，这里先自己收一下
        self._icon.setToolTip(tooltip[:120])
        self._act_start.setEnabled(can_start)
        self._act_cancel.setEnabled(can_cancel)

    # ------------------------------------------------------------ 交互
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # 左键单击和双击都当作“把窗口叫回来”，符合 Windows 上的习惯
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
            QSystemTrayIcon.MiddleClick,
        ):
            self.show_requested.emit()
