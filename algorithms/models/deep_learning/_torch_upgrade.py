"""为 14 个既有 numpy 简化版算法定义 PyTorch 模型骨架 + 统一的"torch → numpy 降级"调度器。

不直接重写既有算法文件，而是：
- 每个算法在文件里加 3-5 行接入此模块（保留原 numpy 逻辑作为 `_numpy_predict`）
- 当 checkpoint 存在 → 用 `XxxTorchModel` 推理
- 当 torch 不可用 / checkpoint 缺失 / 推理异常 → 回退到 `_numpy_predict`

模型设计统一为：输入 [B, W, F] → 输出 [B, H]（H 步速度预测）
特征 F 默认 5：view_count, like_count, coin_count, favorite_count, share_count
"""

import logging
from typing import Any, Callable, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
except ImportError:
    _torch_available = False
    nn = None  # type: ignore
    F = None  # type: ignore


DEFAULT_FEATURES = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]
DEFAULT_WINDOW = 10
DEFAULT_HORIZON = 3


# ════════════════════════════════════════════════════════
#  Torch 模型骨架（14 个）
# ════════════════════════════════════════════════════════

if _torch_available:  # noqa: C901
    # ── 1. LSTM ────────────────────────────────────
    class LSTMTorchModel(nn.Module):
        def __init__(self, in_features=5, hidden=32, layers=1, horizon=3):
            super().__init__()
            self.lstm = nn.LSTM(in_features, hidden, num_layers=layers, batch_first=True)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    # ── 2. GRU ─────────────────────────────────────
    class GRUTorchModel(nn.Module):
        def __init__(self, in_features=5, hidden=32, layers=1, horizon=3):
            super().__init__()
            self.gru = nn.GRU(in_features, hidden, num_layers=layers, batch_first=True)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            out, _ = self.gru(x)
            return self.head(out[:, -1, :])

    # ── 3. BiLSTM ──────────────────────────────────
    class BiLSTMTorchModel(nn.Module):
        def __init__(self, in_features=5, hidden=32, layers=1, horizon=3):
            super().__init__()
            self.lstm = nn.LSTM(in_features, hidden, num_layers=layers, batch_first=True, bidirectional=True)
            self.head = nn.Linear(hidden * 2, horizon)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    # ── 4. MLP / Neural Network / NeuralNetwork ──
    class MLPTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, hidden=64, horizon=3):
            super().__init__()
            self.net = nn.Sequential(
                nn.Flatten(),
                nn.Linear(window * in_features, hidden),
                nn.GELU(),
                nn.Linear(hidden, hidden // 2),
                nn.GELU(),
                nn.Linear(hidden // 2, horizon),
            )

        def forward(self, x):
            return self.net(x)

    # ── 5. TCN（Dilated Conv1d） ─────────────────
    class TCNTorchModel(nn.Module):
        def __init__(self, in_features=5, channels=16, kernel=3, horizon=3):
            super().__init__()
            # 三层 dilation 1, 2, 4
            self.tcn = nn.Sequential(
                nn.Conv1d(in_features, channels, kernel, padding=1, dilation=1),
                nn.GELU(),
                nn.Conv1d(channels, channels, kernel, padding=2, dilation=2),
                nn.GELU(),
                nn.Conv1d(channels, channels, kernel, padding=4, dilation=4),
                nn.GELU(),
            )
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.head = nn.Linear(channels, horizon)

        def forward(self, x):
            # x: [B, W, F] → conv1d 需要 [B, F, W]
            h = x.transpose(1, 2)
            h = self.tcn(h)
            h = self.pool(h).squeeze(-1)
            return self.head(h)

    # ── 6. CNN-LSTM 混合 ──────────────────────────
    class CNNLSTMTorchModel(nn.Module):
        def __init__(self, in_features=5, conv_channels=16, lstm_hidden=32, horizon=3):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv1d(in_features, conv_channels, 3, padding=1),
                nn.GELU(),
                nn.Conv1d(conv_channels, conv_channels, 3, padding=1),
                nn.GELU(),
            )
            self.lstm = nn.LSTM(conv_channels, lstm_hidden, batch_first=True)
            self.head = nn.Linear(lstm_hidden, horizon)

        def forward(self, x):
            h = x.transpose(1, 2)  # [B, F, W]
            h = self.conv(h)
            h = h.transpose(1, 2)  # [B, W, C]
            out, _ = self.lstm(h)
            return self.head(out[:, -1, :])

    # ── 7. Attention（多头注意力） ────────────────
    class AttentionTorchModel(nn.Module):
        def __init__(self, in_features=5, d_model=32, n_heads=4, window=10, horizon=3):
            super().__init__()
            self.input_proj = nn.Linear(in_features, d_model)
            self.attn = nn.MultiheadAttention(d_model, n_heads, batch_first=True)
            self.norm = nn.LayerNorm(d_model)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            h = self.input_proj(x)
            attn_out, _ = self.attn(h, h, h)
            h = self.norm(h + attn_out)
            return self.head(h.flatten(1))

    # ── 8. DLinear（trend + seasonal 双分支） ───
    class DLinearTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, horizon=3, kernel=5):
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.in_features = in_features
            self.kernel = kernel
            # 趋势分支：moving average → Linear
            self.trend_linear = nn.Linear(window, horizon)
            # 季节分支：x - trend → Linear
            self.seasonal_linear = nn.Linear(window, horizon)
            # 多变量合并
            self.combine = nn.Linear(horizon * in_features, horizon)

        def forward(self, x):
            # x: [B, W, F]
            B, W, F = x.shape
            # 用窗口左右 padding 的 1D moving average
            pad = self.kernel // 2
            x_t = x.transpose(1, 2)  # [B, F, W]
            x_pad = nn_pad1d(x_t, pad, pad)
            trend = nn_avg_pool1d(x_pad, self.kernel, stride=1)  # [B, F, W]
            seasonal = x_t - trend  # [B, F, W]
            trend_out = self.trend_linear(trend)  # [B, F, H]
            seasonal_out = self.seasonal_linear(seasonal)  # [B, F, H]
            y = trend_out + seasonal_out  # [B, F, H]
            return self.combine(y.transpose(1, 2).flatten(1))  # [B, H]

    # ── 9. N-BEATS（block stacking） ─────────────
    class NBeatsTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, horizon=3, n_blocks=3, hidden=64):
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.blocks = nn.ModuleList()
            for _ in range(n_blocks):
                self.blocks.append(
                    nn.Sequential(
                        nn.Linear(window * in_features, hidden),
                        nn.GELU(),
                        nn.Linear(hidden, window * in_features + horizon),
                    )
                )

        def forward(self, x):
            B = x.shape[0]
            res = x.flatten(1)  # [B, W*F]
            forecast = torch.zeros(B, self.horizon, device=x.device)
            for block in self.blocks:
                out = block(res)
                backcast = out[:, : res.shape[1]]
                f = out[:, res.shape[1] :]
                res = res - backcast
                forecast = forecast + f
            return forecast

    # ── 10. PatchTST（Patch + Transformer） ────
    class PatchTSTTorchModel(nn.Module):
        def __init__(
            self, in_features=5, window=10, horizon=3, patch_len=4, stride=2, d_model=32, n_heads=4, n_layers=2
        ):
            super().__init__()
            self.patch_len = patch_len
            self.stride = stride
            self.in_features = in_features
            # 估算 patch 数
            self.n_patches = max(1, (window - patch_len) // stride + 1)
            self.patch_proj = nn.Linear(patch_len * in_features, d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model,
                n_heads,
                dim_feedforward=64,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
            self.head = nn.Linear(d_model * self.n_patches, horizon)

        def forward(self, x):
            # x: [B, W, F]，切 patch
            patches = []
            for s in range(0, x.shape[1] - self.patch_len + 1, self.stride):
                patches.append(x[:, s : s + self.patch_len, :].flatten(1))
            if not patches:
                patches.append(x[:, : self.patch_len, :].flatten(1))
            p = torch.stack(patches, dim=1)  # [B, N, P*F]
            z = self.patch_proj(p)  # [B, N, D]
            z = self.encoder(z)
            return self.head(z.flatten(1))

    # ── 11. Informer（ProbSparse 简化版） ──────
    class InformerTorchModel(nn.Module):
        """简化 Informer：用稀疏 Top-K 注意力替代 ProbSparse。"""

        def __init__(self, in_features=5, d_model=32, n_heads=2, window=10, horizon=3, top_k_ratio=0.5):
            super().__init__()
            self.proj = nn.Linear(in_features, d_model)
            self.qkv = nn.Linear(d_model, 3 * d_model)
            self.heads = n_heads
            self.dk = d_model // n_heads
            self.top_k_ratio = top_k_ratio
            self.norm = nn.LayerNorm(d_model)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            qkv = self.qkv(h).reshape(B, W, 3, self.heads, self.dk).permute(2, 0, 3, 1, 4)
            q, k, v = qkv[0], qkv[1], qkv[2]  # [B, H, W, dk]
            scores = (q @ k.transpose(-2, -1)) / np.sqrt(self.dk)
            # Top-K mask
            top_k = max(1, int(W * self.top_k_ratio))
            top_vals, _ = scores.topk(top_k, dim=-1)
            kth = top_vals[..., -1:].expand_as(scores)
            mask = scores < kth
            scores = scores.masked_fill(mask, float("-inf"))
            attn = scores.softmax(dim=-1)
            attn = torch.nan_to_num(attn, nan=0.0)
            out = (attn @ v).permute(0, 2, 1, 3).reshape(B, W, D)
            out = self.norm(out + h)
            return self.head(out.flatten(1))

    # ── 12. TFT（Variable Selection + LSTM + Attn） ──
    class TFTTorchModel(nn.Module):
        def __init__(self, in_features=5, hidden=32, horizon=3, n_heads=4):
            super().__init__()
            # Variable selection: gate over features
            self.var_gate = nn.Sequential(
                nn.Linear(in_features, in_features),
                nn.Sigmoid(),
            )
            self.lstm = nn.LSTM(in_features, hidden, batch_first=True)
            self.attn = nn.MultiheadAttention(hidden, n_heads, batch_first=True)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            gate = self.var_gate(x.mean(dim=1, keepdim=True))
            x = x * gate
            out, _ = self.lstm(x)
            attn_out, _ = self.attn(out, out, out)
            return self.head((out + attn_out)[:, -1, :])

    # ── 13. TimesNet（period-based FFT） ───────
    class TimessNetTorchModel(nn.Module):
        def __init__(self, in_features=5, d_model=32, window=10, horizon=3, top_k=2):
            super().__init__()
            self.proj = nn.Linear(in_features, d_model)
            self.top_k = top_k
            self.conv = nn.Conv2d(d_model, d_model, 3, padding=1)
            self.norm = nn.LayerNorm(d_model)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            # x: [B, W, F]
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # FFT 找 top_k 周期
            ft = torch.fft.rfft(h, dim=1)
            amps = ft.abs().mean(dim=(0, 2))
            amps[0] = 0  # 排除直流
            top_idx = amps.topk(min(self.top_k, amps.shape[0])).indices
            outs = []
            for p_idx in top_idx:
                period = max(2, W // max(1, int(p_idx.item())))
                pad = (period - W % period) % period
                h_pad = torch.nn.functional.pad(h, (0, 0, 0, pad))
                # 重塑成 [B, n_period, period, D]
                reshaped = h_pad.reshape(B, -1, period, D).permute(0, 3, 1, 2)
                conv_out = self.conv(reshaped)  # [B, D, n, p]
                outs.append(conv_out.permute(0, 2, 3, 1).reshape(B, -1, D)[:, :W])
            agg = torch.stack(outs, dim=0).mean(dim=0) if outs else h
            agg = self.norm(agg + h)
            return self.head(agg.flatten(1))

    # ── 14. TIDE（残差 MLP 编码器） ─────────────
    class TIDETorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, hidden=64, horizon=3):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Flatten(),
                nn.Linear(window * in_features, hidden),
                nn.GELU(),
                nn.Linear(hidden, hidden),
                nn.GELU(),
            )
            self.decoder = nn.Linear(hidden, horizon)
            self.residual = nn.Linear(window * in_features, horizon)

        def forward(self, x):
            flat = x.flatten(1)
            return self.decoder(self.encoder(flat)) + self.residual(flat)

    # ── 15. TSMixer（时间维 + 通道维 MLP 交替混合） ──
    class TSMixerTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, hidden=64, horizon=3):
            super().__init__()
            self.time_mlp = nn.Sequential(
                nn.Linear(window, hidden),
                nn.GELU(),
                nn.Linear(hidden, window),
            )
            self.channel_mlp = nn.Sequential(
                nn.Linear(in_features, hidden),
                nn.GELU(),
                nn.Linear(hidden, in_features),
            )
            self.norm_time = nn.LayerNorm(window)
            self.norm_channel = nn.LayerNorm(in_features)
            self.head = nn.Linear(window * in_features, horizon)

        def forward(self, x):
            x_t = x.transpose(1, 2)
            x_t = x_t + self.time_mlp(self.norm_time(x_t))
            h = x_t.transpose(1, 2)
            h = h + self.channel_mlp(self.norm_channel(h))
            return self.head(h.flatten(1))

    # ── 16. DeepAR（GRU 自回归概率） ────────────
    class DeepARTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, hidden=32, horizon=3):
            super().__init__()
            self.gru = nn.GRU(in_features, hidden, batch_first=True)
            self.mu = nn.Linear(hidden, horizon)
            self.sigma = nn.Sequential(nn.Linear(hidden, horizon), nn.Softplus())

        def forward(self, x):
            out, _ = self.gru(x)
            h = out[:, -1, :]
            return self.mu(h) + self.sigma(h) * torch.randn_like(self.sigma(h)) * 0.01

    # ── 17. Chronos（轻量 T5 式编码器） ─────────
    class ChronosTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, d_model=32, n_heads=2, horizon=3):
            super().__init__()
            self.proj = nn.Linear(in_features, d_model)
            encoder_layer = nn.TransformerEncoderLayer(d_model, n_heads, dim_feedforward=64, batch_first=True)
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            h = self.proj(x)
            h = self.encoder(h)
            return self.head(h.flatten(1))

    # ── 18. Mamba S6（简化 SSM） ───────────────
    class MambaS6TorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, d_state=4, horizon=3):
            super().__init__()
            self.d_state = d_state
            self.proj = nn.Linear(in_features, d_state)
            self.A = nn.Parameter(torch.randn(d_state, d_state) * 0.01)
            self.B = nn.Linear(in_features, d_state)
            self.C = nn.Linear(d_state, 1)
            self.head = nn.Linear(d_state, horizon)

        def forward(self, x):
            B = x.shape[0]
            dt = 0.1
            state = torch.zeros(B, self.d_state, device=x.device)
            for t in range(x.shape[1]):
                b_t = self.B(x[:, t, :])
                state = state @ self.A.T + b_t * dt
            return self.head(state)

    # ── 19. iTransformer（变量作为 token） ─────
    class ITransformerTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, d_model=32, n_heads=4, horizon=3):
            super().__init__()
            self.var_proj = nn.Linear(window, d_model)
            encoder_layer = nn.TransformerEncoderLayer(d_model, n_heads, dim_feedforward=64, batch_first=True)
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
            self.head = nn.Linear(d_model * in_features, horizon)

        def forward(self, x):
            h = self.var_proj(x.transpose(1, 2))
            h = self.encoder(h)
            return self.head(h.flatten(1))

    # ── 20. SCINet（二叉树下采样卷积） ─────────
    class SCINetTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, hidden=16, horizon=3):
            super().__init__()
            self.conv_even = nn.Conv1d(in_features, hidden, 3, padding=1)
            self.conv_odd = nn.Conv1d(in_features, hidden, 3, padding=1)
            self.interact = nn.Conv1d(hidden * 2, hidden, 1)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            x = x.transpose(1, 2)
            even = self.conv_even(x[:, :, ::2])
            odd = self.conv_odd(x[:, :, 1::2])
            if even.shape[-1] > odd.shape[-1]:
                even = even[..., : odd.shape[-1]]
            diff = even - odd
            gate_e = torch.tanh(diff)
            gate_o = torch.tanh(-diff)
            even_out = even + gate_e * odd
            odd_out = odd + gate_o * even[..., : odd.shape[-1]]
            combined = torch.cat([even_out, odd_out], dim=1)
            h = self.interact(combined)
            h = h.mean(dim=-1)
            return self.head(h)

    # ── 21. TimesFM（Patch + Decoder） ──────────
    class TimesFMTorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, patch_len=4, d_model=32, n_heads=2, horizon=3):
            super().__init__()
            self.patch_len = min(patch_len, window)
            self.n_patches = max(1, window // self.patch_len)
            self.patch_proj = nn.Linear(self.patch_len * in_features, d_model)
            decoder_layer = nn.TransformerDecoderLayer(d_model, n_heads, dim_feedforward=64, batch_first=True)
            self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=2)
            self.tgt = nn.Parameter(torch.randn(1, horizon, d_model) * 0.01)
            self.head = nn.Linear(d_model, 1)

        def forward(self, x):
            B = x.shape[0]
            patches = []
            for s in range(0, x.shape[1] - self.patch_len + 1, self.patch_len):
                patches.append(x[:, s : s + self.patch_len, :].flatten(1))
            if not patches:
                patches.append(x[:, : self.patch_len, :].flatten(1))
            p = torch.stack(patches, dim=1)
            mem = self.patch_proj(p)
            tgt = self.tgt.expand(B, -1, -1)
            h = self.decoder(tgt, mem)
            return self.head(h).squeeze(-1)

    # ── 22. Time-MoE（轻量专家混合） ───────────
    class TimeMoETorchModel(nn.Module):
        def __init__(self, in_features=5, window=10, n_experts=4, d_model=16, horizon=3):
            super().__init__()
            self.n_experts = n_experts
            self.proj = nn.Linear(window * in_features, d_model)
            self.gate = nn.Linear(d_model, n_experts)
            self.experts = nn.ModuleList(
                [
                    nn.Sequential(nn.Linear(d_model, d_model), nn.GELU(), nn.Linear(d_model, horizon))
                    for _ in range(n_experts)
                ]
            )

        def forward(self, x):
            h = self.proj(x.flatten(1))
            gates = self.gate(h).softmax(dim=-1)
            out = sum(gates[:, i : i + 1] * self.experts[i](h) for i in range(self.n_experts))
            return out

    # ── 工具：手写 1D padding + avg pool（避免与外部 import 冲突） ──
    def nn_pad1d(x, left, right):
        return torch.nn.functional.pad(x, (left, right), mode="replicate")

    def nn_avg_pool1d(x, kernel, stride=1):
        return torch.nn.functional.avg_pool1d(x, kernel, stride=stride)

