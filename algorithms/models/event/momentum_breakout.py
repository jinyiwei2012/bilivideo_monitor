"""
动量突破检测算法 (Momentum Breakout Detection)

【算法类别】事件驱动 / 技术分析

【核心思想】
借鉴金融领域的技术分析指标，将其映射到播放量分析的语境中：

  - 双均线交叉（Golden Cross / Dead Cross）：
    快均线（5 点）：近期增长速度的短期移动平均
    慢均线（15 点）：较长时间窗口的增长速度均值
    快线 > 慢线 = 动量向上突破（看涨信号）

  - MACD 型信号（异同移动平均线）：
    MACD 线 = 快均线 - 慢均线（反映速度差）
    信号线 = 0.5 × MACD 线 + 0.5 × 中期偏离（平滑后的触发线）
    突破信号 = MACD 线 - 信号线（正值表示加速）

  - RSI 型信号（相对强弱）：
    正差分比例（近 8 点中增长为正的占比）
    比例 > 0.5 表示多头主导，< 0.5 表示空头主导

处理流程：
  差分序列 → 快/慢均线计算 → MACD/信号线 → RSI 正比例
  → 合成动量信号 → 调整增长预测

【适用场景】
- 播放量增长出现"加速度变化"时（从匀速→加速或从加速→减速）
- 类比金融市场的趋势突破/反转判断
- 历史数据量 ≥12 点

【参数说明】
- 快均线窗口：5 点
- 慢均线窗口：min(15, len) 点
- 信号线平滑系数：0.5
- 动量加成：growth × (1 + 0.3 × 突破信号 + 0.2 × RSI 动量)
- 置信度：基于数据点数，范围 [0.1, 0.85]

【关键方法】
- predict(video_data, threshold): 主预测入口，计算技术指标并合成动量信号
"""

import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class MomentumBreakoutAlgorithm(BaseAlgorithm):
    """
    动量突破检测算法

    借鉴金融技术分析中 MACD（异同移动平均线）和 RSI（相对强弱指标）的思想，
    通过计算快慢均线交叉、MACD 信号线和正差分比例，
    合成动量突破信号来判断播放量增速是否出现突破性变化。

    类属性：
        name: 算法显示名称 "动量突破"
        algorithm_id: 算法唯一标识符 "momentum_breakout"
        description: 双均线交叉+RSI+MACD信号，检测播放量增速突破
        category: 算法分类 "事件驱动"
        default_weight: 集成学习默认权重 1.0
    """

    name = "动量突破"
    algorithm_id = "momentum_breakout"
    description = "双均线交叉+RSI+MACD信号，检测播放量增速突破"
    category = "事件驱动"
    default_weight = 1.0

    def predict(self, video_data: Dict, threshold: int = 100000) -> PredictionResult:
        """
        执行动量突破预测

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
                - metadata: 附加信息（方法名、MACD值、正差分比例）
                - timestamp: 预测时间戳

        算法逻辑：
            1. 数据检查：历史数据 < 12 点或无增速 → 回退匀速预测
            2. 计算播放量一阶差分序列
            3. 快均线（5 点 MA）vs 慢均线（15 点 MA）
            4. MACD 线 = 快均线 - 慢均线，信号线 = 0.5×MACD + 0.5×中期偏离
            5. 突破信号 = MACD 线 - 信号线（正值=看涨突破）
            6. RSI 型动量 = 近 8 点正差分比例 - 0.5（正值=多头主导）
            7. 合成增长 = 平均差分 × (1 + 0.3×突破信号 + 0.2×RSI动量)
            8. 计算达标时间和置信度
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
                metadata={"method": "momentum_fallback"}, timestamp=datetime.now(),
            )

        try:
            # 取最近 40 条历史记录的播放量
            views = np.array([h.get("view_count", 0) for h in history[-40:]], dtype=np.float64)
            n = len(views)

            # 平滑播放量：一阶差分 = 每步增长量
            diffs = np.diff(views)
            if len(diffs) < 6:
                # 差分不足 6 点：无法可靠计算均线，直接使用当前速度
                growth = velocity * 3600
            else:
                # 快均线 (5 点 SMA)：近期增长速度的短期移动平均
                fast_ma = np.mean(diffs[-5:]) if len(diffs) >= 5 else np.mean(diffs)
                # 慢均线 (15 点 SMA)：较长时间窗口的增长速度均值
                slow_ma = np.mean(diffs[-min(15, len(diffs)):])

                # MACD: 快-慢 的差分指数平滑
                # MACD 线 = 快均线 - 慢均线，正值表示短期增速高于长期（加速信号）
                macd_line = fast_ma - slow_ma
                # 信号线：MACD 线的平滑版，加入了中期偏离项作为参考
                # 0.5×MACD + 0.5×(中期均值-慢均线)，如果只有近10点平均与慢线的差距
                signal_line = 0.5 * macd_line + 0.5 * (np.mean(diffs[-10:]) - slow_ma) if len(diffs) >= 10 else 0

                # RSI 型信号：正差分比例
                # 最近 8 个差分中正值占比，>0.5 表示多头主导
                pos_ratio = np.sum(diffs[-8:] > 0) / min(8, len(diffs[-8:])) if len(diffs) >= 8 else 0.5

                # 合成信号
                # 突破信号 = MACD线 - 信号线：正值表示 MACD 上穿信号线（金叉/突破）
                breakout_signal = macd_line - signal_line
                # RSI 动量 = 正比例 - 0.5：正值表示多头，负值表示空头
                momentum = pos_ratio - 0.5

                # 合成增长 = 平均差分 × (1 + 0.3×突破信号 + 0.2×RSI动量)
                # 突破信号和动量信号共同调整基线增长
                growth = np.mean(diffs) * (1 + 0.3 * breakout_signal + 0.2 * momentum)
                growth = max(0, growth)  # 确保非负

            # 换算为每秒速度（差分值 / 3600 秒）
            predicted_velocity = max(0, growth / 3600)
            if predicted_velocity < 1:  # 速度过低时沿用当前速度
                predicted_velocity = velocity

            # 计算达到阈值所需小时数
            remaining = threshold - current_views
            predicted_hours = remaining / predicted_velocity if remaining > 0 else float("inf")
            # 置信度：基础 0.35 + 数据点加成（0-0.5），上限 0.85
            confidence = max(0.1, min(0.85, 0.35 + 0.02 * min(n, 25)))

            return PredictionResult(
                algorithm_name=self.name, algorithm_id=self.algorithm_id,
                target_threshold=threshold, predicted_hours=predicted_hours,
                confidence=confidence, current_views=current_views, current_velocity=velocity,
                metadata={
                    "method": "momentum_breakout",
                    "macd": round(float(macd_line), 4) if "macd_line" in dir() else 0,  # MACD 线值
                    "pos_ratio": round(float(pos_ratio), 3),  # 正差分比例
                },
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
                metadata={"method": "momentum_error"}, timestamp=datetime.now(),
            )
