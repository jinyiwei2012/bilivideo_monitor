"""Read-only repository behavior and active-root routing tests."""

import hashlib
import sqlite3

from core.database.connection import open_readonly_connection
from core.repositories import MonitorRepository, PredictionRepository, ReadModelRepository, ViewerRepository
from ui.monitor import _service


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_central(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE videos (bvid TEXT, title TEXT, updated_at TEXT);
        CREATE TABLE monitor_records (bvid TEXT, timestamp TEXT, view_count INTEGER);
        INSERT INTO videos VALUES ('BV2', 'second', '2026-01-02');
        INSERT INTO videos VALUES ('BV1', 'first', '2026-01-01');
        INSERT INTO monitor_records VALUES ('BV1', '2026-01-01', 5);
        INSERT INTO monitor_records VALUES ('BV1', '2026-01-02', 15);
        INSERT INTO monitor_records VALUES ('BV2', '2026-01-03', 20);
        """)
    connection.commit()
    connection.close()


def _create_video(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE predictions (algorithm TEXT, target_threshold INTEGER, created_at TEXT);
        CREATE TABLE weekly_scores (timestamp TEXT, total_score REAL);
        CREATE TABLE yearly_scores (timestamp TEXT, total_score REAL);
        INSERT INTO predictions VALUES ('a', 1, '2026-01-01');
        INSERT INTO predictions VALUES ('a', 1, '2026-01-03');
        INSERT INTO predictions VALUES ('b', 1, '2026-01-02');
        INSERT INTO weekly_scores VALUES ('2026-01-02', 11.0);
        INSERT INTO yearly_scores VALUES ('2026-01-02', 22.0);
        """)
    connection.commit()
    connection.close()


def test_read_model_and_monitor_modes_are_read_only(tmp_path):
    central = tmp_path / "central.db"
    _create_central(central)
    before = _digest(central)
    read_model = ReadModelRepository(str(central))
    assert [row["bvid"] for row in read_model.load_videos()] == ["BV2", "BV1"]
    assert read_model.load_watch_bvids() == ["BV2", "BV1"]

    repository = MonitorRepository(str(central))
    assert len(repository.query_central("最新N条", 2, 0, None, None)) == 2
    assert repository.query_central("播放首次大于X", 0, 10, "BV1", None)[0]["timestamp"] == "2026-01-02"
    assert len(repository.query_central("播放首次大于X", 0, 10, None, None)) == 2
    assert len(repository.query_central("播放量大于X", 0, 10, None, None)) == 2
    assert [row["timestamp"] for row in repository.query_central("播放趋势", 0, 0, None, "BV1")] == [
        "2026-01-01",
        "2026-01-02",
    ]
    assert len(repository.query_central("全量数据", 0, 0, "BV1", None)) == 2
    assert before == _digest(central)

    connection = open_readonly_connection(str(central))
    assert connection is not None
    try:
        try:
            connection.execute("INSERT INTO videos VALUES ('BV3', 'third', '2026-01-04')")
        except sqlite3.OperationalError:
            pass
        else:
            raise AssertionError("read-only connection accepted a write")
    finally:
        connection.close()


def test_monitor_repository_deletes_with_central_and_video_identities(tmp_path):
    database = tmp_path / "monitor.db"
    _create_central(database)
    repository = MonitorRepository(str(database))

    repository.delete_monitor_records([("BV1", "2026-01-02")], by_bvid=True)
    repository.delete_monitor_records([("ignored", "2026-01-03")], by_bvid=False)

    connection = sqlite3.connect(database)
    try:
        rows = connection.execute("SELECT bvid, timestamp FROM monitor_records ORDER BY timestamp").fetchall()
    finally:
        connection.close()
    assert rows == [("BV1", "2026-01-01")]


def test_viewer_repository_persists_latest_snapshot(monkeypatch, tmp_path):
    root = tmp_path / "viewer-data"
    monkeypatch.setattr("core.database.data_layout.backup_root", lambda: str(root))
    timestamps = iter(["2026-01-01 00:00:00", "2026-01-01 00:00:01"])
    monkeypatch.setattr("core.repositories.viewer.now_ts", lambda: next(timestamps))
    repository = ViewerRepository()
    try:
        repository.write("BV1", 10, 6, 4)
        repository.write("BV1", 20, 12, 8)
        assert repository.read_latest() == {"BV1": {"total": 20, "web": 12, "app": 8}}
    finally:
        repository.close()


def test_prediction_repository_preserves_batch_prediction_preload(tmp_path):
    video = tmp_path / "video.db"
    _create_video(video)
    before = _digest(video)
    cache = {"conns": {}, "preds": {}}
    repository = PredictionRepository(str(video))
    first = repository.load_extra_data("2026-01-02", cache)
    second = repository.load_extra_data("2026-01-03", cache)
    try:
        assert [row["algorithm"] for row in first["_predictions"]] == ["a", "b"]
        assert len(second["_predictions"]) == 2
        assert first["weekly_total_score"] == 11.0
        assert first["yearly_total_score"] == 22.0
        assert len(cache["preds"]) == 1
        assert len(cache["conns"]) == 1
    finally:
        for connection in cache["conns"].values():
            connection.close()
    assert before == _digest(video)


def test_watch_list_uses_read_model_repository(monkeypatch, tmp_path):
    central = tmp_path / "data" / "bilibili_monitor.db"
    central.parent.mkdir()
    _create_central(central)

    class FakeReadModelRepository(ReadModelRepository):
        def __init__(self):
            super().__init__(str(central))

    monkeypatch.setattr("core.repositories.ReadModelRepository", FakeReadModelRepository)
    assert _service._load_watch_list_from_db() == ["BV2", "BV1"]
