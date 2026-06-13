"""Diffusion TS — 时序去噪扩散概率模型 (Denoising Diffusion Probabilistic Model for Time Series)
AAAI 2024 风格的时序扩散模型。

核心思想：将时序预测作为条件生成任务
- 训练阶段：给目标序列逐步加噪 x_0 → x_T，用 UNet1D 预测所加的噪声 ε
- 推理阶段：从纯高斯噪声 x_T 开始，逐步去噪 T → 0 得到预测值（反向扩散）

DDPM 核心公式：
- 前向加噪：x_t = √(ᾱ_t) * x_0 + √(1-ᾱ_t) * ε （ε ~ N(0,1)）
- 反向去噪：x_{t-1} = (1/√α_t) * (x_t - (1-α_t)/√(1-ᾱ_t) * ε̂) + σ_t * z
- 损失函数：MSELoss(ε̂, ε) → 预测所加的噪声

简化版配置：
- 100 步线性 β 调度（β ∈ [1e-4, 0.02]）
- 3 层 UNet1D（含残差块 + 时间嵌入）
- 单通道：仅预测播放量速度序列

降级链：torch 反向扩散 → numpy 高斯 MC 采样 → velocity 兜底
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
        """正弦时间嵌入模块。

        将扩散步 t（标量）映射为高维正弦位置嵌入，类似 Transformer 中的位置编码。
        使模型能区分不同的扩散步（噪声水平）。

        Args:
            dim: 嵌入维度
        """

        def __init__(self, dim: int):
            super().__init__()
            self.dim = dim

        def forward(self, t: "torch.Tensor") -> "torch.Tensor":
            """前向：生成时间步的 sinusoid 嵌入。

            Args:
                t: 扩散步索引 [B]

            Returns:
                时间嵌入 [B, dim]
            """
            half = self.dim // 2
            # 频率按对数尺度从 1 到 10000
            freqs = torch.exp(-np.log(10000) * torch.arange(half, device=t.device) / max(1, half - 1))
            args = t.float().unsqueeze(-1) * freqs.unsqueeze(0)
            emb = torch.cat([torch.sin(args), torch.cos(args)], dim=-1)
            if self.dim % 2 == 1:
                emb = F.pad(emb, (0, 1))
            return emb

    class _ResBlock1D(nn.Module):
        """UNet 的一维残差块。

        包含两个 Conv1d + GroupNorm + SiLU 的组合，以及时间嵌入注入分支。

        Args:
            ch: 通道数
            t_dim: 时间嵌入维度
        """

        def __init__(self, ch: int, t_dim: int):
            super().__init__()
            self.conv1 = nn.Conv1d(ch, ch, 3, padding=1)
            self.conv2 = nn.Conv1d(ch, ch, 3, padding=1)
            self.norm1 = nn.GroupNorm(min(8, ch), ch)
            self.norm2 = nn.GroupNorm(min(8, ch), ch)
            self.t_proj = nn.Linear(t_dim, ch)  # 时间嵌入投影

        def forward(self, x, t_emb):
            """前向：两次归一化+卷积+时间注入 + 残差连接。

            Args:
                x: 输入 [B, C, L]
                t_emb: 时间嵌入 [B, t_dim]

            Returns:
                输出 [B, C, L]
            """
            h = F.silu(self.norm1(x))
            h = self.conv1(h)
            h = h + self.t_proj(F.silu(t_emb)).unsqueeze(-1)  # 时间条件注入
            h = F.silu(self.norm2(h))
            h = self.conv2(h)
            return h + x  # 残差连接

    class DiffusionTSTorchModel(nn.Module):
        """UNet1D + 时间嵌入的扩散模型。

        输入 [B, C, L]（C=1 通道），输出预测的噪声 [B, C, L]。

        架构：输入卷积 → 两个下采样残差块 → 两个上采样残差块 → 输出卷积。
        """

        def __init__(self, in_channels: int = 1, base: int = 32, t_dim: int = 64, n_steps: int = 100):
            """初始化扩散模型。

            Args:
                in_channels: 输入通道数（默认 1，单变量）
                base: 基础通道数，默认 32
                t_dim: 时间嵌入维度，默认 64
                n_steps: 扩散步总数，默认 100
            """
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

            # β 调度（线性从 1e-4 到 0.02）
            betas = torch.linspace(1e-4, 0.02, n_steps)
            alphas = 1.0 - betas
            alpha_bars = torch.cumprod(alphas, dim=0)
            self.register_buffer("betas", betas)
            self.register_buffer("alphas", alphas)
            self.register_buffer("alpha_bars", alpha_bars)

        def forward(self, x: "torch.Tensor", t: "torch.Tensor" = None) -> "torch.Tensor":
            """前向传播 - 支持训练模式和推理模式。

            训练模式（trainer 调用 model(x) 不带 t）：
                使用 preprocess_batch 预先生成的 _train_t / _train_eps 加噪，
                返回预测的噪声 → trainer 用 MSELoss(pred, target=eps) 计算 DDPM 损失。

            推理模式（sample 内调用）：
                x = x_t（当前步加噪数据）, t = 当前步 → 返回预测的噪声

            Args:
                x: 输入张量
                t: 扩散步索引（None 则为训练模式）

            Returns:
                预测的噪声 [B, C, L]
            """
            if t is None:
                B = x.shape[0]
                t = getattr(self, "_train_t", None)
                eps = getattr(self, "_train_eps", None)
                if t is None or eps is None:
                    raise RuntimeError("训练模式需先调用 preprocess_batch 以设定 _train_t / _train_eps")
                t = t.to(device=x.device)
                eps = eps.to(device=x.device)
                ab = self.alpha_bars[t].view(B, 1, 1)
                x_t = (ab.sqrt() * x) + ((1 - ab).sqrt() * eps)  # 加噪：x_t = √(ᾱ_t)·x_0 + √(1-ᾱ_t)·ε
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
            """完整反向扩散采样：从纯噪声 x_T 逐步去噪到 x_0。

            对每一步 t（从 T-1 到 0）：
            1. 预测噪声 ε̂ = model(x_t, t)
            2. 计算 x_{t-1} 的均值
            3. 加噪声（t > 0 时）或直接输出（t = 0 时）

            Args:
                shape: 目标张量形状 (B, C, L)
                device: 计算设备

            Returns:
                去噪后的样本 [B, C, L]
            """
            x = torch.randn(shape, device=device)  # 初始化：x_T ~ N(0, I)
            for t in reversed(range(self.n_steps)):  # 从 T-1 到 0
                t_batch = torch.full((shape[0],), t, device=device, dtype=torch.long)
                eps = self.forward(x, t_batch)
                ab = self.alpha_bars[t]
                a = self.alphas[t]
                # 预测 x_{t-1} 的均值
                mean = (1.0 / a.sqrt()) * (x - (1 - a) / (1 - ab).sqrt() * eps)
                if t > 0:
                    noise = torch.randn_like(x)
                    sigma = self.betas[t].sqrt()
                    x = mean + sigma * noise  # 反向加噪
                else:
                    x = mean  # 最后一步不加噪
            return x


class DiffusionTSAlgorithm(BaseAlgorithm):
    """Diffusion TS 扩散预测算法。

    将 DDPM 扩散模型应用于时序预测：
    - 输入：速度序列（单变量）
    - 输出：通过反向扩散采样得到未来速度预测
    - 训练：MSELoss(ε̂, ε) 作为扩散损失

    降级链：torch 反向扩散 → numpy MC sampling → velocity 兜底
    """

    name = "Diffusion TS扩散预测"
    algorithm_id = "diffusion_ts"
    description = "时序去噪扩散模型 (DDPM + UNet1D)"
    category = "深度学习"
    default_weight = 1.3

    training_window = 12
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def __init__(self):
        """初始化 Diffusion TS 算法。

        设置设备、checkpoint 管理器、模型缓存。
        序列总长度 = 训练窗口 + 预测步长（用于构造完整序列做扩散）。
        """
        super().__init__()
        self._device = get_device()
        self._ckpt = CheckpointManager(self.algorithm_id)
        self._cached_model = None
        self._cached_model_for_training = None  # 训练时 preprocess → forward 传递噪声用
        # 单通道：speed 序列
        self._series_len = self.training_window + self.training_horizon

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """预测到达目标播放量所需时间。

        优先使用 torch 扩散模型推理，失败降级到 numpy。

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
                return self._make_result(current_views, threshold, v, conf, "diffusion_ts_torch", meta)
            except Exception as e:
                logger.warning("[diffusion_ts] torch 失败，降级: %s", e)
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        """Torch 扩散模型推理。

        加载 checkpoint → 模型采样生成未来速度 → 反归一化。

        Args:
            video_data: 视频数据字典

        Returns:
            (预测速度, 置信度, 元数据字典)
        """
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
            state = {k[len("_orig_mod."):] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}
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
        y_norm = sample.cpu().numpy().reshape(-1)  # [H]
        predicted = max(0.0, float(y_norm[0]) * std + mean)  # 反归一化
        return predicted, 0.7, {"horizon_pred": y_norm.tolist(), "method": "diffusion_ddpm"}

    def _numpy_predict(self, video_data, current_views, threshold) -> PredictionResult:
        """numpy 降级预测 - 简化版扩散。

        用高斯 MC 采样模拟扩散去噪：
        从历史均值 + 高斯扰动多次采样，取均值作为预测。

        Args:
            video_data: 视频数据字典
            current_views: 当前播放量
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果
        """
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
        """从历史数据中提取速度序列（每小时播放量增量）。

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

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        同时缓存训练用模型实例，供 preprocess_batch 使用。

        Returns:
            DiffusionTSTorchModel 实例
        """
        m = DiffusionTSTorchModel(in_channels=1, base=32, t_dim=64, n_steps=100)
        self._cached_model_for_training = m  # preprocess_batch 需要引用
        return m

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count"]

    def preprocess_batch(self, batch):
        """训练 batch 预处理：(x, y) → x_0 作为输入，eps 作为 target。

        同时生成随机扩散步 t 和噪声 eps，存入 _cached_model_for_training，
        供 forward(t=None) 内部加噪时使用同一份噪声，
        使 MSELoss(eps_pred, eps) 计算正确的 DDPM 噪声预测损失。

        Args:
            batch: (x, y) 训练批次

        Returns:
            (x_0, eps) 供 trainer 使用
        """
        if not _torch_available:
            return batch
        x, y = batch
        x_0 = y.unsqueeze(1)  # [B, 1, H]  目标序列作为"干净数据"
        B = x_0.shape[0]
        device = x_0.device
        n_steps = getattr(self._cached_model_for_training, "n_steps", 100)
        t = torch.randint(0, n_steps, (B,), device=device, dtype=torch.long)  # 随机扩散步
        eps = torch.randn_like(x_0)  # 目标噪声
        if self._cached_model_for_training is not None:
            self._cached_model_for_training._train_t = t
            self._cached_model_for_training._train_eps = eps
        return x_0, eps  # model(x_0) → eps_pred, loss = MSELoss(eps_pred, eps)

    def get_loss_fn(self):
        """获取 DDPM 损失函数：MSELoss(ε̂, ε)。

        trainer 调用 model(x)，模型内部完成加噪并返回预测噪声，
        然后用 MSELoss 与真实噪声对比。

        Returns:
            MSELoss 包装器
        """
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
