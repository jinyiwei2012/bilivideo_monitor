"""
多任务学习预测算法 (Multi-Task Learning)
========================================

基于多任务学习框架的预测算法，同时预测多个里程碑阈值的时间。
通过共享特征提取层，让模型隐式学习到播放量数据的共享结构，
提高对不同阈值预测的一致性和准确性。

核心原理：
    1. 共享特征提取 - 用同一组特征（播放量/点赞/投币的近期窗口）
       同时预测多个时间步的变化率，使模型隐式学习数据的共享结构。
    2. 多头预测（PyTorch 路径）- 共享 2 层 MLP + 3 个独立输出头，
       每个头预测不同时间步的相对增长率（t+1, t+2, t+3）。
    3. 阈值解耦（numpy 路径）- 按阈值分段策略（短期/中期/长期），
       对 10 万/100 万/1000 万三个里程碑独立建模。
    4. 一致性检查 - 确保不同阈值的预测结果逻辑自洽，
       若不同阈值预测速度的标准差/均值比超过阈值则降置信度。
    5. PyTorch 优先 / numpy 回退 - 有 PyTorch 时训练 MLP 共享网络；
       无 PyTorch 时用 numpy 实现基于速度统计的启发式多阈值预测。

三个里程碑阈值：
    - 10 万 (权重 0.4): 短期目标，使用近期速度预测
    - 100 万 (权重 0.4): 中期目标，结合近期和平均速度
    - 1000 万 (权重 0.2): 长期目标，考虑衰减模型
"""

import logging
import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# 检查 PyTorch 是否可用
_HAS_TORCH = False
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _HAS_TORCH = True
except ImportError:
    pass


