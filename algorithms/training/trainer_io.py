"""
训练管线 — Checkpoint IO 与评估工具

从 trainer.py 提取的 checkpoint 保存和模型评估方法。
"""
import logging
import os

from algorithms.training.checkpoint_manager import CheckpointManager
from utils import project_path

logger = logging.getLogger(__name__)

# 延迟导入 torch（在 trainer.py 已检测可用性）
_torch_available = True
try:
    import torch
except ImportError:
    _torch_available = False


def save_checkpoint(model, algo_id, bvid, dataset, best_val, last_val, val_loader,
                    epochs, device, optimizer=None, prev_epochs=0, data_trained_until=0.0,
                    scheduler=None, best_epoch=0):
    """保存模型 checkpoint 并同步到视频目录。

    Args:
        model:              PyTorch 模型。
        algo_id:            算法标识符。
        bvid:               视频 BV 号。
        dataset:            训练数据集。
        best_val:           最佳验证损失。
        last_val:           最近验证损失。
        val_loader:         验证 DataLoader。
        epochs:             本次训练轮数。
        device:             训练设备。
        optimizer:          PyTorch 优化器。
        prev_epochs:        之前已完成的 epoch 数。
        data_trained_until: 本次训练覆盖数据的最大时间戳。
        scheduler:          ComboScheduler 实例。
        best_epoch:         最佳 epoch 编号。

    Returns:
        str: 新创建的 checkpoint 版本名。
    """
    ckpt = CheckpointManager(algo_id, bvid=bvid)
    lr = optimizer.param_groups[0]["lr"] if optimizer is not None else 0.001
    metadata = {
        "data_count": len(dataset),
        "val_loss": best_val if val_loader is not None else last_val,
        "epochs": epochs,
        "completed_epochs": prev_epochs + epochs,
        "best_epoch": best_epoch if val_loader is not None else epochs,
        "device": str(device),
        "learning_rate": lr,
        "data_trained_until": data_trained_until,
    }
    if scheduler is not None:
        metadata["scheduler_state"] = scheduler.state_dict()
    model_to_save = model._orig_mod if hasattr(model, '_orig_mod') else model
    version = ckpt.save(model_to_save.state_dict(), metadata=metadata)
    # 视频微调时也保存到 data/<bvid>/model/ 目录
    if bvid:
        _save_model_to_video_dir(model, bvid, algo_id)
    # 训练完成后自动导出 ONNX 模型
    try:
        from algorithms.training.onnx_exporter import export_to_onnx, is_onnx_available
        if is_onnx_available():
            export_to_onnx(model_to_save, algo_id, bvid or "", force=True)
    except Exception:
        logger.debug("[ONNX] 导出失败（非致命，跳过）%s", algo_id)
    return version


def _save_model_to_video_dir(model, bvid, algo_id):
    """将模型 state_dict 保存到 data/<bvid>/model/<algo_id>.pt"""
    video_model_dir = project_path("data", bvid, "model")
    os.makedirs(video_model_dir, exist_ok=True)
    path = os.path.join(video_model_dir, f"{algo_id}.pt")
    try:
        model_to_save = model._orig_mod if hasattr(model, '_orig_mod') else model
        torch.save(model_to_save.state_dict(), path)
        logger.info("[trainer] 模型已保存到 %s", path)
    except Exception as e:
        logger.warning("[trainer] 保存模型到视频目录失败: %s", e)


def evaluate_model(model, loader, loss_fn, preprocess) -> float:
    """在验证集上评估模型损失（torch.no_grad）"""
    model.eval()
    total = 0.0
    n = 0
    device = next(model.parameters()).device
    with torch.no_grad():
        for batch in loader:
            x, y = preprocess(batch)
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)
            pred = model(x)
            if pred.dim() == y.dim() + 1 and pred.shape[-1] == 1:
                pred = pred.squeeze(-1)
            total += float(loss_fn(pred, y).item())
            n += 1
    return total / max(1, n)
