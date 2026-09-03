"""
中间详情面板模块 - PyQt6 版

QWidget + QTabWidget 标签页切换 + ChartWidget 图表
涵盖视频详情头、统计栏、播放趋势图、详细数据、互动率、弹幕
"""

import threading
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTextEdit, QRadioButton, QLineEdit,
    QScrollArea, QCheckBox, QDialog, QProgressBar, QSizePolicy,
    QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import (
    QFont, QTextCharFormat, QColor, QTextCursor, QPixmap, QMouseEvent,
)

from ui.theme import C
from ui.helpers import (
    FONT, FONT_SM, FONT_BOLD, FONT_MONO, FONT_MONO_LG,
    FONT_TITLE, FONT_CAPTION, SPACE_MD,
    THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS, fmt_num,
)
from ui.widgets import SectionHeader, EmptyState, WaveDivider
from ui import lty_voice
from ui.chart import ChartWidget
from ui.detail_tabs import _RatioDanmakuMixin
from ui.invoker import invoke
from utils.weekly_score import calculate_from_dict as _calc_ws
from utils.yearly_score import calculate_yearly_from_dict as _calc_ys
from utils.update_checker import _confirm_risky


class FinetuneDialog(QDialog):
    """微调对话框"""

    def __init__(self, gui, bvid, algos):
        super().__init__(gui)
        self.gui = gui
        self.bvid = bvid
        self.algos: list = algos or []
        self.setWindowTitle(f"♪ 微调 — {bvid}")
        self.setMinimumSize(480, 400)
        self.setModal(True)
        self.setStyleSheet(f"background-color: {C['bg_base']};")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel(f"想在 {self.bvid} 上微调哪些算法呢?天依陪你选 ♪")
        title.setStyleSheet(f"color: {C['text_1']}; font-size: 12pt; font-weight: bold; padding-bottom: 6px;")
        layout.addWidget(title)

        # Algorithm checklist
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background-color: {C['bg_surface']}; border: none; }}
        """)
        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {C['bg_surface']};")
        clayout = QVBoxLayout(scroll_content)
        clayout.setContentsMargins(4, 4, 4, 4)
        clayout.setSpacing(2)

        self._algo_checks = {}
        for a in sorted(self.algos, key=lambda x: x["name"]):
            cb = QCheckBox(f"{a['name']} ({a['algorithm_id']})")
            cb.setChecked(True)
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {C['text_1']}; font-size: 10pt; padding: 2px; }}
                QCheckBox::indicator {{ width: 16px; height: 16px; }}
            """)
            clayout.addWidget(cb)
            self._algo_checks[a["algorithm_id"]] = cb
        clayout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # Params
        param_h = QHBoxLayout()
        param_h.setSpacing(16)

        param_h.addWidget(self._make_param_label("Epochs:"))
        self._epoch_input = QLineEdit("5")
        self._epoch_input.setFixedWidth(60)
        self._epoch_input.setStyleSheet(f"""
            QLineEdit {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
            font-family: Consolas; border: 1px solid {C['border']}; padding: 2px 4px; }}
        """)
        param_h.addWidget(self._epoch_input)

        param_h.addWidget(self._make_param_label("Batch:"))
        self._batch_input = QLineEdit("16")
        self._batch_input.setFixedWidth(60)
        self._batch_input.setStyleSheet(self._epoch_input.styleSheet())
        param_h.addWidget(self._batch_input)
        param_h.addStretch()
        layout.addLayout(param_h)

        # Status
        self._status_lbl = QLabel("天依准备好了 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 10pt;")
        layout.addWidget(self._status_lbl)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(6)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar {{ background-color: {C['bg_elevated']}; border: none; }}
            QProgressBar::chunk {{ background-color: {C['accent']}; }}
        """)
        layout.addWidget(self._progress)

        # Buttons
        btn_h = QHBoxLayout()
        self._start_btn = QPushButton("开始微调 ♪")
        self._start_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {C['accent']}; color: white;
            border: none; padding: 6px 16px; font-size: 10pt; }}
            QPushButton:hover {{ background-color: {C['accent_hover']}; }}
            QPushButton:disabled {{ background-color: {C['bg_elevated']}; color: {C['text_3']}; }}
        """)
        self._start_btn.clicked.connect(self._run)
        btn_h.addWidget(self._start_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
            border: none; padding: 6px 16px; font-size: 10pt; }}
            QPushButton:hover {{ background-color: {C['bg_hover']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_h.addWidget(cancel_btn)
        btn_h.addStretch()
        layout.addLayout(btn_h)

    def _make_param_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt;")
        return lbl

    def _run(self):
        """启动微调"""
        from PyQt6.QtWidgets import QMessageBox

        selected = [aid for aid, cb in self._algo_checks.items() if cb.isChecked()]
        if not selected:
            QMessageBox.information(self, "♪ 提示", "至少选一个算法哦,不然天依不知道练哪首 ♪")
            return
        if getattr(self, "_running", False):
            QMessageBox.information(self, "♪ 提示", "微调正在进行中呢…天依正唱着歌练习,稍等一下下哦 ♪")
            return

        try:
            epochs = max(1, int(self._epoch_input.text()))
        except ValueError:
            epochs = 5
        try:
            batch = max(1, int(self._batch_input.text()))
        except ValueError:
            batch = 16

        self._start_btn.setEnabled(False)
        self._start_btn.setText("微调中…♪")
        self._running = True  # 防止重复启动

        def _worker():
            from algorithms.training.trainer import ModelTrainer

            trainer = ModelTrainer()
            total = len(selected)
            self.gui.set_finetune_status(f"◎ 天依正在微调 {self.bvid} …")
            for i, aid in enumerate(selected):
                msg = f"[{i + 1}/{total}] 微调 {aid}…"
                gui_msg = f"◎ 天依在微调 {self.bvid}: [{i + 1}/{total}] {aid}"
                invoke(lambda m=msg: self._status_lbl.setText(m))
                invoke(lambda p=(i + 0.5) / total: self._progress.setValue(int(p * 100)))
                invoke(lambda m=gui_msg: self.gui.set_finetune_status(m))
                try:
                    version = trainer.finetune_for_video(
                        algo_id=aid, bvid=self.bvid, epochs=epochs, batch_size=batch,
                    )
                    msg = f"✓ {aid} → {version[:12]}"
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).debug("微调 %s 失败: %s", aid, e)
                    msg = f"✗ {aid}: 呜…出错了,天依已悄悄记到日志里啦"
                invoke(lambda m=msg: self._status_lbl.setText(m))
            invoke(lambda: self._status_lbl.setText(f"✓ 微调完成啦!♪ ({total} 个算法)"))
            invoke(lambda: self._progress.setValue(100))
            invoke(lambda: self._start_btn.setText("完成 ♪"))
            invoke(lambda: self._start_btn.setEnabled(True))
            invoke(lambda: self.gui.set_finetune_status(f"✓ 微调 {self.bvid} 完成啦 ({total})♪"))
            invoke(lambda: setattr(self, "_running", False))

        threading.Thread(target=_worker, daemon=True).start()


class DetailPanel(_RatioDanmakuMixin):
    """中间详情面板 — PyQt6 版"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._stat_labels = {}
        self._current_tab_name = "↗ 播放量趋势"
        self._chart_mode = "step"  # step | delta | full
        self._chart_max_points = 20
        self._rendered_modes = set()
        self._chart_fingerprint = None
        self._detail_text_fp = None
        self._header_bvid = None  # 缓存当前 header 对应的 bvid，避免重复构建
        self._header_video = None  # 缓存当前 header 对应的 video 对象（身份校验，防陈旧缓存）

        self._build()

    def _build(self):
        """构建中间面板"""
        p = self._parent
        self.frame = QWidget(p)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video detail header
        self._detail_header = QWidget()
        self._detail_header.setStyleSheet(f"background-color: {C['bg_surface']};")
        self._detail_header.setFixedHeight(80)
        layout.addWidget(self._detail_header)

        # 天依蓝水波分隔线 (header ↔ 统计栏)
        layout.addWidget(WaveDivider())

        self._build_header_empty()

        # Stat bar
        self._stat_bar = QWidget()
        self._stat_bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        layout.addWidget(self._stat_bar)

        # 天依蓝水波分隔线 (统计栏 ↔ 标签页)
        layout.addWidget(WaveDivider())

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {C['bg_base']};
                border: none;
            }}
            QTabBar::tab {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                padding: 8px 14px;
                border: none;
                font-size: 10pt;
            }}
            QTabBar::tab:selected {{
                color: {C['lty_blue_deep']};
                border-bottom: 2px solid {C['lty_blue']};
            }}
            QTabBar::tab:hover {{
                color: {C['text_1']};
            }}
        """)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Tab 0: Chart
        self._chart_tab = QWidget()
        ct_layout = QVBoxLayout(self._chart_tab)
        ct_layout.setContentsMargins(16, 10, 16, 12)
        ct_layout.setSpacing(8)

        # Chart control bar
        ctrl_bar = QWidget()
        ctrl_bar.setStyleSheet(f"background-color: {C['bg_base']};")
        ctrl_h = QHBoxLayout(ctrl_bar)
        ctrl_h.setContentsMargins(0, 0, 0, 0)
        ctrl_h.setSpacing(6)

        self._radio_step = QRadioButton("新增")
        self._radio_delta = QRadioButton("增量")
        self._radio_full = QRadioButton("全量")
        for rb in (self._radio_step, self._radio_delta, self._radio_full):
            rb.setStyleSheet(f"""
                QRadioButton {{ color: {C['text_1']}; font-size: 10pt; }}
                QRadioButton::indicator {{ width: 14px; height: 14px; }}
            """)
        self._radio_step.setChecked(True)
        self._radio_step.toggled.connect(lambda checked: self._on_chart_mode_change() if checked else None)
        self._radio_delta.toggled.connect(lambda checked: self._on_chart_mode_change() if checked else None)
        self._radio_full.toggled.connect(lambda checked: self._on_chart_mode_change() if checked else None)
        ctrl_h.addWidget(self._radio_step)
        ctrl_h.addWidget(self._radio_delta)
        ctrl_h.addWidget(self._radio_full)

        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet(f"background-color: {C['border_sub']}; max-width: 1px;")
        vsep.setFixedWidth(1)
        vsep.setFixedHeight(14)
        ctrl_h.addWidget(vsep)

        ctrl_h.addWidget(self._mk_label("显示"))
        self._pts_input = QLineEdit("20")
        self._pts_input.setFixedWidth(40)
        self._pts_input.setStyleSheet(f"""
            QLineEdit {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
            font-family: Consolas; border: 1px solid {C['border']}; padding: 1px 4px; }}
        """)
        ctrl_h.addWidget(self._pts_input)
        ctrl_h.addWidget(self._mk_label("点"))

        self._render_btn = QPushButton("⟳ 渲染")
        self._render_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {C['bg_elevated']}; color: {C['accent']};
            border: none; padding: 2px 8px; font-size: 10pt; }}
            QPushButton:hover {{ background-color: {C['bg_hover']}; }}
        """)
        self._render_btn.clicked.connect(self._manual_render_chart)
        ctrl_h.addWidget(self._render_btn)

        self._chart_stat_lbl = self._mk_label("")
        self._chart_stat_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 10pt;")
        ctrl_h.addWidget(self._chart_stat_lbl, 1, Qt.AlignmentFlag.AlignRight)

        ct_layout.addWidget(ctrl_bar)

        # Chart widget
        self._chart_widget = ChartWidget()
        ct_layout.addWidget(self._chart_widget, 1)

        # 图表空状态 (未选中/无数据时覆盖显示)
        self._chart_empty = EmptyState(lty_voice.no_data())
        self._chart_empty.setVisible(False)
        ct_layout.addWidget(self._chart_empty, 1)

        self._tabs.addTab(self._chart_tab, "↗ 播放量趋势")

        # Tab 1: Detail text
        self._detail_tab = QWidget()
        dt_layout = QVBoxLayout(self._detail_tab)
        dt_layout.setContentsMargins(16, 12, 16, 12)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                font-family: Consolas; font-size: 10pt;
                border: none; padding: 10px 12px;
            }}
        """)
        dt_layout.addWidget(self._detail_text)
        self._tabs.addTab(self._detail_tab, "☰ 详细数据")

        # Tab 2: Ratio
        self._ratio_tab = QWidget()
        self._ratio_layout = QVBoxLayout(self._ratio_tab)
        self._ratio_layout.setContentsMargins(16, 12, 16, 12)
        self._ratio_layout.setSpacing(6)
        self._tabs.addTab(self._ratio_tab, "⟳ 互动率")

        # Tab 3: Danmaku
        self._danmaku_tab = QWidget()
        dm_layout = QVBoxLayout(self._danmaku_tab)
        dm_layout.setContentsMargins(0, 0, 0, 0)
        dm_layout.setSpacing(0)

        dm_top = QWidget()
        dm_top.setStyleSheet(f"background-color: {C['bg_surface']};")
        dm_top_h = QHBoxLayout(dm_top)
        dm_top_h.setContentsMargins(16, 10, 16, 4)

        dm_title = SectionHeader("实时弹幕 ♪")
        dm_title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        dm_top_h.addWidget(dm_title)

        self._dm_count_lbl = QLabel("")
        self._dm_count_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        dm_top_h.addWidget(self._dm_count_lbl)

        dm_top_h.addStretch()

        self._dm_refresh_btn = QPushButton("⟳ 刷新")
        self._dm_refresh_btn.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; color: {C['accent']};
            border: none; font-size: 10pt; }}
            QPushButton:hover {{ color: {C['text_1']}; }}
        """)
        self._dm_refresh_btn.clicked.connect(self._refresh_danmaku_display)
        dm_top_h.addWidget(self._dm_refresh_btn)

        dm_layout.addWidget(dm_top)

        self._dm_text = QTextEdit()
        self._dm_text.setReadOnly(True)
        self._dm_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['canvas_bg']}; color: {C['canvas_text']};
                font-family: "Microsoft YaHei UI"; font-size: 10pt;
                border: none; padding: 8px 12px;
            }}
        """)
        dm_layout.addWidget(self._dm_text, 1)

        # 弹幕空状态 (无记录时显示)
        self._dm_empty = EmptyState(lty_voice.danmaku_empty() + " 监控过程中天依会自动收好哦")
        self._dm_empty.setVisible(False)
        dm_layout.addWidget(self._dm_empty, 1)

        self._tabs.addTab(self._danmaku_tab, "♬ 弹幕")

        layout.addWidget(self._tabs, 1)

        self._rebuild_stat_bar({})

        # 初始无选中视频: 图表显示空状态
        self._chart_empty.setVisible(True)
        self._chart_widget.setVisible(False)

    def _mk_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt; background-color: transparent;")
        return lbl

    # ── Header ──────────────────────────────────

    def _build_header_empty(self):
        """空状态头部"""
        self._clear_header()
        empty = EmptyState(lty_voice.empty("选择视频"), self._detail_header)
        layout = self._detail_header.layout()
        if layout is None:
            layout = QHBoxLayout(self._detail_header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(empty)

    def _clear_header(self):
        """清空 header 布局中的全部子 widget，保留布局对象以复用"""
        self._header_bvid = None  # 重置 header 缓存
        self._header_video = None
        layout = self._detail_header.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item is not None:
                    w = item.widget()
                    if w:
                        w.deleteLater()

    def build_header(self, video):
        """构建视频详情头部"""
        bvid = video.get("bvid", "")
        if video is self._header_video:
            return  # 同一视频对象，跳过销毁+重建（身份校验防止缓存返回旧 dict）
        self._clear_header()
        self._header_bvid = bvid
        self._header_video = video
        title = video.get("title", "未知标题")
        author = video.get("author", "未知UP主")
        dur_sec = video.get("duration", 0)
        pub_ts = video.get("pubdate", 0)
        dur_str = f"{dur_sec // 60}:{dur_sec % 60:02d}" if dur_sec else "—"
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d") if pub_ts else "—"

        layout = self._detail_header.layout()
        if layout is None:
            layout = QHBoxLayout(self._detail_header)
        layout.setContentsMargins(14, 10, 14, 10)

        info = QWidget()
        info.setStyleSheet(f"background-color: {C['bg_surface']};")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)

        # Title
        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setFont(FONT_TITLE)
        title_lbl.setStyleSheet(f"color: {C['text_1']}; background-color: transparent;")
        info_layout.addWidget(title_lbl)

        # Meta row
        meta = QWidget()
        meta.setStyleSheet(f"background-color: {C['bg_surface']};")
        meta_h = QHBoxLayout(meta)
        meta_h.setContentsMargins(0, 0, 0, 0)
        meta_h.setSpacing(14)

        for icon, val in [("☺", author), ("⏱", dur_str), ("▦", pub_str)]:
            tf = QWidget()
            tf.setStyleSheet(f"background-color: {C['bg_surface']};")
            tf_h = QHBoxLayout(tf)
            tf_h.setContentsMargins(0, 0, 0, 0)
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt;")
            tf_h.addWidget(icon_lbl)
            val_lbl = QLabel(" " + val)
            val_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt;")
            tf_h.addWidget(val_lbl)
            meta_h.addWidget(tf)

        # BV label (clickable)
        bv_lbl = QPushButton(bvid)
        bv_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        bv_lbl.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['bg_elevated']}; color: {C['text_3']};
                font-family: Consolas; font-size: 10pt; padding: 2px 6px;
                border: none;
            }}
            QPushButton:hover {{ color: {C['accent']}; }}
        """)
        bv_lbl.clicked.connect(lambda: self.gui._copy_bvid(bvid))
        meta_h.addWidget(bv_lbl)
        meta_h.addStretch()
        info_layout.addWidget(meta)

        # Finetune bar
        ft_bar = QWidget()
        ft_bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        ft_h = QHBoxLayout(ft_bar)
        ft_h.setContentsMargins(0, 0, 0, 0)
        ft_h.setSpacing(6)

        self._finetune_btn = QPushButton("◎ 微调此视频 ♪")
        self._finetune_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['accent']}; color: white;
                border: none; padding: 4px 10px; font-size: 9pt;
            }}
            QPushButton:hover {{ background-color: {C['accent_hover']}; }}
        """)
        self._finetune_btn.clicked.connect(
            lambda: _confirm_risky("微调视频模型") and self._open_finetune_dialog(bvid)
        )
        ft_h.addWidget(self._finetune_btn)

        self._finetune_status = QLabel("")
        self._finetune_status.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        ft_h.addWidget(self._finetune_status, 1)

        info_layout.addWidget(ft_bar)
        layout.addWidget(info, 1)
        self._detail_header.setFixedHeight(info.sizeHint().height() + 20)

    def _open_finetune_dialog(self, bvid: str):
        """打开微调对话框"""
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        algos = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            ckpt = CheckpointManager(aid)
            if ckpt.has_checkpoint():
                algos.append({"algorithm_id": aid, "name": getattr(algo, "name", aid)})

        if not algos:
            QMessageBox.information(self.frame, "♪ 提示", "呜…还没有已训练的深度学习算法呢,先训练一下,天依才能唱得更准哦 ♪")
            return

        dlg = FinetuneDialog(self.gui, bvid, algos)
        dlg.exec()

    # ── Stat Bar ─────────────────────────────────

    def _rebuild_stat_bar(self, video):
        """构建/重建统计栏"""
        # 已构建且无有效视频数据时跳过重建（由 update_stat_bar 负责后续更新）
        if self._stat_labels and not video:
            return
        # Clear existing widgets, keep layout object for reuse
        old_layout = self._stat_bar.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item is not None:
                    w = item.widget()
                    if w:
                        w.deleteLater()

        layout = self._stat_bar.layout()
        if layout is None:
            layout = QHBoxLayout(self._stat_bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(SPACE_MD)

        self._stat_labels = {}
        fields = [
            ("播放量", "view_count", C["lty_blue"]),
            ("点赞", "like_count", C["text_1"]),
            ("投币", "coin_count", C["text_1"]),
            ("收藏", "favorite_count", C["text_1"]),
            ("弹幕", "danmaku_count", C["text_1"]),
            ("评论", "reply_count", C["text_1"]),
            ("在线人数", "_online_viewers", C["accent"]),
            ("点赞率", "_like_rate", C["success"]),
            ("周刊分数", "_weekly_score", C["accent"]),
            ("年刊分数", "_yearly_score", C["warning"]),
        ]

        for label, key, color in fields:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {C['bg_elevated']};
                    border: 1px solid {C['border_sub']};
                    border-radius: {C['radius_sm']}px;
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(6, 4, 6, 4)
            card_layout.setSpacing(0)

            lbl = QLabel(label)
            lbl.setFont(FONT_CAPTION)
            lbl.setStyleSheet(f"color: {C['text_3']}; background-color: transparent;")
            card_layout.addWidget(lbl)

            # Value
            if key == "_like_rate":
                views = video.get("view_count", 1) or 1
                val_text = f"{video.get('like_count', 0) / views * 100:.2f}%"
            elif key == "_weekly_score":
                val_text = self._calc_weekly_score_text(video)
            elif key == "_yearly_score":
                val_text = self._calc_yearly_score_text(video)
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val_text = f"{fmt_num(total)}" if total > 0 else "—"
            else:
                val_text = fmt_num(video.get(key, 0)) if video else "—"

            val_lbl = QLabel(val_text)
            val_lbl.setFont(FONT_MONO_LG)
            val_lbl.setStyleSheet(f"color: {color}; background-color: transparent;")
            card_layout.addWidget(val_lbl)

            delta_lbl = QLabel("")
            delta_lbl.setFont(FONT_CAPTION)
            delta_lbl.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            card_layout.addWidget(delta_lbl)

            layout.addWidget(card, 1)
            self._stat_labels[key] = (val_lbl, delta_lbl)

    def update_stat_bar(self, video):
        """更新统计栏数据"""
        fields = [
            ("view_count", C["bilibili"]),
            ("like_count", C["text_1"]),
            ("coin_count", C["text_1"]),
            ("favorite_count", C["text_1"]),
            ("danmaku_count", C["text_1"]),
            ("reply_count", C["text_1"]),
            ("_online_viewers", C["accent"]),
            ("_like_rate", C["success"]),
            ("_weekly_score", C["accent"]),
            ("_yearly_score", C["warning"]),
        ]
        views = video.get("view_count", 1) or 1
        for key, color in fields:
            pair = self._stat_labels.get(key)
            if not pair:
                continue
            val_lbl, _ = pair
            if key == "_like_rate":
                val_lbl.setText(f"{video.get('like_count', 0) / views * 100:.2f}%")
            elif key == "_weekly_score":
                val_lbl.setText(self._calc_weekly_score_text(video))
            elif key == "_yearly_score":
                val_lbl.setText(self._calc_yearly_score_text(video))
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val_lbl.setText(fmt_num(total) if total > 0 else "—")
            else:
                val_lbl.setText(fmt_num(video.get(key, 0)))

    # ── Tabs ─────────────────────────────────────

    def _on_tab_changed(self, index):
        """标签页切换"""
        name = self._tabs.tabText(index)
        self._current_tab_name = name
        if name == "↗ 播放量趋势":
            if self._chart_mode == "step":
                self._auto_render_chart()
            else:
                self._rendered_modes.discard(self._chart_mode)
        elif name == "☰ 详细数据":
            video = self._get_selected_video()
            if video:
                self._fill_detail_text(video)
        elif name == "⟳ 互动率":
            video = self._get_selected_video()
            if video:
                self._fill_ratio_frame(video)
        elif name == "♬ 弹幕":
            self._refresh_danmaku_display()

    def _get_selected_video(self):
        """获取当前选中视频（每次现查，避免缓存指向已删除/重建的旧 dict）"""
        bvid = self.gui.selected_bvid
        if not bvid:
            return None
        return next(
            (v for v in self.gui.monitored_videos if v.get("bvid") == bvid), None
        )

    # ── Chart Rendering ─────────────────────────

    def _on_chart_mode_change(self):
        """模式切换"""
        if self._radio_step.isChecked():
            mode = "step"
        elif self._radio_delta.isChecked():
            mode = "delta"
        else:
            mode = "full"

        self._chart_mode = mode
        if mode == "step":
            self._render_btn.setText("⟳ 渲染")
            self._render_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {C['bg_elevated']}; color: {C['accent']};
                border: none; padding: 2px 8px; font-size: 10pt; }}
                QPushButton:hover {{ background-color: {C['bg_hover']}; }}
            """)
            self._chart_stat_lbl.setText("自动刷新 ✓ ♪")
            self._chart_stat_lbl.setStyleSheet(f"color: {C['success']}; font-size: 10pt;")
            self._auto_render_chart()
        else:
            hint = "增量" if mode == "delta" else "全量"
            self._render_btn.setText(f"▶ 渲染{hint}")
            self._render_btn.setStyleSheet(f"""
                QPushButton {{ background-color: {C['bg_elevated']}; color: {C['bilibili']};
                border: none; padding: 2px 8px; font-size: 10pt; }}
                QPushButton:hover {{ background-color: {C['bg_hover']}; }}
            """)
            self._chart_stat_lbl.setText("手动渲染 ♪")
            self._chart_stat_lbl.setStyleSheet(f"color: {C['warning']}; font-size: 10pt;")
            self._rendered_modes.discard(mode)

    def _auto_render_chart(self):
        """自动渲染"""
        mode = self._chart_mode
        if mode != "step" and mode not in self._rendered_modes:
            return
        self._do_render_chart()

    def _manual_render_chart(self):
        """手动渲染"""
        self._do_render_chart()

    def _do_render_chart(self):
        """执行图表渲染"""
        if not self.gui.selected_bvid:
            self._chart_empty.setVisible(True)
            self._chart_widget.setVisible(False)
            return
        video = next((v for v in self.gui.monitored_videos if v.get("bvid") == self.gui.selected_bvid), None)
        if not video:
            self._chart_empty.setVisible(True)
            self._chart_widget.setVisible(False)
            return
        try:
            points = max(2, int(self._pts_input.text()))
        except ValueError:
            points = 20
        self._chart_max_points = points
        pred = self.gui.prediction_results.get(self.gui.selected_bvid)

        history = self.gui.history_data.get(self.gui.selected_bvid, [])
        pred_val = pred.get("prediction", 0) if pred else 0
        fp = (self.gui.selected_bvid, video.get("view_count", 0), len(history), pred_val, self._chart_mode)
        if fp == self._chart_fingerprint:
            return
        self._chart_fingerprint = fp

        self._chart_widget.update_chart(
            self.gui.history_data, self.gui.selected_bvid, video,
            mode=self._chart_mode, max_points=points, prediction=pred,
        )
        self._rendered_modes.add(self._chart_mode)
        self._chart_empty.setVisible(False)
        self._chart_widget.setVisible(True)

    @property
    def chart_mode(self):
        return self._chart_mode

    # ── Detail Text ─────────────────────────────

    def _fill_detail_text(self, video):
        """填充详细数据"""
        # Fingerprint check
        fp_fields = (
            video.get("view_count", 0), video.get("like_count", 0),
            video.get("coin_count", 0), video.get("favorite_count", 0),
            video.get("share_count", 0), video.get("danmaku_count", 0),
            video.get("reply_count", 0), video.get("viewers_total", 0),
            video.get("title", ""), video.get("author", ""),
        )
        new_fp = hash(fp_fields)
        if new_fp == self._detail_text_fp:
            return
        self._detail_text_fp = new_fp

        bvid = video.get("bvid", "")
        title = video.get("title", "N/A")
        author = video.get("author", "未知")
        views = video.get("view_count", 0)
        pub_ts = video.get("pubdate", 0)
        dur = video.get("duration", 0)
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M") if pub_ts else "—"
        dur_str = f"{dur // 60}:{dur % 60:02d}" if dur else "—"

        lines = []
        def add(text, style=""):
            lines.append((text, style))

        add("=== 视频信息 ===", "head")
        add(f"BV号    {bvid}", "mono")
        add(f"标题    {title}", "mono")
        add(f"UP主    {author}", "mono")
        add(f"时长    {dur_str}", "mono")
        add(f"发布    {pub_str}", "mono")
        add("")
        add("=== 播放数据 ===", "head")
        add(f"播放量  {fmt_num(views)}", "mono_b")
        add(f"点赞    {fmt_num(video.get('like_count', 0))}", "mono")
        add(f"投币    {fmt_num(video.get('coin_count', 0))}", "mono")
        add(f"分享    {fmt_num(video.get('share_count', 0))}", "mono")
        add(f"收藏    {fmt_num(video.get('favorite_count', 0))}", "mono")
        add(f"弹幕    {fmt_num(video.get('danmaku_count', 0))}", "mono")
        add(f"评论    {fmt_num(video.get('reply_count', 0))}", "mono")
        add("")
        add("=== 互动率 ===", "head")
        add(f"点赞率  {video.get('like_count', 0) / max(views, 1) * 100:.2f}%", "mono")
        add(f"投币率  {video.get('coin_count', 0) / max(views, 1) * 100:.2f}%", "mono")
        add(f"收藏率  {video.get('favorite_count', 0) / max(views, 1) * 100:.2f}%", "mono")
        add("")
        add("=== 在线人数 ===", "head")
        viewers_total = video.get("viewers_total", 0)
        if viewers_total > 0:
            viewers_raw = video.get("viewers_total_raw", "")
            add(f"总在线  {fmt_num(viewers_total)}  ({viewers_raw})", "mono_accent")
            add(f"Web端   {fmt_num(video.get('viewers_web', 0))}", "mono")
            add(f"APP端   {fmt_num(video.get('viewers_app', 0))}", "mono")
        else:
            add("暂无在线人数数据", "mono")
        add("")
        add("=== 阈值进度 ===", "head")
        for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
            p = min(100, views / t * 100)
            g = t - views
            if g > 0:
                add(f"{name}  {p:.1f}%  (还差 {fmt_num(g)})", "mono")
            else:
                add(f"{name}  已达成 ✓", "mono_ok")

        # Build HTML
        html_parts = ["<pre style='font-family: Consolas; font-size: 10pt; line-height: 1.4; margin: 0; white-space: pre-wrap;'>"]
        style_map = {
            "head": f"color: {C['bilibili']}; font-weight: bold;",
            "mono": f"color: {C['text_1']};",
            "mono_b": f"color: {C['bilibili']}; font-weight: bold;",
            "mono_ok": f"color: {C['success']};",
            "mono_accent": f"color: {C['accent']}; font-weight: bold;",
        }
        for text, style in lines:
            css = style_map.get(style, f"color: {C['text_1']};")
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_parts.append(f"<span style='{css}'>{escaped}</span>\n")
        html_parts.append("</pre>")

        # Weekly score section
        ws = self._calc_weekly_score(video)
        if ws:
            extra = [
                ("", ""),
                ("=== 周刊分数 ===", "head"),
                (f"最终得点  {ws.total_score:>10,.2f}", "mono_accent"),
                ("", ""),
                (f"播放得点  {ws.view_score:>10,.2f}  (基础 {ws.base_view_score:,.0f} × 修正D {ws.correction_d:.4f})", "mono"),
                (f"互动得点  {ws.interaction_score:>10,.2f}  (修正A {ws.correction_a:.4f})", "mono"),
                (f"收藏得点  {ws.favorite_score:>10,.2f}  ({video.get('favorite_count', 0):,} × 修正B {ws.correction_b:.4f})", "mono"),
                (f"硬币得点  {ws.coin_score:>10,.2f}  ({video.get('coin_count', 0):,} × 修正C {ws.correction_c:.4f})", "mono"),
                (f"点赞得点  {ws.like_score:>10,.2f}", "mono"),
            ]
            for text, style in extra:
                css = style_map.get(style, f"color: {C['text_1']};")
                escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(f"<span style='{css}'>{escaped}</span>\n")

        # Yearly score section
        ys = self._calc_yearly_score(video)
        if ys:
            extra = [
                ("", ""),
                ("=== 年刊分数 ===", "head"),
                (f"最终得点  {ys.total_score:>10,.2f}", "mono_accent"),
                ("", ""),
                (f"播放得点  {ys.view_score:>10,.2f}", "mono"),
                (f"互动得点  {ys.interaction_score:>10,.2f}  (修正A {ys.correction_a:.4f})", "mono"),
                (f"收藏得点  {ys.favorite_score:>10,.2f}  ({video.get('favorite_count', 0):,} × 修正B {ys.correction_b:.4f})", "mono"),
                (f"硬币得点  {ys.coin_score:>10,.2f}  ({video.get('coin_count', 0):,} × 修正C {ys.correction_c:.4f})", "mono"),
                (f"点赞得点  {ys.like_score:>10,.2f}", "mono"),
            ]
            for text, style in extra:
                css = style_map.get(style, f"color: {C['text_1']};")
                escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(f"<span style='{css}'>{escaped}</span>\n")

        # Historical scores
        if bvid in self.gui.video_dbs:
            history_scores = self.gui.video_dbs[bvid].get_weekly_scores(limit=5)
            if len(history_scores) > 1:
                html_parts.append(f"<span style='{style_map['head']}'>\n=== 历史周刊分数 ===\n</span>")
                for row in history_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    html_parts.append(f"<span style='{style_map['mono']}'>  {ts_str}  {total:>10,.2f}\n</span>")
            yearly_scores = self.gui.video_dbs[bvid].get_yearly_scores(limit=5)
            if len(yearly_scores) > 1:
                html_parts.append(f"<span style='{style_map['head']}'>\n=== 历史年刊分数 ===\n</span>")
                for row in yearly_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    html_parts.append(f"<span style='{style_map['mono']}'>  {ts_str}  {total:>10,.2f}\n</span>")

        html_parts.append("</pre>")
        self._detail_text.setHtml("".join(html_parts))

    def _calc_weekly_score(self, video):
        try:
            return _calc_ws(video)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug("周刊分数计算失败: %s", e)
            return None

    def _calc_weekly_score_text(self, video):
        ws = self._calc_weekly_score(video)
        return f"{ws.total_score:,.0f}" if ws else "—"

    def _calc_yearly_score(self, video):
        try:
            return _calc_ys(video)
        except Exception:
            import logging
            logging.getLogger(__name__).debug("年刊分数计算失败")
            return None

    def _calc_yearly_score_text(self, video):
        ys = self._calc_yearly_score(video)
        return f"{ys.total_score:,.0f}" if ys else "—"

    @property
    def chart_canvas(self):
        return self._chart_widget

    @property
    def current_tab(self):
        return self._current_tab_name
