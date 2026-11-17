"""舟舟工具箱（ZZBox） · 程序入口。"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _base_dir() -> Path:
    """源码运行取项目根，打包后取 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _base_dir()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _log_crash(exc_text: str) -> Path:
    """把崩溃信息落到 logs/error.log，供用户直接发送。"""
    try:
        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "error.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 60 + "\n")
            fh.write(exc_text + "\n")
        return path
    except Exception:
        return ROOT / "logs" / "error.log"


def _report(exc_text: str) -> None:
    """双击启动时没有控制台，必须弹窗告知，而不是静默退出。"""
    path = _log_crash(exc_text)
    try:
        sys.stderr.write(exc_text)
        sys.stderr.flush()
    except Exception:
        pass
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("启动失败")
        box.setText("程序启动时出错，无法继续运行。")
        box.setInformativeText(f"错误详情已记录到：\n{path}\n\n请把这个文件发给开发者。")
        box.setDetailedText(exc_text)
        box.exec()
    except Exception:
        pass


def _selftest() -> int:
    """无人值守自检：验证 FFmpeg 定位、显卡识别、真实出片。

    打包后用 `ZZBox.exe --selftest` 调用，结果写入 logs/selftest.txt。
    这是给"用户双不双击"之外的第二种验证手段——不依赖界面也能证明管线可用。
    """
    import subprocess
    import time

    from app.core.encoder import EncodeSettings, build_command, make_output_path  # noqa: PLC0415
    from app.core.media import probe_media  # noqa: PLC0415
    from app.core.probe import probe_environment  # noqa: PLC0415

    lines: list[str] = []
    ok = True
    t0 = time.time()

    def say(text: str) -> None:
        lines.append(text)
        try:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    say(f"root = {ROOT}")
    say(f"frozen = {getattr(sys, 'frozen', False)}")

    env = probe_environment()
    say(f"gpu = {env.gpu_name} | driver = {env.driver} | vram = {env.vram_mb} MB")
    say(f"ffmpeg = {env.ffmpeg} | version = {env.ffmpeg_version}")
    say(f"ffprobe = {env.ffprobe}")
    say(f"ready = {env.ready}")
    for enc in env.encoders:
        say(f"  encoder {enc.label}: available={enc.available} {enc.reason}")
    if not env.ready:
        ok = False

    # AI 引擎是可选组件：缺了不影响自检结论，但要在报告里说清楚
    from app.core.ai import detect_engines, vram_profile  # noqa: PLC0415

    profile = vram_profile(env.vram_mb)
    say(f"vram profile = {profile.tier} (tile={profile.tile}, max={profile.max_pixels}px)")
    for key, eng in detect_engines().items():
        models = "/".join(eng.models[:3]) or "-"
        say(f"  ai {key}: ok={eng.ok} models={models} {eng.reason}")

    work = ROOT / "logs" / "_selftest"
    work.mkdir(parents=True, exist_ok=True)
    src = work / "in.mp4"
    create = subprocess.run(
        [
            env.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src),
        ],
        capture_output=True,
    )
    if create.returncode != 0 or not src.exists():
        say("FAIL 生成测试素材失败: " + create.stderr.decode("utf-8", "replace")[-300:])
        ok = False
    else:
        media = probe_media(src)
        say(f"source = {media.resolution_text} {media.duration_text} {media.vcodec}")
        st = EncodeSettings(encoder="hevc", mode="crf", crf=22, scale_percent=50)
        out = make_output_path(src, st, st.encoder)
        res = build_command(media, st, env.ffmpeg, out)
        rt = time.time()
        proc = subprocess.run(res.cmd, capture_output=True)
        cost = time.time() - rt
        if proc.returncode != 0 or not out.exists():
            say("FAIL 编码失败 rc=%d: %s" % (proc.returncode, proc.stderr.decode("utf-8", "replace")[-500:]))
            ok = False
        else:
            om = probe_media(out)
            size = out.stat().st_size / 1024
            say(f"output = {om.resolution_text} {om.vcodec} {size:.0f} KB in {cost:.1f}s")
            expect = (640, 360)
            got = (om.width, om.height)
            if got != expect:
                say(f"FAIL 缩放结果不符 期望 {expect} 实际 {got}")
                ok = False
            elif om.vcodec.lower() not in ("hevc", "h265"):
                say(f"FAIL 编码格式不符 实际 {om.vcodec}")
                ok = False
            else:
                say(f"PASS 50% 缩放 + HEVC NVENC 正常，用时 {cost:.1f}s")

    # ---- 图片管线：压缩与超分各出一张
    # 冻结环境里最容易翻车的是引擎与 ffmpeg 的路径解析，所以这段不跳过
    from app.core.image import (  # noqa: PLC0415
        ImageSettings,
        build_ai_steps,
        build_compress_steps,
        probe_image,
    )

    def run_steps(steps: list[list[str]]) -> tuple[int, str]:
        """按顺序跑命令链，第一处非零退出就返回。"""
        for cmd in steps:
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0:
                return proc.returncode, proc.stderr.decode("utf-8", "replace")[-500:]
        return 0, ""

    pic = work / "in.png"
    made = subprocess.run(
        [
            env.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=800x600:rate=1",
            "-frames:v", "1", str(pic),
        ],
        capture_output=True,
    )  # fmt: skip
    info = None
    if made.returncode != 0 or not pic.exists():
        say("FAIL 生成测试图片失败: " + made.stderr.decode("utf-8", "replace")[-300:])
        ok = False
    else:
        info = probe_image(pic)
        say(f"image = {info.resolution_text} {info.fmt_text} {info.size / 1024:.0f} KB")

    if info is not None and info.ok:
        # 1) 压缩：PNG → WebP，长边限 400（800×600 应得 400×300）
        cs = ImageSettings(fmt="webp", quality=70, max_side=400, output_dir=str(work))
        steps, out, err = build_compress_steps(env.ffmpeg, pic, cs, info)
        rc, msg = run_steps(steps) if steps else (-1, err)
        if rc != 0 or not out.exists():
            say(f"FAIL 图片压缩失败 rc={rc}: {msg}")
            ok = False
        else:
            oi = probe_image(out)
            if (oi.width, oi.height) != (400, 300):
                say(f"FAIL 压缩尺寸不符 期望 400×300 实际 {oi.width}×{oi.height}")
                ok = False
            elif not oi.size:
                say("FAIL 压缩产物为空文件")
                ok = False
            else:
                say(
                    f"PASS 图片压缩 PNG→WebP {oi.width}×{oi.height} "
                    f"{oi.size / 1024:.0f} KB"
                )

        # 2) 超分：选 2× 时引擎按 4× 推理再降采样，最终应是 1600×1200
        esrgan = detect_engines()["esrgan"]
        if not esrgan.ok:
            say(f"SKIP 图片超分：{esrgan.reason}")
        else:
            ais = ImageSettings(scale=2, model="photo", quality=85, output_dir=str(work))
            tmp = work / "up.png"
            steps, out, err = build_ai_steps(
                env.ffmpeg,
                esrgan.exe,
                str(Path(esrgan.exe).parent / "models"),
                pic,
                ais,
                info,
                tmp,
                profile.tile,
            )
            rt = time.time()
            rc, msg = run_steps(steps) if steps else (-1, err)
            cost = time.time() - rt
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            if rc != 0 or not out.exists():
                say(f"FAIL 图片超分失败 rc={rc}: {msg}")
                ok = False
            else:
                oi = probe_image(out)
                if (oi.width, oi.height) != (1600, 1200):
                    say(
                        f"FAIL 超分尺寸不符 期望 1600×1200 实际 {oi.width}×{oi.height}"
                        "（推理倍率被当成输出倍率了？）"
                    )
                    ok = False
                elif tmp.exists():
                    say("FAIL 超分中间文件未清理")
                    ok = False
                else:
                    say(
                        f"PASS 图片超分 2× 输出 1600×1200 "
                        f"{oi.size / 1024:.0f} KB，用时 {cost:.1f}s"
                    )

    # ---- PDF 管线：图片合成 → 读回页数 → 渲染一页
    # 打包后最容易安静翻车的就是这里：pdfium.dll 是数据文件，PyInstaller 的
    # import 分析看不见它，源码跑得好好的，一点 PDF 就报 cannot load library。
    # 本段存在的唯一目的就是在发版前把它揪出来。
    from app.core.pdf import PageRef, export_pdf, probe_pdf, render_page  # noqa: PLC0415

    if pic.exists():
        pdf_out = work / "out.pdf"
        refs = [
            PageRef(str(pic), "image"),
            PageRef(str(pic), "image", 0, rotate=90),
        ]
        try:
            export_pdf(refs, pdf_out)
            pinfo = probe_pdf(pdf_out)
            if pinfo.pages != 2:
                say(f"FAIL PDF 页数不符 期望 2 实际 {pinfo.pages}")
                ok = False
            else:
                img0 = render_page(PageRef(str(pdf_out), "pdf", 0), dpi=72)
                if not (img0.width and img0.height):
                    say("FAIL PDF 渲染返回空图")
                    ok = False
                else:
                    say(
                        f"PASS PDF 合成 2 页（含旋转页），渲染 {img0.width}×{img0.height}，"
                        f"{pdf_out.stat().st_size / 1024:.0f} KB"
                    )
                    # ---- 图片压缩（pypdf 管线）
                    # 这条和上面完全不同的库：pypdf 是纯 Python，PyInstaller
                    # 一般能收到，但 pypdf.generic 里有动态导入，漏了就是
                    # 用户点"启用压缩功能"立刻报 ImportError。这里跑一遍
                    # 真实的"读页面 → 重编码图片 → 重写文件"，顺便确认文字层
                    # 和页面尺寸没被改坏
                    from app.core.pdf_images import merge_pdf, scan_pdf  # noqa: PLC0415

                    refs_all = [
                        PageRef(str(pdf_out), "pdf", 0),
                        PageRef(str(pdf_out), "pdf", 1),
                    ]
                    scans = scan_pdf(pdf_out)
                    zam = work / "zip.pdf"
                    merge_pdf(refs_all, zam, quality=60)
                    after = probe_pdf(zam)
                    if after.pages != 2 or float(after.sizes[0][0]) <= 0:
                        say(f"FAIL PDF 图片压缩后结构不对（{after.pages} 页）")
                        ok = False
                    else:
                        # 体积只报告不判定：这张测试图本身就压不动，
                        # 硬要求变小会让发版卡在一条无意义的断言上。
                        # 真正要防的是 pypdf 没被收进来 —— 那会直接抛异常
                        first = scans.get(0)
                        delta = pdf_out.stat().st_size - zam.stat().st_size
                        say(
                            f"PASS PDF 图片压缩（pypdf）2 页，"
                            f"{pdf_out.stat().st_size}→{zam.stat().st_size} 字节"
                            f"（省 {delta}），第 1 页 {first.count if first else 0} 张图"
                        )
        except Exception as exc:  # noqa: BLE001
            say(f"FAIL PDF 管线异常：{type(exc).__name__}: {exc}")
            ok = False

    say(f"total {time.time() - t0:.1f}s")
    say("RESULT = " + ("PASS" if ok else "FAIL"))
    (ROOT / "logs" / "selftest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --quiet 供自动化调用：结果只看 logs/selftest.txt，不弹窗等人点确定
    if "--quiet" in sys.argv:
        return 0 if ok else 1

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        box = QMessageBox()
        box.setIcon(QMessageBox.Information if ok else QMessageBox.Critical)
        box.setWindowTitle("自检结果")
        box.setText("全部通过" if ok else "存在问题")
        box.setDetailedText("\n".join(lines))
        box.exec()
        del app
    except Exception:
        pass
    return 0 if ok else 1


def _set_app_id() -> None:
    """源码运行时告诉 Windows 这是独立程序，别按 python.exe 归类。

    注意只在非打包模式设：打包后的 exe 自带 version 资源，Windows 会按 exe 的
    产品名识别（托盘通知里显示的就是它）。一旦硬塞一个没注册过的 AppID，
    通知气泡的标题会变成那串 ID，很难看。
    """
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZZBox.Dev.0.6")
    except Exception:
        pass


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from app.ui import icons
    from app.ui.main_window import MainWindow
    from app.ui.style import build_qss, pick_font

    _set_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("ZZBox")
    # 注意：别再设 setApplicationDisplayName，Qt 会把它拼到标题后面变成
    # "舟舟工具箱（ZZBox） v0.9.1 - 舟舟工具箱（ZZBox）"，标题栏会显得重复
    # 标题栏/任务栏/Alt-Tab 都取这份图标
    app.setWindowIcon(icons.app_icon())
    # 关窗口只是藏到托盘，真正的退出由托盘菜单触发，所以不能“最后一个窗口关掉就退”
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(QFont(pick_font().strip('"'), 9))
    app.setStyleSheet(build_qss())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        _report(traceback.format_exc())
        raise SystemExit(1)
