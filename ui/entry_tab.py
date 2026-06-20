"""
数据录入标签页 - 里程碑/快照数据录入 (PyQt6 版)
"""

import logging
from typing import List, Dict
from decimal import Decimal

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QRadioButton, QCheckBox, QLineEdit,
    QComboBox, QTreeWidget, QTreeWidgetItem, QTabWidget,
    QGroupBox, QMessageBox, QFrame, QHeaderView, QMenu,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QCursor

from core.database import get_db
from ui.theme import C
from ui.scrollable_frame import ScrollableFrame
from .data_comparison import _fmt, _parse_dt
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)

_ENTRY_FIELDS = [
    ("view_count", "播放量*", True),
    ("like_count", "点赞", False),
    ("coin_count", "硬币", False),
    ("share_count", "分享", False),
    ("favorite_count", "收藏", False),
    ("danmaku_count", "弹幕", False),
    ("reply_count", "评论", False),
    ("note", "备注", False),
]


class EntryTab(QWidget):
    """数据录入标签页 (PyQt6 版)"""

    def __init__(self, parent, monitored_videos, video_dbs, on_add_monitor):
        super().__init__(parent)
        self._monitored_videos = monitored_videos
        self._video_dbs = video_dbs
        self._on_add_monitor = on_add_monitor

        self._mode = "milestone"  # "milestone" | "snapshot"
        self._ms_checks: Dict[str, bool] = {}
        self._snap_dt = ""
        self._rows: List[dict] = []
        self._monitored_set = {v.get("bvid", "") for v in self._monitored_videos}

        self._bvid_text: QPlainTextEdit = QPlainTextEdit()
        self._snap_combo: QComboBox = QComboBox()
        self._container: QWidget = QWidget()
        self._tbl: QTreeWidget = QTreeWidget()
        self._status: QLabel = QLabel(
            "选择录入模式，输入 BV 号后点击「生成输入表」"
        )
        self._ms_frame: QWidget = QWidget()
        self._snap_frame: QWidget = QWidget()
        self._dt_entry: QLineEdit = QLineEdit()

        self._build()
        QTimer.singleShot(50, self._reload_table)

    # ── UI 构建 ──
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        # ── Mode bar ──
        mode_bar = QWidget()
        mode_bar_layout = QHBoxLayout(mode_bar)
        mode_bar_layout.setContentsMargins(0, 0, 0, 4)

        mode_label = QLabel("录入模式：")
        mode_label.setStyleSheet("font-weight: bold;")
        mode_bar_layout.addWidget(mode_label)

        self._milestone_rb = QRadioButton("里程碑（一周/月/年）")
        self._milestone_rb.setChecked(True)
        self._milestone_rb.toggled.connect(lambda checked: self._switch_mode() if checked else None)
        self._milestone_rb.setStyleSheet(f"color: {C['text_1']}; spacing: 6px;")
        mode_bar_layout.addWidget(self._milestone_rb)

        self._snapshot_rb = QRadioButton("历史快照（指定时间点）")
        self._snapshot_rb.toggled.connect(lambda checked: self._switch_mode() if checked else None)
        self._snapshot_rb.setStyleSheet(f"color: {C['text_1']}; spacing: 6px;")
        mode_bar_layout.addWidget(self._snapshot_rb)

        mode_bar_layout.addStretch()
        layout.addWidget(mode_bar)

        # ── Input area (top half) ──
        input_area = QWidget()
        input_layout = QHBoxLayout(input_area)
        input_layout.setContentsMargins(0, 4, 0, 4)

        # Left: BV input
        bv_box = QGroupBox("BV号（每行一个，可批量）")
        bv_box.setStyleSheet(f"""
            QGroupBox {{
                color: {C['text_1']}; font-weight: bold;
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                margin-top: 12px; padding-top: 16px;
                background-color: {C['bg_surface']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 8px;
            }}
        """)
        bv_layout = QVBoxLayout(bv_box)
        bv_layout.setContentsMargins(6, 8, 6, 6)

        self._bvid_text.setPlaceholderText("BV1xx...\nBV1yy...")
        self._bvid_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                font-family: Consolas; font-size: 10pt;
                padding: 4px;
            }}
            QPlainTextEdit:focus {{ border-color: {C['accent']}; }}
        """)
        bv_layout.addWidget(self._bvid_text, 1)

        add_mon_btn = QPushButton("从监控列表添加全部")
        add_mon_btn.clicked.connect(self._add_all_monitored)
        bv_layout.addWidget(add_mon_btn)

        input_layout.addWidget(bv_box, 2)

        # Middle: parameters
        param_box = QGroupBox("参数")
        param_box.setStyleSheet(bv_box.styleSheet())
        param_layout = QVBoxLayout(param_box)
        param_layout.setContentsMargins(6, 8, 6, 6)

        # Milestone params
        self._ms_frame = QWidget()
        ms_layout = QVBoxLayout(self._ms_frame)
        ms_layout.setContentsMargins(0, 0, 0, 0)
        ms_title = QLabel("统计周期")
        ms_title.setStyleSheet(f"font-weight: bold; color: {C['text_2']};")
        ms_layout.addWidget(ms_title)

        for p in get_db().MILESTONE_PERIODS:
            cb = QCheckBox(p)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, period=p: self._on_ms_toggle(period, checked))
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {C['text_1']}; spacing: 6px; }}
                QCheckBox::indicator {{
                    width: 16px; height: 16px;
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                    background-color: {C['bg_base']};
                }}
                QCheckBox::indicator:checked {{
                    background-color: {C['accent']};
                    border-color: {C['accent']};
                }}
            """)
            ms_layout.addWidget(cb)
            self._ms_checks[p] = True
        ms_layout.addStretch()

        # Snapshot params
        self._snap_frame = QWidget()
        snap_layout = QVBoxLayout(self._snap_frame)
        snap_layout.setContentsMargins(0, 0, 0, 0)
        snap_title = QLabel("选择日期时间")
        snap_title.setStyleSheet(f"font-weight: bold; color: {C['text_2']};")
        snap_layout.addWidget(snap_title)

        self._dt_entry.setPlaceholderText("2026-04-22 12:00")
        self._dt_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                padding: 4px 8px;
                font-family: Consolas; font-size: 9pt;
            }}
        """)
        snap_layout.addWidget(self._dt_entry)

        fmt_hint = QLabel("格式：2026-04-22 12:00")
        fmt_hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        snap_layout.addWidget(fmt_hint)

        combo_hint = QLabel("\n或从下拉选已有时间点：")
        combo_hint.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt;")
        snap_layout.addWidget(combo_hint)

        self._snap_combo = QComboBox()
        self._snap_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']};
                border-radius: {C['radius_sm']}px;
                padding: 4px 8px;
            }}
        """)
        self._snap_combo.currentTextChanged.connect(self._on_snap_combo_select)
        snap_layout.addWidget(self._snap_combo)

        snap_layout.addStretch()

        param_layout.addWidget(self._ms_frame)
        param_layout.addWidget(self._snap_frame)
        self._snap_frame.setVisible(False)

        input_layout.addWidget(param_box, 1)

        # Right: action buttons
        btn_panel = QWidget()
        btn_layout = QVBoxLayout(btn_panel)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        gen_btn = QPushButton("生成输入表")
        gen_btn.setProperty("primary", True)
        gen_btn.clicked.connect(self._generate_rows)
        btn_layout.addWidget(gen_btn)

        save_btn = QPushButton("💾 保存全部")
        save_btn.setProperty("accent", True)
        save_btn.clicked.connect(self._save_all)
        btn_layout.addWidget(save_btn)

        btn_layout.addStretch()
        input_layout.addWidget(btn_panel, 0)

        layout.addWidget(input_area)

        # ── Bottom: scrollable input rows + data table ──
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 4, 0, 0)

        inner_tabs = QTabWidget()
        inner_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {C['border']};
                border-top: none;
                background-color: {C['bg_base']};
            }}
            QTabBar::tab {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: 1px solid {C['border']};
                border-bottom: none;
                padding: 6px 16px;
                margin-right: 2px;
                border-top-left-radius: {C['radius_sm']}px;
                border-top-right-radius: {C['radius_sm']}px;
            }}
            QTabBar::tab:selected {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border-bottom-color: {C['bg_base']};
            }}
        """)
        bottom_layout.addWidget(inner_tabs)

        # Input rows tab
        tab_input = QWidget()
        tab_input_layout = QVBoxLayout(tab_input)
        tab_input_layout.setContentsMargins(0, 0, 0, 0)

        sf = ScrollableFrame(height=None, bg=C.get("bg_base", "#0d1117"))
        tab_input_layout.addWidget(sf)
        self._container = sf.inner
        inner_tabs.addTab(tab_input, "  输入行  ")

        # Data table tab
        tab_table = QWidget()
        tab_table_layout = QVBoxLayout(tab_table)
        tab_table_layout.setContentsMargins(0, 0, 0, 0)

        cols = ["bvid", "type", "time_key", "播放量", "点赞", "硬币", "收藏", "分享", "弹幕", "评论", "记录时间"]
        self._tbl.setColumnCount(len(cols))
        self._tbl.setHeaderLabels(cols)
        self._tbl.setRootIsDecorated(False)
        self._tbl.setAlternatingRowColors(False)
        self._tbl.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                border: 1px solid {C['border']};
                font-size: 9pt;
            }}
            QTreeWidget::item {{
                padding: 2px 4px;
            }}
            QTreeWidget::item:selected {{
                background-color: {C['bg_hover']};
                color: {C['text_1']};
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']};
                color: {C['text_2']};
                border: none;
                border-right: 1px solid {C['border']};
                border-bottom: 1px solid {C['border']};
                padding: 4px 8px;
                font-weight: bold;
            }}
        """)
        widths = [110, 70, 130, 80, 60, 60, 60, 60, 60, 60, 120]
        for i, w in enumerate(widths):
            self._tbl.setColumnWidth(i, w)

        tab_table_layout.addWidget(self._tbl)

        inner_tabs.addTab(tab_table, "  已录入数据  ")

        layout.addWidget(bottom, 1)

        # ── Status ──
        self._status.setStyleSheet(f"color: {C['text_2']}; padding: 2px 12px;")
        layout.addWidget(self._status)

        # ── Right-click menu on table ──
        self._tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tbl.customContextMenuRequested.connect(self._show_table_menu)

    def _show_table_menu(self, pos):
        menu = QMenu(self)
        del_action = QAction("删除选中行", self)
        del_action.triggered.connect(self._delete_selected)
        menu.addAction(del_action)
        menu.exec(self._tbl.mapToGlobal(pos))

    def _on_ms_toggle(self, period: str, checked: bool):
        self._ms_checks[period] = checked

    def _on_snap_combo_select(self, text: str):
        if text:
            self._dt_entry.setText(text)

    # ── Mode switch ──
    def _switch_mode(self):
        self._mode = "milestone" if self._milestone_rb.isChecked() else "snapshot"
        self._ms_frame.setVisible(self._mode == "milestone")
        self._snap_frame.setVisible(self._mode == "snapshot")
        if self._mode == "snapshot":
            self._refresh_snap_combo()

    def _refresh_snap_combo(self):
        ts_set = set()
        for bvid in self._video_dbs:
            try:
                for rec in self._video_dbs[bvid].get_all_records():
                    ts = str(rec.get("timestamp", ""))[:16]
                    if ts:
                        ts_set.add(ts)
            except Exception as e:
                logger.debug("刷新快照时间下拉列表失败: %s", e)
        ts_list = sorted(ts_set, reverse=True)
        self._snap_combo.clear()
        self._snap_combo.addItems(ts_list[:200])

    # ── Add all monitored ──
    def _add_all_monitored(self):
        self._bvid_text.clear()
        for v in self._monitored_videos:
            bvid = v.get("bvid", "")
            if bvid:
                self._bvid_text.appendPlainText(bvid)

    # ── BV validation ──
    @staticmethod
    def _is_valid_bvid(s: str) -> bool:
        from ui.helpers import is_valid_bvid
        return is_valid_bvid(s)

    # ── Generate rows ──
    def _generate_rows(self):
        raw = self._bvid_text.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请先输入 BV 号")
            return

        bvids, invalid = self._validate_bvids(raw)
        if not bvids:
            return

        self._prompt_add_monitor(bvids)
        mode, row_labels, periods, dt_str = self._generate_row_labels(bvids)
        if not row_labels:
            return

        # Clear old rows
        for i in reversed(range(self._container.layout().count())):
            item = self._container.layout().itemAt(i)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._rows.clear()

        # Load existing data
        existing_ms, existing_snap = self._load_existing_data(mode, bvids, dt_str)

        # Create input rows
        for bv, key in row_labels:
            self._create_single_row(bv, key, mode, existing_ms, existing_snap)

        n = len(self._rows)
        detail = (
            f"{len(periods)} 周期" if mode == "milestone" else "1 时间点"
        )
        self._status.setText(
            f"已生成 {n} 行输入（{len(bvids)} 视频 × {detail}），填写后点击「保存全部」"
        )

    def _validate_bvids(self, raw):
        bvids, invalid = [], []
        for line in raw.splitlines():
            bv = line.strip()
            if not bv:
                continue
            if self._is_valid_bvid(bv):
                if bv not in bvids:
                    bvids.append(bv)
            else:
                invalid.append(bv)
        if invalid:
            QMessageBox.warning(self, "格式错误", "以下格式不合法已跳过：\n" + "\n".join(invalid[:10]))
        return bvids, invalid

    def _prompt_add_monitor(self, bvids):
        not_monitored = [b for b in bvids if b not in self._monitored_set]
        if not_monitored:
            msg = "以下 BV 号不在监控列表：\n" + "\n".join(not_monitored[:10]) + "\n\n是否加入监控？"
            reply = QMessageBox.question(self, "加入监控", msg, QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                for bv in not_monitored:
                    if self._on_add_monitor:
                        self._on_add_monitor(bv)
                    self._monitored_set.add(bv)

    def _generate_row_labels(self, bvids):
        mode = self._mode
        periods = []
        dt_str = ""
        row_labels = []

        if mode == "milestone":
            periods = [p for p, checked in self._ms_checks.items() if checked]
            if not periods:
                QMessageBox.warning(self, "提示", "请至少选择一个周期")
                return mode, None, None, None
            for bv in bvids:
                for p in periods:
                    row_labels.append((bv, p))
        else:
            dt_str = self._dt_entry.text().strip()
            if not dt_str:
                QMessageBox.warning(self, "提示", "请填写日期时间或从下拉选择")
                return mode, None, None, None
            dt = _parse_dt(dt_str)
            if dt is None:
                QMessageBox.warning(self, "格式错误", "日期格式不正确，请使用 2026-04-22 12:00 格式")
                return mode, None, None, None
            for bv in bvids:
                row_labels.append((bv, dt_str[:16]))

        return mode, row_labels, periods, dt_str

    def _load_existing_data(self, mode, bvids, dt_str=""):
        existing_ms = {}
        if mode == "milestone":
            for row in get_db().get_milestones():
                existing_ms[(row["bvid"], row["period"])] = row

        existing_snap = {}
        if mode == "snapshot":
            for bvid in bvids:
                if bvid in self._video_dbs:
                    try:
                        for rec in self._video_dbs[bvid].get_all_records():
                            rec_ts = str(rec.get("timestamp", ""))[:16]
                            if rec_ts == dt_str[:16]:
                                existing_snap[bvid] = dict(rec)
                                break
                    except Exception as e:
                        logger.debug("加载快照数据失败: %s", e)

        return existing_ms, existing_snap

    def _create_single_row(self, bv, key, mode, existing_ms, existing_snap):
        row_frame = QWidget()
        row_frame.setStyleSheet(f"background-color: {C['bg_base']};")
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(4)

        # BV label
        bv_lbl = QLabel(bv)
        bv_lbl.setFixedWidth(100)
        bv_lbl.setStyleSheet(f"color: {C['accent']}; font-family: Consolas; font-size: 9pt; background: transparent;")
        row_layout.addWidget(bv_lbl)

        # Key label
        key_lbl = QLabel(key)
        key_lbl.setFixedWidth(120)
        key_lbl.setStyleSheet(f"color: {C['text_1']}; font-weight: bold; font-size: 9pt; background: transparent;")
        row_layout.addWidget(key_lbl)

        vars_dict = {}
        for fkey, flabel, required in _ENTRY_FIELDS:
            # Label
            lbl = QLabel(flabel + ("*" if required else ""))
            lbl.setFixedWidth(50)
            color = C.get("danger", "#f85149") if required else C.get("text_2", "#8b949e")
            lbl.setStyleSheet(f"color: {color}; font-size: 8pt; background: transparent;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(lbl)

            # Input
            entry = QLineEdit()
            w = 80 if fkey == "note" else 60
            entry.setFixedWidth(w)
            entry.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {C['bg_elevated']};
                    color: {C['text_1']};
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                    padding: 2px 4px;
                    font-family: Consolas; font-size: 9pt;
                }}
                QLineEdit:focus {{ border-color: {C['accent']}; }}
            """)

            # Prefill
            if mode == "milestone":
                existing = existing_ms.get((bv, key))
                if existing and existing.get(fkey) is not None:
                    entry.setText(str(existing[fkey]))
            else:
                existing = existing_snap.get(bv)
                if existing and existing.get(fkey) is not None:
                    entry.setText(str(existing[fkey]))

            row_layout.addWidget(entry)
            vars_dict[fkey] = entry

        row_layout.addStretch()

        # Add to scrollable container
        container_layout = self._container.layout()
        if container_layout is not None:
            container_layout.insertWidget(container_layout.count() - 1, row_frame)

        self._rows.append({
            "bvid": bv,
            "key": key,
            "vars": vars_dict,
            "mode": mode,
        })

    # ── Save all ──
    def _save_all(self):
        if not self._rows:
            QMessageBox.warning(self, "提示", "请先生成输入表")
            return

        saved = skipped = errors = 0
        for row in self._rows:
            s, sk, e = self._save_single_row(row)
            saved += s
            skipped += sk
            errors += e

        msg = f"✅ 已保存 {saved} 条"
        if skipped:
            msg += f"，跳过 {skipped} 条（播放量为空）"
        if errors:
            msg += f"，失败 {errors} 条"

        color = C.get("success", "#3fb950") if not errors else C.get("warning", "#d29922")
        self._status.setText(msg)
        self._status.setStyleSheet(f"color: {color}; padding: 2px 12px;")

        if saved:
            self._reload_table()
            QMessageBox.information(self, "保存完成", msg)

    def _save_single_row(self, row):
        vars_d = row["vars"]
        raw_view = vars_d["view_count"].text().strip().replace(",", "")
        if not raw_view:
            return (0, 1, 0)
        try:
            view_val = int(Decimal(raw_view))
        except (ValueError, ArithmeticError):
            return (0, 0, 1)

        data = {"view_count": view_val}
        for fkey in ["like_count", "coin_count", "share_count", "favorite_count", "danmaku_count", "reply_count"]:
            val = vars_d[fkey].text().strip()
            if val:
                try:
                    data[fkey] = int(float(val.replace(",", "")))
                except ValueError:
                    pass
        note = vars_d["note"].text().strip()
        if note:
            data["note"] = note

        mode = row["mode"]
        bvid = row["bvid"]

        if mode == "milestone":
            ok = get_db().upsert_milestone(bvid, row["key"], data)
        else:
            ok = self._save_snapshot_record(bvid, row["key"], data)

        return (1, 0, 0) if ok else (0, 0, 1)

    def _save_snapshot_record(self, bvid: str, ts_str: str, data: dict) -> bool:
        if bvid not in self._video_dbs:
            return False
        try:
            video_db = self._video_dbs[bvid]
            dt = _parse_dt(ts_str)
            if dt is None:
                return False
            ts_str_full = dt.strftime("%Y-%m-%d %H:%M:%S")

            from core.database import MonitorRecord

            record = MonitorRecord(
                bvid=bvid,
                timestamp=ts_str_full,
                view_count=data.get("view_count", 0),
                like_count=data.get("like_count", 0),
                coin_count=data.get("coin_count", 0),
                share_count=data.get("share_count", 0),
                favorite_count=data.get("favorite_count", 0),
                danmaku_count=data.get("danmaku_count", 0),
                reply_count=data.get("reply_count", 0),
            )
            video_db.add_monitor_record(record)
            try:
                get_db().sync_monitor_record(bvid, {
                    "timestamp": ts_str_full,
                    "view_count": data.get("view_count", 0),
                    "like_count": data.get("like_count", 0),
                    "coin_count": data.get("coin_count", 0),
                    "share_count": data.get("share_count", 0),
                    "favorite_count": data.get("favorite_count", 0),
                    "danmaku_count": data.get("danmaku_count", 0),
                    "reply_count": data.get("reply_count", 0),
                })
            except Exception as e:
                logger.debug("entry_tab 同步中央库失败 %s: %s", bvid, e)
            return True
        except Exception as e:
            logger.warning("快照写入失败 [%s]: %s", bvid, e)
            return False

    # ── Reload table ──
    def _reload_table(self):
        self._tbl.clear()
        self._tbl.setHeaderLabels(["bvid", "type", "time_key", "播放量", "点赞", "硬币", "收藏", "分享", "弹幕", "评论", "记录时间"])

        for row in get_db().get_milestones():
            item = QTreeWidgetItem(self._tbl)
            item.setText(0, row.get("bvid", ""))
            item.setText(1, "里程碑")
            item.setText(2, row.get("period", ""))
            item.setText(3, _fmt(row.get("view_count")))
            item.setText(4, _fmt(row.get("like_count")))
            item.setText(5, _fmt(row.get("coin_count")))
            item.setText(6, _fmt(row.get("favorite_count")))
            item.setText(7, _fmt(row.get("share_count")))
            item.setText(8, _fmt(row.get("danmaku_count")))
            item.setText(9, _fmt(row.get("reply_count")))
            item.setText(10, str(row.get("recorded_at", ""))[:16])

    def _delete_selected(self):
        selected = self._tbl.selectedItems()
        if not selected:
            return
        reply = QMessageBox.question(
            self, "确认", f"删除选中的 {len(selected)} 条记录？",
            QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for item in selected:
            bvid = item.text(0)
            entry_type = item.text(1)
            time_key = item.text(2)
            if entry_type == "里程碑":
                get_db().delete_milestone(bvid, time_key)
        self._reload_table()
