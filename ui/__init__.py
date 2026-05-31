"""
UI 界面模块包

导出所有主要界面类，供外部模块统一导入。
"""

from .main_gui import BilibiliMonitorGUI, main
from .settings_window import SettingsWindow
from .video_search import VideoSearchWindow
from .crossover_analysis import CrossoverAnalysisWindow
from .data_comparison import DataComparisonWindow

__all__ = [
    "BilibiliMonitorGUI",
    "main",
    "SettingsWindow",
    "VideoSearchWindow",
    "CrossoverAnalysisWindow",
    "DataComparisonWindow",
]
