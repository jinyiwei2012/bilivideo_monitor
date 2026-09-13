"""PyTorch model definitions extracted from the compatibility facade."""

from typing import TYPE_CHECKING

from .context import _torch_available, nn

if _torch_available or TYPE_CHECKING:  # noqa: C901

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

else:
    LSTMTorchModel = None
    GRUTorchModel = None
    BiLSTMTorchModel = None
    MLPTorchModel = None
    TCNTorchModel = None
    CNNLSTMTorchModel = None
    AttentionTorchModel = None

__all__ = [
    "LSTMTorchModel",
    "GRUTorchModel",
    "BiLSTMTorchModel",
    "MLPTorchModel",
    "TCNTorchModel",
    "CNNLSTMTorchModel",
    "AttentionTorchModel",
]
