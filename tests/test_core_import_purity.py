"""Regression guard for side effects during the ``core`` package import."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_IMPORT_PROBE = r"""
import json
from pathlib import Path
import socket
import threading
import requests
from requests import adapters

def db_files():
    return sorted(str(path.relative_to(Path.cwd())) for path in Path.cwd().rglob("*.db"))

network_attempts = []
http_constructions = []
original_connect = socket.socket.connect
original_create_connection = socket.create_connection

def reject_connect(sock, address):
    network_attempts.append(repr(address))
    raise AssertionError("network access during import")

def reject_create_connection(address, *args, **kwargs):
    network_attempts.append(repr(address))
    raise AssertionError("network access during import")

socket.socket.connect = reject_connect
socket.create_connection = reject_create_connection
def reject_session(*args, **kwargs):
    http_constructions.append("Session")
    raise AssertionError("requests.Session construction during import")

def reject_adapter(*args, **kwargs):
    http_constructions.append("HTTPAdapter")
    raise AssertionError("HTTPAdapter construction during import")

requests.Session = reject_session
adapters.HTTPAdapter = reject_adapter
before_threads = {thread.ident for thread in threading.enumerate()}
before_db_files = db_files()

try:
    import core
    error = None
except Exception as exc:
    error = repr(exc)
finally:
    socket.socket.connect = original_connect
    socket.create_connection = original_create_connection

after_threads = {thread.ident for thread in threading.enumerate()}
print(json.dumps({
    "error": error,
    "new_db_files": sorted(set(db_files()) - set(before_db_files)),
    "new_threads": sorted(thread_id for thread_id in after_threads - before_threads if thread_id is not None),
    "network_attempts": network_attempts,
    "http_constructions": http_constructions,
}))
"""


def test_import_core_has_no_runtime_side_effects(tmp_path: Path) -> None:
    """Importing core must not initialize persistent or concurrent infrastructure."""
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PROJECT_ROOT) if not python_path else os.pathsep.join((str(PROJECT_ROOT), python_path))

    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    probe = json.loads(result.stdout)

    assert probe["error"] is None
    assert probe["new_db_files"] == []
    assert probe["new_threads"] == []
    assert probe["network_attempts"] == []
    assert probe["http_constructions"] == []


def test_http_session_is_lazy_thread_safe_and_reinitializes(monkeypatch) -> None:
    """The shared HTTP session is constructed once on demand and recreated after close."""
    from core.database import connection

    sessions = []
    construction_lock = threading.Lock()

    class FakeSession:
        def __init__(self) -> None:
            with construction_lock:
                sessions.append(self)
            self.headers = {}
            self.mounts = []
            self.closed = False

        def mount(self, prefix, adapter) -> None:
            self.mounts.append((prefix, adapter))

        def close(self) -> None:
            self.closed = True

    connection.close_http_session()
    monkeypatch.setattr(connection.requests, "Session", FakeSession)
    monkeypatch.setattr(connection, "HTTPAdapter", lambda **kwargs: kwargs)

    assert sessions == []

    threads = [threading.Thread(target=connection.get_http_session) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(sessions) == 1
    first_session = connection.get_http_session()
    assert first_session is sessions[0]
    assert first_session.headers["Referer"] == "https://www.bilibili.com/"
    assert {prefix for prefix, _adapter in first_session.mounts} == {"http://", "https://"}

    connection.close_http_session()

    assert first_session.closed
    second_session = connection.get_http_session()
    assert second_session is not first_session
    assert len(sessions) == 2
    connection.close_http_session()


def test_close_http_session_before_first_use_does_not_construct_session(monkeypatch) -> None:
    """Closing an unused HTTP session factory must remain a no-op."""
    from core.database import connection

    calls = []

    def fake_session():
        calls.append("Session")
        raise AssertionError("close_http_session must not create a session")

    connection.close_http_session()
    monkeypatch.setattr(connection.requests, "Session", fake_session)

    connection.close_http_session()

    assert calls == []
