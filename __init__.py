"""
B站视频监控与播放量预测系统

版本号规则（语义化版本）：
  X.Y.Z
  Z = patch — 小更新/小 commit（bug 修复、日志调整、文档）
  Y = minor — 大更新/必要修复（新功能、架构变更、API 修改）
  X = major — 重大更新（架构重写、不兼容变更）

版本: 2.6.1
功能:
- 100+ 种预测算法
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

__version__ = "2.7.0"
__author__ = "Bilibili Monitor Team"

from config import PROJECT_ROOT, DATA_DIR, COVER_DIR, EXPORT_DIR

__all__ = ["__version__", "__author__", "PROJECT_ROOT", "DATA_DIR", "COVER_DIR", "EXPORT_DIR"]
