"""
报告定时器设置窗口 — PyQt6 版
手动或定时生成数据报告（CSV/JSON/HTML/Excel）
"""

import os
import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QComboBox, QCheckBox, QListWidget, QMessageBox,
    QFrame, QApplication,
)
from PyQt6.QtCore import QTimer

from ui.theme import C
from config import DATA_DIR

logger = logging.getLogger(__name__)

_SCHEDULE_CONFIG = Path(DATA_DIR) / ".export_schedule.json"


class ReportSchedulerWindow(QDialog):
    """报告导出与定时器设置窗口 — PyQt6 版"""

    def __init__(self, parent=None, gui=None):
        super().__init__(parent)
        self.gui = gui
        self._scheduled_job = None

        self.setWindowTitle("定时导出报告")
        screen = self.screen()
        if screen:
            geo = screen.geometry()
            sw, sh = geo.width(), geo.height()
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.42), int(sh * 0.60))

        self._setup_ui()

    def _setup_ui(self):
        """构建报告定时器设置窗口 UI：手动导出、定时导出、已导出文件列表"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Header ──
        header = QLabel("定时导出报告")
        header.setStyleSheet(f"""
            color: {C['text_1']}; font-size: 14pt; font-weight: bold;
            padding: 16px 24px 4px 24px; background-color: {C['bg_surface']};
        """)
        main_layout.addWidget(header)

        sub = QLabel("手动导出 / 按计划自动导出 CSV / JSON / HTML / Excel")
        sub.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt; padding: 0 24px 12px 24px; background-color: {C['bg_surface']};")
        main_layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        main_layout.addWidget(sep)

        # Scrollable content
        content = QWidget()
        content.setStyleSheet(f"background-color: {C['bg_elevated']};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 12)

        # ── 手动导出 ──
        cl.addWidget(self._section_title("手动导出"))

        format_row = QWidget()
        format_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        fr = QHBoxLayout(format_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr_lbl = QLabel("导出格式:")
        fr_lbl.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        fr.addWidget(fr_lbl)

        self._format_group = {}
        for fmt, label in [("html", "HTML"), ("excel", "Excel"), ("csv", "CSV"), ("json", "JSON"), ("both", "所有")]:
            rb = QRadioButton(label)
            rb.setStyleSheet(f"color: {C['text_1']}; background-color: transparent;")
            if fmt == "html":
                rb.setChecked(True)
            self._format_group[fmt] = rb
            fr.addWidget(rb)
        fr.addStretch()
        cl.addWidget(format_row)

        export_btn = QPushButton("立即导出")
        export_btn.setProperty("primary", True)
        export_btn.setFixedWidth(120)
        export_btn.clicked.connect(self._export_now)
        cl.addWidget(export_btn)

        self._export_status = QLabel("")
        self._export_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        cl.addWidget(self._export_status)

        pred_btn = QPushButton("📊 导出预测vs实际对比表")
        pred_btn.clicked.connect(self._export_pred_vs_actual)
        cl.addWidget(pred_btn)

        # ── 定时导出 ──
        cl.addWidget(self._section_title("定时导出"))

        desc = QLabel("按计划自动导出到 reports/ 目录")
        desc.setStyleSheet(f"color: {C['text_3']}; background-color: transparent;")
        cl.addWidget(desc)

        sched_row = QWidget()
        sched_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        sr = QHBoxLayout(sched_row)
        sr.setContentsMargins(0, 0, 0, 0)

        self._schedule_enabled = QCheckBox("启用定时导出")
        self._schedule_enabled.setStyleSheet(f"color: {C['text_1']}; background-color: transparent;")
        self._schedule_enabled.toggled.connect(self._on_schedule_toggle)
        sr.addWidget(self._schedule_enabled)

        sr_lbl = QLabel("  间隔:")
        sr_lbl.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        sr.addWidget(sr_lbl)
        self._interval_combo = QComboBox()
        self._interval_combo.addItems(["hourly", "daily", "weekly"])
        self._interval_combo.setFixedWidth(100)
        sr.addWidget(self._interval_combo)

        sf_lbl = QLabel("  导出格式:")
        sf_lbl.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        sr.addWidget(sf_lbl)
        self._schedule_format_combo = QComboBox()
        self._schedule_format_combo.addItems(["csv", "json", "html"])
        self._schedule_format_combo.setFixedWidth(80)
        sr.addWidget(self._schedule_format_combo)

        sr.addStretch()
        cl.addWidget(sched_row)

        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self._save_schedule)
        save_btn.setFixedWidth(120)
        cl.addWidget(save_btn)

        self._schedule_status = QLabel("")
        self._schedule_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        cl.addWidget(self._schedule_status)

        # ── 已导出文件列表 ──
        cl.addWidget(self._section_title("已导出文件"))

        self._file_list = QListWidget()
        self._file_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                font-family: Consolas; font-size: 9pt;
                border: 1px solid {C['border']};
                min-height: 150px;
            }}
            QListWidget::item {{ padding: 4px; }}
            QListWidget::item:selected {{
                background-color: {C['bg_hover']};
                color: {C['text_1']};
            }}
        """)
        cl.addWidget(self._file_list, 1)

        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 6, 0, 0)

        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self._refresh_file_list)
        br.addWidget(refresh_btn)

        open_btn = QPushButton("打开文件夹")
        open_btn.clicked.connect(self._open_folder)
        br.addWidget(open_btn)

        br.addStretch()
        cl.addWidget(btn_row)

        main_layout.addWidget(content, 1)

        self._refresh_file_list()
        self._load_schedule()

    def _section_title(self, text: str) -> QLabel:
        """创建分节标题"""
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            color: {C['text_1']}; font-size: 10pt; font-weight: bold;
            padding: 8px 0 4px 0; background-color: transparent;
        """)
        return lbl

    def _get_format(self) -> str:
        """获取当前选中的导出格式"""
        for fmt, rb in self._format_group.items():
            if rb.isChecked():
                return fmt
        return "html"

    def _export_pred_vs_actual(self):
        """导出预测值 vs 实际播放量对比表"""
        if not self.gui or not self.gui.video_dbs:
            QMessageBox.warning(self, "提示", "暂无预测数据")
            return
        self._export_status.setText("正在导出预测对比表...")
        self._export_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        try:
            from utils.report_exporter import export_prediction_vs_actual

            path = export_prediction_vs_actual(self.gui.video_dbs)
            if path:
                self._export_status.setText(f"✅ 已导出: {path}")
                self._export_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            else:
                self._export_status.setText("⚠️ 无有效的预测-实际对照数据")
                self._export_status.setStyleSheet(f"color: {C['warning']}; background-color: transparent;")
        except Exception as e:
            self._export_status.setText(f"❌ 导出失败: {e}")
            self._export_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

    def _export_now(self):
        """立即按选定格式导出监控数据报告"""
        if not self.gui or not self.gui.monitored_videos:
            QMessageBox.warning(self, "提示", "暂无监控视频数据")
            return
        fmt = self._get_format()
        self._export_status.setText("正在导出...")
        self._export_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")

        from utils.report_exporter import export_html, export_excel, export_csv, export_json

        results = []
        try:
            fmts = {
                "html": [export_html],
                "excel": [export_excel],
                "csv": [export_csv],
                "json": [export_json],
                "both": [export_html, export_excel, export_csv, export_json],
            }
            for exporter in fmts.get(fmt, [export_html]):
                path = exporter(self.gui.monitored_videos)
                results.append(f"{exporter.__name__.replace('export_', '').upper()}: {path}")
            self._export_status.setText("导出完成！\n" + "\n".join(results))
            self._export_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            self._refresh_file_list()
        except Exception as e:
            self._export_status.setText(f"导出失败: {e}")
            self._export_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

    # ── 定时导出 ──

    def _on_schedule_toggle(self, checked):
        """启用定时导出时重置间隔和格式为默认值"""
        if checked:
            self._interval_combo.setCurrentText("daily")
            self._schedule_format_combo.setCurrentText("csv")

    def _load_schedule(self):
        """从配置文件加载已保存的定时设置"""
        try:
            if _SCHEDULE_CONFIG.exists():
                data = json.loads(_SCHEDULE_CONFIG.read_text(encoding="utf-8"))
                self._schedule_enabled.setChecked(data.get("enabled", False))
                self._interval_combo.setCurrentText(data.get("interval", "daily"))
                self._schedule_format_combo.setCurrentText(data.get("format", "csv"))
                self._schedule_status.setText("已加载保存的定时设置")
                self._schedule_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    def _save_schedule(self):
        """保存定时设置到配置文件并排程下一次导出"""
        data = {
            "enabled": self._schedule_enabled.isChecked(),
            "interval": self._interval_combo.currentText(),
            "format": self._schedule_format_combo.currentText(),
        }
        try:
            _SCHEDULE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            _SCHEDULE_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._schedule_status.setText("设置已保存")
            self._schedule_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            if self._schedule_enabled.isChecked() and self.gui:
                QTimer.singleShot(100, self._schedule_next)
        except Exception as e:
            self._schedule_status.setText(f"保存失败: {e}")
            self._schedule_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

    def _schedule_next(self):
        """排程下次导出"""
        if not self._schedule_enabled.isChecked() or not self.gui:
            return
        interval = self._interval_combo.currentText()
        delays = {"hourly": 3600000, "daily": 86400000, "weekly": 604800000}
        delay_ms = delays.get(interval, 86400000)
        try:
            self._scheduled_job = QTimer.singleShot(delay_ms, self._do_scheduled_export)
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    def _do_scheduled_export(self):
        """执行定时导出并重新排程"""
        if not self.gui or not self.gui.monitored_videos:
            self._schedule_next()
            return
        try:
            fmt = self._schedule_format_combo.currentText()
            from utils.report_exporter import export_csv, export_json, export_html

            exporters = {"csv": export_csv, "json": export_json, "html": export_html}
            exporter = exporters.get(fmt, export_csv)
            path = exporter(self.gui.monitored_videos)
            logger.info("定时导出完成: %s", path)
        except Exception as e:
            logger.warning("定时导出失败: %s", e)
        self._refresh_file_list()
        self._schedule_next()

    # ── 文件列表 ──

    def _refresh_file_list(self):
        """刷新已导出文件列表，显示最近的 30 个文件"""
        self._file_list.clear()
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        if os.path.isdir(reports_dir):
            files = sorted(os.listdir(reports_dir), reverse=True)[:30]
            for f in files:
                full_path = os.path.join(reports_dir, f)
                size = os.path.getsize(full_path)
                size_str = f"{size / 1024:.1f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"
                self._file_list.addItem(f"{f}  ({size_str})")

    def _open_folder(self):
        """打开报告导出目录"""
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        try:
            os.startfile(reports_dir)
        except AttributeError:
            import subprocess
            subprocess.run(["explorer", reports_dir])
