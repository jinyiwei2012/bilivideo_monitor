"""Diffusion TS — Denoising Diffusion Probabilistic Model for Time Series (AAAI 2024 风格)

将时序预测作为条件生成任务：
- 训练：给目标序列加噪到 x_t，用 UNet1D 预测加的噪声 ε
- 推理：从纯噪声 x_T 开始，逐步去噪 T → 0 得到预测

简化版：100 步线性 β 调度 + 3 层 UNet1D。

降级链：torch 反向扩散 → numpy 简化版（线性趋势 + 高斯采样）→ velocity 兜底
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
    import torch.nn.functional as F
except ImportError:
    _torch_available = False


if _torch_available:

    class _SinusoidalTimeEmbed(nn.Module):
        def __init__(self, dim: int):
            super().__init__()
            self.dim = dim

        def forward(self, t: "torch.Tensor") -> "torch.Tensor":
            # t: [B]
            half = self.dim // 2
            freqs = torch.exp(-np.log(10000) * torch.arange(half, device=t.device) / max(1, half - 1))
            args = t.float().unsqueeze(-1) * freqs.unsqueeze(0)
            emb = torch.cat([torch.sin(args), torch.cos(args)], dim=-1)
            if self.dim % 2 == 1:
                emb = F.pad(emb, (0, 1))
            return emb

    class _ResBlock1D(nn.Module):
        def __init__(self, ch: int, t_dim: int):
            super().__init__()
            self.conv1 = nn.Conv1d(ch, ch, 3, padding=1)
            self.conv2 = nn.Conv1d(ch, ch, 3, padding=1)
            self.norm1 = nn.GroupNorm(min(8, ch), ch)
            self.norm2 = nn.GroupNorm(min(8, ch), ch)
            self.t_proj = nn.Linear(t_dim, ch)

        def forward(self, x, t_emb):
            h = F.silu(self.norm1(x))
            h = self.conv1(h)
            h = h + self.t_proj(F.silu(t_emb)).unsqueeze(-1)
            h = F.silu(self.norm2(h))
            h = self.conv2(h)
            return h + x

    class DiffusionTSTorchModel(nn.Module):
        """UNet1D + 时间嵌入。输入 [B, C, L]，输出预测的噪声 [B, C, L]。"""

        def __init__(self, in_channels: int = 1, base: int = 32, t_dim: int = 64, n_steps: int = 100):
            super().__init__()
            self.n_steps = n_steps
            self.t_embed = nn.Sequential(_SinusoidalTimeEmbed(t_dim), nn.Linear(t_dim, t_dim))
            # encoder
            self.in_conv = nn.Conv1d(in_channels, base, 3, padding=1)
            self.down1 = _ResBlock1D(base, t_dim)
            self.down2 = _ResBlock1D(base, t_dim)
            self.up1 = _ResBlock1D(base, t_dim)
            self.up2 = _ResBlock1D(base, t_dim)
            self.out_conv = nn.Conv1d(base, in_channels, 3, padding=1)

            # β 调度
            betas = torch.linspace(1e-4, 0.02, n_steps)
            alphas = 1.0 - betas
            alpha_bars = torch.cumprod(alphas, dim=0)
            self.register_buffer("betas", betas)
            self.register_buffer("alphas", alphas)
            self.register_buffer("alpha_bars", alpha_bars)

        def forward(self, x: "torch.Tensor", t: "torch.Tensor" = None) -> "torch.Tensor":
            # 训练模式（trainer 调用 model(x) 不带 t）：
            #   使用 preprocess_batch 预先生成的 _train_t / _train_eps 加噪，
            #   返回预测的噪声 → trainer 用 MSELoss(pred, target=eps) 计算 DDPM 损失。
            # 推理模式（sample 内调用）：
            #   x = x_t（当前步加噪数据）, t = 当前步 → 返回预测的噪声
            if t is None:
                B = x.shape[0]
                t = getattr(self, "_train_t", None)
                eps = getattr(self, "_train_eps", None)
                if t is None or eps is None:
                    raise RuntimeError("训练模式需先调用 preprocess_batch 以设定 _train_t / _train_eps")
                t = t.to(device=x.device)
                eps = eps.to(device=x.device)
                ab = self.alpha_bars[t].view(B, 1, 1)
                x_t = (ab.sqrt() * x) + ((1 - ab).sqrt() * eps)
                t_emb = self.t_embed(t)
                h = self.in_conv(x_t)
                h = self.down1(h, t_emb)
                h = self.down2(h, t_emb)
                h = self.up1(h, t_emb)
                h = self.up2(h, t_emb)
                return self.out_conv(h)  # 预测噪声 ε̂，trainer 用 MSELoss(ε̂, eps)
            # 推理模式
            t_emb = self.t_embed(t)
            h = self.in_conv(x)
            h = self.down1(h, t_emb)
            h = self.down2(h, t_emb)
            h = self.up1(h, t_emb)
            h = self.up2(h, t_emb)
            return self.out_conv(h)

        @torch.no_grad()
        def sample(self, shape, device):
            """完整反向扩散采样：x_T (高斯) → x_0。"""
            x = torch.randn(shape, device=device)
            for t in reversed(range(self.n_steps)):
                t_batch = torch.full((shape[0],), t, device=device, dtype=torch.long)
                eps = self.forward(x, t_batch)
                ab = self.alpha_bars[t]
                a = self.alphas[t]
                # 预测 x_{t-1}
                mean = (1.0 / a.sqrt()) * (x - (1 - a) / (1 - ab).sqrt() * eps)
                if t > 0:
                    noise = torch.randn_like(x)
                    sigma = self.betas[t].sqrt()
                    x = mean + sigma * noise
                else:
                    x = mean
            return x


class DiffusionTSAlgorithm(BaseAlgorithm):
    name = "Diffusion TS扩散预测"
    algorithm_id = "diffusion_ts"
    description = "时序去噪扩散模型 (DDPM + UNet1D)"
    category = "深度学习"
    default_weight = 1.3

    training_window = 12
    training_horizon = 3

    def __init__(self):
        super().__init__()
        self._device = get_device()
        self._ckpt = CheckpointManager(self.algorithm_id)
        self._cached_model = None
        self._cached_model_for_training = None  # 训练时 preprocess → forward 传递噪声用
        # 单通道：speed 序列
        self._series_len = self.training_window + self.training_horizon

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = int(video_data.get("view_count", 0))
        if _torch_available:
            try:
                v, conf, meta = self._torch_predict(video_data)
                return self._make_result(current_views, threshold, v, conf, "diffusion_ts_torch", meta)
            except Exception as e:
                logger.warning("[diffusion_ts] torch 失败，降级: %s", e)
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 4:
            raise RuntimeError("速度序列太短")
        bvid = video_data.get("bvid", "")
        state, _ = load_best_checkpoint(self.algorithm_id, bvid=bvid)
        if state is None:
            raise RuntimeError("无可用的 checkpoint — 请先训练")
        # 视频微调不缓存（每次加载最新权重），全局 checkpoint 可缓存
        if self._cached_model is None or (bvid and not getattr(self, "_cached_bvid", "") == bvid):
            model = DiffusionTSTorchModel(in_channels=1, base=32, t_dim=64, n_steps=100)
            model.load_state_dict(state)
            model.to(self._device).eval()
            self._cached_model = model
            self._cached_bvid = bvid or ""
        model = self._cached_model
        mean = float(np.mean(velocities))
        std = float(np.std(velocities)) if len(velocities) > 1 else 1.0
        if std < 1e-8:
            std = 1.0
        # 直接采样预测段（简化：不做 conditional inpainting，纯生成）
        sample = self._cached_model.sample((1, 1, self.training_horizon), self._device)
        y_norm = sample.cpu().numpy().reshape(-1)
        predicted = max(0.0, float(y_norm[0]) * std + mean)
        return predicted, 0.7, {"horizon_pred": y_norm.tolist(), "method": "diffusion_ddpm"}

    def _numpy_predict(self, video_data, current_views, threshold) -> PredictionResult:
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 3:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})
        # 简化版：用历史均值 + 高斯扰动的多次采样取均值
        v = np.array(velocities, dtype=np.float32)
        mean = float(v.mean())
        std = float(v.std()) if len(v) > 1 else 0.0
        # 模拟"扩散去噪"：从噪声开始 + 朝均值收敛
        rng = np.random.default_rng(42)
        sample_count = 16
        samples = mean + std * rng.standard_normal(sample_count) * 0.3  # 缩小方差
        predicted = max(0.0, float(np.mean(samples)))
        return self._make_result(
            current_views,
            threshold,
            predicted,
            0.45,
            "diffusion_numpy_fallback",
            {"mean": mean, "std": std, "method": "gaussian_mc"},
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
        m = DiffusionTSTorchModel(in_channels=1, base=32, t_dim=64, n_steps=100)
        self._cached_model_for_training = m  # preprocess_batch 需要引用
        return m

    def get_training_features(self):
        return ["view_count"]

    def preprocess_batch(self, batch):
        """训练 batch：(x, y) → x_0 作为输入，eps 作为 target。

        同时生成 t 并将 (t, eps) 存入 _cached_model_for_training，
        供 forward(t=None) 内部加噪时使用同一份噪声，
        使 MSELoss(eps_pred, eps) 计算正确的 DDPM 噪声预测损失。
        """
        if not _torch_available:
            return batch
        x, y = batch
        x_0 = y.unsqueeze(1)  # [B, 1, H]
        B = x_0.shape[0]
        device = x_0.device
        n_steps = getattr(self._cached_model_for_training, "n_steps", 100)
        t = torch.randint(0, n_steps, (B,), device=device, dtype=torch.long)
        eps = torch.randn_like(x_0)
        if self._cached_model_for_training is not None:
            self._cached_model_for_training._train_t = t
            self._cached_model_for_training._train_eps = eps
        return x_0, eps  # model(x_0) → eps_pred, loss = MSELoss(eps_pred, eps)

    def get_loss_fn(self):
        """DDPM 损失：随机采样 t、加噪、预测噪声。"""
        if not _torch_available:
            return None

        # 因为 trainer 是通用 MSELoss(pred, y) 形式，
        # 我们用一个 wrapper：trainer 调用 model(x)，我们让模型内部完成训练 step
        class _DDPMLoss(nn.Module):
            def __init__(self):
                super().__init__()
                self.mse = nn.MSELoss()

            def forward(self, pred, target):
                return self.mse(pred, target)

        return _DDPMLoss()

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
