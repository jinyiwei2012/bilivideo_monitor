"""
报告定时器设置窗口 — PyQt6 版
手动或定时生成数据报告（CSV/JSON/HTML/Excel）
"""

import os
import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QComboBox,
    QCheckBox,
    QListWidget,
    QMessageBox,
    QFrame,
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
        self.show()

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

        sub = QLabel("手动导出 / 按计划自动导出 CSV / JSON / HTML / Excel ♪")
        sub.setStyleSheet(
            f"color: {C['text_3']}; font-size: 9pt; padding: 0 24px 12px 24px; background-color: {C['bg_surface']};"
        )
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

        # C3: AI 解读开关（需已配置 AI 密钥）
        self._ai_insight = QCheckBox("◈ 附 AI 数据解读（需 LLM 密钥）")
        self._ai_insight.setChecked(True)
        self._ai_insight.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        cl.addWidget(self._ai_insight)

        # D1: 手动导出完成后同步推送摘要
        self._manual_notify = QCheckBox("◈ 导出完成后推送摘要（QQ/Webhook/Windows）")
        self._manual_notify.setChecked(False)
        self._manual_notify.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        cl.addWidget(self._manual_notify)

        self._export_status = QLabel("")
        self._export_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        cl.addWidget(self._export_status)

        pred_btn = QPushButton("◧ 导出预测vs实际对比表")
        pred_btn.clicked.connect(self._export_pred_vs_actual)
        cl.addWidget(pred_btn)

        # ── 定时导出 ──
        cl.addWidget(self._section_title("定时导出"))

        desc = QLabel("到点啦,天依会把数据整理成歌谱,自动收进 reports/ 目录 ♪")
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

        # C3: 定时导出附带 AI 解读
        self._schedule_ai = QCheckBox("AI解读")
        self._schedule_ai.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        self._schedule_ai.setChecked(True)
        sr.addWidget(self._schedule_ai)

        # D1: 导出完成后推送摘要到通知渠道（QQ/Webhook/Windows）
        self._schedule_notify = QCheckBox("完成后推送")
        self._schedule_notify.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        self._schedule_notify.setChecked(False)
        sr.addWidget(self._schedule_notify)

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
            QMessageBox.warning(self, "提示", "还没有预测数据呢,等天依唱出预测再导出吧 ♪")
            return
        self._export_status.setText("天依正在整理预测对比表…像在谱写乐谱 ♪")
        self._export_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")
        try:
            from utils.report_exporter import export_prediction_vs_actual

            path = export_prediction_vs_actual(self.gui.video_dbs)
            if path:
                self._export_status.setText(f"✓ 导出完成啦!♪ 已保存到: {path}")
                self._export_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            else:
                self._export_status.setText("△ 还没有可对比的预测与实际数据呢,天依先记下了 ♪")
                self._export_status.setStyleSheet(f"color: {C['warning']}; background-color: transparent;")
        except Exception as e:
            logger.warning("导出预测对比表失败: %s", e)
            self._export_status.setText("呜…导出失败了,天依会再试试的哦 ♪")
            self._export_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

    def _export_now(self):
        """立即按选定格式导出监控数据报告（HTML 可选附 AI 解读）"""
        if not self.gui or not self.gui.monitored_videos:
            QMessageBox.warning(self, "提示", "还没有监控视频呢,先添加一些,天依才能导出哦 ♪")
            return
        fmt = self._get_format()

        # C3: HTML（含 both）且勾选 AI → 后台执行 AI 解读 + 导出
        want_ai = self._ai_insight.isChecked()
        if want_ai and fmt in ("html", "both"):
            self._export_status.setText("天依正在请 AI 为报告写解读…可能要多等一会儿哦 ♪")
            self._export_status.setStyleSheet(f"color: {C['warning']}; background-color: transparent;")

            from utils.thread_utils import fire_and_forget

            def _worker():
                try:
                    from utils.report_exporter import (
                        generate_ai_insight,
                        export_html,
                        export_excel,
                        export_csv,
                        export_json,
                    )

                    insight = generate_ai_insight(self.gui.monitored_videos)
                    results = []
                    if insight:
                        p = export_html(self.gui.monitored_videos, ai_insight=insight)
                        results.append(f"HTML(AI解读): {p}")
                    else:
                        p = export_html(self.gui.monitored_videos)
                        results.append(f"HTML: {p}")
                    if fmt == "both":
                        for exporter, name in ((export_excel, "Excel"), (export_csv, "CSV"), (export_json, "JSON")):
                            try:
                                results.append(f"{name}: {exporter(self.gui.monitored_videos)}")
                            except Exception:
                                pass
                    QTimer.singleShot(
                        0,
                        lambda r=results: self._on_ai_export_done(r, insight),
                    )
                except Exception as e:
                    logger.warning("AI解读导出失败: %s", e)
                    QTimer.singleShot(
                        0,
                        lambda: self._on_ai_export_error(),
                    )

            fire_and_forget(_worker, name="manual-export-ai")
            return

        self._export_status.setText("天依正在把数据唱成报告…稍等一下下哦 ♪")
        self._export_status.setStyleSheet(f"color: {C['text_2']}; background-color: transparent;")

        from utils.report_exporter import export_html, export_excel, export_csv, export_json

        results = []
        try:
            fmts: dict[str, list[Callable[[list], str]]] = {
                "html": [export_html],
                "excel": [export_excel],
                "csv": [export_csv],
                "json": [export_json],
                "both": [export_html, export_excel, export_csv, export_json],
            }
            for exporter in fmts.get(fmt, [export_html]):
                path = exporter(self.gui.monitored_videos)
                results.append(f"{exporter.__name__.replace('export_', '').upper()}: {path}")
            self._export_status.setText("导出完成啦!♪ 数据都好好收藏起来了:\n" + "\n".join(results))
            self._export_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            self._refresh_file_list()
            if self._manual_notify.isChecked():
                notify_export_done(self.gui, results[0].split(": ", 1)[-1], fmt=fmt, manual=True)
        except Exception as e:
            logger.warning("导出报告失败: %s", e)
            self._export_status.setText("呜…导出失败了,天依不会放弃的,请再试一次哦 ♪")
            self._export_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

    def _on_ai_export_done(self, results, insight):
        """AI 解读导出完成回调（主线程）"""
        try:
            if self._export_status is None:
                return
        except RuntimeError:
            return  # 对话框已销毁，静默跳过
        self._export_status.setText(
            "导出完成啦!♪ AI解读" + ("已附上" if insight else "未生成(检查AI密钥)") + ":\n" + "\n".join(results)
        )
        self._export_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
        self._refresh_file_list()
        try:
            if self._manual_notify.isChecked() and results:
                path = results[0].split(": ", 1)[-1]
                notify_export_done(self.gui, path, fmt="html", manual=True)
        except Exception as e:
            logger.debug("手动导出(AI)推送失败: %s", e)

    def _on_ai_export_error(self):
        """AI 解读导出失败回调（主线程）"""
        try:
            if self._export_status is None:
                return
        except RuntimeError:
            return
        self._export_status.setText("呜…AI解读导出失败了,天依会再试试的哦 ♪")
        self._export_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

    # ── 定时导出 ──

    def _on_schedule_toggle(self, checked):
        """启用定时导出时重置间隔和格式为默认值"""
        if checked:
            self._interval_combo.setCurrentText("daily")
            self._schedule_format_combo.setCurrentText("csv")

    def _load_schedule(self):
        try:
            if _SCHEDULE_CONFIG.exists():
                data = json.loads(_SCHEDULE_CONFIG.read_text(encoding="utf-8"))
                self._schedule_enabled.setChecked(data.get("enabled", False))
                self._interval_combo.setCurrentText(data.get("interval", "daily"))
                self._schedule_format_combo.setCurrentText(data.get("format", "csv"))
                self._schedule_ai.setChecked(bool(data.get("ai_insight", True)))
                if hasattr(self, "_schedule_notify"):
                    self._schedule_notify.setChecked(bool(data.get("notify", False)))
                self._schedule_status.setText("定时设置已经加载好啦 ♪")
                self._schedule_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    def _save_schedule(self):
        """保存定时设置到配置文件并让主窗口接管排程（不再依赖对话框存活）"""
        data = {
            "enabled": self._schedule_enabled.isChecked(),
            "interval": self._interval_combo.currentText(),
            "format": self._schedule_format_combo.currentText(),
            "ai_insight": self._schedule_ai.isChecked(),
            "notify": self._schedule_notify.isChecked() if hasattr(self, "_schedule_notify") else False,
        }
        try:
            _SCHEDULE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            _SCHEDULE_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._schedule_status.setText("设置保存好啦!♪ 天依会按计划按时唱出来哦")
            self._schedule_status.setStyleSheet(f"color: {C['success']}; background-color: transparent;")
            # 把排程交给主窗口级定时器，对话框关闭后依然生效
            if self.gui:
                QTimer.singleShot(100, lambda: resume_export_schedule(self.gui))
        except Exception as e:
            logger.warning("保存定时设置失败: %s", e)
            self._schedule_status.setText("呜…设置没能保存,天依再试试 ♪")
            self._schedule_status.setStyleSheet(f"color: {C['danger']}; background-color: transparent;")

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


