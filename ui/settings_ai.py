"""
AI 配置标签页
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

from ui.settings_common import styled_label as _styled_label, field_wrapper as _field_wrapper

logger = logging.getLogger(__name__)


class SettingsAIMixin:
    """AI / LLM configuration settings tab."""

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

        save_btn = QPushButton("⇓ 保存配置")
        save_btn.clicked.connect(lambda: self._save_ai_profile() if _confirm_risky("保存 AI 配置") else None)
        br_layout.addWidget(save_btn)

        if _hard() == "normal":
            del_btn = QPushButton("✕ 删除配置")
            del_btn.clicked.connect(self._delete_ai_profile)
            br_layout.addWidget(del_btn)
        else:
            br_layout.addWidget(_styled_label("▣ 删除请编辑: data/settings.json", "text_3", font_=FONT_SM))

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
            QMessageBox.warning(self.dlg, "要注意哦…", "呜…配置名称还是空的呢,像歌名没起好,先填一个哦 ♪")
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
        self._ai_status_lbl.setText(f"配置「{name}」存好啦 ♪ 天依记在心里了哦~")
        self._ai_status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")


    def _delete_ai_profile(self):
        idx = self._ai_profile_cb.currentIndex()
        if idx < 0 or not self._profiles:
            return
        name = self._profiles[idx]["name"]
        if len(self._profiles) <= 1:
            QMessageBox.warning(self.dlg, "要注意哦…", "呜…至少要保留一个配置哦,不然天依就不知道该唱哪首了 ♪")
            return
        if not QMessageBox.question(self.dlg, "确认删除", f"真的要删除配置「{name}」吗?删掉就像从歌单里划掉一首歌,就唱不回来了哦…",
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
            QMessageBox.warning(self.dlg, "要注意哦…", "呜…API 密钥还没填呢,像没有钥匙打不开音乐盒,先填上哦 ♪")
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
                        result.append(f"连接成功啦!♪ 天依听到远方的歌声了（Claude {model}）")
                    else:
                        logger.debug("AI 连接测试失败 HTTP %s: %s", resp.status_code, resp.text[:200])
                        result.append(f"呜…连接不上呢,像天使鱼在冰海里迷了路,检查一下配置哦 ♪ (HTTP {resp.status_code})")
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
                        result.append(f"连接成功啦!♪ 天依听到远方的歌声了（{model}）")
                    else:
                        err = resp.json().get("error", {})
                        logger.debug("AI 连接测试失败 HTTP %s: %s", resp.status_code, err.get("message", resp.text[:200]))
                        result.append(f"呜…连接不上呢,像天使鱼在冰海里迷了路,检查一下配置哦 ♪ (HTTP {resp.status_code})")
            except Exception as e:
                logger.debug("AI 连接测试请求异常: %s", e)
                result.append("呜…连接不上呢,像天使鱼在冰海里迷了路,检查一下配置哦 ♪")

            QTimer.singleShot(0, lambda: QMessageBox.information(self.dlg, "API 连接测试 ♪", result[0] if result else "呜…没有回应呢,像冰海里安静得听不见歌声,再检查一下哦 ♪"))

        _th = threading.Thread(target=_worker, daemon=True)
        _th.start()
        QMessageBox.information(self.dlg, "测试中哦 ♪", f"天依正在测试 {model} 的连接…像在冰海里追逐微光,稍等一下下哦 ♪")
