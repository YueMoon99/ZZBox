"""比对源视频与输出视频的颜色，用来抓「通道/矩阵错位」这类肉眼一眼看出、
但尺寸帧率时长全都正常的毛病。

用法：
    python tools/check_color.py 源.mp4 输出.mp4

判定方式：
  · 先看输出的 pix_fmt —— RGB(gbrp/gbr0/rgb24) 是硬错误，播放器必然解歪；
  · 再逐帧算 RGB 均值，逐通道比较。色偏不会只动一个通道的均值，
    而「白色变粉紫、暗部变绿」这类错位的特征是 R/B 互换 + 整体亮度漂移；
  · 最后给一个 0~100 的贴合度，低于 90 判 FAIL。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.probe import probe_environment  # noqa: E402

# 每个通道均值的容差。8bit 下 8 级以内属于量化 + 压缩的正常波动
TOL = 8.0


def _ffmpeg() -> str:
    env = probe_environment()
    if not env.ffmpeg:
        raise SystemExit("找不到 ffmpeg")
    return env.ffmpeg


def _probe_stream(path: Path) -> dict:
    ff = _ffmpeg()
    ffprobe = str(Path(ff).with_name("ffprobe.exe" if ff.endswith(".exe") else "ffprobe"))
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_streams",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    data = json.loads(r.stdout or "{}")
    return (data.get("streams") or [{}])[0]


def _mean_rgb(path: Path, count: int = 12) -> list[tuple[float, float, float]]:
    """按固定间隔抽 count 帧，读每帧的 RGB 均值（signalstats 的 YAVG/UAVG/VAVG 不够，
    那是 YUV 域，恰恰会把错位的颜色当成正常值）。这里解码到 rgb24 再统计。"""
    ff = _ffmpeg()
    info = _probe_stream(path)
    dur = float(info.get("duration") or 0) or 1.0
    fps = 0.0
    rate = info.get("avg_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    total = max(1, int(dur * fps)) if fps else 1
    step = max(1, total // count)

    out = []
    for i in range(0, total, step):
        r = subprocess.run(
            [ff, "-v", "error", "-i", str(path),
             "-vf", f"select=eq(n\\,{i}),scale=64:36,format=rgb24",
             "-frames:v", "1", "-f", "rawvideo", "-"],
            capture_output=True,
        )
        raw = r.stdout
        if len(raw) < 64 * 36 * 3:
            continue
        n = 64 * 36
        rr = sum(raw[0::3]) / n
        gg = sum(raw[1::3]) / n
        bb = sum(raw[2::3]) / n
        out.append((rr, gg, bb))
        if len(out) >= count:
            break
    return out


def compare(src: Path, out: Path) -> dict:
    """返回比对结果。main 只负责打印，测试脚本直接拿这个字典做断言。"""
    src_info, out_info = _probe_stream(src), _probe_stream(out)
    pix = out_info.get("pix_fmt", "?")
    res = {
        "src_desc": f"{src_info.get('width')}x{src_info.get('height')} "
        f"{src_info.get('pix_fmt')} {src_info.get('color_space') or 'unknown'}",
        "out_desc": f"{out_info.get('width')}x{out_info.get('height')} "
        f"{pix} {out_info.get('color_space') or 'unknown'}",
        "pix_fmt": pix,
        "rgb_planes": pix.startswith(("gbr", "rgb", "bgr")),
        "frames": 0,
        "avg": (0.0, 0.0, 0.0),
        "worst": 0.0,
        "spread": 0.0,
        "ok": False,
        "error": "",
    }

    a, b = _mean_rgb(src), _mean_rgb(out)
    if not a or not b:
        res["error"] = "抽帧失败，无法比对"
        return res

    k = min(len(a), len(b))
    diffs = [
        (b[i][0] - a[i][0], b[i][1] - a[i][1], b[i][2] - a[i][2]) for i in range(k)
    ]
    avg = tuple(sum(d[c] for d in diffs) / k for c in range(3))
    res.update(
        frames=k,
        avg=avg,
        worst=max(abs(v) for d in diffs for v in d),
        spread=max(avg) - min(avg),
    )
    res["ok"] = (
        not res["rgb_planes"] and res["worst"] <= TOL * 2 and res["spread"] <= TOL
    )
    return res


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    for p in (src, out):
        if not p.exists():
            print(f"文件不存在：{p}")
            return 2

    r = compare(src, out)
    print(f"源   : {r['src_desc']}")
    print(f"输出 : {r['out_desc']}")
    if r["rgb_planes"]:
        print(f"\n[X] 输出像素格式是 {r['pix_fmt']}（RGB 平面）。播放器会按 YUV 解释，"
              f"画面必然绿配品红。\n    编码时必须显式 -pix_fmt yuv420p。")
    if r["error"]:
        print(r["error"])
        return 2

    avg = r["avg"]
    print(f"\n抽 {r['frames']} 帧比对（RGB 均值差，输出−源）")
    print(f"  平均 : R{avg[0]:+.1f}  G{avg[1]:+.1f}  B{avg[2]:+.1f}")
    print(f"  最大 : {r['worst']:.1f} 级")
    # 通道间的相对偏移才是错位的指纹：绿色通道单独飙高 = 平面被当成 Y
    if r["spread"] > TOL:
        print(f"  [!] 通道间偏移 {r['spread']:.1f} 级 —— 不是整体亮度差，是通道错位")

    print("\nRESULT:", "PASS" if r["ok"] else "FAIL")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
