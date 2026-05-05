"""
现代化周刊分数计算界面
手动输入或选择已监控视频，计算周刊虚拟歌手中文曲排行榜分数
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO
from ui.dialog_base import DialogBase
from utils.weekly_score import (
    VideoData,
    WeeklyScoreResult,
    calculate_weekly_score,
    calculate_from_dict,
    format_score_result,
)


class WeeklyScoreWindow:
    """周刊分数计算窗口（现代化风格）"""

    def __init__(self, parent=None, monitored_videos: Optional[List[Dict]] = None, video_dbs: Optional[Dict] = None):
        self.dlg = DialogBase(parent, "周刊分数计算", "740x600", resizable=(True, True), modal=False)
        self.window = self.dlg.window
        self.monitored_videos = monitored_videos or []
        self.video_dbs = video_dbs or {}
        self._entries: Dict[str, tk.Entry] = {}

        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("周刊分数计算", "虚拟歌手中文曲排行榜分数计算器")

        # 数据来源选择
        sec = self.dlg.section(padding=8)

        mode_row = tk.Frame(sec, bg=C["bg_elevated"])
        mode_row.pack(fill=tk.X, pady=(0, 6))
        self._mode = tk.StringVar(value="manual")
        tk.Radiobutton(
            mode_row,
            text="手动输入",
            variable=self._mode,
            value="manual",
            bg=C["bg_elevated"],
            command=self._toggle_mode,
        ).pack(side=tk.LEFT, padx=(4, 16))
        tk.Radiobutton(
            mode_row,
            text="选择已监控视频",
            variable=self._mode,
            value="select",
            bg=C["bg_elevated"],
            command=self._toggle_mode,
        ).pack(side=tk.LEFT)

        # 手动输入区域
        self._manual_frame = tk.Frame(sec, bg=C["bg_elevated"])
        self._manual_frame.pack(fill=tk.X)

        labels = [
            ("播放量", "view_count"),
            ("点赞数", "like_count"),
            ("硬币数", "coin_count"),
            ("收藏数", "favorite_count"),
            ("弹幕数", "danmaku_count"),
            ("评论数", "reply_count"),
        ]
        for i, (label, key) in enumerate(labels):
            row, col = divmod(i, 3)
            f = tk.Frame(self._manual_frame, bg=C["bg_elevated"])
            f.grid(row=row, column=col, padx=(0 if col == 0 else 12, 0), pady=3, sticky="w")
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=8, anchor="e").pack(
                side=tk.LEFT, padx=(0, 4)
            )
            entry = tk.Entry(
                f,
                width=14,
                font=FONT_MONO,
                bg=C["bg_base"],
                fg=C["text_1"],
                insertbackground=C["text_1"],
                relief="flat",
                highlightthickness=1,
                highlightbackground=C["border"],
            )
            entry.pack(side=tk.LEFT)
            self._entries[key] = entry

        # 已监控视频下拉
        self._select_frame = tk.Frame(sec, bg=C["bg_elevated"])
        self._select_combo = ttk.Combobox(self._select_frame, state="readonly", width=50, font=FONT)
        for v in self.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "")[:35]
            vals = list(self._select_combo["values"])
            vals.append(f"{bvid}  {title}")
            self._select_combo["values"] = vals
        self._select_combo.pack(fill=tk.X)

        # 操作按钮
        btn_row = tk.Frame(sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="计算分数", command=self._calculate, style="Primary.TButton").pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(btn_row, text="清空", command=self._clear).pack(side=tk.LEFT)

        # 结果区域
        res_sec = tk.Frame(self.dlg.container, bg=C["bg_base"])
        res_sec.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        tk.Label(
            res_sec, text="计算结果", bg=C["bg_base"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
        ).pack(anchor="w")

        text_frame = tk.Frame(res_sec, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        self._result_text = tk.Text(
            text_frame,
            font=("Consolas", 11),
            bg=C["bg_base"],
            fg=C["text_1"],
            relief="flat",
            wrap="none",
            state="disabled",
            cursor="arrow",
            insertbackground=C["text_1"],
        )
        sb = ttk.Scrollbar(text_frame, orient="vertical", command=self._result_text.yview)
        self._result_text.config(yscrollcommand=sb.set)
        self._result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._result_text.tag_configure("title", font=("Consolas", 12, "bold"), foreground=C["text_3"])
        self._result_text.tag_configure("total", font=("Consolas", 14, "bold"), foreground=C["bilibili"])
        self._result_text.tag_configure("separator", foreground=C["text_3"])
        self._result_text.tag_configure("label", foreground=C["text_2"])
        self._result_text.tag_configure("value", foreground=C["text_1"])
        self._result_text.tag_configure("detail", foreground=C["accent"], font=("Consolas", 10))

        self._toggle_mode()

    def _toggle_mode(self):
        if self._mode.get() == "manual":
            self._manual_frame.pack(fill=tk.X)
            self._select_frame.pack_forget()
        else:
            self._manual_frame.pack_forget()
            self._select_frame.pack(fill=tk.X, pady=4)

    def _get_video_data(self) -> Optional[VideoData]:
        if self._mode.get() == "select":
            sel = self._select_combo.current()
            if sel < 0 or sel >= len(self.monitored_videos):
                messagebox.showwarning("提示", "请选择一个视频", parent=self.window)
                return None
            video = self.monitored_videos[sel]
            bvid = video.get("bvid", "")
            if bvid in self.video_dbs:
                try:
                    records = self.video_dbs[bvid].get_all_records()
                    if records:
                        latest = records[-1]
                        return VideoData(
                            view_count=latest.get("view_count", 0),
                            like_count=latest.get("like_count", 0),
                            coin_count=latest.get("coin_count", 0),
                            favorite_count=latest.get("favorite_count", 0),
                            danmaku_count=latest.get("danmaku_count", 0),
                            reply_count=latest.get("reply_count", 0),
                        )
                except Exception as e:
                    logger.debug("从数据库加载视频数据失败: %s", e)
            return VideoData(
                view_count=video.get("view_count", 0),
                like_count=video.get("like_count", 0),
                coin_count=video.get("coin_count", 0),
                favorite_count=video.get("favorite_count", 0),
                danmaku_count=video.get("danmaku_count", 0),
                reply_count=video.get("reply_count", 0),
            )
        else:
            try:
                data = {}
                for key, entry in self._entries.items():
                    val = entry.get().strip()
                    data[key] = int(float(val)) if val else 0
                return VideoData(**data)
            except (ValueError, TypeError):
                messagebox.showwarning("提示", "请输入有效的数字", parent=self.window)
                return None

    def _calculate(self):
        video_data = self._get_video_data()
        if not video_data:
            return
        if video_data.view_count == 0 and video_data.like_count == 0:
            messagebox.showwarning("提示", "请至少输入播放量", parent=self.window)
            return
        result = calculate_weekly_score(video_data)
        self._display_result(video_data, result)

    def _display_result(self, data: VideoData, result: WeeklyScoreResult):
        self._result_text.config(state="normal")
        self._result_text.delete("1.0", "end")

        def add(text, tag="value"):
            self._result_text.insert("end", text, tag)

        add("周刊虚拟歌手中文曲排行榜分数\n", "title")
        add("─" * 42 + "\n", "separator")

        add("输入数据\n", "label")
        add(f"  播放: {data.view_count:>12,}    点赞: {data.like_count:>8,}\n")
        add(f"  硬币: {data.coin_count:>12,}    收藏: {data.favorite_count:>8,}\n")
        add(f"  弹幕: {data.danmaku_count:>12,}    评论: {data.reply_count:>8,}\n")
        add("\n")

        add(f"最终得点: {result.total_score:>12,.2f}\n", "total")
        add("─" * 42 + "\n", "separator")

        items = [
            ("播放得点", result.view_score, f"基础 {result.base_view_score:,.2f} × 修正D {result.correction_d:.4f}"),
            (
                "互动得点",
                result.interaction_score,
                f"({data.danmaku_count + data.reply_count}) × 修正A {result.correction_a:.4f} × 15",
            ),
            ("收藏得点", result.favorite_score, f"{data.favorite_count:,} × 修正B {result.correction_b:.4f}"),
            ("硬币得点", result.coin_score, f"{data.coin_count:,} × 修正C {result.correction_c:.4f}"),
            ("点赞得点", result.like_score, ""),
        ]
        for name, score, detail in items:
            add(f"{name:<8} {score:>12,.2f}\n")
            if detail:
                add(f"         └ {detail}\n", "detail")

        add("─" * 42 + "\n", "separator")
        self._result_text.config(state="disabled")

    def _clear(self):
        for entry in self._entries.values():
            entry.delete(0, "end")
        self._select_combo.set("")
        self._result_text.config(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.config(state="disabled")
