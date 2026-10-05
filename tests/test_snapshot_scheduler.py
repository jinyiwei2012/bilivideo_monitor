"""Periodic snapshot scheduler and shutdown finalizer wiring tests."""

from types import SimpleNamespace
from unittest.mock import Mock

from ui import main_gui_events_runtime, main_gui_tick


def test_snapshot_interval_uses_config_and_floor(monkeypatch):
    settings = {"snapshot": {"interval_seconds": 900}}
    monkeypatch.setattr(main_gui_tick, "load_config", lambda: settings)
    assert main_gui_tick._snapshot_interval_ms() == 900 * 1000

    settings["snapshot"]["interval_seconds"] = 1
    assert main_gui_tick._snapshot_interval_ms() == 30 * 1000


def test_snapshot_cycle_delegates_to_backup_snapshot(monkeypatch):
    central = Mock()
    monkeypatch.setattr("core.get_db", lambda: central)

    main_gui_tick._run_snapshot_cycle(SimpleNamespace())

    central.sync_per_video_dbs_to_backup.assert_called_once_with()


def test_start_and_stop_snapshot_timer(monkeypatch):
    events = []

    class _FakeTimer:
        def __init__(self, _parent):
            self.interval = None
            self.started = False
            self.stopped = False
            self.timeout = SimpleNamespace(connect=lambda slot: events.append(slot))

        def setInterval(self, value):
            self.interval = value

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(main_gui_tick, "QTimer", _FakeTimer)
    monkeypatch.setattr(main_gui_tick, "load_config", lambda: {"snapshot": {"interval_seconds": 600}})
    gui = SimpleNamespace()

    main_gui_tick.start_snapshot_timer(gui)
    timer = gui._snapshot_timer
    assert timer.interval == 600 * 1000
    assert timer.started
    assert events and callable(events[0])

    main_gui_tick.stop_snapshot_timer(gui)
    assert timer.stopped
    assert gui._snapshot_timer is None


def test_shutdown_finalizer_snapshots_before_closing(monkeypatch):
    central = Mock()
    monkeypatch.setattr("core.get_db", lambda: central)

    calls = []
    gui = SimpleNamespace(_shutdown_finalized=False)
    gui.log_panel = SimpleNamespace(cleanup=lambda: calls.append("log_cleanup"))
    gui._stop_export_schedule = lambda: calls.append("export")
    gui._file_logger = SimpleNamespace(cancel_midnight_checker=lambda: None, close=lambda: None)

    import ui.main_gui_tick as tick
    import ui.monitor as monitor_pkg
    from ui.monitor import _lifecycle

    monkeypatch.setattr(_lifecycle, "begin_stopping", lambda _gui: calls.append("stopping"))
    monkeypatch.setattr(monitor_pkg, "_stop_all_workers", lambda _gui: calls.append("workers") or [])
    monkeypatch.setattr(_lifecycle, "drain_registered_tasks", lambda _gui: [])
    monkeypatch.setattr(_lifecycle, "has_registered_tasks", lambda _gui: False)
    monkeypatch.setattr(tick, "stop_global_tick", lambda _gui: calls.append("stop_tick"))
    monkeypatch.setattr("ui.main_gui_data.save_watch_list", lambda _gui: calls.append("watch_list"))
    monkeypatch.setattr(central, "sync_per_video_dbs_to_backup", lambda: calls.append("snapshot"))

    class _Snap:
        def __init__(self, _gui):
            pass

    monkeypatch.setattr(main_gui_events_runtime, "QTimer", SimpleNamespace(singleShot=lambda *_a: None))
    monkeypatch.setattr(main_gui_events_runtime, "QApplication", SimpleNamespace(quit=lambda: calls.append("quit")))
    monkeypatch.setattr(main_gui_events_runtime, "get_db", lambda: central, raising=False)
    monkeypatch.setattr("core.get_db", lambda: central)
    monkeypatch.setattr("core.get_bilibili_api", lambda: Mock(close=lambda: None))

    import algorithms.online_learner as online_learner

    monkeypatch.setattr(online_learner, "get_online_learner", lambda: Mock(save=lambda _p: None))
    import algorithms.weight_manager as weight_manager

    monkeypatch.setattr(weight_manager, "get_weight_manager", lambda: Mock(sync_save=lambda: None))
    import algorithms.registry as registry_mod

    monkeypatch.setattr(registry_mod.AlgorithmRegistry, "shutdown", classmethod(lambda _cls: None))
    import core.notification as notification_mod

    monkeypatch.setattr(notification_mod, "notification_manager", Mock(shutdown=lambda: None))
    import core.database.connection as connection_mod

    monkeypatch.setattr(connection_mod, "close_http_session", lambda: None)
    monkeypatch.setattr(_lifecycle, "close_video_dbs", lambda _gui: calls.append("close_dbs"))
    monkeypatch.setattr(_lifecycle, "mark_stopped", lambda _gui: calls.append("stopped"))

    main_gui_events_runtime.on_exit(gui)

    # Final snapshot must run after local transactions drain but before video DBs close.
    assert "snapshot" in calls
    assert calls.index("snapshot") < calls.index("close_dbs")
    assert gui._shutdown_finalized is True
