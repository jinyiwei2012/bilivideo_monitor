"""
报告定时器设置窗口 — 手动或定时生成数据报告
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox

from ui.theme import C
from ui.dialog_base import DialogBase


class ReportSchedulerWindow:
    """报告导出与定时器设置窗口"""

    def __init__(self, parent=None, gui=None):
        self.dlg = DialogBase(parent, "定时导出报告",
                              DialogBase.calc_geometry(parent, 0.38, 0.56),
                              resizable=(True, True), modal=False)
        self.window = self.dlg.window
        self.gui = gui
        self._scheduled_jobs = []
        self._setup_ui()

    def _setup_ui(self):
        self.dlg.header("定时导出报告", "生成HTML/Excel格式的数据报告")

        # 手动导出卡片
        sec = self.dlg.section(title="手动导出", padding=10)
        row = tk.Frame(sec, bg=C["bg_elevated"])
        row.pack(fill=tk.X)

        tk.Label(row, text="导出格式:", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 10)).pack(
            side=tk.LEFT
        )
        self._format_var = tk.StringVar(value="html")
        tk.Radiobutton(row, text="HTML", variable=self._format_var, value="html", bg=C["bg_elevated"]).pack(
            side=tk.LEFT, padx=6
        )
        tk.Radiobutton(row, text="Excel", variable=self._format_var, value="excel", bg=C["bg_elevated"]).pack(
            side=tk.LEFT, padx=6
        )
        tk.Radiobutton(row, text="两者", variable=self._format_var, value="both", bg=C["bg_elevated"]).pack(
            side=tk.LEFT, padx=6
        )

        ttk.Button(sec, text="立即导出", command=self._export_now, style="Primary.TButton").pack(
            anchor="w", padx=4, pady=(8, 0)
        )

        self._export_status = tk.Label(
            sec, text="", bg=C["bg_elevated"], fg=C["text_2"], font=("Microsoft YaHei UI", 9)
        )
        self._export_status.pack(anchor="w", padx=4, pady=(4, 0))

        # 定时设置卡片
        sec2 = self.dlg.section(title="定时设置（开发中）", padding=10)
        tk.Label(
            sec2,
            text="定时导出功能将在后续版本中支持。\n目前可使用「立即导出」手动生成报告。",
            bg=C["bg_elevated"],
            fg=C["text_3"],
            font=("Microsoft YaHei UI", 9),
            anchor="w",
            justify="left",
        ).pack(fill=tk.X, padx=4, pady=4)

        # 已导出文件列表
        sec3 = self.dlg.section(title="已导出文件", padding=8)
        self._file_list = tk.Listbox(
            sec3,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Consolas", 9),
            height=6,
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self._file_list.pack(fill=tk.BOTH, expand=True)

        self._refresh_file_list()

        btn_row = tk.Frame(sec3, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text="🔄 刷新列表", command=self._refresh_file_list).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="📂 打开文件夹", command=self._open_folder).pack(side=tk.LEFT, padx=2)

    def _export_now(self):
        if not self.gui or not self.gui.monitored_videos:
            messagebox.showwarning("提示", "暂无监控视频数据", parent=self.window)
            return

        fmt = self._format_var.get()
        self._export_status.config(text="正在导出...", fg=C["text_2"])
        self.window.update_idletasks()

        from utils.report_exporter import export_html, export_excel

        results = []
        try:
            if fmt in ("html", "both"):
                path = export_html(self.gui.monitored_videos)
                results.append(f"HTML: {path}")
            if fmt in ("excel", "both"):
                path = export_excel(self.gui.monitored_videos)
                results.append(f"Excel: {path}")

            self._export_status.config(text="导出完成！\n" + "\n".join(results), fg=C["success"])
            self._refresh_file_list()
        except Exception as e:
            self._export_status.config(text=f"导出失败: {e}", fg=C["danger"])

    def _refresh_file_list(self):
        self._file_list.delete(0, tk.END)
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        if os.path.isdir(reports_dir):
            files = sorted(os.listdir(reports_dir), reverse=True)[:20]
            for f in files:
                size = os.path.getsize(os.path.join(reports_dir, f))
                size_str = f"{size / 1024:.1f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"
                self._file_list.insert(tk.END, f"{f}  ({size_str})")

    def _open_folder(self):
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        os.startfile(reports_dir)
