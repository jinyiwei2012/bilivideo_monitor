"""
B站视频监控与播放量预测系统
主入口文件
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ui import main

if __name__ == "__main__":
    main()
