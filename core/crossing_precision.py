"""播放量阶梯刷新下的过线时刻估算。

只有在目标附近进行快速采样，阶梯时刻的区间才可能窄到亚秒级。播放量在相邻
阶梯间平滑累积是插值的必要假设；刚性网格还假设局部刷新周期稳定。真实服务的
刷新节奏可能“换挡”，此时跨换挡区间的网格拟合应当失败并退回普通插值。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


def _epoch(value: datetime) -> float:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("step bracket datetimes must be timezone-aware")
    return value.timestamp()


def _at(epoch: float, template: datetime) -> datetime:
    return datetime.fromtimestamp(epoch, tz=template.tzinfo)


@dataclass(frozen=True)
class StepBracket:
    """一次计数阶梯的观测区间，真实阶梯时刻位于 ``(t_lower, t_upper]``。"""

    index: int
    t_lower: datetime
    t_upper: datetime
    v_before: int
    v_after: int

    def __post_init__(self) -> None:
        if _epoch(self.t_lower) > _epoch(self.t_upper):
            raise ValueError("step bracket lower bound exceeds upper bound")
        if self.v_after <= self.v_before:
            raise ValueError("step bracket must contain a positive counter increase")


@dataclass(frozen=True)
class CrossingEstimate:
    """普通插值得到的过线估计及其两条基准阶梯。"""

    target: int
    fraction: float
    estimate: datetime
    range_start: datetime
    range_end: datetime
    display_window_start: datetime
    display_window_end: datetime
    before_index: int
    after_index: int


@dataclass(frozen=True)
class GridFit:
    """局部刚性周期网格的可行周期范围。"""

    period_lo: float
    period_hi: float
    steps: tuple[StepBracket, ...]

    @property
    def period_s(self) -> float:
        return (self.period_lo + self.period_hi) / 2

    def project(self, index: int) -> tuple[datetime, datetime]:
        """返回指定阶梯索引在全部可行网格中的最小包络。"""
        candidates = _projection_candidates(self.steps, self.period_lo, self.period_hi)
        lower = min(_t0_lower(self.steps, period) + index * period for period in candidates)
        upper = max(_t0_upper(self.steps, period) + index * period for period in candidates)
        return _at(lower, self.steps[0].t_lower), _at(upper, self.steps[0].t_upper)


def estimate_crossing(steps: Sequence[StepBracket], target: int) -> CrossingEstimate | None:
    """在包围目标值的相邻阶梯间线性插值。

    展示窗口保留首次达到目标的阶梯观测区间，而估计范围由该阶梯与前一阶梯的
    时刻区间插值得到。计数增长若并非平滑发生，结果仅是模型估计而非实测时刻。
    """
    for before, after in zip(steps, steps[1:]):
        if after.v_before < target <= after.v_after:
            fraction = (target - after.v_before) / (after.v_after - after.v_before)
            lo = (1 - fraction) * _epoch(before.t_lower) + fraction * _epoch(after.t_lower)
            hi = (1 - fraction) * _epoch(before.t_upper) + fraction * _epoch(after.t_upper)
            midpoint = (lo + hi) / 2
            return CrossingEstimate(
                target=target,
                fraction=fraction,
                estimate=_at(midpoint, after.t_upper),
                range_start=_at(lo, after.t_lower),
                range_end=_at(hi, after.t_upper),
                display_window_start=after.t_lower,
                display_window_end=after.t_upper,
                before_index=before.index,
                after_index=after.index,
            )
    return None


def _period_bounds(steps: Sequence[StepBracket], p_min: float, p_max: float) -> tuple[float, float]:
    lo, hi = p_min, p_max
    for left in steps:
        for right in steps:
            coefficient = right.index - left.index
            if coefficient == 0:
                continue
            bound = (_epoch(right.t_upper) - _epoch(left.t_lower)) / coefficient
            if coefficient > 0:
                hi = min(hi, bound)
            else:
                lo = max(lo, bound)
    return lo, hi


def fit_rigid_grid(steps: Sequence[StepBracket], p_min: float = 30.0, p_max: float = 180.0) -> GridFit | None:
    """拟合 ``T_k = T0 + k*P`` 的可行周期区间。

    此实现解析求出与“粗到细网格扫描”相同的区间交集边界，速度更快且不会因
    扫描步长漏掉窄可行带。索引允许稀疏；若局部刷新 cadence 已换挡则返回 None。
    """
    if len(steps) < 2 or p_min <= 0 or p_max < p_min:
        return None
    ordered = tuple(steps)
    for step in ordered:
        _epoch(step.t_lower)
        _epoch(step.t_upper)
    lo, hi = _period_bounds(ordered, p_min, p_max)
    if lo > hi or _t0_lower(ordered, (lo + hi) / 2) > _t0_upper(ordered, (lo + hi) / 2):
        return None
    return GridFit(lo, hi, ordered)


def _t0_lower(steps: Sequence[StepBracket], period: float) -> float:
    return max(_epoch(step.t_lower) - step.index * period for step in steps)


def _t0_upper(steps: Sequence[StepBracket], period: float) -> float:
    return min(_epoch(step.t_upper) - step.index * period for step in steps)


def _projection_candidates(steps: Sequence[StepBracket], lo: float, hi: float) -> list[float]:
    candidates = [lo, hi]
    for left in steps:
        for right in steps:
            delta = left.index - right.index
            if delta == 0:
                continue
            period = (_epoch(left.t_lower) - _epoch(right.t_lower)) / delta
            if lo <= period <= hi:
                candidates.append(period)
            period = (_epoch(left.t_upper) - _epoch(right.t_upper)) / delta
            if lo <= period <= hi:
                candidates.append(period)
    return candidates


def refine_crossing(estimate: CrossingEstimate, fit: GridFit) -> tuple[datetime, datetime]:
    """用刚性网格投影的两条基准阶梯重新计算过线范围。"""
    before_lo, before_hi = fit.project(estimate.before_index)
    after_lo, after_hi = fit.project(estimate.after_index)
    fraction = estimate.fraction
    lo = (1 - fraction) * _epoch(before_lo) + fraction * _epoch(after_lo)
    hi = (1 - fraction) * _epoch(before_hi) + fraction * _epoch(after_hi)
    return _at(lo, before_lo), _at(hi, after_hi)
