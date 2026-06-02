"""
UI 界面模块包

本模块是 B站视频监控与播放量预测系统 的 Tkinter 图形用户界面层。
采用三栏式主窗口布局（左侧视频卡片列表、中间详情/图表、右侧预测面板），
同时包含弹幕分析、AI 问答、数据大屏、交叉计算、异常检测等子窗口模块。

导出所有主要界面类，供外部模块通过 `from ui import XXX` 统一导入。
"""

from .main_gui import BilibiliMonitorGUI, main            # 主 GUI 窗口及入口函数
from .settings_window import SettingsWindow               # 系统设置窗口
from .video_search import VideoSearchWindow               # 视频搜索窗口
from .crossover_analysis import CrossoverAnalysisWindow    # 播放量交叉计算窗口
from .data_comparison import DataComparisonWindow          # 数据对比窗口（趋势图+快照+录入）

__all__ = [
    "BilibiliMonitorGUI",
    "main",
    "SettingsWindow",
    "VideoSearchWindow",
    "CrossoverAnalysisWindow",
    "DataComparisonWindow",
]
