"""PyTorch model definitions extracted from the compatibility facade."""

from .context import F, _torch_available, nn, torch

if _torch_available:  # noqa: C901

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
                nn.Linear(8 * d_model, d_model * 2),
                nn.GELU(),
                nn.Linear(d_model * 2, d_model),
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
                nn.Linear(window // 2 + 1, d_model),
                nn.GELU(),
                nn.Linear(d_model, window // 2 + 1),
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
            self.head = nn.Sequential(
                nn.Linear(d_model * window, horizon * 2), nn.GELU(), nn.Linear(horizon * 2, horizon)
            )

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
                nn.Linear(d_model * 2, d_model * 4),
                nn.GELU(),
                nn.Linear(d_model * 4, d_model),
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
            sampled = h[:, :: self.stride, :]  # [B, N, D]  每隔 stride 步采样
            if sampled.shape[1] < self.n_samples:
                pad_len = self.n_samples - sampled.shape[1]
                sampled = F.pad(sampled, (0, 0, 0, pad_len))  # 补齐不足
            return self.head(self.mlp(sampled.flatten(1)))

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

else:
    FiLMTorchModel = None  # type: ignore
    FreTSTorchModel = None  # type: ignore
    AutoformerTorchModel = None  # type: ignore
    FEDformerTorchModel = None  # type: ignore
    LightTSTorchModel = None  # type: ignore
    CrossformerTorchModel = None  # type: ignore

__all__ = [
    "FiLMTorchModel",
    "FreTSTorchModel",
    "AutoformerTorchModel",
    "FEDformerTorchModel",
    "LightTSTorchModel",
    "CrossformerTorchModel",
]
