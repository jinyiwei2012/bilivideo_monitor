"""
互动衰减建模算法 (Engagement Decay Model)

【算法类别】内容感知 / 生命周期分析

【核心思想】
视频的互动率（点赞数/播放量）会随着时间推移自然衰减：
  - 发布初期：观众新鲜感强，互动率高 → 增长期（growth）
  - 中期：互动率趋于稳定，忠实观众持续互动 → 成熟期（mature）
  - 后期：新鲜感消退，互动率下降 → 衰退期（decline）

通过拟合互动率的衰减曲线来判断视频所处的生命周期阶段，
并据此调整播放量预测。

处理流程：
  播放量/点赞序列 → 计算互动率（点赞/播放）→ 对数线性拟合衰减率
  → 根据衰减率判定生命周期阶段 → 应用阶段因子调整增长预测

【生命周期阶段判定】
  衰减率 threshold    阶段          阶段因子    含义
  ───────────────────────────────────────────────────
  < -0.02            growth        1.3         互动率上升，高速增长期
  [-0.02, 0.005)     mature        1.0         互动率稳定，成熟期
  [0.005, 0.02)      decline_slow  0.7         缓慢衰减
  ≥ 0.02             decline_fast  0.4         快速衰减

【适用场景】
- 需要基于视频"内容质量"的客观指标（互动率）来预测未来播放量
- 判断视频是处于上升通道还是下降通道
- 历史数据量 ≥10 点且包含点赞数据

【参数说明】
- 指数衰减拟合：对 log(互动率 - min(互动率) + ε) 做一阶多项式拟合
- 衰减率 = -拟合斜率（正值为衰减，负值为增长）
- 阶段因子范围：[0.4, 1.3]，对应快速衰退到高速增长
- 置信度：基于阶段因子和数据点数，范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，拟合互动衰减并判定生命周期
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class EngagementDecayAlgorithm(BaseAlgorithm):
    """
    互动衰减建模算法

    通过分析视频的互动率（点赞/播放）随时间的变化趋势，拟合互动衰减曲线，
    判断视频所处的生命周期阶段（增长期、成熟期、缓慢衰退期、快速衰退期），
    并基于阶段因子调整播放量增长速度的预测。

    类属性：
        name: 算法显示名称 "互动衰减"
        algorithm_id: 算法唯一标识符 "engagement_decay"
        description: 互动率衰减曲线拟合，推断视频生命周期阶段
        category: 算法分类 "内容感知"
        default_weight: 集成学习默认权重 1.1
    """

    name = "互动衰减"
    algorithm_id = "engagement_decay"
    description = "互动率衰减曲线拟合，推断视频生命周期阶段"
    category = "内容感知"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行互动衰减预测

        参数：
            video_data (Dict): 视频数据字典，必须包含:
                - view_count (int): 当前播放量
                - history_data (list): 历史监控记录列表，每条含 view_count、like_count 字段
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
                - metadata: 附加信息（方法名、衰减率、生命周期阶段）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 10 点或无增速 → 回退匀速预测
            2. 提取最近 40 条记录的播放量和点赞数
            3. 计算互动率 = 点赞 / max(播放, 1)
            4. 对数变换后做一阶多项式拟合，衰减率 = -斜率
            5. 根据衰减率阈值判定生命周期阶段并应用阶段因子
            6. 调整增长 = 当前速度 × 3600 × 阶段因子
            7. 计算达标时间和置信度
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据量不足或速度为负/零时：回退到匀速预测
        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "decay_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 40 条历史记录，提取播放量和点赞数
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            likes = np.array([h.get("like_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 计算互动率序列：点赞数 / 播放量（播放量过小用 1 兜底防止除零）
            engagement = likes / np.maximum(views, 1)
            x = np.arange(n)

            # 指数衰减拟合: eng = a * exp(-lambda * t) + c
            # 转换为对数域做线性拟合: log(eng - min(eng) + ε) = k * t + b，衰减率 = -k
            try:
                valid = engagement > 0  # 仅使用互动率 > 0 的有效点
                if np.sum(valid) >= 5:
                    # 对数变换：减去最小值使数据非负，加小量 ε = 1e-10 防止 log(0)
                    log_eng = np.log(engagement[valid] - np.min(engagement[valid]) + 1e-10)
                    coeff = np.polyfit(x[valid], log_eng, 1)  # 一阶多项式拟合
                    decay_rate = -coeff[0]  # 衰减率 = -斜率（正值=衰减，负值=增长）
                else:
                    decay_rate = 0.01  # 有效点不足时默认轻微衰减
            except Exception:
                decay_rate = 0.01  # 拟合异常时默认轻微衰减

            # 生命周期阶段判定：根据衰减率区间划分 4 个阶段
            if decay_rate < -0.02:
                stage = "growth"  # 互动率上升，高速增长期
                stage_factor = 1.3  # 增长加成 30%
            elif decay_rate < 0.005:
                stage = "mature"  # 互动率稳定，成熟期
                stage_factor = 1.0  # 保持当前速度
            elif decay_rate < 0.02:
                stage = "decline_slow"  # 互动率缓慢衰减
                stage_factor = 0.7  # 预测减速 30%
            else:
                stage = "decline_fast"  # 互动率快速衰减
                stage_factor = 0.4  # 预测减速 60%

            # 应用阶段因子调整增长预测：growth = 当前每秒速度 × 3600（转为每小时） × 阶段因子
            growth = velocity * 3600 * stage_factor
            # 换算回每秒速度
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时回退到当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            # 置信度：基础 0.3 + 阶段因子加成（0-0.3）+ 数据点加成（0-0.5），上限 0.85
            confidence = max(0.1, min(0.85, 0.3 + 0.1 * min(stage_factor, 3) + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "engagement_decay",
                    "decay_rate": round(float(decay_rate), 4),  # 记录衰减率到 4 位小数
                    "stage": stage,  # 记录生命周期阶段
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
                metadata={"method": "decay_error"}, timestamp=datetime.now(),
            )
