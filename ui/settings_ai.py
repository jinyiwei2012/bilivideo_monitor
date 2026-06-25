"""
AI 配置标签页

Mixin functions for SettingsWindow.
"""

import os
import logging
import webbrowser
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit, QCheckBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QTabWidget, QFrame, QMessageBox,
    QScrollArea, QSizePolicy, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QGridLayout, QProgressBar, QSplitter, QDialog, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_BOLD, FONT_SM, FONT_MONO, project_path
from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import get_weight_manager
from utils.update_checker import _s, _hard, _train, _confirm_risky
from ui.scrollable_frame import ScrollableFrame

logger = logging.getLogger(__name__)


# ═══════════════ 辅助函数 ════════════════════════════════


def _styled_label(text, color_key="text_2", bold=False, font_=FONT):
    lbl = QLabel(text)
    style = f"color: {C[color_key]}; background: transparent;"
    if bold:
        style += " font-weight: bold;"
    lbl.setStyleSheet(style)
    lbl.setFont(font_)
    return lbl


def _field_wrapper(parent, label_text):
    """一行：标签 + 输入框"""
    row = QWidget(parent)
    row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 3, 0, 3)
    lbl = _styled_label(label_text, font_=FONT)
    lbl.setFixedWidth(120)
    rl.addWidget(lbl)
    entry = QLineEdit()
    entry.setMinimumWidth(240)
    entry.setStyleSheet(
        f"background-color: {C['bg_base']}; color: {C['text_1']}; "
        f"border: 1px solid {C['border']}; border-radius: 2px; padding: 2px 4px;"
    )
    entry.setFont(FONT)
    rl.addWidget(entry)
    rl.addStretch()
    return entry


# ═══════════════ AI 配置 ═══════════════════════════════


def _build_ai_tab(self, nb):
    page = QWidget()
    page.setStyleSheet(f"background-color: {C['bg_base']};")
    nb.addTab(page, "  AI配置  ")
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(0, 0, 0, 0)

    sec = self._section(page, "LLM 配置管理")
    sec_layout = sec.layout()
    ai_cfg = self._cfg.get("ai", {})

    sel_row = QWidget()
    sel_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    sr_layout = QHBoxLayout(sel_row)
    sr_layout.setContentsMargins(0, 0, 0, 8)

    sr_layout.addWidget(_styled_label("当前配置:"))
    self._ai_profile_cb = QComboBox()
    self._ai_profile_cb.setMinimumWidth(280)
    self._ai_profile_cb.currentIndexChanged.connect(self._on_ai_profile_selected)
    sr_layout.addWidget(self._ai_profile_cb)
    sr_layout.addStretch()
    sec_layout.addWidget(sel_row)

    profiles = ai_cfg.get("profiles", [])
    if not profiles:
        old_key = ai_cfg.get("api_key", "")
        old_ep = ai_cfg.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
        old_mdl = ai_cfg.get("model", "gpt-4o-mini")
        if old_key:
            profiles.append({"name": "默认配置", "api_key": old_key, "endpoint": old_ep, "model": old_mdl})
    if not profiles:
        profiles.append({
            "name": "默认配置",
            "api_key": "",
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        })
    self._profiles = profiles
    selected_name = ai_cfg.get("selected_profile", profiles[0]["name"])
    self._profile_names = [p["name"] for p in profiles]
    self._ai_profile_cb.addItems(self._profile_names)
    if selected_name in self._profile_names:
        self._ai_profile_cb.setCurrentText(selected_name)

    detail = QWidget()
    detail.setStyleSheet(
        f"background-color: {C['bg_elevated']}; "
        f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
    )
    detail_layout = QVBoxLayout(detail)
    detail_layout.setContentsMargins(10, 10, 10, 10)

    detail_title = _styled_label("配置详情", bold=True)
    detail_title.setStyleSheet(detail_title.styleSheet() + " font-size: 8pt;")
    detail_layout.addWidget(detail_title)

    self._ai_name_entry = _field_wrapper(detail, "配置名称")
    self._ai_key_entry = _field_wrapper(detail, "API密钥")
    self._ai_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
    self._ai_endpoint_entry = _field_wrapper(detail, "接口地址")
    self._ai_model_entry = _field_wrapper(detail, "模型名称")
    detail_layout.addStretch()
    sec_layout.addWidget(detail)

    btn_row = QWidget()
    btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
    br_layout = QHBoxLayout(btn_row)
    br_layout.setContentsMargins(0, 6, 0, 0)

    save_btn = QPushButton("💾 保存配置")
    save_btn.clicked.connect(lambda: self._save_ai_profile() if _confirm_risky("保存 AI 配置") else None)
    br_layout.addWidget(save_btn)

    if _hard() == "normal":
        del_btn = QPushButton("🗑 删除配置")
        del_btn.clicked.connect(self._delete_ai_profile)
        br_layout.addWidget(del_btn)
    else:
        br_layout.addWidget(_styled_label("📁 删除请编辑: data/settings.json", "text_3", font_=FONT_SM))

    new_btn = QPushButton("+ 新增")
    new_btn.clicked.connect(self._new_ai_profile)
    br_layout.addWidget(new_btn)
    br_layout.addStretch()
    sec_layout.addWidget(btn_row)

    # 快速填入行
    preset_row = QWidget()
    preset_row.setStyleSheet(f"background-color: {C['bg_base']};")
    pr_layout = QHBoxLayout(preset_row)
    pr_layout.setContentsMargins(0, 0, 0, 0)
    pr_layout.addWidget(_styled_label("快速填入:", "text_2"))

    presets = {
        "DeepSeek": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
        "OpenAI": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
        "Claude": ("https://api.anthropic.com/v1/messages", "claude-sonnet-4-6"),
        "SiliconFlow": ("https://api.siliconflow.cn/v1/chat/completions", "deepseek-ai/DeepSeek-V3"),
    }
    for name, (ep, mdl) in presets.items():
        btn = QPushButton(name)
        btn.clicked.connect(lambda checked, ep=ep, mdl=mdl: (
            self._ai_endpoint_entry.setText(ep),
            self._ai_model_entry.setText(mdl),
        ))
        pr_layout.addWidget(btn)

    test_btn = QPushButton("测试连接")
    test_btn.clicked.connect(self._test_ai_connection)
    pr_layout.addWidget(test_btn)
    pr_layout.addStretch()
    page_layout.addWidget(preset_row)

    self._ai_status_lbl = _styled_label("", "text_3", font_=FONT_SM)
    page_layout.addWidget(self._ai_status_lbl)
    page_layout.addStretch()

    self._on_ai_profile_selected()


