"""
频谱残差预测算法 (Spectral Residual)

【算法类别】频域分析 / 异常检测

【核心思想】
基于频谱残差（Spectral Residual）理论：自然图像的频域幅度谱服从 1/f 规律，
减去均值滤波后的"背景谱"得到的残差对应显著/异常区域。

处理流程：
  1. 去趋势：用一阶多项式拟合去除线性趋势
  2. FFT：将去趋势序列变换到频域
  3. 对数幅度谱：log|FFT|，扩大微弱信号的区分度
  4. 均值滤波（背景谱）：用滑动平均估计正常的频谱背景
  5. 频谱残差 = log 谱 - 背景谱：提取偏离正常模式的频率分量
  6. iFFT 重建 → 显著图：残差越大的位置越可能是异常/突发事件
  7. 分离趋势分量与突发分量：显著区域用非显著区域插值替代
  8. 趋势外推：基于过滤后的趋势分量预测增长速度

【适用场景】
- 需要区分"正常趋势增长"与"突发脉冲事件"时
- 播放量数据存在明显阶段性突变（如被推荐、上热搜）
- 历史数据量 ≥10 点

【参数说明】
- 去趋势：一阶多项式，消除整体升降趋势对频域分析的干扰
- 均值滤波核大小：min(5, n//2)，自适应数据长度
- 显著阈值：1.5 × 标准差 + 均值，平衡灵敏度和误检率
- 置信度：基于突发比例（突发越少置信越高），范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，执行频谱残差分析与预测
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class SpectralResidualAlgorithm(BaseAlgorithm):
    """
    频谱残差预测算法

    利用 FFT（快速傅里叶变换）将播放量时序变换到频域，通过对数幅度谱减去均值
    滤波背景谱计算频谱残差，再经 iFFT 重建显著图来区分正常趋势和突发脉冲事件。
    过滤掉突发分量后，基于纯净的趋势分量进行外推预测。

    类属性：
        name: 算法显示名称 "频谱残差"
        algorithm_id: 算法唯一标识符 "spectral_residual"
        description: FFT对数幅度谱残差检测，区分趋势与突发信号
        category: 算法分类 "频域分析"
        default_weight: 集成学习默认权重 1.1
    """

    name = "频谱残差"
    algorithm_id = "spectral_residual"
    description = "FFT对数幅度谱残差检测，区分趋势与突发信号"
    category = "频域分析"
    default_weight = 1.1

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行频谱残差预测

        参数：
            video_data (Dict): 视频数据字典，必须包含:
                - view_count (int): 当前播放量
                - history_data (list): 历史监控记录列表，每条含 view_count 字段
            threshold (int): 目标播放量阈值，默认 10 万

        返回：
            PredictionResult: 包含预测结果的命名元组，字段包括:
                - algorithm_name: 算法名称
                - algorithm_id: 算法标识符
                - target_threshold: 目标阈值
                - predicted_hours: 预测达到阈值所需小时数
                - confidence: 置信度 [0.1, 0.85]
                - current_views: 当前播放量
                - current_velocity: 当前速度（播放/秒）
                - metadata: 附加信息（方法名、突发比例、数据点数）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 10 点或无增速 → 回退匀速预测
            2. 取最近 32 点播放量数据（FFT 偏好 2 的幂次长度）
            3. 去趋势：一阶多项式拟合移除线性趋势
            4. FFT → 对数幅度谱 log|FFT|
            5. 均值滤波估计频谱背景
            6. 频谱残差 = log谱 - 背景谱
            7. iFFT 重建显著图
            8. 显著区域提取（>1.5σ 阈值），非显著区域插值替代显著区域
            9. 基于过滤后趋势分量的末尾差分均值外推
            10. 计算达标时间和置信度（突发越少越可信）
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为负/零时：回退到匀速预测
        if len(history) < 10 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spectral_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 32 条历史记录（2 的幂次更有利于 FFT 计算效率）
            views = np.array([h.get("view_count", 0) for h in history[-32:]], dtype=np.float64)
            n = len(views)

            # 去趋势：用一阶多项式拟合移除整体线性趋势
            # 消除线性升降对频域分析的干扰，保留波动特征
            detrended = views - np.polyval(np.polyfit(np.arange(n), views, 1), np.arange(n))

            # FFT → 对数幅度谱
            fft = np.fft.fft(detrended)  # 快速傅里叶变换
            log_amp = np.log(np.abs(fft) + 1e-10)  # 对数幅度谱，+ε 防止 log(0)

            # 均值滤波得到背景谱：用滑动平均估计正常的频谱背景
            kernel = min(5, len(log_amp) // 2)  # 滤波核大小自适应数据长度
            if kernel >= 3:
                kernel_arr = np.ones(kernel) / kernel  # 等权滑动平均核
                bg = np.convolve(log_amp, kernel_arr, mode='same')  # 一维卷积做滑动平均
            else:
                bg = np.mean(log_amp)  # 核太小则用全局均值替代

            # 频谱残差 = log谱 - 背景谱
            # 残差越大的频率分量越偏离正常模式，对应异常/突发信号
            residual = log_amp - bg

            # iFFT → 显著图（时域重建）
            # exp(残差) 还原幅度，保留原始相位 angle(fft) 保证重建准确性
            salient = np.abs(np.fft.ifft(np.exp(residual + 1j * np.angle(fft))))

            # 显著区域提取：超过 1.5 倍标准差的点标记为突发区域
            threshold_val = 1.5 * np.std(salient) + np.mean(salient)
            burst_region = salient > threshold_val  # 布尔掩码，True = 突发区域

            # 趋势分量 = 非显著区域（过滤掉突发事件）
            trend_component = views.copy()
            if np.any(~burst_region):  # 有非突发区域时才做插值
                # 突发区域的值用两侧非突发区域的值线性插值替代
                trend_component[burst_region] = np.interp(
                    np.where(burst_region)[0],  # 突发区域的索引
                    np.where(~burst_region)[0],  # 非突发区域的索引
                    views[~burst_region],  # 非突发区域的值
                )

            # 趋势外推：基于过滤后的趋势分量末尾差分均值
            if len(trend_component) >= 5:
                growth = np.mean(np.diff(trend_component[-5:]))  # 末尾 5 点差分均值
            else:
                growth = velocity * 3600  # 回退到当前速度

            # 换算为每秒速度（差分值 / 3600 秒）
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")

            # 突发比例：突发区域点数占总点数的比例
            burst_ratio = np.sum(burst_region) / max(len(burst_region), 1)
            # 置信度：突发越少越可信，基础 0.5 × (1-突发比例) + 数据点加成
            confidence = max(0.1, min(0.85, 0.5 * (1 - burst_ratio) + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spectral_residual", "burst_ratio": round(burst_ratio, 3), "data_points": n},
                timestamp=datetime.now(),
            )
        except Exception:
            # 任何异常回退到匀速预测
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "spectral_error"}, timestamp=datetime.now(),
            )
