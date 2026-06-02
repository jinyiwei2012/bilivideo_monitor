"""
SIRD 传染病传播模型 (Susceptible-Infected-Recovered-Depleted)
============================================================

将视频的观看传播过程类比为传染病的传播过程，使用经典的 SIR 模型
的扩展版 SIRD 来进行建模和预测。

核心原理：
    1. SIRD 模型将总人口分为四类：
        - S (Susceptible/易感): 尚未观看但可能观看的潜在观众（粉丝池）
        - I (Infected/感染): 正在观看视频的活跃观众（当前播放增长）
        - R (Recovered/恢复): 已经观看并"免疫"的观众（不再贡献增长）
        - D (Depleted/消亡): 对视频不再感兴趣的用户
    2. 微分方程系统：
        dS/dt = -beta * S * I / N     （易感者被感染者转化为感染）
        dI/dt = beta * S * I / N - gamma * I - delta * I  （新增感染 - 恢复 - 消亡）
        dR/dt = gamma * I              （感染者以速率 gamma 恢复）
        dD/dt = delta * I              （感染者以速率 delta 消亡）
    3. 参数自动估计：
        - beta (传播率): 从日均观看增长量估算
        - gamma (恢复率): 从感染/恢复比估算
        - delta (消亡率): 设为 gamma 的 50%
    4. 使用 scipy.integrate.odeint 求解微分方程，做 90 天预测

适用场景：
    - 需要模拟病毒式传播的动力学过程
    - 数据量 >= 5 个历史点
    - 需要 scipy (不可用时回退为简单速度外推)
    - 适合有大规模粉丝基础的 UP 主视频
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

# 尝试导入 scipy（用于常微分方程求解）
try:
    from scipy.integrate import odeint

    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


class SirdModelAlgorithm(BaseAlgorithm):
    """
    SIRD 传染病传播模型预测算法

    主要功能：
        - 使用 SIRD 四室模型模拟视频播放量的传播动力学
        - 自动从历史数据估算模型参数 (beta, gamma, delta)
        - 通过 odeint 求解微分方程预测未来 90 天的传播趋势
        - 无 scipy 时回退为简单速度外推

    模型假设：
        - 传播遵循易感-感染-恢复-消亡的模式
        - 总人口 = UP 主粉丝数
        - 感染恢复后的用户不再贡献播放增长

    类属性：
        name (str)            : "SIRD传播模型"
        algorithm_id (str)    : "sird_model"
        category (str)        : "高级分析"
        default_weight (float): 1.3
    """

    name = "SIRD传播模型"
    algorithm_id = "sird_model"
    description = "易感-感染-恢复-消亡微分方程模型"
    category = "高级分析"
    default_weight = 1.3

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        使用 SIRD 模型进行预测

        算法流程：
            1. 计算初始状态：S0（易感人口）、I0（当前感染者）、R0（恢复者）、D0（消亡者）
            2. 从历史数据估算模型参数：beta（传播率）、gamma（恢复率）、delta（消亡率）
            3. 使用 odeint 求解微分方程，预测未来 90 天
            4. 在预测结果中搜索到达目标阈值的时间点
            5. 如果 90 天内无法到达，使用峰值预测和增长率外推

        Args:
            video_data (Dict[str, Any]): 视频数据字典
                - view_count (int)        : 当前总播放量
                - history_data (list)     : 历史数据点列表
                - up_fans (int)           : UP 主粉丝数（作为总人口 S0 的参考）
            threshold (int): 目标播放量阈值

        Returns:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)
        # 总易感人口 = UP 主粉丝数，至少为当前播放量的 10 倍或 10 万
        total_fans = video_data.get("up_fans", max(current_views * 10, 100000))

        # 数据不足或速度非正或 scipy 不可用：回退
        if len(history) < 5 or velocity <= 0 or not _HAS_SCIPY:
            return self._fallback(velocity, current_views, threshold)

        try:
            # 提取播放量序列
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            t = np.arange(len(views))  # 时间索引

            # ── 初始化 SIRD 四室状态 ──
            # 易感人数 S0 = 总粉丝数 - 已观看人数
            S0 = max(total_fans - views[-1], 1)
            # 感染者 I0 = 最近播放增量（传播中的播放量）
            I0 = max(views[-1] - views[-2] if len(views) >= 2 else velocity * 3600, 0)
            # 恢复者 R0 = 总播放量 - 当前感染者
            R0 = views[-1] - I0
            # 消亡者 D0（对视频失去兴趣的用户）
            D0 = 0

            # ── SIRD 微分方程定义 ──
            def sird_model(y, t, beta, gamma, delta):
                """
                SIRD 模型的常微分方程组

                Args:
                    y (list): 状态向量 [S, I, R, D]
                    t (float): 时间
                    beta (float): 传播率
                    gamma (float): 恢复率
                    delta (float): 消亡率

                Returns:
                    list: 各状态的导数 [dS/dt, dI/dt, dR/dt, dD/dt]
                """
                S, I, R, D = y
                N = max(S + I + R, 1)  # 归一化因子，避免除以 0
                dS = -beta * S * I / N  # 易感者减少 = 被感染者接触并转化
                dI = beta * S * I / N - gamma * I - delta * I  # 新增感染 - 恢复 - 消亡
                dR = gamma * I  # 恢复者增加 = 感染者 * 恢复率
                dD = delta * I  # 消亡者增加 = 感染者 * 消亡率
                return [dS, dI, dR, dD]

            # ── 参数估计 ──
            # 计算日均观看量（将差分转换为日尺度）
            daily_views = np.diff(views) / max(np.mean(np.diff(t)), 1) * 24
            avg_daily = np.mean(daily_views[-min(5, len(daily_views)) :])  # 最近 5 天日均观看
            # beta: 传播率 = 日均观看 / 易感人数
            beta = max(0.01, avg_daily / max(S0, 1))
            # gamma: 恢复率 = I0 / R0（感染者相对于恢复者的比例）
            gamma = max(0.01, I0 / max(R0, 1)) if R0 > 0 else 0.1
            # delta: 消亡率 = gamma 的 50%
            delta = gamma * 0.5

            # ── 求解微分方程（未来 90 天）──
            future_t = np.linspace(0, 90, 90)  # 90 天，每天一个点
            sol = odeint(sird_model, [S0, I0, R0, D0], future_t, args=(beta, gamma, delta))
            I_pred = sol[:, 1]  # 预测的感染者序列
            R_pred = sol[:, 2]  # 预测的恢复者序列
            total_pred = I_pred + R_pred  # 总累积播放量 = 感染者 + 恢复者

            remaining = threshold - current_views
            # 搜索达到目标阈值的时间点
            idx = np.where(total_pred >= threshold)[0]

            if len(idx) > 0:
                # 找到了达到目标的时间
                predicted_days = future_t[idx[0]]
                predicted_hours = predicted_days * 24
                # 置信度：越早达到目标，置信度越高
                confidence = min(0.8, 0.3 + 0.5 * (1 - predicted_days / 90))
            elif remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                # 90 天内无法达到目标：使用峰值预测和增长率外推
                peak_time = future_t[np.argmax(I_pred)]  # 感染峰值时间
                max_reach = np.max(total_pred)  # 最大可能播放量
                if max_reach > current_views:
                    # 还可能有增长：使用最后 10 天的平均增长率
                    growth_rate = np.mean(np.diff(total_pred[-min(10, len(total_pred)) :])) * 24
                    predicted_velocity_est = max(0, growth_rate)
                    predicted_hours = remaining / max(predicted_velocity_est, 1)
                else:
                    predicted_hours = remaining / velocity  # 已到峰值，回退为速度外推
                confidence = 0.3

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=min(0.85, confidence),
                current_views=current_views,
                current_velocity=velocity,
                metadata={
                    "method": "sird",
                    "beta": float(beta),  # 传播率参数
                    "gamma": float(gamma),  # 恢复率参数
                    "peak_hours": float(peak_time * 24) if "peak_time" in dir() else 0,  # 峰值时间
                },
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
                metadata={"method": "sird", "reason": "fallback"},
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
            metadata={"method": "sird", "reason": "fallback"},
            timestamp=datetime.now(),
        )
