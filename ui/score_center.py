"""周/年分数中心 —— 计算、查询与补齐归档

定位（只做三件事）：
1. **计算**：按需把 ``monitor_records`` 物化为整点桶分数（``utils.score_materializer``）
2. **查询**：按视频 + 时间范围查看周刊 / 年刊分数
3. **补齐**：把「之前未写入但刚算出的」数据幂等写库（重复点击不产生重复行）

标注：**分数按需计算 · 趋势按小时归档**（非每帧写入，未打开窗口 / 未请求的视频零写入）。
主线程只做渲染：所有数据库读写都发生在后台线程或纯函数中，经 :func:`ui.invoker.invoke` 回主线程。
"""

import logging
import threading
from datetime import datetime, timedelta

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ui.dialog_base import DialogBase
from ui.invoker import invoke
from ui.theme import C
from utils.score_materializer import ensure_scores
from utils.thread_utils import fire_and_forget
from utils.time_utils import format_ts

logger = logging.getLogger(__name__)

#: 时间范围选项（标签 → 天数；None 表示不过滤）
RANGE_OPTIONS = (("全部", None), ("最近7天", 7), ("最近30天", 30), ("最近90天", 90))

WEEKLY_COLUMNS = (
    "时间戳", "总分", "播放", "互动", "收藏", "硬币", "点赞",
    "修正A", "修正B", "修正C", "修正D", "基础播放",
)
YEARLY_COLUMNS = (
    "时间戳", "总分", "播放", "互动", "收藏", "硬币", "点赞",
    "修正A", "修正B", "修正C",
)

#: 两表共用的得分列顺序
_BASE_KEYS = ("total_score", "view_score", "interaction_score", "favorite_score", "coin_score", "like_score")
_WEEKLY_EXTRA = ("correction_a", "correction_b", "correction_c", "correction_d", "base_view_score")
_YEARLY_EXTRA = ("correction_a", "correction_b", "correction_c")

_TABLE_QSS = (
    f"QTableWidget {{ background-color: {C['bg_base']}; color: {C['text_1']};"
    f" gridline-color: {C['border']}; font-size: 9pt; }}"
    f"QHeaderView::section {{ background-color: {C['bg_elevated']}; color: {C['text_2']};"
    f" border: none; padding: 4px; }}"
)


# ── 纯函数（无 Qt 依赖，可无界面测试）────────────────────────


def range_cutoff(key: str):
    """时间范围标签 → 起始时间戳（规范格式）；"全部" 返回 None。"""
    for label, days in RANGE_OPTIONS:
        if key == label:
            return None if days is None else format_ts(datetime.now() - timedelta(days=days))
    return None


def _fmt_score(value) -> str:
    """分数字段 → 单元格文本；None / 非数值返回空串。"""
    if value is None:
        return ""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return ""


def format_score_row(row: dict, kind: str = "weekly") -> list:
    """把一条分数行格式化为表格单元格文本（列顺序固定，与表头一致）。"""
    cells = [str(row.get("timestamp", ""))]
    cells.extend(_fmt_score(row.get(key)) for key in _BASE_KEYS)
    extras = _WEEKLY_EXTRA if kind == "weekly" else _YEARLY_EXTRA
    cells.extend(_fmt_score(row.get(key)) for key in extras)
    return cells


def filter_rows(rows: list, cutoff) -> list:
    """按起始时间戳过滤（规范格式下字典序即时间序）；cutoff 为 None 时不过滤。"""
    if not cutoff:
        return list(rows)
    return [r for r in rows if str(r.get("timestamp", "")) >= cutoff]


def load_scores(video_db, kind: str = "weekly") -> list:
    """先按整点桶补齐归档（幂等），再读取全部分数行。

    这是「先物化再读」契约的唯一入口：详情面板与分数中心都走它，保证趋势始终含最新点。
    """
    ensure_scores(video_db)
    if kind == "yearly":
        return video_db.get_yearly_scores(limit=0)
    return video_db.get_weekly_scores(limit=0)


def sort_rows_ascending(rows: list) -> list:
    """按 timestamp 升序（趋势图从左到右 = 时间从早到晚）。"""
    return sorted(rows, key=lambda r: str(r.get("timestamp", "")))


# ── 迷你趋势图 ───────────────────────────────────────────────


