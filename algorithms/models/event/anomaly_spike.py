"""
异常脉冲检测算法 (Anomaly Spike Detection)

【算法类别】事件驱动 / 异常检测

【核心思想】
播放量数据由两部分叠加组成：
  - 基线（Baseline）：自然增长趋势，反映视频的"正常"播放速度
  - 脉冲（Spike）：事件驱动的短期爆发，如被推荐、上热门、外部引流等

处理流程：
  1. 计算播放量的一阶差分序列（每步增量）
  2. 滑动窗口 Z-score 检测异常脉冲点：
     对每个时间点，用前 window 个差分值估计局部均值和标准差，
     若当前差分值偏离超过 2σ，则标记为脉冲
  3. 分离脉冲与基线：非脉冲点均值 = 基线增长，脉冲点均值 = 脉冲幅度
  4. 脉冲衰减建模：假设脉冲后遵循指数衰减，
     衰减系数 0.3 × (脉冲数/总长)，脉冲越多衰减越快
  5. 调整增长预测 = 基线 + 脉冲幅度 × exp(-衰减系数 × 脉冲比例)

【适用场景】
- 视频短期内播放量出现明显的"跳跃式"增长
- 需要在预测中区分"可持续增长"与"一次性爆发"
- 历史数据量 ≥10 点

【参数说明】
- Z-score 阈值：2.0，约 5% 概率的显著偏离
- 滑动窗口大小：min(10, n//3)，自适应数据量
- 衰减系数：0.3，控制脉冲能量的消散速度
- 脉冲比例上限：50%，超过此比例则认为全序列异常
- 置信度：基于脉冲比例（脉冲越少越可信），范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，执行脉冲检测与衰减建模
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class AnomalySpikeAlgorithm(BaseAlgorithm):
    """
    异常脉冲检测算法

    使用滑动窗口 Z-score 方法检测播放量时序中的异常脉冲点，
    将数据分解为基线（自然增长）和脉冲（事件爆发）两个分量，
    对脉冲分量建立指数衰减模型后合成调整后的增长预测。

    类属性：
        name: 算法显示名称 "脉冲检测"
        algorithm_id: 算法唯一标识符 "anomaly_spike"
        description: Z-score滑动窗口检测播放量异常脉冲，建模衰减
        category: 算法分类 "事件驱动"
        default_weight: 集成学习默认权重 1.0
    """

    name = "脉冲检测"
    algorithm_id = "anomaly_spike"
    description = "Z-score滑动窗口检测播放量异常脉冲，建模衰减"
    category = "事件驱动"
    default_weight = 1.0

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行异常脉冲检测预测

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
                - metadata: 附加信息（方法名、脉冲数、脉冲比例）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 10 点或无增速 → 回退匀速预测
            2. 计算播放量一阶差分序列（每步增长量）
            3. 滑动窗口 Z-score：对每个时间点，用前 window 个差分估计局部均值和标准差
               若 Z-score > 2.0，标记该点为异常脉冲
            4. 分离基线（非脉冲点均值）和脉冲幅度（脉冲点均值-基线）
            5. 脉冲衰减建模：adjusted_growth = 基线 + 脉冲幅度 × exp(-0.3 × 脉冲比例)
            6. 若脉冲比例 ≥ 50%，全序列视为异常，取整体均值
            7. 计算达标时间和置信度（脉冲越少越可信）
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为负/零时：回退到匀速预测
        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spike_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 40 条历史记录的播放量
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 滑动窗口 Z-score 检测异常脉冲
            # 窗口大小取 min(10, n//3)，自适应数据量
            window = min(10, n // 3)
            diffs = np.diff(views)  # 一阶差分：每步增长量
            spikes = np.zeros(len(diffs), dtype=bool)  # 脉冲标记数组
            for i in range(window, len(diffs)):
                # 取当前点之前的 window 个差分值作为局部参考窗口
                local = diffs[max(0, i - window): i]
                # 局部窗口至少 3 个点且标准差 > 0 才计算 Z-score
                if len(local) >= 3 and np.std(local) > 0:
                    z = (diffs[i] - np.mean(local)) / np.std(local)  # 标准化Z-score
                    if z > 2.0:  # 2σ 阈值，约 5% 显著性水平
                        spikes[i] = True  # 标记为异常脉冲

            # 分离脉冲和基线
            n_spikes = np.sum(spikes)
            # 脉冲点数量在合理范围内（>0 且 <50%）时才做分离
            if n_spikes > 0 and n_spikes < len(diffs) * 0.5:
                # 基线 = 非脉冲点的平均每步增长量
                baseline = np.mean(diffs[~spikes]) if np.sum(~spikes) > 0 else np.mean(diffs)
                # 脉冲幅度 = 脉冲点均值超出基线的部分
                spike_magnitude = np.mean(diffs[spikes]) - baseline if n_spikes > 0 else 0
                # 脉冲后衰减: 假设指数衰减模型
                # 衰减系数 0.3，脉冲越多→衰减比例越大→脉冲贡献被削弱更多
                decay_rate = 0.3 if not np.isnan(spike_magnitude) else 0.2
                # 调整增长 = 基线 + 脉冲幅度 × exp(-衰减率 × 脉冲比例)
                adjusted_growth = baseline + spike_magnitude * np.exp(-decay_rate * n_spikes / max(n, 1))
            else:
                # 脉冲过多（≥50%）或为零：视为异常，取整体均值
                adjusted_growth = np.mean(diffs)

            # 换算为每秒速度（差分值 / 3600 秒）
            predicted_velocity = max(0, adjusted_growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            # 脉冲比例：脉冲点占总差分点数的比例
            spike_ratio = n_spikes / max(len(diffs), 1)
            # 置信度：脉冲越少越可信，基础 0.5 × (1-脉冲比例) + 数据点加成
            confidence = max(0.1, min(0.85, 0.5 * (1 - spike_ratio) + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "anomaly_spike", "spikes": int(n_spikes), "spike_ratio": round(spike_ratio, 3)},
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
                metadata={"method": "spike_error"}, timestamp=datetime.now(),
            )
