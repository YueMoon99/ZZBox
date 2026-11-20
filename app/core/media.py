"""用 ffprobe 读取媒体信息。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.core.probe import _find_tool

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

AUDIO_CODEC_LABEL = {
    "aac": "AAC",
    "mp3": "MP3",
    "ac3": "AC3",
    "eac3": "EAC3",
    "flac": "FLAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "pcm_s16le": "PCM",
    "alac": "ALAC",
}


_DEPTH_TAIL = re.compile(r"p(\d{2})(?:le|be)?$")
_DEPTH_RAW = re.compile(r"(\d{2})(?:le|be)$")


def guess_bit_depth(pix_fmt: str) -> int:
    """从 pix_fmt 推位深。认得出来的只有 9/10/12/14/16，其余一律当 8bit。

    yuv420p10le / p010le / yuv444p16le / gbrp12le 这些是常见的 10bit+ 像素格式；
    yuv420p、nv12、p010 之外的写法（rgb24、bgr0…）都是 8bit，别被 nv12 的 12 骗了。
    """
    f = (pix_fmt or "").lower()
    if f.startswith("p0"):  # p010 / p012 / p016
        try:
            return int(f[1:4])
        except ValueError:
            return 10
    m = _DEPTH_TAIL.search(f) or _DEPTH_RAW.search(f)
    if m:
        d = int(m.group(1))
        if d in (9, 10, 12, 14, 16):
            return d
    return 8


@dataclass
class AudioTrack:
    index: int
    codec: str
    channels: int
    bit_rate: int
    language: str = ""
    # 声道路由名（stereo / 5.1(side) / unknown）。PCM 工程文件和部分 MKV 里
    # 这一项是 unknown，AAC 编码器只认「5.1」这类名字，见到 "6 channels" 直接拒绝，
    # 结果整个压制失败。
    layout: str = ""

    @property
    def label(self) -> str:
        return AUDIO_CODEC_LABEL.get(self.codec, self.codec.upper())

    @property
    def layout_unknown(self) -> bool:
        return self.layout in ("", "unknown")


@dataclass
class MediaInfo:
    path: str
    width: int = 0
    height: int = 0
    duration: float = 0.0
    fps: float = 0.0
    vcodec: str = ""
    vbitrate: int = 0
    pix_fmt: str = ""
    size: int = 0
    # 色彩标签。源文件大多不写这几个字段（ffprobe 报 unknown），
    # 但一旦写了就必须照着它转，否则 RGB 往返一次就偏色。
    color_range: str = ""
    color_space: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    # 手机竖拍视频的真实画面是横着存的，靠这个角度转过来。
    # 只要动了 -vf，ffmpeg 就会先自动旋转再跑滤镜，目标尺寸必须按「转完之后」算，
    # 否则 scale=960:540 会把竖构图硬压成横的。
    rotation: int = 0
    audio: list[AudioTrack] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.width > 0 and self.height > 0

    @property
    def is_rgb(self) -> bool:
        """源本身就是 RGB 编码（gbrp / gbr0 / rgb24 …）。

        这类视频直接交给 NVENC 会被编成 HEVC Rext + gbrp，播放器按 YUV 解，
        画面就是一片绿配品红。压缩面板据此决定要不要强制转 yuv420p。
        """
        return self.pix_fmt.startswith(("gbr", "rgb", "bgr"))

    @property
    def is_420(self) -> bool:
        """是否已经是 4:2:0。

        4:2:2 / 4:4:4 的工程素材（ProRes、DNxHR、部分相机格式）直接丢给 NVENC，
        会编出 HEVC Rext —— 显卡、手机、Safari 全都解不了，等于出个废片。
        必须显式降到 4:2:0，位深可以保留。
        """
        f = (self.pix_fmt or "").lower()
        if not f:
            return True
        return not ("422" in f or "444" in f or f.startswith(("gbr", "rgb", "bgr")))

    @property
    def rotated(self) -> bool:
        """画面被旋转了 90/270 度：存储的宽高和实际显示是反的。"""
        return self.rotation % 180 != 0

    @property
    def display_width(self) -> int:
        return self.height if self.rotated else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotated else self.height

    @property
    def bit_depth(self) -> int:
        """源素材位深。10bit HDR 能不能直通，取决于编码器吃不吃 10bit。"""
        return guess_bit_depth(self.pix_fmt)

    @property
    def is_hdr(self) -> bool:
        """PQ（HDR10 / Dolby Vision 底层）或 HLG 都算 HDR。

        只认 transfer：bt2020 的 SDR 素材确实存在，光看原色域会误判。
        """
        return self.color_transfer in ("smpte2084", "arib-std-b67")

    @property
    def resolution_text(self) -> str:
        """显示尺寸，不是存储尺寸。

        竖拍视频存成 1920×1080 加一个旋转标记，用户看到的是 1080×1920。
        队列里要是写 1920×1080，导出格式那列又写 1080×1920，看着像被换了方向。
        """
        if not self.ok:
            return "—"
        return f"{self.display_width}×{self.display_height}"

    @property
    def duration_text(self) -> str:
        s = int(round(self.duration))
        return f"{s // 60:02d}:{s % 60:02d}"

    @property
    def fps_text(self) -> str:
        if self.fps <= 0:
            return "—"
        v = round(self.fps, 2)
        if abs(v - round(v)) < 0.02:  # 23.976/29.97 这类保留两位，整帧率不带小数
            return f"{int(round(v))}fps"
        return f"{v:.2f}fps"

    @property
    def spec_text(self) -> str:
        """分辨率 · 帧率 · 时长：队列的「原始格式」列直接用这个。"""
        if not self.ok:
            return "—"
        return f"{self.resolution_text} · {self.fps_text} · {self.duration_text}"

    @property
    def audio_summary(self) -> str:
        if not self.audio:
            return "无音轨"
        kinds = {a.label for a in self.audio}
        return f"{len(self.audio)} 条音轨 · {'/'.join(sorted(kinds))}"


def human_size(n: float) -> str:
    """按资源管理器的习惯显示大小：三位有效数字 + 单位。"""
    size = float(n or 0)
    if size <= 0:
        return "—"
    for unit, base in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= base:
            v = size / base
            if v >= 100:
                text = f"{v:.0f}"
            elif v >= 10:
                text = f"{v:.1f}"
            else:
                text = f"{v:.2f}"
            return f"{text} {unit}"
    return f"{int(size)} B"


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_fps(rate: str) -> float:
    if not rate or "/" not in rate:
        return _to_float(rate)
    num, den = rate.split("/", 1)
    den_f = _to_float(den, 1.0) or 1.0
    return _to_float(num) / den_f


def _parse_rotation(st: dict) -> int:
    """读旋转角度，归一化成 0/90/180/270。

    ffprobe 有两条路：新版本放在 side_data_list 的 Display Matrix 里，
    老 MOV 只看 tags.rotate。两个都没有就是不旋转。
    """
    raw = None
    for sd in st.get("side_data_list") or []:
        if "rotation" in sd:
            raw = sd.get("rotation")
            break
    if raw is None:
        raw = (st.get("tags") or {}).get("rotate")
    try:
        deg = int(round(float(raw)))
    except (TypeError, ValueError):
        return 0
    deg %= 360
    return 0 if deg == 360 else deg


def probe_media(path: str | Path) -> MediaInfo:
    src = Path(path)
    info = MediaInfo(path=str(src))
    ffprobe = _find_tool("ffprobe")
    if not ffprobe:
        info.error = "未找到 ffprobe.exe"
        return info
    if not src.exists():
        info.error = "文件不存在"
        return info

    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(src),
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=40,
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

    fmt = data.get("format", {}) or {}
    info.duration = _to_float(fmt.get("duration"))
    info.size = int(_to_float(fmt.get("size")))

    for st in data.get("streams", []) or []:
        kind = st.get("codec_type")
        if kind == "video" and not info.width:
            # 封面图（attached_pic）也是 video 流。MKV/MP4 里它排在第一位时，
            # 按「第一个 video 流」取值就会把封面当成片子：分辨率 320×240、
            # 时长 0 秒，后面选 -map 0:v:0 却取到正片，参数全对不上。
            if (st.get("disposition") or {}).get("attached_pic"):
                continue
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            info.vcodec = st.get("codec_name", "")
            info.pix_fmt = st.get("pix_fmt", "")
            info.color_range = st.get("color_range", "") or ""
            info.color_space = st.get("color_space", "") or ""
            info.color_transfer = st.get("color_transfer", "") or ""
            info.color_primaries = st.get("color_primaries", "") or ""
            info.rotation = _parse_rotation(st)
            info.fps = _parse_fps(st.get("avg_frame_rate") or st.get("r_frame_rate") or "")
            info.vbitrate = int(_to_float(st.get("bit_rate")))
            if not info.duration:
                info.duration = _to_float(st.get("duration"))
        elif kind == "audio":
            info.audio.append(
                AudioTrack(
                    index=int(st.get("index", 0)),
                    codec=st.get("codec_name", ""),
                    channels=int(st.get("channels") or 0),
                    bit_rate=int(_to_float(st.get("bit_rate"))),
                    language=(st.get("tags") or {}).get("language", ""),
                    layout=st.get("channel_layout", "") or "",
                )
            )

    if not info.width:
        info.error = "该文件不包含视频流"
    return info
