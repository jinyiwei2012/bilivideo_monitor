"""
代理设置 — PyQt6 版

Mixin functions for SettingsWindow.
"""

import json
import os
import re
import logging
import threading
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QPlainTextEdit, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QMessageBox, QDialog,
    QTextEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_SM, project_path
from core.bilibili_api import get_bilibili_api
from core.proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


class _BatchImportDialog(QDialog):
    """批量导入代理对话框"""

    _imported = pyqtSignal(list)  # imported_proxies

    def __init__(self, default_proto: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量导入代理")
        screen = parent.screen() if parent else None
        if screen:
            geo = screen.geometry()
            sw, sh = geo.width(), geo.height()
        else:
            sw, sh = 1920, 1080
        self.resize(int(sw * 0.35), int(sh * 0.45))
        self.setStyleSheet(f"background-color: {C['bg_surface']};")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)

        title = QLabel("批量导入代理地址")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C['text_1']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        proto_row = QWidget()
        proto_row.setStyleSheet(f"background-color: {C['bg_surface']};")
        proto_layout = QHBoxLayout(proto_row)
        proto_layout.setContentsMargins(0, 4, 0, 2)
        plbl = QLabel("协议:")
        plbl.setFont(FONT)
        plbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        proto_layout.addWidget(plbl)
        self._proto_combo = QComboBox()
        self._proto_combo.addItems(["http://", "https://", "socks4://", "socks5://"])
        idx = self._proto_combo.findText(default_proto)
        if idx >= 0:
            self._proto_combo.setCurrentIndex(idx)
        self._proto_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px;
            }}
        """)
        proto_layout.addWidget(self._proto_combo)
        proto_layout.addStretch()
        layout.addWidget(proto_row)

        hint = QLabel("每行一个地址（host:port 或完整URL），导入时自动补全协议头")
        hint.setFont(FONT_SM)
        hint.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        layout.addWidget(hint)

        self._text = QPlainTextEdit()
        self._text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']}; color: {C['text_1']};
                font-family: Consolas; font-size: 10pt;
                border: 1px solid {C['border']};
            }}
        """)
        layout.addWidget(self._text, 1)

        self._status = QLabel("")
        self._status.setFont(FONT_SM)
        self._status.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        layout.addWidget(self._status)

        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_surface']};")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 4, 0, 0)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()

        import_btn = QPushButton("导入并追加")
        import_btn.setProperty("primary", True)
        style = import_btn.style()
        if style is not None:
            style.unpolish(import_btn)
            style.polish(import_btn)
        import_btn.clicked.connect(self._do_import)
        btn_layout.addWidget(import_btn)

        layout.addWidget(btn_row)

    def _do_import(self):
        raw = self._text.toPlainText().strip()
        if not raw:
            self._status.setText("请输入代理地址")
            self._status.setStyleSheet(f"color: {C['danger']};")
            return

        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        proto = self._proto_combo.currentText()
        imported = []
        for ln in lines:
            if re.match(r"^(https?|socks[45])://", ln, re.IGNORECASE):
                imported.append(ln)
            else:
                imported.append(f"{proto}{ln}")

        self._imported.emit(imported)
        self.accept()


