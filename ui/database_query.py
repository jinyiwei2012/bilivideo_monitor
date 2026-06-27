"""
现代化数据库查询界面 — PyQt6 版
"""

import csv
import logging
import os
import sqlite3
import threading
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QMessageBox, QFileDialog, QStackedWidget,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QAction, QIcon

from ui.theme import C
from ui.helpers import FONT, FONT_SM, project_path, is_valid_bvid
from ui.invoker import invoke
from ui.dialog_base import DialogBase
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)

_BASE_EXPORT_HEADERS = [
    "序号", "BV号", "时间", "播放量", "点赞", "投币", "分享", "收藏",
    "弹幕", "评论", "APP观看", "网页观看", "总观看", "播赞比",
    "周刊总分", "周刊播放", "周刊互动", "周刊收藏", "周刊硬币", "周刊点赞",
    "周刊修正A", "周刊修正B", "周刊修正C", "周刊修正D", "周刊基础播放",
    "年刊总分", "年刊播放", "年刊互动", "年刊收藏", "年刊硬币", "年刊点赞",
    "年刊修正A", "年刊修正B", "年刊修正C",
]


def _build_export_headers(algo_names: list) -> list:
    headers = list(_BASE_EXPORT_HEADERS)
    for name in algo_names:
        headers.append(f"{name}_预测时间")
        headers.append(f"{name}_预测秒数")
        headers.append(f"{name}_置信度")
    return headers


def _build_export_row(index: int, row, extra: Optional[dict] = None, algo_names: Optional[list] = None) -> list:
    e = extra or {}
    algo_names = algo_names or []
    if hasattr(row, "keys"):
        row = dict(row)
    algo_pred_map = {}
    for pred in e.get("_predictions", []):
        algo = pred.get("algorithm", "")
        if algo not in algo_pred_map:
            algo_pred_map[algo] = pred

    base_row = [
        index, row["bvid"], row["timestamp"],
        row["view_count"], row["like_count"], row["coin_count"],
        row["share_count"], row["favorite_count"],
        row["danmaku_count"], row["reply_count"],
        row.get("viewers_app", "") or "",
        row.get("viewers_web", "") or "",
        row.get("viewers_total", "") or "",
        row.get("like_view_ratio", "") or "",
        e.get("weekly_total", ""), e.get("weekly_view", ""),
        e.get("weekly_interaction", ""), e.get("weekly_favorite", ""),
        e.get("weekly_coin", ""), e.get("weekly_like", ""),
        e.get("weekly_corr_a", ""), e.get("weekly_corr_b", ""),
        e.get("weekly_corr_c", ""), e.get("weekly_corr_d", ""),
        e.get("weekly_base_view", ""),
        e.get("yearly_total", ""), e.get("yearly_view", ""),
        e.get("yearly_interaction", ""), e.get("yearly_favorite", ""),
        e.get("yearly_coin", ""), e.get("yearly_like", ""),
        e.get("yearly_corr_a", ""), e.get("yearly_corr_b", ""),
        e.get("yearly_corr_c", ""),
    ]
    for name in algo_names:
        pred = algo_pred_map.get(name, {})
        base_row.append(pred.get("predicted_time", ""))
        base_row.append(pred.get("predicted_seconds", ""))
        base_row.append(pred.get("confidence", ""))
    return base_row


class _ParamPage(QWidget):
    """参数输入行页面"""
    def __init__(self, label: str, default: str, hint: str):
        super().__init__()
        self.entry = QLineEdit(default)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(label)
        lbl.setFont(FONT)
        lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        layout.addWidget(lbl)
        self.entry.setFont(FONT)
        self.entry.setFixedWidth(120)
        self.entry.setStyleSheet(f"""
            QLineEdit {{ background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px; }}
        """)
        layout.addWidget(self.entry)
        h = QLabel(hint)
        h.setFont(FONT_SM)
        h.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        layout.addWidget(h)
        layout.addStretch()


class _DeleteFinishSignal(QWidget):
    """删除线程回调信号"""
    finished = pyqtSignal(object, int)  # del_data, count


