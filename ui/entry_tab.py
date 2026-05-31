"""
数据录入标签页 - 里程碑/快照数据录入
"""

import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y
import logging
from typing import List, Dict

from core.database import get_db
from ui.theme import C
from ui.scrollable_frame import ScrollableFrame
from .data_comparison import _fmt, _parse_dt
from utils.update_checker import _confirm_risky

logger = logging.getLogger(__name__)


class EntryTab:
    """数据录入标签页"""

    def __init__(self, parent_frame, monitored_videos, video_dbs, on_add_monitor, window):
        self._parent = parent_frame
        self._monitored_videos = monitored_videos
        self._video_dbs = video_dbs
        self._on_add_monitor = on_add_monitor
        self._window = window

        # 录入模式
        self._mode = tk.StringVar(value="milestone")
        self._ms_vars: Dict[str, tk.BooleanVar] = {}
        self._snap_dt = tk.StringVar(value="")
        self._snap_combo = None
        self._snap_frame = None
        self._ms_frame = None
        self._param_frame = None
        self._container = None
        self._tbl = None
        self._tbl_menu = None
        self._status = None
        self._bvid_text = None

        self._rows: List[dict] = []  # [{bvid, period_or_ts, vars:{field: StringVar}}, ...]
        self._monitored_set = {v.get("bvid", "") for v in self._monitored_videos}

        self._build()

    # ── 构建UI ──────────────────────────────────────────────────────────────────
    def _build(self):
        f = self._parent

        # 录入模式切换
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
            input_area,
            text="BV号（每行一个，可批量）",
            padx=6,
            pady=6,
            fg=C.get("text_1", "#e6edf3"),
            bg=C.get("bg_surface", "#161b22"),
        )
        bv_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 8))

        self._bvid_text = tk.Text(
            bv_frame,
            width=24,
            height=8,
            bg=C.get("bg_base", "#0d1117"),
            fg=C.get("text_1", "#e6edf3"),
            insertbackground=C.get("text_1", "#e6edf3"),
            font=("Consolas", 10),
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightcolor=C.get("accent", "#fb7299"),
            highlightbackground=C.get("border", "#30363d"),
        )
        self._bvid_text.pack(fill=BOTH, expand=True)

        # 从监控列表批量添加按钮
        ttk.Button(bv_frame, text="从监控列表添加全部", command=self._add_all_monitored).pack(fill=X, pady=(4, 0))

        # 中列：模式参数区（里程碑用周期勾选 / 快照用日期选择）
        self._param_frame = tk.LabelFrame(
            input_area, text="参数", padx=6, pady=6, fg=C.get("text_1", "#e6edf3"), bg=C.get("bg_surface", "#161b22")
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
            self._snap_frame,
            text="格式：2026-04-22 12:00",
            font=("Microsoft YaHei UI", 8),
            fg=C.get("text_2", "#8b949e"),
        ).pack(anchor="w")
        tk.Label(
            self._snap_frame,
            text="\n或从下拉选已有时间点：",
            font=("Microsoft YaHei UI", 8),
            fg=C.get("text_2", "#8b949e"),
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

        # Notebook 嵌套：输入行 / 已有数据
        inner_nb = ttk.Notebook(bottom)
        inner_nb.pack(fill=BOTH, expand=True)

        tab_input = tk.Frame(inner_nb)
        tab_table = tk.Frame(inner_nb)
        inner_nb.add(tab_input, text="  输入行  ")
        inner_nb.add(tab_table, text="  已录入数据  ")

        # 输入行区域
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

        # 右键删除
        self._tbl_menu = tk.Menu(self._window, tearoff=0)
        self._tbl_menu.add_command(
            label="删除选中行",
            command=lambda: _confirm_risky("删除选中数据行") and self._delete_selected(),
        )
        self._tbl.bind("<Button-3>", lambda e: self._tbl_menu.tk_popup(e.x_root, e.y_root))

        # 状态栏
        self._status = tk.Label(
            f,
            text="选择录入模式，输入 BV 号后点击「生成输入表」",
            font=("Microsoft YaHei UI", 9),
            fg=C.get("text_2", "#8b949e"),
            anchor="w",
        )
        self._status.pack(fill=X, padx=12, pady=(0, 6))

        # 初始显示里程碑参数
        self._switch_mode()
        # 加载已有数据
        self._reload_table()

    # ── 录入模式切换 ──────────────────────────────────────────────────────────
    def _switch_mode(self):
        mode = self._mode.get()
        # 切换参数面板
        self._ms_frame.pack_forget()
        self._snap_frame.pack_forget()
        if mode == "milestone":
            self._ms_frame.pack(fill=X)
            self._param_frame.config(text="统计周期")
        else:
            self._snap_frame.pack(fill=X)
            self._param_frame.config(text="日期时间")
            self._refresh_snap_combo()

    def _refresh_snap_combo(self):
        """刷新快照模式下拉时间点列表。"""
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
        self._snap_combo["values"] = ts_list[:200]

    def _on_snap_combo_select(self, event=None):
        val = self._snap_combo.get()
        if val:
            self._snap_dt.set(val)

    # ── 从监控列表添加全部 ────────────────────────────────────────────────────
    def _add_all_monitored(self):
        text = self._bvid_text
        text.delete("1.0", tk.END)
        for v in self._monitored_videos:
            bvid = v.get("bvid", "")
            if bvid:
                text.insert(tk.END, bvid + "\n")

    # ── BV号验证 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _is_valid_bvid(s: str) -> bool:
        from ui.helpers import is_valid_bvid

        return is_valid_bvid(s)

    # ── 生成输入行 ────────────────────────────────────────────────────────────
    def _generate_rows(self):
        """主函数 - 生成数据录入表格"""
        raw = self._bvid_text.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入 BV 号", parent=self._window)
            return

        # 验证BV号
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
        """验证BV号格式，返回有效的BV号列表和无效列表"""
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
        """提示将不在监控列表的BV号加入监控"""
        not_monitored = [b for b in bvids if b not in self._monitored_set]
        if not_monitored:
            msg = "以下 BV 号不在监控列表：\n" + "\n".join(not_monitored[:10]) + "\n\n是否加入监控？"
            if messagebox.askyesno("加入监控", msg, parent=self._window):
                for bv in not_monitored:
                    if self._on_add_monitor:
                        self._on_add_monitor(bv)
                    self._monitored_set.add(bv)

    def _generate_row_labels(self, bvids):
        """生成行标签（BV号 × 周期/时间点）"""
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
        """清空旧的行"""
        for w in self._container.winfo_children():
            w.destroy()
        self._rows.clear()

    def _load_existing_data(self, mode, bvids, dt_str=""):
        """加载已有数据做预填"""
        existing_ms = {}
        if mode == "milestone":
            for row in get_db().get_milestones():
                existing_ms[(row["bvid"], row["period"])] = row

        # 快照已有数据
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
        """创建输入行UI"""
        fields = [
            ("view_count", "播放量*", True),
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
        """创建单行输入"""
        row_frame = tk.Frame(self._container, padx=4, pady=2)
        row_frame.pack(fill=tk.X)

        # BV号 + key 标签
        tk.Label(
            row_frame,
            text=bv,
            font=("Consolas", 9),
            fg=C.get("accent", "#fb7299"),
            bg=C.get("bg_base", "#0d1117"),
            width=14,
            anchor="w",
        ).grid(row=0, column=0, padx=(0, 4))

        tk.Label(
            row_frame,
            text=key,
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=C.get("text_1", "#e6edf3"),
            bg=C.get("bg_base", "#0d1117"),
            width=16,
            anchor="w",
        ).grid(row=0, column=1, padx=(0, 8))

        vars_dict = {}
        col = 2
        for fkey, flabel, required in fields:
            self._create_field_input(
                row_frame, bv, key, mode, fkey, flabel, required, col, vars_dict, existing_ms, existing_snap
            )
            col += 2

        self._rows.append(
            {
                "bvid": bv,
                "key": key,
                "vars": vars_dict,
                "mode": mode,
            }
        )

    def _create_field_input(
        self, row_frame, bv, key, mode, fkey, flabel, required, col, vars_dict, existing_ms, existing_snap
    ):
        """创建字段输入框"""
        tk.Label(
            row_frame,
            text=flabel + ("*" if required else ""),
            font=("Microsoft YaHei UI", 8),
            fg=C.get("danger", "#f85149") if required else C.get("text_2", "#8b949e"),
            bg=C.get("bg_base", "#0d1117"),
            anchor="e",
            width=6,
        ).grid(row=0, column=col, padx=(2, 1))

        var = tk.StringVar()
        # 预填
        if mode == "milestone":
            existing = existing_ms.get((bv, key))
            if existing and existing.get(fkey) is not None:
                var.set(str(existing[fkey]))
        else:
            existing = existing_snap.get(bv)
            if existing and existing.get(fkey) is not None:
                var.set(str(existing[fkey]))

        vars_dict[fkey] = var
        w = 18 if fkey == "note" else 8
        ent = tk.Entry(
            row_frame,
            textvariable=var,
            font=("Consolas", 9),
            width=w,
            bg=C.get("bg_base", "#0d1117"),
            fg=C.get("text_1", "#e6edf3"),
            insertbackground=C.get("text_1", "#e6edf3"),
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightcolor=C.get("accent", "#fb7299"),
            highlightbackground=C.get("border", "#30363d"),
        )
        ent.grid(row=0, column=col + 1, padx=(0, 4))

    # ── 保存全部 ──────────────────────────────────────────────────────────────
    def _save_all(self):
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
        self._status.config(text=msg, fg=C.get("success", "#3fb950") if not errors else C.get("warning", "#d29922"))

        if saved:
            self._reload_table()
            messagebox.showinfo("保存完成", msg, parent=self._window)

    def _save_single_row(self, row):
        """处理单行数据保存。返回 (saved, skipped, errors) 三元组。"""
        vars_d = row["vars"]
        raw_view = vars_d["view_count"].get().strip().replace(",", "")
        if not raw_view:
            return (0, 1, 0)
        try:
            view_val = int(float(raw_view))
        except ValueError:
            return (0, 0, 1)

        data = {"view_count": view_val}
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

        if mode == "milestone":
            ok = get_db().upsert_milestone(bvid, row["key"], data)
        else:
            ok = self._save_snapshot_record(bvid, row["key"], data)

        return (1, 0, 0) if ok else (0, 0, 1)

    def _build_save_msg(self, saved, skipped, errors):
        """构建保存结果消息。"""
        msg = f"✅ 已保存 {saved} 条"
        if skipped:
            msg += f"，跳过 {skipped} 条（播放量为空）"
        if errors:
            msg += f"，失败 {errors} 条"
        return msg

    def _save_snapshot_record(self, bvid: str, ts_str: str, data: dict) -> bool:
        """将快照数据写入视频的历史记录表。"""
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
                bvid=bvid,
                timestamp=ts_str_full,
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

    # ── 刷新已有数据表格 ──────────────────────────────────────────────────────
    def _reload_table(self):
        for item in self._tbl.get_children():
            self._tbl.delete(item)

        # 里程碑数据
        for row in get_db().get_milestones():
            self._tbl.insert(
                "",
                tk.END,
                values=(
                    row.get("bvid", ""),
                    "里程碑",
                    row.get("period", ""),
                    _fmt(row.get("view_count")),
                    _fmt(row.get("like_count")),
                    _fmt(row.get("coin_count")),
                    _fmt(row.get("favorite_count")),
                    _fmt(row.get("share_count")),
                    _fmt(row.get("danmaku_count")),
                    _fmt(row.get("reply_count")),
                    str(row.get("recorded_at", ""))[:16],
                ),
            )

        # 快照数据（手动录入的标记 tricky，显示所有里程碑即可；快照已录入历史表
        # 不在里程碑表中，这里主要显示里程碑）

    def _delete_selected(self):
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
