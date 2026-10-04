"""Characterize PredictionPanel's AppState/AppActions migration boundary."""

import os
from datetime import datetime
from types import MappingProxyType
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from ui.prediction_panel import PredictionPanel

APP = QApplication.instance() or QApplication([])


class FakeState(QObject):
    """Small frozen-snapshot state source for the prediction boundary."""

    selection_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.selected_bvid: str | None = None
        self.history_data: MappingProxyType[str, Any] = MappingProxyType({})
        self.prediction_results: MappingProxyType[str, Any] = MappingProxyType({})


class FakeActions:
    """Record video resolution without exposing a panel-usable host."""

    def __init__(self, videos: dict[str, Any]) -> None:
        self._videos = videos
        self.lookups: list[str] = []

    def get_video(self, bvid: str) -> Any:
        self.lookups.append(bvid)
        return self._videos.get(bvid)


def make_video(bvid: str = "BV1prediction") -> dict[str, Any]:
    """Build a representative video payload without external I/O."""
    return {
        "bvid": bvid,
        "view_count": 100,
        "like_count": 10,
        "coin_count": 2,
        "favorite_count": 3,
        "share_count": 4,
        "danmaku_count": 5,
        "viewers_total": 6,
        "viewers_web": 4,
        "viewers_app": 2,
    }


def make_panel() -> tuple[QWidget, PredictionPanel, FakeState, FakeActions]:
    """Build a real offscreen panel with injected state and actions."""
    parent = QWidget()
    state = FakeState()
    actions = FakeActions({})
    panel = PredictionPanel(parent, state, actions)
    parent.resize(320, 600)
    parent.show()
    APP.processEvents()
    return parent, panel, state, actions


def test_algo_list_uses_state_snapshots_and_actions_lookup_once() -> None:
    """Algorithm info resolves its selected video once and consumes frozen snapshots."""
    _parent, panel, state, actions = make_panel()
    video = make_video()
    bvid = video["bvid"]
    history = ((datetime(2026, 1, 1), 90), (datetime(2026, 1, 2), 100))
    cached = MappingProxyType({"valid": 4, "total": 5, "ensemble_confidence": 0.8})
    actions._videos[bvid] = video
    state.selected_bvid = bvid
    state.history_data = MappingProxyType({bvid: history})
    state.prediction_results = MappingProxyType({bvid: cached})
    updates: list[tuple[Any, Any, Any]] = []
    panel.update_info = lambda resolved, rows, result: updates.append((resolved, rows, result))

    panel._update_algo_list([], [])

    assert not hasattr(panel, "gui")
    assert actions.lookups == [bvid]
    assert updates == [(video, history, cached)]


def test_empty_selection_and_missing_video_clear_info() -> None:
    """Legacy empty-state behavior remains intact for unavailable selections."""
    _parent, panel, state, actions = make_panel()
    clears: list[bool] = []
    panel._clear_info = lambda: clears.append(True)

    panel._update_algo_list([], [])
    state.selected_bvid = "BV1missing"
    panel._update_algo_list([], [])

    assert clears == [True, True]
    assert actions.lookups == ["BV1missing"]


def test_hero_and_info_render_representative_payload_without_double_selection_render() -> None:
    """Hero/info caching stays imperative, so one selection signal cannot double-render."""
    _parent, panel, state, actions = make_panel()
    video = make_video()
    bvid = video["bvid"]
    history = ((datetime(2026, 1, 1), 90), (datetime(2026, 1, 2), 100))
    cached = MappingProxyType({"valid": 4, "total": 5, "ensemble_confidence": 0.8})
    actions._videos[bvid] = video
    state.selected_bvid = bvid
    state.history_data = MappingProxyType({bvid: history})
    state.prediction_results = MappingProxyType({bvid: cached})

    panel.build_pred_hero(150, 100, 1.0, bias_info={"applied": True, "factor": 0.9, "samples": 3})
    panel._update_algo_list([], [])
    state.selection_changed.emit(bvid)
    APP.processEvents()

    assert panel._hero_has_data
    assert panel._hero_widgets["val_lbl"].text() == "150"
    assert panel._info_dynamic["algo_valid"].text() == "4/5"
    assert panel._info_dynamic["n_records"].text() == "2"
    assert actions.lookups == [bvid]
