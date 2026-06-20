"""
微调面板 — 与训练面板同级同显示
支持选择多个视频 + 多个算法，一键启动微调
右侧实时 loss 图表 + 训练质量监控 + 文字日志
自动切换当前训练视频的模型信息与置信度
"""

import time
import logging
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QProgressBar,
    QFrame, QTabWidget, QGroupBox, QGridLayout, QScrollArea,
    QPlainTextEdit, QMessageBox, QDialog, QSplitter, QSizePolicy,
    QToolButton, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QRadioButton, QButtonGroup, QHeaderView,
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
from ui.training_base import BaseTrainingPanel, TrainingMonitor
from ui.scrollable_frame import ScrollableFrame
from utils.update_checker import _train

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class FinetunePanel(BaseTrainingPanel):
    """微调面板 — 与训练面板同级同显示"""

    def __init__(self, parent: QWidget, main_gui):
        super().__init__(parent, main_gui)

        # 视频 / 算法勾选状态
        self._video_vars: Dict[str, QCheckBox] = {}
        self._algo_vars: Dict[str, QCheckBox] = {}
        self._algo_meta: Dict[str, Dict] = {}

        # 当前任务上下文
        self._current_bvid = ""

        # 微调结果回溯（用于训练完成自动回调）
        self._last_finetune_count = 0

        # 自动调整状态
        self._auto_control: Dict = {}
        self._auto_monitors: Dict[str, TrainingMonitor] = {}
        self._algo_lr_factors: Dict[str, float] = {}
        self._use_new_data_only = False

        # 当前视频的所有算法结果缓存（用于自动切换显示）
        self._video_results: Dict[str, List[Dict]] = {}

        self._build_ui()

    # ══════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════

    def _build_ui(self):
        """构建微调面板的完整 UI，包含左（视频+算法）、右（图表+监控+日志）、底部控制栏"""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── 顶部信息栏 ──
        info_bar = QFrame(self)
        info_bar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(8, 8, 8, 4)
        outer_layout.addWidget(info_bar)
        info_lbl = QLabel("批量微调 — 选择视频和算法，一键微调已有全局 checkpoint 的模型")
        info_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        info_layout.addWidget(info_lbl)
        info_layout.addStretch()
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self._refresh_all)
        info_layout.addWidget(refresh_btn)

        # ── 主体区域: 左(视频+算法) | 右(图表+监控+日志) ──
        body = QFrame(self)
        body.setStyleSheet(f"background-color: {C['bg_base']};")
        outer_layout.addWidget(body, 1)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 4, 8, 4)
        body_layout.setSpacing(4)

        self._build_left(body)
        self._build_right(body)

        # ── 底部控制栏 ──
        self._build_controls(self)

    # ── 左侧: 视频 + 算法 ──

    def _build_left(self, parent):
        """构建左侧面板：视频列表和算法列表（含勾选框、置信度、版本信息）"""
        left = QFrame(parent)
        left.setStyleSheet(f"background-color: {C['bg_surface']};")
        parent_layout = parent.layout()
        parent_layout.addWidget(left, 35)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # ── 视频列表 ──
        v_frame = QFrame(left)
        v_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        left_layout.addWidget(v_frame, 1)
        vf_layout = QVBoxLayout(v_frame)
        vf_layout.setContentsMargins(0, 0, 0, 0)
        v_hdr = QFrame(v_frame)
        v_hdr.setStyleSheet(f"background-color: {C['bg_elevated']};")
        vhdr_layout = QHBoxLayout(v_hdr)
        vhdr_layout.setContentsMargins(4, 4, 4, 0)
        v_title = QLabel("🎬 选择视频")
        v_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        vhdr_layout.addWidget(v_title)
        vhdr_layout.addStretch()
        self._video_count_lbl = QLabel("")
        self._video_count_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT_SM};")
        vhdr_layout.addWidget(self._video_count_lbl)
        vf_layout.addWidget(v_hdr)

        v_sf = ScrollableFrame(v_frame, bg=C["bg_elevated"])
        vf_layout.addWidget(v_sf, 1)
        self._video_inner = v_sf.inner

        # ── 算法列表（带状态/置信度/版本列）──
        a_frame = QFrame(left)
        a_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        left_layout.addWidget(a_frame, 1)
        af_layout = QVBoxLayout(a_frame)
        af_layout.setContentsMargins(0, 0, 0, 0)
        a_hdr = QFrame(a_frame)
        a_hdr.setStyleSheet(f"background-color: {C['bg_elevated']};")
        ahdr_layout = QHBoxLayout(a_hdr)
        ahdr_layout.setContentsMargins(4, 4, 4, 0)
        a_title = QLabel("🧠 选择算法（已训练）")
        a_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        ahdr_layout.addWidget(a_title)
        ahdr_layout.addStretch()
        self._algo_count_lbl = QLabel("")
        self._algo_count_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT_SM};")
        ahdr_layout.addWidget(self._algo_count_lbl)
        af_layout.addWidget(a_hdr)

        a_toolbar = QFrame(a_frame)
        a_toolbar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        at_layout = QHBoxLayout(a_toolbar)
        at_layout.setContentsMargins(4, 2, 4, 2)
        at_layout.setSpacing(1)
        btn_sel_all = QPushButton("全选")
        btn_sel_all.setFixedWidth(50)
        btn_sel_all.clicked.connect(lambda: self._toggle_algos(True))
        at_layout.addWidget(btn_sel_all)
        btn_sel_inv = QPushButton("反选")
        btn_sel_inv.setFixedWidth(50)
        btn_sel_inv.clicked.connect(lambda: self._toggle_algos(False))
        at_layout.addWidget(btn_sel_inv)
        btn_version = QPushButton("🗑️ 版本管理")
        btn_version.setFixedWidth(85)
        btn_version.clicked.connect(self._on_manage_versions)
        at_layout.addWidget(btn_version)
        at_layout.addStretch()
        af_layout.addWidget(a_toolbar)

        # 表头
        hdr_row = QFrame(a_frame)
        hdr_row.setStyleSheet(f"background-color: {C['bg_surface']};")
        hdr_layout = QHBoxLayout(hdr_row)
        hdr_layout.setContentsMargins(4, 0, 4, 0)
        hdr_layout.setSpacing(2)
        for txt, w in [("", 30), ("算法", 110), ("ID", 90), ("状态", 80), ("置信度", 70), ("版本", 50)]:
            lbl = QLabel(txt)
            lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: 8pt bold;")
            lbl.setFixedWidth(w)
            hdr_layout.addWidget(lbl)
        hdr_layout.addStretch()
        af_layout.addWidget(hdr_row)

        # 滚动容器
        a_sf = ScrollableFrame(a_frame, bg=C["bg_elevated"], height=200)
        af_layout.addWidget(a_sf, 1)
        self._algo_inner = a_sf.inner

    # ── 右侧: 图表 + 监控 + 日志 ──

    def _build_right(self, parent):
        """构建右侧面板：任务信息栏、Loss 图表、训练质量监控、文字日志"""
        right = QFrame(parent)
        right.setStyleSheet(f"background-color: {C['bg_surface']};")
        parent_layout = parent.layout()
        parent_layout.addWidget(right, 65)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        # ── 当前任务信息栏 ──
        task_bar = QFrame(right)
        task_bar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        task_layout = QHBoxLayout(task_bar)
        task_layout.setContentsMargins(8, 4, 8, 4)
        self._task_lbl = QLabel("就绪 — 选择视频和算法后开始微调")
        self._task_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT};")
        task_layout.addWidget(self._task_lbl)
        task_layout.addStretch()
        self._task_detail = QLabel("")
        self._task_detail.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT_SM};")
        task_layout.addWidget(self._task_detail)
        right_layout.addWidget(task_bar)

        # ── 上半: Loss 图表 ──
        chart_frame = self._build_chart_widgets(right, title="微调 Loss 曲线")
        right_layout.addWidget(chart_frame, 1)

        # ── 中部: 训练质量监控 ──
        monitor_bar = self._build_monitor_bar(right)
        right_layout.addWidget(monitor_bar)

        # ── 下半: 文字日志 ──
        log_frame = self._build_log_widgets(right, title="微调日志")
        right_layout.addWidget(log_frame, 1)

    # ── 底部控制栏 ──

    def _build_controls(self, parent):
        """构建底部控制栏：Epochs、Batch、模式选择、开始/取消/跳过按钮、进度条"""
        ctrl = QFrame(parent)
        ctrl.setStyleSheet(f"background-color: {C['bg_elevated']};")
        layout = self.layout() if isinstance(parent, FinetunePanel) else QVBoxLayout()
        if not isinstance(parent, FinetunePanel):
            ctrl.setLayout(layout)
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(8, 4, 8, 6)
        ctrl_layout.setSpacing(8)

        epoch_label = QLabel("Epochs:")
        epoch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent; font: {FONT_SM};")
        ctrl_layout.addWidget(epoch_label)
        self._epoch_spin = QSpinBox()
        self._epoch_spin.setRange(1, 100)
        self._epoch_spin.setValue(15)
        self._epoch_spin.setFixedWidth(60)
        ctrl_layout.addWidget(self._epoch_spin)

        batch_label = QLabel("Batch:")
        batch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent; font: {FONT_SM};")
        ctrl_layout.addWidget(batch_label)
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 512)
        self._batch_spin.setValue(16)
        self._batch_spin.setFixedWidth(60)
        ctrl_layout.addWidget(self._batch_spin)

        mode_label = QLabel("模式:")
        mode_label.setStyleSheet(f"color: {C['text_2']}; background: transparent; font: {FONT_SM};")
        ctrl_layout.addWidget(mode_label)
        self._mode_incremental = QRadioButton("增量微调")
        self._mode_retrain = QRadioButton("重新训练")
        self._mode_retrain.setEnabled(_train() == "normal")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_incremental)
        self._mode_group.addButton(self._mode_retrain)
        self._mode_incremental.setChecked(True)
        ctrl_layout.addWidget(self._mode_incremental)
        ctrl_layout.addWidget(self._mode_retrain)

        self._train_btn = QPushButton("▶ 开始微调")
        self._train_btn.clicked.connect(self._on_start)
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

        if _train() != "normal":
            hint_lbl = QLabel("💡 创建 .enabletraining 文件开启微调 / 完整 devmode 见 README.md")
            hint_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent; font: 8pt;")
            ctrl_layout.addWidget(hint_lbl)

        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        ctrl_layout.addWidget(self._progress, 1)

        self._status_lbl = QLabel("就绪")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT_SM};")
        self._status_lbl.setFixedWidth(250)
        ctrl_layout.addWidget(self._status_lbl)

        parent_layout = self.layout()
        parent_layout.addWidget(ctrl)

    # ══════════════════════════════════════════════
    # 数据刷新
    # ══════════════════════════════════════════════

    def on_show(self):
        """面板显示时刷新视频和算法列表"""
        self._refresh_all()

    def _refresh_all(self):
        """刷新视频列表和算法列表"""
        self._refresh_videos()
        self._refresh_algos()

    def _refresh_videos(self):
        """从主监控列表刷新视频勾选列表"""
        v_layout = self._video_inner.layout()
        if v_layout is not None:
            while v_layout.count():
                item = v_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._video_vars.clear()

        videos = []
        try:
            for v in self.main.monitored_videos:
                bvid = v.get("bvid", "")
                title = v.get("title", bvid)
                if bvid:
                    videos.append({"bvid": bvid, "title": title[:50]})
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        self._video_count_lbl.setText(f"{len(videos)} 个视频")
        for v in sorted(videos, key=lambda x: x["bvid"]):
            cb = QCheckBox(f"{v['title']}  ({v['bvid']})")
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {C['text_1']};")
            self._video_vars[v["bvid"]] = cb
            self._video_inner.layout().addWidget(cb)

    def _refresh_algos(self):
        """从算法注册表刷新算法列表，显示训练状态、置信度和版本号"""
        a_layout = self._algo_inner.layout()
        if a_layout is not None:
            while a_layout.count():
                item = a_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._algo_vars.clear()
        self._algo_meta.clear()

        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()

        algos = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            ckpt = CheckpointManager(aid)
            versions = ckpt.list_versions()
            has_ckpt = ckpt.has_checkpoint()
            algos.append(
                {
                    "algorithm_id": aid,
                    "name": getattr(algo, "name", aid),
                    "has_ckpt": has_ckpt,
                    "active_version": ckpt.active_version() or "",
                    "version_count": len(versions),
                    "category": getattr(algo, "category", ""),
                }
            )

        trained = sum(1 for a in algos if a["has_ckpt"])
        self._algo_count_lbl.setText(f"{len(algos)} 算法 · 已训练 {trained}")

        # 按训练状态和名称排序（已训练的排前）
        for a in sorted(algos, key=lambda x: (not x["has_ckpt"], x["name"])):
            aid = a["algorithm_id"]
            self._algo_meta[aid] = a

            row = QFrame(self._algo_inner)
            row.setStyleSheet(f"background-color: {C['bg_surface']}; border: 1px solid {C['border_sub']};")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 1, 4, 1)
            row_layout.setSpacing(2)
            self._algo_inner.layout().addWidget(row)

            cb = QCheckBox("")
            cb.setChecked(True)
            self._algo_vars[aid] = cb
            row_layout.addWidget(cb)

            name_lbl = QLabel(a["name"])
            name_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
            name_lbl.setFixedWidth(110)
            row_layout.addWidget(name_lbl)

            id_lbl = QLabel(aid)
            id_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT_MONO};")
            id_lbl.setFixedWidth(90)
            row_layout.addWidget(id_lbl)

            if a["has_ckpt"]:
                st = f"✅ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 未训练"
                sf = C["text_3"]
            status_lbl = QLabel(st)
            status_lbl.setStyleSheet(f"color: {sf}; background: transparent; font: {FONT_SM};")
            status_lbl.setFixedWidth(80)
            row_layout.addWidget(status_lbl)

            conf = load_algo_confidence(aid)
            conf_text, conf_color = format_confidence(conf)
            conf_lbl = QLabel(conf_text)
            conf_lbl.setStyleSheet(f"color: {conf_color}; background: transparent; font: {FONT_SM};")
            conf_lbl.setFixedWidth(70)
            row_layout.addWidget(conf_lbl)

            ver_lbl = QLabel(f"v{a['version_count']}")
            ver_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; font: {FONT_SM};")
            ver_lbl.setFixedWidth(50)
            row_layout.addWidget(ver_lbl)

            row_layout.addStretch()

    def _refresh_algo_row(
        self,
        row_idx: int,
        aid: str,
        status_text: str,
        status_color: str,
        conf_text: str = "",
        conf_color: str = "",
        ver_text: str = "",
    ):
        """更新算法行指定列（不会重建整个列表）。"""
        # Simplified: just update any matching algo by finding its status/conf/ver labels
        # Since we don't store row refs, we rely on metadata store
        pass  # Full algo list refresh handles this

    def _toggle_algos(self, flag: bool):
        """全选或反选所有算法复选框"""
        for cb in self._algo_vars.values():
            cb.setChecked(flag)

    # ── 置信度辅助（已提取到 helpers）──

    def _load_video_confidence(self, algo_id: str, bvid: str) -> float:
        """读取视频微调 checkpoint 的置信度"""
        try:
            from algorithms.training.checkpoint_manager import CheckpointManager

            ckpt = CheckpointManager(algo_id, bvid=bvid)
            versions = ckpt.list_versions()
            active_v = ckpt.active_version()
            if not versions or not active_v:
                return 0.0
            for v in versions:
                if v["version"] == active_v:
                    return loss_to_confidence(v.get("val_loss", -1.0))
            return loss_to_confidence(versions[0].get("val_loss", -1.0))
        except Exception as e:
            import logging; logging.getLogger(__name__).debug("微调置信度计算失败: %s", e)
            return 0.0

    def _on_manage_versions(self):
        """打开版本管理对话框（复用训练面板的完整实现）"""
        if hasattr(self.main, "training_panel") and self.main.training_panel is not None:
            self.main.training_panel._on_manage_versions()

    # ══════════════════════════════════════════════
    # 微调执行
    # ══════════════════════════════════════════════

    def _on_start(self):
        """开始微调：校验选择、确认设置、启动后台训练线程"""
        if self._training:
            return
        config = self._build_finetune_config()
        if config is None:
            return
        selected_videos, selected_algos, epochs, batch, total, mode = config
        self._prepare_training()
        self._video_results.clear()
        self._auto_monitors.clear()
        self._auto_control = {}
        self._last_monitor_status = ""
        self._last_monitor_log_epoch = 0
        mode_label = "重新训练" if mode == "retrain" else "增量微调"
        data_label = "仅新数据" if self._use_new_data_only else "全部数据"
        self._append_log(
            f"🚀 开始{mode_label}（{data_label}）: {len(selected_videos)} 视频 × {len(selected_algos)} 算法, "
            f"epoch={epochs}, batch={batch}"
        )
        self._task_lbl.setText(f"{mode_label}进行中…")
        self._task_detail.setText(f"0/{total}")
        self._status_lbl.setText("准备任务…")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']};")

        def _cb(payload: Dict):
            self._handle_finetune_progress(payload, mode)

        self._start_finetune_worker(selected_videos, selected_algos, epochs, batch, total, mode, _cb)

    def _build_finetune_config(self):
        """校验选择、确认设置、检查增量数据范围，返回训练配置或 None"""
        selected_videos = [b for b, v in self._video_vars.items() if v.isChecked()]
        selected_algos = [a for a, v in self._algo_vars.items() if v.isChecked()]
        if not selected_videos:
            QMessageBox.warning(self, "提示", "请至少选择一个视频")
            return None
        if not selected_algos:
            QMessageBox.warning(self, "提示", "请至少选择一个算法")
            return None

        epochs = max(1, self._epoch_spin.value())
        batch = max(1, self._batch_spin.value())
        total = len(selected_videos) * len(selected_algos)
        mode = "retrain" if self._mode_retrain.isChecked() else "incremental"

        if mode == "retrain":
            reply = QMessageBox.question(
                self,
                "重新训练",
                "将删除所选算法在当前所有选定视频上的已有微调版本并重置版本号，\n"
                "同时删除 data/<bvid>/model/ 中的对应文件。\n确定要继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return None

        reply = QMessageBox.question(
            self,
            "确认微调",
            f"模式: {'重新训练' if mode == 'retrain' else '增量微调'}\n"
            f"视频: {len(selected_videos)} 个\n算法: {len(selected_algos)} 个\n"
            f"总任务: {total}\nepoch={epochs}  batch={batch}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None

        self._use_new_data_only = False
        if mode == "incremental":
            has_prev = False
            try:
                from algorithms.training.checkpoint_manager import CheckpointManager

                for _bv in selected_videos:
                    for _al in selected_algos:
                        _cm = CheckpointManager(_al, bvid=_bv)
                        if _cm.has_checkpoint():
                            has_prev = True
                            break
                    if has_prev:
                        break
            except Exception as e:
                logger.debug("忽略异常: %s", e)
            if has_prev:
                reply = QMessageBox.question(
                    self,
                    "增量数据范围",
                    "已有微调 checkpoint，训练数据范围如何选择？\n\n"
                    "「是」 = 仅使用上次训练截止后新增的数据（续训，速度快）\n"
                    "「否」 = 使用该视频的全部历史数据（更充分）",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                self._use_new_data_only = reply == QMessageBox.StandardButton.Yes

        return (selected_videos, selected_algos, epochs, batch, total, mode)

    def _handle_finetune_progress(self, payload: Dict, mode: str):
        """训练回调 — 运行在工作线程中，负责通信 + 自动调整"""
        payload["_mode"] = mode
        payload["_control"] = dict(self._auto_control) if self._auto_control else {}

        if self._skip_algo_flag[0]:
            self._auto_control["early_stop"] = True
            self._auto_control["_force_early_stop"] = True
            payload["_adjustment"] = "⏭ 用户手动跳过"
            self._train_queue.put(payload)
            return

        if payload.get("stage") == "epoch":
            aid = payload.get("algo_id", "")
            bvid_ = payload.get("bvid", "") or self._current_bvid
            ep = payload.get("epoch", 0)
            tloss = payload.get("train_loss", 0.0)
            vloss = payload.get("val_loss", -1.0)

            key = f"{aid}@{bvid_}"
            if key not in self._auto_monitors:
                self._auto_monitors[key] = TrainingMonitor()
            mon = self._auto_monitors[key]
            mon.update(ep, tloss, vloss if vloss >= 0 else -1)

            if mon.level in ("warning", "danger") and self._auto_control is not None:
                status = mon.status
                if "nan" in status.lower():
                    self._auto_control["early_stop"] = True
                    payload["_adjustment"] = "🔧 NaN 检测 — 提前停止"
                elif "爆炸" in status:
                    scale = mon.compute_lr_scale("explosion")
                    gc = mon.compute_grad_clip("explosion")
                    self._auto_control["lr_scale"] = scale
                    if gc > 0:
                        self._auto_control["grad_clip"] = gc
                    self._algo_lr_factors[aid] = max(0.01, min(10.0, self._algo_lr_factors.get(aid, 1.0) * scale))
                    parts = [f"LR×{scale:.2f}"]
                    if gc > 0:
                        parts.append(f"梯度裁剪={gc:.2f}")
                    parts.append(f"累计×{self._algo_lr_factors[aid]:.2f}")
                    payload["_adjustment"] = f"🔧 Loss 爆炸 — {', '.join(parts)}"
                elif "严重过拟合" in status:
                    self._auto_control["early_stop"] = True
                    wd = mon.compute_weight_decay()
                    if wd > 0:
                        self._auto_control["weight_decay"] = wd
                    payload["_adjustment"] = "🔧 严重过拟合 — 提前停止" + (f", weight_decay={wd:.4f}" if wd > 0 else "")
                elif "震荡" in status:
                    scale = mon.compute_lr_scale("oscillation")
                    gc = mon.compute_grad_clip("oscillation")
                    self._auto_control["lr_scale"] = scale
                    if gc > 0:
                        self._auto_control["grad_clip"] = gc
                    self._algo_lr_factors[aid] = max(0.01, min(10.0, self._algo_lr_factors.get(aid, 1.0) * scale))
                    parts = [f"LR×{scale:.2f}"]
                    if gc > 0:
                        parts.append(f"梯度裁剪={gc:.2f}")
                    parts.append(f"累计×{self._algo_lr_factors[aid]:.2f}")
                    payload["_adjustment"] = f"🔧 Loss 震荡 — {', '.join(parts)}"
                elif "过拟合" in status:
                    scale = mon.compute_lr_scale("overfitting")
                    wd = mon.compute_weight_decay()
                    self._auto_control["lr_scale"] = scale
                    if wd > 0:
                        self._auto_control["weight_decay"] = wd
                    self._algo_lr_factors[aid] = max(0.01, min(10.0, self._algo_lr_factors.get(aid, 1.0) * scale))
                    parts = [f"LR×{scale:.2f}"]
                    if wd > 0:
                        parts.append(f"weight_decay={wd:.4f}")
                    parts.append(f"累计×{self._algo_lr_factors[aid]:.2f}")
                    payload["_adjustment"] = f"🔧 过拟合 — {', '.join(parts)}"
                elif "欠拟合" in status or "下降过慢" in status:
                    scale = mon.compute_lr_scale("underfitting")
                    self._auto_control["lr_scale"] = scale
                    self._algo_lr_factors[aid] = max(0.01, min(10.0, self._algo_lr_factors.get(aid, 1.0) * scale))
                    payload["_adjustment"] = f"🔧 欠拟合 — LR×{scale:.2f} (累计×{self._algo_lr_factors[aid]:.2f})"
                elif "不再收敛" in status:
                    self._auto_control["early_stop"] = True
                    payload["_adjustment"] = "🔧 不再收敛 — 提前停止"

        self._train_queue.put(payload)

    def _start_finetune_worker(self, selected_videos, selected_algos, epochs, batch, total, mode, progress_cb):
        """创建后台工作线程并启动，遍历选定视频和算法逐一执行微调"""

        def _worker():
            from algorithms.training.trainer import ModelTrainer
            from algorithms.training.checkpoint_manager import CheckpointManager
            import os as _os

            trainer = ModelTrainer()
            _data_root = project_path("data")
            done = 0
            for bvid in selected_videos:
                if self._cancel_flag[0]:
                    self._train_queue.put({"stage": "cancelled", "done": done, "total": total})
                    return
                for aid in selected_algos:
                    if self._cancel_flag[0]:
                        self._train_queue.put({"stage": "cancelled", "done": done, "total": total})
                        return
                    done += 1

                    if mode == "retrain":
                        vid_ckpt = CheckpointManager(aid, bvid=bvid)
                        deleted = vid_ckpt.delete_all()
                        model_path = _os.path.join(_data_root, bvid, "model", f"{aid}.pt")
                        try:
                            if _os.path.exists(model_path):
                                _os.remove(model_path)
                        except Exception as e:
                            logger.debug("忽略异常: %s", e)
                        if deleted:
                            self._train_queue.put(
                                {
                                    "stage": "log",
                                    "text": f"  🗑 已清除 {aid}@{bvid} 的 {deleted} 个旧版本",
                                }
                            )

                    self._skip_algo_flag[0] = False
                    QTimer.singleShot(0, lambda: self._skip_btn.setEnabled(True))

                    self._train_queue.put(
                        {
                            "stage": "start",
                            "done": done,
                            "total": total,
                            "aid": aid,
                            "bvid": bvid,
                        }
                    )
                    self._auto_control = {}
                    default_epochs = epochs
                    self._algo_lr_factors[aid] = 1.0
                    prev_lr = None
                    try:
                        prev_ckpt = CheckpointManager(aid, bvid=bvid)
                        prev_versions = prev_ckpt.list_versions()
                        if prev_versions:
                            for _v in prev_versions:
                                if _v["active"]:
                                    plr = _v.get("learning_rate", -1.0)
                                    if plr > 0:
                                        prev_lr = plr
                                    break
                    except Exception as e:
                        logger.debug("忽略异常: %s", e)
                    algo_factor = self._algo_lr_factors.get(aid, 1.0)
                    effective_lr = (prev_lr or 0.001) * algo_factor
                    try:
                        ver = trainer.finetune_for_video(
                            algo_id=aid,
                            bvid=bvid,
                            epochs=default_epochs,
                            batch_size=batch,
                            progress_cb=progress_cb,
                            control_dict=self._auto_control,
                            lr=effective_lr,
                            use_new_data_only=self._use_new_data_only,
                        )
                        ckpt = CheckpointManager(aid, bvid=bvid)
                        versions = ckpt.list_versions()
                        val_loss = -1.0
                        if versions:
                            val_loss = versions[0].get("val_loss", -1.0)
                        conf = loss_to_confidence(val_loss)
                        self._train_queue.put(
                            {
                                "stage": "done",
                                "done": done,
                                "total": total,
                                "aid": aid,
                                "bvid": bvid,
                                "version": ver[:12],
                                "confidence": conf,
                                "val_loss": val_loss,
                            }
                        )
                    except Exception as e:
                        self._train_queue.put(
                            {
                                "stage": "error",
                                "done": done,
                                "total": total,
                                "aid": aid,
                                "bvid": bvid,
                                "error": str(e),
                            }
                        )
            self._train_queue.put({"stage": "all_done", "done": done, "total": total})

        self._launch_worker(_worker)

    def _on_cancel(self):
        """取消当前正在运行的全部微调任务"""
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.setEnabled(False)
        self._append_log("⏹ 用户请求取消")
        self.main.set_finetune_status("⏹ 微调已取消", color=C["warning"])

    def _on_skip_algo(self):
        """跳过当前正在微调的（视频,算法）对，继续下一个。"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.setEnabled(False)
        self._append_log("⏭ 用户请求跳过当前任务")

    STAGE_HANDLERS = {
        "start": "_on_stage_start",
        "epoch": "_on_stage_epoch",
        "done": "_on_stage_done",
        "error": "_on_stage_error",
        "auto_adjust": "_on_stage_auto_adjust",
        "log": "_on_stage_log",
        "cancelled": "_on_stage_cancelled",
        "all_done": "_on_stage_all_done",
    }

    def _handle_stage(self, msg) -> bool:
        """根据消息阶段字段分发到对应的处理函数"""
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        """处理微调任务开始阶段：更新 UI 状态和进度"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        aid = msg.get("aid", "?")
        bvid = msg.get("bvid", "?")
        self._current_bvid = bvid
        self._current_aid = aid

        if bvid not in self._video_results:
            self._loss_history.clear()
            self._clear_chart()
            self._monitor.reset()
            self._task_lbl.setText(f"🎯 视频 {bvid}: 开始微调 {aid}")
            self._task_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        else:
            self._task_lbl.setText(f"🎯 视频 {bvid}: 微调 {aid}")
            self._task_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        self._task_detail.setText(f"{done}/{total}")
        pct = min(100, int(done / max(1, total) * 100))
        self._progress.setValue(pct)
        self._status_lbl.setText(f"[{done}/{total}] 微调 {aid} → {bvid}")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        self._append_log(f"── [{done}/{total}] 开始微调 {aid}@{bvid} ──")
        self.main.set_finetune_status(f"🎯 微调 {bvid}: [{done}/{total}] {aid}")
        self._refresh_algo_row(0, aid, "▶ 训练中", C["accent"], "", "", "")

    def _on_stage_epoch(self, msg):
        """处理每个 epoch 的进度更新：更新 Loss 图表、进度条和质量监控"""
        aid = msg.get("algo_id", self._current_aid)
        bvid = msg.get("bvid", self._current_bvid)
        ep = msg.get("epoch", 0)
        eps = msg.get("epochs", 1)
        total_ep = msg.get("total_epoch", ep)
        total_eps = msg.get("total_epochs", eps)
        tloss = msg.get("train_loss", 0.0)
        vloss = msg.get("val_loss", -1.0)
        elapsed = msg.get("elapsed_s", 0.0)

        conf = loss_to_confidence(vloss) if vloss >= 0 else 0.0
        conf_str, _ = format_confidence(conf)

        # 计算并更新进度百分比
        pct = min(100, int((ep / max(1, eps)) * 100))
        self._progress.setValue(pct)
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""
        ctrl_data = msg.get("_control", {})
        ep_display = f"{total_ep}/{total_eps}" if total_eps != eps else f"{ep}/{eps}"
        if ctrl_data.get("early_stop"):
            self._status_lbl.setText(f"{aid}@{bvid}  ep{ep_display}  ⏹ 即将停止")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        elif ctrl_data.get("lr_scale"):
            self._status_lbl.setText(f"{aid}@{bvid}  ep{ep_display}  ⚡ 调整LR")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        else:
            self._status_lbl.setText(f"{aid}@{bvid}  ep{ep_display}  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s")
            self._status_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")

        self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
        self._refresh_monitor()

        self._loss_history.append(
            {
                "algo": aid,
                "bvid": bvid,
                "epoch": ep,
                "train_loss": tloss,
                "val_loss": vloss,
            }
        )
        self._update_chart()
        adj = msg.get("_adjustment", "")
        adj_suffix = f"  |  {adj}" if adj else ""
        self._append_log(
            f"  epoch {total_ep:>3}/{total_eps}  |  "
            f"train_loss={tloss:.6f}  |  "
            f"{f'val_loss={vloss:.6f}' if vloss >= 0 else 'val_loss=N/A'}  |  "
            f"confidence={conf_str}  |  "
            f"{elapsed:.1f}s{adj_suffix}"
        )

    def _on_stage_done(self, msg):
        """处理单个算法微调完成阶段：更新结果缓存和 UI"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        aid = msg.get("aid", "?")
        bvid = msg.get("bvid", "?")
        ver = msg.get("version", "")
        conf = msg.get("confidence", 0.0)
        val_loss = msg.get("val_loss", -1.0)

        pct = min(100, int(done / max(1, total) * 100))
        self._progress.setValue(pct)
        self._task_detail.setText(f"{done}/{total}")
        conf_str, conf_color = format_confidence(conf)

        if bvid not in self._video_results:
            self._video_results[bvid] = []
        self._video_results[bvid].append(
            {
                "aid": aid,
                "version": ver,
                "confidence": conf,
                "val_loss": val_loss,
            }
        )

        self._refresh_algo_row(0, aid, f"✓ {ver}", C["success"], conf_str, conf_color, f"v{msg.get('done', 0)}")

        self._status_lbl.setText(f"✓ {aid}@{bvid}  → {ver}  conf={conf_str}  ({done}/{total})")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        self._append_log(f"  ✓ {aid}@{bvid} → {ver}  置信度={conf_str}  val_loss={val_loss:.4f}")

    def _on_stage_error(self, msg):
        """处理微调出错阶段：显示错误信息并更新 UI"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        aid = msg.get("aid", "?")
        bvid = msg.get("bvid", "?")
        err = msg.get("error", "")
        pct = min(100, int(done / max(1, total) * 100))
        self._progress.setValue(pct)
        self._task_detail.setText(f"{done}/{total}")
        self._status_lbl.setText(f"✗ {aid}@{bvid}: {err}")
        self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
        self._append_log(f"  ✗ {aid}@{bvid}: {err}")
        self._refresh_algo_row(0, aid, "✗ 失败", C["danger"], "", "", "")

    def _on_stage_auto_adjust(self, msg):
        """处理自动调整事件：记录调整操作到日志"""
        action = msg.get("action", "")
        message = msg.get("message", "")
        self._append_log(f"  🔧 自动调整: {message}")
        self._status_lbl.setText(f"⚡ {message}")
        self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        if action == "early_stop":
            self._monitor_status.setText("⏹ 自动提前停止")
            self._monitor_status.setStyleSheet(f"color: {C['warning']}; background: transparent;")

    def _on_stage_log(self, msg):
        """处理日志消息：追加到日志面板"""
        self._append_log(msg.get("text", ""))

    def _on_stage_cancelled(self, msg):
        """处理取消事件：显示当前完成进度"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        self._status_lbl.setText(f"已取消 ({done}/{total})")
        self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log(f"⏹ 已取消, {done}/{total} 已完成")
        return True

    def _on_stage_all_done(self, msg):
        """处理全部微调完成事件：输出汇总信息并清理状态"""
        done = msg.get("done", 0)
        elapsed = time.time() - self._train_t0 if self._train_t0 else 0

        conf_summary = ""
        for bvid, results in self._video_results.items():
            for r in results:
                cs, _ = format_confidence(r["confidence"])
                conf_summary += f"\n  {bvid} → {r['aid']}: {cs}"

        self._task_lbl.setText("✅ 微调全部完成")
        self._task_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        self._task_detail.setText(f"{done}/{done}")
        self._status_lbl.setText(f"全部完成: {done} 任务 · {elapsed:.0f}s")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        self._progress.setValue(100)
        self._append_log(f"🏁 批量微调全部完成: {done} 任务, 耗时 {elapsed:.0f}s")
        self._append_log(f"📊 各算法最终置信度:{conf_summary}")
        self.main.set_finetune_status(f"✅ 批量微调完成 ({done})")
        self._last_finetune_count = done
        return True

    def _cleanup_training(self):
        """微调结束后的清理工作：刷新模型状态并触发完成回调"""
        super()._cleanup_training()
        try:
            self.main._refresh_model_status()
        except Exception as e:
            logger.debug("忽略异常: %s", e)
        # 微调完成自动回调
        n = getattr(self, "_last_finetune_count", 0)
        if n > 0:
            try:
                self.main._on_training_completed("微调", n)
            except Exception as e:
                logger.debug("忽略异常: %s", e)

    # ══════════════════════════════════════════════
    # 训练质量监控
    # ══════════════════════════════════════════════

    def _on_monitor_changed(self):
        """记录训练质量变化日志，包含 LR 调整信息"""
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

                # 显示累积 LR 调整信息
                factor = self._algo_lr_factors.get(self._current_aid, 1.0)
                if factor != 1.0:
                    base_lr = 0.001
                    cur_lr = base_lr * factor
                    self._append_log(
                        f"  📐 当前有效学习率: {cur_lr:.6f} (基础 {base_lr} × {factor:.2f}) — 自动调整已应用于后续训练"
                    )

    # ══════════════════════════════════════════════
    # 图表（使用基类 _update_chart / _clear_chart，
    # 但重写 _get_chart_series 以按当前视频过滤）
    # ══════════════════════════════════════════════

    def _get_chart_series(self):
        """仅显示当前视频的 Loss 曲线"""
        current_algos = set(d["algo"] for d in self._loss_history if d.get("bvid") == self._current_bvid)
        if not current_algos:
            current_algos = set(d["algo"] for d in self._loss_history)
        return [(a, [d for d in self._loss_history if d["algo"] == a]) for a in sorted(current_algos)]
