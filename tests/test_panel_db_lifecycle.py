"""Panel database work must share the monitor runtime lifetime lease."""

import threading

from ui.dashboard_mode import _collect_health_alerts
from ui.online_viewers_panel import OnlineViewersPanel

from ui.monitor._lifecycle import (
    begin_stopping,
    close_video_dbs,
    drain_registered_tasks,
    set_video_db,
    start_registered_task,
    use_video_db,
)


class _Gui:
    def __init__(self) -> None:
        self.video_dbs = {}
        self._data_lock = threading.RLock()


class _BlockingDb:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.entered = entered
        self.release = release
        self.closed = False

    def read(self) -> None:
        self.entered.set()
        self.release.wait(1)
        if self.closed:
            raise RuntimeError("database closed during panel read")

    def close(self) -> None:
        self.closed = True


def test_panel_style_registered_task_rejects_after_stopping() -> None:
    """The entrypoint used by panel workers atomically refuses shutdown work."""
    gui = _Gui()
    begin_stopping(gui)
    assert start_registered_task(gui, lambda: None, name="score-history:BV1") is None


def test_panel_style_task_lease_blocks_database_close() -> None:
    """A registered panel task retains its DB lease until its read completes."""
    gui = _Gui()
    entered = threading.Event()
    release = threading.Event()
    db = _BlockingDb(entered, release)
    assert set_video_db(gui, "BV1", db)

    def panel_worker() -> None:
        use_video_db(gui, "BV1", lambda video_db: video_db.read())

    assert start_registered_task(gui, panel_worker, name="danmaku:BV1") is not None
    assert entered.wait(1)
    assert not close_video_dbs(gui)
    assert not db.closed
    release.set()
    assert drain_registered_tasks(gui) == []
    assert close_video_dbs(gui)
    assert db.closed


def test_dashboard_health_collection_uses_shutdown_aware_db_lease() -> None:
    """Dashboard health work must not query a handle after STOPPING starts."""

    class _Db:
        def __init__(self) -> None:
            self.calls = 0

        def get_all_records(self, limit: int) -> list:
            self.calls += 1
            return []

    gui = _Gui()
    db = _Db()
    gui.monitored_videos = [{"bvid": "BV1", "title": "video"}]
    assert set_video_db(gui, "BV1", db)
    begin_stopping(gui)
    assert _collect_health_alerts(gui) == []
    assert db.calls == 0


def test_online_viewer_submission_stops_before_api_futures() -> None:
    """A STOPPING runtime prevents the online-viewer panel from submitting API work."""

    class _Pool:
        def __init__(self) -> None:
            self.submissions = 0

        def submit(self, *args):
            self.submissions += 1
            raise AssertionError("STOPPING must not submit API work")

    gui = _Gui()
    begin_stopping(gui)
    panel = OnlineViewersPanel.__new__(OnlineViewersPanel)
    panel.gui = gui
    panel._fetch_pool = _Pool()
    panel._wait_viewer_futures([("BV1", 1)])
    assert panel._fetch_pool.submissions == 0
