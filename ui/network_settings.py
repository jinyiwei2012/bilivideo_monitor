"""
网络设置窗口 - 配置代理、Cookie等网络参数
用于绕过B站412频率限制
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import os
from core.bilibili_api import bilibili_api
from ui.theme import C


class NetworkSettingsWindow:
    """网络设置窗口"""
    
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("网络设置 - 412错误处理")
        self.window.geometry("600x500")
        self.window.transient(parent)
        self.window.grab_set()
        
        # 加载保存的配置
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'network_config.json')
        self.config = self._load_config()
        
        self._create_widgets()
        self._load_current_status()
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {'proxies': [], 'cookies': {}}
    
    def _save_config(self):
        """保存配置"""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
    
    def _create_widgets(self):
        """创建控件"""
        # 标题
        title_frame = ttk.Frame(self.window)
        title_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(title_frame, text="网络设置", font=('Arial', 14, 'bold')).pack(side='left')
        ttk.Label(title_frame, text="用于配置代理和Cookie，绕过B站412频率限制", 
                 font=('', 9), foreground=C["text_3"]).pack(side='left', padx=10)
        
        # Notebook分页
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill='both', expand=True, padx=10, pady=5)
        
        # === 代理设置页面 ===
        proxy_frame = ttk.Frame(notebook, padding=10)
        notebook.add(proxy_frame, text='代理设置')
        
        ttk.Label(proxy_frame, text="HTTP代理列表（每行一个，格式: http://host:port 或 http://user:pass@host:port）",
                 font=('', 9)).pack(anchor='w')
        
        proxy_text = scrolledtext.ScrolledText(proxy_frame, height=8, width=60, font=('', 10))
        proxy_text.pack(fill='x', pady=5)
        
        # 预填现有代理
        if self.config.get('proxies'):
            proxy_text.insert('1.0', '\n'.join(self.config.get('proxies', [])))
        self.proxy_text = proxy_text
        
        btn_frame = ttk.Frame(proxy_frame)
        btn_frame.pack(fill='x', pady=5)
        
        ttk.Button(btn_frame, text="应用代理", command=self._apply_proxies).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="清空代理", command=self._clear_proxies).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="从配置文件加载", command=self._load_proxies_from_config).pack(side='left', padx=5)
        
        ttk.Label(proxy_frame, text="提示: 使用代理可有效绕过IP级别的频率限制",
                 font=('', 9), foreground=C["warning"]).pack(anchor='w', pady=5)
        
        # === Cookie设置页面 ===
        cookie_frame = ttk.Frame(notebook, padding=10)
        notebook.add(cookie_frame, text='Cookie设置')
        
        ttk.Label(cookie_frame, text="B站Cookie（SESSDATA等，用于保持登录状态）",
                 font=('', 9)).pack(anchor='w')
        ttk.Label(cookie_frame, text="格式: name=value; name=value; ...",
                 font=('', 8), foreground=C["text_3"]).pack(anchor='w')
        
        cookie_text = scrolledtext.ScrolledText(cookie_frame, height=6, width=60, font=('', 10))
        cookie_text.pack(fill='x', pady=5)
        
        if self.config.get('cookies'):
            cookie_str = '; '.join(f'{k}={v}' for k, v in self.config.get('cookies', {}).items())
            cookie_text.insert('1.0', cookie_str)
        self.cookie_text = cookie_text
        
        ttk.Button(cookie_frame, text="应用Cookie", command=self._apply_cookies).pack(anchor='w', pady=5)
        
        ttk.Label(cookie_frame, text="提示: 设置有效的Cookie可提高请求成功率，降低被风控概率",
                 font=('', 9), foreground=C["warning"]).pack(anchor='w', pady=5)
        
        # === 状态与重试设置页面 ===
        status_frame = ttk.Frame(notebook, padding=10)
        notebook.add(status_frame, text='状态与重试')
        
        # 当前状态
        status_group = ttk.LabelFrame(status_frame, text='当前API状态', padding=10)
        status_group.pack(fill='x', pady=5)
        
        self.status_labels = {}
        for i, key in enumerate(['consecutive_412_errors', 'min_request_interval', 'proxy_count', 'has_cookies']):
            frame = ttk.Frame(status_group)
            frame.pack(fill='x')
            ttk.Label(frame, text=f"{key}:", width=25).pack(side='left')
            value_label = ttk.Label(frame, text="-", foreground=C["success"])
            value_label.pack(side='left')
            self.status_labels[key] = value_label
        
        btn_status_frame = ttk.Frame(status_group)
        btn_status_frame.pack(fill='x', pady=10)
        
        ttk.Button(btn_status_frame, text="刷新状态", command=self._refresh_status).pack(side='left', padx=5)
        ttk.Button(btn_status_frame, text="重置状态", command=self._reset_status).pack(side='left', padx=5)
        
        # 重试设置
        retry_group = ttk.LabelFrame(status_frame, text='重试参数', padding=10)
        retry_group.pack(fill='x', pady=5)
        
        ttk.Label(retry_group, text="最大重试次数:").pack(anchor='w')
        self.retry_count_var = tk.IntVar(value=bilibili_api.max_retries)
        retry_count_spin = ttk.Spinbox(retry_group, from_=1, to=10, textvariable=self.retry_count_var, width=10)
        retry_count_spin.pack(anchor='w', pady=2)
        
        ttk.Label(retry_group, text="基础重试延迟(秒):").pack(anchor='w')
        self.base_delay_var = tk.DoubleVar(value=bilibili_api.base_retry_delay)
        base_delay_spin = ttk.Spinbox(retry_group, from_=1, to=30, textvariable=self.base_delay_var, width=10)
        base_delay_spin.pack(anchor='w', pady=2)
        
        ttk.Label(retry_group, text="最小请求间隔(秒):").pack(anchor='w')
        self.min_interval_var = tk.DoubleVar(value=bilibili_api._min_request_interval)
        min_interval_spin = ttk.Spinbox(retry_group, from_=0.1, to=10, textvariable=self.min_interval_var, width=10)
        min_interval_spin.pack(anchor='w', pady=2)
        
        ttk.Button(retry_group, text="应用设置", command=self._apply_retry_settings).pack(anchor='w', pady=5)
        
        # === 日志页面 ===
        log_frame = ttk.Frame(notebook, padding=10)
        notebook.add(log_frame, text='重试日志')
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=70, font=('', 9))
        self.log_text.pack(fill='both', expand=True)
        
        ttk.Button(log_frame, text="清空日志", command=lambda: self.log_text.delete('1.0', 'end')).pack(pady=5)
        
        # 底部按钮
        bottom_frame = ttk.Frame(self.window, padding=10)
        bottom_frame.pack(fill='x')
        
        ttk.Button(bottom_frame, text="保存所有设置", command=self._save_all).pack(side='right', padx=5)
        ttk.Button(bottom_frame, text="关闭", command=self.window.destroy).pack(side='right')
    
    def _apply_proxies(self):
        """应用代理设置"""
        text = self.proxy_text.get('1.0', 'end').strip()
        proxy_list = [line.strip() for line in text.split('\n') if line.strip()]
        
        bilibili_api.clear_proxies()
        for proxy_str in proxy_list:
            proxy = {
                'http': proxy_str,
                'https': proxy_str
            }
            bilibili_api.add_proxy(proxy)
        
        self._log(f"已应用 {len(proxy_list)} 个代理")
        messagebox.showinfo("成功", f"已应用 {len(proxy_list)} 个代理")
    
    def _clear_proxies(self):
        """清空代理"""
        self.proxy_text.delete('1.0', 'end')
        bilibili_api.clear_proxies()
        self._log("已清空所有代理")
    
    def _load_proxies_from_config(self):
        """从配置文件加载代理"""
        self.proxy_text.delete('1.0', 'end')
        if self.config.get('proxies'):
            self.proxy_text.insert('1.0', '\n'.join(self.config.get('proxies', [])))
        self._log("已从配置文件加载代理列表")
    
    def _apply_cookies(self):
        """应用Cookie设置"""
        text = self.cookie_text.get('1.0', 'end').strip()
        if not text:
            messagebox.showwarning("警告", "Cookie不能为空")
            return
        
        cookies = {}
        for item in text.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                cookies[key.strip()] = value.strip()
        
        bilibili_api.set_cookies(cookies)
        self.config['cookies'] = cookies
        self._log(f"已应用Cookie: {list(cookies.keys())}")
        messagebox.showinfo("成功", f"已应用Cookie: {list(cookies.keys())}")
    
    def _refresh_status(self):
        """刷新状态"""
        status = bilibili_api.get_status()
        for key, label in self.status_labels.items():
            value = status.get(key, 'N/A')
            if key == 'has_cookies':
                value = '是' if value else '否'
                label.config(foreground=C["success"] if value == '是' else C["danger"])
            elif key == 'consecutive_412_errors':
                label.config(foreground=C["danger"] if value > 0 else C["success"])
            else:
                label.config(foreground=C["success"])
            label.config(text=str(value))
        self._log("状态已刷新")
    
    def _reset_status(self):
        """重置状态"""
        if messagebox.askyesno("确认", "确定要重置所有状态吗？"):
            bilibili_api.reset_status()
            self._refresh_status()
            self._log("API状态已重置")
    
    def _apply_retry_settings(self):
        """应用重试设置"""
        bilibili_api.max_retries = self.retry_count_var.get()
        bilibili_api.base_retry_delay = self.base_delay_var.get()
        bilibili_api._min_request_interval = self.min_interval_var.get()
        
        self._log(f"重试设置已更新: 最大{bilibili_api.max_retries}次, 延迟{bilibili_api.base_retry_delay}s, 间隔{bilibili_api._min_request_interval}s")
        messagebox.showinfo("成功", "重试设置已更新")
    
    def _load_current_status(self):
        """加载当前状态"""
        self._refresh_status()
    
    def _log(self, message: str):
        """添加日志"""
        from datetime import datetime
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert('end', f"[{timestamp}] {message}\n")
        self.log_text.see('end')
    
    def _save_all(self):
        """保存所有设置"""
        # 保存代理列表
        text = self.proxy_text.get('1.0', 'end').strip()
        self.config['proxies'] = [line.strip() for line in text.split('\n') if line.strip()]
        
        self._save_config()
        self._log("所有设置已保存到配置文件")
        messagebox.showinfo("成功", "设置已保存")


# 启动测试
if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    window = NetworkSettingsWindow(root)
    window.window.mainloop()
