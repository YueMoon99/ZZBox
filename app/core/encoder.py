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
class EncCaps:
    """当前显卡/ffmpeg 的真实能力。探测结果由 probe.py 填，测试可手工构造。

    这几项共同决定命令能不能跑起来 —— 任何一项写死，老卡上都会当场初始化失败。
    """

    bit10: bool = True      # 编码器能直接吃 10bit 输入
    bframes: bool = True    # 支持 B 帧参考（-b_ref_mode middle，Turing 起）
    tonemap: bool = True    # ffmpeg 带 zscale，能把 HDR 转成 SDR
    advanced: bool = True   # p6 预设 + 空间 AQ + lookahead + multipass 这组能跑


# HDR10 / HLG → BT.709 SDR。H.264 没有 10bit（Blackwell 之前），要它出片只能先转 SDR。
# npl=100 是 100 nit 的参考白，hable 曲线对高光的压缩比 reinhard 自然。
# 头部显式写死输入的矩阵/原色/传输：工程素材经常整片不带色彩标签，缺标签时
# zscale 会直接报 "no path between colorspaces" 并让整条命令失败。
TONEMAP_TAIL = (
    "format=gbrpf32le,zscale=t=linear:npl=100,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)
TONEMAP_CHAIN = "zscale=t=linear:npl=100," + TONEMAP_TAIL

# NVENC 的硬尺寸边界（NVIDIA 官方能力表）：
#   H.264 每边上限 4096 —— 5K/8K/全景素材选 H.264 会直接初始化失败，
#           报的却是 "Nothing was written into output file"，用户根本看不出原因。
#   HEVC / AV1 每边上限 8192。
#   最小边约 144×48，低于它 NVENC 拒绝初始化（缩放到 25% 的小素材会撞上）。
ENC_MAX_DIM = {"h264": 4096, "hevc": 8192, "av1": 8192}
ENC_MIN_W = 144
ENC_MIN_H = 48
ENC_LABEL = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1"}


def tonemap_chain(media: MediaInfo) -> str:
    """按素材自己的色彩标签拼色调映射链，标签缺失时按 HDR10 的常规值兜底。"""
    matrix = media.color_space or "bt2020nc"
    prim = media.color_primaries or "bt2020"
    trc = media.color_transfer or "smpte2084"
    known = {"bt2020nc", "bt709", "smpte170m", "bt470bg"}
    if matrix not in known:
        matrix = "bt2020nc"
    if prim not in {"bt2020", "bt709", "smpte170m"}:
        prim = "bt2020"
    if trc not in {"smpte2084", "arib-std-b67"}:
        trc = "smpte2084"
    return f"zscale=m={matrix}:p={prim}:t={trc}:r=tv," + TONEMAP_TAIL


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


def _raw_target(media: MediaInfo, s: EncodeSettings) -> tuple[int, int]:
    """按用户选的缩放算出目标尺寸。

    注意用的是「显示尺寸」而不是存储尺寸：手机竖拍是横着存的加一个旋转标记，
    ffmpeg 一上滤镜就先转正，再按存储宽高去 scale 会把画面压扁。
    """
    sw, sh = media.display_width, media.display_height
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


def target_plan(media: MediaInfo, s: EncodeSettings) -> tuple[int, int, str]:
    """目标尺寸 + 一句「为什么和你想的不一样」。

    两条硬边界在这里兜住，不让它们变成一条看不懂的 ffmpeg 报错：
      超过编码器上限 → 等比缩到上限（8K 选 H.264 只能到 4096，这是必然的）；
      低于 NVENC 下限 → 放弃缩放、按原尺寸出（否则初始化直接失败）。
    """
    w, h = _raw_target(media, s)
    if not w or not h:
        return 0, 0, ""

    cap = ENC_MAX_DIM.get(s.encoder, 8192)
    if w > cap or h > cap:
        f = min(cap / w, cap / h)
        nw, nh = _even(w * f), _even(h * f)
        note = (
            f"{w}×{h} 超出 {ENC_LABEL.get(s.encoder, s.encoder.upper())} 的上限 {cap}px，"
            f"已按 {nw}×{nh} 输出"
        )
        return nw, nh, note

    if w < ENC_MIN_W or h < ENC_MIN_H:
        sw, sh = media.display_width, media.display_height
        if sw >= ENC_MIN_W and sh >= ENC_MIN_H:
            note = f"目标 {w}×{h} 小于显卡最小尺寸 {ENC_MIN_W}×{ENC_MIN_H}，已按原尺寸输出"
            return sw - sw % 2, sh - sh % 2, note
        # 素材本身就比下限还小，只能往上放大 —— 否则 NVENC 连初始化都不做
        f = max(ENC_MIN_W / max(sw, 1), ENC_MIN_H / max(sh, 1))
        nw, nh = _even(sw * f), _even(sh * f)
        note = f"分辨率 {sw}×{sh} 低于显卡最小尺寸，已放大到 {nw}×{nh} 后编码"
        return nw, nh, note

    return w, h, ""


def compute_target(media: MediaInfo, s: EncodeSettings) -> tuple[int, int]:
    w, h, _ = target_plan(media, s)
    return w, h


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
    media: MediaInfo,
    s: EncodeSettings,
    ffmpeg: str,
    output: Path | None = None,
    caps: EncCaps | None = None,
) -> BuildResult:
    warnings: list[str] = []
    caps = caps or EncCaps()
    src = Path(media.path)
    enc = ENC_NAME.get(s.encoder, "hevc_nvenc")
    out = output or make_output_path(src, s, s.encoder)
    tw, th, size_note = target_plan(media, s)
    if size_note:
        warnings.append(size_note)

    cmd: list[str] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    cmd += ["-i", str(src)]

    cmd += ["-map", "0:V:0", "-map_metadata", "0"]

    # ---- 缩放 / HDR 处理 ----
    # 跟「显示尺寸」比：竖拍视频的存储宽高是横的，转正之后才对得上。
    dw, dh = media.display_width, media.display_height
    need_scale = tw and th and (tw != dw or th != dh)
    filters: list[str] = []
    if need_scale:
        filters.append(f"scale={tw}:{th}:flags=lanczos")

    # NVENC 的 10bit 支持按代际分：H.264 要 Blackwell（RTX 50 系），HEVC 要 Pascal 起，
    # Maxwell 的 HEVC 只有 8bit。直接喂 10bit 会报 "No capable devices found" 并立刻退出
    # —— 这就是「选了编码器就失败」最常见的那个原因。
    # 处理办法：能色调映射就映射成 SDR（画面正确），映射不了至少把标签改对，
    # 免得播放器拿 PQ 曲线去解释 8bit 数据，整片发灰。
    label = ENC_LABEL.get(s.encoder, s.encoder.upper())
    deep = media.bit_depth > 8
    needs_down = not caps.bit10 and deep
    # 只有真的是 HDR 才做色调映射。10bit ≠ HDR —— ProRes / DNxHR 这类 10bit SDR
    # 工程素材一旦被塞进 tonemap 链，zscale 会因为缺色彩标签报
    # "no path between colorspaces"，整条命令当场失败。
    tonemap = needs_down and caps.tonemap and media.is_hdr
    if tonemap:
        filters.append(tonemap_chain(media))

    if filters:
        cmd += ["-vf", ",".join(filters)]

    # ---- 视频编码 ----
    # 老卡 / 老驱动上 p6 + 空间 AQ + multipass 这一组可能有一项不吃，
    # 探测没过就退回最朴素的参数：画质略差，但一定出得来片。
    if caps.advanced:
        cmd += ["-c:v", enc, "-preset", "p6", "-tune", "hq"]
    else:
        cmd += ["-c:v", enc]

    # 像素格式不能交给它自己挑：
    #   4:2:2 / 4:4:4（ProRes、DNxHR…）原样交出去，NVENC 会编成 HEVC Rext，
    #   显卡硬解、手机、Safari 全都解不了 —— 文件能出，但等于废片。
    #   RGB 源会编成 gbrp，播放器按 YUV 解就是绿配品红。
    # 统一降到 4:2:0，位深能留就留（10bit 走 yuv420p10le，HDR 才保得住）。
    pix = ""
    if needs_down:
        pix = "yuv420p"
    elif not media.is_420:
        pix = "yuv420p10le" if (deep and caps.bit10) else "yuv420p"
    if pix:
        cmd += ["-pix_fmt", pix]

    if needs_down and media.is_hdr:
        # 降位深之后画面已经是 SDR 了，标签必须跟着改，否则 HDR 播放器会二次映射。
        # 10bit 但不是 HDR 的素材不改标签 —— 它本来就没走 PQ 曲线。
        cmd += [
            "-color_range", "tv",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
        ]  # fmt: skip
        warnings.append(
            f"{label} 不支持 10bit，HDR 素材已转为 SDR"
            if tonemap
            else f"{label} 不支持 10bit，已降为 8bit（HDR 信息丢失）"
        )
    elif needs_down:
        # 10bit 但不带 HDR（ProRes / DNxHR 这类工程素材）：只是降位深，别吓人
        warnings.append(f"{label} 不支持 10bit，已降为 8bit")

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
        if caps.advanced:
            cmd += [
                "-spatial-aq", "1",
                "-aq-strength", "8",
                "-rc-lookahead", "20",
                "-multipass", "qres",
            ]  # fmt: skip
        # B 帧参考要 Turing 起才有（Pascal / Maxwell / Volta 的 HEVC 连 B 帧都不支持）。
        # 老卡上必须显式写 0：FFmpeg 默认是 -1（自动），gyan.dev 这类构建会自己开
        # middle，NVENC 初始化直接返回「设备不支持」—— 表现就是 HEVC 也压不了。
        cmd += ["-b_ref_mode", "middle" if caps.bframes else "0"]

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
            # 声道布局是 unknown 的素材（PCM 工程文件、部分 MKV）在 AAC 里会变成
            # "6 channels" 这种没有名字的布局，编码器直接报错，
            # 连带整个文件压不出来。aformat 只是把布局名补正，声道数不变。
            if any(a.layout_unknown for a in media.audio):
                cmd += ["-af", "aformat=channel_layouts=mono|stereo|5.1|7.1"]
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
    cmd += ["-map", "0:V:0", "-c:v", "copy", "-map_metadata", "0", "-an", "-sn", "-dn"]
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
    first = media.audio[0] if media.audio else None
    copying = fmt != "mp3" and bool(first and first.codec == "aac")
    # 声道布局 unknown 的 5.1 会被 AAC 编码器以 "6 channels" 拒绝，抽出来是 0 字节
    if not copying and first is not None and first.layout_unknown:
        cmd += ["-af", "aformat=channel_layouts=mono|stereo|5.1|7.1"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "copy" if copying else "aac"]
    cmd += ["-progress", "pipe:1", "-nostats", str(out)]
    return cmd
