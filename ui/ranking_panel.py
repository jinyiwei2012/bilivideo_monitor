"""
视频排行榜面板
按增速/互动率/播放量/在线人数等维度对所有监控视频排序
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt

from ui.theme import C
from ui.helpers import FONT, FONT_SM, fmt_num
from ui.dialog_base import DialogBase


class RankingPanel:
    SORT_OPTIONS = [
        ("↗ 增速 (每小时)", "velocity"),
        ("◉ 播放量", "views"),
        ("✓ 点赞率", "like_rate"),
        ("◎ 投币率", "coin_rate"),
        ("◧ 互动率", "engagement"),
        ("☻ 在线人数", "online"),
        ("▦ 发布天数", "age"),
    ]

    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "♛ 视频排行榜", "800x540")
        self.dlg.header("视频排行榜", "天依帮你给每首歌排排座次哦 ♪")
        self._build_ui()

    def _build_ui(self):
        """构建排行榜面板 UI：排序维度选择、树形结果表格"""
        top = QWidget()
        top.setStyleSheet(f"background-color: {C['bg_base']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(10, 4, 10, 4)

        lbl = QLabel("排序维度:")
        lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        lbl.setFont(FONT)
        top_layout.addWidget(lbl)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems([s[0] for s in self.SORT_OPTIONS])
        self._sort_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        self._sort_combo.currentIndexChanged.connect(lambda: self._refresh())
        top_layout.addWidget(self._sort_combo)

        top_layout.addStretch()

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._status_lbl.setFont(FONT_SM)
        top_layout.addWidget(self._status_lbl)

        # 内容区: QTreeWidget
        content = QWidget()
        content.setStyleSheet(f"background-color: {C['bg_base']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 0, 10, 4)

        columns = ["#", "BV号", "标题", "UP主", "播放量", "增速/h", "互动率", "在线"]
        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(columns))
        self._tree.setHeaderLabels(columns)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']};
                alternate-background-color: {C['bg_surface']};
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']}; color: {C['text_2']};
                font-weight: bold; padding: 4px;
                border: 1px solid {C['border']};
            }}
        """)
        hdr = self._tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(0, 30)
        self._tree.setColumnWidth(1, 100)
        self._tree.setColumnWidth(2, 220)
        self._tree.setColumnWidth(3, 100)
        self._tree.setColumnWidth(4, 90)
        self._tree.setColumnWidth(5, 80)
        self._tree.setColumnWidth(6, 70)
        self._tree.setColumnWidth(7, 70)
        content_layout.addWidget(self._tree)

        # 将 top 和 content 放入 dlg 的 content_area
        area = self.dlg.content_area()
        outer = QVBoxLayout(area)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(top)
        outer.addWidget(content, 1)

        self._refresh()

    def _compute_velocity(self, bvid):
        """根据最近两条历史记录计算该视频的播放增速（次/小时）"""
        history = self.gui.history_data.get(bvid, [])
        if len(history) < 2:
            return 0
        t1, v1 = history[-2]
        t0, v0 = history[-1]
        t1 = (
            t1
            if isinstance(t1, datetime)
            else datetime.fromisoformat(str(t1)) if isinstance(t1, str) else datetime.fromtimestamp(float(t1))
        )
        t0 = (
            t0
            if isinstance(t0, datetime)
            else datetime.fromisoformat(str(t0)) if isinstance(t0, str) else datetime.fromtimestamp(float(t0))
        )
        dt = (t0 - t1).total_seconds() / 3600
        if dt <= 0 or v0 < v1:
            return 0
        return (v0 - v1) / dt

    def _refresh(self):
        """根据当前排序维度重新计算并刷新排行榜"""
        sort_idx = self._sort_combo.currentIndex()
        if sort_idx < 0:
            return
        sort_key = self.SORT_OPTIONS[sort_idx][1]

        items = []
        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            views = v.get("view_count", 0)
            likes = v.get("like_count", 0)
            coins = v.get("coin_count", 0)
            online = v.get("viewers_total", 0)
            velocity = self._compute_velocity(bvid)
            like_rate = likes / max(views, 1)
            coin_rate = coins / max(views, 1)
            engagement = (likes + coins + v.get("favorite_count", 0) + v.get("share_count", 0)) / max(views, 1)
            pubdate = v.get("pubdate", 0)
            age = (datetime.now().timestamp() - pubdate) / 86400 if pubdate > 0 else 0

            if sort_key == "velocity":
                sort_val = velocity
            elif sort_key == "views":
                sort_val = views
            elif sort_key == "like_rate":
                sort_val = like_rate
            elif sort_key == "coin_rate":
                sort_val = coin_rate
            elif sort_key == "engagement":
                sort_val = engagement
            elif sort_key == "online":
                sort_val = online
            elif sort_key == "age":
                sort_val = age
            else:
                sort_val = 0

            items.append(
                (sort_val, bvid, v.get("title", bvid)[:30], v.get("author", ""), views, velocity, engagement, online)
            )

        items.sort(key=lambda x: -abs(x[0]))

        self._tree.clear()
        for i, (_, bvid, title, author, views, velocity, engagement, online) in enumerate(items, 1):
            vel_str = fmt_num(int(velocity)) if velocity > 0 else "—"
            eng_str = f"{engagement * 100:.1f}%" if engagement > 0 else "—"
            online_str = fmt_num(online) if online > 0 else "—"
            vals = (str(i), bvid, title, author, fmt_num(views), vel_str, eng_str, online_str)
            item = QTreeWidgetItem(vals)
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(5, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(6, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(7, Qt.AlignmentFlag.AlignRight)
            self._tree.addTopLevelItem(item)

        self._status_lbl.setText(f"共 {len(items)} 个视频，排名唱完啦 ♪")
