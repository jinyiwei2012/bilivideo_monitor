"""
现代化数据库查询界面
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import os
import re
import csv
import logging
from datetime import datetime
from typing import Optional

from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)


def _validate_bvid(bvid: str) -> bool:
    return bool(re.match(r"^BV[A-Za-z0-9]{10}$", bvid))


_BASE_EXPORT_HEADERS = [
    "序号",
    "BV号",
    "时间",
    "播放量",
    "点赞",
    "投币",
    "分享",
    "收藏",
    "弹幕",
    "评论",
    "APP观看",
    "网页观看",
    "总观看",
    "播赞比",
    "周刊总分",
    "周刊播放",
    "周刊互动",
    "周刊收藏",
    "周刊硬币",
    "周刊点赞",
    "周刊修正A",
    "周刊修正B",
    "周刊修正C",
    "周刊修正D",
    "周刊基础播放",
    "年刊总分",
    "年刊播放",
    "年刊互动",
    "年刊收藏",
    "年刊硬币",
    "年刊点赞",
    "年刊修正A",
    "年刊修正B",
    "年刊修正C",
]


def _build_export_headers(algo_names: list) -> list:
    headers = list(_BASE_EXPORT_HEADERS)
    for name in algo_names:
        headers.append(f"{name}_预测时间")
        headers.append(f"{name}_预测秒数")
        headers.append(f"{name}_置信度")
    return headers


def _build_export_row(index: int, row, extra: dict = None, algo_names: list = None) -> list:
    e = extra or {}
    algo_names = algo_names or []
    if hasattr(row, "keys"):
        row = dict(row)
    algo_pred_map = {}
    for pred in e.get("_predictions", []):
        algo = pred.get("algorithm", "")
        if algo not in algo_pred_map:
            algo_pred_map[algo] = pred

    base_row = [
        index,
        row["bvid"],
        row["timestamp"],
        row["view_count"],
        row["like_count"],
        row["coin_count"],
        row["share_count"],
        row["favorite_count"],
        row["danmaku_count"],
        row["reply_count"],
        row.get("viewers_app", "") or "",
        row.get("viewers_web", "") or "",
        row.get("viewers_total", "") or "",
        row.get("like_view_ratio", "") or "",
        e.get("weekly_total", ""),
        e.get("weekly_view", ""),
        e.get("weekly_interaction", ""),
        e.get("weekly_favorite", ""),
        e.get("weekly_coin", ""),
        e.get("weekly_like", ""),
        e.get("weekly_corr_a", ""),
        e.get("weekly_corr_b", ""),
        e.get("weekly_corr_c", ""),
        e.get("weekly_corr_d", ""),
        e.get("weekly_base_view", ""),
        e.get("yearly_total", ""),
        e.get("yearly_view", ""),
        e.get("yearly_interaction", ""),
        e.get("yearly_favorite", ""),
        e.get("yearly_coin", ""),
        e.get("yearly_like", ""),
        e.get("yearly_corr_a", ""),
        e.get("yearly_corr_b", ""),
        e.get("yearly_corr_c", ""),
    ]
    for name in algo_names:
        pred = algo_pred_map.get(name, {})
        base_row.append(pred.get("predicted_time", ""))
        base_row.append(pred.get("predicted_seconds", ""))
        base_row.append(pred.get("confidence", ""))
    return base_row


class DatabaseQueryWindow:
    """数据库查询窗口（现代化风格）"""

    def __init__(self, parent):
        self.dlg = DialogBase(parent, "数据库查询", "1040x720", resizable=(True, True), modal=False)
        self.window = self.dlg.window
        self.db_path = self._get_db_path()
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self._query_running = False

        self.setup_ui()
        self.load_videos_list()

    def _get_db_path(self) -> str:
        cd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(cd, "data", "bilibili_monitor.db")

    def setup_ui(self):
        self.dlg.header("数据库查询", "查询监控记录、播放趋势与算法预测数据")

        # 查询条件卡片
        q_sec = self.dlg.section(padding=6)

        # 视频筛选
        fr = tk.Frame(q_sec, bg=C["bg_elevated"])
        fr.pack(fill=tk.X, pady=2)
        tk.Label(fr, text="视频筛选", bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=12, anchor="w").pack(
            side=tk.LEFT
        )
        self.video_filter_var = tk.StringVar(value="全部视频")
        self.video_filter_combo = ttk.Combobox(
            fr, textvariable=self.video_filter_var, state="readonly", width=40, font=FONT
        )
        self.video_filter_combo.pack(side=tk.LEFT, padx=(8, 0))

        # 查询方式
        mr = tk.Frame(q_sec, bg=C["bg_elevated"])
        mr.pack(fill=tk.X, pady=2)
        tk.Label(mr, text="查询方式", bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=12, anchor="w").pack(
            side=tk.LEFT
        )
        self.query_mode = tk.StringVar(value="latest")
        mode_combo = ttk.Combobox(
            mr,
            textvariable=self.query_mode,
            values=["最新N条", "播放首次大于X", "播放趋势", "全量数据"],
            state="readonly",
            width=20,
            font=FONT,
        )
        mode_combo.pack(side=tk.LEFT, padx=(8, 0))
        mode_combo.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())

        # 参数
        self.param_frame = tk.Frame(q_sec, bg=C["bg_elevated"])
        self.param_frame.pack(fill=tk.X, pady=2)
        self.video_combo = None
        self.video_combo_var = tk.StringVar()

        # 按钮行
        br = tk.Frame(q_sec, bg=C["bg_elevated"])
        br.pack(fill=tk.X, pady=(6, 0))
        self._query_btn = ttk.Button(br, text="查询", command=self._do_query, style="Primary.TButton")
        self._query_btn.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(br, text="重置", command=self._reset_query).pack(side=tk.LEFT)

        self._on_mode_change()

        # 结果区域
        container = tk.Frame(self.dlg.container, bg=C["bg_base"])
        container.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        res_label = tk.Frame(container, bg=C["bg_base"])
        res_label.pack(fill=tk.X)
        tk.Label(
            res_label, text="查询结果", bg=C["bg_base"], fg=C["text_2"], font=("Microsoft YaHei UI", 8, "bold")
        ).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(res_label, textvariable=self.status_var, bg=C["bg_base"], fg=C["text_3"], font=FONT_SM).pack(
            side=tk.RIGHT
        )

        res_frame = tk.Frame(container, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        res_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        columns = (
            "seq",
            "bv",
            "timestamp",
            "views",
            "likes",
            "coins",
            "shares",
            "favorites",
            "danmaku",
            "reply",
            "viewers_total",
            "viewers_web",
            "viewers_app",
            "like_ratio",
        )
        self.result_tree = ttk.Treeview(res_frame, columns=columns, show="headings", height=15)
        col_configs = [
            ("seq", "序号", 50),
            ("bv", "BV号", 120),
            ("timestamp", "时间", 150),
            ("views", "播放量", 90),
            ("likes", "点赞", 75),
            ("coins", "投币", 75),
            ("shares", "分享", 75),
            ("favorites", "收藏", 75),
            ("danmaku", "弹幕", 75),
            ("reply", "评论", 75),
            ("viewers_total", "总在线", 75),
            ("viewers_web", "Web在线", 75),
            ("viewers_app", "APP在线", 75),
            ("like_ratio", "播赞比", 75),
        ]
        for col, heading, width in col_configs:
            self.result_tree.column(col, width=width, anchor="center")
            self.result_tree.heading(col, text=heading)
        sb = ttk.Scrollbar(res_frame, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=sb.set)
        self.result_tree.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        sb.pack(side="right", fill="y")

        # 底部操作按钮
        ba = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        ba.pack(fill=tk.X, padx=24, pady=(8, 16))
        ttk.Button(ba, text="导出CSV", command=self._export_csv).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(ba, text="导出Excel", command=self._export_excel).pack(side=tk.LEFT, padx=4)
        ttk.Button(ba, text="删除选中", command=self._delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(ba, text="清空结果", command=self._clear_results).pack(side=tk.LEFT, padx=4)

    def _get_filter_bvid(self) -> Optional[str]:
        sel = self.video_filter_var.get()
        if sel == "全部视频" or not sel:
            return None
        return self._video_bvid_map.get(sel)

    def _get_video_db_path(self, bvid: str) -> Optional[str]:
        """查找视频独立库路径：优先 data/，回退 core/data/"""
        primary = os.path.join(os.path.dirname(self.db_path), bvid, f"{bvid}.db")
        if os.path.exists(primary):
            return primary
        # 互补：备份路径 core/data/BVxxx/BVxxx.db
        backup = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "core", "data", bvid, f"{bvid}.db",
        )
        return backup if os.path.exists(backup) else None

    def _load_extra_data(self, bvid: str, timestamp: str) -> dict:
        extra = {}
        vdp = self._get_video_db_path(bvid)
        if not vdp:
            return extra
        try:
            uri = "file:{}?mode=ro".format(vdp.replace("\\", "/").replace(" ", "%20"))
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM predictions WHERE created_at <= ? ORDER BY algorithm, created_at DESC", (timestamp,)
            )
            pred_rows = cur.fetchall()
            seen = set()
            pred_list = []
            for pr in pred_rows:
                an = pr["algorithm"]
                if an not in seen:
                    seen.add(an)
                    pred_list.append(dict(pr))
            extra["_predictions"] = pred_list

            cur.execute(
                "SELECT * FROM weekly_scores WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1", (timestamp,)
            )
            ws = cur.fetchone()
            if ws:
                wd = dict(ws)
                for k in [
                    "total_score",
                    "view_score",
                    "interaction_score",
                    "favorite_score",
                    "coin_score",
                    "like_score",
                    "correction_a",
                    "correction_b",
                    "correction_c",
                    "correction_d",
                    "base_view_score",
                ]:
                    extra[f"weekly_{k}"] = wd.get(k, "")
            cur.execute(
                "SELECT * FROM yearly_scores WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1", (timestamp,)
            )
            ys = cur.fetchone()
            if ys:
                yd = dict(ys)
                for k in [
                    "total_score",
                    "view_score",
                    "interaction_score",
                    "favorite_score",
                    "coin_score",
                    "like_score",
                    "correction_a",
                    "correction_b",
                    "correction_c",
                ]:
                    extra[f"yearly_{k}"] = yd.get(k, "")
            conn.close()
        except Exception as e:
            logger.debug("查询视频额外数据失败: %s", e)
        return extra

    def _on_mode_change(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        mode = self.query_mode.get()
        if mode == "最新N条":
            tk.Label(self.param_frame, text="数量N:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
            self.param_var = tk.StringVar(value="100")
            ttk.Entry(self.param_frame, textvariable=self.param_var, width=10, font=FONT).pack(
                side=tk.LEFT, padx=(4, 0)
            )
            tk.Label(self.param_frame, text="(要查询的记录数)", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM).pack(
                side=tk.LEFT, padx=8
            )
        elif mode == "播放首次大于X":
            tk.Label(self.param_frame, text="播放量X:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
                side=tk.LEFT
            )
            self.param_var = tk.StringVar(value="10000")
            ttk.Entry(self.param_frame, textvariable=self.param_var, width=15, font=FONT).pack(
                side=tk.LEFT, padx=(4, 0)
            )
        elif mode == "播放趋势":
            tk.Label(self.param_frame, text="选择视频:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
                side=tk.LEFT
            )
            self.video_combo = ttk.Combobox(
                self.param_frame, textvariable=self.video_combo_var, state="readonly", width=30, font=FONT
            )
            self.video_combo.pack(side=tk.LEFT, padx=(4, 0))
        elif mode == "全量数据":
            tk.Label(
                self.param_frame, text="(将导出所有监控记录数据)", bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM
            ).pack(side=tk.LEFT)

    def load_videos_list(self):
        if not os.path.exists(self.db_path):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT bvid, title FROM videos ORDER BY updated_at DESC")
            videos = cur.fetchall()
            items = ["全部视频"]
            self._video_bvid_map = {}
            for v in videos:
                d = f"{v['bvid']} - {v['title']}"
                items.append(d)
                self._video_bvid_map[d] = v["bvid"]
            self.video_filter_combo["values"] = items
            self.video_filter_combo.current(0)
            if self.video_combo:
                self.video_combo["values"] = items[1:]
            conn.close()
        except Exception as e:
            logger.debug("加载视频列表失败: %s", e)

    def _do_query(self):
        if not os.path.exists(self.db_path):
            messagebox.showerror("错误", "数据库文件不存在", parent=self.window)
            return
        if self._query_running:
            return

        mode = self.query_mode.get()
        filter_bvid = self._get_filter_bvid()
        bvid_for_trend = None

        if mode == "播放趋势":
            sel = self.video_combo_var.get()
            if not sel:
                if filter_bvid:
                    bvid_for_trend = filter_bvid
                else:
                    messagebox.showwarning("提示", "请选择视频", parent=self.window)
                    return
            else:
                bvid_for_trend = sel.split()[0] if " " in sel else sel
                if filter_bvid:
                    bvid_for_trend = filter_bvid
            if not _validate_bvid(bvid_for_trend):
                messagebox.showerror("错误", "选中视频的BV号格式无效", parent=self.window)
                return

        self._query_running = True
        self._query_btn.config(state="disabled", text="查询中…")
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self.status_var.set("查询中…")

        import threading

        threading.Thread(target=self._query_worker, args=(mode, filter_bvid, bvid_for_trend), daemon=True).start()

    def _query_worker(self, mode, filter_bvid, bvid_for_trend):
        """后台线程：执行数据库查询并加载关联数据。"""
        raw_rows = []
        err_msg = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            raw_rows = self._run_query(cur, mode, filter_bvid, bvid_for_trend)
            conn.close()
        except Exception as e:
            err_msg = str(e)

        if err_msg:
            self.window.after(
                0,
                lambda: (
                    messagebox.showerror("错误", f"查询失败: {err_msg}", parent=self.window),
                    self._reset_query_state(),
                ),
            )
            return

        total = len(raw_rows)
        self.window.after(0, lambda: self.status_var.set(f"查询到 {total} 条，加载关联数据…"))

        extra_list, anames = self._load_query_extra_data(raw_rows)
        self.window.after(0, lambda: self._finish_query(raw_rows, extra_list, anames))

    def _run_query(self, cur, mode, filter_bvid, bvid_for_trend):
        """根据查询模式执行 SQL，返回 dict 行列表。"""
        if mode == "最新N条":
            limit = int(getattr(self, "param_var", None) and self.param_var.get() or 100)
            if filter_bvid:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp DESC LIMIT ?",
                    (filter_bvid, limit),
                )
            else:
                cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT ?", (limit,))
        elif mode == "播放首次大于X":
            thr = int(getattr(self, "param_var", None) and self.param_var.get() or 10000)
            if filter_bvid:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? AND view_count > ? ORDER BY timestamp ASC LIMIT 1",
                    (filter_bvid, thr),
                )
            else:
                cur.execute(
                    """WITH fa AS (SELECT bvid, MIN(timestamp) as ft FROM monitor_records WHERE view_count > ? GROUP BY bvid)
                               SELECT m.* FROM monitor_records m INNER JOIN fa f ON m.bvid = f.bvid AND m.timestamp = f.ft ORDER BY m.timestamp DESC""",
                    (thr,),
                )
        elif mode == "播放趋势":
            cur.execute("SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp ASC", (bvid_for_trend,))
        elif mode == "全量数据":
            if filter_bvid:
                cur.execute("SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp DESC", (filter_bvid,))
            else:
                cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC")
        return [dict(r) for r in cur.fetchall()]

    def _load_query_extra_data(self, raw_rows):
        """加载查询结果的关联数据（算法预测等）。返回 (extra_list, algo_names)。"""
        extra_list = []
        all_an = set()
        total = len(raw_rows)
        batch = max(1, total // 20)
        for idx, row in enumerate(raw_rows):
            extra = self._load_extra_data(row["bvid"], row["timestamp"])
            extra_list.append(extra)
            for pred in extra.get("_predictions", []):
                all_an.add(pred.get("algorithm", ""))
            if total > 50 and (idx + 1) % batch == 0:
                p = idx + 1
                self.window.after(0, lambda pp=p, tt=total: self.status_var.set(f"加载关联数据 {pp}/{tt}…"))
        known = ["线性增长", "移动平均", "加权移动平均", "指数平滑", "趋势外推", "Gompertz"]
        anames = sorted(all_an, key=lambda n: (known.index(n) if n in known else len(known), n))
        return extra_list, anames

    def _reset_query_state(self):
        self._query_running = False
        self._query_btn.config(state="normal", text="查询")

    def _finish_query(self, raw_rows, extra_list, algo_names):
        self.query_results = raw_rows
        self._extra_data = extra_list
        self._algo_names = algo_names
        self.result_tree.delete(*self.result_tree.get_children())
        for i, row in enumerate(raw_rows, 1):
            lr = row.get("like_view_ratio") or 0
            vals = (
                i,
                row["bvid"],
                row["timestamp"],
                f"{row['view_count']:,}",
                f"{row['like_count']:,}",
                f"{row['coin_count']:,}",
                f"{row['share_count']:,}",
                f"{row['favorite_count']:,}",
                f"{row['danmaku_count']:,}",
                f"{row['reply_count']:,}",
                f"{(row.get('viewers_total') or 0):,}",
                f"{(row.get('viewers_web') or 0):,}",
                f"{(row.get('viewers_app') or 0):,}",
                f"{lr:.4f}",
            )
            self.result_tree.insert("", "end", values=vals, tags=(row["bvid"],))
        self.status_var.set(f"查询到 {len(raw_rows)} 条记录")
        self._reset_query_state()

    def _reset_query(self):
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self.status_var.set("就绪")

    def _get_export_default_name(self, ext: str) -> str:
        mode = self.query_mode.get()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fb = self._get_filter_bvid()
        tag = f"_{fb}" if fb else ""
        mn = {
            "最新N条": "latest",
            "播放首次大于X": f"above{self.param_var.get()}",
            "播放趋势": self.video_combo_var.get().split()[0] if self.video_combo_var.get() else "trend",
            "全量数据": "all",
        }.get(mode, "query")
        return f"{mn}{tag}_{ts}.{ext}"

    def _export_csv(self):
        if not self.query_results:
            messagebox.showwarning("提示", "没有可导出的数据", parent=self.window)
            return
        fp = filedialog.asksaveasfilename(
            title="导出CSV",
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=self._get_export_default_name("csv"),
            parent=self.window,
        )
        if not fp:
            return
        try:
            hd = _build_export_headers(self._algo_names)
            with open(fp, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(hd)
                el = getattr(self, "_extra_data", [])
                for i, row in enumerate(self.query_results, 1):
                    extra = el[i - 1] if i - 1 < len(el) else None
                    w.writerow(_build_export_row(i, row, extra, self._algo_names))
            messagebox.showinfo("成功", f"已导出到:\n{fp}", parent=self.window)
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}", parent=self.window)

    def _export_excel(self):
        if not self.query_results:
            messagebox.showwarning("提示", "没有可导出的数据", parent=self.window)
            return
        try:
            import openpyxl
        except ImportError:
            messagebox.showerror("错误", "需要安装 openpyxl 库\n请运行: pip install openpyxl", parent=self.window)
            return
        fp = filedialog.asksaveasfilename(
            title="导出Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
            initialfile=self._get_export_default_name("xlsx"),
            parent=self.window,
        )
        if not fp:
            return
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "查询结果"
            ws.append(_build_export_headers(self._algo_names))
            el = getattr(self, "_extra_data", [])
            for i, row in enumerate(self.query_results, 1):
                extra = el[i - 1] if i - 1 < len(el) else None
                ws.append(_build_export_row(i, row, extra, self._algo_names))
            for col in ws.columns:
                ml = max((len(str(c.value)) for c in col if c.value is not None), default=0)
                ws.column_dimensions[col[0].column_letter].width = min(ml + 2, 50)
            wb.save(fp)
            messagebox.showinfo("成功", f"已导出到:\n{fp}", parent=self.window)
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}", parent=self.window)

    def _delete_selected(self):
        sel = self.result_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的记录", parent=self.window)
            return
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(sel)} 条记录？", parent=self.window):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            for item in sel:
                vals = self.result_tree.item(item)["values"]
                bvid, ts = vals[1], vals[2]
                cur.execute("DELETE FROM monitor_records WHERE bvid = ? AND timestamp = ?", (bvid, ts))
                self.query_results = [r for r in self.query_results if not (r["bvid"] == bvid and r["timestamp"] == ts)]
            conn.commit()
            conn.close()
            self._do_query()
            self.status_var.set(f"已删除 {len(sel)} 条记录")
        except Exception as e:
            messagebox.showerror("错误", f"删除失败: {e}", parent=self.window)

    def _clear_results(self):
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self.status_var.set("已清空结果")
