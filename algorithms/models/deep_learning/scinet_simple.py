"""
SCINet (Sample Convolution and Interaction Network)
===================================================

基于二叉树结构的样本卷积交互网络，通过逐层下采样-卷积-交互捕捉不同时间尺度的模式，
用于B站视频播放量增长预测。

核心原理:
    1. 二叉树下采样：将序列交替分离为偶数位（even）和奇数位（odd）子序列
    2. 卷积滤波：使用简化1D卷积核平滑偶数序列
    3. 差分交互：计算虚实差异，用tanh门控广播交互信息
    4. 多级递归：在多个尺度上重复上述过程，捕捉从局部到全局的模式

降级链：torch checkpoint（SCINetTorchModel） → numpy二叉树交互 → velocity兜底

参考论文：
    "SCINet: Sample Convolution and Interaction Network for Time Series Forecasting"
    (Liu et al., NeurIPS 2022)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import SCINetTorchModel, try_torch_predict


class ScinetSimpleAlgorithm(BaseAlgorithm):
    """SCINet 样本卷积交互网络

    通过二叉树下采样-卷积-交互的多尺度结构预测视频增长速度。
    两层SCI Block分别捕捉不同时间分辨率下的模式。
    """

    name = "SCINet卷积交互"
    algorithm_id = "scinet_simple"
    description = "二叉树下采样-卷积-交互，多尺度模式捕捉"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
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
            SCINetTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建SCINet PyTorch模型实例"""
        return SCINetTorchModel(in_features=getattr(self, '_training_n_features', 5), hidden=16, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行numpy版本的SCINet预测

        流程：
        1. 提取播放量序列
        2. 第一层SCI Block：奇偶分离 + 卷积滤波 + 差分交互
        3. 第二层SCI Block：在第一层结果上再次递归
        4. 融合双层趋势信号预测速度

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时降级
        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold, method="scinet")

        try:
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            # ===== SCI Block：奇偶分离 + 1D卷积 + 交互 =====
            def _sci_block(x):
                """一次SCI交互块

                1. 奇偶分离（二叉树下采样）
                2. 卷积平滑偶数序列提取低频趋势
                3. 计算偶数-奇数差异
                """
                even = x[::2]    # 偶数位采样
                odd = x[1::2]   # 奇数位采样
                if len(even) > len(odd):
                    even = even[: len(odd)]  # 对齐长度
                diff = even - odd             # 奇偶差异信号
                k = np.array([0.5, 0.5])     # 简化卷积核（移动平均）

                def conv1d(signal, kernel):
                    """简化1D卷积（same模式）"""
                    return np.convolve(signal, kernel, mode="same")[: len(signal)]

                # 卷积平滑偶数序列
                even_filt = conv1d(even, k)
                even_out = even - even_filt   # 去除低频趋势后的残差
                odd_out = odd + even_filt     # 将低频趋势广播到奇数序列
                return even_out, odd_out, diff

            def _interact(even, odd, diff):
                """差分交互：用tanh门控将diff信息广播到偶数和奇数序列"""
                # gate_e: 用diff调制even序列（tanh激活后与odd交互）
                gate_e = np.tanh(
                    diff[: len(even)] if len(diff) >= len(even) else np.pad(diff, (0, len(even) - len(diff)))
                )
                gate_o = np.tanh(diff[: len(odd)] if len(diff) >= len(odd) else np.pad(diff, (0, len(odd) - len(diff))))
                return even + gate_e * odd[: len(even)], odd + gate_o * even[: len(odd)]

            # ===== 第一层SCI Block =====
            combined = views
            even1, odd1, diff1 = _sci_block(combined)
            even1_int, odd1_int = _interact(even1, odd1, diff1)

            # ===== 第二层SCI Block（在第一层结果上递归） =====
            if len(even1_int) >= 4:
                even2, odd2, diff2 = _sci_block(even1_int[: len(even1_int) // 2 * 2])
                if len(even2) > 0 and len(odd2) > 0:
                    even2_int, odd2_int = _interact(even2, odd2, diff2)
                    scale2_trend = np.mean(np.abs(even2_int[-3:])) if len(even2_int) >= 3 else 0
                else:
                    scale2_trend = 0
            else:
                scale2_trend = 0

            # ===== 融合多尺度趋势信号 =====
            scale1_trend = np.mean(np.abs(even1_int[-3:])) if len(even1_int) >= 3 else 0
            recent_diff = np.mean(np.diff(views[-5:])) if len(views) >= 5 else velocity * 3600
            # 双层趋势 + 近期变化的加权融合
            predicted_velocity = max(0, (recent_diff + (scale1_trend + scale2_trend) * 50) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0  # 已达到阈值
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = max(0.1, min(0.8, 0.5))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "scinet", "scales": 2},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold, method="scinet")