class DatabaseQueryWindow(DialogBase):
    """数据库查询窗口 — PyQt6 版"""

    _query_complete = pyqtSignal(object, object, object)  # raw_rows, extra_list, algo_names
    _status_update = pyqtSignal(str)
    _delete_finished = pyqtSignal(object, int)  # del_data, count

    def __init__(self, parent):
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        super().__init__(parent, "数据库查询", (int(sw * 0.54), int(sh * 0.72)), modal=False)

        self.db_path = project_path("data", "bilibili_monitor.db")
        self.query_results: List[Dict] = []
        self._extra_data: List[Dict] = []
        self._algo_names: List[str] = []
        self._query_running = False
        self._query_source_bvid: Optional[str] = None
        self._video_bvid_map: Dict[str, str] = {}
        # 保持线程引用
        self._threads: List[threading.Thread] = []

        self._query_complete.connect(self._finish_query)
        self._status_update.connect(self._update_status)
        self._delete_finished.connect(self._finish_delete)

        self._setup_ui()
        self._load_videos_list()

    def _setup_ui(self):
        self.header("数据库查询", "查询监控记录、播放趋势与算法预测数据")

        # ── 查询条件卡片 ──
        sec = self.section(padding=6)
        sec_layout = sec.layout()

        # 视频筛选
        filter_row = QWidget()
        filter_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 2, 0, 2)

        lbl1 = QLabel("视频筛选")
        lbl1.setFont(FONT)
        lbl1.setStyleSheet(f"color: {C['text_2']};")
        lbl1.setFixedWidth(80)
        filter_layout.addWidget(lbl1)

        self._filter_combo = QComboBox()
        self._filter_combo.setMinimumWidth(300)
        self._filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        filter_layout.addWidget(self._filter_combo)

        if sec_layout is not None:
            sec_layout.addWidget(filter_row)

        # 查询方式
        mode_row = QWidget()
        mode_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 2, 0, 2)

        lbl2 = QLabel("查询方式")
        lbl2.setFont(FONT)
        lbl2.setStyleSheet(f"color: {C['text_2']};")
        lbl2.setFixedWidth(80)
        mode_layout.addWidget(lbl2)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["最新N条", "播放首次大于X", "播放量大于X", "播放趋势", "全量数据"])
        self._mode_combo.setMinimumWidth(160)
        self._mode_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self._mode_combo)

        if sec_layout is not None:
            sec_layout.addWidget(mode_row)

        # 参数行（QStackedWidget 动态切换）
        self._param_stack = QStackedWidget()
        self._param_stack.setStyleSheet(f"background-color: {C['bg_elevated']};")

        # 0: 最新N条
        self._param_page_latest = self._make_param("数量N:", "100", "(要查询的记录数)")
        self._param_stack.addWidget(self._param_page_latest)

        # 1: 播放首次大于X
        self._param_page_first = self._make_param("播放量X:", "10000", "(每视频首次超过X的记录)")
        self._param_stack.addWidget(self._param_page_first)

        # 2: 播放量大于X
        self._param_page_above = self._make_param("播放量X:", "10000", "(所有播放量超过X的记录)")
        self._param_stack.addWidget(self._param_page_above)

        # 3: 播放趋势（带视频选择）
        self._param_page_trend = QWidget()
        trend_layout = QHBoxLayout(self._param_page_trend)
        trend_layout.setContentsMargins(0, 2, 0, 2)
        lbl3 = QLabel("选择视频:")
        lbl3.setFont(FONT)
        lbl3.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        trend_layout.addWidget(lbl3)
        self._trend_combo = QComboBox()
        self._trend_combo.setMinimumWidth(280)
        self._trend_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        trend_layout.addWidget(self._trend_combo)
        trend_layout.addStretch()
        self._param_stack.addWidget(self._param_page_trend)

        # 4: 全量数据
        self._param_page_all = QWidget()
        all_layout = QHBoxLayout(self._param_page_all)
        all_layout.setContentsMargins(0, 2, 0, 2)
        lbl4 = QLabel("(将导出所有监控记录数据)")
        lbl4.setFont(FONT_SM)
        lbl4.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        all_layout.addWidget(lbl4)
        all_layout.addStretch()
        self._param_stack.addWidget(self._param_page_all)

        if sec_layout is not None:
            sec_layout.addWidget(self._param_stack)

        # 按钮行
        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 6, 0, 0)

        self._query_btn = QPushButton("查询")
        self._query_btn.setProperty("primary", True)
        style = self._query_btn.style()
        if style is not None:
            style.unpolish(self._query_btn)
            style.polish(self._query_btn)
        self._query_btn.clicked.connect(self._do_query)
        btn_layout.addWidget(self._query_btn)

        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self._reset_query)
        btn_layout.addWidget(reset_btn)

        btn_layout.addStretch()
        if sec_layout is not None:
            sec_layout.addWidget(btn_row)

        self._on_mode_changed("最新N条")

        # ── 结果区域 ──
        res_header = QWidget()
        res_header.setStyleSheet(f"background-color: {C['bg_base']};")
        res_header_layout = QHBoxLayout(res_header)
        res_header_layout.setContentsMargins(0, 0, 0, 0)

        res_title = QLabel("查询结果")
        res_title.setFont(QFont("Microsoft YaHei UI", 8, QFont.Weight.Bold))
        res_title.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        res_header_layout.addWidget(res_title)

        res_header_layout.addStretch()

        self._status_display = QLabel("就绪")
        self._status_display.setFont(FONT_SM)
        self._status_display.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        res_header_layout.addWidget(self._status_display)

        self._main_layout.addWidget(res_header)

        # 结果表格
        col_specs = [
            ("seq", "序号", 50), ("bv", "BV号", 120), ("timestamp", "时间", 150),
            ("views", "播放量", 90), ("likes", "点赞", 75), ("coins", "投币", 75),
            ("shares", "分享", 75), ("favorites", "收藏", 75), ("danmaku", "弹幕", 75),
            ("reply", "评论", 75), ("viewers_total", "总在线", 75),
            ("viewers_web", "Web在线", 75), ("viewers_app", "APP在线", 75),
            ("like_ratio", "播赞比", 75),
        ]
        self._result_tree = QTreeWidget()
        self._result_tree.setHeaderLabels([h for _, h, _ in col_specs])
        self._result_tree.setRootIsDecorated(False)
        self._result_tree.setAlternatingRowColors(False)
        self._result_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border_sub']}; font-size: 9pt;
            }}
            QTreeWidget::item:selected {{
                background-color: {C['bilibili']}; color: white;
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']}; color: {C['text_2']};
                border: 1px solid {C['border_sub']}; padding: 2px 6px;
                font-weight: bold;
            }}
        """)
        header = self._result_tree.header()
        if header is not None:
            for i, (_, _, w) in enumerate(col_specs):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._result_tree.setColumnWidth(i, w)

        self._main_layout.addWidget(self._result_tree, 1)

        # 底部操作按钮
        bottom = QWidget()
        bottom.setStyleSheet(f"background-color: {C['bg_surface']};")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 8, 0, 0)

        csv_btn = QPushButton("导出CSV")
        csv_btn.clicked.connect(self._export_csv)
        bottom_layout.addWidget(csv_btn)

        xls_btn = QPushButton("导出Excel")
        xls_btn.clicked.connect(self._export_excel)
        bottom_layout.addWidget(xls_btn)

        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(lambda: _confirm_risky("删除数据库记录") and self._delete_selected())
        bottom_layout.addWidget(del_btn)

        clear_btn = QPushButton("清空结果")
        clear_btn.clicked.connect(self._clear_results)
        bottom_layout.addWidget(clear_btn)

        bottom_layout.addStretch()
        self._main_layout.addWidget(bottom)

    def _make_param(self, label: str, default: str, hint: str) -> _ParamPage:
        """创建简洁的参数输入行"""
        return _ParamPage(label, default, hint)

    def _get_param_value(self, default: str = "100") -> str:
        """获取当前参数页的输入值"""
        w = self._param_stack.currentWidget()
        if isinstance(w, _ParamPage) and w.entry:
            return w.entry.text().strip()
        return default

    def _on_mode_changed(self, text: str):
        """查询模式切换"""
        idx_map = {
            "最新N条": 0, "播放首次大于X": 1, "播放量大于X": 2,
            "播放趋势": 3, "全量数据": 4,
        }
        idx = idx_map.get(text, 0)
        self._param_stack.setCurrentIndex(idx)

        # 播放趋势模式下同步视频列表到趋势下拉框
        if idx == 3:
            self._sync_trend_combo()

    def _sync_trend_combo(self):
        """同步视频列表到趋势下拉框"""
        self._trend_combo.clear()
        for item_text in self._video_bvid_map:
            self._trend_combo.addItem(item_text)
        if self._trend_combo.count() > 0:
            self._trend_combo.setCurrentIndex(0)

    def _get_filter_bvid(self) -> Optional[str]:
        sel = self._filter_combo.currentText()
        if sel == "全部视频" or not sel:
            return None
        return self._video_bvid_map.get(sel)

    def _get_video_db_path(self, bvid: str) -> Optional[str]:
        if not is_valid_bvid(bvid):
            return None
        primary = os.path.join(os.path.dirname(self.db_path), bvid, f"{bvid}.db")
        if os.path.exists(primary):
            return primary
        backup = project_path("core", "data", bvid, f"{bvid}.db")
        return backup if os.path.exists(backup) else None

    def _load_extra_data(self, bvid: str, timestamp: str) -> dict:
        extra = {}
        vdp = self._get_video_db_path(bvid)
        if not vdp:
            return extra
        conn = None
        try:
            uri = "file:{}?mode=ro".format(urllib.parse.quote(vdp.replace("\\", "/"), safe="/:"))
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM predictions WHERE created_at <= ? ORDER BY algorithm, created_at DESC",
                (timestamp,)
            )
            pred_rows = cur.fetchall()
            seen = set()
            pred_list = []
            for pr in pred_rows:
                an = pr["algorithm"]
                if an not in seen:
                    seen.add(an)
                    pred_list.append(dict(pr))
            extra["_predictions"] = pred_list

            cur.execute(
                "SELECT * FROM weekly_scores WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
                (timestamp,)
            )
            ws = cur.fetchone()
            if ws:
                wd = dict(ws)
                for k in ["total_score", "view_score", "interaction_score",
                           "favorite_score", "coin_score", "like_score",
                           "correction_a", "correction_b", "correction_c",
                           "correction_d", "base_view_score"]:
                    extra[f"weekly_{k}"] = wd.get(k, "")

            cur.execute(
                "SELECT * FROM yearly_scores WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
                (timestamp,)
            )
            ys = cur.fetchone()
            if ys:
                yd = dict(ys)
                for k in ["total_score", "view_score", "interaction_score",
                           "favorite_score", "coin_score", "like_score",
                           "correction_a", "correction_b", "correction_c"]:
                    extra[f"yearly_{k}"] = yd.get(k, "")
        except Exception as e:
            logger.debug("查询视频额外数据失败: %s", e)
        finally:
            if conn:
                conn.close()
        return extra

    def _load_videos_list(self):
        """从中央数据库加载视频列表"""
        if not os.path.exists(self.db_path):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT bvid, title FROM videos ORDER BY updated_at DESC")
            videos = cur.fetchall()
            conn.close()

            items = ["全部视频"]
            self._video_bvid_map = {}
            for v in videos:
                d = f"{v['bvid']} - {v['title']}"
                items.append(d)
                self._video_bvid_map[d] = v["bvid"]

            self._filter_combo.clear()
            self._filter_combo.addItems(items)
        except Exception as e:
            logger.debug("加载视频列表失败: %s", e)

    def _do_query(self):
        """启动查询"""
        if not os.path.exists(self.db_path):
            QMessageBox.critical(self, "错误", "数据库文件不存在")
            return
        if self._query_running:
            return

        mode = self._mode_combo.currentText()
        filter_bvid = self._get_filter_bvid()
        bvid_for_trend = None

        if mode == "播放趋势":
            sel = self._trend_combo.currentText()
            if not sel:
                if filter_bvid:
                    bvid_for_trend = filter_bvid
                else:
                    QMessageBox.warning(self, "提示", "请选择视频")
                    return
            else:
                bvid_for_trend = sel.split()[0] if " " in sel else sel
                if filter_bvid:
                    bvid_for_trend = filter_bvid
            if not is_valid_bvid(bvid_for_trend):
                QMessageBox.critical(self, "错误", "选中视频的BV号格式无效")
                return

        self._query_running = True
        self._query_btn.setEnabled(False)
        self._query_btn.setText("查询中…")
        self._result_tree.clear()
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self._update_status("查询中…")

        t = threading.Thread(
            target=self._run_fallback_query,
            args=(mode, filter_bvid, bvid_for_trend),
            daemon=True,
        )
        self._threads.append(t)
        t.start()

    def _query_video_db(self, bvid: str, mode: str) -> list:
        vdp = self._get_video_db_path(bvid)
        if not vdp:
            return []
        uri = "file:{}?mode=ro".format(urllib.parse.quote(vdp.replace("\\", "/"), safe="/:"))
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            rows = self._run_video_query(cur, mode)
        finally:
            conn.close()
        result = [dict(r) for r in rows]
        for row in result:
            row.setdefault("bvid", bvid)
        return result

    @staticmethod
    def _get_param_int(widget, default: int) -> int:
        if hasattr(widget, '_param_entry'):
            raw = widget._param_entry.text().strip()
            if raw.isdigit():
                return int(raw)
        return default

    def _run_video_query(self, cur, mode: str) -> list:
        if mode == "最新N条":
            limit = self._get_param_int(self._param_stack.widget(0), 100)
            cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT ?", (limit,))
        elif mode == "播放首次大于X":
            thr = self._get_param_int(self._param_stack.widget(1), 10000)
            cur.execute("SELECT * FROM monitor_records WHERE view_count > ? ORDER BY timestamp ASC LIMIT 1", (thr,))
        elif mode == "播放量大于X":
            thr = self._get_param_int(self._param_stack.widget(2), 10000)
            cur.execute("SELECT * FROM monitor_records WHERE view_count > ? ORDER BY timestamp DESC", (thr,))
        elif mode == "播放趋势":
            cur.execute("SELECT * FROM monitor_records ORDER BY timestamp ASC")
        elif mode == "全量数据":
            cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC")
        return cur.fetchall()

    def _run_fallback_query(self, mode, filter_bvid, bvid_for_trend):
        raw_rows = self._query_central_db(mode, filter_bvid, bvid_for_trend)
        if raw_rows is None:
            return
        self._status_update.emit(f"中央库查到 {len(raw_rows)} 条，加载关联数据…")
        try:
            extra_list, anames = self._load_query_extra_data(raw_rows)
        except Exception as e:
            logger.exception("加载关联数据失败")
            self._status_update.emit(f"加载关联数据失败: {e}")
            self._reset_query_state()
            return
        self._query_source_bvid = None
        self._query_complete.emit(raw_rows, extra_list, anames)

    def _query_central_db(self, mode, filter_bvid, bvid_for_trend):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            raw_rows = self._run_query(cur, mode, filter_bvid, bvid_for_trend)
            conn.close()
            return raw_rows
        except Exception as e:
            QMessageBox.critical(self, "错误", f"中央库查询失败: {e}")
            self._reset_query_state()
            return None

    def _run_query(self, cur, mode, filter_bvid, bvid_for_trend):
        if mode == "最新N条":
            limit = self._get_param_int(self._param_stack.widget(0), 100)
            if filter_bvid:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp DESC LIMIT ?",
                    (filter_bvid, limit),
                )
            else:
                cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC LIMIT ?", (limit,))
        elif mode == "播放首次大于X":
            thr = self._get_param_int(self._param_stack.widget(1), 10000)
            if filter_bvid:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? AND view_count > ? ORDER BY timestamp ASC LIMIT 1",
                    (filter_bvid, thr),
                )
            else:
                cur.execute("""
                    WITH fa AS (
                        SELECT bvid, MIN(timestamp) as ft
                        FROM monitor_records WHERE view_count > ? GROUP BY bvid
                    )
                    SELECT m.* FROM monitor_records m
                    INNER JOIN fa f ON m.bvid = f.bvid AND m.timestamp = f.ft
                    ORDER BY m.timestamp DESC
                """, (thr,))
        elif mode == "播放量大于X":
            thr = self._get_param_int(self._param_stack.widget(2), 10000)
            if filter_bvid:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? AND view_count > ? ORDER BY timestamp DESC",
                    (filter_bvid, thr),
                )
            else:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE view_count > ? ORDER BY timestamp DESC",
                    (thr,),
                )
        elif mode == "播放趋势":
            cur.execute(
                "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp ASC",
                (bvid_for_trend,),
            )
        elif mode == "全量数据":
            if filter_bvid:
                cur.execute(
                    "SELECT * FROM monitor_records WHERE bvid = ? ORDER BY timestamp DESC",
                    (filter_bvid,),
                )
            else:
                cur.execute("SELECT * FROM monitor_records ORDER BY timestamp DESC")
        return [dict(r) for r in cur.fetchall()]

    def _load_query_extra_data(self, raw_rows):
        extra_list = []
        all_an = set()
        total = len(raw_rows)
        batch = max(1, total // 20)
        for idx, row in enumerate(raw_rows):
            extra = self._load_extra_data(row["bvid"], row["timestamp"])
            extra_list.append(extra)
            for pred in extra.get("_predictions", []):
                all_an.add(pred.get("algorithm", ""))
            if total > 50 and (idx + 1) % batch == 0:
                self._status_update.emit(f"加载关联数据 {idx + 1}/{total}…")
        known = ["线性增长", "移动平均", "加权移动平均", "指数平滑", "趋势外推", "Gompertz"]
        anames = sorted(all_an, key=lambda n: (known.index(n) if n in known else len(known), n))
        return extra_list, anames

    def _reset_query_state(self):
        self._query_running = False
        self._query_source_bvid = None
        self._query_btn.setEnabled(True)
        self._query_btn.setText("查询")

    def _update_status(self, text: str):
        self._status_display.setText(text)

    def _finish_query(self, raw_rows, extra_list, algo_names):
        self.query_results = raw_rows
        self._extra_data = extra_list
        self._algo_names = algo_names
        self._result_tree.clear()

        try:
            for i, row in enumerate(raw_rows, 1):
                lr = row.get("like_view_ratio") or 0
                item = QTreeWidgetItem()
                data = [
                    str(i),
                    row.get("bvid", ""),
                    row.get("timestamp", ""),
                    self._safe_fmt(row.get("view_count")),
                    self._safe_fmt(row.get("like_count")),
                    self._safe_fmt(row.get("coin_count")),
                    self._safe_fmt(row.get("share_count")),
                    self._safe_fmt(row.get("favorite_count")),
                    self._safe_fmt(row.get("danmaku_count")),
                    self._safe_fmt(row.get("reply_count")),
                    self._safe_fmt(row.get("viewers_total")),
                    self._safe_fmt(row.get("viewers_web")),
                    self._safe_fmt(row.get("viewers_app")),
                    f"{lr:.4f}",
                ]
                for ci, txt in enumerate(data):
                    item.setText(ci, txt)
                    item.setTextAlignment(ci, Qt.AlignmentFlag.AlignCenter)
                    item.setTextAlignment(1, Qt.AlignmentFlag.AlignLeft)
                self._result_tree.addTopLevelItem(item)
            self._update_status(f"查询到 {len(raw_rows)} 条记录")
        except Exception as e:
            logger.exception("显示查询结果失败")
            self._update_status(f"显示结果失败: {e}")
        self._reset_query_state()

    @staticmethod
    def _safe_fmt(v):
        if v is None:
            return "0"
        try:
            return f"{int(v):,}"
        except (ValueError, TypeError):
            return str(v)

    def _reset_query(self):
        self._result_tree.clear()
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self._update_status("就绪")

    def _get_export_default_name(self, ext: str) -> str:
        mode = self._mode_combo.currentText()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fb = self._get_filter_bvid()
        tag = f"_{fb}" if fb else ""
        mn = {
            "最新N条": "latest",
            "播放首次大于X": f"first_above{self._get_param_value('0')}",
            "播放量大于X": f"above{self._get_param_value('0')}",
            "播放趋势": self._trend_combo.currentText().split()[0] if self._trend_combo.currentText() else "trend",
            "全量数据": "all",
        }.get(mode, "query")
        return f"{mn}{tag}_{ts}.{ext}"

    def _export_csv(self):
        if not self.query_results:
            QMessageBox.warning(self, "提示", "没有可导出的数据")
            return
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出CSV", self._get_export_default_name("csv"),
            "CSV文件 (*.csv);;所有文件 (*.*)",
        )
        if not fp:
            return
        try:
            hd = _build_export_headers(self._algo_names)
            with open(fp, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(hd)
                el = getattr(self, "_extra_data", [])
                for i, row in enumerate(self.query_results, 1):
                    extra = el[i - 1] if i - 1 < len(el) else None
                    w.writerow(_build_export_row(i, row, extra, self._algo_names))
            QMessageBox.information(self, "成功", f"已导出到:\n{fp}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def _export_excel(self):
        if not self.query_results:
            QMessageBox.warning(self, "提示", "没有可导出的数据")
            return
        try:
            import openpyxl  # type: ignore[import-untyped]
        except ImportError:
            QMessageBox.critical(self, "错误", "需要安装 openpyxl 库\n请运行: pip install openpyxl")
            return
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出Excel", self._get_export_default_name("xlsx"),
            "Excel文件 (*.xlsx);;所有文件 (*.*)",
        )
        if not fp:
            return
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "查询结果"
            ws.append(_build_export_headers(self._algo_names))
            el = getattr(self, "_extra_data", [])
            for i, row in enumerate(self.query_results, 1):
                extra = el[i - 1] if i - 1 < len(el) else None
                ws.append(_build_export_row(i, row, extra, self._algo_names))
            for col in ws.columns:
                ml = max((len(str(c.value)) for c in col if c.value is not None), default=0)
                ws.column_dimensions[col[0].column_letter].width = min(ml + 2, 50)
            wb.save(fp)
            QMessageBox.information(self, "成功", f"已导出到:\n{fp}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def _delete_selected(self):
        sel = self._result_tree.selectedItems()
        if not sel:
            QMessageBox.warning(self, "提示", "请先选择要删除的记录")
            return

        reply = QMessageBox.question(
            self, "确认", f"确定删除选中的 {len(sel)} 条记录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        source_bvid = self._query_source_bvid
        if source_bvid:
            db_path = self._get_video_db_path(source_bvid)
            if not db_path:
                QMessageBox.critical(self, "错误", "视频独立库文件不存在")
                return
        else:
            db_path = self.db_path

        del_data = []
        for item in sel:
            vals = [item.text(i) for i in range(self._result_tree.columnCount())]
            del_data.append((vals[1], vals[2]))

        def _do_delete():
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                for bvid, ts in del_data:
                    if source_bvid:
                        cur.execute("DELETE FROM monitor_records WHERE timestamp = ?", (ts,))
                    else:
                        cur.execute(
                            "DELETE FROM monitor_records WHERE bvid = ? AND timestamp = ?",
                            (bvid, ts),
                        )
                conn.commit()
                conn.close()
                self._delete_finished.emit(del_data, len(sel))
            except Exception as e:
                invoke(lambda err=str(e): QMessageBox.critical(self, "错误", f"删除失败: {err}"))

        self._finish_delete_signal = _DeleteFinishSignal()
        self._finish_delete_signal.finished.connect(self._finish_delete)
        self._update_status(f"正在删除 {len(sel)} 条记录…")
        t = threading.Thread(target=_do_delete, daemon=True)
        self._threads.append(t)
        t.start()

    def _finish_delete(self, del_data: list, count: int):
        for bvid, ts in del_data:
            self.query_results = [
                r for r in self.query_results
                if not (r["bvid"] == bvid and r["timestamp"] == ts)
            ]
        self._do_query()
        self._update_status(f"已删除 {count} 条记录")

    def _clear_results(self):
        self._result_tree.clear()
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self._update_status("已清空结果")


# 辅助信号类用于删除线程回调
class _DeleteFinishSignal(QWidget):
    finished = pyqtSignal(object, int)  # del_data, count
