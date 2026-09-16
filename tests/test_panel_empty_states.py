# -*- coding: utf-8 -*-
"""面板「看不到信息」回归（离线，offscreen）。

两个实测到的用户可见缺陷：
1. **预测准确率回看**：默认筛选是「10万 / 7天」，而库里 137 条预测全在 1000万
   → `target_threshold = 100000` 命中 0 行 → 面板只显示「还没有预测记录呢」。
   修复要求：命中 0 行时**自适应**切到确实有数据的筛选并渲染，且摘要里说明已切换。
2. **异常检查**：0 条命中时只有一句安慰文案，用户分不清「确实没异常」还是「压根没扫到」
   → 修复要求：文案与详情区必须给出扫描范围与跳过原因（纯函数 `scan_summary_text`）。
"""

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTableWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

from core.database.video_db import VideoDatabase  # noqa: E402
from ui.anomaly_panel import AnomalyPanel, scan_summary_text  # noqa: E402
from ui.prediction_accuracy import _THRESHOLDS, PredictionAccuracyPanel, pick_best_threshold  # noqa: E402

BVID = "BV1Bfjq6LEDi"


def _seed(tmp_path, threshold: int, when: datetime, n_pred: int = 2, n_rec: int = 3) -> VideoDatabase:
    """建一个临时视频库，直插 predictions / monitor_records（绕开镜像与中央库写入）。"""
    vdb = VideoDatabase(BVID, base_dir=str(tmp_path))
    stamp = when.strftime("%Y-%m-%d %H:%M:%S")
    with vdb._get_connection() as conn:
        for i in range(n_pred):
            conn.execute(
                "INSERT INTO predictions (algorithm, algorithm_id, target_threshold, predicted_seconds,"
                " predicted_time, confidence, current_views, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (f"algo-{i}", f"a{i}", threshold, 3600, stamp, 0.9, 5000, stamp),
            )
        for i in range(n_rec):
            conn.execute(
                "INSERT INTO monitor_records (timestamp, view_count) VALUES (?, ?)",
                ((when + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S"), 5000 + 10 * i),
            )
        conn.commit()
    return vdb


class _StubGui:
    def __init__(self, vdb: VideoDatabase) -> None:
        self.monitored_videos = [{"bvid": BVID, "title": "t", "view_count": 5000, "viewers_total": 0}]
        self.video_dbs = {BVID: vdb}
        self.history_data = {BVID: [(r["timestamp"], r["view_count"]) for r in vdb.get_all_records()]}
        self._cached_up_info: Dict[str, Any] = {}


def _spin(ms: int = 1500) -> None:
    """转 Qt 事件循环，让后台线程的 invoke 回调落到主线程。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


# ═══════════════ 预测准确率回看 ═══════════════


def test_pick_best_threshold_prefers_most_rows() -> None:
    assert pick_best_threshold([(10000000, 5), (1000000, 9)], _THRESHOLDS) == 1000000
    assert pick_best_threshold([(999, 5)], _THRESHOLDS) is None
    assert pick_best_threshold([], _THRESHOLDS) is None


def test_accuracy_panel_auto_switches_to_threshold_with_data(tmp_path) -> None:
    """只有 1000万 预测时，面板不得停在默认「10万/7天」的空态。"""
    vdb = _seed(tmp_path, 10000000, datetime.now() - timedelta(hours=2))
    panel = PredictionAccuracyPanel(parent=None, gui=_StubGui(vdb))

    table = panel.dlg.findChildren(QTableWidget)[0]
    assert table.rowCount() > 0, "自适应后必须渲染出预测行"
    assert panel._thresh_combo.currentIndex() == _THRESHOLDS.index(10000000)
    assert "已自动切到有数据的筛选" in panel._summary_lbl.text()


def test_accuracy_panel_widens_window_when_data_is_older(tmp_path) -> None:
    """数据都在 7 天窗外时，除了换阈值还要把时间范围放宽到「全部」。"""
    vdb = _seed(tmp_path, 1000000, datetime.now() - timedelta(days=40))
    panel = PredictionAccuracyPanel(parent=None, gui=_StubGui(vdb))

    assert panel.dlg.findChildren(QTableWidget)[0].rowCount() > 0
    assert panel._days_combo.currentText() == "全部"


def test_accuracy_panel_reports_truly_empty_video(tmp_path) -> None:
    """库里确实没有预测时才允许空态文案。"""
    vdb = _seed(tmp_path, 1000000, datetime.now() - timedelta(hours=1), n_pred=0, n_rec=3)
    panel = PredictionAccuracyPanel(parent=None, gui=_StubGui(vdb))

    assert panel.dlg.findChildren(QTableWidget)[0].rowCount() == 0
    assert "没有预测记录" in panel._summary_lbl.text()


# ═══════════════ 异常检查 ═══════════════


def test_scan_summary_explains_empty_result() -> None:
    assert "还没有监控中的视频" in scan_summary_text(0, {"videos": 0})
    assert "记录不足" in scan_summary_text(0, {"videos": 2, "scanned": 0, "skipped_records": 2})
    txt = scan_summary_text(0, {"videos": 3, "scanned": 2, "skipped_records": 1, "skipped_history": 0})
    assert "已检查 2/3" in txt and "1 个记录不足被跳过" in txt
    assert "失败" not in txt
    hits = scan_summary_text(4, {"videos": 3, "scanned": 2})
    assert "已检查 2/3" in hits and "4 处变化" in hits


def test_anomaly_panel_empty_state_shows_scan_breakdown() -> None:
    """没有足够记录时，状态栏与详情区必须说明跳过了谁，而不是一片空白。"""

    class _Gui:
        monitored_videos = [{"bvid": BVID, "title": "t", "view_count": 1}]
        history_data: Dict[str, Any] = {}
        video_dbs: Dict[str, Any] = {}
        _cached_up_info: Dict[str, Any] = {}

    panel = AnomalyPanel(None, _Gui())
    _spin(1500)

    assert "记录不足" in panel._status_lbl.text()
    assert "本次扫描明细" in panel._detail_text.toPlainText()
