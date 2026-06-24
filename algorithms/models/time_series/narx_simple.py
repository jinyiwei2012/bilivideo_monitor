"""
NARX预测算法 (Nonlinear AutoRegressive with eXogenous inputs)

带外生输入的非线性自回归模型，将点赞、投币、收藏等互动数据
作为外生变量（Exogenous Inputs）纳入预测，捕捉互动行为对播放量增长的推动作用。

核心原理：
    传统AR模型仅使用历史播放量预测未来播放量。
    NARX模型额外引入外生输入（点赞、投币、收藏），
    利用多元回归建模"互动 → 播放"的因果关系。

    模型形式：
        Δviews_t = f(Δviews_{t-1}, ..., Δviews_{t-p},
                      Δlikes_{t-1}, ..., Δlikes_{t-p},
                      Δcoins_{t-1}, ..., Δcoins_{t-p},
                      Δfavs_{t-1}, ..., Δfavs_{t-p})

    其中：
    - p 为滞后阶数（默认4）
    - f 可为线性回归（OLS）或非线性回归（Ridge + 多项式特征）

双级实现策略：
    1. sklearn Ridge + PolynomialFeatures — 非线性自回归
    2. NumPy lstsq — 线性最小二乘回退

适用场景：
    - 有丰富互动数据的视频（点赞/投币/收藏均有记录）
    - 互动与播放量有强相关性的场景
    - 需要利用多维度数据提高预测精度的场景

参考:
    Billings & Tsang (1989) "Spectral analysis for non-linear systems"
"""

import logging
import numpy as np
from typing import Dict, Any
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# ── 可选依赖检测 ──────────────────────────────────
_HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import PolynomialFeatures

    _HAS_SKLEARN = True
except ImportError:
    pass


