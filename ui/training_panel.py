"""Training panel public facade."""

from typing import Dict, Optional, TextIO

from PyQt6.QtWidgets import QCheckBox, QWidget

from ui.helpers import project_path
from ui.training_base import BaseTrainingPanel
from ui.training_batch import TrainingBatchMixin
from ui.training_events import TrainingEventsMixin
from ui.training_jobs import TrainingJobsMixin
from ui.training_logging import TrainingLoggingMixin
from ui.training_monitoring import TrainingMonitoringMixin
from ui.training_refresh import TrainingRefreshMixin
from ui.training_runner import TrainingRunnerMixin
from ui.training_ui_build import TrainingUiMixin
from ui.training_version import VersionManagerMixin


class TrainingPanel(
    TrainingUiMixin,
    TrainingRefreshMixin,
    TrainingBatchMixin,
    TrainingJobsMixin,
    TrainingRunnerMixin,
    TrainingEventsMixin,
    TrainingMonitoringMixin,
    TrainingLoggingMixin,
    BaseTrainingPanel,
    VersionManagerMixin,
):
    """训练面板 - 主界面选项卡，支持模型增量训练/重新训练"""

    def __init__(self, parent: QWidget, main_gui):
        """初始化训练面板"""
        super().__init__(parent, main_gui)

        # 算法列表状态
        self._check_vars: Dict[str, QCheckBox] = {}
        self._algo_meta: Dict[str, Dict] = {}
        self._algo_confidence: Dict[str, float] = {}

        # 算法行标签引用（用于动态更新状态/置信度）
        self._algo_row_refs: Dict[str, list] = {}

        # 日志存盘
        self._log_dir = project_path("data", "log", "training")
        self._log_file: Optional[TextIO] = None
        self._log_file_path: str = ""
        self._saved_title: Optional[str] = None  # 训练时保存的窗口标题

        self._build_ui()
