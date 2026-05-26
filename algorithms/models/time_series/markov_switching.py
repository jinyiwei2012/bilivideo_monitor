"""
马尔可夫体制转换 (Markov Regime Switching) 预测
假设播放量增长在不同"体制"间切换（如快速增长期 vs 平稳期）
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
    """

    name = "马尔可夫体制转换"
    algorithm_id = "markov_switching"
    description = "隐马尔可夫链描述增长体制切换，独立预测各阶段"
    category = "时间序列"
    default_weight = 1.2

    def __init__(self):
        super().__init__()
        self.n_regimes = 2
        # 转移概率矩阵 (P[i][j] = 从体制i转移到j的概率)
        self.transition = np.array([[0.85, 0.15], [0.10, 0.90]])
        # 每个体制的持久性

    def _forward_algorithm(self, emissions: np.ndarray) -> np.ndarray:
        """前向算法计算每个时间点的体制概率"""
        n = len(emissions)
        T = self.transition

        # 初始化 (均匀分布)
        alpha = np.ones(self.n_regimes) / self.n_regimes

        # 观测概率（基于增长率）
        probs = np.zeros((n, self.n_regimes))

        for t in range(n):
            # 根据增长率计算属于每个体制的概率
            g = emissions[t]
            if self.n_regimes == 2:
                # 体制1: 高增长 (均值0.1, std 0.05)
                # 体制2: 低增长 (均值0.01, std 0.02)
                means = np.array([0.08, 0.01])
                stds = np.array([0.04, 0.015])
            else:
                means = np.array([0.08, 0.02, 0.0])
                stds = np.array([0.04, 0.02, 0.01])

            # 高斯观测概率
            obs_prob = np.exp(-0.5 * ((g - means) / np.maximum(stds, 1e-6)) ** 2) / (
                np.sqrt(2 * np.pi) * np.maximum(stds, 1e-6)
            )
            obs_prob = np.maximum(obs_prob, 1e-10)

            if t == 0:
                alpha = obs_prob * alpha
            else:
                alpha = obs_prob * (alpha @ T)
            alpha = alpha / max(np.sum(alpha), 1e-10)
            probs[t] = alpha

        return probs

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "markov_switching"}, threshold)

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
        """从历史记录中提取并排序播放量序列"""
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T"," ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 6:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_arr, current_views, velocity, remaining, threshold, video_data):
        """执行马尔可夫体制转换核心预测"""
        n = len(views_arr)

        quality = self.get_quality_score(video_data)
        self.get_engagement_rate(video_data)

        # ── 计算增长率序列作为观测 ────────────────
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
        regime_probs = self._forward_algorithm(growth_rates)
        current_regime_probs = regime_probs[-1]

        # ── 估计每个体制的增长参数 ────────────────
        # 硬分配每个时间点到最可能的体制
        hard_assignments = np.argmax(regime_probs, axis=1)

        regime_growth_rates = {}
        for r in range(self.n_regimes):
            mask = hard_assignments == r
            if np.sum(mask) >= 2:
                r_rates = growth_rates[mask]
                regime_growth_rates[r] = {
                    "mean": float(np.mean(r_rates)),
                    "std": float(max(np.std(r_rates), 0.001)),
                    "count": int(np.sum(mask)),
                }
            else:
                regime_growth_rates[r] = {
                    "mean": 0.01 * (1 + r),
                    "std": 0.01,
                    "count": 0,
                }

        # ── 未来体制模拟（蒙特卡洛） ─────────────
        mc_simulations = 50
        forecast_days = min(365, max(14, int((threshold - current_views) / max(velocity * 24, 1)) * 2 + 10))

        all_hit_days = []
        for _ in range(mc_simulations):
            pred_v = float(current_views)
            current_regime = np.random.choice(self.n_regimes, p=current_regime_probs)
            hit_day = None

            for day in range(1, forecast_days + 1):
                # 体制转换
                if np.random.random() > self.transition[current_regime, current_regime]:
                    probs = self.transition[current_regime]
                    choices = [r for r in range(self.n_regimes) if r != current_regime]
                    if choices:
                        alt_probs = np.array([probs[c] for c in choices])
                        alt_probs = alt_probs / max(np.sum(alt_probs), 1e-10)
                        current_regime = np.random.choice(choices, p=alt_probs)

                rg = regime_growth_rates[current_regime]
                daily_growth = views_arr[-1] * np.random.normal(rg["mean"], rg["std"])
                daily_growth = max(0, daily_growth * (0.5 + 0.5 * math.exp(-day / 60.0)))
                pred_v += daily_growth

                if pred_v >= threshold:
                    hit_day = day
                    break

            if hit_day is not None:
                all_hit_days.append(hit_day)

        # ── 综合预测 ─────────────────────────────
        if all_hit_days:
            median_day = float(np.median(all_hit_days))
            q25_day = float(np.percentile(all_hit_days, 25))
            q75_day = float(np.percentile(all_hit_days, 75))

            predicted_hours = median_day * 24
            spread = max(1, q75_day - q25_day)
            stability = max(0.0, 1.0 - spread / max(median_day, 1) * 0.5)

            data_qual = min(1.0, n / 20)
            quality_conf = quality * 0.15
            regime_clarity = float(np.max(current_regime_probs))
            conf = min(0.85, 0.3 + 0.2 * data_qual + 0.15 * stability + 0.1 * regime_clarity + quality_conf)
        else:
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
        """构造 PredictionResult"""
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
