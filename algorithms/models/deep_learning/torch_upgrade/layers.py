"""PyTorch model definitions extracted from the compatibility facade."""

from .context import _torch_available, torch

if _torch_available:  # noqa: C901

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
    nn_pad1d = None  # type: ignore
    nn_avg_pool1d = None  # type: ignore

__all__ = ["nn_pad1d", "nn_avg_pool1d"]
