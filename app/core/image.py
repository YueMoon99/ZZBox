"""图片压缩与 AI 超分。

和视频走的不是同一条路：视频必须拆帧才能喂给 ncnn 引擎，图片本来就是
单帧，引擎直接吃文件。所以这里没有临时帧序列、没有多阶段权重，
一张图最多两条命令：引擎超分 → ffmpeg 缩放/锐化/编码。

复用 ai.py 的模型体系（实拍 / 动画）和降噪、锐化档位，参数语义完全一致 ——
用户在视频页学会的那套，图片页不用重新理解一遍。
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.core.ai import DEFAULT_MODEL, MODELS
from app.core.media import human_size
from app.core.probe import _find_tool

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 不收 GIF：动图进了批量队列会被静默压成第一帧，用户拿到的是一张静态图。
# 与其事后解释，不如一开始就不认。
IMAGE_EXT = {
    ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp", ".tif", ".tiff", ".tga", ".avif",
}  # fmt: skip

# 每种格式对应的 ffmpeg 编码器。值里的 None 表示「这条命令不吃质量参数」。
ENCODERS = {
    "jpg": ("mjpeg", "yuvj420p"),
    "jpeg": ("mjpeg", "yuvj420p"),
    "png": ("png", None),
    "webp": ("libwebp", None),
    "bmp": ("bmp", None),
    "tif": ("tiff", None),
    "tiff": ("tiff", None),
    "tga": ("targa", None),
    "avif": ("libaom-av1", None),
}

# 能作为输出目标的格式（keep 时若源格式不在其中，退回 png）
WRITABLE = {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "tga"}

FMT_LABEL = {
    "keep": "保持原样",
    "jpg": "JPG",
    "png": "PNG",
    "webp": "WebP",
}

# 带 alpha 通道的像素格式。据此决定输出要不要留透明 —— JPG 没有 alpha，
# 硬塞会得到一张黑底图，必须先把 alpha 摊到白底上。
_ALPHA_PIX = {
    "rgba", "bgra", "argb", "abgr", "ya8", "ya16be", "ya16le",
    "yuva420p", "yuva422p", "yuva444p", "gbrap", "gbrap16be", "gbrap16le",
    "pal8",
}  # fmt: skip

# 单帧耗时的实测基准（RTX 4060 8G, tile 128）。图片是一张一张来，
# 所以这里按「每百万像素多少秒」建模，别拿视频的每帧耗时套。
AI_SEC_PER_MP = {
    "photo": 8.5,   # x4plus: 1080p(2.07MP) 约 18 秒
    "anime": 1.6,   # animevideov3
}


# ---------------------------------------------------------------- 探测


@dataclass
class ImageInfo:
    path: str
    width: int = 0
    height: int = 0
    size: int = 0
    fmt: str = ""            # 源格式小写，不含点
    alpha: bool = False
    rotation: int = 0        # EXIF 方向（手机竖拍常见 90/270）
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.width > 0 and self.height > 0

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def megapixels(self) -> float:
        return self.pixels / 1_000_000

    @property
    def resolution_text(self) -> str:
        if not self.ok:
            return "—"
        # 竖拍照片的 EXIF 旋转 90° 时，用户看到的宽高是反的。
        # 队列里报「看到的样子」，不是报存储里的样子。
        if self.rotation in (90, 270):
            return f"{self.height}×{self.width}"
        return f"{self.width}×{self.height}"

    @property
    def view_size(self) -> tuple[int, int]:
        """用户眼里的宽高（考虑 EXIF 旋转）。"""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height

    @property
    def fmt_text(self) -> str:
        if self.error:
            return "—"
        return (self.fmt or "?").upper()


def _to_int(v, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def probe_image(path: str | Path) -> ImageInfo:
    src = Path(path)
    info = ImageInfo(path=str(src), fmt=src.suffix.lower().lstrip("."))
    ffprobe = _find_tool("ffprobe")
    if not ffprobe:
        info.error = "未找到 ffprobe.exe"
        return info
    if not src.exists():
        info.error = "文件不存在"
        return info
    try:
        info.size = src.stat().st_size
    except OSError:
        pass

    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(src),
    ]  # fmt: skip
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:  # noqa: BLE001
        info.error = f"读取失败：{exc}"
        return info
    if r.returncode != 0:
        info.error = "文件无法解析，可能已损坏或格式不支持"
        return info

    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        info.error = "ffprobe 输出解析失败"
        return info

    for st in data.get("streams", []) or []:
        if st.get("codec_type") != "video":
            continue
        info.width = _to_int(st.get("width"))
        info.height = _to_int(st.get("height"))
        info.alpha = (st.get("pix_fmt") or "").lower() in _ALPHA_PIX
        # 新版 ffprobe 把 EXIF 方向折成 rotation side data
        for sd in st.get("side_data_list", []) or []:
            rot = _to_int(sd.get("rotation"))
            if rot:
                info.rotation = abs(rot) % 360
        break

    if not info.width:
        info.error = "该文件不包含图像"
    return info


# ---------------------------------------------------------------- 参数


@dataclass
class ImageSettings:
    fmt: str = "keep"           # keep | jpg | png | webp
    quality: int = 82           # 1-100，JPG/WebP 有效，PNG 忽略
    max_side: int = 0           # 0=不改尺寸；否则限制长边像素
    strip_meta: bool = False    # 去掉 EXIF / ICC / 拍摄信息

    scale: int = 2              # 0=不超分；2/3/4
    model: str = DEFAULT_MODEL  # MODELS 的键
    denoise: int = 0            # 超分前的降噪档位，和视频页同一套
    sharpen: int = 1            # 降采样后的锐化档位

    output_dir: str = ""

    @property
    def has_ai(self) -> bool:
        return self.scale > 1

    @property
    def has_compress(self) -> bool:
        """是否需要重新编码/缩放（AI 之外的动作）。"""
        return self.fmt != "keep" or self.max_side > 0 or self.strip_meta or self.quality < 100


# ---------------------------------------------------------------- 尺寸


def _even(v: int) -> int:
    """yuv420p 要求偶数边长。奇数会让 ffmpeg 报错或悄悄裁一列。"""
    return max(2, v - (v % 2))


def out_format(info: ImageInfo, s: ImageSettings) -> str:
    """最终输出格式：keep 时跟源走，源不可写就退到 png。"""
    if s.fmt != "keep":
        return s.fmt
    src = info.fmt or "png"
    if src in ("jpeg", "jpe"):
        return "jpg"
    if src in WRITABLE:
        return src
    return "png"


def target_size(info: ImageInfo, s: ImageSettings, factor: int = 1) -> tuple[int, int]:
    """算出最终输出尺寸。factor 是「相对原图放大几倍」，即用户要的倍率。

    注意别拿推理倍率当 factor 传进来：x4plus 请求 2× 时引擎按 4× 推理，
    但输出应当是 2×，多出来的那一档是用来降采样的超采样余量，不是成品。
    """
    w, h = info.view_size
    if not (w and h):
        return 0, 0
    w, h = w * max(1, factor), h * max(1, factor)
    if s.max_side and max(w, h) > s.max_side:
        k = s.max_side / max(w, h)
        w, h = w * k, h * k
    # 缩到长边上限时会得到小数，ffmpeg 的 scale 不接受 640.0 这种写法
    return _even(int(round(w))), _even(int(round(h)))


def infer_scale(s: ImageSettings) -> int:
    """实际推理倍率。

    和视频页同一个道理：x4plus 只有 4× 一档，请求 2× 时按 4× 推理再降采样，
    这是超采样而不是妥协。图片是单张，慢一点完全可以接受 —— 这里不做
    视频那种「显存不够就降倍率」的妥协，改成靠 tile 兜住。
    """
    if not s.has_ai:
        return 1
    scales = MODELS.get(s.model, MODELS[DEFAULT_MODEL])[1]
    fits = [v for v in scales if v >= s.scale] or [scales[-1]]
    return fits[0]


# ---------------------------------------------------------------- 命令


def quality_of(s: ImageSettings, fmt: str) -> int:
    """把 1-100 的质量换算成各编码器的刻度。"""
    q = max(1, min(100, s.quality))
    if fmt in ("jpg", "jpeg"):
        # mjpeg 的 -q:v 是 2..31，越小越好。q100→2, q50→16
        return max(2, min(31, round(31 - q * 29 / 100)))
    return q


def denoise_filter(s: ImageSettings) -> str:
    from app.core.ai import DENOISE_FILTER

    return DENOISE_FILTER.get(s.denoise, "")


def sharpen_filter(s: ImageSettings) -> str:
    from app.core.ai import SHARPEN_FILTER

    return SHARPEN_FILTER.get(s.sharpen, "")


def _rotate_filter(rotation: int) -> str:
    if rotation == 90:
        return "transpose=1"
    if rotation == 180:
        return "transpose=1,transpose=1"
    if rotation == 270:
        return "transpose=2"
    return ""


def _encode_args(fmt: str, s: ImageSettings, keep_alpha: bool) -> list[str]:
    """按格式挑编码参数。alpha 只在能装下的容器里保留。"""
    enc, pix = ENCODERS.get(fmt, ("mjpeg", "yuvj420p"))
    args = ["-c:v", enc]
    if fmt in ("jpg", "jpeg"):
        args += ["-q:v", str(quality_of(s, fmt)), "-pix_fmt", "yuvj420p"]
        return args
    if fmt == "webp":
        args += ["-quality", str(max(1, min(100, s.quality))), "-compression_level", "4"]
        args += ["-pix_fmt", "yuva420p"] if keep_alpha else ["-pix_fmt", "yuv420p"]
        return args
    if fmt == "png":
        args += ["-compression_level", "6"]
        # 源有 alpha 就留着，没有就转 rgb24 —— 否则 png 会被升级成 rgba，
        # 文件白胖 25% 却看不出区别
        args += ["-pix_fmt", "rgba"] if keep_alpha else ["-pix_fmt", "rgb24"]
        return args
    if pix:
        args += ["-pix_fmt", pix]
    return args


def make_output_path(
    src: Path,
    s: ImageSettings,
    info: ImageInfo,
    out_size: tuple[int, int] | None = None,
    ai: bool = False,
) -> Path:
    """输出文件名：压缩加 _压缩，超分加 _4x（按实际倍率），两者都有就都带。

    同目录下若会覆盖源文件（格式没变的极端情况），自动补一个「副本」，
    绝不让用户点一次处理就丢掉原图。
    """
    out_dir = Path(s.output_dir) if s.output_dir else src.parent
    fmt = out_format(info, s)
    # 后缀只标「用户要的那个倍率」，不标推理倍率 —— 选 2× 却拿到 _超分4x.jpg，
    # 用户第一反应是设置没生效（视频那边踩过一模一样的坑）。
    stem = src.stem + (f"_超分{max(2, s.scale)}x" if ai else "_压缩")
    path = out_dir / f"{stem}.{fmt}"
    if path.resolve() == src.resolve() or path.exists() and path == src:
        path = out_dir / f"{stem}_1.{fmt}"
        n = 2
        while path.exists():
            path = out_dir / f"{stem}_{n}.{fmt}"
            n += 1
    return path


def preview_compress_bytes(
    src: Path,
    s: ImageSettings,
    info: ImageInfo | None = None,
) -> int:
    """按图片工作台的方案真编一次到内存，返回字节数。

    给 PDF 队列拖质量条时做实时预估用。必须和 build_compress_steps
    使用同一套格式 / 质量 / 长边，否则预估说 66kb、压出来 102kb，
    用户会以为数字是编的。
    """
    import io

    from PIL import Image

    info = info or probe_image(src)
    fmt = out_format(info, s)
    w, h = target_size(info, s, 1)
    with Image.open(src) as im:
        pic = im if im.mode in ("RGB", "L") else im.convert("RGB")
        if w and h and (w, h) != pic.size:
            pic = pic.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        if fmt == "png":
            pic.save(buf, format="PNG", optimize=True)
        elif fmt == "webp":
            pic.save(buf, format="WEBP", quality=s.quality, method=4)
        else:
            pic.save(buf, format="JPEG", quality=s.quality, optimize=True)
    return len(buf.getvalue())


def build_compress_steps(
    ffmpeg: str,
    src: Path,
    s: ImageSettings,
    info: ImageInfo,
    out_path: Path | None = None,
) -> tuple[list[list[str]], Path, str]:
    """纯压缩：一条 ffmpeg 命令搞定，返回 (步骤, 输出路径, 错误)。

    out_path 给了就写到那里 —— PDF 工作台压缩图片时要落到软件目录的
    临时文件夹，绝不能覆盖用户的原图。不给则照旧按图片工作台的规则
    生成「_压缩」文件名。
    """
    fmt = out_format(info, s)
    w, h = target_size(info, s, 1)
    if not (w and h):
        return [], Path(), "无法读取图片尺寸"

    vf: list[str] = []
    rot = _rotate_filter(info.rotation)
    if rot:
        vf.append(rot)
    if (w, h) != info.view_size:
        vf.append(f"scale={w}:{h}:flags=lanczos")
    if fmt in ("jpg", "jpeg") and info.alpha:
        # JPG 没有 alpha 通道：直接编会得到黑底，先摊到白底上
        vf.append("format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a=255")
    filt = ",".join(vf) if vf else "null"

    out = Path(out_path) if out_path is not None else make_output_path(src, s, info)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-i", str(src), "-frames:v", "1", "-vf", filt,
        *_encode_args(fmt, s, info.alpha),
        "-map_metadata", "-1" if s.strip_meta else "0",
        str(out),
    ]  # fmt: skip
    return [cmd], out, ""


def build_ai_steps(
    ffmpeg: str,
    engine: str,
    models_dir: str,
    src: Path,
    s: ImageSettings,
    info: ImageInfo,
    tmp_png: Path,
    tile: int = 128,
) -> tuple[list[list[str]], Path, str]:
    """AI 超分：引擎出 4× PNG，再交给 ffmpeg 缩放 / 锐化 / 编码。

    中间文件刻意用 PNG —— 引擎只会写 PNG/JPG/WEBP，而 JPG 会在这一步就把
    重建出来的细节再压掉一次，后面降采样时就看不出超分的收益了。
    """
    name = MODELS.get(s.model, MODELS[DEFAULT_MODEL])[0]
    k = infer_scale(s)          # 引擎实际跑的倍率
    out_k = max(2, s.scale)     # 用户要的输出倍率
    w, h = target_size(info, s, out_k)
    if not (w and h):
        return [], Path(), "无法读取图片尺寸"

    rot = _rotate_filter(info.rotation)

    step1 = [
        engine, "-i", str(src), "-o", str(tmp_png),
        "-n", name, "-s", str(k), "-t", str(tile), "-m", models_dir,
        "-f", "png", "-g", "0",
    ]  # fmt: skip

    vf: list[str] = []
    if rot:
        vf.append(rot)
    # 降采样只在「推理尺寸 > 目标尺寸」时才需要；两者相等时多走一次 lanczos
    # 纯属白送一次软化
    up_w, up_h = info.view_size[0] * k, info.view_size[1] * k
    if (w, h) != (up_w, up_h):
        vf.append(f"scale={w}:{h}:flags=lanczos")
    sharp = sharpen_filter(s)
    if sharp:
        vf.append(sharp)
    if out_format(info, s) in ("jpg", "jpeg") and info.alpha:
        vf.append("format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a=255")
    filt = ",".join(vf) if vf else "null"

    out = make_output_path(src, s, info, (w, h), ai=True)
    step2 = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-i", str(tmp_png), "-frames:v", "1", "-vf", filt,
        *_encode_args(out_format(info, s), s, info.alpha),
        "-map_metadata", "-1" if s.strip_meta else "0",
        str(out),
    ]  # fmt: skip
    return [step1, step2], out, ""


# ---------------------------------------------------------------- 估算


def estimate_output_bytes(info: ImageInfo, s: ImageSettings, factor: int = 1) -> int:
    """预估输出体积。

    按压缩后的经验比特率建模：JPEG 在 q82 大约是 0.19 字节/像素，
    质量对体积的影响接近平方关系；PNG 是无损的，只能给个偏保守的量级。
    队列里写的是「约」，实际浮动可以到 ±40%。
    """
    if not info.ok:
        return 0
    w, h = target_size(info, s, factor)
    if not (w and h):
        return 0
    px = w * h
    fmt = out_format(info, s)
    if fmt == "png":
        # 照片类 PNG 约 1.5 字节/像素；纯色图能压到 1/10，这里取保守值
        return int(px * 1.5)
    if fmt == "webp":
        bpp = 0.095 * (max(1, s.quality) / 82) ** 1.8
        if info.size and info.pixels and info.fmt in ("jpg", "jpeg", "webp"):
            bpp = min(bpp, info.size / info.pixels * 0.8)
        return int(px * bpp)
    if fmt in ("jpg", "jpeg"):
        # 0.17 字节/像素 @ q82：真实照片的典型值。画面越平（截图、视频帧）
        # 实际会明显更小，所以要拿源文件自己的压缩率封顶 —— 重编码不会
        # 凭空长出细节，源已经很扁的时候按模型算会高估好几倍。
        bpp = 0.17 * (max(1, s.quality) / 82) ** 1.8
        if info.size and info.pixels and info.fmt in ("jpg", "jpeg", "webp"):
            bpp = min(bpp, info.size / info.pixels * 1.1)
        return int(px * bpp)
    if fmt in ("tif", "tiff"):
        return int(px * 3.0)
    if fmt == "bmp":
        return int(px * 3.0)
    return int(px * 1.5)


def estimate_seconds(info: ImageInfo, s: ImageSettings) -> float:
    """单张耗时粗估（秒）。超分占绝对大头，编码那一步可以忽略。"""
    if not s.has_ai or not info.ok:
        return 0.0
    base = AI_SEC_PER_MP.get(s.model, AI_SEC_PER_MP["photo"])
    k = infer_scale(s)
    # 重量级模型固定 4× 推理，耗时只跟输入像素有关；轻量模型随倍率涨
    scale_k = 1.0 if s.model == "photo" else (k / 2) ** 0.7
    return base * info.megapixels * scale_k


def plan_summary(
    info: ImageInfo, s: ImageSettings
) -> tuple[str, str]:
    """(输出规格一行, 体积与耗时一行)。UI 直接用，不重复算。"""
    if not info.ok:
        return "", ""
    out_k = max(2, s.scale) if s.has_ai else 1
    w, h = target_size(info, s, out_k)
    fmt = out_format(info, s).upper()
    parts = [f"{w}×{h}", fmt]
    if s.has_ai:
        infer = infer_scale(s)
        # 推理倍率高于输出倍率时要说清是超采样，否则用户会以为设置没生效；
        # 只写「4× 推理」还不够 —— 得看出最后又降回了 2×，否则像走错了档
        if infer > out_k:
            parts.insert(1, f"{infer}× 推理 → {out_k}×")
        else:
            parts.insert(1, f"{out_k}× 超分")
    spec = " · ".join(parts)

    size = estimate_output_bytes(info, s, out_k)
    arrow = ""
    # 体积对比只在「没放大」时有意义：超分本来就是要变大的，
    # 报一句「比原图大 30 倍」纯属吓人。
    # 压缩场景直接给两个数，让用户自己比 —— 百分比在这种小文件上会失真
    # （几十 KB 的文件差 20 KB 就是 40%），看着像 bug。
    if info.size and not s.has_ai:
        arrow = f" · 原图 {human_size(info.size)}"
    cost = f"约 {human_size(size)}{arrow}"
    secs = estimate_seconds(info, s)
    if secs > 0:
        cost += f" · 每张约 {secs:.0f} 秒"
    return spec, cost


def warnings_for(info: ImageInfo, s: ImageSettings) -> list[str]:
    """用户看了会改变决定的那几条，别的都不说。"""
    out: list[str] = []
    if not info.ok:
        return out
    out_k = max(2, s.scale) if s.has_ai else 1
    w, h = target_size(info, s, out_k)
    px = w * h
    if px > 80_000_000:
        out.append(f"输出 {w}×{h} 超过 8000 万像素，单张可能占用数 GB 显存")
    elif px > 33_000_000:
        out.append(f"输出 {w}×{h} 约 {px / 1e6:.0f} MP，一张要跑几十秒")
    if s.has_ai and info.megapixels > 8:
        out.append(f"源图 {info.megapixels:.0f} MP，超分后像素接近 {px / 1e6:.0f} MP，耗时很长")
    if s.has_ai and s.max_side and s.max_side <= max(info.view_size):
        out.append("目标尺寸不超过原图长边，超分出来的细节会被直接缩掉，白花时间")
    if out_format(info, s) == "jpg" and info.alpha:
        out.append("源图带透明通道，转 JPG 后透明区域会变成白色")
    return out


def free_space_mb(path: Path) -> int:
    from app.core.ai import free_space_mb as _free

    return _free(path)
