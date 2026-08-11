"""
ElasticNet 回归 — Elastic Net Regression
=========================================

结合 L1 (Lasso) 和 L2 (Ridge) 正则化的线性回归预测算法。

核心原理：
  1. 损失函数 = MSE + α·(l1_ratio·|w|₁ + (1-l1_ratio)·|w|₂²)
  2. L1 项产生稀疏解（自动特征选择），L2 项稳定解（处理共线性）
  3. 使用坐标下降法（Coordinate Descent）优化：
     - 逐特征更新，固定其他系数对当前系数求软阈值解
     - 软阈值函数: S(x, λ) = sign(x)·max(|x|-λ, 0)
  4. 适合特征间存在相关性的场景（如播放量、点赞、投币等互动指标）

适用场景：历史数据 >= 8 条，特征维度较高且存在共线性
"""

import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
import logging

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)


class ElasticNetRegressionAlgorithm(BaseAlgorithm):
    """
    Elastic Net 回归预测算法

    结合 L1 (Lasso) 和 L2 (Ridge) 正则化，兼具特征选择和系数收缩能力。
    使用坐标下降法优化，适合特征间存在相关性的场景。

    属性:
        alpha (float): 正则化强度，默认 0.01
        l1_ratio (float): L1 正则化比例（0=纯L2, 1=纯L1），默认 0.5
        max_iter (int): 坐标下降最大迭代次数，默认 1000
        tol (float): 收敛容差，默认 1e-4
        coef_ (np.ndarray): 拟合后的特征系数
        intercept_ (float): 拟合后的截距项
    """

    name = "ElasticNet回归"
    description = "L1+L2正则化线性回归，坐标下降优化"
    category = "统计模型"

    def __init__(self):
        """初始化 ElasticNet 模型，设置默认超参数"""
        super().__init__()
        self.alpha = 0.01  # 正则化强度
        self.l1_ratio = 0.5  # L1/L2 混合比例 (0.5 = 等量混合)
        self.max_iter = 1000  # 最大迭代次数
        self.tol = 1e-4  # 收敛容差
        self.coef_ = None  # 特征系数
        self.intercept_ = 0.0  # 截距

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
          2. 构建特征矩阵和标签向量
          3. 用坐标下降法拟合 ElasticNet
          4. 用拟合后的系数预测当前增量
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
            # 构建特征和标签
            X, y = self._prepare_features(history_data)
            if len(X) < 6:
                return None

            # 拟合 ElasticNet
            self._fit(X, y)

            # 已达目标，直接返回
            if current_views >= target_views:
                return (0, 1.0)

            # 用最新特征预测当前增量
            last_features = X[-1]
            predicted_growth = np.dot(self.coef_, last_features) + self.intercept_

            # 增量非正时，回退到历史平均增量
            if predicted_growth <= 0:
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            # 预测时间不合理
            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)  # 转换为秒
            confidence = self._calculate_confidence(X, y)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"ElasticNet预测失败: {e}")
            return None

    def _prepare_features(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备特征矩阵和标签向量

        特征 (9 维):
          [1, view/10000, like/1000, coin/100, share/100,
           reply/100, follower/10000, hour/24, day_week/7]
          包含偏置项、互动指标和两维时间特征。

        标签:
          下一条记录的 view 减去当前 view（单期增量）

        所有特征和标签均做标准化（Z-score 归一化）。

        参数:
            history_data (List[Dict]): 历史数据列表

        返回:
            Tuple[np.ndarray, np.ndarray]: (标准化特征矩阵 X, 标准化标签 y)
        """
        X, y = [], []
        for i in range(len(history_data) - 1):
            cur = history_data[i]
            nxt = history_data[i + 1]
            # 时间特征：小时和星期几，归一化到 [0,1]
            ts = cur.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(str(ts)[:19].replace("T", " "))
                hour = dt.hour / 24.0  # 小时 / 24 → [0,1]
                day_week = dt.weekday() / 7.0  # 星期几 / 7 → [0,1)
            except Exception:
                hour, day_week = 0.5, 0.5  # 解析失败使用中间值

            features = [
                1.0,  # 偏置项
                cur.get("view", 0) / 10000,  # 播放量（万级归一化）
                cur.get("like", 0) / 1000,  # 点赞数（千级归一化）
                cur.get("coin", 0) / 100,  # 投币数（百级归一化）
                cur.get("share", 0) / 100,  # 分享数（百级归一化）
                cur.get("reply", 0) / 100,  # 评论数（百级归一化）
                cur.get("follower", 1000) / 10000,  # 粉丝数（万级归一化）
                hour,  # 小时特征
                day_week,  # 星期特征
            ]
            growth = nxt.get("view", 0) - cur.get("view", 0)
            X.append(features)
            y.append(growth)

        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)

        # Z-score 标准化（保存均值和标准差以供反标准化）
        self._X_mean = np.mean(X, axis=0)
        self._X_std = np.std(X, axis=0) + 1e-8  # +1e-8 防止除零
        X = (X - self._X_mean) / self._X_std

        # 对 y 也做标准化
        self._y_mean = np.mean(y)
        self._y_std = np.std(y) + 1e-8
        y = (y - self._y_mean) / self._y_std

        return X, y

    def _soft_threshold(self, x: float, thresh: float) -> float:
        """
        软阈值函数 (Soft Thresholding)

        S(x, λ) = sign(x) · max(|x| - λ, 0)
        这是 L1 正则化优化中的核心操作，实现 Lasso 系数收缩。

        参数:
            x (float): 输入值（基于偏残差和当前特征的点积）
            thresh (float): 阈值 (λ = alpha × l1_ratio)

        返回:
            float: 软阈值处理后的值
        """
        if x > thresh:
            return x - thresh
        elif x < -thresh:
            return x + thresh
        return 0.0

    def _fit(self, X: np.ndarray, y: np.ndarray):
        """
        使用坐标下降法拟合 ElasticNet

        算法流程:
          1. 初始化所有系数为零
          2. 外层循环迭代 max_iter 次
          3. 内层循环逐特征更新（坐标下降）
          4. 对每个特征 j:
             a. 计算偏残差（移除该特征的当前贡献）
             b. 计算 rho = <X_j, residuals> / n
             c. ElasticNet 更新: coef[j] = S(rho, l1_penalty) / (1 + l2_penalty)
             d. 更新残差
          5. 检查系数变化是否 < tol，满足则提前终止
          6. 将标准化空间中的系数反标准化到原始空间

        参数:
            X (np.ndarray): 标准化特征矩阵 (n_samples, n_features)
            y (np.ndarray): 标准化标签向量 (n_samples,)
        """
        n_samples, n_features = X.shape
        # 初始化系数全零
        self.coef_ = np.zeros(n_features)
        self.intercept_ = 0.0

        # 计算正则化项
        l1_penalty = self.alpha * self.l1_ratio  # L1 惩罚
        l2_penalty = self.alpha * (1 - self.l1_ratio)  # L2 惩罚

        residuals = y.copy()  # 初始残差 = y（去除截距和所有特征贡献前）

        for _ in range(self.max_iter):
            max_change = 0.0  # 记录本轮最大系数变化

            # 更新截距：截距 = mean(residuals + 旧截距)
            old_intercept = self.intercept_
            self.intercept_ = np.mean(residuals + self.intercept_)
            residuals += old_intercept - self.intercept_  # 更新残差以反映新截距
            max_change = max(max_change, abs(old_intercept - self.intercept_))

            # 逐特征更新（坐标下降的核心）
            for j in range(n_features):
                old_coef = self.coef_[j]
                X_j = X[:, j]  # 第 j 个特征向量

                # 计算偏残差：移除第 j 个特征的当前贡献
                residuals += X_j * old_coef

                # rho = <X_j, residuals> / n：偏残差与特征的内积（梯度方向）
                rho = np.dot(X_j, residuals) / n_samples

                # ElasticNet 更新公式：
                # coef[j] = S(rho, l1_penalty) / (1 + l2_penalty)
                # 若 l2_penalty=0，退化为纯 Lasso
                if l2_penalty > 0:
                    self.coef_[j] = self._soft_threshold(rho, l1_penalty) / (1 + l2_penalty)
                else:
                    self.coef_[j] = self._soft_threshold(rho, l1_penalty)

                # 更新残差以反映新系数
                residuals -= X_j * self.coef_[j]
                max_change = max(max_change, abs(old_coef - self.coef_[j]))

            # 收敛检查：所有系数变化均小于 tol
            if max_change < self.tol:
                break

        # 反标准化：将标准化空间中的系数还原到原始尺度
        self.coef_ = self.coef_ * self._y_std / self._X_std
        self.intercept_ = self._y_mean - np.dot(self._X_mean, self.coef_)

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """
        计算预测置信度

        基于样本数量和拟合质量（MAPE 倒数）综合评估。

        参数:
            X (np.ndarray): 特征矩阵（原始尺度）
            y (np.ndarray): 标签向量（原始尺度）

        返回:
            float: 置信度，范围 [0, 0.9]
        """
        n = len(X)
        # 基础置信度随样本数增加
        base_conf = min(0.85, 0.3 + n * 0.02)
        if n >= 5:
            # 用拟合后的系数计算预测值，评估 MAPE
            predictions = X @ self.coef_ + self.intercept_
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)  # 拟合质量 = 1 - MAPE
            # 综合基础置信度和拟合质量
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        return min(0.9, base_conf)
