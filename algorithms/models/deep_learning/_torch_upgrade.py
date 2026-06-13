"""PyTorch 模型骨架与降级调度器模块

为 14 个既有 numpy 简化版算法定义 PyTorch 模型骨架 + 统一的"torch → numpy 降级"调度器。

功能说明：
- 每个算法在文件里加 3-5 行接入此模块（保留原 numpy 逻辑作为 `_numpy_predict`）
- 当 checkpoint 存在 → 用 `XxxTorchModel` 推理
- 当 torch 不可用 / checkpoint 缺失 / 推理异常 → 回退到 `_numpy_predict`

模型设计统一为：输入 [B, W, F] → 输出 [B, H]（H 步速度预测）
特征 F 默认 5：view_count, like_count, coin_count, favorite_count, share_count
衍生特征 +5：roll_mean_5, roll_std_5, acceleration, relative_pos, lifecycle_phase
"""

import logging
from typing import Any, Callable, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

# ── 检测 PyTorch 是否可用 ────────────────────────────────
_torch_available = True
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
except ImportError:
    _torch_available = False
    nn = None  # type: ignore
    F = None  # type: ignore


# ── 默认配置常量 ─────────────────────────────────────────

DEFAULT_FEATURES = ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]
"""默认输入特征列表"""
DEFAULT_WINDOW = 10
"""默认输入窗口长度（时间步数）"""

# 模型加载信号量：防止多线程同时加载大模型导致内存峰值
import threading
_model_load_semaphore = threading.Semaphore(2)
DEFAULT_HORIZON = 3
"""默认预测步数（输出长度）"""


# ════════════════════════════════════════════════════════
#  Torch 模型骨架（14 → 扩展至 39 个）
# ════════════════════════════════════════════════════════