else:
    # 占位：torch 不可用时让 import 不爆
    LSTMTorchModel = None  # type: ignore
    GRUTorchModel = None  # type: ignore
    BiLSTMTorchModel = None  # type: ignore
    MLPTorchModel = None  # type: ignore
    TCNTorchModel = None  # type: ignore
    CNNLSTMTorchModel = None  # type: ignore
    AttentionTorchModel = None  # type: ignore
    DLinearTorchModel = None  # type: ignore
    NBeatsTorchModel = None  # type: ignore
    PatchTSTTorchModel = None  # type: ignore
    InformerTorchModel = None  # type: ignore
    TFTTorchModel = None  # type: ignore
    TimessNetTorchModel = None  # type: ignore
    TIDETorchModel = None  # type: ignore
    TSMixerTorchModel = None  # type: ignore
    DeepARTorchModel = None  # type: ignore
    ChronosTorchModel = None  # type: ignore
    MambaS6TorchModel = None  # type: ignore
    ITransformerTorchModel = None  # type: ignore
    SCINetTorchModel = None  # type: ignore
    TimesFMTorchModel = None  # type: ignore
    TimeMoETorchModel = None  # type: ignore


# ════════════════════════════════════════════════════════
#  统一的"torch → numpy 降级"调度器
# ════════════════════════════════════════════════════════


