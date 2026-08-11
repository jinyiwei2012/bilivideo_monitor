"""
监控参数设置 — PyQt6 版
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QFrame,
)
from PyQt6.QtCore import Qt
from ui.theme import C
from ui.helpers import FONT_SM, auto_threshold_name


class SettingsMonitorMixin:
    """Monitor parameter settings tab."""

    def _build_monitor_tab(self, nb):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        nb.addTab(page, "  监控参数  ")

        sec = self._section(page, "基础参数")
        # Re-create spin_field as an inline QSpinBox
        row = QWidget(sec)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel("最大监控数")
        lbl.setStyleSheet(f"color: {C['text_2']};")
        lbl.setFixedWidth(130)
        rl.addWidget(lbl)
        self.max_monitors = QSpinBox()
        self.max_monitors.setRange(10, 500)
        self.max_monitors.setValue(self._cfg.get("monitor", {}).get("max_monitor_count", 100))
        rl.addWidget(self.max_monitors)
        rl.addStretch()
        sec.layout().addWidget(row)

        th_sec = self._section(page, "播放量阈值")
        hint = QLabel("每个阈值代表一个里程碑，达到时触发推送提醒")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        th_sec.layout().addWidget(hint)

        th_list_frame = QWidget()
        th_list_frame.setLayout(QVBoxLayout())
        th_list_frame.layout().setContentsMargins(0, 0, 0, 0)
        th_list_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        th_sec.layout().addWidget(th_list_frame)

        self._thresh_rows = []

        raw = self._cfg.get("prediction", {}).get("thresholds", [])
        if raw and isinstance(raw[0], (list, tuple)):
            th_data = [(int(v), str(n)) for v, n in raw]
        else:
            th_data = (
                [(int(v), auto_threshold_name(v)) for v in raw]
                if raw
                else [(100000, "10万"), (1000000, "100万"), (10000000, "1000万")]
            )

        for v, n in sorted(th_data, key=lambda x: x[0]):
            self._add_threshold_row(th_list_frame, v, n)

        add_btn = QPushButton("+ 添加阈值")
        add_btn.clicked.connect(lambda: self._add_threshold_row(th_list_frame))
        th_sec.layout().addWidget(add_btn)


    def _add_threshold_row(self, parent, value=100000, name=""):
        row = QWidget(parent)
        row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)

        v_spin = QSpinBox()
        v_spin.setRange(1000, 999999999)
        v_spin.setValue(int(value))
        rl.addWidget(QLabel("播放量:"))
        rl.addWidget(v_spin)

        n_entry = QLabel(name or auto_threshold_name(value))
        n_entry.setStyleSheet(f"color: {C['text_2']};")
        rl.addWidget(QLabel("名称:"))
        rl.addWidget(n_entry)
        rl.addStretch()

        del_btn = QPushButton("✗")
        del_btn.setStyleSheet(f"color: {C['danger']}; border: none;")
        del_btn.clicked.connect(lambda: (row.deleteLater(), self._thresh_rows.remove((v_spin, n_entry, row))))
        rl.addWidget(del_btn)

        parent.layout().addWidget(row)
        self._thresh_rows.append((v_spin, n_entry, row))
