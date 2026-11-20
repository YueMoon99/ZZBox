"""压制命令的「兜底规则」回归测试。

这些都是会让整条压制直接失败、或者出了片却没人能播的坑，逐个钉住：

  1. 分辨率超过 NVENC 上限（H.264 4096 / HEVC 8192）→ 等比缩到上限并提示
  2. 分辨率低于 NVENC 下限（约 144×48）→ 回退原尺寸或放大，绝不发死命令
  3. 竖拍视频带旋转标记 → 目标尺寸必须按转正后的方向算，否则画面被压扁
  4. 4:2:2 / 4:4:4 源 → 必须降到 4:2:0，否则编出 HEVC Rext，手机/显卡解不了
  5. 10bit 但不是 HDR（ProRes 工程素材）→ 不能走色调映射，zscale 会直接报错
  6. 音轨声道布局 unknown（PCM 工程文件常见）→ AAC 编码器会拒绝，要补 aformat
  7. 老卡跑不动 p6 + 空间 AQ + multipass → 退回最小参数集

跑法：python tools/test_encode_guards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.encoder import (  # noqa: E402
    ENC_MAX_DIM,
    EncCaps,
    EncodeSettings,
    build_command,
    compute_target,
    target_plan,
)
from app.core.media import AudioTrack, MediaInfo, _parse_rotation  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def arg_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1] if flag in cmd else ""


def vf_of(cmd: list[str]) -> str:
    return arg_after(cmd, "-vf")


def media(**kw) -> MediaInfo:
    base = dict(path="x.mp4", width=1920, height=1080, duration=10.0, fps=25.0,
                vcodec="hevc", pix_fmt="yuv420p")
    base.update(kw)
    return MediaInfo(**base)


def s(enc: str = "hevc", **kw) -> EncodeSettings:
    st = EncodeSettings(encoder=enc, mode="crf", crf=22, audio_mode="aac")
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def main() -> int:
    print("== 分辨率上限 ==")
    big = media(width=7680, height=4320, pix_fmt="yuv420p")
    w, h, note = target_plan(big, s("h264"))
    check("8K → H.264 缩到 4096 宽", (w, h) == (4096, 2304), f"{w}×{h}")
    check("给出上限提示", "4096" in note, note)
    w, h, note = target_plan(big, s("hevc"))
    check("8K → HEVC 原样", (w, h) == (7680, 4320), f"{w}×{h}")
    five = media(width=5120, height=2700)
    w, h, _ = target_plan(five, s("h264"))
    check("5K → H.264 缩到 4096", (w, h) == (4096, 2160), f"{w}×{h}")
    check("H.264 上限表是 4096", ENC_MAX_DIM["h264"] == 4096)
    uhd = media(width=3840, height=2160)
    check("4K 不触发缩放", compute_target(uhd, s("h264")) == (3840, 2160))

    print("\n== 分辨率下限 ==")
    small = media(width=320, height=240)
    w, h, note = target_plan(small, s("hevc", scale_percent=25))
    check("25% 太小 → 回退原尺寸", (w, h) == (320, 240), f"{w}×{h}")
    check("给出回退提示", "最小尺寸" in note, note)
    tiny = media(width=64, height=64)
    w, h, note = target_plan(tiny, s("hevc", scale_percent=100))
    check("64×64 源自动放大到 144", (w, h) == (144, 144), f"{w}×{h}")
    check("给出放大提示", "放大" in note, note)

    print("\n== 旋转（竖拍视频）==")
    rot = media(width=1920, height=1080, rotation=90)
    check("90° 后显示尺寸变成竖的", (rot.display_width, rot.display_height) == (1080, 1920))
    w, h, _ = target_plan(rot, s("hevc", scale_percent=50))
    check("50% 得到 540×960 而不是 960×540", (w, h) == (540, 960), f"{w}×{h}")
    res = build_command(rot, s("hevc", scale_percent=50), "ffmpeg.exe")
    check("scale 用竖的尺寸", "scale=540:960" in vf_of(res.cmd), vf_of(res.cmd))
    res = build_command(rot, s("hevc", scale_percent=100), "ffmpeg.exe")
    check("100% 不加缩放滤镜", "-vf" not in res.cmd)
    flat = media(width=1920, height=1080, rotation=180)
    check("180° 不交换宽高", (flat.display_width, flat.display_height) == (1920, 1080))
    check("rotation 字段解析", _parse_rotation({"side_data_list": [{"rotation": -90}]}) == 270)
    check("老 MOV 的 rotate 标签", _parse_rotation({"tags": {"rotate": "90"}}) == 90)
    check("没有旋转信息时为 0", _parse_rotation({}) == 0)

    print("\n== 4:2:2 / 4:4:4 → 4:2:0 ==")
    p422 = media(pix_fmt="yuv422p10le")
    res = build_command(p422, s("hevc"), "ffmpeg.exe")
    check("10bit 4:2:2 保留 10bit 但降到 4:2:0",
          arg_after(res.cmd, "-pix_fmt") == "yuv420p10le", arg_after(res.cmd, "-pix_fmt"))
    p444 = media(pix_fmt="yuva444p12le")
    res = build_command(p444, s("hevc"), "ffmpeg.exe")
    check("4:4:4 12bit 同样降 4:2:0", arg_after(res.cmd, "-pix_fmt") == "yuv420p10le")
    p422_8 = media(pix_fmt="yuv422p")
    res = build_command(p422_8, s("hevc"), "ffmpeg.exe")
    check("8bit 4:2:2 降到 yuv420p", arg_after(res.cmd, "-pix_fmt") == "yuv420p")
    rgb = media(pix_fmt="gbrp")
    res = build_command(rgb, s("hevc"), "ffmpeg.exe")
    check("RGB 源强制 yuv420p", arg_after(res.cmd, "-pix_fmt") == "yuv420p")
    ok420 = media(pix_fmt="yuv420p10le")
    res = build_command(ok420, s("hevc"), "ffmpeg.exe")
    check("本来就是 4:2:0 时不动它", "-pix_fmt" not in res.cmd)

    print("\n== 10bit 但不是 HDR ==")
    sdr10 = media(pix_fmt="yuv422p10le", color_transfer="bt709", color_primaries="bt709")
    check("未判成 HDR", not sdr10.is_hdr)
    res = build_command(sdr10, s("h264"), "ffmpeg.exe", caps=EncCaps(bit10=False))
    check("不走色调映射", "zscale" not in vf_of(res.cmd), vf_of(res.cmd))
    check("只是降位深，不提 HDR", any("8bit" in w for w in res.warnings)
          and not any("HDR" in w for w in res.warnings), str(res.warnings))
    hdr = media(pix_fmt="yuv420p10le", color_space="bt2020nc",
                color_transfer="smpte2084", color_primaries="bt2020")
    res = build_command(hdr, s("h264"), "ffmpeg.exe", caps=EncCaps(bit10=False))
    check("真 HDR 才做映射", "tonemap=tonemap=hable" in vf_of(res.cmd))
    check("映射链带显式输入参数", "zscale=m=bt2020nc:p=bt2020:t=smpte2084" in vf_of(res.cmd),
          vf_of(res.cmd)[:70])
    untagged = media(pix_fmt="yuv420p10le", color_transfer="smpte2084")
    res = build_command(untagged, s("h264"), "ffmpeg.exe", caps=EncCaps(bit10=False))
    check("缺色彩标签也能拼出合法链",
          "zscale=m=bt2020nc:p=bt2020:t=smpte2084" in vf_of(res.cmd), vf_of(res.cmd)[:70])

    print("\n== 老卡参数降级 ==")
    res = build_command(media(), s("hevc"), "ffmpeg.exe", caps=EncCaps(advanced=False))
    check("不写 -preset", "-preset" not in res.cmd)
    check("不写 -spatial-aq", "-spatial-aq" not in res.cmd)
    check("不写 -multipass", "-multipass" not in res.cmd)
    check("仍然指定编码器", arg_after(res.cmd, "-c:v") == "hevc_nvenc")
    res = build_command(media(), s("hevc"), "ffmpeg.exe", caps=EncCaps(advanced=True))
    check("正常卡保留 p6", arg_after(res.cmd, "-preset") == "p6")

    print("\n== 音轨声道布局 ==")
    unk = media(audio=[AudioTrack(1, "pcm_s16le", 6, 0, layout="unknown")])
    res = build_command(unk, s("hevc"), "ffmpeg.exe")
    check("布局未知时补 aformat", "aformat=channel_layouts=" in arg_after(res.cmd, "-af"),
          arg_after(res.cmd, "-af"))
    known = media(audio=[AudioTrack(1, "eac3", 6, 640000, layout="5.1(side)")])
    res = build_command(known, s("hevc"), "ffmpeg.exe")
    check("布局正常时不加滤镜", "-af" not in res.cmd)
    copy = media(audio=[AudioTrack(1, "pcm_s16le", 6, 0, layout="unknown")])
    res = build_command(copy, s("hevc", container="mkv", audio_mode="copy"), "ffmpeg.exe")
    check("直通音轨不会被加滤镜", "-af" not in res.cmd and arg_after(res.cmd, "-c:a") == "copy")

    print("\n== 流选择：跳过封面图 ==")
    res = build_command(media(), s("hevc"), "ffmpeg.exe")
    check("用 0:V:0（排除 attached_pic）", "0:V:0" in res.cmd)

    print()
    if _fails:
        print("RESULT = FAIL ->", ", ".join(_fails))
        return 1
    print("RESULT = PASS（全部检查项通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
