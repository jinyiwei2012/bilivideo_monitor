"""KNF — Koopman 神经预测器 (Koopman Neural Forecaster)
ICLR 2023

核心思想：将非线性时序通过编码器映射到 Koopman 不变子空间，在该空间内
时间演化变为线性操作 K·z_t → z_{t+1}。

关键贡献：
- 全局 Koopman 算子 K_global：跨视频共享的"通用"演化规律矩阵
- 局部 Koopman 算子 K_local：单个视频样本自适应的微调修正（由元网络预测）
- 反馈循环：每一步预测的结果都会反馈到下一步输入（自回归结构）

Koopman 理论背景：
任何非线性动力系统都可以在某个高维可观测空间中等效为线性系统。
KNF 用一个神经网络找到这个空间中的线性算子 K。

Torch 实现 + 降级链：
- 有 checkpoint → 真实 KNF 推理（全局 K + 局部低秩修正 + 反馈循环）
- 无 checkpoint / 失败 → numpy 简化版（EMA + 一阶线性外推）
- 兜底 → calculate_velocity
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.training.checkpoint_manager import CheckpointManager, load_best_checkpoint
from algorithms.training.device import get_device

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
    import torch.nn as nn
except ImportError:
    _torch_available = False


# ── Torch Model ───────────────────────────────────────

if _torch_available:

    class KnfTorchModel(nn.Module):
        """Koopman 神经预测器 (简化版)。

        编码器 (W,F)→z → K_global·z → 低秩修正 → 解码器 → 预测值。
        包含反馈循环：每步预测基于上一步的 Koopman 状态。
        """

        def __init__(
            self,
            in_features: int = 5,
            window: int = 10,
            horizon: int = 3,
            koopman_dim: int = 16,
            hidden: int = 64,
        ):
            """初始化 KNF 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                koopman_dim: Koopman 空间维度，默认 16
                hidden: 隐藏层维度，默认 64
            """
            super().__init__()
            self.in_features = in_features
            self.window = window
            self.horizon = horizon
            self.koopman_dim = koopman_dim

            # 编码器：(W, F) → z (koopman_dim)
            self.encoder = nn.Sequential(
                nn.Linear(window * in_features, hidden),
                nn.GELU(),
                nn.Linear(hidden, koopman_dim),
            )
            # 全局 Koopman 算子（学习的方阵，初始为单位矩阵 + 小扰动）
            self.K_global = nn.Parameter(torch.eye(koopman_dim) + 0.01 * torch.randn(koopman_dim, koopman_dim))
            # 局部 Koopman 元网络：从 z 预测一个低秩修正 (u, v)
            self.meta = nn.Sequential(
                nn.Linear(koopman_dim, hidden),
                nn.GELU(),
                nn.Linear(hidden, koopman_dim * 2),  # 低秩 u, v → 修正 = u @ v.T
            )
            # 解码器：z → 预测的速度（标量）
            self.decoder = nn.Sequential(
                nn.Linear(koopman_dim, hidden),
                nn.GELU(),
                nn.Linear(hidden, 1),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            """前向传播 - 含反馈循环的多步预测。

            每步：编码 → 全局 K + 局部修正 → 解码为预测值 → 反馈 z 到下一步。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]（H 个时间步的预测）
            """
            # x: [B, W, F]
            B = x.shape[0]
            flat = x.reshape(B, -1)
            z = self.encoder(flat)  # [B, K]  初始状态
            outs = []
            for _ in range(self.horizon):
                # 局部修正：元网络输出 (u, v)，构造低秩 1 修正矩阵
                uv = self.meta(z)  # [B, 2K]
                u, v = uv[:, : self.koopman_dim], uv[:, self.koopman_dim :]
                # K_local = K_global + outer(u, v)（低秩 1 修正）
                # z_next = z @ K_global.T + (z·v) * u
                z_global = z @ self.K_global.T  # 全局演化
                inner = (z * v).sum(dim=-1, keepdim=True)  # [B, 1]  内积标量
                z_local = inner * u  # 低秩 1 修正项
                z = z_global + 0.1 * z_local  # 控制局部修正幅度（权重 0.1）
                y = self.decoder(z).squeeze(-1)  # [B]  解码为预测标量
                outs.append(y)
            return torch.stack(outs, dim=1)  # [B, H]


# ── Algorithm Wrapper ─────────────────────────────────


class KnfAlgorithm(BaseAlgorithm):
    """KNF Koopman 神经预测算法。

    核心机制（Torch）：
    - 编码器将多维时序压入 Koopman 空间
    - K_global 提供跨视频的通用演化规律
    - 元网络基于当前状态预测低秩修正（视频自适应）
    - 反馈循环实现自回归多步预测

    降级链：torch KNF → numpy EMA+AR(1) → velocity 兜底
    """

    name = "KNF Koopman预测"
    algorithm_id = "knf"
    description = "Koopman Neural Forecaster: 全局+局部线性演化 + 反馈循环"
    category = "深度学习"
    default_weight = 1.4

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def __init__(self):
        """初始化 KNF 算法。

        设置设备、checkpoint 管理器、模型缓存和基础特征列表。
        """
        super().__init__()
        self._device = get_device()
        self._ckpt = CheckpointManager(self.algorithm_id)
        self._cached_model = None
        self._features = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    # —— BaseAlgorithm ——

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """预测到达目标播放量所需时间。

        优先使用 torch KNF 推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        current_views = int(video_data.get("view_count", 0))
        if _torch_available:
            try:
                v, conf, meta = self._torch_predict(video_data)
                return self._make_result(current_views, threshold, v, conf, "knf_torch", meta)
            except Exception as e:
                logger.warning("[knf] torch 推理失败，降级 numpy: %s", e)
        return self._numpy_predict(video_data, current_views, threshold)

    # —— Torch 推理 ——

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        """Torch KNF 推理：加载 checkpoint → 编码 → Koopman 演化 → 解码。

        Args:
            video_data: 视频数据字典

        Returns:
            (预测速度, 置信度, 元数据字典)
        """
        x_arr = self._build_input_array(video_data)  # [W, F] 归一化输入
        bvid = video_data.get("bvid", "")
        state, _ = load_best_checkpoint(self.algorithm_id, bvid=bvid)
        if state is None:
            raise RuntimeError("无可用的 checkpoint — 请先训练")
        if self._cached_model is None or (bvid and not getattr(self, "_cached_bvid", "") == bvid):
            model = KnfTorchModel(
                in_features=getattr(self, '_training_n_features', len(self._features) + 5), window=self.training_window, horizon=self.training_horizon
            )
            state = {k[len("_orig_mod."):] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}
            model.load_state_dict(state)
            model.to(self._device).eval()
            self._cached_model = model
            self._cached_bvid = bvid or ""
        x = torch.from_numpy(x_arr).unsqueeze(0).to(self._device)
        with torch.no_grad():
            y = self._cached_model(x).cpu().numpy().squeeze(0)  # [H]
        # y 是归一化后的速度，反归一化用历史的均值/标准差
        velocity = self._denormalize_prediction(video_data, y)
        return velocity, 0.78, {"horizon_pred": y.tolist(), "method": "knf_torch"}

    def _build_input_array(self, video_data: Dict[str, Any]) -> np.ndarray:
        """构建归一化输入数组 [W, F+5]。

        从 history_data 提取窗口特征 → 追加 5 个衍生特征 → z-score 归一化。

        Args:
            video_data: 视频数据字典

        Returns:
            归一化特征数组 [W, F+5]
        """
        from algorithms.models.deep_learning._torch_upgrade import _add_derived_features

        history = video_data.get("history_data", [])
        n = self.training_window
        arr = np.zeros((n, len(self._features)), dtype=np.float32)
        recent = history[-n:] if len(history) >= n else history
        offset = n - len(recent)
        for i, e in enumerate(recent):
            for j, f in enumerate(self._features):
                arr[offset + i, j] = float(e.get(f, 0) or 0)

        arr_ext = _add_derived_features(arr)  # 追加衍生特征
        mean = arr_ext.mean(axis=0, keepdims=True)
        std = arr_ext.std(axis=0, keepdims=True)
        std = np.where(std < 1e-8, 1.0, std)
        return ((arr_ext - mean) / std).astype(np.float32)

    def _denormalize_prediction(self, video_data: Dict[str, Any], y_norm: np.ndarray) -> float:
        """模型预测的是 z-score 后的速度差分，需反归一化到原始尺度。

        Args:
            video_data: 视频数据字典
            y_norm: 归一化模型输出 [H]

        Returns:
            反归一化后的预测速度值
        """
        history = video_data.get("history_data", [])
        views = [float(e.get("view_count", 0) or 0) for e in history]
        if len(views) < 2:
            return self.calculate_velocity(video_data)
        ts = []
        for e in history:
            t = e.get("timestamp", 0)
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            ts.append(float(t) if t else 0.0)
        velocities = []
        for i in range(1, len(views)):
            dt = (ts[i] - ts[i - 1]) / 3600.0
            if dt > 0:
                velocities.append((views[i] - views[i - 1]) / dt)
        if not velocities:
            return self.calculate_velocity(video_data)
        v = np.array(velocities, dtype=np.float32)
        mean = float(v.mean())
        std = float(v.std()) if len(v) > 1 else 1.0
        if std < 1e-8:
            std = 1.0
        # 取预测的第一个时间步作为代表速度
        return max(0.0, float(y_norm[0]) * std + mean)

    # —— numpy 降级 ——

    def _numpy_predict(self, video_data: Dict[str, Any], current_views: int, threshold: int) -> PredictionResult:
        """numpy 降级预测 - 简化版 KNF。

        用 EMA（指数移动平均）+ 一阶线性外推模拟 Koopman 演化。
        EMA 模拟全局趋势，线性斜率模拟局部修正。

        Args:
            video_data: 视频数据字典
            current_views: 当前播放量
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果
        """
        history = video_data.get("history_data", [])
        if len(history) < 5:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})

        velocities = self._compute_velocity_series(history)
        if len(velocities) < 3:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "short_series", {})

        # 简化版 KNF：把速度序列做 EMA 平滑 + 一阶 AR 外推
        # EMA 模拟 Koopman 全局演化
        ema = velocities[0]
        alpha = 0.4  # 平滑系数（越大对新值越敏感）
        for v in velocities[1:]:
            ema = alpha * v + (1 - alpha) * ema
        # 一阶线性外推模拟局部修正
        if len(velocities) >= 4:
            slope = float(np.polyfit(np.arange(len(velocities)), velocities, 1)[0])
        else:
            slope = 0.0
        predicted = max(0.0, ema + slope)  # EMA + 趋势修正
        return self._make_result(
            current_views,
            threshold,
            predicted,
            0.45,
            "knf_numpy_fallback",
            {"ema": ema, "slope": slope, "method": "knf_simplified"},
        )

    @staticmethod
    def _compute_velocity_series(history: List[Dict]) -> List[float]:
        """从历史数据中提取速度序列。

        Args:
            history: 历史数据列表

        Returns:
            速度列表（每小时播放量增量）
        """
        vs = []
        for i in range(1, len(history)):
            t0 = history[i - 1].get("timestamp", 0)
            t1 = history[i].get("timestamp", 0)
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            dt = (float(t1) - float(t0)) / 3600.0
            if dt <= 0:
                continue
            v0 = float(history[i - 1].get("view_count", 0) or 0)
            v1 = float(history[i].get("view_count", 0) or 0)
            vs.append((v1 - v0) / dt)
        return vs

    # —— Trainer 接口 ——

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            KnfTorchModel 实例
        """
        return KnfTorchModel(
            in_features=getattr(self, '_training_n_features', len(self._features)), window=self.training_window, horizon=self.training_horizon
        )

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return list(self._features)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        """构造 PredictionResult 预测结果。

        Args:
            current_views: 当前播放量
            threshold: 目标播放量阈值
            velocity: 预测速度（每小时播放量）
            confidence: 置信度 [0, 1]
            reason: 预测原因标识
            extra: 额外元数据字典

        Returns:
            PredictionResult 预测结果对象
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
