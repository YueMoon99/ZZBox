"""从 assets/icon.svg 生成 icon.png（512/256）与多尺寸 icon.ico。

只依赖 PySide6（QtSvg 渲染 + QImage 存 PNG），不需要 Pillow。
ICO 用 PNG 内嵌格式（Vista 以后系统原生支持），16~256 共 10 档，
任务栏/托盘/资源管理器各取所需，不会糊。

16~24px 单独用 icon_small.svg（去掉胶片打孔、加粗笔画）：
大图靠细节认，小图靠轮廓认，两者不能共用一张图。

用法：python tools/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = ROOT / "assets"
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def render(svg: bytes, size: int) -> QImage:
    """按目标像素渲染，开抗锯齿；128 以上按 4 倍超采样再缩，边缘更干净。"""
    factor = 4 if size <= 64 else 2
    img = QImage(size * factor, size * factor, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    QSvgRenderer(QByteArray(svg)).render(p)
    p.end()
    return img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def dib_bytes(img: QImage) -> bytes:
    """把 QImage 转成 ICO 里的经典 DIB 条目（32 位 BGRA + 1 位 AND 掩码）。

    为什么不用「整包 PNG」的 ICO：Windows 的 LoadIcon 认，但打包工具在把 ICO
    转写成 exe 资源时容易只留下少数几张、还把 alpha 弄丢——exe 图标会变空白。
    DIB 是 1990 年代就在用的格式，一路通关。
    """
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()

    header = struct.pack(
        "<IiiHHIIiiII",
        40,        # biSize
        w,         # biWidth
        h * 2,     # biHeight：XOR 图 + AND 掩码各占一份
        1,         # biPlanes
        32,        # biBitCount
        0,         # biCompression = BI_RGB
        0, 0, 0, 0, 0,
    )

    rows = bytearray()
    for y in range(h - 1, -1, -1):  # DIB 自下而上
        rows += bytes(img.constScanLine(y))[: w * 4]

    # AND 掩码：Alpha 为 0 的像素置 1（老系统不支持 alpha 时靠它抠图）
    mask_stride = ((w + 31) // 32) * 4
    mask = bytearray(mask_stride * h)
    for y in range(h):
        src = bytes(img.constScanLine(h - 1 - y))
        for x in range(w):
            if src[x * 4 + 3] == 0:
                mask[y * mask_stride + x // 8] |= 0x80 >> (x % 8)

    return header + bytes(rows) + bytes(mask)


def write_ico(items: list[tuple[int, bytes]], path: Path) -> None:
    count = len(items)
    header = struct.pack("<HHH", 0, 1, count)
    dir_size = 6 + 16 * count
    offset = dir_size
    entries = b""
    body = b""
    for size, data in items:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,  # 256 用 0 表示
            size if size < 256 else 0,
            0,  # 调色板数
            0,  # 保留
            1,  # 色彩平面
            32,  # 位深
            len(data),
            offset,
        )
        body += data
        offset += len(data)
    path.write_bytes(header + entries + body)


def main() -> int:
    app = QGuiApplication([])  # noqa: F841  QSvgRenderer 需要 GUI 上下文
    svg = (ASSETS / "icon.svg").read_bytes()
    svg_small = (ASSETS / "icon_small.svg").read_bytes()

    def pick(size: int) -> bytes:
        return svg_small if size <= 24 else svg

    big = render(svg, 512)
    big.save(str(ASSETS / "icon.png"))
    render(svg, 256).save(str(ASSETS / "icon_256.png"))

    imgs = {s: render(pick(s), s) for s in SIZES}
    for size, im in imgs.items():
        # 各尺寸单独存一份 PNG：QIcon 按尺寸登记，托盘/任务栏才不会现场缩放发虚
        (ASSETS / f"icon_{size}.png").write_bytes(png_bytes(im))

    # 256 用 PNG 条目（Vista 以后的标准做法，体积小一半），其余走 DIB
    ico_items = [
        (size, png_bytes(imgs[size]) if size == 256 else dib_bytes(imgs[size]))
        for size in SIZES
    ]
    write_ico(ico_items, ASSETS / "icon.ico")

    # 预览用拼图：一排不同尺寸，方便肉眼检查小图是否糊成一团
    sheet = QImage(620, 180, QImage.Format_ARGB32)
    sheet.fill(Qt.white)
    p = QPainter(sheet)
    x = 12
    for s in (16, 20, 24, 32, 48, 64, 128):
        p.drawImage(x, (150 - s) // 2 + 8, render(pick(s), s))
        x += s + 14
    p.end()
    sheet.save(str(ROOT / "_test" / "icon_sheet.png"))

    ico = ASSETS / "icon.ico"
    print(f"icon.png     {(ASSETS / 'icon.png').stat().st_size / 1024:.1f} KB")
    print(f"icon.ico     {ico.stat().st_size / 1024:.1f} KB  ({len(ico_items)} 种尺寸)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
