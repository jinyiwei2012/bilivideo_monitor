"""
现代对话框模块
集中管理所有弹窗窗口 — 统一使用 DialogBase 样式
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num, FAST_GAP, FAST_INTERVAL
from ui.dialog_base import DialogBase


class Dialogs:
    """所有对话框的统一入口"""

    def __init__(self, gui):
        self.gui = gui

    # ──────────────────────────────────────────
    # 刷新间隔设置
    # ──────────────────────────────────────────

    def open_interval_settings(self):
        dlg = DialogBase(self.gui.root, "刷新间隔设置", "380x260")
        dlg.header("刷新间隔设置", "自定义各监控视频的数据刷新频率")

        sec = dlg.section(title="间隔参数")

        # 普通间隔
        row1 = tk.Frame(sec, bg=C["bg_elevated"])
        row1.pack(fill=tk.X, pady=(4, 2))
        tk.Label(row1, text="普通刷新间隔", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT, width=18, anchor="w").pack(side=tk.LEFT, padx=(4, 0))
        var = tk.IntVar(value=self.gui.DEFAULT_INTERVAL)
        spin = ttk.Spinbox(row1, from_=10, to=3600, textvariable=var, width=10)
        spin.pack(side=tk.LEFT)
        tk.Label(row1, text="秒", bg=C["bg_elevated"], fg=C["text_3"],
                 font=FONT).pack(side=tk.LEFT, padx=(4, 0))

        # 快速模式提示
        tip = tk.Frame(sec, bg=C["bg_elevated"])
        tip.pack(fill=tk.X, pady=(2, 4))
        tk.Label(tip, text=f"距阈值 < {FAST_GAP} 时自动切换快速模式",
                 bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM,
                 anchor="w").pack(padx=(4, 0))
        tk.Label(tip, text=f"快速间隔: {FAST_INTERVAL}s",
                 bg=C["bg_elevated"], fg=C["warning"], font=FONT_SM,
                 anchor="w").pack(padx=(4, 0))

        def _save():
            self.gui.DEFAULT_INTERVAL = var.get()
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                timer = self.gui._video_timers.get(bvid)
                if timer and timer["interval"] != self.gui.FAST_INTERVAL:
                    self.gui._register_video_timer(bvid)
            dlg.window.destroy()

        dlg.button_row([
            ("取消", dlg.window.destroy, ""),
            ("保存", _save, "primary"),
        ])

    # ──────────────────────────────────────────
    # 权重设置
    # ──────────────────────────────────────────

    def open_weight_settings(self):
        try:
            from .weight_settings import WeightSettingsWindow
            WeightSettingsWindow(self.gui.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开权重设置失败: {e}")

    # ──────────────────────────────────────────
    # 数据库查询
    # ──────────────────────────────────────────

    def open_database_query(self):
        try:
            from .database_query import DatabaseQueryWindow
            DatabaseQueryWindow(self.gui.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开数据库查询失败: {e}")

    # ──────────────────────────────────────────
    # 视频搜索
    # ──────────────────────────────────────────

    def open_video_search(self):
        try:
            from .video_search import VideoSearchWindow
            VideoSearchWindow(self.gui.root, on_import=self.gui._import_search_results)
        except Exception as e:
            messagebox.showerror("错误", f"打开视频搜索失败: {e}")

    # ──────────────────────────────────────────
    # 数据对比
    # ──────────────────────────────────────────

    def open_data_comparison(self):
        try:
            from .data_comparison import DataComparisonWindow
            DataComparisonWindow(self.gui.root, monitored_videos=self.gui.monitored_videos,
                                 history_data=self.gui.history_data,
                                 video_dbs=self.gui.video_dbs,
                                 on_add_monitor=self.gui._add_bvid_to_monitor)
        except Exception as e:
            messagebox.showerror("错误", f"打开数据对比失败: {e}")

    # ──────────────────────────────────────────
    # 交叉计算
    # ──────────────────────────────────────────

    def open_crossover_analysis(self):
        try:
            from .crossover_analysis import CrossoverAnalysisWindow
            CrossoverAnalysisWindow(self.gui.root, monitored_videos=self.gui.monitored_videos,
                                    history_data=self.gui.history_data, video_dbs=self.gui.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开交叉计算失败: {e}")

    # ──────────────────────────────────────────
    # 周刊分数
    # ──────────────────────────────────────────

    def open_weekly_score(self):
        try:
            from .weekly_score import WeeklyScoreWindow
            WeeklyScoreWindow(self.gui.root, monitored_videos=self.gui.monitored_videos,
                              video_dbs=self.gui.video_dbs)
        except Exception as e:
            messagebox.showerror("错误", f"打开周刊分数计算失败: {e}")

    # ──────────────────────────────────────────
    # 里程碑统计
    # ──────────────────────────────────────────

    def open_milestone_stats(self):
        try:
            from .milestone_stats import MilestoneStatsWindow
            MilestoneStatsWindow(
                self.gui.root,
                monitored_videos=self.gui.monitored_videos,
                on_add_monitor=self.gui._add_bvid_to_monitor,
            )
        except Exception as e:
            import traceback
            messagebox.showerror("错误", f"打开里程碑统计失败: {e}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────
    # 添加 BV 到监控（里程碑回调）
    # ──────────────────────────────────────────

    def add_bvid_to_monitor(self, bvid: str):
        for v in self.gui.monitored_videos:
            if v.get("bvid") == bvid:
                return
        entry = {"bvid": bvid, "title": bvid, "view_count": 0}
        self.gui.monitored_videos.append(entry)
        self.gui._save_watch_list()
        self.gui.log_panel.add_log("INFO", f"已将 {bvid} 加入监控列表（里程碑入口）")

    # ──────────────────────────────────────────
    # 网络设置
    # ──────────────────────────────────────────

    def open_network_settings(self):
        try:
            from .network_settings import NetworkSettingsWindow
            NetworkSettingsWindow(self.gui.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开网络设置失败: {e}")

    # ──────────────────────────────────────────
    # 系统设置
    # ──────────────────────────────────────────

    def open_settings(self):
        try:
            from .settings_window import SettingsWindow
            SettingsWindow(self.gui.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开系统设置失败: {e}")

    # ──────────────────────────────────────────
    # 导入搜索结果
    # ──────────────────────────────────────────

    def import_search_results(self, videos: list):
        if not videos:
            return

        import threading

        def _worker():
            added, skipped = 0, 0
            from core import bilibili_api
            for v in videos:
                bvid = v.get("bvid", "")
                if not bvid:
                    continue
                if any(mv.get("bvid") == bvid for mv in self.gui.monitored_videos):
                    skipped += 1
                    continue
                try:
                    info = bilibili_api.get_video_info(bvid)
                    if not info:
                        skipped += 1
                        continue
                    video = self.gui._map_api_to_video_dict(bvid, info, fallback=v)
                    self.gui.root.after(0, lambda v=video: self.gui._register_video_to_monitor(v))
                    added += 1
                except Exception as e:
                    self.gui.log_panel.add_log("WARNING", f"导入 {bvid} 失败: {e}")
                    skipped += 1
                time.sleep(0.3)

            self.gui.root.after(0, self.gui._save_watch_list)
            msg = f"成功导入 {added} 个视频"
            if skipped:
                msg += f"（跳过 {skipped} 个：已存在或获取失败）"
            if added or skipped:
                self.gui.root.after(0, lambda: messagebox.showinfo("导入完成", msg))
            self.gui.log_panel.add_log("INFO", f"导入完成：成功 {added}，跳过 {skipped}")

        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────
    # 算法信息
    # ──────────────────────────────────────────

    def open_algorithm_info(self):
        """打开算法信息对话框（现代卡片布局）"""
        dlg = DialogBase(self.gui.root, "算法信息", "540x520", resizable=(True, True))
        dlg.header("预测算法信息", "已加载算法的权重、准确率与模块状态")

        # 轮播容器
        canvas = tk.Canvas(dlg.container, bg=C["bg_base"], highlightthickness=0)
        vsb = ttk.Scrollbar(dlg.container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, pady=(10, 0))
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(24, 0), pady=(10, 0))

        inner = tk.Frame(canvas, bg=C["bg_base"])
        cwin = canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))

        try:
            from algorithms.registry import AlgorithmRegistry
            from algorithms.weight_manager import weight_manager

            algo_names = AlgorithmRegistry.get_algorithm_names()
            algo_infos = AlgorithmRegistry.get_weights_info()

            # 算法概述卡片
            summary = tk.Frame(inner, bg=C["bg_elevated"],
                               highlightthickness=1, highlightbackground=C["border_sub"])
            summary.pack(fill=tk.X, pady=(0, 8), ipadx=12, ipady=10)
            tk.Label(summary, text=f"已加载 {len(algo_names)} 个算法",
                     bg=C["bg_elevated"], fg=C["text_1"],
                     font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=(6, 2))

            # 算法列表
            for info in algo_infos[:20]:
                name = info.get('name', 'Unknown')
                weight = info.get('weight', 1.0)
                accuracy = info.get('accuracy', 0.5)
                card = tk.Frame(inner, bg=C["bg_surface"],
                                highlightthickness=1, highlightbackground=C["border_sub"])
                card.pack(fill=tk.X, pady=2, ipadx=10, ipady=4)
                tk.Label(card, text=name, bg=C["bg_surface"], fg=C["text_1"],
                         font=FONT, anchor="w", width=24).pack(side=tk.LEFT, padx=(8, 4))
                tk.Label(card, text=f"权重 {weight:.2f}", bg=C["bg_surface"],
                         fg=C["accent"], font=FONT_SM, width=12).pack(side=tk.LEFT)
                tk.Label(card, text=f"准确率 {accuracy:.1%}", bg=C["bg_surface"],
                         fg=C["success"], font=FONT_SM).pack(side=tk.LEFT)

            if len(algo_names) > 20:
                tk.Label(inner, text=f"... 还有 {len(algo_names) - 20} 个算法",
                         bg=C["bg_base"], fg=C["text_3"],
                         font=FONT_SM).pack(anchor="w", pady=4)

            # 高级模块状态
            mod_title = tk.Label(inner, text="高级模块状态",
                                 bg=C["bg_base"], fg=C["text_1"],
                                 font=("Microsoft YaHei UI", 10, "bold"),
                                 anchor="w")
            mod_title.pack(fill=tk.X, pady=(12, 4))

            modules = [
                ("onli_learner", "在线学习模块", "algorithms.online_learner", "get_online_learner"),
                ("causal", "因果推断模块", "algorithms.causal_inference", "get_causal_analyzer"),
                ("graph", "图神经网络模块", "algorithms.graph_neural", "get_video_graph"),
            ]
            for mod_id, label, mod_path, attr_name in modules:
                mod_card = tk.Frame(inner, bg=C["bg_surface"],
                                    highlightthickness=1, highlightbackground=C["border_sub"])
                mod_card.pack(fill=tk.X, pady=2, ipadx=10, ipady=4)
                try:
                    __import__(mod_path)
                    status_text = "已加载"
                    status_color = C["success"]
                except ImportError:
                    status_text = "未加载"
                    status_color = C["text_3"]

                tk.Label(mod_card, text=label, bg=C["bg_surface"], fg=C["text_1"],
                         font=FONT, anchor="w").pack(side=tk.LEFT, padx=(8, 8))
                tk.Label(mod_card, text=status_text, bg=C["bg_surface"],
                         fg=status_color, font=FONT_SM).pack(side=tk.RIGHT, padx=8)

        except Exception as e:
            tk.Label(inner, text=f"加载算法信息失败: {e}",
                     bg=C["bg_base"], fg=C["danger"],
                     font=FONT).pack(pady=20)

        dlg.button_row([
            ("关闭", dlg.window.destroy, "primary"),
        ])

    # ──────────────────────────────────────────
    # UP主追踪
    # ──────────────────────────────────────────

    def open_up_tracker(self):
        try:
            from .up_tracker import UpTrackerWindow
            UpTrackerWindow(self.gui.root, api=self.gui.bilibili_api)
        except Exception as e:
            messagebox.showerror("错误", f"打开UP主追踪失败: {e}")

    # ──────────────────────────────────────────
    # 弹幕/评论分析
    # ──────────────────────────────────────────

    def open_danmaku_analysis(self):
        try:
            from .danmaku_analysis import DanmakuAnalysisWindow
            DanmakuAnalysisWindow(self.gui.root, api=self.gui.bilibili_api)
        except Exception as e:
            messagebox.showerror("错误", f"打开弹幕/评论分析失败: {e}")

    # ──────────────────────────────────────────
    # AI智能问答
    # ──────────────────────────────────────────

    def open_ai_qa(self):
        try:
            from .ai_qa_window import AIQAWindow
            AIQAWindow(self.gui.root, gui=self.gui)
        except Exception as e:
            messagebox.showerror("错误", f"打开AI问答失败: {e}")

    # ──────────────────────────────────────────
    # 热门视频发现
    # ──────────────────────────────────────────

    def open_trending_discovery(self):
        try:
            from .trending_discovery import TrendingDiscoveryWindow
            TrendingDiscoveryWindow(self.gui.root, api=self.gui.bilibili_api,
                                    on_add_monitor=self.gui._add_bvid_to_monitor)
        except Exception as e:
            messagebox.showerror("错误", f"打开热门视频发现失败: {e}")

    # ──────────────────────────────────────────
    # 数据大屏
    # ──────────────────────────────────────────

    def open_dashboard(self):
        try:
            from .dashboard_mode import DashboardWindow
            DashboardWindow(self.gui, self.gui.root)
        except Exception as e:
            messagebox.showerror("错误", f"打开数据大屏失败: {e}")

    # ──────────────────────────────────────────
    # 定时导出报告
    # ──────────────────────────────────────────

    def open_report_scheduler(self):
        try:
            from .report_scheduler import ReportSchedulerWindow
            ReportSchedulerWindow(self.gui.root, gui=self.gui)
        except Exception as e:
            messagebox.showerror("错误", f"打开报告定时器失败: {e}")
