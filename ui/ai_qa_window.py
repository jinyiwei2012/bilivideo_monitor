"""
AI智能问答窗口 — 聊天气泡风格对话界面
"""
import tkinter as tk
from tkinter import ttk
from typing import Optional

from ui.theme import C
from ui.dialog_base import DialogBase


class AIQAWindow:
    """AI智能问答窗口"""

    def __init__(self, parent=None, gui=None):
        self.dlg = DialogBase(parent, "AI智能问答助手", "720x520",
                              resizable=(True, True))
        self.window = self.dlg.window
        self.gui = gui

        from utils.ai_qa import AIQASession
        self.session = AIQASession()
        if gui:
            self.session.set_context(
                gui.monitored_videos, gui.history_data, gui.video_dbs)

        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("AI智能问答助手",
                        "基于监控数据的自然语言问答（可离线使用）")

        # 快捷问题按钮
        quick = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        quick.pack(fill=tk.X, padx=24, pady=(10, 0))
        ttk.Button(quick, text="📊 当前监控多少视频？",
                   command=lambda: self._quick_ask("当前监控多少视频？")).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick, text="⚡ 哪个增长最快？",
                   command=lambda: self._quick_ask("哪个视频增长最快？")).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick, text="🏆 播放量排行",
                   command=lambda: self._quick_ask("播放量排行？")).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick, text="⚠️ 有无异常预警",
                   command=lambda: self._quick_ask("有无异常预警？")).pack(side=tk.LEFT, padx=2)

        # 对话区
        chat_frame = tk.Frame(self.dlg.container, bg=C["bg_elevated"],
                              highlightthickness=1,
                              highlightbackground=C["border_sub"])
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        self._chat_text = tk.Text(chat_frame, bg=C["bg_base"], fg=C["text_1"],
                                  font=("Microsoft YaHei UI", 10), relief="flat",
                                  state="disabled", cursor="arrow",
                                  padx=14, pady=10, wrap="word")
        vsb = ttk.Scrollbar(chat_frame, orient="vertical",
                            command=self._chat_text.yview)
        self._chat_text.config(yscrollcommand=vsb.set)
        self._chat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 标签配置
        self._chat_text.tag_configure("user", foreground=C["bilibili"],
                                       font=("Microsoft YaHei UI", 10, "bold"))
        self._chat_text.tag_configure("assistant", foreground=C["success"],
                                       font=("Microsoft YaHei UI", 10, "bold"))
        self._chat_text.tag_configure("content", foreground=C["text_1"],
                                       font=("Microsoft YaHei UI", 10),
                                       spacing1=2, spacing3=4)

        # 输入区
        input_frame = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        input_frame.pack(fill=tk.X, padx=24, pady=(10, 16))

        self._input_entry = tk.Text(input_frame, height=3,
                                     bg=C["bg_elevated"], fg=C["text_1"],
                                     font=("Microsoft YaHei UI", 10),
                                     insertbackground=C["text_1"],
                                     relief="flat", highlightthickness=1,
                                     highlightbackground=C["border"],
                                     padx=8, pady=6, wrap="word")
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._input_entry.bind("<Return>", lambda e: self._send() if not (e.state & 0x1) else None)
        self._input_entry.bind("<Shift-Return>", lambda e: self._input_entry.insert(tk.END, "\n"))

        self._send_btn = ttk.Button(input_frame, text="发送", command=self._send,
                                     style="Primary.TButton")
        self._send_btn.pack(side=tk.RIGHT, padx=(8, 0), ipadx=10)

        self._show_welcome()

    def _show_welcome(self):
        self._chat_text.config(state="normal")
        self._chat_text.delete("1.0", tk.END)
        self._chat_text.insert(tk.END, "助手\n", "assistant")
        self._chat_text.insert(tk.END, "你好！我是监控助手。你可以问我：\n"
                               "• 当前监控情况\n"
                               "• 哪个视频增长最快\n"
                               "• 播放量排行\n"
                               "• 有无异常预警\n"
                               "• 健康探针情况\n\n"
                               "或者直接输入任意问题。\n", "content")
        self._chat_text.config(state="disabled")

    def _quick_ask(self, question: str):
        self._input_entry.delete("1.0", tk.END)
        self._input_entry.insert(tk.END, question)
        self._send()

    def _send(self):
        question = self._input_entry.get("1.0", tk.END).strip()
        if not question:
            return

        self._input_entry.delete("1.0", tk.END)

        # 更新上下文
        if self.gui:
            self.session.set_context(
                self.gui.monitored_videos, self.gui.history_data, self.gui.video_dbs)

        self._chat_text.config(state="normal")
        self._chat_text.insert(tk.END, f"\n你\n", "user")
        self._chat_text.insert(tk.END, f"{question}\n", "content")
        self._chat_text.see(tk.END)
        self._chat_text.config(state="disabled")
        self.window.update_idletasks()

        # 异步回答
        self._send_btn.config(state="disabled")
        self.window.after(50, lambda: self._do_answer(question))

    def _do_answer(self, question: str):
        answer = self.session.ask(question)
        self._chat_text.config(state="normal")
        self._chat_text.insert(tk.END, f"\n助手\n", "assistant")
        self._chat_text.insert(tk.END, f"{answer}\n", "content")
        self._chat_text.see(tk.END)
        self._chat_text.config(state="disabled")
        self._send_btn.config(state="normal")