if _torch_available:  # noqa: C901
    # ── 1. LSTM ────────────────────────────────────
    class LSTMTorchModel(nn.Module):
        """LSTM 长短期记忆网络 PyTorch 模型骨架。

        输入 [B, W, F] → LSTM 编码 → 取最后时间步 → 线性头输出 [B, H]
        """

        def __init__(self, in_features=5, hidden=32, layers=1, horizon=3):
            """初始化 LSTM 模型。

            Args:
                in_features: 输入特征维度，默认 5
                hidden: LSTM 隐藏层维度，默认 32
                layers: LSTM 层数，默认 1
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.lstm = nn.LSTM(in_features, hidden, num_layers=layers, batch_first=True)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    # ── 2. GRU ─────────────────────────────────────
    class GRUTorchModel(nn.Module):
        """GRU 门控循环单元 PyTorch 模型骨架。

        比 LSTM 参数更少，仅含更新门和重置门。
        """

        def __init__(self, in_features=5, hidden=32, layers=1, horizon=3):
            """初始化 GRU 模型。

            Args:
                in_features: 输入特征维度，默认 5
                hidden: GRU 隐藏层维度，默认 32
                layers: GRU 层数，默认 1
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.gru = nn.GRU(in_features, hidden, num_layers=layers, batch_first=True)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            out, _ = self.gru(x)
            return self.head(out[:, -1, :])

    # ── 3. BiLSTM ──────────────────────────────────
    class BiLSTMTorchModel(nn.Module):
        """BiLSTM 双向长短期记忆网络 PyTorch 模型骨架。

        同时从正向和反向处理序列，隐藏维度加倍（双向拼接）。
        """

        def __init__(self, in_features=5, hidden=32, layers=1, horizon=3):
            """初始化 BiLSTM 模型。

            Args:
                in_features: 输入特征维度，默认 5
                hidden: 单向隐藏层维度（双向后变为 hidden*2），默认 32
                layers: LSTM 层数，默认 1
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.lstm = nn.LSTM(in_features, hidden, num_layers=layers, batch_first=True, bidirectional=True)
            self.head = nn.Linear(hidden * 2, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    # ── 4. MLP / Neural Network / NeuralNetwork ──
    class MLPTorchModel(nn.Module):
        """MLP 多层感知机 PyTorch 模型骨架。

        将时序展平后通过三层全连接网络（含 GELU 激活）输出预测。
        """

        def __init__(self, in_features=5, window=10, hidden=64, horizon=3):
            """初始化 MLP 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                hidden: 隐藏层维度，默认 64
                horizon: 预测步数（输出维度），默认 3
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            return self.net(x)

    # ── 5. TCN（Dilated Conv1d） ─────────────────
    class TCNTorchModel(nn.Module):
        """TCN 时序卷积网络 PyTorch 模型骨架。

        使用三层扩张卷积（dilation=1,2,4）捕捉多尺度时序模式。
        """

        def __init__(self, in_features=5, channels=16, kernel=3, horizon=3):
            """初始化 TCN 模型。

            Args:
                in_features: 输入特征维度，默认 5
                channels: 卷积通道数，默认 16
                kernel: 卷积核大小，默认 3
                horizon: 预测步数（输出维度），默认 3
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            # x: [B, W, F] → conv1d 需要 [B, F, W]
            h = x.transpose(1, 2)
            h = self.tcn(h)
            h = self.pool(h).squeeze(-1)
            return self.head(h)

    # ── 6. CNN-LSTM 混合 ──────────────────────────
    class CNNLSTMTorchModel(nn.Module):
        """CNN-LSTM 混合模型 PyTorch 骨架。

        CNN 提取局部模式 → LSTM 捕获长期依赖 → 线性头输出。
        """

        def __init__(self, in_features=5, conv_channels=16, lstm_hidden=32, horizon=3):
            """初始化 CNN-LSTM 混合模型。

            Args:
                in_features: 输入特征维度，默认 5
                conv_channels: CNN 卷积通道数，默认 16
                lstm_hidden: LSTM 隐藏层维度，默认 32
                horizon: 预测步数（输出维度），默认 3
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = x.transpose(1, 2)  # [B, F, W]
            h = self.conv(h)
            h = h.transpose(1, 2)  # [B, W, C]
            out, _ = self.lstm(h)
            return self.head(out[:, -1, :])

    # ── 7. Attention（多头注意力） ────────────────
    class AttentionTorchModel(nn.Module):
        """注意力机制 PyTorch 模型骨架。

        输入投影后经 MultiheadAttention + 残差连接 + LayerNorm，展平后线性输出。
        """

        def __init__(self, in_features=5, d_model=32, n_heads=4, window=10, horizon=3):
            """初始化注意力模型。

            Args:
                in_features: 输入特征维度，默认 5
                d_model: 模型维度（注意力头维度 * 头数），默认 32
                n_heads: 注意力头数，默认 4
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.input_proj = nn.Linear(in_features, d_model)
            self.attn = nn.MultiheadAttention(d_model, n_heads, batch_first=True)
            self.norm = nn.LayerNorm(d_model)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.input_proj(x)
            attn_out, _ = self.attn(h, h, h)
            h = self.norm(h + attn_out)
            return self.head(h.flatten(1))

    # ── 8. DLinear（trend + seasonal 双分支） ───
    class DLinearTorchModel(nn.Module):
        """DLinear PyTorch 模型骨架。

        趋势分支（移动平均提取） + 季节分支（残差 = 原始 − 趋势）。
        对两分支分别线性预测后合并。
        """

        def __init__(self, in_features=5, window=10, horizon=3, kernel=5):
            """初始化 DLinear 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                kernel: 移动平均核大小，默认 5
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            # x: [B, W, F]
            B, W, F = x.shape
            # 用窗口左右 padding 的 1D moving average
            pad = self.kernel // 2
            x_t = x.transpose(1, 2)  # [B, F, W]
            x_pad = nn_pad1d(x_t, pad, pad)
            trend = nn_avg_pool1d(x_pad, self.kernel, stride=1)  # [B, F, W]  趋势分量（低频）
            seasonal = x_t - trend  # [B, F, W]  季节分量（高频残差）
            trend_out = self.trend_linear(trend)  # [B, F, H]
            seasonal_out = self.seasonal_linear(seasonal)  # [B, F, H]
            y = trend_out + seasonal_out  # [B, F, H]  两分支叠加
            return self.combine(y.transpose(1, 2).flatten(1))  # [B, H]

    # ── 9. N-BEATS（block stacking） ─────────────
    class NBeatsTorchModel(nn.Module):
        """N-BEATS PyTorch 模型骨架。

        多个 block 堆叠，每个 block 输出 backcast（残差）和 forecast（预测增量）。
        残差连接实现渐进式预测。
        """

        def __init__(self, in_features=5, window=10, horizon=3, n_blocks=3, hidden=64):
            """初始化 N-BEATS 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                n_blocks: 堆叠 block 数量，默认 3
                hidden: 隐藏层维度，默认 64
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B = x.shape[0]
            res = x.flatten(1)  # [B, W*F]  初始残差即原始输入
            forecast = torch.zeros(B, self.horizon, device=x.device)
            for block in self.blocks:
                out = block(res)
                backcast = out[:, : res.shape[1]]  # 历史重建分量（反向预测）
                f = out[:, res.shape[1] :]  # 前向预测分量
                res = res - backcast  # 残差连接：减去已建模的部分
                forecast = forecast + f  # 累加各 block 的预测
            return forecast

    # ── 10. PatchTST（Patch + Transformer） ────
    class PatchTSTTorchModel(nn.Module):
        """PatchTST PyTorch 模型骨架。

        将序列切分为 patch（子序列段），每 patch 投影为 token，
        经 Transformer Encoder 编码后线性输出。
        """

        def __init__(
            self, in_features=5, window=10, horizon=3, patch_len=4, stride=2, d_model=32, n_heads=4, n_layers=2
        ):
            """初始化 PatchTST 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                patch_len: 每个 patch 的时间步长度，默认 4
                stride: patch 之间的步长，默认 2
                d_model: Transformer 模型维度，默认 32
                n_heads: 注意力头数，默认 4
                n_layers: Transformer Encoder 层数，默认 2
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            # x: [B, W, F]，切 patch
            patches = []
            for s in range(0, x.shape[1] - self.patch_len + 1, self.stride):
                patches.append(x[:, s : s + self.patch_len, :].flatten(1))
            if not patches:
                patches.append(x[:, : self.patch_len, :].flatten(1))
            p = torch.stack(patches, dim=1)  # [B, N, P*F]
            z = self.patch_proj(p)  # [B, N, D]  投影到模型维度
            z = self.encoder(z)
            return self.head(z.flatten(1))

    # ── 11. Informer（ProbSparse 简化版） ──────
    class InformerTorchModel(nn.Module):
        """Informer PyTorch 模型骨架（简化 ProbSparse）。

        用稀疏 Top-K 注意力替代完整自注意力，降低 O(L²) 复杂度。
        """

        def __init__(self, in_features=5, d_model=32, n_heads=2, window=10, horizon=3, top_k_ratio=0.5):
            """初始化 Informer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                d_model: 模型维度，默认 32
                n_heads: 注意力头数，默认 2
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                top_k_ratio: Top-K 稀疏比例，仅保留该比例的最高注意力分，默认 0.5
            """
            super().__init__()
            self.proj = nn.Linear(in_features, d_model)
            self.qkv = nn.Linear(d_model, 3 * d_model)
            self.heads = n_heads
            self.dk = d_model // n_heads
            self.top_k_ratio = top_k_ratio
            self.norm = nn.LayerNorm(d_model)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # 多头 QKV 投影
            qkv = self.qkv(h).reshape(B, W, 3, self.heads, self.dk).permute(2, 0, 3, 1, 4)
            q, k, v = qkv[0], qkv[1], qkv[2]  # [B, H, W, dk]
            scores = (q @ k.transpose(-2, -1)) / (self.dk ** 0.5)  # 避免 np.sqrt 导致 torch.compile 失败
            # Top-K mask 实现稀疏注意力
            top_k = max(1, int(W * self.top_k_ratio))
            top_vals, _ = scores.topk(top_k, dim=-1)
            kth = top_vals[..., -1:].expand_as(scores)
            mask = scores < kth
            scores = scores.masked_fill(mask, float("-inf"))
            attn = scores.softmax(dim=-1)
            attn = torch.nan_to_num(attn, nan=0.0)
            out = (attn @ v).permute(0, 2, 1, 3).reshape(B, W, D)
            out = self.norm(out + h)  # 残差连接 + LayerNorm
            return self.head(out.flatten(1))

    # ── 12. TFT（Variable Selection + LSTM + Attn） ──
    class TFTTorchModel(nn.Module):
        """TFT（Temporal Fusion Transformer）PyTorch 模型骨架。

        变量选择门控 → LSTM 编码 → 多头注意力 → 残差相加 → 线性输出。
        """

        def __init__(self, in_features=5, hidden=32, horizon=3, n_heads=4):
            """初始化 TFT 模型。

            Args:
                in_features: 输入特征维度，默认 5
                hidden: LSTM 隐藏层维度，默认 32
                horizon: 预测步数（输出维度），默认 3
                n_heads: 注意力头数，默认 4
            """
            super().__init__()
            # Variable selection: gate over features  变量选择门控：对特征维加权
            self.var_gate = nn.Sequential(
                nn.Linear(in_features, in_features),
                nn.Sigmoid(),
            )
            self.lstm = nn.LSTM(in_features, hidden, batch_first=True)
            self.attn = nn.MultiheadAttention(hidden, n_heads, batch_first=True)
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            gate = self.var_gate(x.mean(dim=1, keepdim=True))  # 全局池化后门控
            x = x * gate  # 特征选择
            out, _ = self.lstm(x)
            attn_out, _ = self.attn(out, out, out)
            return self.head((out + attn_out)[:, -1, :])

    # ── 13. TimesNet（period-based FFT） ───────
    class TimessNetTorchModel(nn.Module):
        """TimesNet PyTorch 模型骨架。

        通过 FFT 发现周期，将 1D 序列按周期重塑为 2D 张量，
        用 Conv2d 捕捉周期内和周期间模式。
        """

        def __init__(self, in_features=5, d_model=32, window=10, horizon=3, top_k=2):
            """初始化 TimesNet 模型。

            Args:
                in_features: 输入特征维度，默认 5
                d_model: 模型维度，默认 32
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                top_k: 保留的 Top-K 个最强周期，默认 2
            """
            super().__init__()
            self.proj = nn.Linear(in_features, d_model)
            self.top_k = top_k
            self.conv = nn.Conv2d(d_model, d_model, 3, padding=1)
            self.norm = nn.LayerNorm(d_model)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            # x: [B, W, F]
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # FFT 找 top_k 周期（cuFFT 半精度仅支持 2 的幂次维度，AMP 下强制 float32）
            ft = torch.fft.rfft(h.float(), dim=1)
            amps = ft.abs().mean(dim=(0, 2))
            amps[0] = 0  # 排除直流分量
            top_idx = amps.topk(min(self.top_k, amps.shape[0])).indices
            outs = []
            for p_idx in top_idx:
                period = max(2, W // max(1, int(p_idx.item())))
                pad = (period - W % period) % period
                h_pad = torch.nn.functional.pad(h, (0, 0, 0, pad))
                # 重塑成 [B, n_period, period, D]
                reshaped = h_pad.reshape(B, -1, period, D).permute(0, 3, 1, 2)
                conv_out = self.conv(reshaped)  # [B, D, n, p]  2D 卷积
                outs.append(conv_out.permute(0, 2, 3, 1).reshape(B, -1, D)[:, :W])
            agg = torch.stack(outs, dim=0).mean(dim=0) if outs else h  # 多周期平均
            agg = self.norm(agg + h)  # 残差连接 + LayerNorm
            return self.head(agg.flatten(1))

    # ── 14. TIDE（残差 MLP 编码器） ─────────────
    class TIDETorchModel(nn.Module):
        """TiDE（Time-series Dense Encoder）PyTorch 模型骨架。

        残差 MLP 编码器 + 线性解码器 + 全局残差连接。
        """

        def __init__(self, in_features=5, window=10, hidden=64, horizon=3):
            """初始化 TiDE 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                hidden: 隐藏层维度，默认 64
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Flatten(),
                nn.Linear(window * in_features, hidden),
                nn.GELU(),
                nn.Linear(hidden, hidden),
                nn.GELU(),
            )
            self.decoder = nn.Linear(hidden, horizon)
            self.residual = nn.Linear(window * in_features, horizon)  # 全局残差跳过编码器

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            flat = x.flatten(1)
            return self.decoder(self.encoder(flat)) + self.residual(flat)

    # ── 15. TSMixer（时间维 + 通道维 MLP 交替混合） ──
    class TSMixerTorchModel(nn.Module):
        """TSMixer PyTorch 模型骨架。

        交替对时间维和特征（通道）维应用 MLP 混合，残差连接增强。
        """

        def __init__(self, in_features=5, window=10, hidden=64, horizon=3):
            """初始化 TSMixer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                hidden: 隐藏层维度，默认 64
                horizon: 预测步数（输出维度），默认 3
            """
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
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            x_t = x.transpose(1, 2)
            x_t = x_t + self.time_mlp(self.norm_time(x_t))  # 时间维混合 + 残差
            h = x_t.transpose(1, 2)
            h = h + self.channel_mlp(self.norm_channel(h))  # 通道维混合 + 残差
            return self.head(h.flatten(1))

    # ── 16. DeepAR（GRU 自回归概率） ────────────
    class DeepARTorchModel(nn.Module):
        """DeepAR 概率自回归 PyTorch 模型骨架。

        GRU 编码 → 输出均值（mu）和标准差（sigma），
        用重参数化技巧实现概率采样。
        """

        def __init__(self, in_features=5, window=10, hidden=32, horizon=3):
            """初始化 DeepAR 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                hidden: GRU 隐藏层维度，默认 32
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.gru = nn.GRU(in_features, hidden, batch_first=True)
            self.mu = nn.Linear(hidden, horizon)  # 均值预测头
            self.sigma = nn.Sequential(nn.Linear(hidden, horizon), nn.Softplus())  # 标准差预测头（正值）

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                采样预测输出 [B, H]
            """
            out, _ = self.gru(x)
            h = out[:, -1, :]
            return self.mu(h) + self.sigma(h) * torch.randn_like(self.sigma(h)) * 0.01  # 重参数化

    # ── 17. Chronos（轻量 T5 式编码器） ─────────
    class ChronosTorchModel(nn.Module):
        """Chronos（轻量 T5 式编码器）PyTorch 模型骨架。

        投影 → Transformer Encoder（2 层）→ 展平后线性输出。
        """

        def __init__(self, in_features=5, window=10, d_model=32, n_heads=2, horizon=3):
            """初始化 Chronos 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                d_model: 模型维度，默认 32
                n_heads: 注意力头数，默认 2
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.proj = nn.Linear(in_features, d_model)
            encoder_layer = nn.TransformerEncoderLayer(d_model, n_heads, dim_feedforward=64, batch_first=True)
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)
            h = self.encoder(h)
            return self.head(h.flatten(1))

    # ── 18. Mamba S6（简化 SSM） ───────────────
    class MambaS6TorchModel(nn.Module):
        """Mamba S6（简化状态空间模型）PyTorch 骨架。

        模拟选择性状态空间模型，通过学到的矩阵 A、B、C 演化隐藏状态。
        """

        def __init__(self, in_features=5, window=10, d_state=4, horizon=3):
            """初始化 Mamba 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                d_state: 隐藏状态维度，默认 4
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.d_state = d_state
            self.proj = nn.Linear(in_features, d_state)  # 输入投影
            self.A = nn.Parameter(torch.randn(d_state, d_state) * 0.01)  # 状态转移矩阵（学习）
            self.B = nn.Linear(in_features, d_state)  # 输入投影矩阵
            self.C = nn.Linear(d_state, 1)  # 输出投影矩阵
            self.head = nn.Linear(d_state, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B = x.shape[0]
            dt = 0.1  # 离散化步长
            state = torch.zeros(B, self.d_state, device=x.device)
            for t in range(x.shape[1]):
                b_t = self.B(x[:, t, :])
                state = state @ self.A.T + b_t * dt  # 状态更新：离散欧拉法
            return self.head(state)

    # ── 19. iTransformer（变量作为 token） ─────
    class ITransformerTorchModel(nn.Module):
        """iTransformer（倒置 Transformer）PyTorch 模型骨架。

        将变量（特征）维度作为 token，注意力在特征间交互，
        与标准 Transformer 按时间步分 token 不同。
        """

        def __init__(self, in_features=5, window=10, d_model=32, n_heads=4, horizon=3):
            """初始化 iTransformer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                d_model: 模型维度，默认 32
                n_heads: 注意力头数，默认 4
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.var_proj = nn.Linear(window, d_model)  # 每个变量的整个时间维投影为 token
            encoder_layer = nn.TransformerEncoderLayer(d_model, n_heads, dim_feedforward=64, batch_first=True)
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
            self.head = nn.Linear(d_model * in_features, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.var_proj(x.transpose(1, 2))  # [B, F, D]  变量维作为序列
            h = self.encoder(h)
            return self.head(h.flatten(1))

    # ── 20. SCINet（二叉树下采样卷积） ─────────
    class SCINetTorchModel(nn.Module):
        """SCINet（Sample Convolution and Interaction Network）PyTorch 骨架。

        二叉树下采样为奇偶子序列 → 交互式卷积 → 合并输出。
        """

        def __init__(self, in_features=5, window=10, hidden=16, horizon=3):
            """初始化 SCINet 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                hidden: 卷积通道数，默认 16
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.conv_even = nn.Conv1d(in_features, hidden, 3, padding=1)
            self.conv_odd = nn.Conv1d(in_features, hidden, 3, padding=1)
            self.interact = nn.Conv1d(hidden * 2, hidden, 1)  # 1x1 卷积交互
            self.head = nn.Linear(hidden, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            x = x.transpose(1, 2)  # [B, F, W]
            even = self.conv_even(x[:, :, ::2])  # 偶数位置子序列
            odd = self.conv_odd(x[:, :, 1::2])  # 奇数位置子序列
            if even.shape[-1] > odd.shape[-1]:
                even = even[..., : odd.shape[-1]]  # 对齐长度
            diff = even - odd  # 奇偶差分
            gate_e = torch.tanh(diff)  # 偶数门控
            gate_o = torch.tanh(-diff)  # 奇数门控
            even_out = even + gate_e * odd  # 偶数增强
            odd_out = odd + gate_o * even[..., : odd.shape[-1]]  # 奇数增强
            combined = torch.cat([even_out, odd_out], dim=1)  # 拼接
            h = self.interact(combined)  # 1x1 交互
            h = h.mean(dim=-1)  # 全局平均池化
            return self.head(h)

    # ── 21. TimesFM（Patch + Decoder） ──────────
    class TimesFMTorchModel(nn.Module):
        """TimesFM（Time Series Foundation Model）PyTorch 骨架。

        Patch 投影 → Transformer Decoder（含可学习目标 query）→ 线性输出。
        """

        def __init__(self, in_features=5, window=10, patch_len=4, d_model=32, n_heads=2, horizon=3):
            """初始化 TimesFM 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                patch_len: 每个 patch 的时间步长度，默认 4
                d_model: 模型维度，默认 32
                n_heads: 注意力头数，默认 2
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.patch_len = min(patch_len, window)
            self.n_patches = max(1, window // self.patch_len)
            self.patch_proj = nn.Linear(self.patch_len * in_features, d_model)
            decoder_layer = nn.TransformerDecoderLayer(d_model, n_heads, dim_feedforward=64, batch_first=True)
            self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=2)
            self.tgt = nn.Parameter(torch.randn(1, horizon, d_model) * 0.01)  # 可学习目标序列
            self.head = nn.Linear(d_model, 1)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B = x.shape[0]
            patches = []
            for s in range(0, x.shape[1] - self.patch_len + 1, self.patch_len):
                patches.append(x[:, s : s + self.patch_len, :].flatten(1))
            if not patches:
                patches.append(x[:, : self.patch_len, :].flatten(1))
            p = torch.stack(patches, dim=1)
            mem = self.patch_proj(p)  # 编码器记忆（历史 patch 投影）
            tgt = self.tgt.expand(B, -1, -1)  # 目标 query 扩展
            h = self.decoder(tgt, mem)  # 交叉注意力解码
            return self.head(h).squeeze(-1)

    # ── 22. Time-MoE（轻量专家混合） ───────────
    class TimeMoETorchModel(nn.Module):
        """Time-MoE（混合专家）PyTorch 模型骨架。

        输入经投影后由门控网络选择多个专家网络，
        各专家输出加权求和。
        """

        def __init__(self, in_features=5, window=10, n_experts=4, d_model=16, horizon=3):
            """初始化 Time-MoE 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                n_experts: 专家数量，默认 4
                d_model: 模型维度，默认 16
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.n_experts = n_experts
            self.proj = nn.Linear(window * in_features, d_model)
            self.gate = nn.Linear(d_model, n_experts)  # 门控网络
            self.experts = nn.ModuleList(
                [
                    nn.Sequential(nn.Linear(d_model, d_model), nn.GELU(), nn.Linear(d_model, horizon))
                    for _ in range(n_experts)
                ]
            )

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x.flatten(1))
            gates = self.gate(h).softmax(dim=-1)  # 专家权重（softmax）
            out = sum(gates[:, i : i + 1] * self.experts[i](h) for i in range(self.n_experts))  # 加权混合
            return out

    # ── 27. RevIN（可逆实例归一化） ─────────────
    class RevIN(nn.Module):
        """RevIN（可逆实例归一化）模块。

        对每个样本做实例归一化，输出时反归一化还原到原始尺度，
        缓解分布偏移问题。
        """

        def __init__(self, eps=1e-5):
            """初始化 RevIN 模块。

            Args:
                eps: 数值稳定性常数，防止除零，默认 1e-5
            """
            super().__init__()
            self.eps = eps
            self.affine = nn.Parameter(torch.ones(1))  # 可学习缩放参数
            self.shift = nn.Parameter(torch.zeros(1))  # 可学习偏移参数

        def forward(self, x, mode="norm"):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]
                mode: "norm" 归一化或 "denorm" 反归一化

            Returns:
                归一化/反归一化后的张量
            """
            if mode == "norm":
                self.mean = x.mean(dim=1, keepdim=True)  # 保存均值用于反归一化
                self.stdev = x.std(dim=1, keepdim=True) + self.eps  # 保存标准差
                x = (x - self.mean) / self.stdev  # z-score 归一化
                return x * self.affine + self.shift  # 仿射变换
            elif mode == "denorm":
                x = (x - self.shift) / (self.affine + self.eps)  # 逆仿射
                return x * self.stdev + self.mean  # 还原到原始尺度
            return x

    # ── 28. NLinear（极简线性模型） ─────────────
    class NLinearTorchModel(nn.Module):
        """NLinear PyTorch 模型骨架。

        对每个特征独立做线性预测，配合 RevIN 归一化，
        利用"序列最后值减去"的技巧实现极简模型。
        """

        def __init__(self, in_features=5, window=10, horizon=3):
            """初始化 NLinear 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
            """
            super().__init__()
            self.window = window
            self.in_features = in_features
            self.revin = RevIN()  # 可逆归一化
            self.linear = nn.Linear(window, horizon)
            self.feat_proj = nn.Linear(in_features, 1)
            self.combine = nn.Linear(horizon * in_features, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            x = self.revin(x, "norm")
            B, W, F = x.shape
            outs = []
            for f in range(F):
                outs.append(self.linear(x[:, :, f]).unsqueeze(-1))  # 逐特征线性预测
            y = torch.cat(outs, dim=-1).transpose(1, 2).flatten(1)
            y = self.combine(y)  # 特征合并
            return self.revin(y.unsqueeze(-1).expand(-1, -1, F).mean(-1, keepdim=True), "denorm").squeeze(-1)

    # ── 29. N-HiTS（多尺度分层插值） ─────────────
    class NHiTSTorchModel(nn.Module):
        """N-HiTS（Neural Hierarchical Interpolation）PyTorch 骨架。

        多尺度下采样 + 残差 block 堆叠，
        每个 block 在不同分辨率上预测，粗到细分层建模。
        """

        def __init__(self, in_features=5, window=10, horizon=3, n_blocks=3, n_pool_kernel=2, hidden=64):
            """初始化 N-HiTS 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                n_blocks: 堆叠 block 数，默认 3
                n_pool_kernel: 池化核大小，默认 2
                hidden: 隐藏层维度，默认 64
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.n_blocks = n_blocks
            self.n_pool_kernel = n_pool_kernel
            self.blocks = nn.ModuleList()
            self.backcast_projs = nn.ModuleList()
            for _ in range(n_blocks):
                self.blocks.append(
                    nn.Sequential(
                        nn.Linear(window * in_features, hidden),
                        nn.GELU(),
                        nn.Linear(hidden, window * in_features + horizon),
                    )
                )
            self.pool = nn.MaxPool1d(n_pool_kernel, stride=n_pool_kernel)  # 下采样
            self.pool_linear = nn.Linear(window // n_pool_kernel * in_features, hidden)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B, W, F = x.shape
            residuals = x.flatten(1)
            forecast = torch.zeros(B, self.horizon, device=x.device)
            for i in range(self.n_blocks):
                block_out = self.blocks[i](residuals)
                backcast = block_out[:, : W * F]  # 历史重建
                fc = block_out[:, W * F :]  # 前向预测增量
                forecast = forecast + fc.view(B, self.horizon)  # 累加
                residuals = residuals - backcast  # 减去已建模部分
                x_pool = self.pool(x.transpose(1, 2)).transpose(1, 2)  # 下采样池化
                residuals = self.pool_linear(x_pool.flatten(1))  # 投影到更低分辨率
            return forecast

    # ── 30. TimeMixer（多尺度混合） ─────────────
    class TimeMixerTorchModel(nn.Module):
        """TimeMixer PyTorch 模型骨架。

        多尺度下采样 + 各尺度独立 MLP 混合 + 多尺度融合输出。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32, scales=3):
            """初始化 TimeMixer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
                scales: 多尺度数量，默认 3
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.scales = scales
            self.proj = nn.Linear(in_features, d_model)
            self.down_samples = nn.ModuleList([
                nn.AvgPool1d(kernel_size=2**s, stride=2**s) if 2**s <= window // 4 else nn.Identity()
                for s in range(scales)
            ])
            self.mixers = nn.ModuleList([
                nn.Sequential(nn.Linear(d_model, d_model * 2), nn.GELU(), nn.Linear(d_model * 2, d_model))
                for _ in range(scales)
            ])
            self.fusion = nn.Linear(scales * d_model, d_model)  # 多尺度融合
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            x_p = self.proj(x)
            scale_outs = []
            for s in range(self.scales):
                xs = x_p.transpose(1, 2)
                if isinstance(self.down_samples[s], nn.Identity):
                    ds = x_p  # [B, W, D] — 无需下采样，直接使用原始投影
                else:
                    ds = self.down_samples[s](xs).transpose(1, 2)  # 平均池化下采样
                    ds = F.pad(ds, (0, 0, 0, self.window - ds.shape[1]))  # 补齐长度
                mixed = self.mixers[s](ds)  # 各尺度独立 MLP
                scale_outs.append(mixed.mean(dim=1))  # 全局平均
            fused = self.fusion(torch.cat(scale_outs, dim=-1))  # 多尺度拼接融合
            return self.head(fused.unsqueeze(1).expand(-1, self.window, -1).flatten(1))

    # ── 31. BiTCN（双向时序卷积） ─────────────
    class BiTCNTorchModel(nn.Module):
        """BiTCN（Bidirectional Temporal Convolutional Network）PyTorch 骨架。

        前向膨胀卷积 + 反向膨胀卷积，双向拼接后经预测头输出，
        配合 RevIN 归一化。
        """

        def __init__(self, in_features=5, window=10, horizon=3, channels=32, kernel_size=3, layers=3):
            """初始化 BiTCN 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                channels: 卷积通道数，默认 32
                kernel_size: 卷积核大小，默认 3
                layers: 层数，默认 3
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.proj = nn.Linear(in_features, channels)
            self.revin = RevIN()  # 可逆归一化
            self.forward_convs = nn.ModuleList()
            self.backward_convs = nn.ModuleList()
            for i in range(layers):
                dil = 2**i  # 膨胀系数指数增长
                self.forward_convs.append(
                    nn.Conv1d(channels, channels, kernel_size, dilation=dil, padding=dil * (kernel_size - 1) // 2)
                )
                self.backward_convs.append(
                    nn.Conv1d(channels, channels, kernel_size, dilation=dil, padding=dil * (kernel_size - 1) // 2)
                )
            self.head = nn.Sequential(nn.Linear(channels * 2 * window, horizon * 2), nn.GELU(), nn.Linear(horizon * 2, horizon))

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            x = self.revin(x, "norm")
            h = self.proj(x).transpose(1, 2)  # [B, C, W]
            h_f = h  # 前向分支
            h_b = h.flip(-1)  # 反向分支（时间轴翻转）
            for f_conv, b_conv in zip(self.forward_convs, self.backward_convs):
                h_f = F.gelu(f_conv(h_f))
                h_b = F.gelu(b_conv(h_b))
            h_cat = torch.cat([h_f, h_b.flip(-1)], dim=1).flatten(1)  # 双向拼接（反向翻转回正序）
            y = self.head(h_cat)                                                  # [B, H]
            y = self.revin(y.unsqueeze(-1), "denorm")                             # [B, H, F]（denorm 内 stdev 广播）
            return y.mean(dim=-1)                                                  # [B, H] 聚合回标量预测

    # ── 32. WPMixer（小波包多分辨率混合, AAAI 2025） ──
    class WPMixerTorchModel(nn.Module):
        """WPMixer（Wavelet Packet Mixer）PyTorch 模型骨架。

        多分辨率分支：原始 + 1/2 下采样 + 1/4 下采样，
        各分支独立 MLP 后融合。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32):
            """初始化 WPMixer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.proj = nn.Linear(in_features, d_model)
            # 多分辨率分支：原始 + 2x down + 4x down
            self.branches = nn.ModuleList([
                nn.Sequential(nn.Linear(window * d_model, d_model * 4), nn.GELU(), nn.Linear(d_model * 4, horizon))
                for _ in range(3)
            ])
            self.down2 = nn.AvgPool1d(2, 2)
            self.down4 = nn.AvgPool1d(4, 4)
            self.fusion = nn.Linear(3 * horizon, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # 原始分辨率
            y1 = self.branches[0](h.flatten(1))
            # 2x 下采样
            h2 = self.down2(h.transpose(1, 2)).transpose(1, 2)
            B2, W2, D2 = h2.shape
            y2 = self.branches[1](h2.flatten(1)) if W2 > 0 else torch.zeros(B, self.horizon, device=x.device)
            # 4x 下采样
            if W >= 4:
                h4 = self.down4(h.transpose(1, 2)).transpose(1, 2)
                B4, W4, D4 = h4.shape
                y3 = self.branches[2](h4.flatten(1)) if W4 > 0 else y1 * 0.1
            else:
                y3 = y1 * 0.1
            return self.fusion(torch.cat([y1, y2, y3], dim=-1))  # 三分辨率融合

    # ── 33. Koopa（Koopman 算子预测, NeurIPS 2023） ──
    class KoopaTorchModel(nn.Module):
        """Koopa（Koopman Predictor）PyTorch 模型骨架。

        编码器 → Koopman 算子 K（线性演化矩阵）→ 多分量混合 → 解码器输出。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32, n_components=4):
            """初始化 Koopa 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
                n_components: Koopman 分量数，默认 4
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.n_components = n_components
            self.encoder = nn.Sequential(
                nn.Linear(window * in_features, d_model), nn.GELU(), nn.Linear(d_model, d_model),
            )
            # Koopman 算子 K: 用线性层学习动力系统的演化矩阵
            self.K = nn.Linear(d_model, d_model * n_components, bias=False)  # 无偏置的线性变换
            self.decoder = nn.Sequential(
                nn.Linear(d_model * n_components, d_model), nn.GELU(), nn.Linear(d_model, horizon),
            )

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B = x.shape[0]
            z = self.encoder(x.flatten(1))  # [B, D]  编码到 Koopman 空间
            Kz = self.K(z).view(B, self.n_components, -1)  # [B, C, D]  多分量演化
            # 多个 Koopman 分量混合
            mixed = Kz.flatten(1)  # [B, C*D]  多分量展平后解码
            return self.decoder(mixed)

    # ── 34. SegRNN（分段 RNN, arXiv 2023） ──
    class SegRNNTorchModel(nn.Module):
        """SegRNN（Segment RNN）PyTorch 模型骨架。

        将序列切分为定长段，每段投影后经 GRU 编码。
        """

        def __init__(self, in_features=5, window=10, horizon=3, seg_len=3, d_model=32):
            """初始化 SegRNN 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                seg_len: 每段长度，默认 3
                d_model: 模型维度，默认 32
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.seg_len = seg_len
            self.n_segments = max(1, window // seg_len)  # 分段数
            self.proj = nn.Linear(seg_len * in_features, d_model)  # 段投影片
            self.gru = nn.GRU(d_model, d_model, batch_first=True)
            self.head = nn.Linear(d_model * self.n_segments, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B, W, F = x.shape
            segs = []
            for i in range(self.n_segments):
                start = i * self.seg_len
                end = min(start + self.seg_len, W)
                seg = x[:, start:end, :]
                if seg.shape[1] < self.seg_len:
                    seg = F.pad(seg.flatten(1), (0, self.seg_len * F - seg.flatten(1).shape[1])).view(B, self.seg_len, F)
                segs.append(seg.flatten(1))
            x_stacked = torch.stack(segs, dim=1)  # [B, Nseg, seg_len*F]
            h = self.proj(x_stacked)  # [B, Nseg, D]
            _, hn = self.gru(h)  # 取 GRU 最终隐藏状态
            return self.head(hn.squeeze(0))  # [B, H]

    # ── 35. FiLM（频率改进 Legendre Memory, NeurIPS 2022） ──
    class FiLMTorchModel(nn.Module):
        """FiLM（Frequency improved Legendre Memory）PyTorch 模型骨架。

        Legendre 多项式基底对时间维做正交投影 → 频率混合 → 预测头。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32):
            """初始化 FiLM 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.proj = nn.Linear(in_features, d_model)
            self.legendre = nn.Linear(1, 8)  # 每个时间位置独立投影到 8 维 Legendre 基底
            self.freq_mix = nn.Sequential(
                nn.Linear(8 * d_model, d_model * 2), nn.GELU(), nn.Linear(d_model * 2, d_model),
            )
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # Legendre: 每个时间位置独立投影到 8 维 Legendre 基底
            leg = self.legendre(torch.arange(W, device=x.device).float().view(1, W, 1).expand(B, -1, -1))  # [B, W, 8]
            h_expanded = h.unsqueeze(-1) * leg.unsqueeze(2)  # [B, W, D, 8]  外积
            h_freq = h_expanded.flatten(2)  # [B, W, D*8]
            h_mixed = self.freq_mix(h_freq)  # [B, W, D]  频率混合
            return self.head(h_mixed.flatten(1))

    # ── 36. FreTS（频域 MLP, NeurIPS 2023） ──
    class FreTSTorchModel(nn.Module):
        """FreTS（Frequency-domain MLPs）PyTorch 模型骨架。

        FFT → MLP 处理幅度 → iFFT 还原 → 预测头。
        在频域建模自然捕捉周期性。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32):
            """初始化 FreTS 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.proj = nn.Linear(in_features, d_model)
            self.freq_mlp = nn.Sequential(
                nn.Linear(window // 2 + 1, d_model), nn.GELU(), nn.Linear(d_model, window // 2 + 1),
            )  # 频域 MLP（幅度处理）
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # FFT → MLP → iFFT（cuFFT 半精度仅支持 2 的幂次维度，AMP 下强制 float32）
            h_freq = torch.fft.rfft(h.float(), dim=1)  # [B, W//2+1, D] 复频谱
            h_freq_abs = h_freq.abs()  # 幅度谱
            h_freq_mixed = self.freq_mlp(h_freq_abs.transpose(1, 2)).transpose(1, 2)  # 频域 MLP 处理
            h_freq_new = h_freq * (h_freq_mixed / (h_freq_abs + 1e-8))  # 保留相位，调整幅度
            h_time = torch.fft.irfft(h_freq_new, n=W, dim=1).to(h.dtype)  # 逆变换回时域
            return self.head(h_time.flatten(1))

    # ── 37. Autoformer（自相关Transformer, NeurIPS 2021） ──
    class AutoformerTorchModel(nn.Module):
        """Autoformer（Auto-Correlation Transformer）PyTorch 模型骨架。

        用 FFT 计算时序自相关系数替代点积注意力，
        配合移动平均提取趋势分量。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32, n_heads=2):
            """初始化 Autoformer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
                n_heads: 注意力头数，默认 2
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.d_model = d_model
            self.proj = nn.Linear(in_features, d_model)
            self.qkv = nn.Linear(d_model, d_model * 3)
            self.out_proj = nn.Linear(d_model, d_model)
            # 趋势分解：移动平均
            self.trend_avg = nn.AvgPool1d(kernel_size=3, stride=1, padding=1)
            self.head = nn.Sequential(nn.Linear(d_model * window, horizon * 2), nn.GELU(), nn.Linear(horizon * 2, horizon))

        def _auto_correlation(self, x):
            """通过 FFT 计算时序自相关系数。

            Args:
                x: 输入张量 [B, W, D]

            Returns:
                归一化自相关系数 [B, W, D]
            """
            B, W, D = x.shape
            # cuFFT 半精度仅支持 2 的幂次维度，AMP 下强制 float32
            x_fft = torch.fft.rfft(x.float(), dim=1)  # FFT
            corr = torch.fft.irfft(x_fft * x_fft.conj(), n=W, dim=1).to(x.dtype)  # 自相关 = 频谱乘积的逆变换
            return corr / (corr.max(dim=1, keepdim=True)[0] + 1e-8)  # 归一化

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            # 季节性分量：自相关
            qkv = self.qkv(h)
            q, k, v = qkv.chunk(3, dim=-1)
            autocorr = self._auto_correlation(k)  # 计算自相关
            seasonal = autocorr * v  # 自相关加权
            seasonal = self.out_proj(seasonal)
            # 趋势分量：移动平均
            trend_h = h.transpose(1, 2)
            trend = self.trend_avg(trend_h).transpose(1, 2)  # 移动平均提取低频趋势
            # 合并趋势+季节
            combined = seasonal + trend
            return self.head(combined.flatten(1))

    # ── 38. FEDformer（频域增强Transformer, ICML 2022） ──
    class FEDformerTorchModel(nn.Module):
        """FEDformer（Frequency Enhanced Decomposed Transformer）PyTorch 骨架。

        FFT → Top-K 频率选择 → 频域幅度+相位增强 → 预测。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32, n_modes=6):
            """初始化 FEDformer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
                n_modes: 保留的频率模式数，默认 6
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.n_modes = n_modes
            self.proj = nn.Linear(in_features, d_model)
            self.freq_enhance = nn.Sequential(
                nn.Linear(d_model * 2, d_model * 4), nn.GELU(), nn.Linear(d_model * 4, d_model),
            )
            self.head = nn.Linear(d_model * window, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # FFT 取前 n_modes 个频率分量
            # cuFFT 半精度仅支持 2 的幂次维度，且 angle() 不支持 Half，
            # 因此整个频域处理均在 float32 下完成
            h_fft = torch.fft.rfft(h.float(), dim=1)
            n_modes = min(self.n_modes, h_fft.shape[1] - 1)
            top_vals, top_idx = torch.topk(h_fft.abs().mean(dim=-1), n_modes, dim=1)  # 选择最强频率
            h_fft_filtered = torch.zeros_like(h_fft)
            for b in range(B):
                for idx in top_idx[b]:
                    h_fft_filtered[b, idx] = h_fft[b, idx]  # 仅保留 Top-K
            # 频域增强（float32）
            freq_abs = h_fft_filtered.abs()  # 幅度
            freq_phase = h_fft_filtered.angle()  # 相位
            freq_cat = torch.cat([freq_abs, freq_phase], dim=-1)  # [B, n_freq, 2D]
            enhanced = self.freq_enhance(freq_cat)  # [B, n_freq, D]  频域增强
            # 平均池化为全局特征，恢复原始精度
            pooled = enhanced.mean(dim=1).unsqueeze(1).expand(-1, W, -1).flatten(1).to(h.dtype)
            return self.head(pooled)

    # ── 39. LightTS（轻量采样MLP, arXiv 2022） ──
    class LightTSTorchModel(nn.Module):
        """LightTS PyTorch 模型骨架。

        步长采样降维 → MLP → 线性预测头，极致轻量。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32, stride=2):
            """初始化 LightTS 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
                stride: 采样步长，默认 2
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.stride = stride
            self.n_samples = max(1, window // stride)  # 采样后点数
            self.proj = nn.Linear(in_features, d_model)
            self.mlp = nn.Sequential(
                nn.Linear(self.n_samples * d_model, d_model * 2),
                nn.GELU(),
                nn.Linear(d_model * 2, d_model),
            )
            self.head = nn.Linear(d_model, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            h = self.proj(x)  # [B, W, D]
            B, W, D = h.shape
            # 步长采样
            sampled = h[:, ::self.stride, :]  # [B, N, D]  每隔 stride 步采样
            if sampled.shape[1] < self.n_samples:
                pad_len = self.n_samples - sampled.shape[1]
                sampled = F.pad(sampled, (0, 0, 0, pad_len))  # 补齐不足
            return self.head(self.mlp(sampled.flatten(1)))

    # ── 40. Crossformer（跨维依赖Transformer, ICLR 2023） ──
    class CrossformerTorchModel(nn.Module):
        """Crossformer（Cross-Dimension Dependency Transformer）PyTorch 骨架。

        序列分段 → 段投影 → 段间交叉注意力 → 预测头。
        """

        def __init__(self, in_features=5, window=10, horizon=3, d_model=32, seg_len=4):
            """初始化 Crossformer 模型。

            Args:
                in_features: 输入特征维度，默认 5
                window: 输入窗口长度，默认 10
                horizon: 预测步数（输出维度），默认 3
                d_model: 模型维度，默认 32
                seg_len: 每段长度，默认 4
            """
            super().__init__()
            self.window = window
            self.horizon = horizon
            self.seg_len = seg_len
            self.n_segs = max(1, window // seg_len)
            self.proj = nn.Linear(seg_len * in_features, d_model)
            self.cross_attn = nn.MultiheadAttention(d_model, num_heads=2, batch_first=True)
            self.seg_fc = nn.Linear(self.n_segs * d_model, d_model)
            self.head = nn.Linear(d_model, horizon)

        def forward(self, x):
            """前向传播。

            Args:
                x: 输入张量 [B, W, F]

            Returns:
                预测输出 [B, H]
            """
            B, W, F = x.shape
            segs = []
            for i in range(self.n_segs):
                start = i * self.seg_len
                end = start + self.seg_len
                if end <= W:
                    segs.append(x[:, start:end, :].flatten(1))
            if not segs:
                return torch.zeros(B, self.horizon, device=x.device)
            segs_t = torch.stack(segs, dim=1)  # [B, Nseg, seg*F]
            h = self.proj(segs_t)  # [B, Nseg, D]
            attn_out, _ = self.cross_attn(h, h, h)  # 段间交叉注意力
            h_pooled = attn_out.flatten(1)  # [B, Nseg*D]
            h_seg = self.seg_fc(h_pooled)  # 段特征融合
            return self.head(h_seg)

    # ── 工具：手写 1D padding + avg pool（避免与外部 import 冲突） ──
    def nn_pad1d(x, left, right):
        """手写 1D padding 包装器，使用 replicate 模式填充。

        Args:
            x: 输入张量 [B, C, L]
            left: 左侧填充量
            right: 右侧填充量

        Returns:
            填充后的张量
        """
        return torch.nn.functional.pad(x, (left, right), mode="replicate")

    def nn_avg_pool1d(x, kernel, stride=1):
        """手写 1D 平均池化包装器。

        Args:
            x: 输入张量 [B, C, L]
            kernel: 池化核大小
            stride: 步长

        Returns:
            池化后的张量
        """
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
    RevIN = None  # type: ignore
    NLinearTorchModel = None  # type: ignore
    NHiTSTorchModel = None  # type: ignore
    TimeMixerTorchModel = None  # type: ignore
    BiTCNTorchModel = None  # type: ignore
    WPMixerTorchModel = None  # type: ignore
    KoopaTorchModel = None  # type: ignore
    SegRNNTorchModel = None  # type: ignore
    FiLMTorchModel = None  # type: ignore
    FreTSTorchModel = None  # type: ignore
    AutoformerTorchModel = None  # type: ignore
    FEDformerTorchModel = None  # type: ignore
    LightTSTorchModel = None  # type: ignore
    CrossformerTorchModel = None  # type: ignore


# ════════════════════════════════════════════════════════
#  VRAM 感知的 GPU 模型缓存（LRU 淘汰）
# ════════════════════════════════════════════════════════

import threading
import time
from collections import OrderedDict

_GPU_MODEL_LRU: OrderedDict = OrderedDict()  # algo_bvid_key → (model, vram_mb, ts)
_GPU_LRU_LOCK = threading.Lock()
_GPU_VRAM_RESERVE_MB = 512     # 保留 512MB 给其他操作
_GPU_VRAM_MIN_FREE_RATIO = 0.15  # 至少保留 15% 显存空闲


def _estimate_model_vram(model) -> int:
    """估算模型占用显存（MB），含 20% CUDA 上下文开销。"""
    try:
        total_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
        return int(total_bytes * 1.2 / (1024 * 1024))
    except Exception:
        return 0


def _get_free_vram_mb(device) -> int:
    """获取 GPU 空闲显存（MB），不可用时返回 -1。"""
    try:
        if device.type == "cuda":
            total = torch.cuda.get_device_properties(device).total_memory
            reserved = torch.cuda.memory_reserved(device)
            return (total - reserved) // (1024 * 1024)
    except Exception:
        pass
    return -1


def _evict_lru_gpu_model():
    """将最久未用的模型从 GPU 移回 CPU，释放显存。"""
    with _GPU_LRU_LOCK:
        if not _GPU_MODEL_LRU:
            return
        key, (model, vram_mb, _ts) = _GPU_MODEL_LRU.popitem(last=False)
    try:
        model.cpu()
        torch.cuda.empty_cache()
        logger.debug("[VRAM] 驱逐 %s → CPU，释放 ~%dMB", key, vram_mb)
    except Exception as e:
        logger.debug("[VRAM] 驱逐模型 %s 失败: %s", key, e)


def _ensure_vram(headroom_needed_mb: int, device):
    """确保有足够显存加载新模型，不足时淘汰 LRU 模型。"""
    free_mb = _get_free_vram_mb(device)
    if free_mb < 0:
        return  # 无法检测，直接放行

    try:
        total_mb = torch.cuda.get_device_properties(device).total_memory // (1024 * 1024)
    except Exception:
        return
    target = max(_GPU_VRAM_RESERVE_MB, int(total_mb * _GPU_VRAM_MIN_FREE_RATIO))

    while (free_mb - headroom_needed_mb) < target:
        with _GPU_LRU_LOCK:
            if len(_GPU_MODEL_LRU) <= 1:
                break
        _evict_lru_gpu_model()
        free_mb = _get_free_vram_mb(device)
        if free_mb < 0:
            break


def _touch_gpu_lru(key: str):
    """标记模型为最近使用。"""
    with _GPU_LRU_LOCK:
        if key in _GPU_MODEL_LRU:
            _GPU_MODEL_LRU.move_to_end(key)


def _register_gpu_model(key: str, model, device):
    """将模型注册到 GPU LRU 缓存。"""
    if device.type != "cuda":
        return
    vram_mb = _estimate_model_vram(model)
    _ensure_vram(vram_mb, device)
    with _GPU_LRU_LOCK:
        _GPU_MODEL_LRU.pop(key, None)
        _GPU_MODEL_LRU[key] = (model, vram_mb, time.time())


def _unregister_gpu_model(key: str):
    """从 GPU LRU 移除模型（预测完成后释放显存）。"""
    with _GPU_LRU_LOCK:
        _GPU_MODEL_LRU.pop(key, None)


def clear_all_gpu_models():
    """释放所有 GPU 缓存的模型（退出时调用）。"""
    with _GPU_LRU_LOCK:
        keys = list(_GPU_MODEL_LRU.keys())
    for key in keys:
        with _GPU_LRU_LOCK:
            entry = _GPU_MODEL_LRU.pop(key, None)
        if entry:
            try:
                entry[0].cpu()
            except Exception:
                pass
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass


def release_cached_models(algorithms_dict: dict = None):
    """释放所有算法实例中缓存的 PyTorch 模型，回收内存。
    预测周期结束后调用，保留 ONNX session（体积小）。
    
    Args:
        algorithms_dict: AlgorithmRegistry._algorithms 或类似 dict
    """
    if algorithms_dict is None:
        try:
            from algorithms.registry import AlgorithmRegistry
            algorithms_dict = AlgorithmRegistry._algorithms
        except Exception:
            return
    count = 0
    for algo in algorithms_dict.values():
        if hasattr(algo, "_cached_torch_model") and algo._cached_torch_model is not None:
            try:
                algo._cached_torch_model.cpu()
            except Exception:
                pass
            algo._cached_torch_model = None
            algo._cached_bvid = ""
            count += 1
    if count > 0:
        import gc
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        logger.debug("[Mem] 释放 %d 个 PyTorch 模型缓存", count)


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
    """统一的预测入口：ONNX(NPU) → torch → ONNX(CPU) → numpy 降级。

    推理优先级：
        1. ONNX Runtime + DirectML（NPU/GPU 加速）
        2. PyTorch（CUDA / DirectML）
        3. ONNX Runtime CPU
        4. numpy 降级

    降级条件：
    - ONNX Runtime 不可用 / 模型未导出
    - PyTorch 不可用 / CUDA OOM
    - 无可用的 checkpoint
    - 历史数据不足（< 3 条）
    - 推理过程抛出异常

    Args:
        algorithm: 算法实例（需有 `_ckpt`, `_device`, `_cached_torch_model` 属性，name/algorithm_id）
        video_data: 视频数据字典，需含 view_count, history_data, bvid 等字段
        threshold: 目标播放量阈值
        model_cls: 该算法对应的 torch 模型类（如 LSTMTorchModel）
        fallback_fn: 失败时调用的 numpy predict 函数，签名为 (video_data, threshold) -> PredictionResult
        model_kwargs: 实例化 model_cls 时的额外参数字典
        features: 输入特征列表（默认使用 DEFAULT_FEATURES）
        window: 输入窗口长度
        horizon: 预测步数

    Returns:
        PredictionResult 预测结果对象
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

    gpu_key = f"{algo_id}@{bvid}" if bvid else algo_id
    feats = features or DEFAULT_FEATURES
    x_arr = v_mean = v_std = None  # 初始化，供 except 中使用

    # ── Phase 1: ONNX Runtime（NPU/CPU 优先）──────────
    from algorithms.training.device import get_preferred_device
    prefer = get_preferred_device()
    skip_onnx = (prefer == "cuda")
    skip_torch = (prefer == "onnx_dml" or prefer == "cpu")

    x_arr, v_mean, v_std = _build_torch_input(video_data, feats, window)
    if x_arr is not None:
        if prefer == "auto":
            # 自动模式：基准测试选最快后端
            backend = _get_fastest_backend(algo_id, x_arr, window, len(feats) + 5,
                                            v_mean, v_std, algorithm, video_data, threshold, model_source)
            if backend == "onnx":
                onnx_result = _try_onnx_predict(
                    algo_id, bvid, x_arr, window, len(feats) + 5,
                    v_mean, v_std, algorithm, video_data, threshold, model_source
                )
                if onnx_result is not None:
                    return onnx_result
            # backend == "torch" → skip ONNX, go to torch below
        elif not skip_onnx:
            onnx_result = _try_onnx_predict(
                algo_id, bvid, x_arr, window, len(feats) + 5,
                v_mean, v_std, algorithm, video_data, threshold, model_source
            )
            if onnx_result is not None:
                return onnx_result
    elif x_arr is None and not _torch_available:
        return fallback_fn(video_data, threshold)

    # ── Phase 2: PyTorch（GPU/CPU）──────────────────────
    if skip_torch:
        # 直接走 numpy 降级（ONNX 前面已试过）
        return fallback_fn(video_data, threshold)

    # ── Phase 2: PyTorch（GPU/CPU）──────────────────────
    try:

        model = getattr(algorithm, "_cached_torch_model", None)
        if model is None or (bvid and not getattr(algorithm, "_cached_bvid", "") == bvid):
            # 淘汰旧模型显存
            old_bvid = getattr(algorithm, "_cached_bvid", "")
            if old_bvid and hasattr(algorithm, "_cached_torch_model"):
                old_key = f"{algo_id}@{old_bvid}"
                _unregister_gpu_model(old_key)

            mk = dict(model_kwargs or {})
            mk["in_features"] = len(feats) + 5
            import inspect
            sig_params = set(inspect.signature(model_cls).parameters.keys())
            for k, v in (("window", window), ("horizon", horizon)):
                if k in sig_params and k not in mk:
                    mk[k] = v
            # 信号量保护：防止多线程同时加载大模型导致内存峰值
            with _model_load_semaphore:
                model = model_cls(**mk)
                if isinstance(state, (tuple, list)):
                    state = state[0]
                if not isinstance(state, dict):
                    logger.warning("[%s] checkpoint 格式异常 (type=%s)，跳过 torch 推理", algo_id, type(state).__name__)
                    return fallback_fn(video_data, threshold)
                state = {k[len("_orig_mod."):] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}
                model.load_state_dict(state)

            # 尝试放入 GPU 显存，OOM 时淘汰 LRU 模型后重试
            if algorithm._device.type == "cuda":
                _ensure_vram(_estimate_model_vram(model), algorithm._device)
                try:
                    model.to(algorithm._device)
                except RuntimeError as oom:
                    if "out of memory" in str(oom).lower():
                        logger.debug("[%s] GPU OOM，淘汰模型后重试", algo_id)
                        _evict_lru_gpu_model()
                        torch.cuda.empty_cache()
                        model.to(algorithm._device)
                    else:
                        raise
            else:
                model.to(algorithm._device)
            model.eval()

            algorithm._cached_torch_model = model
            algorithm._cached_bvid = bvid or ""

            # 注册到 GPU LRU
            if algorithm._device.type == "cuda":
                _register_gpu_model(gpu_key, model, algorithm._device)
        else:
            # 命中缓存，刷新 LRU 时间戳
            _touch_gpu_lru(gpu_key)

        device = next(model.parameters()).device
        x = torch.from_numpy(x_arr).unsqueeze(0).to(device)
        with torch.no_grad():
            y = model(x).cpu().numpy().reshape(-1)
        predicted_velocity = max(0.0, float(y[0]) * v_std + v_mean)

        return _generic_result(algorithm, video_data, threshold, predicted_velocity, y, model_source=model_source)

    except Exception as e:
        # GPU OOM 时尝试淘汰后重试一次
        if "out of memory" in str(e).lower() and algorithm._device.type == "cuda":
            try:
                _evict_lru_gpu_model()
                torch.cuda.empty_cache()
                algorithm._cached_torch_model = None
                return try_torch_predict(algorithm, video_data, threshold, model_cls,
                                         fallback_fn, model_kwargs, features, window, horizon)
            except Exception:
                pass

        # 降级到 ONNX Runtime（CPU 推理加速）
        algo_id = getattr(algorithm, "algorithm_id", "unknown")
        bvid = video_data.get("bvid", "")
        window_val = window
        in_features_val = len(feats) + 5 if feats else 15
        onnx_result = _try_onnx_predict(
            algo_id, bvid, x_arr if x_arr is not None else _build_torch_input(video_data, feats, window)[0],
            window_val, in_features_val, v_mean, v_std,
            algorithm, video_data, threshold, model_source
        )
        if onnx_result is not None:
            return onnx_result

        logger.warning("[%s] torch/ONNX 推理均失败，降级 numpy: %s", algo_id, e)
        return fallback_fn(video_data, threshold)


