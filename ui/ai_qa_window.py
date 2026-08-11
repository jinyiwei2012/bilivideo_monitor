"""
AI智能问答窗口 — PyQt6 版
聊天气泡风格对话界面，支持 LLM 智能问答
"""

import logging
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QTextCursor

from ui.theme import C
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)


class AIQAWindow(DialogBase):
    """AI智能问答窗口 — 聊天气泡风格对话界面"""

    _answer_ready = pyqtSignal(str, str)  # (answer: str, error: str | None)

    def __init__(self, parent=None, gui=None):
        if parent:
            screen = parent.screen()
            if screen:
                geo = screen.geometry()
                sw, sh = geo.width(), geo.height()
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        super().__init__(
            parent, "AI智能问答助手 ♪",
            (int(sw * 0.48), int(sh * 0.68)),
            modal=False,
        )
        self.gui = gui

        from utils.ai_qa import AIQASession

        self.session = AIQASession()
        if gui:
            self.session.set_context(gui.monitored_videos, gui.history_data, gui.video_dbs)

        self._answer_ready.connect(self._on_answer_ready)
        self._setup_ui()

        # 延迟检查 API 状态
        QTimer.singleShot(200, self._check_api_status)

    def _setup_ui(self):
        """构建对话窗口 UI：API 状态、快捷问题、对话区、输入框"""
        self.header("AI智能问答助手 ♪", "基于监控数据的自然语言问答哦（可离线使用）♪")

        # API 状态提示
        self._api_status = QLabel("")
        self._api_status.setFont(QFont("Microsoft YaHei UI", 8))
        self._api_status.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        self._main_layout.addWidget(self._api_status)

        # 快捷问题按钮（两行）
        quick_widget = QWidget()
        quick_widget.setStyleSheet(f"background-color: {C['bg_surface']};")
        quick_layout = QVBoxLayout(quick_widget)
        quick_layout.setContentsMargins(0, 10, 0, 0)
        quick_layout.setSpacing(4)

        q_buttons = [
            ("◧ 监控概况", "当前监控多少视频？各视频播放量概况？"),
            ("⚡ 增长最快", "哪个视频增长最快？增速是多少？"),
            ("♛ 播放排行", "按播放量从高到低列出所有监控视频"),
            ("♨ 互动排行", "按互动率从高到低排序所有视频有哪些？"),
            ("↗ 今日增量", "今天每个视频的播放增量是多少？"),
            ("△ 异常预警", "有无播放量异常或增速骤降的视频？"),
            ("▦ 周报总结", "总结本周各视频的表现趋势"),
            ("◎ 预测分析", "哪个视频最有望在未来一周突破百万播放？"),
        ]
        row1 = QWidget()
        row1.setStyleSheet(f"background-color: {C['bg_surface']};")
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(4)

        row2 = QWidget()
        row2.setStyleSheet(f"background-color: {C['bg_surface']};")
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(4)

        for i, (text, q) in enumerate(q_buttons):
            btn = QPushButton(text)
            btn.setFont(QFont("Microsoft YaHei UI", 8))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {C['bg_elevated']}; color: {C['text_2']};
                    border: 1px solid {C['border_sub']}; padding: 4px 10px;
                    font-size: 8pt;
                }}
                QPushButton:hover {{
                    background-color: {C['bg_hover']}; color: {C['text_1']};
                }}
            """)
            btn.clicked.connect(lambda checked, qq=q: self._quick_ask(qq))
            target = row1_layout if i < 4 else row2_layout
            target.addWidget(btn)

        row1_layout.addStretch()
        row2_layout.addStretch()
        quick_layout.addWidget(row1)
        quick_layout.addWidget(row2)

        self._main_layout.addWidget(quick_widget)

        # 对话区（QTextEdit + HTML 样式）
        self._chat_text = QTextEdit()
        self._chat_text.setReadOnly(True)
        self._chat_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                font-family: "Microsoft YaHei UI"; font-size: 10pt;
                border: 1px solid {C['border_sub']};
                padding: 14px 10px;
            }}
        """)
        self._main_layout.addWidget(self._chat_text, 1)

        # 输入区
        input_container = QWidget()
        input_container.setStyleSheet(f"background-color: {C['bg_surface']};")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 10, 0, 0)

        self._input_entry = QTextEdit()
        self._input_entry.setMaximumHeight(80)
        self._input_entry.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                font-family: "Microsoft YaHei UI"; font-size: 10pt;
                border: 1px solid {C['border']};
                padding: 6px 8px;
            }}
        """)
        self._input_entry.installEventFilter(self)
        input_layout.addWidget(self._input_entry, 1)

        self._send_btn = QPushButton("发送 ♪")
        self._send_btn.setProperty("primary", True)
        style = self._send_btn.style()
        if style is not None:
            style.unpolish(self._send_btn)
            style.polish(self._send_btn)
        self._send_btn.clicked.connect(self._send)
        input_layout.addWidget(self._send_btn)

        self._main_layout.addWidget(input_container)

        self._show_welcome()

    def eventFilter(self, a0, a1):
        """捕获 Enter/Shift+Enter 事件"""
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent

        if a0 is self._input_entry and isinstance(a1, QKeyEvent):
            if a1.key() == Qt.Key.Key_Return and not (a1.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._send()
                return True
        return super().eventFilter(a0, a1)

    def _check_api_status(self):
        """检查LLM API连接状态"""
        if self.session.api_key:
            self._api_status.setText(f"✓ LLM 已连接啦 ♪ ({self.session.model})")
            self._api_status.setStyleSheet(f"color: {C['success']}; background: transparent;")
        else:
            self._api_status.setText("△ 还没配置 API 密钥呢，先用离线规则回答哦（设置 → AI配置）♪")
            self._api_status.setStyleSheet(f"color: {C['warning']}; background: transparent;")

    def _show_welcome(self):
        """显示欢迎信息"""
        self._chat_text.clear()
        html = self._build_message(
            "assistant",
            self._welcome_text(),
        )
        self._chat_text.setHtml(html)
        self._scroll_to_bottom()

    def _welcome_text(self) -> str:
        """返回欢迎文本"""
        if self.gui and not self.gui.monitored_videos:
            return (
                "你好呀！现在还没有监控数据呢…♪\n\n"
                "先到主界面添加视频到监控列表哦：\n"
                "1. 点击「▣ 视频搜索」搜索视频\n"
                "2. 在搜索列表里点「+ 监控」添加\n"
                "3. 或者手动输入 BV 号添加\n\n"
                "添加视频之后，我就能帮你分析播放趋势、预测达标时间啦 ♪\n"
            )
        return (
            "你好呀！我是你的监控小助手哦 ♪ 你可以问我：\n"
            "• 当前监控情况\n"
            "• 哪个视频增长最快\n"
            "• 播放量排行\n"
            "• 有没有异常预警\n"
            "• 健康探针情况\n\n"
            "或者直接输入任意问题哦。\n"
        )

    def _quick_ask(self, question: str):
        """点击快捷问题按钮：填入输入框并自动发送"""
        self._input_entry.setPlainText(question)
        self._send()

    def _send(self):
        """发送用户输入的问题"""
        question = self._input_entry.toPlainText().strip()
        if not question:
            return

        self._input_entry.clear()

        # 更新上下文（确保数据最新）
        if self.gui:
            self.session.set_context(self.gui.monitored_videos, self.gui.history_data, self.gui.video_dbs)

        # 追加用户消息
        self._append_chat("user", f"你\n{question}")

        # 异步回答
        self._send_btn.setEnabled(False)
        self._chat_text.setReadOnly(True)

        # 显示"思考中..."占位
        self._append_chat("assistant", "助手\n思考中哦…♪")
        self._thinking_placeholder = True

        t = threading.Thread(target=self._do_ask, args=(question,), daemon=True)
        t.start()

    def _do_ask(self, question: str):
        """后台线程：调用 LLM 获取回答"""
        try:
            answer = self.session.ask(question)
            self._answer_ready.emit(answer, "")
        except Exception as e:
            logger.error("AI问答失败", exc_info=True)
            self._answer_ready.emit("", "呜…回答失败啦，请稍后再试哦 ♪")

    def _on_answer_ready(self, answer: str, error: str):
        """主线程回调：更新回答"""
        self._send_btn.setEnabled(True)

        if error:
            self._replace_last_assistant(f"助手\n{error}")
            return

        self._replace_last_assistant(f"助手\n{answer}")

    def _append_chat(self, role: str, text: str):
        """追加一段聊天内容到 QTextEdit"""
        html = self._build_message(role, text)
        cursor = self._chat_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._chat_text.setTextCursor(cursor)
        self._chat_text.insertHtml(html)
        self._scroll_to_bottom()

    def _replace_last_assistant(self, text: str):
        """替换最后一段助手回复（替换"思考中..."占位）"""
        html = self._build_message("assistant", text)
        full_html = self._chat_text.toHtml()
        # 用正则或简单字符串替换找最后一个 assistant 消息
        # 更可靠的方式：清除最后一段 HTML 标记再追加
        doc = self._chat_text.document()
        if doc is not None:
            block = doc.lastBlock()
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        # 再追加新内容
        self._append_chat("assistant", text.split("\n", 1)[1] if "\n" in text else text)

    def _scroll_to_bottom(self):
        """滚动到 QTextEdit 底部"""
        scrollbar = self._chat_text.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    @staticmethod
    def _build_message(role: str, content: str) -> str:
        """构建单条消息的 HTML（用户蓝色粗体 / 助手绿色粗体 + 内容）"""
        if role == "user":
            role_color = C["bilibili"]
        else:
            role_color = C["success"]

        lines = []
        parts = content.split("\n", 1)
        if len(parts) == 2:
            header, body = parts[0], parts[1]
            lines.append(
                f'<p style="margin:8px 0 0 0;"><span style="'
                f'color:{role_color}; font-weight:bold; font-size:10pt;">'
                f'{_html_escape(header)}</span></p>'
            )
            lines.append(
                f'<p style="margin:2px 0 6px 0;"><span style="'
                f'color:{C["text_1"]}; font-size:10pt;">'
                f'{_html_escape(body)}</span></p>'
            )
        else:
            lines.append(
                f'<p style="margin:8px 0 6px 0;"><span style="'
                f'color:{role_color}; font-weight:bold; font-size:10pt;">'
                f'{_html_escape(content)}</span></p>'
            )
        return "".join(lines)


def _html_escape(text: str) -> str:
    """转义 HTML 特殊字符"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )
