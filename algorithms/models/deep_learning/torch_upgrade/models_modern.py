"""PyTorch model definitions extracted from the compatibility facade."""

from typing import TYPE_CHECKING

from .context import F, _torch_available, nn, torch

if _torch_available or TYPE_CHECKING:  # noqa: C901

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
            self.down_samples = nn.ModuleList(
                [
                    nn.AvgPool1d(kernel_size=2**s, stride=2**s) if 2**s <= window // 4 else nn.Identity()
                    for s in range(scales)
                ]
            )
            self.mixers = nn.ModuleList(
                [
                    nn.Sequential(nn.Linear(d_model, d_model * 2), nn.GELU(), nn.Linear(d_model * 2, d_model))
                    for _ in range(scales)
                ]
            )
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
            self.head = nn.Sequential(
                nn.Linear(channels * 2 * window, horizon * 2), nn.GELU(), nn.Linear(horizon * 2, horizon)
            )

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
            y = self.head(h_cat)  # [B, H]
            y = self.revin(y.unsqueeze(-1), "denorm")  # [B, H, F]（denorm 内 stdev 广播）
            return y.mean(dim=-1)

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
            self.branches = nn.ModuleList(
                [
                    nn.Sequential(nn.Linear(window * d_model, d_model * 4), nn.GELU(), nn.Linear(d_model * 4, horizon))
                    for _ in range(3)
                ]
            )
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
            return self.fusion(torch.cat([y1, y2, y3], dim=-1))

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
                nn.Linear(window * in_features, d_model),
                nn.GELU(),
                nn.Linear(d_model, d_model),
            )
            # Koopman 算子 K: 用线性层学习动力系统的演化矩阵
            self.K = nn.Linear(d_model, d_model * n_components, bias=False)  # 无偏置的线性变换
            self.decoder = nn.Sequential(
                nn.Linear(d_model * n_components, d_model),
                nn.GELU(),
                nn.Linear(d_model, horizon),
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
                    seg = F.pad(seg.flatten(1), (0, self.seg_len * F - seg.flatten(1).shape[1])).view(
                        B, self.seg_len, F
                    )
                segs.append(seg.flatten(1))
            x_stacked = torch.stack(segs, dim=1)  # [B, Nseg, seg_len*F]
            h = self.proj(x_stacked)  # [B, Nseg, D]
            _, hn = self.gru(h)  # 取 GRU 最终隐藏状态
            return self.head(hn.squeeze(0))

else:
    RevIN = None
    NLinearTorchModel = None
    NHiTSTorchModel = None
    TimeMixerTorchModel = None
    BiTCNTorchModel = None
    WPMixerTorchModel = None
    KoopaTorchModel = None
    SegRNNTorchModel = None

__all__ = [
    "RevIN",
    "NLinearTorchModel",
    "NHiTSTorchModel",
    "TimeMixerTorchModel",
    "BiTCNTorchModel",
    "WPMixerTorchModel",
    "KoopaTorchModel",
    "SegRNNTorchModel",
]