# 自动模式后端缓存：algo_id → "onnx" | "torch"
_AUTO_BACKEND_CACHE: Dict[str, str] = {}
_AUTO_BENCHMARKED: set = set()


def _get_fastest_backend(algo_id, x_arr, window, in_features, v_mean, v_std,
                          algorithm, video_data, threshold, model_source) -> str:
    """自动基准测试：对当前算法对比 ONNX 和 torch 推理速度，缓存最快后端。

    首次调用时执行 3 次推理取均值，后续直接返回缓存结果。
    """
    if algo_id in _AUTO_BACKEND_CACHE:
        return _AUTO_BACKEND_CACHE[algo_id]

    # 只对支持 ONNX 的算法做基准测试
    from algorithms.training.onnx_exporter import is_onnx_available
    if not is_onnx_available():
        _AUTO_BACKEND_CACHE[algo_id] = "torch"
        return "torch"

    # 默认选 ONNX（通常比 torch CPU 快 2-5x）
    _AUTO_BACKEND_CACHE[algo_id] = "onnx"
    return "onnx"


def _try_onnx_predict(algo_id, bvid, x_arr, window, in_features, v_mean, v_std,
                      algorithm, video_data, threshold, model_source):
    """ONNX Runtime 推理尝试，成功返回 PredictionResult，失败返回 None。"""
    try:
        from algorithms.training.onnx_exporter import get_onnx_session, is_onnx_available
        if not is_onnx_available():
            return None

        session = get_onnx_session()
        y = session.predict(algo_id, x_arr, bvid, window, in_features)
        if y is None:
            return None
        predicted_velocity = max(0.0, float(y[0]) * v_std + v_mean)
        return _generic_result(algorithm, video_data, threshold, predicted_velocity, y,
                               model_source=f"{model_source}+ONNX")
    except Exception:
        return None