class _ScoreTrend(QWidget):
    """迷你趋势图：总分折线（输入需为时间升序）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list = []
        self.setMinimumHeight(90)
        self.setStyleSheet(f"background-color: {C['bg_base']};")

    def set_rows(self, rows: list):
        """更新数据点（rows 应为时间升序）。"""
        self._points = [float(r.get("total_score", 0) or 0) for r in rows]
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(C["bg_base"]))
        if len(self._points) < 2:
            painter.setPen(QPen(QColor(C["text_3"])))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "数据点还太少，攒够 2 个小时就有曲线啦 ♪")
            return

        lo, hi = min(self._points), max(self._points)
        span = (hi - lo) or 1.0
        width, height, pad = self.width(), self.height(), 10
        step = (width - 2 * pad) / (len(self._points) - 1)
        poly = QPolygonF([
            QPointF(pad + i * step, height - pad - (value - lo) / span * (height - 2 * pad))
            for i, value in enumerate(self._points)
        ])
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(C["accent"]), 2))
        painter.drawPolyline(poly)


# ── 窗口 ─────────────────────────────────────────────────────


class ScoreCenterWindow:
    """周/年分数中心窗口（非模态）。"""

    def __init__(self, parent=None, gui=None):
        self.gui = gui
        self.dlg = DialogBase(parent, "周/年分数中心", "920x640", modal=False)
        self._busy = False
        self._cancel = threading.Event()
        self._cache: dict = {}       # (bvid|"", kind) -> {"rows": [...], "latest": str}
        self._pending: set = set()   # 正在后台读取的 (bvid, kind)
        self._setup_ui()

    # ── 界面 ────────────────────────────────────────────

    def _setup_ui(self):
        dlg = self.dlg
        dlg.header("周/年分数中心", "分数按需计算 · 趋势按小时归档（非每帧写入）")

        top = dlg.section(title="视频与操作")
        row = QHBoxLayout()

        self._video_cb = QComboBox()
        self._video_cb.setMinimumWidth(320)
        self._reload_videos()
        self._video_cb.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self._video_cb)

        self._range_cb = QComboBox()
        self._range_cb.addItems([label for label, _ in RANGE_OPTIONS])
        self._range_cb.currentIndexChanged.connect(self._on_selection_changed)
        row.addWidget(self._range_cb)

        self._run_btn = QPushButton("计算并补齐")
        self._run_btn.setProperty("primary", True)
        self._run_btn.clicked.connect(self._start_materialize)
        row.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_materialize)
        row.addWidget(self._cancel_btn)
        row.addStretch()
        top.layout().addLayout(row)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        top.layout().addWidget(self._status)

        area = dlg.content_area()
        outer = QVBoxLayout(area)
        outer.setContentsMargins(14, 10, 14, 10)

        self._tabs = QTabWidget()
        self._tables = {}
        for kind, name, columns in (
            ("weekly", "周刊分数", WEEKLY_COLUMNS),
            ("yearly", "年刊分数", YEARLY_COLUMNS),
        ):
            table = QTableWidget(0, len(columns))
            table.setHorizontalHeaderLabels(list(columns))
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setStyleSheet(_TABLE_QSS)
            self._tables[kind] = table
            self._tabs.addTab(table, name)
        self._tabs.currentChanged.connect(lambda _i: self._on_selection_changed())
        outer.addWidget(self._tabs, 1)

        self._trend = _ScoreTrend()
        outer.addWidget(self._trend)

        dlg.button_row([("关闭", self.dlg.close, "")])
        self._on_selection_changed()

    def _reload_videos(self):
        """填充视频下拉框（"全部视频" + 每个监控视频）。"""
        self._video_cb.blockSignals(True)
        self._video_cb.clear()
        self._video_cb.addItem("全部视频", "")
        for video in getattr(self.gui, "monitored_videos", []) or []:
            bvid = video.get("bvid", "")
            if bvid:
                self._video_cb.addItem(f"[{bvid}] {video.get('title', bvid)[:40]}", bvid)
        self._video_cb.blockSignals(False)

    @property
    def _kind(self) -> str:
        return "yearly" if self._tabs.currentIndex() == 1 else "weekly"

    def _selected_bvid(self) -> str:
        return self._video_cb.currentData() or ""

    def _selected_bvids(self) -> list:
        bvid = self._selected_bvid()
        if bvid:
            return [bvid]
        return [v.get("bvid", "") for v in (getattr(self.gui, "monitored_videos", []) or []) if v.get("bvid")]

    # ── 渲染（主线程，零查库）────────────────────────────

    def _on_selection_changed(self):
        """选择变化 / 切页 / 改范围：先用缓存渲染，再按需后台加载。"""
        kind = self._kind
        bvid = self._selected_bvid()
        entry = self._cache.get((bvid, kind))
        if entry is None:
            self._render(kind, [])
            self._status.setText("正在读取归档… · 分数按需计算 · 趋势按小时归档")
            self._schedule_load(bvid, kind)
            return
        cutoff = range_cutoff(self._range_cb.currentText())
        rows = filter_rows(entry["rows"], cutoff)
        self._render(kind, rows)
        latest = entry.get("latest") or "无归档"
        self._status.setText(f"最近归档: {latest} · 共 {len(rows)} 行 · 分数按需计算 · 趋势按小时归档")

    def _render(self, kind: str, rows: list):
        """把行数据填进表格与趋势图（纯 UI）。"""
        table = self._tables[kind]
        table.setRowCount(0)
        for row in rows:
            cells = format_score_row(row, kind)
            r = table.rowCount()
            table.insertRow(r)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                alignment = Qt.AlignmentFlag.AlignRight if c else Qt.AlignmentFlag.AlignLeft
                item.setTextAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        self._trend.set_rows(sort_rows_ascending(rows))

    # ── 后台加载（先物化再读）────────────────────────────

    def _schedule_load(self, bvid: str, kind: str):
        """后台读取分数（含幂等物化），完成后回主线程刷新缓存。"""
        key = (bvid, kind)
        if key in self._pending:
            return
        self._pending.add(key)

        def _work():
            rows, latest = [], ""
            try:
                if bvid:
                    video_db = getattr(self.gui, "video_dbs", {}).get(bvid)
                    if video_db is not None:
                        rows = load_scores(video_db, kind)
                        latest_row = video_db.get_latest_weekly_score()
                        latest = str((latest_row or {}).get("timestamp", "") or "")
                else:
                    for other in self._selected_bvids():
                        video_db = getattr(self.gui, "video_dbs", {}).get(other)
                        if video_db is None:
                            continue
                        rows.extend(load_scores(video_db, kind))
                    rows = sort_rows_ascending(rows)
                    rows.reverse()  # 表格按最新在前
                    latest = str((rows[0] or {}).get("timestamp", "")) if rows else ""
            except Exception as e:
                logger.warning("分数中心读取失败 %s/%s: %s", bvid, kind, e)

            def _apply():
                self._pending.discard(key)
                self._cache[key] = {"rows": rows, "latest": latest}
                if self._selected_bvid() == bvid and self._kind == kind:
                    self._on_selection_changed()

            invoke(_apply)

        fire_and_forget(_work, name=f"score-center:{bvid or 'all'}:{kind}")

    # ── 计算并补齐 ───────────────────────────────────────

    def _start_materialize(self):
        """后台对各选中视频执行 ensure_scores（幂等），支持取消。"""
        if self._busy:
            return
        bvids = self._selected_bvids()
        if not bvids:
            self._status.setText("还没有监控的视频呢，先添加一个再来吧 ♪")
            return

        self._busy = True
        self._cancel.clear()
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        total = len(bvids)
        self._status.setText(f"待补齐 {total} 个视频…")

        def _work():
            computed = written = 0
            done = 0
            cancelled = False
            for bvid in bvids:
                if self._cancel.is_set():
                    cancelled = True
                    break
                video_db = getattr(self.gui, "video_dbs", {}).get(bvid)
                if video_db is not None:
                    try:
                        result = ensure_scores(video_db)
                        computed += int(result.get("computed", 0))
                        written += int(result.get("written", 0))
                    except Exception as e:
                        logger.warning("分数补齐失败 %s: %s", bvid, e)
                done += 1
                invoke(lambda d=done, w=written: self._status.setText(f"待补齐 {d}/{total} · 已写入 {w}"))

            invoke(lambda: self._finish_materialize(computed, written, cancelled))

        fire_and_forget(_work, name="score-center-materialize")

    def _cancel_materialize(self):
        """请求取消（当前视频跑完即停）。"""
        self._cancel.set()
        self._status.setText("正在取消…（当前视频完成后停止）")

    def _finish_materialize(self, computed: int, written: int, cancelled: bool):
        """补齐结束：清缓存并重新渲染。"""
        self._busy = False
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._cache.clear()
        tail = "已取消" if cancelled else "完成"
        self._status.setText(f"{tail} · 待补齐 {computed} · 已写入 {written} · 分数按需计算 · 趋势按小时归档")
        self._on_selection_changed()

    # ── 生命周期 ─────────────────────────────────────────

    def show(self):
        """显示窗口（会把 fps 刷新到最新监控列表）。"""
        self._reload_videos()
        self._on_selection_changed()
        self.dlg.show()


_window_ref = None  # 模块级单例


def open_score_center(gui):
    """打开（或前置）周/年分数中心；重复调用只保留一个窗口。"""
    global _window_ref
    if _window_ref is None:
        _window_ref = ScoreCenterWindow(gui, gui)
    else:
        _window_ref.gui = gui
    _window_ref.show()
    _window_ref.dlg.raise_()
    _window_ref.dlg.activateWindow()
    return _window_ref


__all__ = [
    "RANGE_OPTIONS",
    "ScoreCenterWindow",
    "filter_rows",
    "format_score_row",
    "load_scores",
    "open_score_center",
    "range_cutoff",
    "sort_rows_ascending",
]
