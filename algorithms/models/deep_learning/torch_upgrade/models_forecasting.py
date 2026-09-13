"""PyTorch model definitions extracted from the compatibility facade."""

from .context import _torch_available, nn, torch
from .layers import nn_avg_pool1d, nn_pad1d

if _torch_available:  # noqa: C901

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
            return self.combine(y.transpose(1, 2).flatten(1))

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
            scores = (q @ k.transpose(-2, -1)) / (self.dk**0.5)  # 避免 np.sqrt 导致 torch.compile 失败
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
            return self.mu(h) + self.sigma(h) * torch.randn_like(self.sigma(h)) * 0.01

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

else:
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

__all__ = [
    "DLinearTorchModel",
    "NBeatsTorchModel",
    "PatchTSTTorchModel",
    "InformerTorchModel",
    "TFTTorchModel",
    "TimessNetTorchModel",
    "TIDETorchModel",
    "TSMixerTorchModel",
    "DeepARTorchModel",
    "ChronosTorchModel",
    "MambaS6TorchModel",
    "ITransformerTorchModel",
    "SCINetTorchModel",
    "TimesFMTorchModel",
    "TimeMoETorchModel",
]