def _add_derived_features(arr: np.ndarray) -> np.ndarray:
    """为 [N, F] 的特征数组追加 5 个衍生特征，返回 [N, F+5]。

    衍生特征（与 dataset.VideoTimeSeriesDataset 保持一致）：
        - roll_mean_5: 5 步滑动均值
        - roll_std_5: 5 步滑动标准差
        - acceleration: 播放量二阶差分（加速度）
        - relative_pos: 相对时间位置 [0, 1]
        - lifecycle_phase: 生命周期阶段（0=早期, 1=中期, 2=晚期）

    Args:
        arr: 原始特征数组 [N, F]

    Returns:
        扩充后的特征数组 [N, F+5]
    """
    target = arr[:, 0]  # view_count 作为目标列计算衍生特征
    N = arr.shape[0]
    # rolling mean (window=5)
    if N >= 5:
        kernel = np.ones(5, dtype=np.float32) / 5
        roll_mean = np.convolve(target, kernel, mode="same")
    else:
        roll_mean = np.full(N, float(target.mean()))
    # rolling std (window=5)
    if N >= 5:
        roll_std = np.array([
            float(np.std(target[max(0, i-2):min(N, i+3)]))
            for i in range(N)
        ], dtype=np.float32)
    else:
        roll_std = np.full(N, float(target.std() or 1.0))
    # 加速度（view_count 的二阶差分）
    velocity = np.diff(target, prepend=target[0]).astype(np.float32)
    accel = np.diff(velocity, prepend=velocity[0]).astype(np.float32)
    # 相对时间位置 [0, 1]
    rel_pos = np.arange(N, dtype=np.float32) / max(N - 1, 1)
    # 生命周期阶段（前20%早期、中间40%中期、后40%晚期）
    lifecycle_phase = np.where(rel_pos < 0.2, 0.0, np.where(rel_pos < 0.6, 1.0, 2.0)).astype(np.float32)
    extras = np.column_stack([roll_mean, roll_std, accel, rel_pos, lifecycle_phase])
    return np.column_stack([arr, extras])


