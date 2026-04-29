"""
数据库查询界面
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import os
import re
import csv
from datetime import datetime
from typing import List, Dict, Optional


def _validate_bvid(bvid: str) -> bool:
    """验证BV号格式是否合法（BV + 10位字母数字）"""
    return bool(re.match(r'^BV[A-Za-z0-9]{10}$', bvid))


# 基础导出表头（固定列）
_BASE_EXPORT_HEADERS = [
    '序号', 'BV号', '时间', '播放量', '点赞', '投币',
    '分享', '收藏', '弹幕', '评论', 'APP观看', '网页观看', '总观看', '播赞比',
    # 周刊分数
    '周刊总分', '周刊播放', '周刊互动', '周刊收藏', '周刊硬币', '周刊点赞',
    '周刊修正A', '周刊修正B', '周刊修正C', '周刊修正D', '周刊基础播放',
    # 年刊分数
    '年刊总分', '年刊播放', '年刊互动', '年刊收藏', '年刊硬币', '年刊点赞',
    '年刊修正A', '年刊修正B', '年刊修正C',
]


def _build_export_headers(algo_names: list) -> list:
    """动态构建导出表头，包含所有算法的预测列
    
    Args:
        algo_names: 算法名列表（已排序）
    """
    # 在基础表头第14列（播赞比）后插入预测列
    headers = list(_BASE_EXPORT_HEADERS)
    for name in algo_names:
        headers.append(f'{name}_预测时间')
        headers.append(f'{name}_预测秒数')
        headers.append(f'{name}_置信度')
    return headers


def _build_export_row(index: int, row, extra: dict = None, algo_names: list = None) -> list:
    """将单条查询结果构建为导出行（CSV / Excel 共用）
    
    Args:
        row: monitor_records 的行（dict 或 sqlite3.Row）
        extra: 关联的预测/分数数据字典
        algo_names: 算法名列表（已排序），用于动态填充预测列
    """
    e = extra or {}
    algo_names = algo_names or []
    
    # 确保 row 是字典（sqlite3.Row 不支持 .get()）
    if hasattr(row, 'keys'):
        row = dict(row)
    
    # 构建每个算法的预测列
    algo_pred_map = {}
    predictions = e.get('_predictions', [])
    for pred in predictions:
        algo = pred.get('algorithm', '')
        # 用最近的预测记录（每个算法可能对多个阈值有预测，取最近一条）
        if algo not in algo_pred_map:
            algo_pred_map[algo] = pred
    
    base_row = [
        index,
        row['bvid'],
        row['timestamp'],
        row['view_count'],
        row['like_count'],
        row['coin_count'],
        row['share_count'],
        row['favorite_count'],
        row['danmaku_count'],
        row['reply_count'],
        row.get('viewers_app', '') or '',
        row.get('viewers_web', '') or '',
        row.get('viewers_total', '') or '',
        row.get('like_view_ratio', '') or '',
        # 周刊分数
        e.get('weekly_total', ''),
        e.get('weekly_view', ''),
        e.get('weekly_interaction', ''),
        e.get('weekly_favorite', ''),
        e.get('weekly_coin', ''),
        e.get('weekly_like', ''),
        e.get('weekly_corr_a', ''),
        e.get('weekly_corr_b', ''),
        e.get('weekly_corr_c', ''),
        e.get('weekly_corr_d', ''),
        e.get('weekly_base_view', ''),
        # 年刊分数
        e.get('yearly_total', ''),
        e.get('yearly_view', ''),
        e.get('yearly_interaction', ''),
        e.get('yearly_favorite', ''),
        e.get('yearly_coin', ''),
        e.get('yearly_like', ''),
        e.get('yearly_corr_a', ''),
        e.get('yearly_corr_b', ''),
        e.get('yearly_corr_c', ''),
    ]
    
    # 追加每个算法的预测列
    for name in algo_names:
        pred = algo_pred_map.get(name, {})
        base_row.append(pred.get('predicted_time', ''))
        base_row.append(pred.get('predicted_seconds', ''))
        base_row.append(pred.get('confidence', ''))
    
    return base_row


class DatabaseQueryWindow:
    """数据库查询窗口"""
    
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("数据库查询")
        self.window.geometry("1000x700")
        
        self.db_path = self._get_db_path()
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self._query_running = False  # 防止重复点击
        
        self.setup_ui()
        self.load_videos_list()
    
    def _get_db_path(self) -> str:
        """获取数据库路径"""
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(current_dir, 'data', 'bilibili_monitor.db')
    
    def setup_ui(self):
        """设置UI"""
        # 顶部查询区域
        query_frame = ttk.LabelFrame(self.window, text="查询条件", padding=10)
        query_frame.pack(fill='x', padx=10, pady=10)
        
        # 第一行：视频筛选（全局）
        filter_row = ttk.Frame(query_frame)
        filter_row.pack(fill='x', pady=5)
        
        ttk.Label(filter_row, text="视频筛选:").pack(side='left')
        self.video_filter_var = tk.StringVar(value="全部视频")
        self.video_filter_combo = ttk.Combobox(
            filter_row, textvariable=self.video_filter_var,
            state='readonly', width=40)
        self.video_filter_combo.pack(side='left', padx=5)
        
        # 第二行：查询方式选择
        mode_frame = ttk.Frame(query_frame)
        mode_frame.pack(fill='x', pady=5)
        
        ttk.Label(mode_frame, text="查询方式:").pack(side='left')
        self.query_mode = tk.StringVar(value="latest")
        
        mode_combo = ttk.Combobox(mode_frame, textvariable=self.query_mode,
                                   values=['最新N条', '播放首次大于X', '播放趋势', '全量数据'],
                                   state='readonly', width=15)
        mode_combo.pack(side='left', padx=5)
        mode_combo.bind('<<ComboboxSelected>>', lambda e: self._on_mode_change())
        
        # 参数输入区
        self.param_frame = ttk.Frame(query_frame)
        self.param_frame.pack(fill='x', pady=5)
        
        # 视频选择（用于播放趋势查询，复用 video_filter_combo）
        self.video_combo = None
        self.video_combo_var = tk.StringVar()
        
        # 查询按钮
        btn_frame = ttk.Frame(query_frame)
        btn_frame.pack(fill='x', pady=10)
        
        self._query_btn = ttk.Button(btn_frame, text="查询", command=self._do_query)
        self._query_btn.pack(side='left', padx=5)
        ttk.Button(btn_frame, text="重置", command=self._reset_query).pack(side='left', padx=5)
        
        self._on_mode_change()
        
        # 结果区域（container 管理整体伸缩，按钮固定底部）
        container = ttk.Frame(self.window)
        container.pack(fill='both', expand=True, padx=10, pady=10)
        
        result_frame = ttk.LabelFrame(container, text="查询结果", padding=10)
        result_frame.pack(fill='both', expand=True)
        
        # 创建表格
        columns = ('seq', 'bv', 'timestamp', 'views', 'likes', 'coins', 'shares', 'favorites',
                   'danmaku', 'reply', 'viewers_total', 'viewers_web', 'viewers_app', 'like_ratio')
        self.result_tree = ttk.Treeview(result_frame, columns=columns, show='headings', height=15)
        
        col_configs = [
            ('seq', '序号', 50),
            ('bv', 'BV号', 120),
            ('timestamp', '时间', 150),
            ('views', '播放量', 90),
            ('likes', '点赞', 75),
            ('coins', '投币', 75),
            ('shares', '分享', 75),
            ('favorites', '收藏', 75),
            ('danmaku', '弹幕', 75),
            ('reply', '评论', 75),
            ('viewers_total', '总在线', 75),
            ('viewers_web', 'Web在线', 75),
            ('viewers_app', 'APP在线', 75),
            ('like_ratio', '播赞比', 75),
        ]
        
        for col, heading, width in col_configs:
            self.result_tree.column(col, width=width, anchor='center')
            self.result_tree.heading(col, text=heading)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scrollbar.set)
        
        self.result_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # 底部按钮区（放在 container 中，紧跟 result_frame 下方）
        btn_area = ttk.Frame(container)
        btn_area.pack(fill='x', pady=(5, 0))
        
        ttk.Button(btn_area, text="导出CSV", command=self._export_csv).pack(side='left', padx=5)
        ttk.Button(btn_area, text="导出Excel", command=self._export_excel).pack(side='left', padx=5)
        ttk.Button(btn_area, text="删除选中", command=self._delete_selected).pack(side='left', padx=5)
        ttk.Button(btn_area, text="清空结果", command=self._clear_results).pack(side='left', padx=5)
        
        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(btn_area, textvariable=self.status_var).pack(side='right')
    
    def _get_filter_bvid(self) -> Optional[str]:
        """从全局视频筛选下拉框获取 bvid，返回 None 表示不筛选"""
        selection = self.video_filter_var.get()
        if selection == "全部视频" or not selection:
            return None
        return self._video_bvid_map.get(selection)

    def _load_extra_data(self, bvid: str, timestamp: str) -> dict:
        """从视频独立数据库加载与记录时间最近的预测和分数数据
        
        Args:
            bvid: 视频BV号
            timestamp: 记录时间戳
            
        Returns:
            包含关联数据的字典
        """
        extra = {}
        video_db_path = os.path.join(
            os.path.dirname(self.db_path), bvid, f"{bvid}.db")
        
        if not os.path.exists(video_db_path):
            return extra
        
        try:
            # 以只读模式打开，避免与 VideoDatabase 长连接发生锁竞争
            uri = "file:{}?mode=ro".format(
                video_db_path.replace("\\", "/").replace(" ", "%20"))
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 查找时间点之前/最近的所有算法预测记录
            cursor.execute('''
                SELECT * FROM predictions 
                WHERE created_at <= ?
                ORDER BY algorithm, created_at DESC
            ''', (timestamp,))
            pred_rows = cursor.fetchall()
            # 每个算法只保留最近一条记录
            seen_algo = set()
            pred_list = []
            for pr in pred_rows:
                algo_name = pr['algorithm']
                if algo_name not in seen_algo:
                    seen_algo.add(algo_name)
                    pred_list.append(dict(pr))
            extra['_predictions'] = pred_list
            
            # 查找时间点之前/最近的周刊分数
            cursor.execute('''
                SELECT * FROM weekly_scores 
                WHERE timestamp <= ?
                ORDER BY timestamp DESC LIMIT 1
            ''', (timestamp,))
            ws_row = cursor.fetchone()
            if ws_row:
                ws = dict(ws_row)
                extra['weekly_total'] = ws.get('total_score', '')
                extra['weekly_view'] = ws.get('view_score', '')
                extra['weekly_interaction'] = ws.get('interaction_score', '')
                extra['weekly_favorite'] = ws.get('favorite_score', '')
                extra['weekly_coin'] = ws.get('coin_score', '')
                extra['weekly_like'] = ws.get('like_score', '')
                extra['weekly_corr_a'] = ws.get('correction_a', '')
                extra['weekly_corr_b'] = ws.get('correction_b', '')
                extra['weekly_corr_c'] = ws.get('correction_c', '')
                extra['weekly_corr_d'] = ws.get('correction_d', '')
                extra['weekly_base_view'] = ws.get('base_view_score', '')
            
            # 查找时间点之前/最近的年刊分数
            cursor.execute('''
                SELECT * FROM yearly_scores 
                WHERE timestamp <= ?
                ORDER BY timestamp DESC LIMIT 1
            ''', (timestamp,))
            ys_row = cursor.fetchone()
            if ys_row:
                ys = dict(ys_row)
                extra['yearly_total'] = ys.get('total_score', '')
                extra['yearly_view'] = ys.get('view_score', '')
                extra['yearly_interaction'] = ys.get('interaction_score', '')
                extra['yearly_favorite'] = ys.get('favorite_score', '')
                extra['yearly_coin'] = ys.get('coin_score', '')
                extra['yearly_like'] = ys.get('like_score', '')
                extra['yearly_corr_a'] = ys.get('correction_a', '')
                extra['yearly_corr_b'] = ys.get('correction_b', '')
                extra['yearly_corr_c'] = ys.get('correction_c', '')
            
            conn.close()
        except Exception as e:
            print(f"加载关联数据失败 {bvid}: {e}")
        
        return extra

    def _on_mode_change(self):
        """查询模式改变"""
        # 清除现有参数控件
        for widget in self.param_frame.winfo_children():
            widget.destroy()
        
        mode = self.query_mode.get()
        
        if mode == '最新N条':
            ttk.Label(self.param_frame, text="数量N:").pack(side='left')
            self.param_var = tk.StringVar(value="100")
            ttk.Entry(self.param_frame, textvariable=self.param_var, width=10).pack(side='left', padx=5)
            ttk.Label(self.param_frame, text="(输入要查询的记录数)").pack(side='left')
            
        elif mode == '播放首次大于X':
            ttk.Label(self.param_frame, text="播放量X:").pack(side='left')
            self.param_var = tk.StringVar(value="10000")
            ttk.Entry(self.param_frame, textvariable=self.param_var, width=15).pack(side='left', padx=5)
            ttk.Label(self.param_frame, text="(查找播放量首次超过此值的记录)").pack(side='left')
            
        elif mode == '播放趋势':
            ttk.Label(self.param_frame, text="选择视频:").pack(side='left')
            self.video_combo = ttk.Combobox(self.param_frame, textvariable=self.video_combo_var,
                                            state='readonly', width=30)
            self.video_combo.pack(side='left', padx=5)
            
        elif mode == '全量数据':
            ttk.Label(self.param_frame, text="(将导出所有监控记录数据)").pack(side='left')
    
    def load_videos_list(self):
        """加载视频列表"""
        if not os.path.exists(self.db_path):
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT bvid, title FROM videos ORDER BY updated_at DESC')
            videos = cursor.fetchall()
            
            # 全局视频筛选列表（带"全部视频"选项）
            video_items = ["全部视频"]
            self._video_bvid_map = {}  # display_text -> bvid
            for v in videos:
                display = f"{v['bvid']} - {v['title']}"
                video_items.append(display)
                self._video_bvid_map[display] = v['bvid']
            
            self.video_filter_combo['values'] = video_items
            self.video_filter_combo.current(0)
            
            # 播放趋势模式下的下拉框（复用同样的列表）
            if self.video_combo:
                trend_items = video_items[1:]  # 不含"全部视频"
                self.video_combo['values'] = trend_items
            
            conn.close()
        except Exception as e:
            print(f"加载视频列表失败: {e}")
    
    def _do_query(self):
        """执行查询（异步后台线程，避免 UI 卡死）"""
        if not os.path.exists(self.db_path):
            messagebox.showerror("错误", "数据库文件不存在")
            return
        if self._query_running:
            return  # 防止重复点击

        mode = self.query_mode.get()
        filter_bvid = self._get_filter_bvid()

        # 趋势模式需提前在主线程读取 combo 值
        bvid_for_trend = None
        if mode == '播放趋势':
            selection = self.video_combo_var.get()
            if not selection:
                if filter_bvid:
                    bvid_for_trend = filter_bvid
                else:
                    messagebox.showwarning("提示", "请选择视频")
                    return
            else:
                bvid_for_trend = selection.split()[0] if ' ' in selection else selection
                if filter_bvid:
                    bvid_for_trend = filter_bvid
            if not _validate_bvid(bvid_for_trend):
                messagebox.showerror("错误", "选中视频的BV号格式无效")
                return

        # 切换为加载状态
        self._query_running = True
        self._query_btn.config(state='disabled', text='查询中…')
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self.status_var.set("查询中，请稍候…")

        import threading

        def _worker():
            raw_rows = []
            err_msg = None
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if mode == '最新N条':
                    limit = int(getattr(self, 'param_var', None) and self.param_var.get() or 100)
                    if filter_bvid:
                        cursor.execute('''
                            SELECT * FROM monitor_records 
                            WHERE bvid = ?
                            ORDER BY timestamp DESC 
                            LIMIT ?
                        ''', (filter_bvid, limit))
                    else:
                        cursor.execute('''
                            SELECT * FROM monitor_records 
                            ORDER BY timestamp DESC 
                            LIMIT ?
                        ''', (limit,))

                elif mode == '播放首次大于X':
                    threshold = int(getattr(self, 'param_var', None) and self.param_var.get() or 10000)
                    if filter_bvid:
                        cursor.execute('''
                            SELECT * FROM monitor_records
                            WHERE bvid = ? AND view_count > ?
                            ORDER BY timestamp ASC
                            LIMIT 1
                        ''', (filter_bvid, threshold))
                    else:
                        cursor.execute('''
                            WITH FirstAbove AS (
                                SELECT bvid, MIN(timestamp) as first_ts
                                FROM monitor_records
                                WHERE view_count > ?
                                GROUP BY bvid
                            )
                            SELECT m.* FROM monitor_records m
                            INNER JOIN FirstAbove f ON m.bvid = f.bvid AND m.timestamp = f.first_ts
                            ORDER BY m.timestamp DESC
                        ''', (threshold,))

                elif mode == '播放趋势':
                    cursor.execute('''
                        SELECT * FROM monitor_records 
                        WHERE bvid = ?
                        ORDER BY timestamp ASC
                    ''', (bvid_for_trend,))

                elif mode == '全量数据':
                    if filter_bvid:
                        cursor.execute('''
                            SELECT * FROM monitor_records 
                            WHERE bvid = ?
                            ORDER BY timestamp DESC
                        ''', (filter_bvid,))
                    else:
                        cursor.execute('SELECT * FROM monitor_records ORDER BY timestamp DESC')

                raw_rows = [dict(r) for r in cursor.fetchall()]
                conn.close()
            except Exception as e:
                err_msg = str(e)

            if err_msg:
                self.window.after(0, lambda: (
                    messagebox.showerror("错误", f"查询失败: {err_msg}"),
                    self._reset_query_state()
                ))
                return

            total = len(raw_rows)
            self.window.after(0, lambda: self.status_var.set(
                f"查询到 {total} 条记录，正在加载关联数据…"))

            # 加载 extra_data（在后台线程，按批次更新进度）
            extra_list = []
            all_algo_names = set()
            batch = max(1, total // 20)  # 每 5% 更新一次进度
            for idx, row in enumerate(raw_rows):
                bvid = row['bvid']
                ts = row['timestamp']
                extra = self._load_extra_data(bvid, ts)
                extra_list.append(extra)
                for pred in extra.get('_predictions', []):
                    all_algo_names.add(pred.get('algorithm', ''))
                if total > 50 and (idx + 1) % batch == 0:
                    progress = idx + 1
                    self.window.after(0, lambda p=progress, t=total: self.status_var.set(
                        f"加载关联数据 {p}/{t}…"))

            known_order = [
                '线性增长', '移动平均', '加权移动平均', '指数平滑',
                '趋势外推', 'Gompertz',
            ]
            algo_names = sorted(
                all_algo_names,
                key=lambda n: (known_order.index(n) if n in known_order else len(known_order), n)
            )

            # 回到主线程刷新 Treeview
            self.window.after(0, lambda: self._finish_query(raw_rows, extra_list, algo_names))

        threading.Thread(target=_worker, daemon=True).start()

    def _reset_query_state(self):
        """恢复查询按钮可用状态"""
        self._query_running = False
        self._query_btn.config(state='normal', text='查询')

    def _finish_query(self, raw_rows, extra_list, algo_names):
        """后台查询完成后，在主线程刷新 Treeview"""
        self.query_results = raw_rows
        self._extra_data = extra_list
        self._algo_names = algo_names

        self.result_tree.delete(*self.result_tree.get_children())
        for i, row in enumerate(raw_rows, 1):
            like_ratio = row.get('like_view_ratio') or 0
            values = (
                i,
                row['bvid'],
                row['timestamp'],
                f"{row['view_count']:,}",
                f"{row['like_count']:,}",
                f"{row['coin_count']:,}",
                f"{row['share_count']:,}",
                f"{row['favorite_count']:,}",
                f"{row['danmaku_count']:,}",
                f"{row['reply_count']:,}",
                f"{(row.get('viewers_total') or 0):,}",
                f"{(row.get('viewers_web') or 0):,}",
                f"{(row.get('viewers_app') or 0):,}",
                f"{like_ratio:.4f}",
            )
            self.result_tree.insert('', 'end', values=values, tags=(row['bvid'],))

        self.status_var.set(f"查询到 {len(raw_rows)} 条记录")
        self._reset_query_state()
    
    def _reset_query(self):
        """重置查询"""
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self.status_var.set("就绪")
    
    def _get_export_default_name(self, extension: str) -> str:
        """生成导出文件的默认文件名（CSV / Excel 共用）"""
        mode = self.query_mode.get()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filter_bvid = self._get_filter_bvid()
        video_tag = f"_{filter_bvid}" if filter_bvid else ""
        mode_name = {
            '最新N条': 'latest',
            '播放首次大于X': f'above{self.param_var.get()}',
            '播放趋势': self.video_combo_var.get().split()[0] if self.video_combo_var.get() else 'trend',
            '全量数据': 'all',
        }.get(mode, 'query')
        return f"{mode_name}{video_tag}_{timestamp}.{extension}"

    def _export_csv(self):
        """导出CSV"""
        if not self.query_results:
            messagebox.showwarning("提示", "没有可导出的数据")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="导出CSV",
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=self._get_export_default_name("csv")
        )
        if not filepath:
            return
        
        try:
            headers = _build_export_headers(self._algo_names)
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                extra_list = getattr(self, '_extra_data', [])
                for i, row in enumerate(self.query_results, 1):
                    extra = extra_list[i - 1] if i - 1 < len(extra_list) else None
                    writer.writerow(_build_export_row(i, row, extra, self._algo_names))
            messagebox.showinfo("成功", f"已导出到:\n{filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")
    
    def _export_excel(self):
        """导出Excel"""
        if not self.query_results:
            messagebox.showwarning("提示", "没有可导出的数据")
            return
        
        try:
            import openpyxl
        except ImportError:
            messagebox.showerror("错误", "需要安装 openpyxl 库\n请运行: pip install openpyxl")
            return
        
        filepath = filedialog.asksaveasfilename(
            title="导出Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
            initialfile=self._get_export_default_name("xlsx")
        )
        if not filepath:
            return
        
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "查询结果"
            headers = _build_export_headers(self._algo_names)
            ws.append(headers)
            extra_list = getattr(self, '_extra_data', [])
            for i, row in enumerate(self.query_results, 1):
                extra = extra_list[i - 1] if i - 1 < len(extra_list) else None
                ws.append(_build_export_row(i, row, extra, self._algo_names))
            
            # 自动调整列宽
            for col in ws.columns:
                max_length = max(
                    (len(str(cell.value)) for cell in col if cell.value is not None),
                    default=0
                )
                ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)
            
            wb.save(filepath)
            messagebox.showinfo("成功", f"已导出到:\n{filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")
    
    def _delete_selected(self):
        """删除选中记录"""
        selection = self.result_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的记录")
            return
        
        if not messagebox.askyesno("确认", f"确定要删除选中的 {len(selection)} 条记录吗？"):
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for item in selection:
                values = self.result_tree.item(item)['values']
                bvid = values[1]
                timestamp = values[2]
                
                cursor.execute('''
                    DELETE FROM monitor_records 
                    WHERE bvid = ? AND timestamp = ?
                ''', (bvid, timestamp))
                
                # 从查询结果中移除
                self.query_results = [r for r in self.query_results 
                                       if not (r['bvid'] == bvid and r['timestamp'] == timestamp)]
            
            conn.commit()
            conn.close()
            
            # 刷新显示
            self._do_query()
            self.status_var.set(f"已删除 {len(selection)} 条记录")
            
        except Exception as e:
            messagebox.showerror("错误", f"删除失败: {e}")
    
    def _clear_results(self):
        """清空结果"""
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self._extra_data = []
        self._algo_names = []
        self.status_var.set("已清空结果")
