"""打包脚本：把程序构建成不依赖 Python 的独立 exe。

用法（在本目录下）：python build.py
输出：ZZBox v<版本>/  —— 整个文件夹可直接拷到任何 Windows 机器上双击运行
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "ZZBox"
STAGE = ROOT / "_stage"
DIST = ROOT / "ZZBox v0.6.1"
BUILD = ROOT / "build"
ICON = ROOT / "assets" / "icon.ico"
ASSETS = ROOT / "assets"

# 只用到 QtCore/QtGui/QtWidgets，其余 Qt 模块全部排除，减小体积、减少出错面
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
    "PySide6.QtNetwork",
    "tkinter",
    "unittest",
    "pydoc_data",
    "test",
]


def _park(path: Path) -> Path:
    """把旧产物改名为 build/prev-时间戳，代替删除。"""
    import time

    park_root = BUILD / "prev"
    park_root.mkdir(parents=True, exist_ok=True)
    target = park_root / f"{path.name}-{time.strftime('%H%M%S')}"
    n = 1
    while target.exists():
        target = park_root / f"{path.name}-{time.strftime('%H%M%S')}-{n}"
        n += 1
    path.rename(target)
    print(f"  旧版本已挪到 {target.relative_to(ROOT)}")
    return target


def main() -> int:
    # 不删除任何文件：旧产物一律改名挪到 build/prev-* 下，避免误删风险
    staging = STAGE / APP_NAME
    if staging.exists():
        _park(staging)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(STAGE),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
        "--noupx",
    ]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    # exe 自身的图标（资源管理器/任务栏显示的就是它）
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    # 版本资源：属性面板里的产品名，也是托盘通知里显示的程序名
    ver = ASSETS / "version_info.txt"
    if ver.exists():
        cmd += ["--version-file", str(ver)]
    # 运行时用的多尺寸 PNG，打进 _internal/assets，托盘和 Alt-Tab 才不会发虚
    cmd += ["--add-data", f"{ASSETS}{os.pathsep}assets"]
    cmd.append(str(ROOT / "main.py"))

    print("构建中…（首次约 1-3 分钟）")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        print("构建失败")
        return proc.returncode

    built = staging  # staging 已是 distpath/APP_NAME，不能再套一层

    # FFmpeg / ffprobe 放到 exe 同级 bin 目录，probe.app_root() 会据此找到
    src_bin = ROOT / "bin"
    dst_bin = built / "bin"
    dst_bin.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        src = src_bin / name
        if src.exists():
            shutil.copy2(src, dst_bin / name)
            print(f"  已附带 {name} ({src.stat().st_size / 1048576:.0f} MB)")
        else:
            print(f"  [警告] 缺少 {src}")

    readme = ROOT / "README.txt"
    if readme.exists():
        shutil.copy2(readme, built / readme.name)

    # 许可证与第三方声明：分发 GPL 的 ffmpeg 二进制时必须随包附带
    for extra in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        src = ROOT / extra
        if src.exists():
            shutil.copy2(src, built / src.name)
    lic_src = ROOT / "licenses"
    if lic_src.is_dir():
        dst_lic = built / "licenses"
        dst_lic.mkdir(parents=True, exist_ok=True)
        for f in lic_src.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_lic / f.name)

    # 旧版本改名挪走（不删除），新版本就位
    if DIST.exists():
        _park(DIST)
    shutil.copytree(built, DIST)

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    exe = DIST / f"{APP_NAME}.exe"
    print(f"\n完成：{exe}")
    print(f"文件夹总大小：{total / 1048576:.0f} MB")
    return 0 if exe.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
