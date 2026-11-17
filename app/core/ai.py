"""AI 增强：ncnn 引擎探测、显存档位、命令行管线编排。

设计原则（见 README「AI 增强」）：

* 只依赖 Vulkan 后端的 ncnn 发行版，不要求用户装 CUDA / PyTorch；
* 先超分后补帧 —— 超分是计算大头，帧数越少越省；
* 显存按档位限制输出像素数，宁可降目标分辨率也不给用户一个必 OOM 的选项。
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.core.media import MediaInfo
from app.core.probe import app_root

# ---------------------------------------------------------------- 常量

# 超分后每帧 PNG 的体积粗估（无损 RGB，实拍素材经验值）。
# 只用于给用户看「大约要占多少临时空间」，不参与任何正确性判断。
PNG_BYTES_PER_PIXEL = 1.2

# 模型 -> (ncnn 模型名, 支持的整数倍率, 展示名, 说明)
MODELS: dict[str, tuple[str, tuple[int, ...], str, str]] = {
    "photo": (
        "realesrgan-x4plus",
        (4,),
        "真人实拍",
        "RRDB 深度网络（约 1670 万参数），能重建皮肤纹理、发丝、布料\n"
        "固定 4× 推理再降采样到目标尺寸，单帧约 6 秒（8G 卡）",
    ),
    "anime": (
        "realesr-animevideov3",
        (2, 3, 4),
        "动画番剧",
        "SRVGGNet 轻量架构（约 60 万参数，仅 1.4 MB），速度快 5 倍\n"
        "训练集全是动画帧，拿它处理真人会把皮肤抹成色块 —— 只给番剧/动画用",
    ),
}

# 默认走实拍模型。之前默认是动画模型，导致真人素材被人脸糊成塑料 —— 
# 这个默认值本身就是个产品错误，实拍才是绝大多数用户的实际素材。
DEFAULT_MODEL = "photo"

# 显存档位：输出像素上限 / tile 大小 / 一句话说明
@dataclass(frozen=True)
class VramProfile:
    tier: str
    max_pixels: int
    tile: int
    note: str


def vram_profile(vram_mb: int) -> VramProfile:
    """按显存给出能力上限。

    tile 是 ncnn 的分块尺寸：越小越省显存、越慢。6G 卡上 1080p 素材
    直接开 4K 会 OOM，所以这里把上限压到 1440p，而不是让用户在失败里试。
    """
    if vram_mb >= 12000:
        # 12G 卡跑 5K 也扛得住，所以这里的上限给到 5120×2880；
        # 真正把倍率压到 4K 的是 OUTPUT_MAX_PIXELS，那是交付上限不是显存上限
        return VramProfile("高", 14_745_600, 192, "12G 以上，4K 输出全开")
    if vram_mb >= 7600:
        return VramProfile("中", 8_294_400, 128, "8G 档，4K 需要较长等待")
    if vram_mb >= 5500:
        return VramProfile("低", 3_686_400, 128, "6G 档，建议最高 1440p")
    return VramProfile("极低", 2_073_600, 96, "4G 及以下，仅建议 1080p")


# ---------------------------------------------------------------- 引擎

@dataclass
class AiEngine:
    key: str
    label: str
    exe: str = ""
    models: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.exe)

    def pick_model(self, wanted: str, fallback: str = "") -> str:
        """挑一个本机确实存在的模型权重，避免版本差异直接报错。"""
        for name in (wanted, fallback):
            if name and name in self.models:
                return name
        return self.models[0] if self.models else ""


def ai_dir() -> Path:
    """AI 引擎目录：与 bin/ 同级，便于用户自己替换版本。"""
    return app_root() / "bin" / "ai"


def _find_exe(stem: str, subdir: str = "") -> str:
    """按 subdir → ai 根 → bin → 程序根 的顺序找 exe。

    两个引擎各占一个子目录，是因为它们都把权重放在自己旁边的 models/ 里，
    平铺在同一层会互相覆盖。
    """
    exe = stem + (".exe" if sys.platform == "win32" else "")
    dirs = [ai_dir() / subdir] if subdir else []
    dirs += [ai_dir(), app_root() / "bin", app_root()]
    for base in dirs:
        p = base / exe
        if p.exists():
            return str(p)
    return ""


def _scan_models(exe: str, subdir: str = "models") -> list[str]:
    """扫引擎自带的权重名。

    两个引擎的目录约定不一样，必须分开处理：
      · realesrgan-ncnn-vulkan —— models/ 下是 *.param 文件，权重名即文件名；
      · rife-ncnn-vulkan       —— 每个模型是一个同级子目录（rife-v4.6/...），
                                  没有 models/ 这一层。
    搞混的后果是命令行完全对不上，所以这里按实际布局探测。
    """
    if not exe:
        return []
    root = Path(exe).parent
    d = root / subdir
    if d.is_dir():
        names = {p.stem for p in d.iterdir() if p.suffix.lower() in (".param", ".bin")}
        # animevideov3 会带 -x2/-x3/-x4 后缀，归一成主名（倍率由 -s 决定）
        out: set[str] = set()
        for n in names:
            for suffix in ("-x2", "-x3", "-x4"):
                if n.endswith(suffix):
                    n = n[: -len(suffix)]
            out.add(n)
        return sorted(out)
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and any(p.glob("*.param"))
    )


def detect_engines() -> dict[str, AiEngine]:
    """探测两个 ncnn 引擎。缺失不算错误，UI 会给安装指引。"""
    esrgan = AiEngine("esrgan", "超分引擎", _find_exe("realesrgan-ncnn-vulkan", "esrgan"))
    esrgan.models = _scan_models(esrgan.exe)
    if not esrgan.ok:
        esrgan.reason = "未找到 realesrgan-ncnn-vulkan.exe"

    rife = AiEngine("rife", "补帧引擎", _find_exe("rife-ncnn-vulkan", "rife"))
    rife.models = _scan_models(rife.exe)
    if not rife.ok:
        rife.reason = "未找到 rife-ncnn-vulkan.exe"
    return {"esrgan": esrgan, "rife": rife}


# ---------------------------------------------------------------- 参数

@dataclass
class AiSettings:
    # 输出尺寸就是「源尺寸 × 倍率」，没有第二个尺寸旋钮。
    # 曾经有过一个 target（输出高度上限）和一个超分倍率并列，两者都在决定
    # 最终分辨率：选 2× + 上限 1080p 会得到 1.5×，选 2× + 上限 4K 则完全没用，
    # 用户没法预测结果。现在只留倍率这一个自由度。
    scale: int = 2              # 0=不超分；2/3/4 = 整数倍率，输出 = 源 × 倍率
    model: str = DEFAULT_MODEL  # MODELS 的键
    interp: int = 1             # 1=不补帧；2/4 = 帧率倍数
    encoder: str = "hevc"
    # 增强过的画面不该再被码率糟蹋一次：CRF 18 折算成 hevc 的 cq 21，
    # 比原来的 25 高出一档，代价是文件大约 2 倍。
    crf: int = 18
    denoise: int = 0            # 0=关；1=轻；2=强。低码率源先降噪再超分
    sharpen: int = 1            # 0=关；1=轻；2=强。降采样后用 unsharp 找回锐度
    container: str = "mp4"
    output_dir: str = ""

    @property
    def has_upscale(self) -> bool:
        return self.scale > 1

    @property
    def has_interp(self) -> bool:
        return self.interp > 1

    def crf_to_cq(self) -> int:
        # 与 encoder.py 同一套校准，AI 页单独持有是为了不引入循环依赖
        from app.core.encoder import CQ_OFFSET

        return max(1, min(51, self.crf + CQ_OFFSET.get(self.encoder, 3)))


# 「显存够不够」判定用的宽松倍数。档位标称面积（8G 档 8.29 MP）是个保守值：
# 实测 720p 的 4×（14.7 MP，约 1.8 倍）在 tile 128 下能稳定跑完，所以真正
# 判死线时按 2 倍算，避免把能跑的组合误判成跑不动。
AREA_TOLERANCE = 2.0

# 推荐档位的目标高度。补到 1440p 左右最实用：1080p 屏能直接看，4K 屏也撑得住；
# 再往上体积涨得比观感快得多（1440p→2880p 是 4 倍像素）。
RECOMMEND_HEIGHT = 1440


def _even(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def output_size(media: MediaInfo, s: AiSettings) -> tuple[int, int]:
    """最终输出尺寸 = 源尺寸 × 用户选的倍率。补帧不改变尺寸。

    只有一个自由度，用户选 2× 就一定是 2×，不会被别处的上限悄悄改写。
    """
    sw, sh = _even(media.width), _even(media.height)
    if not sw or not sh:
        return 0, 0
    k = s.scale if s.has_upscale else 1
    return _even(sw * k), _even(sh * k)


def infer_scale(s: AiSettings) -> int:
    """引擎实际跑的倍率。

    和输出倍率是两件事：x4plus 只有 4× 一档，请求 2× 时仍按 4× 推理，再把
    结果 lanczos 降采样到 2×。这是超采样 —— 先在 4 倍尺度上重建细节再缩回去，
    比原生 2× 更锐，不是妥协，也不是设置没生效。
    """
    if not s.has_upscale:
        return 1
    scales = MODELS.get(s.model, MODELS[DEFAULT_MODEL])[1]
    fits = [v for v in scales if v >= s.scale]
    return fits[0] if fits else scales[-1]


def infer_pixels(media: MediaInfo, s: AiSettings) -> int:
    """单帧推理面积（像素）。显存够不够、耗时多久，都看这个数。"""
    k = infer_scale(s)
    return _even(media.width) * k * _even(media.height) * k


def recommend_scale(
    media: MediaInfo, profile: VramProfile, model: str = DEFAULT_MODEL
) -> tuple[int, str]:
    """按当前素材与显卡给一档推荐倍率，返回 (倍率, 理由)。

    判据两条，先看尺寸再让位给显存：

    1. 把输出高度补到 1440p 附近最实用 —— 2× 档的 720p 正好 1440p。
    2. 推理面积不超过档位标称面积的 AREA_TOLERANCE 倍（实测 1.8 倍仍稳）。

    注意第 2 条必须按**推理**面积算而不是输出面积：x4plus 只有 4× 一档，
    请求 2× 也是按 4× 推理，显卡扛的是 4× 那块画布。按输出面积判会把
    「1080p 选 2×」误判成可跑 —— 实际那是 33 MP 的推理，8G 卡跑不动。
    """
    sh = _even(media.height)
    if not sh:
        return 2, ""
    if sh >= RECOMMEND_HEIGHT:
        return 0, f"源已是 {sh}p，再超分收益很小"

    budget = profile.max_pixels * AREA_TOLERANCE

    def fits(k: int) -> bool:
        return infer_pixels(media, AiSettings(scale=k, model=model)) <= budget

    # 从小到大找第一个「够 1440p 且显存放得下」的档位
    for k in (2, 3, 4):
        if sh * k >= RECOMMEND_HEIGHT and fits(k):
            return k, f"{sh}p → {sh * k}p"
    # 小分辨率源：1440p 够不着，退回显存放得下的最大档位
    for k in (4, 3, 2):
        if fits(k):
            return k, f"{sh}p → {sh * k}p"
    # 一档都放不下：这张卡跑不了这个尺寸的超分，别让用户白等几小时
    return 0, f"{sh}p 在这张卡上推理面积过大，建议不放大"


def plan_warnings(
    media: MediaInfo, s: AiSettings, profile: VramProfile
) -> list[str]:
    """动手前该说清楚的几条。不改变结果，只把代价摆到明面上。"""
    out: list[str] = []
    if not media.ok:
        return out

    ow, oh = output_size(media, s)
    if not ow or not oh:
        return out

    px = infer_pixels(media, s)
    limit = profile.max_pixels
    if s.has_upscale and px > limit * AREA_TOLERANCE:
        out.append(
            f"推理面积 {px / 1e6:.0f} MP，约为 {profile.tier}档显存建议值的 "
            f"{px / limit:.1f} 倍，可能因显存不足失败或明显变慢"
        )

    # 4K 之上多数播放器、剪辑软件和平台都吃不下，说一句而不是偷偷裁掉
    if oh > 2160:
        out.append(f"输出 {ow}×{oh} 超过 4K，多数播放器与平台吃不下")

    if s.has_upscale and ow <= _even(media.width):
        out.append("输出尺寸没有超过源文件，这次超分不会带来更大画面")

    return out


# 降噪档位。低码率视频的退化是「压缩块 + 振铃」，直接超分等于把这些伪影
# 也一起放大 4 倍。先轻度去噪再超分，结果是细节更干净而不是更少。
DENOISE_FILTER = {
    1: "hqdn3d=1.0:1.0:4:4",
    2: "hqdn3d=2.0:2.0:9:9",
}

# 锐化档位。4× 重建后再 lanczos 降采样，边缘会略微发软，补一点 unsharp
# 能让观感回到「清晰」而不是「糊但干净」。强度刻意压得很低 —— 放大过的
# 画面经不起强锐化，会立刻出白边。
SHARPEN_FILTER = {
    1: "unsharp=5:5:0.5:5:5:0.0",
    2: "unsharp=5:5:0.9:5:5:0.0",
}


def denoise_filter(s: "AiSettings") -> str:
    return DENOISE_FILTER.get(s.denoise, "")


def sharpen_filter(s: "AiSettings") -> str:
    return SHARPEN_FILTER.get(s.sharpen, "")


def color_matrix(media: MediaInfo) -> str:
    """拆帧和合成必须用同一套 YUV↔RGB 系数，否则往返一次就整体偏色。

    源文件通常不写 color_space（ffprobe 报 unknown），这时按 ffmpeg 自己的规则
    推断：高度 ≥ 720 视为 HD 用 bt709，SD 用 bt601。这里把它固化下来，而不是
    让 swscale 在两次转换里各判一次 —— 判据一旦不一致，肤色就会跑偏。
    """
    space = (media.color_space or "").strip()
    if space in ("bt709", "smpte170m", "bt470bg", "bt2020nc", "bt2020c"):
        return space
    return "bt709" if (media.height or 0) >= 720 else "smpte170m"


def color_range(media: MediaInfo) -> str:
    """源用 tv(limited) 还是 pc(full)。未知按 tv —— 摄像机/编码器的默认。"""
    rng = (media.color_range or "").strip()
    return rng if rng in ("tv", "pc") else "tv"


def output_fps(media: MediaInfo, s: AiSettings) -> float:
    base = media.fps or 25.0
    return base * (s.interp if s.has_interp else 1)


def estimate_frames(media: MediaInfo, s: AiSettings) -> int:
    if media.duration <= 0:
        return 0
    return max(1, int(round(media.duration * output_fps(media, s))))


# 单帧耗时的实测基准（RTX 4060 8G, tile 128, 720p 输入）。
# 只用来给「大概要等多久」一个量级，不同显卡差异很大，所以界面上必须
# 写成「约」而不是精确值。
#
# 取的是**批处理下的边际耗时**：引擎按目录跑，进程启动与模型加载约 2.2 秒
# 只付一次。单帧单独跑是 6.4 秒，但 90 帧连着跑每帧 3.85 秒 —— 真实视频都
# 是长跑，按单帧算会把 3 分钟的片子报成 10 分钟。
PER_FRAME_SEC = {
    "photo": 3.9,   # x4plus, 720p → 2880p（实测 90 帧 339 秒）
    "anime": 1.2,   # animevideov3 2×, 720p → 1440p
}


def estimate_seconds(media: MediaInfo, s: AiSettings, infer_scale: int = 0) -> float:
    """粗估超分 + 补帧的总耗时（秒）。

    超分占绝对大头（RIFE 大约只有它的 1/10），所以只按超分建模，
    补帧折进去一个系数。给用户看的是量级，不是承诺。
    """
    if not s.has_upscale or not media.width or media.duration <= 0:
        return 0.0
    frames = estimate_frames(media, replace(s, interp=1))
    base = PER_FRAME_SEC.get(s.model, PER_FRAME_SEC["photo"])
    mp = (media.width * media.height) / (1280 * 720)
    k = infer_scale or s.scale
    # 轻量模型对倍率敏感，重量级模型反正固定 4× 推理，不随倍率变
    scale_k = 1.0 if s.model == "photo" else (k / 2) ** 0.7
    per = base * mp * scale_k
    total = frames * per
    if s.has_interp:
        total *= 1.12   # 补帧的额外开销
        total += frames * s.interp * 0.012
    return total


def estimate_temp_bytes(
    media: MediaInfo,
    s: AiSettings,
    infer_scale: int | None = None,
    out_size: tuple[int, int] | None = None,
) -> int:
    """临时目录的峰值占用。

    必须按「推理倍率」而不是「用户选的倍率」来算：x4plus 请求 2× 时实际按
    4× 推理，中间产物是 2880p 的 PNG —— 按 2× 估会低估 4 倍，用户就会在写
    到一半的时候盘满。

    实际占用与画面复杂度强相关（纯色/动画能压到 1/3），这里给的是偏保守的
    量级 —— 宁可让用户提前腾地方。
    """
    src_frames = estimate_frames(media, replace(s, interp=1))
    if src_frames <= 0:
        return 0
    sw, sh = _even(media.width), _even(media.height)
    bpp = PNG_BYTES_PER_PIXEL
    total = src_frames * sw * sh * bpp                      # 拆帧

    fps_size = (sw, sh)
    if s.has_upscale:
        k = max(1, infer_scale or s.scale)
        uw, uh = _even(sw * k), _even(sh * k)
        total += src_frames * uw * uh * bpp                 # 超分产物
        fps_size = (uw, uh)
        # 补帧前会先降到目标尺寸，这一份也占地方
        if out_size and out_size != (uw, uh):
            total += src_frames * out_size[0] * out_size[1] * bpp
            fps_size = out_size
    if s.has_interp:
        total += src_frames * s.interp * fps_size[0] * fps_size[1] * bpp
    return int(total)


# 基础 bpp 模型是按压缩页的 CRF 区间标定的，外推到 AI 页的 CRF 18 会偏高：
# 实测 720p→1440p 的真人素材（hevc cq21）视频码率 16.0 Mbps，bpp 0.145，
# 而模型外推得 0.176。CRF 越低曲线越平，外推会一直放大这个偏差，所以乘一个
# 实测修正。宁可略微高估也别低估 —— 但 36% 的高估会让用户以为文件大得不能接受。
AI_BPP_FACTOR = 0.83


def estimate_output_bytes(media: MediaInfo, s: AiSettings) -> int:
    """预估成片体积，给队列那一列用。

    按「输出分辨率 × 帧率 × CRF」反推码率，bpp 系数与压缩页共用同一套标定，
    再乘一个超分画面的修正系数。补帧把帧率翻倍，码率也近似跟着翻倍 ——
    这是 AI 页体积的主要来源，不乘上去会低估一半。
    """
    if not media.ok or media.duration <= 0:
        return 0
    w, h = output_size(media, s)
    if not w or not h:
        return 0

    from app.core.encoder import BPP_AT_CRF26, CRF_BITRATE_STEP  # noqa: PLC0415

    bpp = BPP_AT_CRF26.get(s.encoder, 0.066) * CRF_BITRATE_STEP ** (26 - s.crf)
    bpp = max(0.01, min(1.5, bpp)) * AI_BPP_FACTOR
    v_kbps = bpp * w * h * output_fps(media, s) / 1000.0
    return int((v_kbps + _audio_kbps(media, s)) * 1000 / 8 * media.duration)


def _audio_kbps(media: MediaInfo, s: AiSettings) -> float:
    """音轨直通时按源码率算，容器不兼容转 AAC 时按目标码率算。"""
    if not media.audio:
        return 0.0
    from app.core.encoder import AUDIO_TARGET_KBPS, MP4_AUDIO_OK  # noqa: PLC0415

    if s.container in ("mp4", "mov") and any(
        a.codec not in MP4_AUDIO_OK for a in media.audio
    ):
        return float(AUDIO_TARGET_KBPS)
    return sum(a.bit_rate for a in media.audio) / 1000.0


# ---------------------------------------------------------------- 管线

@dataclass
class Stage:
    """一个执行阶段。kind 决定进度怎么算：

    * ffmpeg —— 解析 -progress 的 out_time，除以 duration；
    * count  —— 数目标目录里的文件数，除以 expect。
    """

    label: str
    cmd: list[str] = field(default_factory=list)
    kind: str = "ffmpeg"
    weight: float = 0.0
    duration: float = 0.0
    watch_dir: str = ""
    expect: int = 0


@dataclass
class AiPlan:
    stages: list[Stage] = field(default_factory=list)
    output: str = ""
    final_w: int = 0
    final_h: int = 0
    fps: float = 0.0
    temp_dir: str = ""
    temp_bytes: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def make_output_path(
    src: Path,
    s: AiSettings,
    scale: int | None = None,
    out_size: tuple[int, int] | None = None,
) -> Path:
    """文件名用「实际输出高度」而不是倍率。

    推理倍率和输出倍率脱钩之后（x4plus 请求 2× 也是按 4× 推理），
    再写 `_4x` 会让用户以为拿到的是 4× 的片子，实际是 1440p —— 标 1440p 没有歧义。
    """
    out_dir = Path(s.output_dir) if s.output_dir else src.parent
    eff = s.scale if scale is None else scale
    tags = []
    if s.has_upscale:
        tags.append(f"{out_size[1]}p" if out_size else f"{eff}x")
    if s.has_interp:
        tags.append(f"{s.interp}fps")
    tag = "_".join(tags) or "ai"
    ext = s.container
    base = f"{src.stem}_AI_{tag}"
    candidate = out_dir / f"{base}.{ext}"
    n = 1
    while candidate.exists():
        candidate = out_dir / f"{base}_{n}.{ext}"
        n += 1
    return candidate


def build_plan(
    media: MediaInfo,
    s: AiSettings,
    engines: dict[str, AiEngine],
    ffmpeg: str,
    work_dir: Path,
    output: Path | None = None,
    vram_mb: int = 0,
) -> AiPlan:
    """把参数翻译成 4 个（或 3 个）子进程命令。

    顺序固定：拆帧 → 超分 → 补帧 → 合成。中间产物落盘而不是走管道，
    因为 realesrgan-ncnn-vulkan 只接受图片目录，这是它的接口限制。
    """
    plan = AiPlan()
    src = Path(media.path)
    if not media.ok:
        plan.error = "源文件不可读"
        return plan
    if not s.has_upscale and not s.has_interp:
        plan.error = "超分和补帧都关掉了，没有可做的事"
        return plan

    profile = vram_profile(vram_mb)
    tw, th = output_size(media, s)
    inf = infer_scale(s)
    plan.warnings.extend(plan_warnings(media, s, profile))
    if not tw or not th:
        plan.error = "无法计算输出尺寸"
        return plan
    plan.final_w, plan.final_h = tw, th
    plan.fps = output_fps(media, s)
    plan.temp_bytes = estimate_temp_bytes(media, s, inf)

    out = output or make_output_path(src, s, inf, (tw, th))
    plan.output = str(out)
    plan.temp_dir = str(work_dir)

    work_dir.mkdir(parents=True, exist_ok=True)
    frames = work_dir / "frames"
    up = work_dir / "up"
    fps_dir = work_dir / "fps"
    for d in (frames, up, fps_dir):
        d.mkdir(parents=True, exist_ok=True)

    src_frames = estimate_frames(media, replace(s, interp=1))
    uw0, uh0 = _even(media.width * inf), _even(media.height * inf)

    # 显存兜底靠分块，不靠降倍率。x4plus 只有 4× 一档，6G 卡选 4× 时倍率
    # 根本降不下来 —— 硬跑就是 OOM。tile 越小，单次进显存的像素越少，
    # 代价只是慢，但能跑完。
    #
    # 阈值给 2 倍而不是 1 倍：实测 8G 卡跑 720p 4×（输出 5120×2880，是 4K
    # 面积的 1.8 倍）用 tile 128 完全没问题，反而比 64 快 40%。真正会炸的是
    # 「面积远超档位」的情况，此时才值得牺牲速度换稳定。
    tile = profile.tile
    if s.has_upscale and uw0 * uh0 > profile.max_pixels * 2:
        tile = min(tile, 64)
        plan.warnings.append(
            f"{uw0}×{uh0} 超出 {profile.tier}档显存建议范围，已改用 {tile}px 分块处理，耗时会明显增加"
        )

    # ---- 权重：按各阶段的实测耗时占比分配，越靠后的阶段占比越大
    w_split, w_sr, w_fps, w_mux, w_mid = 0.06, 0.0, 0.0, 0.22, 0.0
    # 推理尺寸比最终输出大时，补帧前要先降下来（见下面的 2.5 阶段）
    need_mid = (
        s.has_upscale and s.has_interp and (uw0, uh0) != (tw, th)
    )
    if need_mid:
        w_mid = 0.05
    if s.has_upscale and s.has_interp:
        w_sr, w_fps = 0.55 - w_mid, 0.17
    elif s.has_upscale:
        w_sr = 0.72
    else:
        w_fps = 0.72

    # ---- 1. 拆帧
    # 无论超分还是补帧，引擎都只吃图片目录，所以这一步永远要跑。
    # PNG 本身不保存色彩标签，YUV→RGB 的系数必须此时定死，合成时再照同一套转回去。
    yuv2rgb = (
        f"scale=in_color_matrix={color_matrix(media)}"
        f":in_range={color_range(media)},format=rgb24"
    )
    # 降噪必须在转 RGB 之后做：hqdn3d 默认按 YUV 三平面处理，
    # 但对 rgb24 同样有效，且放在转换后能顺手压掉转换带来的量化噪点
    denoise = denoise_filter(s)
    if denoise:
        yuv2rgb += "," + denoise
    plan.stages.append(
        Stage(
            label="拆帧",
            cmd=[
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
                "-i", str(src), "-map", "0:v:0",
                "-fps_mode", "passthrough",
                "-vf", yuv2rgb,
                "-pix_fmt", "rgb24",
                str(frames / "%06d.png"),
            ],  # fmt: skip
            kind="ffmpeg",
            weight=w_split,
            duration=media.duration or 1.0,
        )
    )

    # ---- 2. 超分
    cur_input = frames
    if s.has_upscale:
        engine = engines.get("esrgan")
        if not engine or not engine.ok:
            plan.error = "超分引擎缺失：需要 bin/ai/realesrgan-ncnn-vulkan.exe"
            return plan
        raw_name = MODELS.get(s.model, MODELS[DEFAULT_MODEL])[0]
        name = engine.pick_model(raw_name, "realesrgan-x4plus")
        if not name:
            plan.error = "超分引擎没有可用模型，请检查 bin/ai/models 目录"
            return plan
        cmd = [
            engine.exe, "-i", str(frames), "-o", str(up),
            "-n", name, "-s", str(inf), "-t", str(tile),
            "-m", str(Path(engine.exe).parent / "models"),
            "-f", "png", "-g", "0",
        ]  # fmt: skip
        plan.stages.append(
            Stage(
                label=f"超分 {inf}×",
                cmd=cmd,
                kind="count",
                weight=w_sr,
                watch_dir=str(up),
                expect=src_frames,
            )
        )
        cur_input = up

    # ---- 2.5 补帧前先降到目标尺寸
    # 推理按 4× 走（720p→2880p），但最终只要 1440p。如果直接在这个尺寸上补帧：
    #   · RIFE 的耗时与像素数成正比，2880p 是 1440p 的 4 倍
    #   · 中间帧在 2880p 上生成再缩小，边缘反而不如直接在小尺寸上插
    # 先降再补，两个问题一起解决。只补帧不超分时不存在这一步。
    if need_mid:
        mid = work_dir / "mid"
        mid.mkdir(exist_ok=True)
        plan.stages.append(
            Stage(
                label="降采样",
                cmd=[
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
                    "-i", str(up / "%06d.png"),
                    "-vf", f"scale={tw}:{th}:flags=lanczos",
                    str(mid / "%06d.png"),
                ],  # fmt: skip
                kind="count",
                weight=w_mid,
                watch_dir=str(mid),
                expect=src_frames,
            )
        )
        cur_input = mid

    # ---- 3. 补帧
    if s.has_interp:
        engine = engines.get("rife")
        if not engine or not engine.ok:
            plan.error = "补帧引擎缺失：需要 bin/ai/rife-ncnn-vulkan.exe"
            return plan
        name = engine.pick_model("rife-v4.6", "rife-v4") or "rife-v4.6"
        # -n 在这个程序里是「目标总帧数」，不是模型名（默认 N*2，即帧率翻倍）
        # -m 指到具体模型目录，否则它会去当前工作目录找 rife-v2.3
        # -f 强制 6 位命名，否则默认 8 位，合成阶段按 %06d 找不到文件
        cmd = [
            engine.exe, "-i", str(cur_input), "-o", str(fps_dir),
            "-m", str(Path(engine.exe).parent / name),
            "-f", "%06d.png", "-g", "0",
        ]  # fmt: skip
        if uw0 * uh0 > 3_000_000:
            # UHD 模式分块推理：4K 级别的帧不开它大概率直接显存溢出
            cmd += ["-u"]
        if s.interp != 2:
            # -n 是目标总帧数，缺省只按 2× 算；开 4× 时必须显式给，
            # 否则引擎照旧出一倍 —— 帧数对不上，时长也跟着错
            cmd += ["-n", str(max(2, src_frames * s.interp))]
        plan.stages.append(
            Stage(
                label=f"补帧 {s.interp}×",
                cmd=cmd,
                kind="count",
                weight=w_fps,
                watch_dir=str(fps_dir),
                expect=max(1, src_frames * s.interp),
            )
        )
        cur_input = fps_dir

    # ---- 4. 合成
    audio_args, audio_warn = _audio_args(media, s)
    plan.warnings.extend(audio_warn)
    # 只有最终尺寸与引擎输出不一致时才需要缩放（超采样降采样就发生在这里）。
    # 但 scale 无论如何都要留在链上：RGB→YUV 的矩阵得在这里指定，
    # 不带宽高的 scale 就是纯粹的色彩空间转换。
    uw, uh = _even(media.width * inf), _even(media.height * inf)
    cm, cr = color_matrix(media), color_range(media)
    if (tw, th) != (uw, uh):
        vf = f"scale={tw}:{th}:flags=lanczos:out_color_matrix={cm}:out_range={cr}"
    else:
        vf = f"scale=out_color_matrix={cm}:out_range={cr}"
    # 锐化放在缩放之后：4× 重建再往下缩，边缘必然软一档，补一点 unsharp
    # 能拉回「清晰」的观感。放在缩放之前等于把锐度一起缩没了。
    sharp = sharpen_filter(s)
    if sharp:
        vf += "," + sharp

    enc = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}.get(
        s.encoder, "hevc_nvenc"
    )
    mux = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-framerate", f"{plan.fps:.6f}", "-start_number", "1",
        "-i", str(cur_input / "%06d.png"),
        "-i", str(src),
        "-map", "0:v:0",
    ]  # fmt: skip
    if audio_args:
        mux += ["-map", "1:a?"]
    mux += ["-vf", vf]
    mux += ["-c:v", enc, "-preset", "p6", "-tune", "hq"]
    # 关键：输入是 RGB 的 PNG 序列，不写 -pix_fmt 的话 ffmpeg 会自动协商成
    # HEVC Rext + gbrp —— 文件能播，但播放器按 YUV 解释三个平面，画面整体绿配品红。
    mux += ["-pix_fmt", "yuv420p"]
    # 把转换用的系数一并写进码流，播放器就不会再自己猜
    mux += [
        "-color_range", cr,
        "-colorspace", cm,
        "-color_primaries", "bt709" if cm == "bt709" else "smpte170m",
        "-color_trc", "bt709" if cm == "bt709" else "smpte170m",
    ]  # fmt: skip
    mux += ["-rc", "vbr", "-cq", str(s.crf_to_cq()), "-b:v", "0"]
    if s.encoder in ("h264", "hevc"):
        mux += ["-spatial-aq", "1", "-aq-strength", "8", "-rc-lookahead", "20"]
    if s.encoder == "hevc" and s.container in ("mp4", "mov"):
        mux += ["-tag:v", "hvc1"]
    mux += audio_args
    if s.container in ("mp4", "mov"):
        mux += ["-movflags", "+faststart"]
    if s.has_interp:
        # 补帧后帧数比源多，音轨长度不变，短边对齐避免尾巴挂空
        mux += ["-shortest"]
    mux += ["-progress", "pipe:1", "-nostats", str(out)]

    plan.stages.append(
        Stage(
            label="合成",
            cmd=mux,
            kind="ffmpeg",
            weight=w_mux,
            duration=max(0.1, estimate_frames(media, s) / max(plan.fps, 1)),
        )
    )
    return plan


def _audio_args(media: MediaInfo, s: AiSettings) -> tuple[list[str], list[str]]:
    """音轨直通优先，容器不兼容时退回 AAC。"""
    from app.core.encoder import AUDIO_TARGET_KBPS, MP4_AUDIO_OK

    if not media.audio:
        # 图序列没有音轨，源文件也没有，直接不映射即可；给 -an 会和 -map 打架
        return [], []
    if s.container in ("mp4", "mov"):
        bad = [a.label for a in media.audio if a.codec not in MP4_AUDIO_OK]
        if bad:
            return (
                ["-c:a", "aac", "-b:a", f"{AUDIO_TARGET_KBPS}k"],
                [f"音轨为 {'/'.join(bad)}，容器不支持，已转 AAC"],
            )
    return ["-c:a", "copy"], []


def cleanup(work_dir: str) -> bool:
    """删临时目录，返回是否真的删干净了。

    不能直接 rmtree(ignore_errors=True) 了事：Windows 上刚退出的引擎进程往往
    还攥着几个文件的句柄，杀毒软件也可能正在扫刚写出的 PNG。一次失败就放弃的
    结果是几 GB 帧序列悄悄留在用户硬盘上 —— 必须重试，并且把失败报上去。

    重试窗口要按目录规模给：几万个小文件删到一半被打断，残留的是"删了一半"的
    状态，越大的目录越容易撞上句柄；固定 1 秒对 GB 级目录根本不够。
    """
    if not work_dir:
        return True
    d = Path(work_dir)
    # 间隔递增，累计约 4.6 秒 —— 覆盖杀软扫描和句柄延迟释放
    for delay in (0.2, 0.4, 0.8, 1.2, 1.6):
        if not d.exists():
            return True
        try:
            shutil.rmtree(d)
            return True
        except OSError:
            time.sleep(delay)
    shutil.rmtree(d, ignore_errors=True)
    return not d.exists()


def sweep_stale(root: Path, hours: float = 2.0) -> int:
    """清掉上次没删掉的临时目录，返回清理掉的个数。

    重试能解决绝大部分句柄占用，但总有删不动的（进程被强杀、杀毒软件锁着）。
    不处理的话这些目录会一直躺在用户盘上占几 GB，而且用户根本不知道它在哪。
    只清理 2 小时以前的：万一同一个目录下还有另一个实例正在跑，不能动它的。
    """
    if not root.is_dir():
        return 0
    cutoff = time.time() - hours * 3600
    n = 0
    for d in root.glob("zzbox_ai_*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff and cleanup(str(d)):
                n += 1
        except OSError:
            continue
    return n


def free_space_mb(path: Path) -> int:
    try:
        return int(shutil.disk_usage(str(path)).free / 1048576)
    except Exception:  # noqa: BLE001
        return 0


def count_files(d: str) -> int:
    """数目录里已产出的帧数。scandir 比 listdir 省一次 stat。"""
    try:
        with os.scandir(d) as it:
            return sum(1 for e in it if e.name.lower().endswith(".png"))
    except OSError:
        return 0
