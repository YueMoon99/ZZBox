"""控制面板布局与高度回归测试。

锁住四件事：
1. 面板高度固定 —— 提示文字（灰/黄）出现、变长、清空都不改变面板高度；
2. 提示区恒定两行（灰一行 + 黄一行），超宽走跑马灯滚动而不是换行撑高；
3. 视频 AI 页两行三列（超分/补帧/模型、编码/降噪/锐化），标签竖向对齐；
   图片 AI 页同款（倍率/模型/格式、降噪/锐化）；四个面板都只有两行按钮；
4. 胶囊按钮组内等宽、全局等高；面板只剩一层圆角边框（ptabpane 无边框）。

用法：python tools/test_panel_layout.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from app.ui import style  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

app.setStyleSheet(style.build_qss())

FAILS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS += 1


def main() -> int:
    win = MainWindow()
    win.resize(1180, 820)
    win.show()
    app.processEvents()

    # ================================================================
    print("== 面板高度固定（提示文字不许撑高） ==")
    win.tabs.setCurrentIndex(1)
    app.processEvents()
    panel = win.ai_panel
    h0 = panel.height()
    check("基准高度 > 0", h0 > 0, str(h0))

    for label, note, alert in (
        ("空提示", "引擎检测中…", ""),
        (
            "长警告",
            "引擎检测中…",
            "⚠ " + "很长的警告" * 40,
        ),
        (
            "长说明+长警告",
            "超分 就绪·5模型 · 补帧 就绪 · 显存 8G·高 · 推荐 2× · 当前 3840×2160 · 60fps",
            "⚠ 临时约 3.2 GB → D:\\ · 另一条警告",
        ),
        ("清空后", "", ""),
    ):
        panel.set_note(note)
        panel.set_alert(alert)
        app.processEvents()
        check(f"{label}高度不变", panel.height() == h0, f"{panel.height()} vs {h0}")

    heights = {}
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    heights["视频压缩"] = win.compress_panel.height()
    win.tabs.setCurrentIndex(1)
    app.processEvents()
    heights["视频AI"] = win.ai_panel.height()
    win.img_tabs.setCurrentIndex(0)
    app.processEvents()
    heights["图片压缩"] = win.img_panel.height()
    win.img_tabs.setCurrentIndex(1)
    app.processEvents()
    heights["图片AI"] = win.img_ai_panel.height()
    check("四面板高度一致", len(set(heights.values())) == 1, str(heights))

    # ================================================================
    print("== 提示区恒定两行，超宽滚动 ==")
    win.tabs.setCurrentIndex(1)
    app.processEvents()
    panel = win.ai_panel
    check("note 是固定单行", panel.note.height() == 18 and not panel.note.wordWrap())
    check("alert 是固定单行", panel.alert.height() == 18 and not panel.alert.wordWrap())
    check(
        "提示行上下相邻（灰上黄下）",
        panel.alert.y() > panel.note.y(),
        f"note.y={panel.note.y()} alert.y={panel.alert.y()}",
    )
    panel.set_alert("⚠ " + "很长的警告" * 40)
    app.processEvents()
    check("超宽警示进入滚动", panel.alert._timer.isActive())
    panel.set_alert("短")
    app.processEvents()
    check("短文本不滚动", not panel.alert._timer.isActive())
    panel.set_alert("")

    # ================================================================
    print("== AI 页两行三列，标签竖向对齐 ==")
    win.tabs.setCurrentIndex(1)
    app.processEvents()
    grid = win.ai_panel._grid
    cells = sum(
        1 for r in range(3) for c in range(3) if grid.itemAtPosition(r, c) is not None
    )
    check("AI 页 2×3 六格", cells == 6, f"cells={cells}")
    check("AI 页没有第三行", grid.itemAtPosition(2, 0) is None)

    def tag_x(r: int, c: int) -> int:
        cell = grid.itemAtPosition(r, c).widget()
        return cell.layout().itemAt(0).widget().geometry().x()

    aligned = (
        tag_x(0, 0) == tag_x(1, 0)
        and tag_x(0, 1) == tag_x(1, 1)
        and tag_x(0, 2) == tag_x(1, 2)
    )
    check("AI 页标签竖向对齐（表格列）", aligned)

    labels = []
    for r in range(2):
        row = []
        for c in range(3):
            cell = grid.itemAtPosition(r, c).widget()
            row.append(cell.layout().itemAt(0).widget().text())
        labels.append(row)
    check(
        "AI 页排布为 超分/补帧/模型 + 编码/降噪/锐化",
        labels == [["超分", "补帧", "模型"], ["编码", "降噪", "锐化"]],
        str(labels),
    )

    win.img_tabs.setCurrentIndex(1)
    app.processEvents()
    igrid = win.img_ai_panel._grid
    icells = sum(
        1 for r in range(3) for c in range(3) if igrid.itemAtPosition(r, c) is not None
    )
    check("图片 AI 页五格（降噪/锐化独立成格）", icells == 5, f"cells={icells}")
    ilabels = []
    for r in range(2):
        row = []
        for c in range(3):
            item = igrid.itemAtPosition(r, c)
            if item is not None:
                row.append(item.widget().layout().itemAt(0).widget().text())
        ilabels.append(row)
    check(
        "图片 AI 页排布为 倍率/模型/格式 + 降噪/锐化",
        ilabels == [["倍率", "模型", "格式"], ["降噪", "锐化"]],
        str(ilabels),
    )

    # 四个面板都只有两行按钮（第 2 行有格子、第 3 行没有）
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    for name, panel in (
        ("视频压缩", win.compress_panel),
        ("视频AI", win.ai_panel),
        ("图片压缩", win.img_panel),
        ("图片AI", win.img_ai_panel),
    ):
        g = panel._grid
        has_r2 = any(g.itemAtPosition(2, c) is not None for c in range(4))
        check(f"{name}只有两行按钮", not has_r2)

    # ================================================================
    print("== 胶囊统一尺寸 ==")
    check(
        "胶囊固定高度 28",
        win.ai_scale_chips.button("2").height() == 28,
    )
    check(
        "同组等宽（降噪）",
        win.ai_denoise_chips.button("0").width()
        == win.ai_denoise_chips.button("1").width(),
    )
    check(
        "同组等宽（编码）",
        win.ai_enc_chips.button("h264").width()
        == win.ai_enc_chips.button("av1").width(),
    )
    check(
        "跨组同高（模型）",
        win.ai_model_chips.button("photo").height() == 28,
    )

    # ================================================================
    print("== 同列按钮组左右边缘对齐（像表格一样） ==")
    win.tabs.setCurrentIndex(1)
    app.processEvents()
    # 一列一组：超分/编码、补帧/降噪、模型/锐化
    for idx, col in enumerate(
        (
            (win.ai_scale_chips, win.ai_enc_chips),
            (win.ai_interp_chips, win.ai_denoise_chips),
            (win.ai_model_chips, win.ai_sharpen_chips),
        ),
        start=1,
    ):
        edges = []
        for grp in col:
            btns = list(grp._buttons.values())
            left = btns[0].mapTo(win.ai_panel, btns[0].rect().topLeft()).x()
            right = btns[-1].mapTo(win.ai_panel, btns[-1].rect().topRight()).x()
            edges.append((left, right))
        check(
            f"第 {idx} 列按钮组左边缘一致（统一居左）",
            len({e[0] for e in edges}) == 1,
            str(edges),
        )
        check(
            f"第 {idx} 列按钮组右边缘一致（宽度之和相等）",
            len({e[1] for e in edges}) == 1,
            str(edges),
        )
    check(
        "列内按钮平分整格（降噪与补帧同宽）",
        win.ai_denoise_chips.button("0").width() == win.ai_interp_chips.button("2").width(),
        f"{win.ai_denoise_chips.button('0').width()} vs "
        f"{win.ai_interp_chips.button('2').width()}",
    )

    # ================================================================
    print("== 单层边框 ==")
    from PySide6.QtWidgets import QStackedWidget

    stack = win.tabs.stack
    check("ptabpane 是 QStackedWidget", isinstance(stack, QStackedWidget))
    ss = stack.styleSheet() or ""
    # 全局 QSS 里 ptabpane 不应再画边框
    qss = style.build_qss()
    seg = qss.split("QStackedWidget#ptabpane")[1].split("}")[0]
    check("ptabpane 无边框", "border:none" in seg.replace(" ", ""), seg.strip())
    seg2 = qss.split("QPushButton#ptab")[1].split("}")[0]
    check("ptab 扁平无三面边框", "border:none" in seg2.replace(" ", ""), seg2.strip())

    print("FAILS:", FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
