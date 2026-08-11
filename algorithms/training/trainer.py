"""统一训练管线模块
==================

核心的训练编排器，负责将算法模型、数据集、调度器、checkpoint
等组件组合成完整的训练流程。

支持的训练模式：
--------------
1. **全局预训练** (train_global):
   - 扫描 core/data/ 下所有视频数据，构建全局数据集
   - 对一组算法分别训练，生成全局 checkpoint
   - 支持从头训练和增量训练（init_from_global=True）
   - 支持只使用新数据进行训练（use_new_data_only=True）

2. **视频微调** (finetune_for_video):
   - 基于全局 active checkpoint，对单个视频做少量 epoch 微调
   - 微调结果存到 <algo_id>/_video/<bvid>/ 子目录
   - 支持增量微调（基于视频已有 checkpoint 续训）

公开 API：
---------
    trainer = ModelTrainer()
    info = trainer.estimate_data_size()                        # 预扫描数据量/规模

    # 全局预训练
    results = trainer.train_global(
        algo_ids=["kalman_filter", "arima", ...],
        epochs=50,
        progress_cb=my_callback,    # 进度回调函数
        init_from_global=False,     # False=从头训练, True=增量训练
    )

    # 视频微调
    version = trainer.finetune_for_video(
        algo_id="kalman_filter",
        bvid="BV1xxx",
        epochs=5,
        progress_cb=my_callback,
    )

训练过程实时控制：
-----------------
通过 control_dict 字典（线程安全）可在训练过程中动态调整：
- control_dict["early_stop"] = True   → 优雅停止当前 epoch
- control_dict["lr_scale"] = 0.5      → 将学习率乘以指定系数
- control_dict["weight_decay"] = 0.01 → 设置权重衰减
- control_dict["activation_decay"]    → 激活值 L2 正则化系数
- control_dict["label_smoothing"]     → 标签噪声比例（防止过拟合）
- control_dict["mixup_alpha"]         → MixUp 数据增强的 Beta 分布参数
- control_dict["amplitude_weight"]    → 按振幅加权（避免高播放量主导 loss）
- control_dict["feat_dropout"]        → 特征随机丢弃比例
- control_dict["grad_clip"]           → 梯度裁剪阈值

算法侧约定（torch 算法必须实现以下方法）：
----------------------------------------
    build_model() -> nn.Module             # 构建 PyTorch 模型
    get_loss_fn() -> nn.Module             # 损失函数（可选，默认 MSELoss）
    preprocess_batch(batch) -> (input, target)  # batch 预处理（可选，默认透传）
    get_optimizer(model) -> Optimizer      # 优化器（可选，默认 Adam(lr=1e-3)）
    get_training_features() -> list[str]  # 训练特征列（可选，默认 5 个基础特征）
"""

import logging
import math
import time
from typing import Callable, Dict, List, Optional

import numpy as np
from utils import project_path
from algorithms.training.checkpoint_manager import CheckpointManager
from algorithms.training.device import get_device
from algorithms.training.dataset import VideoTimeSeriesDataset, estimate_dataset_size
from algorithms.training.schedulers import HyperbolicLR, ComboScheduler
from algorithms.training.trainer_io import save_checkpoint, _save_model_to_video_dir, evaluate_model

# 模块级日志记录器
logger = logging.getLogger(__name__)

# ── PyTorch 可用性检测 ─────────────────────────────────
_torch_available = True
try:
    import torch
    from torch.utils.data import DataLoader, random_split
except ImportError:
    _torch_available = False

# 进度回调类型别名：接收 Dict 参数，无返回值
ProgressCb = Optional[Callable[[Dict], None]]


