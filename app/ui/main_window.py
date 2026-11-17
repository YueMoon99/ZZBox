"""主窗口：视频 / 图片 / PDF 三个工作台，各自一份队列 + 参数面板 + 共用进度条。"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.ai import (
    DEFAULT_MODEL,
    MODELS,
    AiSettings,
    ai_dir,
    build_plan,
    cleanup,
    detect_engines,
    estimate_seconds,
    estimate_temp_bytes,
    free_space_mb,
    infer_scale,
    infer_pixels,
    output_size,
    plan_warnings,
    recommend_scale,
    sweep_stale,
    vram_profile,
)
# 压缩页与 AI 页各有一套体积模型，同名不同义，别名区分，免得看串
from app.core.ai import estimate_output_bytes as estimate_ai_bytes
from app.core.ai_runner import AiRunner
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
from app.core.image import (
    IMAGE_EXT,
    ImageInfo,
    ImageSettings,
    build_ai_steps,
    build_compress_steps,
    plan_summary,
    probe_image,
    warnings_for,
)
from app.core.image_runner import ImageRunner
from app.core.media import MediaInfo, probe_media
from app.core.pdf import (
    PageRef,
    PdfError,
    PdfInfo,
    export_images,
    export_pdf,
    page_stem,
    probe_pdf,
    safe_stem,
    thumb_bytes,
    unique_path,
)
from app.core.pdf_runner import PdfRunner
from app.core.pdf_images import PageStat, estimate_pdf, merge_pdf, stage_page
from app.core.probe import EnvInfo, probe_environment
from app.core.runner import EncodeRunner
from app.ui import icons, style
from app.ui.page_grid import PageGrid
from app.ui.tray import Tray
from app.ui.widgets import (
    ChipGroup,
    OptionPanel,
    PropertyTabs,
    QueueTable,
    RowCells,
    RowState,
)

APP_TITLE = "舟舟工具箱（ZZBox）"
APP_VERSION = "v0.7.0"

VIDEO_EXT = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".ts", ".m4v",
    ".mpg", ".mpeg", ".rmvb", ".rm", ".m2ts", ".vob", ".3gp",
}  # fmt: skip


def _dur_text(secs: float) -> str:
    """把预估秒数说成人话。

    AI 增强动辄几小时，「约 207 分钟」读起来没概念，超过一个半小时就换成小时。
    """
    if secs < 90:
        return f"约 {max(1, round(secs))} 秒"
    if secs < 5400:
        return f"约 {secs / 60:.0f} 分钟"
    return f"约 {secs / 3600:.1f} 小时"


@dataclass
class PdfItem:
    """PDF 队列里的一格。

    队列是「页面列表」而不是「文件列表」：一份 80 页的扫描件进来就是 80 格。
    uid 是唯一真相 —— 拖动排序后界面会重建 item，只能靠它把顺序找回来。
    """

    uid: str
    ref: PageRef
    label: str = ""
    w: float = 0.0
    h: float = 0.0
    thumbbed: bool = False
    # 缩略图原始 PNG。重建列表时直接拿它重设图标，不用再渲染一遍 ——
    # 200 页的队列删一格就重渲染全部，会卡好几秒
    thumb_png: bytes = b""
    origin: str = ""        # 来源文件名，导出分组时用


def _fmt_bytes(n: float) -> str:
    """和 core 里的口径一致，但这里要给"图片 1.6 MB → 392 KB"这种一行字用，
    小数值留一位就够了。"""
    for unit, base in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= base:
            v = n / base
            return f"{v:.0f} {unit}" if v >= 10 else f"{v:.1f} {unit}"
    return f"{int(n)} B"


class _Emitter(QObject):
    env_ready = Signal(object)
    meta_ready = Signal(object)
    img_meta_ready = Signal(object)
    pdf_thumb_ready = Signal(str, bytes)
    # (generation, 源文件, 页号, PageStat)。带 generation 是为了丢掉过期的
    # 估算结果 —— 用户拖一下质量条，上一轮的几十页结果会陆续飘回来，
    # 不认代次的话界面上会出现"旧质量算出来的数字"混在新数字里
    pdf_stat_ready = Signal(int, str, int, object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        self.setWindowIcon(icons.app_icon())
        # 六列表格比原来的卡片行宽，窗口也要跟着放宽，否则文件名会被挤成省略号
        self.resize(1120, 760)
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
        self.ai_settings = AiSettings()
        # AI 引擎与显存档位：环境探测完成前先留空，UI 上显示「检测中」
        self.engines: dict = {}
        self._ai_root: Path | None = None
        self._ai_jobs: list[dict] = []
        self._ai_cur: dict | None = None
        self._ai_ok = 0
        self._ai_fail = 0
        self._tab = 0
        # 0 = 视频工作台, 1 = 图片工作台, 2 = PDF 工作台
        self._page = 0
        self.img_tab = 0
        # 图片队列独立于视频队列：两边文件类型不同、参数不同、状态也不同
        self.img_files: list[Path] = []
        self.img_rows: list[RowCells] = []
        self.img_states: dict[Path, RowState] = {}
        self.img_cache: dict[str, ImageInfo] = {}
        self._img_batch: list[Path] = []
        self._img_index = 0
        self._img_ok = 0
        self._img_fail = 0
        self._img_t0 = 0.0
        # PDF 队列是页面级的：一份 N 页的 PDF 展开成 N 格，排序删除都按页来
        self.pdf_items: list[PdfItem] = []
        self.pdf_by_uid: dict[str, PdfItem] = {}
        self.pdf_cache: dict[str, PdfInfo] = {}
        self._pdf_seq = 0
        self._pdf_pool: ThreadPoolExecutor | None = None
        self._pdf_thumb_jobs = 0
        self._pdf_thumb_done = 0
        self._pdf_kind = ""
        self._pdf_t0 = 0.0
        self._pdf_result = ""
        # 压缩区状态：off / pick / all / part（见 _pdf_zip_panel 的注释）
        self._pdf_zip_mode = "off"
        self._pdf_stats: dict[tuple[str, int], PageStat] = {}
        # (源文件, 页号, 质量) → 统计。来回点选同一页时不用重新解码
        self._pdf_stat_cache: dict[tuple[str, int, int], PageStat] = {}
        self._pdf_est_key: tuple | None = None
        self._pdf_est_gen = 0
        self._pdf_est_cancel: threading.Event | None = None
        self._pdf_est_pool: ThreadPoolExecutor | None = None
        # 压缩部分：压好的单页 PDF 先落盘，(源文件, 页号, 旋转角) → 路径
        self._pdf_staged: dict[tuple[str, int, int], str] = {}
        self._pdf_stage_dir: Path | None = None
        self._pdf_zip_results: list = []
        self._quitting = False
        self._tray_hinted = False
        self.tray: Tray | None = None

        self.emitter = _Emitter()
        self.emitter.env_ready.connect(self._on_env)
        self.emitter.meta_ready.connect(self._on_meta)
        self.emitter.img_meta_ready.connect(self._on_img_meta)
        self.emitter.pdf_thumb_ready.connect(self._on_pdf_thumb)
        self.emitter.pdf_stat_ready.connect(self._on_pdf_stat)

        self.runner = EncodeRunner(self)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)

        self.ai_runner = AiRunner(self)
        self.ai_runner.progress.connect(self._on_ai_progress)
        self.ai_runner.stage.connect(self._on_ai_stage)
        self.ai_runner.finished.connect(self._on_ai_finished)

        self.img_runner = ImageRunner(self)
        self.img_runner.progress.connect(self._on_img_progress)
        self.img_runner.finished.connect(self._on_img_finished)

        self.pdf_runner = PdfRunner(self)
        self.pdf_runner.progress.connect(self._on_pdf_progress)
        self.pdf_runner.finished.connect(self._on_pdf_finished)

        self._build_ui()
        self._set_mode(0)
        self._setup_tray()
        self._probe_env()
        # 上次进程被强杀（关窗口时正好卡在引擎里、任务管理器结束进程、崩溃）会留下
        # 整份帧序列，用户下次打开时自动扫掉，别让几十 GB 悄悄占着盘
        QTimer.singleShot(1500, self._sweep_orphans)

    def _sweep_orphans(self) -> None:
        """清理系统临时目录里上次遗留的帧序列。

        只删 2 小时以前的：同一个程序多开时，别的实例可能正在用。
        """
        try:
            n = sweep_stale(Path(tempfile.gettempdir()))
        except OSError:
            return
        if n:
            self.stats_label.setText(f"已清理 {n} 个上次遗留的临时目录")

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

        # ---- 视频 / 图片 / PDF 三个工作台 ----
        bl.addWidget(self._mode_bar())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._video_page())
        self.pages.addWidget(self._image_page())
        self.pages.addWidget(self._pdf_page())
        bl.addWidget(self.pages, 1)

        # ---- 输出目录（两个工作台共用，切模式不丢） ----
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

    # ------------------------------------------------------------ 模式切换
    def _mode_bar(self) -> QWidget:
        """视频 / 图片 / PDF 三个工作台的切换条。

        放在队列上方而不是塞进页签：这不是「同一个队列的两种参数」，而是
        三套完全独立的文件列表（视频进视频队列，图片进图片队列，PDF 按页
        展开进 PDF 队列）。做成大分段，用户一眼能看出自己在哪个工作台。
        """
        bar = QFrame()
        bar.setObjectName("modebar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 5, 12, 5)
        lay.setSpacing(6)

        group = QButtonGroup(self)
        group.setExclusive(True)
        self.btn_mode_video = QPushButton("视频处理")
        self.btn_mode_image = QPushButton("图片处理")
        self.btn_mode_pdf = QPushButton("PDF 处理")
        for i, btn in enumerate(
            (self.btn_mode_video, self.btn_mode_image, self.btn_mode_pdf)
        ):
            btn.setObjectName("mode")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(28)
            group.addButton(btn)
            btn.clicked.connect(lambda _=False, k=i: self._set_mode(k))
            lay.addWidget(btn)
        self.btn_mode_video.setChecked(True)
        self.btn_mode_video.setToolTip("压缩 · 转码 · AI 超分补帧 · 音轨处理")
        self.btn_mode_image.setToolTip("批量压缩 · 格式转换 · AI 超分放大")
        self.btn_mode_pdf.setToolTip("多图合成 · 页面重排 · 拆分导出 · 压缩")

        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("hint")
        lay.addSpacing(8)
        lay.addWidget(self.mode_hint)
        lay.addStretch(1)
        return bar

    _MODE_HINTS = (
        "压缩 · 转码 · AI 超分补帧 · 音轨处理",
        "批量压缩 · 格式转换 · AI 超分放大",
        "拖入 PDF 或图片，按页排序后导出",
    )

    def _set_mode(self, mode: int) -> None:
        """切工作台。三个队列各自记状态，互不影响。"""
        self._page = mode
        self.btn_mode_video.setChecked(mode == 0)
        self.btn_mode_image.setChecked(mode == 1)
        self.btn_mode_pdf.setChecked(mode == 2)
        self.pages.setCurrentIndex(mode)
        self.mode_hint.setText(self._MODE_HINTS[mode] if mode < 3 else "")
        self.btn_extract.setVisible(mode == 0)
        self.btn_strip.setVisible(mode == 0)
        self._update_start_text()
        self._refresh_count()
        if mode == 2:
            self._pdf_refresh()
        self._sync_tray()

    # ------------------------------------------------------------ 队列标题行
    def _queue_head(
        self,
        title: str,
        add_tip: str,
        add_cb,
        retry_cb,
        del_cb,
        clear_cb,
    ) -> tuple[QHBoxLayout, QLabel, QPushButton, QPushButton, QPushButton]:
        """队列标题行：标题 · 添加 / 重提 / 删除 / 清空。

        视频和图片各一套 —— 两边队列独立，按钮不能共用一个回调，否则点
        「清空」会把另一个工作台的文件也清掉。
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")

        btn_add = QPushButton("+")
        btn_add.setObjectName("addbtn")
        btn_add.setFixedSize(26, 24)
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setToolTip(add_tip)
        btn_add.clicked.connect(add_cb)

        btn_retry = QPushButton("重提所选")
        btn_retry.setObjectName("link")
        btn_retry.setCursor(Qt.PointingHandCursor)
        btn_retry.setToolTip("把选中的行状态重置为就绪，可再次参与处理")
        btn_retry.setEnabled(False)
        btn_retry.clicked.connect(retry_cb)

        btn_del = QPushButton("删除所选")
        btn_del.setObjectName("link")
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setToolTip("从队列中移除选中的行")
        btn_del.setEnabled(False)
        btn_del.clicked.connect(del_cb)

        btn_clear = QPushButton("清空")
        btn_clear.setObjectName("link")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(clear_cb)

        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(btn_add)
        row.addWidget(btn_retry)
        row.addWidget(btn_del)
        row.addWidget(btn_clear)
        return row, label, btn_add, btn_retry, btn_del

    def _queue_frame(self, table: QueueTable) -> QFrame:
        frame = QFrame()
        frame.setObjectName("queue")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        lay.addWidget(table)
        return frame

    # ------------------------------------------------------------ 视频工作台
    def _video_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        (
            fh,
            self.count_label,
            self.btn_add,
            self.btn_retry_sel,
            self.btn_del_sel,
        ) = self._queue_head(
            "文件队列",
            "添加视频文件（也可以直接把视频拖进列表）",
            self._pick_files,
            self._retry_selected,
            self._delete_selected,
            self._clear_files,
        )
        lay.addLayout(fh)

        self.table = QueueTable()
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.reordered.connect(self._on_reorder)
        lay.addWidget(self._queue_frame(self.table), 1)

        # ---- 参数页：视频压缩 / AI 增强 ----
        self.tabs = PropertyTabs()
        self.tabs.add_page(self._page_compress(), "视频压缩", "缩放、编码与音轨处理")
        self.tabs.add_page(self._page_ai(), "AI 增强", "超分辨率重建与 AI 补帧")
        self.tabs.finish_tabs()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        lay.addWidget(self.tabs)
        return page

    # ------------------------------------------------------------ 图片工作台
    def _image_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        (
            fh,
            self.img_count,
            self.img_btn_add,
            self.img_btn_retry,
            self.img_btn_del,
        ) = self._queue_head(
            "图片队列",
            "添加图片（也可以直接把图片拖进列表）",
            self._pick_images,
            self._img_retry_selected,
            self._img_delete_selected,
            self._img_clear,
        )
        lay.addLayout(fh)

        self.img_table = QueueTable(
            empty_text="把图片拖到这里，或点右上角“+”添加图片"
        )
        self.img_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.img_table.itemSelectionChanged.connect(self._img_on_selection)
        self.img_table.reordered.connect(self._img_on_reorder)
        lay.addWidget(self._queue_frame(self.img_table), 1)

        self.img_tabs = PropertyTabs()
        self.img_tabs.add_page(self._page_img_compress(), "图片压缩", "格式、质量与长边缩放")
        self.img_tabs.add_page(self._page_img_ai(), "AI 超分", "Real-ESRGAN 放大与锐化")
        self.img_tabs.finish_tabs()
        self.img_tabs.currentChanged.connect(self._on_img_tab_changed)
        lay.addWidget(self.img_tabs)
        return page

    # ------------------------------------------------------------ PDF 工作台
    def _pdf_page(self) -> QWidget:
        """PDF 工作台：上面是页面格墙，下面一条操作栏。

        和另外两个工作台最大的差别在队列 —— 这里一格是一「页」而不是
        一「个文件」。一份 80 页的扫描件拖进来就是 80 格，用户对着页面
        排序、删页、旋转，导出的就按这个顺序落盘。

        下方只有「旋转选中」「导出选中」两个按钮。压缩功能区已整块移除，
        这里不再有任何参数项 —— 页面格墙因此能多占一行，最小窗口下也不
        挤。
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # ---- 队列标题行
        head = QHBoxLayout()
        head.setSpacing(8)
        self.pdf_count = QLabel("PDF 队列 · 空")
        self.pdf_count.setObjectName("sectionTitle")

        self.pdf_btn_add = QPushButton("+")
        self.pdf_btn_add.setObjectName("addbtn")
        self.pdf_btn_add.setFixedSize(26, 24)
        self.pdf_btn_add.setCursor(Qt.PointingHandCursor)
        self.pdf_btn_add.setToolTip("添加 PDF 或图片（也可以直接拖进列表）")
        self.pdf_btn_add.clicked.connect(self._pdf_pick)

        self.pdf_btn_all = QPushButton("全选")
        self.pdf_btn_all.setObjectName("link")
        self.pdf_btn_all.setCursor(Qt.PointingHandCursor)
        self.pdf_btn_all.clicked.connect(self._pdf_select_all)

        self.pdf_btn_del = QPushButton("删除所选")
        self.pdf_btn_del.setObjectName("link")
        self.pdf_btn_del.setCursor(Qt.PointingHandCursor)
        self.pdf_btn_del.setToolTip("把选中的页面从队列里移除（不动源文件）")
        self.pdf_btn_del.setEnabled(False)
        self.pdf_btn_del.clicked.connect(self._pdf_delete_selected)

        self.pdf_btn_clear = QPushButton("清空")
        self.pdf_btn_clear.setObjectName("link")
        self.pdf_btn_clear.setCursor(Qt.PointingHandCursor)
        self.pdf_btn_clear.clicked.connect(self._pdf_clear)

        head.addWidget(self.pdf_count)
        head.addStretch(1)
        head.addWidget(self.pdf_btn_add)
        head.addWidget(self.pdf_btn_all)
        head.addWidget(self.pdf_btn_del)
        head.addWidget(self.pdf_btn_clear)
        lay.addLayout(head)

        # ---- 页面格墙
        self.pdf_grid = PageGrid(
            empty_text="把 PDF 或图片拖到这里\n多页 PDF 会自动展开成多个页面"
        )
        self.pdf_grid.setToolTip("单击 / Shift 连选 / Ctrl 加选 · 拖动格子排序 · Ctrl+滚轮缩放")
        self.pdf_grid.order_changed.connect(self._pdf_on_reorder)
        self.pdf_grid.itemSelectionChanged.connect(self._pdf_on_selection)
        frame = QFrame()
        frame.setObjectName("queue")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(4, 4, 4, 4)
        fl.setSpacing(0)
        fl.addWidget(self.pdf_grid)
        lay.addWidget(frame, 1)

        # ---- 下方工作区：左边页面操作，右边压缩。
        # 压缩区默认不启用 —— 它的口径和别的功能不一样（会重编码图片、
        # 改变导出结果），不该让人一进来就撞上一堆参数
        work = QHBoxLayout()
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(10)
        work.addWidget(self._pdf_ops_panel())
        work.addWidget(self._pdf_zip_panel(), 1)
        lay.addLayout(work)
        return page

    def _pdf_ops_panel(self) -> QWidget:
        """左侧页面操作区：只放"对选中的页面做点什么"的按钮。"""
        panel = QFrame()
        panel.setObjectName("optpanel")
        panel.setFixedWidth(150)
        # 垂直方向跟着右边那张卡一起长高，两张卡高低不一会像没对齐
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.pdf_ops_panel = panel

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        self.pdf_btn_rotate = QPushButton("旋转选中")
        self.pdf_btn_rotate.setObjectName("ghost")
        self.pdf_btn_rotate.setCursor(Qt.PointingHandCursor)
        self.pdf_btn_rotate.setToolTip("选中的页面顺时针转 90°（再点继续叠加）")
        self.pdf_btn_rotate.setEnabled(False)
        self.pdf_btn_rotate.clicked.connect(self._pdf_rotate)

        self.pdf_btn_extract = QPushButton("导出选中")
        self.pdf_btn_extract.setObjectName("ghost")
        self.pdf_btn_extract.setCursor(Qt.PointingHandCursor)
        self.pdf_btn_extract.setToolTip(
            "把选中的页面导出成 PDF 或图片\n"
            "导出 PDF 时不重新渲染，文字层、链接、表单原样保留"
        )
        self.pdf_btn_extract.setEnabled(False)
        self.pdf_btn_extract.clicked.connect(self._pdf_extract)

        # 上下各留一段弹簧：卡片会被右侧拉高，按钮留在中间比顶在头上好看
        lay.addStretch(1)
        lay.addWidget(self.pdf_btn_rotate)
        lay.addWidget(self.pdf_btn_extract)
        lay.addStretch(1)
        return panel

    # ------------------------------------------------------------ PDF 压缩区
    def _pdf_zip_panel(self) -> QWidget:
        """压缩区。四个状态，靠显隐切换，不重建控件：

          off  未启用     → 【启用压缩功能】+ "压缩功能未启用"
          pick 选方式     → 【压缩部分】【压缩全部】
          all  压缩全部   → 质量条 + 提示；格子显示每页预估，导出时才压
          part 压缩部分   → 质量条 + 【压缩选中】；只算选中页，压完回 off

        为什么不做成一进来就摆满参数：这一版压缩会重编码图片、改变导出
        结果，属于"得先想清楚再开"的功能。默认关着，想用的人点一下。
        """
        panel = QFrame()
        panel.setObjectName("optpanel")
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.pdf_zip_panel = panel

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.pdf_zip_enable = QPushButton("启用压缩功能")
        self.pdf_zip_enable.setObjectName("ghost")
        self.pdf_zip_enable.setCursor(Qt.PointingHandCursor)
        self.pdf_zip_enable.setToolTip(
            "只重编码页面里的图片，页面尺寸、文字层、链接都不动"
        )
        self.pdf_zip_enable.clicked.connect(lambda: self._pdf_zip_set("pick"))

        self.pdf_zip_all = QPushButton("压缩全部")
        self.pdf_zip_all.setObjectName("ghost")
        self.pdf_zip_all.setCursor(Qt.PointingHandCursor)
        self.pdf_zip_all.setToolTip("按质量压缩所有页面的图片，导出时才真正执行")
        self.pdf_zip_all.clicked.connect(lambda: self._pdf_zip_set("all"))

        self.pdf_zip_part = QPushButton("压缩部分")
        self.pdf_zip_part.setObjectName("ghost")
        self.pdf_zip_part.setCursor(Qt.PointingHandCursor)
        self.pdf_zip_part.setToolTip("只压选中的页面，结果先存到临时文件")
        self.pdf_zip_part.clicked.connect(lambda: self._pdf_zip_set("part"))

        self.pdf_zip_run = QPushButton("压缩选中")
        self.pdf_zip_run.setObjectName("ghost")
        self.pdf_zip_run.setCursor(Qt.PointingHandCursor)
        self.pdf_zip_run.setToolTip("立刻压缩选中的页面，结果暂存，导出时直接用")
        self.pdf_zip_run.clicked.connect(self._pdf_zip_compress_selected)

        self.pdf_zip_cancel = QPushButton("← 退出压缩")
        self.pdf_zip_cancel.setObjectName("link")
        self.pdf_zip_cancel.setCursor(Qt.PointingHandCursor)
        self.pdf_zip_cancel.setToolTip("关掉压缩，回到原始导出（不压图片）")
        self.pdf_zip_cancel.clicked.connect(lambda: self._pdf_zip_set("off"))

        for btn in (
            self.pdf_zip_enable,
            self.pdf_zip_all,
            self.pdf_zip_part,
            self.pdf_zip_run,
        ):
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)

        # 质量行：只在 all / part 出现。格式、长边这些选项这一版不要了 ——
        # 图片像素尺寸和颜色空间都得原样保留，能调的只剩 JPEG 质量
        self.pdf_zip_qwrap = QWidget()
        qrow = QHBoxLayout(self.pdf_zip_qwrap)
        qrow.setContentsMargins(0, 0, 0, 0)
        qrow.setSpacing(8)
        qlab = QLabel("质量")
        qlab.setObjectName("optlabel")
        qlab.setFixedWidth(30)
        self.pdf_zip_quality = QSlider(Qt.Horizontal)
        self.pdf_zip_quality.setRange(30, 100)
        self.pdf_zip_quality.setValue(78)
        self.pdf_zip_quality.setToolTip("越低体积越小，画面越糊。78 是扫描件的甜点")
        self.pdf_zip_quality.valueChanged.connect(self._pdf_zip_on_quality)
        self.pdf_zip_qv = QLabel("78")
        self.pdf_zip_qv.setFixedWidth(26)
        self.pdf_zip_qv.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        qrow.addWidget(qlab)
        qrow.addWidget(self.pdf_zip_quality, 1)
        qrow.addWidget(self.pdf_zip_qv)
        lay.addWidget(self.pdf_zip_qwrap)

        # 提示行右边挂「退出压缩」。放这一行而不是按钮行：
        # 压缩全部态按钮行是空的，退出按钮孤零零占一行很难看
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(8)
        self.pdf_zip_hint = QLabel("压缩功能未启用")
        self.pdf_zip_hint.setObjectName("hint")
        self.pdf_zip_hint.setWordWrap(True)
        hint_row.addWidget(self.pdf_zip_hint, 1)
        hint_row.addWidget(self.pdf_zip_cancel, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.addLayout(hint_row)
        lay.addStretch(1)

        # 质量条拖动会连发 valueChanged，每动一格就整队重算会把界面拖死
        self._pdf_zip_timer = QTimer(self)
        self._pdf_zip_timer.setSingleShot(True)
        self._pdf_zip_timer.setInterval(420)
        self._pdf_zip_timer.timeout.connect(self._pdf_zip_estimate)

        self._pdf_zip_set("off")
        return panel

    def _pdf_zip_set(self, mode: str) -> None:
        """切换压缩区状态。切走时把上一轮的估算停掉，别让旧数字飘上来。"""
        prev = getattr(self, "_pdf_zip_mode", "off")
        self._pdf_zip_mode = mode
        if mode in ("off", "pick"):
            self._pdf_zip_stop_estimate()
            self._pdf_zip_clear_subs()
        if prev != mode and mode in ("all", "part"):
            self._pdf_zip_clear_subs()

        off = mode == "off"
        pick = mode == "pick"
        self.pdf_zip_enable.setVisible(off)
        self.pdf_zip_all.setVisible(pick)
        self.pdf_zip_part.setVisible(pick)
        self.pdf_zip_run.setVisible(mode == "part")
        # 只要不在 off，「退出压缩」就得在，否则选了压缩部分又反悔时无路可退
        self.pdf_zip_cancel.setVisible(not off)
        self.pdf_zip_qwrap.setVisible(mode in ("all", "part"))
        self.pdf_zip_hint.setText(
            {
                "off": "压缩功能未启用",
                "pick": "选择压缩范围：全部页面，或只压选中的几页",
                "all": "导出时按此质量压缩所有页面的图片，文字层与页面尺寸不变",
                "part": "只压选中的页面，压缩结果先存临时文件；压完自动关闭压缩",
            }[mode]
        )
        self._pdf_zip_refresh()
        if mode in ("all", "part"):
            self._pdf_zip_estimate()

    def _pdf_zip_refresh(self) -> None:
        """压缩区按钮的可用性。选项跟着队列和选中走。"""
        n = len(self.pdf_items)
        sel = len(self.pdf_grid.selected_uids()) if hasattr(self, "pdf_grid") else 0
        busy = self._busy()
        self.pdf_zip_enable.setEnabled(n > 0 and not busy)
        self.pdf_zip_all.setEnabled(n > 0 and not busy)
        self.pdf_zip_part.setEnabled(sel > 0 and not busy)
        self.pdf_zip_run.setEnabled(sel > 0 and not busy)
        self.pdf_zip_cancel.setEnabled(not busy)

    def _pdf_zip_on_quality(self, v: int) -> None:
        self.pdf_zip_qv.setText(str(v))
        # 质量一变，之前压好的暂存文件就作废了 —— 留着会让导出用上
        # 旧质量的图片，用户完全看不出来
        if self._pdf_staged:
            self._pdf_drop_staged()
            self.pdf_zip_hint.setText("质量变了，之前的压缩结果已作废，请重新压缩")
        self._pdf_zip_timer.start()

    # ------------------------------------------------------------ 压缩：估算
    def _pdf_zip_targets(self) -> list[PdfItem]:
        """当前该显示预估的页面。压缩部分只看选中的几页。"""
        if self._pdf_zip_mode == "part":
            uids = set(self.pdf_grid.selected_uids())
            return [it for it in self.pdf_items if it.uid in uids]
        return list(self.pdf_items)

    def _pdf_zip_stop_estimate(self) -> None:
        self._pdf_est_gen += 1
        if self._pdf_est_cancel is not None:
            self._pdf_est_cancel.set()
            self._pdf_est_cancel = None
        self._pdf_est_key = None

    def _pdf_zip_clear_subs(self) -> None:
        """把格子下面那行尺寸字擦掉。"""
        for it in self.pdf_items:
            self.pdf_grid.set_sub(it.uid, "")

    def _pdf_zip_estimate(self) -> None:
        """算每页"当前 → 预估"。真解码真编码，所以整个丢后台，逐页回填。

        同一份 PDF 的多页合并成一次任务：pypdf 解析一份 80 页的文件要几百
        毫秒，每页各来一遍纯属浪费。
        """
        mode = self._pdf_zip_mode
        if mode not in ("all", "part"):
            return
        targets = [it for it in self._pdf_zip_targets() if it.ref.kind == "pdf"]
        q = self.pdf_zip_quality.value()
        key = (mode, q, tuple(it.uid for it in targets))
        if key == self._pdf_est_key:
            return
        self._pdf_est_stop_and_restart()
        self._pdf_est_key = key

        # 图片条目没有"页面内嵌图片"，直接标一句，别让它空着像算漏了
        for it in self.pdf_items:
            if it.ref.kind != "pdf":
                self.pdf_grid.set_sub(it.uid, "图片文件 · 不参与压缩", "dim")

        groups: dict[str, list[PdfItem]] = {}
        for it in targets:
            groups.setdefault(it.ref.src, []).append(it)
        if not groups:
            self._pdf_zip_update_hint()
            return

        gen = self._pdf_est_gen
        cancel = self._pdf_est_cancel
        if self._pdf_est_pool is None:
            # 单线程：估算本身是 CPU 活，多线程抢 GIL 只会更慢，
            # 而且 pypdf 的 reader 缓存不适合并发访问
            self._pdf_est_pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="pdfestimate"
            )
        for src, items in groups.items():
            self._pdf_est_pool.submit(self._pdf_est_job, gen, src, items, q, cancel)
        self._pdf_zip_update_hint()

    def _pdf_est_stop_and_restart(self) -> None:
        """取消上一轮估算，换一张新的取消票。"""
        if self._pdf_est_cancel is not None:
            self._pdf_est_cancel.set()
        self._pdf_est_gen += 1
        self._pdf_est_cancel = threading.Event()

    def _pdf_est_job(self, gen: int, src: str, items: list[PdfItem], quality: int, cancel) -> None:
        # 先吃缓存：压缩部分模式下用户来回点选同一页太常见了，每点一次
        # 都把整页图片重新解码一遍，界面会一顿一顿的
        todo: list[int] = []
        for it in items:
            hit = self._pdf_stat_cache.get((src, it.ref.index, quality))
            if hit is not None:
                self.emitter.pdf_stat_ready.emit(gen, src, it.ref.index, hit)
            else:
                todo.append(it.ref.index)
        if not todo:
            return
        try:
            stats = estimate_pdf(src, quality, todo, cancel=cancel)
        except Exception:  # noqa: BLE001
            return
        for idx, st in stats.items():
            self._pdf_stat_cache[(src, idx, quality)] = st
            if gen != self._pdf_est_gen:
                continue
            self.emitter.pdf_stat_ready.emit(gen, src, idx, st)

    def _on_pdf_stat(self, gen: int, src: str, idx: int, st) -> None:
        if gen != self._pdf_est_gen:
            return
        self._pdf_stats[(src, idx)] = st
        label = st.label()
        tone = "ok" if st.estimated else "dim"
        for it in self.pdf_items:
            if it.ref.src == src and it.ref.index == idx:
                self.pdf_grid.set_sub(it.uid, label, tone)
        self._pdf_zip_update_hint()

    def _pdf_zip_update_hint(self) -> None:
        """提示行汇总当前预估：全部 12 页 · 图片 8.4 MB → 2.1 MB（省 75%）。"""
        mode = self._pdf_zip_mode
        if mode not in ("all", "part"):
            return
        targets = [it for it in self._pdf_zip_targets() if it.ref.kind == "pdf"]
        if not targets:
            self.pdf_zip_hint.setText("队列里没有 PDF 页面可压缩")
            return
        done = sum(
            1 for it in targets if (it.ref.src, it.ref.index) in self._pdf_stats
        )
        head = f"选中 {len(targets)} 页" if mode == "part" else f"全部 {len(targets)} 页"
        if done < len(targets):
            self.pdf_zip_hint.setText(f"{head} · 正在估算 {done}/{len(targets)}…")
            return
        cur, est = self._pdf_zip_totals(targets)
        if not cur:
            self.pdf_zip_hint.setText(f"{head} · 没有可压缩的图片")
            return
        pct = (1 - est / cur) * 100 if cur else 0
        self.pdf_zip_hint.setText(
            f"{head} · 图片 {_fmt_bytes(cur)} → {_fmt_bytes(est)}（省 {pct:.0f}%）"
        )

    def _pdf_zip_totals(self, targets: list[PdfItem]) -> tuple[int, int]:
        cur = est = 0
        for it in targets:
            st = self._pdf_stats.get((it.ref.src, it.ref.index))
            if st is None:
                continue
            cur += st.cur_bytes
            est += st.est_bytes or st.cur_bytes
        return cur, est

    # ------------------------------------------------------------ 压缩：执行
    def _pdf_zip_compress_selected(self) -> None:
        """压缩选中：立刻压、存临时文件，压完把压缩区收回未启用。"""
        if self._busy():
            return
        items = [it for it in self._pdf_zip_targets() if it.ref.kind == "pdf"]
        if not items:
            QMessageBox.information(
                self, "没有可压缩的页面", "选中的都是图片文件，压缩只作用于 PDF 页面里的图片。"
            )
            return
        quality = self.pdf_zip_quality.value()
        stamp = time.strftime("%H%M%S")
        out_dir = self._pdf_stage_root() / stamp
        self._pdf_zip_results = []

        def work(progress):
            total = len(items)
            for i, it in enumerate(items):
                path = out_dir / f"p{i:04d}.pdf"
                stage_page(it.ref, path, quality)
                self._pdf_zip_results.append(
                    ((it.ref.src, it.ref.index, it.ref.rotate % 360), path)
                )
                progress(int((i + 1) / total * 100))
            return f"已压缩 {total} 页，导出时生效"

        self._pdf_kind = "zip"
        self._pdf_t0 = time.time()
        self._pdf_result = str(out_dir)
        self._set_running(True)
        self._set_progress(0)
        self.current_label.setText(f"正在压缩 {len(items)} 页的图片…")
        self.pdf_runner.start(work, "zip")

    def _pdf_stage_root(self) -> Path:
        if self._pdf_stage_dir is None:
            self._pdf_stage_dir = Path(tempfile.mkdtemp(prefix="zzbox_pdf_zip_"))
        return self._pdf_stage_dir

    def _pdf_drop_staged(self) -> None:
        """丢掉暂存的压缩页。质量变了、队列清空、程序退出时都要调。"""
        self._pdf_staged.clear()
        if self._pdf_stage_dir is not None:
            shutil.rmtree(self._pdf_stage_dir, ignore_errors=True)
            self._pdf_stage_dir = None
        for it in self.pdf_items:
            if it.ref.kind == "pdf" and self._pdf_zip_mode in ("all", "part"):
                continue
            self.pdf_grid.set_sub(it.uid, "")

    # ------------------------------------------------------------ PDF 导入
    def _pdf_pick(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 PDF 或图片",
            "",
            "PDF 与图片 (*.pdf *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif)"
            ";;PDF (*.pdf);;图片 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif)"
            ";;所有文件 (*.*)",
        )
        if files:
            self._pdf_add_paths([Path(f) for f in files])

    def _pdf_add_paths(self, paths: list[Path]) -> None:
        """导入：PDF 按页展开，图片一格一张。

        读不出来的文件不塞进队列（会变成一堆点不开的红格子），
        收集起来一次性告诉用户是哪几个。
        """
        added: list[PdfItem] = []
        bad: list[str] = []
        for p in paths:
            if not p.is_file():
                continue
            suffix = p.suffix.lower()
            if suffix == ".pdf":
                info = self.pdf_cache.get(str(p)) or probe_pdf(p)
                self.pdf_cache[str(p)] = info
                if not info.ok:
                    bad.append(f"{p.name}（{info.error}）")
                    continue
                for i in range(info.pages):
                    added.append(self._pdf_new_item(p, "pdf", i, info))
            elif suffix in IMAGE_EXT:
                from app.core.image import probe_image as _probe

                info = self.img_cache.get(str(p)) or _probe(p)
                self.img_cache[str(p)] = info
                if not info.ok:
                    bad.append(f"{p.name}（{info.error}）")
                    continue
                added.append(self._pdf_new_item(p, "image", 0, None))
            else:
                bad.append(f"{p.name}（不支持这种格式）")

        if added:
            self.pdf_items.extend(added)
            self._pdf_rebuild_grid()
            self._pdf_start_thumbs(added)
        self._pdf_refresh()

        if bad:
            extra = f"\n另外 {len(added)} 页已加入队列。" if added else ""
            QMessageBox.warning(
                self,
                "有文件没能读取",
                "以下文件被跳过：\n\n" + "\n".join(bad[:8])
                + (f"\n…还有 {len(bad) - 8} 个" if len(bad) > 8 else "")
                + extra,
            )

    def _pdf_new_item(self, path: Path, kind: str, index: int, info) -> PdfItem:
        self._pdf_seq += 1
        uid = f"p{self._pdf_seq}"
        item = PdfItem(uid=uid, ref=PageRef(str(path), kind, index), origin=path.name)
        if kind == "pdf" and info is not None and index < len(info.sizes):
            item.w, item.h = info.sizes[index]
            item.label = f"第 {index + 1} 页 · {path.stem}"
            item.label = self._pdf_elide(item.label)
        else:
            from app.core.image import probe_image as _probe

            img = self.img_cache.get(str(path)) or _probe(path)
            item.w, item.h = float(img.width), float(img.height)
            item.label = self._pdf_elide(f"图片 · {path.name}")
        self.pdf_by_uid[uid] = item
        return item

    @staticmethod
    def _pdf_elide(text: str, limit: int = 16) -> str:
        # 格子下面只有一行字，超过这个长度就中间省略，否则会被 Qt 截成
        # 「第 1 页 · 二〇二…」，看不出是哪个文件
        return text if len(text) <= limit else text[: limit - 3] + "…"

    def _pdf_rebuild_grid(self) -> None:
        self.pdf_grid.blockSignals(True)
        self.pdf_grid.rebuild([(it.uid, self._pdf_label_of(it)) for it in self.pdf_items])
        self.pdf_grid.blockSignals(False)
        # 已有的缩略图直接回填，只给还没渲染过的排队
        for it in self.pdf_items:
            if it.thumb_png:
                self.pdf_grid.set_thumb(it.uid, it.thumb_png)
        self._pdf_repaint_labels()
        self._pdf_repaint_subs()

    def _pdf_repaint_subs(self) -> None:
        """重建格子会把 item 的 data 全清掉，尺寸行得补回来。

        压缩部分模式不补：它只显示选中页的数字，而重建之后选中是空的 ——
        补出来的会是"上一位用户的选中"，等 selection 回调再算一遍才对。
        """
        mode = getattr(self, "_pdf_zip_mode", "off")
        for it in self.pdf_items:
            if self._pdf_staged.get((it.ref.src, it.ref.index, it.ref.rotate % 360)):
                self.pdf_grid.set_sub(it.uid, "已压缩 · 导出时生效", "ok")
                continue
            if mode == "all" and it.ref.kind == "pdf":
                st = self._pdf_stats.get((it.ref.src, it.ref.index))
                if st is not None:
                    self.pdf_grid.set_sub(
                        it.uid, st.label(), "ok" if st.estimated else "dim"
                    )

    def _pdf_label_of(self, it: PdfItem) -> str:
        if it.ref.rotate:
            return f"{it.label} ↻{it.ref.rotate % 360}°"
        return it.label

    def _pdf_repaint_labels(self) -> None:
        for it in self.pdf_items:
            self.pdf_grid.set_label(it.uid, self._pdf_label_of(it))

    def _pdf_start_thumbs(self, items: list[PdfItem]) -> None:
        """缩略图丢进线程池。渲染一页 A4 约 30~80 ms，200 页四线程不到 4 秒。"""
        if self._pdf_pool is None:
            self._pdf_pool = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="pdfthumb"
            )
        for it in items:
            self._pdf_thumb_jobs += 1
            self._pdf_pool.submit(self._pdf_thumb_job, it.uid, it.ref)

    def _pdf_thumb_job(self, uid: str, ref: PageRef) -> None:
        try:
            data, _w, _h = thumb_bytes(ref)
        except Exception:  # noqa: BLE001
            return
        self.emitter.pdf_thumb_ready.emit(uid, data)

    def _on_pdf_thumb(self, uid: str, data: bytes) -> None:
        self.pdf_grid.set_thumb(uid, data)
        item = self.pdf_by_uid.get(uid)
        if item is not None:
            item.thumbbed = True
            item.thumb_png = data
        self._pdf_thumb_done += 1
        if self._pdf_thumb_done >= self._pdf_thumb_jobs:
            self._pdf_thumb_jobs = 0
            self._pdf_thumb_done = 0
            self._pdf_refresh()

    # ------------------------------------------------------------ PDF 队列
    def _pdf_on_reorder(self, uids: list) -> None:
        order = {uid: i for i, uid in enumerate(uids)}
        self.pdf_items.sort(key=lambda it: order.get(it.uid, 1 << 30))
        self._pdf_refresh()

    def _pdf_on_selection(self) -> None:
        n = len(self.pdf_grid.selected_uids())
        busy = self._busy()
        self.pdf_btn_rotate.setEnabled(bool(n) and not busy)
        self.pdf_btn_extract.setEnabled(bool(n) and not busy)
        self.pdf_btn_del.setEnabled(bool(n) and not busy)
        self._pdf_refresh()
        # 压缩部分只给选中的页面算预估，选中变了就得重算一遍；
        # 压缩全部不受选中影响，不用跟着抖
        if getattr(self, "_pdf_zip_mode", "off") == "part":
            self._pdf_zip_clear_subs()
            self._pdf_zip_estimate()

    def _pdf_select_all(self) -> None:
        self.pdf_grid.select_all_items()

    def _pdf_delete_selected(self) -> None:
        if self._busy():
            return
        drop = set(self.pdf_grid.selected_uids())
        if not drop:
            return
        self.pdf_items = [it for it in self.pdf_items if it.uid not in drop]
        for uid in drop:
            self.pdf_by_uid.pop(uid, None)
        self._pdf_rebuild_grid()
        # 重建会清掉选中项，按钮可用性得按"现在还剩什么"重算一遍
        self._pdf_on_selection()

    def _pdf_clear(self) -> None:
        if self._busy():
            return
        self.pdf_items.clear()
        self.pdf_by_uid.clear()
        self._pdf_thumb_jobs = 0
        self._pdf_thumb_done = 0
        self._pdf_zip_stop_estimate()
        self._pdf_stats.clear()
        self._pdf_stat_cache.clear()
        self._pdf_drop_staged()
        self._pdf_zip_set("off")
        self._pdf_rebuild_grid()
        self._pdf_on_selection()

    def _pdf_refresh(self) -> None:
        """统一刷新计数和按钮可用性。"""
        n = len(self.pdf_items)
        sel = len(self.pdf_grid.selected_uids()) if hasattr(self, "pdf_grid") else 0
        if not n:
            self.pdf_count.setText("PDF 队列 · 空")
        else:
            parts = [f"{n} 页"]
            if sel:
                parts.append(f"选中 {sel}")
            if self._pdf_thumb_jobs:
                parts.append(f"生成预览 {self._pdf_thumb_done}/{self._pdf_thumb_jobs}")
            self.pdf_count.setText("PDF 队列 · " + " · ".join(parts))

        busy = self._busy()
        self.pdf_btn_all.setEnabled(bool(n) and not busy)
        self.pdf_btn_clear.setEnabled(bool(n) and not busy)
        if not n:
            for b in (
                self.pdf_btn_rotate,
                self.pdf_btn_extract,
                self.pdf_btn_del,
            ):
                b.setEnabled(False)
        if hasattr(self, "pdf_zip_enable"):
            self._pdf_zip_refresh()
        if self._page == 2:
            self._update_start_text()
            self._sync_tray()

    def _pdf_rotate(self) -> None:
        uids = self.pdf_grid.selected_uids()
        if not uids:
            return
        for uid in uids:
            it = self.pdf_by_uid.get(uid)
            if it is None:
                continue
            it.ref.rotate = (it.ref.rotate + 90) % 360
            it.thumbbed = False
            it.thumb_png = b""
            self.pdf_grid.set_label(uid, self._pdf_label_of(it))
            # 旋转后的缩略图必须重渲染，否则用户看到的还是正的，
            # 导出却是歪的 —— 这种"界面和结果不一致"最伤信任
            if self._pdf_pool is not None:
                self._pdf_thumb_jobs += 1
                self._pdf_pool.submit(self._pdf_thumb_job, uid, it.ref)
        self._pdf_refresh()

    def _pdf_target_refs(self, only_selected: bool) -> list[PageRef]:
        if only_selected:
            uids = self.pdf_grid.selected_uids()
            return [self.pdf_by_uid[u].ref for u in uids if u in self.pdf_by_uid]
        return [it.ref for it in self.pdf_items]

    def _pdf_out_base(self) -> Path:
        text = self.out_dir.text().strip()
        if text:
            p = Path(text)
            if p.is_dir():
                return p
        if self.pdf_items:
            return Path(self.pdf_items[0].ref.src).parent
        return Path.home()

    # ------------------------------------------------------------ PDF 导出
    def _pdf_extract(self) -> None:
        """导出选中：无损搬运，文字层和链接都留着。"""
        refs = self._pdf_target_refs(only_selected=True)
        if not refs:
            return
        menu = QMenu(self)
        act_one = menu.addAction(f"导出为 1 个 PDF（{len(refs)} 页）")
        act_many = menu.addAction("导出为多个 PDF（每页一个）")
        menu.addSeparator()
        act_png = menu.addAction("导出为 PNG 图片")
        act_jpg = menu.addAction("导出为 JPG 图片")
        act_one.setToolTip("不重新渲染，文字层、链接、表单原样保留")
        chosen = menu.exec(self.pdf_btn_extract.mapToGlobal(self.pdf_btn_extract.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen is act_png:
            self._pdf_run_images(refs, "png")
        elif chosen is act_jpg:
            self._pdf_run_images(refs, "jpg")
        elif chosen is act_many:
            self._pdf_run_pdf_each(refs)
        else:
            self._pdf_run_pdf_one(refs, stem=f"选中_{len(refs)}页")

    def _pdf_export(self) -> None:
        """底部导出：按当前队列顺序落盘。"""
        if not self.pdf_items:
            QMessageBox.information(
                self, "队列是空的", "先把 PDF 或图片拖进来，或点右上角“+”添加。"
            )
            return
        # 托盘菜单也能触发导出，但选格式必须看得见菜单 —— 窗口藏着的话先叫回来
        if not self.isVisible():
            self.restore_from_tray()
        refs = self._pdf_target_refs(only_selected=False)
        menu = QMenu(self)
        act_one = menu.addAction("合并为 1 个 PDF")
        act_by_src = menu.addAction("按来源分别导出多个 PDF")
        menu.addSeparator()
        act_png = menu.addAction("导出为 PNG 图片（每页一张）")
        act_jpg = menu.addAction("导出为 JPG 图片（每页一张）")
        chosen = menu.exec(
            self.btn_start.mapToGlobal(self.btn_start.rect().topLeft())
        )
        if chosen is None:
            return
        if chosen is act_png:
            self._pdf_run_images(refs, "png")
        elif chosen is act_jpg:
            self._pdf_run_images(refs, "jpg")
        elif chosen is act_by_src:
            self._pdf_run_pdf_many(refs, prefix="整理")
        else:
            self._pdf_run_pdf_one(refs, stem="合并")

    def _pdf_stamp(self) -> str:
        return time.strftime("%Y%m%d_%H%M")

    def _pdf_run_pdf_one(self, refs: list[PageRef], stem: str) -> None:
        out = self._pdf_out_base() / f"{safe_stem(stem)}_{self._pdf_stamp()}.pdf"
        if self._pdf_zip_active():
            self._pdf_start_zip([(refs, out)], f"导出 {len(refs)} 页")
            return
        self._pdf_start_job("export", f"导出 {len(refs)} 页", out, refs)

    def _pdf_run_pdf_each(self, refs: list[PageRef]) -> None:
        """每页一个 PDF，名字跟着原始文件走：`报告·3.pdf`。

        页号是这页在原始文件里的位置，不是队列里的位置。同一个原文件
        被拖进来两次时页号会撞车，unique_path 自动挂 (2)，不覆盖。
        """
        base = self._pdf_out_base()
        used: set[str] = set()
        jobs = [
            (page_stem(ref), [ref], unique_path(base, page_stem(ref), ".pdf", used))
            for ref in refs
        ]
        if self._pdf_zip_active():
            self._pdf_start_zip(
                [(group, out) for _name, group, out in jobs], f"导出 {len(jobs)} 个 PDF"
            )
            return
        self._pdf_start_batch_pdf(jobs)

    def _pdf_run_pdf_many(self, refs: list[PageRef], prefix: str) -> None:
        """按来源分组，每组一个 PDF。同一份源文件被拆开过，导回来还是它自己。"""
        groups: dict[str, list[PageRef]] = {}
        for ref in refs:
            groups.setdefault(ref.src, []).append(ref)
        base = self._pdf_out_base()
        stamp = self._pdf_stamp()
        jobs = [
            (Path(src).stem, group, base / f"{safe_stem(Path(src).stem)}_{prefix}_{stamp}.pdf")
            for src, group in groups.items()
        ]
        if self._pdf_zip_active():
            self._pdf_start_zip(
                [(group, out) for _name, group, out in jobs], f"导出 {len(jobs)} 个 PDF"
            )
            return
        self._pdf_start_batch_pdf(jobs)

    def _pdf_zip_active(self) -> bool:
        """这次导出要不要走 pypdf 那条（能改图片的）管线。

        两种情况：压缩全部开着（导出时才真压），或者有部分页已经压好暂存了
        （那些页必须用暂存文件，否则用户的"压缩选中"白点了）。
        """
        if getattr(self, "_pdf_zip_mode", "off") == "all":
            return True
        return any(Path(p).exists() for p in self._pdf_staged.values())

    def _pdf_start_zip(self, jobs: list[tuple[list[PageRef], Path]], label: str) -> None:
        """走 pypdf 管线导出：边合并边替换页面里的图片。

        和 export_pdf（pdfium 整页搬运）二选一 —— pdfium 没有修改 PDF
        对象的 API，压缩只能换另一条路。代价是 pypdf 写文件比 pdfium 慢，
        换来的是文字层和页面尺寸一个字节都不动。
        """
        quality = self.pdf_zip_quality.value() if self._pdf_zip_mode == "all" else None
        staged = dict(self._pdf_staged)
        total = max(1, len(jobs))

        def work(progress):
            for i, (refs, out) in enumerate(jobs):
                def sub(pct, _i=i):
                    progress(int((_i + pct / 100) / total * 100))

                merge_pdf(
                    refs,
                    out,
                    quality=quality,
                    staged=staged,
                    progress=sub,
                    cancel=self.pdf_runner.cancel_event,
                )
            return f"已导出 {total} 个 PDF"

        self._pdf_kind = "zip-export"
        self._pdf_t0 = time.time()
        self._pdf_result = str(jobs[0][1].parent) if jobs else ""
        self._set_running(True)
        self._set_progress(0)
        self.current_label.setText(f"{label}…")
        self.pdf_runner.start(work, "zip-export")

    def _pdf_run_images(self, refs: list[PageRef], fmt: str) -> None:
        base = self._pdf_out_base()
        # 单来源用自己的名字，多来源混排就叫「拆分」，免得张冠李戴
        heads = {Path(ref.src).stem for ref in refs}
        tag = safe_stem(next(iter(heads))) if len(heads) == 1 else "拆分"
        out_dir = base / f"{tag}_{'png' if fmt == 'png' else 'jpg'}_{self._pdf_stamp()}"

        def work(progress):
            files = export_images(
                refs, out_dir,
                fmt=fmt, dpi=200.0, quality=92, progress=progress,
            )
            return f"已导出 {len(files)} 张图片到 {out_dir.name}"

        self._pdf_kind = "image"
        self._pdf_t0 = time.time()
        self._pdf_result = str(out_dir)
        self._set_running(True)
        self._set_progress(0)
        self.current_label.setText(f"正在导出 {len(refs)} 张图片…")
        self.pdf_runner.start(work, "image")

    def _pdf_start_job(self, kind: str, label: str, out: Path, refs: list[PageRef]) -> None:
        def work(progress):
            export_pdf(refs, out, progress=progress)
            return str(out)

        self._pdf_kind = kind
        self._pdf_t0 = time.time()
        self._pdf_result = str(out)
        self._set_running(True)
        self._set_progress(0)
        self.current_label.setText(f"{label} → {out.name}")
        self.pdf_runner.start(work, kind)

    def _pdf_start_batch_pdf(self, jobs: list[tuple[str, list[PageRef], Path]]) -> None:
        """多个输出文件串行跑，进度按文件数切段。"""
        total = len(jobs)

        def work(progress):
            done = 0
            for _name, refs, out in jobs:
                def sub(pct, _d=done):
                    progress(int((_d + pct / 100) / total * 100))

                export_pdf(refs, out, progress=sub)
                done += 1
            return f"已导出 {total} 个 PDF"

        self._pdf_kind = "export"
        self._pdf_t0 = time.time()
        self._pdf_result = str(jobs[0][2].parent) if jobs else ""
        self._set_running(True)
        self._set_progress(0)
        self.current_label.setText(f"正在导出 {total} 个 PDF…")
        self.pdf_runner.start(work, "export")

    # ------------------------------------------------------------ PDF 执行
    def _on_pdf_progress(self, pct: int) -> None:
        self._set_progress(pct)
        if self._pdf_kind == "zip":
            self.current_label.setText(f"正在压缩图片… {pct}%")
        elif self._pdf_kind == "image":
            self.current_label.setText(f"正在导出图片… {pct}%")
        else:
            self.current_label.setText(f"正在导出… {pct}%")

    def _on_pdf_finished(self, ok: bool, msg: str) -> None:
        kind = self._pdf_kind
        self._stopping = False
        self._set_running(False)
        secs = time.time() - self._pdf_t0 if self._pdf_t0 else 0.0
        verb = {"image": "导出图片", "zip": "压缩"}.get(kind, "导出")

        if ok and kind == "zip":
            # 部分压缩完成：把临时文件登记进暂存表，压缩区收回未启用。
            # 之后的导出直接拿这些文件用，不再重算
            for key, path in self._pdf_zip_results:
                self._pdf_staged[key] = str(path)
            count = len(self._pdf_zip_results)
            self._pdf_zip_results = []
            self._set_progress(100)
            self.current_label.setText(f"已压缩 {count} 页")
            self.stats_label.setText("压缩结果已暂存，导出时直接使用")
            self._pdf_zip_set("off")
            self._pdf_repaint_subs()
            if not self.isVisible() and self.tray:
                self.tray.notify("压缩完成", f"{count} 页已暂存")
            self._pdf_kind = ""
            self._pdf_on_selection()
            return

        if ok:
            self._set_progress(100)
            self.current_label.setText(f"{verb}完成")
            where = Path(self._pdf_result).name if self._pdf_result else ""
            self.stats_label.setText(
                f"{where} · 用时 {'<1' if secs < 1 else f'{secs:.0f}'} 秒"
            )
            if not self.isVisible() and self.tray:
                self.tray.notify(f"{verb}完成", where or msg)
        elif msg == "已取消":
            self.current_label.setText("已取消")
            self.stats_label.setText("")
        else:
            self.current_label.setText(f"{verb}失败")
            self.stats_label.setText(msg[:80])
            QMessageBox.warning(self, f"{verb}失败", msg)
        self._pdf_kind = ""
        # _set_running(False) 把所有按钮无脑打开，得按当前选中状态再收一遍，
        # 否则跑完之后「旋转选中」在没选页时也是亮的，点了什么都不会发生
        self._pdf_on_selection()

    # ------------------------------------------------------------ 视频参数面板
    def _page_compress(self) -> QWidget:
        """四组参数压成一张扁面板的 2×2 格子。

        原来是四张卡片，每张都有标题行和说明行，光装饰就 200 多像素 ——
        那是五条队列。说明改到 tooltip，参数一行说完，队列立刻多显示几行。
        """
        panel = OptionPanel(2)
        self.compress_panel = panel

        self.enc_chips = ChipGroup(
            [("h264", "H.264"), ("hevc", "HEVC"), ("av1", "AV1")]
        )
        self.enc_chips.set_value("hevc")
        self.enc_chips.changed.connect(lambda _k: self._refresh_rows())
        for key, tip in (
            ("h264", "兼容性最好，同画质体积最大"),
            ("hevc", "同画质约为 H.264 的 88%，现代设备都能播"),
            ("av1", "同画质约为 H.264 的 75%，压缩最省，但老设备播不了"),
        ):
            self.enc_chips.button(key).setToolTip(tip)

        self.audio_chips = ChipGroup(
            [("aac", "压缩 AAC"), ("copy", "保留原样"), ("none", "删除")]
        )
        self.audio_chips.set_value("aac")
        self.audio_chips.changed.connect(lambda _k: self._refresh_rows())
        self.audio_chips.button("copy").setToolTip("音轨原样拷贝，不重新编码，速度最快")
        self.audio_chips.button("none").setToolTip("输出文件不带音轨")

        panel.add("编码器", self.enc_chips)
        panel.add("音轨", self.audio_chips)
        panel.add("质量", self._quality_row())
        panel.add("缩放", self._scale_row())
        panel.set_note("选择文件后显示输出规格")
        return panel

    def _quality_row(self) -> QWidget:
        self.mode_chips = ChipGroup([("crf", "CRF"), ("bitrate", "码率")], stretch=False)
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

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(self.mode_chips)
        row.addWidget(self._crf_row, 1)
        row.addWidget(self._br_row, 1)
        self._br_row.setVisible(False)
        self.mode_chips.button("crf").setToolTip(
            "数值越小画质越好、体积越大\n已按 CPU CRF 等效校准"
        )
        self.mode_chips.button("bitrate").setToolTip("固定码率，出片体积可预期")
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    def _scale_row(self) -> QWidget:
        self.scale_chips = ChipGroup(
            [("25", "25%"), ("50", "50%"), ("100", "100%"), ("200", "200%")],
            stretch=False,
        )
        self.scale_chips.set_value("100")
        self.scale_chips.changed.connect(self._on_scale_chip)

        self.custom_pct = QLineEdit()
        self.custom_pct.setPlaceholderText("百分比或 1280x720")
        self.custom_pct.setToolTip("填 37 表示 37%；填 1280x720 表示指定尺寸")
        # 宽度按占位文字算，够用就好，不要占满整行
        fm = self.custom_pct.fontMetrics()
        self.custom_pct.setFixedWidth(
            max(120, min(176, fm.horizontalAdvance(self.custom_pct.placeholderText()) + 22))
        )
        self.custom_pct.textChanged.connect(self._on_custom_scale)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.scale_chips)
        row.addWidget(self.custom_pct)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    # ------------------------------------------------------------ 视频 AI 面板
    def _page_ai(self) -> QWidget:
        panel = OptionPanel(2)
        self.ai_panel = panel

        self.ai_scale_chips = ChipGroup(
            [("0", "关闭"), ("2", "2×"), ("3", "3×"), ("4", "4×")]
        )
        self.ai_scale_chips.set_value("2")
        self.ai_scale_chips.changed.connect(lambda _k: self._refresh_ai())

        self.ai_model_chips = ChipGroup(
            [("photo", "真人实拍"), ("anime", "动画番剧")]
        )
        self.ai_model_chips.set_value(DEFAULT_MODEL)
        self.ai_model_chips.changed.connect(lambda _k: self._refresh_ai())
        for key, (_n, _sc, _label, note) in MODELS.items():
            self.ai_model_chips.button(key).setToolTip(note)

        self.ai_interp_chips = ChipGroup([("1", "关闭"), ("2", "2×"), ("4", "4×")])
        self.ai_interp_chips.set_value("1")
        self.ai_interp_chips.changed.connect(lambda _k: self._refresh_ai())
        self.ai_interp_chips.button("2").setToolTip("帧率翻倍，时长不变，音轨原样保留")

        self.ai_enc_chips = ChipGroup(
            [("h264", "H.264"), ("hevc", "HEVC"), ("av1", "AV1")]
        )
        self.ai_enc_chips.set_value("hevc")
        self.ai_enc_chips.changed.connect(lambda _k: self._refresh_ai())

        # 降噪 / 锐化：补模型短板的两个开关，挤在同一格里省一行
        self.ai_denoise_chips = ChipGroup(
            [("0", "关"), ("1", "轻度"), ("2", "较强")], stretch=False
        )
        self.ai_denoise_chips.set_value("0")
        self.ai_denoise_chips.changed.connect(lambda _k: self._refresh_ai())
        for k in ("0", "1", "2"):
            self.ai_denoise_chips.button(k).setToolTip(
                "低码率视频先降噪再超分，避免把压缩块和振铃一起放大 4 倍\n"
                "逐帧对比过：轻度档对细节几乎无损，压制痕迹明显的源值得开"
            )
        self.ai_sharpen_chips = ChipGroup(
            [("0", "关"), ("1", "轻度"), ("2", "较强")], stretch=False
        )
        self.ai_sharpen_chips.set_value("1")
        self.ai_sharpen_chips.changed.connect(lambda _k: self._refresh_ai())
        for k in ("0", "1", "2"):
            self.ai_sharpen_chips.button(k).setToolTip(
                "4× 重建后降到目标尺寸，边缘会软一档，补一点 unsharp 拉回来\n"
                "默认轻度；开到「较强」会开始出白边，慎用"
            )

        panel.add("超分", self.ai_scale_chips)
        panel.add("模型", self.ai_model_chips)
        panel.add("补帧", self.ai_interp_chips)
        panel.add("编码", self.ai_enc_chips)
        # 降噪/锐化两组胶囊半格放不下，独占一行
        panel.add_row(self._ai_quality_row())

        self.ai_engine_info = panel.note
        self.ai_alert = panel.alert
        panel.set_note("引擎检测中…")
        return panel

    def _ai_quality_row(self) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        # 一组「标签 + 三颗胶囊」要留够间隙，不然「降噪」和「关」会粘成
        # 一个词，看上去像「降噪关」
        row.setSpacing(10)
        for text, widget in (
            ("降噪", self.ai_denoise_chips),
            ("锐化", self.ai_sharpen_chips),
        ):
            tag = QLabel(text)
            tag.setObjectName("optlabel")
            tag.setFixedWidth(26)
            row.addWidget(tag)
            row.addWidget(widget, 1)
            row.addSpacing(6)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

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
        if self._page == 2:
            n = len(self.pdf_items)
            if self.pdf_runner.busy():
                pct = self._progress_pct
                return (
                    f"PDF 处理中 {pct}%",
                    f"{APP_TITLE} · PDF · {pct}%",
                )
            if n:
                return f"就绪 · {n} 页", f"{APP_TITLE} · PDF（{n} 页）"
            return "就绪 · 队列为空", f"{APP_TITLE} · 就绪"
        total = len(self.files)
        if self._busy() and 0 <= self._index < total:
            name = self.files[self._index].name
            pct = self._progress_pct
            # 工具类任务和压制共用托盘，措辞得跟着换，不然抽音频也显示“压制中”
            verb = {"encode": "压制中", "ai": "AI 增强中"}.get(
                self._mode, self.TOOL_PROGRESS.get(self._mode, "处理中")
            )
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
        busy = self._busy()
        if self._page == 2:
            # PDF 不依赖 FFmpeg，环境没探测好也照样能导出
            runnable = bool(self.pdf_items)
            ready_env = True
        else:
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
        if self._busy():
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
            # 四条管线各有各的执行器，取消要挨个点名 ——
            # 只取消 runner 的话，PDF 那条线程会拖着程序退不干净
            if self.pdf_runner.busy():
                self.pdf_runner.cancel()
            if self.runner.busy():
                self.runner.cancel()
        self._quitting = True
        # 压缩暂存目录是 mkdtemp 建的，系统不会帮我们收 —— 里面可能是
        # 几十个单页 PDF，不删就一直占着硬盘
        self._pdf_drop_staged()
        if self._pdf_est_pool is not None:
            self._pdf_est_pool.shutdown(wait=False, cancel_futures=True)
            self._pdf_est_pool = None
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
    # ------------------------------------------------------------ 图片参数面板
    def _page_img_compress(self) -> QWidget:
        """图片压缩：格式 / 质量 / 长边 / 元数据。

        和视频压缩页同一个布局逻辑（一张扁面板、两列格子），用户在视频那边
        建立的肌肉记忆直接能用。
        """
        panel = OptionPanel(2)
        self.img_panel = panel

        self.img_fmt_chips = ChipGroup(
            [("keep", "保持原样"), ("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP")]
        )
        self.img_fmt_chips.set_value("keep")
        self.img_fmt_chips.changed.connect(lambda _k: self._refresh_img())
        self.img_fmt_chips.button("keep").setToolTip("跟随每张图自己的格式，只改质量和尺寸")
        self.img_fmt_chips.button("jpg").setToolTip("通用性最好，不支持透明")
        self.img_fmt_chips.button("png").setToolTip("无损，体积最大，支持透明")
        self.img_fmt_chips.button("webp").setToolTip("同画质体积约为 JPG 的 70%，支持透明")

        self.img_quality_slider = QSlider(Qt.Horizontal)
        self.img_quality_slider.setRange(40, 100)
        self.img_quality_slider.setValue(82)
        self.img_quality_slider.valueChanged.connect(self._on_img_quality)
        self.img_quality_value = QLabel("82")
        self.img_quality_value.setFixedWidth(24)
        self.img_quality_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.img_side_chips = ChipGroup(
            [("0", "不改变"), ("1920", "长边 1920"), ("1280", "长边 1280")],
            stretch=False,
        )
        self.img_side_chips.set_value("0")
        self.img_side_chips.changed.connect(lambda _k: self._refresh_img())
        self.img_side_input = QLineEdit()
        self.img_side_input.setPlaceholderText("像素")
        self.img_side_input.setFixedWidth(64)
        self.img_side_input.setToolTip("自定义长边像素，只缩不放")
        self.img_side_input.textChanged.connect(lambda _t: self._refresh_img())

        self.img_meta_chips = ChipGroup([("keep", "保留"), ("strip", "清除")])
        self.img_meta_chips.set_value("keep")
        self.img_meta_chips.changed.connect(lambda _k: self._refresh_img())
        self.img_meta_chips.button("strip").setToolTip(
            "去掉 EXIF、拍摄时间、GPS 和相机型号 —— 发图前建议清掉"
        )

        panel.add("格式", self.img_fmt_chips)
        panel.add("质量", self._img_quality_row())
        panel.add("长边", self._img_side_row())
        panel.add("元数据", self.img_meta_chips)

        self.img_cost_info = panel.note
        panel.set_note("选择图片后显示输出规格")
        return panel

    def _on_img_quality(self, v: int) -> None:
        self.img_quality_value.setText(str(v))
        self._refresh_img()

    def _img_quality_row(self) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.img_quality_slider, 1)
        row.addWidget(self.img_quality_value)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    def _img_side_row(self) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.img_side_chips)
        row.addWidget(self.img_side_input)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    def _page_img_ai(self) -> QWidget:
        panel = OptionPanel(2)
        self.img_ai_panel = panel

        self.img_ai_scale = ChipGroup(
            [("0", "关闭"), ("2", "2×"), ("3", "3×"), ("4", "4×")]
        )
        self.img_ai_scale.set_value("2")
        self.img_ai_scale.changed.connect(lambda _k: self._refresh_img())

        self.img_ai_model = ChipGroup(
            [("photo", "真人实拍"), ("anime", "动画番剧")]
        )
        self.img_ai_model.set_value(DEFAULT_MODEL)
        self.img_ai_model.changed.connect(lambda _k: self._refresh_img())
        for key, (_n, _sc, _label, note) in MODELS.items():
            self.img_ai_model.button(key).setToolTip(note)

        self.img_ai_fmt = ChipGroup(
            [("keep", "跟随源"), ("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")]
        )
        self.img_ai_fmt.set_value("keep")
        self.img_ai_fmt.changed.connect(lambda _k: self._refresh_img())
        self.img_ai_fmt.button("png").setToolTip("超分细节最完整的落盘格式，体积也最大")

        self.img_ai_denoise = ChipGroup(
            [("0", "关"), ("1", "轻度"), ("2", "较强")], stretch=False
        )
        self.img_ai_denoise.set_value("0")
        self.img_ai_denoise.changed.connect(lambda _k: self._refresh_img())
        self.img_ai_sharpen = ChipGroup(
            [("0", "关"), ("1", "轻度"), ("2", "较强")], stretch=False
        )
        self.img_ai_sharpen.set_value("1")
        self.img_ai_sharpen.changed.connect(lambda _k: self._refresh_img())

        panel.add("倍率", self.img_ai_scale)
        panel.add("模型", self.img_ai_model)
        panel.add("格式", self.img_ai_fmt)
        panel.add("画质", self._img_ai_quality_row())

        self.img_ai_info = panel.note
        panel.set_note("超分引擎就绪后可批量放大")
        return panel

    def _img_ai_quality_row(self) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        for text, widget in (
            ("降噪", self.img_ai_denoise),
            ("锐化", self.img_ai_sharpen),
        ):
            tag = QLabel(text)
            tag.setObjectName("optlabel")
            tag.setFixedWidth(26)
            row.addWidget(tag)
            row.addWidget(widget, 1)
            row.addSpacing(6)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    # ------------------------------------------------------------ 图片参数收集
    def _img_side_value(self) -> int:
        key = self.img_side_chips.value() or "0"
        if key != "0":
            return int(key)
        txt = self.img_side_input.text().strip()
        if txt.isdigit():
            return max(16, min(20000, int(txt)))
        return 0

    def _collect_img(self) -> ImageSettings:
        """按当前页签收集图片参数。

        两个页签共用 ImageSettings 这个结构，但只用各自那部分字段 ——
        压缩页不碰模型，超分页不碰质量，省得一边的默认值污染另一边。
        """
        if self.img_tab == 0:
            strip = (self.img_meta_chips.value() or "keep") == "strip"
            return ImageSettings(
                fmt=self.img_fmt_chips.value() or "keep",
                quality=self.img_quality_slider.value(),
                max_side=self._img_side_value(),
                strip_meta=strip,
                scale=0,
                output_dir=self.out_dir.text().strip(),
            )
        return ImageSettings(
            fmt=self.img_ai_fmt.value() or "keep",
            quality=92,
            max_side=0,
            strip_meta=False,
            scale=int(self.img_ai_scale.value() or "0"),
            model=self.img_ai_model.value() or DEFAULT_MODEL,
            denoise=int(self.img_ai_denoise.value() or "0"),
            sharpen=int(self.img_ai_sharpen.value() or "0"),
            output_dir=self.out_dir.text().strip(),
        )

    # ------------------------------------------------------------ 图片队列
    def _pick_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.avif);;所有文件 (*.*)",
        )
        if files:
            self._img_add_paths([Path(f) for f in files])

    def _img_add_paths(self, paths: list[Path]) -> None:
        added: list[Path] = []
        for p in paths:
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
                continue
            if p in self.img_files:
                continue
            self.img_files.append(p)
            self.img_states[p] = RowState()
            added.append(p)
        if not added:
            return
        self._img_rebuild()
        if self.img_table.currentRow() < 0:
            self.img_table.setCurrentCell(0, 0)

        def work() -> None:
            for p in added:
                self.img_cache[str(p)] = probe_image(p)
                self.emitter.img_meta_ready.emit(p)

        threading.Thread(target=work, daemon=True).start()

    def _img_state(self, path: Path) -> RowState:
        st = self.img_states.get(path)
        if st is None:
            st = RowState()
            self.img_states[path] = st
        return st

    def _img_index_of(self, path: Path) -> int:
        try:
            return self.img_files.index(path)
        except ValueError:
            return -1

    def _img_row_texts(self, path: Path) -> tuple[str, str, str, str]:
        info = self.img_cache.get(str(path))
        if info is None:
            return "读取中…", "—", "—", "—"
        if not info.ok:
            return "—", "—", human_size(info.size), "—"
        s = self._collect_img()
        # 这一列只有 200px，放「尺寸 · 格式」刚好；plan_summary 那串带
        # 「4× 推理」的完整说明留给面板，塞进表格会被中间省略成
        # 「2560×14…理 · JPG」，反而看不出输出多大
        from app.core.image import estimate_output_bytes, out_format, target_size

        factor = max(2, s.scale) if s.has_ai else 1
        w, h = target_size(info, s, factor)
        out = f"{w}×{h} · {out_format(info, s).upper()}" if w and h else "—"
        est = human_size(estimate_output_bytes(info, s, factor))
        return f"{info.resolution_text} · {info.fmt_text}", out, human_size(info.size), est

    def _img_paint_row(self, path: Path) -> None:
        idx = self._img_index_of(path)
        if not (0 <= idx < len(self.img_rows)):
            return
        src, out, ssize, est = self._img_row_texts(path)
        self.img_table.render(
            self.img_rows[idx],
            self._img_state(path),
            src=src,
            out=out,
            src_size=ssize,
            est=est,
        )

    def _img_refresh_rows(self) -> None:
        """参数一变，全表重算输出规格与预估体积。"""
        for path in self.img_files:
            self._img_paint_row(path)
        self._refresh_img()

    def _img_rebuild(self) -> None:
        cur = self.img_table.currentRow()
        self.img_rows = self.img_table.rebuild(self.img_files)
        for i, path in enumerate(self.img_files):
            src, out, ssize, est = self._img_row_texts(path)
            self.img_table.render(
                self.img_rows[i],
                self._img_state(path),
                src=src,
                out=out,
                src_size=ssize,
                est=est,
            )
            acts = self.img_rows[i].actions
            acts.lock_clicked.connect(self._img_on_lock)
            acts.retry_clicked.connect(self._img_on_retry)
            acts.delete_clicked.connect(self._img_on_delete)
        if self.img_files:
            self.img_table.setCurrentCell(min(max(cur, 0), len(self.img_files) - 1), 0)
        self._img_refresh_count()
        self._img_on_selection()

    def _on_img_meta(self, path: object) -> None:
        key = Path(str(path))
        info = self.img_cache.get(str(key))
        st = self._img_state(key)
        if info is None or not info.ok:
            st.phase = "failed"
            st.status = "无法读取"
            st.tip = (info.error if info else "") or "读取失败"
        else:
            st.tip = ""
        self._img_paint_row(key)
        self._refresh_img()

    def _img_refresh_count(self) -> None:
        n = len(self.img_files)
        if not n:
            self.img_count.setText("图片队列 · 空")
            return
        locked = sum(1 for p in self.img_files if self._img_state(p).locked)
        done = sum(1 for p in self.img_files if self._img_state(p).phase == "done")
        parts = [f"{n} 张"]
        if locked:
            parts.append(f"锁定 {locked}")
        if done:
            parts.append(f"完成 {done}")
        self.img_count.setText("图片队列 · " + " · ".join(parts))

    def _img_clear(self) -> None:
        if self._busy():
            return
        self.img_files.clear()
        self.img_states.clear()
        self.img_cache.clear()
        self._img_rebuild()

    def _img_on_lock(self, path: object) -> None:
        st = self._img_state(Path(str(path)))
        st.locked = not st.locked
        self._img_paint_row(Path(str(path)))
        self._img_refresh_count()

    def _img_on_retry(self, path: object) -> None:
        key = Path(str(path))
        st = self._img_state(key)
        st.phase = "ready"
        st.locked = False
        st.status = ""
        st.tip = ""
        self._img_paint_row(key)
        self._img_refresh_count()

    def _img_on_delete(self, path: object) -> None:
        key = Path(str(path))
        if self._busy() and self._img_index >= 0 and (
            self._img_index < len(self._img_batch) and self._img_batch[self._img_index] == key
        ):
            self.stats_label.setText("正在处理的图片不能删除")
            return
        idx = self._img_index_of(key)
        if idx < 0:
            return
        self.img_files.pop(idx)
        self.img_states.pop(key, None)
        self.img_cache.pop(str(key), None)
        self._img_rebuild()

    def _img_on_reorder(self, src: int, dst: int) -> None:
        if not (0 <= src < len(self.img_files) and 0 <= dst < len(self.img_files)):
            return
        if src == dst:
            return
        item = self.img_files.pop(src)
        self.img_files.insert(dst, item)
        self._img_rebuild()

    def _img_on_selection(self) -> None:
        rows = self._img_selected_rows()
        self.img_btn_retry.setEnabled(bool(rows) and not self._busy())
        self.img_btn_del.setEnabled(bool(rows) and not self._busy())
        self._refresh_img()

    def _img_selected_rows(self) -> list[int]:
        sm = self.img_table.selectionModel()
        if sm is None:
            return []
        return sorted({i.row() for i in sm.selectedRows()})

    def _img_retry_selected(self) -> None:
        for i in self._img_selected_rows():
            if i < len(self.img_files):
                self._img_on_retry(self.img_files[i])

    def _img_delete_selected(self) -> None:
        for i in sorted(self._img_selected_rows(), reverse=True):
            if i < len(self.img_files):
                self._img_on_delete(self.img_files[i])

    def _img_current(self) -> ImageInfo | None:
        rows = self._img_selected_rows()
        if rows:
            i = rows[0]
        else:
            i = self.img_table.currentRow()
        if not (0 <= i < len(self.img_files)):
            return None
        return self.img_cache.get(str(self.img_files[i]))

    # ------------------------------------------------------------ 图片说明行
    def _refresh_img(self) -> None:
        """重算图片面板底部的输出规格与开销。"""
        if not hasattr(self, "img_cost_info"):
            return
        s = self._collect_img()
        info = self._img_current()
        n = len(self.img_files)

        if not info or not info.ok:
            self.img_cost_info.setText(
                "选择图片后显示输出规格" if not n else "读取中…"
            )
            self.img_ai_info.setText("超分引擎就绪后可批量放大")
            return

        spec, cost = plan_summary(info, s)
        warn = warnings_for(info, s)
        # 台数提示放在最前面：用户最想知道「这批要跑多久」
        head = f"共 {n} 张　" if n > 1 else ""
        line = f"{head}{spec} · {cost}"
        if warn:
            line += "\n⚠ " + warn[0]
        # 两个页签各有自己的说明行，另一页留空 —— 它当前不参与处理，
        # 摆一行数字只会让人以为那个设置也生效了
        if self.img_tab == 0:
            self.img_cost_info.setText(line)
            self.img_ai_info.setText("")
        else:
            eng = self.engines.get("esrgan")
            status = "就绪" if eng and eng.ok else "缺失"
            models = f" · {len(eng.models)} 个模型" if eng and eng.ok else ""
            self.img_ai_info.setText(line + f"\n超分引擎 {status}{models}")
            self.img_cost_info.setText("")

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
            self.ai_enc_chips.set_available(e.key, e.available, e.reason)
        if not any(e.available for e in info.encoders):
            self.btn_start.setEnabled(False)
        # AI 引擎缺失不算环境错误：普通压制照样能用，只把增强页标出来
        self.engines = detect_engines()
        self._refresh_ai()
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
        pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
        vids = [p for p in paths if p.suffix.lower() in VIDEO_EXT]
        imgs = [p for p in paths if p.suffix.lower() in IMAGE_EXT]

        # 在 PDF 工作台里拖进来的一律进 PDF 队列 —— 用户已经站在这个页面
        # 上，把图片塞进图片工作台等于让他自己再找一遍
        if self._page == 2:
            if pdfs or imgs:
                self._pdf_add_paths(pdfs + imgs)
            return

        if vids:
            self._add_paths(vids)
        if imgs:
            self._img_add_paths(imgs)
        # PDF 落在别的页：自动切到 PDF 工作台，手不用离开鼠标
        if pdfs:
            self._pdf_add_paths(pdfs)
            self._set_mode(2)
            return
        # 拖进来的是图片就自动切到图片工作台（反之亦然）。用户既然把图片
        # 拖进来了，他想看的就是图片队列 —— 再让他自己点一下是多余的。
        if imgs and not vids and self._page == 0:
            self._set_mode(1)
        elif vids and not imgs and self._page == 1:
            self._set_mode(0)

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

        结论跟着当前页签走：压缩页按缩放算，AI 页按超分倍率算。以前这里恒用
        压缩参数，于是 AI 页上那一列报的是「压到 720p 之后」的体积 —— 和用户
        正在配的超分结果完全无关，看上去就是估算不准。
        """
        info = self.media_cache.get(str(path))
        if info is None:
            return "读取中…", "—", "—", "—"
        if not info.ok:
            return "—", "—", human_size(info.size), "—"

        if self._tab == 1:
            ai = self._collect_ai()
            w, h = output_size(info, ai)
            fps = (info.fps or 0) * (ai.interp if ai.has_interp else 1)
            out = (
                f"{w}×{h} · {fps:.0f}fps · {info.duration_text}"
                if w and h
                else "—"
            )
            # 超分和补帧都关着的时候不会产出任何东西，报个体积反而像在骗人
            est = (
                human_size(estimate_ai_bytes(info, ai))
                if (ai.has_upscale or ai.has_interp)
                else "—"
            )
            return info.spec_text, out, human_size(info.size), est

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
        self._refresh_scale_preview()
        self._refresh_ai()

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
        if self._busy():
            return
        self.files.clear()
        self.states.clear()
        self.media_cache.clear()
        self._rebuild_list()
        self._refresh_scale_preview()

    # ------------------------------------------------------------ 行操作
    def _on_lock(self, path: object) -> None:
        st = self._state(Path(str(path)))
        st.locked = not st.locked
        self._repaint_row(Path(str(path)))

    def _on_retry(self, path: object) -> None:
        key = Path(str(path))
        if self._busy() and 0 <= self._index < len(self.files) and self.files[self._index] == key:
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
        if self._busy() and 0 <= self._index < len(self.files) and self.files[self._index] == key:
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
        if self._busy():
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
        self._refresh_ai()
        has_sel = bool(self._selected_rows())
        idle = not self._busy()
        self.btn_retry_sel.setEnabled(has_sel and idle)
        self.btn_del_sel.setEnabled(has_sel and idle)
        m = self._current_media()
        if m and m.ok:
            self._refresh_scale_preview()

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
        if not self._busy():
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
        """面板底部那一行：输出尺寸 + 音轨摘要。

        原来这两条分别占一张卡的一行，现在合并成一行 —— 卡片没了，
        信息一条都不能少。
        """
        if not hasattr(self, "compress_panel"):
            return
        m = self._current_media()
        if not m or not m.ok:
            self.compress_panel.note.setText("选择文件后显示输出规格")
            return
        s = EncodeSettings(**self._scale_params())
        w, h = compute_target(m, s)
        if w and h:
            ratio = w / m.width * 100 if m.width else 100
            pct = "" if abs(ratio - 100) < 0.5 else f"，{ratio:.0f}%"
            head = f"输出 {w}×{h}（源 {m.width}×{m.height}{pct}）"
        else:
            head = "输出 原尺寸"
        self.compress_panel.note.setText(f"{head} · {m.audio_summary}")

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

    def _collect_ai(self) -> AiSettings:
        return AiSettings(
            scale=int(self.ai_scale_chips.value() or "0"),
            model=self.ai_model_chips.value() or DEFAULT_MODEL,
            interp=int(self.ai_interp_chips.value() or "1"),
            encoder=self.ai_enc_chips.value() or "hevc",
            crf=18,
            denoise=int(self.ai_denoise_chips.value() or "0"),
            sharpen=int(self.ai_sharpen_chips.value() or "0"),
            container="mp4",
            output_dir=self.out_dir.text().strip(),
        )

    # ------------------------------------------------------------ AI 面板
    def _on_tab_changed(self, idx: int) -> None:
        self._tab = idx
        self._update_start_text()
        # 音轨工具只属于视频压缩页，AI 页看着它们出现会很困惑
        for btn in (self.btn_extract, self.btn_strip):
            btn.setVisible(idx == 0)
        # 队列的「导出格式 / 预计导出大小」两列按页签换口径，切页要重画
        self._refresh_rows()
        self._refresh_ai()
        self._sync_tray()

    def _refresh_ai(self) -> None:
        """重算 AI 页的输出规格、推荐档位与代价。

        输出尺寸只有一个来源 —— 源尺寸 × 倍率 —— 所以这里不做仲裁，只负责
        「翻译」：告诉用户这一档会得到多大、大约要等多久、要占多少临时空间。
        动手之前的三个疑问（结果多大、要多久、会不会把盘写满）都在这里回答完。
        """
        if not hasattr(self, "ai_engine_info"):
            return
        s = self._collect_ai()
        # AI 参数一变，队列里的「导出格式」和「预计导出大小」也得跟着重算
        if self._tab == 1:
            for path in self.files:
                self._paint_row(path)
        vram = (self.env.vram_mb if self.env else 0) or 0
        profile = vram_profile(vram)

        up = self.engines.get("esrgan")
        rife = self.engines.get("rife")
        eng: list[str] = []
        if up is not None:
            eng.append(
                f"超分 {'就绪·' + str(len(up.models)) + '模型' if up.ok else '缺失'}"
            )
        if rife is not None:
            eng.append(f"补帧 {'就绪' if rife.ok else '缺失'}")
        if vram:
            eng.append(f"显存 {vram} MB（{profile.tier}档）")
        head = " · ".join(eng) if eng else "引擎检测中…"

        m = self._current_media()
        if not m or not m.ok:
            self._update_scale_tips(None, profile)
            self.ai_engine_info.setText(f"{head}\n选择文件后显示输出规格与推荐档位")
            self.ai_alert.setText("")
            self.ai_alert.hide()
            return

        self._update_scale_tips(m, profile)
        rec, why = recommend_scale(m, profile)

        # 第二行：推荐哪一档 + 当前设置的实际结果
        if not (s.has_upscale or s.has_interp):
            self.ai_engine_info.setText(f"{head}\n超分与补帧均已关闭")
            self.ai_alert.setText("")
            self.ai_alert.hide()
            return

        tw, th = output_size(m, s)
        inf = infer_scale(s)
        fps = m.fps * (s.interp if s.has_interp else 1)
        bits: list[str] = []
        if s.has_upscale:
            bit = f"{tw}×{th}"
            # 推理倍率高于输出倍率时要说清是超采样，否则用户会以为设置没生效
            if inf > s.scale:
                bit += f"（{inf}× 推理后降采样）"
            bits.append(bit)
        else:
            bits.append(f"{tw}×{th} 原尺寸")
        bits.append(f"{fps:.0f}fps")
        secs = estimate_seconds(m, s, inf)
        if secs > 0:
            bits.append(_dur_text(secs))
        rec_txt = f"推荐 {rec}×（{why}）" if rec else f"推荐关闭（{why}）"
        # 选了比推荐更高的一档时，把代价直接写在后面 —— 用户点完就看见
        if s.has_upscale and rec and s.scale > rec:
            rec_txt += " · 高于推荐档，更慢更占空间"
        self.ai_engine_info.setText(f"{head}\n{rec_txt} · 当前 {' · '.join(bits)}")

        # 警示行：临时空间 —— 这一条比耗时更危险，盘写满会把整台机器拖死
        need = estimate_temp_bytes(m, s, inf, (tw, th))
        self._show_temp_alert(m, s, need, plan_warnings(m, s, profile))

    def _show_temp_alert(
        self, m: MediaInfo, s: AiSettings, need: int, warns: list[str]
    ) -> None:
        """把临时空间占用和硬性风险摆到明面上，并说清它落在哪个盘。

        临时目录优先建在输出目录所在的盘（用户通常已经在那儿腾过空间），
        所以「别把输出放在系统盘」是有实际意义的建议，不是套话。
        """
        need_mb = need / 1048576
        # 解析成绝对路径再取盘符：相对路径拿不到 drive，会印出一串目录名
        root = Path(s.output_dir) if s.output_dir else Path(m.path).parent
        root = root.resolve()
        drive = (root.drive or str(root)) + "\\"
        free = free_space_mb(root) if root.exists() else 0
        lines: list[str] = []

        if need_mb:
            if free and need_mb > free:
                lines.append(
                    f"⚠ 临时文件约 {need_mb / 1024:.1f} GB，但 {drive} 只剩 "
                    f"{free / 1024:.1f} GB —— 空间不足，请换一个输出目录"
                )
            else:
                tail = f"（该盘剩余 {free / 1024:.0f} GB）" if free else ""
                lines.append(
                    f"⚠ 处理过程会在 {drive} 产生约 {need_mb / 1024:.1f} GB "
                    f"临时文件{tail}，做完自动删除。请确认空间够用，输出目录"
                    "尽量别放系统盘，写满会让整机卡死"
                )

        lines.extend(f"⚠ {w}" for w in warns)
        self.ai_alert.setText("\n".join(lines))
        self.ai_alert.setVisible(bool(lines))

    def _update_scale_tips(self, m: MediaInfo | None, profile) -> None:
        """给每颗倍率胶囊写一条「选了会得到什么」。

        用户点之前就该知道 4× 在 1080p 素材上是 33 MP 推理，而不是等半小时
        之后才撞上显存不足。tooltip 随素材变化，附上推荐档位。
        """
        model = self.ai_model_chips.value() or DEFAULT_MODEL
        rec = recommend_scale(m, profile, model)[0] if m and m.ok else -1
        for key in ("0", "2", "3", "4"):
            btn = self.ai_scale_chips.button(key)
            if not btn:
                continue
            k = int(key)
            if m is None or not m.ok:
                btn.setToolTip("")
                continue
            if k == 0:
                tip = "不放大，只做补帧（如果补帧也关着，就没有可做的事）"
                if rec == 0:
                    tip += "\n\n★ 当前素材推荐关闭：放大不划算"
            else:
                probe = AiSettings(scale=k, model=model)
                ow, oh = output_size(m, probe)
                # 显卡扛的是推理面积 —— photo 模型请求 2× 也是按 4× 推理
                px = infer_pixels(m, probe)
                mark = "\n\n★ 当前素材推荐这一档" if k == rec else ""
                if px > profile.max_pixels * 2:
                    fit = (
                        f"推理 {px / 1e6:.0f} MP，明显超出 {profile.tier}档显存"
                        f"建议范围，容易失败或很慢"
                    )
                else:
                    fit = f"推理 {px / 1e6:.0f} MP，{profile.tier}档显存可以应付"
                tip = f"{m.width}×{m.height} → {ow}×{oh}\n{fit}{mark}"
            btn.setToolTip(tip)

    def _pick_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.out_dir.setText(d)

    # ========================================================== 执行
    def _busy(self) -> bool:
        """压制、AI 增强、图片处理、PDF 处理共用一套「忙」判断。

        前三者都吃 GPU，同时跑只会互相拖慢并抢显存；PDF 虽然不碰显卡，
        但导出期间队列不该被改动，否则导出的内容和用户看到的不一致。
        """
        return (
            self.runner.busy()
            or self.ai_runner.busy()
            or self.img_runner.busy()
            or self.pdf_runner.busy()
        )

    def _update_start_text(self) -> None:
        """开始按钮的文案要说清「这一下会做什么」，别让用户猜。"""
        if self._page == 2:
            self.btn_start.setText("导出")
            return
        if self._page == 1:
            self.btn_start.setText("开始超分" if self.img_tab == 1 else "开始压缩")
            return
        self.btn_start.setText("开始增强" if self._tab == 1 else "开始压制")

    def _set_running(self, running: bool) -> None:
        for w in (
            self.enc_chips,
            self.mode_chips,
            self.scale_chips,
            self.audio_chips,
            self.crf_slider,
            self.br_spin,
            self.out_dir,
            self.ai_scale_chips,
            self.ai_model_chips,
            self.ai_interp_chips,
            self.ai_denoise_chips,
            self.ai_sharpen_chips,
            self.ai_enc_chips,
            self.img_fmt_chips,
            self.img_quality_slider,
            self.img_side_chips,
            self.img_side_input,
            self.img_meta_chips,
            self.img_ai_scale,
            self.img_ai_model,
            self.img_ai_fmt,
            self.img_ai_denoise,
            self.img_ai_sharpen,
            self.pdf_btn_add,
            self.pdf_btn_all,
            self.pdf_btn_del,
            self.pdf_btn_clear,
            self.pdf_btn_rotate,
            self.pdf_btn_extract,
            self.pdf_zip_enable,
            self.pdf_zip_all,
            self.pdf_zip_part,
            self.pdf_zip_run,
            self.pdf_zip_cancel,
            self.pdf_zip_quality,
        ):
            w.setEnabled(not running)
        self.btn_start.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        # 工具和压制共用执行器，跑起来时互斥
        self.btn_extract.setEnabled(not running)
        self.btn_strip.setEnabled(not running)
        self.btn_add.setEnabled(not running)
        self.img_btn_add.setEnabled(not running)
        self.btn_retry_sel.setEnabled(not running and bool(self._selected_rows()))
        self.btn_del_sel.setEnabled(not running and bool(self._selected_rows()))
        self.btn_mode_video.setEnabled(not running)
        self.btn_mode_image.setEnabled(not running)
        self.btn_mode_pdf.setEnabled(not running)
        self.img_btn_retry.setEnabled(not running and bool(self._img_selected_rows()))
        self.img_btn_del.setEnabled(not running and bool(self._img_selected_rows()))
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
        if self._page == 2:
            self._pdf_export()
            return
        if self._page == 1:
            self._start_images()
            return
        if self._tab == 1:
            self._start_ai()
            return
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
        if self.pdf_runner.busy():
            self.pdf_runner.cancel()
            self.current_label.setText("正在停止…")
        elif self.runner.busy():
            self.runner.cancel()
        elif self.ai_runner.busy():
            self.ai_runner.cancel()
        elif self.img_runner.busy():
            self.img_runner.cancel()
        elif self._page == 1:
            self._img_finish()
        elif self._mode == "ai":
            self._finish_ai()
        else:
            self._finish_all()

    # ========================================================== 图片处理
    def _on_img_tab_changed(self, idx: int) -> None:
        self.img_tab = idx
        # 压缩完的图在「超分」页里不代表处理过 —— 两个页签是两套独立的操作。
        # 不重置的话，用户压完图切过来点开始会被拦一句「都已完成」，还得自己
        # 去点「重提所选」，纯属添堵。失败的保持失败，让他看得见原因。
        for p in self.img_files:
            st = self._img_state(p)
            if st.phase == "done":
                st.phase, st.status, st.tip = "ready", "", ""
        self._update_start_text()
        # 「导出格式 / 预计导出大小」两列跟着页签变（压缩页看格式和长边，
        # 超分页看倍率和模型），必须整表重算，不能只刷新面板说明
        self._img_refresh_rows()
        self._img_refresh_count()

    def _img_tmp_path(self, out: Path) -> Path:
        """超分中间图放在输出文件旁边。

        不放系统临时目录：输出到机械盘/网络盘时，跨盘复制一个 20 MB 的 PNG
        比重新算一遍还慢。放同目录，用完立刻删。
        """
        return out.with_name(out.stem + ".zzbox_up.png")

    def _start_images(self) -> None:
        if self._busy():
            return
        if not self.img_files:
            QMessageBox.information(
                self, "没有图片", "先把图片拖进来，或点右上角“+”添加图片。"
            )
            return
        if not self.env or not self.env.ffmpeg:
            QMessageBox.warning(
                self, "缺少 FFmpeg", "找不到 bin/ffmpeg.exe，无法编码图片。"
            )
            return

        s = self._collect_img()
        if self.img_tab == 1:
            if not s.has_ai:
                QMessageBox.information(
                    self,
                    "没有启用超分",
                    "「倍率」是关闭状态，没有要处理的内容。\n至少选一个倍率再点开始。",
                )
                return
            eng = self.engines.get("esrgan")
            if not (eng and eng.ok):
                QMessageBox.warning(
                    self,
                    "缺少超分引擎",
                    "没有找到 realesrgan-ncnn-vulkan.exe。\n\n"
                    "把它解压到这个目录下即可：\n"
                    + str(ai_dir())
                    + "\n\n目录结构：\n"
                    "  bin/ai/realesrgan-ncnn-vulkan.exe\n"
                    "  bin/ai/models/\n\n"
                    "引擎是 Vulkan 版，不需要装 CUDA 或 Python。",
                )
                return

        batch = [
            p
            for p in self.img_files
            if not self._img_state(p).locked and self._img_state(p).phase == "ready"
        ]
        if not batch:
            QMessageBox.information(
                self,
                "没有可处理的图片",
                "所有图片都已完成或被锁定。\n"
                "点行尾的「重提」可以把它们重新放回队列。",
            )
            return

        for p in batch:
            st = self._img_state(p)
            st.phase, st.status, st.tip = "ready", "", ""
        self._img_batch = batch
        self._img_index = 0
        self._img_ok = 0
        self._img_fail = 0
        self._img_t0 = time.time()
        self._stopping = False
        self._set_running(True)
        self._set_progress(0)
        self._img_refresh_count()
        self._img_run_next()

    def _img_run_next(self) -> None:
        """取下一张图，构造命令链丢给执行器。"""
        while self._img_index < len(self._img_batch):
            path = self._img_batch[self._img_index]
            st = self._img_state(path)
            if st.locked:
                self._img_index += 1
                continue

            info = self.img_cache.get(str(path)) or probe_image(path)
            self.img_cache[str(path)] = info
            if not info.ok:
                st.phase, st.status, st.tip = "failed", "无法读取", info.error
                self._img_fail += 1
                self._img_paint_row(path)
                self._img_index += 1
                continue

            s = self._collect_img()
            out_hint = ""
            if s.has_ai:
                eng = self.engines.get("esrgan")
                # 中间文件路径要提前算出来：build_ai_steps 需要它，
                # 取消/失败时也要靠它删掉残留
                probe_out = self._img_preview_output(path, s, info)
                tmp = self._img_tmp_path(probe_out)
                steps, out, err = build_ai_steps(
                    self.env.ffmpeg,
                    eng.exe if eng else "",
                    str(Path(eng.exe).parent / "models") if eng and eng.exe else "",
                    path,
                    s,
                    info,
                    tmp,
                )
                cleanups = [tmp]
            else:
                steps, out, err = build_compress_steps(
                    self.env.ffmpeg, path, s, info
                )
                cleanups = []

            if err or not steps:
                st.phase, st.status, st.tip = "failed", "参数有误", err or "无法构造命令"
                self._img_fail += 1
                self._img_paint_row(path)
                self._img_index += 1
                continue

            st.phase = "running"
            st.status = "处理中 0%"
            self.current_label.setText(f"正在处理　{path.name}")
            self._img_paint_row(path)
            self.img_runner.start(steps, cleanups)
            return

        self._img_finish()

    def _img_preview_output(self, path: Path, s: ImageSettings, info: ImageInfo) -> Path:
        """算出这张图的输出路径，只为了给中间文件找个同目录的落点。

        真正的输出路径由 build_ai_steps 内部再算一遍（它还要处理重名），
        这里不追求完全一致，只要落在同一个目录即可。
        """
        from app.core.image import make_output_path

        return make_output_path(path, s, info, None, ai=True)

    def _on_img_progress(self, pct: int) -> None:
        total = max(1, len(self._img_batch))
        self._set_progress(int((self._img_index + pct / 100) / total * 100))
        if 0 <= self._img_index < len(self._img_batch):
            path = self._img_batch[self._img_index]
            st = self._img_state(path)
            if st.phase == "running":
                st.status = f"处理中 {pct}%"
                self._img_paint_row(path)

    def _on_img_finished(self, ok: bool, msg: str) -> None:
        if self._stopping:
            self._img_finish()
            return
        if not (0 <= self._img_index < len(self._img_batch)):
            self._img_finish()
            return
        path = self._img_batch[self._img_index]
        st = self._img_state(path)
        if ok:
            st.phase, st.status, st.tip = "done", "已完成", ""
            self._img_ok += 1
        else:
            st.phase, st.status, st.tip = "failed", "失败", msg
            self._img_fail += 1
        self._img_paint_row(path)
        self._img_index += 1
        self._img_run_next()

    def _img_finish(self) -> None:
        secs = time.time() - self._img_t0 if self._img_t0 else 0.0
        self._stopping = False
        self._img_batch = []
        self._img_index = 0
        self._set_running(False)
        self._img_refresh_count()
        if self._img_ok or self._img_fail:
            tail = f" · 失败 {self._img_fail}" if self._img_fail else ""
            self.current_label.setText(f"完成 {self._img_ok} 张{tail}")
            # 压缩一张图往往不到 1 秒，写「用时 0 秒」看着像没干活
            self.stats_label.setText(
                "用时 <1 秒" if secs < 1 else f"用时 {secs:.0f} 秒"
            )
        else:
            self.current_label.setText("就绪")
            self.stats_label.setText("")
        self._sync_tray()

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
        if self._busy():
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

    # ========================================================== AI 增强
    # 一条任务 = 拆帧 → 超分 → 补帧 → 合成 四个子进程，逐文件串行。
    # 临时帧序列走磁盘（引擎只认图片目录），所以开始前必须先把空间算清楚：
    # 一个 3 分钟的 720p 片段超分 2× 就要吃掉好几个 GB。
    _ai_stage_name = ""

    def _start_ai(self) -> None:
        if not self.files:
            QMessageBox.information(
                self, "没有文件", "先把视频拖进来，或点右上角“+”添加文件。"
            )
            return
        if not self.env or not self.env.ffmpeg:
            return

        s = self._collect_ai()
        if not (s.has_upscale or s.has_interp):
            QMessageBox.information(
                self,
                "没有启用增强",
                "「超分」和「补帧」都关着，没东西可做。\n至少打开一个再点开始。",
            )
            return

        missing: list[str] = []
        up = self.engines.get("esrgan")
        rife = self.engines.get("rife")
        if s.has_upscale and not (up and up.ok):
            missing.append("超分引擎 realesrgan-ncnn-vulkan.exe")
        if s.has_interp and not (rife and rife.ok):
            missing.append("补帧引擎 rife-ncnn-vulkan.exe")
        if missing:
            QMessageBox.warning(
                self,
                "缺少 AI 引擎",
                "以下组件没有找到：\n  "
                + "\n  ".join(missing)
                + "\n\n把它们解压到这个目录下即可：\n"
                + str(ai_dir())
                + "\n\n目录结构：\n"
                "  bin/ai/realesrgan-ncnn-vulkan.exe\n"
                "  bin/ai/models/\n"
                "  bin/ai/rife-ncnn-vulkan.exe\n"
                "  bin/ai/rife/models/\n\n"
                "引擎是 Vulkan 版，不需要装 CUDA 或 Python。",
            )
            return

        pending = [
            p
            for p in self.files
            if not self._state(p).locked and self._state(p).phase == "ready"
        ]
        if not pending:
            QMessageBox.information(
                self, "没有可处理的文件", "所有项目都已完成或被锁定。"
            )
            return

        # 先把所有待处理文件读一遍，算出临时空间的峰值需求
        pairs: list[tuple[Path, MediaInfo]] = []
        worst = 0
        for path in pending:
            info = self.media_cache.get(str(path)) or probe_media(path)
            self.media_cache[str(path)] = info
            if not info.ok:
                st = self._state(path)
                st.phase, st.status, st.tip = "failed", "无法读取", info.error
                self._repaint_row(path)
                self._ai_fail += 1
                continue
            pairs.append((path, info))
            # 必须按推理倍率算：photo 模型请求 2× 也是 4× 推理，中间产物是
            # 4 倍尺寸的 PNG。按输出倍率估会低估好几倍，然后写到一半盘满。
            worst = max(
                worst,
                estimate_temp_bytes(info, s, infer_scale(s), output_size(info, s)),
            )
        if not pairs:
            return

        need_mb = int(worst / 1048576 * 1.05) + 256
        # 候选盘：输出目录（用户往往已在那个盘腾了空间）→ 系统临时目录
        cands: list[Path] = []
        if s.output_dir:
            cands.append(Path(s.output_dir))
        else:
            cands.append(pairs[0][0].parent)
        cands.append(Path(tempfile.gettempdir()))
        root_dir = next((c for c in cands if free_space_mb(c) >= need_mb), None)
        if root_dir is None:
            have = max(free_space_mb(c) for c in cands)
            QMessageBox.warning(
                self,
                "磁盘空间不足",
                f"这次增强需要约 {human_size(worst)} 临时空间，\n"
                f"输出目录与系统临时盘最多只剩 {human_size(have * 1048576)}。\n\n"
                "换一个空间充裕的输出目录，或先处理短一点的片段。\n"
                "临时文件会落在输出目录所在的磁盘，尽量不要放在系统盘。",
            )
            return

        # 上一次可能留了没删干净的帧序列，先扫掉（2 小时内的不动，避免误删并行任务）
        freed = sweep_stale(root_dir)
        if freed:
            self.stats_label.setText(f"已清理 {freed} 个残留临时目录")

        try:
            root = Path(tempfile.mkdtemp(prefix="zzbox_ai_", dir=str(root_dir)))
        except OSError as exc:
            QMessageBox.warning(self, "无法创建临时目录", f"{root_dir}\n{exc}")
            return

        jobs: list[dict] = []
        vram = self.env.vram_mb or 0
        for i, (path, info) in enumerate(pairs):
            plan = build_plan(
                info,
                s,
                self.engines,
                self.env.ffmpeg,
                root / f"{i:02d}",
                vram_mb=vram,
            )
            if plan.error:
                st = self._state(path)
                st.phase, st.status, st.tip = "failed", "无法规划", plan.error
                self._repaint_row(path)
                continue
            jobs.append({"path": path, "plan": plan})

        if not jobs:
            cleanup(str(root))
            return

        if len(jobs) > 1:
            ret = QMessageBox.question(
                self,
                "AI 增强",
                f"将处理 {len(jobs)} 个文件。\n"
                f"临时帧序列峰值约 {human_size(worst)}（放在 {root_dir}）\n\n"
                "AI 增强是用算力换画质：1 分钟 720p 片段可能需要几分钟到几十分钟。\n"
                "处理期间请勿关闭程序或拔掉硬盘。\n\n继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ret != QMessageBox.Yes:
                cleanup(str(root))
                return

        self._ai_root = root
        self._ai_jobs = jobs
        self._ai_ok = 0
        self._ai_fail = 0
        self._index = -1
        self._stopping = False
        self._mode = "ai"
        self.ai_settings = s
        self._set_running(True)
        self._set_progress(0)
        self._ai_stage_name = ""
        self.stats_label.setText("准备中…")
        self._run_ai_next()

    def _run_ai_next(self) -> None:
        if self._stopping or not self._ai_jobs:
            self._finish_ai()
            return
        job = self._ai_jobs.pop(0)
        self._ai_cur = job
        path: Path = job["path"]
        idx = self._row_index(path)
        self._index = idx if idx >= 0 else -1
        st = self._state(path)
        st.phase = "running"
        st.status = "AI 增强 0%"
        st.tip = ""
        if idx >= 0:
            self._repaint_row(path)
        self.current_label.setText(path.name)
        self.current_label.setToolTip(str(path))
        self._set_progress(0)
        self.ai_runner.start(job["plan"])

    def _on_ai_stage(self, index: int, label: str) -> None:
        self._ai_stage_name = label
        if 0 <= self._index < len(self.files):
            st = self._state(self.files[self._index])
            st.status = f"{label}…"
            self._repaint_row(self.files[self._index])
        self.stats_label.setText(f"{label}…")
        self._sync_tray()

    def _on_ai_progress(self, pct: int) -> None:
        self._set_progress(pct)
        stage = self._ai_stage_name or "AI 增强"
        self.stats_label.setText(f"{stage} · {pct}%")
        if 0 <= self._index < len(self.files):
            st = self._state(self.files[self._index])
            st.status = f"{stage} {pct}%"
            self._repaint_row(self.files[self._index])
        self._sync_tray()

    def _on_ai_finished(self, ok: bool, msg: str) -> None:
        job = self._ai_cur
        self._ai_cur = None
        if job:
            path: Path = job["path"]
            plan = job["plan"]
            st = self._state(path)
            if self._stopping:
                st.phase, st.status, st.tip = "failed", "已停止", "手动停止"
                self._ai_fail += 1
            elif ok:
                st.phase = "done"
                st.status = "已增强"
                st.tip = f"输出：{plan.output}"
                self._ai_ok += 1
            else:
                st.phase, st.status, st.tip = "failed", "失败", msg
                self._ai_fail += 1
            self._repaint_row(path)
            # 单个文件处理完立刻清掉它的帧序列，别把几个 GB 堆到整批结束
            cleanup(plan.temp_dir)

        if self._stopping:
            self._finish_ai()
            return
        QTimer.singleShot(30, self._run_ai_next)

    def _finish_ai(self) -> None:
        self._mode = "encode"
        leftover = ""
        if self._ai_root is not None:
            gone = cleanup(str(self._ai_root))
            if not gone:
                # 删不掉就说清楚在哪，别让用户白白丢几百 MB；
                # 同时排一次延迟重试 —— 句柄刚释放的那一刻往往就能删了
                leftover = f"　临时文件未删净：{self._ai_root}"
                QTimer.singleShot(8000, lambda p=str(self._ai_root): cleanup(p))
            self._ai_root = None
        self._ai_jobs = []
        self._set_running(False)
        if self._stopping:
            self.stats_label.setText("已停止" + leftover)
            self.current_label.setText("已手动停止")
        else:
            if self._ai_fail == 0:
                self._set_progress(100)
            self.stats_label.setText(
                f"增强 {self._ai_ok} · 失败 {self._ai_fail}" + leftover
            )
            self.current_label.setText(
                "全部完成" if not self._ai_fail else "存在失败任务"
            )
            if not self.isVisible() and self.tray:
                self.tray.notify(
                    "AI 增强完成" if not self._ai_fail else "任务结束",
                    f"成功 {self._ai_ok} · 失败 {self._ai_fail}",
                )
        self._stopping = False
        self._refresh_count()
