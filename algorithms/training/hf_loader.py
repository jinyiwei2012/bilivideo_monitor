"""Foundation 模型懒加载（MOIRAI-2 / Lag-Llama）

只在被算法首次调用时从 HuggingFace 下载并缓存到 ~/.cache/huggingface/。
后续调用走进程内单例缓存，避免重复加载占内存。

公开 API：
    get_moirai_model()   → 返回 (model, ok: bool, reason: str)
    get_lag_llama_model() → 返回 (model, ok: bool, reason: str)
    is_hf_available()     → transformers + huggingface_hub 是否已安装
    clear_cache()         → 释放进程内单例（不删磁盘缓存）

返回值约定：ok=False 时 model=None，reason 用于日志/UI 显示。
"""

import logging
import threading
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False

_hf_available = True
try:
    import transformers  # noqa: F401
    import huggingface_hub  # noqa: F401
except ImportError:
    _hf_available = False

# Repo ID 常量
MOIRAI_REPO = "Salesforce/moirai-1.1-R-small"
LAG_LLAMA_REPO = "time-series-foundation-models/Lag-Llama"

# 进程内单例缓存
_models: dict = {}
_lock = threading.Lock()


def is_hf_available() -> bool:
    return _torch_available and _hf_available


def clear_cache():
    """释放进程内模型对象（磁盘缓存不删）。"""
    with _lock:
        _models.clear()


def get_moirai_model() -> Tuple[Optional[Any], bool, str]:
    """加载 MOIRAI-2 small 模型。返回 (model, ok, reason)。

    MOIRAI 的 config.json 用 uni2ts 自定义类型，标准 transformers.AutoModel
    无法识别 → 必须走 uni2ts.model.moirai.MoiraiModule.from_pretrained。
    没装 uni2ts 时降级到 numpy 路径（warning 在算法侧消音）。
    """
    if not is_hf_available():
        return None, False, "需要 transformers + huggingface_hub"
    with _lock:
        if "moirai" in _models:
            cached = _models["moirai"]
            if cached is None:
                return None, False, "cached_failure"
            return cached, True, "cached"
    try:
        from uni2ts.model.moirai import MoiraiModule
        logger.debug("[hf_loader] uni2ts 已安装，MOIRAI 将使用 torch 推理")
    except ImportError as e:
        logger.debug("[hf_loader] uni2ts 未安装，MOIRAI 走 numpy 降级: %s", e)
        with _lock:
            _models["moirai"] = None  # 缓存失败结果，避免下次再 import
        return None, False, "需要 pip install uni2ts"
    try:
        logger.debug("[hf_loader] 首次加载 MOIRAI，从 HuggingFace 下载或读缓存: %s", MOIRAI_REPO)
        model = MoiraiModule.from_pretrained(MOIRAI_REPO)
        model.eval()
        with _lock:
            _models["moirai"] = model
        logger.info("[hf_loader] MOIRAI 模型已加载 → 使用 torch 推理")
        return model, True, "loaded"
    except Exception as e:
        logger.debug("[hf_loader] MOIRAI 加载失败，走 numpy 降级: %s", e)
        with _lock:
            _models["moirai"] = None
        return None, False, str(e)


def get_lag_llama_model() -> Tuple[Optional[Any], bool, str]:
    """加载 Lag-Llama 模型。返回 (model, ok, reason)。"""
    if not is_hf_available():
        return None, False, "需要 transformers + huggingface_hub"
    with _lock:
        if "lag_llama" in _models:
            cached = _models["lag_llama"]
            if cached is None:
                return None, False, "cached_failure"
            return cached, True, "cached"
    try:
        from huggingface_hub import hf_hub_download

        logger.debug("[hf_loader] 首次加载 Lag-Llama，从 HuggingFace 下载或读缓存: %s", LAG_LLAMA_REPO)
        ckpt_path = hf_hub_download(
            repo_id=LAG_LLAMA_REPO,
            filename="lag-llama.ckpt",
        )
        import torch as _torch

        try:
            ckpt = _torch.load(ckpt_path, map_location="cpu", weights_only=True)
        except Exception:
            logger.debug("[hf_loader] weights_only=True 加载失败，回退 trust_load（HF 官方 checkpoint）")
            ckpt = _torch.load(ckpt_path, map_location="cpu", weights_only=False)
        with _lock:
            _models["lag_llama"] = ckpt
        logger.info("[hf_loader] Lag-Llama 模型已加载 → 使用 torch 推理")
        return ckpt, True, "loaded"
    except Exception as e:
        logger.debug("[hf_loader] Lag-Llama 加载失败，走 numpy 降级: %s", e)
        with _lock:
            _models["lag_llama"] = None
        return None, False, str(e)


def hf_cache_dir() -> str:
    """返回 HuggingFace 缓存目录（用于 UI 显示）。"""
    try:
        from huggingface_hub import constants

        return constants.HF_HUB_CACHE
    except Exception:
        import os

        return os.path.expanduser("~/.cache/huggingface/hub")
