"""应用图标定位与加载。

图标资源随 exe 一起打包，路径在三种场景下都不一样：
  源码运行   → 项目根/assets
  打包运行   → exe 同级/assets（PyInstaller 6 会放进 _internal）
  打包兜底   → sys._MEIPASS/assets
所以这里按优先级逐个试，谁先命中用谁。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

# 托盘/标题栏/任务栏实际会用到的像素尺寸，全部预先登记，避免 Qt 从大图现场缩放
_PIXMAP_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

_cache: QIcon | None = None


def assets_dir() -> Path:
    here = Path(__file__).resolve().parents[2]  # 源码：<项目根>
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets")
    try:
        from app.core.probe import app_root

        candidates.append(app_root() / "assets")
    except Exception:
        pass
    candidates.append(here / "assets")
    for c in candidates:
        if (c / "icon.ico").exists():
            return c
    return candidates[-1]


def app_icon() -> QIcon:
    """多尺寸 QIcon：任务栏要 32，托盘要 16/20，Alt-Tab 要 64。"""
    global _cache
    if _cache is not None:
        return _cache

    d = assets_dir()
    icon = QIcon()
    for size in _PIXMAP_SIZES:
        png = d / f"icon_{size}.png"
        if png.exists():
            icon.addFile(str(png))

    if icon.isNull():
        ico = d / "icon.ico"
        if ico.exists():
            icon = QIcon(str(ico))
    if icon.isNull():
        png = d / "icon.png"
        if png.exists():
            icon = QIcon(str(png))

    _cache = icon
    return icon


def logo_pixmap(size: int):
    """顶栏那个小标志，直接用同一份图标，视觉上保持一致。"""
    return app_icon().pixmap(size, size)
