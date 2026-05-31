"""
预测回测（误差分析）面板
对比历史预测值 vs 实际播放量，计算 MAE/MAPE，评估各算法表现
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import math
from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num
from ui.dialog_base import DialogBase


class BacktestPanel:
    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "📊 预测回测", "800x540")
        self.dlg.header("预测回测 — 误差分析", "对比历史预测值 vs 实际播放量")
        self._build_ui()

    def _build_ui(self):
        top = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        top.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(top, text="选择视频:", bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(side=tk.LEFT)
        self._video_var = tk.StringVar()
        self._video_combo = ttk.Combobox(top, textvariable=self._video_var, font=FONT, state="readonly", width=40)
        self._video_combo.pack(side=tk.LEFT, padx=6)
        self._video_combo.bind("<<ComboboxSelected>>", lambda e: self._analyze())

        ttk.Button(top, text="📊 分析", command=self._analyze).pack(side=tk.LEFT, padx=4)

        # 统计摘要
        self._summary_frame = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        self._summary_frame.pack(fill=tk.X, padx=10, pady=4)

        # 结果表格
        columns = ("algo", "mae", "mape", "samples", "avg_pred", "avg_actual", "bias")
        self._tree = ttk.Treeview(
            self.dlg.content_area(), columns=columns, show="headings", height=16
        )
        self._tree.heading("algo", text="算法")
        self._tree.heading("mae", text="MAE")
        self._tree.heading("mape", text="MAPE")
        self._tree.heading("samples", text="样本数")
        self._tree.heading("avg_pred", text="平均预测")
        self._tree.heading("avg_actual", text="平均实际")
        self._tree.heading("bias", text="偏差倾向")
        self._tree.column("algo", width=160)
        self._tree.column("mae", width=80, anchor="e")
        self._tree.column("mape", width=70, anchor="e")
        self._tree.column("samples", width=60, anchor="center")
        self._tree.column("avg_pred", width=90, anchor="e")
        self._tree.column("avg_actual", width=90, anchor="e")
        self._tree.column("bias", width=70, anchor="center")
        self._tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        scroll = ttk.Scrollbar(self._tree, command=self._tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.configure(yscrollcommand=scroll.set)

        # 填充视频列表
        videos = self.gui.monitored_videos
        names = [f"{v.get('title', v.get('bvid', ''))[:35]} ({v.get('bvid', '')})" for v in videos]
        self._video_combo["values"] = names
        if names:
            self._video_combo.current(0)
            self._analyze()

    def _analyze(self):
        for row in self._tree.get_children():
            self._tree.delete(row)
        for w in self._summary_frame.winfo_children():
            w.destroy()

        idx = self._video_combo.current()
        if idx < 0:
            return
        video = self.gui.monitored_videos[idx]
        bvid = video.get("bvid", "")
        title = video.get("title", bvid)[:30]

        video_db = self.gui.video_dbs.get(bvid)
        if not video_db:
            tk.Label(self._summary_frame, text="该视频无数据库记录", fg=C["text_3"], bg=C["bg_base"], font=FONT).pack()
            return

        try:
            predictions = video_db.get_predictions(limit=5000)
        except Exception as e:
            tk.Label(self._summary_frame, text=f"读取预测记录失败: {e}", fg=C["danger"], bg=C["bg_base"], font=FONT).pack()
            return

        if not predictions:
            tk.Label(self._summary_frame, text="暂无预测记录", fg=C["text_3"], bg=C["bg_base"], font=FONT).pack()
            return

        # 按算法分组计算误差
        algo_stats = {}
        for p in predictions:
            try:
                pred_views = p.get("predicted_views", 0) or p.get("predicted_view", 0)
                actual_views = p.get("current_views_at_eval", 0) or p.get("actual_views", 0)
                algo = p.get("algorithm", p.get("algorithm_name", "未知"))
                if pred_views <= 0 or actual_views <= 0:
                    continue
            except Exception:
                continue

            if algo not in algo_stats:
                algo_stats[algo] = {"preds": [], "actuals": []}
            algo_stats[algo]["preds"].append(pred_views)
            algo_stats[algo]["actuals"].append(actual_views)

        if not algo_stats:
            tk.Label(self._summary_frame, text="无有效的预测-实际对照数据", fg=C["text_3"], bg=C["bg_base"], font=FONT).pack()
            return

        # 计算各项指标
        rows = []
        for algo, data in algo_stats.items():
            preds = data["preds"]
            actuals = data["actuals"]
            if len(preds) < 2:
                continue
            errors = [abs(p - a) / max(a, 1) for p, a in zip(preds, actuals)]
            mape = sum(errors) / len(errors) * 100
            mae = sum(abs(p - a) for p, a in zip(preds, actuals)) / len(preds)
            avg_pred = sum(preds) / len(preds)
            avg_actual = sum(actuals) / len(actuals)
            bias = "偏高" if avg_pred > avg_actual * 1.1 else "偏低" if avg_pred < avg_actual * 0.9 else "适中"
            rows.append((mape, algo, mae, mape, len(preds), avg_pred, avg_actual, bias))

        rows.sort(key=lambda x: x[0])  # 按 MAPE 升序

        # 摘要
        best = rows[0]
        worst = rows[-1] if len(rows) > 1 else None
        summary_text = f"🎯 最佳: {best[1]} (MAPE={best[3]:.1f}%)"
        if worst:
            summary_text += f"  |  ❌ 最差: {worst[1]} (MAPE={worst[3]:.1f}%)"
        tk.Label(self._summary_frame, text=summary_text, bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(anchor="w")

        for _, algo, mae, mape, samples, avg_pred, avg_actual, bias in rows:
            self._tree.insert("", tk.END, values=(
                algo[:20], fmt_num(int(mae)), f"{mape:.1f}%", samples,
                fmt_num(int(avg_pred)), fmt_num(int(avg_actual)), bias
            ))