def _build_proxy_tab(self, nb):
    page = QWidget()
    page.setStyleSheet(f"background-color: {C['bg_base']};")

    layout = QVBoxLayout(page)
    layout.setContentsMargins(16, 12, 16, 12)

    sec = QWidget()
    sec.setStyleSheet(f"""
        QWidget#proxySec {{
            background-color: {C['bg_elevated']};
            border: 1px solid {C['border_sub']};
            border-radius: 6px;
        }}
    """)
    sec.setObjectName("proxySec")
    sec_layout = QVBoxLayout(sec)
    sec_layout.setContentsMargins(10, 8, 10, 8)

    sec_title = QLabel("代理列表（每行一个）")
    sec_title.setFont(FONT)
    sec_title.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    sec_layout.addWidget(sec_title)

    # 添加行
    add_row = QWidget()
    add_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    add_layout = QHBoxLayout(add_row)
    add_layout.setContentsMargins(0, 0, 0, 4)

    proto_lbl = QLabel("协议:")
    proto_lbl.setFont(FONT_SM)
    proto_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    add_layout.addWidget(proto_lbl)

    self._proxy_proto_combo = QComboBox()
    self._proxy_proto_combo.addItems(["http://", "https://", "socks4://", "socks5://"])
    self._proxy_proto_combo.setStyleSheet(f"""
        QComboBox {{
            background-color: {C['bg_base']}; color: {C['text_1']};
            border: 1px solid {C['border']}; padding: 2px 6px;
        }}
    """)
    add_layout.addWidget(self._proxy_proto_combo)
    add_layout.addSpacing(8)

    addr_lbl = QLabel("地址:")
    addr_lbl.setFont(FONT_SM)
    addr_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    add_layout.addWidget(addr_lbl)

    self._proxy_addr_entry = QLineEdit()
    self._proxy_addr_entry.setFont(FONT_SM)
    self._proxy_addr_entry.setStyleSheet(f"""
        QLineEdit {{
            background-color: {C['bg_base']}; color: {C['text_1']};
            border: 1px solid {C['border']}; padding: 2px 6px;
        }}
    """)
    self._proxy_addr_entry.returnPressed.connect(self._add_proxy_entry)
    add_layout.addWidget(self._proxy_addr_entry)

    add_btn = QPushButton("添加")
    add_btn.setProperty("primary", True)
    style = add_btn.style()
    if style is not None:
        style.unpolish(add_btn)
        style.polish(add_btn)
    add_btn.clicked.connect(self._add_proxy_entry)
    add_layout.addWidget(add_btn)

    sec_layout.addWidget(add_row)

    # 代理文本编辑
    self._proxy_text = QPlainTextEdit()
    self._proxy_text.setMaximumBlockCount(500)
    self._proxy_text.setStyleSheet(f"""
        QPlainTextEdit {{
            background-color: {C['bg_base']}; color: {C['text_1']};
            font-family: Consolas; font-size: 10pt;
            border: 1px solid {C['border']};
        }}
    """)
    sec_layout.addWidget(self._proxy_text)

    if self._net_cfg.get("proxies"):
        self._proxy_text.setPlainText("\n".join(self._net_cfg["proxies"]))

    # 按钮行
    btn_row = QWidget()
    btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    btn_layout = QHBoxLayout(btn_row)
    btn_layout.setContentsMargins(0, 4, 0, 0)

    apply_btn = QPushButton("应用代理")
    apply_btn.clicked.connect(self._apply_proxies)
    btn_layout.addWidget(apply_btn)

    batch_btn = QPushButton("批量导入")
    batch_btn.clicked.connect(self._batch_import_proxies)
    btn_layout.addWidget(batch_btn)

    check_btn = QPushButton("检查可用性")
    check_btn.clicked.connect(self._check_proxies)
    btn_layout.addWidget(check_btn)

    self._proxy_test_status = QLabel("")
    self._proxy_test_status.setFont(FONT_SM)
    self._proxy_test_status.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    btn_layout.addWidget(self._proxy_test_status)

    btn_layout.addStretch()
    sec_layout.addWidget(btn_row)

    # 自动获取
    auto_row = QWidget()
    auto_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    auto_layout = QHBoxLayout(auto_row)
    auto_layout.setContentsMargins(0, 4, 0, 0)

    auto_btn = QPushButton("🌐 自动获取代理")
    auto_btn.clicked.connect(self._auto_fetch_proxies)
    auto_layout.addWidget(auto_btn)

    self._auto_fetch_status = QLabel("")
    self._auto_fetch_status.setFont(FONT_SM)
    self._auto_fetch_status.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    auto_layout.addWidget(self._auto_fetch_status)

    auto_layout.addStretch()
    sec_layout.addWidget(auto_row)

    # 自定义代理源
    src_row = QWidget()
    src_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    src_layout = QHBoxLayout(src_row)
    src_layout.setContentsMargins(0, 4, 0, 0)

    src_lbl = QLabel("自定义代理源:")
    src_lbl.setFont(FONT_SM)
    src_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    src_layout.addWidget(src_lbl)

    self._proxy_src_entry = QLineEdit()
    self._proxy_src_entry.setFont(FONT_SM)
    self._proxy_src_entry.setStyleSheet(f"""
        QLineEdit {{
            background-color: {C['bg_base']}; color: {C['text_1']};
            border: 1px solid {C['border']}; padding: 2px 6px;
        }}
    """)
    self._proxy_src_entry.returnPressed.connect(self._add_proxy_source)
    src_layout.addWidget(self._proxy_src_entry, 1)

    add_src_btn = QPushButton("添加源")
    add_src_btn.clicked.connect(self._add_proxy_source)
    src_layout.addWidget(add_src_btn)

    sec_layout.addWidget(src_row)

    # 测试地址
    url_row = QWidget()
    url_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    url_layout = QHBoxLayout(url_row)
    url_layout.setContentsMargins(0, 4, 0, 0)

    test_lbl = QLabel("测试地址:")
    test_lbl.setFont(FONT_SM)
    test_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
    test_lbl.setFixedWidth(60)
    url_layout.addWidget(test_lbl)

    self._test_url_entry = QLineEdit("https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7hQ")
    self._test_url_entry.setFont(FONT_SM)
    self._test_url_entry.setStyleSheet(f"""
        QLineEdit {{
            background-color: {C['bg_base']}; color: {C['text_1']};
            border: 1px solid {C['border']}; padding: 2px 6px;
        }}
    """)
    url_layout.addWidget(self._test_url_entry, 1)

    sec_layout.addWidget(url_row)

    # 结果表格
    result_container = QWidget()
    result_container.setStyleSheet(f"""
        QWidget#proxyResult {{
            background-color: {C['bg_base']};
            border: 1px solid {C['border']};
        }}
    """)
    result_container.setObjectName("proxyResult")
    result_layout = QVBoxLayout(result_container)
    result_layout.setContentsMargins(2, 2, 2, 2)

    self._proxy_tree = QTreeWidget()
    cols = ["代理地址", "状态", "延迟/原因", "地区", "IP", "ASN", "ISP"]
    self._proxy_tree.setHeaderLabels(cols)
    self._proxy_tree.setRootIsDecorated(False)
    self._proxy_tree.setAlternatingRowColors(False)
    self._proxy_tree.setStyleSheet(f"""
        QTreeWidget {{
            background-color: {C['bg_base']}; color: {C['text_1']};
            border: none; font-family: Consolas; font-size: 9pt;
        }}
        QTreeWidget::item {{
            padding: 2px 4px;
        }}
        QHeaderView::section {{
            background-color: {C['bg_surface']}; color: {C['text_2']};
            border: 1px solid {C['border_sub']}; padding: 2px 6px;
        }}
    """)
    header = self._proxy_tree.header()
    if header is not None:
        widths = {"代理地址": 200, "状态": 50, "延迟/原因": 200, "地区": 80, "IP": 140, "ASN": 150, "ISP": 150}
        for i, c in enumerate(cols):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self._proxy_tree.setColumnWidth(i, widths[c])

    result_layout.addWidget(self._proxy_tree)
    sec_layout.addWidget(result_container, 1)

    # 提示
    tip = QLabel("使用代理可有效绕过IP级别的频率限制")
    tip.setFont(FONT_SM)
    tip.setStyleSheet(f"color: {C['warning']}; background: transparent;")
    sec_layout.addWidget(tip)

    layout.addWidget(sec)

    tab_idx = nb.addTab(page, "  代理设置  ")
    return tab_idx


