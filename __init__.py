"""
B站视频监控与播放量预测系统

版本: 2.0
功能:
- 40+种预测算法
- 实时监控视频数据
- 阈值突破推送通知
- Windows原生通知 + QQ Bot
- 数据导出功能
- 视频封面展示
- 播放量增长趋势图
- 算法权重自定义
- 播放量交叉计算
- 多关键词视频搜索
- 系统设置配置

项目结构:
- core/: 核心模块（数据库、API、通知）
- ui/: 界面模块（GUI界面）
- algorithms/: 预测算法模块
- utils/: 工具模块
- config/: 配置模块
- data/: 数据目录
- exports/: 导出目录
"""

__version__ = "2.0.0"
__author__ = "Bilibili Monitor Team"

from config import PROJECT_ROOT, DATA_DIR, COVER_DIR, EXPORT_DIR

__all__ = [
    '__version__',
    '__author__',
    'PROJECT_ROOT',
    'DATA_DIR',
    'COVER_DIR',
    'EXPORT_DIR'
]
