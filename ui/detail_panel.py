"""
中间详情面板模块 - CustomTkinter 版

负责视频详情头部、统计栏、图表切换、详细数据文本、互动率等展示。
"""

import tkinter as tk
from tkinter import ttk
import threading
from datetime import datetime
import customtkinter as ctk

from ui.theme import C
from ui.helpers import (
    FONT,
    FONT_SM,
    FONT_BOLD,
    FONT_MONO,
    THRESHOLDS,
    THRESHOLD_NAMES,
    fmt_num,
)
from ui.chart import draw_chart, draw_chart_placeholder
from utils.weekly_score import calculate_from_dict as _calc_ws
from utils.yearly_score import calculate_yearly_from_dict as _calc_ys
from utils.update_checker import _confirm_risky


class DetailPanel:
    """中间详情面板"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._stat_labels = {}
        self._tab_btns = {}
        self._current_tab = "📈 播放量趋势"
        self._chart_resize_job = None
        self._chart_mode = tk.StringVar(value="step")
        self._chart_max_points = tk.StringVar(value="20")
        # 标记当前模式是否已经渲染过；防止 resize 绕过 delta/full 的"手动点击"门控
        self._rendered_modes = set()
        self._build()

    def _build(self):
        self._build_center_panel()

    def _build_center_panel(self):
        """构建中间面板整体布局：头部、统计栏、标签页、内容区"""
        p = self._parent
        self._detail_header = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        self._detail_header.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        self._build_center_header_empty()

        self._stat_bar = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        self._stat_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)

        # 标签页栏
        tab_bar = ctk.CTkFrame(p, fg_color=C["bg_surface"], corner_radius=0)
        tab_bar.pack(fill=tk.X)
        tk.Frame(p, bg=C["border"], height=1).pack(fill=tk.X)
        for name in ["📈 播放量趋势", "📋 详细数据", "🔄 互动率"]:
            b = ctk.CTkLabel(
                tab_bar, text=name, fg_color="transparent", text_color=C["text_2"], font=FONT, cursor="hand2"
            )
            b.pack(side=tk.LEFT, padx=14, pady=8)
            b.bind("<Button-1>", lambda e, n=name: self._switch_tab(n))
            b.bind(
                "<Enter>",
                lambda e, b=b, n=name: b.configure(text_color=C["text_1"]) if n != self._current_tab else None,
            )
            b.bind(
                "<Leave>",
                lambda e, b=b, n=name: b.configure(text_color=C["text_2"]) if n != self._current_tab else None,
            )
            self._tab_btns[name] = b
        # 默认选中第一个标签
        self._tab_btns["📈 播放量趋势"].configure(text_color=C["bilibili"])

        # 内容区域
        self._content_area = ctk.CTkFrame(p, fg_color=C["bg_base"], corner_radius=0)
        self._content_area.pack(fill=tk.BOTH, expand=True)

        # 图表控制栏
        bar = tk.Frame(self._content_area, bg=C["bg_base"])
        bar.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Radiobutton(
            bar,
            text="新增",
            variable=self._chart_mode,
            value="step",
            bg=C["bg_base"],
            fg=C["text_1"],
            selectcolor=C["bg_base"],
            font=FONT_SM,
            command=self._on_chart_mode_change,
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            bar,
            text="增量",
            variable=self._chart_mode,
            value="delta",
            bg=C["bg_base"],
            fg=C["text_1"],
            selectcolor=C["bg_base"],
            font=FONT_SM,
            command=self._on_chart_mode_change,
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            bar,
            text="全量",
            variable=self._chart_mode,
            value="full",
            bg=C["bg_base"],
            fg=C["text_1"],
            selectcolor=C["bg_base"],
            font=FONT_SM,
            command=self._on_chart_mode_change,
        ).pack(side=tk.LEFT)
        tk.Frame(bar, bg=C["border_sub"], width=1, height=14).pack(side=tk.LEFT, padx=6)
        tk.Label(bar, text="显示", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
        # 点数输入框
        pt_entry = tk.Entry(
            bar,
            textvariable=self._chart_max_points,
            width=3,
            font=FONT_MONO,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        pt_entry.pack(side=tk.LEFT, padx=2)
        tk.Label(bar, text="点", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(0, 6))
        # 渲染按钮
        self._chart_render_btn = tk.Label(
            bar,
            text="▶ 渲染",
            bg=C["bg_elevated"],
            fg=C["accent"],
            font=FONT_SM,
            cursor="hand2",
            padx=6,
            pady=1,
        )
        self._chart_render_btn.pack(side=tk.LEFT)
        self._chart_render_btn.bind("<Button-1>", lambda e: self._manual_render_chart())
        self._chart_render_btn.bind("<Enter>", lambda e: self._chart_render_btn.config(bg=C["bg_hover"]))
        self._chart_render_btn.bind("<Leave>", lambda e: self._chart_render_btn.config(bg=C["bg_elevated"]))
        self._chart_stat_lbl = tk.Label(bar, text="", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM)
        self._chart_stat_lbl.pack(side=tk.RIGHT, padx=4)

        # 图表 Canvas
        self._chart_canvas = tk.Canvas(self._content_area, bg=C["bg_base"], bd=0, highlightthickness=0)
        self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        self._chart_canvas.bind("<Configure>", self._on_chart_resize)

        # 详细数据文本区
        self._detail_text_frame = ctk.CTkFrame(self._content_area, fg_color=C["bg_base"], corner_radius=0)
        detail_vsb = ttk.Scrollbar(self._detail_text_frame)
        detail_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail_text = tk.Text(
            self._detail_text_frame,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            font=FONT_MONO,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            yscrollcommand=detail_vsb.set,
            state="disabled",
            cursor="arrow",
        )
        self._detail_text.pack(fill=tk.BOTH, expand=True)
        detail_vsb.config(command=self._detail_text.yview)
        self._configure_detail_tags()

        # 互动率面板
        self._ratio_frame = ctk.CTkFrame(self._content_area, fg_color=C["bg_base"], corner_radius=0)

        draw_chart_placeholder(self._chart_canvas)
        self._rebuild_stat_bar({})

    def _configure_detail_tags(self):
        """配置详细数据文本的样式标签"""
        self._detail_text.tag_config("head", foreground=C["bilibili"], font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("mono", foreground=C["text_1"], font=FONT_MONO)
        self._detail_text.tag_config("mono_b", foreground=C["bilibili"], font=("Consolas", 10, "bold"))
        self._detail_text.tag_config("mono_ok", foreground=C["success"], font=FONT_MONO)
        self._detail_text.tag_config("mono_accent", foreground=C["accent"], font=("Consolas", 10, "bold"))

    def _build_center_header_empty(self):
        """构建空状态头部提示"""
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        ctk.CTkLabel(h, text="← 从左侧选择一个视频", text_color=C["text_3"], font=FONT, fg_color="transparent").pack(
            side=tk.LEFT, padx=20, pady=18
        )

    def _build_center_header(self, video):
        """构建视频详情头部（标题、UP主、时长、BV号等）"""
        h = self._detail_header
        for w in h.winfo_children():
            w.destroy()
        bvid = video.get("bvid", "")
        title = video.get("title", "未知标题")
        author = video.get("author", "未知UP主")
        dur_sec = video.get("duration", 0)
        pub_ts = video.get("pubdate", 0)
        dur_str = f"{dur_sec // 60}:{dur_sec % 60:02d}" if dur_sec else "—"
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d") if pub_ts else "—"

        info = ctk.CTkFrame(h, fg_color=C["bg_surface"], corner_radius=0)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=14, pady=10)
        # 自适应标题折行宽度（按屏幕宽度的 55% 计算，避免溢出）
        _center_w = int(self.gui.root.winfo_screenwidth() * 0.55)
        title_lbl = ctk.CTkLabel(
            info,
            text=title,
            text_color=C["text_1"],
            font=("Microsoft YaHei UI", 12, "bold"),
            anchor="w",
            wraplength=max(200, _center_w),
            justify="left",
            fg_color="transparent",
        )
        title_lbl.pack(fill=tk.X)

        # 窗口缩放时更新折行宽度
        def _update_wraplength(ev=None):
            try:
                w = info.winfo_width() - 10
                if w > 50:
                    title_lbl.configure(wraplength=w)
            except tk.TclError:
                pass

        info.bind("<Configure>", _update_wraplength)
        # 元数据行：UP主、时长、发布时间
        meta = ctk.CTkFrame(info, fg_color=C["bg_surface"], corner_radius=0)
        meta.pack(fill=tk.X, pady=(4, 0))
        for icon, val in [("👤", author), ("⏱️", dur_str), ("📅", pub_str)]:
            tf = ctk.CTkFrame(meta, fg_color=C["bg_surface"], corner_radius=0)
            tf.pack(side=tk.LEFT, padx=(0, 14))
            ctk.CTkLabel(tf, text=icon, text_color=C["text_2"], font=FONT, fg_color="transparent").pack(side=tk.LEFT)
            ctk.CTkLabel(tf, text=" " + val, text_color=C["text_2"], font=FONT, fg_color="transparent").pack(
                side=tk.LEFT
            )

        # BV 号（可点击复制）
        bv_lbl = ctk.CTkLabel(
            meta,
            text=bvid,
            fg_color=C["bg_elevated"],
            text_color=C["text_3"],
            font=FONT_MONO,
            cursor="hand2",
            corner_radius=4,
        )
        bv_lbl.pack(side=tk.LEFT, padx=6)
        bv_lbl.bind("<Button-1>", lambda e: self.gui._copy_bvid(bvid))
        bv_lbl.bind("<Enter>", lambda e: bv_lbl.configure(text_color=C["accent"]))
        bv_lbl.bind("<Leave>", lambda e: bv_lbl.configure(text_color=C["text_3"]))

        # ── 微调工具栏 ──
        ft_bar = ctk.CTkFrame(info, fg_color=C["bg_surface"], corner_radius=0)
        ft_bar.pack(fill=tk.X, pady=(6, 0))
        self._finetune_btn = ctk.CTkButton(
            ft_bar,
            text="🎯 微调此视频",
            font=FONT_SM,
            fg_color=C.get("accent", "#4A90D9"),
            hover_color=C.get("accent_hover", "#357ABD"),
            text_color="#FFFFFF",
            height=26,
            corner_radius=4,
            width=100,
            command=lambda: _confirm_risky("微调视频模型") and self._open_finetune_dialog(bvid),
        )
        self._finetune_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._finetune_status = ctk.CTkLabel(
            ft_bar,
            text="",
            text_color=C["text_3"],
            font=FONT_SM,
            fg_color="transparent",
        )
        self._finetune_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _open_finetune_dialog(self, bvid: str):
        """打开微调对话框，选择算法并启动微调。"""
        # 扫描有全局 checkpoint 的 DL 算法
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        algos = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            ckpt = CheckpointManager(aid)
            if ckpt.has_checkpoint():
                algos.append({"algorithm_id": aid, "name": getattr(algo, "name", aid)})

        if not algos:
            tk.messagebox.showinfo("提示", "没有已训练的深度学习算法可供微调", parent=self.gui.root)
            return

        dialog = ctk.CTkToplevel(self.gui.root)
        dialog.title(f"微调 — {bvid}")
        dialog.geometry("480x400")
        dialog.transient(self.gui.root)
        dialog.grab_set()

        main_frame = ctk.CTkFrame(dialog, fg_color=C["bg_base"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            main_frame,
            text=f"选择要在 {bvid} 上微调的算法",
            font=FONT_BOLD,
            text_color=C["text_1"],
        ).pack(anchor="w", pady=(0, 6))

        # 算法复选框列表
        scroll = ctk.CTkScrollableFrame(main_frame, fg_color=C["bg_surface"], height=180)
        scroll.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        algo_vars = {}
        for a in sorted(algos, key=lambda x: x["name"]):
            var = tk.BooleanVar(value=True)
            algo_vars[a["algorithm_id"]] = var
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill=tk.X, pady=1)
            ctk.CTkCheckBox(
                row,
                text=f"{a['name']} ({a['algorithm_id']})",
                variable=var,
                font=FONT_SM,
                text_color=C["text_1"],
                fg_color=C.get("accent", "#4A90D9"),
            ).pack(side=tk.LEFT, padx=4, pady=2)

        # 参数设置
        param_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        param_frame.pack(fill=tk.X, pady=(0, 8))
        ctk.CTkLabel(param_frame, text="Epochs:", font=FONT_SM, text_color=C["text_2"]).pack(side=tk.LEFT, padx=(0, 4))
        epoch_var = tk.IntVar(value=5)
        epoch_spin = ctk.CTkEntry(param_frame, textvariable=epoch_var, width=60, font=FONT_MONO)
        epoch_spin.pack(side=tk.LEFT, padx=(0, 16))
        ctk.CTkLabel(param_frame, text="Batch:", font=FONT_SM, text_color=C["text_2"]).pack(side=tk.LEFT, padx=(0, 4))
        batch_var = tk.IntVar(value=16)
        batch_spin = ctk.CTkEntry(param_frame, textvariable=batch_var, width=60, font=FONT_MONO)
        batch_spin.pack(side=tk.LEFT, padx=(0, 16))

        # 状态 & 进度
        status_lbl = ctk.CTkLabel(main_frame, text="就绪", font=FONT_SM, text_color=C["text_3"])
        status_lbl.pack(fill=tk.X, anchor="w")
        progress_bar = ctk.CTkProgressBar(main_frame, height=6)
        progress_bar.pack(fill=tk.X, pady=(4, 8))
        progress_bar.set(0)

        # 按钮
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill=tk.X)
        start_btn = ctk.CTkButton(
            btn_frame,
            text="开始微调",
            font=FONT_SM,
            fg_color=C.get("accent", "#4A90D9"),
            command=lambda: self._run_finetune(
                dialog,
                bvid,
                algo_vars,
                epoch_var,
                batch_var,
                status_lbl,
                progress_bar,
                start_btn,
            ),
        )
        start_btn.pack(side=tk.LEFT, padx=(0, 6))
        ctk.CTkButton(
            btn_frame,
            text="取消",
            font=FONT_SM,
            fg_color=C["bg_elevated"],
            text_color=C["text_1"],
            command=dialog.destroy,
        ).pack(side=tk.LEFT)

    def _run_finetune(
        self,
        dialog,
        bvid,
        algo_vars,
        epoch_var,
        batch_var,
        status_lbl,
        progress_bar,
        start_btn,
    ):
        """在后台线程运行微调，更新对话框进度。"""
        selected = [aid for aid, var in algo_vars.items() if var.get()]
        if not selected:
            tk.messagebox.showinfo("提示", "请至少选择一个算法", parent=dialog)
            return

        epochs = max(1, epoch_var.get())
        batch = max(1, batch_var.get())
        start_btn.configure(state="disabled", text="微调中…")

        def _worker():
            from algorithms.training.trainer import ModelTrainer

            trainer = ModelTrainer()
            total = len(selected)
            self.gui.set_finetune_status(f"🎯 微调 {bvid} …")
            for i, aid in enumerate(selected):
                msg = f"[{i + 1}/{total}] 微调 {aid}…"
                gui_msg = f"🎯 微调 {bvid}: [{i + 1}/{total}] {aid}"
                dialog.after(0, lambda m=msg: status_lbl.configure(text=m))
                dialog.after(0, lambda p=(i + 0.5) / total: progress_bar.set(p))
                dialog.after(0, lambda m=gui_msg: self.gui.set_finetune_status(m))
                try:
                    version = trainer.finetune_for_video(
                        algo_id=aid,
                        bvid=bvid,
                        epochs=epochs,
                        batch_size=batch,
                    )
                    msg = f"✓ {aid} → {version[:12]}"
                except Exception as e:
                    msg = f"✗ {aid}: {e}"
                dialog.after(0, lambda m=msg: status_lbl.configure(text=m))
            dialog.after(0, lambda: status_lbl.configure(text=f"✅ 微调完成 ({total} 个算法)"))
            dialog.after(0, lambda: progress_bar.set(1.0))
            dialog.after(0, lambda: start_btn.configure(text="完成", state="normal"))
            dialog.after(0, lambda: self._finetune_status.configure(text=f"✅ 微调完成 ({total})"))
            dialog.after(0, lambda: self.gui.set_finetune_status(f"✅ 微调 {bvid} 完成 ({total})"))

        threading.Thread(target=_worker, daemon=True).start()

    def _rebuild_stat_bar(self, video):
        """构建统计栏（播放量、点赞、投币、在线人数、分数等）"""
        bar = self._stat_bar
        for w in bar.winfo_children():
            w.destroy()
        self._stat_labels = {}
        fields = [
            ("播放量", "view_count", C["bilibili"]),
            ("点赞", "like_count", C["text_1"]),
            ("投币", "coin_count", C["text_1"]),
            ("收藏", "favorite_count", C["text_1"]),
            ("弹幕", "danmaku_count", C["text_1"]),
            ("评论", "reply_count", C["text_1"]),
            ("在线人数", "_online_viewers", C["accent"]),
            ("点赞率", "_like_rate", C["success"]),
            ("周刊分数", "_weekly_score", C["accent"]),
            ("年刊分数", "_yearly_score", C["warning"]),
        ]
        for label, key, color in fields:
            card = ctk.CTkFrame(
                bar, fg_color=C["bg_elevated"], border_width=1, border_color=C["border_sub"], corner_radius=6
            )
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=8)
            ctk.CTkLabel(
                card, text=label, text_color=C["text_3"], font=FONT_SM, fg_color="transparent", anchor="w"
            ).pack(fill=tk.X, padx=8, pady=(4, 0))
            # 根据 key 获取对应值
            if key == "_like_rate":
                views = video.get("view_count", 1) or 1
                val = f"{video.get('like_count', 0) / views * 100:.2f}%"
            elif key == "_weekly_score":
                val = self._calc_weekly_score_text(video)
            elif key == "_yearly_score":
                val = self._calc_yearly_score_text(video)
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val = f"{fmt_num(total)}" if total > 0 else "—"
            else:
                val = fmt_num(video.get(key, 0)) if video else "—"
            val_lbl = ctk.CTkLabel(
                card, text=val, text_color=color, font=("Consolas", 13, "bold"), fg_color="transparent", anchor="w"
            )
            val_lbl.pack(fill=tk.X, padx=8)
            delta_lbl = ctk.CTkLabel(
                card, text="", text_color=C["success"], font=FONT_SM, fg_color="transparent", anchor="w"
            )
            delta_lbl.pack(fill=tk.X, padx=8, pady=(0, 4))
            self._stat_labels[key] = (val_lbl, delta_lbl)

    def update_stat_bar(self, video):
        """更新统计栏数据"""
        fields = [
            ("view_count", C["bilibili"]),
            ("like_count", C["text_1"]),
            ("coin_count", C["text_1"]),
            ("favorite_count", C["text_1"]),
            ("danmaku_count", C["text_1"]),
            ("reply_count", C["text_1"]),
            ("_online_viewers", C["accent"]),
            ("_like_rate", C["success"]),
            ("_weekly_score", C["accent"]),
            ("_yearly_score", C["warning"]),
        ]
        views = video.get("view_count", 1) or 1
        for key, color in fields:
            pair = self._stat_labels.get(key)
            if not pair:
                continue
            val_lbl, _ = pair
            if key == "_like_rate":
                val_lbl.configure(text=f"{video.get('like_count', 0) / views * 100:.2f}%")
            elif key == "_weekly_score":
                val_lbl.configure(text=self._calc_weekly_score_text(video))
            elif key == "_yearly_score":
                val_lbl.configure(text=self._calc_yearly_score_text(video))
            elif key == "_online_viewers":
                total = video.get("viewers_total", 0)
                val_lbl.configure(text=fmt_num(total) if total > 0 else "—")
            else:
                val_lbl.configure(text=fmt_num(video.get(key, 0)))

    def _switch_tab(self, name):
        """切换标签页"""
        for k, b in self._tab_btns.items():
            b.configure(text_color=C["bilibili"] if k == name else C["text_2"])
        self._current_tab = name
        # 隐藏所有面板
        self._chart_canvas.pack_forget()
        self._detail_text_frame.pack_forget()
        self._ratio_frame.pack_forget()
        if name == "📈 播放量趋势":
            self._chart_canvas.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            mode = self._chart_mode.get()
            if mode == "step":
                self._auto_render_chart()
            else:
                # 非自动模式：切回 tab / 切视频 时清除旧图并显示 placeholder
                self._rendered_modes.discard(mode)
                hint = "点击「渲染增量」查看累计增长" if mode == "delta" else "点击「渲染全量」查看完整数据"
                draw_chart_placeholder(self._chart_canvas, hint)
        elif name == "📋 详细数据":
            self._detail_text_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            video = self._get_selected_video()
            if video:
                self._fill_detail_text(video)
        elif name == "🔄 互动率":
            self._ratio_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
            video = self._get_selected_video()
            if video:
                self._fill_ratio_frame(video)

    def _get_selected_video(self):
        """获取当前选中视频（缓存 bvid→video 避免重复线性搜索）。"""
        bvid = self.gui.selected_bvid
        if not bvid:
            return None
        if not hasattr(self, "_video_index"):
            self._video_index = {}
        if bvid not in self._video_index:
            self._video_index[bvid] = next(
                (v for v in self.gui.monitored_videos if v.get("bvid") == bvid), None
            )
        return self._video_index[bvid]

    def _on_chart_resize(self, event=None):
        """图表尺寸变化时防抖重绘"""
        if self._chart_resize_job:
            self.gui.root.after_cancel(self._chart_resize_job)
        self._chart_resize_job = self.gui.root.after(200, self._do_chart_redraw)

    def _do_chart_redraw(self):
        """执行图表重绘（delta/full 模式下仅当用户已点过渲染才允许）"""
        self._chart_resize_job = None
        # delta/full 模式下，仅当用户已点过渲染才允许 resize 重绘；否则维持 placeholder
        mode = self._chart_mode.get()
        if mode != "step" and mode not in self._rendered_modes:
            return
        self._do_render_chart()

    # ── 图表渲染控制 ─────────────────────────────────

    def _auto_render_chart(self):
        """自动渲染：新数据到来时自动重绘图表（含指纹缓存，数据未变时跳过）"""
        mode = self._chart_mode.get()
        if mode != "step" and mode not in self._rendered_modes:
            return
        self._do_render_chart()

    def _manual_render_chart(self):
        """手动渲染：强制渲染（无模式限制）"""
        self._do_render_chart()

    def _do_render_chart(self):
        """实际执行渲染"""
        if not self.gui.selected_bvid:
            draw_chart_placeholder(self._chart_canvas)
            return
        video = next((v for v in self.gui.monitored_videos if v.get("bvid") == self.gui.selected_bvid), None)
        if not video:
            draw_chart_placeholder(self._chart_canvas)
            return
        try:
            points = max(2, int(self._chart_max_points.get()))
        except (ValueError, tk.TclError):
            points = 20
        pred = self.gui.prediction_results.get(self.gui.selected_bvid)
        draw_chart(
            self._chart_canvas,
            self.gui.history_data,
            self.gui.selected_bvid,
            video,
            FONT,
            mode=self._chart_mode.get(),
            max_points=points,
            prediction=pred,
        )
        self._rendered_modes.add(self._chart_mode.get())

    def _on_chart_mode_change(self):
        """模式切换回调：新增 自动渲染；增量/全量 需点击渲染"""
        mode = self._chart_mode.get()
        if mode == "step":
            self._chart_render_btn.config(text="⟳ 渲染", fg=C["accent"])
            self._chart_stat_lbl.config(text="自动刷新 ✓", fg=C["success"])
            self._auto_render_chart()
        elif mode == "delta":
            self._chart_render_btn.config(text="▶ 渲染增量", fg=C["bilibili"])
            self._chart_stat_lbl.config(text="手动渲染", fg=C["warning"])
            self._rendered_modes.discard("delta")
            draw_chart_placeholder(self._chart_canvas, "点击「渲染增量」查看累计增长")
        else:
            self._chart_render_btn.config(text="▶ 渲染全量", fg=C["bilibili"])
            self._chart_stat_lbl.config(text="手动渲染", fg=C["warning"])
            self._rendered_modes.discard("full")
            draw_chart_placeholder(self._chart_canvas, "点击「渲染全量」查看完整数据")

    @property
    def chart_mode(self):
        return self._chart_mode.get()

    def _fill_detail_text(self, video):
        """填充详细数据文本区。数据指纹未变时跳过全量重建。"""
        # 计算数据指纹，避免无变更时的无效重建
        fp_fields = (
            video.get("view_count", 0), video.get("like_count", 0),
            video.get("coin_count", 0), video.get("favorite_count", 0),
            video.get("share_count", 0), video.get("danmaku_count", 0),
            video.get("reply_count", 0), video.get("viewers_total", 0),
            video.get("title", ""), video.get("author", ""),
        )
        new_fp = hash(fp_fields)
        if new_fp == getattr(self, "_detail_text_fp", None):
            return
        self._detail_text_fp = new_fp

        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", tk.END)
        bvid = video.get("bvid", "")
        title = video.get("title", "N/A")
        author = video.get("author", "未知")
        views = video.get("view_count", 0)
        pub_ts = video.get("pubdate", 0)
        dur = video.get("duration", 0)
        pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M") if pub_ts else "—"
        dur_str = f"{dur // 60}:{dur % 60:02d}" if dur else "—"

        lines = [
            ("=== 视频信息 ===", "head"),
            (f"BV号    {bvid}", "mono"),
            (f"标题    {title}", "mono"),
            (f"UP主    {author}", "mono"),
            (f"时长    {dur_str}", "mono"),
            (f"发布    {pub_str}", "mono"),
            ("", ""),
            ("=== 播放数据 ===", "head"),
            (f"播放量  {fmt_num(views)}", "mono_b"),
            (f"点赞    {fmt_num(video.get('like_count', 0))}", "mono"),
            (f"投币    {fmt_num(video.get('coin_count', 0))}", "mono"),
            (f"分享    {fmt_num(video.get('share_count', 0))}", "mono"),
            (f"收藏    {fmt_num(video.get('favorite_count', 0))}", "mono"),
            (f"弹幕    {fmt_num(video.get('danmaku_count', 0))}", "mono"),
            (f"评论    {fmt_num(video.get('reply_count', 0))}", "mono"),
            ("", ""),
            ("=== 互动率 ===", "head"),
            (f"点赞率  {video.get('like_count', 0) / max(views, 1) * 100:.2f}%", "mono"),
            (f"投币率  {video.get('coin_count', 0) / max(views, 1) * 100:.2f}%", "mono"),
            (f"收藏率  {video.get('favorite_count', 0) / max(views, 1) * 100:.2f}%", "mono"),
            ("", ""),
            ("=== 在线人数 ===", "head"),
        ]
        viewers_total = video.get("viewers_total", 0)
        viewers_web = video.get("viewers_web", 0)
        viewers_app = video.get("viewers_app", 0)
        viewers_raw = video.get("viewers_total_raw", "")
        if viewers_total > 0:
            lines.append((f"总在线  {fmt_num(viewers_total)}  ({viewers_raw})", "mono_accent"))
            lines.append((f"Web端   {fmt_num(viewers_web)}", "mono"))
            lines.append((f"APP端   {fmt_num(viewers_app)}", "mono"))
        else:
            lines.append(("暂无在线人数数据", "mono"))
        lines.append(("", ""))
        lines.append(("=== 阈值进度 ===", "head"))
        for t, name in zip(THRESHOLDS, THRESHOLD_NAMES):
            p = min(100, views / t * 100)
            g = t - views
            if g > 0:
                lines.append((f"{name}  {p:.1f}%  (还差 {fmt_num(g)})", "mono"))
            else:
                lines.append((f"{name}  已达成 ✓", "mono_ok"))

        for text, tag in lines:
            self._detail_text.insert(tk.END, text + "\n", tag if tag else ())

        # 周刊分数详情
        ws = self._calc_weekly_score(video)
        if ws:
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, "=== 周刊分数 ===\n", "head")
            self._detail_text.insert(tk.END, f"最终得点  {ws.total_score:>10,.2f}\n", "mono_accent")
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(
                tk.END,
                f"播放得点  {ws.view_score:>10,.2f}  (基础 {ws.base_view_score:,.0f} × 修正D {ws.correction_d:.4f})\n",
                "mono",
            )
            self._detail_text.insert(
                tk.END, f"互动得点  {ws.interaction_score:>10,.2f}  (修正A {ws.correction_a:.4f})\n", "mono"
            )
            self._detail_text.insert(
                tk.END,
                f"收藏得点  {ws.favorite_score:>10,.2f}  ({video.get('favorite_count', 0):,} × 修正B {ws.correction_b:.4f})\n",
                "mono",
            )
            self._detail_text.insert(
                tk.END,
                f"硬币得点  {ws.coin_score:>10,.2f}  ({video.get('coin_count', 0):,} × 修正C {ws.correction_c:.4f})\n",
                "mono",
            )
            self._detail_text.insert(tk.END, f"点赞得点  {ws.like_score:>10,.2f}\n", "mono")

        # 年刊分数详情
        ys = self._calc_yearly_score(video)
        if ys:
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, "=== 年刊分数 ===\n", "head")
            self._detail_text.insert(tk.END, f"最终得点  {ys.total_score:>10,.2f}\n", "mono_accent")
            self._detail_text.insert(tk.END, "\n", ())
            self._detail_text.insert(tk.END, f"播放得点  {ys.view_score:>10,.2f}\n", "mono")
            self._detail_text.insert(
                tk.END, f"互动得点  {ys.interaction_score:>10,.2f}  (修正A {ys.correction_a:.4f})\n", "mono"
            )
            self._detail_text.insert(
                tk.END,
                f"收藏得点  {ys.favorite_score:>10,.2f}  ({video.get('favorite_count', 0):,} × 修正B {ys.correction_b:.4f})\n",
                "mono",
            )
            self._detail_text.insert(
                tk.END,
                f"硬币得点  {ys.coin_score:>10,.2f}  ({video.get('coin_count', 0):,} × 修正C {ys.correction_c:.4f})\n",
                "mono",
            )
            self._detail_text.insert(tk.END, f"点赞得点  {ys.like_score:>10,.2f}\n", "mono")

        # 历史分数
        if bvid in self.gui.video_dbs:
            history_scores = self.gui.video_dbs[bvid].get_weekly_scores(limit=5)
            if len(history_scores) > 1:
                self._detail_text.insert(tk.END, "\n", ())
                self._detail_text.insert(tk.END, "=== 历史周刊分数 ===\n", "head")
                for row in history_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    self._detail_text.insert(tk.END, f"  {ts_str}  {total:>10,.2f}\n", "mono")
            yearly_scores = self.gui.video_dbs[bvid].get_yearly_scores(limit=5)
            if len(yearly_scores) > 1:
                self._detail_text.insert(tk.END, "\n", ())
                self._detail_text.insert(tk.END, "=== 历史年刊分数 ===\n", "head")
                for row in yearly_scores:
                    ts_str = row.get("timestamp", "")[:16]
                    total = row.get("total_score", 0)
                    self._detail_text.insert(tk.END, f"  {ts_str}  {total:>10,.2f}\n", "mono")
        self._detail_text.config(state="disabled")

    def _calc_weekly_score(self, video):
        """计算周刊分数"""
        try:
            return _calc_ws(video)
        except Exception:
            return None

    def _calc_weekly_score_text(self, video):
        """获取周刊分数文本"""
        ws = self._calc_weekly_score(video)
        return f"{ws.total_score:,.0f}" if ws else "—"

    def _calc_yearly_score(self, video):
        """计算年刊分数"""
        try:
            return _calc_ys(video)
        except Exception:
            return None

    def _calc_yearly_score_text(self, video):
        """获取年刊分数文本"""
        ys = self._calc_yearly_score(video)
        return f"{ys.total_score:,.0f}" if ys else "—"

    def _fill_ratio_frame(self, video):
        """填充互动率面板"""
        for w in self._ratio_frame.winfo_children():
            w.destroy()
        views = video.get("view_count", 1) or 1
        ratios = [
            ("点赞率", video.get("like_count", 0) / views * 100, C["bilibili"]),
            ("投币率", video.get("coin_count", 0) / views * 100, C["accent"]),
            ("收藏率", video.get("favorite_count", 0) / views * 100, C["success"]),
            ("弹幕率", video.get("danmaku_count", 0) / views * 100, C["warning"]),
        ]
        for label, pct, color in ratios:
            row = ctk.CTkFrame(self._ratio_frame, fg_color=C["bg_base"], corner_radius=0)
            row.pack(fill=tk.X, pady=6)
            ctk.CTkLabel(row, text=label, text_color=C["text_2"], font=FONT, fg_color="transparent", width=48).pack(
                side=tk.LEFT
            )
            bg_bar = tk.Frame(row, bg=C["bg_elevated"], height=12)
            bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            bg_bar.pack_propagate(False)
            fill_pct = min(pct / 20, 1.0)
            tk.Frame(bg_bar, bg=color, height=12).place(x=0, y=0, relwidth=fill_pct, relheight=1)
            ctk.CTkLabel(
                row, text=f"{pct:.3f}%", text_color=color, font=FONT_MONO, fg_color="transparent", width=72
            ).pack(side=tk.LEFT)

    @property
    def chart_canvas(self):
        return self._chart_canvas

    @property
    def current_tab(self):
        return self._current_tab
