"""
Richards曲线模型
广义Logistic模型，更灵活的S型曲线
可以模拟不对称的增长过程
"""

import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from scipy.optimize import curve_fit
from algorithms.base import BaseAlgorithm

logger = logging.getLogger(__name__)

_TS_FMT = "%Y-%m-%d %H:%M:%S"


class RichardsCurveAlgorithm(BaseAlgorithm):
    """
    Richards Curve Model (Generalized Logistic)

    公式: V(t) = K / (1 + ν * exp(-r * (t - t0)))^(1/ν)
    其中:
    - K: 最大播放量
    - r: 增长率
    - t0: 中点时间
    - ν: 形状参数 (控制曲线不对称性)
    """

    name = "Richards曲线模型"
    description = "广义Logistic模型，支持不对称增长"
    category = "扩散模型"

    def __init__(self):
        super().__init__()
        self.K = 1000000
        self.r = 0.2
        self.t0 = 30
        self.nu = 1.0
        self._maxfev = 300
        self._min_curvefit_points = 10

    def predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间
        """
        if not history_data or len(history_data) < 4:
            return None

        try:
            times, views = self._prepare_data(history_data)

            if len(times) < 4:
                return None

            self._fit_curve(times, views, video_info)

            if current_views >= target_views:
                return (0, 1.0)

            if target_views >= self.K * 0.99:
                self.K = target_views * 1.2

            current_t = times[-1]
            target_t = self._find_time_for_views(target_views)

            if target_t is None:
                return None

            days_needed = target_t - current_t

            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(times, views)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Richards模型预测失败: {e}")
            return None

    def _prepare_data(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """准备数据"""
        n = len(history_data)
        times = np.empty(n, dtype=float)
        views = np.empty(n, dtype=float)

        first_ts = history_data[0]["timestamp"]
        if isinstance(first_ts, str):
            base_epoch = datetime.strptime(first_ts, _TS_FMT).timestamp()
        elif isinstance(first_ts, datetime):
            base_epoch = first_ts.timestamp()
        else:
            base_epoch = float(first_ts)

        times[0] = 0.0
        views[0] = history_data[0].get("view", history_data[0].get("view_count", 0))

        for i in range(1, n):
            data = history_data[i]
            views[i] = data.get("view", data.get("view_count", 0))
            ts_raw = data["timestamp"]
            if isinstance(ts_raw, str):
                ts_epoch = datetime.strptime(ts_raw, _TS_FMT).timestamp()
            elif isinstance(ts_raw, datetime):
                ts_epoch = ts_raw.timestamp()
            else:
                ts_epoch = float(ts_raw)
            times[i] = (ts_epoch - base_epoch) / 86400.0

        return times, views

    def _richards(self, t, K, r, t0, nu):
        """Richards函数"""
        return K / np.power(1 + nu * np.exp(-r * (t - t0)), 1.0 / nu)

    def _fit_curve(self, times: np.ndarray, views: np.ndarray, video_info: Dict[str, Any]):
        """拟合Richards曲线"""
        if len(times) < self._min_curvefit_points:
            self.K = max(views) * 3
            self.r = 0.15
            self.t0 = np.median(times) if len(times) > 0 else 30
            self.nu = 1.0
            if "follower" in video_info:
                self.K = max(self.K, video_info["follower"] * 2.5)
            return

        try:
            K_est = max(views) * 2.5
            r_est = 0.2
            t0_est = np.median(times)
            nu_est = 1.0

            p0 = [K_est, r_est, t0_est, nu_est]
            bounds = ([max(views), 0.01, 0, 0.1], [K_est * 10, 2.0, times[-1] * 5, 5.0])

            popt, _ = curve_fit(self._richards, times, views, p0=p0, bounds=bounds, maxfev=self._maxfev)

            self.K, self.r, self.t0, self.nu = popt

        except Exception:
            self.K = max(views) * 3
            self.r = 0.15
            self.t0 = np.median(times) if len(times) > 0 else 30
            self.nu = 1.0

            if "follower" in video_info:
                self.K = max(self.K, video_info["follower"] * 2.5)

    def _find_time_for_views(self, target_views: int) -> Optional[float]:
        """找到达到目标播放量所需时间"""
        try:
            # V = K / (1 + ν * exp(-r * (t - t0)))^(1/ν)
            # (K/V)^ν = 1 + ν * exp(-r * (t - t0))
            # (K/V)^ν - 1 = ν * exp(-r * (t - t0))
            # ((K/V)^ν - 1) / ν = exp(-r * (t - t0))
            # ln(((K/V)^ν - 1) / ν) = -r * (t - t0)
            # t = t0 - ln(((K/V)^ν - 1) / ν) / r

            if target_views >= self.K:
                return None

            ratio = np.power(self.K / target_views, self.nu) - 1
            if ratio <= 0:
                return None

            inner = ratio / self.nu
            if inner <= 0:
                return None

            t = self.t0 - np.log(inner) / self.r
            return max(0, t)
        except Exception:
            return None

    def _calculate_confidence(self, times: np.ndarray, views: np.ndarray) -> float:
        """计算置信度"""
        n = len(times)
        base_conf = min(0.9, 0.4 + n * 0.025)

        if n >= 5:
            try:
                predicted = self._richards(times, self.K, self.r, self.t0, self.nu)
                mape = np.mean(np.abs((views - predicted) / (views + 1)))
                fit_quality = max(0, 1 - mape)
                base_conf = 0.5 * base_conf + 0.5 * fit_quality
            except Exception as e:
                logger.debug("Richards曲线置信度计算失败: %s", e)

        return min(0.95, base_conf)
