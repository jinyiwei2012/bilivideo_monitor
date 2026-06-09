"""
TimesNet简化版 (TimesNet Simplified) — 时序2D变换网络
=====================================================

ICLR 2023论文的简化实现——将1D时间序列通过多周期reshape转换为2D表示，
捕捉周期内和周期间的模式，用于B站视频播放量增长预测。

核心原理:
    1. 1D → 2D变换：按不同周期长度将序列reshape为2D矩阵
       例：长度为12的序列，周期3 → 4行×3列的矩阵
    2. 2D卷积：在2D空间提取特征：
       - 列均值：周期内模式（同一周期位置的平均值）
       - 行均值：周期间模式（不同周期的变化）
    3. 多周期融合：对[3, 6, 12]三种周期分别提取特征，加权融合

简化版实现：
    - 使用均值/标准差等统计量代替真正的2D卷积
    - 根据自相关系数判断周期性强度，自适应调整权重

降级链：torch checkpoint（TimessNetTorchModel） → numpy 1D→2D reshape + 简化2D卷积

参考论文：
    "TimesNet: Temporal 2D-Variation Modeling for General Time Series Analysis"
    (Wu et al., ICLR 2023)
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TimessNetTorchModel, try_torch_predict


class TimesNetSimpleAlgorithm(BaseAlgorithm):
    """TimesNet简化版算法

    核心思路（简化）：
    1. 将1D时间序列转换为2D（按不同周期长度reshape）
    2. 使用简化2D卷积提取特征
    3. 融合多周期特征进行预测

    论文：TimesNet: Temporal 2D-Variation Modeling for General Time Series Analysis
    (ICLR 2023, Wu et al.)
    """

    name = "TimesNet简化版"
    algorithm_id = "times_net_simple"
    description = "将1D序列转为2D，捕获周期内和周期间的模式"
    category = "深度学习"
    default_weight = 1.4

    def __init__(self):
        """初始化TimesNet参数

        设置候选周期列表和卷积参数。
        """
        super().__init__()
        self.periods = [3, 6, 12]       # 候选周期长度（对应短/中/长周期）
        self.min_seq_len = 15           # 最少需要的序列长度
        self.conv_kernel = 2            # 简化卷积核大小
        self.min_data_points = 15       # 最少需要的数据点数

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data, threshold=100000):
        """执行预测

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            TimessNetTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建TimesNet PyTorch模型实例"""
        return TimessNetTorchModel(in_features=getattr(self, '_training_n_features', 5), window=10, horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行numpy版本预测

        核心流程：
        1. 提取播放量序列和速度序列
        2. 对每个周期长度，将速度序列reshape为2D矩阵
        3. 用简化2D卷积提取周期内和周期间特征
        4. 基于周期性强度决定特征权重，融合近期速度

        Args:
            video_data: 视频数据，包含 history_data 列表
            threshold: 目标播放量阈值

        Returns:
            PredictionResult
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据不足时退化为简单预测
        if len(history) < self.min_data_points:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity, confidence=0.3, period_features=None, reason="insufficient_data"
            )

        # 提取时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < self.min_seq_len:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, threshold, velocity, confidence=0.3, period_features=None, reason="short_series"
            )

        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < self.min_seq_len:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, threshold, velocity, confidence=0.4, period_features=None, reason="short_velocity_series"
            )

        # TimesNet核心：多周期特征提取
        period_features = self._extract_multi_period_features(velocities)

        if not period_features:
            # 无法提取周期特征，使用平均速度
            avg_vel = np.mean(velocities)
            return self._make_result(
                current_views, threshold, avg_vel, confidence=0.4, period_features=None, reason="no_period_found"
            )

        # 基于多周期特征预测
        predicted_velocity, confidence = self._predict_from_period_features(period_features, velocities)

        return self._make_result(
            current_views,
            threshold,
            predicted_velocity,
            confidence=confidence,
            period_features=period_features,
            reason="times_net",
        )

    def _extract_multi_period_features(self, series: np.ndarray) -> Dict[int, np.ndarray]:
        """提取多周期特征

        对每个候选周期长度，将1D序列转换为2D（reshape为 rows×period），
        然后使用简化2D卷积提取特征。

        Args:
            series: 速度序列

        Returns:
            字典：{周期长度: 特征向量}，每个特征向量包含6个统计量
        """
        features = {}

        for period in self.periods:
            if len(series) < period * 2:
                continue  # 序列太短，无法使用此周期

            # 将1D序列转换为2D
            # 例如：series = [1,2,3,4,5,6], period=3
            # 2D = [[1,2,3], [4,5,6]]  (2行×3列)
            try:
                # 截断到 period 的整数倍
                truncate_len = (len(series) // period) * period
                truncated = series[:truncate_len]

                # reshape 为 2D 矩阵
                matrix_2d = truncated.reshape(-1, period)

                # 简化2D卷积（手动实现，用统计量代替卷积核）
                conv_features = self._simple_2d_conv(matrix_2d)

                features[period] = conv_features
            except Exception:
                continue

        return features

    def _simple_2d_conv(self, matrix: np.ndarray) -> np.ndarray:
        """简化2D卷积：用统计特征代替卷积核

        提取6个统计量作为该周期的特征表示：
        1. 列均值均值 —— 周期内平均水平
        2. 列均值标准差 —— 周期内变异
        3. 行均值均值 —— 周期间平均水平
        4. 行均值标准差 —— 周期间变异
        5. 全局均值 —— 整体水平
        6. 全局标准差 —— 整体变异

        Args:
            matrix: 2D矩阵 (rows × period)

        Returns:
            np.ndarray: 6维特征向量
        """
        if matrix.size == 0:
            return np.array([0.0, 0.0, 0.0])

        # 周期内模式（列均值：每个周期位置的平均值）
        col_means = np.mean(matrix, axis=0)

        # 周期间模式（行均值：每个周期的平均值）
        row_means = np.mean(matrix, axis=1)

        # 简化"卷积"：使用统计特征代替
        features = [
            np.mean(col_means),  # 列均值均值（周期内全局水平）
            np.std(col_means),   # 列均值标准差（周期内变异程度）
            np.mean(row_means),  # 行均值均值（周期间全局水平）
            np.std(row_means),   # 行均值标准差（周期间变异程度）
            np.mean(matrix),     # 全局均值
            np.std(matrix),      # 全局标准差
        ]

        return np.array(features)

    def _predict_from_period_features(
        self, period_features: Dict[int, np.ndarray], velocities: np.ndarray
    ) -> Tuple[float, float]:
        """基于多周期特征预测

        根据自相关计算的周期性强度自适应调整特征权重：
        - 强周期性（>0.6）：更多依赖周期特征（6:4）
        - 中等周期性（>0.3）：各半依赖
        - 弱周期性：更多依赖近期速度（2:8）

        Args:
            period_features: 多周期特征字典
            velocities: 原始速度序列

        Returns:
            (预测速度, 置信度)
        """
        if not period_features:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.3

        # 融合多周期特征：所有周期的所有统计量拼接
        all_features = []
        for period, feats in period_features.items():
            all_features.extend(feats)

        if not all_features:
            return velocities[-1], 0.3

        # 使用特征均值作为预测
        feature_mean = np.mean(all_features)

        # 结合近期速度
        recent_vel = velocities[-1]

        # 判断周期性强度（基于自相关系数）
        periodicity_strength = self._calculate_periodicity(velocities)

        # 根据周期性强度自适应调整权重
        if periodicity_strength > 0.6:
            # 强周期性：更多依赖周期特征（周期间规律性强）
            weight_feature = 0.6
            weight_recent = 0.4
            confidence = 0.7
        elif periodicity_strength > 0.3:
            # 中等周期性：折中
            weight_feature = 0.4
            weight_recent = 0.6
            confidence = 0.6
        else:
            # 弱周期性：更多依赖近期速度（无明显周期）
            weight_feature = 0.2
            weight_recent = 0.8
            confidence = 0.5

        predicted_velocity = weight_feature * feature_mean + weight_recent * recent_vel

        return max(predicted_velocity, 0.0), confidence

    def _calculate_periodicity(self, series: np.ndarray) -> float:
        """计算周期性强度

        使用自相关函数（ACF）在lag=3处的值作为周期性指标。
        值越接近1说明周期性越强。

        Args:
            series: 速度序列

        Returns:
            float: 周期性强度 [0, 1]
        """
        if len(series) < 6:
            return 0.0

        # 计算自相关（lag=3）
        lag = min(3, len(series) // 2)
        if lag < 1:
            return 0.0

        try:
            # 归一化序列（z-score）
            normalized = (series - np.mean(series)) / (np.std(series) + 1e-6)

            # 计算自相关系数（常量序列会导致 np.corrcoef 内部除零）
            with np.errstate(invalid="ignore"):
                autocorr = np.corrcoef(normalized[lag:], normalized[:-lag])[0, 1]
            if not np.isfinite(autocorr):
                return 0.0

            # 映射到 [0, 1]（负相关视为无周期）
            periodicity = max(0, autocorr)
            return periodicity
        except Exception:
            return 0.0

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列

        从历史记录中提取播放量和时间戳，按时间排序。

        Args:
            history: 历史数据记录列表

        Returns:
            (播放量数组, 时间戳数组)
        """
        views = []
        timestamps = []

        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)

            # 统一时间戳格式
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    from datetime import datetime as dt

                    t = dt.fromisoformat(t).timestamp()
                except Exception:
                    continue

            if v > 0 and t > 0:
                views.append(float(v))
                timestamps.append(float(t))

        # 按时间排序
        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]

        return np.array(views), np.array(timestamps)

    def _calculate_velocity_series(self, views: np.ndarray, timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算速度序列（每小时播放量变化）

        Args:
            views: 播放量数组
            timestamps: 时间戳数组

        Returns:
            (速度数组, 对应的时间戳数组)
        """
        if len(views) < 2:
            return np.array([]), np.array([])

        velocities = []
        vel_times = []

        for i in range(1, len(views)):
            dt = (timestamps[i] - timestamps[i - 1]) / 3600.0
            if dt <= 0:
                continue
            dv = views[i] - views[i - 1]
            velocity = dv / dt
            velocities.append(velocity)
            vel_times.append(timestamps[i])

        return np.array(velocities), np.array(vel_times)

    def _make_result(
        self,
        current_views: int,
        threshold: int,
        velocity: float,
        confidence: float,
        period_features: Optional[Dict],
        reason: str,
    ) -> PredictionResult:
        """构造预测结果

        Args:
            current_views: 当前播放量
            threshold: 目标阈值
            velocity: 预测速度（每小时）
            confidence: 置信度 [0, 1]
            period_features: 周期特征字典
            reason: 预测来源标识

        Returns:
            PredictionResult: 标准化预测结果
        """

        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity

        # 构造元数据：包含周期信息
        metadata = {
            "reason": reason,
            "periods_used": list(period_features.keys()) if period_features else [],
            "num_periods": len(period_features) if period_features else 0,
            "method": "times_net_simplified",
        }

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
