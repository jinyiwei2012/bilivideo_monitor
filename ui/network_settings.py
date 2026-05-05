"""
现代化网络设置窗口 - 配置代理、Cookie等网络参数
用于绕过B站412频率限制
"""
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

from core.bilibili_api import bilibili_api
from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase


class NetworkSettingsWindow:
    """网络设置窗口（现代化风格）"""

    def __init__(self, parent):
        self.dlg = DialogBase(parent, "网络设置 - 412错误处理", "640x560",
                              resizable=(True, True))
        self.window = self.dlg.window

        self.config_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config', 'network_config.json')
        self.config = self._load_config()
        self._create_widgets()
        self._load_current_status()

    def _load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'proxies': [], 'cookies': {}}

    def _save_config(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _create_widgets(self):
        self.dlg.header("网络设置", "配置代理和Cookie以绕过B站412频率限制")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # ── 代理设置 ──
        proxy_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(proxy_page, text="  代理设置  ")

        sec_p = tk.Frame(proxy_page, bg=C["bg_elevated"],
                         highlightthickness=1, highlightbackground=C["border_sub"])
        sec_p.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)

        tk.Label(sec_p, text="HTTP代理列表（每行一个）",
                 bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT).pack(anchor="w", pady=(0, 4))
        tk.Label(sec_p, text="格式: http://host:port 或 http://user:pass@host:port",
                 bg=C["bg_elevated"], fg=C["text_3"],
                 font=FONT_SM).pack(anchor="w")

        self.proxy_text = tk.Text(sec_p, height=8,
                                  bg=C["bg_base"], fg=C["text_1"],
                                  insertbackground=C["text_1"],
                                  font=("Consolas", 10), relief="flat",
                                  highlightthickness=1,
                                  highlightbackground=C["border"])
        self.proxy_text.pack(fill=tk.BOTH, expand=True, pady=6)
        if self.config.get('proxies'):
            self.proxy_text.insert('1.0', '\n'.join(self.config.get('proxies', [])))

        btn_row = tk.Frame(sec_p, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="应用代理",
                   command=self._apply_proxies).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="清空代理",
                   command=self._clear_proxies).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="从配置文件加载",
                   command=self._load_proxies_from_config).pack(side=tk.LEFT, padx=4)

        tip_p = tk.Label(sec_p, text="使用代理可有效绕过IP级别的频率限制",
                         bg=C["bg_elevated"], fg=C["warning"],
                         font=FONT_SM, anchor="w")
        tip_p.pack(fill=tk.X, pady=(6, 0))

        # ── Cookie设置 ──
        cookie_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(cookie_page, text="  Cookie设置  ")

        sec_c = tk.Frame(cookie_page, bg=C["bg_elevated"],
                         highlightthickness=1, highlightbackground=C["border_sub"])
        sec_c.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)

        tk.Label(sec_c, text="B站Cookie（SESSDATA等）",
                 bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT).pack(anchor="w")
        tk.Label(sec_c, text="格式: name=value; name=value; …",
                 bg=C["bg_elevated"], fg=C["text_3"],
                 font=FONT_SM).pack(anchor="w")

        self.cookie_text = tk.Text(sec_c, height=6,
                                   bg=C["bg_base"], fg=C["text_1"],
                                   insertbackground=C["text_1"],
                                   font=("Consolas", 10), relief="flat",
                                   highlightthickness=1,
                                   highlightbackground=C["border"])
        self.cookie_text.pack(fill=tk.BOTH, expand=True, pady=6)
        if self.config.get('cookies'):
            cookie_str = '; '.join(f'{k}={v}' for k, v in self.config.get('cookies', {}).items())
            self.cookie_text.insert('1.0', cookie_str)

        ttk.Button(sec_c, text="应用Cookie",
                   command=self._apply_cookies).pack(anchor="w")

        tip_c = tk.Label(sec_c, text="设置有效的Cookie可提高请求成功率",
                         bg=C["bg_elevated"], fg=C["warning"],
                         font=FONT_SM, anchor="w")
        tip_c.pack(fill=tk.X, pady=(6, 0))

        # ── 重试参数 ──
        retry_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(retry_page, text="  重试参数  ")

        sec_r = tk.Frame(retry_page, bg=C["bg_elevated"],
                         highlightthickness=1, highlightbackground=C["border_sub"])
        sec_r.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=10)

        def _spin_r(parent, label, default, fr, to):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT, width=20, anchor="w").pack(side=tk.LEFT)
            sv = tk.DoubleVar(value=default)
            sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
            sp.pack(side=tk.LEFT, padx=(6, 0))
            return sv

        self.retry_count_var = _spin_r(sec_r, "最大重试次数",
                                       bilibili_api.max_retries, 1, 10)
        self.base_delay_var = _spin_r(sec_r, "基础重试延迟(秒)",
                                       bilibili_api.base_retry_delay, 1, 30)
        self.min_interval_var = _spin_r(sec_r, "最小请求间隔(秒)",
                                         bilibili_api._min_request_interval, 0.1, 10)

        ttk.Button(sec_r, text="应用重试设置",
                   command=self._apply_retry_settings).pack(anchor="w", pady=(8, 0))

        # ── 状态 ──
        status_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(status_page, text="  运行状态  ")

        sec_s = tk.Frame(status_page, bg=C["bg_elevated"],
                         highlightthickness=1, highlightbackground=C["border_sub"])
        sec_s.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=8)

        self.status_labels = {}
        for key in ['consecutive_412_errors', 'min_request_interval',
                    'proxy_count', 'has_cookies']:
            f = tk.Frame(sec_s, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=key, bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT, width=28, anchor="w").pack(side=tk.LEFT)
            vl = tk.Label(f, text="-", bg=C["bg_elevated"],
                          fg=C["success"], font=FONT)
            vl.pack(side=tk.LEFT)
            self.status_labels[key] = vl

        btn_s = tk.Frame(sec_s, bg=C["bg_elevated"])
        btn_s.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_s, text="刷新状态",
                   command=self._refresh_status).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_s, text="重置状态",
                   command=self._reset_status).pack(side=tk.LEFT, padx=4)

        # ── 底部按钮 ──
        self.dlg.button_row([
            ("关闭", self.window.destroy, ""),
            ("保存所有设置", self._save_all, "primary"),
        ])

    def _apply_proxies(self):
        text = self.proxy_text.get('1.0', 'end').strip()
        proxy_list = [line.strip() for line in text.split('\n') if line.strip()]
        bilibili_api.clear_proxies()
        for proxy_str in proxy_list:
            bilibili_api.add_proxy({'http': proxy_str, 'https': proxy_str})
        messagebox.showinfo("成功", f"已应用 {len(proxy_list)} 个代理", parent=self.window)

    def _clear_proxies(self):
        self.proxy_text.delete('1.0', 'end')
        bilibili_api.clear_proxies()

    def _load_proxies_from_config(self):
        self.proxy_text.delete('1.0', 'end')
        if self.config.get('proxies'):
            self.proxy_text.insert('1.0', '\n'.join(self.config.get('proxies', [])))

    def _apply_cookies(self):
        text = self.cookie_text.get('1.0', 'end').strip()
        if not text:
            messagebox.showwarning("警告", "Cookie不能为空", parent=self.window)
            return
        cookies = {}
        for item in text.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                cookies[key.strip()] = value.strip()
        bilibili_api.set_cookies(cookies)
        self.config['cookies'] = cookies
        messagebox.showinfo("成功", f"已应用Cookie: {list(cookies.keys())}", parent=self.window)

    def _refresh_status(self):
        status = bilibili_api.get_status()
        for key, label in self.status_labels.items():
            value = status.get(key, 'N/A')
            if key == 'has_cookies':
                v = '是' if value else '否'
                label.config(fg=C["success"] if value else C["danger"])
            elif key == 'consecutive_412_errors':
                v = str(value)
                label.config(fg=C["danger"] if value > 0 else C["success"])
            else:
                v = str(value)
                label.config(fg=C["success"])
            label.config(text=v)

    def _reset_status(self):
        if messagebox.askyesno("确认", "确定要重置所有状态吗？", parent=self.window):
            bilibili_api.reset_status()
            self._refresh_status()

    def _apply_retry_settings(self):
        bilibili_api.max_retries = int(self.retry_count_var.get())
        bilibili_api.base_retry_delay = self.base_delay_var.get()
        bilibili_api._min_request_interval = self.min_interval_var.get()
        messagebox.showinfo("成功", "重试设置已更新", parent=self.window)

    def _load_current_status(self):
        self._refresh_status()

    def _save_all(self):
        text = self.proxy_text.get('1.0', 'end').strip()
        self.config['proxies'] = [line.strip() for line in text.split('\n') if line.strip()]
        self._save_config()
        messagebox.showinfo("成功", "设置已保存", parent=self.window)


if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    window = NetworkSettingsWindow(root)
    window.window.mainloop()