class NarxSimpleAlgorithm(BaseAlgorithm):
    """NARX 带外生输入自回归

    将点赞、投币、收藏等互动数据作为外生输入，
    与播放量历史一起构建非线性自回归模型。

    核心思想:
        互动行为（点赞/投币/收藏）是播放量增长的"先行指标"，
        通过建模互动变化 → 播放量变化的关系来预测未来。

    属性:
        name (str): 算法显示名称 "NARX外生自回归"
        algorithm_id (str): 算法唯一标识 "narx_simple"
        description (str): 算法描述
        category (str): 算法分类 "时间序列"
        default_weight (float): 集成预测中的默认权重 1.1
    """

    name = "NARX外生自回归"
    algorithm_id = "narx_simple"
    description = "带外生输入(点赞/投币/分享)的非线性自回归"
    category = "时间序列"
    default_weight = 1.1

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行NARX预测（两级级联回退）

        按优先级尝试：
        1. sklearn Ridge + PolynomialFeatures 非线性自回归（数据≥10点）
        2. NumPy lstsq 线性自回归回退

        参数:
            video_data (Dict[str, Any]): 视频数据字典
            threshold (int): 目标播放量阈值，默认 100000

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时回退
        if len(history) < 6 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold, method="narx_sklearn")

        # 优先使用 sklearn Ridge 做非线性自回归（带点赞/投币/收藏外生输入）
        if _HAS_SKLEARN and len(history) >= 10:
            try:
                result = self._sklearn_predict(video_data, threshold)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug("NARX sklearn 失败，回退 numpy: %s", e)

        return self._numpy_predict(video_data, threshold)

    def _sklearn_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """使用 sklearn Ridge + 多项式特征做 NARX 非线性自回归预测

        构建特征矩阵:
            [Δviews_{t-1}, Δlikes_{t-1}, Δcoins_{t-1}, Δfavs_{t-1},
             Δviews_{t-2}, Δlikes_{t-2}, Δcoins_{t-2}, Δfavs_{t-2}, ...]
         共 p × 4 个特征（p=4 时共16个特征）

        然后通过 PolynomialFeatures(degree=2) 生成交叉项和平方项，
        用 Ridge 岭回归（L2正则化）防止过拟合。

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult 或 None
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 提取原始序列
        views = np.array([h.get("view_count", 0) for h in history], dtype=np.float64)
        likes = np.array([h.get("like_count", 0) for h in history], dtype=np.float64)
        coins = np.array([h.get("coin_count", 0) for h in history], dtype=np.float64)
        favs = np.array([h.get("favorite_count", 0) for h in history], dtype=np.float64)

        # 计算各指标的差分序列（一阶差分 = 变化量）
        v_diff = np.diff(views)
        l_diff = np.diff(likes)
        c_diff = np.diff(coins)
        f_diff = np.diff(favs)

        # 滞后阶数 p=4，构造自回归+外生特征矩阵
        p = 4
        X, y = [], []
        for i in range(p, len(v_diff)):
            feat = []
            for j in range(p):
                # 每个滞后阶数包含4个变量：播放量、点赞、投币、收藏的差分
                feat.extend([v_diff[i - j - 1], l_diff[i - j - 1], c_diff[i - j - 1], f_diff[i - j - 1]])
            X.append(feat)
            y.append(v_diff[i])  # 目标：当前播放量差分

        if len(X) < 5:
            return None

        X, y = np.array(X), np.array(y)
        # 二次多项式特征扩展（捕获非线性交叉项如 views×likes）
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_poly = poly.fit_transform(X)

        # Ridge 岭回归（L2 正则化 α=1.0 防止过拟合）
        model = Ridge(alpha=1.0)
        model.fit(X_poly, y)

        # 构造最后一个特征向量用于预测下一步
        last_feat = []
        for j in range(p):
            idx = len(v_diff) - 1 - j
            if idx >= 0:
                last_feat.extend([v_diff[idx], l_diff[idx], c_diff[idx], f_diff[idx]])
            else:
                last_feat.extend([0, 0, 0, 0])  # 不足时补零
        last_poly = poly.transform(np.array([last_feat]))
        pred_diff = float(model.predict(last_poly)[0])  # 预测的下一步差分
        predicted_velocity = max(0, pred_diff / 3600)  # 转换为小时速度

        if predicted_velocity < 1:
            predicted_velocity = velocity

        remaining = threshold - current_views
        if remaining <= 0:
            predicted_hours, confidence = 0, 1.0
        else:
            predicted_hours = remaining / predicted_velocity if predicted_velocity > 0 else float("inf")
            # 计算残差和变异系数（RMSE / 均值）作为模型质量评估
            residuals = y - model.predict(X_poly)
            rmse = np.sqrt(np.mean(residuals**2))
            cv = float(rmse / max(np.mean(np.abs(y)), 1))  # 变异系数
            confidence = max(0.1, min(0.85, 0.6 - cv))  # 变异系数越小置信度越高

        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "narx_sklearn", "lag": p, "rmse": float(rmse)},
            timestamp=datetime.now(),
        )

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int) -> PredictionResult:
        """NumPy 简化版 NARX 预测（线性最小二乘回退）

        使用 np.linalg.lstsq 进行线性最小二乘回归，
        滞后阶数 p=3，4个外生变量共12个特征+截距项。

        参数:
            video_data: 视频数据字典
            threshold: 目标阈值

        返回:
            PredictionResult: 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        try:
            # 提取序列（使用简化的字段名）
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            likes = np.array([h.get("like", 0) for h in history], dtype=np.float64)
            coins = np.array([h.get("coin", 0) for h in history], dtype=np.float64)
            favorites = np.array([h.get("favorite", 0) for h in history], dtype=np.float64)

            # 一阶差分
            v_diff = np.diff(views)
            l_diff = np.diff(likes)
            c_diff = np.diff(coins)
            f_diff = np.diff(favorites)

            # 滞后阶数 p=3
            p = 3
            X, y = [], []
            for i in range(p, len(v_diff)):
                feat = []
                for j in range(p):
                    feat.extend([v_diff[i - j], l_diff[i - j], c_diff[i - j], f_diff[i - j]])
                X.append(feat)
                y.append(v_diff[i])

            if len(X) < 3:
                return self._fallback(velocity, current_views, threshold, method="narx_sklearn")

            X, y = np.array(X), np.array(y)
            # 添加截距项（全1列）
            X = np.column_stack([np.ones(len(X)), X])

            # 最小二乘求解
            try:
                theta = np.linalg.lstsq(X, y, rcond=None)[0]
            except np.linalg.LinAlgError:
                return self._fallback(velocity, current_views, threshold, method="narx_sklearn")

            # 构造最后一个特征向量
            last_feat = []
            for j in range(p):
                idx = len(v_diff) - 1 - j
                if idx >= 0:
                    last_feat.extend([v_diff[idx], l_diff[idx], c_diff[idx], f_diff[idx]])
                else:
                    last_feat.extend([0, 0, 0, 0])

            # 预测下一步差分
            pred_diff = np.dot(np.array([1] + last_feat), theta)
            predicted_velocity = max(0, pred_diff / 3600)

            if predicted_velocity < 1:
                predicted_velocity = velocity

            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                # 计算残差和变异系数
                residuals = y - X @ theta
                rmse = np.sqrt(np.mean(residuals**2)) if len(residuals) > 0 else 1
                cv = rmse / max(np.mean(y), 1)
                confidence = max(0.1, min(0.85, 0.6 - cv))

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "narx", "lag": p, "rmse": float(rmse) if "rmse" in dir() else 0},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold, method="narx_sklearn")