def try_torch_predict(
    algorithm,
    video_data: Dict[str, Any],
    threshold: int,
    model_cls: type,
    fallback_fn: Callable,
    model_kwargs: Dict[str, Any] = None,
    features: List[str] = None,
    window: int = DEFAULT_WINDOW,
    horizon: int = DEFAULT_HORIZON,
):
    """统一的预测入口：torch 推理 → numpy 降级。

    Args:
        algorithm: 算法实例（需有 `_ckpt`, `_device`, `_cached_torch_model` 属性，name/algorithm_id）
        video_data: 视频数据
        threshold: 阈值
        model_cls: 该算法对应的 torch 模型类（如 LSTMTorchModel）
        fallback_fn: 失败时调用的 numpy predict 函数，签名为 (video_data, threshold) -> PredictionResult
        model_kwargs: 实例化 model_cls 时的额外参数
        features: 输入特征列表
        window: 输入窗口长度
        horizon: 预测步数

    Returns:
        PredictionResult
    """
    if not _torch_available or model_cls is None:
        return fallback_fn(video_data, threshold)

    # 懒加载 checkpoint manager + device
    if not hasattr(algorithm, "_ckpt"):
        from algorithms.training.checkpoint_manager import CheckpointManager

        algorithm._ckpt = CheckpointManager(getattr(algorithm, "algorithm_id", "unknown"))
    if not hasattr(algorithm, "_device"):
        from algorithms.training.device import get_device

        algorithm._device = get_device()

    # 优先加载视频微调 checkpoint，回退到全局
    from algorithms.training.checkpoint_manager import load_best_checkpoint

    algo_id = getattr(algorithm, "algorithm_id", "unknown")
    bvid = video_data.get("bvid", "")
    state, model_source = load_best_checkpoint(algo_id, bvid=bvid)
    if state is None:
        return fallback_fn(video_data, threshold)

    try:
        feats = features or DEFAULT_FEATURES
        x_arr, v_mean, v_std = _build_torch_input(video_data, feats, window)
        if x_arr is None:
            return fallback_fn(video_data, threshold)

        model = getattr(algorithm, "_cached_torch_model", None)
        if model is None or (bvid and not getattr(algorithm, "_cached_bvid", "") == bvid):
            mk = dict(model_kwargs or {})
            # 真实特征数 = 基础特征 + 5 个衍生特征（roll_mean/roll_std/accel/rel_pos/lifecycle）
            mk["in_features"] = len(feats) + 5
            model = model_cls(**mk)
            if isinstance(state, (tuple, list)):
                state = state[0]
            if not isinstance(state, dict):
                logger.warning("[%s] checkpoint 格式异常 (type=%s)，跳过 torch 推理", algo_id, type(state).__name__)
                return fallback_fn(video_data, threshold)
            model.load_state_dict(state)
            model.to(algorithm._device).eval()
            algorithm._cached_torch_model = model
            algorithm._cached_bvid = bvid or ""

        device = next(model.parameters()).device
        x = torch.from_numpy(x_arr).unsqueeze(0).to(device)
        with torch.no_grad():
            y = model(x).cpu().numpy().reshape(-1)
        predicted_velocity = max(0.0, float(y[0]) * v_std + v_mean)

        return _generic_result(algorithm, video_data, threshold, predicted_velocity, y, model_source=model_source)

    except Exception as e:
        logger.warning("[%s] torch 推理失败，降级 numpy: %s", getattr(algorithm, "algorithm_id", "?"), e)
        return fallback_fn(video_data, threshold)


