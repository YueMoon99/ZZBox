"""运行环境探测：定位 FFmpeg、读取显卡信息、验证 NVENC 编码器真实可用性。"""

from __future__ import annotations

import subprocess
import sys
import re
from dataclasses import dataclass, field
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _run(cmd: list[str], timeout: int = 25) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None


@dataclass
class Encoder:
    key: str
    name: str
    label: str
    available: bool = False
    reason: str = ""


@dataclass
class EnvInfo:
    ffmpeg: str = ""
    ffprobe: str = ""
    ffmpeg_version: str = ""
    gpu_name: str = ""
    driver: str = ""
    vram_mb: int = 0
    encoders: list[Encoder] = field(default_factory=list)
    error: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.ffmpeg) and any(e.available for e in self.encoders)

    def encoder(self, key: str) -> Encoder | None:
        for e in self.encoders:
            if e.key == key:
                return e
        return None


def _find_tool(name: str) -> str:
    exe = name + (".exe" if sys.platform == "win32" else "")
    for base in (app_root() / "bin", app_root()):
        p = base / exe
        if p.exists():
            return str(p)
    import shutil

    return shutil.which(name) or ""


def _ffmpeg_version(ffmpeg: str) -> str:
    if not ffmpeg:
        return ""
    r = _run([ffmpeg, "-hide_banner", "-version"], timeout=15)
    if not r or r.returncode != 0:
        return ""
    first = (r.stdout or "").splitlines()[0] if r.stdout else ""
    m = re.search(r"ffmpeg version (\S+)", first)
    return m.group(1) if m else first.strip()[:40]


def _detect_gpu() -> tuple[str, str, int]:
    r = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout=10,
    )
    if not r or r.returncode != 0 or not r.stdout.strip():
        return "", "", 0
    parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
    name = parts[0] if parts else ""
    driver = parts[1] if len(parts) > 1 else ""
    try:
        vram = int(float(parts[2])) if len(parts) > 2 else 0
    except ValueError:
        vram = 0
    return name, driver, vram


def _smoke_test(ffmpeg: str, enc: str) -> tuple[bool, str]:
    """真跑 0.2 秒空帧，确认编码器在当前驱动上确实能出码。"""
    r = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=25:d=0.2",
            "-c:v",
            enc,
            "-f",
            "null",
            "-",
        ],
        timeout=25,
    )
    if r is None:
        return False, "启动失败"
    if r.returncode == 0:
        return True, ""
    msg = (r.stderr or "").strip().splitlines()
    return False, msg[-1][:120] if msg else "未知错误"


def probe_environment() -> EnvInfo:
    info = EnvInfo()
    info.ffmpeg = _find_tool("ffmpeg")
    info.ffprobe = _find_tool("ffprobe")
    if not info.ffmpeg:
        info.error = "未找到 ffmpeg.exe，请确认 bin 目录完整"
        return info

    info.ffmpeg_version = _ffmpeg_version(info.ffmpeg)
    info.gpu_name, info.driver, info.vram_mb = _detect_gpu()

    candidates = [
        ("h264", "h264_nvenc", "H.264"),
        ("hevc", "hevc_nvenc", "HEVC"),
        ("av1", "av1_nvenc", "AV1"),
    ]
    for key, enc, label in candidates:
        item = Encoder(key=key, name=enc, label=label)
        ok, reason = _smoke_test(info.ffmpeg, enc)
        item.available, item.reason = ok, reason
        info.encoders.append(item)
    return info
