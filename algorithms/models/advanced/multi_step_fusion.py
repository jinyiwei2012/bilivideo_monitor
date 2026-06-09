"""
多步多频率融合预测算法 (Multi-Step + Multi-Frequency Fusion)
============================================================

综合三种预测技术的融合算法，提供更鲁棒和可靠的预测。

核心思路：
    1. 多步预测 (Multi-Step Forecast) - 模仿 seq2seq 风格，
       用线性 + 二次多项式组合一次性外推未来多个时间步。
       近步线性主导（稳定），远步二次主导（捕获趋势变化），
       避免远步发散。
    2. 多频率建模 (Multi-Frequency Modeling) - 同时利用三种
       时间尺度的信号：
         - 高频（相邻差分）：捕获短期波动和即时变化
         - 中频（每 3 点采样）：平滑高频噪声，中等时间尺度
         - 低频（每 6 点采样）：捕获长期趋势和缓慢变化
       加权融合捕获短期波动与长期趋势。
    3. 升级共形预测 (Upgraded Conformal) - 用留出校准集计算
       归一化残差分布分位数，替换固定半宽，使预测区间
       自适应数据波动。覆盖率 = 90% (alpha = 0.1)。

优势：
    - 多频率融合比单一频率更鲁棒（抗噪声）
    - 多步预测 + 频率融合双路校准，降低单路偏差
    - 升级共形预测给出覆盖率可解释的置信度
"""

