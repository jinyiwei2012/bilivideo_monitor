"""
异常增长检测面板
基于 core/smart_alert.py 对全量监控视频执行异常检测并展示结果
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
        self.dlg = DialogBase(parent, "🚨 异常增长检测", "720x540")
        self.dlg.header("异常增长检测", "检测播放量突增/突降/停滞等异常行为")
        self._build_ui()
        self._scan()

    def _build_ui(self):
        top = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        top.pack(fill=tk.X, padx=10, pady=4)

        ttk.Button(top, text="🔄 重新扫描", command=self._scan).pack(side=tk.LEFT)
        self._status_lbl = tk.Label(top, text="", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM)
        self._status_lbl.pack(side=tk.LEFT, padx=10)

        # 结果列表
        self._tree = ttk.Treeview(
            self.dlg.content_area(),
            columns=("bvid", "title", "type", "detail"),
            show="headings",
            height=16,
        )
        self._tree.heading("bvid", text="BV号")
        self._tree.heading("title", text="标题")
        self._tree.heading("type", text="异常类型")
        self._tree.heading("detail", text="详情")
        self._tree.column("bvid", width=100)
        self._tree.column("title", width=200)
        self._tree.column("type", width=100)
        self._tree.column("detail", width=280)
        self._tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        scroll = ttk.Scrollbar(self._tree, command=self._tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.configure(yscrollcommand=scroll.set)

        TYPE_COLORS = {"📈 增速飙升": C["danger"], "📉 趋势反转": C["warning"],
                       "⏸ 播放停滞": C["text_3"], "👁 在线飙升": C["accent"], "📉 在线暴跌": C["danger"]}
        def _apply_tag_style():
            style = ttk.Style()
            for t, c in TYPE_COLORS.items():
                style.configure(f"type_{t}.TLabel", foreground=c)
        self.dlg.window.after(100, _apply_tag_style)

    def _scan(self):
        self._status_lbl.config(text="扫描中…")
        for row in self._tree.get_children():
            self._tree.delete(row)

        def worker():
            results = []
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                history = self.gui.history_data.get(bvid, [])
                if len(history) < 3:
                    continue
                records = []
                for ts, v in history[-20:]:
                    dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts)) if isinstance(ts, str) else datetime.fromtimestamp(float(ts))
                    records.append({
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
                try:
                    alerts = AnomalyDetector.detect_all(records, bvid=bvid)
                    for a in alerts:
                        type_icon = "📈 增速飙升" if "增速" in a else "📉 趋势反转" if "趋势" in a else "⏸ 播放停滞" if "停滞" in a else "👁 在线飙升" if "在线人数飙升" in a else "📉 在线暴跌"
                        results.append((bvid, video.get("title", bvid)[:25], type_icon, a[:50]))
                except Exception as e:
                    results.append((bvid, video.get("title", bvid)[:25], "⚠ 错误", str(e)[:40]))

            self.dlg.window.after(0, lambda: self._show_results(results))

        threading.Thread(target=worker, daemon=True).start()

    def _show_results(self, results):
        self._tree.delete(*self._tree.get_children())
        for bvid, title, typ, detail in results:
            self._tree.insert("", tk.END, values=(bvid, title, typ, detail))
        self._status_lbl.config(text=f"扫描完成，发现 {len(results)} 条异常" if results else "扫描完成，无异常 ✓", fg=C["danger"] if results else C["success"])
