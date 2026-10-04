"""Qt event-loop evidence for deferred shutdown without real application dependencies."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_deferred_teardown_retries_in_a_real_qt_event_loop() -> None:
    """A close event must defer teardown until a survivor clears, then quit once."""
    source_root = Path(__file__).resolve().parents[1]
    source = textwrap.dedent("""
        import sys
        import types

        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QWidget

        from ui import main_gui_events_runtime as runtime
        import ui.main_gui_data as gui_data
        import ui.main_gui_tick as tick
        import ui.monitor as monitor
        from ui.monitor import _lifecycle

        calls = {"stop_workers": 0, "db": 0, "api": 0, "registry": 0, "notification": 0, "http": 0}
        released = {"value": False}

        class FakeLog:
            def cleanup(self):
                pass

        class FakeFileLogger:
            def cancel_midnight_checker(self):
                pass

            def close(self):
                pass

        class Gui:
            def __init__(self):
                self.video_dbs = {}
                self._data_lock = __import__("threading").RLock()
                self.log_panel = FakeLog()
                self._file_logger = FakeFileLogger()

            def _stop_export_schedule(self):
                pass

        class FakeResource:
            def __init__(self, key):
                self.key = key

            def close(self):
                calls[self.key] += 1

        def stop_workers(gui):
            calls["stop_workers"] += 1
            return [] if released["value"] else ["slow-survivor"]

        tick.stop_global_tick = lambda gui: None
        gui_data.save_watch_list = lambda gui: None
        monitor._stop_all_workers = stop_workers
        runtime.drain_registered_tasks = lambda gui: []
        runtime.has_registered_tasks = lambda gui: False
        _lifecycle.close_video_dbs = lambda gui: True

        core = types.ModuleType("core")
        core.get_db = lambda: FakeResource("db")
        core.get_bilibili_api = lambda: FakeResource("api")
        sys.modules["core"] = core

        online = types.ModuleType("algorithms.online_learner")
        online.get_online_learner = lambda: types.SimpleNamespace(save=lambda path: None)
        weights = types.ModuleType("algorithms.weight_manager")
        weights.get_weight_manager = lambda: types.SimpleNamespace(sync_save=lambda: None)
        registry = types.ModuleType("algorithms.registry")
        registry.AlgorithmRegistry = types.SimpleNamespace(shutdown=lambda: calls.__setitem__("registry", calls["registry"] + 1))
        sys.modules["algorithms.online_learner"] = online
        sys.modules["algorithms.weight_manager"] = weights
        sys.modules["algorithms.registry"] = registry

        helpers = types.ModuleType("ui.helpers")
        helpers.project_path = lambda *parts: "unused"
        sys.modules["ui.helpers"] = helpers
        covers = types.ModuleType("ui.video_list_panel")
        covers._cover_session = types.SimpleNamespace(close=lambda: None)
        sys.modules["ui.video_list_panel"] = covers
        notification = types.ModuleType("core.notification")
        notification.notification_manager = types.SimpleNamespace(
            shutdown=lambda: calls.__setitem__("notification", calls["notification"] + 1)
        )
        connection = types.ModuleType("core.database.connection")
        connection.close_http_session = lambda: calls.__setitem__("http", calls["http"] + 1)
        sys.modules["core.notification"] = notification
        sys.modules["core.database.connection"] = connection

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        gui = Gui()

        class ClosingWindow(QWidget):
            def closeEvent(self, event):
                runtime.on_exit(gui)
                event.accept()

        window = ClosingWindow()
        window.show()
        QTimer.singleShot(0, window.close)
        QTimer.singleShot(40, lambda: released.__setitem__("value", True))
        QTimer.singleShot(2000, lambda: app.exit(9))
        exit_code = app.exec()

        assert exit_code == 0, exit_code
        assert calls["stop_workers"] >= 2, calls
        assert calls["db"] == calls["api"] == calls["registry"] == calls["notification"] == calls["http"] == 1, calls
        """)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONPATH"] = str(source_root) + os.pathsep + environment.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        env=environment,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
