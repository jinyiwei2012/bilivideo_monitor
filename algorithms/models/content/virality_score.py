"""
病毒传播评分算法 (Virality Score)

【算法类别】内容感知 / 传播潜力评估

【核心思想】
通过多维度指标综合评估视频的"病毒式传播"潜力：

  维度1 — 播放量增速（权重 0.30）：
    近期播放量的相对增长率，增速越快 → 传播势能越强
    评分公式：min(1.0, max(0, 增长率 × 20))

  维度2 — 互动率（权重 0.35，最高权重）：
    综合互动指标：(点赞 + 硬币×2 + 收藏×3) / 播放量
    硬币和收藏被赋予更高权重，因为它们代表更深的用户认同
    评分公式：min(1.0, 平均互动率 × 20)

  维度3 — 分享率（权重 0.15）：
    分享数 / 播放量，是最直接的传播信号
    评分公式：min(1.0, 平均分享率 × 50)
    系数 ×50（高于互动率×20），因为分享天然稀少但更关键

  维度4 — 加速度（权重 0.20）：
    播放量增速的变化趋势，正加速度 = 传播在加速
    评分公式：将加速度映射到 [0, 1]，以 0.5 为中心

处理流程：
  提取各维度指标 → 分别归一化到 [0, 1]
  → 加权求和得到病毒传播评分 virality ∈ [0, 1]
  → 映射为加速因子 boost = 0.5 + 2.0 × virality ∈ [0.5, 2.5]
  → 调整后的增长 = 当前速度 × boost

【加速因子含义】
  - boost = 0.5：传播力最弱，预测减慢一半
  - boost = 1.0：无特殊传播效应，保持当前速度
  - boost = 2.5：病毒式传播，预测加速 2.5 倍

【适用场景】
- 需要综合评估视频的社交传播能力
- 判断视频是否具有"爆款"潜力
- 历史数据量 ≥8 点且包含互动数据（点赞、硬币、收藏、分享）

【参数说明】
- 权重分配：互动(0.35) > 播放量(0.30) > 加速度(0.20) > 分享(0.15)
- 互动权重偏移：硬币权重 2，收藏权重 3（反映用户投入程度）
- 加速因子范围：[0.5, 2.5]
- 置信度：基于病毒评分和数据点数，范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，计算四维度传播评分
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class ViralityScoreAlgorithm(BaseAlgorithm):
    """
    病毒传播评分算法

    从播放量增速、互动率、分享率和加速度四个维度综合评估视频的"病毒式传播"潜力，
    将各维度归一化后加权求和得到病毒传播评分，映射为加速因子调整增长预测。

    类属性：
        name: 算法显示名称 "病毒传播"
        algorithm_id: 算法唯一标识符 "virality_score"
        description: 多维传播潜力评分，预测病毒式增长概率
        category: 算法分类 "内容感知"
        default_weight: 集成学习默认权重 1.1
    """

    name = "病毒传播"
    algorithm_id = "virality_score"
    description = "多维传播潜力评分，预测病毒式增长概率"
    category = "内容感知"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行病毒传播评分预测

        参数：
            video_data (Dict): 视频数据字典，必须包含:
                - view_count (int): 当前播放量
                - history_data (list): 历史监控记录列表，每条含 view_count、like_count、
                  coin_count、share_count、favorite_count 字段
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
                - metadata: 附加信息（方法名、病毒评分、加速因子、各维度评分）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 8 点或无增速 → 回退匀速预测
            2. 取最近 30 条记录的播放量、点赞、硬币、分享、收藏
            3. 维度1：计算播放量增速 → 归一化到 [0, 1]
            4. 维度2：计算综合互动率（点赞+硬币×2+收藏×3）/播放量 → 归一化
            5. 维度3：计算分享率 → 归一化（分享×50，因分享稀缺加权更高）
            6. 维度4：计算加速度趋势 → 映射到 [0, 1] 以 0.5 为中心
            7. 加权求和得病毒评分，映射为加速因子 boost ∈ [0.5, 2.5]
            8. 调整增长 = 当前速度 × boost
            9. 计算达标时间和置信度
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
                metadata={"method": "viral_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 30 条历史记录，提取五个维度的数据
            views = np.array([h.get("view_count", 0) for h in history[-30:]], dtype=np.float64)
            likes = np.array([h.get("like_count", 0) for h in history[-30:]], dtype=np.float64)
            coins = np.array([h.get("coin_count", 0) for h in history[-30:]], dtype=np.float64)
            shares = np.array([h.get("share_count", 0) for h in history[-30:]], dtype=np.float64)
            favs = np.array([h.get("favorite_count", 0) for h in history[-30:]], dtype=np.float64)

            n = len(views)

            # 维度1: 播放量增速（权重 0.30）
            # 计算最近 8 个点的相对增长率：差分均值 / 原始均值
            recent_views = views[-min(8, n):]
            view_growth = np.mean(np.diff(recent_views)) / max(np.mean(recent_views[:-1]), 1) if len(recent_views) >= 2 else 0
            # 归一化：增长率 × 20，限制在 [0, 1]（增长率 5% = 满分）
            view_score = min(1.0, max(0, view_growth * 20))

            # 维度2: 互动率（权重 0.35，最高权重）
            # 综合互动指标：点赞×1 + 硬币×2 + 收藏×3，硬币和收藏代表更深用户认同
            engagement = (likes + coins * 2 + favs * 3) / np.maximum(views, 1)
            # 取最近 5 个点的平均互动率进行归一化
            recent_eng = engagement[-min(5, n):]
            eng_score = min(1.0, np.mean(recent_eng) * 20)

            # 维度3: 分享率（权重 0.15）
            # 分享数 / 播放量，分享天然稀少但传播信号最强
            share_rate = shares / np.maximum(views, 1)
            # 归一化系数 ×50（高于互动×20），因为分享比例通常远小于互动比例
            share_score = min(1.0, np.mean(share_rate[-min(5, n):]) * 50)

            # 维度4: 加速度（权重 0.20）
            # 播放量增速的变化趋势：二阶差分（加速度）的均值
            if n >= 6:
                vel = np.diff(views)  # 一阶差分 = 每步增长量（速度）
                accel = np.diff(vel[-min(6, len(vel)):])  # 二阶差分 = 加速度
                # 加速度得分映射到 [0, 1]，以 0.5 为中心（零加速度 = 0.5 分）
                accel_score = min(1.0, max(0, np.mean(accel) / max(abs(np.mean(accel)), 1e-10)) * 0.5 + 0.5)
            else:
                accel_score = 0.5  # 数据不足时默认中性加速度

            # 综合病毒传播评分：四维度加权求和
            w_view, w_eng, w_share, w_accel = 0.3, 0.35, 0.15, 0.2
            virality = w_view * view_score + w_eng * eng_score + w_share * share_score + w_accel * accel_score

            # 映射到加速因子 [0.5, 2.5]
            # virality=0 → boost=0.5（最弱），virality=1 → boost=2.5（最强）
            boost = 0.5 + 2.0 * virality
            # 应用加速因子：当前每小时速度 × boost
            growth = velocity * 3600 * boost

            # 换算回每秒速度
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            # 置信度：基础 0.3 + 病毒评分加成（0-0.4）+ 数据点加成（0-0.5），上限 0.85
            confidence = max(0.1, min(0.85, 0.3 + 0.4 * virality + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "virality_score",
                    "virality": round(float(virality), 3),  # 综合病毒传播评分 [0, 1]
                    "boost": round(float(boost), 2),  # 加速因子 [0.5, 2.5]
                    "scores": {
                        "view": round(float(view_score), 2),  # 播放量增速子评分
                        "engagement": round(float(eng_score), 2),  # 互动率子评分
                        "share": round(float(share_score), 2),  # 分享率子评分
                        "accel": round(float(accel_score), 2),  # 加速度子评分
                    },
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
                metadata={"method": "viral_error"}, timestamp=datetime.now(),
            )
