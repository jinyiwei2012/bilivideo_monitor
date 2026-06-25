"""
对话框模块 - PyQt6 版

集中管理所有弹窗窗口的统一入口。
"""

import threading
import time
import logging

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QPushButton, QMessageBox, QSpinBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_BOLD, FAST_GAP, FAST_INTERVAL

logger = logging.getLogger(__name__)


class Dialogs:
    """所有对话框的统一入口"""

    def __init__(self, gui):
        self.gui = gui

    # ──────────────────────────────────────────
    # 视频标签管理
    # ──────────────────────────────────────────

    def open_tag_manager(self):
        """打开视频标签管理窗口"""
        try:
            from ui.tag_manager import TagManagerWindow
            TagManagerWindow(self.gui, self.gui)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开标签管理失败:\n{e}")

    # ──────────────────────────────────────────
    # 预测回测
    # ──────────────────────────────────────────

    def open_backtest(self):
        """打开预测回测面板"""
        try:
            from ui.backtest_panel import BacktestPanel
            BacktestPanel(self.gui, self.gui)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开预测回测失败:\n{e}")

    # ──────────────────────────────────────────
    # 视频排行榜
    # ──────────────────────────────────────────

    def open_ranking(self):
        """打开视频排行榜"""
        try:
            from ui.ranking_panel import RankingPanel
            RankingPanel(self.gui, self.gui)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开排行榜失败:\n{e}")

    # ──────────────────────────────────────────
    # 异常增长检测
    # ──────────────────────────────────────────

    def open_anomaly_detection(self):
        """打开异常检测面板"""
        try:
            from ui.anomaly_panel import AnomalyPanel
            AnomalyPanel(self.gui, self.gui)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开异常检测失败:\n{e}")

    # ──────────────────────────────────────────
    # 刷新间隔设置
    # ──────────────────────────────────────────

    def open_interval_settings(self):
        """打开刷新间隔设置对话框"""
        dialog = QDialog(self.gui)
        dialog.setWindowTitle("刷新间隔设置")
        screen = self.gui.screen()
        sw = screen.size().width() if screen else 1920
        sh = screen.size().height() if screen else 1080
        dialog.resize(int(sw * 0.22), int(sh * 0.25))
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumSize(300, 200)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 0)

        lbl = QLabel("普通刷新间隔（秒）：")
        lbl.setStyleSheet(f"color: {C['text_1']};")
        layout.addWidget(lbl)

        spin = QSpinBox()
        spin.setRange(10, 3600)
        spin.setValue(self.gui.DEFAULT_INTERVAL)
        layout.addWidget(spin)

        hint = QLabel(f"距阈值 < {FAST_GAP} 时自动切换快速模式（{FAST_INTERVAL}s）")
        hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

        def _save():
            self.gui.DEFAULT_INTERVAL = spin.value()
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                timer = self.gui._video_timers.get(bvid)
                if timer and timer["interval"] != self.gui.FAST_INTERVAL:
                    self.gui._register_video_timer(bvid)
            dialog.accept()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(_save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        dialog.exec()

    # ──────────────────────────────────────────
    # 数据库查询
    # ──────────────────────────────────────────

    def open_database_query(self):
        """打开数据库查询窗口"""
        try:
            from ui.database_query import DatabaseQueryWindow
            DatabaseQueryWindow(self.gui)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开数据库查询失败: {e}")

    # ──────────────────────────────────────────
    # 视频搜索
    # ──────────────────────────────────────────

    def open_video_search(self):
        """打开视频搜索窗口"""
        try:
            from ui.video_search import VideoSearchWindow
            VideoSearchWindow(self.gui, on_import=self.gui._import_search_results)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开视频搜索失败: {e}")

    # ──────────────────────────────────────────
    # 数据对比
    # ──────────────────────────────────────────

    def open_data_comparison(self):
        """打开数据对比窗口"""
        try:
            from ui.data_comparison import DataComparisonWindow
            DataComparisonWindow(
                self.gui,
                monitored_videos=self.gui.monitored_videos,
                history_data=self.gui.history_data,
                video_dbs=self.gui.video_dbs,
                on_add_monitor=self.gui._add_bvid_to_monitor,
            )
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开数据对比失败: {e}")

    # ──────────────────────────────────────────
    # 交叉计算
    # ──────────────────────────────────────────

    def open_crossover_analysis(self):
        """打开交叉计算窗口"""
        try:
            from ui.crossover_analysis import CrossoverAnalysisWindow
            CrossoverAnalysisWindow(
                self.gui,
                monitored_videos=self.gui.monitored_videos,
                history_data=self.gui.history_data,
                video_dbs=self.gui.video_dbs,
            )
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开交叉计算失败: {e}")

    # ──────────────────────────────────────────
    # 周刊分数
    # ──────────────────────────────────────────

    def open_weekly_score(self):
        """打开周刊分数计算窗口"""
        try:
            from ui.weekly_score import WeeklyScoreWindow
            WeeklyScoreWindow(self.gui, monitored_videos=self.gui.monitored_videos, video_dbs=self.gui.video_dbs)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开周刊分数计算失败: {e}")

    # ──────────────────────────────────────────
    # 里程碑统计
    # ──────────────────────────────────────────

    def open_milestone_stats(self):
        """打开里程碑统计窗口"""
        try:
            from ui.milestone_stats import MilestoneStatsWindow
            MilestoneStatsWindow(
                self.gui,
                monitored_videos=self.gui.monitored_videos,
                on_add_monitor=self.gui._add_bvid_to_monitor,
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开里程碑统计失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 添加 BV 到监控（里程碑回调）
    # ──────────────────────────────────────────

    def add_bvid_to_monitor(self, bvid: str):
        """添加 BV 号到监控列表（供里程碑等模块回调）"""
        for v in self.gui.monitored_videos:
            if v.get("bvid") == bvid:
                return
        entry = {"bvid": bvid, "title": bvid, "view_count": 0}
        self.gui.monitored_videos.append(entry)
        self.gui._save_watch_list()
        self.gui.log_panel.add_log("INFO", f"已将 {bvid} 加入监控列表（里程碑入口）")

    # ──────────────────────────────────────────
    # 算法可视化比较
    # ──────────────────────────────────────────

    def open_algorithm_comparison(self):
        """打开算法比较窗口"""
        try:
            from ui.algorithm_compare import AlgorithmCompareWindow
            AlgorithmCompareWindow(self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开算法比较失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 系统设置
    # ──────────────────────────────────────────

    def open_settings(self):
        """打开系统设置窗口"""
        try:
            from ui.settings_window import SettingsWindow
            SettingsWindow(self.gui, gui=self.gui)
        except Exception as e:
            QMessageBox.critical(self.gui, "错误", f"打开系统设置失败: {e}")

    # ──────────────────────────────────────────
    # 导入搜索结果
    # ──────────────────────────────────────────

    def import_search_results(self, videos: list):
        """导入搜索到的视频到监控列表"""
        if not videos:
            return

        def _worker():
            added, skipped = 0, 0
            from core import get_bilibili_api

            for v in videos:
                bvid = v.get("bvid", "")
                if not bvid:
                    continue
                if any(mv.get("bvid") == bvid for mv in self.gui.monitored_videos):
                    skipped += 1
                    continue
                try:
                    info = get_bilibili_api().get_video_info(bvid)
                    if not info:
                        skipped += 1
                        continue
                    video = self.gui._map_api_to_video_dict(bvid, info, fallback=v)
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda v=video: self.gui._register_video_to_monitor(v))
                    added += 1
                except Exception as e:
                    self.gui.log_panel.add_log("WARNING", f"导入 {bvid} 失败: {e}")
                    skipped += 1
                time.sleep(0.3)

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.gui._save_watch_list)
            msg = f"成功导入 {added} 个视频"
            if skipped:
                msg += f"（跳过 {skipped} 个：已存在或获取失败）"
            if added or skipped:
                QTimer.singleShot(0, lambda: QMessageBox.information(self.gui, "导入完成", msg))
            self.gui.log_panel.add_log("INFO", f"导入完成：成功 {added}，跳过 {skipped}")

        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────
    # 算法信息
    # ──────────────────────────────────────────

    def open_algorithm_info(self):
        """打开算法信息对话框"""
        dialog = QDialog(self.gui)
        dialog.setWindowTitle("算法信息")
        screen = self.gui.screen()
        sw = screen.size().width() if screen else 1920
        sh = screen.size().height() if screen else 1080
        dialog.resize(int(sw * 0.36), int(sh * 0.48))
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumSize(400, 300)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title_lbl = QLabel("预测算法信息")
        title_lbl.setStyleSheet(f"""
            font-size: 14pt; font-weight: bold; color: {C['text_1']};
            background-color: {C['bg_surface']}; padding: 15px;
        """)
        layout.addWidget(title_lbl)

        # 滚动区域
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {C['bg_surface']};")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(20, 10, 20, 10)

        try:
            from algorithms.registry import AlgorithmRegistry

            algo_names = AlgorithmRegistry.get_algorithm_names()
            algo_infos = AlgorithmRegistry.get_weights_info()

            # 算法数量
            info_frame = QFrame()
            info_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {C['bg_elevated']};
                    border: 1px solid {C['border']};
                    border-radius: 8px;
                }}
            """)
            info_layout = QVBoxLayout(info_frame)

            count_lbl = QLabel(f"已加载算法: {len(algo_names)} 个")
            count_lbl.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {C['text_1']}; padding: 10px;")
            info_layout.addWidget(count_lbl)
            scroll_layout.addWidget(info_frame)

            # 算法列表（最多 20 个）
            for info in algo_infos[:20]:
                algo_row = QWidget()
                algo_row.setStyleSheet(f"background-color: {C['bg_surface']};")
                row_layout = QHBoxLayout(algo_row)
                row_layout.setContentsMargins(0, 2, 0, 2)

                name = info.get("name", "Unknown")
                weight = info.get("weight", 1.0)
                accuracy = info.get("accuracy", 0.5)

                name_lbl = QLabel(f"• {name}")
                name_lbl.setStyleSheet(f"color: {C['text_1']};")
                row_layout.addWidget(name_lbl)

                row_layout.addStretch()

                w_lbl = QLabel(f"权重: {weight:.2f}")
                w_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 8pt;")
                row_layout.addWidget(w_lbl)

                a_lbl = QLabel(f"准确率: {accuracy:.2%}")
                a_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 8pt;")
                row_layout.addWidget(a_lbl)

                scroll_layout.addWidget(algo_row)

            if len(algo_names) > 20:
                more_lbl = QLabel(f"... 还有 {len(algo_names) - 20} 个算法")
                more_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
                scroll_layout.addWidget(more_lbl)

            # 高级模块状态
            section_title = QLabel("高级模块状态:")
            section_title.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {C['text_1']}; padding-top: 15px;")
            scroll_layout.addWidget(section_title)

            def _module_status(name, import_path):
                try:
                    __import__(import_path, fromlist=[""])
                    return QLabel(f"✅ {name}已加载")
                except ImportError:
                    return QLabel(f"❌ {name}未找到")

            for mod_name, mod_path in [
                ("在线学习模块", "algorithms.online_learner"),
                ("因果推断模块", "algorithms.causal_inference"),
                ("图神经网络模块", "algorithms.graph_neural"),
            ]:
                slbl = _module_status(mod_name, mod_path)
                slbl.setStyleSheet(f"color: {C['success']}; padding-left: 10px;"
                                   if "✅" in slbl.text()
                                   else f"color: {C['danger']}; padding-left: 10px;")
                scroll_layout.addWidget(slbl)

        except Exception as e:
            err_lbl = QLabel(f"加载算法信息失败: {e}")
            err_lbl.setStyleSheet(f"color: {C['danger']};")
            scroll_layout.addWidget(err_lbl)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        # 关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(20, 10, 20, 15)
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    # ──────────────────────────────────────────
    # UP主追踪
    # ──────────────────────────────────────────

    def open_up_tracker(self):
        """打开 UP主 追踪窗口"""
        try:
            from ui.up_tracker import UpTrackerWindow
            from core import get_bilibili_api
            UpTrackerWindow(self.gui, api=get_bilibili_api())
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开UP主追踪失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 弹幕分析
    # ──────────────────────────────────────────

    def open_danmaku_analysis(self):
        """打开弹幕分析窗口"""
        try:
            from ui.danmaku_analysis import DanmakuAnalysisWindow
            from core import get_bilibili_api
            DanmakuAnalysisWindow(self.gui, api=get_bilibili_api(), gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开弹幕分析失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 历史弹幕拉取
    # ──────────────────────────────────────────

    def open_danmaku_history(self):
        """打开历史弹幕拉取窗口"""
        try:
            from ui.danmaku_history import DanmakuHistoryWindow
            DanmakuHistoryWindow(parent=self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开历史弹幕失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 热门发现
    # ──────────────────────────────────────────

    def open_trending_discovery(self):
        """打开热门发现窗口"""
        try:
            from ui.trending_discovery import TrendingDiscoveryWindow
            from core import get_bilibili_api
            TrendingDiscoveryWindow(self.gui, api=get_bilibili_api(), on_add_monitor=self.gui._add_bvid_to_monitor)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开热门发现失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # AI智能问答
    # ──────────────────────────────────────────

    def open_ai_qa(self):
        """打开 AI 智能问答窗口"""
        try:
            from ui.ai_qa_window import AIQAWindow
            AIQAWindow(self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开AI问答失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 数据大屏
    # ──────────────────────────────────────────

    def open_prediction_accuracy(self):
        """打开预测准确率回看窗口"""
        try:
            from ui.prediction_accuracy import PredictionAccuracyPanel
            PredictionAccuracyPanel(parent=self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开预测回看失败: {e}\n{traceback.format_exc()}")

    def open_time_analysis(self):
        """打开时段播放分析窗口"""
        try:
            from ui.time_analysis import TimeAnalysisPanel
            TimeAnalysisPanel(parent=self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开时段分析失败: {e}\n{traceback.format_exc()}")

    def open_video_compare_enhanced(self):
        """打开视频对比增强窗口"""
        try:
            from ui.video_compare_enhanced import VideoCompareEnhanced
            VideoCompareEnhanced(parent=self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开视频对比增强失败: {e}\n{traceback.format_exc()}")

    def open_dashboard(self):
        """打开数据大屏窗口"""
        try:
            from ui.dashboard_mode import DashboardWindow
            DashboardWindow(gui=self.gui, parent=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开数据大屏失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 报告导出
    # ──────────────────────────────────────────

    def open_report_scheduler(self):
        """打开报告导出窗口"""
        try:
            from ui.report_scheduler import ReportSchedulerWindow
            ReportSchedulerWindow(self.gui, gui=self.gui)
        except Exception as e:
            import traceback
            QMessageBox.critical(self.gui, "错误", f"打开报告导出失败: {e}\n{traceback.format_exc()}")
