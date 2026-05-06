"""
健康探针详情窗口 — 雷达图 + 详细指标 + 建议
"""

import math
import tkinter as tk
from typing import Optional

from ui.theme import C
from ui.dialog_base import DialogBase
from utils.interaction_quality import (
    calculate_probe,
)


class HealthProbeWindow:
    """健康探针详情窗口，含五维雷达图、详细指标与建议"""

    def __init__(self, parent=None, video: Optional[dict] = None):
        self.dlg = DialogBase(parent, "一键三连健康探针", "780x640", resizable=(True, True), modal=False)
        self.window = self.dlg.window
        self.video = video or {}

        views = self.video.get("view_count", 0)
        likes = self.video.get("like_count", 0)
        coins = self.video.get("coin_count", 0)
        favors = self.video.get("favorite_count", 0)
        shares = self.video.get("share_count", 0)
        self.result = calculate_probe(views, likes, coins, favors, shares)

        self._setup_ui()

    def _setup_ui(self):
        title = self.video.get("title", "未知视频")[:30]
        self.dlg.header(f"一键三连健康探针 — {title}", "基于点赞率·硬币率·收藏率·分享率的综合评估")

        # 上部分：雷达图 + 分数卡片（水平布局）
        top = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        top.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        # 雷达图
        radar_frame = tk.Frame(top, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        radar_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=8, ipady=8)

        self._radar_canvas = tk.Canvas(radar_frame, bg=C["bg_elevated"], width=280, height=240, highlightthickness=0)
        self._radar_canvas.pack(fill=tk.BOTH, expand=True)
        self._radar_canvas.bind("<Configure>", lambda e: self._draw_radar())

        # 右侧摘要卡片
        summary = tk.Frame(top, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        summary.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(12, 0), ipadx=18, ipady=14)

        score = self.result.health_score
        grade = self.result.health_grade

        # 大分数
        grade_colors = {"S": "#fb7299", "A": "#23ade5", "B": "#42b983", "C": "#f5a623", "D": "#e74c3c"}
        gc = grade_colors.get(grade, C["text_1"])
        tk.Label(summary, text=f"{score:.0f}", bg=C["bg_elevated"], fg=gc, font=("Consolas", 48, "bold")).pack(
            anchor="center", pady=(10, 0)
        )
        tk.Label(
            summary, text=f"评级 {grade}", bg=C["bg_elevated"], fg=gc, font=("Microsoft YaHei UI", 16, "bold")
        ).pack(anchor="center")
        tk.Label(
            summary,
            text=f"{len(self.result.anomalies)} 项异常",
            bg=C["bg_elevated"],
            fg=C["danger"] if self.result.anomalies else C["success"],
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="center", pady=(6, 0))

        # 比率小卡片
        stat_frame = tk.Frame(summary, bg=C["bg_elevated"])
        stat_frame.pack(anchor="center", pady=(12, 0))
        items = [
            ("点赞率", self.result.like_rate, "%"),
            ("硬币率", self.result.coin_rate, "%"),
            ("收藏率", self.result.favorite_rate, "%"),
            ("分享率", self.result.share_rate, "%"),
        ]
        for label, val, unit in items:
            sf = tk.Frame(stat_frame, bg=C["bg_elevated"])
            sf.pack(fill=tk.X, pady=1)
            tk.Label(
                sf, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9), width=8, anchor="w"
            ).pack(side=tk.LEFT)
            tk.Label(sf, text=f"{val:.2f}{unit}", bg=C["bg_elevated"], fg=C["text_1"], font=("Consolas", 10)).pack(
                side=tk.RIGHT
            )

        # 下部分：异常与建议
        bottom = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        bottom.pack(fill=tk.X, padx=24, pady=(12, 0))

        if self.result.anomalies:
            sec = self.dlg.section(title="⚠ 异常项", parent=bottom, padding=8)
            for a in self.result.anomalies:
                tk.Label(
                    sec,
                    text=f"  • {a}",
                    bg=C["bg_elevated"],
                    fg=C["danger"],
                    font=("Microsoft YaHei UI", 9),
                    anchor="w",
                ).pack(fill=tk.X, pady=1)

        if self.result.tips:
            sec2 = self.dlg.section(title="💡 建议", parent=bottom, padding=8)
            for t in self.result.tips:
                tk.Label(
                    sec2,
                    text=f"  • {t}",
                    bg=C["bg_elevated"],
                    fg=C["text_1"],
                    font=("Microsoft YaHei UI", 9),
                    anchor="w",
                ).pack(fill=tk.X, pady=1)

        self.dlg.button_row([("关闭", self.window.destroy, "default")])

        # 延迟绘制雷达图
        self.window.after(200, self._draw_radar)

    def _draw_radar(self):
        c = self._radar_canvas
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 50 or H < 50:
            self.window.after(200, self._draw_radar)
            return

        c.delete("all")
        cx, cy = W // 2, H // 2
        radius = min(W, H) * 0.35

        labels = ["点赞率", "硬币率", "收藏率", "分享率"]
        # 归一化：0-100% 映射到 0-radius
        # 正常上界视为 12%（让低值也能看到形状）
        values = [
            min(self.result.like_rate, 15),
            min(self.result.coin_rate, 15),
            min(self.result.favorite_rate, 15),
            min(self.result.share_rate, 15),
        ]
        max_val = 15.0

        angles = [i * math.pi * 2 / 4 - math.pi / 2 for i in range(4)]

        # 网格
        for ring in range(1, 5):
            r = radius * ring / 4
            pts = []
            for ang in angles:
                pts.extend([cx + r * math.cos(ang), cy + r * math.sin(ang)])
            c.create_polygon(*pts, outline=C["border_sub"], fill="", width=1)

        # 轴
        for ang, lbl in zip(angles, labels):
            x2 = cx + radius * 1.15 * math.cos(ang)
            y2 = cy + radius * 1.15 * math.sin(ang)
            c.create_line(
                cx, cy, cx + radius * math.cos(ang), cy + radius * math.sin(ang), fill=C["border_sub"], width=1
            )
            c.create_text(x2, y2, text=lbl, fill=C["text_2"], font=("Microsoft YaHei UI", 9))

        # 数据多边形
        pts = []
        for val, ang in zip(values, angles):
            r = radius * val / max_val
            pts.extend([cx + r * math.cos(ang), cy + r * math.sin(ang)])
        c.create_polygon(*pts, fill="#fb729944", outline="#fb7299", width=2)

        # 数据点
        for val, ang in zip(values, angles):
            r = radius * val / max_val
            x = cx + r * math.cos(ang)
            y = cy + r * math.sin(ang)
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#fb7299", outline="")


def open_health_probe(parent, video):
    HealthProbeWindow(parent, video)
