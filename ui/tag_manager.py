"""
视频标签管理窗口
为监控视频添加/删除/筛选自定义标签
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QComboBox, QMessageBox,
    QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt

from ui.theme import C
from ui.helpers import FONT
from ui.dialog_base import DialogBase
from utils.tag_manager import get_tags, set_tags, all_tags, suggest_tags


class TagManagerWindow:
    """视频标签管理窗口 — 支持为监控视频添加/删除/筛选自定义标签"""

    def __init__(self, parent, gui):
        """初始化标签管理窗口"""
        self.gui = gui
        self.dlg = DialogBase(parent, "◫ 视频标签管理", "600x500")
        self.dlg.header("视频标签管理", "为监控视频添加自定义标签，方便分类筛选")
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        """构建界面布局：左侧视频列表 + 标签输入，右侧当前标签 + 筛选"""
        main = QWidget()
        main.setStyleSheet(f"background-color: {C['bg_base']};")
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(10, 4, 10, 4)

        # ── 左侧：视频列表 + 标签输入 ──
        left = QWidget()
        left.setStyleSheet(f"background-color: {C['bg_base']};")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_title = QLabel("监控视频")
        left_title.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        left_title.setFont(FONT)
        left_layout.addWidget(left_title)

        self._video_list = QListWidget()
        self._video_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: none;
            }}
            QListWidget::item:selected {{
                background-color: {C['bilibili']};
            }}
        """)
        self._video_list.currentRowChanged.connect(self._on_select)
        left_layout.addWidget(self._video_list, 1)

        tag_input_row = QWidget()
        tag_input_row.setStyleSheet(f"background-color: {C['bg_base']};")
        tag_input_layout = QHBoxLayout(tag_input_row)
        tag_input_layout.setContentsMargins(0, 4, 0, 0)

        self._tag_entry = QLineEdit()
        self._tag_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: none; padding: 4px;
            }}
        """)
        self._tag_entry.returnPressed.connect(self._add_tag)
        tag_input_layout.addWidget(self._tag_entry, 1)

        add_btn = QPushButton("添加标签")
        add_btn.clicked.connect(self._add_tag)
        tag_input_layout.addWidget(add_btn)

        suggest_btn = QPushButton("✦ 建议")
        suggest_btn.setToolTip("根据视频信息自动建议标签")
        suggest_btn.clicked.connect(self._auto_suggest)
        tag_input_layout.addWidget(suggest_btn)

        left_layout.addWidget(tag_input_row)
        main_layout.addWidget(left, 1)

        # ── 右侧：当前标签 + 筛选 ──
        right = QWidget()
        right.setStyleSheet(f"background-color: {C['bg_base']};")
        right.setFixedWidth(200)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)

        right_title = QLabel("当前标签")
        right_title.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        right_title.setFont(FONT)
        right_layout.addWidget(right_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background-color: {C['bg_base']}; border: none;")
        self._tags_container = QWidget()
        self._tags_container.setStyleSheet(f"background-color: {C['bg_base']};")
        self._tags_layout = QVBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(1)
        self._tags_layout.addStretch()
        scroll.setWidget(self._tags_container)
        right_layout.addWidget(scroll, 1)

        filter_title = QLabel("按标签筛选")
        filter_title.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        filter_title.setFont(FONT)
        right_layout.addWidget(filter_title)

        self._filter_combo = QComboBox()
        self._filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        self._filter_combo.currentTextChanged.connect(lambda: self._refresh())
        right_layout.addWidget(self._filter_combo)

        clear_btn = QPushButton("清除筛选")
        clear_btn.clicked.connect(lambda: [self._filter_combo.setCurrentIndex(0), self._refresh()])
        right_layout.addWidget(clear_btn)

        main_layout.addWidget(right)

        # 放入 dlg
        area = self.dlg.content_area()
        outer = QVBoxLayout(area)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(main)

    def _refresh(self):
        """刷新视频列表和筛选下拉框"""
        self._video_list.blockSignals(True)
        self._video_list.clear()
        self._bvid_map = []
        filter_tag = self._filter_combo.currentText()

        for v in self.gui.monitored_videos:
            bvid = v.get("bvid", "")
            title = v.get("title", bvid)[:30]
            tags = get_tags(bvid)
            if filter_tag and filter_tag not in tags:
                continue
            display = f"[{' '.join(tags)}] {title}" if tags else title
            self._video_list.addItem(display)
            self._bvid_map.append(bvid)

        # 刷新筛选下拉框
        current_filter = self._filter_combo.currentText()
        self._filter_combo.blockSignals(True)
        self._filter_combo.clear()
        self._filter_combo.addItem("")
        for t in sorted(all_tags()):
            self._filter_combo.addItem(t)
        # 恢复选中
        idx = self._filter_combo.findText(current_filter)
        if idx >= 0:
            self._filter_combo.setCurrentIndex(idx)
        self._filter_combo.blockSignals(False)

        self._video_list.blockSignals(False)
        self._selected_bvid = None

    def _on_select(self):
        """视频列表选中事件 — 更新选中视频并显示其标签"""
        row = self._video_list.currentRow()
        if row < 0 or row >= len(self._bvid_map):
            return
        self._selected_bvid = self._bvid_map[row]
        self._refresh_tags()

    def _refresh_tags(self):
        """刷新当前选中视频的标签显示"""
        for i in reversed(range(self._tags_layout.count())):
            w = self._tags_layout.itemAt(i).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        # re-add stretch
        self._tags_layout.addStretch()

        if not self._selected_bvid:
            return

        for tag in get_tags(self._selected_bvid):
            row = QWidget()
            row.setStyleSheet(f"background-color: {C['bg_surface']};")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)

            lbl = QLabel(f"  #{tag}")
            lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
            lbl.setFont(FONT)
            row_layout.addWidget(lbl)

            del_lbl = QLabel("✗")
            del_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            del_lbl.setFont(FONT)
            del_lbl.mousePressEvent = lambda e, t=tag: self._delete_tag(t)
            row_layout.addWidget(del_lbl, 0, Qt.AlignmentFlag.AlignRight)

            self._tags_layout.insertWidget(self._tags_layout.count() - 1, row)

    def _delete_tag(self, tag):
        """删除指定标签"""
        if self._selected_bvid:
            existing = get_tags(self._selected_bvid)
            if tag in existing:
                existing.remove(tag)
                set_tags(self._selected_bvid, existing)
            self._refresh_tags()

    def _add_tag(self):
        """为选中视频添加新标签"""
        if not self._selected_bvid:
            QMessageBox.warning(self.dlg.window, "提示", "请先在左侧选择一个视频")
            return
        tag = self._tag_entry.text().strip()
        if not tag:
            return
        if " " in tag:
            QMessageBox.warning(self.dlg.window, "提示", "标签不能包含空格")
            return
        existing = get_tags(self._selected_bvid)
        if tag not in existing:
            set_tags(self._selected_bvid, existing + [tag])
        self._tag_entry.clear()
        self._refresh_tags()
        self._refresh()

    def _auto_suggest(self):
        """根据视频信息自动建议并添加标签"""
        if not self._selected_bvid:
            return
        video = next((v for v in self.gui.monitored_videos if v.get("bvid") == self._selected_bvid), None)
        if not video:
            return
        suggestions = suggest_tags(video)
        existing = set(get_tags(self._selected_bvid))
        new_tags = [t for t in suggestions if t not in existing]
        if not new_tags:
            QMessageBox.information(self.dlg.window, "提示", "没有新的建议标签")
            return
        added = ", ".join(new_tags)
        reply = QMessageBox.question(
            self.dlg.window, "标签建议",
            f"建议添加以下标签：\n{added}\n\n是否添加？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            set_tags(self._selected_bvid, list(existing) + new_tags)
            self._refresh_tags()
            self._refresh()
