"""FileLogger 日志保留策略测试：保留 / 压缩 / 删除三态与 running.log 保护。"""

import gzip
import os
from datetime import datetime, timedelta

from utils.file_logger import FileLogger


def _touch_aged(path: str, days: float) -> None:
    """把文件 mtime 设为 days 天前。"""
    ts = (datetime.now() - timedelta(days=days)).timestamp()
    os.utime(path, (ts, ts))


def _make_logger(tmp_path, monkeypatch):
    monkeypatch.setattr(FileLogger, "_open_file", lambda self, now=None: None)
    return FileLogger(str(tmp_path))


def test_recent_logs_are_kept_as_is(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch)
    recent = tmp_path / "20260101_010101-020202.log"
    recent.write_text("fresh", encoding="utf-8")
    _touch_aged(str(recent), 2)

    logger._apply_retention(keep_days=7, compress_days=30)

    assert recent.exists()
    assert not (tmp_path / "20260101_010101-020202.log.gz").exists()


def test_mid_age_logs_are_compressed(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch)
    mid = tmp_path / "20260101_010101-020202.log"
    mid.write_text("compress me", encoding="utf-8")
    _touch_aged(str(mid), 15)

    logger._apply_retention(keep_days=7, compress_days=30)

    gz = tmp_path / "20260101_010101-020202.log.gz"
    assert not mid.exists()
    assert gz.exists()
    with gzip.open(str(gz), "rb") as f:
        assert f.read() == b"compress me"


def test_old_logs_and_archives_are_deleted(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch)
    old_log = tmp_path / "20250101_010101-020202.log"
    old_log.write_text("old", encoding="utf-8")
    _touch_aged(str(old_log), 60)
    old_gz = tmp_path / "20240101_010101-020202.log.gz"
    with gzip.open(str(old_gz), "wb") as f:
        f.write(b"ancient")
    _touch_aged(str(old_gz), 60)

    logger._apply_retention(keep_days=7, compress_days=30)

    assert not old_log.exists()
    assert not old_gz.exists()


def test_running_log_is_never_touched(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch)
    running = tmp_path / "20200101_010101-running.log"
    running.write_text("live", encoding="utf-8")
    _touch_aged(str(running), 999)

    logger._apply_retention(keep_days=7, compress_days=30)

    assert running.exists()
    assert not (tmp_path / "20200101_010101-running.log.gz").exists()


def test_retention_is_invoked_after_archive(tmp_path, monkeypatch):
    """归档（改名）后应自动触发保留策略。"""
    monkeypatch.setattr(FileLogger, "_open_file", lambda self, now=None: None)
    logger = FileLogger(str(tmp_path))
    calls = []
    monkeypatch.setattr(logger, "_apply_retention", lambda *a, **k: calls.append("retention"))

    live = tmp_path / "20260101_010101-running.log"
    handle = open(str(live), "a", encoding="utf-8")
    logger._file = handle
    logger._start_dt = datetime(2026, 1, 1, 1, 1, 1)
    logger._current_date = datetime(2026, 1, 1).date()

    logger._rename_to_finished()

    assert calls == ["retention"]
    if logger._file is not None:
        logger._file.close()
