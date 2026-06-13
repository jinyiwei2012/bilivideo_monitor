"""
Mar-BiLSTM — 马尔可夫增强双向LSTM（Markov-augmented BiLSTM）
===========================================================

结合双向LSTM和可学习马尔可夫转移矩阵的高级时序预测模型，用于B站视频播放量趋势分析。

核心原理:
    1. BiLSTM编码：双向LSTM处理短期时间窗口，捕捉前后上下文信息
    2. 状态原型：定义N个可学习"状态原型"（增长/衰减/爆发/稳定/震荡等），每个对应预设的输出速度
    3. 软分配：通过softmax将当前样本分配到各状态原型的概率分布
    4. 马尔可夫演化：使用可学习的N×N转移矩阵进行H步状态演化，预测未来状态分布
    5. 解码输出：将H步后的状态分布乘以各状态输出值，得到预测速度序列

降级链：torch（MarBilstmTorchModel + checkpoint） → numpy（双向EMA + 5状态硬分配）

参考论文：
    Markov-augmented architectures for time series (2024风格)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.training.checkpoint_manager import CheckpointManager, load_best_checkpoint
from algorithms.training.device import get_device

logger = logging.getLogger(__name__)

# 尝试导入PyTorch，标记是否可用
_torch_available = True
try:
    import torch
    import torch.nn as nn
except ImportError:
    _torch_available = False


if _torch_available:

    class MarBilstmTorchModel(nn.Module):
        """Mar-BiLSTM Torch模型

        BiLSTM编码器 + 状态分配器 + 可学习马尔可夫转移矩阵的组合模型。
        输入多维时序特征窗口，输出H步未来的预测序列。

        结构：
            1. 双向LSTM：编码窗口 → 上下文向量
            2. StateProj：将上下文映射到N个状态的softmax分布
            3. Markov转移矩阵：N×N行随机矩阵，模拟状态间转移概率
            4. StateOutputs：每个状态对应的输出速度（z-score空间）
        """

        def __init__(
            self,
            in_features: int = 5,
            hidden: int = 32,
            n_states: int = 5,
            horizon: int = 3,
        ):
            """初始化Mar-BiLSTM Torch模型

            Args:
                in_features: 输入特征维度（播放量+衍生特征）
                hidden: LSTM隐藏层维度
                n_states: 状态原型数量（默认5：衰减/慢速/稳定/增长/爆发）
                horizon: 预测步数
            """
            super().__init__()
            self.n_states = n_states
            self.horizon = horizon
            # 双向LSTM编码器
            self.lstm = nn.LSTM(
                input_size=in_features,
                hidden_size=hidden,
                num_layers=1,
                batch_first=True,
                bidirectional=True,
            )
            # 将LSTM上下文向量映射到N个状态的logits
            self.state_proj = nn.Linear(hidden * 2, n_states)
            # 可学习Markov转移矩阵（row-stochastic通过softmax保证）
            self.markov_logits = nn.Parameter(torch.zeros(n_states, n_states))
            # 状态原型对应的输出速度（z-score空间）
            self.state_outputs = nn.Parameter(torch.linspace(-1.0, 1.5, n_states))

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            """前向传播

            1. BiLSTM编码窗口 → 取最后一步作为上下文
            2. 状态投影 → softmax得到初始状态分布
            3. 多步Markov转移 → 每步与状态输出值点积得到预测速度

            Args:
                x: 输入张量 [B, W, F]（批大小, 窗口长度, 特征维度）

            Returns:
                预测张量 [B, H]（批大小, 预测步数）
            """
            out, _ = self.lstm(x)  # [B, W, 2H]
            ctx = out[:, -1, :]  # 取最后一步的隐藏状态作为上下文
            state_dist = torch.softmax(self.state_proj(ctx), dim=-1)  # [B, N] 初始状态分布
            P = torch.softmax(self.markov_logits, dim=-1)  # 行随机的转移矩阵
            preds = []
            d = state_dist
            for _ in range(self.horizon):
                d = d @ P  # 一步状态转移
                preds.append((d * self.state_outputs.unsqueeze(0)).sum(dim=-1))  # 加权求和
            return torch.stack(preds, dim=1)  # [B, H]


class MarBilstmAlgorithm(BaseAlgorithm):
    """Mar-BiLSTM马尔可夫算法

    BiLSTM + 可学习马尔可夫状态转移的组合预测算法。
    支持checkpoint热加载和模型缓存，torch推理失败时降级到numpy实现。
    """

    name = "Mar-BiLSTM马尔可夫"
    algorithm_id = "mar_bilstm"
    description = "BiLSTM + 可学习马尔可夫状态转移"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def __init__(self):
        """初始化Mar-BiLSTM算法

        设置计算设备、checkpoint管理器、模型缓存和特征列表。
        """
        super().__init__()
        self._device = get_device()                                            # 获取计算设备（CPU/CUDA）
        self._ckpt = CheckpointManager(self.algorithm_id)                      # checkpoint管理器
        self._cached_model = None                                              # 模型缓存（避免重复加载）
        self._features = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]  # 基础特征

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测

        优先使用torch模型，若失败则降级到numpy实现。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = int(video_data.get("view_count", 0))
        if _torch_available:
            try:
                v, conf, meta = self._torch_predict(video_data)
                return self._make_result(current_views, threshold, v, conf, "mar_bilstm_torch", meta)
            except Exception as e:
                logger.warning("[mar_bilstm] torch 失败，降级: %s", e)
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        """Torch推理路径：加载checkpoint模型并执行前向传播

        步骤：
        1. 构建归一化输入特征（含衍生特征）
        2. 从checkpoint_manager加载最优模型权重
        3. 模型前向推理得到z-score空间的预测
        4. 反归一化得到原始速度预测

        Args:
            video_data: 视频数据字典

        Returns:
            (预测速度, 置信度, 元数据字典)

        Raises:
            RuntimeError: 无可用checkpoint或模型加载失败
        """
        # 构建归一化输入特征
        x_arr, vel_mean, vel_std = self._build_input(video_data)
        bvid = video_data.get("bvid", "")
        # 加载最优checkpoint
        state, _ = load_best_checkpoint(self.algorithm_id, bvid=bvid)
        if state is None:
            raise RuntimeError("无可用的 checkpoint — 请先训练")
        # 模型缓存：避免每次预测都重新加载
        if self._cached_model is None or (bvid and not getattr(self, "_cached_bvid", "") == bvid):
            model = MarBilstmTorchModel(
                in_features=getattr(self, '_training_n_features', len(self._features) + 5),
                horizon=self.training_horizon,
            )
            state = {k[len("_orig_mod."):] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}
            model.load_state_dict(state)
            model.to(self._device).eval()     # 送入设备并设为评估模式
            self._cached_model = model
            self._cached_bvid = bvid or ""
        x = torch.from_numpy(x_arr).unsqueeze(0).to(self._device)
        with torch.no_grad():
            y = self._cached_model(x).cpu().numpy().squeeze(0)
        # 反归一化：z-score空间 → 原始速度空间
        predicted = max(0.0, float(y[0]) * vel_std + vel_mean)
        return predicted, 0.74, {"horizon_pred": y.tolist(), "method": "mar_bilstm"}

    def _build_input(self, video_data) -> Tuple[np.ndarray, float, float]:
        """构建模型输入：提取特征、添加衍生特征、z-score归一化

        步骤：
        1. 从history_data提取最近training_window个记录的基础特征
        2. 添加衍生特征（增长率、比例等）
        3. z-score归一化（减均值除标准差）
        4. 单独计算速度序列的均值和标准差用于反归一化

        Args:
            video_data: 视频数据字典

        Returns:
            (归一化特征数组 [window, n_features], 速度均值, 速度标准差)
        """
        from algorithms.models.deep_learning._torch_upgrade import _add_derived_features

        history = video_data.get("history_data", [])
        n = self.training_window
        # 创建零填充的特征数组
        arr = np.zeros((n, len(self._features)), dtype=np.float32)
        # 取最近n个记录（不足则右对齐填充）
        recent = history[-n:] if len(history) >= n else history
        offset = n - len(recent)
        for i, e in enumerate(recent):
            for j, f in enumerate(self._features):
                arr[offset + i, j] = float(e.get(f, 0) or 0)

        # 添加衍生特征（增长率、比值等）
        arr_ext = _add_derived_features(arr)
        # z-score归一化
        mean = arr_ext.mean(axis=0, keepdims=True)
        std = arr_ext.std(axis=0, keepdims=True)
        std = np.where(std < 1e-8, 1.0, std)  # 防止除零
        arr_n = ((arr_ext - mean) / std).astype(np.float32)

        # 反归一化用的速度统计量
        velocities = self._velocity_series(history)
        v_mean = float(np.mean(velocities)) if velocities else 0.0
        v_std = float(np.std(velocities)) if len(velocities) > 1 else 1.0
        if v_std < 1e-8:
            v_std = 1.0
        return arr_n, v_mean, v_std

    def _numpy_predict(self, video_data, current_views, threshold) -> PredictionResult:
        """NumPy回退预测：双向EMA + 5状态硬分配

        模拟BiLSTM的双向特性使用前向+后向指数移动平均，
        根据近期均值与全局均值的比例硬分配到5种状态之一。

        Args:
            video_data: 视频数据字典
            current_views: 当前播放量
            threshold: 目标阈值

        Returns:
            PredictionResult: 预测结果
        """
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 3:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})
        # 简化：双向EMA + 5个状态的硬分配
        v = np.array(velocities, dtype=np.float32)
        # forward EMA（前向指数移动平均）
        fwd = v[0]
        for x in v[1:]:
            fwd = 0.4 * x + 0.6 * fwd
        # backward EMA（后向指数移动平均）
        bwd = v[-1]
        for x in v[::-1][1:]:
            bwd = 0.4 * x + 0.6 * bwd
        bi = 0.5 * (fwd + bwd)  # 双向融合
        # 状态分配：基于近期均值 vs 全局均值的比例
        recent_mean = float(np.mean(v[-3:]))
        global_mean = float(np.mean(v))
        ratio = recent_mean / (global_mean + 1e-6)
        # 硬分配到5种增长状态
        if ratio < 0.5:
            multiplier = 0.6
            state = "decay"    # 衰减
        elif ratio < 0.85:
            multiplier = 0.85
            state = "slow"     # 慢速
        elif ratio < 1.15:
            multiplier = 1.0
            state = "steady"   # 稳定
        elif ratio < 1.75:
            multiplier = 1.25
            state = "growing"  # 增长
        else:
            multiplier = 1.6
            state = "viral"    # 爆发
        predicted = max(0.0, bi * multiplier)
        return self._make_result(
            current_views,
            threshold,
            predicted,
            0.42,
            "mar_bilstm_numpy_fallback",
            {"state": state, "multiplier": multiplier, "bi_ema": bi, "method": "bi_ema_state"},
        )

    @staticmethod
    def _velocity_series(history: List[Dict]) -> List[float]:
        """从历史记录中计算速度序列（播放量变化/时间间隔）

        遍历相邻两个历史点，计算单位时间（小时）内的播放量变化。

        Args:
            history: 历史数据记录列表

        Returns:
            List[float]: 速度序列（每小时播放量变化）
        """
        vs = []
        for i in range(1, len(history)):
            t0 = history[i - 1].get("timestamp", 0)
            t1 = history[i].get("timestamp", 0)
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            dt = (float(t1) - float(t0)) / 3600.0  # 转换为小时
            if dt <= 0:
                continue
            v0 = float(history[i - 1].get("view_count", 0) or 0)
            v1 = float(history[i].get("view_count", 0) or 0)
            vs.append((v1 - v0) / dt)
        return vs

    def build_model(self):
        """构建Mar-BiLSTM PyTorch模型实例

        Returns:
            MarBilstmTorchModel: 用于训练的新模型实例
        """
        return MarBilstmTorchModel(in_features=getattr(self, '_training_n_features', len(self._features)), horizon=self.training_horizon)

    def get_training_features(self):
        """返回训练时使用的特征列表"""
        return list(self._features)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        """构造统一的PredictionResult对象

        Args:
            current_views: 当前播放量
            threshold: 目标阈值
            velocity: 预测速度（每小时播放量变化）
            confidence: 置信度 [0, 1]
            reason: 预测来源标识
            extra: 额外元数据字典

        Returns:
            PredictionResult: 标准化的预测结果
        """
        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            predicted_hours = 0 if remaining <= 0 else remaining / velocity
            if remaining <= 0:
                confidence = 1.0
        metadata = {"reason": reason}
        metadata.update(extra or {})
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=int(current_views),
            current_velocity=float(velocity),
            metadata=metadata,
            timestamp=datetime.now(),
        )
