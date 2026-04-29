"""
对话框模块
集中管理所有弹窗窗口
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import re

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num, FAST_GAP, FAST_INTERVAL


class Dialogs:
    """所有对话框的统一入口"""

    def __init__(self, gui):
        self.gui = gui

    # ──────────────────────────────────────────
    # 刷新间隔设置
    # ──────────────────────────────────────────

    def open_interval_settings(self):
        dialog = tk.Toplevel(self.gui.root)
        dialog.title("刷新间隔设置")
        dialog.geometry("320x220")
        dialog.configure(bg=C["bg_surface"])
        dialog.transient(self.gui.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(dialog, text="普通刷新间隔（秒）：", bg=C["bg_surface"], fg=C["text_1"],
                 font=FONT).pack(pady=(20, 6))

        spin_f = tk.Frame(dialog, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border"])
        spin_f.pack(padx=40, fill=tk.X)
        var = tk.IntVar(value=self.gui.DEFAULT_INTERVAL)
        ttk.Spinbox(spin_f, from_=10, to=3600, textvariable=var, width=10).pack(padx=8, pady=6)
        tk.Label(dialog, text=f"距阈值 < {FAST_GAP} 时自动切换快速模式（{FAST_INTERVAL}s）",
                 bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM, wraplength=280).pack(pady=6)

        def _save():
            self.gui.DEFAULT_INTERVAL = var.get()
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                timer = self.gui._video_timers.get(bvid)
                if timer and timer["interval"] != self.gui.FAST_INTERVAL:
                    self.gui._register_video_timer(bvid)
            dialog.destroy()

        btn_f = tk.Frame(dialog, bg=C["bg_surface"])
        btn_f.pack(pady=14)
        ttk.Button(btn_f, text="保存", style="Primary.TButton", command=_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_f, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=6)

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
                # 主线程已在 import_search_results 中判断，这里再检查一次保险
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
                time.sleep(0.3)  # 每个视频间隔 0.3s，避免集中请求

            self.gui.root.after(0, self.gui._save_watch_list)
            msg = f"成功导入 {added} 个视频"
            if skipped:
                msg += f"（跳过 {skipped} 个：已存在或获取失败）"
            if added or skipped:
                self.gui.root.after(0, lambda: messagebox.showinfo("导入完成", msg))
            self.gui.log_panel.add_log("INFO", f"导入完成：成功 {added}，跳过 {skipped}")

        threading.Thread(target=_worker, daemon=True).start()
