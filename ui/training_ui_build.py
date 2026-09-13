"""UI construction for :mod:`ui.training_panel`."""

from typing import Optional, cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.helpers import FONT, FONT_SM
from ui.scrollable_frame import ScrollableFrame
from ui.theme import C
from ui.training_base import _TrainingPanelContract
from utils.update_checker import _train


class TrainingUiMixin(_TrainingPanelContract):
    _train_btn: Optional[QPushButton]
    _cancel_btn: Optional[QPushButton]
    _skip_btn: Optional[QPushButton]
    _progress: Optional[QProgressBar]
    _status_lbl: Optional[QLabel]

    def _build_ui(self):
        """构建训练面板的完整 UI 布局"""
        outer_layout = QVBoxLayout(cast(QWidget, self))
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── 顶部信息栏：设备信息、数据规模、强制 CPU 开关 ──
        info_bar = QFrame(cast(QWidget, self))
        info_bar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(8, 8, 8, 4)
        info_layout.setSpacing(8)
        outer_layout.addWidget(info_bar)

        device_label = QLabel("训练设备:")
        device_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        device_label.setFont(FONT)
        info_layout.addWidget(device_label)
        self._device_lbl = QLabel("天依在检测设备呢…♪")
        self._device_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        self._device_lbl.setFont(FONT)
        info_layout.addWidget(self._device_lbl)
        info_layout.addSpacing(8)

        data_label = QLabel("数据规模:")
        data_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        data_label.setFont(FONT)
        info_layout.addWidget(data_label)
        self._data_lbl = QLabel("天依在估算数据规模呢…♪")
        self._data_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._data_lbl.setFont(FONT_SM)
        info_layout.addWidget(self._data_lbl)
        info_layout.addStretch()

        self._force_cpu_cb = QCheckBox("强制 CPU")
        self._force_cpu_cb.setStyleSheet(f"color: {C['text_1']};")
        self._force_cpu_cb.toggled.connect(self._on_force_cpu)
        info_layout.addWidget(self._force_cpu_cb)

        refresh_btn = QPushButton("刷新 ♪")
        refresh_btn.clicked.connect(self._refresh_all)
        info_layout.addWidget(refresh_btn)

        # ── 主体区域: 左(算法列表) | 右(图表+日志) ──
        body = QFrame(cast(QWidget, self))
        body.setStyleSheet(f"background-color: {C['bg_base']};")
        outer_layout.addWidget(body, 1)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 4, 8, 4)
        body_layout.setSpacing(0)

        self._build_algo_section(body)
        self._build_chart_section(body)

        # ── 底部控制栏 ──
        self._build_controls(cast(QWidget, self))

    def _build_algo_section(self, parent):
        """构建左侧算法列表区域"""
        left = QFrame(parent)
        left.setStyleSheet(f"background-color: {C['bg_surface']};")
        parent_layout = cast(QBoxLayout, parent.layout())
        parent_layout.addWidget(left, 35)

        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        hdr = QFrame(left)
        hdr.setStyleSheet(f"background-color: {C['bg_surface']};")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(4, 4, 4, 0)
        title_lbl = QLabel("可训练算法（PyTorch）♪")
        title_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()
        self._algo_count_lbl = QLabel("")
        self._algo_count_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._algo_count_lbl.setFont(FONT_SM)
        hdr_layout.addWidget(self._algo_count_lbl)
        left_layout.addWidget(hdr)

        toolbar = QFrame(left)
        toolbar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 2, 4, 2)
        toolbar_layout.setSpacing(1)

        btn_sel_all = QPushButton("全选")
        btn_sel_all.setFixedWidth(50)
        btn_sel_all.clicked.connect(lambda: self._select_all(True))
        toolbar_layout.addWidget(btn_sel_all)
        btn_sel_none = QPushButton("全不选")
        btn_sel_none.setFixedWidth(50)
        btn_sel_none.clicked.connect(lambda: self._select_all(False))
        toolbar_layout.addWidget(btn_sel_none)
        btn_sel_untrained = QPushButton("仅未训练")
        btn_sel_untrained.setFixedWidth(65)
        btn_sel_untrained.clicked.connect(self._select_untrained)
        toolbar_layout.addWidget(btn_sel_untrained)
        btn_version = QPushButton("✕ 版本管理")
        btn_version.setFixedWidth(85)
        btn_version.clicked.connect(self._on_manage_versions)
        toolbar_layout.addWidget(btn_version)
        left_layout.addWidget(toolbar)

        # 滚动容器
        sf = ScrollableFrame(left)
        sf.setStyleSheet(f"background-color: {C['bg_elevated']};")
        left_layout.addWidget(sf, 1)
        self._algo_frame = sf.inner

        # 表头：复选框、算法名、ID、状态、置信度、版本
        hdr_row = QFrame(self._algo_frame)
        hdr_row.setStyleSheet(f"background-color: {C['bg_surface']};")
        hdr_row_layout = QHBoxLayout(hdr_row)
        hdr_row_layout.setContentsMargins(0, 0, 0, 0)
        hdr_row_layout.setSpacing(2)
        for txt, w in [("", 30), ("算法", 110), ("ID", 90), ("状态", 80), ("置信度", 70), ("版本", 50)]:
            lbl = QLabel(txt)
            lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: 8pt bold;")
            lbl.setFixedWidth(w)
            hdr_row_layout.addWidget(lbl)
        hdr_row_layout.addStretch()
        cast(QBoxLayout, self._algo_frame.layout()).addWidget(hdr_row)  # 将表头添加到滚动容器的布局中

    def _build_chart_section(self, parent):
        """构建右侧图表和日志区域"""
        right = QFrame(parent)
        right.setStyleSheet(f"background-color: {C['bg_surface']};")
        parent_layout = cast(QBoxLayout, parent.layout())
        parent_layout.addWidget(right, 65)

        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(2)

        # 上半: Loss 图表
        chart_frame = self._build_chart_widgets(right, title="训练 Loss 曲线 ♪")
        right_layout.addWidget(chart_frame, 1)

        # 中部: 训练质量监控状态栏
        monitor_bar = self._build_monitor_bar(right)
        right_layout.addWidget(monitor_bar)

        # 下半: 文字日志
        log_frame = self._build_log_widgets(right, title="训练日志 ♪")
        right_layout.addWidget(log_frame, 1)

    def _build_controls(self, parent):
        """构建底部训练控制栏"""
        from ui.training_panel import TrainingPanel

        ctrl = QFrame(parent)
        ctrl.setStyleSheet(f"background-color: {C['bg_elevated']};")
        layout = self.layout() if isinstance(parent, TrainingPanel) else QHBoxLayout()
        if not isinstance(parent, TrainingPanel):
            ctrl.setLayout(layout)
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(8, 4, 8, 6)
        ctrl_layout.setSpacing(8)

        # 训练参数
        epoch_label = QLabel("Epoch:")
        epoch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        epoch_label.setFont(FONT_SM)
        ctrl_layout.addWidget(epoch_label)
        self._epoch_spin = QSpinBox()
        self._epoch_spin.setRange(1, 500)
        self._epoch_spin.setValue(20)
        self._epoch_spin.setFixedWidth(60)
        ctrl_layout.addWidget(self._epoch_spin)

        batch_label = QLabel("Batch:")
        batch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        batch_label.setFont(FONT_SM)
        ctrl_layout.addWidget(batch_label)
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 512)
        self._batch_spin.setValue(32)
        self._batch_spin.setFixedWidth(60)
        ctrl_layout.addWidget(self._batch_spin)

        # 学习率
        lr_label = QLabel("LR:")
        lr_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        lr_label.setFont(FONT_SM)
        ctrl_layout.addWidget(lr_label)
        self._lr_entry = QLineEdit("0.001")
        self._lr_entry.setFixedWidth(80)
        ctrl_layout.addWidget(self._lr_entry)
        self._lr_auto_cb = QCheckBox("自动")
        self._lr_auto_cb.setChecked(True)
        self._lr_auto_cb.toggled.connect(self._on_lr_auto_toggle)
        ctrl_layout.addWidget(self._lr_auto_cb)

        # 训练模式：增量训练 / 重新训练
        mode_label = QLabel("模式:")
        mode_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        mode_label.setFont(FONT_SM)
        ctrl_layout.addWidget(mode_label)
        self._mode_incremental = QRadioButton("增量训练")
        self._mode_retrain = QRadioButton("重新训练")
        self._mode_retrain.setEnabled(_train() == "normal")
        self._mode_group = QButtonGroup(cast(QWidget, self))
        self._mode_group.addButton(self._mode_incremental)
        self._mode_group.addButton(self._mode_retrain)
        self._mode_incremental.setChecked(True)
        ctrl_layout.addWidget(self._mode_incremental)
        ctrl_layout.addWidget(self._mode_retrain)

        # 并行训练数
        parallel_label = QLabel("并行:")
        parallel_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        parallel_label.setFont(FONT_SM)
        ctrl_layout.addWidget(parallel_label)
        self._parallel_spin = QSpinBox()
        self._parallel_spin.setRange(1, 4)
        self._parallel_spin.setValue(2)
        self._parallel_spin.setFixedWidth(50)
        ctrl_layout.addWidget(self._parallel_spin)

        # 详细日志
        self._batch_log_cb = QCheckBox("详细日志")
        ctrl_layout.addWidget(self._batch_log_cb)
        interval_label = QLabel("每")
        interval_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        interval_label.setFont(FONT_SM)
        ctrl_layout.addWidget(interval_label)
        self._batch_interval_entry = QLineEdit("10")
        self._batch_interval_entry.setFixedWidth(40)
        ctrl_layout.addWidget(self._batch_interval_entry)
        self._batch_interval_combo = QComboBox()
        self._batch_interval_combo.addItems(["%", "个"])
        self._batch_interval_combo.setFixedWidth(50)
        ctrl_layout.addWidget(self._batch_interval_combo)

        # 按钮
        self._train_btn = QPushButton("▶ 开始训练 ♪")
        self._train_btn.clicked.connect(self._on_train_start)
        self._train_btn.setEnabled(_train() == "normal")
        ctrl_layout.addWidget(self._train_btn)
        self._cancel_btn = QPushButton("✗ 取消")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        ctrl_layout.addWidget(self._cancel_btn)
        self._skip_btn = QPushButton("⏭ 跳过当前")
        self._skip_btn.clicked.connect(self._on_skip_algo)
        self._skip_btn.setEnabled(False)
        ctrl_layout.addWidget(self._skip_btn)
        batch_finetune_btn = QPushButton("◎ 批量微调 ♪")
        batch_finetune_btn.clicked.connect(self._on_batch_finetune)
        batch_finetune_btn.setEnabled(_train() == "normal")
        ctrl_layout.addWidget(batch_finetune_btn)

        if _train() != "normal":
            train_hint = QLabel("✦ 创建 .enabletraining 文件开启训练 / 完整 devmode 见 README.md")
            train_hint.setStyleSheet(f"color: {C['warning']}; background: transparent; font: 8pt;")
            ctrl_layout.addWidget(train_hint)

        # 进度条和状态标签
        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        ctrl_layout.addWidget(self._progress, 1)

        self._status_lbl = QLabel("天依准备好啦 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._status_lbl.setFont(FONT_SM)
        self._status_lbl.setFixedWidth(250)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        ctrl_layout.addWidget(self._status_lbl)

        # Add ctrl to parent layout
        parent_layout = cast(QBoxLayout, self.layout())
        parent_layout.addWidget(ctrl)
