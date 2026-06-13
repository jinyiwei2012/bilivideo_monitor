"""
算法可视化对比窗口
================

对比多个预测算法的历史准确率（MAE/MAPE），
含排名表、误差分布图、预测 vs 实际对比图。

数据来源：per-video 数据库中的 predictions 表（含 error_rate）。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict
from datetime import datetime

from ui.theme import C
from ui.dialog_base import DialogBase
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num


class AlgorithmCompareWindow:
    """算法预测对比分析窗口"""

    def __init__(self, parent=None, gui=None):
        self.dlg = DialogBase(
            parent, "算法预测对比", DialogBase.calc_geometry(parent, 0.62, 0.72),
            resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.gui = gui
        self._algo_data: List[Dict] = []
        self._current_bvid = ""
        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("算法预测对比", "对比各算法的历史预测准确率与误差分布")

        # ── 视频选择 ──
        sec = self.dlg.section(title="选择视频", padding=8)
        row0 = tk.Frame(sec, bg=C["bg_elevated"])
        row0.pack(fill=tk.X)
        tk.Label(row0, text="视频:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT).pack(side=tk.LEFT)

        self._bv_var = tk.StringVar()
        if self.gui and self.gui.monitored_videos:
            values = [f"{v.get('bvid','')}  {v.get('title','')[:25]}"
                      for v in self.gui.monitored_videos]
            self._bv_cb = ttk.Combobox(row0, textvariable=self._bv_var,
                                        values=values, width=50,
                                        font=("Consolas", 9), state="readonly")
            self._bv_cb.pack(side=tk.LEFT, padx=(6, 8))
            if values:
                self._bv_cb.current(0)
            self._bv_cb.bind("<<ComboboxSelected>>", lambda e: self._load_data())

        ttk.Button(row0, text="🔍 分析", command=self._load_data,
                   style="Primary.TButton").pack(side=tk.LEFT)

        self._status_lbl = tk.Label(sec, text="", bg=C["bg_elevated"],
                                     fg=C["text_3"], font=FONT_SM)
        self._status_lbl.pack(anchor="w", padx=4, pady=(4, 0))

        # ── 主内容：Notebook ──
        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(8, 12))

        # Tab 1: 排名表
        rank_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(rank_page, text="  📊 准确率排名  ")
        self._build_rank_tab(rank_page)

        # Tab 2: 误差分布
        err_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(err_page, text="  📈 误差分布  ")
        self._build_error_tab(err_page)

        # Tab 3: 预测 vs 实际
        pred_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(pred_page, text="  🎯 预测 vs 实际  ")
        self._build_predict_tab(pred_page)

    def _build_rank_tab(self, parent):
        """排名表：算法名 / MAE / MAPE / 置信度 / 样本数"""
        cols = ("排名", "算法名称", "MAE", "MAPE", "平均置信度", "样本数")
        tree_frame = tk.Frame(parent, bg=C["bg_elevated"],
                              highlightthickness=1,
                              highlightbackground=C["border_sub"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._rank_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=15)
        widths = [40, 200, 80, 80, 80, 60]
        for col, w in zip(cols, widths):
            self._rank_tree.heading(col, text=col)
            self._rank_tree.column(col, width=w, anchor="center" if col != "算法名称" else "w")
        self._rank_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._rank_tree.yview)
        self._rank_tree.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._rank_tree.tag_configure("top3", foreground=C["bilibili"],
                                       font=("Consolas", 9, "bold"))

    def _build_error_tab(self, parent):
        """误差分布 Canvas（柱状图 + 箱线图）"""
        self._err_canvas = tk.Canvas(parent, bg=C["bg_base"], highlightthickness=0)
        self._err_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._err_canvas.bind("<Configure>", self._on_err_resize)

    def _build_predict_tab(self, parent):
        """预测值 vs 实际值对比表"""
        cols = ("时间", "实际播放量", "加权预测", "最佳预测", "最差预测")
        tree_frame = tk.Frame(parent, bg=C["bg_elevated"],
                              highlightthickness=1,
                              highlightbackground=C["border_sub"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._pred_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=15)
        widths = [140, 100, 100, 180, 180]
        for col, w in zip(cols, widths):
            self._pred_tree.heading(col, text=col)
            self._pred_tree.column(col, width=w, anchor="center")
        self._pred_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._pred_tree.yview)
        self._pred_tree.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def _load_data(self):
        """从数据库加载预测对比数据。"""
        bv_text = self._bv_var.get()
        if not bv_text:
            messagebox.showwarning("提示", "请先选择视频", parent=self.window)
            return
        bvid = bv_text.split()[0]
        self._current_bvid = bvid

        video_db = self.gui.video_dbs.get(bvid) if self.gui else None
        if not video_db:
            self._status_lbl.config(text="无法访问数据库")
            return

        try:
            records = self._get_prediction_history(video_db)
        except Exception as e:
            self._status_lbl.config(text=f"加载失败: {e}")
            return

        if not records:
            self._status_lbl.config(text="暂无预测数据")
            return

        self._algo_data = self._compute_algo_stats(records)
        self._populate_rank_table()
        self._draw_error_chart()
        self._populate_predict_table(records)
        self._status_lbl.config(
            text=f"已加载 {len(self._algo_data)} 个算法 · {len(records)} 条预测记录"
        )

    def _get_prediction_history(self, video_db) -> List[Dict]:
        """从数据库获取预测历史记录。"""
        try:
            with video_db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT p.*, m.view_count as actual_view, m.timestamp as monitor_time
                    FROM predictions p
                    LEFT JOIN monitor_records m ON m.timestamp = p.created_at
                    WHERE m.view_count IS NOT NULL
                    ORDER BY p.created_at DESC
                    LIMIT 500
                """)
                return [dict(row) for row in cursor.fetchall()]
        except Exception:
            # SQLite 不支持复杂 JOIN 时简化为分别查询
            try:
                with video_db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT * FROM predictions ORDER BY created_at DESC LIMIT 500"
                    )
                    return [dict(row) for row in cursor.fetchall()]
            except Exception:
                return []

    def _compute_algo_stats(self, records: List[Dict]) -> List[Dict]:
        """按算法聚合统计：MAE、MAPE、置信度、样本数。"""
        algo_map: Dict[str, List[Dict]] = {}
        for r in records:
            algo = r.get("algorithm", "unknown")
            if algo not in algo_map:
                algo_map[algo] = []
            algo_map[algo].append(r)

        stats = []
        for name, rows in algo_map.items():
            errors = []
            confidences = []
            for r in rows:
                err = r.get("error_rate", 0) or 0
                conf = r.get("confidence", 0) or 0
                current = r.get("current_views", 0) or 1
                predicted = int(r.get("predicted_seconds", 0) / 60) if r.get("predicted_seconds") else 0
                errors.append(err)
                confidences.append(conf)

            n = len(rows)
            mae_val = sum(abs(e) for e in errors) / n if n else 0
            # MAPE 以 error_rate 近似
            mape_val = (sum(e for e in errors if e > 0) / n * 100) if n else 0
            avg_conf = sum(confidences) / n if n else 0

            stats.append({
                "name": name,
                "n": n,
                "mae": mae_val,
                "mape": mape_val,
                "avg_confidence": avg_conf,
            })

        # 按 MAE 升序
        stats.sort(key=lambda x: x["mae"])
        return stats

    def _populate_rank_table(self):
        """填充排名表。"""
        self._rank_tree.delete(*self._rank_tree.get_children())
        for i, s in enumerate(self._algo_data):
            tag = "top3" if i < 3 else ""
            self._rank_tree.insert(
                "", tk.END,
                values=(
                    i + 1,
                    s["name"],
                    f"{s['mae']:,.0f}",
                    f"{s['mape']:.1f}%",
                    f"{s['avg_confidence']:.1%}",
                    s["n"],
                ),
                tags=(tag,),
            )

    def _draw_error_chart(self):
        """在 Canvas 上绘制误差分布柱状图。"""
        c = self._err_canvas
        c.delete("all")
        if not self._algo_data:
            return

        W = c.winfo_width() or 600
        H = c.winfo_height() or 300
        if W < 50 or H < 50:
            return

        ML, MR, MT, MB = 60, 20, 30, 50
        cw = W - ML - MR
        ch = H - MT - MB

        # 只显示前 20 个算法
        top = self._algo_data[:20]
        n = len(top)
        bar_w = max(8, min(30, cw // n - 4))
        max_err = max(s["mae"] for s in top) or 1
        max_mape = max(s["mape"] for s in top) or 1

        # 双 Y 轴：左=MAE, 右=MAPE
        for i, s in enumerate(top):
            x = ML + (i + 0.5) * cw / n
            # MAE 柱
            mae_h = (s["mae"] / max_err) * ch * 0.9 if max_err > 0 else 0
            c.create_rectangle(
                x - bar_w / 2, MT + ch - mae_h, x + bar_w / 2, MT + ch,
                fill=C["accent"], outline="",
            )
            # MAPE 线（散点标记）
            mape_y = MT + ch - (s["mape"] / max_mape) * ch * 0.9 if max_mape > 0 else MT + ch
            c.create_oval(x - 3, mape_y - 3, x + 3, mape_y + 3,
                          fill=C["danger"], outline="")

            # 标签（每 5 个）
            if i % 5 == 0 or i == n - 1:
                name = s["name"].replace("[Model] ", "")[:12]
                c.create_text(x, MT + ch + 12, text=name, fill=C["text_3"],
                              font=("Microsoft YaHei UI", 7), angle=45, anchor="w")

        # 图例
        c.create_rectangle(ML + 4, MT + 4, ML + 16, MT + 16, fill=C["accent"], outline="")
        c.create_text(ML + 22, MT + 10, text="MAE(绝对误差)", anchor="w",
                      fill=C["text_2"], font=("Microsoft YaHei UI", 8))
        c.create_oval(ML + 120, MT + 5, ML + 132, MT + 17, fill=C["danger"], outline="")
        c.create_text(ML + 138, MT + 10, text="MAPE(百分比误差)", anchor="w",
                      fill=C["text_2"], font=("Microsoft YaHei UI", 8))

    def _populate_predict_table(self, records: List[Dict]):
        """填充预测 vs 实际对比表。"""
        self._pred_tree.delete(*self._pred_tree.get_children())
        # 按时间排序取最近 50 条
        sorted_recs = sorted(records, key=lambda r: str(r.get("created_at", "")), reverse=True)[:50]
        for r in sorted_recs:
            ts = str(r.get("created_at", ""))[:16]
            actual = r.get("current_views", 0) or 0
            predicted = int(r.get("predicted_seconds", 0) / 60) if r.get("predicted_seconds") else 0
            algo = r.get("algorithm", "")
            conf = r.get("confidence", 0) or 0
            self._pred_tree.insert(
                "", tk.END,
                values=(ts, fmt_num(actual), fmt_num(predicted),
                        f"{algo} ({conf:.0%})", ""),
            )

    def _on_err_resize(self, event=None):
        """防抖重绘误差图。"""
        if getattr(self, "_err_resize_job", None):
            self.window.after_cancel(self._err_resize_job)
        self._err_resize_job = self.window.after(200, self._draw_error_chart)
