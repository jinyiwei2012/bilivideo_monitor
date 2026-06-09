"""
DistDF - 分布距离预测算法 (Distribution Distance Forecasting)
=============================================================

基于 Wasserstein 距离的分布对齐预测方法（ICLR 2024 风格）。

核心思路：
    1. 视频的速度序列存在分布漂移（冷启动 -> 推荐期 -> 衰减期）
    2. 用 Wasserstein 距离（推土机距离）衡量近期窗口与历史全局分布的差异
    3. 当差异大（分布漂移中），近期窗口预测被全局均值"拉回"以降低过激预测
    4. 当差异小（分布稳定），更信任近期窗口数据

特点：
    - 纯统计算法，不需要训练，可作为 torch 模型的"分布锚点"补强
    - 自适应加权：平衡近期窗口和全局分布的信息
    - 降级链：scipy.stats.wasserstein_distance -> numpy 自实现 -> 近期均值

参考文献：
    Distribution Distance Aligned Forecasting, ICLR 2024
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# 检查 scipy 是否可用，不可用时使用 numpy 自实现的 Wasserstein 距离
_scipy_available = True
try:
    from scipy.stats import wasserstein_distance
except ImportError:
    _scipy_available = False


class DistdfAlignAlgorithm(BaseAlgorithm):
    """
    DistDF 分布对齐预测算法

    主要功能：
        - 使用 Wasserstein 距离衡量近期窗口与全局分布的差异
        - 根据分布差异程度自适应调整近期/全局的加权比例
        - 考虑趋势方向（上升/下降），保留方向感，避免过度拉回

    加权策略：
        - alpha = 1.0 - 0.6 * w_norm + 0.1 * trend_factor
        - 分布稳定（w_norm 小）-> alpha 接近 1，信任近期
        - 分布漂移（w_norm 大）-> alpha 接近 0.2，拉回全局
        - 近期在上升（trend_factor > 0）-> alpha 稍微增加
    """

    name = "DistDF分布对齐"
    algorithm_id = "distdf_align"
    description = "基于 Wasserstein 距离的分布对齐预测（自适应近期/全局加权）"
    category = "高级分析"
    default_weight = 1.2

    def __init__(self):
        """
        初始化 DistDF 分布对齐算法

        设置关键参数：
            _min_seq_len (int)  : 8 (最少需要的历史速度点数量)
            _recent_window (int): 5 (近期窗口大小，用于计算近期均值)
        """
        super().__init__()
        self._min_seq_len = 8  # 最少需要 8 个速度点才能可靠计算分布距离
        self._recent_window = 5  # 近期窗口取最近 5 个速度点

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行分布对齐预测

        算法流程：
            1. 提取播放量序列并计算速度序列
            2. 取近期窗口（最后 5 个点）和全局池（所有点）
            3. 计算近期窗口与全局分布的 Wasserstein 距离（归一化）
            4. 计算近期窗口的趋势斜率（保留方向感）
            5. 自适应加权：漂移大时拉回全局，稳定时信任近期
            6. 置信度：分布越稳定置信度越高

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = int(video_data.get("view_count", 0))
        history = video_data.get("history_data", [])
        # 数据不足：使用简单速度预测
        if len(history) < self._min_seq_len:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})

        views, ts = self._extract_series(history)
        velocities = self._calc_velocity(views, ts)
        if len(velocities) < self._min_seq_len:
            v = float(velocities[-1]) if len(velocities) else 0.0
            return self._make_result(current_views, threshold, v, 0.35, "short_series", {})

        # 近期窗口 vs 全局分布
        recent = velocities[-self._recent_window :]  # 最后 5 个速度点
        global_pool = velocities  # 所有速度点

        recent_mean = float(np.mean(recent))  # 近期均值
        global_mean = float(np.mean(global_pool))  # 全局均值

        # Wasserstein 距离（归一化到 [0, 1]）
        w_dist = self._wasserstein(recent, global_pool)
        global_std = float(np.std(global_pool))
        # 用 tanh 归一化：距离越大，w_norm 越接近 1，表示越偏离全局分布
        w_norm = float(np.tanh(w_dist / (global_std + 1e-6)))

        # 自适应加权：分布稳定（w_norm 小）-> 信任近期；漂移（w_norm 大）-> 拉回全局
        # 但保留方向感：如果近期 > 全局且持续上升，仍稍微相信近期
        slope = float(np.polyfit(np.arange(len(recent)), recent, 1)[0]) if len(recent) > 1 else 0.0
        trend_factor = float(np.tanh(slope / (global_std + 1e-6)))  # 趋势因子

        # 加权：alpha 越接近 1 越信任近期
        alpha_base = 1.0 - 0.6 * w_norm  # 漂移大 -> alpha 降低，回归全局均值
        alpha = float(np.clip(alpha_base + 0.1 * trend_factor, 0.2, 0.9))  # 钳制在 [0.2, 0.9]
        predicted = alpha * recent_mean + (1.0 - alpha) * global_mean  # 加权融合预测速度
        predicted = max(0.0, predicted)

        # 置信度：分布越稳定 -> ALPHA 越高 -> (1-w_norm) 越大 -> 置信度越高
        confidence = float(np.clip(0.5 + 0.3 * (1 - w_norm), 0.4, 0.85))

        meta = {
            "reason": "distdf_align" if _scipy_available else "distdf_align_numpy",
            "method": "wasserstein_alignment",
            "w_distance": w_dist,  # 原始 Wasserstein 距离
            "w_norm": w_norm,  # 归一化后的距离
            "recent_mean": recent_mean,
            "global_mean": global_mean,
            "alpha": alpha,  # 近期权重
            "trend_factor": trend_factor,  # 趋势因子
        }
        return self._make_result(current_views, threshold, predicted, confidence, meta["reason"], meta)

    # ── 内部方法 ──────────────────────────────────────────

    @staticmethod
    def _wasserstein(a: np.ndarray, b: np.ndarray) -> float:
        """
        计算两个一维分布之间的 Wasserstein-1（Earth Mover's Distance）距离

        Wasserstein-1 距离在 1D 情况下等于两个分布的 CDF 差的 L1 积分：
            W_1(P, Q) = integral |CDF_P(x) - CDF_Q(x)| dx

        优先使用 scipy 实现，不可用时使用 numpy 自实现的 CDF 积分法。

        Args:
            a (np.ndarray): 分布 a 的样本
            b (np.ndarray): 分布 b 的样本

        Returns:
            float: Wasserstein 距离值（非负）
        """
        if _scipy_available:
            try:
                return float(wasserstein_distance(a, b))
            except Exception as e:
                logger.debug("Wasserstein 距离计算忽略异常: %s", e)
        # numpy 自实现：1D Wasserstein-1 距离 = 累积分布差的 L1 积分
        a_sorted = np.sort(a)
        b_sorted = np.sort(b)
        n_a, n_b = len(a_sorted), len(b_sorted)
        # 用统一的 CDF 网格
        all_vals = np.concatenate([a_sorted, b_sorted])
        grid = np.unique(all_vals)  # 合并去重后的值作为 CDF 评估网格
        if len(grid) < 2:
            return 0.0
        # 经验 CDF：searchsorted 返回每个网格值在排序数组中的插入位置
        cdf_a = np.searchsorted(a_sorted, grid, side="right") / n_a
        cdf_b = np.searchsorted(b_sorted, grid, side="right") / n_b
        deltas = np.diff(grid)  # 网格间距
        # 积分 = sum(|CDF差| * 网格间距)
        return float(np.sum(np.abs(cdf_a[:-1] - cdf_b[:-1]) * deltas))

    @staticmethod
    def _extract_series(history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史数据列表中提取播放量和时间戳序列

        处理多种时间戳格式（datetime 对象、字符串、数值），
        提取后按时间升序排序。

        Args:
            history (List[Dict]): 历史数据点列表

        Returns:
            Tuple[np.ndarray, np.ndarray]: (播放量数组, 时间戳数组)
        """
        views, ts = [], []
        for e in history:
            v = e.get("view_count", e.get("view", 0))
            t = e.get("timestamp", 0)
            # 处理多种时间戳格式
            if hasattr(t, "timestamp"):
                t = t.timestamp()  # datetime 对象转为 Unix 时间戳
            elif isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()  # ISO 格式字符串解析
                except Exception:
                    continue  # 解析失败则跳过
            if v and v > 0 and t and t > 0:
                views.append(float(v))
                ts.append(float(t))
        # 按时间升序排序
        if len(views) > 1:
            order = np.argsort(ts)
            views = [views[i] for i in order]
            ts = [ts[i] for i in order]
        return np.array(views), np.array(ts)

    @staticmethod
    def _calc_velocity(views: np.ndarray, ts: np.ndarray) -> np.ndarray:
        """
        计算速度序列：相邻时间点的播放量增量除以时间增量（小时）

        公式：velocity_i = (views[i] - views[i-1]) / ((ts[i] - ts[i-1]) / 3600)

        Args:
            views (np.ndarray): 播放量数组
            ts (np.ndarray)   : 时间戳数组

        Returns:
            np.ndarray: 速度数组（播放量/小时）
        """
        if len(views) < 2:
            return np.array([])
        vs = []
        for i in range(1, len(views)):
            dt = (ts[i] - ts[i - 1]) / 3600.0  # 时间差转换为小时
            if dt <= 0:
                continue  # 跳过非正时间差
            vs.append((views[i] - views[i - 1]) / dt)  # 播放量变化 / 时间变化
        return np.array(vs, dtype=np.float32)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        """
        构造预测结果对象

        Args:
            current_views (int) : 当前播放量
            threshold (int)     : 目标播放量阈值
            velocity (float)    : 预测速度
            confidence (float)  : 置信度
            reason (str)        : 预测原因标识
            extra (dict)        : 额外的元数据

        Returns:
            PredictionResult: 预测结果对象
        """
        if velocity <= 0:
            predicted_hours = float("inf")  # 速度非正，无法预测
            confidence = 0.0
        else:
            remaining = threshold - current_views
            predicted_hours = 0 if remaining <= 0 else remaining / velocity
            if remaining <= 0:
                confidence = 1.0  # 已达标，完全置信
        metadata = {"reason": reason}
        metadata.update(extra)  # 合并额外元数据
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
