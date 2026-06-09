"""
泊松回归预测 — Poisson Regression
===================================

基于计数分布的广义线性模型 (GLM)，适合非负整数的播放增量预测。

核心原理：
  1. 播放量增量为非负整数，用泊松分布或负二项分布建模更合理
  2. 泊松分布：均值=方差（适合常规稳定增长）
  3. 负二项分布：方差>均值（适合过度离散的数据，如病毒式传播）
  4. 使用 GLM 框架：连接函数为 log link，即 E[y] = exp(Xβ)
  5. 参数估计使用 IRLS（迭代重加权最小二乘）带 L2 正则化

特征包括：对数播放量、对数量级增加、视频年龄、质量评分、互动率

适用场景：历史数据 >= 6 条，播放量增长稳定或需要概率化建模
"""

import math
import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult


class PoissonRegressionAlgorithm(BaseAlgorithm):
    """
    泊松回归预测算法

    播放量增量为非负整数，使用泊松分布或负二项分布建模。
    使用广义线性模型 (GLM) 框架，连接函数为 log link。

    属性:
        coef (np.ndarray): 拟合后的特征系数
        intercept (float): 拟合后的截距项
        alpha (float): L2 正则化强度，默认 0.01
        use_negative_binomial (bool): 是否使用负二项分布（待实现）
        default_weight (float): 默认集成权重 1.1
    """

    name = "泊松回归"
    algorithm_id = "poisson_regression"
    description = "基于计数分布的广义线性模型，适合非负整数预测"
    category = "统计模型"
    default_weight = 1.1

    def __init__(self):
        """初始化泊松回归模型"""
        super().__init__()
        self.coef = None  # 拟合后的特征系数
        self.intercept = 0.0  # 截距项
        self.alpha = 0.01  # L2 正则化强度
        self.use_negative_binomial = False  # 是否使用负二项（预留扩展）

    def _fit_poisson(
        self, X: np.ndarray, y: np.ndarray, max_iter: int = 200, tol: float = 1e-6
    ) -> Tuple[np.ndarray, float]:
        """
        IRLS (迭代加权最小二乘) 拟合泊松回归

        GLM 框架:
          连接函数: η = log(μ), μ = exp(η)
          工作变量: z = η + (y - μ) / μ
          权重: w = μ (泊松分布的方差 = 均值)
          更新: β = (XᵀWX + αI)⁻¹XᵀWz

        参数:
            X (np.ndarray): 特征矩阵 (n_samples, n_features)
            y (np.ndarray): 标签向量（非负计数值）
            max_iter (int): 最大迭代次数，默认 200
            tol (float): 收敛容差，默认 1e-6

        返回:
            Tuple[np.ndarray, float]: (特征系数, 截距)
        """
        n, p = X.shape
        # 初始化系数（全零特征系数，截距用 log(mean(y)) 作为合理初值）
        coef = np.zeros(p)
        intercept = math.log(max(np.mean(y), 0.1))

        for _ in range(max_iter):
            # 线性预测值 η = Xβ + intercept
            eta = X @ coef + intercept
            # 连接函数反函数 μ = exp(η)（确保正值）
            mu = np.exp(eta)  # 连接函数反函数
            mu = np.clip(mu, 1e-10, None)  # 防止 log(0)

            # 工作变量 z = η + (y - μ) / μ
            z = eta + (y - mu) / mu

            # 权重 w = μ（泊松分布方差）
            w = mu

            # 加权最小二乘 (带 L2 正则化)
            W = np.diag(w)  # 权重对角矩阵
            X_aug = np.column_stack([np.ones(n), X])  # 加入截距
            penalty = self.alpha * np.eye(p + 1)  # L2 惩罚矩阵
            penalty[0, 0] = 0  # 不惩罚截距项

            try:
                # 正规方程: (XᵀWX + penalty) β = XᵀWz
                beta_new = np.linalg.solve(X_aug.T @ W @ X_aug + penalty, X_aug.T @ W @ z)
            except np.linalg.LinAlgError:
                break  # 矩阵奇异，停止迭代

            # 分离截距和特征系数
            intercept_new = beta_new[0]
            coef_new = beta_new[1:]

            # 收敛检查
            if np.max(np.abs(np.concatenate([[intercept_new - intercept], coef_new - coef]))) < tol:
                coef = coef_new
                intercept = intercept_new
                break

            coef = coef_new
            intercept = intercept_new

        return coef, intercept

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行泊松回归预测

        流程:
          1. 检查数据是否充足（>= 6 条历史记录）
          2. 提取并排序播放量序列
          3. 构建特征（对数播放量、对数增量、视频年龄、质量分、互动率）
          4. 用 IRLS 拟合泊松回归
          5. 预测日增量，模拟未来增长路径
          6. 使用 deviance 计算伪 R² 作为拟合质量

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        # 已达阈值
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "poisson"}, threshold)

        # 数据不足
        if len(history) < 6 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "poisson", "notes": "insufficient_data"},
                threshold,
            )

        # 提取并排序播放量序列
        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 6:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "poisson_fallback"},
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
            # 处理多种时间戳格式
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()  # datetime 对象
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()  # ISO 字符串
                except Exception:
                    continue  # 解析失败跳过
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 6:
            return None
        # 按时间升序排列
        order = np.argsort(timestamps)
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """
        执行泊松回归核心预测

        特征构建:
          - 对数播放量: log(max(v, 1)) / 10
          - 对数上期增量: log(max(delta, 1))
          - 视频年龄（月）: min(age_hours/720, 1)
          - 质量评分和互动率（来自 base class 方法）

        预测流程:
          1. 拟合泊松回归得到日增量预测
          2. 模拟未来增长路径（带衰减因子）
          3. 找到达到阈值的天数
          4. 计算 deviance 和伪 R² 评估拟合质量

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

        # 获取视频质量相关特征
        quality = self.get_quality_score(video_data)
        age_hours = self.get_video_age_hours(video_data)
        engagement = self.get_engagement_rate(video_data)

        # ── 构建特征 (预测日增量) ────────────────
        X_list, y_list = [], []
        for i in range(4, n):  # 从第 4 个点开始，确保有足够上下文
            features = [
                1.0,  # 偏置项
                math.log(max(views_sorted[i - 1], 1)) / 10.0,  # 对数播放量（归一化）
                math.log(max(views_sorted[i - 1] - views_sorted[i - 2] + 1, 1)),  # 对数上期增量
                min(age_hours / 720.0, 1.0),  # 视频年龄（月，上限 1）
                quality,  # 质量评分 [0,1]
                engagement,  # 互动率
            ]
            X_list.append(features)
            y_list.append(max(0, int(views_sorted[i] - views_sorted[i - 1])))  # 非负整数增量

        X = np.array(X_list)
        y = np.array(y_list, dtype=float)

        if len(X) < 3:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "poisson_insufficient"},
                threshold,
            )

        # ── 拟合泊松回归 ────────────────────────
        self.coef, self.intercept = self._fit_poisson(X, y)

        # ── 预测当前日增量 ─────────────────────
        last_features = np.array(
            [
                1.0,
                math.log(max(views_sorted[-1], 1)) / 10.0,  # 最新播放量
                math.log(max(views_sorted[-1] - views_sorted[-2] + 1, 1)),  # 最新增量
                min(age_hours / 720.0, 1.0),  # 当前年龄
                quality,  # 质量分
                engagement,  # 互动率
            ]
        )

        # 线性预测 → exp 变换得到正数增量
        eta = float(last_features @ self.coef + self.intercept)
        predicted_daily_increment = max(0, math.exp(eta))

        if predicted_daily_increment <= 0:
            predicted_daily_increment = max(1, velocity * 24)  # 回退到当前速度

        # ── 置信度: 基于 deviance 和伪 R² ──────
        if len(X) >= 5:
            # 泊松 deviance = 2Σ[y·log(y/μ̂) - (y - μ̂)]
            predictions = np.exp(X @ self.coef + self.intercept)
            deviance = 2 * np.sum(y * np.log(np.maximum(y, 1e-10) / np.maximum(predictions, 1e-10)) - (y - predictions))
            # null deviance (仅截距模型)
            null_pred = np.mean(y)
            null_dev = 2 * np.sum(y * np.log(np.maximum(y, 1e-10) / max(null_pred, 1e-10)) - (y - null_pred))
            # 伪 R² = 1 - deviance/null_deviance
            pseudo_r2 = max(0, 1 - deviance / max(null_dev, 1e-10))
        else:
            pseudo_r2 = 0.3  # 默认值

        # ── 模拟未来增长路径 ──────────────────
        forecast_days = min(365, max(10, int((threshold - current_views) / max(predicted_daily_increment, 1)) + 5))

        pred_views = float(current_views)
        target_day = None
        for day in range(1, forecast_days + 1):
            # 添加指数衰减因子模拟自然衰退
            decay = math.exp(-day / 30.0)  # 30 天衰减常数
            increment = predicted_daily_increment * (0.5 + 0.5 * (1.0 - decay))  # 衰减后的增量
            pred_views += increment  # 累加预测播放量
            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 综合置信度：数据质量 + 拟合优度 + 视频质量
            data_qual = min(1.0, n / 20)
            conf = min(0.85, 0.3 + 0.25 * data_qual + 0.25 * pseudo_r2 + 0.1 * quality)
        else:
            predicted_hours = remaining / velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            velocity,
            {
                "method": "poisson",
                "daily_increment": round(float(predicted_daily_increment), 2),
                "pseudo_r2": round(float(pseudo_r2), 3),
                "model_type": "poisson",
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """
        构造 PredictionResult

        统一的结果构造方法，确保 method 字段被正确设置。

        参数:
            predicted_hours (float): 预测到达阈值所需的小时数
            confidence (float): 置信度 [0, 1]
            current_views (int): 当前播放量
            velocity (float): 当前速度
            metadata (Dict): 元数据字典
            threshold (int): 目标阈值

        返回:
            PredictionResult
        """
        metadata.setdefault("method", "poisson")
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
