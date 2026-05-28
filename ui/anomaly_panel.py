"""
异常增长检测面板
基于 core/smart_alert.py 对全量监控视频执行异常检测
展示时间/增量/在线人数等详细上下文信息
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime
from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num
from ui.dialog_base import DialogBase
from core.smart_alert import AnomalyDetector


class AnomalyPanel:
    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "🚨 异常增长检测", "960x580")
        self.dlg.header("异常增长检测", "检测播放量突增/突降/停滞等异常行为，附时间/增量/在线上下文")
        self._build_ui()
        self._scan()

    def _build_ui(self):
        top = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        top.pack(fill=tk.X, padx=10, pady=4)

        ttk.Button(top, text="🔄 重新扫描", command=self._scan).pack(side=tk.LEFT)
        self._status_lbl = tk.Label(top, text="", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM)
        self._status_lbl.pack(side=tk.LEFT, padx=10)

        # 结果列表 — 增加 时间/增量/在线 列
        columns = ("bvid", "title", "type", "time", "views", "delta", "velocity", "online")
        self._tree = ttk.Treeview(
            self.dlg.content_area(), columns=columns, show="headings", height=20
        )
        self._tree.heading("bvid", text="BV号")
        self._tree.heading("title", text="标题")
        self._tree.heading("type", text="异常类型")
        self._tree.heading("time", text="发生时间")
        self._tree.heading("views", text="播放量")
        self._tree.heading("delta", text="近2h增量")
        self._tree.heading("velocity", text="增速/h")
        self._tree.heading("online", text="在线人数")
        self._tree.column("bvid", width=90)
        self._tree.column("title", width=160)
        self._tree.column("type", width=90)
        self._tree.column("time", width=110)
        self._tree.column("views", width=80, anchor="e")
        self._tree.column("delta", width=80, anchor="e")
        self._tree.column("velocity", width=70, anchor="e")
        self._tree.column("online", width=70, anchor="e")
        self._tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        scroll = ttk.Scrollbar(self._tree, command=self._tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.configure(yscrollcommand=scroll.set)

        # 底部详情区
        self._detail_text = tk.Text(
            self.dlg.content_area(), height=5, bg=C["bg_elevated"], fg=C["text_2"],
            font=("Microsoft YaHei UI", 9), relief=tk.FLAT, wrap=tk.WORD, state=tk.DISABLED
        )
        self._detail_text.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._tree.bind("<<TreeviewSelect>>", self._show_detail)

        self._alert_data = []  # store full alert info for detail view

    def _parse_dt(self, ts):
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(str(ts)) if isinstance(ts, str) else datetime.fromtimestamp(float(ts))
        except Exception:
            return datetime.now()

    def _scan(self):
        self._status_lbl.config(text="扫描中…")
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.config(state=tk.DISABLED)
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._alert_data.clear()

        def worker():
            results = []
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                history = self.gui.history_data.get(bvid, [])
                if len(history) < 3:
                    continue

                # 构建 records（含完整上下文）
                full_records = []
                for ts, v in history[-30:]:
                    dt = self._parse_dt(ts)
                    full_records.append({
                        "timestamp": dt.isoformat(),
                        "view_count": v,
                        "like_count": video.get("like_count", 0),
                        "coin_count": video.get("coin_count", 0),
                        "favorite_count": video.get("favorite_count", 0),
                        "share_count": video.get("share_count", 0),
                        "danmaku_count": video.get("danmaku_count", 0),
                        "reply_count": video.get("reply_count", 0),
                        "viewers_total": video.get("viewers_total", 0),
                    })

                # 计算最近 2h 增量和速率
                recent = history[-10:] if len(history) >= 10 else history
                if len(recent) >= 2:
                    t_first, v_first = recent[0]
                    t_last, v_last = recent[-1]
                    dt_first = self._parse_dt(t_first)
                    dt_last = self._parse_dt(t_last)
                    hours = max((dt_last - dt_first).total_seconds() / 3600, 0.01)
                    delta_views = max(0, v_last - v_first)
                    velocity = delta_views / hours
                else:
                    delta_views = 0
                    velocity = 0

                current_views = video.get("view_count", 0)
                online = video.get("viewers_total", 0)

                try:
                    alerts = AnomalyDetector.detect_all(full_records, bvid=bvid)
                    for a in alerts:
                        if "增速" in a:
                            type_icon = "📈 增速飙升"
                        elif "趋势" in a:
                            type_icon = "📉 趋势反转"
                        elif "停滞" in a:
                            type_icon = "⏸ 播放停滞"
                        elif "在线人数飙升" in a:
                            type_icon = "👁 在线飙升"
                        elif "暴跌" in a or "断崖" in a:
                            type_icon = "📉 在线暴跌"
                        else:
                            type_icon = "⚠ 其他"

                        time_str = dt_last.strftime("%m-%d %H:%M") if len(recent) >= 2 else "--"
                        results.append({
                            "bvid": bvid,
                            "title": video.get("title", bvid)[:22],
                            "type": type_icon,
                            "time": time_str,
                            "views": current_views,
                            "delta": delta_views,
                            "velocity": velocity,
                            "online": online,
                            "alert_text": a,
                            "author": video.get("author", ""),
                            "pubdate": video.get("pubdate", 0),
                        })
                except Exception as e:
                    results.append({
                        "bvid": bvid, "title": video.get("title", bvid)[:22], "type": "⚠ 错误",
                        "time": "--", "views": current_views, "delta": 0, "velocity": 0, "online": online,
                        "alert_text": str(e)[:60], "author": "", "pubdate": 0,
                    })

            self.dlg.window.after(0, lambda: self._show_results(results))

        threading.Thread(target=worker, daemon=True).start()

    def _show_results(self, results):
        self._tree.delete(*self._tree.get_children())
        self._alert_data = results
        for r in results:
            self._tree.insert("", tk.END, values=(
                r["bvid"], r["title"], r["type"], r["time"],
                fmt_num(r["views"]), fmt_num(r["delta"]) if r["delta"] > 0 else "—",
                f"{r['velocity']:.0f}" if r["velocity"] > 0 else "—",
                fmt_num(r["online"]) if r["online"] > 0 else "—",
            ))
            # 高亮严重异常
            if r["type"] in ("📈 增速飙升", "📉 在线暴跌"):
                for cid in self._tree.get_children():
                    if self._tree.item(cid, "values")[0] == r["bvid"]:
                        self._tree.tag_configure("danger", foreground=C["danger"])
                        self._tree.item(cid, tags=("danger",))

        count = len(results)
        self._status_lbl.config(
            text=f"扫描完成，发现 {count} 条异常" if count else "扫描完成，无异常 ✓",
            fg=C["danger"] if count else C["success"],
        )

    def _show_detail(self, event):
        sel = self._tree.selection()
        if not sel or not self._alert_data:
            return
        idx = self._tree.index(sel[0])
        if idx >= len(self._alert_data):
            return
        r = self._alert_data[idx]
        detail = (
            f"📌 {r['type']}  |  BV: {r['bvid']}  |  UP: {r.get('author', '?')}\n"
            f"💬  {r['alert_text']}\n"
            f"📊 当前播放: {fmt_num(r['views'])}  |  近2h增量: {fmt_num(r['delta'])}  |  增速: {r['velocity']:.1f}/h  |  在线: {fmt_num(r['online'])}"
        )
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert(tk.END, detail)
        self._detail_text.config(state=tk.DISABLED)
