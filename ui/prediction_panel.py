"""
右侧预测面板模块 - CustomTkinter 版

负责预测英雄卡（加权预测值 + 阈值进度条 + ETA）+ 信息面板（互动率、最近记录、算法统计）。
"""

import tkinter as tk
import customtkinter as ctk
from datetime import datetime, timedelta

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS, fmt_num


class PredictionPanel:
    """右侧预测面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._hero_widgets = {}  # 英雄卡片子控件引用
        self._hero_has_data = False  # 标记英雄卡是否已有数据
        self._info_frame = None  # 信息滚动区域
        self._info_content = None
        self._build_right_panel()

    def _build_right_panel(self):
        """构建右侧面板：预测英雄卡 + 信息滚动区"""
        p = self._parent
        self._pred_hero = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        self._pred_hero.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_pred_hero_empty()

        info_wrap = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        info_wrap.pack(fill=tk.BOTH, expand=True)
        self._info_frame = ctk.CTkScrollableFrame(
            info_wrap,
            fg_color=C["bg_surface"],
            corner_radius=0,
            scrollbar_button_color=C["bg_hover"],
            scrollbar_button_hover_color=C["border"],
        )
        self._info_frame.pack(fill=tk.BOTH, expand=True)

    def _build_pred_hero_empty(self):
        """显示空状态预测英雄卡"""
        if not self._hero_has_data and self._hero_widgets:
            return  # 已有占位，不再重复构建
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        self._hero_widgets = {}
        self._hero_has_data = False
        ctk.CTkLabel(h, text="选择视频后显示预测", text_color=C["text_3"], font=FONT, fg_color="transparent").pack(
            padx=14, pady=14
        )

    def _build_pred_hero(self, weighted_pred, current_views, rate_per_sec, surge_info=None):
        """构建或更新预测英雄卡片

        :param weighted_pred: 加权预测播放量
        :param current_views: 当前播放量
        :param rate_per_sec: 每秒播放量增长速率
        :param surge_info: 推流检测信息 dict (is_surging, surge_label, velocity_history, ...)
        """
        # ── 已有数据时的增量更新 ──
        if self._hero_has_data and "outer" in self._hero_widgets:
            w = self._hero_widgets
            w["val_lbl"].configure(text=fmt_num(weighted_pred))
            delta = weighted_pred - current_views
            delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
            delta_color = C["success"] if delta >= 0 else C["danger"]
            w["delta_lbl"].configure(text=delta_text, text_color=delta_color)
            # 更新速率标签
            if rate_per_sec > 0:
                per_min = rate_per_sec * 60
                per_hour = rate_per_sec * 3600
                if per_hour >= 1:
                    rate_str = f"📈 +{fmt_num(per_hour)}/h"
                elif per_min >= 0.1:
                    rate_str = f"📈 +{per_min:.1f}/min"
                else:
                    rate_str = f"📈 +{rate_per_sec:.2f}/s"
                w["rate_lbl"].configure(text=rate_str)
                w["rate_lbl"].pack(anchor="w", pady=(2, 0))
            else:
                if "rate_lbl" in w:
                    w["rate_lbl"].pack_forget()
            # 更新推流指示器
            self._update_surge_badge(w, surge_info)
            # 更新每个阈值行
            for i, (t, name, col) in enumerate(zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS)):
                if i >= len(w["thr_rows"]):
                    break
                row_data = w["thr_rows"][i]
                pct = min(current_views / t, 1.0)
                row_data["fill_frame"].place(x=0, y=0, relwidth=pct, relheight=1)
                if t <= current_views:
                    eta_str, eta_c = "✓ 已达成", C["success"]
                elif rate_per_sec > 0:
                    need = t - current_views
                    seconds_left = need / rate_per_sec
                    arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                    eta_str = arrive_dt.strftime("%m-%d %H:%M")
                    eta_c = (
                        C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
                    )
                else:
                    eta_str, eta_c = "—", C["text_3"]
                row_data["eta_lbl"].configure(text=eta_str, text_color=eta_c)
            return

        # ── 首次构建 ──
        h = self._pred_hero
        for w in h.winfo_children():
            w.destroy()
        self._hero_widgets = {}
        outer = ctk.CTkFrame(h, fg_color=C["bg_surface"], corner_radius=0)
        outer.pack(fill=tk.X, padx=14, pady=12)

        # 标题
        ctk.CTkLabel(
            outer,
            text="🎯 综合加权预测",
            text_color=C["text_3"],
            font=("Microsoft YaHei UI", 8),
            fg_color="transparent",
        ).pack(anchor="w")

        # 加权预测值
        val_lbl = ctk.CTkLabel(
            outer,
            text=fmt_num(weighted_pred),
            text_color=C["text_1"],
            font=("Consolas", 18, "bold"),
            fg_color="transparent",
        )
        val_lbl.pack(anchor="w", pady=(2, 0))

        # 增长量
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        delta_lbl = ctk.CTkLabel(outer, text=delta_text, text_color=delta_color, font=FONT, fg_color="transparent")
        delta_lbl.pack(anchor="w")

        # 速率指示器
        rate_lbl = None
        if rate_per_sec > 0:
            per_min = rate_per_sec * 60
            per_hour = rate_per_sec * 3600
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            rate_lbl = ctk.CTkLabel(outer, text=rate_str, text_color=C["accent"], font=FONT_SM, fg_color="transparent")
            rate_lbl.pack(anchor="w", pady=(2, 0))

        # ── 推流指示器 ──
        surge_frame = self._build_surge_badge(outer, surge_info)

        tk.Frame(outer, bg=C["border"], height=1).pack(fill=tk.X, pady=6)

        # ── 各阈值进度条 + ETA ──
        thr_rows = []
        for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            row = ctk.CTkFrame(outer, fg_color=C["bg_surface"], corner_radius=0)
            row.pack(fill=tk.X, pady=2)
            ctk.CTkLabel(row, text=name, text_color=C["text_2"], font=FONT_SM, fg_color="transparent", width=38).pack(
                side=tk.LEFT
            )

            bg_bar = ctk.CTkFrame(row, fg_color=C["bg_hover"], height=4, corner_radius=2)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            bg_bar.pack_propagate(False)
            pct = min(current_views / t, 1.0)
            fill_frame = tk.Frame(bg_bar, bg=col, height=4)
            fill_frame.place(x=0, y=0, relwidth=pct, relheight=1)
            if t <= current_views:
                eta_str, eta_c = "✓ 已达成", C["success"]
            elif rate_per_sec > 0:
                need = t - current_views
                seconds_left = need / rate_per_sec
                arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                eta_str = arrive_dt.strftime("%m-%d %H:%M")
                eta_c = C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
            else:
                eta_str, eta_c = "—", C["text_3"]
            eta_lbl = ctk.CTkLabel(
                row, text=eta_str, text_color=eta_c, font=FONT_MONO, fg_color="transparent", width=88, anchor="e"
            )
            eta_lbl.pack(side=tk.LEFT)
            thr_rows.append({"fill_frame": fill_frame, "eta_lbl": eta_lbl})

        self._hero_widgets = {
            "outer": outer,
            "val_lbl": val_lbl,
            "delta_lbl": delta_lbl,
            "rate_lbl": rate_lbl,
            "thr_rows": thr_rows,
            "surge_frame": surge_frame,
            "surge_label": surge_frame.winfo_children()[0] if surge_frame and surge_frame.winfo_children() else None,
        }
        self._hero_has_data = True

    # ── 推流指示器构建/更新 ──────────────────────

    def _build_surge_badge(self, parent, surge_info):
        """构建推流状态指示器，返回容器 frame（无推流时隐藏）。"""
        frame = ctk.CTkFrame(parent, fg_color=C["bg_surface"], corner_radius=0)

        if not surge_info or not surge_info.get("is_surging"):
            return frame  # 空 frame，不显示

        surge_type = surge_info.get("surge_type", "moderate")
        surge_label = surge_info.get("surge_label", "📈 推流中")
        surge_mag = surge_info.get("surge_magnitude", 1.0)
        baseline = surge_info.get("baseline_velocity", 0)
        surge_vel = surge_info.get("surge_velocity", 0)
        daily_vel = surge_info.get("daily_velocity")
        decay_hl = surge_info.get("decay_half_life_hours", 6.0)
        confidence = surge_info.get("surge_confidence", 0.0)

        # 推流颜色
        if surge_type == "strong":
            badge_color = "#ff6b35"  # 橙红
            bg_color = "#fff3e0"
        elif surge_type == "moderate":
            badge_color = "#e6a817"  # 琥珀
            bg_color = "#fffde7"
        else:
            badge_color = "#58a6ff"  # 蓝
            bg_color = "#e8f4fd"

        # 主标签行：🔥 强推流 · 5.0x · 置信度 85%
        header_row = ctk.CTkFrame(frame, fg_color=bg_color, corner_radius=6)
        header_row.pack(fill=tk.X, pady=(4, 0))

        badge = ctk.CTkLabel(
            header_row,
            text=f"  {surge_label}  ",
            text_color=badge_color,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg_color="transparent",
        )
        badge.pack(side=tk.LEFT, padx=(6, 0), pady=3)

        detail = ctk.CTkLabel(
            header_row,
            text=f"· {surge_mag:.1f}x · 置信度 {confidence*100:.0f}% · 衰退 {decay_hl:.1f}h",
            text_color=C["text_3"],
            font=("Microsoft YaHei UI", 7),
            fg_color="transparent",
        )
        detail.pack(side=tk.LEFT, padx=(4, 6), pady=3)

        # 速度对比行
        comp_row = ctk.CTkFrame(frame, fg_color=C["bg_surface"], corner_radius=0)
        comp_row.pack(fill=tk.X, pady=(2, 0))

        # 当前速度
        cur_text = f"当前 +{fmt_num(surge_vel)}/h"
        ctk.CTkLabel(
            comp_row, text=cur_text, text_color=badge_color, font=("Consolas", 8, "bold"), fg_color="transparent"
        ).pack(side=tk.LEFT, padx=(2, 0))

        ctk.CTkLabel(
            comp_row, text=" vs ", text_color=C["text_3"], font=("Consolas", 8), fg_color="transparent"
        ).pack(side=tk.LEFT)

        # 长期基线
        base_text = f"基线 +{fmt_num(baseline)}/h"
        ctk.CTkLabel(
            comp_row, text=base_text, text_color=C["text_2"], font=("Consolas", 8), fg_color="transparent"
        ).pack(side=tk.LEFT)

        # 同日对比（如有数据）
        if daily_vel is not None and daily_vel > 0:
            ctk.CTkLabel(
                comp_row, text=" | ", text_color=C["text_3"], font=("Consolas", 8), fg_color="transparent"
            ).pack(side=tk.LEFT)
            daily_text = f"昨日同期 +{fmt_num(daily_vel)}/h"
            period_ratio = surge_info.get("period_comparison", {}).get("daily_ratio")
            daily_color = C["danger"] if (period_ratio and period_ratio >= 2.0) else C["text_2"]
            ctk.CTkLabel(
                comp_row, text=daily_text, text_color=daily_color, font=("Consolas", 8), fg_color="transparent"
            ).pack(side=tk.LEFT)

        return frame

    def _update_surge_badge(self, hero_widgets, surge_info):
        """增量更新推流指示器（已有 hero card 时调用）。"""
        frame = hero_widgets.get("surge_frame")
        if frame is None:
            return

        # 清除旧内容
        for w in frame.winfo_children():
            w.destroy()

        if not surge_info or not surge_info.get("is_surging"):
            return

        # 重建推流指示器
        self._build_surge_badge_content(frame, surge_info)

    def _build_surge_badge_content(self, frame, surge_info):
        """在已有 frame 中填入推流指示器内容（供增量更新用）。"""
        surge_type = surge_info.get("surge_type", "moderate")
        surge_label = surge_info.get("surge_label", "📈 推流中")
        surge_mag = surge_info.get("surge_magnitude", 1.0)
        baseline = surge_info.get("baseline_velocity", 0)
        surge_vel = surge_info.get("surge_velocity", 0)
        daily_vel = surge_info.get("daily_velocity")
        decay_hl = surge_info.get("decay_half_life_hours", 6.0)
        confidence = surge_info.get("surge_confidence", 0.0)

        if surge_type == "strong":
            badge_color = "#ff6b35"
            bg_color = "#fff3e0"
        elif surge_type == "moderate":
            badge_color = "#e6a817"
            bg_color = "#fffde7"
        else:
            badge_color = "#58a6ff"
            bg_color = "#e8f4fd"

        header_row = ctk.CTkFrame(frame, fg_color=bg_color, corner_radius=6)
        header_row.pack(fill=tk.X, pady=(4, 0))

        badge = ctk.CTkLabel(
            header_row,
            text=f"  {surge_label}  ",
            text_color=badge_color,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg_color="transparent",
        )
        badge.pack(side=tk.LEFT, padx=(6, 0), pady=3)

        detail = ctk.CTkLabel(
            header_row,
            text=f"· {surge_mag:.1f}x · 置信度 {confidence*100:.0f}% · 衰退 {decay_hl:.1f}h",
            text_color=C["text_3"],
            font=("Microsoft YaHei UI", 7),
            fg_color="transparent",
        )
        detail.pack(side=tk.LEFT, padx=(4, 6), pady=3)

        comp_row = ctk.CTkFrame(frame, fg_color=C["bg_surface"], corner_radius=0)
        comp_row.pack(fill=tk.X, pady=(2, 0))

        cur_text = f"当前 +{fmt_num(surge_vel)}/h"
        ctk.CTkLabel(
            comp_row, text=cur_text, text_color=badge_color, font=("Consolas", 8, "bold"), fg_color="transparent"
        ).pack(side=tk.LEFT, padx=(2, 0))

        ctk.CTkLabel(
            comp_row, text=" vs ", text_color=C["text_3"], font=("Consolas", 8), fg_color="transparent"
        ).pack(side=tk.LEFT)

        base_text = f"基线 +{fmt_num(baseline)}/h"
        ctk.CTkLabel(
            comp_row, text=base_text, text_color=C["text_2"], font=("Consolas", 8), fg_color="transparent"
        ).pack(side=tk.LEFT)

        if daily_vel is not None and daily_vel > 0:
            ctk.CTkLabel(
                comp_row, text=" | ", text_color=C["text_3"], font=("Consolas", 8), fg_color="transparent"
            ).pack(side=tk.LEFT)
            daily_text = f"昨日同期 +{fmt_num(daily_vel)}/h"
            period_ratio = surge_info.get("period_comparison", {}).get("daily_ratio")
            daily_color = C["danger"] if (period_ratio and period_ratio >= 2.0) else C["text_2"]
            ctk.CTkLabel(
                comp_row, text=daily_text, text_color=daily_color, font=("Consolas", 8), fg_color="transparent"
            ).pack(side=tk.LEFT)

    def _clear_info(self):
        """清空信息面板内容"""
        for w in self._info_frame.winfo_children():
            w.destroy()
        self._info_content = None

    def update_info(self, video, history, prediction_result):
        """更新右侧信息面板：互动率 + 数据健康 + 算法统计"""
        self._clear_info()
        f = self._info_frame

        # ── 互动率概览 ──
        self._section_title(f, "📊 互动率概览")
        views = max(video.get("view_count", 0), 1)
        likes = video.get("like_count", 0) or 0
        coins = video.get("coin_count", 0) or 0
        favorites = video.get("favorite_count", 0) or 0
        shares = video.get("share_count", 0) or 0
        danmaku = video.get("danmaku_count", 0) or 0

        stats = [
            ("👍 点赞率", f"{likes / views * 100:.2f}%"),
            ("🪙 投币率", f"{coins / views * 100:.2f}%"),
            ("⭐ 收藏率", f"{favorites / views * 100:.2f}%"),
            ("🔗 分享率", f"{shares / views * 100:.2f}%"),
            ("💬 弹幕率", f"{danmaku / views * 100:.2f}%"),
        ]
        grid = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        grid.pack(fill=tk.X, padx=10, pady=(0, 6))
        for i, (label, val) in enumerate(stats):
            row, col = divmod(i, 2)  # 两列布局
            cell = ctk.CTkFrame(grid, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            cell.grid(row=row, column=col, padx=2, pady=1, sticky="ew")
            grid.grid_columnconfigure(col, weight=1, uniform="stats")
            ctk.CTkLabel(cell, text=label, text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
                side=tk.LEFT, padx=(6, 0)
            )
            ctk.CTkLabel(
                cell, text=val, text_color=C["text_1"], font=("Consolas", 9, "bold"), fg_color="transparent"
            ).pack(side=tk.RIGHT, padx=(0, 6))

        # ── 在线人数 ──
        online_total = video.get("viewers_total", 0)
        online_web = video.get("viewers_web", 0)
        online_app = video.get("viewers_app", 0)
        if online_total > 0:
            online_frame = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
            online_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
            row = ctk.CTkFrame(online_frame, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            row.pack(fill=tk.X)
            ctk.CTkLabel(row, text="👁 在线人数", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
                side=tk.LEFT, padx=(6, 0)
            )
            ctk.CTkLabel(
                row,
                text=f"{fmt_num(online_total)}  (网页{fmt_num(online_web)}/APP{fmt_num(online_app)})",
                text_color=C["accent"],
                font=("Consolas", 9),
                fg_color="transparent",
            ).pack(side=tk.RIGHT, padx=(0, 6))

        # ── 最近记录 ──
        self._section_title(f, "📋 最近记录")
        hist_container = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        hist_container.pack(fill=tk.X, padx=10, pady=(0, 6))
        if history and len(history) > 1:
            recent = history[-15:]  # 只显示最近 15 条
            prev_v = recent[0][1] if len(recent) > 1 else 0
            for ts, v in recent:
                dt_str = (
                    ts.strftime("%m-%d %H:%M")
                    if isinstance(ts, datetime)
                    else str(ts)[:-3] if len(str(ts)) > 16 else str(ts)
                )
                delta_v = v - prev_v if prev_v > 0 else 0
                delta_str = f"+{fmt_num(delta_v)}" if delta_v > 0 else "—"
                delta_c = C["success"] if delta_v > 0 else C["text_3"]
                prev_v = v
                row = ctk.CTkFrame(hist_container, fg_color=C["bg_surface"], corner_radius=0)
                row.pack(fill=tk.X, pady=1)
                ctk.CTkLabel(
                    row,
                    text=dt_str,
                    text_color=C["text_3"],
                    font=("Consolas", 8),
                    fg_color="transparent",
                    width=60,
                    anchor="w",
                ).pack(side=tk.LEFT)
                ctk.CTkLabel(
                    row,
                    text=fmt_num(v),
                    text_color=C["text_1"],
                    font=("Consolas", 9, "bold"),
                    fg_color="transparent",
                    width=60,
                    anchor="e",
                ).pack(side=tk.RIGHT)
                ctk.CTkLabel(
                    row,
                    text=delta_str,
                    text_color=delta_c,
                    font=("Consolas", 8),
                    fg_color="transparent",
                    width=50,
                    anchor="e",
                ).pack(side=tk.RIGHT)
        else:
            ctk.CTkLabel(
                hist_container,
                text="暂无历史数据",
                text_color=C["text_3"],
                font=FONT_SM,
                fg_color="transparent",
                anchor="w",
            ).pack(fill=tk.X, pady=4)

        # ── 算法统计 ──
        self._section_title(f, "🧠 算法统计")
        algo_info = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        algo_info.pack(fill=tk.X, padx=10, pady=(0, 6))
        if prediction_result:
            valid = prediction_result.get("valid", 0)
            total = prediction_result.get("total", 0)
            ensemble_conf = prediction_result.get("ensemble_confidence", 0)
            row = ctk.CTkFrame(algo_info, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            row.pack(fill=tk.X)
            ctk.CTkLabel(row, text="有效算法", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
                side=tk.LEFT, padx=(6, 0)
            )
            ctk.CTkLabel(
                row,
                text=f"{valid}/{total}",
                text_color=C["success"] if valid > 0 else C["danger"],
                font=("Consolas", 9, "bold"),
                fg_color="transparent",
            ).pack(side=tk.RIGHT, padx=(0, 6))
            if ensemble_conf > 0:
                row2 = ctk.CTkFrame(algo_info, fg_color=C["bg_elevated"], corner_radius=4, height=28)
                row2.pack(fill=tk.X, pady=(2, 0))
                ctk.CTkLabel(
                    row2, text="集成置信度", text_color=C["text_3"], font=FONT_SM, fg_color="transparent"
                ).pack(side=tk.LEFT, padx=(6, 0))
                ctk.CTkLabel(
                    row2,
                    text=f"{ensemble_conf * 100:.1f}%",
                    text_color=C["accent"],
                    font=("Consolas", 9, "bold"),
                    fg_color="transparent",
                ).pack(side=tk.RIGHT, padx=(0, 6))
        else:
            ctk.CTkLabel(
                algo_info, text="等待首次预测", text_color=C["text_3"], font=FONT_SM, fg_color="transparent", anchor="w"
            ).pack(fill=tk.X, pady=4)

        # ── 数据健康 ──
        self._section_title(f, "📡 数据健康")
        health = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        health.pack(fill=tk.X, padx=10, pady=(0, 6))
        n_records = len(history) if history else 0
        row = ctk.CTkFrame(health, fg_color=C["bg_elevated"], corner_radius=4, height=28)
        row.pack(fill=tk.X)
        ctk.CTkLabel(row, text="数据点数", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ctk.CTkLabel(
            row, text=str(n_records), text_color=C["text_1"], font=("Consolas", 9, "bold"), fg_color="transparent"
        ).pack(side=tk.RIGHT, padx=(0, 6))

        self._info_content = True

    def _section_title(self, parent, text):
        """绘制一个分节标题"""
        row = ctk.CTkFrame(parent, fg_color=C["bg_surface"], corner_radius=0)
        row.pack(fill=tk.X, padx=10, pady=(8, 2))
        ctk.CTkLabel(
            row, text=text, text_color=C["text_3"], font=("Microsoft YaHei UI", 8, "bold"), fg_color="transparent"
        ).pack(side=tk.LEFT)

    # 兼容旧接口 — 不再显示算法列表，转调 update_info
    def _update_algo_list(self, results, failed):
        bvid = self.gui.selected_bvid
        if not bvid:
            self._clear_info()
            return
        video = self.gui._get_video(bvid)
        if not video:
            self._clear_info()
            return
        history = self.gui.history_data.get(bvid, [])
        cached = self.gui.prediction_results.get(bvid, {})
        self.update_info(video, history, cached)

    @property
    def algo_frame(self):
        return self._info_frame
