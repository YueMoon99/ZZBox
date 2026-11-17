"""PDF 内嵌图片压缩：只换图片的像素数据，页面结构一个字节都不动。

和 pdf.py 里那个 compress_pdf（整页重渲染）是两件完全不同的事：

  · compress_pdf      —— 整页拍平成一张位图。体积降得最多，但文字层、
                        链接、书签全没了，页面变成图片。
  · 本模块            —— 只找到页面里 /Subtype /Image 的那些对象，把它们的
                        像素按质量重新编码成 JPEG 再塞回原位。页面的
                        /MediaBox、内容流、文字、矢量线条、链接、书签
                        原封不动；图片在页面上的位置和大小由内容流里的
                        cm 矩阵决定，我们不动内容流，所以摆放也不会变。

两条硬约束（用户明确要求，也是这个模块存在的理由）：

  1. 不缩放图片。像素宽高 /Width /Height 严格保持原值，只降 JPEG 质量。
  2. 不改页面尺寸。压缩前后 MediaBox 必须一模一样。

为什么用 pypdf 而不是 pypdfium2：PDFium 是渲染引擎，只读，没有任何修改
PDF 对象的 API。pypdf 是纯 Python 的 BSD 库，能直接拿到流对象并改写。
pypdf 的 StreamObject.set_data() 只接受 FlateDecode 流（改 JPEG 流会直接
抛 PdfReadError），所以这里走 `obj._data` + 手动改 /Filter ——
write_to_stream 会把 _data 原样写出并按 len(_data) 重算 /Length。

哪些图片会被跳过（宁可少压，也不能压坏）：
  · 带 /SMask 的（有透明通道，JPEG 存不了 alpha）
  · /ImageMask 蒙版图
  · 带 /Decode 数组的（反相或自定义映射，重编码会变色）
  · 解码不了的（JPX/CMYK 之类）
  · 重编码之后反而更大的（已经很小的图，再压就只剩块效应）
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject

from app.core.pdf import PageRef, PdfCancelled, PdfError

# pypdf 的 writer 不是线程安全的：内部有 _id_translated 之类的共享状态，
# 两个线程同时往一个 writer 里 add_page 会写坏对象表。估算和导出有可能
# 前后脚触发，统一串行化最省心（这条管线和 PDFium 那把锁是两回事）。
_PYPDF_LOCK = threading.RLock()

QUALITY_MIN = 30
QUALITY_MAX = 100
QUALITY_DEFAULT = 78

# 解码后允许重编码的 Pillow 模式。其余（P 调色板、1bit 二值、RGBA）转 RGB
# 之后体积经常不降反升，或者本身就是小图标，不值得动
_OK_MODES = ("RGB", "L")


class PdfImageError(PdfError):
    """图片压缩专用错误。继承 PdfError，上层的错误包装逻辑不用改。"""


# ---------------------------------------------------------------- 数据结构


@dataclass
class PageStat:
    """一页的图片体检结果。界面拿它渲染格子下面那行小字。"""

    index: int
    count: int = 0              # 真正能压的图片张数
    cur_bytes: int = 0          # 这些图片当前占多少字节
    est_bytes: int = 0          # 按当前质量压完占多少（未估算时为 0）
    skipped: int = 0            # 被跳过的图片张数
    reason: str = ""            # 整页不可压的原因，给界面直接显示

    @property
    def compressible(self) -> bool:
        return self.count > 0 and self.cur_bytes > 0

    @property
    def estimated(self) -> bool:
        return self.est_bytes > 0

    def label(self) -> str:
        """格子下面那行字：`图片 1.4 MB → 520 KB`。"""
        if self.reason:
            return self.reason
        if not self.compressible:
            return ""
        if not self.estimated:
            return f"图片 {_human(self.cur_bytes)} · 待估算"
        return f"图片 {_human(self.cur_bytes)} → {_human(self.est_bytes)}"


def _human(n: float) -> str:
    """和 media.human_size 同口径，但这里不 import 它 —— core 里少一层依赖。"""
    for unit, base in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= base:
            v = n / base
            return f"{v:.0f} {unit}" if v >= 10 else f"{v:.1f} {unit}"
    return f"{int(n)} B"


# ---------------------------------------------------------------- 读文档


_READERS: dict[tuple[str, float, int], PdfReader] = {}


def _reader(path: str | Path) -> PdfReader:
    """按 (路径, mtime, 大小) 缓存 reader —— 队列里同一份 PDF 有几十页时，
    每页都重新解析整份文件会慢得离谱。文件被外部改动后缓存自动失效。
    """
    p = Path(path)
    try:
        st = p.stat()
    except OSError as exc:
        raise PdfImageError(f"打不开 {p.name}：{exc.strerror or exc}") from exc
    key = (str(p.resolve()), st.st_mtime, st.st_size)
    hit = _READERS.get(key)
    if hit is not None:
        return hit

    try:
        reader = PdfReader(str(p))
        if reader.is_encrypted:
            # 空密码能解的（只限制编辑）照常处理，真加密的直接拒绝
            if not reader.decrypt(""):
                raise PdfImageError(f"{p.name} 已加密，需要密码才能处理")
        len(reader.pages)  # 逼它解析页树，坏文件在这里就能发现
    except PdfImageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PdfImageError(f"读不了 {p.name}：{exc}") from exc

    # 缓存别无限长：太久不用的清掉，避免几十份大文件一直占着内存
    if len(_READERS) > 8:
        _READERS.clear()
    _READERS[key] = reader
    return reader


def clear_cache() -> None:
    _READERS.clear()


# ---------------------------------------------------------------- 找图片


def _as_dict(obj):
    return obj.get_object() if hasattr(obj, "get_object") else obj


def _iter_images(page, depth: int = 0):
    """产出 (资源名, 间接引用, 流对象)。会递归进 Form XObject ——
    扫描件常把整页内容包在 Form 里，图片藏在下一层。
    """
    res = page.get("/Resources")
    if res is None:
        return
    res = _as_dict(res)
    xobjs = res.get("/XObject")
    if xobjs is None:
        return
    for name, ref in _as_dict(xobjs).items():
        obj = _as_dict(ref)
        if obj is None:
            continue
        subtype = obj.get("/Subtype")
        if subtype == "/Image":
            yield str(name), ref, obj
        elif subtype == "/Form" and depth < 4:
            form_page = _FormPage(obj)
            yield from _iter_images(form_page, depth + 1)


class _FormPage:
    """把 Form XObject 包成"只有 /Resources"的最小对象，好复用 _iter_images。"""

    def __init__(self, obj):
        self._obj = obj

    def get(self, key, default=None):
        return self._obj.get(key, default)


def _stream_len(obj) -> int:
    """对象在文件里占的字节数。

    优先用 _data 的长度：pypdf 读流时会把 /Length 从字典里摘掉（长度信息
    挪到了 _data 上），所以 obj.get("/Length") 是 None。看 _data 既准又不
    解码 —— 对大图来说 get_data() 才是真的贵。
    """
    raw = getattr(obj, "_data", None)
    if raw is not None:
        return len(raw)
    n = obj.get("/Length", 0)
    try:
        return max(0, int(_as_dict(n)))
    except (TypeError, ValueError):
        return 0


def _icc_components(obj, cs) -> int | None:
    """ICCBased 颜色空间的分量数（3=RGB、1=Gray、4=CMYK）。"""
    cs = _as_dict(cs)
    if not isinstance(cs, ArrayObject) or len(cs) < 2:
        return None
    if _as_dict(cs[0]) != "/ICCBased":
        return None
    try:
        prof = _as_dict(cs[1])
        return int(prof.get("/N", 0)) or None
    except Exception:  # noqa: BLE001
        return None


def _skip_reason(obj) -> str:
    """不解码就能判断的跳过条件。返回空串表示"可以试着压"。"""
    if obj.get("/SMask") is not None:
        return "有透明遮罩"
    if obj.get("/ImageMask") in (True, "/True"):
        return "蒙版图"
    if obj.get("/Decode") is not None:
        return "自定义颜色映射"
    raw_cs = obj.get("/ColorSpace")
    if raw_cs is None:
        return ""
    cs = _as_dict(raw_cs)
    if isinstance(cs, str) and cs in ("/DeviceCMYK", "/Separation", "/Pattern"):
        return f"{cs} 色彩空间"
    if isinstance(cs, ArrayObject) and len(cs):
        head = _as_dict(cs[0])
        if head in ("/Indexed", "/Separation"):
            return f"{head} 色彩空间"
        if _icc_components(obj, cs) == 4:
            return "CMYK 色彩空间"
    return ""


def _reencode(obj, quality: int) -> tuple[bytes, str] | None:
    """把一张图重新编码成 JPEG。返回 (字节, Pillow模式)；压不动返回 None。"""
    try:
        raw = obj.get_data()
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:  # noqa: BLE001
        return None

    mode = im.mode
    if mode in ("RGBA", "LA", "PA"):
        return None                      # 有 alpha，JPEG 存不了
    if mode == "P":
        # 调色板多半是小图标/线条，转 RGB 之后经常变大，直接放过
        return None
    if mode not in _OK_MODES:
        try:
            im = im.convert("RGB")
        except Exception:  # noqa: BLE001
            return None

    buf = io.BytesIO()
    try:
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    except Exception:  # noqa: BLE001
        return None
    data = buf.getvalue()
    # 已经是很小的图，再压只会更模糊还更大
    if len(data) >= _stream_len(obj):
        return None
    return data, im.mode


def _write_back(obj, data: bytes, mode: str) -> None:
    """把新 JPEG 塞回原对象。宽高、颜色空间按需修正，其余元数据留着。

    pypdf 的 set_data() 只认 FlateDecode，这里直接改 _data ——
    StreamObject.write_to_stream 会原样写出 _data 并按长度重算 /Length。
    """
    obj._data = data
    # get_data() 会把解码结果缓存进 decoded_self，不清掉的话后面读到的
    # 还是旧像素（导出时不会再读，但清一下更安全）
    obj.decoded_self = None
    obj[NameObject("/Filter")] = NameObject("/DCTDecode")
    if "/DecodeParms" in obj:
        del obj["/DecodeParms"]
    obj[NameObject("/BitsPerComponent")] = NumberObject(8)

    cs = _as_dict(obj.get("/ColorSpace"))
    n = _icc_components(obj, cs) if isinstance(cs, ArrayObject) else None
    if mode == "L":
        if cs != "/DeviceGray" and n != 1:
            obj[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
    elif cs != "/DeviceRGB" and n != 3:
        obj[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")


def _apply_quality(obj, quality: int, done: set | None) -> int:
    """压一张图并写回，返回省下的字节数（0 表示跳过）。"""
    ident = getattr(obj, "indirect_reference", None)
    if done is not None and ident is not None:
        num = getattr(ident, "idnum", None)
        if num is not None:
            if num in done:
                return 0
            done.add(num)

    if _skip_reason(obj):
        return 0
    out = _reencode(obj, quality)
    if out is None:
        return 0
    data, mode = out
    before = _stream_len(obj)
    _write_back(obj, data, mode)
    return max(0, before - len(data))


# ---------------------------------------------------------------- 扫描 / 估算


def scan_pdf(path: str | Path, pages: list[int] | None = None) -> dict[int, PageStat]:
    """只统计每页图片有多大，不解码 —— 导入后立刻能显示，不卡界面。"""
    with _PYPDF_LOCK:
        reader = _reader(path)
        total = len(reader.pages)
        idxs = range(total) if pages is None else pages
        out: dict[int, PageStat] = {}
        for i in idxs:
            if not 0 <= i < total:
                continue
            stat = PageStat(index=i)
            for _name, _ref, obj in _iter_images(reader.pages[i]):
                if _skip_reason(obj):
                    stat.skipped += 1
                    continue
                stat.count += 1
                stat.cur_bytes += _stream_len(obj)
            if not stat.count:
                stat.reason = (
                    f"{stat.skipped} 张图片不可压缩" if stat.skipped else "本页无图片"
                )
            out[i] = stat
        return out


def estimate_pdf(
    path: str | Path,
    quality: int,
    pages: list[int] | None = None,
    progress=None,
    cancel: threading.Event | None = None,
) -> dict[int, PageStat]:
    """真解码再编码，算出每页压完多大。慢，必须在后台线程跑。

    这就是"点压缩全部之后要等一下才有数字"的那段计算。按页回调进度，
    用户能看着数字一格格跳出来，比转圈等着强。
    """
    with _PYPDF_LOCK:
        reader = _reader(path)
        total = len(reader.pages)
        idxs = [i for i in (range(total) if pages is None else pages) if 0 <= i < total]
        out: dict[int, PageStat] = {}
        # 对象号 → (原大小, 压完大小)。同一张图被多页共用时只编码一次，
        # 但每页都要按这份结果记账 —— 否则第二页会显示"待估算"，看着像算漏了
        seen: dict[int, tuple[int, int]] = {}
        for step, i in enumerate(idxs, 1):
            _check_cancel(cancel)
            stat = PageStat(index=i)
            for _name, _ref, obj in _iter_images(reader.pages[i]):
                if _skip_reason(obj):
                    stat.skipped += 1
                    continue
                cur = _stream_len(obj)
                ident = getattr(obj, "indirect_reference", None)
                num = getattr(ident, "idnum", None) if ident is not None else None
                if num is not None and num in seen:
                    c, e = seen[num]
                    stat.count += 1
                    stat.cur_bytes += c
                    stat.est_bytes += e
                    continue
                res = _reencode(obj, quality)
                if res is None:
                    stat.skipped += 1
                    continue
                stat.count += 1
                stat.cur_bytes += cur
                stat.est_bytes += len(res[0])
                if num is not None:
                    seen[num] = (cur, len(res[0]))
            if not stat.count:
                stat.reason = (
                    f"{stat.skipped} 张图片不可压缩" if stat.skipped else "本页无图片"
                )
            out[i] = stat
            if progress is not None:
                progress(int(step / max(1, len(idxs)) * 100))
        return out


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise PdfCancelled("已取消")


# ---------------------------------------------------------------- 输出


def _new_reader(path: str | Path) -> PdfReader:
    try:
        return _reader(path)
    except PdfImageError:
        raise


def stage_page(
    ref: PageRef,
    out_path: str | Path,
    quality: int,
    progress=None,
) -> Path:
    """把一页压好存成单页 PDF（临时文件，导出时直接用）。

    旋转在这里一并落到 /Rotate 上，导出时就不用再管 —— 否则暂存页和
    没暂存的页混在一起时，旋转会漏掉一半。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _PYPDF_LOCK:
        reader = _new_reader(ref.src)
        try:
            src_page = reader.pages[ref.index]
        except IndexError as exc:
            raise PdfImageError(f"{Path(ref.src).name} 没有第 {ref.index + 1} 页") from exc
        writer = PdfWriter()
        page = writer.add_page(src_page)
        if ref.rotate:
            page.rotate(ref.rotate)
        done: set = set()
        for _name, _ref, obj in _iter_images(page):
            _apply_quality(obj, quality, done)
        try:
            with open(out, "wb") as fh:
                writer.write(fh)
        except Exception as exc:  # noqa: BLE001
            raise PdfImageError(f"写不出 {out.name}：{exc}") from exc
    if progress is not None:
        progress(100)
    return out


