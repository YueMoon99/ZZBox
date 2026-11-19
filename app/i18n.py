"""界面语言：中文 / English。

UI 源码里继续写中文原文，翻译发生在「文字写进控件」的那一刻，所以加一门
语言不需要去改几百处 setText / setToolTip：

  · ``tr()`` 查表：先整串精确匹配，再按 `` · `` 拆段分别翻，最后用带
    ``{}`` 的模板匹配（例如 ``锁定 {}``），动态数字也能落到译文里。
  · ``install()`` 给 Qt 的文本 setter 打补丁（setText / setToolTip /
    setWindowTitle / addAction / addItem / setHorizontalHeaderLabels …），
    之后所有动态写入都会自动翻译。
  · ``retranslate_all()`` 遍历现成控件重写一遍，实现运行中切语言而不丢队列。

中英双向共用一张表：英文态查正表，中文态查反表，因此 ``tr()`` 是幂等的 ——
把已经是目标语言的文字再喂进去不会翻两次。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from app.i18n_strings import STRINGS

ZH = "zh"
EN = "en"

LANG = ZH

# 中文 -> 英文 / 英文 -> 中文
_EN: dict[str, str] = {}
_ZH: dict[str, str] = {}
# 模板条目：(编译好的正则, 目标模板) —— 按字面量长度从长到短
_TPL_TO_EN: list[tuple[re.Pattern[str], str]] = []
_TPL_TO_ZH: list[tuple[re.Pattern[str], str]] = []

_installed = False
_listeners: list = []
_config_file: Path | None = None


# ====================================================================== 词表
def _template(text: str) -> re.Pattern[str]:
    """``超分 {}×`` -> 只匹配「超分 4×」这类串的正则。

    占位符用 ``(.*?)`` 而不是 ``(.+?)``：像「选中 3 项 · 1.2 MB → 800 KB」
    这种末尾动态段可为空，``+`` 会让整条模板匹配不上，退回更宽松的短模板。
    """
    parts = text.split("{}")
    return re.compile("^" + "(.*?)".join(re.escape(p) for p in parts) + "$", re.S)


def _build() -> None:
    if _EN:
        return
    tpl_en: list[tuple[int, re.Pattern[str], str]] = []
    tpl_zh: list[tuple[int, re.Pattern[str], str]] = []
    for zh, en in STRINGS.items():
        if not zh or not en or zh == en:
            continue
        if "{}" in zh or "{}" in en:
            # 只有两边占位符数量对得上才当模板用，否则按普通词条收着
            if zh.count("{}") == en.count("{}") and "{}" in zh:
                tpl_en.append((len(zh), _template(zh), en))
                tpl_zh.append((len(en), _template(en), zh))
            continue
        _EN[zh] = en
        _ZH.setdefault(en, zh)
    tpl_en.sort(key=lambda x: -x[0])
    tpl_zh.sort(key=lambda x: -x[0])
    _TPL_TO_EN.extend((rx, tpl) for _n, rx, tpl in tpl_en)
    _TPL_TO_ZH.extend((rx, tpl) for _n, rx, tpl in tpl_zh)


_build()


# ====================================================================== 查询
def _split_join(text: str, sep: str, fn) -> str | None:
    """按分隔符拆开逐段翻，再拼回去；没有任何一段被翻过就返回 None。"""
    if sep not in text:
        return None
    pieces = text.split(sep)
    out = [fn(p) for p in pieces]
    if out == pieces:
        return None
    return sep.join(out)


def _fill(template: str, groups: tuple[str, ...], depth: int = 0) -> str:
    """把捕获到的动态部分填回目标模板（顺序对应）。

    捕获段本身也可能带中文（``文件队列 · {}`` 里装着「3 个 · 锁定 1」），
    所以填之前先翻一遍；深度有上限，免得两个模板互相套。
    """
    parts = template.split("{}")
    out = parts[0]
    for i, g in enumerate(groups):
        out += _translate(g, depth + 1) if depth < 4 else g
        if i + 1 < len(parts):
            out += parts[i + 1]
    return out


def _translate(text: str, depth: int = 0) -> str:
    out = _to_en(text, depth) if LANG == EN else _to_zh(text, depth)
    if LANG == EN and out != text:
        # 中文没有单复数，模板只能统一给复数；「1 items」这种收一下
        out = _SINGULAR.sub(lambda m: "1 " + m.group(1)[:-1], out)
    return out


_SINGULAR = re.compile(r"\b1 (items|images|files|pages|models|folders|tasks)\b")


def _to_en(text: str, depth: int = 0) -> str:
    hit = _EN.get(text)
    if hit is not None:
        return hit
    for rx, tpl in _TPL_TO_EN:
        m = rx.match(text)
        if m:
            return _fill(tpl, m.groups(), depth)
    # 「文件队列 · 3 个 · 锁定 1」这种拼接串：一段段翻
    for sep in (" · ", "；", "：", "，"):
        got = _split_join(text, sep, lambda p: _to_en(p, depth + 1))
        if got is not None:
            if sep in "；：，":
                got = got.replace(sep, {"；": "; ", "：": ": ", "，": ", "}[sep])
            return got
    return text


def _to_zh(text: str, depth: int = 0) -> str:
    hit = _ZH.get(text)
    if hit is not None:
        return hit
    for rx, tpl in _TPL_TO_ZH:
        m = rx.match(text)
        if m:
            return _fill(tpl, m.groups(), depth)
    for sep, zh_sep in ((" · ", " · "), ("; ", "；"), (": ", "："), (", ", "，")):
        got = _split_join(text, sep, lambda p: _to_zh(p, depth + 1))
        if got is not None:
            return got.replace(sep, zh_sep) if sep != zh_sep else got
    return text


def tr(text: str) -> str:
    """把一段界面文字翻成当前语言；查不到就原样返回。"""
    if not text or not isinstance(text, str):
        return text
    return _translate(text)


def switch_label() -> str:
    """语言按钮上写「对方」的语言：中文态提示切到英文，反之亦然。"""
    return "Switch to English" if LANG == ZH else "切换至中文"


def switch_tip() -> str:
    return "切换到英文界面" if LANG == ZH else "Switch to Chinese interface"


# ====================================================================== 持久化
def _candidates() -> list[Path]:
    out: list[Path] = []
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(
        __file__
    ).resolve().parents[1]
    out.append(root / "ui.json")
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    out.append(Path(base) / "ZZBox" / "ui.json")
    return out


def _read_lang() -> str:
    global _config_file
    for path in _candidates():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        code = str(data.get("language", "")).lower()
        if code in (ZH, EN):
            _config_file = path
            return code
    return ZH


def _write_lang(code: str) -> None:
    global _config_file
    targets = ([_config_file] if _config_file else []) + _candidates()
    for path in targets:
        if path is None:
            continue
        try:
            data = {}
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            data["language"] = code
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _config_file = path
            return
        except OSError:
            continue


def load() -> str:
    """读上次选的语言。要在建窗口之前调用。"""
    global LANG
    LANG = _read_lang()
    return LANG


# ====================================================================== 切语言
def on_change(cb) -> None:
    _listeners.append(cb)


def set_language(code: str) -> None:
    global LANG
    code = code if code in (ZH, EN) else ZH
    if code == LANG:
        return
    LANG = code
    _write_lang(code)
    retranslate_all()
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            pass


# ====================================================================== 打补丁
_ORIG: dict[tuple[type, str], object] = {}


def _patch(cls, name: str, index: int = 0) -> None:
    """把 ``cls.name(str_arg)`` 的字符串参数先过一遍 tr()。"""
    orig = getattr(cls, name)
    _ORIG[(cls, name)] = orig

    def patched(self, *args, **kwargs):  # noqa: ANN001
        if len(args) > index and isinstance(args[index], str):
            args = list(args)
            args[index] = tr(args[index])
        return orig(self, *args, **kwargs)

    patched.__name__ = name
    setattr(cls, name, patched)


def literal(widget, text: str, attr: str = "setText") -> None:
    """把「已经是对应语言」的文字写进控件，绕开 tr()。

    语言切换按钮自己要用：中文态它上面写的就是英文 ``Switch to English``，
    走 setText 补丁的话会被反向词表当成待翻的英文再翻回中文。
    """
    for cls in type(widget).__mro__:
        orig = _ORIG.get((cls, attr))
        if orig is not None:
            orig(widget, text)
            return
    getattr(widget, attr)(text)


def _patch_init(cls) -> None:
    """构造时就带文字的控件（QLabel("就绪") / QPushButton("开始压制")）。

    运行期新建的行、卡片走的是构造函数而不是 setText，只补 setter 会漏掉它们，
    切到英文后新出现的行仍然是中文。
    """
    orig = cls.__init__

    def patched(self, *args, **kwargs):  # noqa: ANN001
        if args and isinstance(args[0], str):
            args = (tr(args[0]),) + tuple(args[1:])
        orig(self, *args, **kwargs)

    cls.__init__ = patched


def _patch_filter(cls, name: str, index: int) -> None:
    """文件对话框的过滤器用 ``;;`` 分隔，逐段翻。"""
    orig = getattr(cls, name)

    def patched(*args, **kwargs):  # noqa: ANN001
        if len(args) > index and isinstance(args[index], str):
            args = list(args)
            args[index] = ";;".join(tr(p) for p in args[index].split(";;"))
        return orig(*args, **kwargs)

    setattr(cls, name, staticmethod(patched))


def install() -> None:
    """给 Qt 的文本 setter 打补丁。必须在创建控件之前调用。"""
    global _installed
    if _installed:
        return

    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QAbstractButton,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidgetItem,
        QMenu,
        QMenuBar,
        QMessageBox,
        QPushButton,
        QRadioButton,
        QSystemTrayIcon,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QToolButton,
        QWidget,
    )

    # 构造函数带文字的：运行期新建的控件也得跟着当前语言
    for cls in (
        QLabel,
        QPushButton,
        QCheckBox,
        QRadioButton,
        QToolButton,
        QListWidgetItem,
        QTableWidgetItem,
    ):
        try:
            _patch_init(cls)
        except Exception:
            pass

    for cls, name, idx in (
        (QLabel, "setText", 0),
        (QAbstractButton, "setText", 0),
        (QLineEdit, "setPlaceholderText", 0),
        (QGroupBox, "setTitle", 0),
        (QWidget, "setToolTip", 0),
        (QWidget, "setWindowTitle", 0),
        (QWidget, "setStatusTip", 0),
        (QAction, "setText", 0),
        (QTableWidgetItem, "setText", 0),
        (QTableWidgetItem, "setToolTip", 0),
        (QListWidgetItem, "setText", 0),
        (QSystemTrayIcon, "setToolTip", 0),
        (QComboBox, "setItemText", 1),
        (QTabWidget, "setTabText", 1),
    ):
        try:
            _patch(cls, name, idx)
        except Exception:
            pass

    # ---- QComboBox：addItem / addItems
    orig_add_item = QComboBox.addItem

    def combo_add_item(self, *args, **kwargs):  # noqa: ANN001
        if args and isinstance(args[0], str):
            args = list(args)
            args[0] = tr(args[0])
        return orig_add_item(self, *args, **kwargs)

    QComboBox.addItem = combo_add_item

    orig_add_items = QComboBox.addItems

    def combo_add_items(self, items):  # noqa: ANN001
        return orig_add_items(self, [tr(x) for x in items])

    QComboBox.addItems = combo_add_items

    # ---- QMenu / QMenuBar：菜单项是 C++ 里建的 QAction，setText 补丁拦不到
    def _menu_adder(cls, name: str) -> None:
        orig = getattr(cls, name)

        def patched(self, *args, **kwargs):  # noqa: ANN001
            args = list(args)
            for i, v in enumerate(args[:2]):
                if isinstance(v, str):
                    args[i] = tr(v)
                    break
            return orig(self, *args, **kwargs)

        setattr(cls, name, patched)

    for name in ("addAction", "addMenu"):
        try:
            _menu_adder(QMenu, name)
        except Exception:
            pass
    try:
        _menu_adder(QMenuBar, "addMenu")
    except Exception:
        pass

    # ---- QTabWidget：addTab / insertTab 的 label 在第二个或第三个参数
    orig_add_tab = QTabWidget.addTab

    def tab_add(self, *args, **kwargs):  # noqa: ANN001
        args = list(args)
        for i in range(min(3, len(args)) - 1, 0, -1):
            if isinstance(args[i], str):
                args[i] = tr(args[i])
                break
        return orig_add_tab(self, *args, **kwargs)

    QTabWidget.addTab = tab_add

    # ---- 表头：记住原文，切语言时才能重翻
    orig_hhl = QTableWidget.setHorizontalHeaderLabels

    def table_headers(self, labels):  # noqa: ANN001
        self._i18n_headers = tuple(str(x) for x in labels)
        return orig_hhl(self, [tr(x) for x in self._i18n_headers])

    QTableWidget.setHorizontalHeaderLabels = table_headers

    # ---- 弹窗：静态方法自建对话框，实例 setter 的补丁管不到
    for name in ("information", "warning", "critical", "question"):
        orig = getattr(QMessageBox, name, None)
        if orig is None:
            continue

        def make(orig):  # noqa: ANN001, ANN202
            def patched(*args, **kwargs):  # noqa: ANN001
                args = list(args)
                for i in (1, 2):
                    if len(args) > i and isinstance(args[i], str):
                        args[i] = tr(args[i])
                return orig(*args, **kwargs)

            return patched

        setattr(QMessageBox, name, staticmethod(make(orig)))

    _patch_filter(QFileDialog, "getOpenFileName", 3)
    _patch_filter(QFileDialog, "getSaveFileName", 3)
    _patch_filter(QFileDialog, "getExistingDirectory", 1)

    _installed = True


# ====================================================================== 重扫
def _reapply(w) -> None:  # noqa: ANN001
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QMenu,
        QTableWidget,
        QTabWidget,
    )

    if isinstance(w, (QLabel, QAbstractButton)):
        text = w.text()
        if text:
            w.setText(text)
    if isinstance(w, QLineEdit):
        ph = w.placeholderText()
        if ph:
            w.setPlaceholderText(ph)
    if isinstance(w, QGroupBox):
        title = w.title()
        if title:
            w.setTitle(title)
    title = w.windowTitle()
    if title:
        w.setWindowTitle(title)
    tip = w.toolTip()
    if tip:
        w.setToolTip(tip)
    if isinstance(w, QMenu):
        for act in w.actions():
            text = act.text()
            if text:
                act.setText(text)
    if isinstance(w, QTabWidget):
        for i in range(w.count()):
            w.setTabText(i, w.tabText(i))
    if isinstance(w, QComboBox):
        for i in range(w.count()):
            w.setItemText(i, w.itemText(i))
    if isinstance(w, QTableWidget):
        src = getattr(w, "_i18n_headers", None)
        if src:
            for i, text in enumerate(src[: w.columnCount()]):
                item = w.horizontalHeaderItem(i)
                if item is not None:
                    item.setText(text)
        for r in range(w.rowCount()):
            for c in range(w.columnCount()):
                item = w.item(r, c)
                if item is not None:
                    text = item.text()
                    if text:
                        item.setText(text)
    if isinstance(w, QListWidget):
        for i in range(w.count()):
            item = w.item(i)
            if item is not None:
                text = item.text()
                if text:
                    item.setText(text)


def retranslate_all() -> None:
    """按当前语言把已建好的界面重写一遍（运行中切语言用）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    widgets = app.allWidgets()
    for w in widgets:
        try:
            _reapply(w)
        except Exception:
            pass
    # 文字改完后，再让控件自己重算依赖文字的尺寸（页签宽度、胶囊最小宽等）
    for w in widgets:
        hook = getattr(w, "retranslate_ui", None)
        if callable(hook):
            try:
                hook()
            except Exception:
                pass
