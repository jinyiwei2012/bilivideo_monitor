"""
多层感知机 (MLP) — 经典前馈神经网络预测器
==========================================

使用两层全连接神经网络进行B站视频播放量增长预测的经典算法。

核心原理:
    1. 输入层：接收多维度特征（播放量、点赞、投币、收藏、分享数 + 时间步）
    2. 隐藏层：使用ReLU激活函数的全连接层进行非线性变换
    3. 输出层：单神经元线性输出，预测下一时间步的播放量增长
    4. 训练：使用均方误差（MSE）反向传播更新权重，每次预测前重新初始化权重以保证线程安全

关键设计：
    - 每次train重新初始化权重：避免多线程竞争导致形状不匹配
    - 使用numpy手动实现前向/反向传播，无需PyTorch即可运行

降级链：torch checkpoint（MLPTorchModel） → numpy手动MLP训练

参考：
    "Multilayer Perceptron" — 经典前馈神经网络架构
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import MLPTorchModel, try_torch_predict

logger = logging.getLogger(__name__)


class MLPPredictorAlgorithm(BaseAlgorithm):
    """多层感知机(MLP)预测器

    使用两层神经网络进行播放量增长预测。
    输入6个特征，经过16维隐藏层（ReLU），输出1维增长量预测。
    每次训练重新初始化权重以保证多线程安全性。
    """

    name = "多层感知机"
    algorithm_id = "mlp_predictor"
    description = "经典前馈神经网络预测（torch checkpoint 优先，否则 numpy 简化）"
    category = "深度学习"

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def __init__(self):
        """初始化MLP预测器

        设置网络结构参数并随机初始化权重矩阵：
        - W1: (6, 16) 输入→隐藏层权重
        - b1: (16,) 隐藏层偏置
        - W2: (16, 1) 隐藏→输出层权重
        - b2: (1,) 输出层偏置
        """
        super().__init__()
        self.input_size = 6        # 输入特征维度
        self.hidden_size = 16      # 隐藏层神经元数
        self.output_size = 1       # 输出维度（单个增长量预测值）

        # 随机初始化权重（小方差防止梯度饱和）
        self.W1 = np.random.randn(self.input_size, self.hidden_size) * 0.1
        self.b1 = np.zeros(self.hidden_size)
        self.W2 = np.random.randn(self.hidden_size, self.output_size) * 0.1
        self.b2 = np.zeros(self.output_size)

    def build_model(self):
        """构建MLP PyTorch模型实例

        Returns:
            MLPTorchModel: 用于训练的新模型实例
        """
        return MLPTorchModel(in_features=getattr(self, '_training_n_features', 5), window=self.training_window, horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口：从 video_data 提取参数, 委托 _predict_inner, 包装为 PredictionResult。"""
        current_views = video_data.get("view_count", 0)
        history_data = self._normalize_history(video_data.get("history_data", []))
        result = self._predict_inner(current_views, threshold, history_data, video_data)
        return self._to_prediction_result(result, current_views, video_data, threshold)

    def _predict_inner(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """预测到达目标播放量所需时间

        优先使用torch checkpoint进行预测，失败则使用numpy训练并预测。

        Args:
            current_views: 当前播放量
            target_views: 目标播放量
            history_data: 历史数据记录列表
            video_info: 视频信息字典

        Returns:
            Optional[Tuple[int, float]]: (预测秒数, 置信度)，失败返回None
        """
        # torch优先（仅当checkpoint存在时）
        torch_result = self._try_torch_predict(current_views, target_views, history_data, video_info)
        if torch_result is not None:
            return torch_result

        # numpy回退：需要足够的历史数据
        if not history_data or len(history_data) < 8:
            return None

        try:
            # 准备训练数据：从历史记录构建特征矩阵X和目标向量y
            X, y = self._prepare_data(history_data)

            if len(X) < 5:
                return None

            # 训练网络（每次重新初始化权重，保证线程安全）
            self._train(X, y)

            if current_views >= target_views:
                return (0, 1.0)  # 已达到目标

            # 使用最后一个时间步的特征预测增长量
            last_features = X[-1].reshape(1, -1)
            predicted_growth = self._forward(last_features)[0][0, 0]

            if predicted_growth <= 0:
                # 预测增长量为非正，回退到历史平均增长
                views = [d["view"] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i - 1] for i in range(1, len(views))]))

            remaining = target_views - current_views
            days_needed = remaining / predicted_growth

            # 异常值检查
            if days_needed < 0 or days_needed > 3650:
                return None

            seconds_needed = int(days_needed * 86400)  # 转换为秒
            confidence = self._calculate_confidence(X, y)

            return (seconds_needed, confidence)

        except Exception as e:
            logger.warning(f"MLP预测失败: {e}")
            return None

    def _prepare_data(self, history_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """准备训练数据：从历史记录中提取特征和标签

        特征（6维）：
            1. 播放量/10000（归一化）
            2. 点赞数/1000
            3. 投币数/100
            4. 分享数/100
            5. 评论数/100
            6. 时间步位置（i/10）

        标签：
            下一天相对于当前的播放量增长

        Args:
            history_data: 历史数据记录列表

        Returns:
            (特征矩阵X, 目标向量y)
        """
        X = []
        y = []

        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]

            features = [
                current.get("view", 0) / 10000,     # 归一化播放量
                current.get("like", 0) / 1000,       # 归一化点赞
                current.get("coin", 0) / 100,        # 归一化投币
                current.get("share", 0) / 100,       # 归一化分享
                current.get("reply", 0) / 100,       # 归一化评论
                i / 10,                              # 时间步（归一化位置）
            ]

            # 下一时刻相对当前的播放量增长
            growth = next_data.get("view", 0) - current.get("view", 0)

            X.append(features)
            y.append(growth)

        return np.array(X), np.array(y).reshape(-1, 1)

    def _relu(self, x: np.ndarray) -> np.ndarray:
        """ReLU激活函数

        Args:
            x: 输入数组

        Returns:
            np.maximum(0, x): 所有负值置零
        """
        return np.maximum(0, x)

    def _forward(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """前向传播：输入 → 隐藏层(ReLU) → 输出层

        Args:
            X: 输入特征矩阵 [N, 6]

        Returns:
            (输出预测值 [N, 1], 隐藏层加权输入z1, 隐藏层激活a1)
        """
        z1 = X @ self.W1 + self.b1    # 隐藏层加权输入
        a1 = self._relu(z1)           # ReLU激活
        z2 = a1 @ self.W2 + self.b2  # 输出层

        return z2, z1, a1

    def _train(self, X: np.ndarray, y: np.ndarray, epochs: int = 200, lr: float = 0.001):
        """训练网络（每次重新初始化权重，保证线程安全）

        使用均方误差（MSE）损失 + ReLU激活函数进行梯度下降训练。

        关键设计：每次train都重新初始化权重，避免多线程环境下
        不同视频数据维度不一致导致的形状不匹配错误。

        Args:
            X: 特征矩阵 [N, 6]
            y: 目标向量 [N, 1]
            epochs: 训练轮数，默认200
            lr: 学习率，默认0.001
        """
        n_samples = len(X)

        # 重新初始化权重，避免多线程竞争导致形状不匹配
        self.W1 = np.random.randn(self.input_size, self.hidden_size) * 0.1
        self.b1 = np.zeros(self.hidden_size)
        self.W2 = np.random.randn(self.hidden_size, self.output_size) * 0.1
        self.b2 = np.zeros(self.output_size)

        for _ in range(epochs):
            # 前向传播（使用局部变量，不依赖实例状态）
            output, z1, a1 = self._forward(X)

            # 计算损失和梯度（MSE损失的梯度等同于 (output - y)）
            error = output - y

            # 输出层反向传播
            dW2 = a1.T @ error / n_samples
            db2 = np.mean(error, axis=0)

            # 隐藏层反向传播
            da1 = error @ self.W2.T
            dz1 = da1 * (z1 > 0).astype(float)  # ReLU导数：z1>0时为1，否则0
            dW1 = X.T @ dz1 / n_samples
            db1 = np.mean(dz1, axis=0)

            # 梯度下降更新权重
            self.W2 -= lr * dW2
            self.b2 -= lr * db2
            self.W1 -= lr * dW1
            self.b1 -= lr * db1

    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算预测置信度

        基于两个因素：
        1. 基础置信度：数据量越多，置信度越高
        2. 拟合质量：MAPE（平均绝对百分比误差）越小，置信度越高

        Args:
            X: 特征矩阵
            y: 真实目标值

        Returns:
            float: 置信度 [0, 0.9]
        """
        n = len(X)

        # 基础置信度：随样本数增加
        base_conf = min(0.85, 0.3 + n * 0.025)

        # 计算拟合误差：MAPE
        if n >= 5:
            predictions = self._forward(X)[0]
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - min(1, mape))
            base_conf = 0.5 * base_conf + 0.5 * fit_quality

        return min(0.9, base_conf)

    def _try_torch_predict(
        self, current_views: int, target_views: int, history_data: List[Dict[str, Any]], video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """Torch checkpoint预测路径：加载模型、推理、并转换结果

        任何失败都返回None让上游降级到numpy路径。

        Args:
            current_views: 当前播放量
            target_views: 目标播放量
            history_data: 历史数据
            video_info: 视频信息

        Returns:
            Optional[Tuple[int, float]]: (预测秒数, 置信度) 或 None
        """
        if not hasattr(self, "_ckpt"):
            from algorithms.training.checkpoint_manager import CheckpointManager

            self._ckpt = CheckpointManager(self.algorithm_id)
        try:
            video_data = self._wrap_video_data(current_views, history_data, video_info)
            result = try_torch_predict(
                self,
                video_data,
                target_views,
                MLPTorchModel,
                lambda _v, _t: None,  # numpy回退返回None
                window=self.training_window,
                horizon=self.training_horizon,
                model_kwargs={"in_features": getattr(self, '_training_n_features', 5), "window": self.training_window, "horizon": self.training_horizon},
            )
            if result is None or not hasattr(result, "predicted_hours"):
                return None
            if result.predicted_hours == float("inf") or result.predicted_hours < 0:
                return None
            seconds = int(result.predicted_hours * 3600)  # 小时→秒
            return (seconds, result.confidence)
        except Exception as e:
            logger.debug("[mlp_predictor] torch path 异常: %s", e)
            return None

    @staticmethod
    def _wrap_video_data(current_views, history_data, video_info):
        """把full_params输入转换为BaseAlgorithm风格的video_data字典

        对history_data中的字段名进行转换和补全，确保与基础特征列表一致。

        Args:
            current_views: 当前播放量
            history_data: 原始历史数据（字段名可能是view而不是view_count）
            video_info: 视频信息

        Returns:
            Dict: 标准化的video_data字典
        """
        from datetime import datetime

        wrapped_history = []
        for d in history_data:
            ts = d.get("timestamp", 0)
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp()
                except Exception:
                    ts = 0
            wrapped_history.append(
                {
                    "view_count": d.get("view", d.get("view_count", 0)),
                    "like_count": d.get("like", d.get("like_count", 0)),
                    "coin_count": d.get("coin", d.get("coin_count", 0)),
                    "favorite_count": d.get("favorite", d.get("favorite_count", 0)),
                    "share_count": d.get("share", d.get("share_count", 0)),
                    "timestamp": ts,
                }
            )
        return {
            "view_count": current_views,
            "history_data": wrapped_history,
            "timestamp": datetime.now(),
            "bvid": video_info.get("bvid", ""),
        }