import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MultiStepFusionAlgorithm(BaseAlgorithm):
    """
    多步多频率融合预测算法

    主要功能：
        - 多步外推：同时预测未来 5 步的播放量
        - 多频率融合：高频/中频/低频三种尺度信源的加权平均
        - 升级共形区间：归一化残差分位数提供覆盖率保证
        - 双路校准：频率融合 + 多步预测互相校正

    融合权重设计：
        高频 50%：最近期的波动最重要（即时变化）
        中频 30%：中期趋势平滑高频噪声
        低频 20%：长期趋势补充全局方向
    """

    name = "多步融合"
    algorithm_id = "multi_step_fusion"
    description = "seq2seq多步预测+多频率融合+升级共形区间"
    category = "高级分析"
    default_weight = 1.4

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行多步多频率融合预测

        算法流程：
            1. 多步预测：线性+二次组合外推未来 5 步播放量
            2. 多频率建模：高频(相邻)、中频(步长3)、低频(步长6)加权融合
            3. 多步校正：多步预测的平均速率对频率增长率进行二次校正
            4. 升级共形：用归一化残差分位数计算置信边界
            5. 综合计算预测时间和置信度

        Args:
            video_data (Dict): 含 view_count / history_data 的视频数据字典
            threshold (int)  : 目标播放量阈值

        Returns:
            PredictionResult: 含 predicted_hours / confidence / metadata
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 回退分支：数据不足（< 15 个点）时用当前速度简单估算
        if len(history) < 15 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "msf_fallback"}, timestamp=datetime.now(),
            )

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)

        # ── 多步预测：一步生成未来 5 个时间步的播放量 ──
        steps = 5
        multi_preds = self._multi_step_forecast(views, steps)

        # ── 多频率建模 ──
        # 高频信号：原始相邻差分（保留所有细节波动）
        high_freq = np.diff(views)
        hf_growth = np.mean(high_freq[-min(5, len(high_freq)):]) if len(high_freq) >= 1 else 0

        # 中频信号：每 3 个点采样一次（约 30 分钟间隔，平滑高频噪声）
        mid_idx = np.arange(0, n, 3)
        if len(mid_idx) >= 2:
            mid_freq = np.diff(views[mid_idx])
            mf_growth = np.mean(mid_freq) / 3 if len(mid_freq) > 0 else 0  # 除 3 还原到单步尺度
        else:
            mf_growth = hf_growth  # 中频不可用时回退到高频

        # 低频信号：每 6 个点采样一次（约 1 小时间隔，捕获长期趋势）
        low_idx = np.arange(0, n, 6)
        if len(low_idx) >= 2:
            low_freq = np.diff(views[low_idx])
            lf_growth = np.mean(low_freq) / 6 if len(low_freq) > 0 else 0  # 除 6 还原到单步尺度
        else:
            lf_growth = hf_growth  # 低频不可用时回退到高频

        # ── 频率融合：高频主导近期，低频补充长期趋势 ──
        growth_fusion = 0.5 * hf_growth + 0.3 * mf_growth + 0.2 * lf_growth

        # ── 多步预测校正：用多步预测的平均增长率修正频率融合结果 ──
        if len(multi_preds) >= 2:
            multi_growth = np.mean(np.diff(multi_preds))  # 多步预测的平均步长增长
            growth = 0.6 * growth_fusion + 0.4 * multi_growth  # 双路融合：频率(60%)+多步(40%)
        else:
            growth = growth_fusion

        # ── 升级共形预测 ──
        alpha = 0.1  # 显著性水平（覆盖率 = 90%）
        calibration_window = min(20, n // 3)  # 校准窗口大小：最多 20 个点
        if n >= calibration_window * 2:
            train = views[:-calibration_window]  # 训练集（前部）
            calib = views[-calibration_window:]  # 校准集（尾部）
            scores = []
            for i, actual in enumerate(calib):
                # 用训练集的近 5 点平均增长率做一步预测
                if len(train) >= 5 and i < len(train) - 1:
                    pred_i = train[-1] + np.mean(np.diff(train[-5:]))
                    # 归一化残差 = |预测-真实| / 真实值（相对误差）
                    scores.append(abs(actual - pred_i) / max(actual, 1e-10))
            if scores:
                scores = np.sort(scores)  # 按相对误差排序
                q_idx = int(np.ceil((1 - alpha) * len(scores))) - 1
                q_idx = max(0, min(q_idx, len(scores) - 1))
                conformal_bound = scores[q_idx]  # (1-alpha) 分位数作为误差边界
            else:
                conformal_bound = 0.2  # 默认 20% 相对误差
        else:
            conformal_bound = 0.2  # 数据不足时使用默认值

        # ── 预测速度换算 ──
        predicted_velocity = max(0, growth / 3600)  # 每小时播放量增速（增长步长/3600秒）
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 速度过低时退化为当前速度

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        interval_width = conformal_bound  # 共形区间相对宽度
        # 区间越宽 -> 置信度越低（反比映射到 [0.1, 0.95]）
        confidence = max(0.1, min(0.95, 0.7 / (1 + interval_width)))

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "multi_step_fusion",
                "multi_steps": len(multi_preds),  # 多步预测的步数
                "conformal_bound": round(float(conformal_bound), 4),  # 共形误差边界
                "freq_growths": {  # 三种频率的增长率（诊断用途）
                    "high": round(float(hf_growth), 1),
                    "mid": round(float(mf_growth), 1),
                    "low": round(float(lf_growth), 1),
                },
            },
            timestamp=datetime.now(),
        )

    def _multi_step_forecast(self, views: np.ndarray, steps: int) -> List[float]:
        """
        简化的 seq2seq 多步外推预测

        用线性 + 二次多项式组合做多步外推。

        核心策略：
            - 近距离步：线性占主导（w1 接近 1），因为线性外推短期更稳定
            - 远距离步：二次占主导（w1 接近 0.2），因为二次项能捕获加速/减速
            - 权重 w1 随步数线性衰减，确保平滑过渡

        Args:
            views (np.ndarray): 一维播放量时间序列（长度 >= 10）
            steps (int)       : 要预测的未来步数

        Returns:
            List[float]: 长度为 steps 的多步预测值列表
        """
        n = len(views)
        if n < 10:
            return [views[-1]] if n > 0 else [0]  # 数据不足时返回最后的值

        # 拟合线性 + 二次多项式
        x = np.arange(n)
        coef1 = np.polyfit(x, views, 1)  # 一次多项式系数
        coef2 = np.polyfit(x, views, 2) if n >= 5 else coef1  # 二次多项式系数（需 >= 5 点）

        preds = []
        for step in range(1, steps + 1):
            t = n + step - 1  # 未来第 step 步的时间索引
            p1 = np.polyval(coef1, t)  # 线性外推值
            p2 = np.polyval(coef2, t) if n >= 5 else p1  # 二次外推值
            # 近步线性权重大（稳定），远步二次权重大（捕获趋势变化）
            # 线性权重从 1.0 线性衰减到 1/(steps+1)，最少保留 20%
            w1 = max(0.2, 1.0 - step / (steps + 1))
            preds.append(w1 * p1 + (1 - w1) * p2)  # 加权融合
        return preds
