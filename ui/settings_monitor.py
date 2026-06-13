"""
监控参数设置

Mixin functions for SettingsWindow.
"""

import tkinter as tk
from tkinter import ttk
from ui.theme import C
from ui.helpers import FONT_SM, auto_threshold_name


def _build_monitor_tab(self, nb):
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  监控参数  ")

    sec = self._section(page, "基础参数")
    self.max_monitors = self._spin_field(
        sec, "最大监控数", self._cfg.get("monitor", {}).get("max_monitor_count", 100), 10, 500
    )

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

    self._thresh_rows: list = []

    raw = self._cfg.get("prediction", {}).get("thresholds", [])
    if raw and isinstance(raw[0], (list, tuple)):
        th_data = [(int(v), str(n)) for v, n in raw]
    else:
        th_data = (
            [(int(v), auto_threshold_name(v)) for v in raw]
            if raw
            else [(100000, "10万"), (1000000, "100万"), (10000000, "1000万")]
        )

    for v, n in sorted(th_data, key=lambda x: x[0]):
        self._add_threshold_row(th_list_frame, v, n)

    add_btn = ttk.Button(th_sec, text="+ 添加阈值", command=lambda: self._add_threshold_row(th_list_frame))
    add_btn.pack(anchor="w", padx=0)


def _add_threshold_row(self, parent, value=100000, name=""):
    row = tk.Frame(parent, bg=C["bg_elevated"])
    row.pack(fill=tk.X, pady=2)

    v_var = tk.StringVar(value=str(int(value)))
    n_var = tk.StringVar(value=name or auto_threshold_name(value))

    tk.Label(row, text="播放量:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    v_spin = ttk.Spinbox(row, from_=1000, to=999_999_999, textvariable=v_var, width=14, font=FONT_SM)
    v_spin.pack(side=tk.LEFT, padx=(2, 8))

    tk.Label(row, text="名称:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    n_entry = ttk.Entry(row, textvariable=n_var, width=12, font=FONT_SM)
    n_entry.pack(side=tk.LEFT, padx=(2, 8))

    del_btn = tk.Label(
        row, text="✕", bg=C["bg_elevated"], fg=C["danger"], font=("Segoe UI", 10, "bold"), cursor="hand2"
    )
    del_btn.pack(side=tk.LEFT, padx=2)
    del_btn.bind("<Button-1>", lambda e: (row.destroy(), self._thresh_rows.remove((v_var, n_var, row))))

    self._thresh_rows.append((v_var, n_var, row))
