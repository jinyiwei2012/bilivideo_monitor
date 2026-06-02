"""
分位数回归预测 — Quantile Regression
=====================================

通过多个分位点估计完整的预测分布，提供乐观/中位/悲观多情景预测。

核心原理：
  1. 普通最小二乘估计的是条件均值 E[Y|X]，分位数回归估计条件分位数 Q_τ(Y|X)
  2. 分位数损失函数 (check loss / pinball loss):
     ρ_τ(r) = max(τ·r, (τ-1)·r) = r·(τ - 1(r<0))
     即低估的惩罚为 τ，高估的惩罚为 τ-1
  3. 对 τ=0.25（悲观）、τ=0.5（中位数/最稳健）、τ=0.75（乐观）分别拟合
  4. 中位数预测提供点估计，乐观-悲观间距衡量不确定性

参考: Koenker & Hallock (2001), "Quantile Regression"

适用场景：历史数据 >= 5 条，希望获得情景分析（最好/最坏/最可能情况）
"""

import math
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class QuantileRegressionAlgorithm(BaseAlgorithm):
    """
    分位数回归预测算法

    相比普通最小二乘只预测均值，分位数回归能估计完整条件分布。
    对于播放量预测，可同时给出：
      - τ=0.5: 中位数预测（最稳健）
      - τ=0.25: 悲观情景
      - τ=0.75: 乐观情景

    属性:
        tau (float): 默认目标分位数，默认 0.5 (中位数)
        learning_rate (float): 梯度下降学习率，默认 0.01
        max_iter (int): 最大迭代次数，默认 200
        default_weight (float): 默认集成权重 1.15
    """

    name = "分位数回归"
    algorithm_id = "quantile_regression"
    description = "多分位点预测，提供乐观/中位/悲观情景"
    category = "统计模型"
    default_weight = 1.15

    def __init__(self):
        """初始化分位数回归模型"""
        super().__init__()
        self.tau = 0.5  # 默认使用中位数
        self.learning_rate = 0.01  # 初始学习率（会指数衰减）
        self.max_iter = 200  # 最大迭代次数

    def _quantile_loss(self, y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> float:
        """
        分位数损失函数 (Check Loss / Pinball Loss)

        ρ_τ(y, ŷ) = max(τ·(y-ŷ), (τ-1)·(y-ŷ))
        等价形式: Σᵢ (y-ŷ)·(τ - 1(y<ŷ))

        直觉:
          低估 (y>ŷ): 正残差，损失 = τ × 残差 → τ 越大，越惩罚低估
          高估 (y<ŷ): 负残差，损失 = (τ-1) × 残差 → τ 越小，越惩罚高估

        参数:
            y_true (np.ndarray): 真实值
            y_pred (np.ndarray): 预测值
            tau (float): 目标分位数

        返回:
            float: 平均分位数损失
        """
        diff = y_true - y_pred
        # 使用 np.where 高效计算分段损失
        loss = np.where(diff > 0, tau * diff, (tau - 1) * diff)
        return float(np.mean(loss))

    def _fit_quantile(self, X: np.ndarray, y: np.ndarray, tau: float) -> Tuple[np.ndarray, float]:
        """
        使用梯度下降拟合分位数回归

        梯度（关于每个参数）:
          ∂ρ_τ/∂w_j = -Σᵢ X_{ij} · (τ - 1(y<ŷ)) / n
          即对于每个样本 i:
            若 y > ŷ: 梯度的 j 分量贡献 -X_{ij} · τ
            若 y < ŷ: 梯度的 j 分量贡献 -X_{ij} · (τ-1)

        学习率每次迭代后衰减 1%（lr *= 0.99）

        参数:
            X (np.ndarray): 特征矩阵
            y (np.ndarray): 标签向量
            tau (float): 目标分位数

        返回:
            Tuple[np.ndarray, float]: (特征系数, 截距)
        """
        n, p = X.shape
        coef = np.zeros(p)  # 零初始化
        intercept = float(np.median(y))  # 中位数作为截距初值

        for _ in range(self.max_iter):
            # 当前预测值
            pred = X @ coef + intercept
            diff = y - pred  # 残差

            # 分位数梯度计算
            grad_coef = np.zeros(p)
            grad_intercept = 0.0
            for i in range(n):
                if diff[i] > 0:  # 正残差 → 权重 = τ
                    weight = tau
                elif diff[i] < 0:  # 负残差 → 权重 = τ - 1
                    weight = tau - 1
                else:  # 残差为零 → 无梯度
                    weight = 0
                # 梯度累积
                grad_coef += weight * X[i] / n
                grad_intercept += weight / n

            # 梯度上升（注意：我们最小化损失，但 gradient 方向已包含负号）
            coef += self.learning_rate * grad_coef
            intercept += self.learning_rate * grad_intercept

            # 学习率指数衰减
            self.learning_rate *= 0.99

        return coef, intercept

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行分位数回归预测

        流程:
          1. 检查数据是否充足（>= 5 条历史记录）
          2. 提取并排序播放量序列
          3. 构建特征矩阵
          4. 对三个分位数 (0.25, 0.5, 0.75) 分别拟合
          5. 用中位数作为主预测，乐观-悲观间距衡量不确定性
          6. 模拟未来增长路径找到达到阈值的天数

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 包含多分位点信息的预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达阈值
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "quantile"}, threshold)

        # 数据不足
        if len(history) < 5 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "quantile", "notes": "insufficient_data"},
                threshold,
            )

        # 提取并排序播放量序列
        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 5:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "quantile_fallback"},
                threshold,
            )

        try:
            return self._predict_impl(views_sorted, current_views, velocity, remaining, threshold, video_data)
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.0,
                current_views,
                velocity,
                {"error": str(e)},
                threshold,
            )

    def _extract_views(self, history):
        """
        从历史记录中提取并排序播放量序列

        处理多种时间戳格式（float、datetime 对象、字符串），
        按时间升序排列后返回纯播放量数组。

        参数:
            history (List[Dict]): 历史数据列表

        返回:
            np.ndarray 或 None: 排序后的播放量数组，数据不足返回 None
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()  # datetime 对象转浮点
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()  # ISO 字符串
                except Exception:
                    continue  # 解析失败跳过
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 5:
            return None
        # 按时间升序排列
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """
        执行分位数回归核心预测

        对 τ = {0.25: 悲观, 0.50: 中位数, 0.75: 乐观} 分别拟合，
        使用中位数作为主预测，乐观-悲观间距计算稳定性指标。

        特征 (6 维):
          [1, views/10000, delta/100, 7日均值/10000, min(age_hours/168, 1), quality]

        参数:
            views_sorted (np.ndarray): 排序后的播放量数组
            current_views (int): 当前播放量
            velocity (float): 当前速度
            remaining (int): 剩余播放量
            threshold (int): 目标阈值
            video_data (Dict): 视频元数据

        返回:
            PredictionResult
        """
        n = len(views_sorted)

        quality = self.get_quality_score(video_data)
        age_hours = self.get_video_age_hours(video_data)

        # ── 构建特征 ──────────────────────────────
        X_list, y_list = [], []
        for i in range(3, n):  # 从第 3 个点开始（需要上下文）
            features = [
                1.0,  # 偏置项
                views_sorted[i - 1] / 10000,  # 归一化播放量（万级）
                (views_sorted[i - 1] - views_sorted[i - 2]) / 100,  # 近期增量（百级归一化）
                np.mean(views_sorted[max(0, i - 7) : i]) / 10000,  # 7 日移动均值
                min(age_hours / 168.0, 1.0),  # 视频年龄（周，上限 1）
                quality,  # 质量分 [0,1]
            ]
            X_list.append(features)
            y_list.append(views_sorted[i] - views_sorted[i - 1])  # 预测增量

        X = np.array(X_list)
        y = np.array(y_list)

        if len(X) < 3:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "quantile_insufficient"},
                threshold,
            )

        # ── 拟合多个分位数 ────────────────────────
        quantiles = {
            "pessimistic": 0.25,  # 悲观：播放量增长低于预期的 25% 分位
            "median": 0.50,  # 中位数：最可能的值
            "optimistic": 0.75,  # 乐观：播放量增长高于预期的 75% 分位
        }

        results = {}
        for label, tau in quantiles.items():
            coef, intercept = self._fit_quantile(X, y, tau)
            results[label] = {"coef": coef, "intercept": intercept}

        # ── 预测 ─────────────────────────────────
        # 构造最新数据点的特征
        last_X = np.array(
            [
                [
                    1.0,
                    views_sorted[-1] / 10000,  # 最新播放量
                    (views_sorted[-1] - views_sorted[-2]) / 100,  # 最新增量
                    np.mean(views_sorted[-7:]) / 10000 if len(views_sorted) >= 7 else views_sorted[-1] / 10000,  # 7 日均值
                    min(age_hours / 168.0, 1.0),  # 年龄
                    quality,  # 质量
                ]
            ]
        )

        # 三个分位数的日增长预测
        median_pred = float(last_X @ results["median"]["coef"] + results["median"]["intercept"])
        optimistic_pred = float(last_X @ results["optimistic"]["coef"] + results["optimistic"]["intercept"])
        pessimistic_pred = float(last_X @ results["pessimistic"]["coef"] + results["pessimistic"]["intercept"])

        # 使用中位数作为主预测
        daily_growth = max(0, median_pred)

        if daily_growth <= 0:
            daily_growth = max(0, velocity * 24)  # 回退到当前速度

        # 预测区间宽度反映不确定性
        prediction_spread = max(1, optimistic_pred - pessimistic_pred)
        relative_spread = prediction_spread / max(daily_growth, 1)  # 相对区间宽度

        # ── 模拟未来增长路径 ──────────────────
        forecast_days = min(365, max(10, int((threshold - current_views) / max(daily_growth, 1)) + 5))

        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            # 指数衰减因子
            decay = math.exp(-day / 28.0)  # 28 天衰减常数
            growth = daily_growth * (0.6 + 0.4 * (1.0 - decay))  # 衰减后的增量
            pred_views += max(0, growth)
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度综合数据质量、预测稳定性和视频质量
            data_qual = min(1.0, n / 20)
            stability = max(0.0, 1.0 - min(relative_spread * 0.1, 0.5))  # 区间越窄越稳定
            conf = min(0.9, 0.3 + 0.25 * data_qual + 0.2 * stability + 0.1 * quality)
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "quantile",
                "daily_growth_median": round(float(median_pred), 2),
                "daily_growth_optimistic": round(float(optimistic_pred), 2),
                "daily_growth_pessimistic": round(float(pessimistic_pred), 2),
                "prediction_spread": round(float(prediction_spread), 2),  # 乐观-悲观差距
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """
        构造 PredictionResult

        统一的结果构造方法。

        参数:
            predicted_hours (float): 预测小时数
            confidence (float): 置信度
            current_views (int): 当前播放量
            velocity (float): 当前速度
            metadata (Dict): 元数据
            threshold (int): 目标阈值

        返回:
            PredictionResult
        """
        metadata.setdefault("method", "quantile")
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
