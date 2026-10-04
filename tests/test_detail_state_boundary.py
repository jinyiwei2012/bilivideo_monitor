"""Characterize DetailPanel's AppState/AppActions migration boundary."""

import sys
import types
from types import MappingProxyType
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from ui.detail_panel import DetailPanel, FinetuneDialog

APP = QApplication.instance() or QApplication([])


class FakeState(QObject):
    """Read-only signal source and frozen snapshots for the detail boundary."""

    selection_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.selected_bvid: str | None = None
        self.monitored_videos: tuple[Any, ...] = ()
        self.history_data: MappingProxyType[str, Any] = MappingProxyType({})
        self.prediction_results: MappingProxyType[str, Any] = MappingProxyType({})
        self.video_dbs: MappingProxyType[str, Any] = MappingProxyType({})


class FakeActions:
    """Record intents without exposing a legacy main-window object."""

    def __init__(self) -> None:
        self.copied: list[str] = []
        self.finetune_statuses: list[tuple[str, str | None]] = []

    def copy_bvid(self, bvid: str) -> None:
        self.copied.append(bvid)

    def set_finetune_status(self, text: str, color: str | None = None) -> None:
        self.finetune_statuses.append((text, color))


class FakeLifecycleOwner:
    """Opaque lifecycle owner used exclusively for DB leases and task registration."""


def make_video(bvid: str = "BV1detail", views: int = 100) -> dict[str, Any]:
    """Build a complete-enough detail payload without external I/O."""
    return {
        "bvid": bvid,
        "title": "Detail test",
        "author": "tester",
        "view_count": views,
        "like_count": 10,
        "coin_count": 2,
        "favorite_count": 3,
        "danmaku_count": 1,
        "reply_count": 4,
    }


def make_panel() -> tuple[QWidget, DetailPanel, FakeState, FakeActions, FakeLifecycleOwner]:
    """Build a real offscreen panel with state/action/lifecycle substitutes."""
    parent = QWidget()
    state = FakeState()
    actions = FakeActions()
    lifecycle = FakeLifecycleOwner()
    panel = DetailPanel(parent, state, actions, lifecycle)
    parent.resize(700, 500)
    parent.show()
    APP.processEvents()
    return parent, panel, state, actions, lifecycle


def test_panel_uses_state_actions_and_selection_refreshes_once() -> None:
    """Selection notification refreshes header/stat/tab once with no main GUI reference."""
    _parent, panel, state, _actions, _lifecycle = make_panel()
    video = make_video()
    state.monitored_videos = (MappingProxyType(video),)
    state.selected_bvid = video["bvid"]
    refreshes: list[int] = []
    original = panel._on_tab_changed

    def record_refresh(index: int) -> None:
        refreshes.append(index)
        original(index)

    panel._on_tab_changed = record_refresh
    state.selection_changed.emit(video["bvid"])
    APP.processEvents()

    assert not hasattr(panel, "gui")
    assert panel._get_selected_video()["bvid"] == video["bvid"]
    assert refreshes == [0]


def test_chart_modes_fingerprints_and_frozen_snapshots_are_preserved() -> None:
    """Chart rendering consumes frozen snapshots while retaining its render guards."""
    _parent, panel, state, _actions, _lifecycle = make_panel()
    video = make_video()
    bvid = video["bvid"]
    state.selected_bvid = bvid
    state.monitored_videos = (MappingProxyType(video),)
    state.history_data = MappingProxyType({bvid: ((1, 50), (2, 100))})
    state.prediction_results = MappingProxyType({bvid: MappingProxyType({"prediction": 200})})
    calls: list[tuple[Any, ...]] = []
    panel._chart_widget.update_chart = lambda *args, **kwargs: calls.append((args, kwargs))

    panel._do_render_chart()
    panel._do_render_chart()
    panel._radio_delta.setChecked(True)
    panel._manual_render_chart()

    assert len(calls) == 2
    assert calls[0][0][0] is state.history_data
    assert calls[0][0][1] == bvid
    assert calls[1][1]["mode"] == "delta"


def test_copy_bvid_routes_through_actions_once() -> None:
    """The clickable BVID label emits an action, not a legacy main-window call."""
    _parent, panel, _state, actions, _lifecycle = make_panel()
    panel.build_header(make_video())
    button = next(button for button in panel.frame.findChildren(QPushButton) if button.text() == "BV1detail")
    button.click()

    assert actions.copied == ["BV1detail"]


def test_finetune_status_routes_through_actions_via_invoke(monkeypatch) -> None:
    """Worker-originated finetune status updates stay behind the main-thread invoker."""
    parent = QWidget()
    actions = FakeActions()
    dialog = FinetuneDialog(parent, actions, "BV1detail", [{"algorithm_id": "algo", "name": "Algo"}])
    invoked: list[Any] = []

    class FakeTrainer:
        def finetune_for_video(self, **_kwargs: Any) -> str:
            return "version"

    class DirectThread:
        def __init__(self, target: Any, daemon: bool) -> None:
            self._target = target
            assert daemon

        def start(self) -> None:
            self._target()

    def main_thread_invoke(callback: Any) -> None:
        invoked.append(callback)
        callback()

    trainer_module = types.ModuleType("algorithms.training.trainer")
    trainer_module.ModelTrainer = FakeTrainer
    monkeypatch.setitem(sys.modules, "algorithms.training.trainer", trainer_module)
    monkeypatch.setattr("ui.detail_panel.threading.Thread", DirectThread)
    monkeypatch.setattr("ui.detail_panel.invoke", main_thread_invoke)

    dialog._run()

    assert len(actions.finetune_statuses) == 3
    assert actions.finetune_statuses[0][0].startswith("◎ 天依正在微调")
    assert actions.finetune_statuses[-1][0].startswith("✓ 微调 BV1detail 完成")
    assert len(invoked) >= 7


def test_stale_callbacks_use_state_and_background_danmaku_uses_lifecycle(monkeypatch) -> None:
    """Danmaku loads lease DB work and only render after an on-state-selection guard."""
    _parent, panel, state, _actions, lifecycle = make_panel()
    video = make_video()
    bvid = video["bvid"]
    state.selected_bvid = bvid
    state.monitored_videos = (MappingProxyType(video),)
    deferred: list[Any] = []
    registrations: list[tuple[Any, str]] = []
    leases: list[tuple[Any, str]] = []
    renders: list[tuple[Any, Any]] = []

    class FakeDb:
        def get_danmaku_records(self, limit: int = 5000) -> list[dict[str, Any]]:
            assert limit == 200
            return [{"video_ts": 1, "content": "hello"}]

        def count_danmaku(self) -> int:
            return 1

    def use_lease(owner: Any, lease_bvid: str, reader: Any) -> Any:
        leases.append((owner, lease_bvid))
        return reader(FakeDb())

    def register(owner: Any, worker: Any, name: str) -> object:
        registrations.append((owner, name))
        worker()
        return object()

    monkeypatch.setattr("ui.detail_tabs.use_video_db", use_lease)
    monkeypatch.setattr("ui.detail_tabs.start_registered_task", register)
    monkeypatch.setattr("ui.detail_tabs.invoke", deferred.append)
    panel._render_danmaku = lambda records, count: renders.append((records, count))

    panel._schedule_danmaku_load(bvid)
    state.selected_bvid = "BV1other"
    deferred.pop()()

    assert leases == [(lifecycle, bvid)]
    assert registrations == [(lifecycle, f"danmaku:{bvid}")]
    assert renders == []
    assert panel._dm_cache[bvid]["count"] == 1
