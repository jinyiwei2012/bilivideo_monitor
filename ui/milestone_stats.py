"""
里程碑统计窗口 — PyQt6 版
投稿一周/月/年后数据录入与对比
"""

import math
from typing import List, Dict, Optional, Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QCheckBox, QRadioButton, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QTabWidget, QMessageBox,
    QButtonGroup, QFrame, QMenu,
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QSize
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QBrush, QPen, QAction,
    QResizeEvent,
)

from core.database import get_db
from ui.theme import C
from ui.scrollable_frame import ScrollableFrame
from ui.dialog_base import DialogBase
from ui import lty_voice
from utils.update_checker import _confirm_risky
from ui.helpers import FONT, FONT_BOLD, FONT_SM, fmt_num, is_valid_bvid

PERIODS = ["1周", "1月", "1年"]
PERIOD_COLORS = {"1周": "#58a6ff", "1月": "#3fb950", "1年": "#f5a623"}
PERIOD_COLOR_OBJ = {"1周": QColor("#58a6ff"), "1月": QColor("#3fb950"), "1年": QColor("#f5a623")}
FIELDS = [
    ("view_count", "播放量", True, "必填"),
    ("like_count", "点赞数", False, ""),
    ("coin_count", "投币数", False, ""),
    ("share_count", "分享数", False, ""),
    ("favorite_count", "收藏数", False, ""),
    ("danmaku_count", "弹幕数", False, ""),
    ("reply_count", "评论数", False, ""),
    ("note", "备注", False, ""),
]
COL_KEYS = [f[0] for f in FIELDS]
COL_LABELS = ["BV号", "周期"] + [f[1] + ("*" if f[2] else "") for f in FIELDS]
COL_WIDTH = {"BV号": 80, "周期": 50, "播放量*": 100, "点赞数": 80, "投币数": 80,
              "分享数": 80, "收藏数": 80, "弹幕数": 80, "评论数": 80, "备注": 200}


