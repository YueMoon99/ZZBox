"""用 ffprobe 读取媒体信息。"""

from __future__ import annotations

import json
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


@dataclass
class AudioTrack:
    index: int
    codec: str
    channels: int
    bit_rate: int
    language: str = ""

    @property
    def label(self) -> str:
        return AUDIO_CODEC_LABEL.get(self.codec, self.codec.upper())


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
    audio: list[AudioTrack] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.width > 0 and self.height > 0

    @property
    def resolution_text(self) -> str:
        return f"{self.width}×{self.height}" if self.ok else "—"

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
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            info.vcodec = st.get("codec_name", "")
            info.pix_fmt = st.get("pix_fmt", "")
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
                )
            )

    if not info.width:
        info.error = "该文件不包含视频流"
    return info
