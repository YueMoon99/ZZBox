"""图片任务执行器：串行跑完一条 1~2 步的命令链。

图片不需要 ai_runner 那套「数帧数推算进度」的机制 —— 单张图最多两个进程，
进度直接按阶段权重切分：超分引擎会往 stderr 打百分比，能解析就解析，
解析不到就把这一段按 0 处理（反正下一段一到就跳满）。
"""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

# 引擎的进度形如 "  12.50%"（前面可能有若干空格）
_PCT = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%\s*$")


class ImageRunner(QObject):
    progress = Signal(int)           # 整体 0-100
    finished = Signal(bool, str)     # 成功与否, 错误信息
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._cmds: list[list[str]] = []
        self._idx = 0
        self._stderr: deque[str] = deque(maxlen=60)
        self._cancelled = False
        self._step_pct = 0
        self._last = -1

    # ------------------------------------------------------------------
    def busy(self) -> bool:
        return self._proc is not None

    def start(self, cmds: list[list[str]], cleanups: list[Path] | None = None) -> None:
        self._cmds = cmds
        self._cleanups = cleanups or []
        self._idx = 0
        self._cancelled = False
        self._step_pct = 0
        self._last = -1
        if not cmds:
            self.finished.emit(False, "没有可执行的步骤")
            return
        self._run_step()

    def cancel(self) -> None:
        if not self._proc:
            return
        self._cancelled = True
        self._proc.kill()
        self._proc.waitForFinished(3000)

    def _cleanup_files(self) -> None:
        for p in self._cleanups:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
        self._cleanups = []

    # ------------------------------------------------------------------
    def _emit(self) -> None:
        # 每步占的进度区间：最后一步吃掉剩下的，前面的步骤均分到 90%
        n = len(self._cmds)
        span = 90.0 / n if n > 1 else 90.0
        pct = self._idx * span + self._step_pct / 100.0 * span
        pct = max(0, min(100, int(pct)))
        if pct != self._last:
            self._last = pct
            self.progress.emit(pct)

    def _run_step(self) -> None:
        if self._idx >= len(self._cmds):
            self.progress.emit(100)
            self._cleanup_files()
            self.finished.emit(True, "")
            return

        cmd = self._cmds[self._idx]
        self._step_pct = 0
        self._stderr.clear()
        self._emit()

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
        self.log.emit("· " + Path(cmd[0]).name)
        proc.start()

    def _on_stdout(self) -> None:
        if self._proc:
            self._read(bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace"))

    def _on_stderr(self) -> None:
        if self._proc:
            self._read(bytes(self._proc.readAllStandardError()).decode("utf-8", "replace"))

    def _read(self, chunk: str) -> None:
        for line in chunk.splitlines():
            text = line.strip()
            if not text:
                continue
            m = _PCT.match(text)
            if m:
                self._step_pct = max(0, min(99, int(float(m.group(1)))))
                self._emit()
            else:
                self._stderr.append(text)

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            name = Path(self._cmds[self._idx][0]).name if self._cmds else "程序"
            self._cleanup(False, f"无法启动 {name}，请确认文件未被杀毒软件删除")

    def _on_finished(self, code: int, _status) -> None:
        if self._cancelled:
            self._cleanup(False, "已取消")
            return
        if code != 0:
            self._cleanup(False, self._nice_error(code))
            return
        self._step_pct = 100
        self._emit()
        self._proc = None
        self._idx += 1
        self._run_step()

    def _nice_error(self, code: int) -> str:
        text = " ".join(self._stderr)
        low = text.lower()
        if "out of memory" in low or "vkallocatemem" in low or "failed to allocate" in low:
            return "显存不足，请降低超分倍率"
        if "no space left" in low or "disk full" in low:
            return "磁盘空间不足"
        if "permission denied" in low:
            return "没有写入权限，请换一个输出目录"
        if "invalid data" in low or "could not open" in low or "no such file" in low:
            return "图片无法读取，可能已损坏或格式不支持"
        if "unsupported" in low or "not supported" in low:
            return "格式不支持，换一种输出格式再试"
        tail = self._stderr[-1] if self._stderr else f"退出码 {code}"
        return tail[:160]

    def _cleanup(self, ok: bool, msg: str) -> None:
        proc, self._proc = self._proc, None
        if proc:
            proc.deleteLater()
        # 失败/取消时也要删中间文件，否则删一次留一个 20 MB 的 png
        self._cleanup_files()
        self.finished.emit(ok, msg)
