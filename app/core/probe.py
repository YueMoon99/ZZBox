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
    # 硬件能力：只决定命令里能写哪些参数，不影响「可用 / 不可用」的判定
    bit10: bool = True    # 能直接编 10bit 输入（H.264 要 Blackwell）
    bframes: bool = True  # 支持 B 帧参考（要 Turing 起）
    # 完整参数集（p6 预设 + 空间 AQ + lookahead + multipass）能不能跑。
    # 老驱动/老卡上偶有单项不支持，整组降级成最小参数也比压不出来强。
    advanced: bool = True


@dataclass
class EnvInfo:
    ffmpeg: str = ""
    ffprobe: str = ""
    ffmpeg_version: str = ""
    gpu_name: str = ""
    driver: str = ""
    vram_mb: int = 0
    tonemap: bool = True  # ffmpeg 带 zscale，能把 HDR 转 SDR
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


def _caps_test(ffmpeg: str, enc: str, extra: list[str]) -> bool:
    """在 0.2 秒空帧上验证某一项硬件特性到底能不能用。

    参数刻意保持最小集：这里测的是硬件能力，不是预设。把 -preset p6 之类也塞
    进来，老卡会因为别的原因失败，反而把「不支持 B 帧」误判成「编码器不可用」。
    """
    r = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:r=25:d=0.2",
            "-c:v",
            enc,
            *extra,
            "-f",
            "null",
            "-",
        ],
        timeout=25,
    )
    return bool(r is not None and r.returncode == 0)


def _has_filter(ffmpeg: str, name: str) -> bool:
    r = _run([ffmpeg, "-hide_banner", "-filters"], timeout=15)
    if r is None or r.returncode != 0:
        return False
    return re.search(rf"\b{re.escape(name)}\b", r.stdout or "") is not None


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
    # 先按「完整参数集」试一遍：过了就说明编码器可用，且 p6 / 空间 AQ /
    # multipass 这些都能吃，省掉一次单独的冒烟测试（每次都要拉起一个 ffmpeg）。
    advanced_args = [
        "-preset", "p6", "-tune", "hq",
        "-spatial-aq", "1", "-aq-strength", "8",
        "-rc-lookahead", "20", "-multipass", "qres",
    ]  # fmt: skip
    for key, enc, label in candidates:
        item = Encoder(key=key, name=enc, label=label)
        item.advanced = _caps_test(info.ffmpeg, enc, advanced_args)
        if item.advanced:
            item.available = True
        else:
            # 完整参数没过：可能是老卡不吃某一项，也可能编码器根本不可用
            item.available, item.reason = _smoke_test(info.ffmpeg, enc)
        if item.available:
            # 10bit：H.264 要 Blackwell 才有 High10；HEVC 要 Pascal 起；
            # AV1 编码器整代都是 10bit。统一探一遍，别按型号猜。
            item.bit10 = _caps_test(info.ffmpeg, enc, ["-pix_fmt", "p010le"])
            # B 帧参考：Turing 之前没有。不探就只能等用户压到一半去撞墙
            if key in ("h264", "hevc"):
                item.bframes = _caps_test(info.ffmpeg, enc, ["-b_ref_mode", "middle"])
        info.encoders.append(item)
    info.tonemap = _has_filter(info.ffmpeg, "zscale")
    return info
