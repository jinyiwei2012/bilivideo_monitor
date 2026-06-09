"""
希尔伯特-黄变换预测算法 (Hilbert-Huang Transform, HHT)

【算法类别】频域分析 / 自适应信号分解

【核心思想】
希尔伯特-黄变换包含两步：
  1. EMD（经验模态分解）：将非平稳时序自适应地分解为若干本征模态函数（IMF），
     每个 IMF 代表不同时间尺度的振荡模式，按频率从高到低排列。
  2. Hilbert 谱分析：对每个 IMF 做 Hilbert 变换，提取瞬时频率和瞬时幅度（本实现简化）。

处理流程：
  原始播放量序列 → EMD 迭代分解（最多 4 级 IMF）→ 提取各 IMF 的尾部增长趋势
  → 对各 IMF 趋势取均值 → 换算为预测速度 → 计算达标时间

【EMD 分解步骤】
  1. 找到信号的极大值点
  2. 通过线性插值构造上包络线
  3. IMF = 信号 - 0.5 × 上包络（简化筛分过程）
  4. 从残差中减去当前 IMF，继续分解下一级

【适用场景】
- 非平稳、非线性的播放量时序（大部分实际情况）
- 存在多时间尺度波动叠加的场景（如日周期 + 周趋势 + 突发事件）
- 历史数据量 ≥12 点

【参数说明】
- 最大 IMF 数量：4，平衡分解精度与计算开销
- 极值点检测：一阶导符号变化判定极大值
- 包络插值：线性插值（简化替代三次样条，计算更稳定）
- 置信度：基于 IMF 个数和数据点数，范围 [0.3, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，执行 EMD 分解与趋势合成
"""

import numpy as np
from typing import Dict, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class HilbertHuangAlgorithm(BaseAlgorithm):
    """
    希尔伯特-黄变换预测算法

    使用 EMD（经验模态分解）将播放量时序自适应地分解为多个本征模态函数（IMF），
    每个 IMF 代表不同时间尺度的振荡模式。从各 IMF 中提取尾部增长趋势，
    合成得到多尺度融合的增长预测。简化了 Hilbert 谱分析步骤。

    类属性：
        name: 算法显示名称 "希尔伯特黄"
        algorithm_id: 算法唯一标识符 "hilbert_huang"
        description: EMD经验模态分解+Hilbert谱，非平稳时序分析
        category: 算法分类 "频域分析"
        default_weight: 集成学习默认权重 1.2（略高于均值，更重频域信号）
    """

    name = "希尔伯特黄"
    algorithm_id = "hilbert_huang"
    description = "EMD经验模态分解+Hilbert谱，非平稳时序分析"
    category = "频域分析"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行希尔伯特-黄变换预测

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
                - confidence: 置信度 [0.3, 0.85]
                - current_views: 当前播放量
                - current_velocity: 当前速度（播放/秒）
                - metadata: 附加信息（方法名、IMF个数、数据点数）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 12 点或无增速 → 回退匀速预测
            2. EMD 迭代分解（最多 4 级）：
               a. 找极大值点（一阶导符号由正变负处）
               b. 线性插值构造上包络线
               c. IMF = 信号 - 0.5×上包络（简化筛分）
               d. 残差减去 IMF，继续下一级
            3. 提取各 IMF 尾部 5 个点的差分均值作为增长趋势
            4. 所有 IMF 趋势取均值作为最终增长量
            5. 换算为每秒速度并计算达标时间
            6. 置信度基于 IMF 数量和数据点数
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足或速度为负/零时：回退到匀速预测
        if len(history) < 12 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "hht_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 40 条历史记录的播放量
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 简化 EMD: 迭代提取 IMF（本征模态函数）
            residuals = views.astype(float)  # 当前残差序列，初始为原始信号
            imfs: List[np.ndarray] = []  # 存储所有提取出的 IMF
            max_imf = 4  # 最多提取 4 个 IMF，平衡精度与开销
            for _ in range(max_imf):
                if len(residuals) < 4:  # 残差点数不足，停止分解
                    break

                signal = residuals.copy()  # 当前层信号

                # 查找极大值点：一阶导符号由正变负的位置
                maxima = []
                for i in range(1, len(signal) - 1):
                    if signal[i] > signal[i - 1] and signal[i] > signal[i + 1]:
                        maxima.append(i)  # 记录极大值索引
                if len(maxima) < 2:  # 至少需要 2 个极大值点才能构造包络
                    break

                # 上包络：通过线性插值连接所有极大值点
                upper_env = np.interp(np.arange(len(signal)), maxima, signal[maxima])

                # IMF = 信号 - 0.5 × 上包络（简化筛分，标准 EMD 需多次迭代）
                imf = signal - upper_env * 0.5
                imfs.append(imf)  # 保存当前 IMF
                residuals = residuals - imf  # 更新残差 = 原残差 - 当前 IMF

            # 最低频残差做趋势：提取各 IMF 尾部增长量
            growths = []
            for imf in imfs:
                if len(imf) >= 3:
                    # 取各 IMF 末尾 5 个点的差分均值作为增长量
                    g = np.mean(np.diff(imf[-min(5, len(imf)):]))
                    growths.append(g)

            # 添加最低频 IMF（最深层的趋势分量）的增长率
            if imfs:
                trend_imf = imfs[-1]  # 最后一个 IMF 频率最低，代表长期趋势
                if len(trend_imf) >= 3:
                    growths.append(np.mean(np.diff(trend_imf[-5:])))

            # 所有 IMF 趋势取均值，若无有效趋势则回退到当前速度
            growth = np.mean(growths) if growths else velocity * 3600
            # 换算为每秒速度（增长量 / 3600 秒）
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            n_imfs = len(imfs)
            # 置信度：基础 0.3 + IMF 数量加成（0-0.24）+ 数据点加成（0-0.5），上限 0.85
            confidence = min(0.85, 0.3 + 0.08 * min(n_imfs, 3) + 0.02 * min(n, 25))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={"method": "hilbert_huang", "imfs": n_imfs, "data_points": n},
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
                metadata={"method": "hht_error"}, timestamp=datetime.now(),
            )
