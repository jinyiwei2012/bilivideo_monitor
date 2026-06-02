"""
马尔可夫体制转换预测算法 (Markov Regime Switching Prediction)

使用隐马尔可夫链（HMM）描述B站视频播放量增长在不同"体制"（Regime）间的切换。

核心原理：
    B站视频的播放量增长通常会经历几个不同阶段：
    1. 快速增长期（体制1）：发布初期，获得大量推荐流量，增速极快
    2. 稳定增长期（体制2）：推荐流量消退后，依靠搜索和关注流量的平稳增长
    3. 衰退期（体制3）：播放量增长趋于停滞

    模型使用隐马尔可夫链描述体制之间的转换概率，
    通过前向算法（Forward Algorithm）估计每个时间点属于各体制的概率，
    然后用蒙特卡洛模拟未来多个可能路径，取中位数作为最终预测。

算法流程:
    1. 前向算法 → 估计历史各点的体制概率分布
    2. 硬分配 → 将每个点分配到最可能的体制
    3. 参数估计 → 每个体制内独立估计增长参数
    4. 蒙特卡洛 → 模拟多条未来路径（含体制转换）
    5. 聚合 → 取中位数达标天数作为预测

适用场景：
    - 经历了明显阶段变化的视频（新发布 → 热门 → 平稳）
    - 需要建模多阶段转换的视频
    - 有足够历史数据（≥6点）的预测

参考:
    Hamilton, J. D. (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series"
"""

