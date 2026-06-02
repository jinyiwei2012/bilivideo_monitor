"""
监控参数设置模块
================

本模块为 ``SettingsWindow`` 提供 mixin 函数，构建「监控参数」标签页。
包含两个配置区域：
  - 基础参数：检查间隔（秒）、最大监控数
  - 播放量阈值：动态列表，每个阈值代表一个里程碑，达到时触发推送提醒

阈值行支持：
  - 添加新阈值（+ 按钮）
  - 编辑阈值数值和名称
  - 删除阈值（✕ 按钮）
  - 默认预置 3 个阈值：10万、100万、1000万

所有函数由 ``settings_window.py`` 中 SettingsWindow 通过 monkey-patch 方式附加为实例方法。
"""

import tkinter as tk
from tkinter import ttk
from ui.theme import C
from ui.helpers import FONT, FONT_SM, auto_threshold_name


def _build_monitor_tab(self, nb):
    """
    构建「监控参数」标签页并注册到 Notebook。

    :param self: SettingsWindow 实例（隐式）
    :param nb: ttk.Notebook 控件，标签页容器
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  监控参数  ")

    # ── 基础参数区域 ──
    sec = self._section(page, "基础参数")
    self.check_interval = self._spin_field(
        sec, "检查间隔(秒)", self._cfg.get("monitor", {}).get("check_interval", 300), 60, 3600
    )
    self.max_monitors = self._spin_field(
        sec, "最大监控数", self._cfg.get("monitor", {}).get("max_monitor_count", 100), 10, 500
    )

    # ── 播放量阈值区域 ──
    th_sec = self._section(page, "播放量阈值", padding=(16, 8, 12))
    tk.Label(
        th_sec,
        text="每个阈值代表一个里程碑，达到时触发推送提醒",
        bg=C["bg_elevated"],
        fg=C["text_3"],
        font=FONT_SM,
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 6))

    th_list_frame = tk.Frame(th_sec, bg=C["bg_elevated"])
    th_list_frame.pack(fill=tk.X, pady=(0, 6))

    self._thresh_rows: list = []  # 阈值行引用列表: [(v_var, n_var, row_frame), ...]

    # 加载已保存的阈值配置，兼容旧版格式
    raw = self._cfg.get("prediction", {}).get("thresholds", [])
    if raw and isinstance(raw[0], (list, tuple)):
        # 新版格式：[[value, name], ...]
        th_data = [(int(v), str(n)) for v, n in raw]
    else:
        # 旧版格式：纯数值列表，自动生成名称
        th_data = (
            [(int(v), auto_threshold_name(v)) for v in raw]
            if raw
            else [(100000, "10万"), (1000000, "100万"), (10000000, "1000万")]
        )

    # 按数值从小到大排列阈值行
    for v, n in sorted(th_data, key=lambda x: x[0]):
        self._add_threshold_row(th_list_frame, v, n)

    # 添加阈值按钮
    add_btn = ttk.Button(th_sec, text="+ 添加阈值", command=lambda: self._add_threshold_row(th_list_frame))
    add_btn.pack(anchor="w", padx=0)


def _add_threshold_row(self, parent, value=100000, name=""):
    """
    在阈值列表中动态追加一行，包含：播放量 Spinbox、名称 Entry、删除按钮。

    删除按钮绑定了 Lambda，会 destroy 行 Frame 并从 _thresh_rows 中移除。
    新行的默认值为 100000，名称为自动生成（如 "10万"）。

    :param self: SettingsWindow 实例（隐式）
    :param parent: 阈值行容器 Frame
    :param value: 默认播放量数值
    :param name: 默认阈值名称（为空时自动生成）
    """
    row = tk.Frame(parent, bg=C["bg_elevated"])
    row.pack(fill=tk.X, pady=2)

    v_var = tk.StringVar(value=str(int(value)))  # 播放量数值变量
    n_var = tk.StringVar(value=name or auto_threshold_name(value))  # 阈值名称变量

    # 播放量输入（带标签）
    tk.Label(row, text="播放量:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    v_spin = ttk.Spinbox(row, from_=1000, to=999_999_999, textvariable=v_var, width=14, font=FONT_SM)
    v_spin.pack(side=tk.LEFT, padx=(2, 8))

    # 名称输入（带标签）
    tk.Label(row, text="名称:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    n_entry = ttk.Entry(row, textvariable=n_var, width=12, font=FONT_SM)
    n_entry.pack(side=tk.LEFT, padx=(2, 8))

    # 删除按钮（✕）— 同时清理 UI 和引用
    del_btn = tk.Label(
        row, text="✕", bg=C["bg_elevated"], fg=C["danger"], font=("Segoe UI", 10, "bold"), cursor="hand2"
    )
    del_btn.pack(side=tk.LEFT, padx=2)
    del_btn.bind("<Button-1>", lambda e: (row.destroy(), self._thresh_rows.remove((v_var, n_var, row))))

    self._thresh_rows.append((v_var, n_var, row))
