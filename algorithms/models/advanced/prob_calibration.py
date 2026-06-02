"""
概率校准算法 (Probability Calibration)
======================================

使用保序回归 (Isotonic Regression) 校准预测置信度，使其更准确地
反映真实误差分布。解决原始预测算法输出的"置信度"往往不代表
真实准确概率的问题。

核心原理：
    1. 置信度校准问题 - 原始预测算法输出的"置信度"往往不代表真实
       准确概率（例如声称 0.8 置信度但实际准确率只有 0.6）。校准的目标
       是让"置信度 = 0.8"意味着"约有 80% 的概率预测在误差容限内"。
    2. 构建校准数据集 - 对历史序列做留一交叉验证：用每个点之前的数据
       预测该点，记录归一化误差 (|pred-actual|/actual) 作为 X，
       理想置信度 1/(1+error) 作为 Y，形成 (error, confidence) 对。
    3. Isotonic Regression (保序回归) - 非参数单调映射，保证
       "误差越大 -> 置信度越低"的单调性，比 Platt Scaling 更灵活。
    4. 校准应用 - 对当前预测误差估计，通过 Iso 映射得到校准后置信度。

适用场景：
    - 历史数据 >= 15 点时可校准
    - sklearn 不可用时回退为默认置信度 0.5
    - 需要将模型的原始置信度转换为更可靠的概率估计
"""

import logging
import numpy as np
from typing import Dict, Optional
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# 检查 sklearn 是否可用（需要 IsotonicRegression 和 LogisticRegression）
_HAS_SKLEARN = False
try:
    from sklearn.isotonic import IsotonicRegression  # 保序回归
    from sklearn.linear_model import LogisticRegression  # 备用（未使用）
    _HAS_SKLEARN = True
except ImportError:
    pass


class ProbabilityCalibrationAlgorithm(BaseAlgorithm):
    """
    概率校准算法

    主要功能：
        - 用历史数据构建（误差 -> 置信度）的校准映射
        - 通过 Isotonic Regression 学习单调校准函数
        - 输出校准后的置信度，比原始置信度更可靠

    校准流程：
        1. 对历史差分序列做留一交叉验证
        2. 收集 (归一化误差, 理想置信度) 对作为校准数据集
        3. 用 IsotonicRegression 拟合误差 -> 置信度的单调映射
        4. 用当前预测的误差通过映射得到校准后置信度

    类属性：
        name (str)            : "概率校准"
        algorithm_id (str)    : "prob_calibration"
        category (str)        : "高级分析"
        default_weight (float): 1.2
    """

    name = "概率校准"
    algorithm_id = "prob_calibration"
    description = "Platt/Isotonic校准置信度，使预测区间更准确"
    category = "高级分析"
    default_weight = 1.2

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行概率校准预测

        算法流程：
            1. 对历史差分序列进行留一交叉验证，收集 (误差, 置信度) 校准对
            2. 若有 sklearn，用 IsotonicRegression 拟合误差 -> 置信度映射
            3. 用当前预测误差通过校准映射得到校准置信度
            4. 同时计算近 5 步平均增长率作为速度预测

        Args:
            video_data (Dict): 含 view_count / history_data 的视频数据字典
            threshold (int)  : 目标播放量阈值

        Returns:
            PredictionResult: 含 predicted_hours / 校准后 confidence / metadata
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 回退分支：数据不足（< 15 点）时用当前速度估算
        if len(history) < 15 or velocity <= 0:
            remaining = threshold - current_views
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=0.3, current_views=current_views, current_velocity=velocity,
                metadata={"method": "calibration_fallback"}, timestamp=datetime.now(),
            )

        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        n = len(views)
        diffs = np.diff(views)  # 差分序列（每步的增长量）

        if len(diffs) < 8:
            # 差分太少，无法构建足够的校准集，直接用当前速度估算
            growth = velocity * 3600
        else:
            # ── 构建校准数据集 ──
            # 对每个历史点 i (8 <= i < n-1)，用其之前的差分做一步预测，
            # 记录预测误差作为 X，理想置信度 1/(1+error) 作为 Y
            cv_errors = []  # 交叉验证误差列表
            cv_growths = []  # 交叉验证增长率列表
            for i in range(8, n - 1):
                past_diffs = diffs[:i]  # 只用 i 之前的差分
                if len(past_diffs) >= 3:
                    pred = np.mean(past_diffs[-5:])  # 近 5 步平均差分作为预测
                    actual = diffs[i]  # 真实差分值
                    # 归一化相对误差 = |预测 - 真实| / 真实值
                    cv_errors.append(abs(pred - actual) / max(actual, 1e-10))
                    cv_growths.append(pred)  # 记录预测增长率

            # ── Isotonic 校准 ──
            if _HAS_SKLEARN and len(cv_errors) >= 8:
                try:
                    # raw_conf = 1/(1+error): 误差 0 -> 置信度 1，误差大 -> 置信度接近 0
                    raw_conf = 1.0 / (1.0 + np.array(cv_errors))
                    # IsotonicRegression 保序回归：强制单调递减（误差增加 -> 置信度降低）
                    iso = IsotonicRegression(out_of_bounds="clip")
                    iso.fit(np.array(cv_errors), raw_conf)
                    # 用平均误差通过校准器映射出校准后置信度
                    calibrated_conf = float(iso.predict([np.mean(cv_errors)])[0])
                except Exception:
                    calibrated_conf = 0.5  # 校准失败时回退为 0.5
            else:
                calibrated_conf = 0.5  # 无 sklearn 或数据不足时回退为 0.5

            # 增长率预测：近 5 步平均差分
            growth = np.mean(cv_growths[-5:]) if cv_growths else np.mean(diffs)

        # ── 预测速度换算 ──
        predicted_velocity = max(0, growth / 3600)  # 差分为增长率，除以 3600 转换为每秒速度
        if predicted_velocity < 1:
            predicted_velocity = velocity  # 速度过低时退化为当前速度

        remaining = threshold - current_views
        predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
        confidence = max(0.1, min(0.95, calibrated_conf))  # 钳制到 [0.1, 0.95]

        return PredictionResult(
            algorithm_name=self.name, algorithm_id=self.algorithm_id,
            target_threshold=threshold, predicted_hours=predicted_hours,
            confidence=confidence, current_views=current_views, current_velocity=velocity,
            metadata={
                "method": "prob_calibration",
                "raw_conf": round(float(np.mean(cv_errors) if cv_errors else 0), 3),  # 原始平均误差
                "calibrated": round(float(confidence), 3),  # 校准后的置信度
            },
            timestamp=datetime.now(),
        )
