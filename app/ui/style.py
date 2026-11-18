"""深色主题样式表。"""

BG = "#1b1b1e"
SURFACE = "#232327"
HEADER = "#202024"
BORDER = "#2e2e34"
BORDER_STRONG = "#3a3a42"
TEXT = "#ececee"
MUTED = "#9c9ca3"
DIM = "#7c7c84"
ACCENT = "#185fa5"
ACCENT_HOVER = "#1d6fc0"
ACCENT_TEXT = "#e6f1fb"
BLUE_LIGHT = "#85b7eb"
TRACK = "#2f2f35"
QUEUE_BG = "#1f1f24"      # 队列表格底色（操作列自绘背景要和它一致）
ROW_SEL = "#22303f"       # 选中行底色
ROW_HOVER = "#27272d"     # 悬停行底色（整行，包括操作列）
ROW_LINE = "#2e2e37"      # 行分隔线

OK_COLOR = "#5dcaa5"
ERR_COLOR = "#f09595"
WARN_COLOR = "#ef9f27"
DOT_LOCKED = "#6d6d76"

QSS_TEMPLATE = f"""
QMainWindow, QDialog {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-family: __FONT__;
    font-size: 12px;
}}
QLabel#title {{ font-size: 13px; font-weight: 500; }}
QLabel#version {{ font-size: 11px; color: {DIM}; }}
QLabel#hint {{ font-size: 11px; color: {DIM}; }}
QLabel#alert {{ font-size: 11px; color: {WARN_COLOR}; }}
QLabel#sectionTitle {{ font-size: 12px; color: {MUTED}; }}

QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
/* 集成化参数面板：一张扁卡片装满所有参数，替代 2×2 的四张 Card */
QFrame#optpanel {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#optlabel {{ font-size: 11px; color: {MUTED}; }}

/* 顶部「视频处理 / 图片处理」大分段：整条是一个面，选中的那块浮起来 */
QFrame#modebar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton#mode {{
    border: none;
    border-radius: 7px;
    padding: 5px 18px;
    color: {MUTED};
    font-size: 12px;
    background: transparent;
}}
QPushButton#mode:hover {{ color: {TEXT}; background: #2c2c33; }}
QPushButton#mode:checked {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 500;
}}
QPushButton#mode:checked:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#mode:disabled {{ color: #55555c; }}
QFrame#queue {{
    background: {QUEUE_BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
}}
QFrame#header {{
    background: {HEADER};
    border-bottom: 1px solid #2a2a30;
}}

QPushButton {{
    background: transparent;
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 8px;
    color: {MUTED};
}}
QPushButton:hover {{ border-color: #4a4a55; color: {TEXT}; }}
QPushButton:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: {ACCENT_TEXT};
}}
QPushButton:disabled {{ color: #55555c; border-color: #2c2c32; }}
QPushButton:checked:disabled {{ background: #2a3a4d; border-color: #2a3a4d; color: #6c8aa8; }}

QPushButton#primary {{
    background: {ACCENT};
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    color: {ACCENT_TEXT};
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #2a2a30; color: #5c5c64; }}

QPushButton#ghost {{
    padding: 8px 16px;
    border-radius: 8px;
    color: #c9c9cf;
    border: 1px solid {BORDER_STRONG};
}}
QPushButton#rowbtn {{
    border: none;
    border-radius: 4px;
    padding: 0px;
    font-size: 10px;
    color: {DIM};
    background: transparent;
}}
QPushButton#rowbtn:hover {{ background: #2e2e35; color: {TEXT}; }}
QPushButton#rowbtn:checked {{ background: #33333b; color: {WARN_COLOR}; }}
QPushButton#rowbtn:disabled {{ color: #4a4a52; }}

QPushButton#link {{
    border: none;
    padding: 2px 4px;
    color: {BLUE_LIGHT};
    font-size: 11px;
}}
QPushButton#link:hover {{ color: #b5d4f4; }}
QPushButton#link:disabled {{ color: #4a4a52; }}

/* 顶栏那个方形的「+」：只放一个小图标，不占文字宽度 */
QPushButton#addbtn {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 0px;
    color: {MUTED};
    font-size: 16px;
    font-weight: 500;
}}
QPushButton#addbtn:hover {{ border-color: #4a4a55; color: {TEXT}; background: #2a2a31; }}

QLineEdit {{
    background: {BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: #55555c; }}

QSpinBox {{
    background: {BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 4px 6px;
    color: {TEXT};
}}
QSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 0px;
    height: 0px;
    border: none;
}}

/* 队列：文件资源管理器风格的表格。表头常驻，行之间用细线分隔 */
QTableWidget#queueTable {{
    background: transparent;
    border: none;
    outline: none;
    gridline-color: transparent;
    color: {TEXT};
}}
QTableWidget#queueTable::item {{
    /* 行底和行分隔线由 QueueTable 在视口里整行画：QSS 的 item 覆盖不到
       「操作」列（那列是 cellWidget），逐格 setBackground 也会被样式表吃掉 */
    border: none;
    padding: 0px 10px;
}}
/* 悬停不在这里画：QSS 的 :hover 只亮鼠标下那一个格子，整行悬停由
   QueueTable 在视口里自绘 */
QTableWidget#queueTable::item:selected {{
    /* 这一格也不得不给具体颜色：写 transparent 时 Qt 会退回 Fusion 调色板
       的高亮蓝（#308cc6）。给的就是整行选中色，和视口自绘的那一层同色，
       拼起来看不出接缝 */
    background: {ROW_SEL};
    color: {TEXT};
}}
/* 拖动排序的落点提示线：2px，用的是和选中胶囊同一个强调蓝 */
QFrame#dropline {{
    background: {ACCENT};
    border: none;
    border-radius: 1px;
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {HEADER};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid #33333b;
    padding: 0px 10px;
    font-size: 11px;
}}
QHeaderView::section:hover {{ color: #cfcfd6; }}
QTableCornerButton::section {{ background: {HEADER}; border: none; }}
QLabel#emptyHint {{ color: {DIM}; font-size: 12px; }}

/* PDF 页面格墙。和表格不一样，这里是「一格一页」，选中态靠底色 + 描边，
   默认态给一圈透明边框，选中时才换成强调色 —— 否则加边框会把格子挤动 1px，
   整面墙跟着抖一下 */
QListWidget#pageGrid {{
    background: transparent;
    border: none;
    outline: none;
    color: {MUTED};
}}
QListWidget#pageGrid::item {{
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px 2px 2px 2px;
    font-size: 11px;
    color: {DIM};
}}
QListWidget#pageGrid::item:hover {{ background: #27272d; color: {MUTED}; }}
QListWidget#pageGrid::item:selected {{
    background: {ROW_SEL};
    border: 1px solid {ACCENT};
    color: {TEXT};
}}
QLabel#dlgTitle {{ font-size: 14px; font-weight: 500; }}

QProgressBar {{
    background: {TRACK};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: #378add; border-radius: 3px; }}

QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #3a3a42; border-radius: 4px; min-height: 24px;
}}
/* 列被拖宽到超过窗口时才会出现，样式跟竖向保持一致，别冒出个亮色系统滚动条 */
QScrollBar:horizontal {{
    background: transparent; height: 8px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #3a3a42; border-radius: 4px; min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {HEADER};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 4px 6px;
}}

/* 托盘右键菜单：不写这段的话，深色界面里会弹出一块白色系统菜单 */
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 26px 6px 14px;
    border-radius: 5px;
    color: {TEXT};
    font-size: 12px;
}}
QMenu::item:selected {{ background: #2b3949; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}

/* ---- 属性页页签：扁平胶囊 + 圆角内容卡 ----
   原设计是 Windows 属性对话框那种「页签和内容面板连成一体」：内容区画
   方角边框、页签下画贯穿线并在活动页签处断开。但内容卡是圆角的 ——
   直线和方角在圆角外露出来，就是用户说的「圆角框外多一个直角框」。
   现在只保留圆角内容卡这一层边框，页签改成扁平胶囊。 */
QPushButton#ptab {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 5px 18px;
    color: {MUTED};
    font-size: 12px;
}}
QPushButton#ptab:hover {{ color: {TEXT}; background: #26262b; }}
QPushButton#ptab:checked {{
    background: #2c2c33;
    color: {TEXT};
    font-weight: 500;
}}
QStackedWidget#ptabpane {{
    background: transparent;
    border: none;
}}
"""


_FONT_CACHE: str | None = None
_PREFERRED = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans SC",
    "DengXian",
    "PingFang SC",
    "SimHei",
)


def pick_font() -> str:
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE
    from PySide6.QtGui import QFontDatabase

    families = set(QFontDatabase.families())
    for name in _PREFERRED:
        if name in families:
            _FONT_CACHE = f'"{name}"'
            return _FONT_CACHE
    _FONT_CACHE = "sans-serif"
    return _FONT_CACHE


def build_qss() -> str:
    return QSS_TEMPLATE.replace("__FONT__", pick_font())
