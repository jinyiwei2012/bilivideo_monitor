"""DistDF — Distribution Distance Forecasting（基于分布对齐的预测）

思路（ICLR 2024 风格）：
- 视频的速度序列存在分布漂移（如冷启动 → 推荐期 → 衰减期）
- 用 Wasserstein 距离衡量近期窗口与历史全局分布的差异
- 当差异大（分布漂移中），近期窗口预测被全局均值"拉回"；当差异小（分布稳定），更信任近期

不需要训练（统计算法），可作为各 torch 模型的"分布锚点"补强。

降级链：scipy.stats.wasserstein_distance → numpy 自实现 → 近期均值。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_scipy_available = True
try:
    from scipy.stats import wasserstein_distance
except ImportError:
    _scipy_available = False


class DistdfAlignAlgorithm(BaseAlgorithm):
    """DistDF 分布对齐预测算法。"""

    name = "DistDF分布对齐"
    algorithm_id = "distdf_align"
    description = "基于 Wasserstein 距离的分布对齐预测（自适应近期/全局加权）"
    category = "高级分析"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self._min_seq_len = 8
        self._recent_window = 5

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = int(video_data.get("view_count", 0))
        history = video_data.get("history_data", [])
        if len(history) < self._min_seq_len:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})

        views, ts = self._extract_series(history)
        velocities = self._calc_velocity(views, ts)
        if len(velocities) < self._min_seq_len:
            v = float(velocities[-1]) if len(velocities) else 0.0
            return self._make_result(current_views, threshold, v, 0.35, "short_series", {})

        # 近期窗口 vs 全局分布
        recent = velocities[-self._recent_window :]
        global_pool = velocities

        recent_mean = float(np.mean(recent))
        global_mean = float(np.mean(global_pool))

        # Wasserstein 距离（归一化）
        w_dist = self._wasserstein(recent, global_pool)
        global_std = float(np.std(global_pool))
        # 归一化到 [0, 1]：距离越大表示越偏离全局分布
        w_norm = float(np.tanh(w_dist / (global_std + 1e-6)))

        # 自适应加权：分布稳定（w_norm 小）→ 信任近期；漂移（w_norm 大）→ 拉回全局
        # 但保留方向感：如果近期 > 全局且持续上升，仍稍微相信近期
        slope = float(np.polyfit(np.arange(len(recent)), recent, 1)[0]) if len(recent) > 1 else 0.0
        trend_factor = float(np.tanh(slope / (global_std + 1e-6)))

        # 加权：alpha 越接近 1 越信任近期
        alpha_base = 1.0 - 0.6 * w_norm  # 漂移大 → alpha 降低
        alpha = float(np.clip(alpha_base + 0.1 * trend_factor, 0.2, 0.9))
        predicted = alpha * recent_mean + (1.0 - alpha) * global_mean
        predicted = max(0.0, predicted)

        # 置信度：分布越稳定置信度越高
        confidence = float(np.clip(0.5 + 0.3 * (1 - w_norm), 0.4, 0.85))

        meta = {
            "reason": "distdf_align" if _scipy_available else "distdf_align_numpy",
            "method": "wasserstein_alignment",
            "w_distance": w_dist,
            "w_norm": w_norm,
            "recent_mean": recent_mean,
            "global_mean": global_mean,
            "alpha": alpha,
            "trend_factor": trend_factor,
        }
        return self._make_result(current_views, threshold, predicted, confidence, meta["reason"], meta)

    # ── 内部 ──────────────────────────────────────────

    @staticmethod
    def _wasserstein(a: np.ndarray, b: np.ndarray) -> float:
        if _scipy_available:
            try:
                return float(wasserstein_distance(a, b))
            except Exception as e:
                logger.debug("忽略异常: %s", e)
        # 1D Wasserstein-1 距离 = 累积分布差的 L1 积分
        a_sorted = np.sort(a)
        b_sorted = np.sort(b)
        n_a, n_b = len(a_sorted), len(b_sorted)
        # 用统一的 cdf 网格
        all_vals = np.concatenate([a_sorted, b_sorted])
        grid = np.unique(all_vals)
        if len(grid) < 2:
            return 0.0
        cdf_a = np.searchsorted(a_sorted, grid, side="right") / n_a
        cdf_b = np.searchsorted(b_sorted, grid, side="right") / n_b
        deltas = np.diff(grid)
        return float(np.sum(np.abs(cdf_a[:-1] - cdf_b[:-1]) * deltas))

    @staticmethod
    def _extract_series(history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        views, ts = [], []
        for e in history:
            v = e.get("view_count", e.get("view", 0))
            t = e.get("timestamp", 0)
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()
                except Exception:
                    continue
            if v and v > 0 and t and t > 0:
                views.append(float(v))
                ts.append(float(t))
        if len(views) > 1:
            order = np.argsort(ts)
            views = [views[i] for i in order]
            ts = [ts[i] for i in order]
        return np.array(views), np.array(ts)

    @staticmethod
    def _calc_velocity(views: np.ndarray, ts: np.ndarray) -> np.ndarray:
        if len(views) < 2:
            return np.array([])
        vs = []
        for i in range(1, len(views)):
            dt = (ts[i] - ts[i - 1]) / 3600.0
            if dt <= 0:
                continue
            vs.append((views[i] - views[i - 1]) / dt)
        return np.array(vs, dtype=np.float32)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            predicted_hours = 0 if remaining <= 0 else remaining / velocity
            if remaining <= 0:
                confidence = 1.0
        metadata = {"reason": reason}
        metadata.update(extra)
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=int(current_views),
            current_velocity=float(velocity),
            metadata=metadata,
            timestamp=datetime.now(),
        )
