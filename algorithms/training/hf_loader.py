"""HuggingFace Foundation 模型懒加载模块
=======================================

本模块提供 HuggingFace 预训练时序大模型的懒加载支持，
包括 MOIRAI-2 和 Lag-Llama 两个时序 Foundation 模型。

设计原则：
---------
1. **懒加载**: 只在算法首次调用时从 HuggingFace Hub 下载，避免启动时阻塞。
2. **单例缓存**: 进程内只加载一次，后续调用直接返回缓存对象，避免重复占内存。
3. **优雅降级**: 缺少依赖（transformers/huggingface_hub/uni2ts）时返回失败原因，
   不阻塞应用启动，算法侧自动降级到 numpy 路径。
4. **线程安全**: 使用 threading.Lock 保护单例缓存的读写。
5. **失败缓存**: 加载失败的结果也会缓存，避免每次调用都重复尝试 import。

缓存策略：
---------
- 模型文件缓存到 ~/.cache/huggingface/hub/（标准 HuggingFace 缓存目录）。
- 进程内对象缓存在本模块的 _models 字典中。
- 调用 clear_cache() 只释放进程内对象，不删除磁盘缓存。

公开 API：
---------
    # 加载模型
    model, ok, reason = get_moirai_model()       # MOIRAI-2 small 模型
    model, ok, reason = get_lag_llama_model()     # Lag-Llama 模型

    # 辅助功能
    is_hf_available()   # 检查 transformers + huggingface_hub 是否已安装
    clear_cache()       # 释放进程内单例缓存（不删磁盘缓存）
    hf_cache_dir()      # 返回 HuggingFace 缓存目录路径（UI 显示用）

返回值约定：
-----------
ok=True 时 model 为 PyTorch 模型对象（或 checkpoint dict）。
ok=False 时 model=None，reason 为失败原因字符串，用于日志/UI 显示。

特殊说明：
---------
MOIRAI 使用 uni2ts 库的自定义配置格式（不是标准 transformers.AutoModel），
因此必须通过 `uni2ts.model.moirai.MoiraiModule.from_pretrained` 加载。
未安装 uni2ts 时降级到 numpy 路径，warning 在算法侧消音。
"""

import logging
import threading
from typing import Any, Optional, Tuple

# 模块级日志记录器
logger = logging.getLogger(__name__)

# ── PyTorch 可用性检测 ─────────────────────────────────
_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False

# ── HuggingFace 库可用性检测 ──────────────────────────
_hf_available = True
try:
    import transformers  # noqa: F401
    import huggingface_hub  # noqa: F401
except ImportError:
    _hf_available = False

# ── HuggingFace 模型仓库 ID 常量 ─────────────────────
MOIRAI_REPO = "Salesforce/moirai-1.1-R-small"                       # MOIRAI-2 小型版本
LAG_LLAMA_REPO = "time-series-foundation-models/Lag-Llama"          # Lag-Llama 时序基础模型

# ── 进程内单例缓存 ──────────────────────────────────
_models: dict = {}      # {"moirai": model, "lag_llama": model} 或 None（失败标记）
_lock = threading.Lock()  # 线程安全锁


def is_hf_available() -> bool:
    """检查 HuggingFace 相关依赖是否可用。

    需要同时满足：
    1. PyTorch 已安装
    2. transformers 已安装
    3. huggingface_hub 已安装

    Returns:
        bool: True 表示可以使用 HuggingFace 模型。
    """
    return _torch_available and _hf_available


def clear_cache():
    """释放进程内缓存的模型对象。

    释放后下次调用 get_moirai_model()/get_lag_llama_model() 将重新加载。
    注意：此操作不删除磁盘上的 HuggingFace 缓存文件。
    """
    with _lock:
        _models.clear()


