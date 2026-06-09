"""
UP主历史表现贝叶斯模型 — Upcaster History Bayesian Model
========================================================

利用 UP 主历史视频数据，通过贝叶斯估计提升当前视频的播放量预测准确性。

核心原理：
  1. 使用 UP 主历史视频的平均增速作为先验分布（正态分布）
  2. 结合当前视频的实际观测数据（似然）
  3. 贝叶斯更新得到后验分布：
     - 后验均值 = prior_weight × 先验均值 + (1 - prior_weight) × 当前速度
     - 等效于正态-正态共轭模型的加权平均
  4. 置信度基于历史视频数量、当前数据量和先验强度

贝叶斯框架:
  - 先验 (Prior): UP 主历史视频的平均增速 → N(μ_prior, σ²_prior)
  - 似然 (Likelihood): 当前视频观测增速 → N(μ_obs, σ²_obs/n)
  - 后验 (Posterior): 加权融合先验和观测 → N(μ_post, σ²_post)

适用场景：UP 主有 >= 3 个历史视频数据，当前视频数据量较少时特别有效
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class UpcasterHistoryBayesianAlgorithm(BaseAlgorithm):
    """
    UP主历史表现贝叶斯预测算法

    通过贝叶斯推断，将 UP 主历史表现作为先验，
    结合当前视频数据得到更准确的预测。
    历史数据越多，先验越强；当前数据越多，观测越可靠。

    属性:
        min_history_videos (int): 最少需要多少历史视频才能建立可靠先验，默认 3
        prior_weight (float): 先验分布在贝叶斯更新中的权重，默认 0.3
        default_weight (float): 默认集成权重 1.4，贝叶斯方法通常更可靠
    """

    name = "UP主历史贝叶斯"
    algorithm_id = "upcaster_history_bayesian"
    description = "利用UP主历史数据，通过贝叶斯估计提升预测准确性"
    category = "贝叶斯模型"
    default_weight = 1.4

    def __init__(self):
        """初始化 UP 主贝叶斯模型"""
        super().__init__()
        self.min_history_videos = 3  # 最少需要多少历史视频才能建立可靠的先验
        self.prior_weight = 0.3  # 先验分布的权重（越高越依赖历史表现）

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行贝叶斯预测

        流程:
          1. 获取 UP 主历史数据（历史视频表现、平均增速、成功率）
          2. 若无 UP 主历史数据，退化为基于当前数据的普通预测
          3. 若 UP 主历史数据存在，执行贝叶斯更新：
             - 构造先验分布（基于 UP 主历史表现）
             - 观测当前视频的实际表现（似然）
             - 加权融合得到后验速度
          4. 用后验速度计算到达阈值所需时间

        参数:
            video_data (Dict): 视频数据，可包含：
                - upcaster_history: UP 主历史视频的表现数据列表
                - upcaster_avg_velocity: UP 主平均增速
                - upcaster_success_rate: UP 主成功率
                - view_count, history_data 等标准字段
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 包含先验/后验速度等元数据
        """
        current_views = video_data.get("view_count", 0)

        # 获取 UP 主历史数据
        upcaster_history = video_data.get("upcaster_history", [])
        upcaster_avg_vel = video_data.get("upcaster_avg_velocity")
        upcaster_success_rate = video_data.get("upcaster_success_rate")

        # 计算当前视频的速度
        current_velocity = self.calculate_velocity(video_data)

        # 如果没有 UP 主历史数据，退化为普通预测
        if not upcaster_history and upcaster_avg_vel is None:
            return self._predict_fallback(video_data, threshold, current_velocity)

        # 使用贝叶斯更新融合先验和当前观测
        posterior_velocity, confidence = self._bayesian_update(
            current_velocity, upcaster_history, upcaster_avg_vel, upcaster_success_rate, video_data
        )

        # 计算预测时间
        if posterior_velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0  # 已达阈值
                confidence = 1.0
            else:
                predicted_hours = remaining / posterior_velocity

        # 构造元数据，包含先验和后验信息供调试分析
        metadata = {
            "prior_velocity": float(upcaster_avg_vel) if upcaster_avg_vel else None,  # 先验速度
            "current_velocity": current_velocity,  # 当前观测速度
            "posterior_velocity": posterior_velocity,  # 后验速度
            "upcaster_history_count": len(upcaster_history),  # 历史视频数
            "prior_weight": self.prior_weight,  # 先验权重
            "method": "bayesian_update",
        }

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=posterior_velocity,  # 使用后验速度
            metadata=metadata,
            timestamp=datetime.now(),
        )

    def _bayesian_update(
        self,
        current_vel: float,
        history: List[Dict],
        prior_avg: Optional[float],
        prior_success: Optional[float],
        video_data: Dict,
    ) -> Tuple[float, float]:
        """
        贝叶斯更新：融合 UP 主历史先验和当前视频观测

        使用共轭先验：假设速度服从正态分布，使用正态-正态共轭模型。

        先验构造策略:
          - 若有 prior_avg（预设均值）：
            · 历史视频 >= min_history_videos：先验方差小（0.3×均值²→σ≈0.3μ）
            · 历史视频不足：先验方差大（0.5×均值²→σ≈0.5μ）
          - 若无 prior_avg 但有历史数据：
            · 从历史视频计算均值和方差
          - 完全无信息：
            · 使用当前速度作为先验，方差较大

        后验更新:
          使用加权平均近似正态-正态共轭的后验均值：
            μ_post = prior_weight × μ_prior + (1 - prior_weight) × μ_obs

        置信度:
          综合历史视频数量、当前数据量和先验强度

        参数:
            current_vel (float): 当前视频的观测速度
            history (List[Dict]): UP 主历史视频表现数据
            prior_avg (Optional[float]): 预设的先验均值
            prior_success (Optional[float]): UP 主成功率
            video_data (Dict): 当前视频数据

        返回:
            Tuple[float, float]: (后验速度, 置信度)
        """
        # ── 构造先验分布 N(mu_prior, sigma_prior²) ──
        if prior_avg is not None:
            mu_prior = prior_avg  # 使用预设的先验均值
            # 根据历史数据数量确定先验方差（数据越多 → 先验越精确 → 方差越小）
            if len(history) >= self.min_history_videos:
                # 有充足历史数据，先验方差小（先验置信度高）
                (mu_prior * 0.3) ** 2  # σ_prior = 0.3 × μ_prior
            else:
                # 历史数据少，先验方差大（先验更不确定）
                (mu_prior * 0.5) ** 2  # σ_prior = 0.5 × μ_prior
        else:
            # 从 history 计算先验
            if len(history) >= self.min_history_videos:
                # 从各历史视频提取平均速度
                vels = [h.get("avg_velocity", 0) for h in history]
                mu_prior = np.mean(vels)  # 先验均值 = 各视频平均速度的均值
                np.var(vels) + 1e-6  # 先验方差 = 各视频速度的方差
            else:
                # 无先验信息，使用当前速度作为先验（但方差较大表示不确定）
                mu_prior = current_vel if current_vel > 0 else 100.0  # 当前速度或默认 100
                (mu_prior * 0.5) ** 2  # σ_prior = 0.5 × μ_prior

        # ── 当前视频的观测（似然） ──
        # 使用当前视频的历史数据估计观测方差
        history_data = video_data.get("history_data", [])
        if len(history_data) >= 2:
            # 计算速度序列的方差作为观测方差
            vels = self._extract_velocities(history_data)
            if len(vels) >= 2:
                np.var(vels) + 1e-6  # σ_obs² = 观测速度的方差
                n_observations = len(vels)  # 观测数量
            else:
                (current_vel * 0.4) ** 2 + 1e-6  # σ_obs = 0.4 × μ_obs
                n_observations = 1
        else:
            (current_vel * 0.5) ** 2 + 1e-6  # 无足够数据，取较大方差
            n_observations = 1

        # ── 贝叶斯更新 ──
        # 正态-正态共轭模型的后验均值精确公式：
        #   μ_post = (μ_prior/σ²_prior + n·μ_obs/σ²_obs) / (1/σ²_prior + n/σ²_obs)
        # 为简化计算，使用固定权重的加权平均近似：
        prior_weight = self.prior_weight  # 先验权重
        obs_weight = 1.0 - prior_weight  # 观测权重

        if current_vel > 0:
            # 加权平均融合
            posterior_mu = prior_weight * mu_prior + obs_weight * current_vel
        else:
            # 当前无有效速度（如新发布的视频），完全使用先验
            posterior_mu = mu_prior

        # ── 置信度计算 ──
        # 历史数据越多、当前数据越充足，置信度越高
        history_bonus = min(0.3, len(history) * 0.05)  # 历史视频数量加成（上限 0.3）
        data_bonus = min(0.2, n_observations * 0.05)  # 当前观测数加成（上限 0.2）
        prior_strength = 0.5 if len(history) >= self.min_history_videos else 0.3  # 先验强度

        confidence = min(0.95, prior_strength + history_bonus + data_bonus)  # 综合置信度

        return max(0, posterior_mu), confidence

    def _extract_velocities(self, history_data: List[Dict]) -> List[float]:
        """
        从 history_data 中提取速度序列

        速度 = (播放量增量) / (时间增量/3600) = 每小时新增播放量

        处理多种时间戳格式（float、datetime 对象、字符串），
        过滤无效数据（时间倒退、零间隔、零或负增量）。

        参数:
            history_data (List[Dict]): 历史数据列表

        返回:
            List[float]: 速度序列（每小时增量）
        """
        if len(history_data) < 2:
            return []

        vels = []
        for i in range(1, len(history_data)):
            v0 = float(history_data[i - 1].get("view_count", 0))  # 前一点播放量
            v1 = float(history_data[i].get("view_count", 0))  # 当前点播放量

            t0 = history_data[i - 1].get("timestamp", 0)  # 前一点时间戳
            t1 = history_data[i].get("timestamp", 0)  # 当前点时间戳

            # 处理多种时间戳格式 → 统一转为秒（浮点）
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            elif isinstance(t0, str):
                try:
                    from datetime import datetime as dt

                    t0 = dt.fromisoformat(t0).timestamp()
                except Exception:
                    continue  # 解析失败跳过

            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            elif isinstance(t1, str):
                try:
                    from datetime import datetime as dt

                    t1 = dt.fromisoformat(t1).timestamp()
                except Exception:
                    continue

            dt_hours = (t1 - t0) / 3600.0  # 时间差转为小时
            if dt_hours <= 0:
                continue  # 跳过时间倒退或零间隔

            vel = (v1 - v0) / dt_hours  # 每小时播放增量
            if vel > 0:  # 只保留正速度（播放量应该只增不减）
                vels.append(vel)

        return vels

    def _predict_fallback(self, video_data: Dict, threshold: int, velocity: float) -> PredictionResult:
        """
        退化为普通预测（无 UP 主历史数据时使用）

        当没有 UP 主历史数据时，直接使用当前视频的速度做简单预测。
        置信度较低（0.4），因为没有先验信息增强可信度。

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标阈值
            velocity (float): 当前速度

        返回:
            PredictionResult: 回退预测结果
        """
        current_views = video_data.get("view_count", 0)

        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours = 0  # 已达阈值
                confidence = 1.0
            else:
                predicted_hours = remaining / velocity  # 简单外推
                confidence = 0.4  # 无历史数据，置信度较低

        metadata = {"method": "fallback_no_history", "prior_velocity": None, "posterior_velocity": velocity}

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
