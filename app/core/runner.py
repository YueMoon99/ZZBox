"""基于 QProcess 的异步编码进程封装，负责进度解析与取消。"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


class EncodeRunner(QObject):
    progress = Signal(int, float, str)   # 百分比, 速度倍率, 剩余时间文本
    finished = Signal(bool, str)         # 是否成功, 错误信息
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._duration = 0.0
        self._buf = ""
        self._stderr: deque[str] = deque(maxlen=40)
        self._cancelled = False
        self._speed = 1.0

    def busy(self) -> bool:
        return self._proc is not None

    def start(self, cmd: list[str], duration: float) -> None:
        self._duration = max(duration, 0.01)
        self._buf = ""
        self._cancelled = False
        self._stderr.clear()

        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("AV_LOG_FORCE_NOCOLOR", "1")
        proc.setProcessEnvironment(env)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        self._proc = proc
        self.log.emit("· " + " ".join(cmd))
        proc.start()

    def cancel(self) -> None:
        if not self._proc:
            return
        self._cancelled = True
        self._proc.kill()
        self._proc.waitForFinished(3000)

    # ------------------------------------------------------------------
    def _on_stdout(self) -> None:
        if not self._proc:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line: str) -> None:
        if not line or "=" not in line:
            return
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key == "out_time_us":
            try:
                sec = int(val) / 1_000_000
            except ValueError:
                return
            pct = max(0, min(100, int(sec / self._duration * 100)))
            speed = 1.0
            if self._speed:
                speed = self._speed
            remaining = ""
            if speed > 0 and sec < self._duration:
                left = (self._duration - sec) / speed
                m, s = divmod(int(left), 60)
                remaining = f"剩余 {m:02d}:{s:02d}"
            self.progress.emit(pct, speed, remaining)
        elif key == "speed":
            try:
                self._speed = float(val.rstrip("x"))
            except ValueError:
                self._speed = 1.0

    def _on_stderr(self) -> None:
        if not self._proc:
            return
        chunk = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        for line in chunk.splitlines():
            if line.strip():
                self._stderr.append(line.strip())
                self.log.emit(line.rstrip())

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            self._cleanup(False, "无法启动 ffmpeg，请确认 bin 目录中的 ffmpeg.exe 存在")

    def _on_finished(self, code: int, _status) -> None:
        if self._cancelled:
            self._cleanup(False, "已取消")
            return
        if code == 0:
            self.progress.emit(100, self._speed, "完成")
            self._cleanup(True, "")
        else:
            self._cleanup(False, self._nice_error(code))

    def _nice_error(self, code: int) -> str:
        text = " ".join(self._stderr)
        low = text.lower()
        if "no space left" in low or "disk full" in low:
            return "磁盘空间不足"
        if "invalid data found" in low or "moov atom not found" in low:
            return "文件已损坏或格式不支持"
        if "permission denied" in low:
            return "没有写入权限，请换一个输出目录"
        if "unknown encoder" in low:
            return "当前 ffmpeg 不支持该编码器"
        if "out of memory" in low:
            return "显存或内存不足"
        if "already exists" in low:
            return "输出文件已存在"
        tail = self._stderr[-1] if self._stderr else f"ffmpeg 退出码 {code}"
        return tail[:180]

    def _cleanup(self, ok: bool, msg: str) -> None:
        proc, self._proc = self._proc, None
        if proc:
            proc.deleteLater()
        self.finished.emit(ok, msg)
