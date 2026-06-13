"""
在线人数监控面板 — 实时查看所有监控视频的在线观看人数
秒级刷新，独立于主监控线程直接调用 B站 API 获取在线人数。
"""

import tkinter as tk
from tkinter import ttk
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from ui.theme import C
from ui.helpers import FONT, FONT_SM, fmt_num, _parse_viewer_count

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 5000  # 毫秒，秒级刷新（5 秒）
MAX_VIEWER_FETCH_WORKERS = 4  # 并发上限（按需拉取模式下 4 线程足够）
TOP_N_FETCH = 20  # 每次只拉取在线人数最高的前 N 个视频


class OnlineViewersPanel:
    def __init__(self, parent, main_gui):
        self.parent = parent
        self.gui = main_gui
        self.frame = tk.Frame(parent, bg=C["bg_base"])
        self._sort_col = "viewers_total"
        self._sort_rev = True
        self._timer_id = None
        self._refresh_lock = threading.Lock()  # 防止并发刷新
        self._fetch_pool = None  # 延迟初始化，仅面板可见时创建
        self._active = False  # 面板是否可见
        self._build_ui()

    def _build_ui(self):
        """构建在线人数监控面板的 UI：表头、树形表格、状态栏"""
        header = tk.Frame(self.frame, bg=C["bg_surface"], height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="👥 在线人数监控",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(side=tk.LEFT, padx=(16, 4), pady=10)

        self._count_lbl = tk.Label(
            header,
            text="",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT,
        )
        self._count_lbl.pack(side=tk.LEFT, padx=4, pady=10)

        self._time_lbl = tk.Label(
            header,
            text="",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        )
        self._time_lbl.pack(side=tk.RIGHT, padx=16, pady=10)

        sep = tk.Frame(self.frame, bg=C["border"], height=1)
        sep.pack(fill=tk.X)

        tree_frame = tk.Frame(self.frame, bg=C["bg_base"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        columns = (
            "rank",
            "title",
            "bvid",
            "viewers_total",
            "viewers_web",
            "viewers_app",
            "view_count",
            "online_rate",
        )
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        col_cfgs = [
            ("rank", "#", 36, tk.CENTER),
            ("title", "视频标题", 320, tk.LEFT),
            ("bvid", "BV号", 130, tk.CENTER),
            ("viewers_total", "在线人数", 110, tk.CENTER),
            ("viewers_web", "Web端", 90, tk.CENTER),
            ("viewers_app", "App端", 90, tk.CENTER),
            ("view_count", "播放量", 110, tk.CENTER),
            ("online_rate", "在线率", 90, tk.CENTER),
        ]
        for col_id, heading, width, anchor in col_cfgs:
            self._tree.heading(
                col_id,
                text=heading,
                anchor=anchor,
                command=lambda c=col_id: self._sort_by(c),
            )
            self._tree.column(col_id, width=width, anchor=anchor, minwidth=36)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.tag_configure("even", background=C["bg_surface"])
        self._tree.tag_configure("odd", background=C["bg_base"])
        self._tree.tag_configure("online_high", foreground=C["success"])
        self._tree.tag_configure("online_mid", foreground=C["warning"])
        self._tree.tag_configure("online_low", foreground=C["text_3"])

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._apply_tree_style()

        status_bar = tk.Frame(self.frame, bg=C["bg_surface"], height=32)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        self._status_lbl = tk.Label(
            status_bar,
            text="就绪",
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        )
        self._status_lbl.pack(side=tk.LEFT, padx=12, pady=6)

        ttk.Button(
            status_bar,
            text="🔄 刷新",
            command=self.refresh,
            style="Primary.TButton",
        ).pack(side=tk.RIGHT, padx=(4, 12), pady=3)

        ttk.Button(
            status_bar,
            text="跳转到视频",
            command=self._jump_to_video,
        ).pack(side=tk.RIGHT, padx=4, pady=3)

    def _apply_tree_style(self):
        """为树形视图应用自定义颜色样式"""
        style = ttk.Style()
        style.configure(
            "Treeview",
            background=C["bg_elevated"],
            fieldbackground=C["bg_elevated"],
            foreground=C["text_1"],
            rowheight=28,
            font=FONT,
        )
        style.configure(
            "Treeview.Heading",
            background=C["bg_surface"],
            foreground=C["text_2"],
            font=FONT,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", C["bilibili_dim"])],
            foreground=[("selected", "#ffffff")],
        )

    def _sort_by(self, col):
        """切换排序字段或反转排序方向，然后刷新列表"""
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = col in ("viewers_total", "viewers_web", "viewers_app", "view_count", "online_rate", "rank")
        self._populate()

    def _on_select(self, event):
        pass

    def _jump_to_video(self):
        """选中视频后跳转到主界面的监控列表并定位到该视频"""
        sel = self._tree.selection()
        if not sel:
            return
        bvid = self._tree.item(sel[0], "values")[2]
        self.gui._switch_nav("监控列表")
        self.gui._select_video(bvid)

    def refresh(self):
        """刷新在线人数数据：从 B站 API 拉取最新在线人数，然后更新列表"""
        if not self._refresh_lock.acquire(blocking=False):
            return  # 上一次刷新尚未完成，跳过
        threading.Thread(target=self._async_refresh, daemon=True).start()

    def _async_refresh(self):
        """后台线程：并发拉取所有视频的在线人数，完成后回主线程更新 UI"""
        try:
            self._fetch_all_viewers()
        finally:
            self._refresh_lock.release()
        # 回主线程更新 UI
        if self._active:
            self.frame.after(0, self._update_ui_after_fetch)

    def _fetch_all_viewers(self):
        """并发拉取高优先级视频的在线观看人数（按需拉取，非全量）。

        策略：只拉取在线人数最高的前 TOP_N_FETCH 个视频 + 当前选中的视频。
        避免 100+ 视频全量拉取导致秒级刷新无法达标。
        """
        videos = self.gui.monitored_videos
        if not videos:
            return

        # ── 优先级筛选：在线人数 Top N + 当前选中 ──
        selected_bvid = None
        sel = self._tree.selection()
        if sel:
            selected_bvid = self._tree.item(sel[0], "values")[2]

        # 按当前已知在线人数排序（近似，无需精确）
        ranked = sorted(
            [(v, v.get("viewers_total", 0)) for v in videos],
            key=lambda x: x[1], reverse=True,
        )
        priority_videos = [v for v, _ in ranked[:TOP_N_FETCH]]

        # 确保选中的视频也在拉取列表中
        if selected_bvid:
            for v in videos:
                if v.get("bvid") == selected_bvid and v not in priority_videos:
                    priority_videos.append(v)
                    break

        # ── 筛选有 cid 的视频 ──
        fetchable = []
        for v in priority_videos:
            cid = v.get("_cid", 0) or v.get("cid", 0)
            if cid:
                fetchable.append((v, v.get("bvid", ""), cid))

        if not fetchable:
            return

        # 延迟初始化线程池（仅在面板可见时）
        if self._fetch_pool is None:
            self._fetch_pool = ThreadPoolExecutor(max_workers=MAX_VIEWER_FETCH_WORKERS)

        def _fetch_one(video, bvid, cid):
            """拉取单个视频的在线人数（持有 gui._data_lock 写入，与 worker 线程互斥）"""
            try:
                from core import bilibili_api
                viewers = bilibili_api.get_video_viewers(bvid, cid)
                if viewers:
                    with self.gui._data_lock:
                        video["viewers_total_raw"] = viewers.get("total", "0")
                        video["viewers_web_raw"] = viewers.get("count", "0")
                        video["viewers_total"] = _parse_viewer_count(viewers.get("total", "0"))
                        video["viewers_web"] = _parse_viewer_count(viewers.get("count", "0"))
                        video["viewers_app"] = max(0, video["viewers_total"] - video["viewers_web"])
                        video["_viewers_updated_at"] = datetime.now().timestamp()  # 供 worker 判断是否跳过
            except Exception:
                pass  # 单个视频失败不阻塞其他

        futures = [self._fetch_pool.submit(_fetch_one, v, bvid, cid) for v, bvid, cid in fetchable]
        # 等待全部完成（或超时 10 秒）
        for f in as_completed(futures, timeout=10):
            try:
                f.result()
            except Exception:
                pass

    def _populate(self):
        """填充树形表格数据：原地更新已有行（避免 delete+insert 产生临时对象），
        仅在视频增删时创建/销毁行。使用 bvid 作为 iid 便于跟踪。"""
        # ── 构建排序后的行数据 ──
        rows = []
        for video in self.gui.monitored_videos:
            bvid = video.get("bvid", "")
            title = video.get("title", bvid)
            view_count = video.get("view_count", 0)
            viewers_total = video.get("viewers_total", 0)
            viewers_web = video.get("viewers_web", 0)
            viewers_app = video.get("viewers_app", 0)
            online_rate = (viewers_total / view_count * 100) if view_count > 0 else 0
            rows.append((bvid, title, view_count, viewers_total, viewers_web, viewers_app, online_rate))

        col_key = self._sort_col
        reverse = self._sort_rev

        def _sort_key(r):
            idx_map = {
                "title": 1, "bvid": 0, "view_count": 2,
                "viewers_total": 3, "viewers_web": 4, "viewers_app": 5,
                "online_rate": 6, "rank": 3,
            }
            val = r[idx_map.get(col_key, 3)]
            if isinstance(val, str):
                return val.lower()
            return val

        rows.sort(key=_sort_key, reverse=reverse)

        self._count_lbl.config(text=f"共 {len(rows)} 个视频")
        self._status_lbl.config(text=f"共 {len(rows)} 个视频 · 按在线人数排序")

        # ── 集合运算：增删 vs 更新 ──
        new_bvids = {r[0] for r in rows}
        existing = set(self._tree.get_children())  # iid == bvid

        # 删除已移除的视频
        for iid in existing - new_bvids:
            self._tree.delete(iid)

        # 更新已有行 / 插入新行
        for i, r in enumerate(rows):
            bvid = r[0]
            tag = "even" if i % 2 == 0 else "odd"
            vt = r[3]
            if vt >= 10000:
                rate_tag = "online_high"
            elif vt >= 1000:
                rate_tag = "online_mid"
            else:
                rate_tag = "online_low"

            title_display = r[1][:40] + "\u2026" if len(r[1]) > 40 else r[1]
            rate_display = f"{r[6]:.2f}%" if r[6] > 0 else "\u2014"

            values = (
                i + 1, title_display, bvid,
                fmt_num(r[3]), fmt_num(r[4]), fmt_num(r[5]),
                fmt_num(r[2]), rate_display,
            )

            if bvid in existing:
                self._tree.item(bvid, values=values, tags=(tag, rate_tag))
            else:
                self._tree.insert("", tk.END, iid=bvid, values=values, tags=(tag, rate_tag))

        # ── 排序顺序修正：仅当顺序变化时移动行 ──
        desired_iids = [r[0] for r in rows]
        current_iids = list(self._tree.get_children())
        if desired_iids != current_iids:
            for target_idx, iid in enumerate(desired_iids):
                cur_idx = current_iids.index(iid) if iid in current_iids else -1
                if cur_idx != target_idx and cur_idx >= 0:
                    self._tree.move(iid, "", target_idx)
                    # 更新 current_iids 避免 O(n²) 漂移
                    current_iids.remove(iid)
                    current_iids.insert(target_idx, iid)

    def _update_ui_after_fetch(self):
        """在主线程中更新 UI（API 拉取完成后回调）"""
        self._populate()
        self._time_lbl.config(text=f"上次刷新: {datetime.now().strftime('%H:%M:%S')}")

    def on_show(self):
        """面板显示时立即刷新并启动秒级自动刷新"""
        self._active = True
        self._start_auto_refresh()
        self.refresh()  # 在 _active=True 之后调用，确保 UI 更新回调执行

    def on_hide(self):
        """面板隐藏时停止自动刷新，释放线程池"""
        self._active = False
        self._stop_auto_refresh()
        if self._fetch_pool:
            self._fetch_pool.shutdown(wait=False)
            self._fetch_pool = None

    def _start_auto_refresh(self):
        """启动定时自动刷新（秒级间隔）"""
        self._stop_auto_refresh()
        self._timer_id = self.frame.after(REFRESH_INTERVAL, self._auto_refresh_tick)

    def _stop_auto_refresh(self):
        """停止自动刷新定时器"""
        if self._timer_id:
            self.frame.after_cancel(self._timer_id)
            self._timer_id = None

    def _auto_refresh_tick(self):
        """自动刷新定时器触发：刷新数据并重新排程"""
        self.refresh()
        self._timer_id = self.frame.after(REFRESH_INTERVAL, self._auto_refresh_tick)
