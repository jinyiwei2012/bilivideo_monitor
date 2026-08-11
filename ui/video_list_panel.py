"""
左侧视频列表面板模块 - PyQt6 版

使用 QListWidget + 自定义 delegate 替代 CTkScrollableFrame 内嵌卡片。
支持视频卡片展示、搜索、选择、封面异步加载。
"""

import logging
from io import BytesIO
from collections import OrderedDict
import threading

import requests as _req

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QLineEdit,
    QFrame, QSizePolicy, QStyledItemDelegate, QStyle,
    QStackedLayout,
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QObject, QRectF
from PyQt6.QtGui import QPixmap, QColor, QPainter, QPen, QFontMetrics, QPainterPath

from ui.theme import C
from ui.helpers import (
    FONT, FONT_CAPTION, SPACE_SM, SPACE_MD, SPACE_LG,
    fmt_num, nearest_threshold_gap, card_status_tag,
)
from ui.widgets import SectionHeader, EmptyState
from utils.cover_manager import get_valid_cover, save_cover

_cover_session = _req.Session()
_cover_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
})
_cover_semaphore = threading.Semaphore(4)
logger = logging.getLogger(__name__)


class CoverLoader(QObject):
    """封面异步加载器 - 在后台线程加载封面图片"""
    cover_loaded = pyqtSignal(str, object)  # bvid, QPixmap

    def __init__(self):
        super().__init__()
        self._running = True

    def load_cover(self, bvid, url):
        """在后台线程加载封面——不阻塞主线程"""
        if not self._running:
            return

        def _fetch():
            try:
                with _cover_semaphore:
                    resp = _cover_session.get(url, timeout=10)
                    if resp.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(resp.content)
                        if not pixmap.isNull():
                            self.cover_loaded.emit(bvid, pixmap)
                            save_cover(bvid, resp.content)
            except Exception as e:
                logger.debug("封面加载失败 %s: %s", bvid, e)

        threading.Thread(target=_fetch, daemon=True, name=f"cover-{bvid}").start()


