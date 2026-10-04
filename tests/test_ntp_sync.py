"""NTP 时间同步离线测试。

所有网络交互均由假 socket 或内部采样接缝替代，测试不访问真实时间服务器。
"""

import struct
import threading
from typing import Any

import pytest

from utils import ntp_time


class _FakeClock:
    """可手动推进的 wall/monotonic 双时钟。"""

    def __init__(self, wall: float = 1_700_000_000.0, monotonic: float = 500.0) -> None:
        self.wall = wall
        self.monotonic = monotonic

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.monotonic += seconds


@pytest.fixture(autouse=True)
def _reset_ntp_state() -> None:
    ntp_time._reset_state_for_tests()


def _install_clock(monkeypatch: pytest.MonkeyPatch, clock: _FakeClock) -> None:
    monkeypatch.setattr(ntp_time.time, "time", lambda: clock.wall)
    monkeypatch.setattr(ntp_time.time, "monotonic", lambda: clock.monotonic)


def _samples(*offsets: float) -> list[ntp_time._NtpSample]:
    return [ntp_time._NtpSample(f"ntp-{index}", offset, 0.02) for index, offset in enumerate(offsets)]


class _FakeSocket:
    """记录请求并返回预构造 UDP 响应的 socket 替身。"""

    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.sent = b""

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, address: tuple[str, int]) -> None:
        self.address = address

    def send(self, data: bytes) -> int:
        self.sent = data
        return len(data)

    def recv(self, size: int) -> bytes:
        return self.reply

    def close(self) -> None:
        pass


def _reply(
    originate: bytes,
    *,
    flags: int = 0x24,
    stratum: int = 1,
    receive: bytes | None = None,
    transmit: bytes | None = None,
) -> bytes:
    packet = bytearray(48)
    packet[0] = flags
    packet[1] = stratum
    packet[24:32] = originate
    packet[32:40] = receive or ntp_time._pack_ntp_timestamp(1001.0)
    packet[40:48] = transmit or ntp_time._pack_ntp_timestamp(1002.0)
    return bytes(packet)


def test_request_packet_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """请求使用 VN=4、客户端模式，Transmit 字段是发送前的 T1。"""
    fake = _FakeSocket(b"")
    monkeypatch.setattr(ntp_time.socket, "socket", lambda *args: fake)
    monkeypatch.setattr(ntp_time.time, "time", lambda: 1000.0)
    assert ntp_time._query_server("ntp.example", 1.0) is None
    assert len(fake.sent) == 48 and fake.sent[0] == 0x23
    assert fake.sent[40:48] == ntp_time._pack_ntp_timestamp(1000.0)


def test_valid_reply_calculates_offset_and_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """有效响应会按 NTP 四时间戳公式计算偏移和时延。"""
    fake = _FakeSocket(b"")
    times = iter((1000.0, 1004.0))
    monkeypatch.setattr(ntp_time.socket, "socket", lambda *args: fake)
    monkeypatch.setattr(ntp_time.time, "time", lambda: next(times))
    fake.reply = _reply(ntp_time._pack_ntp_timestamp(1000.0))
    sample = ntp_time._query_server("ntp.example", 1.0)
    assert sample is not None
    assert sample.offset == pytest.approx(-0.5)
    assert sample.delay == pytest.approx(3.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"flags": 0x23},
        {"flags": 0xE4},
        {"stratum": 0},
        {"stratum": 16},
        {"receive": b"\0" * 8},
        {"transmit": b"\0" * 8},
    ],
)
def test_invalid_replies_are_rejected(monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]) -> None:
    """协议字段、空时间戳等无效响应均不得产生样本。"""
    fake = _FakeSocket(b"")
    monkeypatch.setattr(ntp_time.socket, "socket", lambda *args: fake)
    monkeypatch.setattr(ntp_time.time, "time", lambda: 1000.0)
    fake.reply = _reply(ntp_time._pack_ntp_timestamp(1000.0), **kwargs)
    assert ntp_time._query_server("ntp.example", 1.0) is None


