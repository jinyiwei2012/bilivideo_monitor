"""CNN-Image — 将时序铺成 2D 图像后用 Conv2d 提取多尺度模式

思路：
- 把 1D 时序窗口 (W, F) 重排成 2D 图像 (F, H, W'')，让 Conv2d 同时在时间方向和特征方向卷积
- 卷积核 (3,3) 等价于跨 3 个特征 × 3 个时间步的局部模式
- 多通道（dilation 不同的两个分支）捕捉多尺度

降级链：torch Conv2d → numpy 滑动均值 → velocity 兜底
"""

import logging
import math
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
    import torch.nn.functional as F
except ImportError:
    _torch_available = False


if _torch_available:

    class CnnImageTorchModel(nn.Module):
        """将 (W, F) 重塑成 (1, H, W') 后做 Conv2d。"""

        def __init__(self, window: int = 12, in_features: int = 5, horizon: int = 3, base: int = 16):
            super().__init__()
            self.window = window
            self.in_features = in_features
            self.horizon = horizon
            # 图像尺寸：rows = sqrt(W*F)、cols = ceil(W*F / rows)
            total = window * in_features
            self.rows = max(2, int(math.sqrt(total)))
            self.cols = math.ceil(total / self.rows)
            self.pad_size = self.rows * self.cols - total

            # 两路：3x3 普通 + 3x3 dilation=2
            self.branch1 = nn.Sequential(
                nn.Conv2d(1, base, 3, padding=1),
                nn.GELU(),
                nn.Conv2d(base, base, 3, padding=1),
                nn.GELU(),
            )
            self.branch2 = nn.Sequential(
                nn.Conv2d(1, base, 3, padding=2, dilation=2),
                nn.GELU(),
                nn.Conv2d(base, base, 3, padding=2, dilation=2),
                nn.GELU(),
            )
            self.pool = nn.AdaptiveAvgPool2d((4, 4))
            self.head = nn.Sequential(
                nn.Flatten(),
                nn.Linear(2 * base * 4 * 4, 64),
                nn.GELU(),
                nn.Linear(64, horizon),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            # x: [B, W, F]
            B = x.shape[0]
            flat = x.reshape(B, -1)  # [B, W*F]
            if self.pad_size > 0:
                flat = F.pad(flat, (0, self.pad_size))
            img = flat.reshape(B, 1, self.rows, self.cols)
            h1 = self.branch1(img)
            h2 = self.branch2(img)
            h = torch.cat([self.pool(h1), self.pool(h2)], dim=1)
            return self.head(h)  # [B, H]


class CnnImageAlgorithm(BaseAlgorithm):
    name = "CNN图像化预测"
    algorithm_id = "cnn_image"
    description = "时序铺成 2D 图像 + 多尺度 Conv2d"
    category = "深度学习"
    default_weight = 1.2

    training_window = 12
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
                return self._make_result(current_views, threshold, v, conf, "cnn_image_torch", meta)
            except Exception as e:
                logger.warning("[cnn_image] torch 失败，降级: %s", e)
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        x_arr, v_mean, v_std = self._build_input(video_data)
        bvid = video_data.get("bvid", "")
        state = load_best_checkpoint(self.algorithm_id, bvid=bvid)
        if state is None:
            raise RuntimeError("无可用的 checkpoint — 请先训练")
        if self._cached_model is None or (bvid and not getattr(self, "_cached_bvid", "") == bvid):
            model = CnnImageTorchModel(
                window=self.training_window,
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
        predicted = max(0.0, float(y[0]) * v_std + v_mean)
        return predicted, 0.72, {"horizon_pred": y.tolist(), "method": "cnn2d"}

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
        v = np.array(velocities, dtype=np.float32)
        # 简化"图像化"：把序列展开成 sqrt(L)×sqrt(L) 后做 mean-pool（替代卷积）
        side = max(2, int(math.sqrt(len(v))))
        pad = side * side - len(v)
        if pad > 0:
            v_pad = np.concatenate([v, np.full(pad, float(np.mean(v)))])
        else:
            v_pad = v[: side * side]
        img = v_pad.reshape(side, side)
        # 2x2 mean pool
        ph = side // 2 * 2
        pooled = img[:ph, :ph].reshape(ph // 2, 2, ph // 2, 2).mean(axis=(1, 3))
        predicted = max(0.0, float(pooled.mean()))
        return self._make_result(
            current_views,
            threshold,
            predicted,
            0.4,
            "cnn_image_numpy_fallback",
            {"side": side, "pooled_shape": list(pooled.shape), "method": "mean_pool_2x2"},
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
        return CnnImageTorchModel(
            window=self.training_window,
            in_features=len(self._features),
            horizon=self.training_horizon,
        )

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