def _add_derived_features(arr: np.ndarray) -> np.ndarray:
    """为 [N, F] 的特征数组追加 5 个衍生特征，返回 [N, F+5]。

    衍生特征（与 dataset.VideoTimeSeriesDataset 保持一致）：
        roll_mean_5, roll_std_5, acceleration, relative_pos, lifecycle_phase
    """
    target = arr[:, 0]  # view_count
    N = arr.shape[0]
    # rolling mean (window=5)
    if N >= 5:
        kernel = np.ones(5, dtype=np.float32) / 5
        roll_mean = np.convolve(target, kernel, mode="same")
    else:
        roll_mean = np.full(N, float(target.mean()))
    # rolling std (window=5)
    if N >= 5:
        roll_std = np.array([float(np.std(target[max(0, i - 2) : min(N, i + 3)])) for i in range(N)], dtype=np.float32)
    else:
        roll_std = np.full(N, float(target.std() or 1.0))
    # 加速度（view_count 的二阶差分）
    velocity = np.diff(target, prepend=target[0]).astype(np.float32)
    accel = np.diff(velocity, prepend=velocity[0]).astype(np.float32)
    # 相对时间位置 [0, 1]
    rel_pos = np.arange(N, dtype=np.float32) / max(N - 1, 1)
    # 生命周期阶段
    lifecycle_phase = np.where(rel_pos < 0.2, 0.0, np.where(rel_pos < 0.6, 1.0, 2.0)).astype(np.float32)
    extras = np.column_stack([roll_mean, roll_std, accel, rel_pos, lifecycle_phase])
    return np.column_stack([arr, extras])


