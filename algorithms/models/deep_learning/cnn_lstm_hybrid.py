"""
CNN-LSTM混合预测模型
先使用CNN提取局部时序模式，再通过LSTM捕获长期依赖
"""

import math
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class CNNLSTMHybridAlgorithm(BaseAlgorithm):
    """CNN-LSTM 混合预测模型

    结合卷积神经网络和循环神经网络的优点：
    - CNN 层: 提取局部时序模式（如日周期、突发增长模式）
    - LSTM 层: 捕获长期依赖关系

    两步走策略使模型能同时感知局部和全局时序特征，
    适合 B 站视频既有日常波动又有长期趋势的数据特点。
    """

    name = "CNN-LSTM混合"
    algorithm_id = "cnn_lstm_hybrid"
    description = "CNN提取局部模式 + LSTM捕获长期依赖的混合模型"
    category = "深度学习"
    default_weight = 1.3

    def __init__(self):
        super().__init__()
        self.cnn_kernel_sizes = [3, 5]  # 不同尺度的卷积核
        self.lstm_units = 16

    def _conv1d(self, seq: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """一维卷积操作"""
        k = len(kernel)
        if len(seq) < k:
            return np.array([np.mean(seq * kernel[: len(seq)])])
        out = np.zeros(len(seq) - k + 1)
        for i in range(len(out)):
            out[i] = np.dot(seq[i : i + k], kernel)
        return out

    def _multi_scale_conv(self, seq: np.ndarray) -> np.ndarray:
        """多尺度卷积特征提取"""
        features = []
        for k_size in self.cnn_kernel_sizes:
            if len(seq) >= k_size:
                # 边缘检测卷积核
                edge_kernel = np.array([-1, 0, 1]) if k_size == 3 else np.array([-1, -1, 0, 1, 1]) / 2
                if len(edge_kernel) != k_size:
                    edge_kernel = np.ones(k_size) / k_size
                conv_out = self._conv1d(seq, edge_kernel)
                if len(conv_out) > 0:
                    features.extend([np.max(conv_out), np.min(conv_out), np.mean(conv_out), np.std(conv_out)])

                # 平滑卷积核
                smooth_kernel = np.ones(k_size) / k_size
                smooth_out = self._conv1d(seq, smooth_kernel)
                if len(smooth_out) > 0:
                    features.extend([np.mean(smooth_out), smooth_out[-1] if len(smooth_out) > 0 else 0])

        return np.array(features)

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测"""
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "cnn_lstm"}, threshold)

        if len(history) < 5 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "cnn_lstm", "notes": "insufficient_data"},
                threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 5:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "cnn_lstm_fallback"},
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
                    ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 5:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """执行CNN-LSTM核心预测"""
        n = len(views_sorted)

        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # ── 对数变换稳定方差 ──────────────────────
        log_views = np.log(np.maximum(views_sorted, 1))
        log_diff = np.diff(log_views)
        if len(log_diff) == 0:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "cnn_lstm_no_diff"},
                threshold,
            )

        # ── CNN阶段: 多尺度特征提取 ──────────────
        cnn_features = self._multi_scale_conv(log_diff)
        if len(cnn_features) == 0:
            cnn_features = np.array([np.mean(log_diff), np.std(log_diff), log_diff[-1]])

        # 从CNN特征中提取关键信号
        cnn_trend = np.mean(cnn_features) if len(cnn_features) > 0 else 0
        np.std(cnn_features) if len(cnn_features) > 1 else 0.5

        # ── LSTM阶段: 时序依赖建模 ──────────────
        # 标准化差分序列
        diff_mean = np.mean(log_diff)
        diff_std = max(np.std(log_diff), 1e-8)
        norm_diff = (log_diff - diff_mean) / diff_std

        # 简化LSTM前向
        h_state = 0.0
        w_h = 0.3
        w_x = 0.5
        for x in norm_diff[-self.lstm_units :]:
            h_state = math.tanh(w_h * h_state + w_x * x)
        lstm_signal = h_state

        # ── 混合预测 ─────────────────────────────
        # CNN贡献（局部模式）
        cnn_growth_factor = 1.0 + cnn_trend * 0.5

        # LSTM贡献（长期依赖）
        lstm_accel = lstm_signal * 0.3

        # 综合预测因子
        combined_factor = cnn_growth_factor + lstm_accel

        mean_daily_growth = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
        adjusted_growth = mean_daily_growth * max(0.3, combined_factor)
        forecast_days = min(365, max(10, int((threshold - current_views) / max(adjusted_growth, 1)) + 5))

        pred_views = float(current_views)
        target_day = None

        for day in range(1, forecast_days + 1):
            # CNN派生的衰减模式
            decay = math.exp(-day / (21.0 + 14.0 * engagement))
            # LSTM派生的加速模式（初始加速，逐渐衰减）
            accel = 1.0 + lstm_accel * math.exp(-day / 30.0)

            daily_growth = adjusted_growth * accel * (1.0 + (1.0 - decay) * 0.2)
            pred_views += max(0, daily_growth)

            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            conf = min(
                0.9,
                0.3 + 0.2 * min(1.0, n / 20) + 0.2 * min(1.0, abs(cnn_trend) * 5) + 0.15 * quality + 0.05 * engagement,
            )
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "cnn_lstm",
                "cnn_features": len(cnn_features),
                "cnn_trend": round(float(cnn_trend), 4),
                "lstm_signal": round(float(lstm_signal), 4),
                "combined_factor": round(float(combined_factor), 4),
                "forecast_horizon": forecast_days,
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult"""
        metadata.setdefault("method", "cnn_lstm")
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
