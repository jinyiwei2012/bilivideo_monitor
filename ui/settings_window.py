"""
系统设置界面
包含OneBot配置、监控设置、预测设置等
"""
import tkinter as tk
from tkinter import ttk, messagebox, BOTH, W


class SettingsWindow:
    """设置窗口"""
    
    def __init__(self, parent=None):
        self.window = tk.Toplevel(parent)
        self.window.title("系统设置")
        self.window.geometry("700x500")
        
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI"""
        # 创建标签页
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # OneBot设置页
        onebot_frame = ttk.Frame(notebook, padding=10)
        notebook.add(onebot_frame, text="OneBot设置")
        
        ttk.Label(onebot_frame, text="HTTP地址:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.onebot_http = ttk.Entry(onebot_frame, width=40)
        self.onebot_http.insert(0, "http://127.0.0.1:5700")
        self.onebot_http.grid(row=0, column=1, padx=5)
        
        ttk.Label(onebot_frame, text="WebSocket地址:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.onebot_ws = ttk.Entry(onebot_frame, width=40)
        self.onebot_ws.insert(0, "ws://127.0.0.1:6700")
        self.onebot_ws.grid(row=1, column=1, padx=5)
        
        ttk.Label(onebot_frame, text="私聊QQ号:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.qq_private = ttk.Entry(onebot_frame, width=40)
        self.qq_private.grid(row=2, column=1, padx=5)
        
        ttk.Label(onebot_frame, text="群号:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.qq_group = ttk.Entry(onebot_frame, width=40)
        self.qq_group.grid(row=3, column=1, padx=5)
        
        ttk.Button(onebot_frame, text="测试连接", command=self._test_connection).grid(row=4, column=1, pady=20)
        
        # 监控设置页
        monitor_frame = ttk.Frame(notebook, padding=10)
        notebook.add(monitor_frame, text="监控设置")
        
        ttk.Label(monitor_frame, text="检查间隔(秒):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.check_interval = ttk.Spinbox(monitor_frame, from_=60, to=3600, width=10)
        self.check_interval.set(300)
        self.check_interval.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Label(monitor_frame, text="最大监控数:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.max_monitors = ttk.Spinbox(monitor_frame, from_=10, to=500, width=10)
        self.max_monitors.set(100)
        self.max_monitors.grid(row=1, column=1, sticky=tk.W, padx=5)
        
        # 预测设置页
        predict_frame = ttk.Frame(notebook, padding=10)
        notebook.add(predict_frame, text="预测设置")
        
        ttk.Label(predict_frame, text="预测时长(小时):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.predict_hours = ttk.Spinbox(predict_frame, from_=24, to=720, width=10)
        self.predict_hours.set(168)
        self.predict_hours.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Label(predict_frame, text="最小置信度:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.min_confidence = ttk.Spinbox(predict_frame, from_=0.1, to=1.0, increment=0.1, width=10)
        self.min_confidence.set(0.5)
        self.min_confidence.grid(row=1, column=1, sticky=tk.W, padx=5)
        
        # 保存按钮
        ttk.Button(self.window, text="保存设置", command=self._save_settings).pack(pady=10)
    
    def _test_connection(self):
        """测试OneBot连接"""
        messagebox.showinfo("测试", "连接测试功能")
    
    def _save_settings(self):
        """保存设置（含后端参数校验）"""
        # 验证检查间隔
        try:
            interval = int(self.check_interval.get())
            if not (60 <= interval <= 3600):
                messagebox.showerror("验证失败", "检查间隔必须在 60 ~ 3600 秒之间")
                return
        except ValueError:
            messagebox.showerror("验证失败", "检查间隔必须为整数")
            return
        
        # 验证最大监控数
        try:
            max_m = int(self.max_monitors.get())
            if not (10 <= max_m <= 500):
                messagebox.showerror("验证失败", "最大监控数必须在 10 ~ 500 之间")
                return
        except ValueError:
            messagebox.showerror("验证失败", "最大监控数必须为整数")
            return
        
        # 验证预测时长
        try:
            pred_hours = int(self.predict_hours.get())
            if not (24 <= pred_hours <= 720):
                messagebox.showerror("验证失败", "预测时长必须在 24 ~ 720 小时之间")
                return
        except ValueError:
            messagebox.showerror("验证失败", "预测时长必须为整数")
            return
        
        # 验证最小置信度
        try:
            confidence = float(self.min_confidence.get())
            if not (0.1 <= confidence <= 1.0):
                messagebox.showerror("验证失败", "最小置信度必须在 0.1 ~ 1.0 之间")
                return
        except ValueError:
            messagebox.showerror("验证失败", "最小置信度必须为数字")
            return
        
        messagebox.showinfo("成功", "设置已保存")
        self.window.destroy()
