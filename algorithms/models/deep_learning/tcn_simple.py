"""
TCN (Temporal Convolutional Network) — 时序卷积网络
====================================================

使用空洞因果卷积（Dilated Causal Convolution）构建的时序预测模型，
用于预测B站视频播放量增长趋势。相比RNN系列，TCN训练更稳定、梯度不会爆炸/消失。

核心原理:
    1. 因果卷积：使用单侧padding确保未来信息不泄露到过去
    2. 空洞卷积：通过膨胀因子指数级扩大感受野，高效捕捉长程依赖
    3. 残差连接：每层输出 = 输入 + 卷积输出，缓解深层网络的梯度消失
    4. 对数差分：先对播放量做log变换再差分，稳定序列方差

降级链：torch checkpoint（TCNTorchModel） → numpy空洞因果卷积残差网络

参考论文：
    "An Empirical Evaluation of Generic Convolutional and Recurrent Networks
     for Sequence Modeling" (Bai et al., 2018)
"""

import math
import numpy as np
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import TCNTorchModel, try_torch_predict


class TCNSimpleAlgorithm(BaseAlgorithm):
    """TCN 时序卷积网络

    使用空洞因果卷积（Dilated Causal Convolution）构建时序模型。
    相比RNN系列，TCN训练更稳定、梯度不会爆炸/消失，
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
        """初始化TCN参数

        设置卷积滤波器数量、卷积核大小和空洞因子序列。
        空洞因子 [1, 2, 4, 8, 16, 32] 使感受野指数增长。
        """
        super().__init__()
        self.nb_filters = 32          # 卷积滤波器数量
        self.kernel_size = 3          # 卷积核大小
        self.dilations = [1, 2, 4, 8, 16, 32]  # 空洞因子列表（指数增长）
        self.dropout = 0.1            # Dropout比率

    def _causal_conv(self, seq: np.ndarray, kernel: np.ndarray, dilation: int) -> np.ndarray:
        """一维空洞因果卷积

        在序列左侧补零保证因果性（未来信息不泄漏到过去）。
        用dilation控制采样间隔，实现指数级感受野扩张。

        Args:
            seq: 输入序列
            kernel: 卷积核
            dilation: 空洞因子（采样间隔）

        Returns:
            np.ndarray: 卷积输出（与输入同长度）
        """
        k = len(kernel)
        padding = (k - 1) * dilation                            # 左侧零填充量
        padded = np.concatenate([np.zeros(padding), seq])       # 在左侧补零
        out = np.zeros(len(seq))
        for i in range(len(seq)):
            for j in range(k):
                idx = i + padding - j * dilation                # 空洞采样的索引
                if 0 <= idx < len(padded):
                    out[i] += padded[idx] * kernel[j]
        return out

    def _residual_block(self, seq: np.ndarray, dilation: int) -> np.ndarray:
        """TCN残差块: 两层空洞卷积 + ReLU + Dropout + 残差连接

        架构：Input → Conv1(ReLU+Dropout) → Conv2(ReLU) → +Input → Output

        Args:
            seq: 输入序列
            dilation: 当前层的空洞因子

        Returns:
            np.ndarray: 残差块输出
        """
        n = len(seq)

        # 两层空洞卷积（用确定性种子初始化卷积核以确保可复现）
        k = self.kernel_size
        rng = np.random.RandomState(42)  # 固定种子，确保确定性
        w1 = rng.randn(k) * 0.1  # 第一层卷积核
        w2 = rng.randn(k) * 0.1  # 第二层卷积核

        conv1 = self._causal_conv(seq, w1, dilation)
        conv1 = np.maximum(conv1, 0)                   # ReLU激活：负值归零
        conv1[rng.rand(n) < self.dropout] = 0    # Dropout正则化（确定性 RNG）

        conv2 = self._causal_conv(conv1, w2, dilation)
        conv2 = np.maximum(conv2, 0)                   # ReLU激活

        # 残差连接：F(x) + x
        if n > 0:
            out = seq + conv2
        else:
            out = conv2

        return out

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data, threshold=100000):
        """执行预测

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            TCNTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建TCN PyTorch模型实例"""
        return TCNTorchModel(in_features=getattr(self, '_training_n_features', 5), horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """执行numpy版本的TCN预测

        核心流程：
        1. 提取播放量序列并按时间排序
        2. 对播放量做log变换 + 差分（稳定方差）
        3. 通过多个空洞因果卷积残差块
        4. 基于TCN输出外推未来播放量增长

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "tcn"}, threshold)

        # 数据不足时回退
        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "tcn", "notes": "insufficient_data"},
                threshold,
            )

        # 提取并排序播放量序列
        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 4:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "tcn_fallback"},
                threshold,
            )

        try:
            return self._predict_impl(views_sorted, current_views, velocity, remaining, threshold)
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

        处理多种时间戳格式（数值、datetime对象、ISO字符串），按时间升序排列。

        Args:
            history: 历史数据记录列表

        Returns:
            np.ndarray: 按时间排序的播放量数组，或None（数据不足）
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            # 统一时间戳格式
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 4:
            return None
        order = np.argsort(timestamps)  # 时间升序索引
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold):
        """执行TCN核心预测

        详细步骤：
        1. 对数差分预处理（稳定方差）
        2. z-score标准化
        3. 通过空洞因果卷积残差块序列
        4. 基于TCN输出逐日外推播放量
        5. 加入衰减因子和季节性微调

        Args:
            views_sorted: 排序后的播放量序列
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 距离阈值的剩余量
            threshold: 目标阈值

        Returns:
            PredictionResult: 预测结果
        """
        n = len(views_sorted)

        # ── 数据预处理: 对数差分（稳定方差） ──────
        log_views = np.log(np.maximum(views_sorted, 1))       # log变换（避免log(0)）
        log_diff = np.diff(log_views)                          # 一阶差分（增长率）
        if len(log_diff) == 0:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "tcn_no_diff"},
                threshold,
            )

        # z-score标准化
        mean_val = np.mean(log_diff)
        std_val = max(np.std(log_diff), 1e-6)                  # 防止除零
        normalized = (log_diff - mean_val) / std_val

        # ── 通过TCN残差块 ────────────────────────
        tcn_out = normalized.copy()
        # 只使用序列长度能容纳的空洞因子
        effective_dilations = [d for d in self.dilations if d < len(tcn_out)]
        for dilation in effective_dilations:
            tcn_out = self._residual_block(tcn_out, dilation)

        # ── 预测: 外推最后一个TCN输出 ──────────────
        last_val = tcn_out[-1] if len(tcn_out) > 0 else 0
        trend = np.mean(tcn_out[-min(5, len(tcn_out)) :]) if len(tcn_out) >= 2 else last_val

        # 根据最近波动估计不确定性（波动越大预测越难）
        recent_volatility = np.std(tcn_out[-min(10, len(tcn_out)) :]) if len(tcn_out) >= 5 else 0.5

        # ── 生成未来预测 ──────────────────────────
        growth_per_day = np.mean(np.diff(views_sorted)) if n > 1 else velocity * 24
        forecast_days = min(365, max(10, int((threshold - current_views) / max(growth_per_day, 1)) + 5))

        pred_views = float(current_views)
        current_log = log_views[-1]

        target_day = None
        for day in range(1, forecast_days + 1):
            # TCN预测的增长因子（带指数衰减，模拟增长逐渐趋缓）
            decay = math.exp(-day / 30.0)                        # 30天半衰期
            growth_factor = trend * std_val * decay + 0.01 * (1 - decay)  # 加权插值到零增长

            # 加入季节性微调（7天周期）
            hour_factor = 1.0 + 0.05 * math.sin(2 * math.pi * day / 7)
            growth_factor *= hour_factor

            current_log += growth_factor
            pred_views = math.exp(current_log)

            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度：数据质量 + 波动惩罚
            data_quality = min(1.0, n / 20)
            vol_penalty = max(0.0, 1.0 - recent_volatility)
            conf = min(0.9, 0.35 + 0.3 * data_quality + 0.2 * vol_penalty)
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "tcn",
                "dilations_used": len(effective_dilations),
                "forecast_horizon": forecast_days,
                "trend": round(float(trend), 4),
                "volatility": round(float(recent_volatility), 4),
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult

        Args:
            predicted_hours: 预测小时数
            confidence: 置信度 [0, 1]
            current_views: 当前播放量
            velocity: 当前速度
            metadata: 元数据字典
            threshold: 目标阈值

        Returns:
            PredictionResult: 标准化预测结果
        """
        metadata.setdefault("method", "tcn")
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
