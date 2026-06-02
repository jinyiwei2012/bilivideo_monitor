"""
代理设置模块
===========

本模块为 ``SettingsWindow`` 提供 mixin 函数，构建「代理设置」标签页。
提供完整的代理管理功能：

  - 代理列表编辑（多行文本区域，每行一个代理 URL）
  - 手动添加（协议 + 地址输入）
  - 批量导入（弹窗中粘贴多行地址）
  - 自动获取（从内置 + 自定义代理源拉取并测试）
  - 代理可用性检查（并发测试，Treeview 展示结果）
  - 失效代理自动清理
  - 配置持久化（保存到 data/network_config.json）

支持的代理协议：http://, https://, socks4://, socks5://

.. note::
   代理测试使用 ``ProxyManager.test_proxy()`` 并发执行，
   测试地址默认为 B 站 API，可在 UI 中自定义。
"""

import json
import os
import re
import tkinter as tk
import logging
from tkinter import ttk, messagebox
from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, project_path
from core.bilibili_api import get_bilibili_api
from core.proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


def _build_proxy_tab(self, nb):
    """
    构建完整的「代理设置」标签页，包含：
      - 代理列表编辑区
      - 手动添加行（协议下拉 + 地址输入 + 添加按钮）
      - 批量导入 / 检查可用性按钮
      - 自动获取代理（内置源 + 自定义源）
      - 代理测试结果 Treeview（地址、状态、延迟、地区、IP、ASN、ISP）
      - 测试地址自定义

    :param self: SettingsWindow 实例（隐式）
    :param nb: ttk.Notebook 控件，标签页容器
    """
    page = tk.Frame(nb, bg=C["bg_base"])
    nb.add(page, text="  代理设置  ")

    sec = tk.Frame(page, bg=C["bg_elevated"], highlightthickness=1, highlightbackground=C["border_sub"])
    sec.pack(fill=tk.BOTH, expand=True, padx=16, pady=12, ipadx=10, ipady=8)
    tk.Label(sec, text="代理列表（每行一个）", bg=C["bg_elevated"], fg=C["text_2"], font=FONT).pack(
        anchor="w", pady=(0, 4)
    )

    # ── 手动添加行：协议 + 地址 + 添加按钮 ──
    add_row = tk.Frame(sec, bg=C["bg_elevated"])
    add_row.pack(fill=tk.X, pady=(0, 4))
    tk.Label(add_row, text="协议:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    self._proxy_proto_var = tk.StringVar(value="http://")
    proto_cb = ttk.Combobox(
        add_row,
        textvariable=self._proxy_proto_var,
        values=["http://", "https://", "socks4://", "socks5://"],
        width=10,
        state="readonly",
        font=FONT_SM,
    )
    proto_cb.pack(side=tk.LEFT, padx=(4, 8))
    tk.Label(add_row, text="地址:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    self._proxy_addr_entry = ttk.Entry(add_row, width=35, font=FONT_SM)
    self._proxy_addr_entry.pack(side=tk.LEFT, padx=(4, 8))
    self._proxy_addr_entry.bind("<Return>", lambda e: self._add_proxy_entry())  # 回车快速添加
    ttk.Button(add_row, text="添加", command=self._add_proxy_entry, style="Primary.TButton").pack(side=tk.LEFT)

    # ── 代理列表文本区 ──
    self.proxy_text = tk.Text(
        sec,
        height=8,
        bg=C["bg_base"],
        fg=C["text_1"],
        insertbackground=C["text_1"],
        font=("Consolas", 10),
        relief="flat",
        highlightthickness=1,
        highlightbackground=C["border"],
    )
    self.proxy_text.pack(fill=tk.X, pady=6)
    # 加载已保存的代理列表
    if self._net_cfg.get("proxies"):
        self.proxy_text.insert("1.0", "\n".join(self._net_cfg["proxies"]))

    # ── 按钮行：应用 / 批量导入 / 检查可用性 ──
    btn_row = tk.Frame(sec, bg=C["bg_elevated"])
    btn_row.pack(fill=tk.X)
    ttk.Button(btn_row, text="应用代理", command=self._apply_proxies).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(btn_row, text="批量导入", command=self._batch_import_proxies).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_row, text="检查可用性", command=self._check_proxies).pack(side=tk.LEFT, padx=4)
    self._proxy_test_status = tk.Label(btn_row, text="", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM)
    self._proxy_test_status.pack(side=tk.LEFT, padx=8)

    # ── 自动获取代理行 ──
    auto_row = tk.Frame(sec, bg=C["bg_elevated"])
    auto_row.pack(fill=tk.X, pady=(4, 0))
    ttk.Button(auto_row, text="🌐 自动获取代理", command=self._auto_fetch_proxies).pack(side=tk.LEFT, padx=(0, 4))
    self._auto_fetch_status = tk.Label(auto_row, text="", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM)
    self._auto_fetch_status.pack(side=tk.LEFT, padx=8)

    # ── 自定义代理源输入行 ──
    src_row = tk.Frame(sec, bg=C["bg_elevated"])
    src_row.pack(fill=tk.X, pady=(2, 0))
    tk.Label(src_row, text="自定义代理源:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT)
    self._proxy_src_entry = ttk.Entry(src_row, width=50, font=FONT_SM)
    self._proxy_src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
    self._proxy_src_entry.bind("<Return>", lambda e: self._add_proxy_source())
    ttk.Button(src_row, text="添加源", command=self._add_proxy_source).pack(side=tk.LEFT)

    # ── 测试地址行 ──
    url_row = tk.Frame(sec, bg=C["bg_elevated"])
    url_row.pack(fill=tk.X, pady=(2, 0))
    tk.Label(
        url_row, text="测试地址:", bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM, width=8, anchor="w"
    ).pack(side=tk.LEFT)
    self._test_url_var = tk.StringVar(value="https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7hQ")
    url_entry = ttk.Entry(url_row, textvariable=self._test_url_var, font=FONT_SM)
    url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

    # ── 代理测试结果 Treeview ──
    result_container = tk.Frame(sec, bg=C["bg_base"], highlightthickness=1, highlightbackground=C["border"])
    result_container.pack(fill=tk.BOTH, expand=True, pady=(6, 4))

    columns = ("addr", "status", "latency", "country", "ip", "asn", "isp")
    self._proxy_tree = ttk.Treeview(result_container, columns=columns, show="headings", height=6)
    self._proxy_tree.heading("addr", text="代理地址")
    self._proxy_tree.heading("status", text="状态")
    self._proxy_tree.heading("latency", text="延迟/原因")
    self._proxy_tree.heading("country", text="地区")
    self._proxy_tree.heading("ip", text="IP")
    self._proxy_tree.heading("asn", text="ASN")
    self._proxy_tree.heading("isp", text="ISP")
    self._proxy_tree.column("addr", anchor="w", width=200, minwidth=120, stretch=True)
    self._proxy_tree.column("status", anchor="center", width=40, minwidth=40, stretch=False)
    self._proxy_tree.column("latency", anchor="w", width=200, minwidth=120, stretch=True)
    self._proxy_tree.column("country", anchor="w", width=80, minwidth=60, stretch=False)
    self._proxy_tree.column("ip", anchor="w", width=140, minwidth=100, stretch=False)
    self._proxy_tree.column("asn", anchor="w", width=150, minwidth=100, stretch=False)
    self._proxy_tree.column("isp", anchor="w", width=150, minwidth=100, stretch=False)

    tree_sb = ttk.Scrollbar(result_container, orient="vertical", command=self._proxy_tree.yview)
    self._proxy_tree.configure(yscrollcommand=tree_sb.set)
    self._proxy_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    tree_sb.pack(side=tk.RIGHT, fill=tk.Y)
    style = ttk.Style()
    style.configure("Treeview", rowheight=24, font=("Consolas", 9))
    self._proxy_tree.tag_configure("ok", foreground=C["success"])   # 可用代理标记
    self._proxy_tree.tag_configure("fail", foreground=C["danger"])  # 失效代理标记

    # 底部提示
    tk.Label(
        sec,
        text="使用代理可有效绕过IP级别的频率限制",
        bg=C["bg_elevated"],
        fg=C["warning"],
        font=FONT_SM,
        anchor="w",
    ).pack(fill=tk.X, pady=(4, 0))


def _auto_fetch_proxies(self):
    """
    自动获取代理：从内置源和自定义源拉取代理列表，并在后台线程中逐个测试。
    测试结果实时更新到 Treeview。

    :param self: SettingsWindow 实例（隐式）
    """
    import threading
    self._auto_fetch_status.config(text="⏳ 获取中…", fg=C["warning"])
    self._proxy_tree.delete(*self._proxy_tree.get_children())  # 清空旧结果
    threading.Thread(target=self._auto_fetch_worker, daemon=True).start()


def _auto_fetch_worker(self):
    """
    后台工作线程：遍历所有代理源 URL，拉取 → 解析 → 逐项测试。

    对每个代理 URL：
      1. 在 Treeview 中插入一行（状态为 ⏳）
      2. 调用 ProxyManager.test_proxy() 测试
      3. 更新 Treeview 行为 ✅ 或 ❌
      4. 可用的代理自动加入 ProxyManager

    完成后更新代理文本框，显示统计结果。

    :param self: SettingsWindow 实例（隐式）
    """
    import requests as _req
    from core import bilibili_api as _api

    api = _api.get_bilibili_api()
    pm = api.proxy_manager
    total_found = 0   # 可用代理计数
    total_tested = 0  # 已测试代理计数

    for src_url in pm.PROXY_SOURCES:
        source_name = src_url.split("/")[2]  # 提取域名作为源名称
        self.window.after(0, lambda n=source_name: self._auto_fetch_status.config(
            text=f"⏳ 拉取 {n}…", fg=C["warning"]))
        try:
            resp = _req.get(src_url, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"}, verify=False)  # nosec B501 — proxy source testing; no sensitive data
            if resp.status_code != 200:
                continue
            urls = pm._parse_proxy_list(resp.text, src_url)  # 解析代理列表
            for url in urls:
                total_tested += 1
                item = self._proxy_tree.insert("", "end", values=(url, "⏳", "测试中…", "", "", "", ""))
                self.window.after(0, lambda: self._proxy_tree.yview_moveto(1))  # 自动滚动到最新
                result = ProxyManager.test_proxy(url, timeout=8)
                ok = result.get("ok", False)
                total_found += 1 if ok else 0
                # 回到主线程更行 Treeview 行
                self.window.after(0, lambda i=item, r=result: (
                    self._proxy_tree.set(i, "status", "✅" if r.get("ok") else "❌"),
                    self._proxy_tree.set(i, "latency", f"{r['latency_ms']}ms" if r.get("ok") else r.get("error", "超时")[:40]),
                    self._proxy_tree.set(i, "country", r.get("country", "") or ""),
                    self._proxy_tree.set(i, "ip", r.get("ip", "") or ""),
                    self._proxy_tree.set(i, "asn", r.get("asn", "") or ""),
                    self._proxy_tree.set(i, "isp", r.get("isp", "") or ""),
                    self._proxy_tree.item(i, tags=("ok" if r.get("ok") else "fail",)),
                ))
                if result.get("ok"):
                    pm.add_proxy({"http": url, "https": url})  # 可用代理加入管理
        except Exception as e:
            self.window.after(0, lambda n=source_name: self._auto_fetch_status.config(
                text=f"⚠ {n} 失败: {e}", fg=C["danger"]))

    # 完成：更新代理文本框 + 状态显示
    urls = [p.get("http", "") for p in pm.proxies if p.get("http")]
    self.window.after(0, lambda: self._update_proxy_text(urls))
    self.window.after(0, lambda: self._auto_fetch_status.config(
        text=f"✅ 测试 {total_tested} 个, 可用 {total_found} 个", fg=C["success"]))


def _update_proxy_text(self, urls):
    """将代理 URL 列表写入文本框"""
    self.proxy_text.delete("1.0", tk.END)
    self.proxy_text.insert("1.0", "\n".join(urls))


def _add_proxy_source(self):
    """
    添加自定义代理源 URL。
    验证以 http:// 或 https:// 开头，去重后加入 ProxyManager.PROXY_SOURCES。

    :param self: SettingsWindow 实例（隐式）
    """
    url = self._proxy_src_entry.get().strip()
    if not url:
        return
    if not url.startswith("http"):
        messagebox.showwarning("提示", "代理源地址必须以 http:// 或 https:// 开头", parent=self.window)
        return
    if url not in ProxyManager.PROXY_SOURCES:
        ProxyManager.PROXY_SOURCES.append(url)
        self._proxy_src_entry.delete(0, tk.END)
        messagebox.showinfo("成功", f"已添加代理源:\n{url}\n\n点击「自动获取代理」即可拉取", parent=self.window)


def _add_proxy_entry(self):
    """
    手动添加单条代理地址到列表。
    如果用户已输入完整 URL 则直接使用，否则自动补全协议头。

    :param self: SettingsWindow 实例（隐式）
    """
    proto = self._proxy_proto_var.get()
    addr = self._proxy_addr_entry.get().strip()
    if not addr:
        return
    # 判断是否已是完整 URL（如 http://1.2.3.4:8080）
    if re.match(r"^(https?|socks[45])://", addr, re.IGNORECASE):
        line = addr
    else:
        line = f"{proto}{addr}"  # 自动补全协议头
    self._proxy_addr_entry.delete(0, tk.END)
    text = self.proxy_text.get("1.0", "end").strip()
    lines = [ln for ln in text.split("\n") if ln.strip()] if text else []
    lines.append(line)
    self.proxy_text.delete("1.0", "end")
    self.proxy_text.insert("1.0", "\n".join(lines))


def _batch_import_proxies(self):
    """
    打开批量导入代理的 Toplevel 弹窗。
    支持每行一个地址（host:port 或完整 URL），自动补全协议头。
    导入后追加到现有代理列表末尾（保留重复项，但有提示）。

    :param self: SettingsWindow 实例（隐式）
    """
    top = tk.Toplevel(self.window)
    top.title("批量导入代理")
    sw = self.window.winfo_screenwidth()
    sh = self.window.winfo_screenheight()
    top.geometry(f"{int(sw * 0.35)}x{int(sh * 0.45)}")
    top.configure(bg=C["bg_surface"])
    top.transient(self.window)
    top.grab_set()
    top.resizable(True, True)

    tk.Label(
        top,
        text="批量导入代理地址",
        bg=C["bg_surface"],
        fg=C["text_1"],
        font=("Microsoft YaHei UI", 11, "bold"),
    ).pack(pady=(14, 2))

    # 协议选择
    proto_row = tk.Frame(top, bg=C["bg_surface"])
    proto_row.pack(fill=tk.X, padx=20, pady=(4, 2))
    tk.Label(proto_row, text="协议:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT)
    batch_proto_var = tk.StringVar(value=self._proxy_proto_var.get())
    ttk.Combobox(
        proto_row,
        textvariable=batch_proto_var,
        values=["http://", "https://", "socks4://", "socks5://"],
        width=12,
        state="readonly",
        font=FONT,
    ).pack(side=tk.LEFT, padx=(6, 0))

    tk.Label(
        top,
        text="每行一个地址（host:port 或完整URL），导入时自动补全协议头",
        bg=C["bg_surface"],
        fg=C["text_3"],
        font=FONT_SM,
    ).pack(pady=(4, 2))

    # 地址输入文本区
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
    text_w.pack(fill=tk.BOTH, expand=True, padx=20, pady=4)

    btn_f = tk.Frame(top, bg=C["bg_surface"])
    btn_f.pack(fill=tk.X, padx=20, pady=(4, 14))

    status_var = tk.StringVar(value="")
    status_lbl = tk.Label(
        btn_f, textvariable=status_var, bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM, anchor="w"
    )
    status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _do_import():
        """执行导入：解析文本 → 去重统计 → 追加到代理列表"""
        raw = text_w.get("1.0", tk.END).strip()
        if not raw:
            status_var.set("请输入代理地址")
            status_lbl.config(fg=C["danger"])
            return

        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        proto = batch_proto_var.get()
        imported = []
        for ln in lines:
            # 已有协议头 → 直接使用；否则补全
            if re.match(r"^(https?|socks[45])://", ln, re.IGNORECASE):
                imported.append(ln)
            else:
                imported.append(f"{proto}{ln}")

        # 追加到现有列表
        current = self.proxy_text.get("1.0", "end").strip()
        all_lines = [ln for ln in current.split("\n") if ln.strip()] if current else []
        all_lines.extend(imported)
        self.proxy_text.delete("1.0", "end")
        self.proxy_text.insert("1.0", "\n".join(all_lines))

        unique = set(all_lines)
        dup_count = len(all_lines) - len(unique)  # 重复计数

        total_count = len(imported)
        status_lbl.config(fg=C["success"])
        msg = f"✅ 已导入 {total_count} 条代理"
        if dup_count:
            msg += f"（含 {dup_count} 条重复）"
        status_var.set(msg)

        top.after(
            200,
            lambda: messagebox.showinfo(
                "导入完成",
                f"成功导入 {total_count} 条代理\n"
                f"当前代理列表共 {len(all_lines)} 条"
                + (f"\n（其中 {dup_count} 条重复已去重）" if dup_count else ""),
                parent=top,
            ),
        )

    ttk.Button(btn_f, text="导入并追加", command=_do_import, style="Primary.TButton").pack(
        side=tk.RIGHT, padx=(4, 0)
    )
    ttk.Button(btn_f, text="取消", command=top.destroy).pack(side=tk.RIGHT, padx=4)


def _apply_proxies(self):
    """
    应用代理设置：清空当前代理池 → 添加文本框中的所有代理 → 保存配置 → 检查可用性。

    :param self: SettingsWindow 实例（隐式）
    """
    text = self.proxy_text.get("1.0", "end").strip()
    proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
    get_bilibili_api().clear_proxies()  # 清空现有代理
    for ps in proxy_list:
        get_bilibili_api().add_proxy({"http": ps, "https": ps})  # 每条代理同时用于 HTTP/HTTPS
    self._net_cfg["proxies"] = proxy_list
    self._save_net_config()  # 持久化到 disk
    self._verify_proxy_persisted()  # 验证保存成功
    self._check_proxies()  # 立即测试可用性


def _verify_proxy_persisted(self):
    """
    验证代理配置是否成功持久化到 data/network_config.json。
    读取文件并检查 proxies 数组长度，写入日志。

    :param self: SettingsWindow 实例（隐式）
    """
    try:
        cfg_path = project_path("data", "network_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            count = len(saved.get("proxies", []))
            logger.info("代理配置持久化验证: %s — %d 条代理已保存", cfg_path, count)
    except Exception as e:
        logger.warning("代理配置持久化验证失败: %s", e)


def _check_proxies(self):
    """
    并发测试所有代理的可用性。
    为每个代理启动一个后台线程进行测试，结果实时更新到 Treeview。
    测试完成后自动移除失效代理。

    支持取消测试（cancel_flag 机制）。

    :param self: SettingsWindow 实例（隐式）
    """
    text = self.proxy_text.get("1.0", "end").strip()
    proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
    if not proxy_list:
        messagebox.showwarning("提示", "请先输入要测试的代理", parent=self.window)
        return

    test_url = self._test_url_var.get().strip()

    # 清空旧测试结果
    for item in self._proxy_tree.get_children():
        self._proxy_tree.delete(item)

    # 插入初始行（状态为 ⏳）
    row_items = []
    for proxy in proxy_list:
        item = self._proxy_tree.insert("", "end", values=(proxy, "⏳", "—", "", "", "", ""))
        row_items.append(item)

    import threading

    total = len(proxy_list)
    ok_count = [0]     # 可用计数（用列表包装以在闭包中修改）
    fail_count = [0]   # 失效计数
    cancel_flag = [False]  # 取消标志
    threads = []
    lock = threading.Lock()  # 线程安全的计数累加
    self._proxy_test_status.configure(text=f"测试中 0/{total} …", fg=C["warning"])

    # 取消按钮（内联到状态标签旁）
    cancel_btn = ttk.Button(
        self._proxy_test_status.master, text="✕ 取消", command=lambda: cancel_flag.__setitem__(0, True)
    )
    cancel_btn.pack(side=tk.LEFT, padx=2)

    def test_one(proxy, item):
        """测试单个代理并更新 Treeview"""
        if cancel_flag[0]:
            return
        result = ProxyManager.test_proxy(proxy, test_url=test_url)
        ok = result.get("ok", False)
        latency = f"{result.get('latency_ms', '—')}ms" if ok else (result.get("error") or "—")
        country = result.get("country") or "—"
        ip = result.get("ip") or "—"
        asn = result.get("asn") or "—"
        isp = result.get("isp") or "—"
        status = "✅" if ok else "❌"
        tag = "ok" if ok else "fail"
        # 回到主线程更新 UI
        self.window.after(
            0,
            lambda item=item, status=status, latency=latency, country=country, ip=ip, asn=asn, isp=isp, tag=tag: (
                self._proxy_tree.set(item, "status", status),
                self._proxy_tree.set(item, "latency", latency),
                self._proxy_tree.set(item, "country", country),
                self._proxy_tree.set(item, "ip", ip),
                self._proxy_tree.set(item, "asn", asn),
                self._proxy_tree.set(item, "isp", isp),
                self._proxy_tree.item(item, tags=(tag,)),
            ),
        )
        with lock:
            if ok:
                ok_count[0] += 1
            else:
                fail_count[0] += 1
            done = ok_count[0] + fail_count[0]
            self.window.after(
                0, lambda d=done: self._proxy_test_status.configure(text=f"测试中 {d}/{total} …", fg=C["warning"])
            )

    # 启动所有测试线程
    for proxy, item in zip(proxy_list, row_items):
        t = threading.Thread(target=test_one, args=(proxy, item), daemon=True)
        t.start()
        threads.append(t)

    def _wait_all():
        """等待所有测试线程完成后的收尾工作"""
        for t in threads:
            t.join()
        self.window.after(0, cancel_btn.destroy)  # 移除取消按钮
        ok_n, fail_n = ok_count[0], fail_count[0]
        status_text = f"完成: {ok_n} 可用" + (f", {fail_n} 失败" if fail_n else "")
        self.window.after(
            0, lambda: self._proxy_test_status.configure(text=status_text, fg=C["success"] if ok_n else C["danger"])
        )

        # 自动移除失效代理
        if fail_n:
            failed = []
            for proxy, item in zip(proxy_list, row_items):
                tags = self._proxy_tree.item(item, "tags")
                if "fail" in tags:
                    failed.append(proxy)
            if failed:
                self.window.after(0, lambda: self._auto_remove_failed_proxies(failed))

    threading.Thread(target=_wait_all, daemon=True).start()


def _auto_remove_failed_proxies(self, failed_urls):
    """
    自动从代理列表和 ProxyManager 中移除测试失败的代理。
    同时更新持久化配置并弹出清理提示。

    :param self: SettingsWindow 实例（隐式）
    :param failed_urls: 失效代理 URL 列表
    """
    text = self.proxy_text.get("1.0", "end").strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    remaining = [ln for ln in lines if ln not in failed_urls]  # 过滤失效项
    self.proxy_text.delete("1.0", "end")
    self.proxy_text.insert("1.0", "\n".join(remaining))

    # 同步更新 API 代理池
    get_bilibili_api().clear_proxies()
    for ps in remaining:
        get_bilibili_api().add_proxy({"http": ps, "https": ps})

    self._net_cfg["proxies"] = remaining
    self._save_net_config()

    # 脱敏显示失效代理地址
    masked = ", ".join(ProxyManager.mask_url(u) for u in failed_urls)
    msg = f"已自动移除 {len(failed_urls)} 个失效代理:\n{masked}"
    logger.info(msg)
    messagebox.showinfo("代理清理", msg, parent=self.window)


def _sync_proxy_text_to_cfg(self):
    """
    将代理文本框内容同步到 self._net_cfg['proxies']（不保存文件）。
    用于 SettingsWindow 关闭时自动保存。

    :param self: SettingsWindow 实例（隐式）
    """
    text = self.proxy_text.get("1.0", "end").strip()
    self._net_cfg["proxies"] = [line.strip() for line in text.split("\n") if line.strip()]
