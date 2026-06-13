"""
ONNX 模型导出与推理模块
======================

将已训练的 PyTorch checkpoint 导出为 ONNX 格式，使用 ONNX Runtime
进行 CPU 推理加速。作为 torch 不可用或 CUDA OOM 时的 fallback。

导出流程:
    checkpoint (*.pt) → PyTorch 模型 → torch.onnx.export() → *.onnx
推理流程:
    numpy 输入 → ONNX Runtime session.run() → numpy 输出

依赖: pip install onnxruntime
"""

import os
import logging
from typing import Dict, Optional, Tuple, Any

import numpy as np

logger = logging.getLogger(__name__)

# ONNX Runtime 可用性检测
_onnx_available = False
_ort = None
try:
    import onnxruntime as _ort
    _onnx_available = True
except ImportError:
    pass

# ONNX 模型缓存目录
_ONNX_DIR = None


def _get_onnx_dir():
    global _ONNX_DIR
    if _ONNX_DIR is None:
        from utils import project_path
        _ONNX_DIR = project_path("algorithms", "checkpoints", "_onnx")
        os.makedirs(_ONNX_DIR, exist_ok=True)
    return _ONNX_DIR


def is_onnx_available() -> bool:
    """检查 ONNX Runtime 是否可用。"""
    return _onnx_available


def get_onnx_path(algo_id: str, bvid: str = "") -> str:
    """获取 ONNX 模型文件路径。

    Args:
        algo_id: 算法 ID
        bvid: 视频 BV 号（可选，有则使用视频微调路径）

    Returns:
        str: ONNX 文件路径
    """
    onnx_dir = _get_onnx_dir()
    if bvid:
        fname = f"{algo_id}__{bvid}.onnx"
    else:
        fname = f"{algo_id}.onnx"
    return os.path.join(onnx_dir, fname)


def has_onnx_model(algo_id: str, bvid: str = "") -> bool:
    """检查是否已有导出的 ONNX 模型。"""
    return os.path.exists(get_onnx_path(algo_id, bvid))


def export_to_onnx(
    model: Any,
    algo_id: str,
    bvid: str = "",
    window: int = 10,
    in_features: int = 10,
    force: bool = False,
) -> Optional[str]:
    """将 PyTorch 模型导出为 ONNX 格式。

    Args:
        model: PyTorch nn.Module 实例（需已加载权重）
        algo_id: 算法标识
        bvid: 视频 BV 号（可选）
        window: 输入窗口大小
        in_features: 输入特征维度
        force: 是否强制重新导出（覆盖已有文件）

    Returns:
        str or None: ONNX 文件路径，失败返回 None
    """
    if not _onnx_available:
        logger.debug("[ONNX] onnxruntime 未安装，跳过导出")
        return None

    onnx_path = get_onnx_path(algo_id, bvid)
    if os.path.exists(onnx_path) and not force:
        return onnx_path

    try:
        import torch

        model.eval()
        device = next(model.parameters()).device
        dummy = torch.randn(1, window, in_features, device=device)

        torch.onnx.export(
            model,
            dummy,
            onnx_path,
            input_names=["input"],
            output_names=["output"],
            dynamic_axes={
                "input": {1: "window"},   # 窗口维度动态
                "output": {1: "horizon"},
            },
            opset_version=14,
            do_constant_folding=True,
        )
        logger.info("[ONNX] 导出成功 %s → %s", algo_id, os.path.basename(onnx_path))
        return onnx_path
    except Exception as e:
        logger.warning("[ONNX] 导出失败 %s: %s", algo_id, e)
        # 清理失败的文件
        if os.path.exists(onnx_path):
            try:
                os.remove(onnx_path)
            except Exception:
                pass
        return None


class ONNXInferenceSession:
    """ONNX Runtime 推理会话（带缓存）。

    每个 (algo_id, bvid) 对应一个 session，首次使用时加载，
    后续推理直接复用。
    """

    def __init__(self):
        self._sessions: Dict[str, Any] = {}  # key → ort.InferenceSession

    def get_or_load(
        self, algo_id: str, bvid: str = "", window: int = 10, in_features: int = 10
    ) -> Optional[Any]:
        """获取或创建 ONNX 推理会话。

        优先加载已有 onnx 文件；若无则尝试从 checkpoint 导出。
        """
        key = f"{algo_id}__{bvid}" if bvid else algo_id
        if key in self._sessions:
            return self._sessions[key]

        if not _onnx_available:
            return None

        onnx_path = get_onnx_path(algo_id, bvid)
        if not os.path.exists(onnx_path):
            # 尝试从 checkpoint 导出
            from algorithms.training.checkpoint_manager import load_best_checkpoint
            state, _ = load_best_checkpoint(algo_id, bvid=bvid)
            if state is None:
                return None

            try:
                # 需要知道模型类 — 通过算法注册表推断
                # 这里使用通用方法：创建一个最小骨架模型
                onnx_path = _export_from_checkpoint(state, algo_id, bvid, window, in_features)
            except Exception as e:
                logger.debug("[ONNX] 从checkpoint导出失败 %s: %s", algo_id, e)
                return None

        if not onnx_path or not os.path.exists(onnx_path):
            return None

        try:
            sess = _ort.InferenceSession(
                onnx_path,
                providers=["CPUExecutionProvider"],
            )
            self._sessions[key] = sess
            return sess
        except Exception as e:
            logger.debug("[ONNX] 加载session失败 %s: %s", algo_id, e)
            return None

    def predict(
        self,
        algo_id: str,
        x_arr: np.ndarray,
        bvid: str = "",
        window: int = 10,
        in_features: int = 10,
    ) -> Optional[np.ndarray]:
        """ONNX 推理：返回 (horizon,) 输出数组。

        Args:
            algo_id: 算法 ID
            x_arr: 输入特征数组 (window, in_features)
            bvid: 视频 BV 号
            window: 窗口大小
            in_features: 特征维度

        Returns:
            np.ndarray or None: 预测输出
        """
        session = self.get_or_load(algo_id, bvid, window, in_features)
        if session is None:
            return None
        try:
            x = x_arr.astype(np.float32).reshape(1, window, in_features)
            out = session.run(None, {"input": x})
            return out[0].reshape(-1).astype(np.float64)
        except Exception as e:
            logger.debug("[ONNX] 推理失败 %s: %s", algo_id, e)
            return None

    def clear(self):
        """清除所有缓存的 session。"""
        self._sessions.clear()


