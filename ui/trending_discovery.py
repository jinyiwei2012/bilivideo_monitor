"""
热门视频发现窗口 — PyQt6 版
热门榜、每周必看、入站必刷 — 浏览榜单，一键添加监控
"""

import threading
from typing import Dict, List, Optional, Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.scrollable_frame import ScrollableFrame
from ui.dialog_base import DialogBase


class TrendingDiscoveryWindow(DialogBase):
    """热门视频发现窗口 — 浏览热门榜、每周必看，一键添加监控"""

    _videos_loaded = pyqtSignal(object)  # List[Dict]

    def __init__(self, parent=None, api=None, on_add_monitor: Optional[Callable] = None):
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        super().__init__(
            parent, "热门视频发现",
            (int(sw * 0.48), int(sh * 0.68)),
            modal=False,
        )
        self.api = api
        self.on_add_monitor = on_add_monitor
        self._videos: List[Dict] = []
        self._videos_loaded.connect(self._display_videos)

        # 内部引用，避免被 gc
        self._thread_refs: List[threading.Thread] = []

        self._setup_ui()

    def _setup_ui(self):
        """构建窗口界面：QTabWidget 标签页 + 视频卡片列表"""
        self.header("热门视频发现", "浏览B站热门榜单,发现藏着好歌声的视频 ♪")

        # QTabWidget：默认自带标签页样式的切换
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-top: none;
            }}
            QTabBar::tab {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                padding: 8px 20px;
                font-size: 10pt;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {C['bilibili']};
                border-bottom: 2px solid {C['bilibili']};
            }}
            QTabBar::tab:hover {{
                color: {C['bilibili']};
            }}
        """)
        self._main_layout.addWidget(self._tabs)

        # 热门榜标签页
        popular_tab = QWidget()
        popular_tab.setStyleSheet(f"background-color: {C['bg_elevated']};")
        pop_layout = QVBoxLayout(popular_tab)
        pop_layout.setContentsMargins(16, 10, 16, 16)

        self._sf_popular = ScrollableFrame(bg=C["bg_elevated"], height=None)
        pop_layout.addWidget(self._sf_popular)

        self._tabs.addTab(popular_tab, "♨ 热门榜")

        # 每周必看标签页
        weekly_tab = QWidget()
        weekly_tab.setStyleSheet(f"background-color: {C['bg_elevated']};")
        wk_layout = QVBoxLayout(weekly_tab)
        wk_layout.setContentsMargins(16, 10, 16, 16)

        self._sf_weekly = ScrollableFrame(bg=C["bg_elevated"], height=None)
        wk_layout.addWidget(self._sf_weekly)

        self._tabs.addTab(weekly_tab, "▦ 每周必看")

        # 切换标签页时加载数据
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # 默认加载热门榜
        self._load_popular()

    def _on_tab_changed(self, index: int):
        """标签页切换事件"""
        if index == 0:
            self._load_popular()
        elif index == 1:
            self._load_weekly()

    def _load_popular(self):
        """异步加载热门榜数据"""
        if not self.api:
            return
        self._clear_cards(self._sf_popular)
        self._add_loading_label(self._sf_popular)

        t = threading.Thread(target=self._fetch_popular, daemon=True)
        self._thread_refs.append(t)
        t.start()

    def _fetch_popular(self):
        """后台线程：获取热门视频"""
        videos = self.api.get_popular_videos() if self.api else []
        self._videos_loaded.emit(videos)

    def _load_weekly(self):
        """异步加载每周必看数据"""
        if not self.api:
            return
        self._clear_cards(self._sf_weekly)
        self._add_loading_label(self._sf_weekly)

        t = threading.Thread(target=self._fetch_weekly, daemon=True)
        self._thread_refs.append(t)
        t.start()

    def _fetch_weekly(self):
        """后台线程：获取每周必看"""
        videos = self.api.get_weekly_series() if self.api else []
        self._videos_loaded.emit(videos)

    def _add_loading_label(self, sf: ScrollableFrame):
        """在 ScrollableFrame 中添加加载中提示"""
        lbl = QLabel("天依正在找…像在银河里找一颗星 ♪")
        lbl.setFont(QFont("Microsoft YaHei UI", 10))
        lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent; padding: 40px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sf.addWidget(lbl)
        self._loading_ref = lbl

    @staticmethod
    def _clear_cards(sf: ScrollableFrame):
        """清空 ScrollableFrame 中的卡片"""
        sf.clear()

    def _display_videos(self, videos: List[Dict]):
        """显示视频卡片列表（主线程回调）"""
        # 判断当前活跃的是哪个 ScrollableFrame
        current_idx = self._tabs.currentIndex()
        if current_idx == 0:
            sf = self._sf_popular
        else:
            sf = self._sf_weekly

        self._clear_cards(sf)

        if not videos:
            self._show_empty(sf)
            return

        for v in videos:
            stat = v.get("stat", v)
            owner_info = v.get("owner", {})
            bvid = v.get("bvid", "")
            title = v.get("title", "未知")[:40]
            author = owner_info.get("name", v.get("author", "未知"))
            views = stat.get("view", 0)
            likes = stat.get("like", 0)
            danmaku = stat.get("danmaku", 0)

            card = QWidget()
            card.setStyleSheet(f"""
                QWidget#trending_card {{
                    background-color: {C['bg_surface']};
                    border: 1px solid {C['border_sub']};
                    border-radius: 4px;
                }}
            """)
            card.setObjectName("trending_card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 6, 12, 6)
            card_layout.setSpacing(4)

            # 第一行：标题 + 按钮
            top_row = QWidget()
            top_row.setStyleSheet(f"background-color: {C['bg_surface']};")
            top_layout = QHBoxLayout(top_row)
            top_layout.setContentsMargins(0, 0, 0, 0)

            title_lbl = QLabel(title)
            title_lbl.setFont(QFont("Microsoft YaHei UI", 10))
            title_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
            title_lbl.setWordWrap(True)
            top_layout.addWidget(title_lbl, 1)

            if bvid:
                add_btn = QPushButton("+ 监控")
                add_btn.setFixedWidth(70)
                add_btn.clicked.connect(lambda checked, b=bvid: self._add_monitor(b))
                top_layout.addWidget(add_btn)

            card_layout.addWidget(top_row)

            # 第二行：元数据
            meta_row = QWidget()
            meta_row.setStyleSheet(f"background-color: {C['bg_surface']};")
            meta_layout = QHBoxLayout(meta_row)
            meta_layout.setContentsMargins(0, 0, 0, 0)

            meta_info = [
                (f"☺ {author}", C["text_2"]),
                (f"▶ {self._fmt(views)}", C["text_2"]),
                (f"✓ {self._fmt(likes)}", C["text_2"]),
                (f"♬ {self._fmt(danmaku)}", C["text_2"]),
            ]
            for text, color in meta_info:
                lbl = QLabel(text)
                lbl.setFont(QFont("Microsoft YaHei UI", 9))
                lbl.setStyleSheet(f"color: {color}; background: transparent;")
                meta_layout.addWidget(lbl)
                meta_layout.addSpacing(12)

            meta_layout.addStretch()
            card_layout.addWidget(meta_row)

            sf.addWidget(card)

    def _show_empty(self, sf: ScrollableFrame):
        """显示空状态提示"""
        msg = QWidget()
        msg.setStyleSheet(f"background-color: {C['bg_elevated']};")
        msg_layout = QVBoxLayout(msg)
        msg_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl1 = QLabel("还没有数据呢…像等待一首歌的旋律,天依陪你一起等 ♪")
        lbl1.setFont(QFont("Microsoft YaHei UI", 12))
        lbl1.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        lbl1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_layout.addWidget(lbl1)

        lbl2 = QLabel("提示：配置好Cookie后,天依才能更顺畅地听到榜单的歌声哦")
        lbl2.setFont(QFont("Microsoft YaHei UI", 9))
        lbl2.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_layout.addWidget(lbl2)

        lbl3 = QLabel("请前往「设置 → 网络设置 → Cookie设置」配置SESSDATA ♪")
        lbl3.setFont(QFont("Microsoft YaHei UI", 9))
        lbl3.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        lbl3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_layout.addWidget(lbl3)

        sf.addWidget(msg)

    def _add_monitor(self, bvid: str):
        """将视频添加到监控列表"""
        if self.on_add_monitor:
            self.on_add_monitor(bvid)
            QMessageBox.information(self, "提示", f"「{bvid}」加入监控啦!♪ 又有一首新歌要开始追光了呢~")

    @staticmethod
    def _fmt(n):
        """格式化大数字为中文单位（万/亿）"""
        if n >= 1_0000_0000:
            return f"{n / 1_0000_0000:.2f}亿"
        if n >= 1_0000:
            return f"{n / 1_0000:.1f}万"
        return str(n)
