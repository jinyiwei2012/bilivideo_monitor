"""pytest 全局配置：让无显示器的环境也能创建 QApplication。

背景：PyQt6 的 wheel 自带 Qt 库，但在 headless 环境（CI / 容器）里 Qt 默认的 xcb
平台插件会直接 abort（`qt.qpa.plugin`）或因缺 libEGL 而 ImportError，导致凡导入 UI
模块的测试全挂。离屏后端（offscreen）下 QApplication 可正常创建，对构造/逻辑类测试
完全够用。

仅在「确实没有显示器」的平台上启用（Linux/其他 POSIX 且未设置 DISPLAY），
本机 Windows / 桌面 Linux 行为不变。
"""

import os
import sys

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
