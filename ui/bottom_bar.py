"""
底部状态栏模块 — PyQt6 版
负责底部操作栏（添加监控、刷新、删除、推送、自动刷新开关）和状态栏信息展示
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QCheckBox,
)
from PyQt6.QtCore import Qt

from ui.theme import C
from ui.helpers import FONT, FONT_CAPTION, SPACE_MD, SPACE_LG
from ui.widgets import WaveDivider


class BottomBar(QWidget):
    """底部操作栏 + 状态栏，包含主要功能按钮和系统状态信息"""

    def __init__(self, root, gui):
        super().__init__(root)
        self.gui = gui
        self._sb_labels = {}  # 状态栏标签字典
        self._build_bottom_bar()
        self._build_status_bar()

    def _build_bottom_bar(self):
        """构建底部操作栏"""
        # 水波分隔线 (洛天依意象)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.addWidget(WaveDivider())

        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        h.setSpacing(SPACE_MD)

        # 「添加监控」主按钮 — 天依蓝强调
        self._add_btn = QPushButton("＋ 添加监控")
        self._add_btn.setProperty("primary", True)
        self._add_btn.setFixedHeight(32)
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['lty_blue']};
                color: #ffffff;
                border: none;
                border-radius: {C['radius_sm']}px;
                padding: 4px 14px;
            }}
            QPushButton:hover {{ background-color: {C['lty_blue_deep']}; }}
            QPushButton:pressed {{ background-color: {C['lty_blue_light']}; }}
        """)
        self._add_btn.clicked.connect(self.gui._add_monitor)
        h.addWidget(self._add_btn)

        # 「立即刷新」按钮
        self._refresh_btn = QPushButton("🔄 立即刷新")
        self._refresh_btn.setFixedHeight(32)
        self._refresh_btn.clicked.connect(self.gui._refresh_data)
        h.addWidget(self._refresh_btn)

        # 「删除监控」按钮
        self._del_btn = QPushButton("🗑 删除监控")
        self._del_btn.setProperty("danger", True)
        self._del_btn.setFixedHeight(32)
        self._del_btn.clicked.connect(self.gui._remove_monitor)
        h.addWidget(self._del_btn)

        # 「撤销删除」按钮
        self._undo_btn = QPushButton("↩ 撤销")
        self._undo_btn.setFixedHeight(32)
        self._undo_btn.setToolTip("撤销最近一次删除 (Ctrl+Z)")
        self._undo_btn.clicked.connect(self.gui._undo_delete)
        self._undo_btn.setVisible(False)
        h.addWidget(self._undo_btn)

        # 「手动推送」按钮
        self._push_btn = QPushButton("📤 手动推送")
        self._push_btn.setProperty("accent", True)
        self._push_btn.setFixedHeight(32)
        self._push_btn.clicked.connect(self.gui._manual_push)
        h.addWidget(self._push_btn)

        h.addStretch()

        # 自动刷新开关（右侧）
        ar_w = QWidget()
        ar_w.setStyleSheet(f"background-color: {C['bg_surface']};")
        ar_h = QHBoxLayout(ar_w)
        ar_h.setContentsMargins(0, 0, 0, 0)
        ar_h.setSpacing(4)

        self._ar_check = QCheckBox("自动刷新")
        self._ar_check.setChecked(True)
        self._ar_check.toggled.connect(self.gui._toggle_auto_refresh)
        self._ar_check.setStyleSheet(f"""
            QCheckBox {{ color: {C['text_2']}; }}
            QCheckBox::indicator {{
                width: 36px; height: 18px;
                border-radius: 9px;
                background-color: {C['bg_hover']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {C['lty_blue']};
            }}
        """)
        ar_h.addWidget(self._ar_check)
        h.addWidget(ar_w)

        self.layout.addWidget(bar)

    def _build_status_bar(self):
        """构建底部状态栏"""
        self.layout.addWidget(WaveDivider())

        bar = QWidget()
        bar.setFixedHeight(22)
        bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(SPACE_LG, 0, SPACE_LG, 0)
        h.setSpacing(SPACE_MD)

        items = [
            ("videos", "监控: 0 个"),
            ("interval", "刷新间隔: —"),
            ("algo", "算法: —"),
            ("alert", ""),
            ("finetune", ""),
            ("last_ref", "上次刷新: —"),
            ("status", "就绪"),
        ]

        for key, text in items:
            lbl = QLabel(text)
            lbl.setFont(FONT_CAPTION)
            lbl.setStyleSheet(f"color: {C['text_3']};")
            if key == "status":
                h.addStretch()
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            else:
                lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(lbl)
            self._sb_labels[key] = lbl

        self.layout.addWidget(bar)

    def update_sb(self, key, text, color=None):
        """更新状态栏标签的文本和颜色"""
        lbl = self._sb_labels.get(key)
        if lbl:
            color = color or C["text_3"]
            lbl.setText(text)
            # 仅在颜色变化时更新样式，避免触发不必要的 QSS 解析
            current_color = getattr(lbl, "_sb_color", None)
            if current_color != color:
                lbl._sb_color = color
                lbl.setStyleSheet(f"color: {color};")

    def show_undo_button(self):
        """显示撤销按钮"""
        self._undo_btn.setVisible(True)

    def hide_undo_button(self):
        """隐藏撤销按钮"""
        self._undo_btn.setVisible(False)

    @property
    def ar_toggle(self):
        """返回自动刷新开关"""
        return self._ar_check