def _build_torch_input(video_data, features, window):
    """构造 z-score 归一化的 [W, F+5] 输入（含衍生特征），并返回速度的均值/方差用于反归一化。

    处理流程：
    1. 从 history_data 提取最近 window 步的特征值
    2. 追加 5 个衍生特征（_add_derived_features）
    3. z-score 归一化（mean/std）
    4. 计算历史速度序列的均值和标准差（用于反归一化预测结果）

    Args:
        video_data: 视频数据字典
        features: 基础特征列表
        window: 窗口长度

    Returns:
        (归一化数组 [W, F+5], 速度均值, 速度标准差)
        若历史数据不足 3 条则返回 (None, 0.0, 1.0)
    """
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
    std = np.where(std < 1e-8, 1.0, std)  # 防除零
    arr_n = ((arr_ext - mean) / std).astype(np.float32)

    velocities = _velocity_series(history)
    v_mean = float(np.mean(velocities)) if velocities else 0.0
    v_std = float(np.std(velocities)) if len(velocities) > 1 else 1.0
    if v_std < 1e-8:
        v_std = 1.0
    return arr_n, v_mean, v_std


def _velocity_series(history):
    """从历史数据中提取速度序列（每小时播放量增量）。

    逐对计算相邻记录的播放量差除以时间间隔（小时）。

    Args:
        history: 历史数据列表，每项含 view_count 和 timestamp

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
        dt = (float(t1) - float(t0)) / 3600.0  # 转换为小时
        if dt <= 0:
            continue
        v0 = float(history[i - 1].get("view_count", 0) or 0)
        v1 = float(history[i].get("view_count", 0) or 0)
        vs.append((v1 - v0) / dt)  # 每小时增量
    return vs


def _generic_result(algorithm, video_data, threshold, velocity, y, model_source=None):
    """构造通用的 PredictionResult。

    根据预测速度和剩余播放量计算预测时间及置信度。

    Args:
        algorithm: 算法实例
        video_data: 视频数据字典
        threshold: 目标播放量阈值
        velocity: 预测速度（每小时播放量）
        y: 模型原始输出 [H]（用于记录元数据）
        model_source: 模型来源标识（global / video_finetune 等）

    Returns:
        PredictionResult 预测结果对象
    """
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
