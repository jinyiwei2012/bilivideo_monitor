"""
现代化周刊分数计算界面
手动输入或选择已监控视频，计算周刊虚拟歌手中文曲排行榜分数
"""

import logging
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QRadioButton, QTextEdit, QMessageBox,
    QGridLayout, QButtonGroup, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_MONO
from ui.dialog_base import DialogBase
from utils.weekly_score import (
    VideoData,
    WeeklyScoreResult,
    calculate_weekly_score,
)

logger = logging.getLogger(__name__)


class WeeklyScoreWindow:
    """周刊分数计算窗口（现代化风格）— 手动输入或使用已监控视频计算分数"""

    def __init__(self, parent=None, monitored_videos: Optional[List[Dict]] = None, video_dbs: Optional[Dict] = None):
        """初始化周刊分数计算窗口"""
        self.dlg = DialogBase(parent, "周刊分数计算", modal=False)
        self.dlg.resize(round(self.dlg.width() * 0.42), round(self.dlg.height() * 0.62))
        self.monitored_videos = monitored_videos or []
        self.video_dbs = video_dbs or {}
        self._entries: Dict[str, QLineEdit] = {}

        self._setup_ui()

    def _setup_ui(self):
        """构建界面：数据来源选择、输入区域、结果展示"""
        self.dlg.header("周刊分数计算", "虚拟歌手中文曲排行榜分数计算器")

        sec = self.dlg.section(padding=8)
        sec_layout = sec.layout() or QVBoxLayout()

        # 模式选择：手动输入 / 选择已监控视频
        mode_row = QWidget()
        mode_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)

        self._mode_group = QButtonGroup()
        self._mode_manual = QRadioButton("手动输入")
        self._mode_select = QRadioButton("选择已监控视频")
        self._mode_manual.setChecked(True)
        self._mode_group.addButton(self._mode_manual, 1)
        self._mode_group.addButton(self._mode_select, 2)
        self._mode_group.buttonClicked.connect(lambda: self._toggle_mode())

        mode_layout.addWidget(self._mode_manual)
        mode_layout.addSpacing(16)
        mode_layout.addWidget(self._mode_select)
        mode_layout.addStretch()
        sec_layout.addWidget(mode_row)

        # 手动输入区域：6 项指标（2×3 网格）
        self._manual_frame = QWidget()
        self._manual_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        manual_grid = QGridLayout(self._manual_frame)
        manual_grid.setContentsMargins(0, 4, 0, 0)
        manual_grid.setSpacing(6)

        labels = [
            ("播放量", "view_count"),
            ("点赞数", "like_count"),
            ("硬币数", "coin_count"),
            ("收藏数", "favorite_count"),
            ("弹幕数", "danmaku_count"),
            ("评论数", "reply_count"),
        ]
        for i, (label, key) in enumerate(labels):
            row, col = divmod(i, 3)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
            lbl.setFixedWidth(60)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            entry = QLineEdit()
            entry.setFixedWidth(120)
            entry.setStyleSheet(
                f"background-color: {C['bg_base']}; color: {C['text_1']}; "
                f"border: 1px solid {C['border']}; border-radius: 2px; padding: 2px 4px;"
            )
            entry.setFont(FONT_MONO)
            h = QHBoxLayout()
            h.addWidget(lbl)
            h.addWidget(entry)
            h.addStretch()
            container = QWidget()
            container.setStyleSheet(f"background-color: {C['bg_elevated']};")
            container.setLayout(h)
            manual_grid.addWidget(container, row, col)
            self._entries[key] = entry

        sec_layout.addWidget(self._manual_frame)

        # 已监控视频下拉选择
        self._select_frame = QWidget()
        self._select_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")
        select_layout = QHBoxLayout(self._select_frame)
        select_layout.setContentsMargins(0, 4, 0, 0)

        self._select_combo = QComboBox()
        self._select_combo.setMinimumWidth(400)
        for v in self.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", "")[:35]
            self._select_combo.addItem(f"{bvid}  {title}")
        select_layout.addWidget(self._select_combo)
        select_layout.addStretch()
        sec_layout.addWidget(self._select_frame)

        # 操作按钮
        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 8, 0, 0)

        calc_btn = QPushButton("计算分数")
        calc_btn.clicked.connect(self._calculate)
        btn_layout.addWidget(calc_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()
        sec_layout.addWidget(btn_row)

        # 计算结果区域
        res_sec = QWidget()
        res_sec.setStyleSheet(f"background-color: {C['bg_base']};")
        res_layout = QVBoxLayout(res_sec)
        res_layout.setContentsMargins(24, 10, 24, 0)

        res_title = QLabel("计算结果")
        res_title.setStyleSheet(f"color: {C['text_2']}; background: transparent; font-weight: bold; font-size: 8pt;")
        res_layout.addWidget(res_title)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setStyleSheet(
            f"background-color: {C['bg_base']}; color: {C['text_1']}; "
            f"font-family: Consolas; font-size: 11pt; "
            f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
        )
        self._result_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        res_layout.addWidget(self._result_text, stretch=1)

        # 添加到 main layout
        self.dlg._main_layout.addWidget(res_sec, 1)

        self._toggle_mode()

    def _toggle_mode(self):
        """切换手动输入 / 选择视频模式"""
        manual = self._mode_manual.isChecked()
        self._manual_frame.setVisible(manual)
        self._select_frame.setVisible(not manual)

    def _get_video_data(self) -> Optional[VideoData]:
        """获取输入的视频数据"""
        if self._mode_select.isChecked():
            idx = self._select_combo.currentIndex()
            if idx < 0 or idx >= len(self.monitored_videos):
                QMessageBox.warning(self.dlg, "提示", "请选择一个视频")
                return None
            video = self.monitored_videos[idx]
            bvid = video.get("bvid", "")
            if bvid in self.video_dbs:
                try:
                    records = self.video_dbs[bvid].get_all_records(limit=1)
                    if records:
                        latest = records[-1]
                        return VideoData(
                            view_count=latest.get("view_count", 0),
                            like_count=latest.get("like_count", 0),
                            coin_count=latest.get("coin_count", 0),
                            favorite_count=latest.get("favorite_count", 0),
                            danmaku_count=latest.get("danmaku_count", 0),
                            reply_count=latest.get("reply_count", 0),
                        )
                except Exception as e:
                    logger.debug("从数据库加载视频数据失败: %s", e)
            return VideoData(
                view_count=video.get("view_count", 0),
                like_count=video.get("like_count", 0),
                coin_count=video.get("coin_count", 0),
                favorite_count=video.get("favorite_count", 0),
                danmaku_count=video.get("danmaku_count", 0),
                reply_count=video.get("reply_count", 0),
            )
        else:
            try:
                data = {}
                for key, entry in self._entries.items():
                    val = entry.text().strip()
                    data[key] = int(float(val)) if val else 0
                return VideoData(**data)
            except (ValueError, TypeError):
                QMessageBox.warning(self.dlg, "提示", "请输入有效的数字")
                return None

    def _calculate(self):
        """计算并显示周刊分数"""
        video_data = self._get_video_data()
        if not video_data:
            return
        if video_data.view_count == 0 and video_data.like_count == 0:
            QMessageBox.warning(self.dlg, "提示", "请至少输入播放量")
            return
        result = calculate_weekly_score(video_data)
        self._display_result(video_data, result)

    def _display_result(self, data: VideoData, result: WeeklyScoreResult):
        """在文本框中格式化工整地显示计算结果"""
        self._result_text.clear()

        lines = []
        lines.append(("周刊虚拟歌手中文曲排行榜分数\n", "#title"))
        lines.append(("─" * 42 + "\n", "#sep"))
        lines.append(("输入数据\n", "#label"))
        lines.append((f"  播放: {data.view_count:>12,}    点赞: {data.like_count:>8,}\n", ""))
        lines.append((f"  硬币: {data.coin_count:>12,}    收藏: {data.favorite_count:>8,}\n", ""))
        lines.append((f"  弹幕: {data.danmaku_count:>12,}    评论: {data.reply_count:>8,}\n", ""))
        lines.append(("\n", ""))

        lines.append((f"最终得点: {result.total_score:>12,.2f}\n", "#total"))
        lines.append(("─" * 42 + "\n", "#sep"))

        items = [
            ("播放得点", result.view_score, f"基础 {result.base_view_score:,.2f} × 修正D {result.correction_d:.4f}"),
            (
                "互动得点",
                result.interaction_score,
                f"({data.danmaku_count + data.reply_count}) × 修正A {result.correction_a:.4f} × 15",
            ),
            ("收藏得点", result.favorite_score, f"{data.favorite_count:,} × 修正B {result.correction_b:.4f}"),
            ("硬币得点", result.coin_score, f"{data.coin_count:,} × 修正C {result.correction_c:.4f}"),
            ("点赞得点", result.like_score, ""),
        ]
        for name, score, detail in items:
            lines.append((f"{name:<8} {score:>12,.2f}\n", ""))
            if detail:
                lines.append((f"         └ {detail}\n", "#detail"))

        lines.append(("─" * 42 + "\n", "#sep"))

        # Build HTML
        style_map = {
            "#title": f"color: {C['text_3']}; font-weight: bold; font-size: 12pt;",
            "#total": f"color: {C['bilibili']}; font-weight: bold; font-size: 14pt;",
            "#sep": f"color: {C['text_3']};",
            "#label": f"color: {C['text_2']}; font-weight: bold;",
            "#detail": f"color: {C['accent']}; font-size: 10pt;",
        }
        html_parts = ['<html><body style="font-family: Consolas; font-size: 11pt;">']
        for text, cls in lines:
            style = style_map.get(cls, f"color: {C['text_1']};")
            html_parts.append(f'<span style="{style}">{text}</span>')
        html_parts.append("</body></html>")

        self._result_text.setHtml("".join(html_parts))

    def _clear(self):
        """清空所有输入和结果"""
        for entry in self._entries.values():
            entry.clear()
        self._select_combo.setCurrentIndex(-1)
        self._result_text.clear()