def _auto_fetch_proxies(self):
    self._auto_fetch_status.setText("⏳ 获取中…")
    self._auto_fetch_status.setStyleSheet(f"color: {C['warning']}; background: transparent;")
    self._proxy_tree.clear()
    threading.Thread(target=self._auto_fetch_worker, daemon=True).start()


def _auto_fetch_worker(self):
    import requests as _req
    from core import bilibili_api as _api

    api = _api.get_bilibili_api()
    pm = api.proxy_manager
    total_found = 0
    total_tested = 0

    for src_url in pm.PROXY_SOURCES:
        source_name = src_url.split("/")[2]
        self._auto_fetch_status.setText(f"⏳ 拉取 {source_name}…")
        self._auto_fetch_status.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        try:
            resp = _req.get(
                src_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}, verify=False
            )
            if resp.status_code != 200:
                continue
            urls = pm._parse_proxy_list(resp.text, src_url)
            for url in urls:
                total_tested += 1
                item = QTreeWidgetItem()
                item.setText(0, url)
                item.setText(1, "⏳")
                item.setText(2, "测试中…")
                self._proxy_tree.addTopLevelItem(item)
                self._proxy_tree.scrollToItem(item)
                result = ProxyManager.test_proxy(url, timeout=8)
                ok = result.get("ok", False)
                total_found += 1 if ok else 0
                item.setText(1, "✅" if ok else "❌")
                item.setText(2, f"{result['latency_ms']}ms" if ok else (result.get("error", "超时")[:40]))
                item.setText(3, result.get("country", "") or "")
                item.setText(4, result.get("ip", "") or "")
                item.setText(5, result.get("asn", "") or "")
                item.setText(6, result.get("isp", "") or "")
                color = C["success"] if ok else C["danger"]
                for c in range(7):
                    item.setForeground(c, Qt.GlobalColor.white if ok else Qt.GlobalColor.white)
                if result.get("ok"):
                    pm.add_proxy({"http": url, "https": url})
        except Exception as e:
            self._auto_fetch_status.setText(f"⚠ {source_name} 失败: {e}")
            self._auto_fetch_status.setStyleSheet(f"color: {C['danger']}; background: transparent;")

    urls = [p.get("http", "") for p in pm.proxies if p.get("http")]
    self._update_proxy_text(urls)
    self._auto_fetch_status.setText(f"✅ 测试 {total_tested} 个, 可用 {total_found} 个")
    self._auto_fetch_status.setStyleSheet(f"color: {C['success']}; background: transparent;")