import math
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MarkovSwitchingAlgorithm(BaseAlgorithm):
    """马尔可夫体制转换模型

    B 站视频播放量通常经历不同阶段：
    - 体制1 (快速增长): 发布初期，推荐流量大
    - 体制2 (稳定增长): 日常搜索流量
    - 体制3 (衰退期): 播放量增长停滞

    模型使用隐马尔可夫链描述体制之间的转换，
    每个体制内用独立的增长模型预测。

    属性:
        name (str): 算法显示名称 "马尔可夫体制转换"
        algorithm_id (str): 算法唯一标识 "markov_switching"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.2
        n_regimes (int): 体制数量，默认 2
        transition (np.ndarray): 转移概率矩阵 P[i][j] = 从体制i转移到j的概率
    """

    name = "马尔可夫体制转换"
    algorithm_id = "markov_switching"
    description = "隐马尔可夫链描述增长体制切换，独立预测各阶段"
    category = "时间序列"
    default_weight = 1.2

    def __init__(self):
        """初始化马尔可夫体制转换模型"""
        super().__init__()
        self.n_regimes = 2
        # 转移概率矩阵 (P[i][j] = 从体制i转移到j的概率)
        # 对角线元素表示停留在当前体制的概率
        # [0.85, 0.15]: 体制1有85%概率保持，15%切换到体制2
        # [0.10, 0.90]: 体制2有10%切换到体制1，90%保持
        self.transition = np.array([[0.85, 0.15], [0.10, 0.90]])

    def _forward_algorithm(self, emissions: np.ndarray) -> np.ndarray:
        """前向算法计算每个时间点的体制概率分布

        前向算法（Forward Algorithm）是隐马尔可夫链的基础算法，
        用于计算给定观测序列下每个时刻的隐藏状态概率。

        参数:
            emissions (np.ndarray): 观测序列（增长率数组）

        返回:
            np.ndarray: shape (n, n_regimes)，每行是各体制的概率分布

        算法步骤:
            1. 初始化：均匀分布
            2. 递推: α_t = obs_prob × (α_{t-1} × T)
            3. 归一化: 每步除以总和防止数值下溢
        """
        n = len(emissions)
        T = self.transition

        # 初始化 (均匀分布：各体制等概率)
        alpha = np.ones(self.n_regimes) / self.n_regimes

        # 观测概率（基于增长率的各体制似然）
        probs = np.zeros((n, self.n_regimes))

        for t in range(n):
            # 根据增长率计算属于每个体制的概率
            # 使用高斯分布作为观测模型
            g = emissions[t]
            if self.n_regimes == 2:
                # 体制1: 高增长 (均值0.08, std 0.04)
                # 体制2: 低增长 (均值0.01, std 0.015)
                means = np.array([0.08, 0.01])
                stds = np.array([0.04, 0.015])
            else:
                # 三体制: 高增长/中增长/衰退
                means = np.array([0.08, 0.02, 0.0])
                stds = np.array([0.04, 0.02, 0.01])

            # 高斯概率密度: p(g|regime) = exp(-0.5 * ((g-μ)/σ)²) / (√(2π) × σ)
            obs_prob = np.exp(-0.5 * ((g - means) / np.maximum(stds, 1e-6)) ** 2) / (
                np.sqrt(2 * np.pi) * np.maximum(stds, 1e-6)
            )
            obs_prob = np.maximum(obs_prob, 1e-10)  # 防止零概率导致数值问题

            if t == 0:
                alpha = obs_prob * alpha  # 初始步：观测概率 × 初始分布
            else:
                alpha = obs_prob * (alpha @ T)  # 递推：观测概率 × (前一步分布 × 转移矩阵)
            alpha = alpha / max(np.sum(alpha), 1e-10)  # 归一化
            probs[t] = alpha

        return probs

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行马尔可夫体制转换预测

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达标
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "markov_switching"}, threshold)

        # 数据不足
        if len(history) < 6 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "markov_switching", "notes": "insufficient_data"},
                threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 6:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "markov_switching_fallback"},
                threshold,
            )

        try:
            return self._predict_impl(views_sorted, current_views, velocity, remaining, threshold, video_data)
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.0,
                current_views,
                velocity,
                {"error": str(e)},
                threshold,
            )

    def _extract_views(self, history):
        """从历史记录中提取并排序播放量序列

        参数:
            history: 历史数据列表

        返回:
            np.ndarray 或 None: 按时间排序的播放量数组
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 6:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_arr, current_views, velocity, remaining, threshold, video_data):
        """执行马尔可夫体制转换核心预测

        完整的预测流程：
        1. 计算增长率序列
        2. 前向算法估计各时间点的体制概率
        3. 每个体制独立估计增长参数
        4. 蒙特卡洛模拟多条未来路径（含体制随机转换）
        5. 聚合模拟结果，取中位数达标天数

        参数:
            views_arr: 排序后的播放量数组
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值
            video_data: 视频数据字典

        返回:
            PredictionResult: 预测结果对象
        """
        n = len(views_arr)

        # 获取视频质量得分和互动率（用于置信度计算）
        quality = self.get_quality_score(video_data)
        self.get_engagement_rate(video_data)

        # ── 计算增长率序列作为观测 ────────────────
        # 每期增长率 = (v_t - v_{t-1}) / v_{t-1}
        growth_rates = np.diff(views_arr) / np.maximum(views_arr[:-1], 1)
        if len(growth_rates) < 3:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "markov_switching_no_growth"},
                threshold,
            )

        # ── 前向算法估计体制概率 ──────────────────
        # regime_probs[t] = [P(体制0|观测), P(体制1|观测)]
        regime_probs = self._forward_algorithm(growth_rates)
        current_regime_probs = regime_probs[-1]  # 当前时刻的体制概率

        # ── 估计每个体制的增长参数 ────────────────
        # 硬分配每个时间点到最可能的体制（取概率最大的）
        hard_assignments = np.argmax(regime_probs, axis=1)

        regime_growth_rates = {}
        for r in range(self.n_regimes):
            mask = hard_assignments == r  # 属于体制r的时间点
            if np.sum(mask) >= 2:
                r_rates = growth_rates[mask]
                regime_growth_rates[r] = {
                    "mean": float(np.mean(r_rates)),  # 体制r的平均增长率
                    "std": float(max(np.std(r_rates), 0.001)),  # 标准差（最小0.001防止除零）
                    "count": int(np.sum(mask)),  # 属于该体制的点数
                }
            else:
                # 数据不足时的默认参数
                regime_growth_rates[r] = {
                    "mean": 0.01 * (1 + r),  # 默认增长率
                    "std": 0.01,
                    "count": 0,
                }

        # ── 未来体制模拟（蒙特卡洛） ─────────────
        # 进行多次模拟取中位数，减少随机性影响
        mc_simulations = 50
        # 预测天数范围
        forecast_days = min(365, max(14, int((threshold - current_views) / max(velocity * 24, 1)) * 2 + 10))

        all_hit_days = []
        for _ in range(mc_simulations):
            pred_v = float(current_views)
            # 从当前体制概率分布中随机采样初始体制
            current_regime = np.random.choice(self.n_regimes, p=current_regime_probs)
            hit_day = None

            for day in range(1, forecast_days + 1):
                # 体制转换检查（根据转移概率随机切换）
                if np.random.random() > self.transition[current_regime, current_regime]:
                    # 当前体制对角线值 = 留在当前体制的概率
                    # 若随机数 > 对角线值 → 转移到其他体制
                    probs = self.transition[current_regime]
                    choices = [r for r in range(self.n_regimes) if r != current_regime]
                    if choices:
                        # 归一化其他体制的转移概率
                        alt_probs = np.array([probs[c] for c in choices])
                        alt_probs = alt_probs / max(np.sum(alt_probs), 1e-10)
                        current_regime = np.random.choice(choices, p=alt_probs)

                # 根据当前体制的增长参数采样日增长量
                rg = regime_growth_rates[current_regime]
                # 正态采样 × 最新播放量 = 日增长量
                daily_growth = views_arr[-1] * np.random.normal(rg["mean"], rg["std"])
                # 衰减因子：越远期增长越慢（指数衰减，60天半衰期）
                daily_growth = max(0, daily_growth * (0.5 + 0.5 * math.exp(-day / 60.0)))
                pred_v += daily_growth

                if pred_v >= threshold:
                    hit_day = day
                    break

            if hit_day is not None:
                all_hit_days.append(hit_day)

        # ── 综合预测 ─────────────────────────────
        if all_hit_days:
            median_day = float(np.median(all_hit_days))  # 中位数达标天数
            q25_day = float(np.percentile(all_hit_days, 25))  # 25分位数
            q75_day = float(np.percentile(all_hit_days, 75))  # 75分位数

            predicted_hours = median_day * 24
            # 四分位距表示预测的不确定性
            spread = max(1, q75_day - q25_day)
            # 稳定性 = 1 - 不确定性比例
            stability = max(0.0, 1.0 - spread / max(median_day, 1) * 0.5)

            # 综合置信度 = 数据质量 + 模拟稳定性 + 体制清晰度 + 视频质量
            data_qual = min(1.0, n / 20)  # 数据量因子（20点=满分）
            quality_conf = quality * 0.15
            regime_clarity = float(np.max(current_regime_probs))  # 当前体制归属的清晰度
            conf = min(0.85, 0.3 + 0.2 * data_qual + 0.15 * stability + 0.1 * regime_clarity + quality_conf)
        else:
            # 所有模拟路径均无法在期限内达标
            predicted_hours = remaining / velocity
            conf = 0.3

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "markov_switching",
                "n_regimes": self.n_regimes,
                "current_regime_probs": [round(float(p), 3) for p in current_regime_probs],
                "regime_growth_means": [round(regime_growth_rates[r]["mean"], 4) for r in range(self.n_regimes)],
                "mc_simulations": mc_simulations,
                "mc_hit_ratio": round(len(all_hit_days) / max(mc_simulations, 1), 3),
                "median_hit_day": round(float(np.median(all_hit_days)), 1) if all_hit_days else None,
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult 预测结果对象

        参数:
            predicted_hours: 预计达到阈值的小时数
            confidence: 预测置信度 (0.0 ~ 1.0)
            current_views: 当前播放量
            velocity: 当前增长速度
            metadata: 元数据字典
            threshold: 目标阈值

        返回:
            PredictionResult: 标准预测结果对象
        """
        metadata.setdefault("method", "markov_switching")
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
