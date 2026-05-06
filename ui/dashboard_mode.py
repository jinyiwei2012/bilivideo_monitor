"""
数据大屏模式 — 全屏无边框自动轮播数据展示
"""

import tkinter as tk
from tkinter import ttk
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from ui.theme import C
from ui.helpers import fmt_num

# 大屏颜色
_DASH_COLORS = {
    "bg": "#0d1117",
    "card_bg": "#161b22",
    "text_1": "#f0f6fc",
    "text_2": "#8b949e",
    "accent": "#58a6ff",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
    "bilibili": "#fb7299",
}


class DashboardWindow:
    """全屏数据大屏 — 自动轮播 4 页"""

    def __init__(self, gui, parent=None):
        self.gui = gui
        self.window = tk.Toplevel(parent)
        self.window.attributes("-fullscreen", True)
        self.window.configure(bg=_DASH_COLORS["bg"])
        self.window.bind("<Escape>", lambda e: self.window.destroy())
        self.window.bind("<F11>", lambda e: self.window.destroy())

        self._page = 0
        self._total_pages = 4
        self._animating = True

        self._setup_ui()
        self._show_page(0)
        self._start_rotation()

    def _setup_ui(self):
        self._main = tk.Frame(self.window, bg=_DASH_COLORS["bg"])
        self._main.pack(fill=tk.BOTH, expand=True)

        # 顶部标题
        self._header = tk.Frame(self._main, bg=_DASH_COLORS["bg"])
        self._header.pack(fill=tk.X, padx=40, pady=(20, 0))
        tk.Label(
            self._header,
            text="📊 数据大屏",
            bg=_DASH_COLORS["bg"],
            fg=_DASH_COLORS["text_1"],
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(side=tk.LEFT)
        self._time_lbl = tk.Label(
            self._header, text="", bg=_DASH_COLORS["bg"], fg=_DASH_COLORS["text_2"], font=("Microsoft YaHei UI", 12)
        )
        self._time_lbl.pack(side=tk.RIGHT)
        self._update_time()

        # 页面指示器
        self._dots = tk.Frame(self._main, bg=_DASH_COLORS["bg"])
        self._dots.pack(pady=(8, 0))
        self._dot_widgets = []
        for i in range(self._total_pages):
            d = tk.Label(
                self._dots, text="●", bg=_DASH_COLORS["bg"], fg=_DASH_COLORS["text_2"], font=("Microsoft YaHei UI", 8)
            )
            d.pack(side=tk.LEFT, padx=4)
            self._dot_widgets.append(d)

        # 内容区
        self._content = tk.Frame(self._main, bg=_DASH_COLORS["bg"])
        self._content.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)

    def _update_time(self):
        self._time_lbl.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if self._animating:
            self.window.after(1000, self._update_time)

    def _start_rotation(self):
        if not self._animating:
            return
        self.window.after(15000, self._next_page)

    def _next_page(self):
        if not self._animating:
            return
        self._page = (self._page + 1) % self._total_pages
        self._show_page(self._page)
        self._start_rotation()

    def _show_page(self, page: int):
        for w in self._content.winfo_children():
            w.destroy()
        for i, d in enumerate(self._dot_widgets):
            d.config(fg=_DASH_COLORS["accent"] if i == page else _DASH_COLORS["text_2"])

        pages = [
            self._build_overview,
            self._build_ranking,
            self._build_prediction,
            self._build_health,
        ]
        if 0 <= page < len(pages):
            pages[page]()

    # ── 第1页：总览 ────────────────────────────
    def _build_overview(self):
        videos = self.gui.monitored_videos
        total = len(videos)
        total_views = sum(v.get("view_count", 0) for v in videos)
        total_likes = sum(v.get("like_count", 0) for v in videos)
        achieved = sum(1 for v in videos if v.get("view_count", 0) >= 10000)

        # 4大指标卡
        stat_row = tk.Frame(self._content, bg=_DASH_COLORS["bg"])
        stat_row.pack(fill=tk.X, pady=20)
        cards = [
            ("监控总数", f"{total}", _DASH_COLORS["accent"]),
            ("总播放量", _fmt(total_views), _DASH_COLORS["bilibili"]),
            ("总互动", _fmt(total_likes), _DASH_COLORS["success"]),
            ("已达标(万)", f"{achieved}", _DASH_COLORS["warning"]),
        ]
        for label, val, color in cards:
            c = tk.Frame(stat_row, bg=_DASH_COLORS["card_bg"], highlightthickness=1, highlightbackground="#30363d")
            c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, ipady=30)
            tk.Label(
                c, text=label, bg=_DASH_COLORS["card_bg"], fg=_DASH_COLORS["text_2"], font=("Microsoft YaHei UI", 12)
            ).pack()
            tk.Label(c, text=val, bg=_DASH_COLORS["card_bg"], fg=color, font=("Consolas", 28, "bold")).pack(pady=(8, 0))

        # 最近视频列表
        titles = ["视频列表"]
        cols = ["BV号", "标题", "播放", "点赞", "弹幕"]
        table_frame = tk.Frame(
            self._content, bg=_DASH_COLORS["card_bg"], highlightthickness=1, highlightbackground="#30363d"
        )
        table_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8, ipady=10)
        tk.Label(
            table_frame,
            text=titles[0],
            bg=_DASH_COLORS["card_bg"],
            fg=_DASH_COLORS["text_2"],
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(8, 4))

        for v in videos[:8]:
            row = tk.Frame(table_frame, bg=_DASH_COLORS["card_bg"])
            row.pack(fill=tk.X, padx=12, pady=1)
            tk.Label(
                row,
                text=v.get("bvid", "")[:12],
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["accent"],
                font=("Consolas", 9),
                width=14,
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=v.get("title", "")[:30],
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_1"],
                font=("Microsoft YaHei UI", 9),
                width=35,
                anchor="w",
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=_fmt(v.get("view_count", 0)),
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_2"],
                font=("Consolas", 9),
                width=12,
                anchor="e",
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=_fmt(v.get("like_count", 0)),
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_2"],
                font=("Consolas", 9),
                width=10,
                anchor="e",
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=_fmt(v.get("danmaku_count", 0)),
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_2"],
                font=("Consolas", 9),
                width=10,
                anchor="e",
            ).pack(side=tk.LEFT)

    # ── 第2页：排行 ────────────────────────────
    def _build_ranking(self):
        videos = sorted(self.gui.monitored_videos, key=lambda v: v.get("view_count", 0), reverse=True)
        if not videos:
            tk.Label(
                self._content,
                text="暂无数据",
                bg=_DASH_COLORS["bg"],
                fg=_DASH_COLORS["text_2"],
                font=("Microsoft YaHei UI", 16),
            ).pack()
            return

        tk.Label(
            self._content,
            text="🏆 播放量排行 Top10",
            bg=_DASH_COLORS["bg"],
            fg=_DASH_COLORS["text_1"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w")

        chart_frame = tk.Frame(self._content, bg=_DASH_COLORS["bg"])
        chart_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        max_views = videos[0].get("view_count", 1) or 1
        canvas_w = 700
        bar_h = 36
        top = videos[:10]

        c = tk.Canvas(
            chart_frame, bg=_DASH_COLORS["bg"], width=canvas_w, height=len(top) * bar_h + 20, highlightthickness=0
        )
        c.pack(anchor="w")

        for i, v in enumerate(top):
            views = v.get("view_count", 0)
            bar_w = max(40, int(views / max_views * (canvas_w - 200)))
            y = 10 + i * bar_h

            # 排名圆
            rank_color = _DASH_COLORS["danger"] if i < 3 else _DASH_COLORS["text_2"]
            c.create_rectangle(
                10,
                y + 6,
                10 + bar_w,
                y + bar_h - 6,
                fill=_DASH_COLORS["accent"],
                outline="",
                stipple="" if i < 3 else "gray50",
            )
            c.create_text(16, y + bar_h // 2, text=f"#{i + 1}", fill="white", font=("Consolas", 10, "bold"), anchor="w")
            c.create_text(
                24 + bar_w,
                y + bar_h // 2,
                text=f"{v.get('title', '')[:20]}  {_fmt(views)}",
                fill=_DASH_COLORS["text_1"],
                font=("Microsoft YaHei UI", 10),
                anchor="w",
            )

    # ── 第3页：预测 ────────────────────────────
    def _build_prediction(self):
        tk.Label(
            self._content,
            text="🎯 预测总览",
            bg=_DASH_COLORS["bg"],
            fg=_DASH_COLORS["text_1"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w")

        row = tk.Frame(self._content, bg=_DASH_COLORS["bg"])
        row.pack(fill=tk.X, pady=20)

        from ui.helpers import THRESHOLDS, THRESHOLD_NAMES

        for v in self.gui.monitored_videos[:6]:
            views = v.get("view_count", 0)
            card = tk.Frame(row, bg=_DASH_COLORS["card_bg"], highlightthickness=1, highlightbackground="#30363d")
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, ipady=14)

            tk.Label(
                card,
                text=v.get("title", "")[:18],
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_1"],
                font=("Microsoft YaHei UI", 10, "bold"),
            ).pack(anchor="w", padx=10, pady=(8, 2))
            tk.Label(
                card,
                text=f"播放: {_fmt(views)}",
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_2"],
                font=("Consolas", 10),
            ).pack(anchor="w", padx=10)

            # 阈值进度
            for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
                pct = min(100, views / t * 100) if t > 0 else 0
                gap = t - views
                status = "✅" if views >= t else f"{pct:.0f}%"
                tk.Label(
                    card,
                    text=f"  {name}: {status}",
                    bg=_DASH_COLORS["card_bg"],
                    fg=_DASH_COLORS["success"] if views >= t else _DASH_COLORS["text_2"],
                    font=("Microsoft YaHei UI", 9),
                ).pack(anchor="w", padx=10)

    # ── 第4页：健康 ────────────────────────────
    def _build_health(self):
        tk.Label(
            self._content,
            text="💚 健康概览",
            bg=_DASH_COLORS["bg"],
            fg=_DASH_COLORS["text_1"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w")

        # 预警列表
        import math
        from core.smart_alert import AnomalyDetector

        alert_frame = tk.Frame(
            self._content, bg=_DASH_COLORS["card_bg"], highlightthickness=1, highlightbackground="#30363d"
        )
        alert_frame.pack(fill=tk.BOTH, expand=True, pady=10, ipady=16)

        tk.Label(
            alert_frame,
            text="实时预警",
            bg=_DASH_COLORS["card_bg"],
            fg=_DASH_COLORS["text_2"],
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(8, 4))

        found_alert = False
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            if bvid in self.gui.video_dbs:
                try:
                    records = self.gui.video_dbs[bvid].get_all_records(limit=10)
                    alerts = AnomalyDetector.detect_all(records, bvid=bvid)
                    if alerts:
                        found_alert = True
                        for msg in alerts:
                            row = tk.Frame(alert_frame, bg=_DASH_COLORS["card_bg"])
                            row.pack(fill=tk.X, padx=12, pady=2)
                            tk.Label(
                                row,
                                text=v.get("title", "")[:18],
                                bg=_DASH_COLORS["card_bg"],
                                fg=_DASH_COLORS["warning"],
                                font=("Microsoft YaHei UI", 9),
                            ).pack(side=tk.LEFT, padx=(0, 8))
                            tk.Label(
                                row,
                                text=msg[:60],
                                bg=_DASH_COLORS["card_bg"],
                                fg=_DASH_COLORS["text_1"],
                                font=("Microsoft YaHei UI", 9),
                            ).pack(side=tk.LEFT)
                except Exception as e:
                    logger.debug("渲染预警卡片失败: %s", e)

        if not found_alert:
            tk.Label(
                alert_frame,
                text="✅ 暂无预警",
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["success"],
                font=("Microsoft YaHei UI", 12),
            ).pack(pady=10)

        # 健康探针
        try:
            from utils.interaction_quality import calculate_probe_from_dict

            probe_frame = tk.Frame(
                self._content, bg=_DASH_COLORS["card_bg"], highlightthickness=1, highlightbackground="#30363d"
            )
            probe_frame.pack(fill=tk.BOTH, expand=True, pady=8, ipady=10)

            tk.Label(
                probe_frame,
                text="一键三连健康探针",
                bg=_DASH_COLORS["card_bg"],
                fg=_DASH_COLORS["text_2"],
                font=("Microsoft YaHei UI", 10, "bold"),
                anchor="w",
            ).pack(fill=tk.X, padx=12, pady=(8, 4))

            for v in self.gui.monitored_videos[:6]:
                try:
                    r = calculate_probe_from_dict(v)
                    grade_colors = {
                        "S": _DASH_COLORS["bilibili"],
                        "A": _DASH_COLORS["accent"],
                        "B": _DASH_COLORS["success"],
                        "C": _DASH_COLORS["warning"],
                        "D": _DASH_COLORS["danger"],
                    }
                    gc = grade_colors.get(r.health_grade, _DASH_COLORS["text_2"])
                    row = tk.Frame(probe_frame, bg=_DASH_COLORS["card_bg"])
                    row.pack(fill=tk.X, padx=12, pady=1)
                    tk.Label(
                        row,
                        text=v.get("title", "")[:20],
                        bg=_DASH_COLORS["card_bg"],
                        fg=_DASH_COLORS["text_1"],
                        font=("Microsoft YaHei UI", 9),
                    ).pack(side=tk.LEFT)
                    tk.Label(
                        row,
                        text=f"{r.health_score:.0f} {r.health_grade}",
                        bg=_DASH_COLORS["card_bg"],
                        fg=gc,
                        font=("Consolas", 11, "bold"),
                    ).pack(side=tk.RIGHT)
                except Exception as e:
                    logger.debug("渲染单个视频健康探针失败: %s", e)
        except Exception as e:
            logger.debug("渲染健康探针区域失败: %s", e)


def _fmt(n):
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)