# ── 应用级定时排程 ──────────────────────────────
# 定时导出须挂在主窗口生命周期上（而非设置对话框），
# 否则窗口关闭后 QTimer 随对话框销毁，导出永远不会发生。


def load_export_schedule() -> dict:
    """读取已保存的导出排程配置。"""
    try:
        if _SCHEDULE_CONFIG.exists():
            data = json.loads(_SCHEDULE_CONFIG.read_text(encoding="utf-8"))
            return dict(data) if isinstance(data, dict) else {}
    except Exception as e:
        logger.debug("读取导出排程失败: %s", e)
    return {}


def resume_export_schedule(gui):
    """由主窗口启动/重启定时导出。已在运行时则先停旧定时器。"""
    stop_export_schedule(gui)
    data = load_export_schedule()
    if not data.get("enabled") or not gui:
        return
    interval = data.get("interval", "daily")
    fmt = data.get("format", "csv")
    delays = {"hourly": 3600000, "daily": 86400000, "weekly": 604800000}
    delay_ms = delays.get(interval, 86400000)
    gui._export_schedule_timer = QTimer(gui)
    gui._export_schedule_timer.setInterval(delay_ms)
    gui._export_schedule_timer.timeout.connect(lambda: do_scheduled_export(gui, fmt))
    gui._export_schedule_timer.start()
    logger.info("已启用定时导出: interval=%s format=%s", interval, fmt)