class _EntryRow(QWidget):
    """单行输入控件——BV号 × 周期"""

    def __init__(self, bvid: str, period: str, existing: Optional[dict] = None):
        super().__init__()
        self.bvid = bvid
        self.period = period
        self._fields: List[QLineEdit] = []

        self.setStyleSheet(f"""
            QWidget#entryRow {{
                background-color: {C['bg_surface']};
                border: 1px solid {C['border_sub']};
                border-radius: 2px;
            }}
        """)
        self.setObjectName("entryRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)

        # BV号
        bv_lbl = QLabel(bvid)
        bv_lbl.setFont(FONT_BOLD)
        bv_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        bv_lbl.setFixedWidth(80)
        layout.addWidget(bv_lbl)

        # 周期
        p_lbl = QLabel(period)
        p_lbl.setFont(FONT_BOLD)
        p_lbl.setStyleSheet(f"color: {PERIOD_COLORS[period]}; background: transparent;")
        p_lbl.setFixedWidth(50)
        layout.addWidget(p_lbl)

        # 字段输入框
        for key, label, required, hint in FIELDS:
            val = ""
            if existing and key in existing and existing[key] is not None:
                val = str(existing[key])

            entry = QLineEdit()
            entry.setText(val)
            entry.setFont(FONT_SM)
            entry.setFixedWidth(80 if key != "note" else 180)
            entry.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {C['bg_base']}; color: {C['text_1']};
                    border: 1px solid {C['border']}; padding: 2px 4px;
                }}
            """)
            self._fields.append(entry)
            layout.addWidget(entry)

        layout.addStretch()

    def collect(self) -> Optional[dict]:
        """收集当前行的输入数据，播放量为空时返回 None"""
        raw = self._fields[0].text().strip().replace(",", "")
        if not raw:
            return None
        try:
            view = int(float(raw))
        except ValueError:
            return None
        data: Dict[str, object] = {"view_count": view}
        for i, (key, *_rest) in enumerate(FIELDS[1:]):
            val = self._fields[i + 1].text().strip()
            if key == "note":
                if val:
                    data["note"] = val
            elif val:
                try:
                    data[key] = int(float(val.replace(",", "")))
                except ValueError:
                    pass
        return data


# ═══════════════════════════════════════════════════════
#  自定义柱状图组件
# ═══════════════════════════════════════════════════════

class _CompareChart(QWidget):
    """里程碑对比柱状图 — 使用 QPainter 绘制"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Dict[str, Dict[str, dict]] = {}
        self._metric = "view_count"
        self._metric_label = "播放量"
        self._bvids: List[str] = []
        self._max_val = 1
        self._status_callback: Optional[Callable[[str], None]] = None

        self.setMinimumHeight(200)
        self.setStyleSheet(f"background-color: {C['canvas_bg']};")

    def set_data(self, data: dict, metric: str, metric_label: str, bvids: list,
                 max_val: float, status_cb: Callable[[str], None]):
        """设置数据并重绘"""
        self._data = data
        self._metric = metric
        self._metric_label = metric_label
        self._bvids = bvids
        self._max_val = max(max_val, 1)
        self._status_callback = status_cb
        if status_cb:
            status_cb(f"♪ 共 {len(bvids)} 个视频 · 展示指标: {metric_label}")
        self.update()

    def _status(self, text: str):
        if self._status_callback:
            self._status_callback(text)

    def paintEvent(self, a0):
        """QPainter 绘制入口"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        if w < 10 or h < 10:
            painter.end()
            return

        n_videos = len(self._bvids)
        if not self._data or n_videos == 0:
            self._draw_empty(painter, w, h)
            painter.end()
            return

        ML, MR, MT, MB = 70, 20, 30, 80
        ch = h - MT - MB
        if n_videos > 0:
            cw = max(w - ML - MR, n_videos * (len(PERIODS) + 1) * 18)
        else:
            cw = w - ML - MR
        self._draw_grid(painter, cw, ch, ML, MT)
        self._draw_bars(painter, cw, ch, ML, MT)
        self._draw_legend(painter, ML, MT, ch)
        self._draw_title(painter, ML, cw)

        painter.end()

    def _draw_empty(self, painter, w, h):
        """无数据提示"""
        painter.setPen(QColor(C["text_2"]))
        font = QFont("Microsoft YaHei UI", 12)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                         "还没有里程碑数据呢…像空白乐谱,去「录入数据」标签页添上第一个音符吧 ♪")

    def _draw_grid(self, painter, cw, ch, ML, MT):
        """网格线和 Y 轴标签"""
        pen = QPen(QColor(C["border"]))
        pen.setStyle(Qt.PenStyle.DashLine)
        for i in range(6):
            ratio = i / 5
            y = MT + ch - int(ch * ratio * 0.92)
            painter.setPen(pen)
            painter.drawLine(ML, y, ML + cw, y)
            val = self._max_val * ratio
            painter.setPen(QColor(C["text_2"]))
            font = QFont("Consolas", 8)
            painter.setFont(font)
            text = f"{val / 10000:.0f}w" if val >= 10000 else str(int(val))
            painter.drawText(QRectF(0, y - 8, ML - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _draw_bars(self, painter, cw, ch, ML, MT):
        """柱状图绘制"""
        n_videos = len(self._bvids)
        n_periods = len(PERIODS)
        group_w = cw / max(n_videos, 1)
        bar_total_w = group_w * 0.75
        bar_w = bar_total_w / n_periods
        gap_w = group_w * 0.125
        font_small = QFont("Consolas", 7)
        font_bold = QFont("Consolas", 7)
        font_bold.setBold(True)
        font_title = QFont("Microsoft YaHei UI", 8)

        for vi, bv in enumerate(self._bvids):
            gx = ML + vi * group_w + gap_w
            title = self._get_title(bv)
            for pi, period in enumerate(PERIODS):
                row = (self._data.get(bv) or {}).get(period) or {}
                val = row.get(self._metric)
                color = PERIOD_COLOR_OBJ[period]
                bx = int(gx + pi * bar_w)
                by = self._to_y(val, self._max_val, MT, ch) if val else MT + ch
                bx2 = int(bx + bar_w - 2)
                if val:
                    painter.setBrush(QBrush(color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(bx, by, bx2 - bx, MT + ch - by)
                    if by > MT + 14:
                        val_text = f"{val / 10000:.0f}w" if val >= 10000 else str(int(val))
                        painter.setPen(QColor(color))
                        painter.setFont(font_bold)
                        painter.drawText(QRectF(bx, by - 14, bx2 - bx, 12),
                                         Qt.AlignmentFlag.AlignCenter, val_text)
                else:
                    painter.setBrush(QBrush(QColor(C["border"])))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(bx, MT + ch - 4, bx2 - bx, 4)

            lx = int(gx + bar_total_w / 2)
            painter.setPen(QColor(C["text_1"]))
            painter.setFont(font_title)
            painter.drawText(QRectF(0, MT + ch + 2, self.width(), 16),
                             Qt.AlignmentFlag.AlignHCenter, title)
            painter.setPen(QColor(C["text_3"]))
            painter.setFont(font_small)
            painter.drawText(QRectF(0, MT + ch + 18, self.width(), 12),
                             Qt.AlignmentFlag.AlignHCenter, bv)

    def _draw_legend(self, painter, ML, MT, ch):
        """颜色图例"""
        lgx = ML + 6
        for p in PERIODS:
            painter.setBrush(QBrush(PERIOD_COLOR_OBJ[p]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(lgx, MT + ch + 52, 10, 10)
            painter.setPen(QColor(PERIOD_COLOR_OBJ[p]))
            font = QFont("Microsoft YaHei UI", 8)
            painter.setFont(font)
            painter.drawText(lgx + 14, MT + ch + 62, f"投稿{p}后")
            lgx += 90

    def _draw_title(self, painter, ML, cw):
        """图表标题"""
        painter.setPen(QColor(C["text_1"]))
        font = QFont("Microsoft YaHei UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(ML, 6, cw, 20), Qt.AlignmentFlag.AlignCenter,
                         f"♪ 投稿里程碑对比 — {self._metric_label}")

    @staticmethod
    def _get_title(bvid):
        return bvid  # caller can override via data

    @staticmethod
    def _to_y(v, max_val, MT, ch):
        if v and max_val:
            return MT + ch - int((v / max_val) * ch * 0.92)
        return MT + ch


# ═══════════════════════════════════════════════════════
#  主窗口
# ═══════════════════════════════════════════════════════

class MilestoneStatsWindow(DialogBase):
    """投稿里程碑统计与对比窗口"""

    def __init__(
        self,
        parent=None,
        monitored_videos: Optional[List[Dict]] = None,
        on_add_monitor: Optional[Callable[[str], None]] = None,
    ):
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        super().__init__(parent, "♪ 投稿里程碑 — 一周 / 月 / 年后数据",
                         (int(sw * 0.62), int(sh * 0.78)), modal=True)

        self.monitored_videos = monitored_videos or []
        self.on_add_monitor = on_add_monitor
        self._monitored_set: set = {v.get("bvid", "") for v in self.monitored_videos}
        self._entry_rows: List[_EntryRow] = []
        self._all_data: dict = {}
        self._rebuild_needed = True

        self._setup_ui()
        self._reload_comparison()

    def _setup_ui(self):
        """构建窗口 UI"""
        self.header("投稿里程碑", "天依陪你记录一周 / 月 / 年后的数据 ♪")

        self._tabs = QTabWidget()
        self._main_layout.addWidget(self._tabs)

        # 录入数据标签页
        self._tab_entry = QWidget()
        self._tab_entry.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(self._tab_entry, "  ↥ 录入数据  ")

        # 对比视图标签页
        self._tab_compare = QWidget()
        self._tab_compare.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tabs.addTab(self._tab_compare, "  ◧ 对比视图  ")

        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._build_entry_tab()
        self._build_compare_tab()

    def _on_tab_changed(self, idx: int):
        if idx == 1:
            self._reload_comparison()

    # ── 录入标签页 ──────────────────────────────────────
    def _build_entry_tab(self):
        tab = self._tab_entry
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 12, 16, 8)

        # 顶部卡片
        top = QFrame()
        top.setStyleSheet(f"""
            QFrame#entryTop {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['border_sub']};
                border-radius: 6px;
            }}
        """)
        top.setObjectName("entryTop")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(10, 8, 10, 8)

        # 左：BV号输入
        bv_col = QWidget()
        bv_col.setStyleSheet(f"background-color: {C['bg_elevated']};")
        bv_inner = QVBoxLayout(bv_col)
        bv_inner.setContentsMargins(0, 0, 0, 0)

        bv_label = QLabel("BV号（每行一个,可批量哦 ♪）")
        bv_label.setFont(FONT_SM)
        bv_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        bv_inner.addWidget(bv_label)

        self._bvid_text = QTextEdit()
        self._bvid_text.setFixedSize(220, 80)
        self._bvid_text.setFont(FONT_SM)
        self._bvid_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 4px;
            }}
        """)
        bv_inner.addWidget(self._bvid_text)

        top_layout.addWidget(bv_col)

        # 中：周期勾选
        period_col = QWidget()
        period_col.setStyleSheet(f"background-color: {C['bg_elevated']};")
        period_inner = QVBoxLayout(period_col)
        period_inner.setContentsMargins(24, 0, 0, 0)

        period_label = QLabel("统计周期")
        period_label.setFont(FONT_SM)
        period_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        period_inner.addWidget(period_label)

        self._period_checks: Dict[str, QCheckBox] = {}
        for p in PERIODS:
            cb = QCheckBox(p)
            cb.setChecked(True)
            cb.setFont(FONT_BOLD)
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {PERIOD_COLORS[p]}; background: transparent;
                }}
                QCheckBox::indicator {{
                    background-color: {C['bg_base']}; border: 1px solid {C['border']};
                }}
            """)
            self._period_checks[p] = cb
            period_inner.addWidget(cb)

        top_layout.addWidget(period_col)

        # 右：按钮
        btn_col = QWidget()
        btn_col.setStyleSheet(f"background-color: {C['bg_elevated']};")
        btn_inner = QVBoxLayout(btn_col)
        btn_inner.setContentsMargins(24, 0, 0, 0)

        gen_btn = QPushButton("生成输入表 ♪")
        gen_btn.clicked.connect(self._generate_entry_rows)
        btn_inner.addWidget(gen_btn)

        save_btn = QPushButton("⇓ 保存全部 ♪")
        save_btn.setProperty("primary", True)
        style = save_btn.style()
        if style is not None:
            style.unpolish(save_btn)
            style.polish(save_btn)
        save_btn.clicked.connect(self._save_all)
        btn_inner.addWidget(save_btn)

        top_layout.addWidget(btn_col)
        layout.addWidget(top)

        # 列头
        header = QWidget()
        header.setStyleSheet(f"background-color: {C['bg_surface']};")
        header.setFixedHeight(24)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 0, 6, 0)
        for ct in COL_LABELS:
            lbl = QLabel(ct)
            lbl.setFont(FONT_SM)
            lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            lbl.setFixedWidth(COL_WIDTH.get(ct, 80))
            header_layout.addWidget(lbl)
        header_layout.addStretch()
        layout.addWidget(header)

        # 可滚动输入行区
        self._entry_sf = ScrollableFrame(bg=C["bg_base"])
        layout.addWidget(self._entry_sf, 1)

        # 状态
        self._entry_status = QLabel("先输入 BV 号、选好周期,再点「生成输入表」,天依帮你记下来 ♪")
        self._entry_status.setFont(FONT_SM)
        self._entry_status.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        layout.addWidget(self._entry_status)

    def _generate_entry_rows(self):
        raw = self._bvid_text.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "♪ 提示", "先输入 BV 号哦,没有主角怎么开唱嘛 ♪")
            return

        bvids = self._parse_and_validate_bvids(raw)
        if not bvids:
            return

        self._prompt_not_monitored_bvids(bvids)

        periods = [p for p, cb in self._period_checks.items() if cb.isChecked()]
        if not periods:
            QMessageBox.warning(self, "♪ 提示", "至少选一个统计周期哦,一周/一月/一年都行 ♪")
            return

        self._populate_milestone_entry_rows(bvids, periods)

    def _parse_and_validate_bvids(self, raw: str) -> Optional[List[str]]:
        bvids, invalid = [], []
        for line in raw.splitlines():
            bv = line.strip()
            if not bv:
                continue
            if is_valid_bvid(bv):
                if bv not in bvids:
                    bvids.append(bv)
            else:
                invalid.append(bv)
        if invalid:
            QMessageBox.warning(self, "♪ 格式错误",
                                "呜…这几个 BV 号天依没看懂,先跳过啦:\n" + "\n".join(invalid))
        if not bvids:
            return None
        return bvids

    def _prompt_not_monitored_bvids(self, bvids):
        not_monitored = [b for b in bvids if b not in self._monitored_set]
        if not_monitored:
            msg = "这些 BV 号还没在监控列表里呢:\n" + "\n".join(not_monitored[:10])
            if len(not_monitored) > 10:
                msg += f"\n...共 {len(not_monitored)} 个"
            msg += "\n\n要把它们加入监控列表,让天依一起看着吗?♪"
            reply = QMessageBox.question(self, "加入监控 ♪", msg,
                                          QMessageBox.StandardButton.Yes |
                                          QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                for bv in not_monitored:
                    if self.on_add_monitor:
                        self.on_add_monitor(bv)
                    self._monitored_set.add(bv)

    def _populate_milestone_entry_rows(self, bvids, periods):
        self._entry_sf.clear()
        self._entry_rows.clear()

        existing_map = {}
        for row in get_db().get_milestones():
            existing_map[(row["bvid"], row["period"])] = row

        for bv in bvids:
            for p in periods:
                row_widget = _EntryRow(bv, p, existing_map.get((bv, p)))
                self._entry_sf.addWidget(row_widget)
                self._entry_rows.append(row_widget)

        total = len(self._entry_rows)
        self._entry_status.setText(
            f"♪ 共生成 {total} 行（{len(bvids)} 视频 × {len(periods)} 周期),填好后点「保存全部」哦"
        )

    def _save_all(self):
        if not self._entry_rows:
            QMessageBox.warning(self, "♪ 提示", "先点「生成输入表」哦,天依才能帮你记录 ♪")
            return
        saved = skipped = errors = 0
        for row in self._entry_rows:
            data = row.collect()
            if data is None:
                skipped += 1
                continue
            ok = get_db().upsert_milestone(row.bvid, row.period, data)
            if ok:
                saved += 1
            else:
                errors += 1
        msg = f"✓ 已保存 {saved} 条!♪"
        if skipped:
            msg += f"，跳过 {skipped} 条（播放量空空的哦）"
        if errors:
            msg += f"，呜…失败 {errors} 条"
        color = C["success"] if not errors else C["warning"]
        self._entry_status.setText(msg)
        self._entry_status.setStyleSheet(f"color: {color}; background: transparent;")
        if saved:
            self._reload_comparison()
            QMessageBox.information(self, "保存完成 ♪", msg)

    # ── 对比标签页 ──────────────────────────────────────
    def _build_compare_tab(self):
        tab = self._tab_compare
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 6, 12, 8)

        # 顶部控制栏
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background-color: {C['bg_surface']};")
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)

        ctrl_layout.addWidget(QLabel("展示指标："))
        self._metric_group = QButtonGroup(self)
        metrics = [
            ("播放量", "view_count"),
            ("点赞数", "like_count"),
            ("投币数", "coin_count"),
            ("收藏数", "favorite_count"),
            ("分享数", "share_count"),
            ("弹幕数", "danmaku_count"),
            ("评论数", "reply_count"),
        ]
        for label, val in metrics:
            rb = QRadioButton(label)
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {C['text_1']}; background: transparent;
                }}
                QRadioButton::indicator {{
                    border: 1px solid {C['border']};
                }}
            """)
            if val == "view_count":
                rb.setChecked(True)
            self._metric_group.addButton(rb)
            self._metric_group.setId(rb, hash(val))
            rb.toggled.connect(lambda checked, v=val: self._on_metric_changed() if checked else None)
            ctrl_layout.addWidget(rb)

        ctrl_layout.addStretch()
        refresh_btn = QPushButton("⟳ 刷新")
        refresh_btn.clicked.connect(self._reload_comparison)
        ctrl_layout.addWidget(refresh_btn)

        layout.addWidget(ctrl)

        # 筛选行
        ff = QWidget()
        ff.setStyleSheet(f"background-color: {C['bg_base']};")
        ff_layout = QHBoxLayout(ff)
        ff_layout.setContentsMargins(0, 4, 0, 0)

        ff_layout.addWidget(QLabel("筛选视频："))
        self._filter_entry = QLineEdit()
        self._filter_entry.setFont(FONT_SM)
        self._filter_entry.setFixedWidth(400)
        self._filter_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        ff_layout.addWidget(self._filter_entry)

        hint = QLabel("（BV号关键词,逗号分隔 ♪）")
        hint.setFont(FONT_SM)
        hint.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        ff_layout.addWidget(hint)

        filter_btn = QPushButton("应用筛选 ♪")
        filter_btn.clicked.connect(self._redraw_compare)
        ff_layout.addWidget(filter_btn)

        ff_layout.addStretch()
        layout.addWidget(ff)

        # 图表
        self._chart = _CompareChart()
        layout.addWidget(self._chart, 1)

        # 明细表
        tbl_frame = QWidget()
        tbl_frame.setStyleSheet(f"background-color: {C['bg_base']};")
        tbl_layout = QVBoxLayout(tbl_frame)
        tbl_layout.setContentsMargins(0, 8, 0, 0)

        tbl_title = QLabel("明细数据 ♪")
        tbl_title.setFont(FONT_SM)
        tbl_title.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        tbl_layout.addWidget(tbl_title)

        cols = ("bvid", "标题", "1周播放", "1月播放", "1年播放", "1周点赞", "1月点赞", "1年点赞", "记录时间")
        self._tbl = QTreeWidget()
        self._tbl.setHeaderLabels(cols)
        self._tbl.setRootIsDecorated(False)
        self._tbl.setFixedHeight(120)
        self._tbl.setStyleSheet(f"""
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
            }}
        """)
        header = self._tbl.header()
        if header is not None:
            col_widths = [110, 220, 80, 80, 80, 70, 70, 70, 130]
            for i, w in enumerate(col_widths):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self._tbl.setColumnWidth(i, w)

        # 右键菜单 — 删除
        self._tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tbl.customContextMenuRequested.connect(self._on_tbl_right_click)

        tbl_layout.addWidget(self._tbl)
        layout.addWidget(tbl_frame)

        self._cmp_status = QLabel("")
        self._cmp_status.setFont(FONT_SM)
        self._cmp_status.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        layout.addWidget(self._cmp_status)

        self._current_metric = "view_count"

    def _on_metric_changed(self):
        self._current_metric = next(
            (v for label, v in [
                ("播放量", "view_count"), ("点赞数", "like_count"),
                ("投币数", "coin_count"), ("收藏数", "favorite_count"),
                ("分享数", "share_count"), ("弹幕数", "danmaku_count"),
                ("评论数", "reply_count"),
            ] if self._metric_group.checkedButton() and
               self._metric_group.id(self._metric_group.checkedButton()) == hash(v)
            ),
            "view_count"
        )
        self._redraw_compare()

    def _on_tbl_right_click(self, pos):
        item = self._tbl.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
                      border: 1px solid {C['border']}; padding: 4px; }}
            QMenu::item {{ padding: 6px 28px; font-size: 9pt; }}
            QMenu::item:selected {{ background-color: {C['bg_hover']}; }}
        """)
        action = QAction("删除选中行的所有里程碑 ♪", self)
        action.triggered.connect(self._delete_selected)
        menu.addAction(action)
        vp = self._tbl.viewport()
        if vp is not None:
            menu.exec(vp.mapToGlobal(pos))

    def _reload_comparison(self):
        self._all_data = get_db().get_all_milestones_grouped()
        self._fill_table()
        self._redraw_compare()

    def _get_video_title(self, bvid: str) -> str:
        for v in self.monitored_videos:
            if v.get("bvid") == bvid:
                t = v.get("title", "")
                return t[:20] if t else bvid
        return bvid

    def _fill_table(self):
        self._tbl.clear()
        for bvid, periods in sorted(self._all_data.items()):
            title = self._get_video_title(bvid)

            def _v(p, key):
                r = periods.get(p, {})
                val = r.get(key)
                return fmt_num(val) if val is not None else "—"

            times = [periods[p].get("recorded_at", "") for p in PERIODS if p in periods]
            latest = max(times)[:16] if times else "—"

            item = QTreeWidgetItem()
            item.setText(0, bvid)
            item.setText(1, title)
            item.setText(2, _v("1周", "view_count"))
            item.setText(3, _v("1月", "view_count"))
            item.setText(4, _v("1年", "view_count"))
            item.setText(5, _v("1周", "like_count"))
            item.setText(6, _v("1月", "like_count"))
            item.setText(7, _v("1年", "like_count"))
            item.setText(8, latest)
            for c in range(9):
                item.setTextAlignment(c, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignLeft)
            self._tbl.addTopLevelItem(item)

    def _delete_selected(self):
        sel = self._tbl.selectedItems()
        if not sel:
            return
        msg = lty_voice.confirm_delete(f"{len(sel)} 个视频的所有里程碑记录")
        reply = QMessageBox.question(self, "确认 ♪", msg,
                                      QMessageBox.StandardButton.Yes |
                                      QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        for item in sel:
            bv = item.text(0)
            for p in PERIODS:
                get_db().delete_milestone(bv, p)
        self._reload_comparison()

    def _redraw_compare(self):
        data = self._apply_compare_filter()
        if not data:
            self._chart.set_data({}, "", "", [], 0, self._set_cmp_status)
            self._cmp_status.setText(lty_voice.no_data())
            return

        bvids = sorted(data.keys())
        metric = self._current_metric

        max_val = 1
        for bv in bvids:
            for p in PERIODS:
                v = (data[bv].get(p) or {}).get(metric)
                if v:
                    max_val = max(max_val, v)

        metric_label = next(
            (lb for key, lb, *_ in FIELDS if key == metric), metric
        )
        self._chart.set_data(data, metric, metric_label, bvids, max_val, self._set_cmp_status)

    def _set_cmp_status(self, text: str):
        self._cmp_status.setText(text)

    def _apply_compare_filter(self) -> dict:
        ft = self._filter_entry.text().strip()
        if not ft:
            return self._all_data
        ks = [k.strip() for k in ft.split(",") if k.strip()]
        return {bv: pd for bv, pd in self._all_data.items()
                if any(k.upper() in bv.upper() for k in ks)}
