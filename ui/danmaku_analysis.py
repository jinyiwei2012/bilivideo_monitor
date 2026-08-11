"""
弹幕/评论分析窗口 — 情绪饼图、关键词标签云、高频列表
支持从监控列表选择、自动保存、LLM 深度分析
"""

import json
import logging
import math
import os
from typing import List, Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit, QTabWidget, QFrame,
    QMessageBox, QSpinBox, QProgressBar, QCheckBox, QSizePolicy,
    QScrollArea, QListWidget, QListWidgetItem, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QColor, QBrush, QPen, QFontMetrics

from ui.theme import C
from ui.dialog_base import DialogBase
from ui.invoker import invoke

logger = logging.getLogger(__name__)


def _sty(text, color_key="text_2", bold=False, font_=None):
    lbl = QLabel(text)
    style = f"color: {C.get(color_key, color_key)}; background: transparent;"
    if bold:
        style += " font-weight: bold;"
    lbl.setStyleSheet(style)
    if font_:
        lbl.setFont(font_)
    return lbl


class DanmakuAnalysisWindow:
    """
    弹幕/评论分析窗口
    功能：抓取弹幕或评论，进行情感分析、关键词提取、时间分布、LLM 深度分析
    """

    def __init__(self, parent=None, api=None, gui=None):
        self.dlg = DialogBase(parent, "弹幕/评论分析 ♪", modal=False)
        self.dlg.resize(round(self.dlg.width() * 0.50), round(self.dlg.height() * 0.72))
        self.api = api  # B 站 API 实例
        self.gui = gui  # 主 GUI 实例
        self._texts: List[str] = []  # 抓取到的文本列表
        self._current_bvid = ""  # 当前分析的 BV 号
        self._setup_ui()

    def _setup_ui(self):
        """构建界面：数据源选择 / 输入卡片、情绪图表、关键词、高频列表、LLM 分析标签页"""
        self.dlg.header("弹幕/评论分析 ♪", "抓取弹幕与评论，进行情绪分析与关键词提取哦 ♪")

        # ── 输入卡片 ──
        sec = self.dlg.section(title="数据源 ♪", padding=8)
        sec_layout = sec.layout()

        # 第一行：从监控列表选择
        if self.gui and self.gui.monitored_videos:
            row0 = QWidget()
            row0.setStyleSheet(f"background-color: {C['bg_elevated']};")
            r0_layout = QHBoxLayout(row0)
            r0_layout.setContentsMargins(0, 0, 0, 4)

            r0_layout.addWidget(_sty("监控列表:", "text_2", font_=QFont("Microsoft YaHei UI", 10)))
            self._monitor_cb = QComboBox()
            self._monitor_cb.setMinimumWidth(300)
            for v in self.gui.monitored_videos:
                self._monitor_cb.addItem(f"{v.get('bvid', '')}  {v.get('title', '')[:30]}")
            if self._monitor_cb.count() > 0:
                self._monitor_cb.setCurrentIndex(0)
            r0_layout.addWidget(self._monitor_cb)
            r0_layout.addSpacing(8)

            fetch_btn = QPushButton("♬ 抓取这个视频 ♪")
            fetch_btn.clicked.connect(self._from_monitor_and_fetch)
            r0_layout.addWidget(fetch_btn)
            r0_layout.addStretch()
            sec_layout.addWidget(row0)

        # 第二行：手动输入 BV + 模式选择（弹幕/评论）+ 数量限制
        row1 = QWidget()
        row1.setStyleSheet(f"background-color: {C['bg_elevated']};")
        r1_layout = QHBoxLayout(row1)
        r1_layout.setContentsMargins(0, 0, 0, 0)

        r1_layout.addWidget(_sty("BV号:", "text_2", font_=QFont("Microsoft YaHei UI", 10)))
        self._bv_entry = QLineEdit()
        self._bv_entry.setFixedWidth(160)
        self._bv_entry.setFont(QFont("Consolas", 10))
        self._bv_entry.setStyleSheet(
            f"background-color: {C['bg_base']}; color: {C['text_1']}; "
            f"border: 1px solid {C['border']}; border-radius: 2px; padding: 2px;"
        )
        r1_layout.addWidget(self._bv_entry)
        r1_layout.addSpacing(10)

        self._mode_danmaku = QRadioButton("弹幕")
        self._mode_comment = QRadioButton("评论")
        self._mode_danmaku.setChecked(True)
        self._mode_group = QButtonGroup()
        self._mode_group.addButton(self._mode_danmaku, 1)
        self._mode_group.addButton(self._mode_comment, 2)
        self._mode_group.buttonClicked.connect(lambda: self._update_hint())
        r1_layout.addWidget(self._mode_danmaku)
        r1_layout.addWidget(self._mode_comment)

        r1_layout.addSpacing(10)
        r1_layout.addWidget(_sty("数量:", "text_2", font_=QFont("Microsoft YaHei UI", 10)))
        self._limit_cb = QComboBox()
        self._limit_cb.addItems(["全量", "50", "100", "500", "1000", "2000"])
        self._limit_cb.setFixedWidth(80)
        r1_layout.addWidget(self._limit_cb)

        self._fetch_btn = QPushButton("抓取并分析 ♪")
        self._fetch_btn.clicked.connect(self._analyze)
        r1_layout.addWidget(self._fetch_btn)
        r1_layout.addStretch()
        sec_layout.addWidget(row1)

        # 第三行：操作按钮（保存 / LLM 深度分析）
        row2 = QWidget()
        row2.setStyleSheet(f"background-color: {C['bg_elevated']};")
        r2_layout = QHBoxLayout(row2)
        r2_layout.setContentsMargins(0, 4, 0, 0)

        self._save_btn = QPushButton("⇓ 保存到本地 ♪")
        self._save_btn.clicked.connect(lambda: self._save_to_file())
        self._save_btn.setEnabled(False)
        r2_layout.addWidget(self._save_btn)

        self._llm_btn = QPushButton("◉ LLM深度分析 ♪")
        self._llm_btn.clicked.connect(self._llm_analysis)
        self._llm_btn.setEnabled(False)
        r2_layout.addWidget(self._llm_btn)

        r2_layout.addStretch()
        sec_layout.addWidget(row2)

        self._status_lbl = _sty("", "text_2", font_=QFont("Microsoft YaHei UI", 9))
        sec_layout.addWidget(self._status_lbl)

        # 内容区：情绪饼图(左) + 关键词(右)
        mid = QWidget()
        mid.setStyleSheet(f"background-color: {C['bg_surface']};")
        mid_layout = QHBoxLayout(mid)
        mid_layout.setContentsMargins(24, 10, 24, 0)

        # 左：情绪饼图
        self._left_frame = QWidget()
        self._left_frame.setStyleSheet(
            f"background-color: {C['bg_elevated']}; "
            f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
        )
        left_layout = QVBoxLayout(self._left_frame)
        left_layout.setContentsMargins(6, 4, 6, 6)

        pie_title = _sty("情绪分布 ♪", "text_2", bold=True, font_=QFont("Microsoft YaHei UI", 8))
        left_layout.addWidget(pie_title)

        self._pie_widget = _PieWidget()
        self._pie_widget.setMinimumSize(200, 180)
        left_layout.addWidget(self._pie_widget, stretch=1)
        mid_layout.addWidget(self._left_frame, stretch=1)

        # 右：高频关键词
        self._right_frame = QWidget()
        self._right_frame.setStyleSheet(
            f"background-color: {C['bg_elevated']}; "
            f"border: 1px solid {C['border_sub']}; border-radius: 2px;"
        )
        right_layout = QVBoxLayout(self._right_frame)
        right_layout.setContentsMargins(6, 4, 6, 6)

        kw_title = _sty("高频关键词 ♪", "text_2", bold=True, font_=QFont("Microsoft YaHei UI", 8))
        right_layout.addWidget(kw_title)

        self._kw_display = QLabel("")
        self._kw_display.setWordWrap(True)
        self._kw_display.setStyleSheet(
            f"background-color: {C['bg_base']}; color: {C['text_1']}; "
            f"padding: 8px; border: none;"
        )
        self._kw_display.setFont(QFont("Microsoft YaHei UI", 10))
        right_layout.addWidget(self._kw_display, stretch=1)
        mid_layout.addWidget(self._right_frame, stretch=1)

        # LLM 摘要覆盖层（初始隐藏）
        self._llm_summary = QTextEdit()
        self._llm_summary.setReadOnly(True)
        self._llm_summary.setStyleSheet(
            f"background-color: {C['bg_elevated']}; color: {C['text_1']}; "
            f"padding: 8px; border: 1px solid {C['border_sub']}; border-radius: 2px;"
        )
        self._llm_summary.setFont(QFont("Microsoft YaHei UI", 10))
        self._llm_summary.hide()
        mid_layout.addWidget(self._llm_summary, stretch=1)

        # 添加到主 layout
        main_layout = self.dlg.container.layout()
        if main_layout:
            main_layout.addWidget(mid, stretch=1)

        # 底部：TabWidget 切换 高频列表 / 时间分布 / LLM分析
        self._bottom_tabs = QTabWidget()
        self._bottom_tabs.setStyleSheet(f"background-color: {C['bg_surface']};")

        # ── 页1：高频列表（带情绪标注） ──
        freq_page = QWidget()
        freq_page.setStyleSheet(f"background-color: {C['bg_base']};")
        freq_layout = QVBoxLayout(freq_page)

        list_header = QWidget()
        list_header.setStyleSheet(f"background-color: {C['bg_base']};")
        lh_layout = QHBoxLayout(list_header)
        lh_layout.setContentsMargins(0, 0, 0, 0)
        lh_layout.addWidget(_sty("高频弹幕/评论 ♪", "text_2", bold=True, font_=QFont("Microsoft YaHei UI", 8)))
        self._count_lbl = _sty("", "text_3", font_=QFont("Microsoft YaHei UI", 9))
        lh_layout.addWidget(self._count_lbl)
        lh_layout.addStretch()
        freq_layout.addWidget(list_header)

        self._list_tree = QTreeWidget()
        self._list_tree.setHeaderLabels(["序号", "内容", "情绪"])
        self._list_tree.setColumnWidth(0, 40)
        self._list_tree.setColumnWidth(1, 400)
        self._list_tree.setColumnWidth(2, 60)
        self._list_tree.setRootIsDecorated(False)
        freq_layout.addWidget(self._list_tree, stretch=1)

        self._bottom_tabs.addTab(freq_page, "  高频弹幕/评论 ♪  ")

        # ── 页2：时间分布柱状图 ──
        time_page = QWidget()
        time_page.setStyleSheet(f"background-color: {C['bg_base']};")
        time_layout = QVBoxLayout(time_page)
        self._time_widget = _TimeHistogramWidget()
        self._time_widget.setMinimumHeight(120)
        time_layout.addWidget(self._time_widget, stretch=1)
        self._bottom_tabs.addTab(time_page, "  ◧ 时间分布 ♪  ")

        # ── 页3：LLM分析结果 ──
        llm_page = QWidget()
        llm_page.setStyleSheet(f"background-color: {C['bg_base']};")
        llm_layout = QVBoxLayout(llm_page)
        self._llm_text = QTextEdit()
        self._llm_text.setReadOnly(True)
        self._llm_text.setStyleSheet(
            f"background-color: {C['bg_base']}; color: {C['text_1']}; "
            f"padding: 10px; border: none;"
        )
        self._llm_text.setFont(QFont("Microsoft YaHei UI", 10))
        llm_layout.addWidget(self._llm_text, stretch=1)
        self._bottom_tabs.addTab(llm_page, "  ◉ LLM分析 ♪  ")

        if main_layout:
            main_layout.addWidget(self._bottom_tabs, stretch=2)

        self._update_hint()

    def _update_hint(self):
        """更新操作提示信息"""
        hint = "输入视频BV号，抓取弹幕分析情感倾向与高频内容哦 ♪"
        self._status_lbl.setText(hint)

    def _get_mode(self) -> str:
        return "danmaku" if self._mode_danmaku.isChecked() else "comment"

    def _get_limit(self) -> int:
        v = self._limit_cb.currentText()
        if v == "全量":
            return 0
        return int(v)

    def _fetch_danmaku(self, bvid, limit):
        """抓取弹幕数据，返回 (文本列表, 错误信息)。"""
        if self.gui and bvid in self.gui.video_dbs:
            try:
                video_db = self.gui.video_dbs[bvid]
                records = video_db.get_danmaku_records(limit=0)
                if records:
                    texts = [r.get("content", "") for r in records if r.get("content")]
                    if limit > 0:
                        texts = texts[:limit]
                    self._status_lbl.setText(f"从本地数据库加载了 {len(texts)} 条弹幕哦 ♪")
                    return texts, None
            except Exception:
                pass

        info = self.api.get_video_info(bvid)
        if not info:
            return None, "呜…获取视频信息失败啦"
        cid = info.get("cid", 0)
        if not cid:
            return None, "呜…无法获取cid呢"
        danmaku = self.api.get_video_danmaku(cid)
        if not danmaku:
            return None, "呜…没有获取到弹幕呢…♪"
        texts = [d["text"] for d in danmaku if d.get("text")]
        if limit > 0:
            texts = texts[:limit]
        return texts, None

    def _fetch_comments(self, bvid, limit):
        """抓取评论数据，返回 (文本列表, 错误信息)"""
        info = self.api.get_video_info(bvid)
        if not info:
            return None, "呜…获取视频信息失败啦"
        aid = info.get("aid", 0)
        if not aid:
            return None, "呜…无法获取aid呢"
        comments = self.api.get_video_comments(aid, limit=limit if limit > 0 else 0)
        if not comments:
            return None, "呜…没有获取到评论呢…♪"
        texts = [c["content"] for c in comments if c.get("content")]
        return texts, None

    def _analyze(self):
        """抓取并分析弹幕/评论"""
        bvid = self._bv_entry.text().strip()
        if not bvid:
            QMessageBox.warning(self.dlg, "要注意哦…", "要先输入BV号哦…♪")
            return

        if not self.api:
            QMessageBox.critical(self.dlg, "呜…出错了", "呜…API 不可用呢…♪")
            return

        limit = self._get_limit()

        self._fetch_btn.setEnabled(False)
        self._status_lbl.setText("正在抓取数据哦…♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")

        try:
            mode = self._get_mode()
            texts = None

            if mode == "danmaku":
                texts, err = self._fetch_danmaku(bvid, limit)
            else:
                texts, err = self._fetch_comments(bvid, limit)

            if err:
                self._status_lbl.setText(err)
                self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
                return

            self._texts = texts
            self._current_bvid = bvid
            limit_label = f"（限制 {limit} 条）" if limit > 0 else "（全量）"
            self._status_lbl.setText(f"抓取成功啦 ♪ 共 {len(texts)} 条{mode} {limit_label}")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")

            self._display_results(texts)
            self._save_btn.setEnabled(True)
            self._llm_btn.setEnabled(True)
            self._save_to_file(silent=True)
            self._load_local_llm_result()
        except Exception as e:
            logger.error("弹幕/评论分析失败", exc_info=True)
            self._status_lbl.setText("呜…分析失败啦，请稍后再试哦 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("ERROR", "弹幕分析失败啦…♪")
        finally:
            self._fetch_btn.setEnabled(True)

    def _display_results(self, texts: List[str]):
        """展示分析结果：情绪饼图、关键词标签云、时间分布、高频列表"""
        self._restore_charts()
        from utils.sentiment_analyzer import (
            analyze_sentiment,
            extract_keywords,
            generate_word_freq,
        )

        sentiment = analyze_sentiment(texts)
        self._draw_pie(sentiment)

        keywords = extract_keywords(texts, top_n=30)
        self._display_keywords(keywords)

        freq = generate_word_freq(texts)

        self._draw_time_distribution(texts)

        self._list_tree.clear()

        from utils.sentiment_analyzer import _tokenize, _POSITIVE_WORDS, _NEGATIVE_WORDS, _INTENSIFIERS, _NEGATORS

        for i, text in enumerate(texts[:50]):
            tokens = _tokenize(text.strip())
            score = 0.0
            for j, token in enumerate(tokens):
                weight = 1.0
                if j > 0 and tokens[j - 1] in _INTENSIFIERS:
                    weight *= 1.5
                if j > 0 and tokens[j - 1] in _NEGATORS:
                    weight *= -1.0
                if token in _POSITIVE_WORDS:
                    score += weight
                elif token in _NEGATIVE_WORDS:
                    score -= weight
            if score > 0.5:
                mood = "积极"
            elif score < -0.5:
                mood = "消极"
            else:
                mood = "中性"
            item = QTreeWidgetItem([str(i + 1), text[:60], mood])
            self._list_tree.addTopLevelItem(item)

        self._count_lbl.setText(f"共 {len(texts)} 条，先显示前 {min(50, len(texts))} 条哦 ♪")

    def _from_monitor_and_fetch(self):
        """从监控列表选择后直接填入 BV 号并自动抓取分析"""
        bvid = self._monitor_cb.currentText().split()[0]
        self._bv_entry.setText(bvid)
        self._analyze()

    def _save_to_file(self, silent: bool = False):
        """保存弹幕/评论到 BV 对应文件夹下的 danmaku 子目录"""
        if not self._texts or not self._current_bvid:
            if not silent:
                QMessageBox.information(self.dlg, "知道啦 ♪", "还没有数据可以保存呢…♪")
            return

        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        os.makedirs(bv_dir, exist_ok=True)

        mode = self._get_mode()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{mode}_{ts}.json"
        filepath = os.path.join(bv_dir, filename)

        data = {
            "bvid": self._current_bvid,
            "mode": mode,
            "count": len(self._texts),
            "timestamp": datetime.now().isoformat(),
            "texts": self._texts,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if not silent:
            QMessageBox.information(self.dlg, "保存成功啦 ♪", f"已保存 {len(self._texts)} 条{mode}\n{filepath}")
        else:
            self._status_lbl.setText(f"自动保存了 {len(self._texts)} 条 → {filepath} ♪")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")

    def _llm_analysis(self):
        """使用 LLM 深度分析弹幕/评论"""
        if not self._texts:
            QMessageBox.information(self.dlg, "知道啦 ♪", "要先抓取数据哦…♪")
            return

        if self._check_llm_existing_result():
            return

        config = self._load_llm_api_config()
        if config is None:
            return
        api_key, endpoint, model = config

        self._prepare_llm_ui()

        mode = self._get_mode()
        prompt = self._prepare_llm_prompt(mode)

        import threading

        threading.Thread(target=self._llm_worker, args=(api_key, endpoint, model, mode, prompt), daemon=True).start()

    def _check_llm_existing_result(self):
        """检查本地已有 LLM 分析结果文件"""
        from config import DATA_DIR

        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        mode = self._get_mode()
        local_files = []
        if os.path.isdir(bv_dir):
            local_files = [
                f for f in os.listdir(bv_dir) if f.startswith("llm_") and f.endswith(".json") and f"_{mode}_" in f
            ]
        if local_files:
            reply = QMessageBox.question(
                self.dlg, "要注意哦…",
                f"已经有 LLM {mode}分析结果啦，要重新调用 API 分析吗？\n选「否」就查看已有结果哦 ♪",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._load_local_llm_result()
                return True
        return False

    def _load_llm_api_config(self):
        """加载 LLM API 配置"""
        try:
            from config import get_active_ai_profile
            profile = get_active_ai_profile()
            api_key = profile.get("api_key", "")
            endpoint = profile.get("endpoint", "") or "https://api.openai.com/v1/chat/completions"
            model = profile.get("model", "gpt-4o-mini")
        except Exception:
            api_key = ""

        if not api_key:
            QMessageBox.warning(self.dlg, "要注意哦…", "呜…还没有配置 LLM API 密钥呢，去「设置 → AI配置」配置一下吧 ♪")
            return None
        return (api_key, endpoint, model)

    def _prepare_llm_ui(self):
        """准备 LLM 分析的 UI 状态"""
        self._llm_btn.setEnabled(False)
        self._status_lbl.setText("LLM 分析中哦…♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")

        self._llm_text.setHtml("LLM 分析请求已发送，请稍等哦…♪")

    def _prepare_llm_prompt(self, mode):
        sample = self._texts[:100]
        prompt = (
            f"你是一个B站视频{mode}分析助手。分析以下{len(sample)}条{mode}数据，"
            f"给出分点总结：\n"
            f"1. 整体情绪倾向（积极/消极/中性比例）\n"
            f"2. 主要讨论话题\n"
            f"3. 高频关键词\n"
            f"4. 代表性评论摘录\n"
            f"5. 总结性建议\n\n"
            f"{mode}数据：\n"
        )
        for i, t in enumerate(sample[:50], 1):
            prompt += f"{i}. {t}\n"
        if self.gui and hasattr(self.gui, "log_panel"):
            self.gui.log_panel.add_log(
                "INFO", f"LLM分析请求已发送（{self._current_bvid}，{mode}，{len(self._texts)}条）"
            )
        return prompt

    def _llm_worker(self, api_key, endpoint, model, mode, prompt):
        result_text = self._call_llm_api(api_key, endpoint, model, prompt)
        invoke(lambda: self._update_llm_ui(result_text, mode, model))

    def _call_llm_api(self, api_key, endpoint, model, prompt):
        """调用 LLM API"""
        try:
            import requests as req
            is_claude = "anthropic.com" in endpoint
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
                        "max_tokens": 2048,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content_list = data.get("content", [])
                    return content_list[0].get("text", "") if content_list else ""
                else:
                    logger.warning("Claude LLM API 请求失败: HTTP %s, %s", resp.status_code, resp.text[:500])
                    return f"呜…API 请求失败啦 (HTTP {resp.status_code})，请稍后再试哦 ♪"
            else:
                resp = req.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "你是一个专业的数据分析助手，擅长从弹幕和评论中提取洞察。"},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 2048,
                        "temperature": 0.5,
                    },
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if not result:
                        logger.warning("LLM API 返回空结果: %s", str(data)[:500])
                        return "呜…API 没有返回内容呢，请稍后再试哦 ♪"
                    return result
                else:
                    logger.warning("LLM API 请求失败: HTTP %s, %s", resp.status_code, resp.text[:500])
                    return f"呜…API 请求失败啦 (HTTP {resp.status_code})，请稍后再试哦 ♪"
        except Exception as e:
            logger.error("LLM 深度分析异常", exc_info=True)
            return "呜…LLM 分析出了点问题，请稍后再试哦 ♪"

    def _update_llm_ui(self, result_text, mode, model):
        """主线程：更新 UI 显示 LLM 分析结果"""
        title = f"◎ LLM {mode}深度分析报告\n"
        meta = f"BV: {self._current_bvid}  |  数据: {len(self._texts)}条  |  模型: {model}\n\n"
        html = f"""
        <h2 style="color: {C['bilibili']};">{title}</h2>
        <p style="color: {C['text_3']};">{meta}</p>
        <pre style="color: {C['text_1']}; font-family: 'Microsoft YaHei UI'; font-size: 10pt;">{result_text}</pre>
        """
        self._llm_text.setHtml(html)
        self._llm_btn.setEnabled(True)
        self._show_llm_summary(result_text, mode, model)
        self._bottom_tabs.setCurrentIndex(2)
        self._status_lbl.setText("LLM 分析完成啦 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        if self.gui and hasattr(self.gui, "log_panel"):
            self.gui.log_panel.add_log("INFO", f"LLM分析完成（{self._current_bvid}，{mode}）")
        self._save_llm_result(result_text, mode, model)

    def _save_llm_result(self, result_text, mode, model):
        """保存 LLM 分析结果到文件"""
        try:
            from config import DATA_DIR
            bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
            os.makedirs(bv_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(bv_dir, f"llm_{mode}_{ts}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "bvid": self._current_bvid,
                        "mode": mode,
                        "model": model,
                        "data_count": len(self._texts),
                        "timestamp": datetime.now().isoformat(),
                        "analysis": result_text,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            self._status_lbl.setText(f"LLM 分析完成啦 ♪ 已保存 → {filepath}")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        except Exception as e:
            logger.warning("保存LLM分析结果失败", exc_info=True)
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("WARNING", "保存LLM分析结果失败啦…♪")

    def _load_local_llm_result(self):
        """加载本地已有的 LLM 分析结果"""
        if not self._current_bvid:
            return
        from config import DATA_DIR
        bv_dir = os.path.join(DATA_DIR, self._current_bvid, "danmaku")
        if not os.path.isdir(bv_dir):
            return
        files = [f for f in os.listdir(bv_dir) if f.startswith("llm_") and f.endswith(".json")]
        if not files:
            return
        mode = self._get_mode()
        mode_files = [f for f in files if f"_{mode}_" in f]
        if not mode_files:
            return
        latest = max(mode_files, key=lambda f: os.path.getmtime(os.path.join(bv_dir, f)))
        try:
            with open(os.path.join(bv_dir, latest), "r", encoding="utf-8") as f:
                data = json.load(f)
            result_text = data.get("analysis", "")
            model = data.get("model", "unknown")
            if result_text:
                self._show_llm_summary(result_text, mode, model)
                title = f"◎ LLM {mode}深度分析报告\n"
                meta = f"BV: {self._current_bvid}  |  数据: {data.get('data_count', 0)}条  |  模型: {model}\n\n"
                html = f"""
                <h2 style="color: {C['bilibili']};">{title}</h2>
                <p style="color: {C['text_3']};">{meta}</p>
                <pre style="color: {C['text_1']}; font-family: 'Microsoft YaHei UI'; font-size: 10pt;">{result_text}</pre>
                """
                self._llm_text.setHtml(html)
                self._status_lbl.setText(f"已加载本地 LLM 分析结果哦（{latest}）♪")
                self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
                QTimer.singleShot(100, lambda: self._bottom_tabs.setCurrentIndex(2))
                self._llm_btn.setEnabled(True)
        except Exception as e:
            logger.warning("加载本地LLM分析结果失败", exc_info=True)
            if self.gui and hasattr(self.gui, "log_panel"):
                self.gui.log_panel.add_log("WARNING", "加载本地LLM分析结果失败啦…♪")

    def _show_llm_summary(self, result_text: str, mode: str, model: str):
        """在上半区显示 LLM 分析结果"""
        self._left_frame.hide()
        self._right_frame.hide()
        title = f"◎ LLM {mode}深度分析报告\n"
        meta = f"BV: {self._current_bvid}  |  数据: {len(self._texts)}条  |  模型: {model}\n\n"
        html = f"""
        <h2 style="color: {C['bilibili']};">{title}</h2>
        <p style="color: {C['text_3']};">{meta}</p>
        <pre style="color: {C['text_1']}; font-family: 'Microsoft YaHei UI'; font-size: 10pt;">{result_text}</pre>
        """
        self._llm_summary.setHtml(html)
        self._llm_summary.show()

    def _restore_charts(self):
        """恢复显示情绪饼图和关键词"""
        self._llm_summary.hide()
        self._left_frame.show()
        self._right_frame.show()

    def _draw_pie(self, sentiment: dict):
        """绘制情绪分布饼图"""
        self._pie_widget.set_data(sentiment)

    def _draw_time_distribution(self, texts: list):
        """绘制弹幕时间分布柱状图"""
        self._time_widget.set_data(texts)

    def _display_keywords(self, keywords: list):
        """展示关键词标签云"""
        if not keywords:
            self._kw_display.setText("还没有关键词呢…♪")
            return
        max_score = max(s for _, s in keywords)
        from utils.sentiment_analyzer import _POSITIVE_WORDS, _NEGATIVE_WORDS

        html_parts = []
        for word, score in keywords[:40]:
            ratio = score / max_score if max_score > 0 else 0
            size = 14 - int(ratio * 5)
            size = max(9, min(14, size))
            if word in _POSITIVE_WORDS:
                color = C["success"]
            elif word in _NEGATIVE_WORDS:
                color = C["danger"]
            else:
                color = C["text_1"]
            html_parts.append(f'<span style="font-size: {size}pt; color: {color};"> {word} </span>')
        self._kw_display.setText("".join(html_parts))
        self._kw_display.setTextFormat(Qt.TextFormat.RichText)


# ── 自定义绘图组件 ──


class _PieWidget(QWidget):
    """情绪分布饼图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = {}
        self._colors = {"positive": "#42b983", "neutral": "#aab0b8", "negative": "#e74c3c"}
        self._labels = {"positive": "积极", "neutral": "中性", "negative": "消极"}

    def set_data(self, data: dict):
        self._data = data
        self.update()

    def paintEvent(self, event):
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx, cy = w // 2, h // 2 - 10
        r = min(w, h) // 2 - 20

        data = [(k, v) for k, v in self._data.items() if v > 0]
        if not data:
            painter.drawText(cx - 20, cy, "还没有数据呢…♪")
            painter.end()
            return

        start_angle = 0
        for key, val in data:
            angle = int(val * 360 * 16)  # QPainter uses 1/16 degree
            if angle <= 0:
                continue
            painter.setBrush(QColor(self._colors.get(key, "#aaa")))
            painter.setPen(QPen(QColor(self._colors.get(key, "#aaa")), 2))
            painter.drawPie(cx - r, cy - r, 2 * r, 2 * r, start_angle, angle)

            mid_angle = start_angle + angle // 2
            lx = int(cx + (r * 0.65) * math.cos(math.radians(mid_angle / 16)))
            ly = int(cy - (r * 0.65) * math.sin(math.radians(mid_angle / 16)))
            if val >= 0.05:
                painter.setPen(Qt.GlobalColor.white)
                font = QFont("Consolas", 9)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(lx - 15, ly - 7, 30, 14, Qt.AlignmentFlag.AlignCenter, f"{val:.0%}")

            start_angle += angle

        # Legend
        ly = cy + r + 10
        for key, val in data:
            painter.setBrush(QColor(self._colors.get(key, "#aaa")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(10, ly - 4, 10, 8)
            painter.setPen(QColor(C["text_2"]))
            painter.drawText(26, ly - 7, 200, 14, Qt.AlignmentFlag.AlignLeft,
                             f"{self._labels[key]} {val:.0%}")
            ly += 18

        painter.end()


class _TimeHistogramWidget(QWidget):
    """弹幕时间分布柱状图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._texts: list = []

    def set_data(self, texts: list):
        self._texts = texts
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        texts = self._texts
        w = self.width()
        h = self.height()

        if not texts:
            painter.setPen(QColor(C["text_3"]))
            painter.drawText(w // 2 - 40, h // 2, "还没有弹幕数据呢…♪")
            painter.end()
            return

        n = len(texts)
        bins = min(20, max(5, n // 5))
        chunk_size = max(1, n // bins)
        counts = []
        for i in range(0, n, chunk_size):
            counts.append(min(1.0, len(texts[i: i + chunk_size]) / chunk_size))

        bar_w = (w - 40) / max(len(counts), 1)
        max_c = max(counts) if counts else 1

        for i, v in enumerate(counts):
            bh = v / max_c * (h - 50)
            x0 = int(20 + i * bar_w)
            y0 = int(h - 30 - bh)
            x1 = int(x0 + bar_w - 1)
            y1 = int(h - 30)
            intensity = int(50 + 180 * v / max_c)
            color = QColor(intensity, 0x66, 0xFF)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(x0, y0, x1 - x0, y1 - y0)

        painter.setPen(QColor(C["text_3"]))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(20, 10, 200, 16, Qt.AlignmentFlag.AlignLeft, "弹幕时间分布（→ 时间轴）♪")
        painter.end()
