"""
账号 / Cookie 设置模块

Mixin 函数模块，为 SettingsWindow 提供账号相关功能:
  - Cookie 导入（Cookie-Editor JSON / 浏览器提取 / 扫码登录 / 密码登录）
  - 多账号管理（添加/切换/删除账号）
  - Cookie 显示与编辑（加锁/解锁查看）
  - 登录状态验证

所有函数以 self 为第一个参数（SettingsWindow 实例），通过 Mixin 方式挂载。
依赖 ui.theme.C 主题色配置和 core.bilibili_api 的 API 实例。
"""

import json
import tkinter as tk
import logging
from tkinter import ttk, messagebox
from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO
from core.bilibili_api import get_bilibili_api
from utils.update_checker import _s

logger = logging.getLogger(__name__)


def _build_account_tab(self, nb):
    """构建账号设置标签页

    包含:
      - 导入方式按钮（Cookie-Editor / 扫码 / 密码 / 浏览器提取）
      - 账号切换下拉框 + 添加/删除按钮
      - Cookie 文本框（支持加锁/解锁查看）
      - 应用/清空按钮

    Args:
        self: SettingsWindow 实例
        nb: ttk.Notebook 对象
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  账号设置  ")

    sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 6), ipadx=10, ipady=6)

    # ── 导入方式按钮行 ──
    import_row = tk.Frame(sec, bg=C["bg_elevated"])
    import_row.pack(fill=tk.X, pady=(0, 6))
    tk.Label(import_row, text="导入方式:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
    ttk.Button(import_row, text="📋 Cookie-Editor JSON", command=self._import_cookie_editor).pack(
        side=tk.LEFT, padx=4
    )
    ttk.Button(import_row, text="📱 扫码登录", command=self._qrcode_login).pack(side=tk.LEFT, padx=4)
    ttk.Button(import_row, text="🔑 密码登录", command=self._password_login, state=_s()).pack(side=tk.LEFT, padx=4)
    ttk.Button(import_row, text="🌐 从浏览器提取", command=self._import_from_browser).pack(side=tk.LEFT, padx=4)

    # ── 当前账号行 ──
    acct_row = tk.Frame(sec, bg=C["bg_elevated"])
    acct_row.pack(fill=tk.X, pady=(2, 4))
    tk.Label(acct_row, text="当前账号:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
    self._acct_combo = ttk.Combobox(acct_row, font=FONT, state="readonly", width=20)
    self._acct_combo.pack(side=tk.LEFT, padx=4)
    self._acct_combo.bind("<<ComboboxSelected>>", lambda e: self._switch_account())
    ttk.Button(acct_row, text="➕", width=3, command=self._add_account_dialog).pack(side=tk.LEFT, padx=1)
    ttk.Button(acct_row, text="✕", width=3, command=self._remove_account).pack(side=tk.LEFT, padx=1)

    # ── Cookie 文本框 ──
    self.cookie_text = tk.Text(
        sec,
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

    # ── 操作按钮行 ──
    btn_row = tk.Frame(sec, bg=C["bg_elevated"])
    btn_row.pack(fill=tk.X)
    ttk.Button(btn_row, text="应用Cookie", command=self._apply_cookies).pack(side=tk.LEFT, padx=(0, 4))
    self._cookie_unlock_btn = ttk.Button(
        btn_row, text="🔒 解锁查看", command=self._toggle_cookie_unlock, width=10,
    )
    self._cookie_unlock_btn.pack(side=tk.LEFT, padx=(4, 0))
    self._refresh_cookie_display()
    self._refresh_account_list()

    from utils.update_checker import _s
    ttk.Button(btn_row, text="清空Cookie", command=self._clear_cookies, state=_s()).pack(side=tk.LEFT)

    # 格式提示
    tk.Label(
        sec,
        text="支持直接粘贴 Cookie 字符串 (key=value; key2=value2) 或 Cookie-Editor JSON 格式，自动识别解析。",
        bg=C["bg_elevated"],
        fg=C["text_3"],
        font=FONT_SM,
        anchor="w",
    ).pack(fill=tk.X, pady=(4, 0))


def _refresh_cookie_display(self):
    """刷新 Cookie 文本框的显示内容

    根据当前锁定状态显示掩码或明文 Cookie。
    如果 Cookie unlocked 则显示完整值，否则显示掩码 "SESSDATA=abcd****wxyz"。
    """
    self.cookie_text.delete("1.0", tk.END)
    cookies = {}
    for cookie in get_bilibili_api().session.cookies:
        if "bilibili.com" in (cookie.domain or ""):
            cookies[cookie.name] = cookie.value
    if not cookies:
        # 回退到网络配置中的 Cookie
        cookies = self._net_cfg.get("cookies", {})
    if cookies:
        show_raw = getattr(self, "_cookie_unlocked", False)
        self._cookie_unlock_btn.config(text="🔓 已解锁" if show_raw else "🔒 解锁查看")
        parts = []
        for k, v in cookies.items():
            if show_raw:
                parts.append(f"{k}={v}")
            else:
                # 构造掩码：保留前4和后4字符，中间用 **** 替换
                masked = v[:4] + "****" + v[-4:] if len(v) > 8 else "********"
                parts.append(f"{k}={masked}")
        self.cookie_text.insert("1.0", "; ".join(parts))


def _toggle_cookie_unlock(self):
    """切换 Cookie 查看锁定状态（加锁 ⟷ 解锁）"""
    self._cookie_unlocked = not getattr(self, "_cookie_unlocked", False)
    self._refresh_cookie_display()


def _apply_cookies(self):
    """应用 Cookie 文本框中的内容到 API 会话

    解析文本框内容，设置 Cookie 到 API 实例，持久化到配置文件，
    更新账号列表，验证登录状态。
    """
    text = self.cookie_text.get("1.0", "end").strip()
    if not text:
        messagebox.showwarning("警告", "Cookie不能为空", parent=self.window)
        return
    cookies = self._parse_cookie_input(text)
    if not cookies:
        messagebox.showerror("错误", "无法解析输入内容，请检查格式", parent=self.window)
        return
    api = get_bilibili_api()
    api.set_cookies(cookies)
    api.add_account(api.get_active_account(), cookies, api.get_refresh_token())
    api._persist_cookies(cookies)
    self._net_cfg["cookies"] = cookies
    self._save_net_config()
    self._refresh_account_list()
    self._refresh_status()
    self.window.after(500, self._verify_login)
    messagebox.showinfo("成功", "已应用 Cookie，正在验证登录状态...", parent=self.window)


def _parse_cookie_input(self, text: str) -> dict:
    """解析 Cookie 输入文本为字典

    支持三种格式:
      1. Cookie-Editor JSON 数组: [{"name": "SESSDATA", "value": "..."}, ...]
      2. JSON 对象: {"SESSDATA": "...", "bili_jct": "..."}
      3. 分号分隔的键值对: "SESSDATA=xxx; bili_jct=yyy"

    Args:
        text: 用户输入的 Cookie 文本

    Returns:
        dict: Cookie 键值对字典，解析失败返回空字典
    """
    import json as _json

    stripped = text.strip()
    # 格式 1: Cookie-Editor JSON 数组
    if stripped.startswith("["):
        try:
            entries = _json.loads(stripped)
            if isinstance(entries, list) and entries:
                cookies = {}
                for entry in entries:
                    if isinstance(entry, dict):
                        name = entry.get("name", "")
                        value = entry.get("value", "")
                        if name and value:
                            cookies[name] = value
                if cookies:
                    return cookies
        except _json.JSONDecodeError:
            pass
    # 格式 2: JSON 对象
    elif stripped.startswith("{"):
        try:
            obj = _json.loads(stripped)
            if isinstance(obj, dict):
                valid_keys = {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid", "buvid3", "buvid4"}
                return {k: v for k, v in obj.items() if k in valid_keys or not k.startswith("_")}
        except _json.JSONDecodeError:
            pass
    # 格式 3: 分号分隔的键值对
    cookies = {}
    for item in stripped.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def _verify_login(self):
    """验证当前 Cookie 的登录状态（后台线程）

    调用 API get_status() 检查登录状态，在主线程回调中更新日志。
    """
    def _worker():
        try:
            status = get_bilibili_api().get_status()
            is_login = status.get("is_login", False)
            login_name = status.get("login_name", "")
            if is_login and hasattr(self, "gui") and self.gui:
                self.window.after(0, lambda: self.gui.log_panel.add_log("INFO", f"Cookie 登录验证成功: {login_name}"))
        except Exception as e:
            logger.debug("检查Cookie登录状态失败: %s", e)
        self.window.after(0, self._refresh_status)
    import threading
    threading.Thread(target=_worker, daemon=True).start()


def _clear_cookies(self):
    """清空所有 Cookie（带确认对话框）"""
    if messagebox.askyesno("确认", "确定要清空所有Cookie吗？", parent=self.window):
        for name in (
            "SESSDATA",
            "bili_jct",
            "DedeUserID",
            "DedeUserID__ckMd5",
            "sid",
            "buvid3",
            "buvid4",
            "buvid_fp",
        ):
            get_bilibili_api().session.cookies.set(name, "", domain=".bilibili.com")
        get_bilibili_api()._cookies = {}
        get_bilibili_api()._refresh_token = ""
        self._net_cfg["cookies"] = {}
        self._net_cfg["refresh_token"] = ""
        self._save_net_config()
        self._refresh_cookie_display()
        self._refresh_status()
        messagebox.showinfo("成功", "Cookie 已清空", parent=self.window)


def _import_from_browser(self):
    """从浏览器自动提取 B站 Cookie（后台线程）

    调用 browser_cookies.extract_from_all_browsers 搜索 Chrome/Edge/Firefox 等浏览器的 Cookie，
    完成后在主线程回调中更新 UI。
    """
    def _worker():
        try:
            from utils.browser_cookies import extract_from_all_browsers
            cookies = extract_from_all_browsers()
            if cookies:
                api = get_bilibili_api()
                api.set_cookies(cookies)
                api.add_account(api.get_active_account(), cookies, api.get_refresh_token())
                api._persist_cookies(cookies)
                self.window.after(0, lambda: self._on_browser_cookies(cookies))
            else:
                self.window.after(0, lambda: messagebox.showerror("失败",
                    "未从浏览器中找到 B 站 Cookie，请确认已登录 bilibili.com", parent=self.window))
        except Exception as e:
            self.window.after(0, lambda: messagebox.showerror("错误", f"提取失败: {e}", parent=self.window))
    import threading
    threading.Thread(target=_worker, daemon=True).start()


def _on_browser_cookies(self, cookies: dict):
    """浏览器 Cookie 提取成功的回调处理"""
    self._refresh_account_list()
    self._refresh_cookie_display()
    self._refresh_status()
    self.window.after(500, self._verify_login)
    messagebox.showinfo("成功", f"已从浏览器提取 Cookie:\n{', '.join(cookies.keys())}", parent=self.window)


def _import_cookie_editor(self):
    """打开 Cookie-Editor JSON 导入窗口

    提供一个大文本框让用户粘贴 Cookie-Editor 导出的 JSON 数组格式 Cookie，
    解析后应用到 API 会话中。
    """
    top = tk.Toplevel(self.window)
    top.title("导入 Cookie-Editor JSON")
    sw = self.window.winfo_screenwidth()
    sh = self.window.winfo_screenheight()
    top.geometry(f"{int(sw * 0.36)}x{int(sh * 0.42)}")
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
        """执行导入操作"""
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
        get_bilibili_api().set_cookies(cookies)
        self._net_cfg["cookies"] = cookies
        self._net_cfg["refresh_token"] = get_bilibili_api().get_refresh_token()
        self._save_net_config()
        self._refresh_cookie_display()
        self._refresh_status()
        top.destroy()
        self.window.after(500, self._verify_login)
        messagebox.showinfo("成功", f"已导入 {len(cookies)} 个 Cookie，正在验证登录状态...", parent=self.window)

    btn_f = tk.Frame(top, bg=C["bg_surface"])
    btn_f.pack(pady=(0, 12))
    ttk.Button(btn_f, text="导入并应用", command=_do_import, style="Primary.TButton").pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_f, text="取消", command=top.destroy).pack(side=tk.LEFT, padx=4)


def _qrcode_login(self):
    """扫码登录 B站

    获取登录二维码，显示在弹窗中，轮询 API 检查扫码状态。
    扫码成功后自动设置 Cookie 并更新 UI。
    """
    qr_data = get_bilibili_api().get_qrcode_login_url()
    if not qr_data:
        messagebox.showerror("错误", "获取二维码失败", parent=self.window)
        return
    qrcode_key = qr_data.get("qrcode_key", "")
    qr_url = qr_data.get("url", "")

    # 生成二维码图片
    self._qr_img = None
    try:
        import qrcode
        from PIL import ImageTk

        img = qrcode.make(qr_url).resize((200, 200))
        self._qr_img = ImageTk.PhotoImage(img)
    except ImportError:
        pass

    qr_top = tk.Toplevel(self.window)
    qr_top.title("扫码登录 B站")
    sw = self.window.winfo_screenwidth()
    sh = self.window.winfo_screenheight()
    qr_top.geometry(f"{int(sw * 0.28)}x{int(sh * 0.45)}")
    qr_top.configure(bg=C["bg_surface"])
    qr_top.transient(self.window)
    qr_top.grab_set()
    qr_top.resizable(True, True)

    tk.Label(
        qr_top,
        text="请使用 B站 手机客户端扫码",
        bg=C["bg_surface"],
        fg=C["text_1"],
        font=("Microsoft YaHei UI", 11, "bold"),
    ).pack(pady=(14, 6))

    if self._qr_img:
        tk.Label(qr_top, image=self._qr_img, bg=C["bg_surface"]).pack(pady=6)
    else:
        tk.Label(
            qr_top,
            text=f"扫码链接:\n{qr_url}",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Consolas", 9),
            wraplength=280,
            justify="left",
        ).pack(pady=6, padx=10)

    status_var = tk.StringVar(value="等待扫码...")
    status_lbl = tk.Label(qr_top, textvariable=status_var, bg=C["bg_surface"], fg=C["text_2"], font=FONT)
    status_lbl.pack(pady=(6, 4))

    def _poll():
        """轮询扫码状态"""
        if not qr_top.winfo_exists():
            return
        import threading

        def _worker():
            try:
                result = get_bilibili_api().poll_qrcode_login(qrcode_key)
            except Exception as e:
                result = {"status": 0, "message": f"轮询异常: {e}"}
            qr_top.after(0, lambda r=result: _handle_poll(r))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_poll(result):
        """处理轮询返回结果"""
        status_var.set(result.get("message", ""))
        if result.get("status") == 2:
            # 扫码成功
            cookies = result.get("cookies", {})
            if cookies:
                get_bilibili_api().set_cookies(cookies)
                get_bilibili_api().add_account(get_bilibili_api().get_active_account(), cookies, get_bilibili_api().get_refresh_token())
                self._refresh_account_list()
                self._refresh_cookie_display()
                self._refresh_status()
                status_lbl.config(fg=C["success"])
                qr_top.after(800, qr_top.destroy)
                self.window.after(1000, self._verify_login)
                messagebox.showinfo("登录成功", f"已获取 Cookie: {', '.join(cookies.keys())}", parent=self.window)
            else:
                self._refresh_status()
                status_lbl.config(fg=C["success"])
                qr_top.after(800, qr_top.destroy)
                self.window.after(1000, self._verify_login)
                messagebox.showinfo("登录成功", "扫码成功！Cookie 已通过浏览器同步。", parent=self.window)
            return
        elif result.get("status") == -1:
            # 二维码过期或失败
            status_lbl.config(fg=C["danger"])
            ttk.Button(
                qr_top, text="重新生成二维码", command=lambda: [qr_top.destroy(), self._qrcode_login()]
            ).pack(pady=4)
            return
        qr_top.after(1500, _poll)

    qr_top.after(500, _poll)


def _refresh_account_list(self):
    """刷新账号下拉列表

    从 API 实例获取所有已添加的账号名称列表，更新下拉框选项。
    """
    api = get_bilibili_api()
    names = api.get_account_names()
    self._acct_combo["values"] = names
    current = api.get_active_account()
    self._acct_combo.set(current if current in names else (names[0] if names else ""))


def _switch_account(self):
    """切换到下拉框选中的账号"""
    name = self._acct_combo.get()
    if name:
        get_bilibili_api().switch_account(name)
        self._refresh_cookie_display()
        self._refresh_status()


def _add_account_dialog(self):
    """添加新账号对话框

    输入账号名称和 Cookie 文本，解析后添加到 API 的多账号管理。
    """
    dlg = tk.Toplevel(self.window)
    dlg.title("添加账号")
    dlg.geometry("400x200")
    dlg.configure(bg=C["bg_surface"])
    dlg.transient(self.window)
    dlg.grab_set()
    tk.Label(dlg, text="账号名称:", bg=C["bg_surface"], fg=C["text_1"], font=FONT).pack(pady=(12, 4))
    name_entry = ttk.Entry(dlg, width=30, font=FONT)
    name_entry.pack()
    tk.Label(dlg, text="Cookie (SESSDATA=xxx; bili_jct=xxx):", bg=C["bg_surface"], fg=C["text_3"],
             font=FONT_SM).pack(pady=(8, 4))
    cookie_entry = tk.Text(dlg, height=3, font=("Consolas", 9), bg=C["bg_base"], fg=C["text_1"])
    cookie_entry.pack(padx=16, fill=tk.X)

    def _save():
        name = name_entry.get().strip()
        raw = cookie_entry.get("1.0", "end").strip()
        if not name or not raw:
            messagebox.showwarning("提示", "请填写账号名称和 Cookie", parent=dlg)
            return
        cookies = self._parse_cookie_input(raw)
        if not cookies:
            messagebox.showerror("错误", "无法解析 Cookie，请检查格式", parent=dlg)
            return
        get_bilibili_api().add_account(name, cookies)
        get_bilibili_api().switch_account(name)
        get_bilibili_api()._persist_cookies(cookies)
        self._refresh_account_list()
        self._refresh_cookie_display()
        self._refresh_status()
        dlg.destroy()

    ttk.Button(dlg, text="保存", command=_save).pack(pady=10)


def _remove_account(self):
    """删除当前选中的账号（带确认对话框）"""
    name = self._acct_combo.get()
    if not name:
        return
    if not messagebox.askyesno("确认", f"确定要删除账号「{name}」吗？", parent=self.window):
        return
    get_bilibili_api().remove_account(name)
    self._refresh_account_list()
    self._refresh_cookie_display()
    self._refresh_status()


def _password_login(self):
    """密码登录 B站

    创建账号密码输入对话框，支持:
      - 短信验证码验证
      - 极验滑块验证（手动模式）
    登录成功后自动设置 Cookie 并更新 UI。
    """
    pwd_top, ui = _draw_login_form(self)

    def _do_login(captcha_code: str = "", ct: int = 0):
        """执行登录请求"""
        uname = ui["username_entry"].get().strip()
        pwd = ui["password_entry"].get()
        if not uname or not pwd:
            messagebox.showwarning("提示", "请输入账号和密码", parent=pwd_top)
            return
        # 禁用输入控件，防止重复提交
        for w in (ui["username_entry"], ui["password_entry"], ui["captcha_entry"]):
            w.config(state="disabled")
        ui["login_btn"].config(state="disabled")
        ui["status_var"].set("登录中..." if not captcha_code else "验证中...")
        ui["status_lbl"].config(fg=C["text_2"])
        pwd_top.update()

        def _worker():
            try:
                result = get_bilibili_api().login_with_password(uname, pwd, captcha=captcha_code, captcha_type=ct)
                pwd_top.after(0, lambda: _handle_result(result))
            except Exception as e:
                pwd_top.after(0, lambda e=e: ui["status_var"].set(f"异常: {e}"))

        import threading

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_result(result):
        """处理登录 API 返回结果"""
        code = result.get("code", -1)
        if code == 0:
            _handle_login_response(self, pwd_top, ui, result)
        elif result.get("need_captcha") and not ui["captcha_entry"].get().strip():
            _handle_captcha_flow(self, pwd_top, ui, result, _do_login)
        elif "验证码" in result.get("message", "") or result.get("code") in (-629, -352):
            _handle_captcha_flow(self, pwd_top, ui, result, _do_login)
        else:
            _handle_login_response(self, pwd_top, ui, result)

    def _submit_captcha():
        """提交短信验证码"""
        code = ui["captcha_entry"].get().strip()
        if not code:
            messagebox.showwarning("提示", "请输入验证码", parent=pwd_top)
            return
        _do_login(captcha_code=code, ct=ui["captcha_type_var"].get())

    ui["login_btn"].config(command=lambda: _do_login())
    ui["submit_captcha_btn"].config(command=_submit_captcha)

    for w in (ui["username_entry"], ui["password_entry"]):
        w.bind("<Return>", lambda e: _do_login())
    ui["captcha_entry"].bind("<Return>", lambda e: _submit_captcha())
    ttk.Button(ui["btn_f"], text="取消", command=pwd_top.destroy).pack(side=tk.LEFT, padx=4)


def _draw_login_form(self):
    """构建密码登录对话框 UI

    Returns:
        tuple: (pwd_top, ui_dict) 窗口对象和 UI 控件字典
      """
    pwd_top = tk.Toplevel(self.window)
    pwd_top.title("密码登录 B站")
    sw = self.window.winfo_screenwidth()
    sh = self.window.winfo_screenheight()
    pwd_top.geometry(f"{int(sw * 0.28)}x{int(sh * 0.36)}")
    pwd_top.configure(bg=C["bg_surface"])
    pwd_top.transient(self.window)
    pwd_top.grab_set()
    pwd_top.resizable(False, False)

    tk.Label(
        pwd_top,
        text="B站 账号密码登录",
        bg=C["bg_surface"],
        fg=C["text_1"],
        font=("Microsoft YaHei UI", 13, "bold"),
    ).pack(pady=(18, 4))
    tk.Label(
        pwd_top,
        text="部分账号需要手机验证码，建议使用扫码登录",
        bg=C["bg_surface"],
        fg=C["text_3"],
        font=FONT_SM,
    ).pack()

    form = tk.Frame(pwd_top, bg=C["bg_surface"])
    form.pack(pady=(12, 0))

    tk.Label(form, text="账号:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).grid(row=0, column=0, sticky="w")
    username_entry = ttk.Entry(form, width=28, font=FONT)
    username_entry.grid(row=0, column=1, padx=(8, 0), pady=4)

    tk.Label(form, text="密码:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).grid(row=1, column=0, sticky="w")
    password_entry = ttk.Entry(form, width=28, font=FONT, show="*")
    password_entry.grid(row=1, column=1, padx=(8, 0), pady=4)

    captcha_frame = tk.Frame(pwd_top, bg=C["bg_surface"])
    captcha_row = tk.Frame(captcha_frame, bg=C["bg_surface"])
    captcha_row.pack()
    tk.Label(captcha_row, text="验证码:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
    captcha_entry = ttk.Entry(captcha_row, width=14, font=FONT)
    captcha_entry.pack(side=tk.LEFT, padx=(8, 0))
    captcha_type_var = tk.IntVar(value=0)

    status_var = tk.StringVar(value="")
    status_lbl = tk.Label(
        pwd_top, textvariable=status_var, bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM, wraplength=300
    )
    status_lbl.pack(pady=(8, 0))

    btn_f = tk.Frame(pwd_top, bg=C["bg_surface"])
    btn_f.pack(pady=(6, 0))
    login_btn = ttk.Button(btn_f, text="登录", style="Primary.TButton")
    login_btn.pack(side=tk.LEFT, padx=4)

    captcha_btn_f = tk.Frame(pwd_top, bg=C["bg_surface"])
    submit_captcha_btn = ttk.Button(captcha_btn_f, text="提交验证码", style="Primary.TButton")
    captcha_btn_f.pack(pady=(4, 0))
    captcha_btn_f.pack_forget()

    cancel_btn = ttk.Button(btn_f, text="取消", command=pwd_top.destroy)
    cancel_btn.pack(side=tk.LEFT, padx=4)

    ui = {
        "pwd_top": pwd_top,
        "username_entry": username_entry,
        "password_entry": password_entry,
        "captcha_frame": captcha_frame,
        "captcha_entry": captcha_entry,
        "captcha_type_var": captcha_type_var,
        "status_var": status_var,
        "status_lbl": status_lbl,
        "btn_f": btn_f,
        "login_btn": login_btn,
        "cancel_btn": cancel_btn,
        "captcha_btn_f": captcha_btn_f,
        "submit_captcha_btn": submit_captcha_btn,
    }
    return pwd_top, ui


def _handle_login_response(self, pwd_top, ui, result):
    """处理登录响应：成功设置 Cookie，失败显示错误信息

    Args:
        self: SettingsWindow 实例
        pwd_top: 登录窗口
        ui: UI 控件字典
        result: API 返回的登录结果
    """
    code = result.get("code", -1)
    if code == 0:
        cookies = result.get("cookies", {})
        get_bilibili_api().set_cookies(cookies)
        get_bilibili_api().add_account(
            get_bilibili_api().get_active_account(), cookies, get_bilibili_api().get_refresh_token()
        )
        self._net_cfg["cookies"] = cookies
        self._net_cfg["refresh_token"] = result.get("refresh_token", "")
        self._save_net_config()
        self._refresh_cookie_display()
        self._refresh_status()
        ui["status_var"].set("登录成功！")
        ui["status_lbl"].config(fg=C["success"])
        pwd_top.after(800, pwd_top.destroy)
        self.window.after(1000, self._verify_login)
        messagebox.showinfo(
            "登录成功",
            f"已获取 Cookie: {', '.join(cookies.keys())}",
            parent=self.window,
        )
    else:
        msg = result.get("message", "未知错误")
        if code == -1057:
            msg += "，请检查账号密码"
        ui["status_var"].set(msg)
        ui["status_lbl"].config(fg=C["danger"])
        for w in (ui["username_entry"], ui["password_entry"], ui["captcha_entry"]):
            w.config(state="normal")
        ui["login_btn"].config(state="normal")


def _handle_captcha_flow(self, pwd_top, ui, result, do_login_cb):
    """处理验证码流程：短信验证码 (type 6) 或极验滑块验证

    Args:
        self: SettingsWindow 实例
        pwd_top: 登录窗口
        ui: UI 控件字典
        result: API 返回的需要验证码的结果
        do_login_cb: 登录回调函数（用于重试登录）
    """
    captcha_frame = ui["captcha_frame"]
    captcha_btn_f = ui["captcha_btn_f"]
    ct = result.get("captcha_type", 0)
    ui["captcha_type_var"].set(ct)
    if ct == 6:
        # 短信验证码流程
        phone = result.get("captcha_phone", "")
        hint = f"验证码已发送至 {phone}" if phone else "请输入手机收到的验证码"
        ui["status_var"].set(hint)
        ui["status_lbl"].config(fg=C["warning"])
        captcha_frame.pack(pady=(6, 0))
        ui["captcha_entry"].config(state="normal")
        ui["captcha_entry"].focus_set()
        captcha_btn_f.pack(pady=(2, 0))
        ui["submit_captcha_btn"].pack(side=tk.LEFT, padx=4)
        ui["login_btn"].pack_forget()
        ui["cancel_btn"].pack_forget()
        ttk.Button(captcha_btn_f, text="取消", command=pwd_top.destroy).pack(side=tk.LEFT, padx=4)
    else:
        # 极验滑块验证流程
        gt = result.get("gt", "")
        challenge = result.get("challenge", "")
        geetest_url = f"https://api.geetest.com/get.php?gt={gt}&challenge={challenge}&lang=zh-cn&product=embed"
        is_retry = bool(result.get("code") in (-629, -352))

        if is_retry:
            ui["status_var"].set("需要极验验证（自动求解未触发，请手动完成）")
        else:
            ui["status_var"].set("需要极验滑块验证（自动求解失败，请手动完成）")
        ui["status_lbl"].config(fg=C["danger"])

        def _open_geetest():
            import webbrowser
            webbrowser.open(geetest_url)
            messagebox.showinfo("极验验证", "请在浏览器中完成滑块验证，然后将 validate 和 seccode 值输入下方", parent=pwd_top)

        ttk.Button(captcha_btn_f, text="🌐 打开极验验证页", command=_open_geetest).pack(side=tk.LEFT, padx=4)
        tk.Label(captcha_frame, text="validate:", bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM).pack()
        geetest_validate_entry = ttk.Entry(captcha_frame, width=40, font=("Consolas", 9))
        geetest_validate_entry.pack(pady=2)
        tk.Label(captcha_frame, text="seccode:", bg=C["bg_surface"], fg=C["text_2"], font=FONT_SM).pack()
        geetest_seccode_entry = ttk.Entry(captcha_frame, width=40, font=("Consolas", 9))
        geetest_seccode_entry.pack(pady=2)
        captcha_frame.pack(pady=(6, 0))

        def _submit_geetest():
            validate = geetest_validate_entry.get().strip()
            seccode = geetest_seccode_entry.get().strip()
            if validate and seccode:
                do_login_cb(captcha_code=f"{validate}:{seccode}", ct=-1)

        ttk.Button(captcha_btn_f, text="提交极验结果", command=_submit_geetest).pack(side=tk.LEFT, padx=4)

    for w in (ui["username_entry"], ui["password_entry"]):
        w.config(state="normal")
    ui["login_btn"].config(state="normal")