class ModelTrainer:
    """统一训练编排器。

    职责：
    - 根据 algo_id 实例化算法对象
    - 构建数据集（全局或按视频）
    - 初始化模型/优化器/损失函数
    - 编排训练循环（epoch 内 batch 循环）
    - 收集和传递训练进度
    - 管理 checkpoint 的保存和加载
    - 响应实时控制指令（early_stop / lr_scale 等）

    数据增强技术（在 _train_epoch 中实现）：
    - Label Smoothing for Regression: 标签加 ~1% 高斯噪声，防止过拟合
    - MixUp 数据增强: 随机混合两个 batch 样本，提高泛化
    - Repulsive Diversity (特征随机丢弃): 迫使模型不依赖单一特征
    - SPADE-S 振幅加权 (Amplitude Weighting): 避免高播放量数据主导 loss
    - Activation Decay: 对预测输出加 L2 正则，平滑损失曲面
    """

    def __init__(self):
        """初始化训练器。

        自动检测最优计算设备并保存引用。
        """
        self.device = get_device()
        # AMP 混合精度：CUDA 设备启用 GradScaler，CPU/DirectML 回退到 FP32
        self._scaler = torch.amp.GradScaler() if self.device.type == "cuda" else None
        # TF32 张量核心加速：Ampere+ GPU 上 matmul 约 2x 加速，精度损失可忽略
        if self.device.type == "cuda":
            torch.set_float32_matmul_precision("high")
            torch.backends.cudnn.benchmark = True

    @property
    def _use_amp(self) -> bool:
        """是否启用 AMP 混合精度训练（仅 CUDA GPU 可用）。"""
        return self._scaler is not None

    # ── 预扫描 ──────────────────────────────────────────

    def estimate_data_size(self) -> Dict:
        """预扫描数据规模，返回预估信息。

        在开始训练前调用，用于 UI 显示预估的训练时间。

        Returns:
            Dict: {
                "total_videos": int,          # 总视频数
                "valid_videos": int,          # 有效视频数（数据量达标）
                "total_records": int,         # 总记录行数
                "total_samples": int,         # 可生成的训练样本数
                "estimated_time_s": int,      # 预估训练时间（秒），粗略公式：
                                              #   样本数 × 0.5ms/样本 × 50 epoch
            }
        """
        info = estimate_dataset_size()
        # 粗略估算：每样本每 epoch 约 0.5ms（CPU），50 epoch
        # 该估算是保守估计，实际速度取决于硬件和模型复杂度
        est_sec = max(5, int(info["total_samples"] * 0.0005 * 50))
        info["estimated_time_s"] = est_sec
        return info

    # ── 全局预训练 ────────────────────────────────────

    def train_global(
        self,
        algo_ids: List[str],
        epochs: int = 50,
        batch_size: int = 32,
        val_ratio: float = 0.15,
        progress_cb: ProgressCb = None,
        init_from_global: bool = False,
        lr: Optional[float] = None,
        control_dict: Optional[Dict] = None,
        use_new_data_only: bool = False,
    ) -> Dict[str, str]:
        """对一组算法做全局预训练。

        顺序遍历每个算法，扫描所有视频数据进行训练，
        生成全局 checkpoint。

        Args:
            algo_ids:          算法标识符列表，如 ["kalman_filter", "lstm_attention"]。
            epochs:            每个算法的训练轮数，默认 50。
            batch_size:        批大小，默认 32（数据量少时会自动缩小）。
            val_ratio:         验证集比例，默认 0.15（15%）。
            progress_cb:       进度回调函数，每 epoch 和关键阶段触发。
                               回调接收 Dict: {"stage": "start"|"epoch"|"done"|"error", ...}
            init_from_global:  True=增量训练（加载已有 checkpoint 继续训练），
                               False=从头训练（随机初始化）。
            lr:                学习率覆盖，None 时使用算法的默认学习率。
            control_dict:      线程安全的控制指令字典，每 epoch 检查其中的
                               early_stop / lr_scale / weight_decay 等键。
            use_new_data_only: True 时只使用上次训练截止时间戳之后的新数据，
                               避免重复训练已有数据。

        Returns:
            Dict[str, str]: {algo_id: version_name} — 成功的算法映射到版本名，
                            失败的算法映射到空字符串 ""。
        """
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法训练")

        results: Dict[str, str] = {}
        total = len(algo_ids)
        # 顺序训练每个算法（每个算法顺序执行，但算法间不阻塞）
        for i, algo_id in enumerate(algo_ids):
            # 通知进度：开始训练该算法
            self._emit(
                progress_cb,
                {
                    "stage": "start",
                    "algo_id": algo_id,
                    "current": i + 1,
                    "total": total,
                },
            )
            try:
                version = self._train_one(
                    algo_id=algo_id,
                    bvid=None,  # bvid=None 表示全局模式（扫描全部视频）
                    epochs=epochs,
                    batch_size=batch_size,
                    val_ratio=val_ratio,
                    progress_cb=progress_cb,
                    init_from_global=init_from_global,
                    lr=lr,
                    control_dict=control_dict,
                    use_new_data_only=use_new_data_only,
                )
                results[algo_id] = version
                # 通知进度：算法训练完成
                self._emit(
                    progress_cb,
                    {
                        "stage": "done",
                        "algo_id": algo_id,
                        "current": i + 1,
                        "total": total,
                        "version": version,
                    },
                )
            except Exception as e:
                # 单个算法训练失败不中断其他算法
                logger.exception("[trainer] %s 训练失败", algo_id)
                results[algo_id] = ""
                self._emit(
                    progress_cb,
                    {
                        "stage": "error",
                        "algo_id": algo_id,
                        "current": i + 1,
                        "total": total,
                        "error": str(e),
                    },
                )
        return results

    # ── 视频微调 ──────────────────────────────────────

    def finetune_for_video(
        self,
        algo_id: str,
        bvid: str,
        epochs: int = 5,
        batch_size: int = 16,
        progress_cb: ProgressCb = None,
        lr: Optional[float] = None,
        control_dict: Optional[Dict] = None,
        use_new_data_only: bool = False,
    ) -> str:
        """基于全局 active checkpoint，对单个视频做微调。

        微调结果保存到 algorithms/checkpoints/<algo_id>/_video/<bvid>/v*.pt。

        Args:
            algo_id:          算法标识符。
            bvid:             目标视频的 BV 号。
            epochs:           微调轮数，默认 5（通常少于全局预训练的 50）。
            batch_size:       批大小，默认 16（微调时数据少，batch 更小）。
            progress_cb:      进度回调函数。
            lr:               学习率覆盖。
            control_dict:     控制指令字典。
            use_new_data_only: True 时只使用新数据。

        Returns:
            str: 新创建的 checkpoint 版本名，失败时抛异常。
        """
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法训练")
        return self._train_one(
            algo_id=algo_id,
            bvid=bvid,
            epochs=epochs,
            batch_size=batch_size,
            val_ratio=0.15,
            progress_cb=progress_cb,
            init_from_global=True,  # 微调必须从已有 checkpoint 开始
            lr=lr,
            control_dict=control_dict,
            use_new_data_only=use_new_data_only,
        )

    # ── 内部训练核心 ─────────────────────────────────

    def _train_one(
        self,
        algo_id: str,
        bvid: Optional[str],
        epochs: int,
        batch_size: int,
        val_ratio: float,
        progress_cb: ProgressCb,
        init_from_global: bool = False,
        lr: Optional[float] = None,
        control_dict: Optional[Dict] = None,
        use_new_data_only: bool = False,
    ) -> str:
        """训练单个算法的内部核心方法。

        完整的训练流程：
        1. 实例化算法对象（通过 registry 查找）
        2. 读取已有 checkpoint 的元数据（增量训练用）
        3. 构建数据集和 DataLoader
        4. 初始化模型、优化器、损失函数
        5. 创建调度器（ComboScheduler）并恢复状态
        6. 执行训练循环（epoch 内 batch 循环）
        7. 在训练中应用数据增强和实时控制
        8. 每个 epoch 后验证并收集最佳模型
        9. 保存 checkpoint

        Args:
            algo_id:          算法标识符。
            bvid:             视频 BV 号，None 表示全局模式。
            epochs:           训练轮数。
            batch_size:       批大小。
            val_ratio:        验证集比例。
            progress_cb:      进度回调。
            init_from_global: 是否从已有 checkpoint 初始化。
            lr:               学习率覆盖。
            control_dict:     控制指令字典。
            use_new_data_only: 是否只用新数据。

        Returns:
            str: 新创建的 checkpoint 版本名。

        Raises:
            RuntimeError: 算法未注册、不支持训练、或数据不足。
        """
        # 1. 实例化算法对象
        algo = self._instantiate_algorithm(algo_id)
        if algo is None:
            raise RuntimeError(f"算法 {algo_id} 未注册或不支持训练")
        if not hasattr(algo, "build_model"):
            raise RuntimeError(f"算法 {algo_id} 未实现 build_model()")

        # 2. 读取已有 checkpoint 的数据范围（用于增量训练和新数据模式）
        prev_epochs = 0           # 之前已完成的训练轮数
        data_trained_until = 0.0  # 之前已训练到的数据时间戳
        try:
            _pc_ckpt = CheckpointManager(algo_id, bvid=bvid)
            _pc_ver = _pc_ckpt.list_versions()
            for _v in _pc_ver:
                if _v["active"]:
                    prev_epochs = _v.get("completed_epochs", 0)
                    data_trained_until = _v.get("data_trained_until", 0.0)
                    break
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 3. 确定数据时间范围并构建数据集
        # 如果需要只训练新数据且已有训练截止时间戳，则只加载新数据
        min_timestamp = data_trained_until if (use_new_data_only and data_trained_until > 0) else None
        dataset, train_loader, val_loader = self._prepare_dataset(
            algo, algo_id, bvid, batch_size, val_ratio, min_timestamp=min_timestamp
        )
        # 4. 初始化模型/优化器/损失函数
        model, optimizer, loss_fn, preprocess = self._init_model_optimizer(algo, algo_id, init_from_global, lr, bvid=bvid)

        # 5. 创建调度器：双曲线衰减 + Plateau 检测
        scheduler = ComboScheduler(optimizer, k=0.1, plateau_patience=5, plateau_factor=0.5, min_lr=1e-6)

        # 5b. 恢复调度器状态（增量训练续训）
        if prev_epochs > 0:
            scheduler._step_count = prev_epochs  # 直接设置步数计数器
        try:
            _sd_ckpt = CheckpointManager(algo_id, bvid=bvid)
            _sd_ver = _sd_ckpt.list_versions()
            for _v in _sd_ver:
                if _v["active"]:
                    _saved_sd = _v.get("scheduler_state")
                    if _saved_sd:
                        scheduler.load_state_dict(_saved_sd)  # 恢复完整调度器状态
                    break
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 6. 训练循环
        best_val = float("inf")      # 最佳验证损失
        best_tracked = float("inf")  # 用于 checkpoint 筛选的最佳 loss（含 train_loss）
        last_val = -1.0              # 最近一次验证损失
        start_time = time.time()     # 记录训练开始时间
        best_epoch = 0               # 最佳 epoch 编号
        train_losses = []            # 训练损失历史（用于早停判断）
        epoch_versions = []          # 每轮保存的 checkpoint (version, loss, epoch)

        for epoch in range(epochs):
            # 检查控制指令（early_stop / lr_scale 等）
            if self._check_control(control_dict, epoch, algo_id, bvid, optimizer, progress_cb, epochs, scheduler=scheduler):
                break

            # 训练一个 epoch
            train_loss = self._train_epoch(model, train_loader, optimizer, loss_fn, preprocess, control_dict, algo_id, progress_cb=progress_cb)
            train_losses.append(train_loss)

            # 调度器步进（双曲线模式）
            if control_dict and control_dict.get("lr_scale"):
                # lr_scale 已由 _check_control 应用到 base_lrs，跳过自动衰减
                pass
            else:
                scheduler.step_hyperbolic()

            # 动态早停检查
            if control_dict and control_dict.get("early_stop"):
                if control_dict.pop("_force_early_stop", False):
                    break
                if len(train_losses) >= 6:
                    recent_3 = sum(train_losses[-3:]) / 3
                    prev_3 = sum(train_losses[-6:-3]) / 3
                    if prev_3 > 1e-8 and (prev_3 - recent_3) / prev_3 < 0.015:
                        break
                control_dict["early_stop"] = False

            # 验证并发送 epoch 进度
            last_val = self._validate_and_emit(
                model, val_loader, loss_fn, preprocess,
                best_val, progress_cb, algo_id, bvid,
                epoch, epochs, train_loss, start_time,
                prev_epochs=prev_epochs,
            )
            # 更新最佳 epoch 追踪
            if val_loader is not None and last_val < best_val:
                best_val = last_val
                best_epoch = epoch + 1
            # 用于 checkpoint 筛选：有验证集用 val_loss，否则用 train_loss
            tracked_loss = last_val if val_loader is not None else train_loss
            if tracked_loss < best_tracked:
                best_tracked = tracked_loss

            # ── 每 epoch 保存 checkpoint（断点续训保护） ──
            data_until = getattr(dataset, "max_timestamp", 0.0)
            version = save_checkpoint(
                model, algo_id, bvid, dataset, best_val, last_val, val_loader,
                1, optimizer, prev_epochs=prev_epochs,
                data_trained_until=data_until,
                scheduler=scheduler, best_epoch=best_epoch,
            )
            epoch_versions.append((version, tracked_loss, epoch + 1))

            # 调度器 Plateau 检测
            scheduler.update(last_val)

        # 7. 清理：仅保留最优 epoch 的 checkpoint，删除中间版本
        if len(epoch_versions) > 1:
            epoch_versions.sort(key=lambda x: x[1])  # 按 loss 升序
            best_version, best_loss, best_ep = epoch_versions[0]
            ckpt_cleanup = CheckpointManager(algo_id, bvid=bvid)
            deleted = 0
            for v, _, _ in epoch_versions[1:]:
                if ckpt_cleanup.delete(v):
                    deleted += 1
            logger.info(
                "[trainer] %s 保留最优 epoch %d (loss=%.4f)，清理 %d 个中间版本",
                algo_id, best_ep, best_loss, deleted,
            )
            return best_version
        elif epoch_versions:
            return epoch_versions[0][0]
        return ""

    # ── 辅助方法 ─────────────────────────────────────

    def _prepare_dataset(self, algo, algo_id, bvid, batch_size, val_ratio, min_timestamp=None):
        """构建数据集和 DataLoader。

        流程：
        1. 从算法获取训练特征列表和窗口参数
        2. 构造 VideoTimeSeriesDataset
        3. 将数据集特征数传给算法（供 build_model() 使用）
        4. 根据数据量自动缩放 batch_size
        5. 按 val_ratio 分割训练集/验证集
        6. 创建 DataLoader

        Args:
            algo:          算法对象。
            algo_id:       算法标识符。
            bvid:          视频 BV 号，None 表示全局。
            batch_size:    初始批大小（可能会自动缩小）。
            val_ratio:     验证集比例。
            min_timestamp: 数据时间下限（增量训练用）。

        Returns:
            Tuple[Dataset, DataLoader, Optional[DataLoader]]: (数据集, 训练加载器, 验证加载器)
        """
        # 从算法获取训练特征（如果算法定义了 get_training_features()）
        features = getattr(algo, "get_training_features", lambda: None)() or [
            "view_count",
            "like_count",
            "coin_count",
            "favorite_count",
            "share_count",
        ]
        # 从算法获取窗口参数（默认 window=10, horizon=3）
        window = getattr(algo, "training_window", 10)
        horizon = getattr(algo, "training_horizon", 3)

        # 构建数据集
        # GPU 预载模式：将全部时序数据直接加载到显存，消除逐 batch 传输
        gpu_preload = self.device.type == "cuda"
        dataset = VideoTimeSeriesDataset(
            window=window, horizon=horizon,
            bvids=[bvid] if bvid else None,  # 指定视频 vs 全部视频
            features=features,
            min_timestamp=min_timestamp,
            device=self.device if gpu_preload else None,
        )
        if len(dataset) == 0:
            raise RuntimeError(f"没有足够的训练样本（algo={algo_id}, bvid={bvid}）")

        # 将数据集实际特征维度传给算法，供 build_model() 使用
        # （特征维度会影响模型输入层的大小）
        algo._training_n_features = dataset.n_features()

        # 自动根据数据量缩放 batch_size：连续光滑公式，无硬阈值
        # 公式：batch_size = min(batch_size, max(4, 2 * sqrt(n)))
        # 小数据集时自动减小 batch_size 避免无 batch 训练
        _n = len(dataset)
        _orig_bs = batch_size
        batch_size = min(batch_size, max(4, int(math.sqrt(_n) * 2)))
        if batch_size != _orig_bs:
            logger.info("[trainer] %s batch_size 自动调整: %d → %d (数据量 %d)", algo_id, _orig_bs, batch_size, _n)

        # 划分训练集和验证集
        if val_ratio > 0 and _n >= 10:
            # 数据量足够时划分验证集
            val_size = max(1, int(_n * val_ratio))
            train_size = _n - val_size
            # 固定随机种子确保可复现
            train_set, val_set = random_split(
                dataset, [train_size, val_size], generator=torch.Generator().manual_seed(42)
            )
        else:
            # 数据量太少时不划分验证集
            train_set, val_set = dataset, None

        # 创建 DataLoader
        # 训练集 shuffle=True 打乱顺序；验证集不需要 shuffle
        # drop_last=False 保留最后一个不完整 batch
        # GPU 预载模式：num_workers=0（GPU tensor 不可跨进程 pickle）
        # CPU 模式：num_workers=2, pin_memory=True, persistent_workers
        if gpu_preload:
            train_loader = DataLoader(
                train_set, batch_size=batch_size, shuffle=True, drop_last=False,
            )
            val_loader = (
                DataLoader(val_set, batch_size=batch_size, shuffle=False)
                if val_set else None
            )
        else:
            train_loader = DataLoader(
                train_set, batch_size=batch_size, shuffle=True, drop_last=False,
                num_workers=2, pin_memory=True, persistent_workers=True,
            )
            val_loader = (
                DataLoader(val_set, batch_size=batch_size, shuffle=False,
                           num_workers=1, pin_memory=True)
                if val_set else None
            )
        return dataset, train_loader, val_loader

    def _init_model_optimizer(self, algo, algo_id, init_from_global, lr, bvid=None):
        """初始化模型、优化器和损失函数。

        加载顺序：视频 checkpoint → 全局 checkpoint → 随机初始化

        Args:
            algo:            算法对象。
            algo_id:         算法标识符。
            init_from_global: 是否从已有 checkpoint 加载权重。
            lr:              学习率覆盖，None 时使用算法默认。
            bvid:            视频 BV 号（用于视频级 checkpoint 加载）。

        Returns:
            Tuple[nn.Module, Optimizer, nn.Module, Callable]:
                (模型, 优化器, 损失函数, batch 预处理函数)
        """
        # 调用算法的 build_model() 构建模型
        model = algo.build_model()

        if init_from_global:
            loaded = False
            # 优先从视频级 checkpoint 加载（增量训练续训）
            if bvid:
                video_ckpt = CheckpointManager(algo_id, bvid=bvid)
                if video_ckpt.has_checkpoint():
                    state = video_ckpt.load()
                    if state is not None:
                        try:
                            state = {k[len("_orig_mod."):] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}
                            model.load_state_dict(state)
                            logger.info("[trainer] %s 从视频 %s checkpoint 续训", algo_id, bvid)
                            loaded = True
                        except Exception as e:
                            logger.warning("[trainer] %s 加载视频 state_dict 失败: %s", algo_id, e)
            # 降级到全局 checkpoint
            if not loaded:
                global_ckpt = CheckpointManager(algo_id)
                if global_ckpt.has_checkpoint():
                    state = global_ckpt.load()
                    if state is not None:
                        try:
                            state = {k[len("_orig_mod."):] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}
                            model.load_state_dict(state)
                            logger.info("[trainer] %s 从全局 checkpoint 初始化", algo_id)
                        except Exception as e:
                            logger.warning("[trainer] %s 加载全局 state_dict 失败: %s", algo_id, e)

        # 将模型移动到检测到的最优设备（GPU/NPU/CPU）
        model = model.to(self.device)
        # torch.compile 已禁用：多种模型结构（BiTCN 的 Python for 循环、Crossformer 的动态
        # segs 列表、FEDformer/FreTS 的 FFT 操作）与 dynamo 的 FX tracing / CUDA graph 的
        # graph break 机制冲突，导致 "FX to symbolically trace a dynamo-optimized function"
        # 或 "torch._C._is_key_in_tls" AssertionError。按模型逐一适配成本过高，统一禁用。
        # 需要时可重新启用：torch.compile(model, mode="default")

        # 获取损失函数（默认 MSELoss）
        loss_fn = getattr(algo, "get_loss_fn", lambda: torch.nn.MSELoss())()
        # 创建优化器（默认 Adam(lr=1e-3)）
        if lr is not None:
            optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        else:
            optimizer = getattr(algo, "get_optimizer", lambda m: torch.optim.Adam(m.parameters(), lr=1e-3))(model)
        # 获取 batch 预处理函数（默认直接解包 (x, y)）
        preprocess = getattr(algo, "preprocess_batch", _default_preprocess)
        return model, optimizer, loss_fn, preprocess

    @staticmethod
    def _check_control(control_dict, epoch, algo_id, bvid, optimizer, progress_cb, epochs, scheduler=None):
        """检查并应用训练过程中的实时控制指令。

        支持的指令键（应用后会从 control_dict 中弹出）：
        - lr_scale: float  → 将学习率乘以系数，同时更新调度器 base_lrs
        - weight_decay: float → 设置优化器的权重衰减
        - early_stop: bool → 触发动态早停（需配合 _train_one 中的逻辑）

        Args:
            control_dict: 控制指令字典（线程安全）。
            epoch:        当前 epoch 索引。
            algo_id:      算法标识符。
            bvid:         视频 BV 号。
            optimizer:    PyTorch 优化器。
            progress_cb:  进度回调。
            epochs:       总训练轮数。
            scheduler:    ComboScheduler 实例（可选）。

        Returns:
            bool: 如果 lr_scale 被应用则返回 False（不触发早停），
                  否则返回 control_dict 中的 early_stop 值（如果有）。
        """
        if control_dict is None:
            return False

        # ── 学习率缩放 ────────────────────────────────
        lr_scale = control_dict.pop("lr_scale", None)
        if lr_scale is not None:
            if scheduler is not None and hasattr(scheduler, "base_lrs"):
                # 更新调度器的 base_lrs，让调度器在此基础上继续衰减
                scheduler.base_lrs = [blr * lr_scale for blr in scheduler.base_lrs]
            # 直接应用缩放
            for pg in optimizer.param_groups:
                new_lr = pg["lr"] * lr_scale
                pg["lr"] = new_lr
            logger.info("[trainer] %s LR adjusted by ×%.2f → %.6f", algo_id, lr_scale, optimizer.param_groups[0]["lr"])

        # ── 权重衰减调整 ──────────────────────────────
        weight_decay = control_dict.pop("weight_decay", None)
        if weight_decay is not None:
            for pg in optimizer.param_groups:
                pg["weight_decay"] = weight_decay
            logger.info("[trainer] %s weight_decay → %.4f", algo_id, weight_decay)
            ModelTrainer._emit(
                progress_cb,
                {
                    "stage": "auto_adjust",
                    "algo_id": algo_id,
                    "bvid": bvid,
                    "action": "lr_scale",
                    "message": f"学习率调整为 {optimizer.param_groups[0]['lr']:.6f} (×{lr_scale:.2f})",
                    "new_lr": optimizer.param_groups[0]["lr"],
                    "scale": lr_scale,
                    "epoch": epoch + 1,
                    "epochs": epochs,
                },
            )
        return False

    def _train_epoch(self, model, train_loader, optimizer, loss_fn, preprocess, control_dict, algo_id, progress_cb=None):
        """执行一个完整 epoch 的训练。

        包含以下数据增强和正则化技术：
        1. Label Smoothing for Regression: 给目标加小比例高斯噪声
        2. MixUp 数据增强: 随机混合两个样本（需 mixup_alpha > 0）
        3. Repulsive Diversity (特征随机丢弃): 迫使模型不依赖单一特征
        4. SPADE-S 振幅加权: 按目标振幅归一化 loss，避免高值主导
        5. Activation Decay: 对预测输出加 L2 正则化
        6. NaN/Inf 检测: 检测到异常值时触发强制早停

        Args:
            model:         PyTorch 模型。
            train_loader:  训练数据 DataLoader。
            optimizer:     PyTorch 优化器。
            loss_fn:       损失函数（默认 MSELoss）。
            preprocess:    batch 预处理函数。
            control_dict:  控制指令字典。
            algo_id:       算法标识符。
            progress_cb:   进度回调（每 10% batch 触发一次）。

        Returns:
            float: 平均训练损失（所有 batch 的均值）。
        """
        model.train()  # 设为训练模式（启用 dropout/batchnorm 等）
        train_loss = 0.0
        n_batches = 0
        total_batches = len(train_loader)

        # batch 报告间隔：优先使用用户配置，否则默认每 10%
        report_interval = max(1, total_batches // 10)  # 默认 10%
        if control_dict and control_dict.get("_batch_interval"):
            bi = control_dict["_batch_interval"]
            mode = control_dict.get("_batch_interval_mode", "%")
            if mode == "%":
                report_interval = max(1, int(total_batches * bi))
            else:
                report_interval = max(1, int(bi))

        # 从 control_dict 读取配置（带默认值）
        act_decay = 0.0
        label_noise = 0.0
        mixup_alpha = 0.0
        amp_weight = False
        feat_dropout = 0.0
        if control_dict is not None:
            act_decay = control_dict.get("activation_decay", 0.0)
            label_noise = control_dict.get("label_smoothing", 0.0)
            mixup_alpha = control_dict.get("mixup_alpha", 0.0)
            amp_weight = control_dict.get("amplitude_weight", False)
            feat_dropout = control_dict.get("feat_dropout", 0.0)

        for batch in train_loader:
            # ── 数据预处理 ────────────────────────────
            x, y = preprocess(batch)
            # non_blocking=True: pin_memory 路径异步传输（GPU 预载时已同设备，no-op）
            x = x.to(self.device, non_blocking=True)
            y = y.to(self.device, non_blocking=True)

            # ── Label Smoothing: 回归版标签平滑 ────────
            # 给目标加 ~1% 噪声，防止过拟合精确值
            if label_noise > 0 and y.numel() > 0:
                y_std = y.std().item()
                if y_std > 1e-8:
                    noise = torch.randn_like(y) * y_std * label_noise
                    y = y + noise

            # ── MixUp 数据增强 ─────────────────────────
            # 随机混合两个 batch 样本：x' = lam*x + (1-lam)*x[perm]
            if mixup_alpha > 0 and x.size(0) > 1:
                lam = float(np.random.beta(mixup_alpha, mixup_alpha))
                perm = torch.randperm(x.size(0), device=self.device)
                x = lam * x + (1 - lam) * x[perm]
                y = lam * y + (1 - lam) * y[perm]

            # ── Repulsive Diversity: 特征随机丢弃 ──────
            # 按概率随机丢弃整个特征维度，迫使模型不依赖单一特征
            if feat_dropout > 0 and x.dim() >= 2:
                # x shape: [B, W, F] (3D) 或 [B, F] (2D)
                feat_dim = x.shape[-1]
                if feat_dim > 1:
                    if x.dim() == 3:
                        # 3D: 对每个特征维度生成 Bernoulli mask
                        mask = torch.bernoulli(
                            torch.full((feat_dim,), 1.0 - feat_dropout, device=self.device)
                        ).view(1, 1, feat_dim)
                    else:
                        # 2D: 对每个特征维度生成 Bernoulli mask
                        mask = torch.bernoulli(
                            torch.full((feat_dim,), 1.0 - feat_dropout, device=self.device)
                        ).view(1, feat_dim)
                    x = x * mask

            # ── 前向传播（AMP 混合精度） ─────────────────
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=self.device.type, enabled=self._use_amp):
                pred = model(x)
                # 如果预测输出多了一个维度（如 [B, H, 1] → [B, H]）
                if pred.dim() == y.dim() + 1 and pred.shape[-1] == 1:
                    pred = pred.squeeze(-1)

                # ── SPADE-S 偏斜修正：按振幅加权 ────────────
                # 避免高播放量视频的 loss 主导梯度，按目标振幅归一化
                if amp_weight:
                    diff = pred - y
                    sq_err = diff ** 2
                    # 分母 = |y| 的均值（按最后一个维度），clamp(min=1.0) 防止除零
                    denom = y.abs().mean(dim=-1, keepdim=True).clamp(min=1.0).detach()
                    loss = (sq_err / denom).mean()
                else:
                    loss = loss_fn(pred, y)

                # ── Activation Decay: 对预测输出加 L2 正则 ──
                # 平滑损失曲面，提高泛化能力
                if act_decay > 0:
                    loss = loss + act_decay * (pred ** 2).mean()

            # ── NaN/Inf 检测（使用未缩放的原始 loss） ──────
            loss_val = float(loss.item())
            if control_dict is not None and (math.isnan(loss_val) or math.isinf(loss_val)):
                # 检测到异常值时触发强制早停（直接退出整个训练）
                logger.warning("[trainer] %s NaN/Inf mid-epoch, early stopping", algo_id)
                control_dict["early_stop"] = True
                control_dict["_force_early_stop"] = True
                break

            # ── 反向传播（AMP: GradScaler 缩放 loss） ──────
            if self._scaler:
                self._scaler.scale(loss).backward()
                # 梯度裁剪前必须先 unscale，还原真实梯度
                self._scaler.unscale_(optimizer)
            else:
                loss.backward()
            # 梯度裁剪（防止梯度爆炸）
            if control_dict is not None and control_dict.get("grad_clip", 0) > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), control_dict["grad_clip"])
            # 优化器步进（AMP: scaler 控制 step + update）
            if self._scaler:
                self._scaler.step(optimizer)
                self._scaler.update()
            else:
                optimizer.step()

            train_loss += loss_val
            n_batches += 1

            # 每 10% batch 发出一次进度（避免过于频繁）
            if progress_cb and n_batches % report_interval == 0:
                self._emit(progress_cb, {
                    "stage": "batch",
                    "algo_id": algo_id,
                    "batch": n_batches,
                    "total_batches": total_batches,
                    "batch_loss": round(loss_val, 6),
                    "avg_loss": round(train_loss / n_batches, 6),
                })

        return train_loss / max(1, n_batches)

    def _validate_and_emit(
        self,
        model,
        val_loader,
        loss_fn,
        preprocess,
        best_val,
        progress_cb,
        algo_id,
        bvid,
        epoch,
        epochs,
        train_loss,
        start_time,
        prev_epochs=0,
    ):
        """验证模型并发起进度回调。

        如果没有验证集，则验证损失为 -1.0。

        Args:
            model:        PyTorch 模型。
            val_loader:   验证数据 DataLoader。
            loss_fn:      损失函数。
            preprocess:   batch 预处理函数。
            best_val:     当前最佳验证损失。
            progress_cb:  进度回调。
            algo_id:      算法标识符。
            bvid:         视频 BV 号。
            epoch:        当前 epoch（0-based）。
            epochs:       总 epoch 数。
            train_loss:   当前训练损失。
            start_time:   训练开始时间。
            prev_epochs:  之前已完成的 epoch 数（增量训练用）。

        Returns:
            float: 验证损失，无验证集时返回 -1.0。
        """
        last_val = -1.0
        if val_loader is not None:
            last_val = evaluate_model(model, val_loader, loss_fn, preprocess)
        # 发送 epoch 完成进度
        ModelTrainer._emit(
            progress_cb,
            {
                "stage": "epoch",
                "algo_id": algo_id,
                "bvid": bvid,
                "epoch": epoch + 1,                       # 当前 epoch（1-based 显示）
                "epochs": epochs,
                "total_epoch": prev_epochs + epoch + 1,   # 累计总 epoch
                "total_epochs": prev_epochs + epochs,
                "_prev_epochs": prev_epochs,
                "train_loss": train_loss,
                "val_loss": last_val,
                "elapsed_s": time.time() - start_time,    # 已用时间（秒）
            },
        )
        return last_val

    # ═══ Checkpoint/评估方法已移入 trainer_io.py ═══

    @staticmethod
    def _emit(cb: ProgressCb, payload: Dict):
        """安全地调用进度回调函数。

        如果回调抛出异常，会被捕获并 debug 日志记录，
        不会中断训练流程。

        Args:
            cb:      进度回调函数（可为 None）。
            payload: 传递给回调的进度数据字典。
        """
        if cb is None:
            return
        try:
            cb(payload)
        except Exception as e:
            logger.debug("progress_cb 抛异常（已忽略）: %s", e)

    @staticmethod
    def _instantiate_algorithm(algo_id: str):
        """从 AlgorithmRegistry 按 algorithm_id 查找算法实例。

        Args:
            algo_id: 算法标识符。

        Returns:
            算法对象，未找到时返回 None。
        """
        try:
            from algorithms.registry import AlgorithmRegistry
        except Exception as e:
            logger.error("无法导入 AlgorithmRegistry: %s", e)
            return None
        AlgorithmRegistry.initialize()
        algo = AlgorithmRegistry.get_algorithm(algo_id)
        return algo


def _default_preprocess(batch):
    """默认 batch 解包预处理函数。

    PyTorch DataLoader 返回的 batch 是一个元组 (x, y)，
    直接解包为输入和目标。

    Args:
        batch: DataLoader 返回的 batch，格式为 (x, y)。

    Returns:
        Tuple[Tensor, Tensor]: (输入 x, 目标 y)。
    """
    return batch[0], batch[1]
