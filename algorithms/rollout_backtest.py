"""
滚动窗口回测框架 (Rolling Window Backtest)

时间序列交叉验证，评估算法在历史数据上的表现。

核心原理：
1. 对每个视频取最近 N 个数据点
2. 用前面的数据预测后面，记录预测误差
3. 滑动窗口重复，累积误差统计（RMSE/MAE/MAPE）
4. 输出每个算法的离线评估指标
5. 可选：自动选出最优 k 个预测器并分配权重

关键参数：
- min_train: 训练窗口最小大小（默认 10 个点）
- step: 窗口滑动步长（默认 3 个点）
- horizon: 预测前置步数（默认 1 步，即预测下一个点）

内置简单预测函数工厂：
- make_linear_fn: 线性回归预测
- make_moving_avg_fn: 移动平均预测
- make_exp_fn: 指数增长预测
- make_theta_fn: Theta 方法预测
"""

import numpy as np
from typing import Dict, List, Tuple, Callable
from datetime import datetime


class RollingBacktester:
    """
    滚动窗口回测器。
    
    对时间序列执行滑动窗口交叉验证，评估预测函数的离线表现。
    不修改任何实际数据，纯离线评估。
    
    用法
    ----
    >>> backtester = RollingBacktester(min_train=10, step=3, horizon=1)
    >>> result = backtester.backtest(series, predict_fn)
    >>> # result = {"rmse": ..., "mae": ..., "mape": ..., "n_tests": ...}
    """

    def __init__(self, min_train: int = 10, step: int = 3, horizon: int = 1):
        """
        初始化回测器。
        
        Args:
            min_train: 最小训练窗口大小（数据点个数）
            step: 窗口向前滑动的步长
            horizon: 预测前置步数（1 表示预测下一个点）
        """
        self.min_train = min_train
        self.step = step
        self.horizon = horizon

    def backtest(
        self, series: np.ndarray, predict_fn: Callable[[np.ndarray], float]
    ) -> Dict[str, float]:
        """对单个预测函数执行滚动回测。
        
        流程：
        1. 从 min_train 点开始，用 [0:i) 的数据训练/预测
        2. 预测第 i+horizon-1 个点（下一个观测）
        3. 窗口向前滑动 step 步，重复

        Args:
            series: 时间序列数据（一维数组）
            predict_fn: predict_fn(train_data) -> 预测的下一个值

        Returns:
            {"rmse": float, "mae": float, "mape": float, "n_tests": int}
        """
        n = len(series)
        errors = []  # 绝对误差列表 = predicted - actual
        abs_pct_errors = []  # 绝对百分比误差列表

        for i in range(self.min_train, n - self.horizon + 1, self.step):
            train = series[:i]  # 训练窗口
            actual = series[i + self.horizon - 1]  # 真实值
            if actual <= 0:
                continue  # 跳过零值，避免 MAPE 除零
            try:
                pred = predict_fn(train)
                err = pred - actual
                errors.append(err)
                abs_pct_errors.append(abs(err) / actual)
            except Exception:
                # 预测异常跳过该窗口
                continue

        if not errors:
            return {"rmse": float("inf"), "mae": float("inf"), "mape": float("inf"), "n_tests": 0}

        errors_arr = np.array(errors)
        ape_arr = np.array(abs_pct_errors)
        return {
            "rmse": float(np.sqrt(np.mean(errors_arr ** 2))),  # 均方根误差
            "mae": float(np.mean(np.abs(errors_arr))),  # 平均绝对误差
            "mape": float(np.mean(ape_arr)),  # 平均绝对百分比误差
            "n_tests": len(errors),  # 测试样本数
        }

    def backtest_multi_predictor(
        self, series: np.ndarray,
        predictors: Dict[str, Callable[[np.ndarray], float]]
    ) -> Dict[str, Dict[str, float]]:
        """对多个预测函数同时回测。
        
        Args:
            series: 时间序列数据
            predictors: {名称: 预测函数} 字典
            
        Returns:
            {name: {rmse, mae, mape, n_tests}, ...}
        """
        results = {}
        for name, fn in predictors.items():
            results[name] = self.backtest(series, fn)
        return results

    def select_top_k(
        self, series: np.ndarray,
        predictors: Dict[str, Callable[[np.ndarray], float]],
        k: int = 5
    ) -> List[Tuple[str, float, float]]:
        """回测后选出最优 k 个预测器，返回 (name, weight, mape)。

        评分规则：score = RMSE + 0.5 * MAE（越小越好）
        权重分配：weight ∝ 1/score（越准的预测器权重越高）

        Args:
            series: 时间序列数据
            predictors: {名称: 预测函数} 字典
            k: 选出前 k 个最优预测器

        Returns:
            [(name, weight, mape), ...] 格式的排名列表
        """
        results = self.backtest_multi_predictor(series, predictors)
        scored = []
        for name, r in results.items():
            if r["n_tests"] < 3:  # 测试次数太少，不可靠
                continue
            score = r["rmse"] + r["mae"] * 0.5  # 综合评分（RMSE 权重更高）
            scored.append((name, score, r["mape"]))
        # 按评分升序排列（分数越低越好）
        scored.sort(key=lambda x: x[1])
        top = scored[:k]
        if not top:
            return [("default", 1.0, 0.5)]  # 兜底
        # 权重与评分成反比：w_i ∝ 1/score_i
        total_score = sum(1.0 / max(s, 1e-10) for _, s, _ in top)
        weights = [(name, (1.0 / max(s, 1e-10)) / total_score, mape) for name, s, mape in top]
        return weights


