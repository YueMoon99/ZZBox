"""主窗口：文件队列 + 参数面板 + 进度。"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QSizePolicy,
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.encoder import (
    EncodeSettings,
    build_audio_extract_cmd,
    build_command,
    build_strip_audio_cmd,
    compute_target,
    estimate_output_bytes,
    make_output_path,
    make_output_with_suffix,
)
from app.core.media import MediaInfo, human_size, probe_media
from app.core.probe import EnvInfo, probe_environment
from app.core.runner import EncodeRunner
from app.ui import icons, style
from app.ui.tray import Tray
from app.ui.widgets import Card, ChipGroup, QueueTable, RowCells, RowState

APP_TITLE = "舟舟视频工具箱（ZZBox）"
APP_VERSION = "v0.6.1"

VIDEO_EXT = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".ts", ".m4v",
    ".mpg", ".mpeg", ".rmvb", ".rm", ".m2ts", ".vob", ".3gp",
}  # fmt: skip


class _Emitter(QObject):
    env_ready = Signal(object)
    meta_ready = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        self.setWindowIcon(icons.app_icon())
        # 六列表格比原来的卡片行宽，窗口也要跟着放宽，否则文件名会被挤成省略号
        self.resize(1100, 730)
        # 再窄下去六列就装不下了（会出横向滚动条），这是底线
        self.setMinimumSize(1020, 660)
        self.setAcceptDrops(True)

        self.env: EnvInfo | None = None
        self.files: list[Path] = []
        self.rows: list[RowCells] = []
        self.states: dict[Path, RowState] = {}
        self.media_cache: dict[str, MediaInfo] = {}
        self._index = -1
        self._cursor = 0
        self._ok = 0
        self._fail = 0
        self._stopping = False
        self._mode = "encode"
        # 工具类批量任务（抽取音频 / 删除音轨）的待办队列
        self._tool_jobs: list[dict] = []
        self._tool_cur: dict | None = None
        self._tool_ok = 0
        self._tool_fail = 0
        self._progress_pct = 0
        self.settings = EncodeSettings()
        self._quitting = False
        self._tray_hinted = False
        self.tray: Tray | None = None

        self.emitter = _Emitter()
        self.emitter.env_ready.connect(self._on_env)
        self.emitter.meta_ready.connect(self._on_meta)

        self.runner = EncodeRunner(self)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)

        self._build_ui()
        self._setup_tray()
        self._probe_env()

    # ================================================================ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶栏 ----
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(42)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(8)

        logo = QLabel()
        logo.setFixedSize(18, 18)
        # 与 exe/托盘同一份图标，用户一眼能把窗口和托盘对应起来
        logo.setPixmap(icons.logo_pixmap(18))
        title = QLabel(APP_TITLE)
        title.setObjectName("title")
        ver = QLabel(APP_VERSION)
        ver.setObjectName("version")

        self.badge = QPushButton("环境检测中…")
        self.badge.setObjectName("link")
        self.badge.setCursor(Qt.PointingHandCursor)
        self.badge.clicked.connect(self._show_env)

        hl.addWidget(logo)
        hl.addWidget(title)
        hl.addWidget(ver)
        hl.addStretch(1)
        hl.addWidget(self.badge)
        root.addWidget(header)

        # ---- 主体 ----
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 14)
        bl.setSpacing(10)
        root.addWidget(body, 1)

        # 文件区标题
        fh = QHBoxLayout()
        fh.setSpacing(8)
        self.count_label = QLabel("文件队列")
        self.count_label.setObjectName("sectionTitle")

        self.btn_add = QPushButton("+")
        self.btn_add.setObjectName("addbtn")
        self.btn_add.setFixedSize(26, 24)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setToolTip("添加文件（也可以直接把视频拖进列表）")
        self.btn_add.clicked.connect(self._pick_files)

        self.btn_retry_sel = QPushButton("重提所选")
        self.btn_retry_sel.setObjectName("link")
        self.btn_retry_sel.setCursor(Qt.PointingHandCursor)
        self.btn_retry_sel.setToolTip("把选中的行状态重置为就绪，可再次参与压制")
        self.btn_retry_sel.setEnabled(False)
        self.btn_retry_sel.clicked.connect(self._retry_selected)

        self.btn_del_sel = QPushButton("删除所选")
        self.btn_del_sel.setObjectName("link")
        self.btn_del_sel.setCursor(Qt.PointingHandCursor)
        self.btn_del_sel.setToolTip("从队列中移除选中的行")
        self.btn_del_sel.setEnabled(False)
        self.btn_del_sel.clicked.connect(self._delete_selected)

        btn_clear = QPushButton("清空")
        btn_clear.setObjectName("link")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(self._clear_files)

        fh.addWidget(self.count_label)
        fh.addStretch(1)
        fh.addWidget(self.btn_add)
        fh.addWidget(self.btn_retry_sel)
        fh.addWidget(self.btn_del_sel)
        fh.addWidget(btn_clear)
        bl.addLayout(fh)

        queue = QFrame()
        queue.setObjectName("queue")
        ql = QVBoxLayout(queue)
        ql.setContentsMargins(4, 4, 4, 4)
        ql.setSpacing(0)

        self.table = QueueTable()
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.reordered.connect(self._on_reorder)
        ql.addWidget(self.table)
        bl.addWidget(queue, 1)

        # ---- 参数卡片 ----
        c_enc = self._card_encoder()
        c_quality = self._card_quality()
        c_scale = self._card_scale()
        c_audio = self._card_audio()
        # 2x2 网格要求四张卡片等高，否则高度差会让它们互相错位
        cards = (c_enc, c_quality, c_scale, c_audio)
        same_h = max(c.sizeHint().height() for c in cards)
        for c in cards:
            c.setMinimumHeight(same_h)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        # 两列等宽：不设统一最小宽度时，列宽会按各自内容宽度分，左右就一大一小
        col_w = max(c.minimumSizeHint().width() for c in cards)
        grid.setColumnMinimumWidth(0, col_w)
        grid.setColumnMinimumWidth(1, col_w)
        grid.addWidget(c_enc, 0, 0)
        grid.addWidget(c_quality, 0, 1)
        grid.addWidget(c_scale, 1, 0)
        grid.addWidget(c_audio, 1, 1)
        # 网格装在固定高度的容器里：否则窗口放大时会把多余高度摊给卡片，
        # 卡片内部就空出一大块，而队列反而没长高
        param_wrap = QWidget()
        param_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        param_wrap.setLayout(grid)
        bl.addWidget(param_wrap)

        # ---- 输出目录 ----
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        out_label = QLabel("输出到")
        out_label.setObjectName("hint")
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("留空 = 输出到源文件同目录")
        btn_browse = QPushButton("浏览")
        btn_browse.setObjectName("link")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._pick_out_dir)
        out_row.addWidget(out_label)
        out_row.addWidget(self.out_dir, 1)
        out_row.addWidget(btn_browse)
        bl.addLayout(out_row)

        # ---- 底部进度 ----
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(7)
        stats_row = QHBoxLayout()
        self.current_label = QLabel("就绪")
        self.current_label.setObjectName("hint")
        self.current_label.setMaximumWidth(420)
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("hint")
        self.stats_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        stats_row.addWidget(self.current_label, 1)
        stats_row.addWidget(self.stats_label)
        left.addLayout(stats_row)

        self.progress = QLabel()
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet(
            f"background:{style.TRACK}; border-radius:3px;"
        )
        self.progress_fill = QLabel(self.progress)
        self.progress_fill.setGeometry(0, 0, 0, 6)
        self.progress_fill.setStyleSheet("background:#378add; border-radius:3px;")
        self._progress_pct = 0
        left.addWidget(self.progress)
        fl.addLayout(left, 1)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("ghost")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_start = QPushButton("开始压制")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self._start)
        self.btn_start.setCursor(Qt.PointingHandCursor)

        # 一次处理一批：工具类操作和压制共用同一个执行器，串行跑
        self.btn_extract = QPushButton("抽取音频")
        self.btn_extract.setObjectName("ghost")
        self.btn_extract.setCursor(Qt.PointingHandCursor)
        self.btn_extract.setToolTip(
            "把所选（未选则全部）文件的音轨导出成 .m4a\n输出到上方的输出目录，未设置则与源文件同目录"
        )
        self.btn_extract.clicked.connect(self._extract_audio)
        self.btn_strip = QPushButton("删除音轨")
        self.btn_strip.setObjectName("ghost")
        self.btn_strip.setCursor(Qt.PointingHandCursor)
        self.btn_strip.setToolTip(
            "只剥掉音轨，视频流原样拷贝、不重新压制\n输出为「原名_无音轨」的副本，源文件不动"
        )
        self.btn_strip.clicked.connect(self._strip_audio)

        fl.addWidget(self.btn_extract)
        fl.addWidget(self.btn_strip)
        fl.addSpacing(6)
        fl.addWidget(self.btn_cancel)
        fl.addWidget(self.btn_start)
        bl.addWidget(foot)

    # ------------------------------------------------------------ 托盘
    def _setup_tray(self) -> None:
        if not Tray.available():
            # 系统托盘被禁用（组策略/远程会话偶发）时退回普通关闭，别让用户关不掉窗口
            self.tray = None
            return
        self.tray = Tray(icons.app_icon(), self)
        self.tray.show_requested.connect(self.restore_from_tray)
        self.tray.start_requested.connect(self._start)
        self.tray.cancel_requested.connect(self._cancel)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.show()
        self._sync_tray()

    def _tray_text(self) -> tuple[str, str]:
        total = len(self.files)
        if self.runner.busy() and 0 <= self._index < total:
            name = self.files[self._index].name
            pct = self._progress_pct
            # 工具类任务和压制共用托盘，措辞得跟着换，不然抽音频也显示“压制中”
            verb = "压制中" if self._mode == "encode" else self.TOOL_PROGRESS[self._mode]
            return (
                f"{verb} {pct}% · {self._index + 1}/{total}",
                f"{APP_TITLE} · {pct}% · {name}",
            )
        done = sum(1 for p in self.files if self._state(p).phase == "done")
        if total and done == total:
            return f"全部完成 · {done} 个", f"{APP_TITLE} · 全部完成（{done} 个文件）"
        if total:
            return f"就绪 · {total} 个文件", f"{APP_TITLE} · 就绪（{total} 个文件）"
        return "就绪 · 队列为空", f"{APP_TITLE} · 就绪"

    def _sync_tray(self) -> None:
        """把进度/可点状态同步到托盘：悬停看进度，右键看菜单。"""
        if not self.tray:
            return
        busy = self.runner.busy()
        runnable = any(
            not self._state(p).locked and self._state(p).phase == "ready"
            for p in self.files
        )
        ready_env = bool(self.env and self.env.ready)
        status, tip = self._tray_text()
        self.tray.set_state(
            status,
            tip,
            can_start=ready_env and runnable and not busy,
            can_cancel=busy,
        )

    def restore_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """唯一的真退出路径：托盘右键「退出」。"""
        if self.runner.busy():
            ret = QMessageBox.question(
                self if self.isVisible() else None,
                "正在压制",
                "队列还在压制，退出会中断当前任务。\n确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
            self._stopping = True
            self.runner.cancel()
        self._quitting = True
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        """点右上角 X：只隐藏窗口，进程和压制任务留在后台。"""
        if self._quitting or self.tray is None:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()
        if not self._tray_hinted:
            self._tray_hinted = True
            self.tray.notify(
                "仍在后台运行",
                "窗口已隐藏，压制任务不会中断。\n"
                "双击托盘图标可恢复窗口，右键托盘图标可退出。",
            )


    # ------------------------------------------------------------ cards
    def _card_encoder(self) -> Card:
        card = Card("编码器")
        self.enc_chips = ChipGroup(
            [("h264", "H.264"), ("hevc", "HEVC"), ("av1", "AV1")]
        )
        self.enc_chips.set_value("hevc")
        self.enc_chips.changed.connect(lambda _k: self._refresh_rows())
        card.body.addWidget(self.enc_chips)
        card.footer.setText("同画质体积 H.264 100% · HEVC 约 88% · AV1 约 75%")
        return card

    def _card_quality(self) -> Card:
        card = Card("质量")
        self.mode_chips = ChipGroup([("crf", "CRF"), ("bitrate", "码率")])
        self.mode_chips.changed.connect(self._on_mode_changed)

        crf_row = QHBoxLayout()
        crf_row.setContentsMargins(0, 0, 0, 0)
        crf_row.setSpacing(8)
        self.crf_slider = QSlider(Qt.Horizontal)
        self.crf_slider.setRange(12, 34)
        self.crf_slider.setValue(22)
        self.crf_slider.valueChanged.connect(self._on_crf_changed)
        self.crf_value = QLabel("22")
        self.crf_value.setFixedWidth(20)
        self.crf_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        crf_row.addWidget(self.crf_slider, 1)
        crf_row.addWidget(self.crf_value)
        self._crf_row = QWidget()
        self._crf_row.setLayout(crf_row)

        self.crf_hint = QLabel(self._crf_hint_text(22))
        self.crf_hint.setObjectName("hint")

        br_row = QHBoxLayout()
        br_row.setContentsMargins(0, 0, 0, 0)
        br_row.setSpacing(8)
        self.br_spin = QSpinBox()
        self.br_spin.setRange(300, 100000)
        self.br_spin.setSingleStep(500)
        self.br_spin.setValue(6000)
        self.br_spin.setSuffix(" kbps")
        # QSpinBox 默认横向 Expanding，会和滑块一样被拉开；这里固定成够用的宽度
        self.br_spin.setFixedWidth(132)
        br_row.addWidget(self.br_spin)
        br_row.addStretch(1)
        self._br_row = QWidget()
        self._br_row.setLayout(br_row)

        # 模式胶囊与滑块并排，别上下堆：卡片少一行，四张卡片才能等高而不留空
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        top.addWidget(self.mode_chips)
        top.addWidget(self._crf_row, 1)
        top.addWidget(self._br_row, 1)
        top_wrap = QWidget()
        top_wrap.setLayout(top)
        card.body.addWidget(top_wrap)
        card.body.addWidget(self.crf_hint)
        self._br_row.setVisible(False)
        # 静态说明并入 CRF 胶囊的悬停提示，省掉一行高度：四张卡片等高时，这一行会让
        # 其余三张卡片底部空出一大块
        self.mode_chips.button("crf").setToolTip(
            "数值越小画质越好、体积越大\n已按 CPU CRF 等效校准"
        )
        return card

    def _card_scale(self) -> Card:
        card = Card("缩放")
        self.scale_chips = ChipGroup(
            [("25", "25%"), ("50", "50%"), ("100", "100%"), ("200", "200%")],
            stretch=False,
        )
        self.scale_chips.set_value("100")
        self.scale_chips.changed.connect(self._on_scale_chip)

        self.custom_pct = QLineEdit()
        self.custom_pct.setPlaceholderText("输入百分比或分辨率")
        self.custom_pct.setToolTip("填 37 表示 37%；填 1280x720 表示指定尺寸")
        # 宽度按占位文字算，够用就好，不要占满整行
        fm = self.custom_pct.fontMetrics()
        self.custom_pct.setFixedWidth(
            max(128, min(176, fm.horizontalAdvance(self.custom_pct.placeholderText()) + 22))
        )
        self.custom_pct.textChanged.connect(self._on_custom_scale)

        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(6)
        chips_row.addWidget(self.scale_chips)
        chips_row.addWidget(self.custom_pct)
        chips_row.addStretch(1)
        chips_wrap = QWidget()
        chips_wrap.setLayout(chips_row)
        card.body.addWidget(chips_wrap)

        self.scale_preview = QLabel("输出 原尺寸")
        self.scale_preview.setObjectName("hint")
        card.body.addWidget(self.scale_preview)
        return card

    def _card_audio(self) -> Card:
        card = Card("音轨")
        self.audio_chips = ChipGroup(
            [("aac", "压缩 AAC"), ("copy", "保留原样"), ("none", "删除")]
        )
        self.audio_chips.set_value("aac")
        self.audio_chips.changed.connect(lambda _k: self._refresh_rows())
        card.body.addWidget(self.audio_chips)
        self.audio_info = QLabel("尚未选择文件")
        self.audio_info.setObjectName("hint")
        card.body.addWidget(self.audio_info)
        return card

    # ============================================================ 环境
    def _probe_env(self) -> None:
        def work() -> None:
            self.emitter.env_ready.emit(probe_environment())

        threading.Thread(target=work, daemon=True).start()

    def _on_env(self, info: EnvInfo) -> None:
        self.env = info
        if not info.ffmpeg:
            self._set_badge("未找到 FFmpeg", style.ERR_COLOR, "#3d2222")
            self._sync_tray()
            QMessageBox.critical(self, "缺少组件", info.error or "找不到 ffmpeg.exe")
            return
        if not info.gpu_name:
            self._set_badge("未检测到 NVIDIA 显卡", style.WARN_COLOR, "#3d2f1f")
        else:
            names = [e.label for e in info.encoders if e.available]
            short = info.gpu_name.replace("NVIDIA ", "").replace("GeForce ", "")
            if names:
                self._set_badge(f"{short} · {'/'.join(names)} 就绪", style.OK_COLOR, "#16352c")
            else:
                self._set_badge(f"{short} · 无可用编码器", style.ERR_COLOR, "#3d2222")

        for e in info.encoders:
            self.enc_chips.set_available(e.key, e.available, e.reason)
        if not any(e.available for e in info.encoders):
            self.btn_start.setEnabled(False)
        self._sync_tray()

    def _set_badge(self, text: str, color: str, bg: str) -> None:
        self.badge.setText(text)
        self.badge.setStyleSheet(
            f"QPushButton {{ color:{color}; background:{bg}; border:none;"
            f" border-radius:6px; padding:3px 9px; font-size:11px; }}"
        )

    def _show_env(self) -> None:
        if not self.env:
            return
        info = self.env
        lines = [
            f"FFmpeg：{info.ffmpeg_version or '未知'}",
            f"路径：{info.ffmpeg}",
            f"显卡：{info.gpu_name or '未检测到'}",
            f"驱动：{info.driver or '未知'}"
            + (f"　显存 {info.vram_mb} MB" if info.vram_mb else ""),
            "",
        ]
        for e in info.encoders:
            mark = "可用" if e.available else f"不可用（{e.reason}）"
            lines.append(f"{e.label}（{e.name}）：{mark}")

        dlg = QDialog(self)
        dlg.setWindowTitle("环境自检")
        dlg.resize(520, 300)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        text = QLabel("\n".join(lines))
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.setWordWrap(True)
        text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        lay.addWidget(text, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_copy = QPushButton("复制诊断信息")
        btn_copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText("\n".join(lines))
        )
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)
        dlg.exec()

    # ============================================================ 文件
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()
        ]
        self._add_paths(paths)

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件", "", "视频文件 (*.mp4 *.mkv *.mov *.avi *.flv *.webm *.ts *.m4v *.wmv *.rmvb);;所有文件 (*.*)"
        )
        if files:
            self._add_paths([Path(f) for f in files])

    def _add_paths(self, paths: list[Path]) -> None:
        added: list[Path] = []
        for p in paths:
            if not p.is_file():
                continue
            if p.suffix.lower() not in VIDEO_EXT:
                continue
            if p in self.files:
                continue
            self.files.append(p)
            self.states[p] = RowState()
            added.append(p)

        if not added:
            return
        self._rebuild_list()
        if self.table.currentRow() < 0:
            self.table.setCurrentCell(0, 0)

        def work() -> None:
            for p in added:
                info = probe_media(p)
                self.media_cache[str(p)] = info
                self.emitter.meta_ready.emit(p)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 队列渲染
    def _state(self, path: Path) -> RowState:
        st = self.states.get(path)
        if st is None:
            st = RowState()
            self.states[path] = st
        return st

    def _row_index(self, path: Path) -> int:
        try:
            return self.files.index(path)
        except ValueError:
            return -1

    def _row_texts(
        self, path: Path, s: EncodeSettings | None = None
    ) -> tuple[str, str, str, str]:
        """原始格式 / 导出格式 / 原始大小 / 预计导出大小。

        帧率和时长不会因为压制而改变，导出格式里只有分辨率随缩放变。
        """
        info = self.media_cache.get(str(path))
        if info is None:
            return "读取中…", "—", "—", "—"
        if not info.ok:
            return "—", "—", human_size(info.size), "—"
        settings = s or self._collect()
        w, h = compute_target(info, settings)
        out = f"{w}×{h} · {info.fps_text} · {info.duration_text}" if w and h else "—"
        est = human_size(estimate_output_bytes(info, settings))
        return info.spec_text, out, human_size(info.size), est

    def _paint_row(self, path: Path, s: EncodeSettings | None = None) -> None:
        idx = self._row_index(path)
        if not (0 <= idx < len(self.rows)):
            return
        src, out, ssize, est = self._row_texts(path, s)
        self.table.render(
            self.rows[idx],
            self._state(path),
            src=src,
            out=out,
            src_size=ssize,
            est=est,
        )

    def _repaint_row(self, path: Path) -> None:
        self._paint_row(path)
        self._refresh_count()

    def _refresh_rows(self) -> None:
        """参数一变，全表重算导出格式与预计体积（不重新读媒体信息）。"""
        s = self._collect()
        for path in self.files:
            self._paint_row(path, s)
        self._refresh_scale_preview()

    def _rebuild_list(self) -> None:
        """把 files/states 重新铺成表格。

        拖拽排序会打乱行控件与数据的对应关系，所以统一按「数据是唯一真相、
        界面由数据渲染」处理：任何结构性变化都整表重建，避免索引错位。
        """
        cur = self.table.currentRow()
        self.rows = self.table.rebuild(self.files)
        s = self._collect()
        for i, path in enumerate(self.files):
            src, out, ssize, est = self._row_texts(path, s)
            self.table.render(
                self.rows[i],
                self._state(path),
                src=src,
                out=out,
                src_size=ssize,
                est=est,
            )
            acts = self.rows[i].actions
            acts.lock_clicked.connect(self._on_lock)
            acts.retry_clicked.connect(self._on_retry)
            acts.delete_clicked.connect(self._on_delete)
        if self.files:
            self.table.setCurrentCell(min(max(cur, 0), len(self.files) - 1), 0)
        self._refresh_count()
        self._on_selection_changed()

    def _on_meta(self, path: object) -> None:
        key = Path(str(path))
        info = self.media_cache.get(str(key))
        st = self._state(key)
        if info is None or not info.ok:
            st.phase = "failed"
            st.status = "无法读取"
            st.tip = (info.error if info else "") or "读取失败"
        else:
            st.tip = ""
        self._paint_row(key)
        cur = self._current_media()
        if cur and cur.ok:
            self.audio_info.setText(cur.audio_summary)
        self._refresh_scale_preview()

    def _refresh_count(self) -> None:
        n = len(self.files)
        self._sync_tray()
        if not n:
            self.count_label.setText("文件队列 · 空")
            return
        locked = sum(1 for p in self.files if self._state(p).locked)
        done = sum(1 for p in self.files if self._state(p).phase == "done")
        parts = [f"{n} 个"]
        if locked:
            parts.append(f"锁定 {locked}")
        if done:
            parts.append(f"完成 {done}")
        self.count_label.setText("文件队列 · " + " · ".join(parts))

    def _clear_files(self) -> None:
        if self.runner.busy():
            return
        self.files.clear()
        self.states.clear()
        self.media_cache.clear()
        self._rebuild_list()
        self._refresh_scale_preview()
        self.audio_info.setText("尚未选择文件")

    # ------------------------------------------------------------ 行操作
    def _on_lock(self, path: object) -> None:
        st = self._state(Path(str(path)))
        st.locked = not st.locked
        self._repaint_row(Path(str(path)))

    def _on_retry(self, path: object) -> None:
        key = Path(str(path))
        if self.runner.busy() and 0 <= self._index < len(self.files) and self.files[self._index] == key:
            self.stats_label.setText("正在压制的文件不能重提")
            return
        st = self._state(key)
        st.phase = "ready"
        st.locked = False
        st.status = ""
        st.tip = ""
        self._repaint_row(key)

    def _on_delete(self, path: object) -> None:
        key = Path(str(path))
        if self.runner.busy() and 0 <= self._index < len(self.files) and self.files[self._index] == key:
            self.stats_label.setText("正在压制的文件不能删除")
            return
        idx = self._row_index(key)
        if idx < 0:
            return
        self.files.pop(idx)
        self.states.pop(key, None)
        self.media_cache.pop(str(key), None)
        if idx < self._cursor:
            self._cursor -= 1
        self._rebuild_list()
        self._refresh_scale_preview()

    def _on_reorder(self, src: int, dst: int) -> None:
        if self.runner.busy():
            self.stats_label.setText("压制过程中不能调整顺序")
            return
        if not (0 <= src < len(self.files) and 0 <= dst < len(self.files)) or src == dst:
            return
        QTimer.singleShot(0, lambda: self._apply_reorder(src, dst))

    def _apply_reorder(self, src: int, dst: int) -> None:
        if not (0 <= src < len(self.files) and 0 <= dst < len(self.files)):
            return
        self.files.insert(dst, self.files.pop(src))
        self._cursor = 0
        self._rebuild_list()
        self.table.setCurrentCell(dst, 0)

    def _current_media(self) -> MediaInfo | None:
        idx = self.table.currentRow()
        if idx < 0 or idx >= len(self.files):
            idx = 0
        if 0 <= idx < len(self.files):
            return self.media_cache.get(str(self.files[idx]))
        return None

    def _on_selection_changed(self) -> None:
        self._refresh_scale_preview()
        has_sel = bool(self._selected_rows())
        idle = not self.runner.busy()
        self.btn_retry_sel.setEnabled(has_sel and idle)
        self.btn_del_sel.setEnabled(has_sel and idle)
        m = self._current_media()
        if m and m.ok:
            self.audio_info.setText(m.audio_summary)

    # ------------------------------------------------------------ 多选
    def _selected_rows(self) -> list[int]:
        rows = self.table.selected_rows()
        return [r for r in rows if 0 <= r < len(self.files)]

    def _targets(self) -> list[int]:
        """批量操作的作用范围：有选中就只做选中的，没有就整队。"""
        rows = self._selected_rows()
        return rows or list(range(len(self.files)))

    def _retry_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        running = self._running_index()
        n = 0
        for r in rows:
            if r == running:
                continue
            st = self._state(self.files[r])
            st.phase = "ready"
            st.locked = False
            st.status = ""
            st.tip = ""
            self._paint_row(self.files[r])
            n += 1
        self.stats_label.setText(f"已重提 {n} 个" if n else "正在压制的文件不能重提")
        self._refresh_count()

    def _delete_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        running = self._running_index()
        skip = [r for r in rows if r == running]
        targets = [r for r in rows if r != running]
        for r in sorted(targets, reverse=True):
            path = self.files.pop(r)
            self.states.pop(path, None)
            self.media_cache.pop(str(path), None)
            if r < self._cursor:
                self._cursor -= 1
        if not targets:
            self.stats_label.setText("正在压制的文件不能删除")
            return
        self._rebuild_list()
        self._refresh_scale_preview()
        if skip:
            self.stats_label.setText("正在压制的文件已跳过")

    def _running_index(self) -> int:
        """当前正在压/正在处理的行号；没有就 -1。"""
        if not self.runner.busy():
            return -1
        return self._index if 0 <= self._index < len(self.files) else -1

    # ========================================================== 参数联动
    def _on_mode_changed(self, key: str) -> None:
        is_crf = key == "crf"
        self._crf_row.setVisible(is_crf)
        self._br_row.setVisible(not is_crf)
        if is_crf:
            self.crf_hint.setText(self._crf_hint_text(self.crf_slider.value()))
        else:
            self.crf_hint.setText("目标码率 · 1080p 建议 4000~8000 kbps，数值越大越清晰")
        self._refresh_rows()

    def _on_crf_changed(self, v: int) -> None:
        self.crf_value.setText(str(v))
        self.crf_hint.setText(self._crf_hint_text(v))
        self._refresh_rows()

    @staticmethod
    def _crf_hint_text(v: int) -> str:
        """把 12~34 的数字翻译成人话，省得用户猜该填多少。"""
        if v <= 18:
            return "接近无损 · 体积约为 CRF25 的 2～3 倍"
        if v <= 23:
            return "高画质 · 体积约为 CRF25 的 1.5 倍"
        if v <= 26:
            return "均衡 · 与小丸工具箱 CRF25 体积相当"
        if v <= 30:
            return "小体积 · 约省 20%～35%（画面略有损失）"
        return "极小体积 · 约省 40% 以上（细节会糊）"

    def _on_scale_chip(self, _key: str) -> None:
        if self.custom_pct.text():
            self.custom_pct.blockSignals(True)
            self.custom_pct.clear()
            self.custom_pct.blockSignals(False)
        self._refresh_rows()

    def _on_custom_scale(self, text: str) -> None:
        if text.strip():
            self.scale_chips.clear_selection()
        else:
            self.scale_chips.set_value("100")
        self._refresh_rows()

    def _scale_params(self) -> dict:
        txt = self.custom_pct.text().strip().lower().replace("*", "x").replace("×", "x")
        if txt:
            if "x" in txt:
                a, b = (txt.split("x", 1) + [""])[:2]
                w = int(a) if a.strip().isdigit() else 0
                h = int(b) if b.strip().isdigit() else 0
                if w or h:
                    return {"scale_percent": 0, "custom_w": w, "custom_h": h}
            elif txt.isdigit():
                return {
                    "scale_percent": max(1, min(400, int(txt))),
                    "custom_w": 0,
                    "custom_h": 0,
                }
        key = self.scale_chips.value() or "100"
        return {"scale_percent": int(key), "custom_w": 0, "custom_h": 0}

    def _refresh_scale_preview(self) -> None:
        m = self._current_media()
        if not m or not m.ok:
            self.scale_preview.setText("输出 原尺寸")
            return
        s = EncodeSettings(**self._scale_params())
        w, h = compute_target(m, s)
        if w and h:
            ratio = w / m.width * 100 if m.width else 100
            self.scale_preview.setText(f"输出 {w} × {h}　（源 {m.width}×{m.height}，{ratio:.0f}%）")
        else:
            self.scale_preview.setText("输出 原尺寸")

    def _collect(self) -> EncodeSettings:
        params = self._scale_params()
        return EncodeSettings(
            encoder=self.enc_chips.value() or "hevc",
            mode=self.mode_chips.value() or "crf",
            crf=self.crf_slider.value(),
            bitrate_kbps=self.br_spin.value(),
            audio_mode=self.audio_chips.value() or "aac",
            output_dir=self.out_dir.text().strip(),
            **params,
        )

    def _pick_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.out_dir.setText(d)

    # ========================================================== 执行
    def _set_running(self, running: bool) -> None:
        for w in (
            self.enc_chips,
            self.mode_chips,
            self.scale_chips,
            self.audio_chips,
            self.crf_slider,
            self.br_spin,
            self.out_dir,
        ):
            w.setEnabled(not running)
        self.btn_start.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        # 工具和压制共用执行器，跑起来时互斥
        self.btn_extract.setEnabled(not running)
        self.btn_strip.setEnabled(not running)
        self.btn_add.setEnabled(not running)
        self.btn_retry_sel.setEnabled(not running and bool(self._selected_rows()))
        self.btn_del_sel.setEnabled(not running and bool(self._selected_rows()))
        self._sync_tray()

    def _set_progress(self, pct: int) -> None:
        self._progress_pct = max(0, min(100, pct))
        width = self.progress.width()
        self.progress_fill.setGeometry(
            0, 0, int(width * self._progress_pct / 100), self.progress.height()
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, lambda: self._set_progress(self._progress_pct))

    def _start(self) -> None:
        if not self.files:
            QMessageBox.information(
                self, "没有文件", "先把视频拖进来，或点右上角“+”添加文件。"
            )
            return
        if not self.env or not self.env.ffmpeg:
            return
        pending = [
            p for p in self.files
            if not self._state(p).locked and self._state(p).phase == "ready"
        ]
        if not pending:
            QMessageBox.information(
                self,
                "没有可压制的文件",
                "所有项目都已完成或被锁定。\n"
                "点行尾的「重提」可以把它们重新放回队列。",
            )
            return

        self.settings = self._collect()
        self._index = -1
        self._cursor = 0
        self._ok = 0
        self._fail = 0
        self._stopping = False
        self._mode = "encode"
        self._tool_jobs = []
        self._tool_cur = None
        self._set_running(True)
        self._set_progress(0)
        self._run_next()

    def _next_runnable(self) -> int | None:
        """从游标处找下一个该压的：跳过已锁定、已完成、已失败的。"""
        for i in range(self._cursor, len(self.files)):
            st = self._state(self.files[i])
            if st.locked or st.phase != "ready":
                continue
            return i
        return None

    def _run_next(self) -> None:
        if self._stopping:
            self._finish_all()
            return

        idx = self._next_runnable()
        if idx is None:
            self._finish_all()
            return

        self._index = idx
        self._cursor = idx + 1
        path = self.files[idx]
        st = self._state(path)
        st.phase = "running"
        st.status = "压制中 0%"
        st.tip = ""
        self._repaint_row(path)

        self.current_label.setText(path.name)
        self.current_label.setToolTip(str(path))

        info = self.media_cache.get(str(path)) or probe_media(path)
        self.media_cache[str(path)] = info
        if not info.ok:
            st.phase = "failed"
            st.status = "无法读取"
            st.tip = info.error
            self._repaint_row(path)
            self._fail += 1
            QTimer.singleShot(20, self._run_next)
            return

        out = make_output_path(path, self.settings, self.settings.encoder)
        res = build_command(info, self.settings, self.env.ffmpeg, out)
        self._set_progress(0)
        self.runner.start(res.cmd, info.duration)

    def _on_progress(self, pct: int, speed: float, remaining: str) -> None:
        if self._mode != "encode":
            self._set_progress(pct)
            self.stats_label.setText(f"{self.TOOL_PROGRESS[self._mode]} {pct}%")
            if 0 <= self._index < len(self.files):
                st = self._state(self.files[self._index])
                st.status = f"{self.TOOL_PROGRESS[self._mode]} {pct}%"
                self._repaint_row(self.files[self._index])
            return
        self._set_progress(pct)
        speed_txt = f"{speed:.1f}×" if speed else ""
        self.stats_label.setText(
            "　".join(x for x in (f"{pct}%", speed_txt, remaining) if x)
        )
        if 0 <= self._index < len(self.files):
            st = self._state(self.files[self._index])
            st.status = f"压制中 {pct}%"
            self._repaint_row(self.files[self._index])
        self._sync_tray()

    def _on_finished(self, ok: bool, msg: str) -> None:
        if self._mode != "encode":
            self._on_tool_finished(ok, msg)
            return

        if 0 <= self._index < len(self.files):
            path = self.files[self._index]
            st = self._state(path)
            if self._stopping:
                st.phase = "failed"
                st.status = "已停止"
                st.tip = "手动停止"
                self._fail += 1
            elif ok:
                st.phase = "done"
                st.status = "已完成压制"
                st.tip = ""
                self._ok += 1
            else:
                st.phase = "failed"
                st.status = "失败"
                st.tip = msg
                self._fail += 1
            self._repaint_row(path)

        if self._stopping:
            self._finish_all()
            return

        QTimer.singleShot(30, self._run_next)

    def _finish_all(self) -> None:
        self._set_running(False)
        self._set_progress(100 if self._fail == 0 else self._progress_pct)
        if self._stopping:
            self.stats_label.setText("已停止")
            self.current_label.setText("已手动停止")
        else:
            self.stats_label.setText(f"成功 {self._ok} · 失败 {self._fail}")
            self.current_label.setText("全部完成" if self._fail == 0 else "存在失败任务")
            # 窗口在托盘里的时候，用户只能靠这条通知知道压完了
            if not self.isVisible() and self.tray:
                body = f"成功 {self._ok} 个 · 失败 {self._fail} 个"
                self.tray.notify("压制完成" if self._fail == 0 else "任务结束", body)
        self._refresh_count()

    def _cancel(self) -> None:
        self._stopping = True
        if self.runner.busy():
            self.runner.cancel()
        else:
            self._finish_all()

    # ========================================================== 音频工具
    # 抽取音频 / 删除音轨：都是批量任务，和压制共用同一个执行器串行跑
    TOOL_VERB = {"extract": "抽取音频", "strip": "删除音轨"}
    TOOL_PROGRESS = {"extract": "抽取中", "strip": "去音轨中"}
    TOOL_DONE = {"extract": "已抽取音频", "strip": "已删除音轨"}

    def _extract_audio(self) -> None:
        self._start_tool("extract")

    def _strip_audio(self) -> None:
        self._start_tool("strip")

    def _tool_output_path(
        self, path: Path, s: EncodeSettings, suffix: str, ext: str = ""
    ) -> Path:
        """工具产物落在输出目录（未设置则源目录），重名自动加序号。"""
        base = Path(s.output_dir) if s.output_dir else path.parent
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            base = path.parent
        return make_output_with_suffix(base / path.name, suffix, ext or path.suffix)

    def _start_tool(self, kind: str) -> None:
        if self.runner.busy():
            self.stats_label.setText("当前任务跑完再操作")
            return
        if not self.env or not self.env.ffmpeg:
            QMessageBox.warning(self, "缺少组件", "还没找到 ffmpeg，无法处理音轨。")
            return
        rows = self._targets()
        if not rows:
            QMessageBox.information(
                self, "队列是空的", "先把视频拖进来，或点右上角“+”添加文件。"
            )
            return

        s = self._collect()
        jobs: list[dict] = []
        no_audio: list[str] = []
        for r in rows:
            path = self.files[r]
            info = self.media_cache.get(str(path)) or probe_media(path)
            self.media_cache[str(path)] = info
            if not info.ok or not info.audio:
                # 没有音轨（或读不出来）的项直接跳过，不打断整批
                no_audio.append(path.name)
                continue
            if kind == "extract":
                out = self._tool_output_path(path, s, "", "m4a")
                cmd = build_audio_extract_cmd(info, self.env.ffmpeg, "m4a", out)
            else:
                out = self._tool_output_path(path, s, "_无音轨")
                cmd = build_strip_audio_cmd(info, self.env.ffmpeg, out).cmd
            jobs.append(
                {"path": path, "cmd": cmd, "duration": info.duration, "output": out}
            )

        if not jobs:
            QMessageBox.warning(
                self,
                "没有可处理的项目",
                "所选文件里没有音频轨道。\n"
                "（删除音轨需要有音轨才谈得上删除；抽取音频同理）",
            )
            return

        verb = self.TOOL_VERB[kind]
        if len(jobs) > 1:
            where = s.output_dir or "各源文件所在目录"
            extra = f"\n将跳过 {len(no_audio)} 个无音轨文件。" if no_audio else ""
            ret = QMessageBox.question(
                self,
                verb,
                f"将对 {len(jobs)} 个文件{verb}。\n输出到：{where}{extra}\n\n继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ret != QMessageBox.Yes:
                return

        self._mode = kind
        self._tool_jobs = jobs
        self._tool_ok = 0
        self._tool_fail = 0
        self._index = -1
        self._cursor = 0
        self._stopping = False
        self._set_running(True)
        self._set_progress(0)
        if no_audio:
            self.stats_label.setText(f"跳过 {len(no_audio)} 个无音轨文件")
        self._run_tool_next()

    def _run_tool_next(self) -> None:
        if self._stopping or not self._tool_jobs:
            self._finish_tool()
            return
        job = self._tool_jobs.pop(0)
        self._tool_cur = job
        path: Path = job["path"]
        idx = self._row_index(path)
        self._index = idx if idx >= 0 else -1
        st = self._state(path)
        st.phase = "running"
        st.status = f"{self.TOOL_PROGRESS[self._mode]} 0%"
        st.tip = ""
        if idx >= 0:
            self._repaint_row(path)
        self.current_label.setText(path.name)
        self.current_label.setToolTip(str(path))
        self.runner.start(job["cmd"], job["duration"])

    def _on_tool_finished(self, ok: bool, msg: str) -> None:
        job = self._tool_cur
        self._tool_cur = None
        if job:
            path: Path = job["path"]
            st = self._state(path)
            if self._stopping:
                st.phase = "failed"
                st.status = "已停止"
                st.tip = "手动停止"
                self._tool_fail += 1
            elif ok:
                st.phase = "done"
                st.status = self.TOOL_DONE[self._mode]
                st.tip = f"输出：{job['output']}"
                self._tool_ok += 1
            else:
                st.phase = "failed"
                st.status = "失败"
                st.tip = msg
                self._tool_fail += 1
            self._repaint_row(path)

        if self._stopping:
            self._finish_tool()
            return
        QTimer.singleShot(30, self._run_tool_next)

    def _finish_tool(self) -> None:
        verb = self.TOOL_DONE[self._mode]
        self._mode = "encode"
        self._set_running(False)
        if self._stopping:
            self.stats_label.setText("已停止")
            self.current_label.setText("已手动停止")
        else:
            self._set_progress(100)
            self.stats_label.setText(f"{verb} {self._tool_ok} · 失败 {self._tool_fail}")
            self.current_label.setText(
                "处理完成" if not self._tool_fail else "存在失败任务"
            )
            if not self.isVisible() and self.tray:
                self.tray.notify(verb, f"成功 {self._tool_ok} · 失败 {self._tool_fail}")
        self._refresh_count()
