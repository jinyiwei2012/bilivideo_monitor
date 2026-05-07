"""
现代化网络设置窗口 - 配置代理、Cookie等网络参数
用于绕过B站412频率限制
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import logging

from core.bilibili_api import bilibili_api
from ui.theme import C
from ui.helpers import FONT, FONT_SM
from ui.dialog_base import DialogBase

logger = logging.getLogger(__name__)


class NetworkSettingsWindow:
    """网络设置窗口（现代化风格）"""

    def __init__(self, parent):
        self.dlg = DialogBase(parent, "网络设置 - 412错误处理", "760x600", resizable=(True, True), modal=False)
        self.window = self.dlg.window

        self.config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "network_config.json")
        self.config = self._load_config()
        self._create_widgets()
        self._load_current_status()

    def _load_config(self) -> dict:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug("加载网络配置失败: %s", e)
        return {"proxies": [], "cookies": {}}

    def _save_config(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _create_widgets(self):
        self.dlg.header("网络设置", "配置代理和Cookie以绕过B站412频率限制")

        nb = ttk.Notebook(self.dlg.container)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # ── 代理设置 ──
        proxy_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(proxy_page, text="  代理设置  ")

        sec_p = tk.Frame(proxy_page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec_p.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)

        tk.Label(sec_p, text="HTTP代理列表（每行一个）", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
            anchor="w", pady=(0, 4)
        )
        tk.Label(
            sec_p,
            text="格式: http://host:port 或 http://user:pass@host:port",
            bg=C["bg_elevated"],
            fg=C["text_3"],
            font=FONT_SM,
        ).pack(anchor="w")

        self.proxy_text = tk.Text(
            sec_p,
            height=8,
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self.proxy_text.pack(fill=tk.BOTH, expand=True, pady=6)
        if self.config.get("proxies"):
            self.proxy_text.insert("1.0", "\n".join(self.config.get("proxies", [])))

        btn_row = tk.Frame(sec_p, bg=C["bg_elevated"])
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="应用代理", command=self._apply_proxies).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="清空代理", command=self._clear_proxies).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="从配置文件加载", command=self._load_proxies_from_config).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="检查可用性", command=self._check_proxies).pack(side=tk.LEFT, padx=4)

        url_row = tk.Frame(sec_p, bg=C["bg_elevated"])
        url_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(url_row, text="测试地址:", bg=C["bg_elevated"], fg=C["text_2"],
                 font=FONT_SM, width=8, anchor="w").pack(side=tk.LEFT)
        self._test_url_var = tk.StringVar(
            value="https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7hQ"
        )
        url_entry = ttk.Entry(url_row, textvariable=self._test_url_var, font=FONT_SM)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        tip_p = tk.Label(
            sec_p,
            text="使用代理可有效绕过IP级别的频率限制",
            bg=C["bg_elevated"],
            fg=C["warning"],
            font=FONT_SM,
            anchor="w",
        )
        tip_p.pack(fill=tk.X, pady=(6, 0))

        # ── Cookie设置 ──
        cookie_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(cookie_page, text="  Cookie设置  ")

        sec_c = tk.Frame(cookie_page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec_c.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 6), ipadx=10, ipady=6)

        # 导入方式选择
        import_row = tk.Frame(sec_c, bg=C["bg_elevated"])
        import_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(import_row, text="导入方式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
        ttk.Button(import_row, text="📋 Cookie-Editor JSON", command=self._import_cookie_editor).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(import_row, text="📱 扫码登录", command=self._qrcode_login).pack(side=tk.LEFT, padx=4)

        # Cookie 文本区（显示/编辑当前Cookie，key=value 格式）
        self.cookie_text = tk.Text(
            sec_c,
            height=5,
            bg=C["bg_base"],
            fg=C["text_1"],
            insertbackground=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
        )
        self.cookie_text.pack(fill=tk.BOTH, expand=True, pady=4)
        self._refresh_cookie_display()

        btn_row_c = tk.Frame(sec_c, bg=C["bg_elevated"])
        btn_row_c.pack(fill=tk.X)
        ttk.Button(btn_row_c, text="应用Cookie", command=self._apply_cookies).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row_c, text="清空Cookie", command=self._clear_cookies).pack(side=tk.LEFT)

        tip_c = tk.Label(
            sec_c,
            text="Cookie-Editor JSON: 从浏览器扩展导出后粘贴即可。扫码登录无需手动填写。",
            bg=C["bg_elevated"],
            fg=C["warning"],
            font=FONT_SM,
            anchor="w",
        )
        tip_c.pack(fill=tk.X, pady=(4, 0))

        # ── 重试参数 ──
        retry_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(retry_page, text="  重试参数  ")

        sec_r = tk.Frame(retry_page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec_r.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=10)

        def _spin_r(parent, label, default, fr, to):
            f = tk.Frame(parent, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=4)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=20, anchor="w").pack(
                side=tk.LEFT
            )
            sv = tk.DoubleVar(value=default)
            sp = ttk.Spinbox(f, from_=fr, to=to, textvariable=sv, width=10)
            sp.pack(side=tk.LEFT, padx=(6, 0))
            return sv

        self.retry_count_var = _spin_r(sec_r, "最大重试次数", bilibili_api.max_retries, 1, 10)
        self.base_delay_var = _spin_r(sec_r, "基础重试延迟(秒)", bilibili_api.base_retry_delay, 1, 30)
        self.min_interval_var = _spin_r(sec_r, "最小请求间隔(秒)", bilibili_api._min_request_interval, 0.1, 10)

        ttk.Button(sec_r, text="应用重试设置", command=self._apply_retry_settings).pack(anchor="w", pady=(8, 0))

        # ── 状态 ──
        status_page = tk.Frame(nb, bg=C["bg_base"])
        nb.add(status_page, text="  运行状态  ")

        sec_s = tk.Frame(status_page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        sec_s.pack(fill=tk.X, padx=16, pady=12, ipadx=10, ipady=8)

        self.status_labels = {}
        status_fields = [
            ("is_login", "登录状态"),
            ("login_name", "登录账号"),
            ("has_cookies", "Cookie已配置"),
            ("consecutive_412_errors", "连续412错误"),
            ("min_request_interval", "请求间隔(秒)"),
            ("proxy_count", "代理数量"),
        ]
        for key, label in status_fields:
            f = tk.Frame(sec_s, bg=C["bg_elevated"])
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=label, bg=C["bg_elevated"], fg=C["text_2"], font=FONT, width=16, anchor="w").pack(
                side=tk.LEFT
            )
            vl = tk.Label(f, text="-", bg=C["bg_elevated"], fg=C["success"], font=FONT)
            vl.pack(side=tk.LEFT)
            self.status_labels[key] = vl

        btn_s = tk.Frame(sec_s, bg=C["bg_elevated"])
        btn_s.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_s, text="刷新状态", command=self._refresh_status).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_s, text="重置状态", command=self._reset_status).pack(side=tk.LEFT, padx=4)

        # ── 底部按钮 ──
        self.dlg.button_row(
            [
                ("关闭", self.window.destroy, ""),
                ("保存所有设置", self._save_all, "primary"),
            ]
        )

    def _apply_proxies(self):
        text = self.proxy_text.get("1.0", "end").strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        bilibili_api.clear_proxies()
        for proxy_str in proxy_list:
            bilibili_api.add_proxy({"http": proxy_str, "https": proxy_str})
        # 同步保存到配置文件
        self.config["proxies"] = proxy_list
        self._save_config()
        # 应用后自动检查可用性
        self._check_proxies()

    def _clear_proxies(self):
        self.proxy_text.delete("1.0", "end")
        bilibili_api.clear_proxies()

    def _load_proxies_from_config(self):
        self.proxy_text.delete("1.0", "end")
        if self.config.get("proxies"):
            self.proxy_text.insert("1.0", "\n".join(self.config.get("proxies", [])))

    def _check_proxies(self):
        """测试每个代理的可用性、延迟、地区、ASN、ISP、响应数据"""
        text = self.proxy_text.get("1.0", "end").strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        if not proxy_list:
            messagebox.showwarning("提示", "请先输入要测试的代理", parent=self.window)
            return

        test_url = self._test_url_var.get().strip()

        top = tk.Toplevel(self.window)
        top.title("代理可用性检测")
        top.geometry("860x450")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()

        tk.Label(
            top, text="正在测试代理可用性…", bg=C["bg_surface"], fg=C["text_1"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(12, 4))

        result_frame = tk.Frame(top, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
        result_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        # 表头
        hdr = tk.Frame(result_frame, bg=C["bg_elevated"])
        hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        cols = [
            ("status", 36, "状态"), ("latency", 60, "延迟"), ("country", 70, "地区"),
            ("asn", 130, "ASN"), ("isp", 130, "ISP"), ("data", 200, "响应数据"), ("addr", 0, "代理地址"),
        ]
        for col_key, w, txt in cols:
            anchor = "e" if col_key == "latency" else "w"
            col_idx = [c[0] for c in cols].index(col_key)
            lbl = tk.Label(hdr, text=txt, bg=C["bg_elevated"], fg=C["text_3"],
                           font=("Microsoft YaHei UI", 8, "bold"), width=w if w else None, anchor=anchor)
            lbl.grid(row=0, column=col_idx, sticky="w" if anchor == "w" else "e", padx=(0, 4))
        hdr.grid_columnconfigure(len(cols) - 1, weight=1)

        # 滚动列表
        canvas = tk.Canvas(result_frame, bg=C["bg_base"], highlightthickness=0)
        sb = ttk.Scrollbar(result_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=C["bg_base"])
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        sb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)

        # 每个代理一行结果
        row_widgets = []
        for i, proxy in enumerate(proxy_list):
            row = tk.Frame(scroll_frame, bg=C["bg_base"])
            row.pack(fill=tk.X, padx=4, pady=1)
            status_lbl = tk.Label(row, text="⏳", bg=C["bg_base"], fg=C["text_2"], width=3)
            status_lbl.grid(row=0, column=0, padx=(0, 4))
            lat_lbl = tk.Label(row, text="—", bg=C["bg_base"], fg=C["text_2"],
                               font=("Consolas", 9), width=7, anchor="e")
            lat_lbl.grid(row=0, column=1, padx=(0, 4))
            country_lbl = tk.Label(row, text="", bg=C["bg_base"], fg=C["text_2"],
                                   font=("Consolas", 9), width=8, anchor="w")
            country_lbl.grid(row=0, column=2, padx=(0, 4))
            asn_lbl = tk.Label(row, text="", bg=C["bg_base"], fg=C["text_2"],
                               font=("Consolas", 9), width=18, anchor="w")
            asn_lbl.grid(row=0, column=3, padx=(0, 4))
            isp_lbl = tk.Label(row, text="", bg=C["bg_base"], fg=C["text_2"],
                               font=("Consolas", 9), width=20, anchor="w")
            isp_lbl.grid(row=0, column=4, padx=(0, 4))
            data_lbl = tk.Label(row, text="", bg=C["bg_base"], fg=C["text_2"],
                                font=("Consolas", 9), anchor="w")
            data_lbl.grid(row=0, column=5, sticky="w", padx=(0, 4))
            addr_lbl = tk.Label(row, text=proxy, bg=C["bg_base"], fg=C["text_1"],
                                font=("Consolas", 9), anchor="w")
            addr_lbl.grid(row=0, column=6, sticky="w")
            row.columnconfigure(5, weight=1)
            row_widgets.append((status_lbl, lat_lbl, country_lbl, asn_lbl, isp_lbl, data_lbl, addr_lbl))

        progress_var = tk.DoubleVar(value=0)
        progress_bar = ttk.Progressbar(top, variable=progress_var, maximum=len(proxy_list))
        progress_bar.pack(fill=tk.X, padx=16, pady=(4, 8))

        btn_f = tk.Frame(top, bg=C["bg_surface"])
        btn_f.pack(pady=(0, 12))
        ttk.Button(btn_f, text="关闭", command=top.destroy).pack(side=tk.LEFT, padx=4)

        import threading

        def _run_checks():
            for i, (proxy, widgets) in enumerate(zip(proxy_list, row_widgets)):
                result = bilibili_api.test_proxy(proxy, test_url=test_url)
                sl, ll, cl, al, il, dl, _ = widgets
                ok = result.get("ok", False)
                data = result.get("data") or {}
                data_text = ""
                if data.get("title"):
                    data_text = f"{data['title']} (播放: {data.get('view', 0)})"
                top.after(0, lambda r=result, ok=ok, sl=sl, ll=ll,
                          cl=cl, al=al, il=il, dl=dl,
                          dt=data_text, pv=progress_var, idx=i: (
                    sl.configure(text="✅" if ok else "❌",
                                 fg=C["success"] if ok else C["danger"]),
                    ll.configure(
                        text=f"{r.get('latency_ms', '—')}ms" if ok else r.get("error", "—")[:10],
                        fg=C["success"] if ok else C["danger"],
                    ),
                    cl.configure(text=r.get("country", "") or ""),
                    al.configure(text=r.get("asn", "") or ""),
                    il.configure(text=r.get("isp", "") or ""),
                    dl.configure(text=dt),
                    pv.set(idx + 1),
                ))
            top.after(0, lambda: (
                progress_bar.destroy(),
                tk.Label(top, text="检测完成", bg=C["bg_surface"], fg=C["success"],
                         font=("Microsoft YaHei UI", 9, "bold")).pack(),
            ))

        threading.Thread(target=_run_checks, daemon=True).start()

    def _get_bilibili_api(self):
        return bilibili_api

    # ── Cookie: 刷新显示 ──
    def _refresh_cookie_display(self):
        self.cookie_text.delete("1.0", tk.END)
        cfg = self._get_bilibili_api().get_status()
        if cfg.get("has_cookies"):
            # 从当前 session cookies 读取
            cookies = {}
            for cookie in self._get_bilibili_api().session.cookies:
                if "bilibili.com" in (cookie.domain or ""):
                    cookies[cookie.name] = cookie.value
            if cookies:
                self.cookie_text.insert("1.0", "; ".join(f"{k}={v}" for k, v in cookies.items()))
                return
        # fallback: 从配置文件读取
        if self.config.get("cookies"):
            self.cookie_text.insert("1.0", "; ".join(f"{k}={v}" for k, v in self.config["cookies"].items()))

    # ── Cookie: 从 Cookie-Editor JSON 导入 ──
    def _import_cookie_editor(self):
        """弹出窗口粘贴 Cookie-Editor 导出的 JSON"""
        top = tk.Toplevel(self.window)
        top.title("导入 Cookie-Editor JSON")
        top.geometry("520x360")
        top.configure(bg=C["bg_surface"])
        top.transient(self.window)
        top.grab_set()

        tk.Label(top, text="粘贴 Cookie-Editor 导出的 JSON 内容：", bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(
            pady=(12, 4)
        )
        tk.Label(
            top,
            text='格式: [{"domain": ".bilibili.com", "name": "SESSDATA", ...}]',
            bg=C["bg_surface"],
            fg=C["text_3"],
            font=FONT_SM,
        ).pack()

        text_w = tk.Text(
            top,
            height=10,
            bg=C["bg_base"],
            fg=C["text_1"],
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["border"],
            insertbackground=C["text_1"],
        )
        text_w.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        def _do_import():
            raw = text_w.get("1.0", tk.END).strip()
            if not raw:
                messagebox.showwarning("提示", "请粘贴 JSON 内容", parent=top)
                return
            try:
                entries = json.loads(raw)
            except json.JSONDecodeError as e:
                messagebox.showerror("解析失败", f"JSON 格式错误:\n{e}", parent=top)
                return
            if not isinstance(entries, list):
                messagebox.showerror("格式错误", "JSON 应为数组格式 [{...}, ...]", parent=top)
                return

            cookies = {}
            for entry in entries:
                name = entry.get("name", "")
                value = entry.get("value", "")
                domain = entry.get("domain", "")
                # 只提取 bilibili.com 的 cookie
                if name and value and ("bilibili.com" in domain or not domain):
                    cookies[name] = value

            if not cookies:
                messagebox.showwarning("未找到", "JSON 中未找到 B站 相关 Cookie 条目", parent=top)
                return

            api = self._get_bilibili_api()
            api.set_cookies(cookies)
            self.config["cookies"] = cookies
            self._refresh_cookie_display()
            self._refresh_status()
            top.destroy()
            messagebox.showinfo(
                "成功", f"已导入 {len(cookies)} 个 Cookie:\n{', '.join(cookies.keys())}", parent=self.window
            )

        btn_f = tk.Frame(top, bg=C["bg_surface"])
        btn_f.pack(pady=(0, 12))
        ttk.Button(btn_f, text="导入并应用", command=_do_import, style="Primary.TButton").pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="取消", command=top.destroy).pack(side=tk.LEFT, padx=4)

    # ── Cookie: 扫码登录 ──
    def _qrcode_login(self):
        """扫码登录 B站 获取 Cookie"""
        api = self._get_bilibili_api()
        qr_data = api.get_qrcode_login_url()
        if not qr_data:
            messagebox.showerror("错误", "获取二维码失败", parent=self.window)
            return

        qrcode_key = qr_data.get("qrcode_key", "")
        qr_url = qr_data.get("url", "")

        # 生成二维码图片（用 qrcode 库或 API 二维码图片URL）
        try:
            import qrcode

            img = qrcode.make(qr_url)
            _img_tk = tk.PhotoImage(width=200, height=200)  # noqa: F841
            # 转换 PIL Image -> tk PhotoImage
            from PIL import ImageTk

            img = img.resize((200, 200))
            self._qr_img = ImageTk.PhotoImage(img)
        except ImportError:
            # 没有 PIL/qrcode 库，使用文本二维码或直接显示链接
            self._qr_img = None

        # 扫码窗口
        qr_top = tk.Toplevel(self.window)
        qr_top.title("扫码登录 B站")
        qr_top.geometry("320x380")
        qr_top.configure(bg=C["bg_surface"])
        qr_top.transient(self.window)
        qr_top.grab_set()
        qr_top.resizable(False, False)

        tk.Label(
            qr_top,
            text="请使用 B站 手机客户端扫码",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(pady=(14, 6))

        if self._qr_img:
            img_label = tk.Label(qr_top, image=self._qr_img, bg=C["bg_surface"])
            img_label.pack(pady=6)
        else:
            # 文本显示二维码链接
            tk.Label(
                qr_top,
                text=f"扫码链接:\n{qr_url}",
                bg=C["bg_surface"],
                fg=C["text_1"],
                font=("Consolas", 9),
                wraplength=280,
                justify="left",
            ).pack(pady=6, padx=10)
            tk.Label(
                qr_top, text="提示: 可用手机浏览器打开此链接再扫码", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM
            ).pack()

        status_var = tk.StringVar(value="等待扫码...")
        status_lbl = tk.Label(qr_top, textvariable=status_var, bg=C["bg_surface"], fg=C["text_2"], font=FONT)
        status_lbl.pack(pady=(6, 4))

        def _poll():
            if not qr_top.winfo_exists():
                return
            result = api.poll_qrcode_login(qrcode_key)
            status_var.set(result.get("message", ""))
            if result.get("status") == 2:
                # 登录成功
                cookies = result.get("cookies", {})
                if cookies:
                    self.config["cookies"] = cookies
                    self._refresh_cookie_display()
                    self._refresh_status()
                    status_lbl.config(fg=C["success"])
                    qr_top.after(800, qr_top.destroy)
                    messagebox.showinfo("登录成功", f"已获取 Cookie: {', '.join(cookies.keys())}", parent=self.window)
                else:
                    # 尝试刷新状态确认是否已设置
                    self._refresh_status()
                    status_lbl.config(fg=C["success"])
                    qr_top.after(800, qr_top.destroy)
                    messagebox.showinfo("登录成功", "扫码成功！Cookie 已通过浏览器同步。", parent=self.window)
                return
            elif result.get("status") == -1:
                status_lbl.config(fg=C["danger"])
                # 过期，提供重新生成按钮
                ttk.Button(
                    qr_top, text="重新生成二维码", command=lambda: [qr_top.destroy(), self._qrcode_login()]
                ).pack(pady=4)
                return
            qr_top.after(1500, _poll)

        qr_top.after(500, _poll)

    # ── Cookie: 清空 ──
    def _clear_cookies(self):
        if messagebox.askyesno("确认", "确定要清空所有 Cookie 吗？", parent=self.window):
            api = self._get_bilibili_api()
            # 清除 bilibili cookies
            expired = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd", "sid", "buvid3", "buvid4", "buvid_fp"]
            for name in expired:
                api.session.cookies.set(name, "", domain=".bilibili.com")
            api._cookies = {}
            self.config["cookies"] = {}
            self._refresh_cookie_display()
            self._refresh_status()
            messagebox.showinfo("成功", "Cookie 已清空", parent=self.window)

    def _apply_cookies(self):
        text = self.cookie_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("警告", "Cookie不能为空", parent=self.window)
            return
        cookies = {}
        for item in text.split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                cookies[key.strip()] = value.strip()
        api = self._get_bilibili_api()
        api.set_cookies(cookies)
        self.config["cookies"] = cookies
        self._refresh_status()
        messagebox.showinfo("成功", f"已应用Cookie: {list(cookies.keys())}", parent=self.window)

    def _refresh_status(self):
        api = self._get_bilibili_api()
        status = api.get_status()
        for key, label in self.status_labels.items():
            value = status.get(key, "N/A")
            if key == "is_login":
                v = "✅ 已登录" if value else "❌ 未登录"
                label.config(fg=C["success"] if value else C["danger"])
            elif key == "login_name":
                v = str(value) if value else "—"
                label.config(fg=C["text_1"] if value else C["text_3"])
            elif key == "has_cookies":
                v = "是" if value else "否"
                label.config(fg=C["success"] if value else C["danger"])
            elif key == "consecutive_412_errors":
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
        text = self.proxy_text.get("1.0", "end").strip()
        self.config["proxies"] = [line.strip() for line in text.split("\n") if line.strip()]
        self._save_config()
        messagebox.showinfo("成功", "设置已保存", parent=self.window)


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    window = NetworkSettingsWindow(root)
    window.window.mainloop()
