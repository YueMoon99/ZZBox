"""兼容入口：PDF 压缩界面测试已改为右键菜单流程，见 test_pdf_context.py。

旧版的「启用压缩功能 / 压缩全部 / 压缩部分」四个按钮已经全部收进队列
右键菜单，老测试断言的控件不再存在。保留这个文件只是防止旧脚本路径失效，
实际执行的是新测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_pdf_context import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
