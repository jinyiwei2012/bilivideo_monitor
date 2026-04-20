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


# 导出表头（CSV / Excel 共用）
_EXPORT_HEADERS = [
    '序号', 'BV号', '时间', '播放量', '点赞', '投币',
    '分享', '收藏', '弹幕', '评论', 'APP观看', '网页观看', '总观看', '播赞比',
]


def _build_export_row(index: int, row) -> list:
    """将单条查询结果构建为导出行（CSV / Excel 共用）"""
    return [
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
        row['viewers_app'],
        row['viewers_web'],
        row['viewers_total'],
        row['like_view_ratio'],
    ]


class DatabaseQueryWindow:
    """数据库查询窗口"""
    
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("数据库查询")
        self.window.geometry("1000x700")
        
        self.db_path = self._get_db_path()
        self.query_results = []
        
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
        
        # 查询方式选择
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
        
        # 视频选择（用于播放趋势查询）
        self.video_combo = None
        self.video_combo_var = tk.StringVar()
        
        # 查询按钮
        btn_frame = ttk.Frame(query_frame)
        btn_frame.pack(fill='x', pady=10)
        
        ttk.Button(btn_frame, text="查询", command=self._do_query).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="重置", command=self._reset_query).pack(side='left', padx=5)
        
        self._on_mode_change()
        
        # 结果区域
        result_frame = ttk.LabelFrame(self.window, text="查询结果", padding=10)
        result_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # 创建表格
        columns = ('bv', 'timestamp', 'views', 'likes', 'coins', 'shares', 'favorites', 'danmaku', 'reply')
        self.result_tree = ttk.Treeview(result_frame, columns=columns, show='tree headings', height=20)
        
        # 设置列
        self.result_tree.column('#0', width=50, stretch=False)
        self.result_tree.heading('#0', text='序号')
        
        col_configs = [
            ('bv', 'BV号', 120),
            ('timestamp', '时间', 150),
            ('views', '播放量', 100),
            ('likes', '点赞', 80),
            ('coins', '投币', 80),
            ('shares', '分享', 80),
            ('favorites', '收藏', 80),
            ('danmaku', '弹幕', 80),
            ('reply', '评论', 80),
        ]
        
        for col, heading, width in col_configs:
            self.result_tree.column(col, width=width, anchor='center')
            self.result_tree.heading(col, text=heading)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scrollbar.set)
        
        self.result_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # 底部按钮区
        btn_area = ttk.Frame(self.window)
        btn_area.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(btn_area, text="导出CSV", command=self._export_csv).pack(side='left', padx=5)
        ttk.Button(btn_area, text="导出Excel", command=self._export_excel).pack(side='left', padx=5)
        ttk.Button(btn_area, text="删除选中", command=self._delete_selected).pack(side='left', padx=5)
        ttk.Button(btn_area, text="清空结果", command=self._clear_results).pack(side='left', padx=5)
        
        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(btn_area, textvariable=self.status_var).pack(side='right')
    
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
            
            if self.video_combo:
                video_list = [f"{v['bvid']} - {v['title'][:20]}..." for v in videos]
                self.video_combo['values'] = video_list
            
            conn.close()
        except Exception as e:
            print(f"加载视频列表失败: {e}")
    
    def _do_query(self):
        """执行查询"""
        if not os.path.exists(self.db_path):
            messagebox.showerror("错误", "数据库文件不存在")
            return
        
        mode = self.query_mode.get()
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if mode == '最新N条':
                limit = int(self.param_var.get() or 100)
                cursor.execute('''
                    SELECT * FROM monitor_records 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (limit,))
                self.query_results = cursor.fetchall()
                
            elif mode == '播放首次大于X':
                threshold = int(self.param_var.get() or 10000)
                # 查找每个BV号首次超过阈值的记录
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
                self.query_results = cursor.fetchall()
                
            elif mode == '播放趋势':
                selection = self.video_combo_var.get()
                if not selection:
                    messagebox.showwarning("提示", "请选择视频")
                    conn.close()
                    return
                
                bvid = selection.split()[0]
                if not _validate_bvid(bvid):
                    messagebox.showerror("错误", "选中视频的BV号格式无效")
                    conn.close()
                    return
                cursor.execute('''
                    SELECT * FROM monitor_records 
                    WHERE bvid = ?
                    ORDER BY timestamp ASC
                ''', (bvid,))
                self.query_results = cursor.fetchall()
                
            elif mode == '全量数据':
                cursor.execute('SELECT * FROM monitor_records ORDER BY timestamp DESC')
                self.query_results = cursor.fetchall()
            
            conn.close()
            
            # 显示结果
            for i, row in enumerate(self.query_results, 1):
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
                )
                self.result_tree.insert('', 'end', values=values, tags=(row['bvid'],))
            
            self.status_var.set(f"查询到 {len(self.query_results)} 条记录")
            
        except Exception as e:
            messagebox.showerror("错误", f"查询失败: {e}")
    
    def _reset_query(self):
        """重置查询"""
        self.result_tree.delete(*self.result_tree.get_children())
        self.query_results = []
        self.status_var.set("就绪")
    
    def _get_export_default_name(self, extension: str) -> str:
        """生成导出文件的默认文件名（CSV / Excel 共用）"""
        mode = self.query_mode.get()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_name = {
            '最新N条': 'latest',
            '播放首次大于X': f'above{self.param_var.get()}',
            '播放趋势': self.video_combo_var.get().split()[0] if self.video_combo_var.get() else 'trend',
            '全量数据': 'all',
        }.get(mode, 'query')
        return f"{mode_name}_{timestamp}.{extension}"

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
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(_EXPORT_HEADERS)
                for i, row in enumerate(self.query_results, 1):
                    writer.writerow(_build_export_row(i, row))
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
            ws.append(_EXPORT_HEADERS)
            for i, row in enumerate(self.query_results, 1):
                ws.append(_build_export_row(i, row))
            
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
        self.status_var.set("已清空结果")
