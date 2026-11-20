"""AE 式「导出保存」对话框。

上方选路径、下方输文件名、再选保存类型 —— 和 After Effects / 媒体编码器
的导出排版一致。底部「保存至子文件夹」勾上后，文件落进所选目录下新建的
`ZZbox output.年.月.日.时.分` 文件夹；不勾就直接输出到所选目录。

三个工作台共用一个对话框，只是「保存类型」下拉的内容不同：
  · 视频 → mp4 / mkv / mov
  · 图片 → png / jpg / webp / PDF（全部合成一个）
  · PDF  → 合并为 1 个 / 按来源分别导出 / 每页一张 PNG / 每页一张 JPG
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.ui import style

# 各工作台的保存类型下拉：(key, 显示文字)
EXPORT_FORMATS: dict[str, list[tuple[str, str]]] = {
    "video": [
        ("mp4", "MP4 视频 (*.mp4)"),
        ("mkv", "MKV 视频 (*.mkv)"),
        ("mov", "MOV 视频 (*.mov)"),
    ],
    "image": [
        ("png", "PNG 图片 (*.png)"),
        ("jpg", "JPG 图片 (*.jpg)"),
        ("webp", "WebP 图片 (*.webp)"),
        ("pdf", "PDF（全部合成一个）"),
    ],
    "pdf": [
        ("pdf_one", "PDF（合并为 1 个）"),
        ("pdf_many", "PDF（按来源分别导出）"),
        ("png", "PNG 图片（每页一张）"),
        ("jpg", "JPG 图片（每页一张）"),
    ],
}

# 保存类型 key → 落盘扩展名（pdf_one/pdf_many 都是 .pdf）
FMT_EXT = {
    "mp4": ".mp4",
    "mkv": ".mkv",
    "mov": ".mov",
    "png": ".png",
    "jpg": ".jpg",
    "webp": ".webp",
    "pdf": ".pdf",
    "pdf_one": ".pdf",
    "pdf_many": ".pdf",
}

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def safe_name(text: str, fallback: str = "导出") -> str:
    """文件名去掉路径非法字符，别让一个斜杠把保存路径搞坏。"""
    text = _ILLEGAL.sub("_", (text or "").strip()).strip(". ")
    return text or fallback


@dataclass
class ExportChoice:
    """用户在对话框里确认的结果。"""

    out_dir: Path          # 最终输出目录（已应用子文件夹规则）
    filename: str          # 文件名（不含扩展名）；多文件导出时调用方忽略
    fmt: str               # 保存类型 key，见 EXPORT_FORMATS
    subdir: bool           # 是否勾了「保存至子文件夹」


class ExportDialog(QDialog):
    """一次导出的落点决策。构造后 exec()，取 chosen()。"""

    # 记住上一次的目录 / 类型 / 子文件夹开关，和 AE 一样省得每次重选
    _last_dir = ""
    _last_fmt: dict[str, str] = {}
    _last_subdir = False

    def __init__(
        self,
        parent=None,
        *,
        title: str = "导出",
        mode: str = "video",
        default_name: str = "",
        initial_dir: str = "",
        formats: list[tuple[str, str]] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self._mode = mode
        self._default_name = safe_name(default_name)
        self._choice: ExportChoice | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        # ---- 上：保存位置 ----
        lay.addWidget(self._label("保存位置"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择一个文件夹作为输出位置")
        self.dir_edit.setText(initial_dir or self._last_dir)
        row.addWidget(self.dir_edit, 1)
        browse = QPushButton("浏览…")
        browse.setFixedWidth(72)
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)

        # ---- 中：文件名 ----
        lay.addWidget(self._label("文件名"))
        self.name_edit = QLineEdit()
        self.name_edit.setText(self._default_name)
        self.name_edit.setPlaceholderText(self._default_name or "输入文件名")
        lay.addWidget(self.name_edit)

        # ---- 保存类型 ----
        lay.addWidget(self._label("保存类型"))
        self.fmt_box = QComboBox()
        # 容器列表可以按编码器裁剪：AV1 在 MOV 里根本封装不了（ffmpeg 直接报
        # "av1 only supported in MP4 and AVIF"），列出来就是给用户挖坑。
        for key, label in formats or EXPORT_FORMATS.get(mode, EXPORT_FORMATS["video"]):
            self.fmt_box.addItem(label, key)
        saved = self._last_fmt.get(mode)
        if saved:
            idx = self.fmt_box.findData(saved)
            if idx >= 0:
                self.fmt_box.setCurrentIndex(idx)
        lay.addWidget(self.fmt_box)

        # ---- 子文件夹开关 ----
        self.subdir_check = QCheckBox("保存至子文件夹（ZZbox output.年.月.日.时.分）")
        self.subdir_check.setChecked(self._last_subdir)
        # 已经站在输出子文件夹里了就别再套一层
        cur = (initial_dir or self._last_dir).rstrip("\\/")
        if cur and Path(cur).name.startswith("ZZbox output."):
            self.subdir_check.setChecked(False)
            self.subdir_check.setEnabled(False)
            self.subdir_check.setToolTip("当前目录已经是输出子文件夹，不再嵌套")
        lay.addWidget(self.subdir_check)

        # ---- 实时预览最终落点 ----
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        # ---- 按钮 ----
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        for w in (self.dir_edit, self.name_edit, self.fmt_box):
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._refresh_hint)
            else:
                w.currentIndexChanged.connect(self._refresh_hint)
        self.subdir_check.toggled.connect(self._refresh_hint)
        self._refresh_hint()

    # ------------------------------------------------------------------
    @staticmethod
    def _label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"font-size: 11px; color: {style.MUTED};")
        return lab

    def _browse(self) -> None:
        start = self.dir_edit.text().strip() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if d:
            self.dir_edit.setText(d)

    def _target_dir(self) -> Path:
        """最终目录：勾了子文件夹就在所选目录下开一个带时间戳的文件夹。"""
        base = Path(self.dir_edit.text().strip() or ".")
        if self.subdir_check.isEnabled() and self.subdir_check.isChecked():
            stamp = time.strftime("%Y.%m.%d.%H.%M")
            return base / f"ZZbox output.{stamp}"
        return base

    def _refresh_hint(self) -> None:
        key = self.fmt_box.currentData() or ""
        ext = FMT_EXT.get(key, "")
        name = safe_name(self.name_edit.text()) or self._default_name or "文件"
        n = max(1, int(getattr(self, "_file_count", 1) or 1))
        if n > 1:
            tail = f"{name}{ext} 等 {n} 个文件"
        else:
            tail = f"{name}{ext}"
        self.hint.setText(f"输出到：{self._target_dir()}\\{tail}")

    def set_file_count(self, n: int) -> None:
        """多文件导出时传进来，预览文案能写「等 N 个文件」。"""
        self._file_count = max(1, n)
        self._refresh_hint()

    def chosen(self) -> ExportChoice | None:
        return self._choice

    def _accept(self) -> None:
        raw = self.dir_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "还没选位置", "先选一个输出文件夹。")
            return
        base = Path(raw)
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            QMessageBox.warning(self, "位置无效", f"这个文件夹无法创建：\n{base}")
            return
        out = self._target_dir()
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError:
            QMessageBox.warning(self, "位置无效", f"这个文件夹无法创建：\n{out}")
            return

        fmt = self.fmt_box.currentData() or ""
        name = safe_name(self.name_edit.text()) or self._default_name or "导出"
        self._choice = ExportChoice(
            out_dir=out,
            filename=name,
            fmt=fmt,
            subdir=self.subdir_check.isEnabled() and self.subdir_check.isChecked(),
        )
        # 记住选择，下次打开默认就是它
        type(self)._last_dir = str(base)
        type(self)._last_fmt[self._mode] = fmt
        type(self)._last_subdir = self._choice.subdir
        self.accept()

    # ------------------------------------------------------------------
    @classmethod
    def get_choice(
        cls,
        parent=None,
        *,
        title: str = "导出",
        mode: str = "video",
        default_name: str = "",
        initial_dir: str = "",
        formats: list[tuple[str, str]] | None = None,
    ) -> ExportChoice | None:
        dlg = cls(
            parent,
            title=title,
            mode=mode,
            default_name=default_name,
            initial_dir=initial_dir,
            formats=formats,
        )
        if dlg.exec() == QDialog.Accepted:
            return dlg.chosen()
        return None
