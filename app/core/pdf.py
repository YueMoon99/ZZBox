"""PDF 页面组织：探测、渲染、无损组装、重采样压缩。

和视频/图片两条管线的根本差别在这里：它们都是「一个文件进、一个文件出」，
PDF 是「一堆页面进、按队列顺序出一个（或一批）」。所以这一层只认
PageRef —— 一个可导出的最小单元（某个 PDF 的第几页，或一张图片），
谁在第几位、缩略图长什么样、选没选中，都是界面的事。

两条完全不同的导出路径，别混着用：

  · 无损组装（提取 / 合并 / 旋转）
    用 pdfium 的 import_pages 整页搬运，页面内容流一个字节都不动 ——
    文字层、矢量、链接、表单全留着，导出的 PDF 还能搜索、还能复制。

  · 重采样（压缩）
    把每页渲染成位图再重新封装。体积能降一半以上，代价是页面变成
    一张图，文字层没了。所以界面上必须让用户知道自己在选什么。

用 pypdfium2（Apache-2.0/BSD-3）+ Pillow（MIT-CMU），不用 PyMuPDF：
后者是 AGPL，打进 MIT 项目的分发包会把整个授权传染掉。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

# PDFium 不是线程安全的：两个线程同时打开/渲染文档会直接段错误
# （不是抛异常，是进程干净利落地消失，连 traceback 都留不下）。
# 缩略图是并发生成的，导出也在后台线程跑，所以这里必须有一把全局锁
# 把所有 pdfium 调用串起来。PIL 侧的自有操作不需要它。
# 用 RLock 是因为 compress_pdf 持锁后还会调 render_page。
_PDFIUM_LOCK = threading.RLock()

# PDF 页面以 point 为单位，1pt = 1/72 英寸
PT_PER_IN = 72.0
# 图片铺进 PDF 时按这个 DPI 换算物理尺寸。96 是屏幕基准，
# 4000px 的照片会得到约 41 英寸宽的页面 —— 打印机会按纸张缩放，够用。
IMAGE_DPI = 96.0

# 缩略图渲染上限：队列里再大也只需要看清版式。320 是配合画布高度选的 ——
# 渲染得比画布小，缩放时会糊；大太多只是白占内存
THUMB_MAX_PX = 340


class PdfError(RuntimeError):
    """带上人话的 PDF 处理错误，界面直接显示 message。"""


class PdfCancelled(PdfError):
    """用户主动取消。是 PdfError 的子类，好让各处的错误包装原样放行，
    界面拿到之后按「取消」而不是「失败」来措辞。"""


# ---------------------------------------------------------------- 数据结构


@dataclass
class PdfInfo:
    """一份 PDF 的探测结果。"""

    path: str
    pages: int = 0
    sizes: list[tuple[float, float]] = field(default_factory=list)  # 每页 pt
    encrypted: bool = False
    has_text: bool = False      # 有任何一页含可选中的文字
    text_pages: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.pages > 0

    @property
    def size_text(self) -> str:
        if not self.ok:
            return "—"
        w, h = self.sizes[0]
        # A4 竖版 595×842pt，四舍五入到整点，界面里不需要小数
        return f"{round(w)}×{round(h)}pt"

    @property
    def size_label(self) -> str:
        """把首页尺寸说成人话：A4 / A3 / Letter / 自定义。"""
        if not self.ok:
            return "—"
        w, h = sorted(self.sizes[0])
        table = {
            (595, 842): "A4",
            (842, 1191): "A3",
            (420, 595): "A5",
            (612, 792): "Letter",
        }
        for (tw, th), name in table.items():
            if abs(w - tw) <= 3 and abs(h - th) <= 3:
                return name
        return f"{round(w)}×{round(h)}pt"


@dataclass
class PageRef:
    """队列里的一项：一个可独立导出、旋转、压缩的页面。

    uid 由界面维护（拖拽排序靠它找回顺序），这里不参与导出逻辑。
    """

    src: str
    kind: str = "pdf"       # pdf | image
    index: int = 0          # PDF 内的页序号，0 起；图片恒为 0
    rotate: int = 0         # 顺时针累计角度，叠加在源页自身的 /Rotate 之上


# ---------------------------------------------------------------- 探测


def probe_pdf(path: str | Path) -> PdfInfo:
    """读页数、每页尺寸、有没有文字层。

    文字层这一项只服务于压缩页的提示：有文字的 PDF 压缩后文字会变成图，
    用户得提前知道搜索和复制会失效。
    """
    src = Path(path)
    info = PdfInfo(path=str(src))
    if not src.exists():
        info.error = "文件不存在"
        return info
    with _PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(str(src))
        except Exception as exc:  # noqa: BLE001
            info.error = _open_error_text(exc)
            return info

        try:
            info.pages = len(doc)
            for i in range(info.pages):
                page = doc[i]
                try:
                    w, h = page.get_size()
                    info.sizes.append((float(w), float(h)))
                    # 只数前 20 页：几百页的扫描件挨个建文本页要好几秒，
                    # 而「有没有文字」这件事看开头就够判断了
                    if i < 20:
                        tp = page.get_textpage()
                        try:
                            if tp.count_chars() > 0:
                                info.has_text = True
                                info.text_pages += 1
                        finally:
                            tp.close()
                finally:
                    page.close()
        except Exception as exc:  # noqa: BLE001
            info.error = f"解析页面失败：{exc}"
        finally:
            doc.close()
    return info


def _open_error_text(exc: Exception) -> str:
    text = str(exc).lower()
    if "password" in text:
        return "这个 PDF 有打开密码，暂不支持带密码的文件"
    if "format" in text or "corrupt" in text or "header" in text:
        return "文件不是有效的 PDF，或已经损坏"
    return f"无法打开：{exc}"


def probe_image_size(path: str | Path) -> tuple[int, int]:
    """图片的像素尺寸。走 Pillow 而不是 ffprobe —— PDF 队列里可能一次
    进来几百张图，每张起一个 ffprobe 进程要几十秒。"""
    try:
        with Image.open(path) as im:
            return im.size
    except Exception as exc:  # noqa: BLE001
        raise PdfError(f"图片无法读取：{exc}") from exc


# ---------------------------------------------------------------- 渲染


def render_page(
    ref: PageRef,
    *,
    dpi: float = 150.0,
    max_side: int = 0,
    thumb: bool = False,
) -> Image.Image:
    """把一页渲染成 PIL 图片。

    max_side 是长边像素上限，压缩时用它替代 DPI —— 用户更容易理解
    「最长边 1600 像素」而不是「133 DPI」。两者同时给时取更严格的那个，
    避免 A3 幅面在同样 DPI 下把体积撑爆。
    """
    if ref.kind == "image":
        return _render_image(ref, dpi=dpi, max_side=max_side, thumb=thumb)

    with _PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(ref.src)
        except Exception as exc:  # noqa: BLE001
            raise PdfError(_open_error_text(exc)) from exc
        try:
            if not (0 <= ref.index < len(doc)):
                raise PdfError("页码超出了文件范围")
            page = doc[ref.index]
            try:
                return _render_pdf_page(
                    page, ref.rotate, dpi=dpi, max_side=max_side, thumb=thumb
                )
            finally:
                page.close()
        finally:
            doc.close()


def _render_pdf_page(
    page, rotate: int, *, dpi: float, max_side: int, thumb: bool
) -> Image.Image:
    w, h = page.get_size()          # 未旋转的页面尺寸（pt）
    if rotate in (90, 270):
        w, h = h, w                 # 转 90° 后宽高互换，缩放基准也得跟着换
    scale = dpi / PT_PER_IN
    if thumb:
        longest = max(w, h) * scale
        if longest > THUMB_MAX_PX:
            scale *= THUMB_MAX_PX / longest
    elif max_side:
        longest = max(w, h) * scale
        if longest > max_side:
            scale *= max_side / longest
    scale = max(scale, 0.02)        # 缩到 0 会让 pdfium 报错

    # rotation 参数只吃 0/90/180/270，正好等于我们累加出来的角度
    bitmap = page.render(scale=scale, rotation=rotate % 360)
    try:
        return bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()


def _render_image(ref: PageRef, *, dpi: float, max_side: int, thumb: bool) -> Image.Image:
    try:
        with Image.open(ref.src) as im:
            im.load()
            img = im.convert("RGBA") if _has_alpha(im) else im.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise PdfError(f"图片无法读取：{exc}") from exc

    if ref.rotate:
        # PIL 的 ROTATE_* 是逆时针，用户点的是「顺时针 90°」
        img = img.transpose(_PIL_ROTATE[(ref.rotate % 360)])

    limit = THUMB_MAX_PX if thumb else max_side
    if limit and max(img.size) > limit:
        k = limit / max(img.size)
        img = img.resize(
            (max(1, round(img.width * k)), max(1, round(img.height * k))),
            Image.LANCZOS,
        )
    return img


_PIL_ROTATE = {
    90: Image.ROTATE_270,
    180: Image.ROTATE_180,
    270: Image.ROTATE_90,
}


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (
        im.mode == "P" and "transparency" in im.info
    )


def thumb_bytes(ref: PageRef, height: int = 320) -> tuple[bytes, int, int]:
    """缩略图 PNG 字节，统一画成一张「竖版纸」。

    刻意不按每页自己的宽高比生成：横版页、竖版页、方形图片混在一个队列里
    时，尺寸各异的缩略图会让格墙参差不齐，行距看着忽宽忽窄。统一成 A4
    竖版画布后，横版内容居中落在纸上（打印出来本来就是这样），格子永远
    对齐。代价是横版页显示得偏小 —— 放大镜（Ctrl+滚轮）能补。

    返回 bytes 而不是 QPixmap：QPixmap 只能在主线程构造。
    """
    import io

    img = render_page(ref, dpi=96.0, thumb=True)
    paper_w = max(1, round(height / 1.4142))
    canvas = Image.new("RGB", (paper_w, height), (247, 247, 249))

    pad = max(4, round(paper_w * 0.03))
    box_w, box_h = paper_w - pad * 2, height - pad * 2
    k = min(box_w / img.width, box_h / img.height)
    new_w = max(1, round(img.width * k))
    new_h = max(1, round(img.height * k))
    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    canvas.paste(scaled, ((paper_w - new_w) // 2, (height - new_h) // 2))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=False)
    return buf.getvalue(), paper_w, height


# ---------------------------------------------------------------- 无损组装


def export_pdf(
    refs: list[PageRef],
    out: str | Path,
    *,
    progress=None,
) -> Path:
    """按队列顺序把页面搬进一个新 PDF，全程不重新渲染。

    这是「提取选中」「合并」「旋转」的唯一实现：pdfium 的 import_pages
    是页面对象级搬运，文字层、矢量、链接、表单、超链接全部原样保留。
    """
    if not refs:
        raise PdfError("没有可导出的页面")
    with _PDFIUM_LOCK:
        return _export_pdf_locked(refs, Path(out), progress)


def _export_pdf_locked(refs: list[PageRef], out_path: Path, progress) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = pdfium.PdfDocument.new()
    opened: dict[str, pdfium.PdfDocument] = {}
    try:
        total = len(refs)
        for i, ref in enumerate(refs):
            if ref.kind == "pdf":
                doc = opened.get(ref.src)
                if doc is None:
                    try:
                        doc = pdfium.PdfDocument(ref.src)
                    except Exception as exc:  # noqa: BLE001
                        raise PdfError(_open_error_text(exc)) from exc
                    opened[ref.src] = doc
                if not (0 <= ref.index < len(doc)):
                    raise PdfError(f"{Path(ref.src).name} 缺少第 {ref.index + 1} 页")
                # import_pages 不返回新页号，只把页追加到末尾，
                # 所以先记下当前页数，那就是刚搬进来的这一页
                new_index = len(target)
                target.import_pages(doc, pages=[ref.index])
                page = target[new_index]
                try:
                    if ref.rotate:
                        page.set_rotation((page.get_rotation() + ref.rotate) % 360)
                finally:
                    page.close()
            else:
                _append_image_page(target, ref)
            if progress:
                progress(int((i + 1) / total * 100))

        target.save(str(out_path))
    except PdfError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PdfError(f"写入失败：{exc}") from exc
    finally:
        for doc in opened.values():
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass
        target.close()
    return out_path


def _append_image_page(target: pdfium.PdfDocument, ref: PageRef) -> None:
    """把一张图片铺成新的一页。

    JPEG 走 load_jpeg：同一批 DCT 系数直接搬进 PDF，一个像素都不重算。
    其余格式解成位图用 Flate 压缩，无损但要重新编码，所以慢一些。
    """
    try:
        with Image.open(ref.src) as im:
            im.load()
            px_w, px_h = im.size
            mode = im.mode
            has_alpha = _has_alpha(im)
            if ref.rotate in (90, 270):
                px_w, px_h = px_h, px_w
    except Exception as exc:  # noqa: BLE001
        raise PdfError(f"图片无法读取：{exc}") from exc

    pw = px_w / IMAGE_DPI * PT_PER_IN
    ph = px_h / IMAGE_DPI * PT_PER_IN
    page = target.new_page(pw, ph)
    try:
        obj = pdfium.PdfImage.new(target)
        suffix = Path(ref.src).suffix.lower()
        straight = suffix in (".jpg", ".jpeg") and mode in ("RGB", "L")
        if straight and not ref.rotate:
            obj.load_jpeg(ref.src)
        else:
            with Image.open(ref.src) as im:
                im.load()
                img = im.convert("RGBA") if has_alpha else im.convert("RGB")
            if ref.rotate:
                img = img.transpose(_PIL_ROTATE[ref.rotate % 360])
            bmp = pdfium.PdfBitmap.from_pil(img)
            try:
                obj.set_bitmap(bmp)
            finally:
                bmp.close()

        obj.set_matrix(pdfium.PdfMatrix().scale(pw, ph))
        page.insert_obj(obj)
        obj.close()
        page.gen_content()
    finally:
        page.close()


# ---------------------------------------------------------------- 重采样压缩


@dataclass
class CompressPlan:
    """压缩结果预估，写进界面的说明行。

    est_bytes 是实测出来的，不是公式算的：抽几页真渲染、真编码，
    拿实际字节数外推。公式估不准的原因很实在 —— 同一套参数下，
    扫描件每页 300 KB，纯文字页只有 17 KB，差 17 倍。
    """

    pages: int = 0
    est_bytes: int = 0
    per_page_bytes: int = 0
    src_bytes: int = 0
    text_pages: int = 0
    sampled: int = 0
    fallback: bool = False      # True 表示采样失败，退回公式估算

    @property
    def grows(self) -> bool:
        """压缩后反而更大。文字型 PDF 经常这样，得拦住用户。"""
        return bool(self.src_bytes and self.est_bytes > self.src_bytes * 1.02)

    @property
    def ratio_text(self) -> str:
        if not self.src_bytes or not self.est_bytes:
            return "—"
        return f"约原体积的 {self.est_bytes / self.src_bytes * 100:.0f}%"

    @property
    def warning(self) -> str:
        if self.grows:
            return (
                f"这个文件已经是文字版，压缩后会变成图片，体积反而涨到约 "
                f"{self.est_bytes / self.src_bytes:.1f} 倍 —— 不建议压缩"
            )
        if self.text_pages:
            return f"检测到 {self.text_pages} 页含文字层，压缩后文字会变成图片、不能再搜索或复制"
        return ""


def estimate_compress(
    refs: list[PageRef],
    infos: dict[str, PdfInfo] | None = None,
    *,
    fmt: str = "jpg",
    quality: int = 80,
    dpi: float = 150.0,
    max_side: int = 0,
    sample_limit: int = 3,
) -> CompressPlan:
    """抽页实测，再按页数外推。

    取首、中、尾三页而不是固定第一页：很多扫描件封面是纯白或空白，
    拿它当样本会把预估压到实际值的十分之一。
    """
    plan = CompressPlan(pages=len(refs))
    if not refs:
        return plan

    if infos:
        total_pages = sum(i.pages for i in infos.values()) or len(refs)
        for info in infos.values():
            share = min(1.0, _pages_of(refs, info.path) / max(1, info.pages))
            plan.src_bytes += int(_file_size(info.path) * share)
        plan.text_pages = sum(i.text_pages for i in infos.values())
        del total_pages

    picks = _sample_indices(len(refs), sample_limit)
    sizes: list[int] = []
    for idx in picks:
        try:
            img = render_page(refs[idx], dpi=dpi, max_side=max_side)
            sizes.append(_encode_size(img, fmt=fmt, quality=quality))
        except Exception:  # noqa: BLE001
            continue

    if sizes:
        plan.sampled = len(sizes)
        plan.per_page_bytes = sum(sizes) // len(sizes)
        # 每页的 PDF 容器开销（页面对象、内容流包装）约 1~2 KB，
        # 页数多时这部分不可忽略，但按 3% 折算比逐页加常数更稳
        plan.est_bytes = int(plan.per_page_bytes * plan.pages * 1.03)
    else:
        plan.fallback = True
        px = 0.0
        for idx in picks or [0]:
            ref = refs[idx]
            try:
                img = render_page(ref, dpi=dpi, max_side=max_side)
            except Exception:  # noqa: BLE001
                continue
            px += img.width * img.height
        avg_px = px / max(1, len(picks)) if px else 0
        bpp = 1.2 if fmt == "png" else 0.14 * (max(1, quality) / 80) ** 1.7
        plan.est_bytes = int(avg_px * bpp * plan.pages * 1.03)
        plan.per_page_bytes = int(avg_px * bpp)
    return plan


def _sample_indices(n: int, limit: int) -> list[int]:
    if n <= limit:
        return list(range(n))
    if limit <= 1:
        return [n // 2]
    # 首、中、尾均匀取点，去掉重复
    raw = [round(i * (n - 1) / (limit - 1)) for i in range(limit)]
    return sorted(set(raw))


def _pages_of(refs: list[PageRef], src: str) -> int:
    return sum(1 for r in refs if r.src == src)


def _encode_size(img: Image.Image, *, fmt: str, quality: int) -> int:
    import io

    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, format="PNG", optimize=True)
    else:
        img.save(buf, format="JPEG", quality=max(20, min(95, quality)), optimize=True)
    return len(buf.getvalue())


def _file_size(path: str) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def compress_pdf(
    refs: list[PageRef],
    out: str | Path,
    *,
    fmt: str = "jpg",
    quality: int = 80,
    dpi: float = 150.0,
    max_side: int = 0,
    progress=None,
) -> Path:
    """渲染每页 → 重新编码 → 封装成新 PDF。

    页面上的一切都会变成像素：文字不可选、链接失效、表单丢失。
    这是「体积换可编辑性」的必然代价，调用方必须在动手前告知用户。
    """
    if not refs:
        raise PdfError("没有可压缩的页面")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 整段持锁：render_page 内部会再要一次同一把 RLock，
    # 与其让每页单独加解锁，不如一口气跑完，免得别的线程插进来
    with _PDFIUM_LOCK:
        target = pdfium.PdfDocument.new()
        try:
            total = len(refs)
            for i, ref in enumerate(refs):
                img = render_page(ref, dpi=dpi, max_side=max_side)
                _append_rendered(target, img, fmt=fmt, quality=quality)
                if progress:
                    progress(int((i + 1) / total * 100))
            target.save(str(out_path))
        except PdfError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PdfError(f"压缩失败：{exc}") from exc
        finally:
            target.close()
    return out_path


def _append_rendered(
    target: pdfium.PdfDocument, img: Image.Image, *, fmt: str, quality: int
) -> None:
    """把渲染好的位图铺成一页。页面尺寸跟着像素走，不缩回原纸张大小 ——
    压缩本来就是要降低分辨率，硬按原尺寸铺会把 DPI 拉低，打印发虚。"""
    w_px, h_px = img.size
    pw = w_px / IMAGE_DPI * PT_PER_IN
    ph = h_px / IMAGE_DPI * PT_PER_IN
    page = target.new_page(pw, ph)
    try:
        obj = pdfium.PdfImage.new(target)
        if fmt == "png":
            bmp = pdfium.PdfBitmap.from_pil(img)
            try:
                obj.set_bitmap(bmp)
            finally:
                bmp.close()
        else:
            # 走 JPEG：先编码到内存再交给 pdfium，它接受 file-like
            import io

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=max(20, min(95, quality)), optimize=True)
            buf.seek(0)
            obj.load_jpeg(buf)
        obj.set_matrix(pdfium.PdfMatrix().scale(pw, ph))
        page.insert_obj(obj)
        obj.close()
        page.gen_content()
    finally:
        page.close()


# ---------------------------------------------------------------- 导出图片


_IMG_ENC = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}


def export_images(
    refs: list[PageRef],
    out_dir: str | Path,
    *,
    fmt: str = "png",
    dpi: float = 150.0,
    quality: int = 92,
    progress=None,
) -> list[Path]:
    """每页一个图片文件，名字跟着原始文件走，顺序与队列一致。"""
    if not refs:
        raise PdfError("没有可导出的页面")
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)

    enc = _IMG_ENC.get(fmt.lower(), "PNG")
    ext = "jpg" if enc == "JPEG" else fmt.lower()
    saved: list[Path] = []
    used: set[str] = set()
    total = len(refs)

    for i, ref in enumerate(refs):
        img = render_page(ref, dpi=dpi)
        path = unique_path(folder, page_stem(ref), f".{ext}", used)
        if enc == "JPEG":
            img.convert("RGB").save(path, format="JPEG", quality=quality, optimize=True)
        elif enc == "WEBP":
            img.save(path, format="WEBP", quality=quality)
        else:
            img.save(path, format="PNG", optimize=True)
        saved.append(path)
        if progress:
            progress(int((i + 1) / total * 100))
    return saved


# ---------------------------------------------------------------- 杂项


def safe_stem(text: str, fallback: str = "合并") -> str:
    """文件名去掉 Windows 不认的字符，也挡住结尾的点和空格。"""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in (text or "")).strip(" .")
    return cleaned or fallback


def page_stem(ref: PageRef) -> str:
    """单页文件的名字：`原文件名·页号`，图片就是它自己的名字。

    页号取的是这页在**原始文件**里的位置（从 1 数），不是队列里的位置 ——
    拆出去再拼回来时，看名字就知道它原来在第几页。
    """
    stem = safe_stem(Path(ref.src).stem, fallback="页面")
    if ref.kind == "pdf":
        return f"{stem}·{ref.index + 1}"
    return stem


def unique_path(folder: Path, stem: str, ext: str, used: set[str] | None = None) -> Path:
    """同名就往后挂 (2)(3)，别让后一页把前一页覆盖掉。

    `used` 收的是本批已经占用的名字（小写），跨批次防重靠 exists()。
    """
    taken = used if used is not None else set()
    name = f"{stem}{ext}"
    n = 2
    while name.lower() in taken or (folder / name).exists():
        name = f"{stem}({n}){ext}"
        n += 1
    taken.add(name.lower())
    return folder / name
