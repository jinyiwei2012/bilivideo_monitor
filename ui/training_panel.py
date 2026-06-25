"""
训练面板 - 主界面集成版
支持模型增量训练/重新训练，实时 loss 图表 + 文字日志。
"""

import io
import logging
import os
import threading
import time
from typing import Dict, List, Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QProgressBar,
    QFrame, QTabWidget, QGroupBox, QGridLayout, QScrollArea,
    QPlainTextEdit, QMessageBox, QDialog, QSplitter, QSizePolicy,
    QToolButton, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QRadioButton, QButtonGroup, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    FONT_MONO,
    FONT_BOLD,
    loss_to_confidence,
    format_confidence,
    load_algo_confidence,
    project_path,
)
from ui.scrollable_frame import ScrollableFrame
from ui.training_base import BaseTrainingPanel, TrainingMonitor
from ui.invoker import invoke
from utils.update_checker import _hard, _train, _confirm_risky

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class TrainingPanel(BaseTrainingPanel):
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
        self._log_file: Optional[io.TextIOWrapper] = None
        self._log_file_path: str = ""
        self._saved_title: Optional[str] = None  # 训练时保存的窗口标题

        self._build_ui()

    # ══════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════

    def _build_ui(self):
        """构建训练面板的完整 UI 布局"""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── 顶部信息栏：设备信息、数据规模、强制 CPU 开关 ──
        info_bar = QFrame(self)
        info_bar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(8, 8, 8, 4)
        info_layout.setSpacing(8)
        outer_layout.addWidget(info_bar)

        device_label = QLabel("训练设备:")
        device_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        device_label.setFont(FONT)
        info_layout.addWidget(device_label)
        self._device_lbl = QLabel("检测中…")
        self._device_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        self._device_lbl.setFont(FONT)
        info_layout.addWidget(self._device_lbl)
        info_layout.addSpacing(8)

        data_label = QLabel("数据规模:")
        data_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        data_label.setFont(FONT)
        info_layout.addWidget(data_label)
        self._data_lbl = QLabel("估算中…")
        self._data_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._data_lbl.setFont(FONT_SM)
        info_layout.addWidget(self._data_lbl)
        info_layout.addStretch()

        self._force_cpu_cb = QCheckBox("强制 CPU")
        self._force_cpu_cb.setStyleSheet(f"color: {C['text_1']};")
        self._force_cpu_cb.toggled.connect(self._on_force_cpu)
        info_layout.addWidget(self._force_cpu_cb)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_all)
        info_layout.addWidget(refresh_btn)

        # ── 主体区域: 左(算法列表) | 右(图表+日志) ──
        body = QFrame(self)
        body.setStyleSheet(f"background-color: {C['bg_base']};")
        outer_layout.addWidget(body, 1)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 4, 8, 4)
        body_layout.setSpacing(0)

        self._build_algo_section(body)
        self._build_chart_section(body)

        # ── 底部控制栏 ──
        self._build_controls(self)

    # ── 算法列表 (左侧) ──

    def _build_algo_section(self, parent):
        """构建左侧算法列表区域"""
        left = QFrame(parent)
        left.setStyleSheet(f"background-color: {C['bg_surface']};")
        parent_layout = parent.layout()
        parent_layout.addWidget(left, 35)

        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        hdr = QFrame(left)
        hdr.setStyleSheet(f"background-color: {C['bg_surface']};")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(4, 4, 4, 0)
        title_lbl = QLabel("可训练算法（PyTorch）")
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
        btn_version = QPushButton("🗑️ 版本管理")
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
        self._algo_frame.layout().addWidget(hdr_row)  # 将表头添加到滚动容器的布局中

    # ── 图表+日志 (右侧) ──

    def _build_chart_section(self, parent):
        """构建右侧图表和日志区域"""
        right = QFrame(parent)
        right.setStyleSheet(f"background-color: {C['bg_surface']};")
        parent_layout = parent.layout()
        parent_layout.addWidget(right, 65)

        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(2)

        # 上半: Loss 图表
        chart_frame = self._build_chart_widgets(right, title="训练 Loss 曲线")
        right_layout.addWidget(chart_frame, 1)

        # 中部: 训练质量监控状态栏
        monitor_bar = self._build_monitor_bar(right)
        right_layout.addWidget(monitor_bar)

        # 下半: 文字日志
        log_frame = self._build_log_widgets(right, title="训练日志")
        right_layout.addWidget(log_frame, 1)

    # ── 底部控制栏 ──

    def _build_controls(self, parent):
        """构建底部训练控制栏"""
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
        self._mode_group = QButtonGroup(self)
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
        self._train_btn = QPushButton("▶ 开始训练")
        self._train_btn.clicked.connect(self._on_train_start)
        self._train_btn.setEnabled(_train() == "normal")
        ctrl_layout.addWidget(self._train_btn)
        self._cancel_btn = QPushButton("✕ 取消")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        ctrl_layout.addWidget(self._cancel_btn)
        self._skip_btn = QPushButton("⏭ 跳过当前")
        self._skip_btn.clicked.connect(self._on_skip_algo)
        self._skip_btn.setEnabled(False)
        ctrl_layout.addWidget(self._skip_btn)
        batch_finetune_btn = QPushButton("🎯 批量微调")
        batch_finetune_btn.clicked.connect(self._on_batch_finetune)
        batch_finetune_btn.setEnabled(_train() == "normal")
        ctrl_layout.addWidget(batch_finetune_btn)

        if _train() != "normal":
            train_hint = QLabel("💡 创建 .enabletraining 文件开启训练 / 完整 devmode 见 README.md")
            train_hint.setStyleSheet(f"color: {C['warning']}; background: transparent; font: 8pt;")
            ctrl_layout.addWidget(train_hint)

        # 进度条和状态标签
        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        ctrl_layout.addWidget(self._progress, 1)

        self._status_lbl = QLabel("就绪")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._status_lbl.setFont(FONT_SM)
        self._status_lbl.setFixedWidth(250)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        ctrl_layout.addWidget(self._status_lbl)

        # Add ctrl to parent layout
        parent_layout = self.layout()
        parent_layout.addWidget(ctrl)

    def _safe_sb(self, key, text, color=None):
        """线程安全的状态栏更新 — 统一 try/except，消除 11 处重复模板"""
        try:
            self.main._sb(key, text, color=color)
        except Exception:
            pass

    # ══════════════════════════════════════════════
    # 数据刷新
    # ══════════════════════════════════════════════

    def on_show(self):
        """此面板被切换到前台时调用"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_all(self):
        """刷新所有数据：设备、数据规模、算法列表"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_device(self):
        """刷新训练设备信息显示"""
        try:
            from algorithms.training.device import get_device_info, is_torch_available, force_cpu

            force_cpu(self._force_cpu_cb.isChecked())
            info = get_device_info()
            if not is_torch_available():
                self._device_lbl.setText("❌ torch 未安装")
                self._device_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            elif info.get("is_gpu"):
                mem = info.get("total_memory_gb", 0)
                self._device_lbl.setText(f"✅ {info['name']} ({mem:.1f} GB)")
                self._device_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
            else:
                self._device_lbl.setText(f"💻 {info['name']}")
                self._device_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        except Exception as e:
            self._device_lbl.setText(f"⚠ {e}")
            self._device_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")

    def _on_force_cpu(self):
        """强制 CPU 切换时重新检测设备"""
        self._refresh_device()

    # ── 学习率控制 ────────────────────────────────

    def _on_lr_auto_toggle(self):
        """自动/手动学习率切换：自动时锁定输入框，并填入推荐值。"""
        if self._lr_auto_cb.isChecked():
            self._lr_entry.setReadOnly(True)
            auto_lr = self._auto_compute_lr()
            self._lr_entry.setText(f"{auto_lr:.6f}")
        else:
            if _confirm_risky("切换到手动学习率模式", self):
                self._lr_entry.setReadOnly(False)
            else:
                self._lr_auto_cb.setChecked(True)

    def _auto_compute_lr(self) -> float:
        """根据数据规模和常用经验自动推荐学习率。"""
        try:
            from algorithms.training.trainer import ModelTrainer

            info = ModelTrainer().estimate_data_size()
            samples = info.get("total_samples", 1000)
        except Exception:
            samples = 1000

        # 样本越多 → 学习率应越小（避免在大数据集上震荡）
        if samples < 500:
            return 5e-3  # 小数据集：较大学习率快速收敛
        elif samples < 5000:
            return 2e-3  # 中等
        elif samples < 20000:
            return 1e-3  # 标准 Adam 默认值
        elif samples < 100000:
            return 5e-4  # 大数据集
        else:
            return 1e-4  # 超大数据集

    def _refresh_data_size(self):
        """刷新数据规模估算信息（异步线程）"""
        self._data_lbl.setText("估算中…")
        self._data_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer

                info = ModelTrainer().estimate_data_size()
                total = info.get("total_videos", 0)
                valid = info.get("valid_videos", 0)
                samples = info.get("total_samples", 0)
                eta = info.get("estimated_time_s", 0)
                txt = f"{total} 视频 · {valid} 有效 · {samples:,} 样本 · 约 {eta / 60:.1f} min/algo"
                invoke(lambda: self._data_lbl.setText(txt))
                invoke(lambda: self._data_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;"))
            except Exception as e:
                invoke(lambda e=e: self._data_lbl.setText(f"⚠ {e}"))
                invoke(lambda e=e: self._data_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;"))

        threading.Thread(target=_worker, daemon=True).start()

    def _discover_algorithms(self) -> List[Dict]:
        """扫描有 build_model 的算法"""
        from algorithms.registry import AlgorithmRegistry

        return AlgorithmRegistry.get_trainable_info()

    def _refresh_algo_list(self):
        """刷新算法列表，显示每个算法的状态、置信度和版本"""
        # Clear existing rows
        layout = self._algo_frame.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._check_vars.clear()
        self._algo_meta.clear()
        self._algo_row_refs.clear()

        try:
            algos = self._discover_algorithms()
        except Exception as e:
            err_lbl = QLabel(f"⚠ 加载失败: {e}")
            err_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            err_lbl.setFont(FONT)
            self._algo_frame.layout().addWidget(err_lbl)
            return

        trained = sum(1 for a in algos if a["has_ckpt"])
        self._algo_count_lbl.setText(f"{len(algos)} 算法 · 已训练 {trained}")

        for a in algos:
            aid = a["algorithm_id"]
            self._algo_meta[aid] = a

            row = QFrame(self._algo_frame)
            row.setStyleSheet(f"background-color: {C['bg_surface']}; border: 1px solid {C['border_sub']};")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 1, 4, 1)
            row_layout.setSpacing(2)
            self._algo_frame.layout().addWidget(row)

            cb = QCheckBox("")
            cb.setChecked(not a["has_ckpt"])
            self._check_vars[aid] = cb
            row_layout.addWidget(cb)

            name_lbl = QLabel(a["name"])
            name_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
            name_lbl.setFont(FONT)
            name_lbl.setFixedWidth(130)
            row_layout.addWidget(name_lbl)

            id_lbl = QLabel(aid)
            id_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            id_lbl.setFont(FONT_MONO)
            id_lbl.setFixedWidth(100)
            row_layout.addWidget(id_lbl)

            if a["has_ckpt"]:
                st = f"✅ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 未训练"
                sf = C["text_3"]
            status_lbl = QLabel(st)
            status_lbl.setStyleSheet(f"color: {sf}; background: transparent;")
            status_lbl.setFont(FONT_SM)
            status_lbl.setFixedWidth(90)
            row_layout.addWidget(status_lbl)

            # 置信度列
            conf = load_algo_confidence(aid)
            conf_text, conf_color = format_confidence(conf)
            conf_lbl = QLabel(conf_text)
            conf_lbl.setStyleSheet(f"color: {conf_color}; background: transparent;")
            conf_lbl.setFont(FONT_SM)
            conf_lbl.setFixedWidth(80)
            row_layout.addWidget(conf_lbl)

            ver_lbl = QLabel(f"v{a['version_count']}")
            ver_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            ver_lbl.setFont(FONT_SM)
            ver_lbl.setFixedWidth(50)
            row_layout.addWidget(ver_lbl)

            row_layout.addStretch()
            self._algo_row_refs[aid] = [status_lbl, conf_lbl, ver_lbl]

    def _select_all(self, flag: bool):
        """全选或全不选所有算法"""
        for cb in self._check_vars.values():
            cb.setChecked(flag)

    def _select_untrained(self):
        """仅选中尚未训练的算法"""
        for aid, cb in self._check_vars.items():
            cb.setChecked(not self._algo_meta.get(aid, {}).get("has_ckpt", False))

    def _update_algo_row(
        self,
        aid: str,
        status: str = None,
        status_color: str = None,
        conf: str = None,
        conf_color: str = None,
        ver: str = None,
    ):
        """动态更新算法列表行的状态/置信度/版本列。"""
        refs = self._algo_row_refs.get(aid)
        if not refs:
            return
        status_lbl, conf_lbl, ver_lbl = refs
        if status is not None:
            status_lbl.setText(status)
            if status_color:
                status_lbl.setStyleSheet(f"color: {status_color}; background: transparent;")
                status_lbl.setFont(FONT_SM)
        if conf is not None:
            conf_lbl.setText(conf)
            if conf_color:
                conf_lbl.setStyleSheet(f"color: {conf_color}; background: transparent;")
                conf_lbl.setFont(FONT_SM)
        if ver is not None:
            ver_lbl.setText(ver)

    # ── 版本管理 ──────────────────────────────────

    def _on_manage_versions(self):
        """打开 checkpoint 版本管理对话框 — 查看/删除/激活版本。"""
        from algorithms.training.checkpoint_manager import CheckpointManager
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        algos = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            ckpt = CheckpointManager(aid)
            if ckpt.has_checkpoint() or os.path.exists(project_path("algorithms", "checkpoints", aid)):
                algos.append(
                    {
                        "algorithm_id": aid,
                        "name": getattr(algo, "name", aid),
                        "category": getattr(algo, "category", ""),
                    }
                )

        if not algos:
            QMessageBox.information(self, "提示", "没有任何已训练的模型")
            return

        self._show_manage_versions(algos)
        return

    def _show_manage_versions(self, algos):
        """打开版本管理对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Checkpoint 版本管理")
        dialog.resize(700, 500)
        dialog.setModal(True)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(8, 8, 8, 8)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(main, 1)

        left_panel = QFrame(main)
        left_panel.setStyleSheet(f"background-color: {C['bg_elevated']};")
        left_panel.setFixedWidth(220)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(left_panel)

        left_title = QLabel("算法")
        left_title.setStyleSheet(f"color: {C['text_2']}; background: transparent; padding: 4px;")
        left_title.setFont(FONT_SM)
        left_layout.addWidget(left_title)

        algo_sf = ScrollableFrame(left_panel, bg=C["bg_elevated"])
        left_layout.addWidget(algo_sf, 1)
        algo_inner = algo_sf.inner

        right_panel = QFrame(main)
        right_panel.setStyleSheet(f"background-color: {C['bg_surface']};")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(right_panel, 1)

        info_lbl = QLabel("← 选择一个算法")
        info_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        info_lbl.setFont(FONT)
        right_layout.addWidget(info_lbl)
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        detail_frame = QFrame(right_panel)
        detail_frame.setStyleSheet(f"background-color: {C['bg_surface']};")
        right_layout.addWidget(detail_frame, 1)

        def _refresh_detail(aid, name):
            self._draw_version_detail_pyqt(detail_frame, info_lbl, aid, name, _refresh_detail)

        self._draw_version_list_pyqt(algo_inner, algos, _refresh_detail)
        dialog.exec()

    def _draw_version_list_pyqt(self, algo_inner, algos, refresh_cb):
        """填充左侧算法列表按钮"""
        layout = algo_inner.layout() if algo_inner.layout() else QVBoxLayout(algo_inner)
        for a in sorted(algos, key=lambda x: x["name"]):
            btn = QPushButton(f"{a['name']}")
            btn.setStyleSheet(
                f"background-color: {C['bg_elevated']}; color: {C['text_1']}; font: {FONT_SM}; "
                f"text-align: left; padding: 3px 6px; border: none;"
            )
            aid_val = a["algorithm_id"]
            name_val = a["name"]
            btn.clicked.connect(lambda checked=False, aid=aid_val, n=name_val: refresh_cb(aid, n))
            layout.addWidget(btn)

    def _draw_version_detail_pyqt(self, detail_frame, info_lbl, aid, name, refresh_cb):
        """刷新指定算法的版本详情面板"""
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        # Clear existing
        old_layout = detail_frame.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        info_lbl.hide()

        layout = QVBoxLayout(detail_frame)
        layout.setContentsMargins(4, 4, 4, 4)

        title_lbl = QLabel(f"{name}  ({aid})")
        title_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        layout.addWidget(title_lbl)

        ckpt = CheckpointManager(aid)

        section_lbl = QLabel("全局版本")
        section_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        section_lbl.setFont(FONT_SM)
        layout.addWidget(section_lbl)

        versions = ckpt.list_versions()
        if not versions:
            no_ver = QLabel("  （无全局 checkpoint）")
            no_ver.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            no_ver.setFont(FONT_SM)
            layout.addWidget(no_ver)
        else:
            for v in versions:
                row = QFrame(detail_frame)
                row.setStyleSheet(f"background-color: {C['bg_elevated']};")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(4, 1, 4, 1)
                layout.addWidget(row)

                active_tag = "★ " if v.get("active") else "  "
                ver_lbl = QLabel(f"{active_tag}{v['version']}")
                ver_lbl.setStyleSheet(
                    f"color: {C['success'] if v.get('active') else C['text_1']}; "
                    f"background: transparent; font: {FONT_MONO};"
                )
                ver_lbl.setFixedWidth(200)
                row_layout.addWidget(ver_lbl)

                if not v.get("active") and len(versions) > 1:
                    activate_btn = QPushButton("激活")
                    activate_btn.setFixedWidth(50)
                    ver_val = v["version"]
                    activate_btn.clicked.connect(
                        lambda checked=False, c=ckpt, ver=ver_val, a=aid, n=name, cb=refresh_cb: (
                            self._activate_version(c, ver, a, n, cb)
                        )
                    )
                    row_layout.addWidget(activate_btn)

                if len(versions) > 1:
                    del_btn = QPushButton("✕")
                    del_btn.setFixedWidth(30)
                    ver_val = v["version"]
                    del_btn.clicked.connect(
                        lambda checked=False, ver=ver_val, c=ckpt, a=aid, n=name, cb=refresh_cb: (
                            c.delete(ver),
                            cb(a, n),
                        )
                    )
                    row_layout.addWidget(del_btn)

                vl = v.get("val_loss", -1)
                if vl >= 0:
                    vl_lbl = QLabel(f"  val_loss={vl:.4f}")
                    vl_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
                    vl_lbl.setFont(FONT_SM)
                    row_layout.addWidget(vl_lbl)

                row_layout.addStretch()

        bvids = list_video_finetune_bvids(aid)
        if bvids:
            ft_lbl = QLabel("\n视频微调版本")
            ft_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
            ft_lbl.setFont(FONT_SM)
            layout.addWidget(ft_lbl)
            for bvid in bvids:
                v_ckpt = CheckpointManager(aid, bvid=bvid)
                v_vers = v_ckpt.list_versions()
                for v in v_vers:
                    row = QFrame(detail_frame)
                    row.setStyleSheet(f"background-color: {C['bg_elevated']};")
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(4, 1, 4, 1)
                    layout.addWidget(row)

                    bvid_lbl = QLabel(f"  📺 {bvid}  {v['version']}")
                    bvid_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
                    bvid_lbl.setFont(FONT_MONO)
                    row_layout.addWidget(bvid_lbl)
                    row_layout.addStretch()

                    del_btn = QPushButton("✕")
                    del_btn.setFixedWidth(30)
                    bvid_val = bvid
                    ver_val = v["version"]
                    del_btn.clicked.connect(
                        lambda checked=False, b=bvid_val, ver=ver_val, a=aid, n=name, cb=refresh_cb: (
                            CheckpointManager(a, bvid=b).delete(ver),
                            cb(a, n),
                        )
                    )
                    row_layout.addWidget(del_btn)

        if versions or bvids:
            layout.addSpacing(4)
            sep = QFrame(detail_frame)
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {C['border']};")
            layout.addWidget(sep)

            btn_row = QWidget()
            btn_row_layout = QHBoxLayout(btn_row)
            btn_row_layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(btn_row)

            if _hard() == "normal":
                del_global_btn = QPushButton("删除所有全局版本")
                del_global_btn.clicked.connect(lambda checked=False, a=aid, n=name: self._delete_all_global(a, n, refresh_cb))
                btn_row_layout.addWidget(del_global_btn)
                if bvids:
                    del_video_btn = QPushButton("删除所有微调版本")
                    del_video_btn.clicked.connect(lambda checked=False, a=aid, n=name: self._delete_all_video(a, n, refresh_cb))
                    btn_row_layout.addWidget(del_video_btn)
            else:
                ckpt_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "algorithms",
                    "checkpoints",
                    aid,
                )
                dir_lbl = QLabel(f"📁 {os.path.relpath(ckpt_dir)}")
                dir_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
                dir_lbl.setFont(FONT_SM)
                btn_row_layout.addWidget(dir_lbl)
            btn_row_layout.addStretch()

        layout.addStretch()

    def _activate_version(self, ckpt, ver, aid, name, refresh_cb):
        """激活指定版本并刷新详情"""
        ckpt.activate(ver)
        refresh_cb(aid, name)

    def _delete_all_global(self, aid, name, refresh_cb):
        """删除算法的所有全局 checkpoint。"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 {name} ({aid}) 的所有全局版本？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from algorithms.training.checkpoint_manager import CheckpointManager

        ckpt = CheckpointManager(aid)
        for v in ckpt.list_versions():
            ckpt.delete(v["version"])
        refresh_cb(aid, name)
        self._refresh_algo_list()

    def _delete_all_video(self, aid, name, refresh_cb):
        """删除算法的所有视频微调 checkpoint。"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 {name} ({aid}) 的所有视频微调版本？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        for bvid in list_video_finetune_bvids(aid):
            ckpt = CheckpointManager(aid, bvid=bvid)
            for v in ckpt.list_versions():
                ckpt.delete(v["version"])
        refresh_cb(aid, name)

    # ── 批量微调 ──────────────────────────────────

    def _on_batch_finetune(self):
        """打开批量微调对话框：选择视频 + 算法，一键微调。"""
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        algo_list = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            if CheckpointManager(aid).has_checkpoint():
                algo_list.append({"algorithm_id": aid, "name": getattr(algo, "name", aid)})

        if not algo_list:
            QMessageBox.warning(self, "提示", "没有已训练的深度学习算法可供微调")
            return

        videos = []
        try:
            for v in self.main.monitored_videos:
                bvid = v.get("bvid", "")
                title = v.get("title", bvid)
                if bvid:
                    videos.append({"bvid": bvid, "title": title[:40]})
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        if not videos:
            QMessageBox.warning(self, "提示", "没有监控中的视频可微调")
            return

        dialog, ui = self._build_batch_dialog(algo_list, videos)

        def _ft_log(msg):
            # Use QTextCursor for O(1) append instead of O(n²) toPlainText concat
            cursor = ui["log_text"].textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(msg + "\n")
            sb = ui["log_text"].verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())

        def _start_ft():
            selected_videos = [b for b, v in ui["video_vars"].items() if v.isChecked()]
            selected_algos = [a for a, v in ui["algo_vars"].items() if v.isChecked()]
            if not selected_videos:
                QMessageBox.warning(dialog, "提示", "请至少选择一个视频")
                return
            if not selected_algos:
                QMessageBox.warning(dialog, "提示", "请至少选择一个算法")
                return

            epochs = max(1, ui["ft_epoch_spin"].value())
            batch = max(1, ui["ft_batch_spin"].value())
            total = len(selected_videos) * len(selected_algos)
            _ft_log(f"开始批量微调: {len(selected_videos)} 视频 × {len(selected_algos)} 算法 = {total} 任务")
            ui["start_btn"].setEnabled(False)

            threading.Thread(
                target=lambda: self._start_batch_worker(
                    selected_videos,
                    selected_algos,
                    epochs,
                    batch,
                    total,
                    dialog,
                    ui,
                    _ft_log,
                ),
                daemon=True,
            ).start()

        ui["start_btn"].clicked.connect(_start_ft)
        ui["cancel_btn"].clicked.connect(dialog.close)
        dialog.exec()

    def _build_batch_dialog(self, algo_list, videos):
        """构建批量微调对话框，返回 (dialog, ui_dict)"""
        dialog = QDialog(self)
        dialog.setWindowTitle("批量微调")
        dialog.resize(650, 500)
        dialog.setModal(True)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(10, 10, 10, 10)

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(main, 1)

        # 选择视频
        video_title = QLabel("选择视频")
        video_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        main_layout.addWidget(video_title)
        video_frame = QFrame(main)
        video_frame.setStyleSheet(f"background-color: {C['bg_elevated']}; border: 1px solid {C['border']};")
        vf_layout = QHBoxLayout(video_frame)
        vf_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(video_frame)
        v_sf = ScrollableFrame(video_frame, bg=C["bg_elevated"], height=100)
        vf_layout.addWidget(v_sf, 1)

        video_vars = {}
        for v in sorted(videos, key=lambda x: x["bvid"]):
            cb = QCheckBox(f"{v['title']}  ({v['bvid']})")
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {C['text_1']};")
            video_vars[v["bvid"]] = cb
            v_sf.addWidget(cb)

        # 选择算法
        algo_title = QLabel("选择算法")
        algo_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        main_layout.addWidget(algo_title)
        algo_frame = QFrame(main)
        algo_frame.setStyleSheet(f"background-color: {C['bg_elevated']}; border: 1px solid {C['border']};")
        af_layout = QHBoxLayout(algo_frame)
        af_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(algo_frame)
        a_sf = ScrollableFrame(algo_frame, bg=C["bg_elevated"], height=100)
        af_layout.addWidget(a_sf, 1)

        algo_vars = {}
        for a in sorted(algo_list, key=lambda x: x["name"]):
            cb = QCheckBox(f"{a['name']}  ({a['algorithm_id']})")
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {C['text_1']};")
            algo_vars[a["algorithm_id"]] = cb
            a_sf.addWidget(cb)

        # 参数行
        param_row = QWidget()
        param_row_layout = QHBoxLayout(param_row)
        param_row_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(param_row)

        epoch_label = QLabel("Epochs:")
        epoch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        epoch_label.setFont(FONT_SM)
        param_row_layout.addWidget(epoch_label)
        ft_epoch_spin = QSpinBox()
        ft_epoch_spin.setRange(1, 100)
        ft_epoch_spin.setValue(5)
        param_row_layout.addWidget(ft_epoch_spin)
        param_row_layout.addSpacing(12)

        batch_label = QLabel("Batch:")
        batch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        batch_label.setFont(FONT_SM)
        param_row_layout.addWidget(batch_label)
        ft_batch_spin = QSpinBox()
        ft_batch_spin.setRange(1, 512)
        ft_batch_spin.setValue(16)
        param_row_layout.addWidget(ft_batch_spin)
        param_row_layout.addStretch()

        ft_status = QLabel("就绪")
        ft_status.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        ft_status.setFont(FONT_SM)
        main_layout.addWidget(ft_status)
        ft_progress = QProgressBar()
        ft_progress.setMaximum(100)
        ft_progress.setValue(0)
        main_layout.addWidget(ft_progress)

        log_text = QPlainTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                font-family: Consolas;
                font-size: 9pt;
                border: 1px solid {C['border']};
            }}
        """)
        main_layout.addWidget(log_text, 1)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(btn_row)
        start_btn = QPushButton("▶ 开始微调")
        btn_row_layout.addWidget(start_btn)
        cancel_btn = QPushButton("取消")
        btn_row_layout.addWidget(cancel_btn)
        btn_row_layout.addStretch()

        return dialog, {
            "video_vars": video_vars,
            "algo_vars": algo_vars,
            "ft_epoch_spin": ft_epoch_spin,
            "ft_batch_spin": ft_batch_spin,
            "ft_status": ft_status,
            "ft_progress": ft_progress,
            "log_text": log_text,
            "start_btn": start_btn,
            "cancel_btn": cancel_btn,
        }

    def _start_batch_worker(self, selected_videos, selected_algos, epochs, batch, total, dialog, ui, _ft_log):
        """后台工作线程：依次对每个视频的每个算法进行微调"""
        from algorithms.training.trainer import ModelTrainer

        trainer = ModelTrainer()
        done = 0
        self.main.set_finetune_status(f"🎯 批量微调 0/{total}")
        for bvid in selected_videos:
            for aid in selected_algos:
                done += 1
                pct = int(done / total * 100)
                msg = f"[{done}/{total}] 微调 {aid} → {bvid}"
                invoke(lambda m=msg: ui["ft_status"].setText(m))
                invoke(lambda p=pct: ui["ft_progress"].setValue(p))
                invoke(lambda m=msg: _ft_log(m))
                invoke(lambda d=done, t=total: self.main.set_finetune_status(f"🎯 批量微调 {d}/{t}"))
                try:
                    ver = trainer.finetune_for_video(
                        algo_id=aid,
                        bvid=bvid,
                        epochs=epochs,
                        batch_size=batch,
                    )
                    invoke(lambda a=aid, b=bvid, v=ver: _ft_log(f"  ✓ {a}@{b} → {v[:12]}"))
                except Exception as e:
                    invoke(lambda a=aid, b=bvid, e=e: _ft_log(f"  ✗ {a}@{b}: {e}"))
        self._batch_done_callback(dialog, ui, _ft_log, done)

    def _batch_done_callback(self, dialog, ui, _ft_log, done):
        """批量微调完成后的 UI 更新回调"""
        invoke(lambda: ui["ft_status"].setText(f"✅ 微调完成 ({done} 任务)"))
        invoke(lambda: ui["ft_progress"].setValue(100))
        invoke(lambda: self.main.set_finetune_status(f"✅ 批量微调完成 ({done})"))
        invoke(lambda: ui["start_btn"].setEnabled(True))
        invoke(lambda: _ft_log("🏁 批量微调全部完成"))

    # ══════════════════════════════════════════════
    # 训练执行
    # ══════════════════════════════════════════════

    def _on_train_start(self):
        """开始训练按钮回调 — 验证参数、确认、启动训练线程"""
        config = self._validate_train_params()
        if config is None:
            return

        selected, epochs, batch, is_incremental, lr, mode_label, lr_label, parallel, batch_log, interval_val, interval_unit = config
        self._build_train_config(selected, epochs, batch, mode_label, lr)
        self._start_train_thread(selected, is_incremental, lr, epochs, batch, parallel, batch_log, interval_val, interval_unit)

    def _validate_train_params(self):
        """校验训练参数并弹出确认对话框，返回训练配置或 None"""
        if self._training:
            return None
        if not _torch_available:
            QMessageBox.critical(self, "torch 未安装", "请先 pip install torch")
            return None

        selected = [aid for aid, cb in self._check_vars.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "提示", "请至少勾选一个算法")
            return None

        epochs = max(1, self._epoch_spin.value())
        batch = max(1, self._batch_spin.value())
        is_incremental = self._mode_incremental.isChecked()
        mode_label = "增量训练" if is_incremental else "重新训练"

        # 并行数 + VRAM 安全检查
        parallel = max(1, min(4, self._parallel_spin.value()))
        if parallel > len(selected):
            parallel = len(selected)
        parallel_warning = ""
        try:
            from algorithms.training.device import get_device_info
            dev_info = get_device_info()
            if dev_info.get("is_gpu") and dev_info.get("total_memory_gb", 0) > 0:
                vram_gb = dev_info["total_memory_gb"]
                # 保守估计每个模型 ~0.4GB（实际模型多数 < 50MB，0.4GB 已含余量）
                est_per_model_gb = 0.4
                max_safe = max(1, int(vram_gb / est_per_model_gb))
                if parallel > max_safe:
                    parallel = max_safe
                    parallel_warning = (
                        f"\n⚠️ 显存安全限制：{vram_gb:.1f}GB 显存，"
                        f"自动降为并行 {parallel}（避免炸显存）"
                    )
        except Exception:
            pass

        if self._lr_auto_cb.isChecked():
            lr = self._auto_compute_lr()
            self._lr_entry.setText(f"{lr:.6f}")
            lr_label = f"自动 ({lr:.6f})"
        else:
            try:
                lr = float(self._lr_entry.text())
            except (ValueError, TypeError):
                QMessageBox.critical(self, "LR 无效", "请输入有效的学习率数值")
                return None
            lr = max(1e-8, min(1.0, lr))
            lr_label = f"手动 ({lr:.6f})"

        reply = QMessageBox.question(
            self, "确认训练",
            f"模式: {mode_label}  并行: {parallel}\n"
            f"算法: {len(selected)} 个\n"
            f"epoch={epochs}  batch={batch}  LR={lr_label}"
            f"{parallel_warning}\n"
            f"训练过程不可中途暂停（只能取消未开始的算法）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None

        return (selected, epochs, batch, is_incremental, lr, mode_label, lr_label, parallel, self._batch_log_cb.isChecked(), self._batch_interval_entry.text(), self._batch_interval_combo.currentText())

    def _build_train_config(self, selected, epochs, batch, mode_label, lr):
        """重置训练状态、打开日志文件、更新状态标签"""
        self._prepare_training()
        self._open_log_file(len(selected), epochs, batch, mode_label, lr)
        self._append_log(
            f"🚀 开始训练: {mode_label}, {len(selected)} 个算法, epoch={epochs}, batch={batch}, lr={lr:.6f}"
        )
        if self._batch_log_cb.isChecked():
            val = self._batch_interval_entry.text()
            unit = self._batch_interval_combo.currentText()
            self._append_log(f"📋 详细日志：每 {val}{unit} batch 输出进度")
        self._status_lbl.setText(f"准备训练 {len(selected)} 个算法 …")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")

        # ── 全局反馈：窗口标题 + 主界面状态栏 ──
        try:
            top = self.window()
            if top and top.window():
                self._saved_title = top.windowTitle()
                top.setWindowTitle(f"🔴 训练中 — {self._saved_title}")
        except Exception:
            self._saved_title = None
        self._safe_sb("algo", f"🤖 训练: 0/{len(selected)} 算法", color=C["accent"])
        self._safe_sb("status", "训练中…", color=C["accent"])
        self._algo_durations: List[float] = []  # 各算法耗时（用于跨算法 ETA）

    def _start_train_thread(self, selected, is_incremental, lr, epochs, batch, parallel, batch_log, interval_val, interval_unit):
        """启动训练线程（支持并行模式 + 可配置 batch 级日志间隔）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(selected)
        algo_lr_factors: Dict[str, float] = {}
        completed_count = [0]

        # 解析 batch 日志间隔
        batch_interval = None
        batch_interval_mode = "%"  # % 或 count
        try:
            val = float(interval_val)
            if interval_unit == "%":
                val = max(1, min(100, val))  # 限制 1%~100%
                batch_interval = val / 100.0  # 转为比例
                batch_interval_mode = "%"
            else:
                val = max(1, int(val))
                batch_interval = val
                batch_interval_mode = "count"
        except (ValueError, TypeError):
            batch_interval = 0.1  # 默认 10%
            batch_interval_mode = "%"

        def _cb(payload: Dict):
            """训练回调 — 线程安全。batch_log 关闭时过滤 batch 消息。"""
            payload["_total_selected"] = total
            payload["_incremental"] = is_incremental

            if not batch_log and payload.get("stage") == "batch":
                return

            if self._skip_algo_flag[0]:
                payload["_adjustment"] = "⏭ 用户手动跳过"
                payload["early_stop"] = True
                self._train_queue.put(payload)
                return

            self._train_queue.put(payload)

        def _train_one_algo(aid):
            """在独立线程中训练单个算法。每个算法有自己的 trainer/control/monitor。"""
            if self._cancel_flag[0]:
                return aid, False

            try:
                from algorithms.training.trainer import ModelTrainer

                # 非增量模式：清除旧 checkpoint
                if not is_incremental:
                    from algorithms.training.checkpoint_manager import CheckpointManager
                    _ckpt = CheckpointManager(aid)
                    _n = _ckpt.delete_all()
                    if _n:
                        self._train_queue.put({"stage": "log", "text": f"  🗑 已清除 {aid} 的 {_n} 个旧版本"})

                self._skip_algo_flag[0] = False
                if self._skip_btn:
                    invoke(lambda: self._skip_btn.setEnabled(False))
                    invoke(lambda: self._skip_btn.setEnabled(True))

                aid_factor = algo_lr_factors.get(aid, 1.0)
                effective_lr = lr * aid_factor
                control = {}
                # 注入 batch 日志间隔配置
                if batch_log and batch_interval is not None:
                    control["_batch_interval"] = batch_interval
                    control["_batch_interval_mode"] = batch_interval_mode
                trainer = ModelTrainer()
                sub = trainer.train_global(
                    [aid],
                    epochs=epochs,
                    batch_size=batch,
                    progress_cb=_cb,
                    init_from_global=is_incremental,
                    lr=effective_lr,
                    control_dict=control,
                )
                completed_count[0] += 1
                return aid, bool(sub.get(aid))
            except Exception as e:
                self._train_queue.put({"stage": "error", "algo_id": aid, "current": completed_count[0], "total": total, "error": str(e)})
                return aid, False

        def _worker():
            """并行训练调度线程"""
            try:
                results = {}
                if parallel <= 1:
                    # 串行模式（保持原有行为）
                    for aid in selected:
                        if self._cancel_flag[0]:
                            self._train_queue.put({"stage": "cancelled", "remaining": selected[completed_count[0]:]})
                            break
                        ok, success = _train_one_algo(aid)
                        results[ok] = ok if success else ""
                else:
                    # 并行模式
                    self._append_log(f"⚡ 并行训练 ({parallel} 线程)")
                    with ThreadPoolExecutor(max_workers=parallel) as pool:
                        futures = {pool.submit(_train_one_algo, aid): aid for aid in selected}
                        for f in as_completed(futures):
                            if self._cancel_flag[0]:
                                # 取消剩余任务
                                for remaining_f in futures:
                                    if not remaining_f.done():
                                        remaining_f.cancel()
                                remaining_aids = [futures[rf] for rf in futures if not rf.done()]
                                self._train_queue.put({"stage": "cancelled", "remaining": remaining_aids})
                                break
                            aid, success = f.result()
                            results[aid] = aid if success else ""

                self._train_queue.put({"stage": "all_done", "results": results})
            except Exception as e:
                self._train_queue.put({"stage": "fatal", "error": str(e)})

        self._launch_worker(_worker)

    def _on_cancel(self):
        """取消训练按钮回调"""
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.setEnabled(False)
        if self._status_lbl:
            self._status_lbl.setText("正在取消（等待当前算法完成）…")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log("⏹ 用户请求取消训练")
        self._close_log_file()

    def _on_skip_algo(self):
        """跳过当前正在训练的算法，继续下一个。"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.setEnabled(False)
        if self._status_lbl:
            self._status_lbl.setText("⏭ 跳过当前算法（等待本轮完成）…")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log("⏭ 用户请求跳过当前算法")

    STAGE_HANDLERS = {
        "start": "_on_stage_start",
        "batch": "_on_stage_batch",
        "epoch": "_on_stage_epoch",
        "done": "_on_stage_done",
        "error": "_on_stage_error",
        "auto_adjust": "_on_stage_auto_adjust",
        "cancelled": "_on_stage_cancelled",
        "all_done": "_on_stage_all_done",
        "fatal": "_on_stage_fatal",
    }

    def _handle_stage(self, msg) -> bool:
        """根据消息 stage 分发给对应的事件处理器"""
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        """处理训练开始事件"""
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        self._current_aid = aid
        self._total_algos = tot
        self._algo_start_time = time.time()
        self._epoch_times: List[float] = []  # 当前算法各 epoch 耗时（秒）
        self._last_epoch_elapsed = 0.0
        if self._status_lbl:
            self._status_lbl.setText(f"[{cur}/{tot}] 训练 {aid} …")
            self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        self._append_log(f"── [{cur}/{tot}] 开始训练 {aid} ──")
        self._update_algo_row(aid, status="▶ 训练中", status_color=C["accent"])
        self._monitor.reset()
        # 状态栏 + 进度条动画
        self._safe_sb("algo", f"🤖 [{cur}/{tot}] {aid}", color=C["accent"])
        if self._progress:
            self._progress.setValue(0)
            self._progress.setMinimum(0)
            self._progress.setMaximum(100)

    def _on_stage_batch(self, msg):
        """处理 batch 完成事件 — 更新状态栏并写入详细日志"""
        aid = msg.get("algo_id", "?")
        b = msg.get("batch", 0)
        tot_b = msg.get("total_batches", 1)
        avg_loss = msg.get("avg_loss", 0)
        batch_loss = msg.get("batch_loss", 0)
        try:
            self.main._sb("status", f"🔄 {aid} batch {b}/{tot_b} loss={avg_loss:.4f}", color=C["text_2"])
        except Exception:
            pass
        # 详细日志：batch 级损失写入日志面板和文件
        pct = b / max(tot_b, 1) * 100
        self._append_log(f"  📊 {aid} batch {b}/{tot_b} ({pct:.0f}%) | batch_loss={batch_loss:.6f} | avg_loss={avg_loss:.6f}")
        return False

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """格式化时长为可读字符串"""
        if seconds < 0:
            return "--"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}m{s}s" if s > 0 else f"{m}m"
        h, r = divmod(int(seconds), 3600)
        m = r // 60
        return f"{h}h{m}m" if m > 0 else f"{h}h"

    def _on_stage_epoch(self, msg):
        """处理每个 epoch 完成事件 — 更新图表、进度、日志、EMA 加权 ETA"""
        aid = msg.get("algo_id", "?")
        ep = msg.get("epoch", 0)
        eps = msg.get("epochs", 1)
        tloss = msg.get("train_loss", 0.0)
        vloss = msg.get("val_loss", -1.0)
        elapsed = msg.get("elapsed_s", 0.0)

        conf = loss_to_confidence(vloss) if vloss >= 0 else 0.0
        conf_str, conf_color = format_confidence(conf)

        if ep == 1 or ep % 5 == 0 or ep == eps:
            self._update_algo_row(aid, conf=conf_str, conf_color=conf_color)

        pct = min(100, int((ep / max(1, eps)) * 100))
        if self._progress:
            self._progress.setValue(pct)
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""

        # ── EMA 加权 ETA：最近 epoch 权重更高 ──
        epoch_duration = max(0, elapsed - self._last_epoch_elapsed)
        self._last_epoch_elapsed = elapsed
        if epoch_duration > 0 and epoch_duration < 3600:  # 排除异常值
            self._epoch_times.append(epoch_duration)
            if len(self._epoch_times) > 10:
                self._epoch_times = self._epoch_times[-10:]

        total_eta_str = ""
        if self._epoch_times:
            # EMA：衰减因子 0.7，最近 epoch 权重指数级更高
            alpha = 0.7
            recent_weights = [alpha ** (len(self._epoch_times) - 1 - i) for i in range(len(self._epoch_times))]
            weight_sum = sum(recent_weights)
            ema_epoch = sum(t * w for t, w in zip(self._epoch_times, recent_weights)) / max(weight_sum, 1e-10)

            # 本算法剩余时间
            algo_remaining = ema_epoch * (eps - ep)
            algo_eta = self._fmt_duration(algo_remaining)

            # 总训练剩余时间 = 本算法剩余 + 未开始算法预估
            cur = msg.get("current", 0)
            tot = msg.get("total", 1)
            remaining_algos = tot - cur
            if remaining_algos > 0 and hasattr(self, "_algo_durations") and self._algo_durations:
                avg_algo_time = sum(self._algo_durations) / len(self._algo_durations)
                # 已完成算法数较少时，用本算法当前速率补充
                if len(self._algo_durations) < 2:
                    avg_algo_time = max(avg_algo_time, ema_epoch * eps * 0.8)
                other_remaining = avg_algo_time * (remaining_algos - 1)  # -1 因为当前算法已在算
            else:
                # 无历史数据：用本算法速率外推
                other_remaining = ema_epoch * eps * max(0, remaining_algos - 1)

            total_remaining = algo_remaining + other_remaining
            total_eta_str = f"  ⏱本{algo_eta} 总{self._fmt_duration(total_remaining)}"

        if self._status_lbl:
            self._status_lbl.setText(
                f"{aid}  ep{ep}/{eps}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s{total_eta_str}"
            )
            self._status_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")

        # 主窗口状态栏（含 ETA）
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        status_text = f"🤖 [{cur}/{tot}] {aid} ep{ep}/{eps}  {elapsed:.0f}s"
        if total_eta_str:
            # 提取总 ETA 部分
            parts = total_eta_str.split("总")
            if len(parts) > 1:
                status_text += f"  ⇨{parts[1]}"
        self._safe_sb("algo", status_text, color=C["accent"])
        self._safe_sb("status", f"训练中  loss={tloss:.4f}", color=C["text_2"])

        self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
        self._refresh_monitor()

        adj = msg.get("_adjustment", "")
        if adj:
            self._append_log(f"  {adj}")

        self._loss_history.append(
            {
                "algo": aid,
                "epoch": ep,
                "train_loss": tloss,
                "val_loss": vloss,
            }
        )
        self._update_chart()
        self._append_log(
            f"  epoch {ep:>3}/{eps}  |  "
            f"train_loss={tloss:.6f}  |  "
            f"{f'val_loss={vloss:.6f}' if vloss >= 0 else 'val_loss=N/A'}  |  "
            f"confidence={conf_str}  |  "
            f"{elapsed:.1f}s"
        )

    def _on_stage_done(self, msg):
        """处理单个算法训练完成事件"""
        total_sel = msg.get("_total_selected", 1)
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        ver = msg.get("version", "")
        algo_elapsed = time.time() - getattr(self, "_algo_start_time", time.time())

        # 记录算法耗时用于跨算法 ETA
        if not hasattr(self, "_algo_durations"):
            self._algo_durations = []
        self._algo_durations.append(algo_elapsed)

        if self._status_lbl:
            self._status_lbl.setText(f"✓ {aid} → {ver} ({cur}/{total_sel})  {algo_elapsed:.0f}s")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        if self._progress:
            self._progress.setValue(int(cur / max(1, total_sel) * 100))

        # 计算总体 ETA
        remaining = total_sel - cur
        total_eta = ""
        if remaining > 0 and self._algo_durations:
            avg_dur = sum(self._algo_durations) / len(self._algo_durations)
            total_eta = f"  ⇨剩余≈{self._fmt_duration(avg_dur * remaining)}"

        # 主窗口状态栏
        self._safe_sb("algo", f"🤖 ✓ [{cur}/{total_sel}] {aid}  {algo_elapsed:.0f}s{total_eta}", color=C["success"])

        # 从 checkpoint 读取 val_loss 和置信度
        from algorithms.training.checkpoint_manager import CheckpointManager

        _val_loss = -1.0
        try:
            _ckpt = CheckpointManager(aid)
            _versions = _ckpt.list_versions()
            if _versions:
                _val_loss = _versions[0].get("val_loss", -1.0)
        except Exception as e:
            logger.debug("忽略异常: %s", e)
        conf = loss_to_confidence(_val_loss) if _val_loss >= 0 else load_algo_confidence(aid)
        conf_str, conf_color = format_confidence(conf)
        self._algo_confidence[aid] = conf
        if _val_loss >= 0:
            self._append_log(f"  ✓ {aid} → {ver}  置信度={conf_str}  val_loss={_val_loss:.4f}")
        else:
            self._append_log(f"  ✓ {aid} → {ver}")
        self._update_algo_row(
            aid,
            status=f"✓ {ver[:10]}",
            status_color=C["success"],
            conf=conf_str,
            conf_color=conf_color,
            ver=f"v{self._algo_meta.get(aid, {}).get('version_count', 0) + 1}",
        )

    def _on_stage_error(self, msg):
        """处理训练错误事件"""
        aid = msg.get("algo_id", "?")
        err = msg.get("error", "")
        if self._status_lbl:
            self._status_lbl.setText(f"✗ {aid} 失败: {err}")
            self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
        self._append_log(f"✗ {aid} 训练失败: {err}")
        self._update_algo_row(aid, status="✗ 失败", status_color=C["danger"])
        self._safe_sb("algo", f"🤖 ✗ {aid} 失败", color=C["danger"])

    def _on_stage_auto_adjust(self, msg):
        """处理自动调整事件"""
        message = msg.get("message", "")
        self._append_log(f"  🔧 自动调整: {message}")
        if self._status_lbl:
            self._status_lbl.setText(f"⚡ {message}")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")

    def _on_stage_cancelled(self, msg):
        """处理取消训练事件"""
        rem = msg.get("remaining", [])
        if self._status_lbl:
            self._status_lbl.setText(f"已取消，剩余 {len(rem)} 个")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log(f"⏹ 已取消, 剩余 {len(rem)} 个算法")
        self._safe_sb("algo", f"⏹ 训练已取消 (剩余{len(rem)}个)", color=C["warning"])
        return True

    def _on_stage_all_done(self, msg):
        """处理所有算法训练完成事件"""
        results = msg.get("results", {})
        self._last_training_results = results
        ok = sum(1 for v in results.values() if v)
        bad = sum(1 for v in results.values() if not v)
        elapsed = time.time() - self._train_t0 if self._train_t0 else 0

        conf_summary = ""
        for aid, ver in results.items():
            if not ver:
                continue
            conf = load_algo_confidence(aid)
            self._algo_confidence[aid] = conf
            conf_str, _ = format_confidence(conf)
            conf_summary += f"  {aid}: {conf_str}"

        if self._status_lbl:
            self._status_lbl.setText(f"全部完成: ✓ {ok}  ✗ {bad}  · {elapsed:.0f}s")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        if self._progress:
            self._progress.setValue(100)
        self._append_log(f"🏁 训练全部完成: {ok} 成功, {bad} 失败, 耗时 {elapsed:.0f}s")
        self._append_log(f"📊 各算法最终置信度:{conf_summary}")
        # 主窗口状态栏
        self._safe_sb("algo", f"🤖 ✓ 训练完成 ({ok}成功 {bad}失败)  {elapsed:.0f}s", color=C["success"])
        return True

    def _on_stage_fatal(self, msg):
        """处理训练进程致命错误事件"""
        err = msg.get("error", "")
        if self._status_lbl:
            self._status_lbl.setText(f"训练异常: {err}")
            self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
        self._append_log(f"💥 训练进程异常: {err}")
        return True

    def _cleanup_training(self):
        """训练清理：关闭日志、刷新列表、通知完成"""
        self._close_log_file()
        super()._cleanup_training()
        self._refresh_algo_list()
        try:
            self.main._refresh_model_status()
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 恢复窗口标题和状态栏
        try:
            if self._saved_title:
                self.window().setWindowTitle(self._saved_title)
        except Exception:
            pass
        self._safe_sb("status", "就绪", color=C["text_3"])

        # 训练自动回调：通知 + 重新预测
        trained = getattr(self, "_last_training_results", {})
        ok = [aid for aid, v in trained.items() if v]
        if ok:
            detail = ", ".join(ok[:6])
            if len(ok) > 6:
                detail += f" …等{len(ok)}个"
            try:
                self.main._on_training_completed("训练", len(ok), detail)
            except Exception as e:
                logger.debug("忽略异常: %s", e)

    # ══════════════════════════════════════════════
    # 训练质量监控
    # ══════════════════════════════════════════════

    def _on_monitor_changed(self):
        """日志记录：状态变化时记录，同状态每 8 epoch 持续监测提醒。"""
        if self._monitor.level in ("warning", "danger") and self._monitor.suggestions:
            cur_status = self._monitor.status
            last_status = getattr(self, "_last_monitor_status", "")
            last_epoch = getattr(self, "_last_monitor_log_epoch", 0)
            cur_epoch = len(self._monitor._points)

            if cur_status != last_status or cur_epoch - last_epoch >= 8:
                self._last_monitor_status = cur_status
                self._last_monitor_log_epoch = cur_epoch
                prefix = "🤖 训练质量检测" if cur_status != last_status else "🔄 持续监测"
                self._append_log(f"{prefix}: {cur_status}")
                for s in self._monitor.suggestions:
                    self._append_log(f"  💡 {s}")

                # 学习率建议：显示当前值和推荐值
                lr_suggestion = self._compute_lr_suggestion()
                if lr_suggestion:
                    self._append_log(f"  📐 {lr_suggestion}")

    def _compute_lr_suggestion(self) -> str:
        """根据 TrainingMonitor 的 loss 数据动态计算推荐学习率。"""
        suggestions_text = " ".join(self._monitor.suggestions).lower()
        if "增大学习率" in suggestions_text or "下降过慢" in self._monitor.status:
            scale = self._monitor.compute_lr_scale("underfitting")
            try:
                cur_lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        elif "大幅降低" in suggestions_text:
            scale = self._monitor.compute_lr_scale("explosion")
            try:
                cur_lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        elif "降低学习率" in suggestions_text:
            status = self._monitor.status
            issue = "oscillation" if "波动" in status else "overfitting"
            scale = self._monitor.compute_lr_scale(issue)
            try:
                cur_lr = float(self._lr_var.get())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        return ""

    # ══════════════════════════════════════════════
    # 日志（UI + 存盘）
    # ══════════════════════════════════════════════

    def _open_log_file(self, algo_count: int, epochs: int, batch: int, mode: str, lr: float = 0.001):
        """创建训练日志文件。"""
        os.makedirs(self._log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file_path = os.path.join(self._log_dir, f"train_{ts}.log")
        self._log_file = open(self._log_file_path, "w", encoding="utf-8")
        # 写文件头
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.write(f"  训练启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._log_file.write(
            f"  模式: {mode}  |  算法: {algo_count}  |  epoch: {epochs}  |  batch: {batch}  |  lr: {lr:.6f}\n"
        )
        self._log_file.write(f"{'=' * 60}\n")
        self._log_file.flush()

    def _close_log_file(self):
        """关闭训练日志文件。"""
        if self._log_file is None:
            return
        try:
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.write(f"  训练结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self._log_file.write(f"{'=' * 60}\n")
            self._log_file.flush()
            self._log_file.close()
        except Exception as e:
            logger.debug("关闭训练日志文件失败: %s", e)
        self._log_file = None
        logger.info("训练日志已保存: %s", self._log_file_path)

    def __del__(self):
        """析构时兜底关闭日志文件，防止异常路径下文件句柄泄漏。"""
        if getattr(self, "_log_file", None) is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _append_log(self, text: str):
        """追加日志到 UI 和文件"""
        super()._append_log(text)
        if self._log_file is not None:
            try:
                line = f"[{time.strftime('%H:%M:%S')}] {text}\n"
                self._log_file.write(line)
                self._log_file.flush()
            except Exception as e:
                logger.debug("写入训练日志文件失败: %s", e)
