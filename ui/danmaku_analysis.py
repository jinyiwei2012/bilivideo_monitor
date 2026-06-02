"""
弹幕/评论分析窗口模块

本模块提供对 B站视频的弹幕和评论进行数据分析与可视化展示的功能：

1. 数据获取：通过 BilibiliAPI 抓取视频弹幕或评论
2. 情绪分析：基于内置词典的正面/负面/中性情绪分布饼图
3. 关键词提取：高频关键词标签云（按词频调整字号和颜色）
4. 高频列表：前 50 条弹幕/评论含情绪标注
5. 时间分布：按批次分桶的柱状图
6. LLM 深度分析：调用远程大语言模型（支持 OpenAI / Claude API）
   - 自动保存 LLM 分析结果到本地 JSON 文件
   - 支持加载已有分析结果，避免重复调用 API
7. 数据导出：自动保存抓取数据到 data/<BV>/danmaku/ 目录
"""

import json
import math
import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List
from datetime import datetime

from ui.theme import C                                     # 颜色主题常量
from ui.dialog_base import DialogBase                      # 现代化对话框基类


class DanmakuAnalysisWindow:
    """
    弹幕/评论分析窗口

    功能：
    1. 从监控列表选择视频或手动输入 BV 号
    2. 切换弹幕/评论模式，设置抓取数量
    3. 抓取并实时分析：
       - 情绪饼图（积极/中性/消极）
       - 关键词标签云
       - 高频弹幕/评论列表（含情绪标注）
       - 时间分布柱状图
    4. LLM 深度分析（自动/手动触发）
    5. 自动保存抓取数据和 LLM 结果到本地
    """

    def __init__(self, parent=None, api=None, gui=None):
        """
        初始化弹幕/评论分析窗口

        :param parent: 父窗口
        :param api: B站 API 实例（用于数据抓取）
        :param gui: 主 GUI 实例（用于获取监控列表等）
        """
        self.dlg = DialogBase(
            parent, "弹幕/评论分析", DialogBase.calc_geometry(parent, 0.50, 0.72), resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.api = api                                        # B站 API 实例
        self.gui = gui                                        # 主 GUI 实例
        self._texts: List[str] = []                           # 抓取到的文本列表
        self._current_bvid = ""                               # 当前分析的 BV 号
        self._setup_ui()

    def _setup_ui(self):
        """
        构建界面：
        - 数据源选择 / 输入卡片（监控下拉框 + 手动输入 BV + 模式 + 数量）
        - 情绪图表区域（左：饼图 / 右：关键词标签云）
        - LLM 摘要覆盖层（分析完成后替代饼图和关键词）
        - 底部 Notebook 标签页：高频列表 / 时间分布 / LLM 分析
        """
        self.dlg.header("弹幕/评论分析", "抓取弹幕与评论，进行情绪分析与关键词提取")

        # ── 输入卡片 ──
        sec = self.dlg.section(title="数据源", padding=8)

        # 第一行：从监控列表选择
        if self.gui and self.gui.monitored_videos:
            row0 = tk.Frame(sec, bg=C["bg_elevated"])
            row0.pack(fill=tk.X, pady=(0, 4))
            tk.Label(row0, text="监控列表:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
                side=tk.LEFT
            )
            self._monitor_var = tk.StringVar()
            self._monitor_cb = ttk.Combobox(
                row0, textvariable=self._monitor_var, width=40, font=("Microsoft YaHei UI", 9), state="readonly"
            )
            self._monitor_cb["values"] = [
                f"{v.get('bvid', '')}  {v.get('title', '')[:30]}" for v in self.gui.monitored_videos
            ]
            self._monitor_cb.pack(side=tk.LEFT, padx=(6, 8))
            self._monitor_cb.bind("<<ComboboxSelected>>", lambda e: self._from_monitor_and_fetch())
            if self._monitor_cb["values"]:
                self._monitor_cb.current(0)                   # 默认选中第一个
            ttk.Button(row0, text="🚀 抓取此视频", command=self._from_monitor_and_fetch, style="Primary.TButton").pack(
                side=tk.LEFT
            )

        # 第二行：手动输入 BV + 模式选择（弹幕/评论）+ 数量限制
        row1 = tk.Frame(sec, bg=C["bg_elevated"])
        row1.pack(fill=tk.X)
        tk.Label(row1, text="BV号:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
            side=tk.LEFT
        )
        self._bv_entry = tk.Entry(
            row1, width=20, font=("Consolas", 10),
            bg=C["bg_base"], fg=C["text_1"], insertbackground=C["text_1"],
            relief="flat", highlightthickness=1, highlightbackground=C["border"],
        )
        self._bv_entry.pack(side=tk.LEFT, padx=(6, 10))

        # 弹幕/评论模式切换（RadioButton）
        self._mode_var = tk.StringVar(value="danmaku")
        tk.Radiobutton(
            row1, text="弹幕", variable=self._mode_var, value="danmaku", bg=C["bg_elevated"], command=self._update_hint
        ).pack(side=tk.LEFT, padx=2)
        tk.Radiobutton(
            row1, text="评论", variable=self._mode_var, value="comment", bg=C["bg_elevated"], command=self._update_hint
        ).pack(side=tk.LEFT, padx=2)

        # 获取数量选择
        tk.Label(row1, text="数量:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
            side=tk.LEFT, padx=(10, 2)
        )
        self._limit_var = tk.StringVar(value="全量")
        self._limit_cb = ttk.Combobox(
            row1, textvariable=self._limit_var, width=8, font=("Microsoft YaHei UI", 9),
            values=["全量", "50", "100", "500", "1000", "2000"],
        )
        self._limit_cb.pack(side=tk.LEFT)

        self._fetch_btn = ttk.Button(row1, text="抓取并分析", command=self._analyze, style="Primary.TButton")
        self._fetch_btn.pack(side=tk.LEFT, padx=(10, 0))

        # 第三行：操作按钮（保存 / LLM 深度分析）
        row2 = tk.Frame(sec, bg=C["bg_elevated"])
        row2.pack(fill=tk.X, pady=(4, 0))

        self._save_btn = ttk.Button(row2, text="💾 保存到本地", command=self._save_to_file, state="disabled")
        self._save_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._llm_btn = ttk.Button(row2, text="🤖 LLM深度分析", command=self._llm_analysis, state="disabled")
        self._llm_btn.pack(side=tk.LEFT, padx=6)

        self._status_lbl = tk.Label(sec, text="", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9))
        self._status_lbl.pack(anchor="w", padx=4, pady=(4, 0))

        # ── 内容区：情绪饼图(左) + 关键词(右) ──
        mid = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        mid.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # 左：情绪饼图
        self._left_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        self._left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)

        tk.Label(
            self._left_frame, text="情绪分布", bg=C["bg_elevated"], fg=C["text_2"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w", padx=6, pady=(4, 0))
        self._pie_canvas = tk.Canvas(self._left_frame, bg=C["bg_elevated"], width=200, height=180, highlightthickness=0)
        self._pie_canvas.pack(fill=tk.BOTH, expand=True)

        # 右：高频关键词
        self._right_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        self._right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

        tk.Label(
            self._right_frame, text="高频关键词", bg=C["bg_elevated"], fg=C["text_2"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w", padx=6, pady=(4, 0))
        self._kw_text = tk.Text(
            self._right_frame, bg=C["bg_base"], fg=C["text_1"], font=("Microsoft YaHei UI", 10),
            relief="flat", state="disabled", cursor="arrow", padx=8, pady=6,
        )
        self._kw_text.pack(fill=tk.BOTH, expand=True)

        # LLM 摘要覆盖层（初始隐藏）
        self._llm_summary = tk.Text(
            mid, bg=C["bg_elevated"], fg=C["text_1"], font=("Microsoft YaHei UI", 10),
            relief="flat", state="disabled", cursor="arrow", padx=12, pady=8, wrap="word",
        )
        self._summ_vsb = ttk.Scrollbar(mid, orient="vertical", command=self._llm_summary.yview)
        self._llm_summary.config(yscrollcommand=self._summ_vsb.set)
        self._llm_summary.tag_configure("summ_head", foreground=C["bilibili"], font=("Microsoft YaHei UI", 11, "bold"))
        self._llm_summary.tag_configure(
            "summ_body", foreground=C["text_1"], font=("Microsoft YaHei UI", 10), spacing1=2
        )
        self._llm_summary.tag_configure("summ_dim", foreground=C["text_3"], font=("Microsoft YaHei UI", 9))

        # ── 底部 Notebook（高频列表 / 时间分布 / LLM 分析） ──
        bottom = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        bottom.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 12))

        self._bottom_nb = ttk.Notebook(bottom)
        self._bottom_nb.pack(fill=tk.BOTH, expand=True)

        # 页 1：高频列表（带情绪标注）
        freq_page = tk.Frame(self._bottom_nb, bg=C["bg_base"])
        self._bottom_nb.add(freq_page, text="  高频弹幕/评论  ")

        list_label = tk.Frame(freq_page, bg=C["bg_base"])
        list_label.pack(fill=tk.X)
        tk.Label(
            list_label, text="高频弹幕/评论", bg=C["bg_base"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
        ).pack(side=tk.LEFT)

        self._count_lbl = tk.Label(list_label, text="", bg=C["bg_base"], fg=C["text_3"], font=("Microsoft YaHei UI", 9))
        self._count_lbl.pack(side=tk.LEFT, padx=12)

        table_frame = tk.Frame(
            freq_page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"]
        )
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("序号", "内容", "情绪")
        self._list_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=6)
        for col in cols:
            self._list_tree.heading(col, text=col)
        self._list_tree.column("序号", width=40, anchor="center")
        self._list_tree.column("内容", width=400)
        self._list_tree.column("情绪", width=60, anchor="center")
        self._list_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self._list_tree.yview)
        self._list_tree.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 页 2：时间分布柱状图
        time_page = tk.Frame(self._bottom_nb, bg=C["bg_base"])
        self._bottom_nb.add(time_page, text="  📊 时间分布  ")
        self._time_canvas = tk.Canvas(time_page, bg=C["bg_base"], highlightthickness=0)
        self._time_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 页 3：LLM 分析结果
        llm_page = tk.Frame(self._bottom_nb, bg=C["bg_base"])
        self._bottom_nb.add(llm_page, text="  🤖 LLM分析  ")

        self._llm_text = tk.Text(
            llm_page, bg=C["bg_base"], fg=C["text_1"], font=("Microsoft YaHei UI", 10),
            relief="flat", state="disabled", cursor="arrow", padx=12, pady=10, wrap="word",
        )
        llm_vsb = ttk.Scrollbar(llm_page, orient="vertical", command=self._llm_text.yview)
        self._llm_text.config(yscrollcommand=llm_vsb.set)
        self._llm_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        llm_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._llm_text.tag_configure("head", foreground=C["bilibili"], font=("Microsoft YaHei UI", 11, "bold"))
        self._llm_text.tag_configure("body", foreground=C["text_1"], font=("Microsoft YaHei UI", 10), spacing1=2)
        self._llm_text.tag_configure("dim", foreground=C["text_3"], font=("Microsoft YaHei UI", 9))

        self._update_hint()

    # ── 辅助方法 ────────────────────────────────────────────────────────────────

    def _update_hint(self):
        """更新操作提示信息（模式切换时调用）"""
        self._mode_var.get()
        hint = "输入视频BV号，抓取弹幕分析情感倾向与高频内容"
        self._status_lbl.config(text=hint)

    def _get_limit(self) -> int:
        """
        从 UI 获取用户设置的数量限制

        :return: 限制数量，0 表示全量
        """
        v = self._limit_var.get()
        if v == "全量":
            return 0
        return int(v)

    def _fetch_danmaku(self, bvid, limit):
        """
        抓取弹幕数据

        :param bvid: 视频 BV 号
        :param limit: 数量限制
        :return: (文本列表, 错误信息)，文本列表可能为 None
        """
        info = self.api.get_video_info(bvid)
        if not info:
            return None, "获取视频信息失败"
        cid = info.get("cid", 0)
        if not cid:
            return None, "无法获取cid"
        danmaku = self.api.get_video_danmaku(cid)
        if not danmaku:
            return None, "未获取到弹幕"
        texts = [d["text"] for d in danmaku if d.get("text")]
        if limit > 0:
            texts = texts[:limit]
        return texts, None

    def _fetch_comments(self, bvid, limit):
        """
        抓取评论数据

        :param bvid: 视频 BV 号
        :param limit: 数量限制
        :return: (文本列表, 错误信息)，文本列表可能为 None
        """
        info = self.api.get_video_info(bvid)
        if not info:
            return None, "获取视频信息失败"
        aid = info.get("aid", 0)
        if not aid:
            return None, "无法获取aid"
        comments = self.api.get_video_comments(aid, limit=limit if limit > 0 else 0)
        if not comments:
            return None, "未获取到评论"
        texts = [c["content"] for c in comments if c.get("content")]
        return texts, None

    def _analyze(self):
        """
        抓取并分析弹幕/评论：情绪分析、关键词提取、时间分布、保存结果

        流程：
        1. 获取 BV 号和模式
        2. 调用对应 API 抓取数据
        3. 展示分析结果（饼图、关键词、时间分布、高频列表）
        4. 自动保存到本地文件
        5. 加载已有的 LLM 分析结果
        """
        bvid = self._bv_entry.get().strip()
        if not bvid:
            messagebox.showwarning("提示", "请输入BV号", parent=self.window)
            return

        if not self.api:
            messagebox.showerror("错误", "API不可用", parent=self.window)
            return

        limit = self._get_limit()

        self._fetch_btn.config(state="disabled")
        self._status_lbl.config(text="正在抓取数据...", fg=C["text_2"])
        self.window.update_idletasks()

        try:
            mode = self._mode_var.get()
            texts = None

            if mode == "danmaku":
                texts, err = self._fetch_danmaku(bvid, limit)
            else:
                texts, err = self._fetch_comments(bvid, limit)

            if err:
                self._status_lbl.config(text=err, fg=C["danger"])
                return

            self._texts = texts
            self._current_bvid = bvid
            limit_label = f"（限制 {limit} 条）" if limit > 0 else "（全量）"
            self._status_lbl.config(text=f"抓取成功：共 {len(texts)} 条{mode} {limit_label}", fg=C["success"])
            self.window.update_idletasks()

            # 展示分析结果
            self._display_results(texts)
            self._save_btn.config(state="normal")
            self._llm_btn.config(state="normal")
            self._save_to_file(silent=True)                   # 自动静默保存
            self._load_local_llm_result()                     # 尝试加载已有 LLM 结果
        except Exception as e:
            self._status_lbl.config(text=f"分析失败: {e}", fg=C["danger"])
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("ERROR", f"弹幕分析失败: {e}")
        finally:
            self._fetch_btn.config(state="normal")

    def _display_results(self, texts: List[str]):
        """
        展示分析结果：情绪饼图、关键词标签云、时间分布、高频列表

        :param texts: 弹幕/评论文本列表
        """
        self._restore_charts()                                # 恢复饼图和关键词（隐藏 LLM 摘要）
        from utils.sentiment_analyzer import (
            analyze_sentiment, extract_keywords, generate_word_freq,
        )

        # 情绪分析
        sentiment = analyze_sentiment(texts)
        self._draw_pie(sentiment)

        # 关键词提取
        keywords = extract_keywords(texts, top_n=30)
        self._display_keywords(keywords)

        # 词频统计
        freq = generate_word_freq(texts)
        _top_freq = sorted(freq.items(), key=lambda x: -x[1])[:20]  # noqa: F841

        # 时间分布柱状图
        self._draw_time_distribution(texts)

        # 更新高频列表（显示前 50 条，含情绪标注）
        for item in self._list_tree.get_children():
            self._list_tree.delete(item)

        # 对每条文本进行情绪评分
        from utils.sentiment_analyzer import _tokenize, _POSITIVE_WORDS, _NEGATIVE_WORDS, _INTENSIFIERS, _NEGATORS

        for i, text in enumerate(texts[:50]):
            tokens = _tokenize(text.strip())
            score = 0.0
            for j, token in enumerate(tokens):
                weight = 1.0
                # 程度副词放大情感权重
                if j > 0 and tokens[j - 1] in _INTENSIFIERS:
                    weight *= 1.5
                # 否定词翻转情感极性
                if j > 0 and tokens[j - 1] in _NEGATORS:
                    weight *= -1.0
                if token in _POSITIVE_WORDS:
                    score += weight
                elif token in _NEGATIVE_WORDS:
                    score -= weight
            # 三类情绪判定
            if score > 0.5:
                mood = "积极"
            elif score < -0.5:
                mood = "消极"
            else:
                mood = "中性"
            self._list_tree.insert("", "end", values=(i + 1, text[:60], mood))

        self._count_lbl.config(text=f"共 {len(texts)} 条，显示前 {min(50, len(texts))} 条")

    # ── 从监控列表选择并自动抓取 ────────────────────────────────────────────────

    def _from_monitor_and_fetch(self):
        """从监控列表选择后直接填入 BV 号并自动抓取分析"""
        sel = self._monitor_var.get()
        if not sel:
            return
        bvid = sel.split()[0]                               # 提取 BV 号（格式：BVxxx 标题...）
        self._bv_entry.delete(0, tk.END)
        self._bv_entry.insert(0, bvid)
        self._analyze()

    def _save_to_file(self, silent: bool = False):
        """
        保存弹幕/评论到 BV 对应文件夹下的 danmaku 子目录

        :param silent: 是否静默保存（不弹窗）
        """
        if not self._texts or not self._current_bvid:
            if not silent:
                messagebox.showinfo("提示", "暂无数据可保存", parent=self.window)
            return

        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        os.makedirs(bv_dir, exist_ok=True)

        mode = self._mode_var.get()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{mode}_{ts}.json"
        filepath = os.path.join(bv_dir, filename)

        data = {
            "bvid": self._current_bvid,
            "mode": mode,
            "count": len(self._texts),
            "timestamp": datetime.now().isoformat(),
            "texts": self._texts,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if not silent:
            messagebox.showinfo("保存成功", f"已保存 {len(self._texts)} 条{mode}\n{filepath}", parent=self.window)
        else:
            self._status_lbl.config(text=f"自动保存 {len(self._texts)} 条 → {filepath}", fg=C["success"])

    # ── LLM 分析 ─────────────────────────────────────────────────────────────────

    def _llm_analysis(self):
        """
        使用 LLM 深度分析弹幕/评论（后台线程，不阻塞 UI）

        流程：
        1. 检查是否已有本地分析结果（有则询问是否重新分析）
        2. 加载 API 配置
        3. 准备 UI 和 prompt
        4. 启动后台线程调用 API
        """
        if not self._texts:
            messagebox.showinfo("提示", "请先抓取数据", parent=self.window)
            return

        if self._check_llm_existing_result():
            return

        config = self._load_llm_api_config()
        if config is None:
            return
        api_key, endpoint, model = config

        self._prepare_llm_ui()

        mode = self._mode_var.get()
        prompt = self._prepare_llm_prompt(mode)

        import threading

        threading.Thread(target=self._llm_worker, args=(api_key, endpoint, model, mode, prompt), daemon=True).start()

    def _check_llm_existing_result(self):
        """
        检查本地已有 LLM 分析结果文件，询问用户是否重新分析

        :return: True 表示已展示已有结果，False 表示需要重新调用 API
        """
        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        mode = self._mode_var.get()
        local_files = []
        if os.path.isdir(bv_dir):
            local_files = [
                f for f in os.listdir(bv_dir) if f.startswith("llm_") and f.endswith(".json") and f"_{mode}_" in f
            ]
        if local_files:
            if not messagebox.askyesno(
                "确认重新分析",
                f"已存在 LLM {mode}分析结果，是否重新调用 API 分析？\n" "选择「否」则查看已有结果。",
                parent=self.window,
            ):
                self._load_local_llm_result()
                return True
        return False

    def _load_llm_api_config(self):
        """
        加载 LLM API 配置

        :return: (api_key, endpoint, model) 或 None
        """
        try:
            from config import get_active_ai_profile

            profile = get_active_ai_profile()
            api_key = profile.get("api_key", "")
            endpoint = profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
            model = profile.get("model", "gpt-4o-mini")
        except Exception:
            api_key = ""

        if not api_key:
            messagebox.showwarning("提示", "未配置LLM API密钥，请在「设置 → AI配置」中配置", parent=self.window)
            return None
        return (api_key, endpoint, model)

    def _prepare_llm_ui(self):
        """准备 LLM 分析的 UI 状态：禁用按钮、显示等待信息"""
        self._llm_btn.config(state="disabled")
        self._status_lbl.config(text="LLM分析中...", fg=C["text_2"])
        self.window.update_idletasks()

        self._llm_text.config(state="normal")
        self._llm_text.delete("1.0", tk.END)
        self._llm_text.insert(tk.END, "LLM分析请求已发送，请稍候...\n", "dim")
        self._llm_text.config(state="disabled")
        self.window.update_idletasks()

    def _prepare_llm_prompt(self, mode):
        """
        构建 LLM 分析用的 prompt，包含前 100 条样本

        :param mode: "danmaku" 或 "comment"
        :return: prompt 字符串
        """
        sample = self._texts[:100]
        prompt = (
            f"你是一个B站视频{mode}分析助手。分析以下{len(sample)}条{mode}数据，"
            f"给出分点总结：\n"
            f"1. 整体情绪倾向（积极/消极/中性比例）\n"
            f"2. 主要讨论话题\n"
            f"3. 高频关键词\n"
            f"4. 代表性评论摘录\n"
            f"5. 总结性建议\n\n"
            f"{mode}数据：\n"
        )
        for i, t in enumerate(sample[:50], 1):
            prompt += f"{i}. {t}\n"

        if self.gui and hasattr(self.gui, "log_panel"):
            self.gui.log_panel.add_log(
                "INFO", f"LLM分析请求已发送（{self._current_bvid}，{mode}，{len(self._texts)}条）"
            )
        return prompt

    def _llm_worker(self, api_key, endpoint, model, mode, prompt):
        """
        后台线程：调用 LLM API 并在主线程更新 UI

        :param api_key: API 密钥
        :param endpoint: API 端点 URL
        :param model: 模型名称
        :param mode: 数据模式
        :param prompt: 分析 prompt
        """
        result_text = self._call_llm_api(api_key, endpoint, model, prompt)
        self.window.after(0, self._update_llm_ui, result_text, mode, model)

    def _call_llm_api(self, api_key, endpoint, model, prompt):
        """
        调用 LLM API（支持 OpenAI 兼容 API 和 Claude API）

        :param api_key: API 密钥
        :param endpoint: API 端点
        :param model: 模型名称
        :param prompt: 分析 prompt
        :return: 结果文本
        """
        try:
            import requests as req

            is_claude = "anthropic.com" in endpoint
            if is_claude:
                # Claude API 调用
                resp = req.post(
                    endpoint,
                    headers={
                        "x-api-key": api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": model,
                        "max_tokens": 2048,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content_list = data.get("content", [])
                    return content_list[0].get("text", "") if content_list else ""
                else:
                    return f"API请求失败 (HTTP {resp.status_code})\n{resp.text[:500]}"
            else:
                # OpenAI 兼容 API 调用
                resp = req.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是一个专业的数据分析助手，擅长从弹幕和评论中提取洞察。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 2048,
                        "temperature": 0.5,
                    },
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if not result:
                        return str(data)[:500]
                    return result
                else:
                    return f"API请求失败 (HTTP {resp.status_code})\n{resp.text[:500]}"
        except Exception as e:
            return f"LLM分析异常: {e}"

    def _update_llm_ui(self, result_text, mode, model):
        """
        主线程：更新 UI 显示 LLM 分析结果，保存到本地

        :param result_text: LLM 返回的分析文本
        :param mode: 数据模式
        :param model: 使用的模型
        """
        try:
            self._llm_text.winfo_exists()
        except Exception:
            return
        self._llm_text.config(state="normal")
        self._llm_text.delete("1.0", tk.END)
        title = f"🎯 LLM {mode}深度分析报告\n"
        meta = f"BV: {self._current_bvid}  |  数据: {len(self._texts)}条  |  模型: {model}\n\n"
        self._llm_text.insert(tk.END, title, "head")
        self._llm_text.insert(tk.END, meta, "dim")
        self._llm_text.insert(tk.END, result_text, "body")
        self._llm_text.config(state="disabled")
        self._llm_btn.config(state="normal")
        # 上半区覆盖显示 LLM 摘要（替代饼图和关键词）
        self._show_llm_summary(result_text, mode, model)
        # 切换到 LLM 标签页
        self._bottom_nb.select(2)
        self._status_lbl.config(text="LLM分析完成", fg=C["success"])
        if self.gui and hasattr(self.gui, "log_panel"):
            self.gui.log_panel.add_log("INFO", f"LLM分析完成（{self._current_bvid}，{mode}）")
        # 保存 LLM 分析结果
        self._save_llm_result(result_text, mode, model)

    def _save_llm_result(self, result_text, mode, model):
        """保存 LLM 分析结果到 BV 对应文件夹下的 danmaku 子目录"""
        try:
            from config import DATA_DIR

            bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
            os.makedirs(bv_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(bv_dir, f"llm_{mode}_{ts}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "bvid": self._current_bvid, "mode": mode, "model": model,
                        "data_count": len(self._texts), "timestamp": datetime.now().isoformat(),
                        "analysis": result_text,
                    },
                    f, ensure_ascii=False, indent=2,
                )
            self._status_lbl.config(text=f"LLM分析完成，已保存 → {filepath}", fg=C["success"])
        except Exception as e:
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("WARNING", f"保存LLM分析结果失败: {e}")

    def _load_local_llm_result(self):
        """加载本地已有的 LLM 分析结果（按修改时间取最新的文件）"""
        if not self._current_bvid:
            return
        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        if not os.path.isdir(bv_dir):
            return
        files = [f for f in os.listdir(bv_dir) if f.startswith("llm_") and f.endswith(".json")]
        if not files:
            return
        mode = self._mode_var.get()  # noqa: F841
        mode_files = [f for f in files if f"_{mode}_" in f]
        if not mode_files:
            return
        latest = max(mode_files, key=lambda f: os.path.getmtime(os.path.join(bv_dir, f)))
        try:
            with open(os.path.join(bv_dir, latest), "r", encoding="utf-8") as f:
                data = json.load(f)
            result_text = data.get("analysis", "")
            model = data.get("model", "unknown")
            if result_text:
                self._show_llm_summary(result_text, mode, model)
                # 也填充底部 LLM 标签页
                self._llm_text.config(state="normal")
                self._llm_text.delete("1.0", tk.END)
                self._llm_text.insert(tk.END, f"🎯 LLM {mode}深度分析报告\n", "head")
                self._llm_text.insert(
                    tk.END,
                    f"BV: {self._current_bvid}  |  数据: {data.get('data_count', 0)}条  |  模型: {model}\n\n",
                    "dim",
                )
                self._llm_text.insert(tk.END, result_text, "body")
                self._llm_text.config(state="disabled")
                self._status_lbl.config(text=f"已加载本地 LLM 分析结果（{latest}）", fg=C["success"])
                self.window.after(100, lambda: self._bottom_nb.select(2))
                self._llm_btn.config(state="normal")
        except Exception as e:
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("WARNING", f"加载本地LLM结果失败: {e}")

    def _show_llm_summary(self, result_text: str, mode: str, model: str):
        """在上半区显示 LLM 分析结果，隐藏情绪饼图和关键词"""
        self._left_frame.pack_forget()
        self._right_frame.pack_forget()
        self._llm_summary.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)
        self._summ_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._llm_summary.config(state="normal")
        self._llm_summary.delete("1.0", tk.END)
        title = f"🎯 LLM {mode}深度分析报告\n"
        meta = f"BV: {self._current_bvid}  |  数据: {len(self._texts)}条  |  模型: {model}\n\n"
        self._llm_summary.insert(tk.END, title, "summ_head")
        self._llm_summary.insert(tk.END, meta, "summ_dim")
        self._llm_summary.insert(tk.END, result_text, "summ_body")
        self._llm_summary.config(state="disabled")

    def _restore_charts(self):
        """恢复显示情绪饼图和关键词，隐藏 LLM 摘要覆盖层"""
        self._llm_summary.pack_forget()
        self._summ_vsb.pack_forget()
        self._left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)
        self._right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

    # ── 图表绘制 ────────────────────────────────────────────────────────────────

    def _draw_pie(self, sentiment: dict):
        """
        绘制情绪分布饼图

        三色分区（积极=绿色/中性=灰色/消极=红色），含百分比标签和图例。

        :param sentiment: {"positive": 0.6, "neutral": 0.3, "negative": 0.1}
        """
        c = self._pie_canvas
        c.delete("all")
        W = c.winfo_width() or 180
        H = c.winfo_height() or 160

        colors = {"positive": "#42b983", "neutral": "#aab0b8", "negative": "#e74c3c"}
        labels_cn = {"positive": "积极", "neutral": "中性", "negative": "消极"}

        data = [(k, v) for k, v in sentiment.items() if v > 0]
        if not data:
            c.create_text(W // 2, H // 2, text="无数据", fill=C["text_3"], font=("Microsoft YaHei UI", 10))
            return

        cx, cy, r = W // 2, H // 2 - 10, min(W, H) // 2 - 20
        start_angle = 0

        for key, val in data:
            angle = val * 360                                # 将比例转换为角度
            if angle <= 0:
                continue
            c.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_angle, extent=angle,
                fill=colors.get(key, "#aaa"), outline=C["bg_elevated"], width=2,
            )
            # 百分比标签（在扇区中间位置）
            mid_angle = start_angle + angle / 2
            lx = cx + (r * 0.65) * math.cos(math.radians(mid_angle))
            ly = cy - (r * 0.65) * math.sin(math.radians(mid_angle))
            if val >= 0.05:                                  # 低于 5% 不显示标签（太小看不清）
                c.create_text(lx, ly, text=f"{val:.0%}", fill="white", font=("Consolas", 9, "bold"))
            start_angle += angle

        # 图例
        ly = cy + r + 10
        for key, val in data:
            c.create_rectangle(10, ly - 4, 20, ly + 4, fill=colors.get(key, "#aaa"), outline="")
            c.create_text(
                26, ly, text=f"{labels_cn[key]} {val:.0%}", fill=C["text_2"],
                font=("Microsoft YaHei UI", 9), anchor="w"
            )
            ly += 18

    def _draw_time_distribution(self, texts: list):
        """
        绘制弹幕时间分布柱状图（按批次分桶）

        将文本列表等分为最多 20 个桶，归一化高度后绘制。

        :param texts: 弹幕文本列表
        """
        c = self._time_canvas
        c.delete("all")
        if not texts:
            c.create_text(200, 80, text="无弹幕数据", fill=C["text_3"], font=("Microsoft YaHei UI", 12))
            return
        w = c.winfo_width() or 500
        h = c.winfo_height() or 200
        n = len(texts)
        bins = min(20, max(5, n // 5))                       # 桶数 = min(20, max(5, n/5))
        chunk_size = max(1, n // bins)
        counts = []
        for i in range(0, n, chunk_size):
            counts.append(min(1.0, len(texts[i:i + chunk_size]) / chunk_size))
        bar_w = (w - 40) / max(len(counts), 1)
        max_c = max(counts) if counts else 1
        for i, v in enumerate(counts):
            bh = v / max_c * (h - 50)
            x0 = 20 + i * bar_w
            y0 = h - 30 - bh
            x1 = x0 + bar_w - 1
            y1 = h - 30
            intensity = int(50 + 180 * v / max_c)            # 颜色深浅随高度变化
            color = f"#{intensity:02x}66ff"
            c.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
        c.create_text(20, 10, text="弹幕时间分布（→ 时间轴）", fill=C["text_3"],
                      font=("Microsoft YaHei UI", 9), anchor="w")

    def _display_keywords(self, keywords: list):
        """
        展示关键词标签云：按词频用不同字号和颜色显示

        积极词用绿色，消极词用红色，其余用默认色。

        :param keywords: [(word, score), ...] 关键词列表
        """
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
            # 根据词性设定颜色
            if word in _POSITIVE_WORDS:
                color = C["success"]
            elif word in _NEGATIVE_WORDS:
                color = C["danger"]
            else:
                color = C["text_1"]
            self._kw_text.tag_configure(f"kw_{id(word)}", font=("Microsoft YaHei UI", size), foreground=color)
            self._kw_text.insert(tk.END, f" {word} ", f"kw_{id(word)}")
        self._kw_text.config(state="disabled")