def merge_pdf(
    refs: list[PageRef],
    out_path: str | Path,
    *,
    quality: int | None = None,
    staged: dict[tuple[str, int, int], str] | None = None,
    progress=None,
    cancel: threading.Event | None = None,
) -> Path:
    """按队列顺序合并成一个 PDF。

    quality 不为 None → 顺手把每页的图片重编码；为 None → 纯无损搬运
    （暂存页仍然优先用压缩后的版本）。

    暂存页的键是 (源文件, 页号, 旋转角)：同一页被拖进队列两次、或旋转
    角度不同，都不能共用同一个暂存文件。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = staged or {}
    total = max(1, len(refs))
    with _PYPDF_LOCK:
        writer = PdfWriter()
        readers: dict[str, PdfReader] = {}
        done: dict[str, set] = {}
        for i, ref in enumerate(refs):
            _check_cancel(cancel)
            key = (ref.src, ref.index, ref.rotate % 360)
            staged_path = staged.get(key)
            if staged_path and Path(staged_path).exists():
                sr = _new_reader(staged_path)
                if len(sr.pages):
                    writer.add_page(sr.pages[0])   # 已压好、已转好，原样放进去
                if progress is not None:
                    progress(int((i + 1) / total * 100))
                continue

            src = ref.src
            rd = readers.get(src)
            if rd is None:
                rd = readers[src] = _new_reader(src)
            try:
                src_page = rd.pages[ref.index]
            except IndexError as exc:
                raise PdfImageError(
                    f"{Path(src).name} 没有第 {ref.index + 1} 页"
                ) from exc
            page = writer.add_page(src_page)
            if ref.rotate:
                page.rotate(ref.rotate)
            if quality is not None:
                mark = done.setdefault(src, set())
                for _name, _ref, obj in _iter_images(page):
                    _apply_quality(obj, quality, mark)
            if progress is not None:
                progress(int((i + 1) / total * 100))

        _check_cancel(cancel)
        try:
            with open(out, "wb") as fh:
                writer.write(fh)
        except Exception as exc:  # noqa: BLE001
            raise PdfImageError(f"写不出 {out.name}：{exc}") from exc
    return out
