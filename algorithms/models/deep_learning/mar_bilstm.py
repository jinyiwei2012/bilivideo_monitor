"""Mar-BiLSTM — Markov-augmented BiLSTM（2024 风格）

BiLSTM 处理短期上下文，可学习的马尔可夫转移矩阵处理长期状态演化：
- BiLSTM 编码窗口 → context vector
- N 个可学习"状态原型"（增长/衰减/爆发/稳定/震荡 等）
- 软分配当前样本到原型分布（softmax）
- 用学习的 Markov 矩阵 H 步演化 → 解码出预测速度

降级链：torch → numpy（仅 BiLSTM 风格的双向 EMA + 简单状态分配）
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


if _torch_available:

    class MarBilstmTorchModel(nn.Module):
        def __init__(
            self,
            in_features: int = 5,
            hidden: int = 32,
            n_states: int = 5,
            horizon: int = 3,
        ):
            super().__init__()
            self.n_states = n_states
            self.horizon = horizon
            self.lstm = nn.LSTM(
                input_size=in_features,
                hidden_size=hidden,
                num_layers=1,
                batch_first=True,
                bidirectional=True,
            )
            self.state_proj = nn.Linear(hidden * 2, n_states)
            # 可学习 Markov 转移矩阵（row-stochastic 通过 softmax）
            self.markov_logits = nn.Parameter(torch.zeros(n_states, n_states))
            # 状态原型对应的输出速度（z-score 空间）
            self.state_outputs = nn.Parameter(torch.linspace(-1.0, 1.5, n_states))

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            # x: [B, W, F]
            out, _ = self.lstm(x)  # [B, W, 2H]
            ctx = out[:, -1, :]  # 取最后一步
            state_dist = torch.softmax(self.state_proj(ctx), dim=-1)  # [B, N]
            P = torch.softmax(self.markov_logits, dim=-1)  # 行随机
            preds = []
            d = state_dist
            for _ in range(self.horizon):
                d = d @ P
                preds.append((d * self.state_outputs.unsqueeze(0)).sum(dim=-1))
            return torch.stack(preds, dim=1)  # [B, H]


class MarBilstmAlgorithm(BaseAlgorithm):
    name = "Mar-BiLSTM马尔可夫"
    algorithm_id = "mar_bilstm"
    description = "BiLSTM + 可学习马尔可夫状态转移"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10
    training_horizon = 3

    def __init__(self):
        super().__init__()
        self._device = get_device()
        self._ckpt = CheckpointManager(self.algorithm_id)
        self._cached_model = None
        self._features = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = int(video_data.get("view_count", 0))
        if _torch_available:
            try:
                v, conf, meta = self._torch_predict(video_data)
                return self._make_result(current_views, threshold, v, conf, "mar_bilstm_torch", meta)
            except Exception as e:
                logger.warning("[mar_bilstm] torch 失败，降级: %s", e)
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        x_arr, vel_mean, vel_std = self._build_input(video_data)
        bvid = video_data.get("bvid", "")
        state = load_best_checkpoint(self.algorithm_id, bvid=bvid)
        if state is None:
            raise RuntimeError("无可用的 checkpoint — 请先训练")
        if self._cached_model is None or (bvid and not getattr(self, "_cached_bvid", "") == bvid):
            model = MarBilstmTorchModel(
                in_features=len(self._features),
                horizon=self.training_horizon,
            )
            model.load_state_dict(state)
            model.to(self._device).eval()
            self._cached_model = model
            self._cached_bvid = bvid or ""
        x = torch.from_numpy(x_arr).unsqueeze(0).to(self._device)
        with torch.no_grad():
            y = self._cached_model(x).cpu().numpy().squeeze(0)
        predicted = max(0.0, float(y[0]) * vel_std + vel_mean)
        return predicted, 0.74, {"horizon_pred": y.tolist(), "method": "mar_bilstm"}

    def _build_input(self, video_data) -> Tuple[np.ndarray, float, float]:
        history = video_data.get("history_data", [])
        n = self.training_window
        arr = np.zeros((n, len(self._features)), dtype=np.float32)
        recent = history[-n:] if len(history) >= n else history
        offset = n - len(recent)
        for i, e in enumerate(recent):
            for j, f in enumerate(self._features):
                arr[offset + i, j] = float(e.get(f, 0) or 0)
        mean = arr.mean(axis=0, keepdims=True)
        std = arr.std(axis=0, keepdims=True)
        std = np.where(std < 1e-8, 1.0, std)
        arr_n = ((arr - mean) / std).astype(np.float32)
        # 反归一化用的速度统计
        velocities = self._velocity_series(history)
        v_mean = float(np.mean(velocities)) if velocities else 0.0
        v_std = float(np.std(velocities)) if len(velocities) > 1 else 1.0
        if v_std < 1e-8:
            v_std = 1.0
        return arr_n, v_mean, v_std

    def _numpy_predict(self, video_data, current_views, threshold) -> PredictionResult:
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 3:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})
        # 简化：双向 EMA + 5 个状态的硬分配
        v = np.array(velocities, dtype=np.float32)
        # forward EMA
        fwd = v[0]
        for x in v[1:]:
            fwd = 0.4 * x + 0.6 * fwd
        # backward EMA
        bwd = v[-1]
        for x in v[::-1][1:]:
            bwd = 0.4 * x + 0.6 * bwd
        bi = 0.5 * (fwd + bwd)
        # 状态分配（基于近期均值 vs 全局均值的比例）
        recent_mean = float(np.mean(v[-3:]))
        global_mean = float(np.mean(v))
        ratio = recent_mean / (global_mean + 1e-6)
        if ratio < 0.5:
            multiplier = 0.6  # decay
            state = "decay"
        elif ratio < 0.85:
            multiplier = 0.85
            state = "slow"
        elif ratio < 1.15:
            multiplier = 1.0
            state = "steady"
        elif ratio < 1.75:
            multiplier = 1.25
            state = "growing"
        else:
            multiplier = 1.6
            state = "viral"
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

    def build_model(self):
        return MarBilstmTorchModel(in_features=len(self._features), horizon=self.training_horizon)

    def get_training_features(self):
        return list(self._features)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
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