class MultiTaskSimpleAlgorithm(BaseAlgorithm):
    """
    多任务学习预测算法

    主要功能：
        - PyTorch 路径：共享特征 MLP 同时预测多个时间步相对增长率
        - numpy 路径：按阈值分段策略独立预测短/中/长期目标
        - 多阈值一致性检查确保预测结果自洽
        - 自动选择主阈值（最近未达到的里程碑）

    类属性：
        name (str)                    : "多任务学习"
        algorithm_id (str)            : "multi_task_simple"
        category (str)                : "多任务学习"
        default_weight (float)        : 1.6
        thresholds (list)             : [100000, 1000000, 10000000]
        threshold_weights (list)      : [0.4, 0.4, 0.2]
        consistency_threshold (float) : 0.3
    """

    name = "多任务学习"
    algorithm_id = "multi_task_simple"
    description = "共享特征提取+多头预测（PyTorch 优先，numpy 回退）"
    category = "多任务学习"
    default_weight = 1.6

    def __init__(self):
        """
        初始化多任务学习算法

        设置三个里程碑阈值和对应的权重：
            - 10 万（短期）：权重 0.4
            - 100 万（中期）：权重 0.4
            - 1000 万（长期）：权重 0.2（衰减权重，长期预测更不确定）
        """
        super().__init__()
        # 三个里程碑阈值：10 万 / 100 万 / 1000 万
        self.thresholds = [100000, 1000000, 10000000]
        # 阈值权重：短期和中期更重要，长期衰减
        self.threshold_weights = [0.4, 0.4, 0.2]
        # 一致性阈值：不同阈值预测速度的标准差/均值超过此值认为不一致
        self.consistency_threshold = 0.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行多任务学习预测

        尝试路径：
            1. 如果 PyTorch 可用且数据 >= 20 个点，使用 _torch_predict
            2. 否则使用 _numpy_predict 作为回退

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 优先尝试 PyTorch 路径（需要 >= 20 个数据点）
        if _HAS_TORCH and len(history) >= 20:
            try:
                result = self._torch_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("MultiTask PyTorch 失败，回退 numpy: %s", e)

        # 回退到 numpy 路径
        return self._numpy_predict(video_data, threshold)

    def _torch_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        PyTorch 路径：使用共享 MLP 多头预测

        构建 _MultiTaskMLP 网络：
            - 输入：5 个时间步的 (播放量, 点赞数, 投币数) = 15 维特征
            - 共享层：2 层 MLP（64 隐藏单元）
            - 3 个输出头：每个输出未来一步的相对增长率
            - 训练目标：t-1->t, t->t+1, t+1->t+2 三步的增长率

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult or None: 预测结果，失败时返回 None
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 提取播放量、点赞数、投币数时间序列
        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float32)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float32)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float32)

        n = len(views)
        if n < 20:
            return None  # 数据不足，回退到 numpy

        # 构造训练数据：窗口大小 p=5，3 个输出任务（预测 3 步增长率）
        p, n_tasks = 5, 3
        X_list, y_list = [], []
        for i in range(p + 10, n - 2):
            feat = []
            for j in range(p):
                feat.extend([views[i - j - 1], likes[i - j - 1], coins[i - j - 1]])
            X_list.append(feat)
            y_list.append([
                views[i - 1] / max(views[i - 2], 1) - 1,  # t-1 -> t 的相对增长率
                views[i] / max(views[i - 1], 1) - 1,       # t -> t+1 的相对增长率
                views[i + 1] / max(views[i], 1) - 1,       # t+1 -> t+2 的相对增长率
            ])

        if len(X_list) < 8:
            return None  # 训练样本不足

        X = torch.tensor(np.array(X_list), dtype=torch.float32)
        y = torch.tensor(np.array(y_list), dtype=torch.float32)

        try:
            # 构建和训练 MLP 共享网络
            model = _MultiTaskMLP(in_dim=X.shape[1], n_tasks=n_tasks)
            opt = optim.Adam(model.parameters(), lr=0.01)
            for _ in range(100):  # 100 轮训练
                model.train()
                opt.zero_grad()
                pred = model(X)
                loss = nn.MSELoss()(pred, y)
                loss.backward()
                opt.step()

            # 用最后窗口的特征做预测
            model.eval()
            with torch.no_grad():
                last_feat = []
                for j in range(p):
                    last_feat.extend([views[-j - 1], likes[-j - 1] if len(likes) > j + 1 else 0,
                                      coins[-j - 1] if len(coins) > j + 1 else 0])
                pred_t = model(torch.tensor([last_feat], dtype=torch.float32)).numpy()[0]  # 预测的相对增长率

            # 预测速度 = 平均相对增长率 * 当前播放量 / 3600（转换为小时速度）
            pred_velocity = max(0, float(np.mean(pred_t)) * current_views / 3600)
            if pred_velocity < 1:
                pred_velocity = velocity  # 速度过低时退化为当前速度

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / pred_velocity if pred_velocity > 0 else float("inf")
                # 置信度基于训练样本量
                confidence = min(0.85, 0.4 + 0.3 * min(1.0, float(len(X_list)) / 30) + 0.15)

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "multi_task_torch", "n_tasks": n_tasks},
                timestamp=datetime.now(),
            )
        except Exception:
            return None  # PyTorch 预测异常，回退到 numpy

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """
        numpy 回退路径：使用启发式策略预测多个阈值

        流程：
            1. 提取播放量序列和速度序列
            2. 对三个里程碑阈值分别预测：
               - 短期（10万）：直接使用当前速度
               - 中期（100万）：综合当前速度和平均速度（6:4）
               - 长期（1000万）：加速度<0时用指数衰减，否则用加权速度
            3. 一致性检查：不同阈值预测速度的标准差/均值
            4. 选择主阈值（最接近当前播放量且未达到的阈值）

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        # 数据太少（< 3 点）：退化为简单速度外推
        if len(history) < 3:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, self.thresholds[0], velocity,
                confidence=0.3, multi_predictions=[], reason="insufficient_data",
            )

        # 提取播放量和时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < 3:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, self.thresholds[0], velocity,
                confidence=0.3, multi_predictions=[], reason="short_series"
            )

        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < 2:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views, self.thresholds[0], velocity,
                confidence=0.4, multi_predictions=[], reason="single_velocity",
            )

        # 多任务预测：同时对三个阈值独立预测
        multi_predictions = self._multi_predict(current_views, views, velocities, video_data)

        # 一致性检查与调整
        adjusted_velocity, confidence, reason = self._consistency_check(multi_predictions, velocities)

        # 选择主要预测的阈值（最接近当前播放量的未达阈值）
        main_threshold = self._select_main_threshold(current_views)

        return self._make_result(
            current_views, main_threshold, adjusted_velocity,
            confidence=confidence, multi_predictions=multi_predictions, reason=reason,
        )

    def _multi_predict(
        self, current_views: int, views: np.ndarray, velocities: np.ndarray, video_data: Dict
    ) -> List[Dict]:
        """
        同时对三个里程碑阈值进行独立预测

        策略设计：
            短期（10万）：使用最近的速度，预测最精确
            中期（100万）：60% 当前速度 + 40% 平均速度，平衡近期和全局
            长期（1000万）：考虑加速度方向
                - 加速度 < 0：使用指数衰减模型（速度随时间下降）
                - 加速度 >= 0：80% 当前速度 + 20% 平均速度

        Args:
            current_views (int)      : 当前播放量
            views (np.ndarray)       : 播放量序列
            velocities (np.ndarray)  : 速度序列
            video_data (Dict)        : 视频数据字典

        Returns:
            List[Dict]: 每个阈值对应的预测结果列表
        """
        predictions = []

        # 计算共享的基础特征
        current_vel = velocities[-1]  # 当前速度
        avg_vel = np.mean(velocities)  # 平均速度
        vel_std = np.std(velocities)  # 速度标准差
        acceleration = self._calculate_acceleration(velocities)  # 加速度

        for idx, thresh in enumerate(self.thresholds):
            if thresh <= current_views:
                # 已达成该阈值
                predictions.append(
                    {
                        "threshold": thresh,
                        "predicted_hours": 0,
                        "velocity": current_vel,
                        "confidence": 1.0,
                        "method": "already_reached",
                    }
                )
                continue

            # ── 根据阈值位置选择预测策略 ──
            if idx == 0:
                # 短期阈值（10万）：直接使用最近速度，最精确
                pred_vel = current_vel
                method = "short_term_recent"

            elif idx == 1:
                # 中期阈值（100万）：综合近期速度（60%）和全局平均速度（40%）
                if len(velocities) >= 3:
                    pred_vel = 0.6 * current_vel + 0.4 * avg_vel
                else:
                    pred_vel = current_vel
                method = "medium_term_combined"

            else:
                # 长期阈值（1000万）：考虑衰减趋势
                if acceleration < 0:
                    # 速度在下降，使用指数衰减模型
                    decay_rate = abs(acceleration) / max(current_vel, 1)
                    pred_vel = current_vel * np.exp(-decay_rate * 24)  # 24 小时后的预测速度
                    pred_vel = max(pred_vel, current_vel * 0.3)  # 最低保留 30%
                else:
                    # 速度稳定或上升：保守估计
                    pred_vel = 0.8 * current_vel + 0.2 * avg_vel
                method = "long_term_decay"

            # 计算预测时间 = 剩余播放量 / 预测速度
            remaining = thresh - current_views
            if pred_vel > 0:
                pred_hours = remaining / pred_vel
            else:
                pred_hours = float("inf")  # 速度为 0 时无法预测

            # 计算该阈值预测的置信度
            if idx == 0:
                conf = 0.8 if len(velocities) >= 3 else 0.5  # 短期置信度较高
            elif idx == 1:
                conf = 0.7 if vel_std < 0.3 * avg_vel else 0.5  # 稳定则置信度高
            else:
                conf = 0.6 if acceleration >= 0 else 0.4  # 加速更可信

            predictions.append(
                {
                    "threshold": thresh,
                    "predicted_hours": pred_hours,
                    "velocity": pred_vel,
                    "confidence": conf,
                    "method": method,
                }
            )

        return predictions

    def _consistency_check(self, predictions: List[Dict], velocities: np.ndarray) -> Tuple[float, float, str]:
        """
        一致性检查：验证不同阈值预测之间的自洽性

        原理：
            - 如果三个阈值的预测速度高度一致（CV < 0.3），则使用加权平均
            - 如果预测速度差异很大，说明模型不稳定，回退到当前观测速度

        具体步骤：
            1. 提取各阈值有效预测的速度值
            2. 计算加权平均速度（权重=各阈值置信度）
            3. 计算变异系数 CV = std/mean
            4. CV < 0.3：一致的 -> 使用加权平均，置信度 0.75
            5. CV >= 0.3：不一致 -> 使用当前速度，置信度 0.55

        Args:
            predictions (List[Dict])  : 多阈值预测结果列表
            velocities (np.ndarray)   : 速度序列

        Returns:
            Tuple[float, float, str]: (调整后速度, 置信度, 调整原因)
        """
        if not predictions:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.3, "no_predictions"

        # 提取有效预测的速度
        velocities_pred = []
        weights = []

        for pred in predictions:
            if pred["predicted_hours"] > 0 and pred["predicted_hours"] != float("inf"):
                # 反推速度：v = (阈值 - 当前播放量) / 预测时间
                current_views = 0  # 需要从外部传入，此处简化为 0（实际上应该修正）
                v = (pred["threshold"] - current_views) / pred["predicted_hours"]
                velocities_pred.append(v)
                weights.append(pred["confidence"])

        if not velocities_pred:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.4, "inconsistent"

        # 计算加权平均速度和一致性
        weights = np.array(weights)
        velocities_pred = np.array(velocities_pred)
        weighted_vel = np.sum(velocities_pred * weights) / np.sum(weights)  # 加权平均

        # 检查一致性：变异系数 = 标准差 / 均值
        if len(velocities_pred) >= 2:
            consistency = np.std(velocities_pred) / (np.mean(velocities_pred) + 1e-6)

            if consistency < self.consistency_threshold:
                # 一致：使用加权平均速度
                adjusted_vel = weighted_vel
                confidence = 0.75
                reason = "consistent"
            else:
                # 不一致：回退到当前观测速度
                adjusted_vel = velocities[-1]
                confidence = 0.55
                reason = "inconsistent_high_variance"
        else:
            adjusted_vel = velocities[-1]
            confidence = 0.6
            reason = "single_prediction"

        return max(adjusted_vel, 0.0), confidence, reason

    def _select_main_threshold(self, current_views: int) -> int:
        """
        选择主要预测的阈值

        选择第一个未被达到的阈值（按 10万 -> 100万 -> 1000万 顺序）。
        如果没有可选阈值，返回最高阈值。

        Args:
            current_views (int): 当前播放量

        Returns:
            int: 选中的主要预测阈值
        """
        for thresh in self.thresholds:
            if thresh > current_views:
                return thresh  # 返回第一个大于当前播放量的阈值
        return self.thresholds[-1]  # 默认返回最高阈值

    def _calculate_acceleration(self, velocities: np.ndarray) -> float:
        """
        计算加速度：速度的变化率

        使用最近 3 个速度值通过简单差分计算。

        Args:
            velocities (np.ndarray): 速度序列

        Returns:
            float: 加速度值
        """
        if len(velocities) < 2:
            return 0.0

        recent = velocities[-min(3, len(velocities)) :]
        if len(recent) < 2:
            return 0.0

        accel = (recent[-1] - recent[0]) / (len(recent) - 1)
        return accel

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史数据列表中提取播放量和时间戳序列

        处理多种时间戳格式并按时间排序。

        Args:
            history (List[Dict]): 历史数据点列表

        Returns:
            Tuple[np.ndarray, np.ndarray]: (播放量数组, 时间戳数组)
        """
        views = []
        timestamps = []

        for entry in history:
            v = entry.get("view_count", entry.get("view", 0))
            t = entry.get("timestamp", 0)

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

        if len(views) > 1:
            sorted_indices = np.argsort(timestamps)
            views = [views[i] for i in sorted_indices]
            timestamps = [timestamps[i] for i in sorted_indices]

        return np.array(views), np.array(timestamps)

    def _calculate_velocity_series(self, views: np.ndarray, timestamps: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算速度序列：播放量增量 / 时间增量（小时）

        Args:
            views (np.ndarray)      : 播放量数组
            timestamps (np.ndarray) : 时间戳数组

        Returns:
            Tuple[np.ndarray, np.ndarray]: (速度数组, 速度时间戳数组)
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
        self, current_views: int, threshold: int, velocity: float,
        confidence: float, multi_predictions: List[Dict], reason: str,
    ) -> PredictionResult:
        """
        构造预测结果对象

        Args:
            current_views (int)           : 当前播放量
            threshold (int)               : 目标播放量阈值
            velocity (float)              : 预测速度
            confidence (float)            : 置信度
            multi_predictions (List[Dict]): 多阈值预测结果列表
            reason (str)                  : 调整原因

        Returns:
            PredictionResult: 预测结果对象
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

        # 构造多任务预测的元数据
        metadata = {
            "multi_predictions": multi_predictions,  # 各阈值的预测详情
            "adjustment_reason": reason,  # 调整原因
            "thresholds": self.thresholds,  # 三个里程碑阈值
            "method": "multi_task_learning",  # 方法标识
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


# 仅在 PyTorch 可用时定义此内部类
if _HAS_TORCH:

    class _MultiTaskMLP(nn.Module):
        """
        多任务 MLP 网络（PyTorch 实现）

        架构：
            - 共享层：2 层全连接 + ReLU 激活（64 隐藏单元）
            - 3 个独立输出头：每个头预测一个时间步的相对增长率

        参数：
            in_dim (int)  : 输入特征维度（5 窗口 * 3 特征 = 15）
            n_tasks (int) : 输出任务数（3 个时间步）
            hidden (int)  : 隐藏层大小（默认 64）
        """

        def __init__(self, in_dim, n_tasks, hidden=64):
            super().__init__()
            # 共享特征提取层
            self.shared = nn.Sequential(
                nn.Linear(in_dim, hidden),  # 输入 -> 隐藏层1
                nn.ReLU(),  # 激活函数
                nn.Linear(hidden, hidden),  # 隐藏层1 -> 隐藏层2
                nn.ReLU(),  # 激活函数
            )
            # 3 个独立输出头（每个预测一个时间步的增长率）
            self.heads = nn.ModuleList([nn.Linear(hidden, 1) for _ in range(n_tasks)])

        def forward(self, x):
            """
            前向传播

            Args:
                x (torch.Tensor): 输入特征张量 [batch_size, in_dim]

            Returns:
                torch.Tensor: 多任务预测输出 [batch_size, n_tasks]
            """
            h = self.shared(x)  # 共享特征提取
            return torch.cat([head(h) for head in self.heads], dim=1)  # 拼接 3 个头的输出
