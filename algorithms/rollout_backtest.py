"""
滚动窗口回测框架 (Rolling Window Backtest)
时间序列交叉验证，评估算法在历史数据上的表现

核心原理：
1. 对每个视频取最近 N 个数据点
2. 用前面的数据预测后面，记录误差
3. 滑动窗口重复，累积误差统计
4. 输出每个算法的 RMSE/MAE/MAPE
"""

import numpy as np
from typing import Dict, List, Tuple, Callable
from datetime import datetime


class RollingBacktester:
    """滚动窗口回测器"""

    def __init__(self, min_train: int = 10, step: int = 3, horizon: int = 1):
        self.min_train = min_train
        self.step = step
        self.horizon = horizon

    def backtest(
        self, series: np.ndarray, predict_fn: Callable[[np.ndarray], float]
    ) -> Dict[str, float]:
        """对单个预测函数执行滚动回测
        
        Args:
            series: 时间序列数据
            predict_fn: predict_fn(train_data) -> 预测的下一个值
            
        Returns:
            {"rmse": ..., "mae": ..., "mape": ..., "n_tests": ...}
        """
        n = len(series)
        errors = []
        abs_pct_errors = []

        for i in range(self.min_train, n - self.horizon + 1, self.step):
            train = series[:i]
            actual = series[i + self.horizon - 1]
            if actual <= 0:
                continue
            try:
                pred = predict_fn(train)
                err = pred - actual
                errors.append(err)
                abs_pct_errors.append(abs(err) / actual)
            except Exception:
                continue

        if not errors:
            return {"rmse": float("inf"), "mae": float("inf"), "mape": float("inf"), "n_tests": 0}

        errors_arr = np.array(errors)
        ape_arr = np.array(abs_pct_errors)
        return {
            "rmse": float(np.sqrt(np.mean(errors_arr ** 2))),
            "mae": float(np.mean(np.abs(errors_arr))),
            "mape": float(np.mean(ape_arr)),
            "n_tests": len(errors),
        }

    def backtest_multi_predictor(
        self, series: np.ndarray,
        predictors: Dict[str, Callable[[np.ndarray], float]]
    ) -> Dict[str, Dict[str, float]]:
        """对多个预测函数同时回测
        
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
        """回测后选出最优 k 个预测器，返回 (name, weight, mape)"""
        results = self.backtest_multi_predictor(series, predictors)
        scored = []
        for name, r in results.items():
            if r["n_tests"] < 3:
                continue
            score = r["rmse"] + r["mae"] * 0.5
            scored.append((name, score, r["mape"]))
        scored.sort(key=lambda x: x[1])
        top = scored[:k]
        if not top:
            return [("default", 1.0, 0.5)]
        total_score = sum(1.0 / max(s, 1e-10) for _, s, _ in top)
        weights = [(name, (1.0 / max(s, 1e-10)) / total_score, mape) for name, s, mape in top]
        return weights


# ── 简单的 predict_fn 工厂 ───────────────────────────

def make_linear_fn(order: int = 1) -> Callable:
    def fn(train: np.ndarray) -> float:
        if len(train) < 2:
            return float(train[-1]) if len(train) > 0 else 0
        return float(np.polyval(np.polyfit(np.arange(len(train)), train, order), len(train)))
    return fn


def make_moving_avg_fn(window: int = 5) -> Callable:
    def fn(train: np.ndarray) -> float:
        if len(train) < 2:
            return float(train[-1]) if len(train) > 0 else 0
        diffs = np.diff(train[-window:])
        return train[-1] + np.mean(diffs) if len(diffs) > 0 else float(train[-1])
    return fn


def make_exp_fn() -> Callable:
    def fn(train: np.ndarray) -> float:
        if len(train) < 3:
            return float(train[-1]) if len(train) > 0 else 0
        log_v = np.log(np.maximum(train, 1))
        return float(np.exp(np.polyval(np.polyfit(np.arange(len(log_v)), log_v, 1), len(log_v))))
    return fn


def make_theta_fn(theta: float = 2.0) -> Callable:
    def fn(train: np.ndarray) -> float:
        if len(train) < 4:
            return float(train[-1]) if len(train) > 0 else 0
        x = np.arange(len(train))
        trend = np.polyfit(x, train, 1)
        seasonal = train - np.polyval(trend, x)
        season_adj = np.mean(seasonal[-max(1, len(train)//4):])
        return float(np.polyval(trend, len(train)) + 0.5 * season_adj)
    return fn
