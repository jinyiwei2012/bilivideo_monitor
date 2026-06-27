"""自定义学习率调度器模块
=======================

为 B站视频播放量预测的增量训练场景量身定制的学习率调度器。

与标准 PyTorch 调度器的区别：
- 标准调度器（如 StepLR、CosineAnnealingLR）假设从 epoch 0 开始训练，
  总训练轮数是固定的。在增量训练场景中，每次 resumed 后这些调度器会
  重置学习率，导致历史衰减信息丢失。
- 本模块的调度器**只依赖当前已完成的 epoch 数**，不与总轮数绑定，
  增量训练 resume 后能无缝继续衰减。

提供的调度器：
-------------
1. **HyperbolicLR**: 双曲线学习率衰减
   - 公式: lr(epoch) = base_lr / (1 + k * epoch)
   - 特点: 与总轮数无关，epoch 越大衰减越慢（趋于平滑）
   - 适用: 长时间增量训练的基线衰减策略

2. **ComboScheduler**: 组合调度器
   - 正常时使用 HyperbolicLR 双曲线衰减
   - 检测到 plateau（验证损失不再下降）时自动切换为衰减模式（LR 乘以 factor）
   - 整合两种策略的优点：前期平缓探索 + 后期强制突破
   - 支持状态持久化（state_dict/load_state_dict），适合增量训练恢复

使用示例：
---------
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    scheduler = ComboScheduler(optimizer, k=0.1, plateau_patience=5)

    for epoch in range(epochs):
        train_loss = train_one_epoch(...)
        val_loss = validate(...)
        scheduler.step_hyperbolic()     # 双曲线衰减
        scheduler.update(val_loss)       # 检测 plateau
"""

import math
import logging

# 模块级日志记录器
logger = logging.getLogger(__name__)

# ── PyTorch 可用性检测 ─────────────────────────────────
_torch_available = True
try:
    import torch
    from torch.optim.lr_scheduler import _LRScheduler
except ImportError:
    _torch_available = False
    # 无 torch 时用 object 占位，保证模块可导入
    _LRScheduler = object


class HyperbolicLR(_LRScheduler):
    """双曲线学习率衰减调度器。

    学习率按双曲线函数衰减，与总训练轮数无关，只依赖当前已完成的 epoch 数。
    特别适合增量训练场景：每次 resumed 后继续衰减，不会重置。

    衰减公式：
        lr(epoch) = max(base_lr / (1 + k * epoch), min_lr)

    特点：
    - epoch=0 时 lr = base_lr（无衰减）
    - epoch 增大时 lr 平滑下降
    - k 越大衰减越快
    - 不会低于 min_lr

    Args:
        optimizer:  被包装的 PyTorch 优化器。
        k:          衰减速率，越大衰减越快（默认 0.1）。
        min_lr:     最低学习率下限，防止学习率过小（默认 1e-6）。
        last_epoch: 初始 epoch 索引（续训时从非零开始，默认 -1）。
    """

    def __init__(self, optimizer, k: float = 0.1, min_lr: float = 1e-6, last_epoch: int = -1):
        """初始化双曲线衰减调度器。

        Args:
            optimizer:  PyTorch 优化器实例。
            k:          衰减速率参数，默认 0.1。
            min_lr:     学习率下限，默认 1e-6。
            last_epoch: 上次训练的最后一个 epoch 索引，默认 -1（从头开始）。
        """
        self.k = k
        self.min_lr = min_lr
        super().__init__(optimizer, last_epoch)

    def get_lr(self):
        """计算当前 epoch 的学习率。

        被 PyTorch 的 _LRScheduler.step() 内部调用。

        Returns:
            List[float]: 每个参数组对应的学习率列表。
        """
        # epoch 0 时返回初始学习率
        if self.last_epoch == 0:
            return [base_lr for base_lr in self.base_lrs]
        # 双曲线衰减公式: lr = base_lr / (1 + k * epoch)
        # max(lr, min_lr) 确保不低于下限
        return [max(base_lr / (1.0 + self.k * self.last_epoch), self.min_lr) for base_lr in self.base_lrs]


