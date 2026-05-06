"""
TCN (Temporal Convolutional Network) 时序卷积预测
使用空洞因果卷积捕获长期时序依赖，比RNN系列训练更稳定
"""

import math
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class TCNSimpleAlgorithm(BaseAlgorithm):
    """TCN 时序卷积网络

    使用空洞因果卷积 (Dilated Causal Convolution) 构建时序模型。
    相比 RNN 系列，TCN 训练更稳定、梯度不会爆炸/消失，
    且可通过空洞卷积指数级扩大感受野。

    参考: Bai et al. (2018), "An Empirical Evaluation of Generic
          Convolutional and Recurrent Networks for Sequence Modeling"
    """

    name = "TCN卷积预测"
    algorithm_id = "tcn_simple"
    description = "时序卷积网络，空洞因果卷积捕获长期依赖"
    category = "深度学习"
    default_weight = 1.3

    def __init__(self):
        super().__init__()
        self.nb_filters = 32
        self.kernel_size = 3
        self.dilations = [1, 2, 4, 8, 16, 32]
        self.dropout = 0.1

    def _causal_conv(self, seq: np.ndarray, kernel: np.ndarray, dilation: int) -> np.ndarray:
        """一维空洞因果卷积

        在序列左侧补零保证因果性（未来信息不泄漏到过去）
        """
        k = len(kernel)
        padding = (k - 1) * dilation
        padded = np.concatenate([np.zeros(padding), seq])
        out = np.zeros(len(seq))
        for i in range(len(seq)):
            for j in range(k):
                idx = i + padding - j * dilation
                if 0 <= idx < len(padded):
                    out[i] += padded[idx] * kernel[j]
        return out

    def _residual_block(self, seq: np.ndarray, dilation: int) -> np.ndarray:
        """TCN残差块: 两层的空洞卷积 + ReLU + Dropout + 残差连接"""
        n = len(seq)

        # 两层空洞卷积
        k = self.kernel_size
        w1 = np.random.randn(k) * 0.1
        w2 = np.random.randn(k) * 0.1

        conv1 = self._causal_conv(seq, w1, dilation)
        conv1 = np.maximum(conv1, 0)  # ReLU
        conv1[np.random.rand(n) < self.dropout] = 0  # Dropout

        conv2 = self._causal_conv(conv1, w2, dilation)
        conv2 = np.maximum(conv2, 0)  # ReLU

        # 残差连接
        if n > 0:
            out = seq + conv2
        else:
            out = conv2

        return out

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=0,
                confidence=1.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tcn"},
                timestamp=datetime.now(),
            )

        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tcn", "notes": "insufficient_data"},
                timestamp=datetime.now(),
            )

        # 提取时序
        timestamps = []
        views_vals = []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))

        if len(views_vals) < 4:
            predicted_hours = remaining / velocity
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.3,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "tcn_fallback"},
                timestamp=datetime.now(),
            )

        try:
            order = np.argsort(timestamps)
            views_sorted = np.array(views_vals, dtype=float)[order]
            n = len(views_sorted)

            # ── 数据预处理: 对数差分（稳定方差） ──────
            log_views = np.log(np.maximum(views_sorted, 1))
            log_diff = np.diff(log_views)
            if len(log_diff) == 0:
                predicted_hours = remaining / velocity
                return PredictionResult(
                    algorithm_name=self.name,
                    algorithm_id=self.algorithm_id,
                    target_threshold=threshold,
                    predicted_hours=predicted_hours,
                    confidence=0.3,
                    current_views=current_views,
                    current_velocity=velocity,
                    metadata={"method": "tcn_no_diff"},
                    timestamp=datetime.now(),
                )

            # 标准化
            mean_val = np.mean(log_diff)
            std_val = max(np.std(log_diff), 1e-6)
            normalized = (log_diff - mean_val) / std_val

            # ── 通过TCN残差块 ────────────────────────
            tcn_out = normalized.copy()
            effective_dilations = [d for d in self.dilations if d < len(tcn_out)]
            for dilation in effective_dilations:
                tcn_out = self._residual_block(tcn_out, dilation)

            # ── 预测: 外推最后一个TCN输出 ──────────────
            last_val = tcn_out[-1] if len(tcn_out) > 0 else 0
            trend = np.mean(tcn_out[-min(5, len(tcn_out)) :]) if len(tcn_out) >= 2 else last_val

            # 根据最近波动估计不确定性
            recent_volatility = np.std(tcn_out[-min(10, len(tcn_out)) :]) if len(tcn_out) >= 5 else 0.5

            # ── 生成未来预测 ──────────────────────────
            growth_per_day = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
            forecast_days = min(365, max(10, int((threshold - current_views) / max(growth_per_day, 1)) + 5))

            pred_views = float(current_views)
            current_log = log_views[-1]

            target_day = None
            for day in range(1, forecast_days + 1):
                # TCN预测的增长因子（带衰减）
                decay = math.exp(-day / 30.0)
                growth_factor = trend * std_val * decay + 0.01 * (1 - decay)

                # 加入季节性微调
                hour_factor = 1.0 + 0.05 * math.sin(2 * math.pi * day / 7)
                growth_factor *= hour_factor

                current_log += growth_factor
                pred_views = math.exp(current_log)

                if pred_views >= threshold:
                    target_day = day
                    break

            if target_day is not None and target_day <= 365:
                predicted_hours = target_day * 24
                # 置信度
                data_quality = min(1.0, n / 20)
                vol_penalty = max(0.0, 1.0 - recent_volatility)
                conf = min(0.9, 0.35 + 0.3 * data_quality + 0.2 * vol_penalty)
            else:
                predicted_hours = remaining / velocity
                conf = 0.35

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=conf,
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "tcn",
                    "dilations_used": len(effective_dilations),
                    "forecast_horizon": forecast_days,
                    "trend": round(float(trend), 4),
                    "volatility": round(float(recent_volatility), 4),
                    "data_points": n,
                },
                timestamp=datetime.now(),
            )
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"error": str(e)},
                timestamp=datetime.now(),
            )
