"""Characterize VideoListPanel's AppState/AppActions migration boundary."""

import threading
from typing import Any

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from ui.app_actions import AppActions
from ui.app_state import AppState
from ui.video_list_panel import VideoListPanel

APP = QApplication.instance() or QApplication([])


class FakeState(QObject):
    """Small signal source matching the panel's state boundary."""

    selection_changed = pyqtSignal(str)


class FakeActions:
    """Record panel intents without requiring a main-window object."""

    def __init__(self, state: Any) -> None:
        self._state = state
        self.selected: list[str] = []
        self.pushed: list[str | None] = []

    def select_video(self, bvid: str) -> None:
        self.selected.append(bvid)
        self._state.selection_changed.emit(bvid)

    def push(self, bvid: str | None = None) -> None:
        self.pushed.append(bvid)


def make_video(bvid: str, title: str = "test", views: int = 10) -> dict[str, Any]:
    """Build one card payload without a cover URL or external I/O."""
    return {"bvid": bvid, "title": title, "view_count": views}


def make_panel() -> tuple[QWidget, VideoListPanel, FakeState, FakeActions]:
    """Build and show a real QWidget panel with injected test dependencies."""
    parent = QWidget()
    state = FakeState()
    actions = FakeActions(state)
    panel = VideoListPanel(parent, state, actions)
    panel._cover_loader.load_cover = lambda _bvid, _url: None
    parent.resize(300, 300)
    parent.show()
    APP.processEvents()
    return parent, panel, state, actions


def test_panel_has_no_main_window_reference_and_click_dispatches_once() -> None:
    """A user click emits its BVID and forwards one selection action."""
    _parent, panel, _state, actions = make_panel()
    panel.rebuild_list([make_video("BV1click")])
    selected: list[str] = []
    panel.video_selected.connect(selected.append)

    index = panel._list.indexFromItem(panel._list.item(0))
    QTest.mouseClick(panel._list.viewport(), Qt.MouseButton.LeftButton, pos=panel._list.visualRect(index).center())
    APP.processEvents()

    assert not hasattr(panel, "gui")
    assert not hasattr(panel, "_parent")
    assert selected == ["BV1click"]
    assert actions.selected == ["BV1click"]


def test_push_all_ignores_clicked_boolean_and_state_selection_does_not_reenter() -> None:
    """The Qt clicked(bool) payload never becomes a BVID or selection callback."""
    _parent, panel, state, actions = make_panel()
    panel.rebuild_list([make_video("BV1one"), make_video("BV1two")])

    push_button = next(button for button in panel.findChildren(QPushButton) if button.text() == "⇪ 全部推送")
    push_button.click()
    state.selection_changed.emit("BV1two")
    APP.processEvents()

    assert actions.pushed == [None]
    assert actions.selected == []
    assert panel._list.currentItem().data(Qt.ItemDataRole.UserRole)["bvid"] == "BV1two"


def test_rebuild_update_remove_search_and_count_preserve_incremental_cards() -> None:
    """Existing public list operations retain their card and filtering behavior."""
    _parent, panel, _state, _actions = make_panel()
    panel.rebuild_list([make_video("BV1one", "First"), make_video("BV1two", "Second")])
    panel.update_card(make_video("BV1one", "Renamed", 99))

    assert panel._count_lbl.text() == "2"
    assert panel._card_widgets["BV1one"].data(Qt.ItemDataRole.UserRole)["view_count"] == 99

    panel._on_search("second")
    panel._apply_search()
    assert panel._card_widgets["BV1one"].isHidden()
    assert not panel._card_widgets["BV1two"].isHidden()

    panel.remove_card("BV1two")
    panel.remove_card("BV1one")
    assert panel._count_lbl.text() == "0"
    assert panel._list_stack.currentWidget() is panel._empty_state


def test_frozen_app_state_snapshot_is_adapted_for_qt_card_payload() -> None:
    """MappingProxyType snapshots are copied before Qt consumers expect dict data."""

    class Host:
        def __init__(self) -> None:
            self._data_lock = threading.Lock()
            self.monitored_videos = [make_video("BV1frozen")]
            self.history_data: dict[str, Any] = {}
            self.prediction_results: dict[str, Any] = {}
            self.video_dbs: dict[str, Any] = {}
            self.selected_bvid: str | None = None
            self._video_index: dict[str, Any] = {}

    host = Host()
    state = AppState(host)
    actions = FakeActions(state)
    parent = QWidget()
    panel = VideoListPanel(parent, state, actions)
    panel.rebuild_list(state.monitored_videos)

    payload = panel._card_widgets["BV1frozen"].data(Qt.ItemDataRole.UserRole)
    assert isinstance(payload, dict)
    assert payload["bvid"] == "BV1frozen"


def test_real_action_facade_preserves_existing_host_wiring(monkeypatch) -> None:
    """A minimal legacy owner still receives the panel's action intents exactly once."""

    class Host:
        def __init__(self) -> None:
            self._data_lock = threading.Lock()
            self.monitored_videos: list[dict[str, Any]] = []
            self.history_data: dict[str, Any] = {}
            self.prediction_results: dict[str, Any] = {}
            self.video_dbs: dict[str, Any] = {}
            self.selected_bvid: str | None = None
            self._video_index: dict[str, Any] = {}
            self.select_calls: list[str] = []
            self.push_calls: list[str | None] = []

    host = Host()
    state = AppState(host)

    def select_legacy_owner(owner: Host, bvid: str) -> None:
        owner.select_calls.append(bvid)
        owner.selected_bvid = bvid
        owner.app_state.notify_selection_changed()

    def push_legacy_owner(owner: Host) -> None:
        owner.push_calls.append(None)

    from ui import main_gui_events_monitor, main_gui_events_runtime

    monkeypatch.setattr(main_gui_events_monitor, "select_video", select_legacy_owner)
    monkeypatch.setattr(main_gui_events_runtime, "manual_push", push_legacy_owner)
    host.app_state = state
    parent = QWidget()
    panel = VideoListPanel(parent, state, AppActions(host))
    panel.rebuild_list([make_video("BV1host")])

    panel._list.setCurrentItem(panel._card_widgets["BV1host"])
    push_button = next(button for button in panel.findChildren(QPushButton) if button.text() == "⇪ 全部推送")
    push_button.click()
    APP.processEvents()

    assert host.select_calls == ["BV1host"]
    assert host.push_calls == [None]
    assert host.selected_bvid == "BV1host"