def test_originate_mismatch_and_negative_delay_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Originate 回显不一致和负延迟都应被拒绝。"""
    fake = _FakeSocket(_reply(b"wrong---"))
    monkeypatch.setattr(ntp_time.socket, "socket", lambda *args: fake)
    monkeypatch.setattr(ntp_time.time, "time", lambda: 1000.0)
    assert ntp_time._query_server("ntp.example", 1.0) is None
    times = iter((1000.0, 1001.0))
    monkeypatch.setattr(ntp_time.time, "time", lambda: next(times))
    fake.reply = _reply(
        ntp_time._pack_ntp_timestamp(1000.0),
        receive=ntp_time._pack_ntp_timestamp(1000.0),
        transmit=ntp_time._pack_ntp_timestamp(1003.0),
    )
    assert ntp_time._query_server("ntp.example", 1.0) is None


def test_era_rollover_uses_nearest_era() -> None:
    """2036 翻卷后的 seconds=0 应按当前 era 解码。"""
    local = ntp_time._NTP_ERA_SECONDS - ntp_time.NTP_DELTA + 10.0
    raw = struct.pack("!II", 5, 0)
    assert ntp_time._unpack_ntp_timestamp(raw, local) == pytest.approx(local - 5.0)


def test_multi_server_drops_outlier_and_updates_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """三个一致样本形成法定共识，离群值不影响中位偏移。"""
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    samples = {
        "a": ntp_time._NtpSample("a", 0.10, 0.30),
        "b": ntp_time._NtpSample("b", 0.20, 0.10),
        "c": ntp_time._NtpSample("c", 0.15, 0.20),
        "bad": ntp_time._NtpSample("bad", 9.0, 0.01),
    }
    monkeypatch.setattr(ntp_time, "_query_server", lambda host, timeout: samples[host])
    result = ntp_time.sync_now(["a", "b", "c", "bad"], 1.0)
    assert result.ok and result.offset_ms == pytest.approx(150.0)
    assert set(result.server.split(", ")) == {"a", "b", "c"}
    assert ntp_time.get_status()["quality"] == "ntp_verified"

    initial = ntp_time.record_now().timestamp()
    clock.advance(1.0)
    after_one_second = ntp_time.record_now().timestamp()
    assert after_one_second - initial == pytest.approx(1.1)
    clock.advance(1.0)
    assert ntp_time.record_now().timestamp() - clock.wall == pytest.approx(0.15)


def test_all_fail_preserves_previous_good_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """同步失败不清除已经成功的校准数据，且永远返回结果而非抛异常。"""
    monkeypatch.setattr(ntp_time, "_query_server", lambda host, timeout: None)
    monkeypatch.setattr(ntp_time, "_http_fallback", False)
    with ntp_time._state_lock:
        ntp_time._synced = True
        ntp_time._offset_ms = 123.0
    result = ntp_time.sync_now(["none"], 1.0)
    assert not result.ok and result.error and ntp_time.get_status()["offset_ms"] == 123.0


def test_http_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """UDP 全失败时可回退到 HTTP Date 采样。"""
    monkeypatch.setattr(ntp_time, "_query_server", lambda host, timeout: None)
    monkeypatch.setattr(ntp_time, "_http_fallback", True)
    monkeypatch.setattr(ntp_time, "_http_date_sample", lambda url, timeout: ntp_time._NtpSample(url, 0.25, 0.1))
    result = ntp_time.sync_now(["none"], 1.0)
    assert result.ok and result.source == "http" and result.server == "https://www.baidu.com/"


def test_calibrated_and_record_time_gating(monkeypatch: pytest.MonkeyPatch) -> None:
    """门控切换通过 slew 收敛，且切换期间记录时间连续不回退。"""
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    assert ntp_time._handle_ntp_samples(_samples(4.9, 5.0, 5.1)).ok
    first = ntp_time.record_now().timestamp()
    clock.advance(50.0)
    calibrated = ntp_time.calibrated_now().timestamp()
    recorded = ntp_time.record_now().timestamp()
    assert calibrated - clock.wall == pytest.approx(5.0)
    assert recorded - clock.wall == pytest.approx(5.0)
    assert recorded > first

    ntp_time.refresh_config({"ntp": {"enabled": False, "apply_to_records": True}})
    before_disable = ntp_time.record_now().timestamp()
    clock.advance(50.0)
    assert ntp_time.calibrated_now().timestamp() - clock.wall == pytest.approx(0.0)
    after_disable = ntp_time.record_now().timestamp()
    assert after_disable >= before_disable

    ntp_time.refresh_config({"ntp": {"enabled": True, "apply_to_records": False}})
    clock.advance(50.0)
    assert ntp_time.calibrated_now().timestamp() - clock.wall == pytest.approx(5.0)
    assert ntp_time.record_now().timestamp() - clock.wall == pytest.approx(0.0)


def test_lower_offset_resync_never_moves_record_clock_backward(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    assert ntp_time._handle_ntp_samples(_samples(2.0, 2.1, 1.9)).ok
    start = ntp_time.record_now().timestamp()
    clock.advance(20.0)
    high = ntp_time.record_now().timestamp()
    assert high - clock.wall == pytest.approx(2.0)

    assert ntp_time._handle_ntp_samples(_samples(-2.0, -2.1, -1.9)).ok
    observed = [high]
    for _ in range(45):
        clock.advance(1.0)
        observed.append(ntp_time.record_now().timestamp())
    assert observed == sorted(observed)
    assert observed[-1] - clock.wall == pytest.approx(-2.0, abs=1e-5)
    assert observed[0] > start


def test_quorum_failure_preserves_previous_verified_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    assert ntp_time._handle_ntp_samples(_samples(0.2, 0.25, 0.3)).ok
    previous = ntp_time.get_status()

    failed = ntp_time._handle_ntp_samples(_samples(-4.0, 4.0))
    status = ntp_time.get_status()
    assert not failed.ok
    assert status["quality"] == "ntp_verified"
    assert status["offset_ms"] == previous["offset_ms"]
    assert "共识不足" in status["last_error"]

    ntp_time._reset_state_for_tests()
    _install_clock(monkeypatch, clock)
    assert not ntp_time._handle_ntp_samples(_samples(-4.0, 4.0)).ok
    assert ntp_time.get_status()["quality"] == "local_unsynced"
    assert ntp_time._handle_ntp_samples(_samples(0.1, 0.15, 0.2)).ok
    assert ntp_time.get_status()["quality"] == "ntp_verified"


def test_offset_over_five_minutes_is_diagnostic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    result = ntp_time._handle_ntp_samples(_samples(301.0, 301.1, 300.9))
    assert not result.ok
    assert ntp_time.get_status()["quality"] == "local_unsynced"
    initial = ntp_time.record_now().timestamp()
    clock.advance(10.0)
    assert ntp_time.record_now().timestamp() - initial == pytest.approx(10.0)


def test_http_coarse_is_opt_in_and_never_disciplines_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    monkeypatch.setattr(ntp_time, "_query_server", lambda host, timeout: None)
    http_calls: list[str] = []

    def sample_http(url: str, timeout: float) -> ntp_time._NtpSample:
        http_calls.append(url)
        return ntp_time._NtpSample(url, 2.0, 0.1)

    monkeypatch.setattr(ntp_time, "_http_date_sample", sample_http)
    assert not ntp_time.get_status()["http_fallback"]
    assert not ntp_time.sync_now(["none"], 1.0).ok
    assert not http_calls

    ntp_time.refresh_config({"http_fallback": True})
    assert ntp_time.sync_now(["none"], 1.0).ok
    assert ntp_time.get_status()["quality"] == "http_coarse"
    initial = ntp_time.record_now().timestamp()
    clock.advance(10.0)
    assert ntp_time.record_now().timestamp() - initial == pytest.approx(10.0)


def test_sync_age_freshness_uses_monotonic_time(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    ntp_time.refresh_config({"auto_sync_hours": 1.0})
    assert ntp_time._handle_ntp_samples(_samples(0.1, 0.15, 0.2)).ok
    clock.wall += 10_000.0
    clock.monotonic += 2 * 3600.0
    stale = ntp_time.get_status()
    assert stale["age_s"] == pytest.approx(2 * 3600.0)
    assert stale["freshness"] == "stale" and stale["active"]

    clock.monotonic += 46 * 3600.0
    expired = ntp_time.get_status()
    assert expired["freshness"] == "expired"
    assert expired["quality"] == "local_unsynced"
    assert not expired["active"]


def test_concurrent_record_now_is_non_decreasing(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    _install_clock(monkeypatch, clock)
    assert ntp_time._handle_ntp_samples(_samples(1.0, 1.1, 0.9)).ok
    values: list[float] = []

    def read_clock() -> None:
        for _ in range(100):
            values.append(ntp_time.record_now().timestamp())

    threads = [threading.Thread(target=read_clock) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(values) == 800
    assert values == sorted(values)


def test_refresh_config_ignores_bad_values() -> None:
    """缺失字段和错误类型不会引发异常或覆盖有效配置。"""
    ntp_time.refresh_config({"ntp": {"timeout_sec": "bad", "servers": [1, ""], "enabled": "yes"}})
    ntp_time.refresh_config({"ntp": None})
    ntp_time.refresh_config({})
    assert isinstance(ntp_time.get_status(), dict)
