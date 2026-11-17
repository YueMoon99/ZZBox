"""多阶段管线执行器：串行跑完拆帧 → 超分 → 补帧 → 合成。

和 runner.py 的区别在于这里一条「任务」是多个进程，且中间阶段的进度
没有 ffmpeg 的 -progress 可用，只能靠数产出目录里的帧数。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from app.core.ai import AiPlan, Stage, count_files


class AiRunner(QObject):
    progress = Signal(int)          # 整体 0-100
    stage = Signal(int, str)        # 阶段序号, 阶段名
    finished = Signal(bool, str)    # 成功与否, 错误信息
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._plan: AiPlan | None = None
        self._idx = 0
        self._done_weight = 0.0
        self._last_pct = -1
        self._buf = ""
        self._stderr: deque[str] = deque(maxlen=60)
        self._cancelled = False
        self._stage_pct = 0

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_count)

    # ------------------------------------------------------------------
    def busy(self) -> bool:
        return self._proc is not None

    def start(self, plan: AiPlan) -> None:
        self._plan = plan
        self._idx = 0
        self._done_weight = 0.0
        self._last_pct = -1
        self._cancelled = False
        self._run_stage()

    def cancel(self) -> None:
        if not self._proc:
            return
        self._cancelled = True
        self._timer.stop()
        self._proc.kill()
        self._proc.waitForFinished(3000)

    # ------------------------------------------------------------------
    def _total_weight(self) -> float:
        if not self._plan:
            return 1.0
        return sum(s.weight for s in self._plan.stages) or 1.0

    def _emit_overall(self) -> None:
        if not self._plan:
            return
        total = self._total_weight()
        frac = self._done_weight + self._stage_pct / 100.0 * self._cur_weight()
        pct = max(0, min(100, int(frac / total * 100)))
        if pct != self._last_pct:
            self._last_pct = pct
            self.progress.emit(pct)

    def _cur_weight(self) -> float:
        if not self._plan or self._idx >= len(self._plan.stages):
            return 0.0
        return self._plan.stages[self._idx].weight

    def _run_stage(self) -> None:
        plan = self._plan
        if not plan or self._idx >= len(plan.stages):
            self._timer.stop()
            self.finished.emit(True, "")
            return

        st: Stage = plan.stages[self._idx]
        self.stage.emit(self._idx, st.label)
        self._buf = ""
        self._stderr.clear()
        self._stage_pct = 0

        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("AV_LOG_FORCE_NOCOLOR", "1")
        proc.setProcessEnvironment(env)
        proc.setProgram(st.cmd[0])
        proc.setArguments(st.cmd[1:])
        # 超分/补帧会把每帧日志打到 stderr，混进同一个通道就解析不了 ffmpeg 的 progress
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        self._proc = proc
        self.log.emit(f"· [{st.label}] {Path(st.cmd[0]).name}")
        proc.start()

        if st.kind == "count":
            self._timer.start()

    # ------------------------------------------------------------------
    def _on_stdout(self) -> None:
        if not self._proc:
            return
        st = self._plan.stages[self._idx] if self._plan else None
        chunk = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if not st or st.kind != "ffmpeg":
            return
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            key, _, val = line.strip().partition("=")
            if key.strip() != "out_time_us":
                continue
            try:
                sec = int(val.strip()) / 1_000_000
            except ValueError:
                continue
            dur = max(st.duration, 0.01)
            self._stage_pct = max(0, min(100, int(sec / dur * 100)))
            self._emit_overall()

    def _on_stderr(self) -> None:
        if not self._proc:
            return
        chunk = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        for line in chunk.splitlines():
            if line.strip():
                self._stderr.append(line.strip())

    def _poll_count(self) -> None:
        """数产出目录的帧数推算进度。目录不存在时按 0 处理。"""
        if not self._plan or self._idx >= len(self._plan.stages):
            return
        st = self._plan.stages[self._idx]
        if st.kind != "count" or not st.watch_dir or st.expect <= 0:
            return
        got = count_files(st.watch_dir)
        self._stage_pct = max(self._stage_pct, min(99, int(got / st.expect * 100)))
        self._emit_overall()

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            name = Path(self._plan.stages[self._idx].cmd[0]).name if self._plan else "引擎"
            self._cleanup(False, f"无法启动 {name}，请确认文件未被杀毒软件删除")

    def _on_finished(self, code: int, _status) -> None:
        self._timer.stop()
        if self._cancelled:
            self._cleanup(False, "已取消")
            return
        st = self._plan.stages[self._idx] if self._plan else None
        if code != 0:
            self._cleanup(False, self._nice_error(code, st.label if st else ""))
            return
        self._stage_pct = 100
        self._done_weight += st.weight if st else 0.0
        self._emit_overall()
        self._proc = None
        self._idx += 1
        self._run_stage()

    # ------------------------------------------------------------------
    def _nice_error(self, code: int, stage: str) -> str:
        text = " ".join(self._stderr)
        low = text.lower()
        if "out of memory" in low or "vkallocatememory" in low or "vk::" in text:
            return f"{stage}阶段失败：显存不足，请降低倍率或输出分辨率"
        if "no space left" in low or "disk full" in low:
            return "磁盘空间不足，临时帧序列写不下了"
        if "cannot open" in low or "failed to open" in low:
            return f"{stage}阶段失败：文件读写被拒绝，检查输出目录权限"
        if "unsupported" in low or "invalid" in low and "model" in low:
            return f"{stage}阶段失败：模型文件不匹配，请重新下载 AI 引擎"
        tail = self._stderr[-1] if self._stderr else f"退出码 {code}"
        return f"{stage}阶段失败：{tail[:160]}"

    def _cleanup(self, ok: bool, msg: str) -> None:
        self._timer.stop()
        proc, self._proc = self._proc, None
        if proc:
            proc.deleteLater()
        self.finished.emit(ok, msg)
