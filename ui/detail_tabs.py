"""详情面板 Mixin — 互动率 + 弹幕标签页

作为 DetailPanel 的 Mixin 类使用。
"""
import logging

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor

from ui.theme import C
from ui.widgets import SectionHeader

logger = logging.getLogger(__name__)


class _RatioDanmakuMixin:
    """互动率 + 弹幕标签页 Mixin"""

    # ── Ratio Frame ─────────────────────────────

    def _fill_ratio_frame(self, video):
        """更新互动率面板数值——不重建 widget，只更新文本和进度条宽度"""
        if not hasattr(self, '_ratio_bars') or not self._ratio_bars:
            self._build_ratio_frame()
        views = video.get("view_count", 1) or 1
        ratios = [
            ("点赞率", video.get("like_count", 0) / views * 100, C["bilibili"]),
            ("投币率", video.get("coin_count", 0) / views * 100, C["accent"]),
            ("收藏率", video.get("favorite_count", 0) / views * 100, C["success"]),
            ("弹幕率", video.get("danmaku_count", 0) / views * 100, C["warning"]),
        ]
        for (_, pct, _), (bar_fill, pct_lbl) in zip(ratios, self._ratio_bars):
            fill_pct = min(pct / 20, 1.0)
            bar_fill.setFixedWidth(int(fill_pct * 200))
            pct_lbl.setText(f"{pct:.3f}%")

    def _build_ratio_frame(self):
        """构建互动率面板（仅一次）"""
        self._ratio_bars = []
        ratios_cfg = [
            ("点赞率", C["bilibili"]),
            ("投币率", C["accent"]),
            ("收藏率", C["success"]),
            ("弹幕率", C["warning"]),
        ]
        self._ratio_layout.addWidget(SectionHeader("⟳ 互动率 ♪"))
        for label, color in ratios_cfg:
            row = QWidget()
            row.setStyleSheet(f"background-color: {C['bg_base']};")
            row_h = QHBoxLayout(row)
            row_h.setContentsMargins(0, 6, 0, 6)
            row_h.setSpacing(8)

            lbl = QLabel(label)
            lbl.setFixedWidth(48)
            lbl.setStyleSheet(f"color: {C['text_2']}; font-size: 10pt;")
            row_h.addWidget(lbl)

            bar_bg = QFrame()
            bar_bg.setFixedHeight(12)
            bar_bg.setStyleSheet(f"background-color: {C['bg_elevated']}; border-radius: 2px;")
            bar_bg_layout = QHBoxLayout(bar_bg)
            bar_bg_layout.setContentsMargins(0, 0, 0, 0)

            bar_fill = QFrame()
            bar_fill.setFixedHeight(12)
            bar_fill.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
            bar_fill.setFixedWidth(0)
            bar_bg_layout.addWidget(bar_fill)
            bar_bg_layout.addStretch()
            row_h.addWidget(bar_bg, 1)

            pct_lbl = QLabel("0.000%")
            pct_lbl.setFixedWidth(72)
            pct_lbl.setStyleSheet(f"color: {color}; font-family: Consolas; font-size: 10pt;")
            row_h.addWidget(pct_lbl)

            self._ratio_layout.addWidget(row)
            self._ratio_bars.append((bar_fill, pct_lbl))

        self._ratio_layout.addStretch()

    # ── Danmaku ─────────────────────────────────

    def _refresh_danmaku_display(self):
        """从数据库加载弹幕并刷新显示"""
        bvid = self.gui.selected_bvid
        if not bvid:
            self._dm_text.setVisible(True)
            self._dm_empty.setVisible(False)
            self._dm_text.setPlainText("还没有选视频呢…像一首没点开的歌,天依等你来点 ♪")
            self._dm_count_lbl.setText("")
            return

        video_db = self.gui.video_dbs.get(bvid)
        if not video_db:
            self._dm_count_lbl.setText("呜…数据库还没找到呢")
            return

        try:
            records = video_db.get_danmaku_records(limit=200)
        except Exception as e:
            logger.debug("弹幕记录获取失败: %s", e)
            records = []
        count = video_db.count_danmaku()
        self._dm_count_lbl.setText(f"♪ 共 {count} 条")

        self._dm_text.clear()
        if not records:
            self._dm_text.setVisible(False)
            self._dm_empty.setVisible(True)
        else:
            self._dm_text.setVisible(True)
            self._dm_empty.setVisible(False)
            html = "<pre style='font-family: \"Microsoft YaHei UI\"; font-size: 10pt; margin: 0; white-space: pre-wrap;'>"
            for r in records[-200:]:
                ts = r.get("video_ts", 0)
                m, s = divmod(int(ts), 60)
                html += f"<span style='color: {C['log_time']}; font-family: Consolas; font-size: 9pt;'>[{m:02d}:{s:02d}]</span> "
                content = r.get("content", "")
                content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html += f"<span style='color: {C['text_1']};'>{content}</span><br>"
            html += "</pre>"
            self._dm_text.setHtml(html)
            # Scroll to bottom
            cursor = self._dm_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._dm_text.setTextCursor(cursor)
