"""
弹幕/评论分析窗口 — 情绪饼图、关键词标签云、高频列表
"""
import math
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Optional

from ui.theme import C
from ui.dialog_base import DialogBase


class DanmakuAnalysisWindow:
    """弹幕/评论分析窗口"""

    def __init__(self, parent=None, api=None):
        self.dlg = DialogBase(parent, "弹幕/评论分析", "780x640",
                              resizable=(True, True))
        self.window = self.dlg.window
        self.api = api
        self._texts: List[str] = []
        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("弹幕/评论分析", "抓取弹幕与评论，进行情绪分析与关键词提取")

        # 输入卡片
        sec = self.dlg.section(title="数据源", padding=8)
        row = tk.Frame(sec, bg=C["bg_elevated"])
        row.pack(fill=tk.X)

        tk.Label(row, text="BV号:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self._bv_entry = tk.Entry(row, width=20, font=("Consolas", 10),
                                   bg=C["bg_base"], fg=C["text_1"],
                                   insertbackground=C["text_1"],
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=C["border"])
        self._bv_entry.pack(side=tk.LEFT, padx=(6, 10))

        self._mode_var = tk.StringVar(value="danmaku")
        tk.Radiobutton(row, text="弹幕", variable=self._mode_var,
                       value="danmaku", bg=C["bg_elevated"],
                       command=self._update_hint).pack(side=tk.LEFT, padx=2)
        tk.Radiobutton(row, text="评论", variable=self._mode_var,
                       value="comment", bg=C["bg_elevated"],
                       command=self._update_hint).pack(side=tk.LEFT, padx=2)

        self._fetch_btn = ttk.Button(row, text="抓取并分析",
                                      command=self._analyze,
                                      style="Primary.TButton")
        self._fetch_btn.pack(side=tk.LEFT, padx=(10, 0))

        self._status_lbl = tk.Label(sec, text="", bg=C["bg_elevated"],
                                     fg=C["text_2"], font=("Microsoft YaHei UI", 9))
        self._status_lbl.pack(anchor="w", padx=4, pady=(4, 0))

        # 内容区：情绪饼图(左) + 关键词(右)
        mid = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        mid.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # 左：情绪饼图
        left = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1,
                        highlightbackground=C["border_sub"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)

        tk.Label(left, text="情绪分布", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        self._pie_canvas = tk.Canvas(left, bg=C["bg_elevated"],
                                      width=200, height=180, highlightthickness=0)
        self._pie_canvas.pack(fill=tk.BOTH, expand=True)

        # 右：关键词
        right = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1,
                         highlightbackground=C["border_sub"])
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

        tk.Label(right, text="高频关键词", bg=C["bg_elevated"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        self._kw_text = tk.Text(right, bg=C["bg_base"], fg=C["text_1"],
                                 font=("Microsoft YaHei UI", 10), relief="flat",
                                 state="disabled", cursor="arrow", padx=8, pady=6)
        self._kw_text.pack(fill=tk.BOTH, expand=True)

        # 底部：高频列表
        bottom = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        bottom.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 12))

        list_label = tk.Frame(bottom, bg=C["bg_surface"])
        list_label.pack(fill=tk.X)
        tk.Label(list_label, text="高频弹幕/评论", bg=C["bg_surface"], fg=C["text_2"],
                 font=("Microsoft YaHei UI", 8, "bold")).pack(side=tk.LEFT)

        self._count_lbl = tk.Label(list_label, text="", bg=C["bg_surface"],
                                    fg=C["text_3"], font=("Microsoft YaHei UI", 9))
        self._count_lbl.pack(side=tk.LEFT, padx=12)

        table_frame = tk.Frame(bottom, bg=C["bg_elevated"], highlightthickness=1,
                               highlightbackground=C["border_sub"])
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("序号", "内容", "情绪")
        self._list_tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                        height=6)
        for col in cols:
            self._list_tree.heading(col, text=col)
        self._list_tree.column("序号", width=40, anchor="center")
        self._list_tree.column("内容", width=400)
        self._list_tree.column("情绪", width=60, anchor="center")
        self._list_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(table_frame, orient="vertical",
                           command=self._list_tree.yview)
        self._list_tree.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._update_hint()

    def _update_hint(self):
        mode = self._mode_var.get()
        hint = "输入视频BV号，抓取弹幕分析情感倾向与高频内容"
        self._status_lbl.config(text=hint)

    def _analyze(self):
        bvid = self._bv_entry.get().strip()
        if not bvid:
            messagebox.showwarning("提示", "请输入BV号", parent=self.window)
            return

        if not self.api:
            messagebox.showerror("错误", "API不可用", parent=self.window)
            return

        self._fetch_btn.config(state="disabled")
        self._status_lbl.config(text="正在抓取数据...", fg=C["text_2"])
        self.window.update_idletasks()

        try:
            mode = self._mode_var.get()
            texts = []

            if mode == "danmaku":
                # 先获取视频信息得到 cid
                info = self.api.get_video_info(bvid)
                if not info:
                    self._status_lbl.config(text="获取视频信息失败", fg=C["danger"])
                    self._fetch_btn.config(state="normal")
                    return
                cid = info.get("cid", 0)
                if not cid:
                    self._status_lbl.config(text="无法获取cid", fg=C["danger"])
                    self._fetch_btn.config(state="normal")
                    return

                danmaku = self.api.get_video_danmaku(cid)
                if not danmaku:
                    self._status_lbl.config(text="未获取到弹幕", fg=C["warning"])
                    self._fetch_btn.config(state="normal")
                    return
                texts = [d["text"] for d in danmaku if d.get("text")]
            else:
                # 评论：需要 aid
                info = self.api.get_video_info(bvid)
                if not info:
                    self._status_lbl.config(text="获取视频信息失败", fg=C["danger"])
                    self._fetch_btn.config(state="normal")
                    return
                aid = info.get("aid", 0)
                if not aid:
                    self._status_lbl.config(text="无法获取aid", fg=C["danger"])
                    self._fetch_btn.config(state="normal")
                    return

                comments = self.api.get_video_comments(aid)
                if not comments:
                    self._status_lbl.config(text="未获取到评论", fg=C["warning"])
                    self._fetch_btn.config(state="normal")
                    return
                texts = [c["content"] for c in comments if c.get("content")]

            self._texts = texts
            self._status_lbl.config(
                text=f"抓取成功：共 {len(texts)} 条{mode}",
                fg=C["success"])
            self._display_results(texts)
        except Exception as e:
            self._status_lbl.config(text=f"分析失败: {e}", fg=C["danger"])
        finally:
            self._fetch_btn.config(state="normal")

    def _display_results(self, texts: List[str]):
        from utils.sentiment_analyzer import (
            analyze_sentiment, extract_keywords, generate_word_freq,
        )

        # 情绪分析
        sentiment = analyze_sentiment(texts)
        self._draw_pie(sentiment)

        # 关键词
        keywords = extract_keywords(texts, top_n=30)
        self._display_keywords(keywords)

        # 词频
        freq = generate_word_freq(texts)
        top_freq = sorted(freq.items(), key=lambda x: -x[1])[:20]

        # 更新列表
        for item in self._list_tree.get_children():
            self._list_tree.delete(item)

        # 简单情绪分类（显示列表）
        for i, text in enumerate(texts[:50]):
            from utils.sentiment_analyzer import _tokenize
            tokens = _tokenize(text)
            score = 0
            for token in tokens:
                from utils.sentiment_analyzer import _POSITIVE_WORDS, _NEGATIVE_WORDS
                if token in _POSITIVE_WORDS:
                    score += 1
                elif token in _NEGATIVE_WORDS:
                    score -= 1
            mood = "积极" if score > 0 else ("消极" if score < 0 else "中性")
            self._list_tree.insert("", "end", values=(
                i + 1, text[:60], mood))

        self._count_lbl.config(text=f"共 {len(texts)} 条，显示前 {min(50, len(texts))} 条")

    def _draw_pie(self, sentiment: dict):
        c = self._pie_canvas
        c.delete("all")
        W = c.winfo_width() or 180
        H = c.winfo_height() or 160

        colors = {"positive": "#42b983", "neutral": "#aab0b8", "negative": "#e74c3c"}
        labels_cn = {"positive": "积极", "neutral": "中性", "negative": "消极"}

        data = [(k, v) for k, v in sentiment.items() if v > 0]
        if not data:
            c.create_text(W // 2, H // 2, text="无数据", fill=C["text_3"],
                          font=("Microsoft YaHei UI", 10))
            return

        cx, cy, r = W // 2, H // 2 - 10, min(W, H) // 2 - 20
        start_angle = 0

        for key, val in data:
            angle = val * 360
            if angle <= 0:
                continue
            c.create_arc(cx - r, cy - r, cx + r, cy + r,
                         start=start_angle, extent=angle,
                         fill=colors.get(key, "#aaa"), outline=C["bg_elevated"], width=2)
            # 标签
            mid_angle = start_angle + angle / 2
            lx = cx + (r * 0.65) * math.cos(math.radians(mid_angle))
            ly = cy - (r * 0.65) * math.sin(math.radians(mid_angle))
            if val >= 0.05:
                c.create_text(lx, ly, text=f"{val:.0%}",
                              fill="white", font=("Consolas", 9, "bold"))
            start_angle += angle

        # 图例
        ly = cy + r + 10
        for key, val in data:
            c.create_rectangle(10, ly - 4, 20, ly + 4,
                               fill=colors.get(key, "#aaa"), outline="")
            c.create_text(26, ly, text=f"{labels_cn[key]} {val:.0%}",
                          fill=C["text_2"], font=("Microsoft YaHei UI", 9), anchor="w")
            ly += 18

    def _display_keywords(self, keywords: list):
        self._kw_text.config(state="normal")
        self._kw_text.delete("1.0", tk.END)
        if not keywords:
            self._kw_text.insert(tk.END, "暂无关键词")
            self._kw_text.config(state="disabled")
            return

        # 用不同字号展示关键词云效果
        max_score = max(s for _, s in keywords)
        sizes = [14, 12, 11, 10, 9]

        from utils.sentiment_analyzer import _POSITIVE_WORDS, _NEGATIVE_WORDS
        for word, score in keywords[:40]:
            ratio = score / max_score if max_score > 0 else 0
            size = sizes[min(int(ratio * len(sizes)), len(sizes) - 1)]
            if word in _POSITIVE_WORDS:
                color = C["success"]
            elif word in _NEGATIVE_WORDS:
                color = C["danger"]
            else:
                color = C["text_1"]
            self._kw_text.tag_configure(f"kw_{id(word)}", font=("Microsoft YaHei UI", size),
                                         foreground=color)
            self._kw_text.insert(tk.END, f" {word} ", f"kw_{id(word)}")
        self._kw_text.config(state="disabled")