# ── 简单的 predict_fn 工厂 ───────────────────────────
# 这些函数返回可作为 predict_fn 参数的闭包，
# 用于快速比较不同基础模型的回测表现


def make_linear_fn(order: int = 1) -> Callable:
    """
    线性/多项式回归预测函数工厂。
    
    用 polyfit 拟合训练数据的多项式趋势，
    然后预测下一个值。order=1 为线性，order=2 为二次。

    Args:
        order: 多项式阶数

    Returns:
        Callable: predict_fn(train_data) → float
    """
    def fn(train: np.ndarray) -> float:
        if len(train) < 2:
            return float(train[-1]) if len(train) > 0 else 0
        return float(np.polyval(np.polyfit(np.arange(len(train)), train, order), len(train)))
    return fn


def make_moving_avg_fn(window: int = 5) -> Callable:
    """
    移动平均预测函数工厂。
    
    计算最近 window 个点的差分的平均值作为预测增量。

    Args:
        window: 移动平均窗口大小

    Returns:
        Callable: predict_fn(train_data) → float
    """
    def fn(train: np.ndarray) -> float:
        if len(train) < 2:
            return float(train[-1]) if len(train) > 0 else 0
        diffs = np.diff(train[-window:])  # 最近窗口的一阶差分
        return train[-1] + np.mean(diffs) if len(diffs) > 0 else float(train[-1])
    return fn


def make_exp_fn() -> Callable:
    """
    指数增长预测函数工厂。
    
    对数据进行 log 变换后用线性回归拟合，再 exp 回去，
    适合预测呈指数增长模式的数据。

    Returns:
        Callable: predict_fn(train_data) → float
    """
    def fn(train: np.ndarray) -> float:
        if len(train) < 3:
            return float(train[-1]) if len(train) > 0 else 0
        log_v = np.log(np.maximum(train, 1))  # log 变换，确保非负
        return float(np.exp(np.polyval(np.polyfit(np.arange(len(log_v)), log_v, 1), len(log_v))))
    return fn


def make_theta_fn(theta: float = 2.0) -> Callable:
    """
    Theta 方法预测函数工厂。

    Theta 方法：将时间序列分解为趋势 + 季节，
    趋势用线性回归，季节分量取均值调整。

    Args:
        theta: theta 参数

    Returns:
        Callable: predict_fn(train_data) → float
    """
    def fn(train: np.ndarray) -> float:
        if len(train) < 4:
            return float(train[-1]) if len(train) > 0 else 0
        x = np.arange(len(train))
        trend = np.polyfit(x, train, 1)  # 线性趋势
        seasonal = train - np.polyval(trend, x)  # 去趋势后的季节分量
        # 取最近一段季节分量的均值作为调整
        season_adj = np.mean(seasonal[-max(1, len(train)//4):])
        return float(np.polyval(trend, len(train)) + 0.5 * season_adj)
    return fn
