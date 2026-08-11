"""
现代化视频搜索界面 — PyQt6 版
支持B站关键词搜索、批量导入到监控列表
"""

import logging
import io
import threading
import webbrowser
from typing import List, Dict, Callable, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QDialog, QMessageBox, QApplication, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QAction

from core import get_bilibili_api
from ui.theme import C
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)


class VideoSearchWindow(DialogBase):
    """视频搜索窗口（现代化风格），支持搜索 B 站视频并批量导入到监控列表"""

    _search_done = pyqtSignal(object, object)  # (results: list, error: str | None)

    def __init__(self, parent=None, on_import: Optional[Callable[[list], None]] = None):
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        super().__init__(parent, "搜索视频 - B站 ♪", (int(sw * 0.48), int(sh * 0.68)), modal=True)
        self.on_import = on_import
        self.search_results: List[Dict] = []
        self.searching = False
        self._threads: List[threading.Thread] = []
        self._search_done.connect(self._on_search_done)

        self._setup_ui()

    def _setup_ui(self):
        """构建搜索界面布局"""
        self.header("搜索视频 ♪", "输入关键词，天依帮你找找好听的歌哦 ♪")

        # ── 搜索栏卡片 ──
        sec = self.section(padding=10)
        sec_layout = sec.layout()

        search_row = QWidget()
        search_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(4, 0, 4, 0)

        # 关键词输入框
        kw_lbl = QLabel("关键词")
        kw_lbl.setFont(QFont("Microsoft YaHei UI", 10))
        kw_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        search_layout.addWidget(kw_lbl)
        search_layout.addSpacing(8)

        self.kw_entry = QLineEdit()
        self.kw_entry.setFont(QFont("Microsoft YaHei UI", 10))
        self.kw_entry.setMinimumWidth(300)
        self.kw_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px 8px;
            }}
        """)
        self.kw_entry.returnPressed.connect(self._start_search)
        search_layout.addWidget(self.kw_entry)
        search_layout.addSpacing(8)

        # 搜索按钮
        search_btn = QPushButton("搜索 ♪")
        search_btn.setProperty("primary", True)
        style = search_btn.style()
        if style is not None:
            style.unpolish(search_btn)
            style.polish(search_btn)
        search_btn.clicked.connect(self._start_search)
        search_layout.addWidget(search_btn)

        search_layout.addStretch()

        # 状态标签
        self.status_lbl = QLabel("天依准备好啦 ♪")
        self.status_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        self.status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        search_layout.addWidget(self.status_lbl)

        if sec_layout is not None:
            sec_layout.addWidget(search_row)

        # ── 结果表格 ──
        cols = ["BV号", "标题", "UP主", "播放量", "点赞"]
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(cols)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(False)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border_sub']};
                font-size: 9pt;
                outline: none;
            }}
            QTreeWidget::item:selected {{
                background-color: {C['bilibili']};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border_sub']};
                padding: 4px 8px;
                font-weight: bold;
            }}
        """)
        header = self.tree.header()
        if header is not None:
            widths = {"BV号": 120, "标题": 320, "UP主": 120, "播放量": 90, "点赞": 80}
            for i, c in enumerate(cols):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self.tree.setColumnWidth(i, widths[c])

        # 双击 / 右键菜单
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_right_click)

        self._main_layout.addWidget(self.tree, 1)

        # ── 底部按钮栏 ──
        bottom = QWidget()
        bottom.setStyleSheet(f"background-color: {C['bg_surface']};")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 12, 0, 0)

        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self._select_all)
        bottom_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("取消全选")
        select_none_btn.clicked.connect(self._select_none)
        bottom_layout.addWidget(select_none_btn)

        bottom_layout.addStretch()

        import_btn = QPushButton("导入所选到监控 ♪")
        import_btn.setProperty("primary", True)
        style2 = import_btn.style()
        if style2 is not None:
            style2.unpolish(import_btn)
            style2.polish(import_btn)
        import_btn.clicked.connect(self._do_import)
        bottom_layout.addWidget(import_btn)

        self._main_layout.addWidget(bottom)

    def _start_search(self):
        """开始搜索：校验输入、清空旧结果、启动后台搜索线程"""
        kw = self.kw_entry.text().strip()
        if not kw:
            QMessageBox.warning(self, "要注意哦…", "要先输入关键词哦，天依才知道要为你找哪首歌呢…♪")
            return
        if self.searching:
            return

        # 清空旧数据
        self.tree.clear()
        self.search_results.clear()
        self.searching = True
        self.status_lbl.setText("天依正在翻找B站的歌海…稍等一下下哦 ♪")
        self.status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")

        t = threading.Thread(target=self._worker, args=(kw,), daemon=True)
        self._threads.append(t)
        t.start()

    def _worker(self, kw: str):
        """后台线程：调用 B 站 API 搜索，通过信号回写 UI"""
        try:
            results = get_bilibili_api().search_videos(kw, page=1, page_size=20)
            self._search_done.emit(results or [], None)
        except Exception as e:
            logger.error("B站视频搜索失败", exc_info=True)
            self._search_done.emit([], "搜索没有回音呢，像对着山谷唱歌，请稍后再试哦 ♪")

    def _on_search_done(self, results: List[Dict], error: Optional[str]):
        """主线程回调：处理搜索结果"""
        self.searching = False

        if error:
            self.status_lbl.setText(f"呜…{error}")
            self.status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            return

        if not results:
            self.status_lbl.setText("没有找到呢…像一首还没人听过的新歌，换个关键词试试?♪")
            self.status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
            return

        for v in results:
            bvid = v.get("bvid", "")
            if not bvid:
                continue
            self.search_results.append(v)
            title = v.get("title", "").replace('<em class="keyword">', "").replace("</em>", "")
            author = v.get("author", "未知")
            play = f"{v.get('play', 0):,}" if v.get("play") else "0"
            like = f"{v.get('like', 0):,}" if v.get("like") else "0"

            item = QTreeWidgetItem()
            item.setText(0, bvid)
            item.setText(1, title[:60])
            item.setText(2, author)
            item.setText(3, play)
            item.setText(4, like)
            # 居中对齐数字列
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)

        self.status_lbl.setText(f"找到 {len(results)} 个结果啦，像发现了一串好听的旋律 ♪")
        self.status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")

    def _select_all(self):
        """全选所有搜索结果的复选框"""
        self.tree.selectAll()

    def _select_none(self):
        """取消全选"""
        self.tree.clearSelection()

    def _do_import(self):
        """将选中的视频导入到监控列表"""
        sel = self.tree.selectedItems()
        if not sel:
            QMessageBox.warning(self, "要注意哦…", "要先选中要导入的视频哦，天依才好把它们都放进歌单呢…♪")
            return
        bvids = {item.text(0) for item in sel}
        videos = [v for v in self.search_results if v.get("bvid") in bvids]
        if not videos:
            return
        self.close()
        if self.on_import:
            self.on_import(videos)

    def _on_tree_double_click(self, item: QTreeWidgetItem, column: int):
        """双击单条结果快速导入"""
        bvid = item.text(0)
        video = next((v for v in self.search_results if v.get("bvid") == bvid), None)
        if not video:
            return
        self.close()
        if self.on_import:
            self.on_import([video])

    def _on_tree_right_click(self, pos):
        """右键菜单：查看详情 / 复制BV号 / 浏览器打开 / 导入"""
        item = self.tree.itemAt(pos)
        if not item:
            return
        bvid = item.text(0)
        video = next((v for v in self.search_results if v.get("bvid") == bvid), None)
        if not video:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 28px; font-size: 9pt;
            }}
            QMenu::item:selected {{
                background-color: {C['bg_hover']};
            }}
        """)

        detail_action = QAction("☰ 查看详情", self)
        detail_action.triggered.connect(lambda: self._show_video_detail(video))
        menu.addAction(detail_action)

        copy_action = QAction("▭ 复制BV号", self)
        copy_action.triggered.connect(lambda: self._copy_bvid(bvid))
        menu.addAction(copy_action)

        open_action = QAction("✈ 在浏览器中打开", self)
        open_action.triggered.connect(lambda: webbrowser.open(f"https://www.bilibili.com/video/{bvid}"))
        menu.addAction(open_action)

        menu.addSeparator()

        import_action = QAction("＋ 导入该视频", self)
        import_action.triggered.connect(lambda: self._import_single(video))
        menu.addAction(import_action)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _show_video_detail(self, video):
        """弹出详情对话框显示搜索结果的视频信息"""
        bvid = video.get("bvid", "")
        title = video.get("title", "").replace('<em class="keyword">', "").replace("</em>", "")
        author = video.get("author", "未知")
        play = video.get("play", 0)
        like = video.get("like", 0)
        pic = video.get("pic", "")

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
        from PyQt6.QtGui import QPixmap, QFont
        from PyQt6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowTitle(f"视频详情 - {bvid} ♪")
        screen = self.screen()
        if screen:
            geo = screen.geometry()
            sw, sh = geo.width(), geo.height()
        else:
            sw, sh = 1920, 1080
        dlg.resize(int(sw * 0.32), int(sh * 0.48))
        dlg.setStyleSheet(f"background-color: {C['bg_surface']};")
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 20, 24, 20)

        # 标题
        title_lbl = QLabel("视频详情 ♪")
        title_lbl.setFont(QFont("Microsoft YaHei UI", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C['text_1']};")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)
        layout.addSpacing(8)

        # 封面图
        if pic.startswith("http"):
            try:
                import requests
                from PIL import Image

                resp = requests.get(pic, timeout=5)
                img_data = io.BytesIO(resp.content)
                pixmap = QPixmap()
                if pixmap.loadFromData(img_data.getvalue()):
                    pixmap = pixmap.scaled(320, 180, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                    cover_lbl = QLabel()
                    cover_lbl.setPixmap(pixmap)
                    cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cover_lbl.setStyleSheet("background: transparent;")
                    layout.addWidget(cover_lbl)
                else:
                    # 用 PIL 兜底转换
                    img = Image.open(io.BytesIO(resp.content)).resize((320, 180))
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    pixmap2 = QPixmap()
                    pixmap2.loadFromData(buf.getvalue())
                    cover_lbl2 = QLabel()
                    cover_lbl2.setPixmap(pixmap2)
                    cover_lbl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cover_lbl2.setStyleSheet("background: transparent;")
                    layout.addWidget(cover_lbl2)
            except Exception as e:
                logger.debug("封面加载失败: %s", e)

        # 信息展示区
        info_widget = QWidget()
        info_widget.setStyleSheet(f"background-color: {C['bg_surface']};")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 8, 0, 8)

        rows = [
            ("BV号", bvid),
            ("标题", title),
            ("UP主", author),
            ("播放量", f"{play:,}" if play else "0"),
            ("点赞", f"{like:,}" if like else "0"),
        ]
        for label, value in rows:
            row = QWidget()
            row.setStyleSheet(f"background-color: {C['bg_surface']};")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)

            lbl = QLabel(label)
            lbl.setFont(QFont("Microsoft YaHei UI", 9))
            lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            lbl.setFixedWidth(60)
            row_layout.addWidget(lbl)

            val = QLabel(value)
            val.setFont(QFont("Microsoft YaHei UI", 9))
            val.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
            val.setWordWrap(True)
            row_layout.addWidget(val, 1)

            info_layout.addWidget(row)

        layout.addWidget(info_widget)
        layout.addStretch()

        # 按钮行
        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_surface']};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 8, 0, 0)

        open_btn = QPushButton("✈ 浏览器打开 ♪")
        open_btn.clicked.connect(lambda: webbrowser.open(f"https://www.bilibili.com/video/{bvid}"))
        btn_layout.addWidget(open_btn)

        import_btn = QPushButton("＋ 导入监控 ♪")
        import_btn.clicked.connect(lambda: [dlg.accept(), self._import_single(video)])
        btn_layout.addWidget(import_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(close_btn)

        layout.addWidget(btn_row)
        dlg.exec()

    def _copy_bvid(self, bvid):
        """复制 BV 号到剪贴板"""
        QApplication.clipboard().setText(bvid)
        self.status_lbl.setText(f"已把 {bvid} 记进歌词本啦 ♪")
        self.status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")

    def _import_single(self, video):
        """导入单个视频到监控"""
        self.close()
        if self.on_import:
            self.on_import([video])
