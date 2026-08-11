"""
Huber 鲁棒回归 — Huber Robust Regression
==========================================

结合 MSE 和 MAE 的鲁棒线性回归，对异常值不敏感。

核心原理：
  1. Huber 损失函数：当 |r| <= ε 时用平方损失（MSE: r²），当 |r| > ε 时用线性损失（MAE: |r|×2ε - ε²）
  2. 平方损失的梯度为 r（小残差高效估计），线性损失的梯度为 ε·sign(r)（大残差鲁棒）
  3. 使用 IRLS（迭代重加权最小二乘）求解：
     - 初始 OLS 估计
     - 计算残差，标准化后计算 Huber 权重
     - 用加权最小二乘更新参数
     - 重复直到收敛

适用场景：历史数据 >= 8 条，存在离群值或不规则播放量突增的数据
"""

import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class HuberRegressionAlgorithm(BaseAlgorithm):
    """
    Huber 鲁棒回归预测算法

    使用 Huber 损失函数（MSE + MAE 混合）的线性回归。
    当残差小于 epsilon 时使用平方损失（高效），
    大于 epsilon 时使用绝对损失（鲁棒）。

    对 B 站播放量数据中的突发高峰（如平台推荐、热搜）有良好的容忍性。

    属性:
        epsilon (float): Huber 损失的分界点，默认 1.35
        max_iter (int): IRLS 最大迭代次数，默认 100
        tol (float): 收敛容差，默认 1e-4
    """

    name = "Huber回归"
    description = "Huber鲁棒回归，对异常值不敏感"
    category = "统计模型"

    def __init__(self):
        """初始化 Huber 回归模型"""
        super().__init__()
        self.epsilon = 1.35  # 损失函数拐点（按 Huber 标准）
        self.max_iter = 100  # IRLS 最大迭代次数
        self.tol = 1e-4  # 收敛容差

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        result = self._predict_inner(current_views, threshold, history_data, video_data)
        return self._to_prediction_result(result, current_views, video_data, threshold)

    def _predict_inner(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需的时间（秒）

        流程:
          1. 检查历史数据是否充足（>=8 条）
          2. 构建标准化特征矩阵
          3. 用 IRLS 拟合 Huber 回归
          4. 用拟合系数预测当前增量
          5. 计算到达目标所需的天数和置信度

        参数:
            current_views (int): 当前播放量
            target_views (int): 目标播放量
            history_data (List[Dict]): 历史数据列表
            video_info (Dict): 视频元信息

        返回:
            Optional[Tuple[int, float]]: (预测秒数, 置信度)，数据不足返回 None
        """
        if not history_data or len(history_data) < 8:
            return None

        try:
            # 构建标准化特征并保留最后一个样本
            X, y, X_last = self._prepare_features(history_data)
            if len(X) < 6:
                return None

            # IRLS 拟合 Huber 回归
            coef, intercept = self._fit_huber(X, y)

            if current_views >= target_views:
                return (0, 1.0)

            # 用最新特征预测当前增量
            predicted_growth = np.dot(coef, X_last) + intercept

            # 预测增量为负时的回退策略
            if predicted_growth <= 0:
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y, coef, intercept)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"Huber回归预测失败: {e}")
            return None

    def _prepare_features(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        准备特征矩阵、标签向量和最新样本特征

        特征 (8 维):
          [view/10000, like/1000, coin/100, share/100,
           reply/100, follower/10000, hour/24, day_week/7]
          无偏置项（最终在 IRLS 中通过 X_aug 加入）

        所有特征和标签均做 Z-score 标准化。

        参数:
            history_data (List[Dict]): 历史数据列表

        返回:
            Tuple[np.ndarray, np.ndarray, np.ndarray]:
                (标准化特征矩阵, 标准化标签向量, 最后一个样本的标准化特征)
        """
        X, y = [], []
        for i in range(len(history_data) - 1):
            cur = history_data[i]
            nxt = history_data[i + 1]
            # 时间特征：提取小时和星期几
            ts = cur.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(str(ts)[:19].replace("T", " "))
                hour = dt.hour / 24.0
                day_week = dt.weekday() / 7.0
            except Exception:
                hour, day_week = 0.5, 0.5

            features = [
                cur.get("view", 0) / 10000,  # 播放量归一化
                cur.get("like", 0) / 1000,  # 点赞归一化
                cur.get("coin", 0) / 100,  # 投币归一化
                cur.get("share", 0) / 100,  # 分享归一化
                cur.get("reply", 0) / 100,  # 评论归一化
                cur.get("follower", 1000) / 10000,  # 粉丝数归一化
                hour,  # 小时特征
                day_week,  # 星期特征
            ]
            growth = nxt.get("view", 0) - cur.get("view", 0)
            X.append(features)
            y.append(growth)

        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)

        # Z-score 标准化（保存参数以备反标准化）
        self._X_mean = np.mean(X, axis=0)
        self._X_std = np.std(X, axis=0) + 1e-8
        X_norm = (X - self._X_mean) / self._X_std

        y_mean = np.mean(y)
        y_std = np.std(y) + 1e-8
        y_norm = (y - y_mean) / y_std
        self._y_mean = y_mean
        self._y_std = y_std

        # 最后一个样本的特征（用于预测未来）
        X_last = X_norm[-1]

        return X_norm, y_norm, X_last

    def _huber_loss_gradient(self, r: np.ndarray) -> np.ndarray:
        """
        Huber 损失梯度

        ψ(r) = r·1(|r|<=ε) + ε·sign(r)·1(|r|>ε)
        即在 |r|<=ε 时梯度为 r（线性），在 |r|>ε 时梯度为 ε·sign(r)（截断）

        参数:
            r (np.ndarray): 残差向量

        返回:
            np.ndarray: Huber 损失的梯度
        """
        return np.where(np.abs(r) <= self.epsilon, r, self.epsilon * np.sign(r))

    def _huber_weights(self, r: np.ndarray) -> np.ndarray:
        """
        计算 IRLS 中的 Huber 权重

        权重 = 1  (|r| <= ε)
        权重 = ε/|r|  (|r| > ε)
        即大残差被降权，小残差保持等权。

        参数:
            r (np.ndarray): 标准化残差向量

        返回:
            np.ndarray: 权重向量
        """
        abs_r = np.abs(r)
        return np.where(abs_r <= self.epsilon, 1.0, self.epsilon / np.maximum(abs_r, 1e-12))

    def _fit_huber(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        IRLS (Iteratively Reweighted Least Squares) 拟合 Huber 回归

        算法流程:
          1. 初始 OLS 估计作为初值
          2. 在每次迭代中:
             a. 用当前参数计算预测和残差
             b. 用 MAD 估计残差尺度（鲁棒尺度估计）
             c. 标准化残差 = residual / scale
             d. 计算 Huber 权重
             e. 加权最小二乘更新：β = (XᵀWX)⁻¹XᵀWy
          3. 检查参数变化是否 < tol，满足则收敛

        参数:
            X (np.ndarray): 标准化特征矩阵 (n_samples, n_features)
            y (np.ndarray): 标准化标签向量 (n_samples,)

        返回:
            Tuple[np.ndarray, float]: (特征系数, 截距)
        """
        n_samples, n_features = X.shape

        # 扩展特征矩阵，加入截距列
        X_aug = np.column_stack([np.ones(n_samples), X])

        # Step 1: 初始 OLS 估计
        try:
            beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            beta = np.zeros(n_features + 1)  # 矩阵奇异时零初始化

        for iteration in range(self.max_iter):
            beta_old = beta.copy()

            # Step 2: 计算预测和残差
            pred = X_aug @ beta
            residuals = y - pred
            # 鲁棒尺度估计：MAD / 0.6745 ≈ 残差标准差（在正态假设下）
            scale = np.median(np.abs(residuals)) / 0.6745 + 1e-8
            standardized_res = residuals / scale  # 标准化残差

            # Step 3: 计算 Huber 权重
            w = self._huber_weights(standardized_res)

            # Step 4: 加权最小二乘更新（避免 np.diag 产生 O(n²) 稠密矩阵）
            Xw = X_aug * w[:, np.newaxis]   # 加权特征 (n, f+1)，O(n) 内存
            XtWX = X_aug.T @ Xw              # (f+1, f+1)
            XtWy = Xw.T @ y                  # (f+1,)
            try:
                beta = np.linalg.solve(XtWX, XtWy)
            except np.linalg.LinAlgError:
                break  # 数值问题，使用上一次结果

            # Step 5: 收敛检查
            if np.max(np.abs(beta - beta_old)) < self.tol:
                break

        # 拆分截距和系数
        intercept = beta[0]
        coef = beta[1:]

        return coef, intercept

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray, coef: np.ndarray, intercept: float) -> float:
        """
        计算预测置信度

        基于样本数量和拟合质量（MAPE）综合评估。

        参数:
            X (np.ndarray): 特征矩阵
            y (np.ndarray): 标签向量
            coef (np.ndarray): 拟合系数
            intercept (float): 截距

        返回:
            float: 置信度，范围 [0, 0.9]
        """
        n = len(X)
        # 基础置信度：样本越多越可信
        base_conf = min(0.85, 0.3 + n * 0.02)
        if n >= 5:
            # 计算 MAPE 评估拟合质量
            predictions = X @ coef + intercept
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)
            # 综合基础置信度和拟合质量
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        return min(0.9, base_conf)
