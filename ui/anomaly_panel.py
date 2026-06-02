"""
异常增长检测面板模块

本模块基于 core/smart_alert.py 的 AnomalyDetector 对全量监控视频执行异常检测。
可检测以下异常类型：
- 疑似买量（播放量异常暴增）
- 正在直播（直播导致的播放量飙升）
- 增速飙升 / 趋势反转 / 播放停滞
- 深夜异常播放 / 在线人数飙升 / 在线暴跌

检测结果以表格形式展示，包含时间、增量、在线人数等详细上下文信息。
选中某条异常后可查看更详细的描述文本。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import logging
from datetime import datetime
from ui.theme import C                                     # 颜色主题常量
from ui.helpers import FONT, FONT_SM, FONT_MONO, fmt_num   # UI 辅助工具
from ui.dialog_base import DialogBase                      # 现代化对话框基类
from core.smart_alert import AnomalyDetector                # 异常检测引擎

logger = logging.getLogger(__name__)


class AnomalyPanel:
    """
    异常增长检测面板

    功能：
    1. 扫描所有监控视频，检测播放量突增/突降/停滞等异常行为
    2. 以表格形式展示异常列表（BV号、标题、异常类型、时间、增量、增速、在线人数）
    3. 选中异常行时显示详细的异常描述文本
    4. 支持重新扫描按钮

    异常检测通过 AnomalyDetector.detect_all() 调用，该函数内部检查：
    - 播放量变化趋势
    - 在线人数波动
    - 深夜时段异常
    - 直播状态检测
    - 买量嫌疑判断
    """

    def __init__(self, parent, gui):
        """
        初始化异常检测面板

        :param parent: 父窗口（Tkinter Toplevel 的父级）
        :param gui: 主 GUI 实例，用于获取视频列表、历史数据和数据库连接
        """
        self.gui = gui
        self.dlg = DialogBase(parent, "🚨 异常增长检测", "960x580")
        self.dlg.header("异常增长检测", "检测播放量突增/突降/停滞等异常行为，附时间/增量/在线上下文")
        self._build_ui()
        self._scan()                                        # 打开时自动扫描

    def _build_ui(self):
        """
        构建界面：
        - 顶部操作栏：重新扫描按钮 + 扫描状态标签
        - 中间结果表格：BV号、标题、异常类型、时间、播放量、近2h增量、增速、在线人数
        - 底部详情文本区：选中异常时显示详细描述
        """
        # ── 顶部操作栏 ──
        top = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        top.pack(fill=tk.X, padx=10, pady=4)

        ttk.Button(top, text="🔄 重新扫描", command=self._scan).pack(side=tk.LEFT)
        self._status_lbl = tk.Label(top, text="", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM)
        self._status_lbl.pack(side=tk.LEFT, padx=10)

        # ── 结果列表表格 ──
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

        # ── 底部详情展示区 ──
        self._detail_text = tk.Text(
            self.dlg.content_area(), height=5, bg=C["bg_elevated"], fg=C["text_2"],
            font=("Microsoft YaHei UI", 9), relief=tk.FLAT, wrap=tk.WORD, state=tk.DISABLED
        )
        self._detail_text.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._tree.bind("<<TreeviewSelect>>", self._show_detail)   # 选中行显示详情

        self._alert_data = []                                # 存储完整告警信息供详情查看

    def _parse_dt(self, ts):
        """
        将多种格式的时间戳统一转换为 datetime 对象

        :param ts: 时间戳，可为 datetime 对象、ISO 格式字符串或数值型时间戳
        :return: datetime 对象，解析失败返回当前时间
        """
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(str(ts)) if isinstance(ts, str) else datetime.fromtimestamp(float(ts))
        except Exception:
            return datetime.now()

    def _scan(self):
        """开始扫描所有监控视频，后台线程执行异常检测（以免阻塞 UI）"""
        # 清空旧数据
        self._status_lbl.config(text="扫描中…")
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.config(state=tk.DISABLED)
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._alert_data.clear()

        def worker():
            """
            后台工作线程：
            1. 遍历所有监控视频
            2. 从数据库获取最近 30 条记录
            3. 计算近 2h 增量和速率
            4. 调用 AnomalyDetector.detect_all() 检测异常
            5. 将结果回主线程更新 UI
            """
            results = []
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                history = self.gui.history_data.get(bvid, [])
                if len(history) < 3:
                    continue                                # 数据太少，跳过检测

                # 构建完整 records（从 DB 获取含 viewers_total 的上下文）
                full_records = []
                try:
                    video_db = self.gui.video_dbs.get(bvid)
                    if video_db:
                        raw = video_db.get_all_records(limit=30)   # 最多取 30 条
                        for r in raw:
                            full_records.append({
                                "timestamp": r["timestamp"],
                                "view_count": r["view_count"],
                                "like_count": r.get("like_count", 0),
                                "coin_count": r.get("coin_count", 0),
                                "favorite_count": r.get("favorite_count", 0),
                                "share_count": r.get("share_count", 0),
                                "danmaku_count": r.get("danmaku_count", 0),
                                "reply_count": r.get("reply_count", 0),
                                "viewers_total": r.get("viewers_total", 0),
                            })
                except Exception as e:
                    logger.debug("从DB获取记录失败 %s: %s", bvid, e)
                if len(full_records) < 3:
                    continue

                # 计算最近 2h 增量和增速（基于最近 10 条历史记录）
                recent = history[-10:] if len(history) >= 10 else history
                if len(recent) >= 2:
                    t_first, v_first = recent[0]
                    t_last, v_last = recent[-1]
                    dt_first = self._parse_dt(t_first)
                    dt_last = self._parse_dt(t_last)
                    hours = max((dt_last - dt_first).total_seconds() / 3600, 0.01)   # 最小 0.01h 防除零
                    delta_views = max(0, v_last - v_first)          # 增量（负数视为 0）
                    velocity = delta_views / hours                   # 每小时增速
                else:
                    delta_views = 0
                    velocity = 0

                current_views = video.get("view_count", 0)
                online = video.get("viewers_total", 0)               # 当前在线人数

                try:
                    # 获取 UP 主信息（用于买量检测）
                    up_info = None
                    owner_mid = video.get("owner_mid", 0) or video.get("mid", 0)
                    if owner_mid and hasattr(self.gui, '_cached_up_info'):
                        up_info = self.gui._cached_up_info.get(str(owner_mid))

                    # 调用异常检测器进行全维度检测
                    alerts = AnomalyDetector.detect_all(full_records, bvid=bvid, video=video, up_info=up_info)
                    for a in alerts:
                        # 根据告警文本内容匹配异常类型图标
                        if "买量" in a or "疑似买量" in a:
                            type_icon = "📢 疑似买量"
                        elif "直播" in a:
                            type_icon = "🔴 正在直播"
                        elif "增速" in a:
                            type_icon = "📈 增速飙升"
                        elif "趋势" in a or "放缓" in a:
                            type_icon = "📉 趋势反转"
                        elif "停滞" in a:
                            type_icon = "⏸ 播放停滞"
                        elif "深夜" in a:
                            type_icon = "🌙 深夜异常"
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
                            "alert_text": a,                     # 完整告警描述文本
                            "author": video.get("author", ""),
                            "pubdate": video.get("pubdate", 0),
                        })
                except Exception as e:
                    # 检测出错时记录错误信息
                    results.append({
                        "bvid": bvid, "title": video.get("title", bvid)[:22], "type": "⚠ 错误",
                        "time": "--", "views": current_views, "delta": 0, "velocity": 0, "online": online,
                        "alert_text": str(e)[:60], "author": "", "pubdate": 0,
                    })

            # 回主线程更新 UI
            self.dlg.window.after(0, lambda: self._show_results(results))

        threading.Thread(target=worker, daemon=True).start()    # daemon 线程随窗口关闭自动终止

    def _show_results(self, results):
        """
        在表格中展示异常检测结果，严重异常行标记为红色

        :param results: 异常检测结果列表
        """
        self._tree.delete(*self._tree.get_children())
        self._alert_data = results
        for r in results:
            self._tree.insert("", tk.END, values=(
                r["bvid"], r["title"], r["type"], r["time"],
                fmt_num(r["views"]), fmt_num(r["delta"]) if r["delta"] > 0 else "—",
                f"{r['velocity']:.0f}" if r["velocity"] > 0 else "—",
                fmt_num(r["online"]) if r["online"] > 0 else "—",
            ))
            # 高亮严重异常（增速飙升、在线暴跌）为红色
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
        """
        点击表格行时在底部详情区显示完整的异常描述信息

        :param event: Treeview 选择事件
        """
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
