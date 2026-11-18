"""PDF 队列图片压缩三项修复的离屏实跑测试。

锁住的承诺：

  1. 预估=实际：preview_compress_bytes 和确认压缩走同一条 ffmpeg 命令，
     同设置下字节数逐字节一致（以前用 PIL 猜，同质量差 1.5~3 倍）
  2. 重编码反而更大时保持原样：不把更大的「压缩件」换进队列，挂
     「不可压缩」黄标，文案写「已保持原样 · 重编码反而更大」；
     确认前 hint 就要预警「N 项预计比原图大」
  3. PNG 无损输出时质量不生效：全部选中项都是 PNG 输出则质量条禁用、
     hint 写「PNG 无损输出，质量不生效」；预估数字不随质量变是正常的

素材：用户提供的真实测试图（gpu-video-encoder/测试图.png、测试图.jpg）。
跑法：python tools/test_pdf_img_zip_fix.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

import app.core.image as _image  # noqa: E402
from app.core.image import (  # noqa: E402
    ImageSettings, build_compress_steps, out_format, preview_compress_bytes,
    probe_image,
)
from app.core.probe import _find_tool  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.page_grid import BADGE_ROLE, BADGE_TONE_ROLE  # noqa: E402

IMG_DIR = ROOT.parents[1]
PNG = IMG_DIR / "测试图.png"
JPG = IMG_DIR / "测试图.jpg"
_fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fails.append(name)


def pump(app, rounds: int = 30, delay: float = 0.02) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(delay)


def wait_est(win, app, timeout: float = 90.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pump(app, 5)
        pending = False
        for uid in win._pdf_compress_uids:
            pair = win._pdf_pair_cache.get(win.pdf_by_uid[uid].uid) or ""
            if "估算中" in pair:
                pending = True
                break
        if not pending:
            pump(app, 15)
            return


def wait_busy(win, app, timeout: float = 180.0) -> None:
    t0 = time.time()
    while win._busy() and time.time() - t0 < timeout:
        pump(app, 10)
    pump(app, 30)


def badge_of(win, uid: str) -> tuple[str, str]:
    item = win.pdf_grid._item_of(uid)
    if item is None:
        return "", ""
    return (item.data(BADGE_ROLE) or ""), (item.data(BADGE_TONE_ROLE) or "")


def item_of(win, name: str):
    for it in win.pdf_items:
        if Path(it.ref.src).name == name or Path(it.origin_src or "").name == name:
            return it
    return None


def pair_of(win, name: str) -> str:
    it = item_of(win, name)
    return (win._pdf_pair_cache.get(it.uid) if it else "") or ""


def reset_queue(win, app) -> None:
    win._pdf_zip_close()
    win._pdf_drop_staged()
    win.pdf_items = []
    win.pdf_by_uid = {}
    win._pdf_undo_stack.clear()
    win._pdf_rebuild_grid()
    win._pdf_stats.clear()
    win._pdf_stat_cache.clear()
    win._pdf_est_failed.clear()
    pump(app, 5)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    for p in (PNG, JPG):
        assert p.exists(), f"缺测试图 {p}"

    # ---------------------------------------------------------------- 1：预估同源
    print("\n[1] preview_compress_bytes 与确认压缩同一条 ffmpeg 命令")
    ffmpeg = _find_tool("ffmpeg")
    for fmt in ("keep", "jpg", "webp"):
        for src in (PNG, JPG):
            info = probe_image(src)
            for q in (30, 78, 95):
                s = ImageSettings(fmt=fmt, quality=q, max_side=0, strip_meta=False)
                est = preview_compress_bytes(src, s, info)
                with tempfile.TemporaryDirectory() as td:
                    out = Path(td) / f"o.{out_format(info, s)}"
                    cmds, made, err = build_compress_steps(
                        ffmpeg, src, s, info, out_path=out)
                    assert not err, err
                    for cmd in cmds:
                        subprocess.run(cmd, check=True, capture_output=True)
                    real = made.stat().st_size
                check(
                    f"预估=实际（{src.name} {fmt} q{q}）",
                    est == real,
                    f"est={est} real={real}",
                )

    # ---------------------------------------------------------------- 2：PNG 质量条
    print("\n[2] PNG 无损输出：质量条禁用 + 提示（用户实测「拖了不动」的场景）")
    win.img_fmt_chips.set_value("png")
    win._pdf_add_paths([PNG, JPG])
    pump(app, 40)
    uids = [it.uid for it in win.pdf_items]
    win._pdf_begin_compress(uids)
    wait_est(win, app)
    check(
        "全 PNG 输出时质量条禁用",
        not win.pdf_zip_quality.isEnabled(),
    )
    check(
        "hint 写明 PNG 质量不生效",
        "PNG 无损输出，质量不生效" in win.pdf_zip_hint.text(),
        win.pdf_zip_hint.text(),
    )
    check(
        "hint 预警比原图大",
        "预计比原图大" in win.pdf_zip_hint.text(),
        win.pdf_zip_hint.text(),
    )
    p_before = pair_of(win, "测试图.png") + "|" + pair_of(win, "测试图.jpg")
    for q in (30, 50, 95):
        win.pdf_zip_quality.setValue(q)
        win._pdf_zip_on_quality(q)
        pump(app, 8)
    p_after = pair_of(win, "测试图.png") + "|" + pair_of(win, "测试图.jpg")
    check(
        "PNG 输出预估不随质量变（无损本来就不变）",
        p_before == p_after and "→" in p_before,
        f"{p_before!r} vs {p_after!r}",
    )
    # 确认压缩：两项都比原图大，都应保持原样
    win._pdf_zip_confirm()
    wait_busy(win, app)
    for name in ("测试图.png", "测试图.jpg"):
        it = item_of(win, name)
        text, tone = badge_of(win, it.uid)
        sub, sub_tone = win._pdf_sub_of(it)
        check(
            f"{name} 重编码变大→保持原样（无暂存件）",
            not it.staged,
            f"staged={it.staged!r}",
        )
        check(
            f"{name} 挂「不可压缩」黄标",
            text == "不可压缩" and tone == "warn",
            f"text={text!r} tone={tone!r}",
        )
        check(
            f"{name} 文案写明保持原样",
            "已保持原样" in sub and sub_tone == "warn",
            f"sub={sub!r}",
        )
    reset_queue(win, app)

    # ---------------------------------------------------------------- 3：keep 混合
    print("\n[3] 保持原样：PNG 项保持原样，JPG 项正常压缩换入")
    win.img_fmt_chips.set_value("keep")
    win._pdf_add_paths([PNG, JPG])
    pump(app, 40)
    uids = [it.uid for it in win.pdf_items]
    win._pdf_begin_compress(uids)
    wait_est(win, app)
    check(
        "混合时质量条可用",
        win.pdf_zip_quality.isEnabled(),
    )
    check(
        "hint 只预警比原图大的那 1 项",
        "1 项预计比原图大" in win.pdf_zip_hint.text(),
        win.pdf_zip_hint.text(),
    )
    win.pdf_zip_quality.setValue(78)
    win._pdf_zip_confirm()
    wait_busy(win, app)
    it_png = item_of(win, "测试图.png")
    it_jpg = item_of(win, "测试图.jpg")
    check("PNG 项保持原样", not it_png.staged)
    text, tone = badge_of(win, it_png.uid)
    check(
        "PNG 项黄标",
        text == "不可压缩" and tone == "warn",
        f"text={text!r} tone={tone!r}",
    )
    check(
        "JPG 项正常换入暂存件",
        bool(it_jpg.staged) and Path(it_jpg.staged).exists(),
        f"staged={it_jpg.staged!r}",
    )
    if it_jpg.staged:
        new = Path(it_jpg.staged).stat().st_size
        check("JPG 项确实变小", new < it_jpg.size, f"{it_jpg.size} -> {new}")
    text, tone = badge_of(win, it_jpg.uid)
    check(
        "JPG 项绿标「已压缩」",
        text == "已压缩" and tone == "ok",
        f"text={text!r} tone={tone!r}",
    )
    # Ctrl+Z 整队回退：暂存件与角标都要还原
    win._pdf_undo()
    pump(app, 20)
    it_png = item_of(win, "测试图.png")
    it_jpg = item_of(win, "测试图.jpg")
    check("Ctrl+Z 后 JPG 项回到未压缩", not it_jpg.staged)
    check("Ctrl+Z 后黄标消失", badge_of(win, it_png.uid)[0] == "")
    reset_queue(win, app)

    # ---------------------------------------------------------------- 4：jpg 输出
    print("\n[4] JPG 输出：预估随质量变化，压缩正常换入")
    win.img_fmt_chips.set_value("jpg")
    win._pdf_add_paths([PNG, JPG])
    pump(app, 40)
    uids = [it.uid for it in win.pdf_items]
    win._pdf_begin_compress(uids)
    wait_est(win, app)
    check("JPG 输出质量条可用", win.pdf_zip_quality.isEnabled())
    pair95 = pair_of(win, "测试图.jpg")
    win.pdf_zip_quality.setValue(40)
    win._pdf_zip_on_quality(40)
    pump(app, 8)
    pair40 = pair_of(win, "测试图.jpg")
    check(
        "拖质量条预估数字跟着变",
        pair95 != pair40 and "→" in pair40,
        f"q95={pair95!r} q40={pair40!r}",
    )
    win._pdf_zip_confirm()
    wait_busy(win, app)
    for name in ("测试图.png", "测试图.jpg"):
        it = item_of(win, name)
        check(
            f"{name} 压缩换入",
            bool(it.staged) and Path(it.staged).exists(),
            f"staged={it.staged!r}",
        )
        check(f"{name} 绿标", badge_of(win, it.uid)[0] == "已压缩")
    reset_queue(win, app)

    # ---------------------------------------------------------------- 收尾
    print("\n[5] 清理")
    win.quit_app()
    pump(app, 10)

    print(f"\n{'=' * 50}")
    if _fails:
        print(f"RESULT = FAIL（{len(_fails)} 项失败）")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("RESULT = PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
