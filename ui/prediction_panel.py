"""
右侧预测面板模块 - PyQt6 版

QWidget + QScrollArea 信息滚动区
预测英雄卡（加权预测值 + 阈值进度条 + ETA）+ 信息面板（互动率、最近记录、算法统计）
"""

from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import (
    FONT_MONO_LG, FONT_CAPTION, SPACE_MD,
    THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS, fmt_num,
)
from ui.widgets import SectionHeader, EmptyState


class _SectionTitle(QWidget):
    """分节标题组件 (兼容旧版, 新代码请使用 ui.widgets.SectionHeader)"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {C['bg_surface']};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 2)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 8pt; font-weight: bold;")
        layout.addWidget(lbl)


class PredictionPanel:
    """右侧预测面板 — PyQt6 版"""

    def __init__(self, parent, gui):
        self.gui = gui
        self._parent = parent
        self._hero_widgets: dict = {}
        self._hero_has_data = False
        self._info_dynamic: dict = {}
        self._info_content = None
        self._info_bvid: Optional[str] = None

        self.frame = QWidget(parent)
        self._build_right_panel()

    def _build_right_panel(self):
        """构建右侧面板"""
        p = self.frame
        layout = QVBoxLayout(p)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Hero card
        self._pred_hero = QWidget()
        self._pred_hero.setStyleSheet(f"background-color: {C['bg_surface']};")
        layout.addWidget(self._pred_hero)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        layout.addWidget(sep)

        # Info scroll area
        info_wrap = QWidget()
        info_wrap.setStyleSheet(f"background-color: {C['bg_surface']};")
        info_layout = QVBoxLayout(info_wrap)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self._info_scroll = QScrollArea()
        self._info_scroll.setWidgetResizable(True)
        self._info_scroll.setStyleSheet(f"""
            QScrollArea {{ background-color: {C['bg_surface']}; border: none; }}
            QScrollBar:vertical {{
                background-color: {C['bg_hover']}; width: 8px;
                border-radius: {C['radius_sm']}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {C['border']}; border-radius: {C['radius_sm']}px; min-height: 20px;
            }}
        """)
        self._info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._info_content_widget = QWidget()
        self._info_content_widget.setStyleSheet(f"background-color: {C['bg_surface']};")
        self._info_content_layout = QVBoxLayout(self._info_content_widget)
        self._info_content_layout.setContentsMargins(0, 0, 0, 0)
        self._info_content_layout.setSpacing(0)
        self._info_content_layout.addStretch()

        self._info_scroll.setWidget(self._info_content_widget)
        info_layout.addWidget(self._info_scroll)
        layout.addWidget(info_wrap, 1)

        self._build_pred_hero_empty()

    def _clear_layout(self, layout):
        """清空布局中的所有 widget"""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w:
                    w.deleteLater()

    # ── Hero Card ──────────────────────────────

    def _build_pred_hero_empty(self):
        """空状态英雄卡"""
        if not self._hero_has_data and self._hero_widgets:
            return
        layout = self._pred_hero.layout()
        if layout:
            self._clear_layout(layout)
        self._hero_widgets = {}
        self._hero_has_data = False

        if layout is None:
            layout = QVBoxLayout(self._pred_hero)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        layout.addWidget(EmptyState("选择视频后显示预测 ♪"))

    def build_pred_hero(self, weighted_pred, current_views, rate_per_sec, surge_info=None):
        """构建或更新预测英雄卡片"""
        # ── 增量更新 ──
        if self._hero_has_data and "outer" in self._hero_widgets:
            w = self._hero_widgets
            w["val_lbl"].setText(fmt_num(weighted_pred))
            delta = weighted_pred - current_views
            delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
            delta_color = C["success"] if delta >= 0 else C["danger"]
            w["delta_lbl"].setText(delta_text)
            w["delta_lbl"].setStyleSheet(f"color: {delta_color}; font-size: 10pt;")

            if rate_per_sec > 0:
                per_hour = rate_per_sec * 3600
                per_min = rate_per_sec * 60
                if per_hour >= 1:
                    rate_str = f"📈 +{fmt_num(per_hour)}/h"
                elif per_min >= 0.1:
                    rate_str = f"📈 +{per_min:.1f}/min"
                else:
                    rate_str = f"📈 +{rate_per_sec:.2f}/s"
                w["rate_lbl"].setText(rate_str)
                w["rate_lbl"].setVisible(True)
            else:
                if w.get("rate_lbl") is not None:
                    w["rate_lbl"].setVisible(False)

            self._update_surge_badge(w, surge_info)

            for i, (t, name, col) in enumerate(zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS)):
                if i >= len(w["thr_rows"]):
                    break
                row_data = w["thr_rows"][i]
                pct = min(current_views / t, 1.0)
                row_data["progress"].setValue(int(pct * 100))
                if t <= current_views:
                    eta_str, eta_c = "✓ 已达成", C["success"]
                elif rate_per_sec > 0:
                    need = t - current_views
                    seconds_left = need / rate_per_sec
                    arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                    eta_str = arrive_dt.strftime("%m-%d %H:%M")
                    eta_c = C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
                else:
                    eta_str, eta_c = "—", C["text_3"]
                row_data["eta_lbl"].setText(eta_str)
                row_data["eta_lbl"].setStyleSheet(f"color: {eta_c}; font-family: Consolas; font-size: 9pt;")
            return

        # ── 首次构建 ──
        layout = self._pred_hero.layout()
        if layout:
            self._clear_layout(layout)
        self._hero_widgets = {}

        outer = QWidget()
        outer.setStyleSheet(f"""
            QWidget {{
                background-color: {C['bg_elevated']};
                border: 1px solid {C['lty_blue']};
                border-radius: {C['radius_lg']}px;
            }}
        """)
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(14, 10, 14, 12)
        ol.setSpacing(4)

        # 水波渐变条 (天依蓝渐变, 呼应洛水天依)
        wave = QFrame()
        wave.setFixedHeight(3)
        wave.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {C['lty_wave_a']}, stop:1 {C['lty_wave_b']}); "
            "border: none; border-radius: 1px;"
        )
        ol.addWidget(wave)

        # 标题
        ol.addWidget(SectionHeader("🎯 综合加权预测 ♪"))

        # 加权预测值
        val_lbl = QLabel(fmt_num(weighted_pred))
        val_font = QFont(FONT_MONO_LG)
        val_font.setPointSize(18)
        val_lbl.setFont(val_font)
        val_lbl.setStyleSheet(f"color: {C['lty_blue_deep']}; background-color: transparent;")
        ol.addWidget(val_lbl)

        # 增长量
        delta = weighted_pred - current_views
        delta_text = f"▲ +{fmt_num(delta)}" if delta >= 0 else f"▼ {fmt_num(delta)}"
        delta_color = C["success"] if delta >= 0 else C["danger"]
        delta_lbl = QLabel(delta_text)
        delta_lbl.setStyleSheet(f"color: {delta_color}; font-size: 10pt;")
        ol.addWidget(delta_lbl)

        # 速率
        rate_lbl = None
        if rate_per_sec > 0:
            per_hour = rate_per_sec * 3600
            per_min = rate_per_sec * 60
            if per_hour >= 1:
                rate_str = f"📈 +{fmt_num(per_hour)}/h"
            elif per_min >= 0.1:
                rate_str = f"📈 +{per_min:.1f}/min"
            else:
                rate_str = f"📈 +{rate_per_sec:.2f}/s"
            rate_lbl = QLabel(rate_str)
            rate_lbl.setStyleSheet(f"color: {C['accent']}; font-size: 9pt;")
            ol.addWidget(rate_lbl)

        # Surge badge
        surge_frame = self._build_surge_badge(outer, surge_info)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {C['border']}; max-height: 1px;")
        ol.addWidget(sep)

        # 阈值进度
        thr_rows = []
        for t, name, col in zip(THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS):
            row = QWidget()
            row.setStyleSheet("background-color: transparent;")
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 2, 0, 2)
            rh.setSpacing(4)

            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(38)
            name_lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 9pt;")
            rh.addWidget(name_lbl)

            pct = min(current_views / t, 1.0)
            progress = QProgressBar()
            progress.setFixedHeight(4)
            progress.setValue(int(pct * 100))
            progress.setTextVisible(False)
            progress.setStyleSheet(f"""
                QProgressBar {{ background-color: {C['bg_hover']}; border: none; }}
                QProgressBar::chunk {{ background-color: {col}; }}
            """)
            rh.addWidget(progress, 1)

            if t <= current_views:
                eta_str, eta_c = "✓ 已达成", C["success"]
            elif rate_per_sec > 0:
                need = t - current_views
                seconds_left = need / rate_per_sec
                arrive_dt = datetime.now() + timedelta(seconds=seconds_left)
                eta_str = arrive_dt.strftime("%m-%d %H:%M")
                eta_c = C["danger"] if seconds_left < 3600 else C["warning"] if seconds_left < 86400 else C["text_2"]
            else:
                eta_str, eta_c = "—", C["text_3"]
            eta_lbl = QLabel(eta_str)
            eta_lbl.setFixedWidth(88)
            eta_lbl.setStyleSheet(f"color: {eta_c}; font-family: Consolas; font-size: 9pt;")
            eta_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rh.addWidget(eta_lbl)

            ol.addWidget(row)
            thr_rows.append({"progress": progress, "eta_lbl": eta_lbl})

        if layout is None:
            layout = QVBoxLayout(self._pred_hero)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(outer)

        self._hero_widgets = {
            "outer": outer,
            "val_lbl": val_lbl,
            "delta_lbl": delta_lbl,
            "rate_lbl": rate_lbl,
            "thr_rows": thr_rows,
            "surge_frame": surge_frame,
        }
        self._hero_has_data = True

    # ── Surge badge ────────────────────────────

    def _build_surge_badge(self, parent, surge_info):
        """构建推流状态指示器"""
        frame = QWidget(parent)
        frame.setStyleSheet("background-color: transparent;")
        frame.setVisible(False)

        if not surge_info or not surge_info.get("is_surging"):
            return frame

        surge_type = surge_info.get("surge_type", "moderate")
        surge_label = surge_info.get("surge_label", "📈 推流中")
        surge_mag = surge_info.get("surge_magnitude", 1.0)
        baseline = surge_info.get("baseline_velocity", 0)
        surge_vel = surge_info.get("surge_velocity", 0)
        daily_vel = surge_info.get("daily_velocity")
        decay_hl = surge_info.get("decay_half_life_hours", 6.0)
        confidence = surge_info.get("surge_confidence", 0.0)

        if surge_type == "strong":
            badge_color = C['warning']
            bg_color = C['bg_surface']
        elif surge_type == "moderate":
            badge_color = C['warning']
            bg_color = C['bg_surface']
        else:
            badge_color = C['lty_blue']
            bg_color = C['lty_blue_light']

        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(2)

        # Header
        header_row = QWidget()
        header_row.setStyleSheet(f"background-color: {bg_color}; border-radius: {C['radius_sm']}px;")
        hh = QHBoxLayout(header_row)
        hh.setContentsMargins(6, 3, 6, 3)

        badge_lbl = QLabel(f"  {surge_label}  ")
        badge_lbl.setStyleSheet(f"color: {badge_color}; font-size: 9pt; font-weight: bold;")
        hh.addWidget(badge_lbl)

        detail_lbl = QLabel(f"· {surge_mag:.1f}x · 置信度 {confidence*100:.0f}% · 衰退 {decay_hl:.1f}h")
        detail_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 7pt;")
        hh.addWidget(detail_lbl)
        hh.addStretch()

        fl.addWidget(header_row)

        # Comparison row
        comp_row = QWidget()
        comp_row.setStyleSheet("background-color: transparent;")
        ch = QHBoxLayout(comp_row)
        ch.setContentsMargins(2, 2, 2, 2)
        ch.setSpacing(4)

        cur_vel_lbl = QLabel(f"当前 +{fmt_num(surge_vel)}/h")
        cur_vel_lbl.setStyleSheet(f"color: {badge_color}; font-family: Consolas; font-size: 8pt; font-weight: bold;")
        ch.addWidget(cur_vel_lbl)

        vs_lbl = QLabel(" vs ")
        vs_lbl.setStyleSheet(f"color: {C['text_3']}; font-family: Consolas; font-size: 8pt;")
        ch.addWidget(vs_lbl)

        base_lbl = QLabel(f"基线 +{fmt_num(baseline)}/h")
        base_lbl.setStyleSheet(f"color: {C['text_2']}; font-family: Consolas; font-size: 8pt;")
        ch.addWidget(base_lbl)

        daily_lbl_ref = None
        if daily_vel is not None and daily_vel > 0:
            sep_lbl = QLabel(" | ")
            sep_lbl.setStyleSheet(f"color: {C['text_3']}; font-family: Consolas; font-size: 8pt;")
            ch.addWidget(sep_lbl)
            period_ratio = surge_info.get("period_comparison", {}).get("daily_ratio")
            daily_color = C["danger"] if (period_ratio and period_ratio >= 2.0) else C["text_2"]
            daily_lbl_ref = QLabel(f"昨日同期 +{fmt_num(daily_vel)}/h")
            daily_lbl_ref.setStyleSheet(f"color: {daily_color}; font-family: Consolas; font-size: 8pt;")
            ch.addWidget(daily_lbl_ref)

        ch.addStretch()
        fl.addWidget(comp_row)
        frame.setVisible(True)

        # Cache surge labels for incremental update
        self._hero_widgets["_surge_refs"] = {
            "badge": badge_lbl,
            "detail": detail_lbl,
            "cur_vel": cur_vel_lbl,
            "baseline": base_lbl,
            "daily": daily_lbl_ref,
        }

        return frame

    def _update_surge_badge(self, hero_widgets, surge_info):
        """增量更新推流指示器"""
        frame = hero_widgets.get("surge_frame")
        if frame is None:
            return

        refs = hero_widgets.get("_surge_refs", {})
        is_surging = surge_info and surge_info.get("is_surging")
        was_surging = frame.isVisible()

        if is_surging != was_surging:
            frame.setVisible(bool(is_surging))
            if is_surging:
                # Will be rebuilt lazily on next full hero rebuild
                pass
            return

        if not is_surging or not refs:
            return

        # Only update numerical values
        surge_label = surge_info.get("surge_label", "📈 推流中")
        surge_mag = surge_info.get("surge_magnitude", 1.0)
        confidence = surge_info.get("surge_confidence", 0.0)
        decay_hl = surge_info.get("decay_half_life_hours", 6.0)
        surge_vel = surge_info.get("surge_velocity", 0)
        baseline = surge_info.get("baseline_velocity", 0)
        daily_vel = surge_info.get("daily_velocity")
        period_ratio = surge_info.get("period_comparison", {}).get("daily_ratio")

        if refs.get("badge"):
            refs["badge"].setText(f"  {surge_label}  ")
        if refs.get("detail"):
            refs["detail"].setText(f"· {surge_mag:.1f}x · 置信度 {confidence*100:.0f}% · 衰退 {decay_hl:.1f}h")
        if refs.get("cur_vel"):
            refs["cur_vel"].setText(f"当前 +{fmt_num(surge_vel)}/h")
        if refs.get("baseline"):
            refs["baseline"].setText(f"基线 +{fmt_num(baseline)}/h")
        if refs.get("daily") and daily_vel is not None:
            daily_color = C["danger"] if (period_ratio and period_ratio >= 2.0) else C["text_2"]
            refs["daily"].setText(f"昨日同期 +{fmt_num(daily_vel)}/h")
            refs["daily"].setStyleSheet(f"color: {daily_color}; font-family: Consolas; font-size: 8pt;")

    # ── Info Panel ─────────────────────────────

    def _clear_info(self):
        """清空信息面板"""
        self._clear_layout(self._info_content_layout)
        self._info_content_layout.addStretch()
        self._info_content = None
        self._info_bvid = None
        self._info_dynamic = {}

    def update_info(self, video, history, prediction_result):
        """更新右侧信息面板"""
        bvid = video.get("bvid", "")
        same_video = bvid and bvid == self._info_bvid and self._info_content

        if same_video:
            self._update_info_values(video, history, prediction_result)
            return

        self._info_bvid = bvid
        self._clear_info()
        self._build_info_static(video, history, prediction_result)
        self._info_content = True

    def _build_info_static(self, video, history, prediction_result):
        """创建全部信息面板 widget"""
        layout = self._info_content_layout
        dyn = self._info_dynamic = {}
        views = max(video.get("view_count", 0), 1)

        # ── 互动率概览 ──
        layout.addWidget(SectionHeader("📊 互动率概览"))
        grid = QWidget()
        grid.setStyleSheet(f"background-color: {C['bg_surface']};")
        gl = QGridLayout(grid)
        gl.setContentsMargins(10, 0, 10, 6)
        gl.setSpacing(2)

        rate_keys = ["like", "coin", "favorite", "share", "danmaku"]
        rate_labels = ["👍 点赞率", "🪙 投币率", "⭐ 收藏率", "🔗 分享率", "💬 弹幕率"]
        for i, (rlbl, rkey) in enumerate(zip(rate_labels, rate_keys)):
            row, col_idx = divmod(i, 2)
            cell = QFrame()
            cell.setFixedHeight(28)
            cell.setStyleSheet(f"background-color: {C['bg_elevated']}; border-radius: {C['radius_sm']}px;")
            cell_h = QHBoxLayout(cell)
            cell_h.setContentsMargins(6, 0, 6, 0)
            name = QLabel(rlbl)
            name.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
            cell_h.addWidget(name)
            val_lbl = QLabel("")
            val_lbl.setStyleSheet(f"color: {C['text_1']}; font-family: Consolas; font-size: 9pt; font-weight: bold;")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cell_h.addWidget(val_lbl, 1)
            gl.addWidget(cell, row, col_idx)
            gl.setColumnStretch(col_idx, 1)
            dyn[f"rate_{rkey}"] = val_lbl

        layout.addWidget(grid)

        # ── 在线人数 ──
        online_wrap = QWidget()
        online_wrap.setStyleSheet(f"background-color: {C['bg_surface']};")
        ow_l = QHBoxLayout(online_wrap)
        ow_l.setContentsMargins(10, 0, 10, 6)
        online_row = QFrame()
        online_row.setFixedHeight(28)
        online_row.setStyleSheet(f"background-color: {C['bg_elevated']}; border-radius: {C['radius_sm']}px;")
        or_h = QHBoxLayout(online_row)
        or_h.setContentsMargins(6, 0, 6, 0)
        online_lbl = QLabel("👁 在线人数")
        online_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        or_h.addWidget(online_lbl)
        online_val = QLabel("")
        online_val.setStyleSheet(f"color: {C['accent']}; font-family: Consolas; font-size: 9pt;")
        online_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        or_h.addWidget(online_val, 1)
        ow_l.addWidget(online_row)
        layout.addWidget(online_wrap)
        dyn["online"] = online_val

        # ── 最近记录 ──
        layout.addWidget(SectionHeader("📋 最近记录"))
        hist_container = QWidget()
        hist_container.setStyleSheet(f"background-color: {C['bg_surface']};")
        self._hist_layout = QVBoxLayout(hist_container)
        self._hist_layout.setContentsMargins(10, 0, 10, 6)
        self._hist_layout.setSpacing(1)
        layout.addWidget(hist_container)
        dyn["hist_container"] = hist_container
        dyn["hist_rows"] = []

        # 表头行 (时间 / 增量 / 播放量 对齐基准)
        hist_header = QWidget()
        hist_header.setStyleSheet(f"background-color: {C['bg_surface']};")
        hh = QHBoxLayout(hist_header)
        hh.setContentsMargins(0, 0, 0, 2)
        hh.setSpacing(4)
        ts_head = QLabel("时间")
        ts_head.setFont(FONT_CAPTION)
        ts_head.setFixedWidth(60)
        ts_head.setStyleSheet(f"color: {C['text_3']}; background-color: transparent;")
        hh.addWidget(ts_head)
        hh.addStretch()
        delta_head = QLabel("增量")
        delta_head.setFont(FONT_CAPTION)
        delta_head.setFixedWidth(50)
        delta_head.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        delta_head.setStyleSheet(f"color: {C['text_3']}; background-color: transparent;")
        hh.addWidget(delta_head)
        view_head = QLabel("播放量")
        view_head.setFont(FONT_CAPTION)
        view_head.setFixedWidth(60)
        view_head.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        view_head.setStyleSheet(f"color: {C['text_3']}; background-color: transparent;")
        hh.addWidget(view_head)
        self._hist_layout.addWidget(hist_header)

        # ── 算法统计 ──
        layout.addWidget(SectionHeader("🧠 算法统计"))
        algo_frame = QWidget()
        algo_frame.setStyleSheet(f"background-color: {C['bg_surface']};")
        af_l = QVBoxLayout(algo_frame)
        af_l.setContentsMargins(10, 0, 10, 6)
        af_l.setSpacing(2)

        ar1 = QFrame()
        ar1.setFixedHeight(28)
        ar1.setStyleSheet(f"background-color: {C['bg_elevated']}; border-radius: {C['radius_sm']}px;")
        ar1_h = QHBoxLayout(ar1)
        ar1_h.setContentsMargins(6, 0, 6, 0)
        valid_lbl = QLabel("有效算法")
        valid_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        ar1_h.addWidget(valid_lbl)
        algo_valid = QLabel("")
        algo_valid.setStyleSheet(f"color: {C['success']}; font-family: Consolas; font-size: 9pt; font-weight: bold;")
        algo_valid.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ar1_h.addWidget(algo_valid, 1)
        af_l.addWidget(ar1)

        ar2 = QFrame()
        ar2.setFixedHeight(28)
        ar2.setStyleSheet(f"background-color: {C['bg_elevated']}; border-radius: {C['radius_sm']}px;")
        ar2_h = QHBoxLayout(ar2)
        ar2_h.setContentsMargins(6, 0, 6, 0)
        ens_lbl = QLabel("集成置信度")
        ens_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        ar2_h.addWidget(ens_lbl)
        ensemble_lbl = QLabel("")
        ensemble_lbl.setStyleSheet(f"color: {C['accent']}; font-family: Consolas; font-size: 9pt; font-weight: bold;")
        ensemble_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ar2_h.addWidget(ensemble_lbl, 1)
        af_l.addWidget(ar2)

        layout.addWidget(algo_frame)
        dyn["algo_valid"] = algo_valid
        dyn["ensemble"] = ensemble_lbl

        # ── 数据健康 ──
        layout.addWidget(SectionHeader("📡 数据健康"))
        health_frame = QWidget()
        health_frame.setStyleSheet(f"background-color: {C['bg_surface']};")
        hf_l = QHBoxLayout(health_frame)
        hf_l.setContentsMargins(10, 0, 10, 6)
        hr = QFrame()
        hr.setFixedHeight(28)
        hr.setStyleSheet(f"background-color: {C['bg_elevated']}; border-radius: {C['radius_sm']}px;")
        hr_h = QHBoxLayout(hr)
        hr_h.setContentsMargins(6, 0, 6, 0)
        rec_lbl = QLabel("数据点数")
        rec_lbl.setStyleSheet(f"color: {C['text_3']}; font-size: 9pt;")
        hr_h.addWidget(rec_lbl)
        n_records_lbl = QLabel("")
        n_records_lbl.setStyleSheet(f"color: {C['text_1']}; font-family: Consolas; font-size: 9pt; font-weight: bold;")
        n_records_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hr_h.addWidget(n_records_lbl, 1)
        hf_l.addWidget(hr)
        layout.addWidget(health_frame)
        dyn["n_records"] = n_records_lbl

        # 首次渲染立即填充数值
        self._update_info_values(video, history, prediction_result)

    def _update_info_values(self, video, history, prediction_result):
        """仅更新动态数值标签"""
        dyn = self._info_dynamic
        if not dyn:
            return

        views = max(video.get("view_count", 0), 1)
        likes = video.get("like_count", 0) or 0
        coins = video.get("coin_count", 0) or 0
        favorites = video.get("favorite_count", 0) or 0
        shares = video.get("share_count", 0) or 0
        danmaku = video.get("danmaku_count", 0) or 0

        for rkey, val, fmt_fn in [
            ("like", likes, lambda v: f"{v / views * 100:.2f}%"),
            ("coin", coins, lambda v: f"{v / views * 100:.2f}%"),
            ("favorite", favorites, lambda v: f"{v / views * 100:.2f}%"),
            ("share", shares, lambda v: f"{v / views * 100:.2f}%"),
            ("danmaku", danmaku, lambda v: f"{v / views * 100:.2f}%"),
        ]:
            lbl = dyn.get(f"rate_{rkey}")
            if lbl:
                lbl.setText(fmt_fn(val))

        # 在线人数
        online_total = video.get("viewers_total", 0)
        online_web = video.get("viewers_web", 0)
        online_app = video.get("viewers_app", 0)
        if dyn.get("online"):
            if online_total > 0:
                dyn["online"].setText(f"{fmt_num(online_total)}  (网页{fmt_num(online_web)}/APP{fmt_num(online_app)})")
            else:
                dyn["online"].setText("—")

        # 最近记录
        self._update_history_rows(history)

        # 算法统计
        if prediction_result:
            valid = prediction_result.get("valid", 0)
            total = prediction_result.get("total", 0)
            ensemble_conf = prediction_result.get("ensemble_confidence", 0)
            if dyn.get("algo_valid"):
                fg = C["success"] if valid > 0 else C["danger"]
                dyn["algo_valid"].setText(f"{valid}/{total}")
                dyn["algo_valid"].setStyleSheet(f"color: {fg}; font-family: Consolas; font-size: 9pt; font-weight: bold;")
            if dyn.get("ensemble"):
                dyn["ensemble"].setText(f"{ensemble_conf * 100:.1f}%" if ensemble_conf > 0 else "—")

        # 数据健康
        if dyn.get("n_records"):
            dyn["n_records"].setText(str(len(history)) if history else "0")

    def _update_history_rows(self, history):
        """增量更新最近记录行"""
        dyn = self._info_dynamic
        if not dyn:
            return
        rows = dyn.get("hist_rows", [])
        container = dyn.get("hist_container")
        hist_layout = self._hist_layout

        if not container or hist_layout is None:
            return

        if not history or len(history) < 2:
            for row_fr, _, _, _ in rows:
                row_fr.deleteLater()
            rows.clear()
            if hist_layout.count() == 0:
                empty_lbl = QLabel("还没有历史数据呢…♪")
                empty_lbl.setFont(FONT_CAPTION)
                empty_lbl.setStyleSheet(f"color: {C['text_3']}; background-color: transparent;")
                hist_layout.addWidget(empty_lbl)
            return

        # 清除占位文本
        for i in range(hist_layout.count()):
            item = hist_layout.itemAt(i)
            if item is not None:
                w = item.widget()
                if w and isinstance(w, QLabel) and w.text() == "还没有历史数据呢…♪":
                    w.deleteLater()

        recent = history[-15:]
        prev_vals = [prev[1] if i > 0 else recent[0][1] for i, prev in enumerate(recent)]

        if len(rows) == len(recent):
            # 行数不变，只更新文本
            for i, (ts, v) in enumerate(recent):
                _, ts_lbl, view_lbl, delta_lbl = rows[i]
                dt_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)[:16]
                ts_lbl.setText(dt_str)
                view_lbl.setText(fmt_num(v))
                delta_v = v - prev_vals[i] if i > 0 and prev_vals[i] > 0 else 0
                if delta_v > 0:
                    delta_lbl.setText(f"+{fmt_num(delta_v)}")
                    delta_lbl.setStyleSheet(f"color: {C['success']}; font-family: Consolas; font-size: 8pt;")
                else:
                    delta_lbl.setText("—")
                    delta_lbl.setStyleSheet(f"color: {C['text_3']}; font-family: Consolas; font-size: 8pt;")
        else:
            # 行数变了，全量重建
            for row_fr, _, _, _ in rows:
                row_fr.deleteLater()
            rows.clear()
            for i, (ts, v) in enumerate(recent):
                dt_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)[:16]
                delta_v = v - prev_vals[i] if i > 0 and prev_vals[i] > 0 else 0
                delta_str = f"+{fmt_num(delta_v)}" if delta_v > 0 else "—"
                delta_c = C["success"] if delta_v > 0 else C["text_3"]

                row_fr = QWidget()
                row_fr.setStyleSheet(f"background-color: {C['bg_surface']};")
                rh = QHBoxLayout(row_fr)
                rh.setContentsMargins(0, 1, 0, 1)
                rh.setSpacing(4)

                ts_lbl = QLabel(dt_str)
                ts_lbl.setFixedWidth(60)
                ts_lbl.setStyleSheet(f"color: {C['text_3']}; font-family: Consolas; font-size: 8pt;")
                rh.addWidget(ts_lbl)

                rh.addStretch()

                delta_lbl = QLabel(delta_str)
                delta_lbl.setFixedWidth(50)
                delta_lbl.setStyleSheet(f"color: {delta_c}; font-family: Consolas; font-size: 8pt;")
                delta_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                rh.addWidget(delta_lbl)

                view_lbl = QLabel(fmt_num(v))
                view_lbl.setFixedWidth(60)
                view_lbl.setStyleSheet(f"color: {C['text_1']}; font-family: Consolas; font-size: 9pt; font-weight: bold;")
                view_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                rh.addWidget(view_lbl)

                hist_layout.addWidget(row_fr)
                rows.append((row_fr, ts_lbl, view_lbl, delta_lbl))

        dyn["hist_rows"] = rows

    # ── 兼容旧接口 ──

    def _update_algo_list(self, results, failed):
        """兼容旧接口"""
        bvid = self.gui.selected_bvid
        if not bvid:
            self._clear_info()
            return
        video = self.gui._get_video(bvid)
        if not video:
            self._clear_info()
            return
        history = self.gui.history_data.get(bvid, [])
        cached = self.gui.prediction_results.get(bvid, {})
        self.update_info(video, history, cached)

    @property
    def algo_frame(self):
        return self._info_scroll
