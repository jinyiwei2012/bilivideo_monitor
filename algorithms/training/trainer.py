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
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
    from torch.utils.data import DataLoader, random_split
except ImportError:
    _torch_available = False

from algorithms.training.checkpoint_manager import CheckpointManager
from algorithms.training.device import get_device
from algorithms.training.dataset import VideoTimeSeriesDataset, estimate_dataset_size


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
    ) -> Dict[str, str]:
        """对一组算法做全局预训练，返回 {algo_id: version_name}。失败的算法 value = ''。

        Args:
            init_from_global: True=增量训练（加载已有 checkpoint 继续训练），
                              False=重新训练（从随机初始化开始）。
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
    ) -> str:
        """基于全局 active checkpoint 微调，存到 <algo_id>/_video/<bvid>/v*.pt。"""
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法训练")
        return self._train_one(
            algo_id=algo_id,
            bvid=bvid,
            epochs=epochs,
            batch_size=batch_size,
            val_ratio=0.0,
            progress_cb=progress_cb,
            init_from_global=True,
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
    ) -> str:
        algo = self._instantiate_algorithm(algo_id)
        if algo is None:
            raise RuntimeError(f"算法 {algo_id} 未注册或不支持训练")
        if not hasattr(algo, "build_model"):
            raise RuntimeError(f"算法 {algo_id} 未实现 build_model()")

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
        )
        if len(dataset) == 0:
            raise RuntimeError(f"没有足够的训练样本（algo={algo_id}, bvid={bvid}）")

        # 划分训练 / 验证
        if val_ratio > 0 and len(dataset) >= 10:
            val_size = max(1, int(len(dataset) * val_ratio))
            train_size = len(dataset) - val_size
            train_set, val_set = random_split(
                dataset,
                [train_size, val_size],
                generator=torch.Generator().manual_seed(42),
            )
        else:
            train_set, val_set = dataset, None

        train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, drop_last=False)
        val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False) if val_set else None

        model = algo.build_model()
        if init_from_global:
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
        optimizer = getattr(algo, "get_optimizer", lambda m: torch.optim.Adam(m.parameters(), lr=1e-3))(model)
        preprocess = getattr(algo, "preprocess_batch", _default_preprocess)

        best_val = float("inf")
        last_val = -1.0
        start_time = time.time()
        for epoch in range(epochs):
            model.train()
            train_loss = 0.0
            n_batches = 0
            for batch in train_loader:
                x, y = preprocess(batch)
                x = x.to(self.device)
                y = y.to(self.device)
                optimizer.zero_grad()
                pred = model(x)
                # 自动 squeeze 末尾维度匹配
                if pred.dim() == y.dim() + 1 and pred.shape[-1] == 1:
                    pred = pred.squeeze(-1)
                loss = loss_fn(pred, y)
                loss.backward()
                optimizer.step()
                train_loss += float(loss.item())
                n_batches += 1
            train_loss /= max(1, n_batches)

            if val_loader is not None:
                val_loss = self._evaluate(model, val_loader, loss_fn, preprocess)
                last_val = val_loss
                if val_loss < best_val:
                    best_val = val_loss
            self._emit(
                progress_cb,
                {
                    "stage": "epoch",
                    "algo_id": algo_id,
                    "bvid": bvid,
                    "epoch": epoch + 1,
                    "epochs": epochs,
                    "train_loss": train_loss,
                    "val_loss": last_val,
                    "elapsed_s": time.time() - start_time,
                },
            )

        # 保存 checkpoint
        ckpt = CheckpointManager(algo_id, bvid=bvid)
        version = ckpt.save(
            model.state_dict(),
            metadata={
                "data_count": len(dataset),
                "val_loss": best_val if val_loader is not None else last_val,
                "epochs": epochs,
                "device": str(self.device),
            },
        )
        return version

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
        """从 registry 按 algorithm_id 查找底层算法实例（绕过 adapter 包装）。

        registry 用 f"[Model] {display_name}" 当 key 存 adapter，所以不能直接
        get_algorithm(algo_id) — 必须扫描全部 adapter 比对 algorithm_id 属性，
        再取出 adapter.algo 把训练需要的 build_model / get_loss_fn 等方法暴露出来。
        """
        try:
            from algorithms.registry import AlgorithmRegistry
        except Exception as e:
            logger.error("无法导入 AlgorithmRegistry: %s", e)
            return None
        AlgorithmRegistry.initialize()
        for adapter in AlgorithmRegistry.get_all_algorithms():
            algo = getattr(adapter, "algo", adapter)
            if getattr(algo, "algorithm_id", None) == algo_id:
                return algo
        return None


def _default_preprocess(batch):
    """默认 batch 解包：dataset 直接返回 (x, y)。"""
    return batch[0], batch[1]
