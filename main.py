"""舟舟视频工具箱（ZZBox） · 程序入口。"""

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

    say(f"total {time.time() - t0:.1f}s")
    say("RESULT = " + ("PASS" if ok else "FAIL"))
    (ROOT / "logs" / "selftest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

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
    # "舟舟视频工具箱（ZZBox） v0.6.1 - 舟舟视频工具箱（ZZBox）"，标题栏会显得重复
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