def get_moirai_model() -> Tuple[Optional[Any], bool, str]:
    """加载 Salesforce MOIRAI-2 small 时序预测模型。

    MOIRAI 是 Salesforce 发布的通用时序预测模型，使用 uni2ts 框架。
    config.json 使用 uni2ts 自定义类型定义，标准 transformers.AutoModel
    无法识别 → 必须走 uni2ts.model.moirai.MoiraiModule.from_pretrained。

    Returns:
        Tuple[Optional[Any], bool, str]:
            - model:  PyTorch 模型对象，失败时为 None
            - ok:     True 表示模型加载成功或命中缓存
            - reason: 状态描述字符串：
                - "cached":         命中进程内缓存
                - "loaded":         首次加载成功
                - "cached_failure": 之前已失败，跳过重试
                - "需要 transformers + huggingface_hub": 缺少基础依赖
                - "需要 pip install uni2ts": 缺少 uni2ts 包
                - 其他: 异常消息字符串
    """
    if not is_hf_available():
        return None, False, "需要 transformers + huggingface_hub"
    # ── 先查进程内缓存（线程安全） ──────────────────
    with _lock:
        if "moirai" in _models:
            cached = _models["moirai"]
            if cached is None:
                # 之前加载失败过，直接返回缓存失败状态
                return None, False, "cached_failure"
            # 命中有效缓存
            return cached, True, "cached"
    try:
        # ── 检查 uni2ts 库 ────────────────────────────
        from uni2ts.model.moirai import MoiraiModule
        logger.debug("[hf_loader] uni2ts 已安装，MOIRAI 将使用 torch 推理")
    except ImportError as e:
        # uni2ts 未安装 → 缓存失败结果，避免下次再尝试 import
        logger.debug("[hf_loader] uni2ts 未安装，MOIRAI 走 numpy 降级: %s", e)
        with _lock:
            _models["moirai"] = None  # 缓存失败结果
        return None, False, "需要 pip install uni2ts"
    try:
        # ── 下载并加载模型 ────────────────────────────
        logger.debug("[hf_loader] 首次加载 MOIRAI，从 HuggingFace 下载或读缓存: %s", MOIRAI_REPO)
        # from_pretrained 会自动检查本地缓存，未命中时从 HuggingFace Hub 下载
        model = MoiraiModule.from_pretrained(MOIRAI_REPO)
        model.eval()  # 设为评估模式（不启用 dropout/batchnorm）
        with _lock:
            _models["moirai"] = model
        logger.info("[hf_loader] MOIRAI 模型已加载 → 使用 torch 推理")
        return model, True, "loaded"
    except Exception as e:
        # 加载失败（网络问题、磁盘空间等）→ 缓存失败结果
        logger.debug("[hf_loader] MOIRAI 加载失败，走 numpy 降级: %s", e)
        with _lock:
            _models["moirai"] = None
        return None, False, str(e)


def get_lag_llama_model() -> Tuple[Optional[Any], bool, str]:
    """加载 Lag-Llama 时序预测模型。

    Lag-Llama 是基于 Llama 架构的时序预测基础模型，可做零样本/少样本预测。
    模型以 .ckpt 文件形式存储，通过 hf_hub_download 下载后直接 torch.load。

    Returns:
        Tuple[Optional[Any], bool, str]:
            - model:  模型 checkpoint dict（或 PyTorch 模型），失败时为 None
            - ok:     True 表示模型加载成功或命中缓存
            - reason: 状态描述字符串：
                - "cached":         命中进程内缓存
                - "loaded":         首次加载成功
                - "cached_failure": 之前已失败，跳过重试
                - 其他: 异常消息字符串
    """
    if not is_hf_available():
        return None, False, "需要 transformers + huggingface_hub"
    # ── 先查进程内缓存（线程安全） ──────────────────
    with _lock:
        if "lag_llama" in _models:
            cached = _models["lag_llama"]
            if cached is None:
                return None, False, "cached_failure"
            return cached, True, "cached"
    try:
        from huggingface_hub import hf_hub_download

        logger.debug("[hf_loader] 首次加载 Lag-Llama，从 HuggingFace 下载或读缓存: %s", LAG_LLAMA_REPO)
        # 下载 .ckpt 文件到本地缓存目录
        ckpt_path = hf_hub_download(
            repo_id=LAG_LLAMA_REPO,
            filename="lag-llama.ckpt",
        )
        import torch as _torch

        # 以 CPU 加载以确保兼容性；weights_only=True 防止安全问题
        ckpt = _torch.load(ckpt_path, map_location="cpu", weights_only=True)
        with _lock:
            _models["lag_llama"] = ckpt
        logger.info("[hf_loader] Lag-Llama 模型已加载 → 使用 torch 推理")
        return ckpt, True, "loaded"
    except Exception as e:
        # 加载失败 → 缓存失败结果
        logger.debug("[hf_loader] Lag-Llama 加载失败，走 numpy 降级: %s", e)
        with _lock:
            _models["lag_llama"] = None
        return None, False, str(e)


def hf_cache_dir() -> str:
    """返回 HuggingFace 缓存目录路径，用于 UI 显示。

    优先从 huggingface_hub.constants 获取官方缓存路径，
    失败时回退到默认路径 ~/.cache/huggingface/hub。

    Returns:
        str: HuggingFace 本地缓存目录的绝对路径。
    """
    try:
        from huggingface_hub import constants

        return constants.HF_HUB_CACHE
    except Exception:
        import os

        return os.path.expanduser("~/.cache/huggingface/hub")
