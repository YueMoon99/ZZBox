"""把界面参数翻译成 ffmpeg 命令行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.media import MediaInfo

MP4_AUDIO_OK = {"aac", "mp3", "ac3", "eac3", "alac"}
ENC_NAME = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}
ENC_EXT_HINT = {"h264": "h264", "hevc": "hevc", "av1": "av1"}

# CRF 与 NVENC CQ 的换算偏移。实测依据（1080p25 实拍素材，30 秒切片，
# 以小丸工具箱 x264 CRF25 为画质基线，用 SSIM 对齐）：
#   h264_nvenc cq28 -> SSIM 0.9889 ≈ x264 CRF25 的 0.9885，体积 1.21 倍
#   hevc_nvenc cq28 -> SSIM 0.9892 ≈ 基线，体积 1.06 倍
#   av1_nvenc  cq34 -> SSIM 0.9892 ≈ 基线，体积 0.89 倍
# 所以同画质下 CQ 要比 CRF 大 3（AV1 大 9）。旧版用 crf-2，属于反向补偿，
# 直接导致文件比 CPU 编码大 2 倍以上。
CQ_OFFSET = {"h264": 3, "hevc": 3, "av1": 9}

# 音轨转码目标码率。源音频若是 PCM（工程文件常见，1080p 下可达 2.3 Mbps），
# 直接封装会让成片凭空多出几十 MB，因此低于该阈值才允许直通。
AUDIO_TARGET_KBPS = 160
AUDIO_COPY_MAX_KBPS = 256


# 体积估算：每像素比特（bpp）基准。标定素材为 1080p25 实拍（51.84 M像素/秒）：
# x264 CRF25 基准 3.49 Mbps ≈ bpp 0.067，NVENC HEVC CRF26 约为基准的 0.98 倍
# → bpp 0.066；CRF 每降 1 码率约 ×1.13（该系数在实测的 CRF22/26/28/29 四点上都对得上）。
# H.264 同 CRF 约多 15%，AV1 约少 16%。
BPP_AT_CRF26 = {"h264": 0.076, "hevc": 0.066, "av1": 0.056}
CRF_BITRATE_STEP = 1.13


@dataclass
class EncodeSettings:
    encoder: str = "hevc"
    mode: str = "crf"            # crf | bitrate
    crf: int = 22
    bitrate_kbps: int = 6000
    scale_percent: int = 100     # 0 表示使用自定义宽高
    custom_w: int = 0
    custom_h: int = 0
    audio_mode: str = "aac"      # aac | copy | none
    container: str = "mp4"
    output_dir: str = ""

    def crf_to_cq(self) -> int:
        """CRF 换成 NVENC 的 CQ。

        两者不是同一个东西：CRF 是逐帧逐块自适应的感知质量，
        CQ 只是给编码器的质量提示。实测同数字时 NVENC 体积明显更大，
        故按编码器分别偏移（数值见 CQ_OFFSET 上方的实测记录）。
        """
        offset = CQ_OFFSET.get(self.encoder, 3)
        return max(1, min(51, self.crf + offset))


@dataclass
class BuildResult:
    cmd: list[str] = field(default_factory=list)
    output: str = ""
    target_w: int = 0
    target_h: int = 0
    warnings: list[str] = field(default_factory=list)


def _even(v: float) -> int:
    n = int(round(v / 2.0)) * 2
    return max(2, n)


def compute_target(media: MediaInfo, s: EncodeSettings) -> tuple[int, int]:
    sw, sh = media.width, media.height
    if not sw or not sh:
        return 0, 0

    if s.scale_percent and s.scale_percent > 0:
        if s.scale_percent == 100:
            return sw - sw % 2, sh - sh % 2
        return _even(sw * s.scale_percent / 100.0), _even(sh * s.scale_percent / 100.0)

    w, h = s.custom_w, s.custom_h
    if w > 0 and h > 0:
        return _even(w), _even(h)
    if w > 0:
        return _even(w), _even(w * sh / sw)
    if h > 0:
        return _even(h * sw / sh), _even(h)
    return sw - sw % 2, sh - sh % 2


def make_output_path(src: Path, s: EncodeSettings, enc: str) -> Path:
    out_dir = Path(s.output_dir) if s.output_dir else src.parent
    tag = {"h264": "h264", "hevc": "hevc", "av1": "av1"}.get(enc, enc)
    ext = s.container
    base = f"{src.stem}_{tag}_gpu"
    candidate = out_dir / f"{base}.{ext}"
    n = 1
    while candidate.exists():
        candidate = out_dir / f"{base}_{n}.{ext}"
        n += 1
    return candidate


def resolve_audio(media: MediaInfo, s: EncodeSettings) -> tuple[str, int, list[str]]:
    """音轨最终怎么处理：("none"|"aac"|"copy", 估算码率 kbps, 警告)。

    编码命令和体积估算都走这里，避免两边的降级逻辑各写一套后互相打架。
    """
    if s.audio_mode == "none" or not media.audio:
        return "none", 0, []

    warnings: list[str] = []
    if s.audio_mode == "copy":
        bad = [a.label for a in media.audio if a.codec not in MP4_AUDIO_OK]
        heavy = [a for a in media.audio if a.bit_rate > AUDIO_COPY_MAX_KBPS * 1000]
        if s.container in ("mp4", "mov") and bad:
            warnings.append(
                f"音轨为 {'/'.join(sorted(set(bad)))}，目标容器不支持，已自动转 AAC"
            )
        elif heavy:
            mbps = max(a.bit_rate for a in heavy) / 1000000
            warnings.append(
                f"源音频码率 {mbps:.1f} Mbps 偏大，已转 AAC {AUDIO_TARGET_KBPS}k 以缩小体积"
            )
        else:
            kbps = int(sum(a.bit_rate for a in media.audio) / 1000)
            return "copy", kbps or AUDIO_TARGET_KBPS * len(media.audio), []

    return "aac", AUDIO_TARGET_KBPS * max(1, len(media.audio)), warnings


def estimate_output_bytes(media: MediaInfo, s: EncodeSettings) -> int:
    """预估成片体积，仅用于队列展示，误差通常在 ±20% 以内。

    码率模式基本可以算准；CRF 模式没有真跑编码，只能用 bpp 经验模型，
    源素材越不常规（动画、纯黑场、噪点很重的夜拍）偏差越大。
    """
    if not media.ok or media.duration <= 0:
        return 0

    if s.mode == "bitrate":
        v_kbps = float(max(100, int(s.bitrate_kbps)))
    else:
        w, h = compute_target(media, s)
        if not w or not h:
            return 0
        bpp = BPP_AT_CRF26.get(s.encoder, 0.157) * CRF_BITRATE_STEP ** (26 - s.crf)
        bpp = max(0.01, min(1.5, bpp))
        v_kbps = bpp * w * h * (media.fps or 25.0) / 1000.0

    _, a_kbps, _ = resolve_audio(media, s)
    return int((v_kbps + a_kbps) * 1000 / 8 * media.duration)


def build_command(
    media: MediaInfo, s: EncodeSettings, ffmpeg: str, output: Path | None = None
) -> BuildResult:
    warnings: list[str] = []
    src = Path(media.path)
    enc = ENC_NAME.get(s.encoder, "hevc_nvenc")
    out = output or make_output_path(src, s, s.encoder)
    tw, th = compute_target(media, s)

    cmd: list[str] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    cmd += ["-i", str(src)]

    cmd += ["-map", "0:v:0", "-map_metadata", "0"]

    # ---- 缩放 ----
    need_scale = tw and th and (tw != media.width or th != media.height)
    if need_scale:
        cmd += ["-vf", f"scale={tw}:{th}:flags=lanczos"]

    # ---- 视频编码 ----
    cmd += ["-c:v", enc, "-preset", "p6", "-tune", "hq"]

    if s.mode == "bitrate":
        kbps = max(100, int(s.bitrate_kbps))
        cmd += [
            "-rc",
            "cbr",
            "-b:v",
            f"{kbps}k",
            "-maxrate",
            f"{kbps}k",
            "-bufsize",
            f"{kbps * 2}k",
        ]
    else:
        # -b:v 0 必须显式给出，否则会退回默认 2Mbps 目标码率，-cq 被压制导致画质崩
        cmd += ["-rc", "vbr", "-cq", str(s.crf_to_cq()), "-b:v", "0"]

    if s.encoder in ("h264", "hevc"):
        cmd += [
            "-spatial-aq", "1",
            "-aq-strength", "8",
            "-rc-lookahead", "20",
            "-multipass", "qres",
            "-b_ref_mode", "middle",
        ]  # fmt: skip

    if s.encoder == "hevc" and s.container in ("mp4", "mov"):
        cmd += ["-tag:v", "hvc1"]  # 不加这行 iOS/Safari 播不了

    # ---- 音频 ----
    audio_mode, _, audio_warn = resolve_audio(media, s)
    warnings.extend(audio_warn)
    if audio_mode == "none":
        cmd += ["-an"]
    else:
        cmd += ["-map", "0:a?"]
        if audio_mode == "aac":
            cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_TARGET_KBPS}k"]
        else:
            cmd += ["-c:a", "copy"]

    if s.container in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]

    cmd += ["-max_muxing_queue_size", "1024", "-progress", "pipe:1", "-nostats", str(out)]

    return BuildResult(cmd=cmd, output=str(out), target_w=tw, target_h=th, warnings=warnings)


def make_output_with_suffix(src: Path, suffix: str, ext: str | None = None) -> Path:
    """在源文件旁边生成「原名 + 后缀.扩展名」，重名就加序号。

    工具类操作（抽音频 / 去音轨）绝不覆盖已有文件，更不能覆盖源文件本身。
    """
    extension = (ext or src.suffix).lstrip(".") or "mp4"
    base = f"{src.stem}{suffix}"
    candidate = src.parent / f"{base}.{extension}"
    n = 1
    while candidate.exists():
        candidate = src.parent / f"{base}_{n}.{extension}"
        n += 1
    return candidate


def build_strip_audio_cmd(
    media: MediaInfo, ffmpeg: str, output: Path | None = None
) -> BuildResult:
    """只剥掉音频轨：视频流原样 copy，一帧都不重编。

    因此输出容器的扩展名跟随源文件（同容器封装必然合法），而不是统一塞 mp4。
    """
    src = Path(media.path)
    out = output or make_output_with_suffix(src, "_无音轨")
    cmd: list[str] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    cmd += ["-i", str(src)]
    # 只取主视频流做 copy，音轨/字幕/数据流一律不带过去
    cmd += ["-map", "0:v:0", "-c:v", "copy", "-map_metadata", "0", "-an", "-sn", "-dn"]
    if out.suffix.lower() in (".mp4", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd += ["-progress", "pipe:1", "-nostats", str(out)]
    return BuildResult(cmd=cmd, output=str(out), target_w=media.width, target_h=media.height)


def build_audio_extract_cmd(
    media: MediaInfo, ffmpeg: str, fmt: str = "m4a", output: Path | None = None
) -> list[str]:
    src = Path(media.path)
    out = output or make_output_with_suffix(src, "", fmt)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-i", str(src)]
    cmd += ["-vn", "-map", "0:a:0"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "copy" if (media.audio and media.audio[0].codec == "aac") else "aac"]
    cmd += ["-progress", "pipe:1", "-nostats", str(out)]
    return cmd
