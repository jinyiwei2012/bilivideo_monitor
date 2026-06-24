"""
层级贝叶斯模型 (Hierarchical Bayesian Model)
=============================================

利用 UP 主级别的超参数共享信息，将新视频纳入层级结构进行收缩估计
（Shrinkage Estimation）。通过贝叶斯方法将视频自身的局部信息与
UP 主的全局先验信息相结合，产生更稳健的预测。

核心原理：
    1. 层级结构 - 每个视频嵌套在 UP 主之下，UP 主的平均播放量作为先验均值
    2. 收缩估计 - 当视频自身数据较少或方差较大时，预测向 UP 主均值收缩
    3. 正态-正态共轭模型 - 先验 ~ N(mu_up, sigma_prior^2)
       似然 ~ N(local_mean, sigma_likelihood^2/n)
       后验 ~ N(posterior_mean, posterior_var)
    4. 速度收缩 - 速度也按相同的收缩因子向 UP 主平均速度收紧

数学推导：
    posterior_mean = (mu_prior/sigma_prior^2 + local_mean/sigma_likelihood^2) /
                     (1/sigma_prior^2 + 1/sigma_likelihood^2)
    shrinkage = local_var / (local_var + sigma_prior^2)

适用场景：
    - 需要利用 UP 主的历史表现对新视频做更可靠的预测
    - 数据量 >= 3 个历史点
    - 没有 UP 主历史数据时回退为局部均值
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HierarchicalBayesAlgorithm(BaseAlgorithm):
    """
    层级贝叶斯模型预测算法

    主要功能：
        - 利用 UP 主的历史平均播放量作为全局先验
        - 使用正态-正态共轭模型计算后验均值和方差
        - 通过收缩因子将视频自身速度向 UP 主平均速度收缩
        - 数据不足时回退为简单速度外推

    收缩因子的含义：
        shrinkage = local_var / (local_var + sigma_prior^2)
        - 当视频自身数据方差很大（不稳定）时，shrinkage 接近 1，预测向先验收缩
        - 当视频自身数据方差很小（稳定）时，shrinkage 接近 0，信任局部数据
    """

    name = "层级贝叶斯"
    algorithm_id = "hierarchical_bayes"
    description = "利用UP主历史信息的层级贝叶斯收缩估计"
    category = "高级分析"
    default_weight = 1.2

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行层级贝叶斯预测

        算法流程：
            1. 获取视频自身的局部统计量（均值、方差）
            2. 获取 UP 主的全局先验（平均播放量）
            3. 使用正态-正态共轭公式计算后验均值和方差
            4. 计算收缩因子：shrinkage = local_var / (local_var + sigma_prior^2)
            5. 按收缩因子混合局部速度和 UP 主平均速度
            6. 计算预测时间和置信度

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)       : 当前总播放量
                - history_data (list)    : 历史数据点列表
                - up_average_views (int) : UP 主历史平均播放量
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)
        up_avg_views = video_data.get("up_average_views", 0)  # UP 主平均播放量

        if len(history) < 3 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold, method="hierarchical_bayes")

        try:
            # 提取播放量序列
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            # 先验均值：优先使用 UP 主平均播放量，最小 1000
            mu_up = max(up_avg_views, 1000) if up_avg_views > 0 else current_views

            # 先验参数设置
            mu_prior = max(mu_up, current_views)  # 先验均值不低于当前播放量
            sigma_prior = mu_prior * 0.5  # 先验标准差设为均值的 50%（较宽的先验）

            # 局部统计量
            local_mean = np.mean(views)  # 局部样本均值
            local_var = np.var(views) + 1e-6  # 局部样本方差（加小量避免除零）

            # 似然：局部均值的标准误差 = sigma / sqrt(n)
            sigma_likelihood = np.sqrt(local_var / max(len(views), 1))

            # 后验均值：精度加权（精度 = 1/方差）
            posterior_mean = (mu_prior / (sigma_prior ** 2) + local_mean / (sigma_likelihood ** 2)) / (
                1 / (sigma_prior ** 2) + 1 / (sigma_likelihood ** 2)
            )

            # 后验方差：精度相加的倒数
            posterior_var = 1 / (1 / (sigma_prior ** 2) + 1 / (sigma_likelihood ** 2))

            # 收缩因子：数值越大，预测越向先验收缩
            shrinkage = local_var / (local_var + sigma_prior ** 2)
            # 收缩速度 = (1-shrinkage)*局部速度 + shrinkage*UP主平均速度
            shrunk_velocity = (1 - shrinkage) * velocity + shrinkage * (mu_up / 3600)

            predicted_velocity = max(0, shrunk_velocity)
            if predicted_velocity < 1:
                predicted_velocity = velocity  # 速度过小时退化为原始速度

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 后验置信区间宽度
                posterior_ci = 1.96 * np.sqrt(posterior_var)  # 95% 置信区间半宽
                cv = posterior_ci / max(posterior_mean, 1)  # 变异系数
                # 置信度：CV 越小（估计越精确）+ 收缩越小（局部数据可信）-> 置信度越高
                confidence = max(0.1, min(0.85, 0.5 - cv * 2 + 0.3 * (1 - shrinkage)))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "hierarchical_bayes",
                    "shrinkage": float(shrinkage),  # 收缩因子
                    "posterior_mean": float(posterior_mean),  # 后验均值
                    "up_avg_views": int(up_avg_views),  # UP 主平均播放量
                },
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold, method="hierarchical_bayes")