def _update_proxy_text(self, urls):
    self._proxy_text.setPlainText("\n".join(urls))


def _add_proxy_source(self):
    url = self._proxy_src_entry.text().strip()
    if not url:
        return
    if not url.startswith("http"):
        QMessageBox.warning(self, "提示", "代理源地址必须以 http:// 或 https:// 开头")
        return
    if url not in ProxyManager.PROXY_SOURCES:
        ProxyManager.PROXY_SOURCES.append(url)
        self._proxy_src_entry.clear()
        QMessageBox.information(self, "成功", f"已添加代理源:\n{url}\n\n点击「自动获取代理」即可拉取")


def _add_proxy_entry(self):
    proto = self._proxy_proto_combo.currentText()
    addr = self._proxy_addr_entry.text().strip()
    if not addr:
        return
    if re.match(r"^(https?|socks[45])://", addr, re.IGNORECASE):
        line = addr
    else:
        line = f"{proto}{addr}"
    self._proxy_addr_entry.clear()
    text = self._proxy_text.toPlainText().strip()
    lines = [ln for ln in text.split("\n") if ln.strip()] if text else []
    lines.append(line)
    self._proxy_text.setPlainText("\n".join(lines))


def _batch_import_proxies(self):
    dlg = _BatchImportDialog(self._proxy_proto_combo.currentText(), self)

    def _on_import(imported):
        current = self._proxy_text.toPlainText().strip()
        all_lines = [ln for ln in current.split("\n") if ln.strip()] if current else []
        all_lines.extend(imported)
        self._proxy_text.setPlainText("\n".join(all_lines))

        unique = set(all_lines)
        dup_count = len(all_lines) - len(unique)
        msg = f"成功导入 {len(imported)} 条代理\n当前代理列表共 {len(all_lines)} 条"
        if dup_count:
            msg += f"\n（其中 {dup_count} 条重复已去重）"
        QMessageBox.information(self, "导入完成", msg)

    dlg._imported.connect(_on_import)
    dlg.exec()


