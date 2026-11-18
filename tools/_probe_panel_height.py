"""验证：提示文字出现/变长/清空时，控制面板高度必须纹丝不动；
并截各页面板确认布局。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from app.ui import style  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

app.setStyleSheet(style.build_qss())

win = MainWindow()
win.resize(1180, 820)
win.show()
app.processEvents()

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        fails += 1


# ---------- 1. 高度稳定性：视频 AI 页 ----------
win.tabs.setCurrentIndex(1)
app.processEvents()
panel = win.ai_panel
h0 = panel.height()

panel.set_alert("")
app.processEvents()
check("AI 页空警示时高度", panel.height() == h0, f"{panel.height()} vs {h0}")

panel.set_alert("⚠ 临时约 3.2 GB → D:\\（余 120 GB），做完自动删 · 高于推荐档，更慢更占空间 · 还有一条很长很长的警告用来测试跑马灯滚动效果会不会把面板撑高")
app.processEvents()
check("AI 页长警示时高度不变", panel.height() == h0, f"{panel.height()} vs {h0}")

panel.set_note("超分 就绪·5模型 · 补帧 就绪 · 显存 8G·高 · 推荐 2×（1080p 素材） · 当前 3840×2160 · 60fps · 约 12 分钟 · 换行不该发生")
app.processEvents()
check("AI 页长说明时高度不变", panel.height() == h0, f"{panel.height()} vs {h0}")

panel.set_alert("")
panel.set_note("引擎检测中…")
app.processEvents()
check("AI 页清空后高度不变", panel.height() == h0, f"{panel.height()} vs {h0}")

# ---------- 2. 四个面板高度一致 ----------
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
check(
    "四面板高度一致",
    len(set(heights.values())) == 1,
    str(heights),
)

# ---------- 3. 布局：两行按钮 ----------
win.tabs.setCurrentIndex(1)
app.processEvents()
grid = win.ai_panel._grid
rows = {grid.itemAtPosition(r, c).widget().height() for r in range(2) for c in range(3)
        if grid.itemAtPosition(r, c) is not None}
cells = sum(
    1 for r in range(3) for c in range(3) if grid.itemAtPosition(r, c) is not None
)
check("AI 页 2×3 格子", cells == 6, f"cells={cells}")
check("AI 页无第三行按钮", grid.itemAtPosition(2, 0) is None)

# 标签竖向对齐：同一列两行的标签 x 坐标一致
def tag_x(r: int, c: int) -> int:
    cell = grid.itemAtPosition(r, c).widget()
    return cell.layout().itemAt(0).widget().x()


check(
    "AI 页标签竖向对齐",
    tag_x(0, 0) == tag_x(1, 0) and tag_x(0, 1) == tag_x(1, 1) and tag_x(0, 2) == tag_x(1, 2),
)

# 胶囊等高
btn = win.ai_scale_chips.button("2")
check("胶囊固定高度 28", btn.height() == 28, str(btn.height()))
check(
    "同组胶囊等宽",
    win.ai_denoise_chips.button("0").width() == win.ai_denoise_chips.button("1").width(),
)

# ---------- 4. 跑马灯：超宽文本时计时器在跑 ----------
win.ai_panel.set_alert("⚠ " + "很长的警告" * 40)
app.processEvents()
check("超宽警示进入滚动", win.ai_panel.alert._timer.isActive())
win.ai_panel.set_alert("短")
app.processEvents()
check("短文本不滚动", not win.ai_panel.alert._timer.isActive())
win.ai_panel.set_alert("")

# ---------- 5. 图片 AI 页布局 ----------
win.img_tabs.setCurrentIndex(1)
app.processEvents()
igrid = win.img_ai_panel._grid
icells = sum(
    1 for r in range(3) for c in range(3) if igrid.itemAtPosition(r, c) is not None
)
check("图片 AI 页 5 格（倍率/模型/格式/降噪/锐化）", icells == 5, f"cells={icells}")

# ---------- 6. 截图存档 ----------
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots"), exist_ok=True)
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
win.tabs.setCurrentIndex(1)
win.ai_panel.set_alert("⚠ 临时约 3.2 GB → D:\\（余 120 GB）")
app.processEvents()
win.grab().save(os.path.join(base, "ai_page.png"))
win.ai_panel.set_alert("")
win.tabs.setCurrentIndex(0)
app.processEvents()
win.grab().save(os.path.join(base, "compress_page.png"))
win.img_tabs.setCurrentIndex(1)
app.processEvents()
win.grab().save(os.path.join(base, "img_ai_page.png"))

print("FAILS:", fails)
sys.exit(1 if fails else 0)
