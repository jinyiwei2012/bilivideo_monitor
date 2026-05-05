"""
现代化系统设置界面
包含OneBot配置、监控设置、预测设置、AI配置、网络设置（代理/Cookie/扫码登录）
"""
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox

from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase
from core.bilibili_api import bilibili_api


class SettingsWindow:
    """统一设置窗口"""

    def __init__(self, parent=None):
        self.dlg = DialogBase(parent, "系统设置", "740x620", resizable=(True, True))
        self.window = self.dlg.window

        from config import load_config
        self._cfg = load_config()

        # 网络配置（代理/Cookie）
        self._net_cfg_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config', 'network_config.json')
        self._net_cfg = self._load_net_config()

        self.setup_ui()

    # ── 网络配置持久化 ──
    def _load_net_config(self) -> dict:
        if os.path.exists(self._net_cfg_file):
            try:
                with open(self._net_cfg_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'proxies': [], 'cookies': {}}

    def _save_net_config(self):
        os.makedirs(os.path.dirname(self._net_cfg_file), exist_ok=True)
        with open(self._net_cfg_file, 'w', encoding='utf-8') as f:
            json.dump(self._net_cfg, f, ensure_ascii=False, indent=2)

    # ── UI helpers ──
    @staticmethod
    def _field(parent, label, default, show=None):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        e = ttk.Entry(f, width=40, font=FONT, show=show or "")
        e.insert(0, default)
        e.pack(side=tk.LEFT, padx=(8, 0))
        return e

    @staticmethod
    def _spin_field(parent, label, default, fr, to):
        f = tk.Frame(parent, bg=C["bg_elevated"])
        f.pack(fill=tk.X, pady=4)
        tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
        sv = tk.StringVar(value=str(default))
        sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
        sp.pack(side=tk.LEFT, padx=(8, 0))
        return sv

    def _section(self, parent, title, padding=(16, 16, 8)):
        f = tk.Frame(parent, bg=C["bg_elevated"],
                      highlightthickness=1, highlightbackground=C["border_sub"])
        f.pack(fill=tk.X, padx=padding[0], pady=padding[1:], ipadx=12, ipady=14)
        if title:
            tk.Label(f, text=title, bg=C["bg_elevated"], fg=C["text_2"],
                     font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w")
        return f

    # ═══════════════ UI 构建 ═══════════════════════════

    def setup_ui(self):
        self.dlg.header("系统设置",
                        "配置通知、监控、AI、代理、Cookie 等全部参数")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(12, 0))

        self._build_onebot_tab(nb)
        self._build_monitor_tab(nb)
        self._build_predict_tab(nb)
        self._build_ai_tab(nb)
        self._build_proxy_tab(nb)
        self._build_cookie_tab(nb)
        self._build_retry_tab(nb)
        self._build_status_tab(nb)

        self.dlg.button_row([
            ("取消", self.window.destroy, ""),
            ("保存设置", self._save_settings, "primary"),
        ])

    # ──── OneBot ────
    def _build_onebot_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  OneBot通知  ")
        sec = self._section(page, "连接参数", (16, 16, 8))
        self.onebot_http = self._field(sec, "HTTP地址",
            self._cfg.get("onebot", {}).get("http_url", "http://127.0.0.1:5700"))
        self.onebot_ws = self._field(sec, "WebSocket地址",
            self._cfg.get("onebot", {}).get("ws_url", "ws://127.0.0.1:6700"))
        self.qq_private = self._field(sec, "私聊QQ号",
            self._cfg.get("onebot", {}).get("private_qq", ""))
        self.qq_group = self._field(sec, "群号",
            self._cfg.get("onebot", {}).get("group_qq", ""))
        ttk.Button(sec, text="测试连接",
                   command=self._test_connection).pack(anchor="w", padx=4, pady=(8, 0))

    # ──── 监控 ────
    def _build_monitor_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  监控参数  ")
        sec = self._section(page, "基础参数")
        self.check_interval = self._spin_field(sec, "检查间隔(秒)",
            self._cfg.get("monitor", {}).get("check_interval", 300), 60, 3600)
        self.max_monitors = self._spin_field(sec, "最大监控数",
            self._cfg.get("monitor", {}).get("max_monitor_count", 100), 10, 500)

    # ──── 预测 ────
    def _build_predict_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  预测参数  ")
        sec = self._section(page, "预测参数")
        self.predict_hours = self._spin_field(sec, "预测时长(小时)",
            self._cfg.get("prediction", {}).get("prediction_hours", 168), 24, 720)
        self.min_confidence = self._spin_field(sec, "最小置信度",
            self._cfg.get("prediction", {}).get("min_confidence", 0.5), 0.1, 1.0)

    # ──── AI配置 ────
    def _build_ai_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  AI配置  ")

        sec = self._section(page, "LLM 接口参数")
        ai_cfg = self._cfg.get("ai", {})
        self.ai_api_key = self._field(sec, "API密钥", ai_cfg.get("api_key", ""), show="*")
        self.ai_endpoint = self._field(sec, "接口地址",
            ai_cfg.get("endpoint", "") or "https://api.openai.com/v1/chat/completions")
        self.ai_model = self._field(sec, "模型名称", ai_cfg.get("model", "gpt-4o-mini"))

        tk.Label(sec, text="支持任何 OpenAI 兼容接口",
                 bg=C["bg_elevated"], fg=C["text_3"],
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=4, pady=(8, 0))

        preset_f = tk.Frame(page, bg=C["bg_base"])
        preset_f.pack(fill=tk.X, padx=16, pady=(4, 0))
        tk.Label(preset_f, text="快速填入:", bg=C["bg_base"], fg=C["text_2"],
                 font=FONT).pack(side=tk.LEFT)
        presets = {
            "DeepSeek": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
            "OpenAI":   ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
            "Claude":   ("https://api.anthropic.com/v1/messages", "claude-sonnet-4-6"),
        }
        for name, (ep, mdl) in presets.items():
            ttk.Button(preset_f, text=name, command=lambda ep=ep, mdl=mdl: (
                self._clear_entry(self.ai_endpoint, ep),
                self._clear_entry(self.ai_model, mdl),
            )).pack(side=tk.LEFT, padx=2)

    # ──── 代理 ────
    def _build_proxy_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  代理设置  ")

        sec = tk.Frame(page, bg=C["bg_elevated"],
                       highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)
        tk.Label(sec, text="HTTP代理列表（每行一个）",
                 bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(anchor="w", pady=(0, 4))
        tk.Label(sec, text="格式: http://host:port 或 http://user:pass@host:port",
                 bg=C["bg_elevated"], fg=C["text_3"], font=FONT_SM).pack(anchor="w")

        self.proxy_text = tk.Text(sec, height=8,
            bg=C["bg_base"], fg=C["text_1"], insertbackground=C["text_1"],
            font=("Consolas", 10), relief="flat",
            highlightthickness=1, highlightbackground=C["border"])
        self.proxy_text.pack(fill=tk.BOTH, expand=True, pady=6)
        if self._net_cfg.get('proxies'):
            self.proxy_text.insert('1.0', '\n'.join(self._net_cfg['proxies']))

        btn_row = tk.Frame(sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="应用代理",
                   command=self._apply_proxies).pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(sec, text="使用代理可有效绕过IP级别的频率限制",
                 bg=C["bg_elevated"], fg=C["warning"],
                 font=FONT_SM, anchor="w").pack(fill=tk.X, pady=(6, 0))

    # ──── Cookie ────
    def _build_cookie_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  Cookie设置  ")

        sec = tk.Frame(page, bg=C["bg_elevated"],
                       highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 6), ipadx=10, ipady=6)

        import_row = tk.Frame(sec, bg=C["bg_elevated"])
        import_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(import_row, text="导入方式:", bg=C["bg_elevated"],
                 fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        ttk.Button(import_row, text="📋 Cookie-Editor JSON",
                   command=self._import_cookie_editor).pack(side=tk.LEFT, padx=4)
        ttk.Button(import_row, text="📱 扫码登录",
                   command=self._qrcode_login).pack(side=tk.LEFT, padx=4)

        self.cookie_text = tk.Text(sec, height=5,
            bg=C["bg_base"], fg=C["text_1"], insertbackground=C["text_1"],
            font=("Consolas", 10), relief="flat",
            highlightthickness=1, highlightbackground=C["border"])
        self.cookie_text.pack(fill=tk.BOTH, expand=True, pady=4)
        self._refresh_cookie_display()

        btn_row = tk.Frame(sec, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="应用Cookie",
                   command=self._apply_cookies).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="清空Cookie",
                   command=self._clear_cookies).pack(side=tk.LEFT)

        tk.Label(sec, text="Cookie-Editor JSON: 从浏览器扩展导出后粘贴即可。扫码登录无需手动填写。",
                 bg=C["bg_elevated"], fg=C["warning"],
                 font=FONT_SM, anchor="w").pack(fill=tk.X, pady=(4, 0))

    # ──── 重试参数 ────
    def _build_retry_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  重试参数  ")

        sec = tk.Frame(page, bg=C["bg_elevated"],
                       highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=10)

        def _spin_r(parent, label, default, fr, to):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT, width=20, anchor="w").pack(side=tk.LEFT)
            sv = tk.DoubleVar(value=default)
            sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
            sp.pack(side=tk.LEFT, padx=(6, 0))
            return sv

        self.retry_count_var = _spin_r(sec, "最大重试次数",
                                       bilibili_api.max_retries, 1, 10)
        self.base_delay_var = _spin_r(sec, "基础重试延迟(秒)",
                                      bilibili_api.base_retry_delay, 1, 30)
        self.min_interval_var = _spin_r(sec, "最小请求间隔(秒)",
                                        bilibili_api._min_request_interval, 0.1, 10)

        ttk.Button(sec, text="应用重试设置",
                   command=self._apply_retry_settings).pack(anchor="w", pady=(8, 0))

    # ──── 运行状态 ────
    def _build_status_tab(self, nb):
        page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(page, text="  运行状态  ")

        sec = tk.Frame(page, bg=C["bg_elevated"],
                       highlightthickness=1, highlightbackground=C["border_sub"])
        sec.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=8)

        self.status_labels = {}
        fields = [
            ('is_login',              '登录状态'),
            ('login_name',            '登录账号'),
            ('has_cookies',           'Cookie已配置'),
            ('consecutive_412_errors', '连续412错误'),
            ('min_request_interval',  '请求间隔(秒)'),
            ('proxy_count',           '代理数量'),
        ]
        for key, label in fields:
            f = tk.Frame(sec, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"],
                     font=FONT, width=16, anchor="w").pack(side=tk.LEFT)
            vl = tk.Label(f, text="-", bg=C["bg_elevated"],
                          fg=C["success"], font=FONT)
            vl.pack(side=tk.LEFT)
            self.status_labels[key] = vl

        btn_s = tk.Frame(sec, bg=C["bg_elevated"])
        btn_s.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_s, text="刷新状态",
                   command=self._refresh_status).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_s, text="重置状态",
                   command=self._reset_status).pack(side=tk.LEFT, padx=4)

        self._refresh_status()

    # ═══════════════════════════════════════════════════

    @staticmethod
    def _clear_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _test_connection(self):
        messagebox.showinfo("测试", "连接测试功能", parent=self.window)

    # ──── 代理操作 ────
    def _apply_proxies(self):
        text = self.proxy_text.get('1.0', 'end').strip()
        proxy_list = [line.strip() for line in text.split('\n') if line.strip()]
        bilibili_api.clear_proxies()
        for ps in proxy_list:
            bilibili_api.add_proxy({'http': ps, 'https': ps})
        messagebox.showinfo("成功", f"已应用 {len(proxy_list)} 个代理", parent=self.window)

    # ──── Cookie: 刷新显示 ────
    def _refresh_cookie_display(self):
        self.cookie_text.delete('1.0', tk.END)
        cookies = {}
        for cookie in bilibili_api.session.cookies:
            if 'bilibili.com' in (cookie.domain or ''):
                cookies[cookie.name] = cookie.value
        if cookies:
            self.cookie_text.insert('1.0',
                '; '.join(f'{k}={v}' for k, v in cookies.items()))
        elif self._net_cfg.get('cookies'):
            self.cookie_text.insert('1.0',
                '; '.join(f'{k}={v}' for k, v in self._net_cfg['cookies'].items()))

    # ──── Cookie: 手动应用 ────
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
        self._net_cfg['cookies'] = cookies
        self._save_net_config()
        self._refresh_status()
        messagebox.showinfo("成功", f"已应用Cookie: {list(cookies.keys())}", parent=self.window)

    # ──── Cookie: 清空 ────
    def _clear_cookies(self):
        if messagebox.askyesno("确认", "确定要清空所有Cookie吗？", parent=self.window):
            for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd",
                         "sid", "buvid3", "buvid4", "buvid_fp"):
                bilibili_api.session.cookies.set(name, "", domain=".bilibili.com")
            bilibili_api._cookies = {}
            self._net_cfg['cookies'] = {}
            self._save_net_config()
            self._refresh_cookie_display()
            self._refresh_status()
            messagebox.showinfo("成功", "Cookie 已清空", parent=self.window)

    # ──── Cookie: Cookie-Editor 导入 ────
    def _import_cookie_editor(self):
        top = tk.Toplevel(self.window)
        top.title("导入 Cookie-Editor JSON")
        top.geometry("520x360")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()

        tk.Label(top, text="粘贴 Cookie-Editor 导出的 JSON 内容：",
                 bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(pady=(12, 4))
        tk.Label(top, text='格式: [{"domain": ".bilibili.com", "name": "SESSDATA", ...}]',
                 bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM).pack()

        text_w = tk.Text(top, height=10,
            bg=C["bg_base"], fg=C["text_1"], font=("Consolas", 10),
            relief="flat", highlightthickness=1, highlightbackground=C["border"],
            insertbackground=C["text_1"])
        text_w.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        def _do_import():
            raw = text_w.get('1.0', tk.END).strip()
            if not raw:
                messagebox.showwarning("提示", "请粘贴 JSON 内容", parent=top)
                return
            try:
                entries = json.loads(raw)
            except json.JSONDecodeError as e:
                messagebox.showerror("解析失败", f"JSON 格式错误:\n{e}", parent=top)
                return
            if not isinstance(entries, list):
                messagebox.showerror("格式错误", "JSON 应为数组格式", parent=top)
                return
            cookies = {}
            for entry in entries:
                name = entry.get("name", "")
                value = entry.get("value", "")
                domain = entry.get("domain", "")
                if name and value and ("bilibili.com" in domain or not domain):
                    cookies[name] = value
            if not cookies:
                messagebox.showwarning("未找到", "JSON 中未找到 B站 相关 Cookie", parent=top)
                return
            bilibili_api.set_cookies(cookies)
            self._net_cfg['cookies'] = cookies
            self._save_net_config()
            self._refresh_cookie_display()
            self._refresh_status()
            top.destroy()
            messagebox.showinfo("成功",
                f"已导入 {len(cookies)} 个 Cookie:\n{', '.join(cookies.keys())}",
                parent=self.window)

        btn_f = tk.Frame(top, bg=C["bg_surface"])
        btn_f.pack(pady=(0, 12))
        ttk.Button(btn_f, text="导入并应用", command=_do_import,
                   style="Primary.TButton").pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="取消", command=top.destroy).pack(side=tk.LEFT, padx=4)

    # ──── Cookie: 扫码登录 ────
    def _qrcode_login(self):
        qr_data = bilibili_api.get_qrcode_login_url()
        if not qr_data:
            messagebox.showerror("错误", "获取二维码失败", parent=self.window)
            return
        qrcode_key = qr_data.get("qrcode_key", "")
        qr_url = qr_data.get("url", "")

        # 生成二维码图片
        self._qr_img = None
        try:
            import qrcode
            from PIL import Image, ImageTk
            img = qrcode.make(qr_url).resize((200, 200))
            self._qr_img = ImageTk.PhotoImage(img)
        except ImportError:
            pass

        qr_top = tk.Toplevel(self.window)
        qr_top.title("扫码登录 B站")
        qr_top.geometry("320x380")
        qr_top.configure(bg=C["bg_surface"])
        qr_top.transient(self.window)
        qr_top.grab_set()
        qr_top.resizable(False, False)

        tk.Label(qr_top, text="请使用 B站 手机客户端扫码",
                 bg=C["bg_surface"], fg=C["text_1"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(14, 6))

        if self._qr_img:
            tk.Label(qr_top, image=self._qr_img, bg=C["bg_surface"]).pack(pady=6)
        else:
            tk.Label(qr_top, text=f"扫码链接:\n{qr_url}", bg=C["bg_surface"],
                     fg=C["text_1"], font=("Consolas", 9), wraplength=280,
                     justify="left").pack(pady=6, padx=10)

        status_var = tk.StringVar(value="等待扫码...")
        status_lbl = tk.Label(qr_top, textvariable=status_var,
                              bg=C["bg_surface"], fg=C["text_2"], font=FONT)
        status_lbl.pack(pady=(6, 4))

        def _poll():
            if not qr_top.winfo_exists():
                return
            result = bilibili_api.poll_qrcode_login(qrcode_key)
            status_var.set(result.get("message", ""))
            if result.get("status") == 2:
                cookies = result.get("cookies", {})
                if cookies:
                    self._net_cfg['cookies'] = cookies
                    self._save_net_config()
                    self._refresh_cookie_display()
                    self._refresh_status()
                    status_lbl.config(fg=C["success"])
                    qr_top.after(800, qr_top.destroy)
                    messagebox.showinfo("登录成功",
                        f"已获取 Cookie: {', '.join(cookies.keys())}",
                        parent=self.window)
                else:
                    self._refresh_status()
                    status_lbl.config(fg=C["success"])
                    qr_top.after(800, qr_top.destroy)
                    messagebox.showinfo("登录成功",
                        "扫码成功！Cookie 已通过浏览器同步。", parent=self.window)
                return
            elif result.get("status") == -1:
                status_lbl.config(fg=C["danger"])
                ttk.Button(qr_top, text="重新生成二维码",
                           command=lambda: [qr_top.destroy(), self._qrcode_login()]
                           ).pack(pady=4)
                return
            qr_top.after(1500, _poll)

        qr_top.after(500, _poll)

    # ──── 重试设置 ────
    def _apply_retry_settings(self):
        bilibili_api.max_retries = int(self.retry_count_var.get())
        bilibili_api.base_retry_delay = self.base_delay_var.get()
        bilibili_api._min_request_interval = self.min_interval_var.get()
        messagebox.showinfo("成功", "重试设置已更新", parent=self.window)

    # ──── 状态 ────
    def _refresh_status(self):
        status = bilibili_api.get_status()
        for key, label in self.status_labels.items():
            value = status.get(key, 'N/A')
            if key == 'is_login':
                v = '✅ 已登录' if value else '❌ 未登录'
                label.config(fg=C["success"] if value else C["danger"])
            elif key == 'login_name':
                v = str(value) if value else '—'
                label.config(fg=C["text_1"] if value else C["text_3"])
            elif key == 'has_cookies':
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

    # ──── 保存系统设置 ────
    def _save_settings(self):
        try:
            interval = int(self.check_interval.get())
            if not (60 <= interval <= 3600):
                messagebox.showerror("验证失败", "检查间隔必须在 60 ~ 3600 秒之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "检查间隔必须为整数", parent=self.window)
            return
        try:
            max_m = int(self.max_monitors.get())
            if not (10 <= max_m <= 500):
                messagebox.showerror("验证失败", "最大监控数必须在 10 ~ 500 之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "最大监控数必须为整数", parent=self.window)
            return
        try:
            pred_hours = int(self.predict_hours.get())
            if not (24 <= pred_hours <= 720):
                messagebox.showerror("验证失败", "预测时长必须在 24 ~ 720 小时之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "预测时长必须为整数", parent=self.window)
            return
        try:
            confidence = float(self.min_confidence.get())
            if not (0.1 <= confidence <= 1.0):
                messagebox.showerror("验证失败", "最小置信度必须在 0.1 ~ 1.0 之间", parent=self.window)
                return
        except ValueError:
            messagebox.showerror("验证失败", "最小置信度必须为数字", parent=self.window)
            return

        from config import save_config
        self._cfg["onebot"] = {
            "enabled": bool(self.onebot_http.get().strip()),
            "http_url": self.onebot_http.get().strip(),
            "ws_url": self.onebot_ws.get().strip(),
            "private_qq": self.qq_private.get().strip(),
            "group_qq": self.qq_group.get().strip(),
        }
        self._cfg["monitor"]["check_interval"] = interval
        self._cfg["monitor"]["max_monitor_count"] = max_m
        self._cfg["prediction"]["prediction_hours"] = pred_hours
        self._cfg["prediction"]["min_confidence"] = confidence
        self._cfg["ai"] = {
            "enabled": bool(self.ai_api_key.get().strip()),
            "api_key": self.ai_api_key.get().strip(),
            "endpoint": self.ai_endpoint.get().strip(),
            "model": self.ai_model.get().strip(),
        }
        save_config(self._cfg)
        self._save_net_config()

        messagebox.showinfo("成功", "设置已保存", parent=self.window)
        self.window.destroy()
