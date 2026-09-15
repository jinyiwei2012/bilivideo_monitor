"""评论抓取面板 —— 独立窗口（经 ``ui/dialog_host.present()`` 显示）。

功能：选视频 / 填 BV 号或链接 → 选排序与上限 → 抓主评论（可选楼中楼）→ 结果表 + 统计 + 导出 CSV。
数据落**独立评论库** ``data/comments/comments.db``（见 ``core/database/comment_db.py``），
抓取逻辑在 ``core/bilibili_comment.py``（独立 session，见 docs/risk_control_playbook.md §6）。
"""

import csv
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QWidget,
)

from core.bilibili_comment import (
    MODE_HOT,
    MODE_LATEST,
    MODE_TIME,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_STOPPED,
    CommentFetchResult,
    CommentFetcher,
)
from core.database.comment_db import CommentDatabase
from ui.dialog_base import DialogBase
from ui.invoker import invoke
from ui.theme import C

logger = logging.getLogger(__name__)

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_TABLE_COLS = ("类型", "用户", "内容", "点赞", "回复", "时间", "IP属地")
_MODE_LABELS = (("按热度", MODE_HOT), ("按时间", MODE_TIME), ("按最新", MODE_LATEST))


class CommentPanel:
    """评论抓取独立窗口（组合式：自身持有 ``self.dlg``）。"""

    def __init__(self, parent: Any = None, gui: Any = None) -> None:
        """构造窗口（不显示；调用方负责 ``dialog_host.present()``）。"""
        self.dlg = DialogBase(parent, "评论抓取", "1000x700", modal=False)
        self.gui = gui
        self._fetcher: Optional[CommentFetcher] = None
        self._db: Optional[CommentDatabase] = None
        self._fetching = False
        self._last_bvid = ""
        self._setup_ui()

    # ── UI ──────────────────────────────────────────────
    def _setup_ui(self) -> None:
        """构建界面（全部颜色取自 ui/theme.py 令牌）。"""
        dlg = self.dlg
        dlg.header("评论抓取", "把评论连楼中楼一起收进独立数据库，字段尽量留全 ♪")

        self._build_target_section()
        self._build_params_section()
        self._build_progress_section()
        self._build_result_section()
        dlg.button_row([("关闭", self._on_close, "")])

    def _build_target_section(self) -> None:
        """目标选择：已监控视频下拉 + 自定义 BV/链接输入。"""
        sec = self.dlg.section(title="抓取目标")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self._video_cb = QComboBox()
        self._video_cb.setMinimumWidth(360)
        self._refresh_video_list()
        layout.addWidget(self._video_cb)

        self._bvid_edit = QLineEdit()
        self._bvid_edit.setPlaceholderText(
            "或直接填 BV 号 / 视频链接（如 https://www.bilibili.com/video/BV1xx411c7mu）"
        )
        layout.addWidget(self._bvid_edit, 1)
        sec.layout().addWidget(row)

    def _build_params_section(self) -> None:
        """抓取参数：排序 / 页数 / 条数上限 / 楼中楼。"""
        sec = self.dlg.section(title="抓取参数")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._label("排序"))
        self._mode_cb = QComboBox()
        for label, value in _MODE_LABELS:
            self._mode_cb.addItem(label, value)
        layout.addWidget(self._mode_cb)

        layout.addWidget(self._label("最多页数"))
        self._pages_spin = QSpinBox()
        self._pages_spin.setRange(1, 500)
        self._pages_spin.setValue(20)
        self._pages_spin.setToolTip("每页 20 条；0 表示不限（本控件最小为 1）")
        layout.addWidget(self._pages_spin)

        layout.addWidget(self._label("最多主评论"))
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(20, 100000)
        self._limit_spin.setSingleStep(100)
        self._limit_spin.setValue(2000)
        layout.addWidget(self._limit_spin)

        self._sub_check = QCheckBox("抓取楼中楼")
        self._sub_check.setChecked(True)
        layout.addWidget(self._sub_check)

        layout.addWidget(self._label("每条最多页"))
        self._sub_pages_spin = QSpinBox()
        self._sub_pages_spin.setRange(1, 50)
        self._sub_pages_spin.setValue(2)
        layout.addWidget(self._sub_pages_spin)

        layout.addWidget(self._label("页间隔(秒)"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 60)
        self._interval_spin.setValue(1)
        layout.addWidget(self._interval_spin)

        layout.addStretch()
        self._start_btn = QPushButton("开始抓取")
        self._start_btn.setProperty("primary", True)
        self._start_btn.clicked.connect(self._start_fetch)
        layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setProperty("danger", True)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_fetch)
        layout.addWidget(self._stop_btn)

        sec.layout().addWidget(row)

    def _build_progress_section(self) -> None:
        """进度条 + 运行日志。"""
        sec = self.dlg.section(title="进度")
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {C['border']};
                border-radius: 4px;
                background-color: {C['bg_base']};
                text-align: center;
                color: {C['text_1']};
            }}
            QProgressBar::chunk {{ background-color: {C['accent']}; border-radius: 3px; }}
            """)
        sec.layout().addWidget(self._progress)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        self._log_text.setStyleSheet(
            f"QTextEdit {{ background-color: {C['bg_base']}; color: {C['text_1']};"
            f" font-family: Consolas; font-size: 9pt; border: 1px solid {C['border']}; }}"
        )
        sec.layout().addWidget(self._log_text)

    def _build_result_section(self) -> None:
        """统计 + 结果表 + 导出。"""
        sec = self.dlg.section(title="结果")
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)

        self._stats_label = QLabel("尚无数据：抓取完成后这里显示统计")
        self._stats_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        head_layout.addWidget(self._stats_label, 1)

        self._reload_btn = QPushButton("刷新结果")
        self._reload_btn.clicked.connect(self._refresh_results)
        head_layout.addWidget(self._reload_btn)

        self._export_btn = QPushButton("导出 CSV")
        self._export_btn.setProperty("accent", True)
        self._export_btn.clicked.connect(self._export_csv)
        head_layout.addWidget(self._export_btn)
        sec.layout().addWidget(head)

        self._table = QTableWidget(0, len(_TABLE_COLS))
        self._table.setHorizontalHeaderLabels(list(_TABLE_COLS))
        self._stretch_message_column()
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {C['bg_base']}; color: {C['text_1']};"
            f" gridline-color: {C['border_sub']}; }}"
        )
        sec.layout().addWidget(self._table)

    @staticmethod
    def _label(text: str) -> QLabel:
        """统一风格的字段标签。"""
        label = QLabel(text)
        label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        return label

    def _refresh_video_list(self) -> None:
        """用主窗口已监控的视频预填下拉框。"""
        self._video_cb.clear()
        videos = getattr(self.gui, "monitored_videos", None) or []
        for video in videos:
            if not isinstance(video, dict):
                continue
            bvid = str(video.get("bvid", "") or "")
            if not bvid:
                continue
            title = str(video.get("title", "") or "")[:40]
            self._video_cb.addItem(f"{bvid}  {title}", bvid)
        if self._video_cb.count() == 0:
            self._video_cb.addItem("（无监控视频，请在右侧直接填 BV 号）", "")

    # ── 抓取 ────────────────────────────────────────────
    def _target_bvid(self) -> str:
        """解析目标 BV 号（输入框优先，其次下拉框）。"""
        text = self._bvid_edit.text().strip()
        if text:
            match = _BV_RE.search(text)
            return match.group(1) if match else text
        return str(self._video_cb.currentData() or "")

    def _start_fetch(self) -> None:
        """校验参数并启动后台抓取线程。"""
        if self._fetching:
            return
        bvid = self._target_bvid()
        if not _BV_RE.fullmatch(bvid):
            self._log("✗ 请填写合法的 BV 号（形如 BV1xx411c7mu）")
            return
        self._fetching = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress.setValue(0)
        self._last_bvid = bvid
        self._log(f"→ 开始抓取 {bvid}")
        params = {
            "mode": int(self._mode_cb.currentData() or MODE_HOT),
            "max_pages": int(self._pages_spin.value()),
            "max_comments": int(self._limit_spin.value()),
            "fetch_sub": bool(self._sub_check.isChecked()),
            "sub_pages": int(self._sub_pages_spin.value()),
            "min_interval": float(self._interval_spin.value()),
        }
        threading.Thread(target=self._worker, args=(bvid, params), daemon=True).start()

    def _worker(self, bvid: str, params: Dict[str, Any]) -> None:
        """后台线程：抓取 + 进度回调（UI 更新一律经 ui.invoker.invoke）。"""
        try:
            min_interval = float(params.pop("min_interval", 1.0))
            fetcher = CommentFetcher(min_interval=min_interval)
        except Exception as exc:
            logger.exception("初始化评论抓取器失败")
            detail = f"初始化失败: {exc}"
            invoke(lambda: self._on_error(detail))
            return
        self._fetcher = fetcher
        result = fetcher.fetch(
            bvid,
            progress=lambda done, message: invoke(lambda: self._on_progress(done, message)),
            should_stop=lambda: not self._fetching,
            **params,
        )
        invoke(lambda: self._on_done(result))

    def _stop_fetch(self) -> None:
        """请求停止（抓取循环会在下一次检查点退出）。"""
        if self._fetcher is not None:
            self._fetcher.stop()
        self._log("… 已请求停止，等待当前页完成")

    def _on_progress(self, done: int, message: str) -> None:
        """进度回调（主线程）。"""
        self._progress.setValue(min(100, done // 20))
        self._log(f"  {message}")

    def _on_done(self, result: CommentFetchResult) -> None:
        """抓取结束（主线程）：汇报并刷新结果表。"""
        self._fetching = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        icon = {"done": "✓", "stopped": "⏹", "blocked": "⚠", "error": "✗"}.get(result.status, "•")
        self._log(
            f"{icon} 结束（{result.status}）：主评论 {result.top_count} / 楼中楼 {result.sub_count}"
            f" / 页 {result.pages} ；{result.message}"
        )
        if result.status == STATUS_BLOCKED:
            self._log(
                "  提示：风控拦截时先重取 WBI 密钥/检查 UA；IP 级风控请稍后重试（见 docs/risk_control_playbook.md）"
            )
        if result.status in (STATUS_DONE, STATUS_STOPPED):
            self._progress.setValue(100 if result.status == STATUS_DONE else self._progress.value())
        self._refresh_results()
        self._release_fetcher()

    def _release_fetcher(self) -> None:
        """释放抓取器（含自建独立会话）；抓取仍在进行时只请求停止，不抢占资源。"""
        fetcher = self._fetcher
        if fetcher is None:
            return
        if self._fetching:
            fetcher.stop()
            return
        self._fetcher = None
        try:
            fetcher.close()
        except Exception as e:
            logger.debug("释放评论抓取器失败: %s", e)

    def _on_error(self, message: str) -> None:
        """初始化等前置错误（主线程）。"""
        self._fetching = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._log(f"✗ {message}")
        self._release_fetcher()

    # ── 结果 ────────────────────────────────────────────
    def _get_db(self) -> CommentDatabase:
        """惰性创建独立的只读连接（WAL 允许与抓取线程并发）。"""
        if self._db is None:
            self._db = CommentDatabase()
        return self._db

    def _refresh_results(self) -> None:
        """从独立库读回该视频的评论并填充表格 + 统计。"""
        bvid = self._last_bvid or self._target_bvid()
        if not _BV_RE.fullmatch(bvid):
            return
        try:
            db = self._get_db()
            rows = db.get_comments(bvid=bvid, limit=500, order="like")
            summary = db.summary(bvid)
        except Exception as e:
            logger.debug("读取评论库失败: %s", e)
            self._log(f"✗ 读取评论失败: {e}")
            return
        self._fill_table(rows)
        self._stats_label.setText(self._format_summary(bvid, summary))

    @staticmethod
    def _format_summary(bvid: str, summary: Dict[str, Any]) -> str:
        """把 summary() 结果格式化为一行统计。"""
        total = int(summary.get("total") or 0)
        sub = int(summary.get("sub_count") or 0)
        users = int(summary.get("user_count") or 0)
        locations = summary.get("locations") or []
        top_loc = "、".join(f"{item['location']}({item['n']})" for item in locations[:5])
        first_ctime = int(summary.get("first_ctime") or 0)
        last_ctime = int(summary.get("last_ctime") or 0)
        span = ""
        if first_ctime and last_ctime:
            span = f"；时间跨度 {CommentPanel._fmt_time(first_ctime)} ~ {CommentPanel._fmt_time(last_ctime)}"
        return f"{bvid}：评论 {total}（楼中楼 {sub}）／用户 {users}{span}；属地 TOP：{top_loc or '—'}"

    def _fill_table(self, rows: List[Dict[str, Any]]) -> None:
        """填充结果表（只读、按点赞排序展示前 500 条）。"""
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                "楼中楼" if int(row.get("is_sub") or 0) else "主评论",
                str(row.get("uname", "")),
                str(row.get("message", "")).replace("\n", " "),
                str(int(row.get("like_count") or 0)),
                str(int(row.get("rcount") or 0)),
                self._fmt_time(int(row.get("ctime") or 0)),
                str(row.get("location", "")),
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~item.flags().ItemIsEditable)
                self._table.setItem(r, c, item)
        self._table.resizeColumnsToContents()
        self._stretch_message_column()

    def _stretch_message_column(self) -> None:
        """让「内容」列自适应宽度（``horizontalHeader()`` 可能为 None，此处收窄类型）。"""
        header = self._table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    @staticmethod
    def _fmt_time(ts: int) -> str:
        """时间戳 → 本地时间字符串。"""
        if not ts:
            return ""
        import datetime

        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    def _export_csv(self) -> None:
        """把当前视频的评论导出为 CSV。"""
        bvid = self._last_bvid or self._target_bvid()
        if not _BV_RE.fullmatch(bvid):
            self._log("✗ 没有可导出的视频")
            return
        path, _ = QFileDialog.getSaveFileName(self.dlg, "导出评论 CSV", f"{bvid}_comments.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            rows = self._get_db().get_comments(bvid=bvid, limit=0, order="like")
        except Exception as e:
            self._log(f"✗ 导出失败: {e}")
            return
        if not rows:
            self._log("✗ 该视频在库中暂无评论")
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        except OSError as e:
            self._log(f"✗ 写入文件失败: {e}")
            return
        self._log(f"✓ 已导出 {len(rows)} 条到 {os.path.basename(path)}")

    # ── 生命周期 ────────────────────────────────────────
    def _log(self, message: str) -> None:
        """追加一行日志（主线程调用）。"""
        self._log_text.append(message)

    def _on_close(self) -> None:
        """关闭窗口：停止抓取并释放连接。"""
        self._fetching = False
        if self._fetcher is not None:
            self._fetcher.stop()
        if self._db is not None:
            self._db.close()
            self._db = None
        self.dlg.close()