class ComboScheduler:
    """组合学习率调度器：正常时双曲线衰减，检测到 plateau 时切换策略。

    不继承 PyTorch 的 _LRScheduler，而是主动管理两种策略的切换和状态持久化。
    设计为与 ModelTrainer 配合使用。

    工作流程：
    1. 每个 epoch 调用 step_hyperbolic() → 按双曲线公式衰减 LR
    2. 验证后调用 update(val_loss) → 检测是否进入 plateau
    3. 如果连续 plateau_patience 轮验证损失不改善 → 切换为 plateau 模式
    4. plateau 模式下将 LR 乘以 plateau_factor（骤降一次）

    两种模式：
    - "hyperbolic": 双曲线平滑衰减（正常训练阶段）
    - "plateau":    Loss 不再下降时 LR 骤降因子（强制突破）

    Args:
        optimizer:         被包装的 PyTorch 优化器。
        k:                 HyperbolicLR 的衰减速率（默认 0.1）。
        plateau_patience:  val_loss 连续多少轮不下降视为 plateau（默认 5）。
        plateau_factor:    plateau 时 LR 乘以该系数，通常 < 1（默认 0.5）。
        min_lr:            最低学习率下限（默认 1e-6）。
    """

    def __init__(
        self,
        optimizer,
        k: float = 0.1,
        plateau_patience: int = 5,
        plateau_factor: float = 0.5,
        min_lr: float = 1e-6,
    ):
        """初始化组合调度器。

        Args:
            optimizer:         PyTorch 优化器实例。
            k:                 双曲线衰减速率，默认 0.1。
            plateau_patience:  验证损失的耐心轮数，默认 5。
            plateau_factor:    进入 plateau 模式时学习率乘以此系数，默认 0.5。
            min_lr:            学习率绝对下限，默认 1e-6。
        """
        self.optimizer = optimizer
        # 缓存每个参数组的初始学习率，防止被外部修改
        self.base_lrs = [pg["lr"] for pg in optimizer.param_groups]
        self.k = k
        self.plateau_patience = plateau_patience
        self.plateau_factor = plateau_factor
        self.min_lr = min_lr

        # ── 运行时状态 ───────────────────────────────
        self._step_count = 0           # 累计双曲线步数（不限模式）
        self._mode = "hyperbolic"      # 当前模式："hyperbolic" 或 "plateau"
        self._best_val = float("inf")  # 历史最佳验证损失
        self._plateau_counter = 0      # 连续未改善的轮数计数
        self._last_lrs = list(self.base_lrs)  # 上次学习率快照

    def step(self, epoch: int = None):
        """兼容 PyTorch scheduler 接口的步进方法。

        Args:
            epoch: 当前 epoch 数（可选）。
        """
        if _torch_available and isinstance(self.optimizer, torch.optim.Optimizer):
            self._step_count += 1

    def update(self, val_loss: float):
        """用验证损失更新状态，检测 plateau 并自动切换策略。

        当连续 plateau_patience 轮验证损失不改善时，从 "hyperbolic" 模式
        切换到 "plateau" 模式，将当前 LR 乘以 plateau_factor。

        Args:
            val_loss: 当前 epoch 的验证损失值（MSE/MAE 等，越低越好）。
                      负值或 torch 不可用时跳过处理。
        """
        if val_loss < 0 or not _torch_available:
            return

        if val_loss < self._best_val:
            # 验证损失改善：更新最佳值，重置计数器，恢复双曲线模式
            self._best_val = val_loss
            self._plateau_counter = 0
            self._mode = "hyperbolic"  # 恢复双曲线衰减
            return

        # 验证损失未改善：累加计数器
        self._plateau_counter += 1

        # 检测到 plateau：从双曲线模式切换到骤降模式
        if self._plateau_counter >= self.plateau_patience and self._mode == "hyperbolic":
            self._mode = "plateau"
            # 读取各组当前 LR，乘以 plateau_factor
            current_lrs = [pg["lr"] for pg in self.optimizer.param_groups]
            new_lrs = [max(lr * self.plateau_factor, self.min_lr) for lr in current_lrs]
            for pg, new_lr in zip(self.optimizer.param_groups, new_lrs):
                pg["lr"] = new_lr
            logger.info(
                "[ComboScheduler] plateau 检测 (val_loss %.4f 连续 %d 轮未改善)，切换为衰减模式 LR=%.6f",
                val_loss, self.plateau_patience, new_lrs[0],
            )
            # 重置计数器（防止重复触发）
            self._plateau_counter = 0

    def step_hyperbolic(self):
        """每 epoch 调用：执行双曲线衰减步进。

        仅在 "hyperbolic" 模式下有效，plateau 模式下不执行衰减
        （plateau 模式下的 LR 调整由 update() 触发的一次性骤降完成）。

        衰减公式: new_lr = base_lr / (1 + k * step_count)
        """
        if self._mode != "hyperbolic":
            return
        if not _torch_available:
            return
        self._step_count += 1
        for pg, base_lr in zip(self.optimizer.param_groups, self.base_lrs):
            new_lr = max(base_lr / (1.0 + self.k * self._step_count), self.min_lr)
            pg["lr"] = new_lr

    def get_lr(self) -> float:
        """获取当前有效学习率。

        Returns:
            float: 第一个参数组的当前学习率，torch 不可用时返回 0.0。
        """
        if _torch_available and len(self.optimizer.param_groups) > 0:
            return self.optimizer.param_groups[0]["lr"]
        return 0.0

    def state_dict(self) -> dict:
        """导出调度器的完整状态，用于 checkpoint 持久化。

        保存所有运行时状态变量，支持增量训练恢复。

        Returns:
            dict: 包含所有调度器状态的字典。
        """
        return {
            "step_count": self._step_count,
            "mode": self._mode,
            "best_val": self._best_val,
            "plateau_counter": self._plateau_counter,
            "base_lrs": self.base_lrs,
        }

    def load_state_dict(self, state_dict: dict):
        """从 checkpoint 恢复调度器状态。

        支持在增量训练中从上次训练的状态继续。

        Args:
            state_dict: 之前由 state_dict() 导出的状态字典。
        """
        self._step_count = state_dict.get("step_count", 0)
        self._mode = state_dict.get("mode", "hyperbolic")
        self._best_val = state_dict.get("best_val", float("inf"))
        self._plateau_counter = state_dict.get("plateau_counter", 0)
        self.base_lrs = state_dict.get("base_lrs", self.base_lrs)
