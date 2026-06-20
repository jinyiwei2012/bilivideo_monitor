"""
异常增长检测面板
基于 core/smart_alert.py 对全量监控视频执行异常检测
展示时间/增量/在线人数等详细上下文信息
"""

import threading
import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QTextEdit,
)
from PyQt6.QtCore import Qt, QTimer

from ui.theme import C
from ui.helpers import FONT_SM, fmt_num
from ui.dialog_base import DialogBase
from ui.invoker import invoke
from core.smart_alert import AnomalyDetector

logger = logging.getLogger(__name__)


class AnomalyPanel:
    """异常增长检测面板：扫描所有监控视频，检测播放量突增/突降/停滞等异常行为"""

    def __init__(self, parent, gui):
        """
        初始化异常检测面板

        :param parent: 父窗口
        :param gui: 主 GUI 实例，用于获取视频数据和数据库
        """
        self.gui = gui
        self.dlg = DialogBase(parent, "🚨 异常增长检测", "960x580")
        self.dlg.header("异常增长检测", "检测播放量突增/突降/停滞等异常行为，附时间/增量/在线上下文")
        self._build_ui()
        self._scan()

    def _build_ui(self):
        """构建界面：扫描按钮、状态标签、结果表格、底部详情区"""
        top = QWidget()
        top.setStyleSheet(f"background-color: {C['bg_base']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)

        scan_btn = QPushButton("🔄 重新扫描")
        scan_btn.clicked.connect(self._scan)
        top_layout.addWidget(scan_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._status_lbl.setFont(FONT_SM)
        top_layout.addWidget(self._status_lbl)
        top_layout.addStretch()

        # 将 top 放入 content_area
        main_layout = QVBoxLayout(self.dlg.content_area())
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(top)

        # 结果列表 — 增加 时间/增量/在线 列
        headers = ["BV号", "标题", "异常类型", "发生时间", "播放量", "近2h增量", "增速/h", "在线人数"]
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(headers)
        self._tree.setColumnCount(8)
        self._tree.setMinimumHeight(20)
        self._tree.setAlternatingRowColors(False)
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.setColumnWidth(0, 90)
        self._tree.setColumnWidth(1, 160)
        self._tree.setColumnWidth(2, 90)
        self._tree.setColumnWidth(3, 110)
        self._tree.setColumnWidth(4, 80)
        self._tree.setColumnWidth(5, 80)
        self._tree.setColumnWidth(6, 70)
        self._tree.setColumnWidth(7, 70)
        # 右对齐数字列
        h = self._tree.headerItem()
        if h:
            for col in (4, 5, 6, 7):
                h.setTextAlignment(col, Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(self._tree, stretch=1)

        # 底部详情区：选中异常时显示详细上下文
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setMaximumHeight(120)
        self._detail_text.setStyleSheet(
            f"background-color: {C['bg_elevated']}; color: {C['text_2']}; "
            f"font-family: 'Microsoft YaHei UI'; font-size: 9pt; border: none;"
        )
        main_layout.addWidget(self._detail_text)

        self._tree.itemSelectionChanged.connect(self._show_detail)

        self._alert_data = []  # 存储完整告警信息供详情查看

    def _parse_dt(self, ts):
        """将多种格式的时间戳统一转换为 datetime 对象"""
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(str(ts)) if isinstance(ts, str) else datetime.fromtimestamp(float(ts))
        except Exception as e:
            import logging; logging.getLogger(__name__).debug("异常面板时间戳解析失败: %s", e)
            return datetime.now()

    def _scan(self):
        """开始扫描所有监控视频，后台线程执行异常检测"""

        # 清空旧数据
        self._status_lbl.setText("扫描中…")
        self._detail_text.clear()
        self._tree.clear()
        self._alert_data.clear()

        def worker():
            """后台工作线程：遍历每个视频，执行异常检测"""
            results = []
            for video in self.gui.monitored_videos:
                bvid = video.get("bvid", "")
                history = self.gui.history_data.get(bvid, [])
                if len(history) < 3:
                    continue

                # 构建完整 records（从DB获取含 viewers_total 的上下文）
                full_records = []
                try:
                    video_db = self.gui.video_dbs.get(bvid)
                    if video_db:
                        raw = video_db.get_all_records(limit=30)
                        for r in raw:
                            full_records.append(
                                {
                                    "timestamp": r["timestamp"],
                                    "view_count": r["view_count"],
                                    "like_count": r.get("like_count", 0),
                                    "coin_count": r.get("coin_count", 0),
                                    "favorite_count": r.get("favorite_count", 0),
                                    "share_count": r.get("share_count", 0),
                                    "danmaku_count": r.get("danmaku_count", 0),
                                    "reply_count": r.get("reply_count", 0),
                                    "viewers_total": r.get("viewers_total", 0),
                                }
                            )
                except Exception as e:
                    logger.debug("从DB获取记录失败 %s: %s", bvid, e)
                if len(full_records) < 3:
                    continue

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
                    # 获取 UP 主信息（用于买量检测）
                    up_info = None
                    owner_mid = video.get("owner_mid", 0) or video.get("mid", 0)
                    if owner_mid and hasattr(self.gui, "_cached_up_info"):
                        up_info = self.gui._cached_up_info.get(str(owner_mid))

                    # 调用异常检测器
                    alerts = AnomalyDetector.detect_all(full_records, bvid=bvid, video=video, up_info=up_info)
                    for a in alerts:
                        # 根据告警文本匹配异常类型图标
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
                        results.append(
                            {
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
                            }
                        )
                except Exception as e:
                    results.append(
                        {
                            "bvid": bvid,
                            "title": video.get("title", bvid)[:22],
                            "type": "⚠ 错误",
                            "time": "--",
                            "views": current_views,
                            "delta": 0,
                            "velocity": 0,
                            "online": online,
                            "alert_text": str(e)[:60],
                            "author": "",
                            "pubdate": 0,
                        }
                    )

            # 回主线程更新 UI
            invoke(lambda: self._show_results(results))

        threading.Thread(target=worker, daemon=True).start()

    def _show_results(self, results):
        """在表格中展示异常检测结果，高亮严重异常"""
        self._tree.clear()
        danger_types = ("📈 增速飙升", "📉 在线暴跌")

        self._alert_data = results
        for index, r in enumerate(results):
            values = (
                r["bvid"], r["title"], r["type"], r["time"],
                fmt_num(r["views"]),
                fmt_num(r["delta"]) if r["delta"] > 0 else "\u2014",
                f"{r['velocity']:.0f}" if r["velocity"] > 0 else "\u2014",
                fmt_num(r["online"]) if r["online"] > 0 else "\u2014",
            )
            item = QTreeWidgetItem(values)
            if r["type"] in danger_types:
                item.setForeground(0, Qt.GlobalColor.red)
            self._tree.addTopLevelItem(item)

        count = len(results)
        msg = f"扫描完成，发现 {count} 条异常" if count else "扫描完成，无异常 ✓"
        color = C["danger"] if count else C["success"]
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet(f"color: {color}; background: transparent;")

    def _show_detail(self):
        """点击表格行时显示异常详情"""
        items = self._tree.selectedItems()
        if not items or not self._alert_data:
            return
        idx = self._tree.indexOfTopLevelItem(items[0])
        if idx < 0 or idx >= len(self._alert_data):
            return
        r = self._alert_data[idx]
        detail = (
            f"📌 {r['type']}  |  BV: {r['bvid']}  |  UP: {r.get('author', '?')}\n"
            f"💬  {r['alert_text']}\n"
            f"📊 当前播放: {fmt_num(r['views'])}  |  近2h增量: {fmt_num(r['delta'])}  |  增速: {r['velocity']:.1f}/h  |  在线: {fmt_num(r['online'])}"
        )
        self._detail_text.setPlainText(detail)