class VideoCardDelegate(QStyledItemDelegate):
    """视频卡片自定义绘制代理"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cover_cache = {}  # bvid -> QPixmap
        self._thumb_size = QSize(80, 45)

    def set_cover(self, bvid, pixmap):
        if pixmap and not pixmap.isNull():
            self._cover_cache[bvid] = pixmap.scaled(
                self._thumb_size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            super().paint(painter, option, index)
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_hovered = option.state & QStyle.StateFlag.State_MouseOver

        # 背景: 默认表面色, hover/选中以天依蓝浅色水波高光
        if is_selected:
            bg = QColor(C["lty_blue"])
            bg.setAlpha(70)
        elif is_hovered:
            bg = QColor(C["lty_blue"])
            bg.setAlpha(36)
        else:
            bg = QColor(C["bg_surface"])
        painter.fillRect(rect, bg)

        margin = SPACE_MD
        x, y = rect.x() + margin, rect.y() + margin
        w, h = rect.width() - 2 * margin, rect.height() - 2 * margin

        # 封面缩略图 (圆角裁剪 + 细描边)
        bvid = data.get("bvid", "")
        thumb = self._cover_cache.get(bvid)
        thumb_rect = QRectF(x, y, 80, 45)
        radius = C["radius_sm"]
        path = QPainterPath()
        path.addRoundedRect(thumb_rect, radius, radius)

        painter.save()
        painter.setClipPath(path)
        if thumb:
            painter.drawPixmap(x, y, 80, 45, thumb)
        else:
            painter.fillRect(thumb_rect, QColor(C["bg_hover"]))
            painter.setPen(QPen(QColor(C["text_3"])))
            painter.drawText(x + SPACE_MD, y + 25, "No Cover")
        painter.restore()

        painter.setPen(QPen(QColor(C["border"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # 标题 (FONT 主层级)
        title = data.get("title", "")[:30]
        tx = x + 90
        ty = y + 14
        painter.setPen(QColor(C["text_1"]))
        font = FONT
        fm = QFontMetrics(font)

        max_w = w - 90
        if fm.horizontalAdvance(title) > max_w:
            title = fm.elidedText(title, Qt.TextElideMode.ElideRight, max_w)
        painter.setFont(font)
        painter.drawText(tx, ty - fm.height() + 14, title)

        # 副信息 (FONT_CAPTION 次层级)
        views = data.get("view_count", 0)
        painter.setPen(QColor(C["text_2"]))
        painter.setFont(FONT_CAPTION)
        painter.drawText(tx, ty + 16, f"播放: {fmt_num(views)}")

        # 状态标签
        gap, _ = nearest_threshold_gap(views)
        tag_text, tag_color = card_status_tag(gap)
        painter.setPen(QColor(tag_color))
        painter.drawText(tx, ty + 30, tag_text)

        # 选中高亮边框 (天依蓝)
        if is_selected:
            painter.setPen(QPen(QColor(C["bilibili"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), C["radius_md"], C["radius_md"])

    def sizeHint(self, option, index):
        return QSize(0, 60)


class VideoListPanel(QWidget):
    """左侧视频列表面板"""

    video_selected = pyqtSignal(str)  # bvid

    def __init__(self, parent, gui):
        super().__init__(parent)
        self.gui = gui
        self._parent = parent
        self._cover_cache = OrderedDict()
        self._card_widgets = {}  # bvid -> index
        self._search_text = ""

        # 封面加载器 — 在主线程通过 QTimer.singleShot 延迟加载，_cover_semaphore(4) 限制并发
        self._cover_loader = CoverLoader()
        self._cover_loader.cover_loaded.connect(self._on_cover_loaded)

        self._build()

    def closeEvent(self, event):
        """清理封面加载器"""
        self._cover_loader._running = False
        super().closeEvent(event)

    def _build(self):
        """构建左侧面板"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题头 (SectionHeader: 天依蓝竖条 + 标题)
        hdr = QWidget()
        hdr.setStyleSheet(f"background-color: {C['bg_surface']};")
        h = QHBoxLayout(hdr)
        h.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_SM)

        h.addWidget(SectionHeader("监控视频", parent=hdr))

        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet(f"""
            background-color: {C['lty_blue_light']}; color: {C['lty_blue_deep']};
            padding: 0px {SPACE_MD}px; border-radius: {C['radius_lg']}px;
            font-weight: bold; font-size: 8pt;
        """)
        h.addWidget(self._count_lbl)

        h.addStretch()

        push_all_btn = QPushButton("⇪ 全部推送")
        push_all_btn.setFixedSize(70, 22)
        push_all_btn.setProperty("accent", True)
        push_all_btn.clicked.connect(self.gui._manual_push)
        h.addWidget(push_all_btn)

        layout.addWidget(hdr)

        # 搜索框
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索BV号或标题...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                margin: {SPACE_SM}px {SPACE_LG}px;
                padding: {SPACE_SM}px {SPACE_MD}px;
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                background-color: {C['bg_base']};
                color: {C['text_1']};
            }}
        """)
        layout.addWidget(self._search)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        layout.addWidget(sep)

        # 视频列表
        self._list = QListWidget()
        self._list.setItemDelegate(VideoCardDelegate())
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSpacing(2)
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_surface']};
                border: none;
                outline: none;
            }}
        """)
        self._list.currentItemChanged.connect(self._on_item_changed)

        # 列表 + 空状态: QStackedLayout 按有无视频切换 (EmptyState ♪)
        self._list_stack = QStackedLayout()
        self._list_stack.addWidget(self._list)
        self._empty_state = EmptyState("暂无监控视频 ♪")
        self._list_stack.addWidget(self._empty_state)
        self._list_stack.setCurrentWidget(self._empty_state)
        layout.addLayout(self._list_stack, 1)

    def _on_cover_loaded(self, bvid, pixmap):
        """封面加载完成回调"""
        delegate = self._list.itemDelegate()
        if isinstance(delegate, VideoCardDelegate):
            delegate.set_cover(bvid, pixmap)
        # 刷新可见项
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("bvid") == bvid:
                self._list.update(self._list.indexFromItem(item))
                break

    def _on_search(self, text):
        """搜索过滤"""
        self._search_text = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                bvid = data.get("bvid", "").lower()
                title = data.get("title", "").lower()
                visible = not self._search_text or self._search_text in bvid or self._search_text in title
                item.setHidden(not visible)

    def _on_item_changed(self, current, previous):
        """选中项变更"""
        if current:
            data = current.data(Qt.ItemDataRole.UserRole)
            if data:
                bvid = data.get("bvid", "")
                self.video_selected.emit(bvid)
                if hasattr(self.gui, '_select_video'):
                    self.gui._select_video(bvid)

    def rebuild_list(self, videos):
        """重建视频列表"""
        self._list.clear()
        delegate = self._list.itemDelegate()
        for v in videos:
            bvid = v.get("bvid", "")
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, v)
            item.setSizeHint(QSize(0, 60))
            self._list.addItem(item)

            # 触发封面异步加载
            cover_url = v.get("pic", v.get("cover_url", ""))
            if cover_url:
                local = get_valid_cover(bvid)
                if local:
                    pixmap = QPixmap(local)
                    if not pixmap.isNull():
                        if isinstance(delegate, VideoCardDelegate):
                            delegate.set_cover(bvid, pixmap)
                else:
                    QTimer.singleShot(0, lambda b=bvid, u=cover_url: (
                        self._cover_loader.load_cover(b, u)
                    ))

        self._update_count()

    def make_card(self, video):
        """添加单个视频卡片"""
        bvid = video.get("bvid", "")
        if not bvid:
            return
        # 检查是否已存在
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("bvid") == bvid:
                return
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, video)
        item.setSizeHint(QSize(0, 60))
        self._list.addItem(item)
        self._update_count()

    def update_card(self, video):
        """更新已有视频卡片的数据（刷新封面、标题、播放量等）"""
        bvid = video.get("bvid", "")
        if not bvid:
            return
        delegate = self._list.itemDelegate()
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("bvid") == bvid:
                # 合并新数据到已有数据
                data.update(video)
                item.setData(Qt.ItemDataRole.UserRole, data)
                # 刷新显示
                self._list.update(self._list.indexFromItem(item))
                # 触发封面加载
                cover_url = video.get("pic", video.get("cover_url", ""))
                if cover_url:
                    local = get_valid_cover(bvid)
                    if local:
                        pixmap = QPixmap(local)
                        if not pixmap.isNull() and isinstance(delegate, VideoCardDelegate):
                            delegate.set_cover(bvid, pixmap)
                    else:
                        QTimer.singleShot(0, lambda b=bvid, u=cover_url: (
                            self._cover_loader.load_cover(b, u)
                        ))
                break

    def update_video_count(self):
        """公开更新视频计数"""
        self._update_count()

    def _update_count(self):
        """更新视频计数"""
        count = self._list.count()
        self._count_lbl.setText(str(count))
        stack = getattr(self, "_list_stack", None)
        if stack is not None:
            stack.setCurrentWidget(self._empty_state if count == 0 else self._list)

    def select_by_bvid(self, bvid):
        """按 BV 号选中"""
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("bvid") == bvid:
                self._list.setCurrentItem(item)
                break

    def highlight_card(self, bvid):
        """高亮选中指定 BV 号的卡片"""
        self.select_by_bvid(bvid)
