"""
数据录入标签页 — 里程碑/快照数据录入模块

本模块是 DataComparisonWindow 的第三个标签页，负责将手工录入的播放量数据
写入数据库。支持两种录入模式：

1. 里程碑模式 — 按周期（一周/一月/一年等）记录视频播放量里程碑
2. 快照模式 — 在指定时间点插入历史播放数据（写入视频独立库的 monitor_records 表）

功能特点：
- 支持批量输入 BV 号（每行一个）
- 支持从监控列表一键添加所有 BV 号
- 自动加载已有数据预填输入框
- 统一保存入口，支持校验和错误提示
- 已录入数据以表格展示并支持右键删除

复用 data_comparison.py 中的 _fmt() 和 _parse_dt() 工具函数。
"""

import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y
from decimal import Decimal
import logging
from typing import List, Dict

from core.database import get_db                            # 中央数据库单例
from ui.theme import C                                      # 颜色主题
from ui.scrollable_frame import ScrollableFrame             # 可滚动容器
from .data_comparison import _fmt, _parse_dt                 # 复用格式化和时间解析工具
from utils.update_checker import _confirm_risky              # 危险操作确认

logger = logging.getLogger(__name__)


class EntryTab:
    """
    数据录入标签页

    职责：
    1. 提供 BV 号输入区（批量，每行一个）
    2. 根据模式（里程碑/快照）动态切换参数面板
    3. 生成输入行表格（BV号 × 周期/时间点 × 字段）
    4. 加载已有数据预填
    5. 保存全部数据到数据库
    6. 已录入数据表格展示 + 删除
    """

    def __init__(self, parent_frame, monitored_videos, video_dbs, on_add_monitor, window):
        """
        初始化数据录入标签页

        :param parent_frame: 父容器 Frame
        :param monitored_videos: 监控视频列表
        :param video_dbs: 视频独立数据库字典 {bvid: VideoDatabase}
        :param on_add_monitor: 添加监控回调函数
        :param window: 父窗口引用
        """
        self._parent = parent_frame
        self._monitored_videos = monitored_videos
        self._video_dbs = video_dbs
        self._on_add_monitor = on_add_monitor
        self._window = window

        # 录入模式
        self._mode = tk.StringVar(value="milestone")         # "milestone" 或 "snapshot"
        self._ms_vars: Dict[str, tk.BooleanVar] = {}         # 里程碑周期勾选状态
        self._snap_dt = tk.StringVar(value="")               # 快照时间点
        self._snap_combo = None                              # 快照时间下拉框
        self._snap_frame = None                              # 快照参数面板
        self._ms_frame = None                                # 里程碑参数面板
        self._param_frame = None                             # 参数区容器
        self._container = None                               # 输入行滚动容器
        self._tbl = None                                     # 已录入数据表格
        self._tbl_menu = None                                # 右键菜单
        self._status = None                                  # 状态栏
        self._bvid_text = None                               # BV 号输入框

        self._rows: List[dict] = []                          # 输入行数据
        self._monitored_set = {v.get("bvid", "") for v in self._monitored_videos}

        self._build()

    # ── UI 构建 ──────────────────────────────────────────────────────────────────

    def _build(self):
        """构建数据录入标签页的完整 UI：模式切换、输入区、输入行、已有数据表格"""
        f = self._parent

        # ── 录入模式切换 ──
        mode_bar = tk.Frame(f)
        mode_bar.pack(fill=X, padx=10, pady=(8, 4))

        tk.Label(mode_bar, text="录入模式：", font=("Microsoft YaHei UI", 9, "bold")).pack(side=LEFT)
        ttk.Radiobutton(
            mode_bar, text="里程碑（一周/月/年）", variable=self._mode, value="milestone", command=self._switch_mode
        ).pack(side=LEFT, padx=(8, 16))
        ttk.Radiobutton(
            mode_bar, text="历史快照（指定时间点）", variable=self._mode, value="snapshot", command=self._switch_mode
        ).pack(side=LEFT)

        # ── 上半：输入区 ──
        input_area = tk.Frame(f)
        input_area.pack(fill=BOTH, expand=True, padx=10, pady=4)

        # 左列：BV号输入
        bv_frame = tk.LabelFrame(
            input_area, text="BV号（每行一个，可批量）",
            padx=6, pady=6,
            fg=C.get("text_1", "#e6edf3"), bg=C.get("bg_surface", "#161b22"),
        )
        bv_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))

        self._bvid_text = tk.Text(
            bv_frame, width=24, height=8,
            bg=C.get("bg_base", "#0d1117"), fg=C.get("text_1", "#e6edf3"),
            insertbackground=C.get("text_1", "#e6edf3"),
            font=("Consolas", 10), relief="flat", bd=1,
            highlightthickness=1, highlightcolor=C.get("accent", "#fb7299"),
            highlightbackground=C.get("border", "#30363d"),
        )
        self._bvid_text.pack(fill=BOTH, expand=True)

        # 从监控列表批量添加按钮
        ttk.Button(bv_frame, text="从监控列表添加全部", command=self._add_all_monitored).pack(fill=X, pady=(4, 0))

        # 中列：模式参数区（里程碑用周期勾选 / 快照用日期选择）
        self._param_frame = tk.LabelFrame(
            input_area, text="参数", padx=6, pady=6,
            fg=C.get("text_1", "#e6edf3"), bg=C.get("bg_surface", "#161b22")
        )
        self._param_frame.pack(side=LEFT, fill=Y, padx=(0, 8))

        # 里程碑参数（周期勾选）
        self._ms_frame = tk.Frame(self._param_frame)
        self._ms_vars = {}
        tk.Label(self._ms_frame, text="统计周期", font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        for p in get_db().MILESTONE_PERIODS:
            var = tk.BooleanVar(value=True)
            self._ms_vars[p] = var
            tk.Checkbutton(self._ms_frame, text=p, variable=var).pack(anchor="w")

        # 快照参数（日期选择）
        self._snap_frame = tk.Frame(self._param_frame)
        tk.Label(self._snap_frame, text="选择日期时间", font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        dt_entry = tk.Entry(self._snap_frame, textvariable=self._snap_dt, width=18, font=("Consolas", 9))
        dt_entry.pack(anchor="w", pady=2)
        tk.Label(
            self._snap_frame, text="格式：2026-04-22 12:00",
            font=("Microsoft YaHei UI", 8), fg=C.get("text_2", "#8b949e"),
        ).pack(anchor="w")
        tk.Label(
            self._snap_frame, text="\n或从下拉选已有时间点：",
            font=("Microsoft YaHei UI", 8), fg=C.get("text_2", "#8b949e"),
        ).pack(anchor="w")
        self._snap_combo = ttk.Combobox(self._snap_frame, width=18, state="readonly")
        self._snap_combo.pack(anchor="w", pady=2)
        self._snap_combo.bind("<<ComboboxSelected>>", self._on_snap_combo_select)

        # 右列：操作按钮
        btn_frame = tk.Frame(input_area)
        btn_frame.pack(side=LEFT, fill=Y)

        ttk.Button(btn_frame, text="生成输入表", command=self._generate_rows).pack(fill=X, pady=3, ipady=2)
        ttk.Button(btn_frame, text="💾 保存全部", command=self._save_all).pack(fill=X, pady=3, ipady=2)

        # ── 下半：可滚动的输入行 + 已有数据表格 ──
        bottom = tk.Frame(f)
        bottom.pack(fill=BOTH, expand=True, padx=10, pady=(4, 4))

        inner_nb = ttk.Notebook(bottom)
        inner_nb.pack(fill=BOTH, expand=True)

        tab_input = tk.Frame(inner_nb)
        tab_table = tk.Frame(inner_nb)
        inner_nb.add(tab_input, text="  输入行  ")
        inner_nb.add(tab_table, text="  已录入数据  ")

        # 输入行区域（可滚动）
        sf = ScrollableFrame(tab_input, bg=C.get("bg_base", "#0d1117"))
        sf.pack(fill=BOTH, expand=True)
        self._container = sf.inner

        # 已录入数据表格
        cols = ("bvid", "type", "time_key", "播放量", "点赞", "硬币", "收藏", "分享", "弹幕", "评论", "记录时间")
        self._tbl = ttk.Treeview(tab_table, columns=cols, show="headings", height=8)
        tbl_sb = ttk.Scrollbar(tab_table, orient="vertical", command=self._tbl.yview)
        self._tbl.configure(yscrollcommand=tbl_sb.set)
        tbl_sb.pack(side=RIGHT, fill=Y)
        self._tbl.pack(fill=BOTH, expand=True)

        widths = [110, 70, 130, 80, 60, 60, 60, 60, 60, 60, 120]
        for col, w in zip(cols, widths):
            self._tbl.heading(col, text=col)
            self._tbl.column(col, width=w, minwidth=40, anchor="center")

        # 右键删除菜单
        self._tbl_menu = tk.Menu(self._window, tearoff=0)
        self._tbl_menu.add_command(
            label="删除选中行",
            command=lambda: _confirm_risky("删除选中数据行") and self._delete_selected(),
        )
        self._tbl.bind("<Button-3>", lambda e: self._tbl_menu.tk_popup(e.x_root, e.y_root))

        # 状态栏
        self._status = tk.Label(
            f, text="选择录入模式，输入 BV 号后点击「生成输入表」",
            font=("Microsoft YaHei UI", 9), fg=C.get("text_2", "#8b949e"), anchor="w",
        )
        self._status.pack(fill=X, padx=12, pady=(0, 6))

        # 初始显示里程碑参数
        self._switch_mode()
        self._reload_table()

    # ── 录入模式切换 ──────────────────────────────────────────────────────────────

    def _switch_mode(self):
        """
        在里程碑模式和快照模式间切换，更新参数面板

        里程碑：显示周期复选框
        快照：显示日期输入框和下拉选择器
        """
        mode = self._mode.get()
        self._ms_frame.pack_forget()
        self._snap_frame.pack_forget()
        if mode == "milestone":
            self._ms_frame.pack(fill=X)
            self._param_frame.config(text="统计周期")
        else:
            self._snap_frame.pack(fill=X)
            self._param_frame.config(text="日期时间")
            self._refresh_snap_combo()                       # 刷新可用时间点

    def _refresh_snap_combo(self):
        """
        刷新快照模式下可用的历史时间点下拉列表

        遍历所有视频独立库，收集 monitor_records 表的时间戳。
        """
        ts_set = set()
        for bvid in self._video_dbs:
            try:
                for rec in self._video_dbs[bvid].get_all_records():
                    ts = str(rec.get("timestamp", ""))[:16]
                    if ts:
                        ts_set.add(ts)
            except Exception as e:
                logger.debug("刷新快照时间下拉列表失败: %s", e)
        ts_list = sorted(ts_set, reverse=True)
        self._snap_combo["values"] = ts_list[:200]           # 最多显示 200 个

    def _on_snap_combo_select(self, event=None):
        """
        快照下拉选择后自动填入时间输入框

        :param event: Combobox 选择事件（可选）
        """
        val = self._snap_combo.get()
        if val:
            self._snap_dt.set(val)

    # ── 从监控列表添加全部 ────────────────────────────────────────────────────────

    def _add_all_monitored(self):
        """将当前所有监控视频的 BV 号填入输入框（每行一个）"""
        text = self._bvid_text
        text.delete("1.0", tk.END)
        for v in self._monitored_videos:
            bvid = v.get("bvid", "")
            if bvid:
                text.insert(tk.END, bvid + "\n")

    # ── BV 号验证 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_valid_bvid(s: str) -> bool:
        """
        检查字符串是否为合法的 BV 号

        :param s: 输入字符串
        :return: 是否合法
        """
        from ui.helpers import is_valid_bvid

        return is_valid_bvid(s)

    # ── 生成输入行 ────────────────────────────────────────────────────────────────

    def _generate_rows(self):
        """
        主入口：解析 BV 号 → 加载已有数据 → 生成数据录入表格行

        流程：
        1. 从文本框解析 BV 号列表并验证格式
        2. 提示用户可将不在监控列表的 BV 加入监控
        3. 按模式生成行标签（BV号 × 周期/时间点）
        4. 加载已有数据（里程碑 / 快照）
        5. 逐行创建输入 UI
        """
        raw = self._bvid_text.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入 BV 号", parent=self._window)
            return

        # 验证 BV 号
        bvids, invalid = self._validate_bvids(raw)
        if not bvids:
            return

        # 提示添加监控
        self._prompt_add_monitor(bvids)

        # 生成行标签
        mode, row_labels, periods, dt_str = self._generate_row_labels(bvids)
        if not row_labels:
            return

        # 清空旧行
        self._clear_old_rows()

        # 加载已有数据
        existing_ms, existing_snap = self._load_existing_data(mode, bvids, dt_str)

        # 创建输入行
        self._create_input_rows(row_labels, mode, existing_ms, existing_snap, bvids, periods)

    def _validate_bvids(self, raw):
        """
        验证 BV 号格式，返回（有效列表, 无效列表）

        :param raw: 原始文本框内容
        :return: (valid_bvids, invalid_bvids)
        """
        bvids, invalid = [], []
        for line in raw.splitlines():
            bv = line.strip()
            if not bv:
                continue
            if self._is_valid_bvid(bv):
                if bv not in bvids:
                    bvids.append(bv)
            else:
                invalid.append(bv)

        if invalid:
            messagebox.showwarning(
                "格式错误", "以下格式不合法已跳过：\n" + "\n".join(invalid[:10]), parent=self._window
            )

        return bvids, invalid

    def _prompt_add_monitor(self, bvids):
        """
        检查并提示用户将不在监控列表的 BV 号加入监控

        :param bvids: 待检查的 BV 号列表
        """
        not_monitored = [b for b in bvids if b not in self._monitored_set]
        if not_monitored:
            msg = "以下 BV 号不在监控列表：\n" + "\n".join(not_monitored[:10]) + "\n\n是否加入监控？"
            if messagebox.askyesno("加入监控", msg, parent=self._window):
                for bv in not_monitored:
                    if self._on_add_monitor:
                        self._on_add_monitor(bv)
                    self._monitored_set.add(bv)

    def _generate_row_labels(self, bvids):
        """
        生成行标签组合（BV 号 × 周期/时间点）

        :param bvids: 有效的 BV 号列表
        :return: (mode, row_labels, periods, dt_str)
        """
        mode = self._mode.get()
        periods = []
        dt_str = ""
        row_labels = []

        if mode == "milestone":
            periods = [p for p, v in self._ms_vars.items() if v.get()]
            if not periods:
                messagebox.showwarning("提示", "请至少选择一个周期", parent=self._window)
                return mode, None, None, None
            for bv in bvids:
                for p in periods:
                    row_labels.append((bv, p))
        else:
            dt_str = self._snap_dt.get().strip()
            if not dt_str:
                messagebox.showwarning("提示", "请填写日期时间或从下拉选择", parent=self._window)
                return mode, None, None, None
            # 验证格式
            dt = _parse_dt(dt_str)
            if dt is None:
                messagebox.showwarning("格式错误", "日期格式不正确，请使用 2026-04-22 12:00 格式", parent=self._window)
                return mode, None, None, None
            for bv in bvids:
                row_labels.append((bv, dt_str[:16]))

        return mode, row_labels, periods, dt_str

    def _clear_old_rows(self):
        """清空已生成的旧输入行和行数据"""
        for w in self._container.winfo_children():
            w.destroy()
        self._rows.clear()

    def _load_existing_data(self, mode, bvids, dt_str=""):
        """
        从数据库加载已有数据用于输入框预填

        :param mode: 录入模式
        :param bvids: BV 号列表
        :param dt_str: 快照时间点
        :return: (existing_ms, existing_snap)
        """
        existing_ms = {}
        if mode == "milestone":
            for row in get_db().get_milestones():
                existing_ms[(row["bvid"], row["period"])] = row

        existing_snap = {}
        if mode == "snapshot":
            for bvid in bvids:
                if bvid in self._video_dbs:
                    try:
                        for rec in self._video_dbs[bvid].get_all_records():
                            rec_ts = str(rec.get("timestamp", ""))[:16]
                            if rec_ts == dt_str[:16]:
                                existing_snap[bvid] = dict(rec)
                                break
                    except Exception as e:
                        logger.debug("加载快照数据失败: %s", e)

        return existing_ms, existing_snap

    def _create_input_rows(self, row_labels, mode, existing_ms, existing_snap, bvids, periods):
        """
        创建完整的输入行 UI，为每行设置字段输入框

        :param row_labels: [(bvid, key), ...] 行标签列表
        :param mode: 录入模式
        :param existing_ms: 已有里程碑数据
        :param existing_snap: 已有快照数据
        :param bvids: BV 号列表
        :param periods: 周期列表
        """
        fields = [
            ("view_count", "播放量*", True),                 # 播放量为必填
            ("like_count", "点赞", False),
            ("coin_count", "硬币", False),
            ("share_count", "分享", False),
            ("favorite_count", "收藏", False),
            ("danmaku_count", "弹幕", False),
            ("reply_count", "评论", False),
            ("note", "备注", False),
        ]

        for bv, key in row_labels:
            self._create_single_row(bv, key, mode, fields, existing_ms, existing_snap)

        n = len(self._rows)
        self._status.config(
            text=f"已生成 {n} 行输入（{len(bvids)} 视频 × "
            + (f"{len(periods)} 周期" if mode == "milestone" else "1 时间点")
            + "），填写后点击「保存全部」"
        )

    def _create_single_row(self, bv, key, mode, fields, existing_ms, existing_snap):
        """
        创建单个 BV × 周期/时间点的输入行 UI

        :param bv: BV 号
        :param key: 周期名（如 "一周"）或时间点字符串
        :param mode: 录入模式
        :param fields: 字段定义列表
        :param existing_ms: 已有里程碑数据
        :param existing_snap: 已有快照数据
        """
        row_frame = tk.Frame(self._container, padx=4, pady=2)
        row_frame.pack(fill=tk.X)

        # BV 号标签
        tk.Label(
            row_frame, text=bv, font=("Consolas", 9),
            fg=C.get("accent", "#fb7299"), bg=C.get("bg_base", "#0d1117"),
            width=14, anchor="w",
        ).grid(row=0, column=0, padx=(0, 4))

        # 周期/时间点标签
        tk.Label(
            row_frame, text=key, font=("Microsoft YaHei UI", 9, "bold"),
            fg=C.get("text_1", "#e6edf3"), bg=C.get("bg_base", "#0d1117"),
            width=16, anchor="w",
        ).grid(row=0, column=1, padx=(0, 8))

        vars_dict = {}
        col = 2
        for fkey, flabel, required in fields:
            self._create_field_input(
                row_frame, bv, key, mode, fkey, flabel, required, col, vars_dict, existing_ms, existing_snap
            )
            col += 2

        self._rows.append({
            "bvid": bv, "key": key, "vars": vars_dict, "mode": mode,
        })

    def _create_field_input(
        self, row_frame, bv, key, mode, fkey, flabel, required, col, vars_dict, existing_ms, existing_snap
    ):
        """
        在指定列位置创建单个字段输入框，并设置预填值

        :param row_frame: 行 Frame
        :param bv: BV 号
        :param key: 周期/时间点
        :param mode: 模式
        :param fkey: 字段名（如 "view_count"）
        :param flabel: 字段标签文本
        :param required: 是否必填
        :param col: 当前列索引
        :param vars_dict: 字段 StringVar 字典
        :param existing_ms: 已有里程碑
        :param existing_snap: 已有快照
        """
        tk.Label(
            row_frame, text=flabel + ("*" if required else ""),
            font=("Microsoft YaHei UI", 8),
            fg=C.get("danger", "#f85149") if required else C.get("text_2", "#8b949e"),
            bg=C.get("bg_base", "#0d1117"), anchor="e", width=6,
        ).grid(row=0, column=col, padx=(2, 1))

        var = tk.StringVar()
        # 预填已有数据
        if mode == "milestone":
            existing = existing_ms.get((bv, key))
            if existing and existing.get(fkey) is not None:
                var.set(str(existing[fkey]))
        else:
            existing = existing_snap.get(bv)
            if existing and existing.get(fkey) is not None:
                var.set(str(existing[fkey]))

        vars_dict[fkey] = var
        w = 18 if fkey == "note" else 8                      # 备注字段更宽
        ent = tk.Entry(
            row_frame, textvariable=var, font=("Consolas", 9), width=w,
            bg=C.get("bg_base", "#0d1117"), fg=C.get("text_1", "#e6edf3"),
            insertbackground=C.get("text_1", "#e6edf3"),
            relief="flat", bd=1, highlightthickness=1,
            highlightcolor=C.get("accent", "#fb7299"),
            highlightbackground=C.get("border", "#30363d"),
        )
        ent.grid(row=0, column=col + 1, padx=(0, 4))

    # ── 保存全部 ──────────────────────────────────────────────────────────────────

    def _save_all(self):
        """
        保存所有输入行的数据到数据库

        逐行处理，统计成功/跳过/失败数量，完成后刷新表格。
        播放量为空的行自动跳过。
        """
        if not self._rows:
            messagebox.showwarning("提示", "请先生成输入表", parent=self._window)
            return

        saved = skipped = errors = 0
        for row in self._rows:
            s, sk, e = self._save_single_row(row)
            saved += s
            skipped += sk
            errors += e

        msg = self._build_save_msg(saved, skipped, errors)
        self._status.config(
            text=msg, fg=C.get("success", "#3fb950") if not errors else C.get("warning", "#d29922")
        )

        if saved:
            self._reload_table()
            messagebox.showinfo("保存完成", msg, parent=self._window)

    def _save_single_row(self, row):
        """
        处理单行数据保存

        :param row: 输入行数据字典
        :return: (saved, skipped, errors) 三元组
        """
        vars_d = row["vars"]
        # 读取播放量（必填）
        raw_view = vars_d["view_count"].get().strip().replace(",", "")
        if not raw_view:
            return (0, 1, 0)                                  # 跳过：播放量为空
        try:
            view_val = int(Decimal(raw_view))                  # 使用 Decimal 处理大整数
        except (ValueError, ArithmeticError):
            return (0, 0, 1)                                  # 错误：格式无效

        data = {"view_count": view_val}
        # 读取可选数值字段
        for fkey in ["like_count", "coin_count", "share_count", "favorite_count", "danmaku_count", "reply_count"]:
            val = vars_d[fkey].get().strip()
            if val:
                try:
                    data[fkey] = int(float(val.replace(",", "")))
                except ValueError:
                    pass
        note = vars_d["note"].get().strip()
        if note:
            data["note"] = note

        mode = row["mode"]
        bvid = row["bvid"]

        # 按模式分别写入
        if mode == "milestone":
            ok = get_db().upsert_milestone(bvid, row["key"], data)
        else:
            ok = self._save_snapshot_record(bvid, row["key"], data)

        return (1, 0, 0) if ok else (0, 0, 1)

    def _build_save_msg(self, saved, skipped, errors):
        """
        构建保存结果摘要消息字符串

        :param saved: 成功数
        :param skipped: 跳过数
        :param errors: 失败数
        :return: 消息字符串
        """
        msg = f"✅ 已保存 {saved} 条"
        if skipped:
            msg += f"，跳过 {skipped} 条（播放量为空）"
        if errors:
            msg += f"，失败 {errors} 条"
        return msg

    def _save_snapshot_record(self, bvid: str, ts_str: str, data: dict) -> bool:
        """
        将快照数据写入视频独立库的历史记录表

        :param bvid: 视频 BV 号
        :param ts_str: 时间点字符串
        :param data: 播放量等字段字典
        :return: 是否成功
        """
        if bvid not in self._video_dbs:
            return False
        try:
            video_db = self._video_dbs[bvid]
            dt = _parse_dt(ts_str)
            if dt is None:
                return False
            ts_str_full = dt.strftime("%Y-%m-%d %H:%M:%S")

            # 构造 MonitorRecord 并写入
            from core.database import MonitorRecord

            record = MonitorRecord(
                bvid=bvid, timestamp=ts_str_full,
                view_count=data.get("view_count", 0),
                like_count=data.get("like_count", 0),
                coin_count=data.get("coin_count", 0),
                share_count=data.get("share_count", 0),
                favorite_count=data.get("favorite_count", 0),
                danmaku_count=data.get("danmaku_count", 0),
                reply_count=data.get("reply_count", 0),
            )
            video_db.add_monitor_record(record)
            return True
        except Exception as e:
            logger.warning("快照写入失败 [%s]: %s", bvid, e)
            return False

    # ── 刷新已有数据表格 ──────────────────────────────────────────────────────────

    def _reload_table(self):
        """重新加载里程碑数据到已录入数据表格"""
        for item in self._tbl.get_children():
            self._tbl.delete(item)

        for row in get_db().get_milestones():
            self._tbl.insert(
                "", tk.END,
                values=(
                    row.get("bvid", ""), "里程碑", row.get("period", ""),
                    _fmt(row.get("view_count")), _fmt(row.get("like_count")),
                    _fmt(row.get("coin_count")), _fmt(row.get("favorite_count")),
                    _fmt(row.get("share_count")), _fmt(row.get("danmaku_count")),
                    _fmt(row.get("reply_count")), str(row.get("recorded_at", ""))[:16],
                ),
            )

    def _delete_selected(self):
        """删除选中的里程碑数据行（通过右键菜单触发）"""
        selected = self._tbl.selection()
        if not selected:
            return
        if not messagebox.askyesno("确认", f"删除选中的 {len(selected)} 条记录？", parent=self._window):
            return
        for iid in selected:
            values = self._tbl.item(iid, "values")
            if not values:
                continue
            bvid = values[0]
            entry_type = values[1]
            time_key = values[2]
            if entry_type == "里程碑":
                get_db().delete_milestone(bvid, time_key)
        self._reload_table()
