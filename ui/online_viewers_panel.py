"""
在线人数监控面板 — PyQt6 版
实时查看所有监控视频的在线观看人数
15s 刷新，数据写入独立 SQLite 数据库（与主视频 dict 分离，避免锁争用）。
"""
import logging
import threading
import os
import sqlite3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from ui.theme import C
from ui.helpers import FONT, FONT_SM, fmt_num, _parse_viewer_count

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 15000  # 毫秒，15 秒刷新
MAX_VIEWER_FETCH_WORKERS = 4
TOP_N_FETCH = 20

# ── 模块级在线人数数据库（每个视频独立 data/<BV>/viewercount.db）──
_db_cache: dict = {}
_db_lock = threading.Lock()


def _get_viewer_db(bvid: str) -> sqlite3.Connection:
    """获取指定视频的在线人数数据库连接（惰性创建）"""
    if bvid in _db_cache:
        return _db_cache[bvid]
    from config import DATA_DIR
    db_path = os.path.join(DATA_DIR, bvid, "viewercount.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = sqlite3.connect(db_path, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS viewers "
        "(timestamp TEXT, total INTEGER, web INTEGER, app INTEGER)"
    )
    db.commit()
    _db_cache[bvid] = db
    return db


def _write_viewer(bvid: str, total: int, web: int, app: int):
    """写入一条在线人数记录"""
    with _db_lock:
        db = _get_viewer_db(bvid)
        db.execute(
            "INSERT INTO viewers (timestamp, total, web, app) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), total, web, app),
        )
        db.commit()


