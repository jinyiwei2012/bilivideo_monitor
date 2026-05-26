"""
弹幕/评论分析窗口 — 情绪饼图、关键词标签云、高频列表
支持从监控列表选择、自动保存、LLM 深度分析
"""

import json
import math
import os
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List
from datetime import datetime

from ui.theme import C
from ui.dialog_base import DialogBase


class DanmakuAnalysisWindow:
    """弹幕/评论分析窗口"""

    def __init__(self, parent=None, api=None, gui=None):
        self.dlg = DialogBase(parent, "弹幕/评论分析",
                              DialogBase.calc_geometry(parent, 0.50, 0.72),
                              resizable=(True, True), modal=False)
        self.window = self.dlg.window
        self.api = api
        self.gui = gui
        self._texts: List[str] = []
        self._current_bvid = ""
        self._setup_ui()

    def _setup_ui(self):
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
            # 选中第一个后自动填入（但有值时才触发抓取）
            if self._monitor_cb["values"]:
                self._monitor_cb.current(0)
            ttk.Button(row0, text="🚀 抓取此视频", command=self._from_monitor_and_fetch, style="Primary.TButton").pack(
                side=tk.LEFT
            )

        # 第二行：手动输入 BV + 模式选择 + 数量限制
        row1 = tk.Frame(sec, bg=C["bg_elevated"])
        row1.pack(fill=tk.X)
        tk.Label(row1, text="BV号:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
            side=tk.LEFT
        )
        self._bv_entry = tk.Entry(
            row1,
            width=20,
            font=("Consolas", 10),
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self._bv_entry.pack(side=tk.LEFT, padx=(6, 10))

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
            row1,
            textvariable=self._limit_var,
            width=8,
            font=("Microsoft YaHei UI", 9),
            values=["全量", "50", "100", "500", "1000", "2000"],
        )
        self._limit_cb.pack(side=tk.LEFT)

        self._fetch_btn = ttk.Button(row1, text="抓取并分析", command=self._analyze, style="Primary.TButton")
        self._fetch_btn.pack(side=tk.LEFT, padx=(10, 0))

        # 第三行：操作按钮
        row2 = tk.Frame(sec, bg=C["bg_elevated"])
        row2.pack(fill=tk.X, pady=(4, 0))

        self._save_btn = ttk.Button(row2, text="💾 保存到本地", command=self._save_to_file, state="disabled")
        self._save_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._llm_btn = ttk.Button(row2, text="🤖 LLM深度分析", command=self._llm_analysis, state="disabled")
        self._llm_btn.pack(side=tk.LEFT, padx=6)

        self._status_lbl = tk.Label(sec, text="", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9))
        self._status_lbl.pack(anchor="w", padx=4, pady=(4, 0))

        # 内容区：情绪饼图(左) + 关键词(右)
        mid = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        mid.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # 左：情绪饼图
        self._left_frame = tk.Frame(mid, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        self._left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)

        tk.Label(
            self._left_frame,
            text="情绪分布",
            bg=C["bg_elevated"],
            fg=C["text_2"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w", padx=6, pady=(4, 0))
        self._pie_canvas = tk.Canvas(self._left_frame, bg=C["bg_elevated"], width=200, height=180, highlightthickness=0)
        self._pie_canvas.pack(fill=tk.BOTH, expand=True)

        # 右：关键词
        self._right_frame = tk.Frame(
            mid, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"]
        )
        self._right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

        tk.Label(
            self._right_frame,
            text="高频关键词",
            bg=C["bg_elevated"],
            fg=C["text_2"],
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(anchor="w", padx=6, pady=(4, 0))
        self._kw_text = tk.Text(
            self._right_frame,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            state="disabled",
            cursor="arrow",
            padx=8,
            pady=6,
        )
        self._kw_text.pack(fill=tk.BOTH, expand=True)

        # LLM 摘要覆盖层（初始隐藏）
        self._llm_summary = tk.Text(
            mid,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            state="disabled",
            cursor="arrow",
            padx=12,
            pady=8,
            wrap="word",
        )
        self._summ_vsb = ttk.Scrollbar(mid, orient="vertical", command=self._llm_summary.yview)
        self._llm_summary.config(yscrollcommand=self._summ_vsb.set)
        self._llm_summary.tag_configure("summ_head", foreground=C["bilibili"], font=("Microsoft YaHei UI", 11, "bold"))
        self._llm_summary.tag_configure(
            "summ_body", foreground=C["text_1"], font=("Microsoft YaHei UI", 10), spacing1=2
        )
        self._llm_summary.tag_configure("summ_dim", foreground=C["text_3"], font=("Microsoft YaHei UI", 9))

        # 底部：Notebook 切换 高频列表 / LLM分析
        bottom = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        bottom.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 12))

        self._bottom_nb = ttk.Notebook(bottom)
        self._bottom_nb.pack(fill=tk.BOTH, expand=True)

        # ── 页1：高频列表 ──
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

        # ── 页2：LLM分析结果 ──
        llm_page = tk.Frame(self._bottom_nb, bg=C["bg_base"])
        self._bottom_nb.add(llm_page, text="  🤖 LLM分析  ")

        self._llm_text = tk.Text(
            llm_page,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            state="disabled",
            cursor="arrow",
            padx=12,
            pady=10,
            wrap="word",
        )
        llm_vsb = ttk.Scrollbar(llm_page, orient="vertical", command=self._llm_text.yview)
        self._llm_text.config(yscrollcommand=llm_vsb.set)
        self._llm_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        llm_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._llm_text.tag_configure("head", foreground=C["bilibili"], font=("Microsoft YaHei UI", 11, "bold"))
        self._llm_text.tag_configure("body", foreground=C["text_1"], font=("Microsoft YaHei UI", 10), spacing1=2)
        self._llm_text.tag_configure("dim", foreground=C["text_3"], font=("Microsoft YaHei UI", 9))

        self._update_hint()

    def _update_hint(self):
        mode = self._mode_var.get()  # noqa: F841
        hint = "输入视频BV号，抓取弹幕分析情感倾向与高频内容"
        self._status_lbl.config(text=hint)

    def _get_limit(self) -> int:
        """从 UI 获取用户设置的数量限制，0 表示全量"""
        v = self._limit_var.get()
        if v == "全量":
            return 0
        return int(v)

    def _fetch_danmaku(self, bvid, limit):
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
            mode = self._mode_var.get()  # noqa: F841
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
            self._display_results(texts)
            self._save_btn.config(state="normal")
            self._llm_btn.config(state="normal")
            self._save_to_file(silent=True)
            self._load_local_llm_result()
        except Exception as e:
            self._status_lbl.config(text=f"分析失败: {e}", fg=C["danger"])
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("ERROR", f"弹幕分析失败: {e}")
        finally:
            self._fetch_btn.config(state="normal")

    def _display_results(self, texts: List[str]):
        self._restore_charts()
        from utils.sentiment_analyzer import (
            analyze_sentiment,
            extract_keywords,
            generate_word_freq,
        )

        # 情绪分析
        sentiment = analyze_sentiment(texts)
        self._draw_pie(sentiment)

        # 关键词
        keywords = extract_keywords(texts, top_n=30)
        self._display_keywords(keywords)

        # 词频
        freq = generate_word_freq(texts)
        _top_freq = sorted(freq.items(), key=lambda x: -x[1])[:20]  # noqa: F841

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
            self._list_tree.insert("", "end", values=(i + 1, text[:60], mood))

        self._count_lbl.config(text=f"共 {len(texts)} 条，显示前 {min(50, len(texts))} 条")

    # ── 新增方法 ────────────────────────────────────

    def _from_monitor_and_fetch(self):
        """从监控列表选择后直接抓取分析"""
        sel = self._monitor_var.get()
        if not sel:
            return
        bvid = sel.split()[0]
        self._bv_entry.delete(0, tk.END)
        self._bv_entry.insert(0, bvid)
        self._analyze()

    def _save_to_file(self, silent: bool = False):
        """保存弹幕/评论到 BV 对应文件夹"""
        if not self._texts or not self._current_bvid:
            if not silent:
                messagebox.showinfo("提示", "暂无数据可保存", parent=self.window)
            return

        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        os.makedirs(bv_dir, exist_ok=True)

        mode = self._mode_var.get()  # noqa: F841
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

    def _llm_analysis(self):
        """使用LLM深度分析弹幕/评论（后台线程，不阻塞UI）"""
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
        """检查本地已有 LLM 结果。返回 True 表示已加载本地结果，无需继续。"""
        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        mode = self._mode_var.get()  # noqa: F841
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
        """加载 LLM API 配置。返回 (api_key, endpoint, model) 或 None。"""
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
        """准备 LLM 分析的 UI 状态。"""
        self._llm_btn.config(state="disabled")
        self._status_lbl.config(text="LLM分析中...", fg=C["text_2"])
        self.window.update_idletasks()

        self._llm_text.config(state="normal")
        self._llm_text.delete("1.0", tk.END)
        self._llm_text.insert(tk.END, "LLM分析请求已发送，请稍候...\n", "dim")
        self._llm_text.config(state="disabled")
        self.window.update_idletasks()

    def _prepare_llm_prompt(self, mode):
        """准备 LLM 分析用的 prompt。"""
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
            self.gui.log_panel.add_log("INFO", f"LLM分析请求已发送（{self._current_bvid}，{mode}，{len(self._texts)}条）")
        return prompt

    def _llm_worker(self, api_key, endpoint, model, mode, prompt):
        """后台线程：调用 LLM API 并更新 UI。"""
        result_text = self._call_llm_api(api_key, endpoint, model, prompt)
        self.window.after(0, self._update_llm_ui, result_text, mode, model)

    def _call_llm_api(self, api_key, endpoint, model, prompt):
        """调用 LLM API，返回结果文本。"""
        try:
            import requests as req

            is_claude = "anthropic.com" in endpoint
            if is_claude:
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
        """主线程：更新 UI 显示 LLM 分析结果。"""
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
        # 上半区覆盖显示 LLM 摘要
        self._show_llm_summary(result_text, mode, model)
        # 切换到LLM标签页
        self._bottom_nb.select(1)
        self._status_lbl.config(text="LLM分析完成", fg=C["success"])
        if self.gui and hasattr(self.gui, "log_panel"):
            self.gui.log_panel.add_log("INFO", f"LLM分析完成（{self._current_bvid}，{mode}）")
        # 保存 LLM 分析结果到文件夹
        self._save_llm_result(result_text, mode, model)

    def _save_llm_result(self, result_text, mode, model):
        """保存 LLM 分析结果到文件夹。"""
        try:
            from config import DATA_DIR

            bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
            os.makedirs(bv_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(bv_dir, f"llm_{mode}_{ts}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "bvid": self._current_bvid,
                        "mode": mode,
                        "model": model,
                        "data_count": len(self._texts),
                        "timestamp": datetime.now().isoformat(),
                        "analysis": result_text,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            self._status_lbl.config(text=f"LLM分析完成，已保存 → {filepath}", fg=C["success"])
        except Exception as e:
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("WARNING", f"保存LLM分析结果失败: {e}")

    def _load_local_llm_result(self):
        """加载本地已有的 LLM 分析结果"""
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
                self.window.after(100, lambda: self._bottom_nb.select(1))
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
        """恢复显示情绪饼图和关键词，隐藏 LLM 摘要"""
        self._llm_summary.pack_forget()
        self._summ_vsb.pack_forget()
        self._left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipadx=6, ipady=6)
        self._right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0), ipadx=6, ipady=6)

    def _draw_pie(self, sentiment: dict):
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
            angle = val * 360
            if angle <= 0:
                continue
            c.create_arc(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                start=start_angle,
                extent=angle,
                fill=colors.get(key, "#aaa"),
                outline=C["bg_elevated"],
                width=2,
            )
            # 标签
            mid_angle = start_angle + angle / 2
            lx = cx + (r * 0.65) * math.cos(math.radians(mid_angle))
            ly = cy - (r * 0.65) * math.sin(math.radians(mid_angle))
            if val >= 0.05:
                c.create_text(lx, ly, text=f"{val:.0%}", fill="white", font=("Consolas", 9, "bold"))
            start_angle += angle

        # 图例
        ly = cy + r + 10
        for key, val in data:
            c.create_rectangle(10, ly - 4, 20, ly + 4, fill=colors.get(key, "#aaa"), outline="")
            c.create_text(
                26, ly, text=f"{labels_cn[key]} {val:.0%}", fill=C["text_2"], font=("Microsoft YaHei UI", 9), anchor="w"
            )
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
            self._kw_text.tag_configure(f"kw_{id(word)}", font=("Microsoft YaHei UI", size), foreground=color)
            self._kw_text.insert(tk.END, f" {word} ", f"kw_{id(word)}")
        self._kw_text.config(state="disabled")
