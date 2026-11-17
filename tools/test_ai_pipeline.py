"""AI 增强管线回归测试：造一个短片，真跑一遍拆帧 → 超分 → 补帧 → 合成。

用法（在本目录的上一级，即项目根目录）：
    python tools/test_ai_pipeline.py
    python tools/test_ai_pipeline.py --scale 2 --interp 2 --seconds 3

它不依赖界面，验证「命令能跑通 + 产物尺寸/帧率/音轨对得上 + 颜色没跑偏」。
颜色那项是补上来的：曾经因为合成阶段漏了 -pix_fmt，编出的片子是 HEVC Rext + gbrp，
尺寸帧率时长全对，只有画面变成绿配品红 —— 光看元数据发现不了。
需要 bin/ffmpeg.exe 与 bin/ai/ 下的两个引擎就位。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.ai import (  # noqa: E402
    AiSettings,
    build_plan,
    cleanup,
    detect_engines,
)
from app.core.ai_runner import AiRunner  # noqa: E402
from app.core.media import probe_media  # noqa: E402
from app.core.probe import probe_environment  # noqa: E402


def make_sample(ffmpeg: str, path: Path, seconds: int) -> None:
    """带运动的测试素材：静态色块测不出补帧有任何意义。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size=1280x720:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True,
        check=False,
    )  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--interp", type=int, default=2)
    ap.add_argument("--seconds", type=int, default=3)
    ap.add_argument("--keep", action="store_true", help="保留临时帧序列")
    args = ap.parse_args()

    env = probe_environment()
    if not env.ffmpeg:
        print("FAIL 找不到 ffmpeg")
        return 1
    engines = detect_engines()
    for key, e in engines.items():
        print(f"{key:8} ok={e.ok} models={e.models[:3]}")
        if not e.ok:
            print(f"FAIL 引擎缺失：{e.reason}")
            return 1

    work = ROOT / "logs" / "_ai_test"
    work.mkdir(parents=True, exist_ok=True)
    src = work / "sample.mp4"
    make_sample(env.ffmpeg, src, args.seconds)
    if not src.exists():
        print("FAIL 生成测试素材失败")
        return 1

    media = probe_media(src)
    print(f"源：{media.spec_text} {media.audio_summary}")

    s = AiSettings(scale=args.scale, interp=args.interp)
    plan = build_plan(
        media, s, engines, env.ffmpeg, work / "tmp", vram_mb=env.vram_mb or 0
    )
    if plan.error:
        print(f"FAIL 规划失败：{plan.error}")
        return 1
    print(
        f"目标：{plan.final_w}×{plan.final_h} @ {plan.fps:.0f}fps"
        f" · 临时约 {plan.temp_bytes / 1048576:.0f} MB"
    )
    for w in plan.warnings:
        print(f"  ! {w}")
    for st in plan.stages:
        print(f"  [{st.label}] {' '.join(st.cmd[:2])} …")

    app = QCoreApplication(sys.argv)
    runner = AiRunner()
    state = {"pct": 0, "last_stage": "", "ok": None, "msg": ""}
    runner.progress.connect(lambda p: state.update(pct=p))
    runner.stage.connect(lambda i, name: (state.update(last_stage=name), print(f"  → {name}")))

    def done(ok: bool, msg: str) -> None:
        state.update(ok=ok, msg=msg)
        app.quit()

    runner.finished.connect(done)
    t0 = time.time()
    runner.start(plan)
    app.exec()
    cost = time.time() - t0

    if not state["ok"]:
        print(f"FAIL {state['msg']}（{cost:.1f}s，进度停在 {state['pct']}%）")
        return 1

    out = probe_media(plan.output)
    if not out.ok:
        print(f"FAIL 产物读不出来：{out.error}")
        return 1
    print(f"产物：{out.resolution_text} · {out.fps_text} · {out.duration_text}")
    print(f"音轨：{out.audio_summary}")
    print(f"耗时：{cost:.1f}s，进度到 {state['pct']}%")

    problems = []
    if (out.width, out.height) != (plan.final_w, plan.final_h):
        problems.append(f"尺寸不符 期望 {plan.final_w}×{plan.final_h} 实际 {out.resolution_text}")
    if abs(out.fps - plan.fps) > 0.6:
        problems.append(f"帧率不符 期望 {plan.fps:.1f} 实际 {out.fps:.2f}")
    if media.audio and not out.audio:
        problems.append("音轨丢了")
    if state["pct"] != 100:
        problems.append(f"进度没走到 100（{state['pct']}）")

    # ---- 颜色：尺寸帧率都对但不代表画面是对的
    sys.path.insert(0, str(ROOT / "tools"))
    from check_color import compare  # noqa: PLC0415

    cr = compare(src, Path(plan.output))
    if cr["error"]:
        problems.append(cr["error"])
    else:
        avg = cr["avg"]
        print(
            f"颜色：输出 {cr['out_desc']} · 平均差 "
            f"R{avg[0]:+.1f} G{avg[1]:+.1f} B{avg[2]:+.1f} · 最大 {cr['worst']:.1f} 级"
        )
        if cr["rgb_planes"]:
            problems.append(
                f"输出是 {cr['pix_fmt']}（RGB 平面）—— 播放器会解成绿配品红，"
                f"合成阶段必须带 -pix_fmt yuv420p"
            )
        elif cr["worst"] > 16:
            problems.append(f"色偏过大：最大通道差 {cr['worst']:.1f} 级")

    if not args.keep:
        cleanup(plan.temp_dir)
    else:
        print(f"临时目录保留在 {plan.temp_dir}")

    if problems:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
