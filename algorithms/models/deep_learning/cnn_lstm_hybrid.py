"""
CNN-LSTM混合预测模型 (Convolutional Neural Network + Long Short-Term Memory)
先使用CNN提取局部时序模式，再通过LSTM捕获长期依赖。

核心思路（两步走）：
1. CNN 阶段：多尺度卷积核（3和5）提取局部模式
   - 边缘检测核：捕捉拐点/突变（如突发推荐、限流）
   - 平滑核：捕捉缓慢趋势
2. LSTM 阶段：在 CNN 特征之上建模长期依赖
   - 标准化差分序列输入
   - 简化 LSTM 前向传播

混合优势：
- CNN 负责"看局部"：识别日周期、突发增长模式
- LSTM 负责"看全局"：捕获长期衰减趋势
- 两者互补，适合 B 站视频既有日常波动又有长期趋势的数据特点
"""

import math
import numpy as np
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import CNNLSTMTorchModel, try_torch_predict


class CNNLSTMHybridAlgorithm(BaseAlgorithm):
    """CNN-LSTM 混合预测模型算法

    结合卷积神经网络和循环神经网络的优点：
    - CNN 层: 提取局部时序模式（如日周期、突发增长模式）
    - LSTM 层: 捕获长期依赖关系

    两步走策略使模型能同时感知局部和全局时序特征，
    适合 B 站视频既有日常波动又有长期趋势的数据特点。

    降级链：torch checkpoint → numpy CNN+LSTM → velocity 兜底
    """

    name = "CNN-LSTM混合"
    algorithm_id = "cnn_lstm_hybrid"
    description = "CNN提取局部模式 + LSTM捕获长期依赖的混合模型"
    category = "深度学习"
    default_weight = 1.3

    def __init__(self):
        """初始化 CNN-LSTM 混合模型。

        设置多尺度 CNN 卷积核大小 [3, 5] 和 LSTM 单元数 16。
        """
        super().__init__()
        self.cnn_kernel_sizes = [3, 5]  # 不同尺度的卷积核（3=短周期、5=长周期）
        self.lstm_units = 16  # LSTM 处理窗口长度

    def _conv1d(self, seq: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """一维卷积操作（numpy 实现）。

        对序列做滑动点积，模拟 Conv1d 的 forward pass。

        Args:
            seq: 一维输入序列 [L]
            kernel: 卷积核 [K]

        Returns:
            卷积输出序列 [L-K+1]
        """
        k = len(kernel)
        if len(seq) < k:
            return np.array([np.mean(seq * kernel[: len(seq)])])
        out = np.zeros(len(seq) - k + 1)
        for i in range(len(out)):
            out[i] = np.dot(seq[i : i + k], kernel)  # 滑动窗口点积
        return out

    def _multi_scale_conv(self, seq: np.ndarray) -> np.ndarray:
        """多尺度卷积特征提取。

        对每个卷积核大小分别提取两组特征：
        - 边缘检测特征：max, min, mean, std（捕捉突变）
        - 平滑特征：mean, last_val（捕捉趋势）

        Args:
            seq: 输入一维序列

        Returns:
            拼接后的多尺度特征向量
        """
        features = []
        for k_size in self.cnn_kernel_sizes:
            if len(seq) >= k_size:
                # 边缘检测卷积核（拉普拉斯式）
                edge_kernel = np.array([-1, 0, 1]) if k_size == 3 else np.array([-1, -1, 0, 1, 1]) / 2
                if len(edge_kernel) != k_size:
                    edge_kernel = np.ones(k_size) / k_size  # 回退到均值核
                conv_out = self._conv1d(seq, edge_kernel)
                if len(conv_out) > 0:
                    # 四个统计量描述卷积输出的分布
                    features.extend([np.max(conv_out), np.min(conv_out), np.mean(conv_out), np.std(conv_out)])

                # 平滑卷积核（移动平均）
                smooth_kernel = np.ones(k_size) / k_size
                smooth_out = self._conv1d(seq, smooth_kernel)
                if len(smooth_out) > 0:
                    features.extend([np.mean(smooth_out), smooth_out[-1] if len(smooth_out) > 0 else 0])

        return np.array(features)

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典，含 view_count, history_data, bvid 等字段
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            CNNLSTMTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            CNNLSTMTorchModel 实例
        """
        return CNNLSTMTorchModel(in_features=getattr(self, '_training_n_features', 5), horizon=self.training_horizon)

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - CNN-LSTM 核心实现。

        流程：
        1. 数据预处理 → 2. CNN 多尺度特征提取 → 3. LSTM 时序建模 →
        4. 混合预测 → 5. 逐日外推

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果
        """
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
        """从历史记录中提取并按时间戳排序播放量序列。

        Args:
            history: 历史数据列表

        Returns:
            排序后的播放量数组，数据不足时返回 None
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
        if len(views_vals) < 5:
            return None
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """执行 CNN-LSTM 核心预测逻辑。

        1. 对数变换稳定方差 → 2. CNN 多尺度特征提取 →
        3. 简化 LSTM 前向传播 → 4. 混合因子综合 → 5. 逐日外推。

        Args:
            views_sorted: 排序后的播放量数组
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值
            video_data: 视频数据字典

        Returns:
            PredictionResult 预测结果
        """
        n = len(views_sorted)

        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # ── 对数变换稳定方差 ──────────────────────
        log_views = np.log(np.maximum(views_sorted, 1))
        log_diff = np.diff(log_views)  # 对数差分 ≈ 增长率
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
        cnn_trend = np.mean(cnn_features) if len(cnn_features) > 0 else 0  # CNN 聚合趋势
        np.std(cnn_features) if len(cnn_features) > 1 else 0.5  # CNN 波动（记录但不直接使用）

        # ── LSTM阶段: 时序依赖建模 ──────────────
        # 标准化差分序列
        diff_mean = np.mean(log_diff)
        diff_std = max(np.std(log_diff), 1e-8)
        norm_diff = (log_diff - diff_mean) / diff_std

        # 简化 LSTM 前向传播（单层、有限步）
        h_state = 0.0
        w_h = 0.3  # 隐藏状态的权重
        w_x = 0.5  # 输入的权重
        for x in norm_diff[-self.lstm_units :]:  # 只处理最近 lstm_units 步
            h_state = math.tanh(w_h * h_state + w_x * x)
        lstm_signal = h_state  # 最终 LSTM 信号

        # ── 混合预测 ─────────────────────────────
        # CNN贡献（局部模式）：趋势放大/缩小因子
        cnn_growth_factor = 1.0 + cnn_trend * 0.5

        # LSTM贡献（长期依赖）：加速/减速因子
        lstm_accel = lstm_signal * 0.3

        # 综合预测因子
        combined_factor = cnn_growth_factor + lstm_accel

        mean_daily_growth = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
        adjusted_growth = mean_daily_growth * max(0.3, combined_factor)
        forecast_days = min(365, max(10, int((threshold - current_views) / max(adjusted_growth, 1)) + 5))

        pred_views = float(current_views)
        target_day = None

        for day in range(1, forecast_days + 1):
            # CNN派生的衰减模式（指数衰减，衰减速度受互动率影响）
            decay = math.exp(-day / (21.0 + 14.0 * engagement))
            # LSTM派生的加速模式（初始加速，逐渐衰减）
            accel = 1.0 + lstm_accel * math.exp(-day / 30.0)

            # 综合日增长 = 基础增长 × 加速因子 × (1 + 残差衰减项)
            daily_growth = adjusted_growth * accel * (1.0 + (1.0 - decay) * 0.2)
            pred_views += max(0, daily_growth)

            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度 = 数据量 + CNN 趋势强度 + 质量评分 + 互动率
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
        """构造 PredictionResult 预测结果对象。

        Args:
            predicted_hours: 预测的小时数
            confidence: 置信度 [0, 1]
            current_views: 当前播放量
            velocity: 当前速度（每小时播放量）
            metadata: 元数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
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
