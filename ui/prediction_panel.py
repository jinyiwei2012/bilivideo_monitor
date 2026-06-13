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
        # 缓存推流指示器动态标签引用，后续增量更新直接用
        if surge_info and surge_info.get("is_surging"):
            self._cache_surge_refs(self._hero_widgets, surge_frame, surge_info)
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
        """增量更新推流指示器（已有 hero card 时调用）。
        首次渲染创建 widget 并缓存引用，后续仅 .configure() 数值。"""
        frame = hero_widgets.get("surge_frame")
        if frame is None:
            return

        is_surging = surge_info and surge_info.get("is_surging")
        cached = hero_widgets.get("_surge_dynamic")

        # 推流状态切换：需要全量重建或清空
        was_surging = bool(cached)
        if is_surging != was_surging:
            for w in frame.winfo_children():
                w.destroy()
            hero_widgets["_surge_dynamic"] = None
            if is_surging:
                self._build_surge_badge_content(frame, surge_info)
                # 缓存首次创建后的动态标签引用
                self._cache_surge_refs(hero_widgets, frame, surge_info)
            return

        if not is_surging:
            return

        # 同状态：仅更新数值
        self._update_surge_values(cached, surge_info)

    def _cache_surge_refs(self, hero_widgets, frame, surge_info):
        """缓存推流指示器中的动态标签引用，供增量更新使用。"""
        refs = {}
        surge_type = surge_info.get("surge_type", "moderate")
        # 遍历 frame 子 widget 找到所有 CTkLabel
        all_labels = []
        def _collect(w):
            for child in w.winfo_children():
                if isinstance(child, ctk.CTkLabel):
                    all_labels.append(child)
                _collect(child)
        _collect(frame)
        # 按顺序缓存：badge_text, detail_text, cur_vel, baseline_vel, daily_vel
        refs["badge"] = all_labels[0] if len(all_labels) > 0 else None
        refs["detail"] = all_labels[1] if len(all_labels) > 1 else None
        refs["cur_vel"] = all_labels[2] if len(all_labels) > 2 else None
        refs["baseline"] = all_labels[3] if len(all_labels) > 3 else None
        refs["daily"] = all_labels[5] if len(all_labels) > 5 else None  # skip separator at idx 4
        hero_widgets["_surge_dynamic"] = refs

    @staticmethod
    def _update_surge_values(refs, surge_info):
        """仅更新推流指示器的数值文本。"""
        if not refs:
            return
        surge_label = surge_info.get("surge_label", "📈 推流中")
        surge_mag = surge_info.get("surge_magnitude", 1.0)
        confidence = surge_info.get("surge_confidence", 0.0)
        decay_hl = surge_info.get("decay_half_life_hours", 6.0)
        surge_vel = surge_info.get("surge_velocity", 0)
        baseline = surge_info.get("baseline_velocity", 0)
        daily_vel = surge_info.get("daily_velocity")
        period_ratio = surge_info.get("period_comparison", {}).get("daily_ratio")

        if refs.get("badge"):
            refs["badge"].configure(text=f"  {surge_label}  ")
        if refs.get("detail"):
            refs["detail"].configure(
                text=f"· {surge_mag:.1f}x · 置信度 {confidence*100:.0f}% · 衰退 {decay_hl:.1f}h"
            )
        if refs.get("cur_vel"):
            refs["cur_vel"].configure(text=f"当前 +{fmt_num(surge_vel)}/h")
        if refs.get("baseline"):
            refs["baseline"].configure(text=f"基线 +{fmt_num(baseline)}/h")
        if refs.get("daily") and daily_vel is not None:
            refs["daily"].configure(text=f"昨日同期 +{fmt_num(daily_vel)}/h")

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
        self._info_bvid = None
        self._info_dynamic = {}  # {key: widget} for incremental value updates

    def update_info(self, video, history, prediction_result):
        """更新右侧信息面板。
        首次渲染创建全部 widget 并缓存动态标签引用；
        同视频后续更新仅 .configure() 数值文本。"""
        bvid = video.get("bvid", "")
        same_video = bvid and bvid == getattr(self, "_info_bvid", None) and self._info_content

        if same_video:
            self._update_info_values(video, history, prediction_result)
            return

        self._info_bvid = bvid
        self._clear_info()
        self._build_info_static(video, history, prediction_result)
        self._info_content = True

    # ── Phase 1: full widget creation (first render) ──

    def _build_info_static(self, video, history, prediction_result):
        """创建全部信息面板 widget 并缓存动态标签引用。"""
        f = self._info_frame
        dyn = self._info_dynamic = {}
        views = max(video.get("view_count", 0), 1)

        # ── 互动率概览 ──
        self._section_title(f, "📊 互动率概览")
        grid = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        grid.pack(fill=tk.X, padx=10, pady=(0, 6))
        rate_keys = ["like", "coin", "favorite", "share", "danmaku"]
        rate_labels = ["👍 点赞率", "🪙 投币率", "⭐ 收藏率", "🔗 分享率", "💬 弹幕率"]
        for i, (rlbl, rkey) in enumerate(zip(rate_labels, rate_keys)):
            row, col = divmod(i, 2)
            cell = ctk.CTkFrame(grid, fg_color=C["bg_elevated"], corner_radius=4, height=28)
            cell.grid(row=row, column=col, padx=2, pady=1, sticky="ew")
            grid.grid_columnconfigure(col, weight=1, uniform="stats")
            ctk.CTkLabel(cell, text=rlbl, text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
                side=tk.LEFT, padx=(6, 0)
            )
            val_lbl = ctk.CTkLabel(
                cell, text="", text_color=C["text_1"], font=("Consolas", 9, "bold"), fg_color="transparent"
            )
            val_lbl.pack(side=tk.RIGHT, padx=(0, 6))
            dyn[f"rate_{rkey}"] = val_lbl

        # ── 在线人数 ──
        online_frame = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        online_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        online_row = ctk.CTkFrame(online_frame, fg_color=C["bg_elevated"], corner_radius=4, height=28)
        online_row.pack(fill=tk.X)
        ctk.CTkLabel(online_row, text="👁 在线人数", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
            side=tk.LEFT, padx=(6, 0)
        )
        online_val = ctk.CTkLabel(
            online_row, text="", text_color=C["accent"], font=("Consolas", 9), fg_color="transparent"
        )
        online_val.pack(side=tk.RIGHT, padx=(0, 6))
        dyn["online"] = online_val

        # ── 最近记录（容器 + 动态行在 _update 中处理）──
        self._section_title(f, "📋 最近记录")
        dyn["hist_container"] = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        dyn["hist_container"].pack(fill=tk.X, padx=10, pady=(0, 6))
        dyn["hist_rows"] = []  # list of (row_frame, ts_lbl, view_lbl, delta_lbl)

        # ── 算法统计 ──
        self._section_title(f, "🧠 算法统计")
        algo_info = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        algo_info.pack(fill=tk.X, padx=10, pady=(0, 6))
        ar1 = ctk.CTkFrame(algo_info, fg_color=C["bg_elevated"], corner_radius=4, height=28)
        ar1.pack(fill=tk.X)
        ctk.CTkLabel(ar1, text="有效算法", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
            side=tk.LEFT, padx=(6, 0)
        )
        algo_valid = ctk.CTkLabel(
            ar1, text="", text_color=C["success"], font=("Consolas", 9, "bold"), fg_color="transparent"
        )
        algo_valid.pack(side=tk.RIGHT, padx=(0, 6))
        dyn["algo_valid"] = algo_valid

        ar2 = ctk.CTkFrame(algo_info, fg_color=C["bg_elevated"], corner_radius=4, height=28)
        ar2.pack(fill=tk.X, pady=(2, 0))
        ctk.CTkLabel(ar2, text="集成置信度", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ensemble_lbl = ctk.CTkLabel(
            ar2, text="", text_color=C["accent"], font=("Consolas", 9, "bold"), fg_color="transparent"
        )
        ensemble_lbl.pack(side=tk.RIGHT, padx=(0, 6))
        dyn["ensemble"] = ensemble_lbl

        # ── 数据健康 ──
        self._section_title(f, "📡 数据健康")
        health = ctk.CTkFrame(f, fg_color=C["bg_surface"], corner_radius=0)
        health.pack(fill=tk.X, padx=10, pady=(0, 6))
        hr = ctk.CTkFrame(health, fg_color=C["bg_elevated"], corner_radius=4, height=28)
        hr.pack(fill=tk.X)
        ctk.CTkLabel(hr, text="数据点数", text_color=C["text_3"], font=FONT_SM, fg_color="transparent").pack(
            side=tk.LEFT, padx=(6, 0)
        )
        n_records_lbl = ctk.CTkLabel(
            hr, text="", text_color=C["text_1"], font=("Consolas", 9, "bold"), fg_color="transparent"
        )
        n_records_lbl.pack(side=tk.RIGHT, padx=(0, 6))
        dyn["n_records"] = n_records_lbl

        # 首次渲染后立即填充数值
        self._update_info_values(video, history, prediction_result)

    # ── Phase 2: value-only updates ──

    def _update_info_values(self, video, history, prediction_result):
        """仅更新动态数值标签，不创建/销毁任何 widget。"""
        dyn = getattr(self, "_info_dynamic", {})
        if not dyn:
            return

        views = max(video.get("view_count", 0), 1)
        likes = video.get("like_count", 0) or 0
        coins = video.get("coin_count", 0) or 0
        favorites = video.get("favorite_count", 0) or 0
        shares = video.get("share_count", 0) or 0
        danmaku = video.get("danmaku_count", 0) or 0

        # 互动率
        for rkey, val, fmt_fn in [
            ("like", likes, lambda v: f"{v / views * 100:.2f}%"),
            ("coin", coins, lambda v: f"{v / views * 100:.2f}%"),
            ("favorite", favorites, lambda v: f"{v / views * 100:.2f}%"),
            ("share", shares, lambda v: f"{v / views * 100:.2f}%"),
            ("danmaku", danmaku, lambda v: f"{v / views * 100:.2f}%"),
        ]:
            lbl = dyn.get(f"rate_{rkey}")
            if lbl:
                lbl.configure(text=fmt_fn(val))

        # 在线人数
        online_total = video.get("viewers_total", 0)
        online_web = video.get("viewers_web", 0)
        online_app = video.get("viewers_app", 0)
        if dyn.get("online"):
            if online_total > 0:
                dyn["online"].configure(
                    text=f"{fmt_num(online_total)}  (网页{fmt_num(online_web)}/APP{fmt_num(online_app)})"
                )
            else:
                dyn["online"].configure(text="—")

        # 最近记录（增量更新行，避免全量重建）
        self._update_history_rows(history)

        # 算法统计
        if prediction_result:
            valid = prediction_result.get("valid", 0)
            total = prediction_result.get("total", 0)
            ensemble_conf = prediction_result.get("ensemble_confidence", 0)
            if dyn.get("algo_valid"):
                fg = C["success"] if valid > 0 else C["danger"]
                dyn["algo_valid"].configure(text=f"{valid}/{total}", text_color=fg)
            if dyn.get("ensemble"):
                dyn["ensemble"].configure(text=f"{ensemble_conf * 100:.1f}%" if ensemble_conf > 0 else "—")

        # 数据健康
        if dyn.get("n_records"):
            dyn["n_records"].configure(text=str(len(history)) if history else "0")

    def _update_history_rows(self, history):
        """增量更新最近记录行：复用已有 widget，仅在行数变化时增/删。"""
        dyn = getattr(self, "_info_dynamic", {})
        rows = dyn.get("hist_rows", [])
        container = dyn.get("hist_container")
        if not container:
            return

        if not history or len(history) < 2:
            # 清空已有行，显示占位
            for _, _, _, _ in rows:
                pass  # will be destroyed below
            for _, row_fr, _, _ in rows:
                row_fr.destroy()
            rows.clear()
            if not container.winfo_children():
                ctk.CTkLabel(
                    container, text="暂无历史数据", text_color=C["text_3"],
                    font=FONT_SM, fg_color="transparent", anchor="w"
                ).pack(fill=tk.X, pady=4)
            return

        # 清除占位文本
        for w in container.winfo_children():
            if isinstance(w, ctk.CTkLabel) and w.cget("text") == "暂无历史数据":
                w.destroy()

        recent = history[-15:]
        prev_vals = [prev[1] if i > 0 else recent[0][1] for i, prev in enumerate(recent)]

        # 行数不变：复用 widget，只更新文本
        if len(rows) == len(recent):
            for i, (ts, v) in enumerate(recent):
                _, ts_lbl, view_lbl, delta_lbl = rows[i]
                dt_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)[:16]
                ts_lbl.configure(text=dt_str)
                view_lbl.configure(text=fmt_num(v))
                delta_v = v - prev_vals[i] if i > 0 and prev_vals[i] > 0 else 0
                if delta_v > 0:
                    delta_lbl.configure(text=f"+{fmt_num(delta_v)}", text_color=C["success"])
                else:
                    delta_lbl.configure(text="—", text_color=C["text_3"])
        else:
            # 行数变了，全量重建
            for _, row_fr, _, _ in rows:
                row_fr.destroy()
            rows.clear()
            for i, (ts, v) in enumerate(recent):
                dt_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)[:16]
                delta_v = v - prev_vals[i] if i > 0 and prev_vals[i] > 0 else 0
                delta_str = f"+{fmt_num(delta_v)}" if delta_v > 0 else "—"
                delta_c = C["success"] if delta_v > 0 else C["text_3"]

                row_fr = ctk.CTkFrame(container, fg_color=C["bg_surface"], corner_radius=0)
                row_fr.pack(fill=tk.X, pady=1)
                ts_lbl = ctk.CTkLabel(row_fr, text=dt_str, text_color=C["text_3"],
                                      font=("Consolas", 8), fg_color="transparent", width=60, anchor="w")
                ts_lbl.pack(side=tk.LEFT)
                view_lbl = ctk.CTkLabel(row_fr, text=fmt_num(v), text_color=C["text_1"],
                                        font=("Consolas", 9, "bold"), fg_color="transparent", width=60, anchor="e")
                view_lbl.pack(side=tk.RIGHT)
                delta_lbl = ctk.CTkLabel(row_fr, text=delta_str, text_color=delta_c,
                                         font=("Consolas", 8), fg_color="transparent", width=50, anchor="e")
                delta_lbl.pack(side=tk.RIGHT)
                rows.append((row_fr, ts_lbl, view_lbl, delta_lbl))

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