def _build_torch_input(video_data, features, window):
    """构造 z-score 归一化的 [W, F+5] 输入（含衍生特征），并返回速度的均值/方差用于反归一化。"""
    history = video_data.get("history_data", [])
    if len(history) < 3:
        return None, 0.0, 1.0
    n = window
    arr = np.zeros((n, len(features)), dtype=np.float32)
    recent = history[-n:] if len(history) >= n else history
    offset = n - len(recent)
    for i, e in enumerate(recent):
        for j, f in enumerate(features):
            arr[offset + i, j] = float(e.get(f, 0) or 0)

    arr_ext = _add_derived_features(arr)
    mean = arr_ext.mean(axis=0, keepdims=True)
    std = arr_ext.std(axis=0, keepdims=True)
    std = np.where(std < 1e-8, 1.0, std)
    arr_n = ((arr_ext - mean) / std).astype(np.float32)

    velocities = _velocity_series(history)
    v_mean = float(np.mean(velocities)) if velocities else 0.0
    v_std = float(np.std(velocities)) if len(velocities) > 1 else 1.0
    if v_std < 1e-8:
        v_std = 1.0
    return arr_n, v_mean, v_std


def _velocity_series(history):
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


def _generic_result(algorithm, video_data, threshold, velocity, y, model_source=None):
    from datetime import datetime
    from algorithms.base import PredictionResult

    current_views = int(video_data.get("view_count", 0))
    if velocity <= 0:
        predicted_hours = float("inf")
        confidence = 0.0
    else:
        remaining = threshold - current_views
        predicted_hours = 0 if remaining <= 0 else remaining / velocity
        confidence = 0.75 if remaining > 0 else 1.0
    metadata = {
        "reason": "torch_inference",
        "horizon_pred": y.tolist() if hasattr(y, "tolist") else list(y),
        "method": getattr(algorithm, "algorithm_id", "?") + "_torch",
    }
    if model_source:
        metadata["model_source"] = model_source
    return PredictionResult(
        algorithm_name=getattr(algorithm, "name", "?"),
        algorithm_id=getattr(algorithm, "algorithm_id", "?"),
        target_threshold=threshold,
        predicted_hours=predicted_hours,
        confidence=confidence,
        current_views=current_views,
        current_velocity=float(velocity),
        metadata={
            "reason": "torch_inference",
            "horizon_pred": y.tolist() if hasattr(y, "tolist") else list(y),
            "method": getattr(algorithm, "algorithm_id", "?") + "_torch",
        },
        timestamp=datetime.now(),
    )
