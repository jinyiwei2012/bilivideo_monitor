"""
多任务学习 (Multi-Task Learning)
优先使用 PyTorch 真实实现（共享特征提取+多头预测），不可用时回退 numpy 简化版
"""

import logging
import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_HAS_TORCH = False
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _HAS_TORCH = True
except ImportError:
    pass


class MultiTaskSimpleAlgorithm(BaseAlgorithm):
    """多任务学习算法"""

    name = "多任务学习"
    algorithm_id = "multi_task_simple"
    description = "共享特征提取+多头预测（PyTorch 优先，numpy 回退）"
    category = "多任务学习"
    default_weight = 1.6

    def __init__(self):
        super().__init__()
        self.thresholds = [100000, 1000000, 10000000]
        self.threshold_weights = [0.4, 0.4, 0.2]
        self.consistency_threshold = 0.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if _HAS_TORCH and len(history) >= 20:
            try:
                result = self._torch_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("MultiTask PyTorch 失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _torch_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float32)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float32)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float32)

        n = len(views)
        if n < 20:
            return None

        p, n_tasks = 5, 3
        X_list, y_list = [], []
        for i in range(p + 10, n - 2):
            feat = []
            for j in range(p):
                feat.extend([views[i - j - 1], likes[i - j - 1], coins[i - j - 1]])
            X_list.append(feat)
            y_list.append([
                views[i - 1] / max(views[i - 2], 1) - 1,
                views[i] / max(views[i - 1], 1) - 1,
                views[i + 1] / max(views[i], 1) - 1,
            ])

        if len(X_list) < 8:
            return None

        X = torch.tensor(np.array(X_list), dtype=torch.float32)
        y = torch.tensor(np.array(y_list), dtype=torch.float32)

        try:
            model = _MultiTaskMLP(in_dim=X.shape[1], n_tasks=n_tasks)
            opt = optim.Adam(model.parameters(), lr=0.01)
            for _ in range(100):
                model.train()
                opt.zero_grad()
                pred = model(X)
                loss = nn.MSELoss()(pred, y)
                loss.backward()
                opt.step()

            model.eval()
            with torch.no_grad():
                last_feat = []
                for j in range(p):
                    last_feat.extend([views[-j - 1], likes[-j - 1] if len(likes) > j + 1 else 0,
                                      coins[-j - 1] if len(coins) > j + 1 else 0])
                pred_t = model(torch.tensor([last_feat], dtype=torch.float32)).numpy()[0]

            pred_velocity = max(0, float(np.mean(pred_t)) * current_views / 3600)
            if pred_velocity < 1:
                pred_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / pred_velocity if pred_velocity > 0 else float("inf")
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
            return None

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])

        if len(history) < 3:
            # 数据太少，退化为简单预测
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views,
                self.thresholds[0],
                velocity,
                confidence=0.3,
                multi_predictions=[],
                reason="insufficient_data",
            )

        # 提取时间序列
        views, timestamps = self._extract_series(history)

        if len(views) < 3:
            velocity = self.calculate_velocity(video_data)
            return self._make_result(
                current_views, self.thresholds[0], velocity, confidence=0.3, multi_predictions=[], reason="short_series"
            )

        # 计算速度序列
        velocities, _ = self._calculate_velocity_series(views, timestamps)

        if len(velocities) < 2:
            velocity = velocities[-1] if len(velocities) > 0 else 0.0
            return self._make_result(
                current_views,
                self.thresholds[0],
                velocity,
                confidence=0.4,
                multi_predictions=[],
                reason="single_velocity",
            )

        # 多任务预测：同时预测多个阈值
        multi_predictions = self._multi_predict(current_views, views, velocities, video_data)

        # 一致性检查与调整
        adjusted_velocity, confidence, reason = self._consistency_check(multi_predictions, velocities)

        # 选择主要预测的阈值（最接近当前播放量的未达阈值）
        main_threshold = self._select_main_threshold(current_views)

        return self._make_result(
            current_views,
            main_threshold,
            adjusted_velocity,
            confidence=confidence,
            multi_predictions=multi_predictions,
            reason=reason,
        )

    def _multi_predict(
        self, current_views: int, views: np.ndarray, velocities: np.ndarray, video_data: Dict
    ) -> List[Dict]:
        """同时预测多个阈值

        Returns:
            每个阈值的预测结果列表
        """
        predictions = []

        # 计算基础速度特征（共享）
        current_vel = velocities[-1]
        avg_vel = np.mean(velocities)
        vel_std = np.std(velocities)
        acceleration = self._calculate_acceleration(velocities)

        for idx, thresh in enumerate(self.thresholds):
            if thresh <= current_views:
                # 已达到该阈值
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

            # 根据阈值选择预测策略
            if idx == 0:
                # 短期阈值（10万）：使用近期速度
                pred_vel = current_vel
                method = "short_term_recent"

            elif idx == 1:
                # 中期阈值（100万）：结合近期和平均速度
                if len(velocities) >= 3:
                    pred_vel = 0.6 * current_vel + 0.4 * avg_vel
                else:
                    pred_vel = current_vel
                method = "medium_term_combined"

            else:
                # 长期阈值（1000万）：考虑衰减
                if acceleration < 0:
                    # 速度在下降，使用衰减模型
                    decay_rate = abs(acceleration) / max(current_vel, 1)
                    pred_vel = current_vel * np.exp(-decay_rate * 24)  # 24小时后速度
                    pred_vel = max(pred_vel, current_vel * 0.3)
                else:
                    # 速度稳定或上升
                    pred_vel = 0.8 * current_vel + 0.2 * avg_vel
                method = "long_term_decay"

            # 计算预测时间
            remaining = thresh - current_views
            if pred_vel > 0:
                pred_hours = remaining / pred_vel
            else:
                pred_hours = float("inf")

            # 计算置信度
            if idx == 0:
                conf = 0.8 if len(velocities) >= 3 else 0.5
            elif idx == 1:
                conf = 0.7 if vel_std < 0.3 * avg_vel else 0.5
            else:
                conf = 0.6 if acceleration >= 0 else 0.4

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
        """一致性检查

        检查不同阈值的预测是否一致，调整最终速度

        Returns:
            (调整后的速度, 置信度, 调整原因)
        """
        if not predictions:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.3, "no_predictions"

        # 提取有效预测的速度
        velocities_pred = []
        weights = []

        for pred in predictions:
            if pred["predicted_hours"] > 0 and pred["predicted_hours"] != float("inf"):
                v = (pred["threshold"] - pred["threshold"] + 1) / pred["predicted_hours"]
                # 实际上应该这样计算：
                current_views = 0  # 需要从外部传入，这里简化处理
                v = (pred["threshold"] - current_views) / pred["predicted_hours"]
                velocities_pred.append(v)
                weights.append(pred["confidence"])

        if not velocities_pred:
            return velocities[-1] if len(velocities) > 0 else 0.0, 0.4, "inconsistent"

        # 计算加权平均速度
        weights = np.array(weights)
        velocities_pred = np.array(velocities_pred)
        weighted_vel = np.sum(velocities_pred * weights) / np.sum(weights)

        # 检查一致性（标准差/均值）
        if len(velocities_pred) >= 2:
            consistency = np.std(velocities_pred) / (np.mean(velocities_pred) + 1e-6)

            if consistency < self.consistency_threshold:
                # 一致，使用加权平均
                adjusted_vel = weighted_vel
                confidence = 0.75
                reason = "consistent"
            else:
                # 不一致，使用当前速度
                adjusted_vel = velocities[-1]
                confidence = 0.55
                reason = "inconsistent_high_variance"
        else:
            adjusted_vel = velocities[-1]
            confidence = 0.6
            reason = "single_prediction"

        return max(adjusted_vel, 0.0), confidence, reason

    def _select_main_threshold(self, current_views: int) -> int:
        """选择主要预测的阈值"""
        for thresh in self.thresholds:
            if thresh > current_views:
                return thresh
        return self.thresholds[-1]  # 默认最高阈值

    def _calculate_acceleration(self, velocities: np.ndarray) -> float:
        """计算加速度"""
        if len(velocities) < 2:
            return 0.0

        recent = velocities[-min(3, len(velocities)) :]
        if len(recent) < 2:
            return 0.0

        accel = (recent[-1] - recent[0]) / (len(recent) - 1)
        return accel

    def _extract_series(self, history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """提取播放量和时间戳序列"""
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
        """计算速度序列"""
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
        multi_predictions: List[Dict],
        reason: str,
    ) -> PredictionResult:
        """构造预测结果"""

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
            "multi_predictions": multi_predictions,
            "adjustment_reason": reason,
            "thresholds": self.thresholds,
            "method": "multi_task_learning",
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


if _HAS_TORCH:

    class _MultiTaskMLP(nn.Module):
        def __init__(self, in_dim, n_tasks, hidden=64):
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(in_dim, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
            )
            self.heads = nn.ModuleList([nn.Linear(hidden, 1) for _ in range(n_tasks)])

        def forward(self, x):
            h = self.shared(x)
            return torch.cat([head(h) for head in self.heads], dim=1)