def _on_ai_profile_selected(self):
    idx = self._ai_profile_cb.currentIndex()
    if idx < 0 or idx >= len(self._profiles):
        return
    p = self._profiles[idx]
    self._ai_name_entry.setText(p.get("name", ""))
    self._ai_key_entry.setText(p.get("api_key", ""))
    self._ai_endpoint_entry.setText(p.get("endpoint", ""))
    self._ai_model_entry.setText(p.get("model", ""))


def _save_ai_profile(self):
    name = self._ai_name_entry.text().strip()
    if not name:
        QMessageBox.warning(self.dlg, "提示", "配置名称不能为空")
        return
    api_key = self._ai_key_entry.text().strip()
    endpoint = self._ai_endpoint_entry.text().strip() or "https://api.openai.com/v1/chat/completions"
    model = self._ai_model_entry.text().strip() or "gpt-4o-mini"

    found = False
    for p in self._profiles:
        if p["name"] == name:
            p.update({"api_key": api_key, "endpoint": endpoint, "model": model})
            found = True
            break
    if not found:
        self._profiles.append({"name": name, "api_key": api_key, "endpoint": endpoint, "model": model})
        self._ai_profile_cb.addItem(name)

    self._ai_profile_cb.setCurrentText(name)
    self._ai_status_lbl.setText(f"配置「{name}」已保存")
    self._ai_status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")


def _delete_ai_profile(self):
    idx = self._ai_profile_cb.currentIndex()
    if idx < 0 or not self._profiles:
        return
    name = self._profiles[idx]["name"]
    if len(self._profiles) <= 1:
        QMessageBox.warning(self.dlg, "提示", "至少保留一个配置")
        return
    if not QMessageBox.question(self.dlg, "确认删除", f"确定删除配置「{name}」？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
        return
    self._profiles = [p for p in self._profiles if p["name"] != name]
    self._ai_profile_cb.clear()
    self._ai_profile_cb.addItems([p["name"] for p in self._profiles])
    self._on_ai_profile_selected()


def _new_ai_profile(self):
    self._ai_name_entry.setText("")
    self._ai_key_entry.setText("")
    self._ai_endpoint_entry.setText("https://api.openai.com/v1/chat/completions")
    self._ai_model_entry.setText("gpt-4o-mini")


def _test_ai_connection(self):
    api_key = self._ai_key_entry.text().strip()
    endpoint = self._ai_endpoint_entry.text().strip()
    model = self._ai_model_entry.text().strip()

    if not api_key:
        QMessageBox.warning(self.dlg, "提示", "请先填写 API 密钥")
        return
    if not endpoint:
        endpoint = "https://api.openai.com/v1/chat/completions"
    if not model:
        model = "gpt-4o-mini"

    import threading

    result = []

    def _worker():
        try:
            is_claude = "anthropic.com" in endpoint
            import requests as req

            if is_claude:
                resp = req.post(
                    endpoint,
                    headers={
                        "x-api-key": api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": model,
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "回复OK即可"}],
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    result.append(f"✅ 连接成功（Claude {model}）")
                else:
                    result.append(f"❌ HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                resp = req.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "回复OK即可"}],
                        "max_tokens": 10,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    result.append(f"✅ 连接成功（{model}）")
                else:
                    err = resp.json().get("error", {})
                    result.append(f"❌ HTTP {resp.status_code}: {err.get('message', resp.text[:200])}")
        except Exception as e:
            result.append(f"❌ 请求失败: {e}")

        QTimer.singleShot(0, lambda: QMessageBox.information(self.dlg, "API 连接测试", result[0] if result else "❌ 无响应"))

    _th = threading.Thread(target=_worker, daemon=True)
    _th.start()
    QMessageBox.information(self.dlg, "测试中", f"正在测试 {model} 连接...\n请稍候")

