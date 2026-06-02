"""
小波分解预测算法 (Wavelet Decomposition)

【算法类别】频域分析 / 信号分解

【核心思想】
使用离散小波变换（DWT）将播放量时序逐级分解为：
  - 近似系数（Approximation）：低频趋势分量，反映播放量的长期走势
  - 细节系数（Detail）：高频噪声分量，反映短期波动和随机干扰

分解流程：原始信号 → 多级 Haar 小波分解 → 对最低频分量做线性趋势拟合
         → 逐级上采样重建（噪声过滤系数 0.3） → 提取重建序列的增长速度 → 预测达标时间

【适用场景】
- 播放量数据噪声较大的情况（如短时间窗口数据）
- 需要分离长期趋势与短期波动时
- 历史数据量中等（≥8点）的场景

【参数说明】
- Haar 小波：最简小波基，计算复杂度 O(n)，适合实时预测
- 分解级数：由数据长度自动决定（≥2点即可分解一级）
- 噪声过滤系数：0.3，即保留 30% 的细节分量，过滤掉 70% 的高频噪声
- 置信度：基于分解级数和数据点数，取值范围 [0.35, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，执行小波分解与重建
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class WaveletDecompositionAlgorithm(BaseAlgorithm):
    """
    小波分解预测算法

    使用 Haar 小波对播放量时序进行多级离散小波变换（DWT），
    将信号分解为近似系数（趋势）和细节系数（噪声），
    在最低频趋势分量上做线性外推后逐级上采样重建，
    从而过滤高频噪声后的纯净趋势进行预测。

    类属性：
        name: 算法显示名称 "小波分解"
        algorithm_id: 算法唯一标识符 "wavelet_decomp"，用于注册表和数据库
        description: 离散小波变换分解，噪声过滤后趋势外推
        category: 算法分类 "频域分析"，用于 UI 分组
        default_weight: 集成学习中的默认权重 1.2（略高于均值，更重频域信号）
    """

    name = "小波分解"
    algorithm_id = "wavelet_decomp"
    description = "离散小波变换分解，噪声过滤后趋势外推"
    category = "频域分析"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行小波分解预测

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
                - confidence: 置信度 [0, 1]
                - current_views: 当前播放量
                - current_velocity: 当前速度（播放/秒）
                - metadata: 附加信息字典（方法名、分解级数、数据点数）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 8 点或速度为 0 → 回退模式
            2. 小波分解：Haar 小波逐级分解为 approx + detail
            3. 趋势拟合：在最低频近似分量上做一阶多项式拟合
            4. 逆重建：从最低频开始逐级上采样，细节分量 ×0.3 过滤噪声
            5. 速度计算：取重建序列末尾 5 点的差分均值
            6. 置信度：基于分解级数和数据点数
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        if len(history) < 8 or velocity <= 0:
            # 数据不足或速度为零：使用基础匀速预测（回退模式）
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "wavelet_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 32 个播放量数据点作为分析窗口（2 的幂次有利于小波分解）
            views = np.array([h.get("view_count", 0) for h in history[-32:]], dtype=np.float64)
            n = len(views)

            # === Haar 小波分解 (离散小波变换) ===
            # 近似系数 approx = (奇数项 + 偶数项) / 2  — 低频趋势分量
            # 细节系数 detail = (奇数项 - 偶数项) / 2  — 高频噪声分量
            coeffs = views.copy()  # 当前层信号，初始为原始数据
            levels = []  # 存储每一级的 (approx, detail) 系数对
            while len(coeffs) >= 2:  # 至少 2 个点才能继续分解
                approx = (coeffs[::2] + coeffs[1::2]) / 2.0  # 偶数索引+奇数索引取平均 → 近似
                detail = (coeffs[::2] - coeffs[1::2]) / 2.0  # 偶数索引-奇数索引取差值 → 细节
                levels.append((approx, detail))  # 保存当前级的分解结果
                coeffs = approx  # 对近似系数递归进行下一级分解

            # === 在最低频分量上做趋势拟合 ===
            # 最低频的近似系数（最后一级的 approx）代表了最宏观的长期趋势走向
            lowest = levels[-1][0] if levels else views  # 若有分解取最后级，否则用原始数据
            x = np.linspace(0, 1, len(lowest))  # 归一化时间坐标到 [0, 1]
            trend = np.polyfit(x, lowest, 1)  # 一阶多项式拟合（线性趋势）：trend[0]×x + trend[1]

            # === 逆重建：从最低频逐级上采样 ===
            # 从最低频开始，逐步恢复原始分辨率，同时过滤高频噪声
            reconstructed = np.polyval(trend, x)  # 最低频的趋势重建值（趋势拟合结果）
            for i in range(len(levels) - 2, -1, -1):  # 从倒数第二级往上一级一级重建
                approx_prev, detail_prev = levels[i]  # 当前级的近似和细节系数
                # 上采样：每个点复制为两个点，恢复到本级分辨率
                upsampled = np.repeat(reconstructed, 2)[:len(approx_prev)]  # 截断到本级长度
                detail_filtered = detail_prev * 0.3  # 噪声过滤：保留 30% 高频细节，过滤 70%
                reconstructed = upsampled + detail_filtered  # 重建信号 = 低频趋势 + 过滤后细节

            # === 计算重建序列的增长趋势 ===
            if len(reconstructed) >= 2:
                # 取重建序列末尾 5 个点的差分均值作为增长量预测
                growth = np.mean(np.diff(reconstructed[-min(5, len(reconstructed)):]))
            else:
                # 重建序列过短时回退到原始速度
                growth = velocity * 3600

            # 换算为单位：播放量/秒（差分值 / 3600 秒）
            predicted_velocity = max(0, growth / 3600)  # 确保速度非负
            if predicted_velocity < 1:  # 速度过低时沿用当前速度，避免预测为 0
                predicted_velocity = velocity

            # === 计算达标时间 ===
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 and predicted_velocity > 0 else float("inf")
            n_levels = len(levels)  # 小波分解级数
            # 置信度：基础 0.35 + 每级分解加 0.08（最多 4 级）+ 数据点加成（0-0.5），上限 0.85
            confidence = min(0.85, 0.35 + 0.08 * min(n_levels, 4) + 0.02 * min(n, 25))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "wavelet", "levels": n_levels, "data_points": n},
                timestamp=datetime.now(),
            )
        except Exception:
            # 任何异常都回退到匀速预测，确保鲁棒性
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "wavelet_error"}, timestamp=datetime.now(),
            )
