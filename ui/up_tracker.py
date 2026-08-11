"""
UP主追踪面板 — PyQt6 版
查询UP主信息、追踪涨粉趋势、查看投稿列表
"""

from typing import Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QHeaderView, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.dialog_base import DialogBase


class UpTrackerWindow(DialogBase):
    """UP主追踪面板 — 查询UP主信息、追踪涨粉趋势、查看投稿列表"""

    def __init__(self, parent=None, api=None):
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
            parent, "UP主追踪",
            (int(sw * 0.50), int(sh * 0.68)),
            modal=False,
        )
        self.api = api

        from core.up_database import UpDatabase
        self.db = UpDatabase()

        self._search_results = []
        self._setup_ui()
        self._load_up_list()

    def _setup_ui(self):
        """构建界面：搜索区 + 列表 + 详情"""
        self.header("UP主追踪", "查询UP主信息、追踪涨粉与投稿趋势 — 天依帮你听他们的歌声 ♪")

        # 添加UP主卡片
        add_sec = self.section(title="添加UP主", padding=8)
        sec_layout = add_sec.layout()

        # 第一行：UID 输入
        uid_row = QWidget()
        uid_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        uid_layout = QHBoxLayout(uid_row)
        uid_layout.setContentsMargins(0, 0, 0, 4)

        lbl = QLabel("UID:")
        lbl.setFont(QFont("Microsoft YaHei UI", 10))
        lbl.setStyleSheet(f"color: {C['text_2']};")
        uid_layout.addWidget(lbl)

        self._uid_entry = QLineEdit()
        self._uid_entry.setText("8047632")
        self._uid_entry.setFont(QFont("Consolas", 10))
        self._uid_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        uid_layout.addWidget(self._uid_entry)

        add_btn = QPushButton("查询并添加")
        add_btn.setProperty("primary", True)
        style = add_btn.style()
        if style is not None:
            style.unpolish(add_btn)
            style.polish(add_btn)
        add_btn.clicked.connect(self._add_up)
        uid_layout.addWidget(add_btn)

        if sec_layout is not None:
            sec_layout.addWidget(uid_row)

        # 第二行：用户名搜索
        name_row = QWidget()
        name_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel("用户名:")
        name_lbl.setFont(QFont("Microsoft YaHei UI", 10))
        name_lbl.setStyleSheet(f"color: {C['text_2']};")
        name_layout.addWidget(name_lbl)

        self._name_entry = QLineEdit()
        self._name_entry.setFont(QFont("Microsoft YaHei UI", 10))
        self._name_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        self._name_entry.returnPressed.connect(self._search_by_name)
        name_layout.addWidget(self._name_entry)

        search_btn = QPushButton("搜索UP主")
        search_btn.setProperty("primary", True)
        style2 = search_btn.style()
        if style2 is not None:
            style2.unpolish(search_btn)
            style2.polish(search_btn)
        search_btn.clicked.connect(self._search_by_name)
        name_layout.addWidget(search_btn)

        if sec_layout is not None:
            sec_layout.addWidget(name_row)

        self._up_status = QLabel("")
        self._up_status.setFont(QFont("Microsoft YaHei UI", 9))
        self._up_status.setStyleSheet(f"color: {C['text_2']};")
        if sec_layout is not None:
            sec_layout.addWidget(self._up_status)

        # 搜索结果列表框
        self._search_list = QListWidget()
        self._search_list.setMaximumHeight(120)
        self._search_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['accent']};
                font-size: 9pt;
            }}
            QListWidget::item:selected {{
                background-color: {C['bilibili']}; color: white;
            }}
        """)
        self._search_list.itemDoubleClicked.connect(lambda: self._add_from_search())
        self._search_list.setVisible(False)
        if sec_layout is not None:
            sec_layout.addWidget(self._search_list)

        # UP主列表 + 详情（水平）
        mid = QWidget()
        mid.setStyleSheet(f"background-color: {C['bg_surface']};")
        mid_layout = QHBoxLayout(mid)
        mid_layout.setContentsMargins(24, 10, 24, 0)

        # 列表（左）
        list_frame = QWidget()
        list_frame.setStyleSheet(f"""
            QWidget {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: 6px;
            }}
        """)
        list_inner = QVBoxLayout(list_frame)
        list_inner.setContentsMargins(6, 4, 6, 6)

        list_header = QWidget()
        list_header.setStyleSheet(f"background-color: {C['bg_elevated']};")
        list_header_layout = QHBoxLayout(list_header)
        list_header_layout.setContentsMargins(6, 4, 6, 4)

        list_title = QLabel("已追踪UP主")
        list_title_font = QFont("Microsoft YaHei UI", 8)
        list_title_font.setBold(True)
        list_title.setFont(list_title_font)
        list_title.setStyleSheet(f"color: {C['text_2']};")
        list_header_layout.addWidget(list_title)

        list_header_layout.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_selected)
        list_header_layout.addWidget(refresh_btn)

        list_inner.addWidget(list_header)

        cols = ("UID", "名称", "粉丝", "投稿", "总播放")
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(cols)
        self._tree.setRootIsDecorated(False)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']};
                border: none; font-size: 9pt;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border_sub']};
                padding: 3px 6px;
                font-weight: bold;
            }}
        """)
        header = self._tree.header()
        if header is not None:
            widths = {"UID": 70, "名称": 100, "粉丝": 80, "投稿": 60, "总播放": 90}
            for i, c in enumerate(cols):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._tree.setColumnWidth(i, widths[c])

        self._tree.itemSelectionChanged.connect(self._on_up_select)
        list_inner.addWidget(self._tree)

        mid_layout.addWidget(list_frame, 1)

        # 详情（右）
        detail_frame = QWidget()
        detail_frame.setStyleSheet(f"""
            QWidget {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: 6px;
            }}
        """)
        detail_inner = QVBoxLayout(detail_frame)
        detail_inner.setContentsMargins(6, 4, 6, 6)

        detail_title = QLabel("UP主详情")
        detail_title_font = QFont("Microsoft YaHei UI", 8)
        detail_title_font.setBold(True)
        detail_title.setFont(detail_title_font)
        detail_title.setStyleSheet(f"color: {C['text_2']};")
        detail_inner.addWidget(detail_title)

        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                font-family: Consolas; font-size: 10pt;
                border: none; padding: 8px;
            }}
        """)
        detail_inner.addWidget(self._detail_text)

        mid_layout.addWidget(detail_frame, 1)

        self._main_layout.addWidget(mid)

    def _load_up_list(self):
        """加载已追踪的 UP 主列表到 Treeview"""
        self._tree.clear()
        ups = self.db.get_all_ups()
        for up in ups:
            item = QTreeWidgetItem()
            item.setText(0, str(up.get("uid", "")))
            item.setText(1, up.get("name", "")[:10])
            item.setText(2, self._fmt(up.get("follower_count", 0)))
            item.setText(3, str(up.get("video_count", 0)))
            item.setText(4, self._fmt(up.get("total_views", 0)))
            for c in range(5):
                item.setTextAlignment(c, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignLeft)
            self._tree.addTopLevelItem(item)

    def _on_up_select(self):
        """UP 主列表选中事件 — 显示选中 UP 主的详情"""
        sel = self._tree.selectedItems()
        if not sel:
            return
        uid = int(sel[0].text(0))
        up = self.db.get_up(uid)
        if not up:
            return
        self._show_detail(up)

    def _show_detail(self, up: Dict):
        """在详情区域显示 UP 主的完整信息（使用 HTML）"""
        uid = up.get("uid", 0)
        fc = up.get("follower_count", 0)
        vc = up.get("video_count", 0)
        tv = up.get("total_views", 0)
        tl = up.get("total_likes", 0)
        name = up.get("name", "未知")

        lines = []
        lines.append(f'<span style="color:{C["bilibili"]}; font-weight:bold;">=== {name} ===</span><br>')
        lines.append(f'UID: {uid}<br>')
        lines.append(f'等级: Lv.{up.get("level", 0)}<br>')
        lines.append(
            f'<span style="color:{C["accent"]}; font-weight:bold;">'
            f'粉丝: {self._fmt(fc):>8}    {fc:,}</span><br>'
        )
        lines.append(f'投稿: {vc:>8,}    总播放: {self._fmt(tv):>8}    {tv:,}<br>')
        lines.append(f'总点赞: {self._fmt(tl):>8}    {tl:,}<br>')
        lines.append(f'<span style="color:{C["text_3"]};">签名: {up.get("sign", "—")[:60]}</span><br>')
        lines.append(f'<span style="color:{C["text_3"]};">更新: {up.get("updated_at", "—")}</span><br>')
        lines.append("<br>")

        # 该 UP 主关联的已监控视频
        videos = self.db.get_up_videos(uid)
        if videos:
            lines.append(f'<span style="color:{C["bilibili"]}; font-weight:bold;">=== 已监控视频 ===</span><br>')
            for v in videos[:8]:
                lines.append(
                    f'  {v.get("bvid", "")}  {v.get("title", "")[:28]}  '
                    f'{self._fmt(v.get("view_count", 0))}<br>'
                )

        # 粉丝历史趋势
        history = self.db.get_history(uid, limit=10)
        if history:
            lines.append(
                f'<br><span style="color:{C["bilibili"]}; font-weight:bold;">=== 粉丝趋势(近10条) ===</span><br>'
            )
            for h in reversed(history):
                lines.append(
                    f'  <span style="color:{C["text_3"]};">{h.get("timestamp", "")[:16]}'
                    f'  粉丝 {self._fmt(h.get("follower_count", 0))}</span><br>'
                )

        self._detail_text.setHtml("".join(lines))

    def _refresh_selected(self):
        """刷新当前选中 UP 主的数据"""
        sel = self._tree.selectedItems()
        if not sel:
            QMessageBox.information(self, "提示", "请先在列表里选一个UP主哦,天依才好帮TA刷新 ♪")
            return
        uid = int(sel[0].text(0))

        if not self.api:
            self._up_status.setText("呜…API暂时够不着呢,天依等会儿再试试 ♪")
            self._up_status.setStyleSheet(f"color: {C['danger']};")
            return

        self._up_status.setText(f"正在刷新 UID:{uid} 数据…天依去看看TA的歌声 ♪")
        self._up_status.setStyleSheet(f"color: {C['text_2']};")

        info = self.api.get_up_info(uid)
        if not info:
            self._up_status.setText("呜…刷新失败了,检查一下网络哦,天依等会儿再试 ♪")
            self._up_status.setStyleSheet(f"color: {C['danger']};")
            return

        stat = self.api.get_up_stat(uid)
        if stat:
            info["total_views"] = stat.get("total_views", 0)
            info["total_likes"] = stat.get("total_likes", 0)

        self.db.upsert_up(info)
        self.db.add_history(
            uid=uid,
            follower_count=info.get("follower_count", 0),
            video_count=info.get("video_count", 0),
            total_views=info.get("total_views", 0),
        )

        self._load_up_list()
        self._show_detail(info)
        self._up_status.setText(
            f"刷新完成啦!♪ {info.get('name', '')}  粉丝: {self._fmt(info.get('follower_count', 0))}"
        )
        self._up_status.setStyleSheet(f"color: {C['success']};")

    def _search_by_name(self):
        """按用户名搜索UP主"""
        keyword = self._name_entry.text().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "输入一个用户名吧,天依帮你找找看 ♪")
            return
        if not self.api:
            self._up_status.setText("呜…API暂时够不着呢,天依等会儿再试试 ♪")
            self._up_status.setStyleSheet(f"color: {C['danger']};")
            return

        self._up_status.setText("天依正在找…像在银河里找一颗星 ♪")
        self._up_status.setStyleSheet(f"color: {C['text_2']};")

        results = self.api.search_up_users(keyword)
        self._search_list.clear()
        self._search_results = results or []

        if not results:
            self._up_status.setText("呜…没找到叫这个名字的UP主呢,换个名字再试试哦 ♪")
            self._up_status.setStyleSheet(f"color: {C['warning']};")
            self._search_list.setVisible(False)
            return

        for r in results:
            name = r.get("uname", "?")
            fans = self._fmt(r.get("fans", 0))
            videos = r.get("videos", 0)
            uid = r.get("mid", 0)
            self._search_list.addItem(f"[{uid}] {name}  粉丝:{fans}  投稿:{videos}")

        self._search_list.setVisible(True)
        self._up_status.setText(f"找到 {len(results)} 个UP主啦!♪ 双击就能添加到天依的歌单哦")
        self._up_status.setStyleSheet(f"color: {C['success']};")

    def _add_from_search(self):
        """从搜索结果添加UP主"""
        sel = self._search_list.currentRow()
        if sel < 0 or sel >= len(self._search_results):
            return
        r = self._search_results[sel]
        uid = r.get("mid", 0)
        self._uid_entry.setText(str(uid))
        self._add_up()

    def _add_up(self):
        """根据 UID 查询并添加 UP 主到追踪列表"""
        uid_str = self._uid_entry.text().strip()
        if not uid_str.isdigit():
            QMessageBox.warning(self, "提示", "UID要纯数字才行哦,再检查一下下 ♪")
            return
        uid = int(uid_str)

        existing = self.db.get_up(uid)
        if existing and existing.get("is_tracking"):
            self._up_status.setText(f"UP主 {existing['name']} 已经在天依的歌单里啦 ♪")
            self._up_status.setStyleSheet(f"color: {C['warning']};")
            return

        if not self.api:
            self._up_status.setText("呜…API暂时够不着呢,天依等会儿再试试 ♪")
            self._up_status.setStyleSheet(f"color: {C['danger']};")
            return

        self._up_status.setText("天依正在查询…像天使鱼在冰海里追光 ♪")
        self._up_status.setStyleSheet(f"color: {C['text_2']};")

        info = self.api.get_up_info(uid)
        if not info:
            self._up_status.setText("呜…没查到这位UP主呢,检查一下UID或网络哦 ♪")
            self._up_status.setStyleSheet(f"color: {C['danger']};")
            return

        stat = self.api.get_up_stat(uid)
        if stat:
            info["total_views"] = stat.get("total_views", 0)
            info["total_likes"] = stat.get("total_likes", 0)

        self.db.upsert_up(info)
        self.db.add_history(
            uid=uid,
            follower_count=info.get("follower_count", 0),
            video_count=info.get("video_count", 0),
            total_views=info.get("total_views", 0),
        )

        self._load_up_list()
        self._up_status.setText(
            f"添加成功啦!♪ {info.get('name', '')} 的歌声也进了天依的收藏 (UID: {uid})  粉丝: {self._fmt(info.get('follower_count', 0))}"
        )
        self._up_status.setStyleSheet(f"color: {C['success']};")

    @staticmethod
    def _fmt(n):
        """格式化大数字为中文单位（万/亿）"""
        if n >= 1_0000_0000:
            return f"{n / 1_0000_0000:.2f}亿"
        if n >= 1_0000:
            return f"{n / 1_0000:.1f}万"
        return str(n)
