from datetime import datetime, timedelta, timezone

import pytest

from ui.monitor._precision_watch import PrecisionWatchManager

TZ = timezone(timedelta(hours=8))


class FakeRuntime:
    def __init__(self, values: list[int], rtts: list[float] | None = None) -> None:
        self.now = datetime(2026, 10, 4, 11, 16, 0, tzinfo=TZ)
        self.mono = 0.0
        self.values = iter(values)
        self.rtts = iter(rtts or [0.0] * len(values))
        self.sleeps: list[float] = []

    def clock(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)
        self.mono += seconds

    def monotonic(self) -> float:
        return self.mono

    def fetch(self, _bvid: str) -> dict[str, dict[str, int]]:
        rtt = next(self.rtts)
        self.now += timedelta(seconds=rtt)
        self.mono += rtt
        return {"stat": {"view": next(self.values)}}


def test_run_watch_adapts_interval_and_persists_crossing() -> None:
    runtime = FakeRuntime([9_999_400, 9_999_900, 10_000_050, 10_000_100])
    saved: list[tuple[str, object]] = []
    notified: list[tuple[str, object]] = []
    manager = PrecisionWatchManager(
        runtime.fetch,
        lambda bvid, event: saved.append((bvid, event)),
        lambda bvid, event: notified.append((bvid, event)),
        clock=runtime.clock,
        monotonic=runtime.monotonic,
        sleep=runtime.sleep,
        near_remaining=10_000,
        close_remaining=1_000,
        interval_near_s=5,
        interval_close_s=1,
        max_requests=4,
        stop_margin_s=1,
    )

    assert manager.run_watch("BV1TEST123", 9_995_000, 10_000_000)
    assert runtime.sleeps == [5, 1, 1, 1]
    assert len(saved) == len(notified) == 1
    event = saved[0][1]
    assert isinstance(event, dict)
    assert event["threshold"] == 10_000_000
    assert event["display_window_start"] < event["display_window_end"]


def test_offer_enforces_range_dedupe_and_capacity_without_starting_threads(monkeypatch) -> None:
    started: list[object] = []

    def fake_start(thread: object) -> None:
        started.append(thread)

    monkeypatch.setattr("threading.Thread.start", fake_start)
    manager = PrecisionWatchManager(lambda _bvid: 0, lambda _bvid, _event: None, max_active=1)

    assert not manager.offer("BV1FAR1234", 1, 20_000)
    assert manager.offer("BV1NEAR123", 9_995, 10_000)
    assert not manager.offer("BV1NEAR123", 9_996, 10_000)
    assert not manager.offer("BV1OTHER12", 9_995, 10_000)
    assert len(started) == 1


def test_run_watch_respects_request_cap_when_target_not_crossed() -> None:
    runtime = FakeRuntime([100, 101, 102])
    saved: list[object] = []
    manager = PrecisionWatchManager(
        runtime.fetch,
        lambda _bvid, event: saved.append(event),
        clock=runtime.clock,
        monotonic=runtime.monotonic,
        sleep=runtime.sleep,
        max_requests=3,
    )

    assert not manager.run_watch("BV1TEST123", 99, 1_000)
    assert runtime.sleeps == [1, 1, 1]
    assert saved == []


def test_run_watch_attributes_receive_time_and_applies_half_rtt_correction() -> None:
    runtime = FakeRuntime([150, 250, 300], rtts=[0.2, 0.4, 0.6])
    saved: list[dict[str, object]] = []
    manager = PrecisionWatchManager(
        runtime.fetch,
        lambda _bvid, event: saved.append(dict(event)),
        clock=runtime.clock,
        monotonic=runtime.monotonic,
        sleep=runtime.sleep,
        interval_near_s=1,
        interval_close_s=1,
        max_requests=3,
        stop_margin_s=1,
    )

    assert manager.run_watch("BV1TEST123", 100, 200)
    event = saved[0]
    assert event["rtt_median_us"] == 400_000
    estimate = event["estimate"]
    corrected = event["corrected_estimate"]
    assert isinstance(estimate, datetime)
    assert isinstance(corrected, datetime)
    # 中点位移由两条接收时刻的修正加权而来；首条下界为不含网络修正的种子值，
    # 因此中点位移约为 0.1s（其上界位移为 0.15s）。
    assert (estimate - corrected).total_seconds() == pytest.approx(0.1, abs=0.01)