def stop_export_schedule(gui):
    """停止定时导出。"""
    timer = getattr(gui, "_export_schedule_timer", None)
    if timer is not None:
        try:
            timer.stop()
        except Exception:
            pass
        gui._export_schedule_timer = None


def notify_export_done(gui, path, fmt="csv", manual=False):
    """导出完成后向通知渠道推送摘要（QQ/Webhook/Windows）。

    摘要取 build_push_msg 的报告文本（监控视频数 + 各视频播放/增速/预测），
    异步发送,不阻塞导出流程。可在后台线程调用——读取前对监控列表做快照,
    避免与主线程增删监控并发迭代。
    """
    try:
        from core.notification import notification_manager

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        head = "手动导出" if manual else "定时导出"
        if not gui or not gui.monitored_videos:
            return
        try:
            with gui._data_lock:
                videos_snapshot = list(gui.monitored_videos)
        except AttributeError:
            videos_snapshot = list(gui.monitored_videos)
        if not videos_snapshot:
            return
        try:
            from ui.main_gui_events import build_push_msg

            digest = build_push_msg(gui, videos_snapshot)
        except Exception:
            digest = f"监控 {len(videos_snapshot)} 个视频"
        msg = f"◧ {head}报告完成 ({now_str})\n格式: {fmt.upper()}\n路径: {path}\n\n{digest}"
        title = f"◧ {head}报告 {now_str}"
        notification_manager.send_qq_private(msg)
        notification_manager.send_qq_group(msg)
        notification_manager.send_webhook(msg)
        notification_manager.send_windows_notification(title, msg[:256])
        logger.info("导出完成推送已发送: %s", path)
    except Exception as e:
        logger.warning("导出完成推送失败: %s", e)


def do_scheduled_export(gui, fmt="csv"):
    """执行一次定时导出（可在无对话框时被主窗口定时器触发）。"""
    if not gui or not gui.monitored_videos:
        return
    data = load_export_schedule()
    with_ai = bool(data.get("ai_insight", True)) and fmt in ("html",)
    if with_ai:
        # C3: 含 AI 解读时后台执行，避免 LLM 调用阻塞主线程
        from utils.thread_utils import fire_and_forget

        fire_and_forget(_export_with_ai_worker, gui, fmt, name="scheduled-export-ai")
        return
    try:
        from utils.report_exporter import export_csv, export_json, export_html

        exporters = {"csv": export_csv, "json": export_json, "html": export_html}
        exporter = exporters.get(fmt, export_csv)
        path = exporter(gui.monitored_videos)
        logger.info("定时导出完成: %s", path)
        if data.get("notify"):
            notify_export_done(gui, path, fmt=fmt, manual=False)
    except Exception as e:
        logger.warning("定时导出失败: %s", e)


def _export_with_ai_worker(gui, fmt="html"):
    """后台执行：生成 AI 解读后导出（AI 无密钥时静默回退为普通导出）。"""
    try:
        from utils.report_exporter import generate_ai_insight, export_html

        insight = generate_ai_insight(gui.monitored_videos)
        path = export_html(gui.monitored_videos, ai_insight=insight or None)
        logger.info("定时导出完成(AI解读): %s", path)
        try:
            if insight:
                gui.log_panel.add_log("INFO", f"报告已附带 AI 解读: {path}")
            else:
                gui.log_panel.add_log("INFO", f"报告导出完成(未配置AI或生成失败): {path}")
        except Exception:
            pass
        try:
            if load_export_schedule().get("notify"):
                notify_export_done(gui, path, fmt=fmt, manual=False)
        except Exception as e:
            logger.debug("定时导出(AI)推送失败: %s", e)
    except Exception as e:
        logger.warning("AI 解读导出失败: %s", e)
        try:
            from utils.report_exporter import export_html

            path = export_html(gui.monitored_videos)
            logger.info("已回退为普通 HTML 导出: %s", path)
            if load_export_schedule().get("notify"):
                notify_export_done(gui, path, fmt=fmt, manual=False)
        except Exception as e2:
            logger.warning("回退导出也失败: %s", e2)
