"""
频域分解预测算法 (Fourier/Wavelet Decomposition)
==============================================

将视频播放量时间序列转换到频域，使用傅里叶变换 (FFT) 进行频域分析。
通过保留前几个主要的谐波分量，滤除高频噪声，再用逆变换重建去噪后的序列。
同时结合线性趋势进行外推预测。

核心原理：
    1. 趋势分离 - 用一次多项式拟合线性趋势，从原始序列中减去趋势得到残差
    2. FFT 分解 - 对残差序列做实数 FFT（rfft），得到频域表示
    3. 频域滤波 - 仅保留前 1/4 的谐波分量（保留主要周期模式，滤除噪声）
    4. 逆变换重建 - 对滤波后的频域信号做逆 FFT（irfft），重建去噪后的序列
    5. 周期速度 - 从重建序列的最近窗口计算周期成分的速度
    6. 趋势速度 - 从一次多项式拟合的斜率计算趋势速度
    7. 综合速度 = 趋势速度 + 周期速度

适用场景：
    - 数据量 >= 6 个历史点
    - 需要捕捉播放量的周期性波动模式
    - 数据不足时回退为简单速度外推
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class FourierWaveletAlgorithm(BaseAlgorithm):
    """
    频域分解预测算法

    主要功能：
        - 使用 FFT 将播放量序列分解到频域
        - 保留主要谐波分量，滤除高频噪声
        - 结合趋势速度和周期速度进行综合预测

    算法步骤：
        1. 去趋势：从原始序列减去线性趋势，得到平稳残差序列
        2. FFT 分解：对残差做实数 FFT，仅保留前 1/4 谐波
        3. 逆变换：重建去噪后的周期成分
        4. 综合速度 = 趋势速度（线性拟合斜率）+ 周期波动速度
    """

    name = "频域分解"
    algorithm_id = "fourier_wavelet"
    description = "傅里叶/小波频域分解，捕捉周期模式"
    category = "高级分析"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行频域分解预测

        算法流程：
            1. 提取历史播放量序列
            2. 去趋势：views - polyval(polyfit(views, 1))
            3. 对残差做实数 FFT（rfft）
            4. 仅保留前 n//4 个谐波分量，其余置零
            5. 逆 FFT 重建去噪后的周期信号
            6. 从重建序列计算周期速度（最近窗口的差分均值）
            7. 从线性趋势计算趋势速度（斜率 / 3600）
            8. 综合速度 = 趋势速度 + 周期速度

        Args:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为零时使用回退策略
        if len(history) < 6 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            # 提取播放量序列
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)

            # 去趋势：减去线性趋势，得到平稳残差序列（均值为 0）
            detrended = views - np.polyval(np.polyfit(np.arange(len(views)), views, 1), np.arange(len(views)))

            # 实数 FFT（仅取正频率部分，因为信号是实的）
            fft = np.fft.rfft(detrended)
            n_harmonics = max(1, len(fft) // 4)  # 保留前 1/4 谐波分量
            # 频域滤波：仅保留低频谐波，其余置零
            fft_filtered = np.zeros_like(fft, dtype=complex)
            fft_filtered[:n_harmonics] = fft[:n_harmonics]

            # 逆 FFT 重建去噪后的周期成分
            reconstructed = np.fft.irfft(fft_filtered, n=len(detrended))

            # 从重建序列的最近窗口计算周期波动速度
            window = min(3, len(reconstructed))
            if window < 1:
                window = 1
            wave_diff = np.diff(reconstructed[-window:])  # 最近窗口的差分
            wave_velocity = np.mean(wave_diff) / 3600 if len(wave_diff) > 0 else 0  # 转换为小时速度

            # 从线性趋势计算趋势速度
            trend_coeffs = np.polyfit(np.arange(len(views)), views, 1)  # 一次多项式系数
            trend_velocity = trend_coeffs[0] / 3600  # 斜率转换为小时速度

            # 综合速度 = 趋势速度 + 周期波动速度
            predicted_velocity = max(0, trend_velocity + wave_velocity)
            if predicted_velocity < 1:
                predicted_velocity = velocity  # 速度过低时退化为当前速度

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 周期性强度：重建序列最近 14 点的标准差 vs 残差标准差
                # 周期性越强，预测越不确定（因为波动大）
                periodicity = (
                    np.std(reconstructed[-14:]) / max(np.std(detrended), 1)
                    if len(reconstructed) >= 14
                    else 0.5
                )
                confidence = max(0.1, min(0.8, 0.5 - periodicity * 0.3))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "fourier_wavelet", "harmonics": n_harmonics},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """
        回退预测：当数据不足或计算异常时使用简单速度外推

        Args:
            velocity (float)    : 当前播放增长速度
            current_views (int) : 当前总播放量
            threshold (int)     : 目标播放量阈值

        Returns:
            PredictionResult: 使用简单速度外推的预测结果
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "fourier_wavelet", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "fourier_wavelet", "reason": "fallback"},
            timestamp=datetime.now(),
        )
