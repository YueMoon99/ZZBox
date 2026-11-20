"""HDR 素材与显卡能力的回归测试。

起因：一位 GTX 1080 Ti 用户反馈「压 HDR 素材直接失败，H.264 / HEVC 都不行」。
两个独立原因：
  1. 源是 10bit HDR。NVENC 的 H.264 只有 Blackwell（RTX 50）能编 10bit，
     Turing / Ampere / Ada / Pascal 一律只吃 8bit —— 直接喂 10bit 会报
     "No capable devices found"。
  2. 命令里写死了 -b_ref_mode middle。B 帧参考要 Turing 起才有，
     Pascal / Maxwell / Volta 上连 HEVC 都初始化不了。

这份测试守住三条：
  a. 位深与 HDR 判定不能错（判错就不会走下面的分支）
  b. H.264 + 10bit 必须改成「色调映射到 SDR」或「降 8bit 并改标签」，不能原样发出去
  c. 显卡不支持 B 帧时必须显式写 0，而不是照写 middle

跑法：python tools/test_hdr_encode.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.encoder import (  # noqa: E402
    EncCaps,
    EncodeSettings,
    build_command,
)
from app.core.media import MediaInfo, guess_bit_depth  # noqa: E402
from app.core.probe import _find_tool  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def hdr_media() -> MediaInfo:
    return MediaInfo(
        path="NF.mkv",
        width=3840,
        height=2160,
        duration=5.2,
        fps=23.976,
        vcodec="hevc",
        pix_fmt="yuv420p10le",
        color_range="tv",
        color_space="bt2020nc",
        color_transfer="smpte2084",
        color_primaries="bt2020",
    )


def sdr_media() -> MediaInfo:
    return MediaInfo(
        path="plain.mp4",
        width=1920,
        height=1080,
        duration=30.0,
        fps=25.0,
        vcodec="h264",
        pix_fmt="yuv420p",
        color_range="tv",
        color_space="bt709",
        color_transfer="bt709",
    )


def settings(enc: str) -> EncodeSettings:
    return EncodeSettings(encoder=enc, mode="crf", crf=22, scale_percent=100, audio_mode="aac")


def arg_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1] if flag in cmd else ""


def vf_of(cmd: list[str]) -> str:
    return arg_after(cmd, "-vf")


def main() -> int:
    print("== 位深判定 ==")
    for fmt, want in (
        ("yuv420p", 8),
        ("nv12", 8),
        ("rgb24", 8),
        ("bgr0", 8),
        ("", 8),
        ("yuv420p10le", 10),
        ("p010le", 10),
        ("p016le", 16),
        ("yuv444p12le", 12),
        ("gbrp16le", 16),
    ):
        got = guess_bit_depth(fmt)
        check(f"{fmt or '(空)'} → {want}bit", got == want, f"实际 {got}")

    print("\n== HDR / SDR 判定 ==")
    h, s = hdr_media(), sdr_media()
    check("PQ 10bit 判为 HDR", h.is_hdr and h.bit_depth == 10)
    check("BT.709 8bit 不是 HDR", not s.is_hdr and s.bit_depth == 8)
    bt2020_sdr = MediaInfo(
        path="x.mkv", pix_fmt="yuv420p", color_space="bt2020nc", color_transfer="bt709"
    )
    check("bt2020 + bt709 不误判成 HDR", not bt2020_sdr.is_hdr)

    print("\n== H.264 + 10bit（普通显卡：没有 High10）==")
    caps = EncCaps(bit10=False, bframes=True, tonemap=True)
    res = build_command(h, settings("h264"), "ffmpeg.exe", caps=caps)
    cmd, vf = res.cmd, vf_of(res.cmd)
    check("走色调映射", "zscale=t=linear" in vf and "tonemap=tonemap=hable" in vf, vf[:60])
    check("最终输出 yuv420p", vf.endswith("format=yuv420p") and arg_after(cmd, "-pix_fmt") == "yuv420p")
    check("色彩标签改成 BT.709", arg_after(cmd, "-color_trc") == "bt709"
          and arg_after(cmd, "-colorspace") == "bt709")
    check("给出降级提示", any("SDR" in w for w in res.warnings), str(res.warnings))

    print("\n== H.264 + 10bit（Blackwell：有 High10）==")
    res = build_command(h, settings("h264"), "ffmpeg.exe", caps=EncCaps(bit10=True))
    check("不色调映射", "zscale" not in vf_of(res.cmd), vf_of(res.cmd)[:60])
    check("不改色彩标签", "-color_trc" not in res.cmd)
    check("无降级提示", not res.warnings, str(res.warnings))

    print("\n== H.264 + 10bit（ffmpeg 没带 zscale）==")
    res = build_command(h, settings("h264"), "ffmpeg.exe", caps=EncCaps(bit10=False, tonemap=False))
    check("退化成直接降 8bit", "zscale" not in vf_of(res.cmd)
          and arg_after(res.cmd, "-pix_fmt") == "yuv420p")
    check("提示写明 HDR 丢失", any("丢失" in w for w in res.warnings), str(res.warnings))

    print("\n== B 帧参考开关 ==")
    res_new = build_command(h, settings("hevc"), "ffmpeg.exe", caps=EncCaps(bframes=True))
    check("Turing 及以后写 middle", arg_after(res_new.cmd, "-b_ref_mode") == "middle")
    res_old = build_command(h, settings("hevc"), "ffmpeg.exe", caps=EncCaps(bframes=False))
    check("Pascal 及更早显式写 0", arg_after(res_old.cmd, "-b_ref_mode") == "0",
          arg_after(res_old.cmd, "-b_ref_mode"))
    res_h264_old = build_command(s, settings("h264"), "ffmpeg.exe", caps=EncCaps(bframes=False))
    check("H.264 也照此处理", arg_after(res_h264_old.cmd, "-b_ref_mode") == "0")

    print("\n== SDR 8bit 不受影响（回归）==")
    res = build_command(s, settings("h264"), "ffmpeg.exe", caps=EncCaps())
    check("不加滤镜", "-vf" not in res.cmd)
    check("不改位深", "-pix_fmt" not in res.cmd)
    check("不改色彩标签", "-color_trc" not in res.cmd)

    print("\n== 真跑一遍 ffmpeg ==")
    ffmpeg = _find_tool("ffmpeg")
    sample = Path.home() / "Downloads" / "NF.mkv"
    if not ffmpeg:
        print("  [SKIP] 找不到 ffmpeg.exe")
    elif not sample.exists():
        print(f"  [SKIP] 缺少 HDR 样片 {sample}")
    else:
        out_dir = Path(tempfile.gettempdir()) / "zzbox_hdr_test"
        out_dir.mkdir(exist_ok=True)
        real = hdr_media()
        real.path = str(sample)
        for name, enc, caps, want in (
            ("h264_tonemap", "h264", EncCaps(bit10=False, bframes=True, tonemap=True), "yuv420p"),
            ("hevc_no_bframes", "hevc", EncCaps(bframes=False), "yuv420p10le"),
        ):
            out = out_dir / f"{name}.mp4"
            res = build_command(real, settings(enc), ffmpeg, out, caps=caps)
            r = subprocess.run(res.cmd, capture_output=True, text=True, errors="replace")
            ok = r.returncode == 0 and out.exists() and out.stat().st_size > 0
            err = (r.stderr or "").strip().splitlines()
            check(f"{name} 编码成功", ok, err[-1][:110] if err and not ok else "")
            if ok:
                probe = subprocess.run(
                    [str(Path(ffmpeg).with_name("ffprobe.exe")), "-v", "error",
                     "-select_streams", "v:0", "-show_entries",
                     "stream=pix_fmt,color_transfer", "-of", "default=nk=1:nw=1", str(out)],
                    capture_output=True, text=True, errors="replace",
                )
                info = (probe.stdout or "").split()
                check(f"{name} 位深/色彩正确", want in info, " ".join(info))
        for f in out_dir.glob("*.mp4"):
            f.unlink(missing_ok=True)

    print()
    if _fails:
        print("RESULT = FAIL ->", ", ".join(_fails))
        return 1
    print("RESULT = PASS（全部检查项通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
