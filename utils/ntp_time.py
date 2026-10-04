"""NTP time calibration with a monotonic, non-decreasing record clock.

Network access never occurs at import time.  HTTP Date remains available as an
explicit coarse diagnostic fallback, but it is not trusted to discipline the
record clock.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from statistics import median
from typing import Any, Mapping, Sequence

import requests

logger = logging.getLogger(__name__)

NTP_DELTA = 2_208_988_800
_NTP_ERA_SECONDS = 2**32
_MAX_DIAGNOSTIC_OFFSET_SECONDS = 30 * 24 * 3600
_MAX_AUTO_OFFSET_SECONDS = 5.0
_MAX_QUORUM_OFFSET_SECONDS = 5 * 60.0
_MAX_DELAY_SECONDS = 5.0
_CONSENSUS_RADIUS_SECONDS = 1.0
_MIN_QUORUM = 3
_SLEW_RATE = 0.1
_HTTP_MIN_UNCERTAINTY_MS = 500.0
_EXPIRED_AFTER_SECONDS = 48 * 3600.0
_HTTP_ENDPOINTS = ("https://www.baidu.com/", "https://www.bilibili.com/")
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}


@dataclass(frozen=True)
class NtpSyncResult:
    """Result of one synchronization operation."""

    ok: bool
    server: str
    offset_ms: float
    delay_ms: float
    source: str
    error: str


@dataclass(frozen=True)
class _NtpSample:
    """One internal time-source sample."""

    server: str
    offset: float
    delay: float


@dataclass
class _ClockState:
    """A wall-clock epoch advanced only by monotonic elapsed time."""

    base_epoch: float = 0.0
    base_monotonic: float = 0.0
    target_offset: float = 0.0
    pending: float = 0.0
    last_returned: float = 0.0


_state_lock = threading.Lock()
_sync_lock = threading.Lock()
_enabled = True
_apply_to_records = True
_servers = ["ntp.aliyun.com", "ntp.tencent.com", "cn.pool.ntp.org", "time.windows.com"]
_timeout_sec = 3.0
_http_fallback = False
_auto_sync_hours = 6.0
_synced = False
_offset_ms = 0.0
_last_sync_ts = 0.0
_last_sync_monotonic = 0.0
_server = ""
_source = ""
_last_error = ""
_quality = "local_unsynced"
_uncertainty_ms = 0.0
_abnormal = False
_calibrated_clock = _ClockState()
_record_clock = _ClockState()


def _pack_ntp_timestamp(unix_time: float) -> bytes:
    """Encode Unix time as an NTP 64-bit fixed-point timestamp."""
    ntp_time = unix_time + NTP_DELTA
    seconds = int(ntp_time) & 0xFFFFFFFF
    fraction = int((ntp_time - int(ntp_time)) * _NTP_ERA_SECONDS) & 0xFFFFFFFF
    return struct.pack("!II", seconds, fraction)


def _unpack_ntp_timestamp(raw: bytes, local_unix: float) -> float:
    """Decode an NTP timestamp, selecting the era nearest local time."""
    seconds, fraction = struct.unpack("!II", raw)
    local_ntp = local_unix + NTP_DELTA
    era = round((local_ntp - seconds) / _NTP_ERA_SECONDS)
    return era * _NTP_ERA_SECONDS + seconds + fraction / _NTP_ERA_SECONDS - NTP_DELTA


def _valid_sample(offset: float, delay: float) -> bool:
    """Reject malformed samples while retaining large offsets for diagnosis."""
    return delay >= 0 and delay <= _MAX_DELAY_SECONDS and abs(offset) <= _MAX_DIAGNOSTIC_OFFSET_SECONDS


def _query_server(host: str, timeout: float) -> _NtpSample | None:
    """Query and validate one NTP server."""
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.connect((host, 123))
        request = bytearray(48)
        request[0] = (4 << 3) | 3
        t1 = time.time()
        transmit = _pack_ntp_timestamp(t1)
        request[40:48] = transmit
        sock.send(bytes(request))
        reply = sock.recv(512)
        t4 = time.time()
        if len(reply) < 48:
            raise ValueError("响应长度不足")
        flags = reply[0]
        leap, version, mode = flags >> 6, (flags >> 3) & 7, flags & 7
        stratum = reply[1]
        if mode != 4 or version not in (3, 4) or leap == 3 or not 1 <= stratum <= 15:
            raise ValueError("响应头字段无效")
        if reply[24:32] != transmit:
            raise ValueError("Originate 时间戳不匹配")
        receive, sent = reply[32:40], reply[40:48]
        if receive == b"\0" * 8 or sent == b"\0" * 8:
            raise ValueError("响应时间戳为空")
        t2 = _unpack_ntp_timestamp(receive, t4)
        t3 = _unpack_ntp_timestamp(sent, t4)
        offset = ((t2 - t1) + (t3 - t4)) / 2
        delay = (t4 - t1) - (t3 - t2)
        if not _valid_sample(offset, delay):
            raise ValueError("偏移或延迟超出安全范围")
        return _NtpSample(host, offset, delay)
    except Exception as exc:
        logger.debug("NTP 服务器 %s 同步失败: %s", host, exc)
        return None
    finally:
        if sock is not None:
            sock.close()


def _http_date_sample(url: str, timeout: float) -> _NtpSample | None:
    """Sample an HTTP Date header as an explicitly coarse time source."""
    response: Any = None
    try:
        t0 = time.time()
        try:
            response = requests.head(url, headers=_HTTP_HEADERS, timeout=timeout, allow_redirects=True)
        except requests.RequestException:
            response = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout, stream=True, allow_redirects=True)
        t1 = time.time()
        parsed = parsedate_to_datetime(response.headers.get("Date", ""))
        if parsed is None:
            raise ValueError("HTTP 响应没有有效 Date 头")
        offset = parsed.timestamp() - (t0 + t1) / 2
        delay = t1 - t0
        if not _valid_sample(offset, delay):
            raise ValueError("HTTP 偏移或延迟超出安全范围")
        return _NtpSample(url, offset, delay)
    except Exception as exc:
        logger.debug("HTTP 时间源 %s 同步失败: %s", url, exc)
        return None
    finally:
        if response is not None:
            response.close()


def _consensus_cluster(samples: list[_NtpSample]) -> list[_NtpSample]:
    """Return the largest deterministic cluster around one observed offset."""
    clusters = [
        [sample for sample in samples if abs(sample.offset - center.offset) <= _CONSENSUS_RADIUS_SECONDS]
        for center in samples
    ]
    return max(clusters, key=lambda cluster: (len(cluster), -sum(item.delay for item in cluster)))


def _aggregate_samples(samples: list[_NtpSample]) -> tuple[_NtpSample, int, float]:
    """Aggregate a consensus cluster and estimate robust uncertainty in ms."""
    cluster = _consensus_cluster(samples)
    offset = float(median(sample.offset for sample in cluster))
    deviations = [abs(sample.offset - offset) for sample in cluster]
    mad_seconds = float(median(deviations)) if deviations else 0.0
    delay = float(median(sample.delay for sample in cluster))
    uncertainty_ms = max(1.0, 1.4826 * mad_seconds * 1000.0 + delay * 500.0)
    attribution = ", ".join(sorted(sample.server for sample in cluster))
    return _NtpSample(attribution, offset, delay), len(cluster), uncertainty_ms


def _advance_clock(clock: _ClockState, monotonic_now: float, wall_now: float) -> float:
    """Advance one discipline anchor, consuming pending correction at a bounded rate."""
    if clock.base_epoch == 0.0:
        clock.base_epoch = wall_now
        clock.base_monotonic = monotonic_now
    elapsed = max(0.0, monotonic_now - clock.base_monotonic)
    limit = elapsed * _SLEW_RATE
    adjustment = max(-limit, min(limit, clock.pending))
    value = clock.base_epoch + elapsed + adjustment
    clock.pending -= adjustment
    clock.base_epoch = value
    clock.base_monotonic = monotonic_now
    value = max(value, clock.last_returned)
    clock.last_returned = value
    return value


def _retarget_clock(clock: _ClockState, target_offset: float, monotonic_now: float, wall_now: float) -> None:
    """Change a clock target without stepping its returned epoch."""
    _advance_clock(clock, monotonic_now, wall_now)
    clock.pending += target_offset - clock.target_offset
    clock.target_offset = target_offset


def _retarget_clocks_locked() -> None:
    monotonic_now = time.monotonic()
    wall_now = time.time()
    trusted_offset = _offset_ms / 1000.0 if _quality == "ntp_verified" else 0.0
    calibrated_target = trusted_offset if _enabled else 0.0
    record_target = calibrated_target if _apply_to_records else 0.0
    _retarget_clock(_calibrated_clock, calibrated_target, monotonic_now, wall_now)
    _retarget_clock(_record_clock, record_target, monotonic_now, wall_now)


def _update_observation(
    sample: _NtpSample, quality: str, uncertainty_ms: float, *, apply: bool, error: str = ""
) -> NtpSyncResult:
    """Atomically publish an observation and optionally discipline the clocks."""
    global _synced, _offset_ms, _last_sync_ts, _last_sync_monotonic, _server, _source
    global _last_error, _quality, _uncertainty_ms, _abnormal
    now_wall = time.time()
    now_monotonic = time.monotonic()
    source = "ntp" if quality != "http_coarse" else "http"
    with _state_lock:
        _synced = quality in ("ntp_verified", "http_coarse")
        _offset_ms = sample.offset * 1000.0
        _last_sync_ts = now_wall
        _last_sync_monotonic = now_monotonic
        _server = sample.server
        _source = source
        _last_error = error
        _quality = quality
        _uncertainty_ms = uncertainty_ms
        _abnormal = quality == "ntp_verified" and abs(sample.offset) > _MAX_AUTO_OFFSET_SECONDS
        if apply:
            _retarget_clocks_locked()
    return NtpSyncResult(True, sample.server, sample.offset * 1000.0, sample.delay * 1000.0, source, error)


def _record_failure(error: str) -> NtpSyncResult:
    """Record failure while preserving the last successful calibration."""
    global _last_error
    with _state_lock:
        _last_error = error
    return NtpSyncResult(False, "", 0.0, 0.0, "", error)


def _record_untrusted_sample(sample: _NtpSample, uncertainty_ms: float, error: str) -> NtpSyncResult:
    """Record an untrusted observation without replacing a valid calibration."""
    global _synced, _offset_ms, _last_sync_ts, _last_sync_monotonic, _server, _source
    global _last_error, _quality, _uncertainty_ms, _abnormal
    with _state_lock:
        if _quality != "ntp_verified":
            _synced = False
            _offset_ms = sample.offset * 1000.0
            _last_sync_ts = time.time()
            _last_sync_monotonic = time.monotonic()
            _server = sample.server
            _source = "ntp"
            _quality = "local_unsynced"
            _uncertainty_ms = uncertainty_ms
            _abnormal = False
        _last_error = error
    return NtpSyncResult(False, sample.server, sample.offset * 1000.0, sample.delay * 1000.0, "ntp", error)


def _handle_ntp_samples(samples: list[_NtpSample]) -> NtpSyncResult:
    sample, cluster_size, uncertainty_ms = _aggregate_samples(samples)
    if cluster_size < _MIN_QUORUM:
        error = f"NTP 共识不足：仅 {cluster_size} 个一致样本，至少需要 {_MIN_QUORUM} 个"
        return _record_untrusted_sample(sample, uncertainty_ms, error)
    if abs(sample.offset) > _MAX_QUORUM_OFFSET_SECONDS:
        error = "NTP 偏移超过 5 分钟，仅记录诊断且未应用"
        return _record_untrusted_sample(sample, uncertainty_ms, error)
    error = "NTP 偏移异常（超过 5 秒），正以受限速率校准" if abs(sample.offset) > _MAX_AUTO_OFFSET_SECONDS else ""
    return _update_observation(sample, "ntp_verified", uncertainty_ms, apply=True, error=error)


def sync_now(servers: Sequence[str] | None = None, timeout: float | None = None) -> NtpSyncResult:
    """Synchronize now; all network and protocol errors become result objects."""
    if not _sync_lock.acquire(blocking=False):
        return NtpSyncResult(False, "", 0.0, 0.0, "", "sync already running")
    try:
        with _state_lock:
            configured_servers = list(_servers)
            configured_timeout = _timeout_sec
            use_http = _http_fallback
        hosts = [item.strip() for item in (servers or configured_servers) if isinstance(item, str) and item.strip()]
        used_timeout = timeout if isinstance(timeout, (int, float)) and timeout > 0 else configured_timeout
        samples: list[_NtpSample] = []
        if hosts:
            with ThreadPoolExecutor(max_workers=min(5, len(hosts))) as executor:
                futures = [executor.submit(_query_server, host, float(used_timeout)) for host in hosts]
                for future in as_completed(futures):
                    try:
                        sample = future.result()
                    except Exception as exc:
                        logger.debug("NTP 采样任务异常: %s", exc)
                        sample = None
                    if sample is not None:
                        samples.append(sample)
        if samples:
            return _handle_ntp_samples(samples)
        errors = ["所有 NTP 服务器均不可用"]
        if use_http:
            for endpoint in _HTTP_ENDPOINTS:
                sample = _http_date_sample(endpoint, float(used_timeout))
                if sample is not None:
                    uncertainty = max(_HTTP_MIN_UNCERTAINTY_MS, 500.0 + sample.delay * 1000.0)
                    return _update_observation(sample, "http_coarse", uncertainty, apply=False)
            errors.append("HTTP 时间源均不可用")
        return _record_failure("；".join(errors))
    except Exception as exc:
        logger.exception("NTP 同步发生未预期异常")
        return _record_failure(str(exc))
    finally:
        _sync_lock.release()


def get_status() -> dict[str, Any]:
    """Return a backward-compatible public status snapshot."""
    with _state_lock:
        age = max(0.0, time.monotonic() - _last_sync_monotonic) if _last_sync_monotonic else None
        stale_after = 2.0 * _auto_sync_hours * 3600.0
        stale = age is not None and age >= stale_after
        expired = age is not None and age >= _EXPIRED_AFTER_SECONDS
        displayed_quality = "local_unsynced" if expired else _quality
        pending_ms = max(abs(_calibrated_clock.pending), abs(_record_clock.pending)) * 1000.0
        return {
            "synced": _synced,
            "offset_ms": _offset_ms,
            "last_sync_ts": _last_sync_ts,
            "server": _server,
            "source": _source,
            "last_error": _last_error,
            "quality": displayed_quality,
            "active": _enabled and displayed_quality == "ntp_verified",
            "enabled": _enabled,
            "apply_to_records": _apply_to_records,
            "age_s": age,
            "stale": stale,
            "expired": expired,
            "freshness": "expired" if expired else ("stale" if stale else ("fresh" if age is not None else "never")),
            "slew_pending_ms": pending_ms,
            "uncertainty_ms": _uncertainty_ms,
            "abnormal": _abnormal,
            "auto_sync_hours": _auto_sync_hours,
            "sync_due": age is None or age >= _auto_sync_hours * 3600.0,
            "last_sync_monotonic": _last_sync_monotonic,
            "http_fallback": _http_fallback,
        }


def refresh_config(cfg: Mapping[str, Any]) -> None:
    """Refresh runtime configuration while preserving clock continuity."""
    global _enabled, _apply_to_records, _servers, _timeout_sec, _http_fallback, _auto_sync_hours
    section: Any = cfg.get("ntp", cfg) if isinstance(cfg, Mapping) else {}
    if not isinstance(section, Mapping):
        return
    with _state_lock:
        old_gating = (_enabled, _apply_to_records)
        if isinstance(section.get("enabled"), bool):
            _enabled = section["enabled"]
        if isinstance(section.get("apply_to_records"), bool):
            _apply_to_records = section["apply_to_records"]
        raw_servers = section.get("servers")
        if isinstance(raw_servers, (list, tuple)):
            valid_servers = [item.strip() for item in raw_servers if isinstance(item, str) and item.strip()]
            if valid_servers:
                _servers = valid_servers
        timeout_value = section.get("timeout_sec")
        if isinstance(timeout_value, (int, float)) and not isinstance(timeout_value, bool) and timeout_value > 0:
            _timeout_sec = float(timeout_value)
        hours_value = section.get("auto_sync_hours")
        if isinstance(hours_value, (int, float)) and not isinstance(hours_value, bool) and hours_value > 0:
            _auto_sync_hours = float(hours_value)
        if isinstance(section.get("http_fallback"), bool):
            _http_fallback = section["http_fallback"]
        if old_gating != (_enabled, _apply_to_records):
            _retarget_clocks_locked()


def _clock_now(clock: _ClockState) -> datetime:
    with _state_lock:
        value = _advance_clock(clock, time.monotonic(), time.time())
    return datetime.fromtimestamp(value)


def calibrated_now() -> datetime:
    """Return the continuously disciplined, non-decreasing calibrated clock."""
    return _clock_now(_calibrated_clock)


def record_now() -> datetime:
    """Return the continuously disciplined, non-decreasing record clock."""
    return _clock_now(_record_clock)


def _reset_state_for_tests() -> None:
    """Reset process state for deterministic offline tests."""
    global _enabled, _apply_to_records, _http_fallback, _auto_sync_hours, _synced, _offset_ms
    global _last_sync_ts, _last_sync_monotonic, _server, _source, _last_error, _quality
    global _uncertainty_ms, _abnormal, _calibrated_clock, _record_clock
    with _state_lock:
        _enabled = True
        _apply_to_records = True
        _http_fallback = False
        _auto_sync_hours = 6.0
        _synced = False
        _offset_ms = 0.0
        _last_sync_ts = 0.0
        _last_sync_monotonic = 0.0
        _server = ""
        _source = ""
        _last_error = ""
        _quality = "local_unsynced"
        _uncertainty_ms = 0.0
        _abnormal = False
        _calibrated_clock = _ClockState()
        _record_clock = _ClockState()
