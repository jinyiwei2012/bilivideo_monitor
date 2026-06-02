"""
质量衰减模型算法 (Quality-Adjusted Decay)

【算法类别】内容感知 / 复合预测

【核心思想】
将两个独立信号融合为一个预测：

  信号1 — 质量加权的时间衰减（权重 0.6）：
    - 基础衰减率 = 1 / 视频年龄（小时），年龄越大衰减越快
    - 质量调整后的衰减率 = 基础衰减率 / (0.3 + 0.7 × 质量分)
      高质量视频：分母 ≈ 1.0，衰减接近自然速度
      低质量视频：分母 ≈ 0.3，衰减加速约 3 倍
    - 质量折扣因子 = 0.4 + 0.6 × 质量分
      高质量视频 ≈ 1.0（几乎不打折），低质量 ≈ 0.4（打 4 折）
    - 24h 衰减倍率 = exp(-调整衰减率 × 24)，模拟一天后的留存比例

  信号2 — 近期速度趋势（权重 0.4）：
    - 最近 10 点的差分均值 + 趋势加速度修正
    - 趋势调整：tanh(加速度 / 近期增长)，非线性压缩到 (-1, 1)
    - 趋势增长 = 近期增长 × (1 + 0.2 × tanh(修正))

  最终预测 = 0.6 × 质量衰减信号 + 0.4 × 趋势信号

【处理流程】
  提取质量分/互动率/视频年龄 → 计算质量调整衰减率
  → 计算 24h 衰减倍率 → 质量衰减信号 = 当前速度 × 质量因子 × 衰减倍率
  → 计算近期趋势信号 → 加权融合 → 输出预测

【适用场景】
- 需要综合考虑"内容质量"和"时间流逝"对播放量的复合影响
- 长期预测（数天到数周），因为时间衰减效应在短期不明显
- 历史数据量 ≥8 点

【参数说明】
- 质量因子范围：[0.4, 1.0]，高质量视频衰减更缓
- 衰减倍率：exp(-衰减率 × 24)，模拟 24 小时的留存
- 融合权重：0.6 质量衰减 + 0.4 趋势，略微偏重长期结构
- 趋势修正系数：0.2，避免过度响应短期波动
- 置信度：基于质量分和数据点数，范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，融合质量衰减与趋势信号
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class QualityDecayAlgorithm(BaseAlgorithm):
    """
    质量衰减模型算法

    将视频的内容质量评分与时间衰减效应融合，结合近期速度趋势进行复合预测。
    质量越高的视频衰减越慢，前景越乐观；低质量视频则随时间加速衰减。

    类属性：
        name: 算法显示名称 "质量衰减"
        algorithm_id: 算法唯一标识符 "quality_decay"
        description: 内容质量分+时间衰减复合预测
        category: 算法分类 "内容感知"
        default_weight: 集成学习默认权重 1.0
    """

    name = "质量衰减"
    algorithm_id = "quality_decay"
    description = "内容质量分+时间衰减复合预测"
    category = "内容感知"
    default_weight = 1.0

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行质量衰减复合预测

        参数：
            video_data (Dict): 视频数据字典，必须包含:
                - view_count (int): 当前播放量
                - history_data (list): 历史监控记录列表，每条含 view_count 字段
                - 质量分、互动率、视频年龄（通过 base 类方法获取）
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
                - metadata: 附加信息（方法名、质量分、衰减率、视频年龄）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 8 点或无增速 → 回退匀速预测
            2. 提取视频的质量分、互动率、年龄（小时）
            3. 计算质量调整衰减率 = 基础衰减率 / (0.3 + 0.7 × 质量分)
            4. 计算 24 小时后的衰减倍率 = exp(-调整衰减率 × 24)
            5. 质量衰减信号 = 当前速度 × 3600 × 质量因子 × 衰减倍率
            6. 计算近期差分均值和趋势加速度作为趋势信号
            7. 加权融合：最终增长 = 0.6 × 质量衰减 + 0.4 × 趋势
            8. 计算达标时间和置信度
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为负/零时：回退到匀速预测
        if len(history) < 8 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "quality_decay_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 40 条历史记录中的播放量
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 通过基类方法获取视频的内容质量分、互动率和视频年龄（小时）
            quality = self.get_quality_score(video_data)  # 质量评分 [0, 1]
            engagement = self.get_engagement_rate(video_data)  # 互动率
            age_hours = self.get_video_age_hours(video_data)  # 视频发布至今的小时数

            # 质量加权的指数衰减
            # 基础衰减率：视频年龄越大衰减越快（1 / 年龄小时数）
            base_decay_rate = 1.0 / max(age_hours, 1) if age_hours > 0 else 0.01
            # 质量调整后衰减率：分母小→衰减大，高质量视频分母接近 1.0 衰减自然
            quality_decay_rate = base_decay_rate / (0.3 + 0.7 * quality)

            # 质量折扣因子: 高质量视频衰减缓，范围 [0.4, 1.0]
            quality_factor = 0.4 + 0.6 * quality

            # 近期速度趋势：最近 10 点的差分均值 + 加速度修正
            if n >= 5:
                # 最近 min(10, n) 个点的差分均值（每步增长量）
                recent_diffs = np.diff(views[-min(10, n):])
                recent_growth = np.mean(recent_diffs)
                # 趋势加速度：最近两步差分的变化量（正值加速、负值减速）
                trend_accel = recent_diffs[-1] - recent_diffs[-2] if len(recent_diffs) >= 2 else 0
            else:
                recent_growth = velocity * 3600  # 回退到当前速度
                trend_accel = 0

            # 复合预测: 质量×衰减 + 速度趋势
            # 时间衰减因子：exp(-调整衰减率 × 24)，模拟 24 小时后的留存比例
            time_factor = np.exp(-quality_decay_rate * 24)  # 24小时后衰减倍率
            # 质量衰减信号：当前每小时速度 × 质量折扣 × 24h 衰减倍率
            base_growth = velocity * 3600 * quality_factor * time_factor
            # 趋势信号：近期增长 × (1 + 0.2 × tanh(加速度/增长))，tanh 将修正压缩到 (-1, 1)
            trend_growth = recent_growth * (1 + 0.2 * np.tanh(trend_accel / max(recent_growth, 1)))
            # 加权融合：偏重质量衰减（0.6），趋势为辅（0.4）
            growth = 0.6 * base_growth + 0.4 * trend_growth

            # 换算为每秒速度
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            # 置信度：基础 0.3 + 质量加成（0-0.3）+ 数据点加成（0-0.5），上限 0.85
            confidence = max(0.1, min(0.85, 0.3 + 0.3 * quality + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "quality_decay",
                    "quality": round(float(quality), 3),  # 内容质量评分
                    "decay_rate": round(float(quality_decay_rate), 5),  # 质量调整衰减率
                    "age_hours": round(float(age_hours), 1),  # 视频发布至今的小时数
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
                metadata={"method": "quality_decay_error"}, timestamp=datetime.now(),
            )
