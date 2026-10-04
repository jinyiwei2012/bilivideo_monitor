"""Characterization coverage for the AppState/AppActions migration skeleton."""

from types import SimpleNamespace
from typing import Any

from PyQt6.QtCore import QObject

from ui.app_actions import AppActions
from ui.app_state import AppState


class _TrackingLock:
    """Minimal context-manager lock that records the snapshot lock ordering."""

    def __init__(self, name: str, trace: list[str]) -> None:
        self.name = name
        self.trace = trace

    def __enter__(self) -> None:
        self.trace.append(f"enter:{self.name}")

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.trace.append(f"exit:{self.name}")


def _make_host() -> SimpleNamespace:
    return SimpleNamespace(
        monitored_videos=[{"bvid": "BV1", "tags": ["music"]}],
        history_data={"BV1": [{"view_count": 1, "metrics": {"likes": 2}}]},
        prediction_results={"BV1": {"prediction": 2, "details": ["weighted"]}},
        video_dbs={"BV1": object()},
        selected_bvid="BV1",
        _video_index={"BV1": {"bvid": "BV1"}},
    )


def test_app_state_snapshots_mirror_main_window_data_contract() -> None:
    """AppState reads all six containers initialized by MainGui unchanged."""
    host = _make_host()
    state = AppState(host)

    assert state.monitored_videos[0]["bvid"] == host.monitored_videos[0]["bvid"]
    assert state.monitored_videos[0]["tags"] == tuple(host.monitored_videos[0]["tags"])
    assert state.history_data["BV1"][0]["view_count"] == host.history_data["BV1"][0]["view_count"]
    assert state.history_data["BV1"][0]["metrics"]["likes"] == host.history_data["BV1"][0]["metrics"]["likes"]
    assert state.prediction_results["BV1"]["prediction"] == host.prediction_results["BV1"]["prediction"]
    assert state.prediction_results["BV1"]["details"] == tuple(host.prediction_results["BV1"]["details"])
    assert dict(state.video_dbs) == host.video_dbs
    assert state.selected_bvid == host.selected_bvid
    assert state._video_index["BV1"]["bvid"] == host._video_index["BV1"]["bvid"]
    assert state.video_index["BV1"]["bvid"] == host._video_index["BV1"]["bvid"]


def test_app_state_snapshots_are_read_only_container_views() -> None:
    """Nested ordinary containers cannot alter host state through snapshots."""
    host = _make_host()
    state = AppState(host)
    videos = state.monitored_videos
    history = state.history_data
    predictions = state.prediction_results

    try:
        videos[0]["title"] = "mutated"
    except TypeError:
        pass
    else:
        raise AssertionError("nested video snapshots must be read-only")
    try:
        history["BV1"].append((0, 0))
    except AttributeError:
        pass
    else:
        raise AssertionError("nested history snapshots must be immutable")
    try:
        predictions["BV1"]["details"].append("mutated")
    except AttributeError:
        pass
    else:
        raise AssertionError("nested prediction snapshots must be immutable")

    assert host.monitored_videos[0] == {"bvid": "BV1", "tags": ["music"]}
    assert host.history_data["BV1"] == [{"view_count": 1, "metrics": {"likes": 2}}]
    assert host.prediction_results["BV1"] == {"prediction": 2, "details": ["weighted"]}


def test_app_state_snapshot_does_not_change_after_host_mutation() -> None:
    """A captured ordinary-data snapshot remains stable after later host writes."""
    host = _make_host()
    state = AppState(host)
    videos = state.monitored_videos
    history = state.history_data
    predictions = state.prediction_results

    host.monitored_videos[0]["tags"].append("later")
    host.history_data["BV1"][0]["metrics"]["likes"] = 99
    host.prediction_results["BV1"]["details"].append("later")

    assert videos[0]["tags"] == ("music",)
    assert history["BV1"][0]["metrics"]["likes"] == 2
    assert predictions["BV1"]["details"] == ("weighted",)


def test_app_state_uses_existing_locks_when_capturing_state() -> None:
    """Data copies use the host data lock and DB membership uses DB lock second."""
    trace: list[str] = []
    host = _make_host()
    host._data_lock = _TrackingLock("data", trace)
    host._video_db_lock = _TrackingLock("video-db", trace)
    state = AppState(host)

    state.monitored_videos
    state.history_data
    state.prediction_results
    state._video_index
    state.video_dbs

    assert trace == [
        "enter:data",
        "exit:data",
        "enter:data",
        "exit:data",
        "enter:data",
        "exit:data",
        "enter:data",
        "exit:data",
        "enter:data",
        "enter:video-db",
        "exit:video-db",
        "exit:data",
    ]


def test_app_state_exposes_qobject_signals() -> None:
    """The skeleton provides typed Qt signals for future panel subscriptions."""
    state = AppState(_make_host())
    received: list[tuple[str, Any]] = []

    assert isinstance(state, QObject)
    state.video_updated.connect(lambda bvid: received.append(("video", bvid)))
    state.selection_changed.connect(lambda bvid: received.append(("selection", bvid)))
    state.prediction_updated.connect(lambda bvid: received.append(("prediction", bvid)))
    state.notify_video_updated("BV1")
    state.notify_selection_changed()
    state.notify_prediction_updated("BV1")

    assert received == [("video", "BV1"), ("selection", "BV1"), ("prediction", "BV1")]


def test_app_actions_delegate_to_existing_handlers(monkeypatch) -> None:
    """Actions forward intent without reimplementing current event behavior."""
    from ui import main_gui_events_monitor, main_gui_events_runtime

    host = SimpleNamespace()
    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(main_gui_events_monitor, "add_monitor", lambda gui: calls.append(("add", (gui,))))
    monkeypatch.setattr(main_gui_events_monitor, "remove_monitor", lambda gui: calls.append(("remove", (gui,))))
    monkeypatch.setattr(main_gui_events_runtime, "do_fetch", lambda gui: calls.append(("refresh", (gui,))))
    monkeypatch.setattr(
        main_gui_events_monitor, "select_video", lambda gui, bvid: calls.append(("select", (gui, bvid)))
    )
    monkeypatch.setattr(main_gui_events_monitor, "get_video", lambda gui, bvid: {"bvid": bvid})
    monkeypatch.setattr(main_gui_events_runtime, "manual_push", lambda gui: calls.append(("push-all", (gui,))))
    monkeypatch.setattr(
        main_gui_events_runtime, "push_single", lambda gui, bvid: calls.append(("push-one", (gui, bvid)))
    )
    monkeypatch.setattr(main_gui_events_monitor, "copy_bvid", lambda gui, bvid: calls.append(("copy", (gui, bvid))))
    host.set_finetune_status = lambda text, color: calls.append(("finetune", (text, color)))
    actions = AppActions(host)

    actions.add_monitor()
    actions.remove_monitor()
    actions.refresh()
    actions.select_video("BV1")
    assert actions.get_video("BV1") == {"bvid": "BV1"}
    actions.push()
    actions.push("BV1")
    actions.copy_bvid("BV1")
    actions.set_finetune_status("ready", "green")

    assert calls == [
        ("add", (host,)),
        ("remove", (host,)),
        ("refresh", (host,)),
        ("select", (host, "BV1")),
        ("push-all", (host,)),
        ("push-one", (host, "BV1")),
        ("copy", (host, "BV1")),
        ("finetune", ("ready", "green")),
    ]
