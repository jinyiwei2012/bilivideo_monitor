"""自定义学习率调度器 — 适配增量训练场景。"""

import math
import logging

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
    from torch.optim.lr_scheduler import _LRScheduler
except ImportError:
    _torch_available = False
    _LRScheduler = object


class HyperbolicLR(_LRScheduler):
    """双曲线学习率衰减：lr(epoch) = base_lr / (1 + k * epoch)

    与总训练轮数无关，只依赖当前已完成的 epoch 数。
    增量训练每次 resumed 后继续衰减，不会重置。

    Args:
        optimizer: 被包装的优化器。
        k: 衰减速率，越大衰减越快。
        min_lr: 最低学习率下限。
        last_epoch: 初始 epoch。
    """

    def __init__(self, optimizer, k: float = 0.1, min_lr: float = 1e-6, last_epoch: int = -1):
        self.k = k
        self.min_lr = min_lr
        super().__init__(optimizer, last_epoch)

    def get_lr(self):
        if self.last_epoch == 0:
            return [base_lr for base_lr in self.base_lrs]
        return [max(base_lr / (1.0 + self.k * self.last_epoch), self.min_lr) for base_lr in self.base_lrs]


class ComboScheduler:
    """组合调度器：正常时用 HyperbolicLR，检测到 plateau 时切换。

    此调度器不继承 _LRScheduler，而是主动管理两种策略的切换。
    通过 update() 传入 val_loss，内部判断是否 plateau 并切换。

    Args:
        optimizer: 优化器。
        k: HyperbolicLR 的衰减速率。
        plateau_patience: val_loss 连续多少轮不下降视为 plateau。
        plateau_factor: plateau 时 LR 乘以该系数（默认 0.5）。
        min_lr: 最低学习率。
    """

    def __init__(
        self,
        optimizer,
        k: float = 0.1,
        plateau_patience: int = 5,
        plateau_factor: float = 0.5,
        min_lr: float = 1e-6,
    ):
        self.optimizer = optimizer
        self.base_lrs = [pg["lr"] for pg in optimizer.param_groups]
        self.k = k
        self.plateau_patience = plateau_patience
        self.plateau_factor = plateau_factor
        self.min_lr = min_lr

        self._step_count = 0
        self._mode = "hyperbolic"  # "hyperbolic" | "plateau"
        self._best_val = float("inf")
        self._plateau_counter = 0
        self._last_lrs = list(self.base_lrs)

    def step(self, epoch: int = None):
        if _torch_available and isinstance(self.optimizer, torch.optim.Optimizer):
            self._step_count += 1

    def update(self, val_loss: float):
        """用验证 loss 更新状态，检测 plateau 并切换策略。"""
        if val_loss < 0 or not _torch_available:
            return

        if val_loss < self._best_val:
            self._best_val = val_loss
            self._plateau_counter = 0
            return

        self._plateau_counter += 1

        # 检测到 plateau：切换到 ReduceLROnPlateau 风格
        if self._plateau_counter >= self.plateau_patience and self._mode == "hyperbolic":
            self._mode = "plateau"
            current_lrs = [pg["lr"] for pg in self.optimizer.param_groups]
            new_lrs = [max(lr * self.plateau_factor, self.min_lr) for lr in current_lrs]
            for pg, new_lr in zip(self.optimizer.param_groups, new_lrs):
                pg["lr"] = new_lr
            logger.info(
                "[ComboScheduler] plateau 检测 (val_loss %.4f 连续 %d 轮未改善)，切换为衰减模式 LR=%.6f",
                val_loss, self.plateau_patience, new_lrs[0],
            )
            self._plateau_counter = 0

    def step_hyperbolic(self):
        """每 epoch 调用：更新 HyperbolicLR 部分（仅 hyperbolic 模式下有效）。"""
        if self._mode != "hyperbolic":
            return
        if not _torch_available:
            return
        self._step_count += 1
        for pg, base_lr in zip(self.optimizer.param_groups, self.base_lrs):
            new_lr = max(base_lr / (1.0 + self.k * self._step_count), self.min_lr)
            pg["lr"] = new_lr

    def get_lr(self) -> float:
        if _torch_available and len(self.optimizer.param_groups) > 0:
            return self.optimizer.param_groups[0]["lr"]
        return 0.0

    def state_dict(self) -> dict:
        return {
            "step_count": self._step_count,
            "mode": self._mode,
            "best_val": self._best_val,
            "plateau_counter": self._plateau_counter,
            "base_lrs": self.base_lrs,
        }

    def load_state_dict(self, state_dict: dict):
        self._step_count = state_dict.get("step_count", 0)
        self._mode = state_dict.get("mode", "hyperbolic")
        self._best_val = state_dict.get("best_val", float("inf"))
        self._plateau_counter = state_dict.get("plateau_counter", 0)
        self.base_lrs = state_dict.get("base_lrs", self.base_lrs)
