"""
周刊分数计算界面
手动输入或选择已监控视频，计算周刊虚拟歌手中文曲排行榜分数
"""
import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y
from typing import List, Dict, Optional

from utils.weekly_score import (
    VideoData, WeeklyScoreResult,
    calculate_weekly_score, calculate_from_dict,
    format_score_result
)


class WeeklyScoreWindow:
    """周刊分数计算窗口"""

    def __init__(self, parent=None,
                 monitored_videos: Optional[List[Dict]] = None,
                 video_dbs: Optional[Dict] = None):
        self.window = tk.Toplevel(parent)
        self.window.title("周刊分数计算")
        self.window.geometry("720x580")
        self.window.transient(parent)

        self.monitored_videos = monitored_videos or []
        self.video_dbs = video_dbs or {}

        self._setup_ui()

    def _setup_ui(self):
        # 顶部：选择已监控视频 或 手动输入
        top_frame = tk.LabelFrame(self.window, text="视频数据来源",
                                  padx=8, pady=6)
        top_frame.pack(fill=X, padx=12, pady=(12, 4))

        # 选择模式
        mode_frame = tk.Frame(top_frame)
        mode_frame.pack(fill=X)

        self._mode = tk.StringVar(value="manual")
        tk.Radiobutton(mode_frame, text="手动输入", variable=self._mode,
                       value="manual", command=self._toggle_mode).pack(side=LEFT, padx=4)
        tk.Radiobutton(mode_frame, text="选择已监控视频", variable=self._mode,
                       value="select", command=self._toggle_mode).pack(side=LEFT, padx=4)

        # 已监控视频下拉
        self._select_frame = tk.Frame(top_frame)
        self._select_combo = ttk.Combobox(self._select_frame, state="readonly",
                                          width=50)
        for v in self.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "")[:35]
            self._select_combo["values"] = (*self._select_combo["values"],
                                            f"{bvid}  {title}")
        self._select_combo.pack(fill=X, pady=4)

        # 手动输入区域
        self._manual_frame = tk.Frame(top_frame)
        self._manual_frame.pack(fill=X)

        labels = [
            ("播放量:", "view_count"),
            ("点赞数:", "like_count"),
            ("硬币数:", "coin_count"),
            ("收藏数:", "favorite_count"),
            ("弹幕数:", "danmaku_count"),
            ("评论数:", "reply_count"),
        ]

        self._entries: Dict[str, tk.Entry] = {}
        for i, (label, key) in enumerate(labels):
            row, col = divmod(i, 3)
            tk.Label(self._manual_frame, text=label, width=8,
                     anchor="e").grid(row=row, column=col * 2,
                                      padx=(4 if col > 0 else 0, 2), pady=3,
                                      sticky="e")
            entry = tk.Entry(self._manual_frame, width=14)
            entry.grid(row=row, column=col * 2 + 1, padx=2, pady=3,
                       sticky="w")
            self._entries[key] = entry

        # 计算按钮
        btn_bar = tk.Frame(top_frame)
        btn_bar.pack(fill=X, pady=(8, 0))
        ttk.Button(btn_bar, text="计算分数",
                   command=self._calculate).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="清空",
                   command=self._clear).pack(side=tk.LEFT, padx=4)

        # 结果区域
        result_frame = tk.LabelFrame(self.window, text="计算结果",
                                     padx=8, pady=6)
        result_frame.pack(fill=BOTH, expand=True, padx=12, pady=8)

        self._result_text = tk.Text(result_frame, font=("Consolas", 11),
                                    bg="#f8f8f2", fg="#282a36",
                                    relief="flat", wrap="none",
                                    state="disabled")
        sb = ttk.Scrollbar(result_frame, orient="vertical",
                           command=self._result_text.yview)
        self._result_text.config(yscrollcommand=sb.set)
        self._result_text.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        # 配置颜色标签
        self._result_text.tag_configure("title", font=("Consolas", 12, "bold"),
                                        foreground="#44475a")
        self._result_text.tag_configure("total", font=("Consolas", 14, "bold"),
                                        foreground="#bd93f9")
        self._result_text.tag_configure("separator", foreground="#6272a4")
        self._result_text.tag_configure("label", foreground="#6272a4")
        self._result_text.tag_configure("value", foreground="#282a36")
        self._result_text.tag_configure("detail", foreground="#8be9fd",
                                        font=("Consolas", 10))

        # 初始模式
        self._toggle_mode()

    def _toggle_mode(self):
        if self._mode.get() == "manual":
            self._manual_frame.pack(fill=X)
            self._select_frame.pack_forget()
        else:
            self._manual_frame.pack_forget()
            self._select_frame.pack(fill=X, pady=4)

    def _get_video_data(self) -> Optional[VideoData]:
        """获取视频数据"""
        if self._mode.get() == "select":
            sel = self._select_combo.current()
            if sel < 0 or sel >= len(self.monitored_videos):
                messagebox.showwarning("提示", "请选择一个视频",
                                       parent=self.window)
                return None
            video = self.monitored_videos[sel]
            bvid = video.get("bvid", "")

            # 尝试从 video_dbs 获取数据
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
                except Exception:
                    pass

            # 回退到 monitored_videos 中的数据
            return VideoData(
                view_count=video.get("view_count", 0),
                like_count=video.get("like_count", 0),
                coin_count=video.get("coin_count", 0),
                favorite_count=video.get("favorite_count", 0),
                danmaku_count=video.get("danmaku_count", 0),
                reply_count=video.get("reply_count", 0),
            )
        else:
            # 手动输入
            try:
                data = {}
                for key, entry in self._entries.items():
                    val = entry.get().strip()
                    if not val:
                        data[key] = 0
                    else:
                        data[key] = int(float(val))
                return VideoData(**data)
            except (ValueError, TypeError):
                messagebox.showwarning("提示", "请输入有效的数字",
                                       parent=self.window)
                return None

    def _calculate(self):
        video_data = self._get_video_data()
        if not video_data:
            return

        # 检查是否有有效数据
        if video_data.view_count == 0 and video_data.like_count == 0:
            messagebox.showwarning("提示", "请至少输入播放量",
                                   parent=self.window)
            return

        result = calculate_weekly_score(video_data)
        self._display_result(video_data, result)

    def _display_result(self, data: VideoData, result: WeeklyScoreResult):
        """格式化显示结果"""
        self._result_text.config(state="normal")
        self._result_text.delete("1.0", "end")

        def add(text, tag="value"):
            self._result_text.insert("end", text, tag)

        add("周刊虚拟歌手中文曲排行榜分数\n", "title")
        add("─" * 42 + "\n", "separator")

        # 视频数据摘要
        add("输入数据\n", "label")
        add(f"  播放: {data.view_count:>12,}    点赞: {data.like_count:>8,}\n")
        add(f"  硬币: {data.coin_count:>12,}    收藏: {data.favorite_count:>8,}\n")
        add(f"  弹幕: {data.danmaku_count:>12,}    评论: {data.reply_count:>8,}\n")
        add("\n")

        # 最终得点
        add(f"最终得点: {result.total_score:>12,.2f}\n", "total")
        add("─" * 42 + "\n", "separator")

        # 各项得点
        items = [
            ("播放得点", result.view_score, f"基础 {result.base_view_score:,.2f} × 修正D {result.correction_d:.4f}"),
            ("互动得点", result.interaction_score, f"({data.danmaku_count + data.reply_count}) × 修正A {result.correction_a:.4f} × 15"),
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
