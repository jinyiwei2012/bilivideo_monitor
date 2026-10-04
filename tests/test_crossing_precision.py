from datetime import datetime, timedelta, timezone

import pytest

from core.crossing_precision import StepBracket, estimate_crossing, fit_rigid_grid, refine_crossing

TZ = timezone(timedelta(hours=8))
TARGET = 10_000_000


def _time(value: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-04T{value}+08:00")


def _step(index: int, lower: str, upper: str, before: int, after: int) -> StepBracket:
    return StepBracket(index, _time(lower), _time(upper), before, after)


GROUP_A = (
    _step(1, "11:10:00.996", "11:10:06.327", 9_998_724, 9_998_875),
    _step(2, "11:11:17.683", "11:11:22.821", 9_998_875, 9_999_044),
    _step(3, "11:12:34.206", "11:12:39.305", 9_999_044, 9_999_227),
    _step(4, "11:13:45.708", "11:13:50.806", 9_999_227, 9_999_450),
    _step(5, "11:15:02.173", "11:15:07.272", 9_999_450, 9_999_670),
    _step(6, "11:16:18.671", "11:16:23.767", 9_999_670, 9_999_878),
    _step(7, "11:17:35.184", "11:17:40.294", 9_999_878, 10_000_137),
)

GROUP_B = (
    _step(45, "12:05:33.726", "12:05:38.827", 10_007_143, 10_007_307),
    _step(46, "12:06:45.168", "12:06:50.275", 10_007_307, 10_007_471),
    _step(47, "12:08:01.705", "12:08:06.815", 10_007_471, 10_007_626),
    _step(48, "12:09:18.253", "12:09:23.344", 10_007_626, 10_007_779),
)

GROUP_C = (
    _step(51, "12:13:06.123", "12:13:07.214", 10_008_088, 10_008_239),
    _step(52, "12:14:20.745", "12:14:21.898", 10_008_239, 10_008_377),
    _step(53, "12:15:35.836", "12:15:36.865", 10_008_377, 10_008_530),
    _step(54, "12:16:51.048", "12:16:52.028", 10_008_530, 10_008_672),
    _step(55, "12:18:06.603", "12:18:07.774", 10_008_672, 10_008_819),
    _step(56, "12:19:22.969", "12:19:24.034", 10_008_819, 10_008_966),
)


def _assert_time(actual: datetime, expected: str, tolerance_s: float = 0.02) -> None:
    assert abs((actual - _time(expected)).total_seconds()) <= tolerance_s


def test_estimate_crossing_matches_regression_fixture() -> None:
    estimate = estimate_crossing(GROUP_A, TARGET)

    assert estimate is not None
    _assert_time(estimate.display_window_start, "11:17:35.184")
    _assert_time(estimate.display_window_end, "11:17:40.294")
    _assert_time(estimate.range_start, "11:16:54.712")
    _assert_time(estimate.range_end, "11:16:59.814")


def test_rigid_grid_and_refined_crossing_match_regression_fixture() -> None:
    estimate = estimate_crossing(GROUP_A, TARGET)
    fit = fit_rigid_grid(GROUP_A + GROUP_B)

    assert estimate is not None
    assert fit is not None
    assert fit.period_lo == pytest.approx(75.681, abs=0.01)
    assert fit.period_hi == pytest.approx(75.723, abs=0.01)
    refined_start, refined_end = refine_crossing(estimate, fit)
    _assert_time(refined_start, "11:16:56.974")
    _assert_time(refined_end, "11:16:57.868")


def test_grid_rejects_cadence_change() -> None:
    assert fit_rigid_grid(GROUP_A + GROUP_B + GROUP_C) is None


def test_invalid_brackets_and_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        StepBracket(1, _time("11:00:01"), _time("11:00:00"), 1, 2)
    with pytest.raises(ValueError):
        StepBracket(1, _time("11:00:00"), _time("11:00:01"), 2, 2)
    with pytest.raises(ValueError):
        StepBracket(1, datetime(2026, 10, 4), datetime(2026, 10, 4, 0, 0, 1), 1, 2)