def _apply_proxies(self):
    text = self._proxy_text.toPlainText().strip()
    proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
    get_bilibili_api().clear_proxies()
    for ps in proxy_list:
        get_bilibili_api().add_proxy({"http": ps, "https": ps})
    self._net_cfg["proxies"] = proxy_list
    self._save_net_config()
    self._verify_proxy_persisted()
    self._check_proxies()


def _verify_proxy_persisted(self):
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
    text = self._proxy_text.toPlainText().strip()
    proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
    if not proxy_list:
        QMessageBox.warning(self, "提示", "请先输入要测试的代理")
        return

    test_url = self._test_url_entry.text().strip()

    self._proxy_tree.clear()

    total = len(proxy_list)
    ok_count = [0]
    fail_count = [0]
    cancel_flag = [False]
    lock = threading.Lock()
    threads = []
    self._proxy_test_status.setText(f"测试中 0/{total} …")
    self._proxy_test_status.setStyleSheet(f"color: {C['warning']};")

    def test_one(proxy: str, item: QTreeWidgetItem):
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

        item.setText(0, proxy)
        item.setText(1, status)
        item.setText(2, latency)
        item.setText(3, country)
        item.setText(4, ip)
        item.setText(5, asn)
        item.setText(6, isp)

        with lock:
            if ok:
                ok_count[0] += 1
            else:
                fail_count[0] += 1
            done = ok_count[0] + fail_count[0]
            self._proxy_test_status.setText(f"测试中 {done}/{total} …")

    for proxy in proxy_list:
        item = QTreeWidgetItem()
        item.setText(0, proxy)
        item.setText(1, "⏳")
        item.setText(2, "—")
        self._proxy_tree.addTopLevelItem(item)
        t = threading.Thread(target=test_one, args=(proxy, item), daemon=True)
        t.start()
        threads.append(t)

    def _wait_all():
        for t in threads:
            t.join()
        ok_n, fail_n = ok_count[0], fail_count[0]
        status_text = f"完成: {ok_n} 可用"
        if fail_n:
            status_text += f", {fail_n} 失败"
        self._proxy_test_status.setText(status_text)
        self._proxy_test_status.setStyleSheet(
            f"color: {C['success']}; background: transparent;" if ok_n
            else f"color: {C['danger']}; background: transparent;"
        )

        if fail_n:
            failed = [proxy_list[i] for i in range(len(proxy_list))
                      if i < self._proxy_tree.topLevelItemCount()
                      and self._proxy_tree.topLevelItem(i).text(1) == "❌"]
            if failed:
                self._auto_remove_failed_proxies(failed)

    threading.Thread(target=_wait_all, daemon=True).start()


def _auto_remove_failed_proxies(self, failed_urls):
    text = self._proxy_text.toPlainText().strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    remaining = [ln for ln in lines if ln not in failed_urls]
    self._proxy_text.setPlainText("\n".join(remaining))

    get_bilibili_api().clear_proxies()
    for ps in remaining:
        get_bilibili_api().add_proxy({"http": ps, "https": ps})

    self._net_cfg["proxies"] = remaining
    self._save_net_config()

    masked = ", ".join(ProxyManager.mask_url(u) for u in failed_urls)
    msg = f"已自动移除 {len(failed_urls)} 个失效代理:\n{masked}"
    logger.info(msg)
    QMessageBox.information(self, "代理清理", msg)


def _sync_proxy_text_to_cfg(self):
    text = self._proxy_text.toPlainText().strip()
    self._net_cfg["proxies"] = [line.strip() for line in text.split("\n") if line.strip()]
