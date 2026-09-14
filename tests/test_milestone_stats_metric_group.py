"""里程碑统计弹窗：指标 QButtonGroup id 回归测试。

背景（实测崩溃，非本次弹窗统一改动引入）：`_build_compare_tab()` 原先用
`setId(rb, hash(val))`，而 Python 字符串 hash 是 64 位，超出 Qt int32 范围 →
`OverflowError: argument 2 overflowed: value must be in the range -2147483648 to 2147483647`，
该弹窗**构造即崩**（哈希随机化使单个值超界概率约 50%）。

修法：id 改用指标下标，并抽出模块级 `_METRIC_OPTIONS` 消除两处重复的指标列表。
"""

from __future__ import annotations

import pytest

INT32_MIN, INT32_MAX = -2147483648, 2147483647


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _window():
    from ui.milestone_stats import MilestoneStatsWindow

    return MilestoneStatsWindow(None)


class TestMetricGroupIds:
    def test_window_constructs_without_overflow(self, qapp):
        """回归：构造不得再抛 OverflowError。"""
        win = _window()
        try:
            assert win._metric_group is not None
            assert win._metric_group.buttons(), "指标单选按钮应已创建"
        finally:
            win.close()

    def test_ids_are_int32_safe_and_unique(self, qapp):
        from ui.milestone_stats import _METRIC_OPTIONS

        win = _window()
        try:
            ids = [win._metric_group.id(button) for button in win._metric_group.buttons()]
            assert len(ids) == len(_METRIC_OPTIONS)
            assert len(set(ids)) == len(ids), f"id 必须唯一: {ids}"
            for value in ids:
                assert INT32_MIN <= value <= INT32_MAX, f"id 超出 Qt int32 范围: {value}"
        finally:
            win.close()

    def test_checked_radio_maps_to_its_metric_key(self, qapp, monkeypatch):
        """勾选任一指标后，_current_metric 必须对应正确的数据键（原先靠 hash 反查）。"""
        from ui.milestone_stats import _METRIC_OPTIONS

        win = _window()
        try:
            monkeypatch.setattr(win, "_redraw_compare", lambda: None)
            for index, (_label, key) in enumerate(_METRIC_OPTIONS):
                win._metric_group.buttons()[index].setChecked(True)
                win._on_metric_changed()
                assert win._current_metric == key, f"下标 {index} 应映射到 {key}"
        finally:
            win.close()

    def test_metric_options_are_well_formed(self):
        from ui.milestone_stats import _METRIC_OPTIONS

        keys = [key for _label, key in _METRIC_OPTIONS]
        assert len(set(keys)) == len(keys), "指标键不得重复"
        assert "view_count" in keys, "默认指标 view_count 必须在列"