def _read_viewers() -> dict:
    """读取每个视频最新的在线人数（bvid → {total, web, app}）"""
    result = {}
    with _db_lock:
        for bvid, db in list(_db_cache.items()):
            cur = db.execute(
                "SELECT total, web, app FROM viewers ORDER BY timestamp DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                result[bvid] = {"total": row[0], "web": row[1], "app": row[2]}
    return result


def _close_viewers_db():
    """关闭所有在线人数数据库连接"""
    with _db_lock:
        for db in _db_cache.values():
            try:
                db.close()
            except Exception:
                pass
        _db_cache.clear()


# ══════════════════════════════════════════════════════════════════════════════
# ── 面板 ──────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


class OnlineViewersPanel(QWidget):
    """在线人数监控面板 — 内嵌在右侧区域的 QWidget"""

    def __init__(self, parent=None, main_gui=None):
        super().__init__(parent)
        self.gui = main_gui
        self._sort_col = "viewers_total"
        self._sort_rev = True
        self._refresh_lock = threading.Lock()
        self._fetch_pool = None
        self._active = False
        self._started = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh_tick)

        self._item_map: dict = {}  # bvid → QTreeWidgetItem
        self._build_ui()

    def _build_ui(self):
        """构建在线人数监控面板的 UI：表头、树形表格、状态栏"""
        self.setStyleSheet(f"background-color: {C['bg_base']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 表头 ──
        header = QWidget()
        header.setStyleSheet(f"background-color: {C['bg_surface']};")
        header.setFixedHeight(48)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title_lbl = QLabel("在线人数监控")
        title_font = QFont("Microsoft YaHei UI", 14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {C['text_1']};")
        header_layout.addWidget(title_lbl)

        self._count_lbl = QLabel("")
        self._count_lbl.setFont(FONT)
        self._count_lbl.setStyleSheet(f"color: {C['text_3']};")
        header_layout.addWidget(self._count_lbl)

        header_layout.addStretch()

        self._time_lbl = QLabel("")
        self._time_lbl.setFont(FONT_SM)
        self._time_lbl.setStyleSheet(f"color: {C['text_3']};")
        header_layout.addWidget(self._time_lbl)

        root.addWidget(header)

        # ── 分隔线 ──
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {C['border']};")
        root.addWidget(sep)

        # ── 树形表格 ──
        columns = ("rank", "title", "bvid", "viewers_total", "viewers_web", "viewers_app", "view_count", "online_rate")
        col_cfgs = [
            ("rank", "#", 36),
            ("title", "视频标题", 320),
            ("bvid", "BV号", 130),
            ("viewers_total", "在线人数", 110),
            ("viewers_web", "Web端", 90),
            ("viewers_app", "App端", 90),
            ("view_count", "播放量", 110),
            ("online_rate", "在线率", 90),
        ]

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(columns)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']};
                alternate-background-color: {C['bg_surface']};
                border: none;
                font-size: 9pt;
            }}
            QTreeWidget::item {{
                padding: 2px 4px;
                min-height: 24px;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: none;
                border-bottom: 1px solid {C['border']};
                padding: 4px 8px;
                font-weight: bold;
            }}
        """)

        header_view = self._tree.header()
        if header_view is not None:
            for col_id, heading, width in col_cfgs:
                idx = columns.index(col_id)
                header_view.setSectionResizeMode(idx, QHeaderView.ResizeMode.Fixed)
                self._tree.setColumnWidth(idx, width)
            # 标题列可拉伸
            header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header_view.sectionClicked.connect(self._on_header_click)

        self._tree.itemSelectionChanged.connect(self._on_selection_changed)

        root.addWidget(self._tree, 1)

        # ── 底部状态栏 ──
        status_bar = QWidget()
        status_bar.setStyleSheet(f"background-color: {C['bg_surface']};")
        status_bar.setFixedHeight(32)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 0, 12, 0)

        self._status_lbl = QLabel("就绪")
        self._status_lbl.setFont(FONT_SM)
        self._status_lbl.setStyleSheet(f"color: {C['text_3']};")
        status_layout.addWidget(self._status_lbl)

        status_layout.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.setProperty("primary", True)
        style = refresh_btn.style()
        if style is not None:
            style.unpolish(refresh_btn)
            style.polish(refresh_btn)
        refresh_btn.clicked.connect(self.refresh)
        status_layout.addWidget(refresh_btn)

        jump_btn = QPushButton("跳转到视频")
        jump_btn.clicked.connect(self._jump_to_video)
        status_layout.addWidget(jump_btn)

        root.addWidget(status_bar)

    # ── 事件 ──────────────────────────────────────────────

    def _on_header_click(self, index):
        """点击表头排序"""
        col_map = {
            0: "rank", 1: "title", 2: "bvid", 3: "viewers_total",
            4: "viewers_web", 5: "viewers_app", 6: "view_count", 7: "online_rate",
        }
        col = col_map.get(index, "viewers_total")
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = col in ("viewers_total", "viewers_web", "viewers_app", "view_count", "online_rate", "rank")
        self._populate()

    def _on_selection_changed(self):
        pass

    def _jump_to_video(self):
        sel = self._tree.selectedItems()
        if not sel:
            return
        bvid = sel[0].data(0, Qt.ItemDataRole.UserRole + 1)
        if bvid and self.gui:
            self.gui._switch_nav("监控列表")
            self.gui._select_video(bvid)

    # ── 刷新 ──────────────────────────────────────────────

    def refresh(self):
        if not self._refresh_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._async_refresh, daemon=True).start()

    def _async_refresh(self):
        try:
            self._fetch_all_viewers()
        finally:
            self._refresh_lock.release()
        if self._active:
            QTimer.singleShot(0, self._update_ui_after_fetch)

    def _fetch_all_viewers(self):
        """并发拉取高优先级视频的在线观看人数，写入独立缓存。"""
        gui = self.gui
        if gui is None:
            return
        videos = gui.monitored_videos
        if not videos:
            return

        # 选中的视频
        selected_bvid = None
        sel = self._tree.selectedItems()
        if sel:
            selected_bvid = sel[0].data(0, Qt.ItemDataRole.UserRole + 1)

        # 按缓存中的在线人数排序
        cached = _read_viewers()
        ranked = sorted(
            [(v, v.get("viewers_total", cached.get(v.get("bvid", ""), {}).get("total", 0))) for v in videos],
            key=lambda x: x[1], reverse=True,
        )
        priority_videos = [v for v, _ in ranked[:TOP_N_FETCH]]

        if selected_bvid:
            for v in videos:
                if v.get("bvid") == selected_bvid and v not in priority_videos:
                    priority_videos.append(v)
                    break

        fetchable = []
        for v in priority_videos:
            cid = v.get("_cid", 0) or v.get("cid", 0)
            if cid:
                fetchable.append((v.get("bvid", ""), cid))

        if not fetchable:
            return

        if self._fetch_pool is None:
            self._fetch_pool = ThreadPoolExecutor(max_workers=MAX_VIEWER_FETCH_WORKERS)

        def _fetch_one(bvid, cid):
            try:
                from core import bilibili_api
                viewers = bilibili_api.get_video_viewers(bvid, cid)
                if viewers:
                    total = _parse_viewer_count(viewers.get("total", "0"))
                    web = _parse_viewer_count(viewers.get("count", "0"))
                    app = max(0, total - web)
                    _write_viewer(bvid, total, web, app)
            except Exception:
                pass

        futures = [self._fetch_pool.submit(_fetch_one, bvid, cid) for bvid, cid in fetchable]
        for f in as_completed(futures, timeout=10):
            try:
                f.result()
            except Exception:
                pass

    def _populate(self):
        """填充树形表格：合并视频列表（标题/播放量）与在线人数缓存"""
        cached = _read_viewers()
        gui = self.gui
        if gui is None:
            return
        videos = gui.monitored_videos
        if not videos:
            return

        rows = []
        for video in videos:
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)
            view_count = video.get("view_count", 0)
            vdata = cached.get(bvid, {})
            viewers_total = vdata.get("total", 0)
            viewers_web = vdata.get("web", 0)
            viewers_app = vdata.get("app", 0)
            online_rate = (viewers_total / view_count * 100) if view_count > 0 else 0
            rows.append((bvid, title, view_count, viewers_total, viewers_web, viewers_app, online_rate))

        col_key = self._sort_col
        reverse = self._sort_rev

        def _sort_key(r):
            idx_map = {
                "title": 1, "bvid": 0, "view_count": 2,
                "viewers_total": 3, "viewers_web": 4, "viewers_app": 5,
                "online_rate": 6, "rank": 3,
            }
            val = r[idx_map.get(col_key, 3)]
            return val.lower() if isinstance(val, str) else val

        rows.sort(key=_sort_key, reverse=reverse)

        self._count_lbl.setText(f"共 {len(rows)} 个视频")
        self._status_lbl.setText(f"共 {len(rows)} 个视频 · 按在线人数排序")

        # 删除不存在的项
        new_bvids = {r[0] for r in rows}
        for bvid in list(self._item_map.keys()):
            if bvid not in new_bvids:
                item = self._item_map.pop(bvid, None)
                if item is not None:
                    root = self._tree.invisibleRootItem()
                    if root is not None:
                        root.removeChild(item)

        # 填充/更新数据
        for i, r in enumerate(rows):
            bvid = r[0]
            vt = r[3]
            if vt >= 10000:
                rate_color = C["success"]
            elif vt >= 1000:
                rate_color = C["warning"]
            else:
                rate_color = C["text_3"]

            title_display = r[1][:40] + "\u2026" if len(r[1]) > 40 else r[1]
            rate_display = f"{r[6]:.2f}%" if r[6] > 0 else "\u2014"

            values = [
                str(i + 1),
                title_display,
                bvid,
                fmt_num(r[3]),
                fmt_num(r[4]),
                fmt_num(r[5]),
                fmt_num(r[2]),
                rate_display,
            ]

            item = self._item_map.get(bvid)
            if item is not None:
                for col_idx, val in enumerate(values):
                    item.setText(col_idx, val)
                item.setForeground(3, QColor(rate_color))
            else:
                item = QTreeWidgetItem(values)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, bvid)
                item.setForeground(3, QColor(rate_color))
                self._tree.addTopLevelItem(item)
                self._item_map[bvid] = item

    def _update_ui_after_fetch(self):
        self._populate()
        self._time_lbl.setText(f"上次刷新: {datetime.now().strftime('%H:%M:%S')}")

    # ── 生命周期 ──────────────────────────────────────────

    def on_show(self):
        """面板显示：启动定时器 + 线程池（首次），然后立即刷新"""
        self._active = True
        if not self._started:
            self._started = True
            self._start_auto_refresh()
            if self._fetch_pool is None:
                self._fetch_pool = ThreadPoolExecutor(max_workers=MAX_VIEWER_FETCH_WORKERS)
        self.refresh()

    def on_hide(self):
        """面板隐藏：仅标记不可见（定时器和线程池继续运行）"""
        self._active = False

    def cleanup(self):
        """应用退出时释放资源"""
        self._active = False
        self._stop_auto_refresh()
        if self._fetch_pool:
            self._fetch_pool.shutdown(wait=False)
            self._fetch_pool = None
        _close_viewers_db()

    def _start_auto_refresh(self):
        self._timer.start(REFRESH_INTERVAL)

    def _stop_auto_refresh(self):
        self._timer.stop()

    def _auto_refresh_tick(self):
        self.refresh()
