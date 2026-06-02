"""
AI智能问答窗口模块

本模块实现了基于 Tkinter 的聊天气泡风格对话界面，允许用户以自然语言
向 AI 助手询问关于监控视频的各种问题（如播放概况、增长排行、异常预警等）。

支持两种回答模式：
1. 离线规则模式（未配置 API 密钥时）：基于内置规则匹配回答
2. LLM 在线模式（配置 API 密钥后）：调用远程大语言模型进行智能分析

对话界面包含快捷问题按钮、上下文感知、异步回答（后台线程不阻塞 UI）。
"""

import tkinter as tk
from tkinter import ttk

from ui.theme import C                                       # 颜色主题常量
from ui.dialog_base import DialogBase                        # 现代化对话框基类


class AIQAWindow:
    """
    AI智能问答窗口 — 聊天气泡风格对话界面

    使用 DialogBase 构建统一的弹窗样式，支持：
    - 快捷问题按钮（一次性填入并发送）
    - 聊天气泡式文本展示（用户消息粉色、助手消息绿色）
    - 异步后台 LLM 调用（通过工作线程，不阻塞 UI）
    - 上下文自动更新（每次提问前同步最新的监控数据）
    """

    def __init__(self, parent=None, gui=None):
        """
        初始化 AI 问答窗口

        :param parent: 父级 Tkinter 窗口
        :param gui:   主 GUI 实例（BilibiliMonitorGUI），用于获取监控数据和状态
        """
        # 创建基础对话框窗口
        self.dlg = DialogBase(
            parent, "AI智能问答助手", DialogBase.calc_geometry(parent, 0.48, 0.68), resizable=(True, True), modal=False
        )
        self.window = self.dlg.window                     # 顶层窗口引用
        self.gui = gui                                    # 主 GUI 实例引用

        from utils.ai_qa import AIQASession

        self.session = AIQASession()                      # 创建 AI 问答会话对象
        if gui:
            # 将当前监控数据注入会话上下文
            self.session.set_context(gui.monitored_videos, gui.history_data, gui.video_dbs)

        self._setup_ui()                                  # 构建对话界面

    def _setup_ui(self):
        """
        构建对话窗口 UI：
        1. 顶部标题栏（含副标题说明）
        2. API 连接状态提示条
        3. 8 个快捷问题按钮（两行排列）
        4. 聊天记录文本区域（带滚动条）
        5. 底部输入框（支持 Enter 发送、Shift+Enter 换行）
        """
        self.dlg.header("AI智能问答助手", "基于监控数据的自然语言问答（可离线使用）")

        # ── API 状态提示 ──
        self._api_status = tk.Label(self.dlg.container, font=("Microsoft YaHei UI", 8), anchor="w", bg=C["bg_surface"])
        self._api_status.pack(fill=tk.X, padx=28, pady=(4, 0))

        # 延迟 200ms 检查 API 配置状态（避免阻塞窗口创建）
        self.window.after(200, self._check_api_status)

        # ── 快捷问题按钮 ──
        quick = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        quick.pack(fill=tk.X, padx=24, pady=(10, 0))
        qf1 = tk.Frame(quick, bg=C["bg_surface"])        # 第一行（前 4 个按钮）
        qf1.pack(fill=tk.X, pady=1)
        qf2 = tk.Frame(quick, bg=C["bg_surface"])        # 第二行（后 4 个按钮）
        qf2.pack(fill=tk.X, pady=1)
        # 按钮列表：(显示文字, 对应问题文本)
        q_buttons = [
            ("📊 监控概况", "当前监控多少视频？各视频播放量概况？"),
            ("⚡ 增长最快", "哪个视频增长最快？增速是多少？"),
            ("🏆 播放排行", "按播放量从高到低列出所有监控视频"),
            ("🔥 互动排行", "按互动率从高到低排序所有视频有哪些？"),
            ("📈 今日增量", "今天每个视频的播放增量是多少？"),
            ("⚠️ 异常预警", "有无播放量异常或增速骤降的视频？"),
            ("📅 周报总结", "总结本周各视频的表现趋势"),
            ("🎯 预测分析", "哪个视频最有望在未来一周突破百万播放？"),
        ]
        for i, (text, q) in enumerate(q_buttons):
            parent_frame = qf1 if i < 4 else qf2           # 前 4 个放第一行
            ttk.Button(parent_frame, text=text, command=lambda q=q: self._quick_ask(q)).pack(side=tk.LEFT, padx=2)

        # ── 对话区（聊天记录） ──
        chat_frame = tk.Frame(
            self.dlg.container, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"]
        )
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        self._chat_text = tk.Text(
            chat_frame,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            state="disabled",                              # 初始只读，通过代码写入
            cursor="arrow",
            padx=14,
            pady=10,
            wrap="word",
        )
        vsb = ttk.Scrollbar(chat_frame, orient="vertical", command=self._chat_text.yview)
        self._chat_text.config(yscrollcommand=vsb.set)
        self._chat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 文本标签配置（用于聊天气泡的颜色分类）
        self._chat_text.tag_configure("user", foreground=C["bilibili"], font=("Microsoft YaHei UI", 10, "bold"))
        self._chat_text.tag_configure("assistant", foreground=C["success"], font=("Microsoft YaHei UI", 10, "bold"))
        self._chat_text.tag_configure(
            "content", foreground=C["text_1"], font=("Microsoft YaHei UI", 10), spacing1=2, spacing3=4
        )

        # ── 输入区 ──
        input_frame = tk.Frame(self.dlg.container, bg=C["bg_surface"])
        input_frame.pack(fill=tk.X, padx=24, pady=(10, 16))

        input_box = tk.Frame(input_frame, bg=C["border"], highlightthickness=1, highlightbackground=C["border"])
        input_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._input_entry = tk.Text(
            input_box,
            height=3,
            bg=C["bg_elevated"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 10),
            insertbackground=C["text_1"],
            relief="flat",
            highlightthickness=0,
            padx=8,
            pady=6,
            wrap="word",
        )
        self._input_entry.pack(fill=tk.BOTH, expand=True)
        # Enter 发送消息（Shift+Enter 换行）
        self._input_entry.bind("<Return>", lambda e: self._send() if not (e.state & 0x1) else None)
        self._input_entry.bind("<Shift-Return>", lambda e: self._input_entry.insert(tk.END, "\n"))

        self._send_btn = ttk.Button(input_frame, text="发送", command=self._send, style="Primary.TButton")
        self._send_btn.pack(side=tk.RIGHT, padx=(8, 0), ipadx=10)

        self._show_welcome()                               # 显示欢迎信息

    def _check_api_status(self):
        """
        检查 LLM API 连接状态并更新顶部状态提示
        - 已配置 API 密钥：显示绿色「LLM已连接」及模型名称
        - 未配置：显示黄色警告，提示用户在设置中配置
        """
        if self.session.api_key:
            self._api_status.config(text=f"✅ LLM已连接 ({self.session.model})", fg=C["success"])
        else:
            self._api_status.config(text="⚠️ 未配置API密钥，使用离线规则回答（设置 → AI配置）", fg=C["warning"])

    def _show_welcome(self):
        """
        显示欢迎信息
        - 当无监控数据时：引导用户添加视频
        - 当有监控数据时：列出可询问的问题示例
        """
        self._chat_text.config(state="normal")
        self._chat_text.delete("1.0", tk.END)
        self._chat_text.insert(tk.END, "助手\n", "assistant")

        if self.gui and not self.gui.monitored_videos:
            # 无监控数据时的引导提示
            self._chat_text.insert(
                tk.END,
                (
                    "你好！当前还没有监控数据。\n\n"
                    "请先在主界面添加视频到监控列表：\n"
                    "1. 点击「📁 视频搜索」搜索视频\n"
                    "2. 在搜索列表中点击「+ 监控」添加\n"
                    "3. 或手动输入 BV 号添加\n\n"
                    "添加视频后，我可以帮你分析播放趋势、预测达标时间等。\n"
                ),
                "content",
            )
        else:
            # 有监控数据时的功能说明
            self._chat_text.insert(
                tk.END,
                (
                    "你好！我是监控助手。你可以问我：\n"
                    "• 当前监控情况\n"
                    "• 哪个视频增长最快\n"
                    "• 播放量排行\n"
                    "• 有无异常预警\n"
                    "• 健康探针情况\n\n"
                    "或者直接输入任意问题。\n"
                ),
                "content",
            )
        self._chat_text.config(state="disabled")

    def _quick_ask(self, question: str):
        """
        点击快捷问题按钮：将预设问题填入输入框并自动发送

        :param question: 预设的问题文本
        """
        self._input_entry.delete("1.0", tk.END)
        self._input_entry.insert(tk.END, question)
        self._send()

    def _send(self):
        """
        发送用户输入的问题：
        1. 获取并清空输入框内容
        2. 更新会话上下文（确保数据最新）
        3. 在对话区显示用户消息
        4. 异步调用 AI 获取回答
        """
        question = self._input_entry.get("1.0", tk.END).strip()
        if not question:
            return

        self._input_entry.delete("1.0", tk.END)

        # 更新上下文（确保 AI 每次提问前拿到最新的监控数据）
        if self.gui:
            self.session.set_context(self.gui.monitored_videos, self.gui.history_data, self.gui.video_dbs)

        # 显示用户消息
        self._chat_text.config(state="normal")
        self._chat_text.insert(tk.END, "\n你\n", "user")
        self._chat_text.insert(tk.END, f"{question}\n", "content")
        self._chat_text.see(tk.END)                        # 自动滚动到底部
        self._chat_text.config(state="disabled")
        self.window.update_idletasks()                      # 强制刷新 UI

        # 禁用发送按钮，异步获取回答
        self._send_btn.config(state="disabled")
        self.window.after(50, lambda: self._do_answer(question))

    def _do_answer(self, question: str):
        """
        在后台线程调用 LLM，避免阻塞 UI：
        1. 显示「思考中...」占位文本
        2. 启动 daemon 线程执行 LLM 调用
        3. 完成后通过 window.after 回主线程更新 UI
        """
        self._send_btn.config(state="disabled")
        # 先显示"思考中..."占位
        self._chat_text.config(state="normal")
        self._chat_text.insert(tk.END, "\n助手\n", "assistant")
        self._chat_text.insert(tk.END, "思考中...\n", "content")
        self._chat_text.see(tk.END)
        self._chat_text.config(state="disabled")
        self.window.update_idletasks()

        import threading

        def _worker():
            """工作线程：调用 AI 获取回答"""
            answer = self.session.ask(question)
            # 通过 after 将结果投递回主线程
            self.window.after(0, _update_ui, answer)

        def _update_ui(answer):
            """
            用真实回答替换"思考中..."占位
            使用 rfind 定位最后一个「思考中...」的位置并精准替换
            """
            self._chat_text.config(state="normal")
            content = self._chat_text.get("1.0", tk.END)
            last_assistant = content.rfind("思考中...")
            if last_assistant >= 0:
                # 找到占位文本，精确替换
                self._chat_text.delete("1.0", tk.END)
                self._chat_text.insert(tk.END, content[:last_assistant], "")
                self._chat_text.insert(tk.END, "\n助手\n", "assistant")
                self._chat_text.insert(tk.END, f"{answer}\n", "content")
            else:
                # 找不到占位（异常情况），直接追加
                self._chat_text.insert(tk.END, "\n助手\n", "assistant")
                self._chat_text.insert(tk.END, f"{answer}\n", "content")
            self._chat_text.see(tk.END)
            self._chat_text.config(state="disabled")
            self._send_btn.config(state="normal")

        threading.Thread(target=_worker, daemon=True).start()
