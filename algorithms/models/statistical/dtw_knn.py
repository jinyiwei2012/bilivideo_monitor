"""
DTW-kNN — 动态时间规整 k 近邻预测
===================================

基于 DTW (Dynamic Time Warping) 距离的 k 近邻类比预测算法。

核心原理：
  1. 将历史播放量/点赞/投币序列的梯度作为"增长轮廓"（profile）
  2. 将轮廓切分为多个局部窗口（segment），每个窗口代表一段时间内的增长模式
  3. 取最新窗口作为查询（query），用 DTW 距离在全量窗口中搜索 k 个最相似的"近邻"
  4. 查看近邻窗口之后实际发生了什么（后续增量），加权平均得到未来增速预测
  5. DTW 距离比欧氏距离更能捕捉形似但时间略有错位的增长模式

适用场景：历史数据 >= 5 条，增长模式具有阶段性特点（爆发期、衰减期等）
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

# scipy 全局可用性标记（简化版 DTW 使用纯 numpy，实际未强依赖 scipy）
try:
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _dtw_distance(s1, s2):
    """
    动态时间规整距离 (Dynamic Time Warping Distance)

    计算两个序列之间的最小累积对齐代价。
    使用标准 DTW 算法 — O(n·m) 时间复杂度。

    参数:
        s1 (array-like): 第一个序列
        s2 (array-like): 第二个序列

    返回:
        float: 归一化 DTW 距离 = dtw[n,m] / max(n,m)
    """
    n, m = len(s1), len(s2)
    # 初始化 DTW 矩阵，首行/首列为 inf，dtw[0,0] = 0
    dtw = np.full((n + 1, m + 1), np.inf)
    dtw[0, 0] = 0
    # 动态规划填充矩阵
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s1[i - 1] - s2[j - 1])  # 当前点对齐代价
            # 三种移动方式：插入、删除、匹配 的最小值 + 当前位置代价
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    return dtw[n, m] / max(n, m)  # 归一化到单位长度


class DtwKnnAlgorithm(BaseAlgorithm):
    """
    DTW-kNN 动态时间规整类比预测算法

    通过 DTW 距离在自身历史中搜索与当前增长模式最相似的窗口，
    然后用 k 个最相似窗口的后续表现为基础预测未来增速。

    属性:
        default_weight (float): 默认集成权重 1.2，因为 DTW-kNN 通常表现良好
    """

    name = "DTW-kNN类比"
    algorithm_id = "dtw_knn"
    description = "用DTW距离检索相似增长模式，加权平均预测"
    category = "统计模型"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 DTW-kNN 预测

        流程:
          1. 从历史数据构建"增长轮廓"（播放量/点赞/投币的梯度序列）
          2. 将轮廓切分为片段（segment）
          3. 取最新片段作为查询，用 DTW 搜索 k 个最近邻
          4. 基于近邻的后续增速加权平均预测未来速度

        参数:
            video_data (Dict): 视频数据，包含 view_count、history_data 等
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度无效时回退到简单预测
        if not _HAS_SCIPY or len(history) < 5 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            # 构建多维增长轮廓（播放量、点赞、投币的梯度）
            profile = self._build_profile(history)
            # 将轮廓切分为局部窗口
            segments = self._segment_profile(profile)
            if len(segments) < 2:
                return self._fallback(velocity, current_views, threshold)

            # 提取播放量序列
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            # 查询向量 = 最新片段（当前增长模式）
            query = segments[-1][1]
            # 在历史片段中搜索近邻
            distances = self._find_knn(query, segments)
            # k 取 min(3, 实际邻居数)，避免过少
            k = min(3, len(distances))

            # 最近邻距离极近（< 1e-10），可能是完全相同或退化情况
            if k == 0 or distances[0][0] < 1e-10:
                return self._fallback(velocity, current_views, threshold)

            # 窗口大小 n
            n = min(6, len(profile) // 2)
            if n < 2:
                n = 2
            # 基于近邻的后续表现预测未来速度
            predicted_velocity = self._predict_future_velocity(distances, k, views, n, velocity)

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / max(predicted_velocity, 1)
                # 置信度随 k 增大而提高（更多邻居 = 更稳健）
                confidence = min(0.9, 0.5 + 0.1 * k)

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "dtw_knn", "k": k, "min_dist": float(distances[0][0])},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    @staticmethod
    def _build_profile(history):
        """
        构建多维增长轮廓

        从历史数据中提取播放量、点赞、投币三个序列，
        分别计算梯度（np.gradient），合并为 (n, 3) 的轮廓矩阵。

        参数:
            history (List[Dict]): 历史数据列表

        返回:
            np.ndarray: (n, 3) 轮廓矩阵，列分别为播放量梯度、点赞梯度、投币梯度
        """
        views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
        # 使用梯度捕捉变化的速率和方向
        return np.column_stack(
            [
                np.gradient(views),
                np.gradient(likes),
                np.gradient(coins),
            ]
        )

    @staticmethod
    def _segment_profile(profile):
        """
        将轮廓切分为局部窗口片段

        使用滑动窗口，窗口大小 n = min(6, len(profile)//2)，
        步长为 n//2（50% 重叠），保证相邻片段有信息连续性。

        参数:
            profile (np.ndarray): (n, 3) 轮廓矩阵

        返回:
            List[Tuple[int, np.ndarray]]: 片段列表，每项为 (起始索引, 片段数据)
        """
        segments = []
        n = min(6, len(profile) // 2)
        if n < 2:
            n = 2
        for i in range(0, len(profile) - n, n // 2):
            seg = profile[i : i + n]
            if len(seg) == n:
                segments.append((i, seg))
        return segments

    @staticmethod
    def _find_knn(query, segments):
        """
        在历史片段中搜索 k 个最近邻

        排除最后一个片段（当前查询窗口自身），
        对之前的所有片段计算 DTW 距离并按距离升序排列。

        参数:
            query (np.ndarray): 查询片段（通常是最新片段）
            segments (List[Tuple]): 所有历史片段

        返回:
            List[Tuple]: 按 DTW 距离升序排列的邻居列表，每项为 (距离, 起始索引, 片段)
        """
        distances = []
        for start, seg in segments[:-1]:  # 排除最后一个（查询自己）
            d = _dtw_distance(query.flatten(), seg.flatten())
            distances.append((d, start, seg))
        distances.sort(key=lambda x: x[0])  # 按距离升序
        return distances

    @staticmethod
    def _predict_future_velocity(distances, k, views, n, velocity):
        """
        基于近邻的后续表现预测未来速度

        对每个近邻窗口，查看窗口结束后的实际播放量变化，
        用距离倒数作为权重加权平均。

        参数:
            distances (List[Tuple]): 排序后的近邻列表
            k (int): 使用的邻居数量
            views (np.ndarray): 完整播放量序列
            n (int): 窗口大小
            velocity (float): 当前速度（回退用）

        返回:
            float: 预测的未来速度
        """
        # 权重 = 1/distance，距离越近权重越大
        weights = np.array([1.0 / max(d[0], 1e-10) for d in distances[:k]])
        weights /= weights.sum()  # 归一化
        future_velocities = []
        for idx, (d, start, seg) in enumerate(distances[:k]):
            end_idx = start + n  # 窗口结束位置
            # 确保窗口后有足够数据计算后续增量
            if end_idx + 3 <= len(views):
                future = views[end_idx : end_idx + 3]  # 取窗口后 3 个点
                if len(future) >= 2:
                    # 计算后续的平均增量
                    fv = np.mean(np.diff(future))
                    future_velocities.append(fv)
        if future_velocities:
            return max(0, np.average(future_velocities, weights=weights[: len(future_velocities)]))
        return velocity  # 无有效后续数据，回退到当前速度

    def _fallback(self, velocity, current_views, threshold):
        """
        回退预测：当数据不足或计算失败时使用

        参数:
            velocity (float): 当前速度
            current_views (int): 当前播放量
            threshold (int): 目标阈值

        返回:
            PredictionResult: 回退预测结果
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "dtw_knn", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = threshold - current_views
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "dtw_knn", "reason": "fallback"},
            timestamp=datetime.now(),
        )
