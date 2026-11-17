"""PDF 任务执行器。

和另外三个执行器不一样：它们跑的是外部 exe（QProcess 能吃 stdout、
能 kill），PDF 处理是进程内的 Python 调用，没有子进程可管。所以这里用
后台线程 + 协作式取消 —— 进度回调每次都问一句「还继续吗」，
取消就是把标记立起来，等它在下一次回调时自己退出。

这种取消不是立即的：正在渲染的那一页会渲染完。对单页最多零点几秒的
任务来说，等它比强行掐断安全得多（强杀线程会留下半个 PDF 文件）。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from app.core.pdf import PdfCancelled, PdfError


class PdfRunner(QObject):
    progress = Signal(int)        # 0-100
    finished = Signal(bool, str)  # 成功与否, 说明或错误

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._running = False

    def busy(self) -> bool:
        return self._running

    @property
    def cancel_event(self) -> threading.Event:
        """给 core 里那些协作式取消的函数用（merge_pdf 之类会一直看它）。"""
        return self._cancel

    def start(self, work, label: str = "") -> None:
        """work(progress) 在后台跑，progress 是 0-100 的回调。

        返回值是给人看的一句话（输出路径、页数之类），原样透传到 finished。
        """
        if self._running:
            self.finished.emit(False, "还有任务在跑，等它结束")
            return
        self._cancel.clear()
        self._running = True
        self._label = label
        self._thread = threading.Thread(target=self._run, args=(work,), daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        if self._running:
            self._cancel.set()

    # ------------------------------------------------------------------
    def _emit(self, pct: int) -> None:
        if self._cancel.is_set():
            # 抛出即中止。core 里 PdfCancelled 是 PdfError 的子类，
            # 不会被"包装成友好错误"的那层 except 吞掉
            raise PdfCancelled("已取消")
        self.progress.emit(max(0, min(100, int(pct))))

    def _run(self, work) -> None:
        try:
            note = work(self._emit) or ""
            ok, msg = True, str(note)
        except PdfCancelled:
            ok, msg = False, "已取消"
        except PdfError as exc:
            ok, msg = False, str(exc)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"{type(exc).__name__}: {exc}"
        self._running = False
        self._thread = None
        self.finished.emit(ok, msg)