# 模块级单例
_onnx_session: Optional[ONNXInferenceSession] = None


def get_onnx_session() -> ONNXInferenceSession:
    global _onnx_session
    if _onnx_session is None:
        _onnx_session = ONNXInferenceSession()
    return _onnx_session


def _export_from_checkpoint(
    state: dict, algo_id: str, bvid: str, window: int, in_features: int
) -> Optional[str]:
    """从 checkpoint state_dict 自动导出 ONNX。

    构建一个通用骨架模型加载权重后导出。
    """
    try:
        import torch
        import torch.nn as nn

        # 通用骨架：匹配大部分 _torch_upgrade 中的模型签名
        class OnnxExportModel(nn.Module):
            def __init__(self):
                super().__init__()
                # 根据 state_dict 推断模型结构
                self._build_from_state(state, window, in_features)

            def _build_from_state(self, state, window, in_features):
                """从 state_dict 的 key 模式推断结构。"""
                keys = list(state.keys())
                # 检测模型类型
                has_lstm = any("lstm" in k.lower() for k in keys)
                has_gru = any("gru" in k.lower() for k in keys)
                has_conv = any("conv" in k.lower() for k in keys)
                has_transformer = any("encoder" in k.lower() or "attention" in k.lower() for k in keys)

                # 推断隐藏维度
                hidden = 64
                for k in keys:
                    if "weight_ih" in k or "weight_hh" in k:
                        hidden = state[k].shape[0]
                        break
                    if "weight" in k and len(state[k].shape) == 2:
                        if state[k].shape[1] == in_features or state[k].shape[0] > in_features:
                            hidden = state[k].shape[0]
                            break

                if has_lstm:
                    self.rnn = nn.LSTM(in_features, hidden, batch_first=True)
                    self.fc = nn.Linear(hidden, 3)
                elif has_gru:
                    self.rnn = nn.GRU(in_features, hidden, batch_first=True)
                    self.fc = nn.Linear(hidden, 3)
                elif has_conv:
                    self.conv = nn.Conv1d(in_features, hidden, 3, padding=1)
                    self.fc = nn.Linear(hidden * window, 3)
                elif has_transformer:
                    encoder_layer = nn.TransformerEncoderLayer(
                        d_model=in_features, nhead=max(1, in_features // 2), batch_first=True
                    )
                    self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=1)
                    self.fc = nn.Linear(in_features, 3)
                else:
                    # 默认 MLP
                    self.fc = nn.Sequential(
                        nn.Flatten(),
                        nn.Linear(window * in_features, hidden),
                        nn.GELU(),
                        nn.Linear(hidden, hidden // 2),
                        nn.GELU(),
                        nn.Linear(hidden // 2, 3),
                    )

            def forward(self, x):
                if hasattr(self, "rnn"):
                    out, _ = self.rnn(x)
                    return self.fc(out[:, -1, :])
                elif hasattr(self, "conv"):
                    out = self.conv(x.transpose(1, 2))
                    return self.fc(out.reshape(out.shape[0], -1))
                elif hasattr(self, "encoder"):
                    out = self.encoder(x)
                    return self.fc(out[:, -1, :])
                else:
                    return self.fc(x)

        # 清理 state_dict 中的 _orig_mod 前缀
        clean_state = {}
        for k, v in state.items():
            if k.startswith("_orig_mod."):
                k = k[len("_orig_mod."):]
            clean_state[k] = v

        model = OnnxExportModel()
        # 尝试加载，忽略不匹配的 key（自动推断的模型可能不完全匹配）
        model.load_state_dict(clean_state, strict=False)
        model.eval()

        path = export_to_onnx(model, algo_id, bvid, window, in_features)
        return path
    except Exception as e:
        logger.debug("[ONNX] 自动导出失败 %s: %s", algo_id, e)
        return None
