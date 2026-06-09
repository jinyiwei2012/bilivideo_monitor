"""
热搜趋势检测算法 (Hot Trend Detection)

【算法类别】事件驱动 / 趋势识别

【核心思想】
通过分析播放量序列的高阶导数来判断视频是否处于"热搜加速"状态：

  一阶差分（速度 v1）：播放量的逐期变化量，类比物理中的速度
  二阶差分（加速度 v2）：速度的变化量，正值表示速度在加快
  三阶差分（急动度 v3）：加速度的变化量，反映加速度变化的剧烈程度

  通过三个物理量联合判断：
    - 加速度是否持续为正（accel_persistent > 0.6）？
    - 加速度均值为正（recent_accel > 0）？
    - 急动度的方向和大小？

处理流程：
  播放量序列 → 逐阶差分得到 v1/v2/v3
  → 判定加速度持续性（近 5 点中正加速度占比）
  → 分三种情况预测：
    1. 加速中（持续性 > 0.6 且 accel > 0）：二次外推，趋势因子 > 1
    2. 减速中（持续性 < 0.3）：保守估计，取 0.7 倍当前速度
    3. 平稳：维持当前速度

【三种状态判定】
  加速：accel_persistent > 0.6 且 recent_accel > 0
       → growth = 当前速度 × (1 + 0.3 × 持续性 + 0.1 × 急动度)
  减速：accel_persistent < 0.3
       → growth = 当前速度 × 0.7
  平稳：else
       → growth = 当前速度

【适用场景】
- 视频突然被推荐或登上热门，播放量进入加速阶段
- 需要判断当前的增长趋势是"加速"还是"减速"
- 历史数据量 ≥12 点（需要足够点数计算二阶/三阶差分）

【参数说明】
- 加速度持续性窗口：最近 5 个加速度点
- 急动度窗口：最近 2 个三阶差点
- 加速加成系数：持续性 0.3、急动度 0.1
- 减速惩罚系数：0.7
- 置信度：基于加速度持续性和数据点数，范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，计算高阶导数并判定趋势状态
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HotTrendAlgorithm(BaseAlgorithm):
    """
    热搜趋势检测算法

    借鉴物理学运动学概念，通过计算播放量序列的一阶差分（速度）、二阶差分（加速度）、
    三阶差分（急动度），判断视频是否处于加速、减速或平稳状态，
    并据此调整增长预测（加速→加速加成，减速→保守估计，平稳→维持现状）。

    类属性：
        name: 算法显示名称 "热搜趋势"
        algorithm_id: 算法唯一标识符 "hot_trend"
        description: 二阶导数拐点检测+加速度持续判断，识别趋势加速
        category: 算法分类 "事件驱动"
        default_weight: 集成学习默认权重 1.1
    """

    name = "热搜趋势"
    algorithm_id = "hot_trend"
    description = "二阶导数拐点检测+加速度持续判断，识别趋势加速"
    category = "事件驱动"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行热搜趋势检测预测

        参数：
            video_data (Dict): 视频数据字典，必须包含:
                - view_count (int): 当前播放量
                - history_data (list): 历史监控记录列表，每条含 view_count 字段
            threshold (int): 目标播放量阈值，默认 10 万

        返回：
            PredictionResult: 包含预测结果的命名元组，字段包括:
                - algorithm_name: 算法名称
                - algorithm_id: 算法标识符
                - target_threshold: 目标阈值
                - predicted_hours: 预测达到阈值所需小时数
                - confidence: 置信度 [0.1, 0.85]
                - current_views: 当前播放量
                - current_velocity: 当前速度（播放/秒）
                - metadata: 附加信息（方法名、加速度持续性、急动度）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 12 点或无增速 → 回退匀速预测
            2. 计算一阶差分（速度 v1）、二阶差分（加速度 v2）、三阶差分（急动度 v3）
            3. 加速度持续性判定：最近 5 个加速度点中正值占比
            4. 三种状态分支：
               - 加速中（持续性 > 0.6 且 accel > 0）：growth = vel × (1 + 0.3×持续性 + 0.1×急动度)
               - 减速中（持续性 < 0.3）：growth = vel × 0.7
               - 平稳（其他）：growth = vel
            5. 计算达标时间和置信度（持久性越高越可信）
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为负/零时：回退到匀速预测
        if len(history) < 12 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "hot_trend_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 40 条历史记录的播放量
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            diffs = np.diff(views)  # 一阶差分
            if len(diffs) < 8:
                # 差分数据不足 8 点：无法计算二阶/三阶差分，直接使用当前速度
                growth = velocity * 3600
            else:
                # 一阶差分（速度）：每步播放量变化量
                v1 = diffs
                # 二阶差分（加速度）：速度的变化量，正值=加速，负值=减速
                v2 = np.diff(v1)
                # 三阶差分（加加速度/急动度）：加速度的变化量，反映变化剧烈程度
                v3 = np.diff(v2) if len(v2) >= 2 else np.zeros(len(v2))

                # 加速度持续性检测：最近 5 个加速度点中正值所占比例
                recent_v2 = v2[-min(5, len(v2)):]
                accel_positive = np.sum(recent_v2 > 0)  # 正加速度的个数
                accel_persistent = accel_positive / max(len(recent_v2), 1)  # 持续性 [0, 1]

                # 趋势强度指标
                # 当前速度：最近 3 个一阶差分的均值
                current_vel = np.mean(v1[-3:]) if len(v1) >= 3 else np.mean(v1)
                # 近期加速度均值
                recent_accel = np.mean(recent_v2)
                # 急动度：最近 2 个三阶差分的均值
                jerk = np.mean(v3[-2:]) if len(v3) >= 2 else 0

                # 趋势判定：根据加速度持续性和方向分三种情况
                if accel_persistent > 0.6 and recent_accel > 0:
                    # 加速中: 二次外推
                    # trend_factor > 1，加速度越持久、急动度越大，加成越多
                    trend_factor = 1.0 + 0.3 * accel_persistent + 0.1 * min(jerk, 5)
                    growth = max(0, current_vel * trend_factor)
                elif accel_persistent < 0.3:
                    # 减速中: 保守估计，取当前速度的 70%
                    growth = max(0, current_vel * 0.7)
                else:
                    # 平稳：维持当前速度不变
                    growth = current_vel

            # 换算为每秒速度
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            # 置信度：基础 0.3 + 加速度持续性加成（0-0.3）+ 数据点加成（0-0.5）
            confidence = max(0.1, min(0.85, 0.3 + 0.3 * accel_persistent + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "hot_trend",
                    "accel_persist": round(float(accel_persistent), 3),  # 加速度持续性 [0, 1]
                    "jerk": round(float(jerk), 3),  # 急动度（加速度的变化率）
                },
                timestamp=datetime.now(),
            )
        except Exception:
            # 任何异常回退到匀速预测
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "hot_trend_error"}, timestamp=datetime.now(),
            )
