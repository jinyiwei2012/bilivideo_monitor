"""
微调面板 — 与训练面板同级同显示
支持选择多个视频 + 多个算法，一键启动微调
右侧实时 loss 图表 + 训练质量监控 + 文字日志
自动切换当前训练视频的模型信息与置信度
"""

import logging
from typing import Dict, List

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QProgressBar,
    QFrame,
    QRadioButton,
    QButtonGroup,
)
from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    FONT_MONO,
    loss_to_confidence,
    format_confidence,
    load_algo_confidence,
)
from ui.training_base import BaseTrainingPanel, TrainingMonitor
from ui.scrollable_frame import ScrollableFrame
from ui.finetune_jobs import FinetuneJobsMixin
from ui.finetune_progress import FinetuneProgressMixin
from utils.update_checker import _train

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class FinetunePanel(FinetuneJobsMixin, FinetuneProgressMixin, BaseTrainingPanel):
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
        info_lbl = QLabel("批量微调 ♪ 选好视频和算法,天依就一首一首地微调它们哦")
        info_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        info_layout.addWidget(info_lbl)
        info_layout.addStretch()
        refresh_btn = QPushButton("刷新列表 ♪")
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
        v_title = QLabel("▶ 选择视频 ♪")
        v_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        vhdr_layout.addWidget(v_title)
        vhdr_layout.addStretch()
        self._video_count_lbl = QLabel("")
        self._video_count_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._video_count_lbl.setFont(FONT_SM)
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
        a_title = QLabel("◍ 选择算法（已训练）♪")
        a_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        ahdr_layout.addWidget(a_title)
        ahdr_layout.addStretch()
        self._algo_count_lbl = QLabel("")
        self._algo_count_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._algo_count_lbl.setFont(FONT_SM)
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
        btn_version = QPushButton("✕ 版本管理")
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
        self._task_lbl = QLabel("天依准备好啦 ♪ 选好视频和算法就可以开始微调哦")
        self._task_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._task_lbl.setFont(FONT)
        task_layout.addWidget(self._task_lbl)
        task_layout.addStretch()
        self._task_detail = QLabel("")
        self._task_detail.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._task_detail.setFont(FONT_SM)
        task_layout.addWidget(self._task_detail)
        right_layout.addWidget(task_bar)

        # ── 上半: Loss 图表 ──
        chart_frame = self._build_chart_widgets(right, title="微调 Loss 曲线 ♪")
        right_layout.addWidget(chart_frame, 1)

        # ── 中部: 训练质量监控 ──
        monitor_bar = self._build_monitor_bar(right)
        right_layout.addWidget(monitor_bar)

        # ── 下半: 文字日志 ──
        log_frame = self._build_log_widgets(right, title="微调日志 ♪")
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
        epoch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        epoch_label.setFont(FONT_SM)
        ctrl_layout.addWidget(epoch_label)
        self._epoch_spin = QSpinBox()
        self._epoch_spin.setRange(1, 100)
        self._epoch_spin.setValue(15)
        self._epoch_spin.setFixedWidth(60)
        ctrl_layout.addWidget(self._epoch_spin)

        batch_label = QLabel("Batch:")
        batch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        batch_label.setFont(FONT_SM)
        ctrl_layout.addWidget(batch_label)
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 512)
        self._batch_spin.setValue(16)
        self._batch_spin.setFixedWidth(60)
        ctrl_layout.addWidget(self._batch_spin)

        mode_label = QLabel("模式:")
        mode_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        mode_label.setFont(FONT_SM)
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

        self._train_btn = QPushButton("▶ 开始微调 ♪")
        self._train_btn.clicked.connect(self._on_start)
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

        if _train() != "normal":
            hint_lbl = QLabel("✦ 创建 .enabletraining 文件开启微调 / 完整 devmode 见 README.md")
            hint_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent; font: 8pt;")
            ctrl_layout.addWidget(hint_lbl)

        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        ctrl_layout.addWidget(self._progress, 1)

        self._status_lbl = QLabel("天依准备好啦 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._status_lbl.setFont(FONT_SM)
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

        self._video_count_lbl.setText(f"天依找到了 {len(videos)} 个视频 ♪")
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
        self._algo_count_lbl.setText(f"天依数了数 ♪ {len(algos)} 算法 · 已训练 {trained}")

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
            id_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            id_lbl.setFont(FONT_MONO)
            id_lbl.setFixedWidth(90)
            row_layout.addWidget(id_lbl)

            if a["has_ckpt"]:
                st = f"✓ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 还没训练呢…♪"
                sf = C["text_3"]
            status_lbl = QLabel(st)
            status_lbl.setStyleSheet(f"color: {sf}; background: transparent;")
            status_lbl.setFont(FONT_SM)
            status_lbl.setFixedWidth(80)
            row_layout.addWidget(status_lbl)

            conf = load_algo_confidence(aid)
            conf_text, conf_color = format_confidence(conf)
            conf_lbl = QLabel(conf_text)
            conf_lbl.setStyleSheet(f"color: {conf_color}; background: transparent;")
            conf_lbl.setFont(FONT_SM)
            conf_lbl.setFixedWidth(70)
            row_layout.addWidget(conf_lbl)

            ver_lbl = QLabel(f"v{a['version_count']}")
            ver_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            ver_lbl.setFont(FONT_SM)
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
            import logging

            logging.getLogger(__name__).debug("微调置信度计算失败: %s", e)
            return 0.0

    def _on_manage_versions(self):
        """打开版本管理对话框（复用训练面板的完整实现）"""
        if hasattr(self.main, "training_panel") and self.main.training_panel is not None:
            self.main.training_panel._on_manage_versions()

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
                prefix = "◉ 训练质量检测" if cur_status != last_status else "⟳ 持续监测"
                self._append_log(f"{prefix}: {cur_status}")
                for s in self._monitor.suggestions:
                    self._append_log(f"  ✦ {s}")

                # 显示累积 LR 调整信息
                factor = self._algo_lr_factors.get(self._current_aid, 1.0)
                if factor != 1.0:
                    base_lr = 0.001
                    cur_lr = base_lr * factor
                    self._append_log(
                        f"  ◫ 当前有效学习率: {cur_lr:.6f} (基础 {base_lr} × {factor:.2f}) — 自动调整已应用于后续训练"
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
