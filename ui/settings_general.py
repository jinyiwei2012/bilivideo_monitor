"""
常规设置（预测参数 + 重试参数 + 运行状态）— PyQt6 版
"""

import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QDoubleSpinBox,
    QMessageBox,
    QFrame,
)
from PyQt6.QtCore import QTimer
from ui.theme import C
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)


class SettingsGeneralMixin:
    """General settings tab: prediction params, retry params, run status."""

    def _build_general_tab(self, nb):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        nb.addTab(page, "  常规设置  ")

        self._build_general_predict_section(page)
        self._build_general_appearance_section(page)
        self._build_general_window_section(page)
        self._build_general_retry_section(page)
        self._build_general_status_section(page)

    def _build_general_appearance_section(self, page):
        """界面外观：主题选择 (深色/亮色) — B2 主题偏好设置入口"""
        from PyQt6.QtWidgets import QComboBox

        sec = self._section(page, "界面主题")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("主题模式:")
        lbl.setStyleSheet(f"color: {C['text_2']};")
        rl.addWidget(lbl)

        self.theme_combo = QComboBox()
        cur = self._cfg.get("ui", {}).get("theme", "darkly")
        self.theme_combo.addItem("🌙 深色 (天依夜巡)", "darkly")
        self.theme_combo.addItem("☀️ 亮色 (天依晨歌)", "light")
        idx = self.theme_combo.findData(cur)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        rl.addWidget(self.theme_combo)
        rl.addStretch()
        sec.layout().addWidget(row)

        hint = QLabel("切换后新开的窗口立即生效;主界面需重启应用后全部换装 ♪ 天依两种模样都好看哦~")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        sec.layout().addWidget(hint)

    def _build_general_window_section(self, page):
        """窗口行为：托盘驻留开关 (B1)"""
        from PyQt6.QtWidgets import QCheckBox

        sec = self._section(page, "窗口行为")
        self.close_to_tray = QCheckBox("关闭窗口时最小化到系统托盘（监控后台继续运行）")
        self.close_to_tray.setChecked(bool(self._cfg.get("ui", {}).get("close_to_tray", True)))
        self.close_to_tray.setStyleSheet(f"color: {C['text_2']};")
        sec.layout().addWidget(self.close_to_tray)

        hint = QLabel("关窗后,天依会藏到托盘里继续守着♪ 右击音符图标: 显示/隐藏、立即刷新、暂停/继续监控、退出")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        sec.layout().addWidget(hint)

    def _build_general_predict_section(self, page):
        sec = self._section(page, "预测参数")
        self.predict_hours = self._spin_field(
            sec, "预测时长(小时)", self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720
        )
        self.min_confidence = self._spin_field_float(
            sec, "最小置信度", self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0
        )

        # ── 阈值阶梯自动扩档 (A1) ──
        esc_sec = self._section(page, "阈值阶梯自动扩档")
        from PyQt6.QtWidgets import QCheckBox

        self.auto_escalate = QCheckBox("达到最高档后自动追加更高目标")
        self.auto_escalate.setChecked(bool(self._cfg.get("prediction", {}).get("auto_escalate", True)))
        self.auto_escalate.setStyleSheet(f"color: {C['text_2']};")
        esc_sec.layout().addWidget(self.auto_escalate)

        self.escalate_factor = self._spin_field_float(
            esc_sec, "阶梯倍数", self._cfg.get("prediction", {}).get("escalate_factor", 5.0), 1.5, 20.0
        )

        hint = QLabel("例: 播放量超过最高档 1000万 后，自动追加 5000万 为新目标 ♪")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        esc_sec.layout().addWidget(hint)

    def _build_general_retry_section(self, page):
        sec = QFrame(page)
        sec.setStyleSheet(
            f"background-color: {C['bg_elevated']}; border: 1px solid {C['border_sub']}; border-radius: 4px;"
        )
        sec_layout = QVBoxLayout(sec)
        page.layout().addWidget(sec)

        title = QLabel("重试参数")
        title.setStyleSheet(f"color: {C['text_2']}; font-weight: bold; font-size: 8pt;")
        sec_layout.addWidget(title)

        def _spin_r(parent, label, default, fr, to):
            f = QWidget(parent)
            fl = QHBoxLayout(f)
            fl.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {C['text_2']};")
            lbl.setFixedWidth(160)
            fl.addWidget(lbl)
            sp = QDoubleSpinBox()
            sp.setRange(fr, to)
            sp.setValue(default)
            sp.setDecimals(0 if isinstance(default, int) else 1)
            fl.addWidget(sp)
            fl.addStretch()
            sec_layout.addWidget(f)
            return sp

        self.retry_count_var = _spin_r(sec, "最大重试次数", get_bilibili_api().max_retries, 1, 10)
        self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)", get_bilibili_api().base_retry_delay, 1, 30)
        self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)", get_bilibili_api()._min_request_interval, 0.1, 10)

        apply_btn = QPushButton("应用重试设置")
        apply_btn.clicked.connect(self._apply_retry_settings)
        sec_layout.addWidget(apply_btn)

    def _build_general_status_section(self, page):
        sec = QFrame(page)
        sec.setStyleSheet(
            f"background-color: {C['bg_elevated']}; border: 1px solid {C['border_sub']}; border-radius: 4px;"
        )
        sec_layout = QVBoxLayout(sec)
        page.layout().addWidget(sec)

        title = QLabel("运行状态")
        title.setStyleSheet(f"color: {C['text_2']}; font-weight: bold; font-size: 8pt;")
        sec_layout.addWidget(title)

        self.status_labels = {}
        fields = [
            ("is_login", "登录状态"),
            ("login_name", "登录账号"),
            ("has_cookies", "Cookie已配置"),
            ("consecutive_412_errors", "连续412错误"),
            ("min_request_interval", "请求间隔(秒)"),
            ("proxy_count", "代理数量"),
        ]
        for key, field_label in fields:
            f = QWidget(sec)
            fl = QHBoxLayout(f)
            fl.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(field_label)
            lbl.setStyleSheet(f"color: {C['text_2']};")
            lbl.setFixedWidth(130)
            fl.addWidget(lbl)
            vl = QLabel("-")
            vl.setStyleSheet(f"color: {C['success']};")
            fl.addWidget(vl)
            fl.addStretch()
            sec_layout.addWidget(f)
            self.status_labels[key] = vl

        btn_s = QWidget(sec)
        btn_sl = QHBoxLayout(btn_s)
        btn_sl.setContentsMargins(0, 4, 0, 0)
        refresh_btn = QPushButton("刷新状态")
        refresh_btn.clicked.connect(self._refresh_status)
        btn_sl.addWidget(refresh_btn)
        reset_btn = QPushButton("重置状态")
        reset_btn.clicked.connect(lambda: _confirm_risky("重置 API 状态") and self._reset_status())
        btn_sl.addWidget(reset_btn)
        btn_sl.addStretch()
        sec_layout.addWidget(btn_s)

        self._refresh_status()

    def _apply_retry_settings(self):
        get_bilibili_api().max_retries = int(self.retry_count_var.value())
        get_bilibili_api().base_retry_delay = self.base_delay_var.value()
        get_bilibili_api()._min_request_interval = self.min_interval_var.value()
        QMessageBox.information(self.dlg, "更新好啦 ♪", "重试设置更新好啦 ♪ 天依会按新的节奏去唱歌的哦~")

    def _refresh_status(self):
        import threading

        def _worker():
            try:
                status = get_bilibili_api().get_status()
            except Exception as e:
                logger.debug("获取状态失败: %s", e)
                status = {}
            QTimer.singleShot(0, lambda s=status: self._apply_status(s))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_status(self, status: dict):
        for key, label in self.status_labels.items():
            value = status.get(key, "N/A")
            if key == "is_login":
                v = "✓ 已登录 ♪" if value else "✗ 未登录呢…"
                label.setStyleSheet(f"color: {C['success'] if value else C['danger']};")
            elif key == "login_name":
                v = str(value) if value else "—"
                label.setStyleSheet(f"color: {C['text_1'] if value else C['text_3']};")
            elif key == "has_cookies":
                v = "是" if value else "否"
                label.setStyleSheet(f"color: {C['success'] if value else C['danger']};")
            elif key == "consecutive_412_errors":
                v = str(value)
                label.setStyleSheet(f"color: {C['danger'] if value and value > 0 else C['success']};")
            else:
                v = str(value)
                label.setStyleSheet(f"color: {C['success']};")
            label.setText(v)

    def _reset_status(self):
        reply = QMessageBox.question(
            self.dlg,
            "确认",
            "真的要重置所有状态吗?重置后原来的进度就像歌的间奏一样,唱不回来了哦…",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            get_bilibili_api().reset_status()
            self._refresh_status()
