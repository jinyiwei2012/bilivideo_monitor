"""
底部状态栏模块 — CustomTkinter 版

本模块负责底部区域的两大部分：
1. 底部操作栏（BottomBar）：提供主要功能按钮
   - 添加监控、立即刷新、删除监控、手动推送
   - 自动刷新开关（Canvas 绘制的圆形开关按钮）

2. 底部状态栏：显示系统运行信息
   - 监控视频数、刷新间隔、当前算法、上次刷新时间、系统状态
"""

import tkinter as tk
import customtkinter as ctk

from ui.theme import C                                     # 颜色主题常量
from ui.helpers import FONT, rounded_rect                  # UI 辅助：字体和圆角矩形绑定


class BottomBar:
    """
    底部操作栏 + 状态栏

    操作栏包含主要功能按钮（添加监控、刷新、删除、推送）和自动刷新开关。
    状态栏显示监控数、刷新间隔、当前算法、预警/微调信息、上次刷新时间和系统状态。
    """

    def __init__(self, root, gui):
        """
        初始化底部栏

        :param root: 根窗口（主窗口的 root frame）
        :param gui: 主 GUI 实例，用于回调各操作
        """
        self.gui = gui
        self._root = root
        self._sb_labels = {}                                # 状态栏标签字典，通过 key（如 "videos"）快速索引更新
        self._build_bottom_bar()                            # 构建操作栏
        self._build_status_bar()                            # 构建状态栏

    def _build_bottom_bar(self):
        """
        构建底部操作栏：
        - 左侧：添加监控（粉色）、立即刷新、删除监控（红色边框）、手动推送（蓝色）
        - 右侧：自动刷新开关（Canvas 绘制圆形开关）
        """
        # 顶部分隔线
        tk.Frame(self._root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = ctk.CTkFrame(self._root, fg_color=C["bg_surface"], height=46, corner_radius=0)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)                           # 固定高度，不随内容扩展

        # 「添加监控」按钮 — 粉色主题
        ctk.CTkButton(
            bar,
            text="＋ 添加监控",
            fg_color=C["bilibili"],
            hover_color=C["bilibili_dim"],
            text_color="#ffffff",
            font=FONT,
            corner_radius=6,
            height=32,
            command=self.gui._add_monitor,
        ).pack(side=tk.LEFT, padx=(12, 4), pady=8)

        # 「立即刷新」按钮
        ctk.CTkButton(
            bar,
            text="🔄 立即刷新",
            fg_color=C["bg_elevated"],
            hover_color=C["bg_hover"],
            text_color=C["text_2"],
            font=FONT,
            corner_radius=6,
            height=32,
            command=self.gui._refresh_data,
        ).pack(side=tk.LEFT, padx=4, pady=8)

        # 「删除监控」按钮 — 红色边框透明底
        ctk.CTkButton(
            bar,
            text="🗑 删除监控",
            fg_color="transparent",
            hover_color=C["bg_hover"],
            text_color=C["danger"],
            font=FONT,
            corner_radius=6,
            height=32,
            border_width=1,
            border_color=C["danger"],
            command=self.gui._remove_monitor,
        ).pack(side=tk.LEFT, padx=4, pady=8)

        # 「手动推送」按钮
        ctk.CTkButton(
            bar,
            text="📤 手动推送",
            fg_color=C.get("accent", "#4A90D9"),
            hover_color=C.get("accent_dim", "#357ABD"),
            text_color="#ffffff",
            font=FONT,
            corner_radius=6,
            height=32,
            command=self.gui._manual_push,
        ).pack(side=tk.LEFT, padx=4, pady=8)

        # ── 自动刷新开关（右侧） ──
        ar_f = ctk.CTkFrame(bar, fg_color=C["bg_surface"], corner_radius=0)
        ar_f.pack(side=tk.RIGHT, padx=14)
        # Canvas 绘制圆形开关按钮
        self._ar_toggle = tk.Canvas(
            ar_f, width=36, height=18, bg=C["bg_surface"], bd=0, highlightthickness=0, cursor="hand2"
        )
        self._ar_toggle.pack(side=tk.LEFT)
        self._ar_toggle.bind("<Button-1>", self.gui._toggle_auto_refresh)   # 点击切换开关
        ctk.CTkLabel(ar_f, text="自动刷新", text_color=C["text_2"], font=FONT, fg_color="transparent").pack(
            side=tk.LEFT, padx=4
        )
        self._draw_toggle(True)                            # 初始状态：开

    def _build_status_bar(self):
        """
        构建底部状态栏：
        - 左对齐字段：监控数、刷新间隔、算法、预警信息、微调信息、上次刷新时间
        - 右对齐字段：系统状态
        所有标签存入 self._sb_labels 字典以便动态更新。
        """
        tk.Frame(self._root, bg=C["border"], height=1).pack(fill=tk.X)
        bar = ctk.CTkFrame(self._root, fg_color=C["bg_surface"], height=22, corner_radius=0)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)                           # 固定高度

        items = [
            ("videos", "监控: 0 个"),       # 监控视频数
            ("interval", "刷新间隔: —"),    # 刷新间隔
            ("algo", "算法: —"),            # 当前使用的预测算法
            ("alert", ""),                  # 预警信息
            ("finetune", ""),               # 微调信息
            ("last_ref", "上次刷新: —"),    # 上次刷新时间
            ("status", "就绪"),             # 系统状态
        ]
        for key, text in items:
            anchor = "e" if key == "status" else "w"
            side = tk.RIGHT if key == "status" else tk.LEFT
            lbl = ctk.CTkLabel(
                bar,
                text=text,
                text_color=C["text_3"],
                font=("Microsoft YaHei UI", 8),
                fg_color="transparent",
                anchor=anchor,
            )
            lbl.pack(side=side, padx=10)
            self._sb_labels[key] = lbl                     # 存储引用供 update_sb 使用

    def _draw_toggle(self, on):
        """
        绘制自动刷新圆形开关按钮

        开关开启时：绿色背景 + 滑块靠右
        开关关闭时：灰色背景 + 滑块靠左

        :param on: 开关状态（True=开，False=关）
        """
        c = self._ar_toggle
        c.delete("all")
        bg = C["success"] if on else C["bg_hover"]          # 开=绿色，关=灰色
        rounded_rect(c, 0, 0, 36, 18, 9, fill=bg, outline="")
        cx = 26 if on else 10                               # 滑块位置：开→右（26），关→左（10）
        c.create_oval(cx - 7, 2, cx + 7, 16, fill="#ffffff", outline="")

    def update_sb(self, key, text, color=None):
        """
        更新状态栏标签的文本和颜色

        :param key: 标签键名（如 "videos", "status", "last_ref" 等）
        :param text: 新文本内容
        :param color: 可选的新颜色，默认使用原色
        """
        lbl = self._sb_labels.get(key)
        if lbl:
            lbl.configure(text=text, text_color=color or C["text_3"])

    @property
    def ar_toggle(self):
        """
        返回自动刷新开关 Canvas 对象

        :return: 开关 Canvas 控件引用
        """
        return self._ar_toggle
