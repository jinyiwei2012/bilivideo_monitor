"""
报告定时器设置窗口模块 — 手动或定时生成数据报告（CSV/JSON/HTML/Excel）

支持:
  - 手动导出: 按选定格式立即导出监控数据报告
  - 预测对比表导出: 导出预测值 vs 实际播放量的对照表
  - 定时导出: 按计划自动导出到 reports/ 目录，支持 hourly/daily/weekly 间隔
  - 已导出文件列表: 查看和打开已导出的报告文件

配置持久化: 定时设置保存到 data/.export_schedule.json

主要组件:
    ReportSchedulerWindow — 报告导出与定时器设置窗口
"""

import os
import json
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from ui.theme import C, FONT
from ui.dialog_base import DialogBase
from config import DATA_DIR

logger = logging.getLogger(__name__)

# 定时导出配置文件路径
_SCHEDULE_CONFIG = Path(DATA_DIR) / ".export_schedule.json"


class ReportSchedulerWindow:
    """报告导出与定时器设置窗口

    提供三种导出模式:
      1. 手动导出 — 立即按选定格式导出
      2. 预测对比 — 导出预测值 vs 实际值对比表
      3. 定时导出 — 按计划自动导出
    """

    def __init__(self, parent=None, gui=None):
        """
        Args:
            parent: 父窗口
            gui: BilibiliMonitorGUI 实例（用于访问监控数据）
        """
        sw = parent.winfo_screenwidth() if parent else 1920
        sh = parent.winfo_screenheight() if parent else 1080
        self.dlg = DialogBase(
            parent, "定时导出报告", f"{int(sw * 0.42)}x{int(sh * 0.60)}", resizable=(True, True), modal=False
        )
        self.window = self.dlg.window
        self.gui = gui
        self._scheduled_job = None  # 定时导出的 after 任务 ID
        self._setup_ui()

    def _setup_ui(self):
        """构建报告定时器设置窗口 UI：手动导出 + 定时导出 + 已导出文件列表"""
        self.dlg.header("定时导出报告", "手动导出 / 按计划自动导出 CSV / JSON / HTML / Excel")

        # ── 手动导出 ──
        sec = self.dlg.section(title="手动导出", padding=10)
        row = tk.Frame(sec, bg=C["bg_elevated"])
        row.pack(fill=tk.X)

        tk.Label(row, text="导出格式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        self._format_var = tk.StringVar(value="html")
        for fmt, label in [("html", "HTML"), ("excel", "Excel"), ("csv", "CSV"), ("json", "JSON"), ("both", "所有")]:
            tk.Radiobutton(row, text=label, variable=self._format_var, value=fmt, bg=C["bg_elevated"]).pack(
                side=tk.LEFT, padx=4
            )

        ttk.Button(sec, text="立即导出", command=self._export_now, style="Primary.TButton").pack(
            anchor="w", padx=4, pady=(8, 0)
        )
        self._export_status = tk.Label(sec, text="", bg=C["bg_elevated"], fg=C["text_2"], font=FONT)
        self._export_status.pack(anchor="w", padx=4, pady=(4, 0))

        # 预测对比导出
        ttk.Button(sec, text="📊 导出预测vs实际对比表", command=self._export_pred_vs_actual).pack(
            anchor="w", padx=4, pady=(4, 0)
        )

        # ── 定时导出 ──
        sec2 = self.dlg.section(title="定时导出", padding=10)
        tk.Label(sec2, text="按计划自动导出到 reports/ 目录", bg=C["bg_elevated"], fg=C["text_3"], font=FONT).pack(
            anchor="w"
        )

        row2 = tk.Frame(sec2, bg=C["bg_elevated"])
        row2.pack(fill=tk.X, pady=(6, 0))
        self._schedule_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row2, text="启用定时导出", variable=self._schedule_enabled, command=self._on_schedule_toggle
        ).pack(side=tk.LEFT)

        tk.Label(row2, text="  间隔:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        self._interval_var = tk.StringVar(value="daily")
        interval_menu = ttk.Combobox(
            row2, textvariable=self._interval_var, values=["hourly", "daily", "weekly"], state="readonly", width=8
        )
        interval_menu.pack(side=tk.LEFT, padx=4)

        tk.Label(row2, text="  导出格式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        self._schedule_format_var = tk.StringVar(value="csv")
        ttk.Combobox(
            row2, textvariable=self._schedule_format_var, values=["csv", "json", "html"], state="readonly", width=6
        ).pack(side=tk.LEFT)

        ttk.Button(sec2, text="保存设置", command=self._save_schedule).pack(anchor="w", padx=4, pady=(8, 0))
        self._schedule_status = tk.Label(sec2, text="", bg=C["bg_elevated"], fg=C["text_2"], font=FONT)
        self._schedule_status.pack(anchor="w", padx=4, pady=(2, 0))

        # ── 已导出文件列表 ──
        sec3 = self.dlg.section(title="已导出文件", padding=8)
        self._file_list = tk.Listbox(
            sec3,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Consolas", 9),
            height=8,
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self._file_list.pack(fill=tk.BOTH, expand=True)

        btn_row = tk.Frame(sec3, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text="刷新列表", command=self._refresh_file_list).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="打开文件夹", command=self._open_folder).pack(side=tk.LEFT, padx=2)

        self._refresh_file_list()
        self._load_schedule()

    def _export_pred_vs_actual(self):
        """导出预测值 vs 实际播放量对比表

        从数据库中的预测记录和实际监控记录中提取数据，
        生成预测准确度对比的 CSV 表格。
        """
        if not self.gui or not self.gui.video_dbs:
            messagebox.showwarning("提示", "暂无预测数据", parent=self.window)
            return
        self._export_status.config(text="正在导出预测对比表...", fg=C["text_2"])
        self.window.update_idletasks()
        try:
            from utils.report_exporter import export_prediction_vs_actual

            path = export_prediction_vs_actual(self.gui.video_dbs)
            if path:
                self._export_status.config(text=f"✅ 已导出: {path}", fg=C["success"])
            else:
                self._export_status.config(text="⚠️ 无有效的预测-实际对照数据", fg=C["warning"])
        except Exception as e:
            self._export_status.config(text=f"❌ 导出失败: {e}", fg=C["danger"])

    def _export_now(self):
        """立即按选定格式导出监控数据报告

        支持的格式:
          - html  : HTML 可视化报告
          - excel : Excel 表格
          - csv   : CSV 纯数据
          - json  : JSON 结构化数据
          - both  : 同时导出以上四种格式
        """
        if not self.gui or not self.gui.monitored_videos:
            messagebox.showwarning("提示", "暂无监控视频数据", parent=self.window)
            return
        fmt = self._format_var.get()
        self._export_status.config(text="正在导出...", fg=C["text_2"])
        self.window.update_idletasks()

        from utils.report_exporter import export_html, export_excel, export_csv, export_json

        results = []
        try:
            fmts = {
                "html": [export_html],
                "excel": [export_excel],
                "csv": [export_csv],
                "json": [export_json],
                "both": [export_html, export_excel, export_csv, export_json],
            }
            for exporter in fmts.get(fmt, [export_html]):
                path = exporter(self.gui.monitored_videos)
                results.append(f"{exporter.__name__.replace('export_', '').upper()}: {path}")
            self._export_status.config(text="导出完成！\n" + "\n".join(results), fg=C["success"])
            self._refresh_file_list()
        except Exception as e:
            self._export_status.config(text=f"导出失败: {e}", fg=C["danger"])

    # ── 定时导出 ──

    def _on_schedule_toggle(self):
        """启用定时导出时重置间隔和格式为默认值

        默认间隔: daily（每天一次）
        默认格式: csv
        """
        self._interval_var.set("daily")
        self._schedule_format_var.set("csv")

    def _load_schedule(self):
        """从配置文件加载已保存的定时设置

        读取 data/.export_schedule.json 中的:
          - enabled: 是否启用
          - interval: 导出间隔（hourly/daily/weekly）
          - format: 导出格式
        """
        try:
            if _SCHEDULE_CONFIG.exists():
                data = json.loads(_SCHEDULE_CONFIG.read_text(encoding="utf-8"))
                self._schedule_enabled.set(data.get("enabled", False))
                self._interval_var.set(data.get("interval", "daily"))
                self._schedule_format_var.set(data.get("format", "csv"))
                self._schedule_status.config(text="已加载保存的定时设置", fg=C["success"])
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    def _save_schedule(self):
        """保存定时设置到配置文件并排程下一次导出

        将当前设置写入 JSON 文件，如果启用了定时导出则排程首次导出。
        """
        data = {
            "enabled": self._schedule_enabled.get(),
            "interval": self._interval_var.get(),
            "format": self._schedule_format_var.get(),
        }
        try:
            _SCHEDULE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            _SCHEDULE_CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._schedule_status.config(text="设置已保存", fg=C["success"])
            if self._schedule_enabled.get() and self.gui:
                self.gui.root.after(100, self._schedule_next)
        except Exception as e:
            self._schedule_status.config(text=f"保存失败: {e}", fg=C["danger"])

    def _schedule_next(self):
        """用 root.after 排程下次导出

        根据间隔计算延迟:
          - hourly: 3600000ms (1小时)
          - daily:  86400000ms (24小时)
          - weekly: 604800000ms (7天)
        """
        if not self._schedule_enabled.get() or not self.gui:
            return
        interval = self._interval_var.get()
        delays = {"hourly": 3600000, "daily": 86400000, "weekly": 604800000}
        delay_ms = delays.get(interval, 86400000)
        self._scheduled_job = self.gui.root.after(delay_ms, self._do_scheduled_export)

    def _do_scheduled_export(self):
        """执行定时导出并重新排程

        调用对应格式的导出函数，完成后刷新文件列表并排程下一次。
        """
        if not self.gui or not self.gui.monitored_videos:
            self._schedule_next()
            return
        try:
            fmt = self._schedule_format_var.get()
            from utils.report_exporter import export_csv, export_json, export_html

            exporters = {"csv": export_csv, "json": export_json, "html": export_html}
            exporter = exporters.get(fmt, export_csv)
            path = exporter(self.gui.monitored_videos)
            logger.info("定时导出完成: %s", path)
        except Exception as e:
            logger.warning("定时导出失败: %s", e)
        self._refresh_file_list()
        self._schedule_next()

    # ── 文件列表 ──

    def _refresh_file_list(self):
        """刷新已导出文件列表，显示 recent 的 30 个文件

        展示每个文件的名称和大小（KB/MB）。
        """
        self._file_list.delete(0, tk.END)
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        if os.path.isdir(reports_dir):
            files = sorted(os.listdir(reports_dir), reverse=True)[:30]
            for f in files:
                size = os.path.getsize(os.path.join(reports_dir, f))
                size_str = f"{size / 1024:.1f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"
                self._file_list.insert(tk.END, f"{f}  ({size_str})")

    def _open_folder(self):
        """打开报告导出目录（使用系统文件管理器）"""
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        try:
            os.startfile(reports_dir)  # Windows
        except AttributeError:
            import subprocess
            subprocess.run(["explorer", reports_dir])
