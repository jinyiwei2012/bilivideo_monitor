"""统一训练管线

公开 API：
    trainer = ModelTrainer()
    trainer.estimate_data_size()                              # 预扫描数据量
    trainer.train_global(algo_ids, epochs=50, progress_cb=cb) # 全局预训练
    trainer.finetune_for_video(algo_id, bvid, epochs=5)       # 视频微调

算法侧约定（torch 算法必须实现以下方法）：
    build_model() -> nn.Module
    get_loss_fn() -> nn.Module        （可选，默认 MSELoss）
    preprocess_batch(batch) -> (input, target)（可选，默认透传）
    get_optimizer(model) -> Optimizer  （可选，默认 Adam(lr=1e-3)）
    get_training_features() -> list[str]（可选，默认 ['view_count', 'like_count', 'coin_count']）
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
from algorithms.training.schedulers import ComboScheduler

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
    from torch.utils.data import DataLoader, random_split
except ImportError:
    _torch_available = False

ProgressCb = Optional[Callable[[Dict], None]]


class ModelTrainer:
    """统一训练编排器。"""

    def __init__(self):
        self.device = get_device()

    # ── 预扫描 ──────────────────────────────────────────

    def estimate_data_size(self) -> Dict:
        """返回 {total_videos, valid_videos, total_records, total_samples, estimated_time_s}"""
        info = estimate_dataset_size()
        # 粗略估算：每样本每 epoch 约 0.5ms（CPU），50 epoch
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
        """对一组算法做全局预训练，返回 {algo_id: version_name}。失败的算法 value = ''。

        Args:
            init_from_global: True=增量训练（加载已有 checkpoint 继续训练），
                              False=重新训练（从随机初始化开始）。
            control_dict: 线程安全的调整指令字典。_train_one 每 epoch 检查其中的
                          early_stop (bool) 和 lr_scale (float) 并自动响应。
            use_new_data_only: True 时只使用上次训练截止后的新数据。
        """
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法训练")

        results: Dict[str, str] = {}
        total = len(algo_ids)
        for i, algo_id in enumerate(algo_ids):
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
                    bvid=None,
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
        """基于全局 active checkpoint 微调，存到 <algo_id>/_video/<bvid>/v*.pt。

        Args:
            control_dict: 线程安全的调整指令字典。_train_one 每 epoch 检查其中的
                          early_stop (bool) 和 lr_scale (float) 并自动响应。
            use_new_data_only: True 时只使用上次训练截止后的新数据。
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
            init_from_global=True,
            lr=lr,
            control_dict=control_dict,
            use_new_data_only=use_new_data_only,
        )

    # ── 内部 ──────────────────────────────────────────

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
        algo = self._instantiate_algorithm(algo_id)
        if algo is None:
            raise RuntimeError(f"算法 {algo_id} 未注册或不支持训练")
        if not hasattr(algo, "build_model"):
            raise RuntimeError(f"算法 {algo_id} 未实现 build_model()")

        # 读取已有 checkpoint 的数据范围（增量训练 / 新数据模式用）
        prev_epochs = 0
        data_trained_until = 0.0
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

        min_timestamp = data_trained_until if (use_new_data_only and data_trained_until > 0) else None
        dataset, train_loader, val_loader = self._prepare_dataset(
            algo, algo_id, bvid, batch_size, val_ratio, min_timestamp=min_timestamp
        )
        model, optimizer, loss_fn, preprocess = self._init_model_optimizer(
            algo, algo_id, init_from_global, lr, bvid=bvid
        )

        # 创建调度器
        scheduler = ComboScheduler(optimizer, k=0.1, plateau_patience=5, plateau_factor=0.5, min_lr=1e-6)

        # 恢复调度器状态（增量训练续训）
        if prev_epochs > 0:
            scheduler._step_count = prev_epochs
        try:
            _sd_ckpt = CheckpointManager(algo_id, bvid=bvid)
            _sd_ver = _sd_ckpt.list_versions()
            for _v in _sd_ver:
                if _v["active"]:
                    _saved_sd = _v.get("scheduler_state")
                    if _saved_sd:
                        scheduler.load_state_dict(_saved_sd)
                    break
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        best_val = float("inf")
        last_val = -1.0
        start_time = time.time()
        best_model_state = None
        best_epoch = 0
        train_losses = []
        for epoch in range(epochs):
            if self._check_control(
                control_dict, epoch, algo_id, bvid, optimizer, progress_cb, epochs, scheduler=scheduler
            ):
                break

            train_loss = self._train_epoch(model, train_loader, optimizer, loss_fn, preprocess, control_dict, algo_id)
            train_losses.append(train_loss)

            # 调度器步进（hyperbolic 模式）
            if control_dict and control_dict.get("lr_scale"):
                pass  # lr_scale 已由 _check_control 应用到 base_lrs
            else:
                scheduler.step_hyperbolic()

            if control_dict and control_dict.get("early_stop"):
                if control_dict.pop("_force_early_stop", False):
                    break
                # 动态早停：仅当 loss 改善趋于停滞时才允许提前停止
                if len(train_losses) >= 6:
                    recent_3 = sum(train_losses[-3:]) / 3
                    prev_3 = sum(train_losses[-6:-3]) / 3
                    if prev_3 > 1e-8 and (prev_3 - recent_3) / prev_3 < 0.015:
                        break
                control_dict["early_stop"] = False

            last_val = self._validate_and_emit(
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
                prev_epochs=prev_epochs,
            )
            if val_loader is not None and last_val < best_val:
                best_val = last_val
                best_epoch = epoch + 1
                best_model_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

            # 调度器 plateau 检测
            scheduler.update(last_val)

        # 无验证集时保存最终模型；有验证集时保存 val_loss 最低的那个
        if best_model_state is not None:
            model.load_state_dict(best_model_state)
            if best_epoch > 0:
                logger.info("[trainer] %s 保存最优模型 (epoch %d, val_loss=%.4f)", algo_id, best_epoch, best_val)
        data_trained_until_new = getattr(dataset, "max_timestamp", 0.0)
        return self._save_checkpoint(
            model,
            algo_id,
            bvid,
            dataset,
            best_val,
            last_val,
            val_loader,
            epochs,
            optimizer,
            prev_epochs=prev_epochs,
            data_trained_until=data_trained_until_new,
            scheduler=scheduler,
            best_epoch=best_epoch,
        )

    def _prepare_dataset(self, algo, algo_id, bvid, batch_size, val_ratio, min_timestamp=None):
        features = getattr(algo, "get_training_features", lambda: None)() or [
            "view_count",
            "like_count",
            "coin_count",
            "favorite_count",
            "share_count",
        ]
        window = getattr(algo, "training_window", 10)
        horizon = getattr(algo, "training_horizon", 3)

        dataset = VideoTimeSeriesDataset(
            window=window,
            horizon=horizon,
            bvids=[bvid] if bvid else None,
            features=features,
            min_timestamp=min_timestamp,
        )
        if len(dataset) == 0:
            raise RuntimeError(f"没有足够的训练样本（algo={algo_id}, bvid={bvid}）")

        # 将数据集实际特征维度传递给算法，供 build_model() 使用
        algo._training_n_features = dataset.n_features()

        # 自动根据数据量缩放 batch size（连续公式，无硬阈值）
        _n = len(dataset)
        _orig_bs = batch_size
        batch_size = min(batch_size, max(4, int(math.sqrt(_n) * 2)))
        if batch_size != _orig_bs:
            logger.info("[trainer] %s batch_size 自动调整: %d → %d (数据量 %d)", algo_id, _orig_bs, batch_size, _n)

        if val_ratio > 0 and _n >= 10:
            val_size = max(1, int(_n * val_ratio))
            train_size = _n - val_size
            train_set, val_set = random_split(
                dataset, [train_size, val_size], generator=torch.Generator().manual_seed(42)
            )
        else:
            train_set, val_set = dataset, None

        train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, drop_last=False)
        val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False) if val_set else None
        return dataset, train_loader, val_loader

    def _init_model_optimizer(self, algo, algo_id, init_from_global, lr, bvid=None):
        model = algo.build_model()
        if init_from_global:
            # 优先从视频级 checkpoint 加载（增量训练续训）
            loaded = False
            if bvid:
                video_ckpt = CheckpointManager(algo_id, bvid=bvid)
                if video_ckpt.has_checkpoint():
                    state = video_ckpt.load()
                    if state is not None:
                        try:
                            model.load_state_dict(state)
                            logger.info("[trainer] %s 从视频 %s checkpoint 续训", algo_id, bvid)
                            loaded = True
                        except Exception as e:
                            logger.warning("[trainer] %s 加载视频 state_dict 失败: %s", algo_id, e)
            if not loaded:
                global_ckpt = CheckpointManager(algo_id)
                if global_ckpt.has_checkpoint():
                    state = global_ckpt.load()
                    if state is not None:
                        try:
                            model.load_state_dict(state)
                            logger.info("[trainer] %s 从全局 checkpoint 初始化", algo_id)
                        except Exception as e:
                            logger.warning("[trainer] %s 加载全局 state_dict 失败: %s", algo_id, e)

        model = model.to(self.device)
        loss_fn = getattr(algo, "get_loss_fn", lambda: torch.nn.MSELoss())()
        if lr is not None:
            optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        else:
            optimizer = getattr(algo, "get_optimizer", lambda m: torch.optim.Adam(m.parameters(), lr=1e-3))(model)
        preprocess = getattr(algo, "preprocess_batch", _default_preprocess)
        return model, optimizer, loss_fn, preprocess

    @staticmethod
    def _check_control(control_dict, epoch, algo_id, bvid, optimizer, progress_cb, epochs, scheduler=None):
        if control_dict is None:
            return False
        lr_scale = control_dict.pop("lr_scale", None)
        if lr_scale is not None:
            if scheduler is not None and hasattr(scheduler, "base_lrs"):
                # 更新调度器的 base_lrs，让调度器在此基础上继续衰减
                scheduler.base_lrs = [blr * lr_scale for blr in scheduler.base_lrs]
            for pg in optimizer.param_groups:
                new_lr = pg["lr"] * lr_scale
                pg["lr"] = new_lr
            logger.info("[trainer] %s LR adjusted by ×%.2f → %.6f", algo_id, lr_scale, optimizer.param_groups[0]["lr"])

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

    def _train_epoch(self, model, train_loader, optimizer, loss_fn, preprocess, control_dict, algo_id):
        model.train()
        train_loss = 0.0
        n_batches = 0
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
            x, y = preprocess(batch)
            x = x.to(self.device)
            y = y.to(self.device)
            # Label Smoothing for Regression: 加 ~1% 噪声防止过拟合
            if label_noise > 0 and y.numel() > 0:
                y_std = y.std().item()
                if y_std > 1e-8:
                    noise = torch.randn_like(y) * y_std * label_noise
                    y = y + noise
            # MixUp 数据增强
            if mixup_alpha > 0 and x.size(0) > 1:
                lam = float(np.random.beta(mixup_alpha, mixup_alpha))
                perm = torch.randperm(x.size(0), device=self.device)
                x = lam * x + (1 - lam) * x[perm]
                y = lam * y + (1 - lam) * y[perm]

            # Repulsive Diversity: 特征随机丢弃 → 模型不依赖单一特征
            if feat_dropout > 0 and x.dim() >= 2:
                # x shape: [B, W, F] 或 [B, F]
                feat_dim = x.shape[-1]
                if feat_dim > 1:
                    mask = (
                        torch.bernoulli(torch.full((feat_dim,), 1.0 - feat_dropout, device=self.device)).view(
                            1, 1, feat_dim
                        )
                        if x.dim() == 3
                        else torch.bernoulli(torch.full((feat_dim,), 1.0 - feat_dropout, device=self.device)).view(
                            1, feat_dim
                        )
                    )
                    x = x * mask

            optimizer.zero_grad()
            pred = model(x)
            if pred.dim() == y.dim() + 1 and pred.shape[-1] == 1:
                pred = pred.squeeze(-1)
            # SPADE-S 偏斜修正：按幅值加权，避免高播放量支配 loss
            if amp_weight:
                diff = pred - y
                sq_err = diff**2
                denom = y.abs().mean(dim=-1, keepdim=True).clamp(min=1.0).detach()
                loss = (sq_err / denom).mean()
            else:
                loss = loss_fn(pred, y)
            # Activation Decay: 对预测输出加 L2 正则，平滑损失曲面
            if act_decay > 0:
                loss = loss + act_decay * (pred**2).mean()
            loss_val = float(loss.item())
            if control_dict is not None and (math.isnan(loss_val) or math.isinf(loss_val)):
                logger.warning("[trainer] %s NaN/Inf mid-epoch, early stopping", algo_id)
                control_dict["early_stop"] = True
                control_dict["_force_early_stop"] = True
                break
            loss.backward()
            if control_dict is not None and control_dict.get("grad_clip", 0) > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), control_dict["grad_clip"])
            optimizer.step()
            train_loss += loss_val
            n_batches += 1
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
        last_val = -1.0
        if val_loader is not None:
            last_val = ModelTrainer._evaluate(model, val_loader, loss_fn, preprocess)
        ModelTrainer._emit(
            progress_cb,
            {
                "stage": "epoch",
                "algo_id": algo_id,
                "bvid": bvid,
                "epoch": epoch + 1,
                "epochs": epochs,
                "total_epoch": prev_epochs + epoch + 1,
                "total_epochs": prev_epochs + epochs,
                "_prev_epochs": prev_epochs,
                "train_loss": train_loss,
                "val_loss": last_val,
                "elapsed_s": time.time() - start_time,
            },
        )
        return last_val

    def _save_checkpoint(
        self,
        model,
        algo_id,
        bvid,
        dataset,
        best_val,
        last_val,
        val_loader,
        epochs,
        optimizer=None,
        prev_epochs=0,
        data_trained_until=0.0,
        scheduler=None,
        best_epoch=0,
    ):
        ckpt = CheckpointManager(algo_id, bvid=bvid)
        lr = optimizer.param_groups[0]["lr"] if optimizer is not None else 0.001
        metadata = {
            "data_count": len(dataset),
            "val_loss": best_val if val_loader is not None else last_val,
            "epochs": epochs,
            "completed_epochs": prev_epochs + epochs,
            "best_epoch": best_epoch if val_loader is not None else epochs,
            "device": str(self.device),
            "learning_rate": lr,
            "data_trained_until": data_trained_until,
        }
        if scheduler is not None:
            metadata["scheduler_state"] = scheduler.state_dict()
        version = ckpt.save(
            model.state_dict(),
            metadata=metadata,
        )
        if bvid:
            self._save_model_to_video_dir(model, bvid, algo_id)
        return version

    def _save_model_to_video_dir(self, model: "torch.nn.Module", bvid: str, algo_id: str):
        """保存模型 state_dict 到 data/<bvid>/model/<algo_id>.pt"""
        import os

        video_model_dir = project_path("data", bvid, "model")
        os.makedirs(video_model_dir, exist_ok=True)
        path = os.path.join(video_model_dir, f"{algo_id}.pt")
        try:
            torch.save(model.state_dict(), path)
            logger.info("[trainer] 模型已保存到 %s", path)
        except Exception as e:
            logger.warning("[trainer] 保存模型到视频目录失败: %s", e)

    @staticmethod
    def _evaluate(model, loader, loss_fn, preprocess) -> float:
        model.eval()
        total = 0.0
        n = 0
        device = next(model.parameters()).device
        with torch.no_grad():
            for batch in loader:
                x, y = preprocess(batch)
                x = x.to(device)
                y = y.to(device)
                pred = model(x)
                if pred.dim() == y.dim() + 1 and pred.shape[-1] == 1:
                    pred = pred.squeeze(-1)
                total += float(loss_fn(pred, y).item())
                n += 1
        return total / max(1, n)

    @staticmethod
    def _emit(cb: ProgressCb, payload: Dict):
        if cb is None:
            return
        try:
            cb(payload)
        except Exception as e:
            logger.debug("progress_cb 抛异常（已忽略）: %s", e)

    @staticmethod
    def _instantiate_algorithm(algo_id: str):
        """从 registry 按 algorithm_id 查找底层算法实例（绕过 adapter 包装）"""
        try:
            from algorithms.registry import AlgorithmRegistry
        except Exception as e:
            logger.error("无法导入 AlgorithmRegistry: %s", e)
            return None
        AlgorithmRegistry.initialize()
        algo = AlgorithmRegistry.get_algorithm(algo_id)
        if algo is None:
            return None
        # 解包 ModelAlgorithmAdapter → 底层算法实例，以访问 build_model / get_loss_fn 等
        if hasattr(algo, "algo"):
            return algo.algo
        return algo


def _default_preprocess(batch):
    """默认 batch 解包：dataset 直接返回 (x, y)。"""
    return batch[0], batch[1]
