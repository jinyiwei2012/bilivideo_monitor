"""Extracted torch-upgrade helpers."""

from typing import Any, Callable, Dict, List, Optional

from .backends import _rank_backends, _try_npu_predict, _try_onnx_predict
from .context import (
    DEFAULT_FEATURES,
    DEFAULT_HORIZON,
    DEFAULT_WINDOW,
    _model_load_semaphore,
    _torch_available,
    logger,
    torch,
)
from .model_io import _build_torch_input, _generic_result, load_checkpoint_model
from .runtime import (
    _ensure_vram,
    _estimate_model_vram,
    _evict_lru_gpu_model,
    _initialize_torch_runtime,
    _load_prediction_checkpoint,
    _register_gpu_model,
    _touch_gpu_lru,
    _unregister_gpu_model,
)


def _try_ranked_backend_predict(
    ranked,
    algo_id,
    bvid,
    x_arr,
    window,
    in_features,
    v_mean,
    v_std,
    algorithm,
    video_data,
    threshold,
    model_source,
    model_cls,
    model_kwargs,
    feats,
    horizon,
    state,
):
    """按基准排序尝试 ONNX/NPU，遇到 torch 时交还主路径。"""
    for backend in ranked:
        if backend == "onnx":
            result = _try_onnx_predict(
                algo_id,
                bvid,
                x_arr,
                window,
                in_features,
                v_mean,
                v_std,
                algorithm,
                video_data,
                threshold,
                model_source,
            )
            if result is not None:
                return result
        elif backend == "npu":
            result = _try_npu_predict(
                algo_id,
                bvid,
                x_arr,
                window,
                in_features,
                v_mean,
                v_std,
                algorithm,
                video_data,
                threshold,
                model_source,
                model_cls=model_cls,
                model_kwargs=model_kwargs,
                feats=feats,
                horizon=horizon,
                state=state,
            )
            if result is not None:
                return result
        elif backend == "torch":
            # torch 在 Phase 2 处理（复用缓存模型）
            break
    return None


def _try_preferred_backend_predict(
    prefer,
    skip_onnx,
    algo_id,
    bvid,
    x_arr,
    window,
    in_features,
    v_mean,
    v_std,
    algorithm,
    video_data,
    threshold,
    model_source,
    model_cls,
    model_kwargs,
    feats,
    horizon,
    state,
):
    """执行 PyTorch 前的首选后端推理阶段。"""
    if prefer == "auto":
        ranked = _rank_backends(
            algo_id,
            x_arr,
            window,
            in_features,
            v_mean,
            v_std,
            algorithm,
            video_data,
            threshold,
            model_source,
            model_cls=model_cls,
            model_kwargs=model_kwargs,
            features=feats,
            horizon=horizon,
        )
        return _try_ranked_backend_predict(
            ranked,
            algo_id,
            bvid,
            x_arr,
            window,
            in_features,
            v_mean,
            v_std,
            algorithm,
            video_data,
            threshold,
            model_source,
            model_cls,
            model_kwargs,
            feats,
            horizon,
            state,
        )
    if skip_onnx:
        return None
    return _try_onnx_predict(
        algo_id,
        bvid,
        x_arr,
        window,
        in_features,
        v_mean,
        v_std,
        algorithm,
        video_data,
        threshold,
        model_source,
    )


def _move_model_to_device(model, algorithm, algo_id):
    """将模型放入设备，CUDA OOM 时淘汰 LRU 后重试。"""
    if algorithm._device.type == "cuda":
        _ensure_vram(_estimate_model_vram(model), algorithm._device)
        try:
            model.to(algorithm._device)
        except RuntimeError as oom:
            if "out of memory" in str(oom).lower():
                logger.debug("[%s] GPU OOM，淘汰模型后重试", algo_id)
                _evict_lru_gpu_model()
                torch.cuda.empty_cache()
                model.to(algorithm._device)
            else:
                raise
    else:
        model.to(algorithm._device)


def _get_torch_model(algorithm, algo_id, bvid, gpu_key, model_cls, model_kwargs, state, window, in_features, horizon):
    """获取缓存模型或加载、布置并缓存新模型。"""
    model = getattr(algorithm, "_cached_torch_model", None)
    if model is not None and (not bvid or getattr(algorithm, "_cached_bvid", "") == bvid):
        # 命中缓存，刷新 LRU 时间戳
        _touch_gpu_lru(gpu_key)
        return model

    # 淘汰旧模型显存
    old_bvid = getattr(algorithm, "_cached_bvid", "")
    if old_bvid and hasattr(algorithm, "_cached_torch_model"):
        old_key = f"{algo_id}@{old_bvid}"
        _unregister_gpu_model(old_key)

    mk = dict(model_kwargs or {})
    # 信号量保护：防止多线程同时加载大模型导致内存峰值
    with _model_load_semaphore:
        model = load_checkpoint_model(model_cls, mk, state, window, in_features, horizon)

    _move_model_to_device(model, algorithm, algo_id)
    model.eval()
    algorithm._cached_torch_model = model
    algorithm._cached_bvid = bvid or ""

    # 注册到 GPU LRU
    if algorithm._device.type == "cuda":
        _register_gpu_model(gpu_key, model, algorithm._device)
    return model


def _prediction_result_from_output(algorithm, video_data, threshold, model, y, v_mean, v_std, horizon, model_source):
    """将模型输出还原为统一预测结果。"""
    predicted_velocity = max(0.0, float(y[0]) * v_std + v_mean)
    # A+B 双尺度：模型扩展为 H+1 时，y[horizon] = 长期平均速率（与短期共用缩放器）
    long_velocity = None
    if bool(getattr(model, "_dual_output", False)) and len(y) > horizon:
        long_velocity = max(0.0, float(y[horizon]) * v_std + v_mean)
    return _generic_result(
        algorithm,
        video_data,
        threshold,
        predicted_velocity,
        y,
        model_source=model_source,
        long_velocity=long_velocity,
    )


def _run_torch_prediction(
    algorithm,
    video_data,
    threshold,
    algo_id,
    bvid,
    gpu_key,
    model_cls,
    model_kwargs,
    state,
    window,
    in_features,
    horizon,
    x_arr,
    v_mean,
    v_std,
    model_source,
):
    """加载或复用模型并执行 PyTorch 推理。"""
    model = _get_torch_model(
        algorithm, algo_id, bvid, gpu_key, model_cls, model_kwargs, state, window, in_features, horizon
    )
    device = next(model.parameters()).device
    x = torch.from_numpy(x_arr).unsqueeze(0).to(device)
    with torch.no_grad():
        y = model(x).cpu().numpy().reshape(-1)
    return _prediction_result_from_output(
        algorithm, video_data, threshold, model, y, v_mean, v_std, horizon, model_source
    )


def _retry_after_cuda_oom(
    error, algorithm, video_data, threshold, model_cls, fallback_fn, model_kwargs, features, window, horizon
):
    """CUDA OOM 时淘汰缓存并递归重试一次。"""
    if "out of memory" not in str(error).lower() or algorithm._device.type != "cuda":
        return False, None
    try:
        _evict_lru_gpu_model()
        torch.cuda.empty_cache()
        algorithm._cached_torch_model = None
        return True, try_torch_predict(
            algorithm,
            video_data,
            threshold,
            model_cls,
            fallback_fn,
            model_kwargs,
            features,
            window,
            horizon,
        )
    except Exception:
        return False, None


def _try_npu_fallback(
    algorithm,
    video_data,
    threshold,
    algo_id,
    bvid,
    model_cls,
    model_kwargs,
    state,
    window,
    in_features,
    horizon,
    x_arr,
    v_mean,
    v_std,
    model_source,
):
    """PyTorch 失败后尝试 NPU 推理。"""
    if x_arr is None:
        return None
    try:
        from algorithms.training.npu_inference import get_npu_engine

        engine = get_npu_engine()
        if not engine.is_available:
            return None
        model = getattr(algorithm, "_cached_torch_model", None)
        if model is None or (bvid and not getattr(algorithm, "_cached_bvid", "") == bvid):
            with _model_load_semaphore:
                model = load_checkpoint_model(model_cls, model_kwargs, state, window, in_features, horizon)
        y = algorithm._npu_infer(model, x_arr, algo_name=algo_id)
        y_np = y.cpu().numpy().reshape(-1)
        return _prediction_result_from_output(
            algorithm, video_data, threshold, model, y_np, v_mean, v_std, horizon, model_source
        )
    except Exception:
        return None


def _fallback_after_torch_error(
    error,
    algorithm,
    video_data,
    threshold,
    model_cls,
    fallback_fn,
    model_kwargs,
    features,
    window,
    horizon,
    algo_id,
    bvid,
    feats,
    state,
    x_arr,
    v_mean,
    v_std,
    model_source,
):
    """按 OOM 重试、NPU、ONNX、numpy 顺序处理 torch 失败。"""
    retried, result = _retry_after_cuda_oom(
        error, algorithm, video_data, threshold, model_cls, fallback_fn, model_kwargs, features, window, horizon
    )
    if retried:
        return result

    in_features = len(feats) + 5
    result = _try_npu_fallback(
        algorithm,
        video_data,
        threshold,
        algo_id,
        bvid,
        model_cls,
        model_kwargs,
        state,
        window,
        in_features,
        horizon,
        x_arr,
        v_mean,
        v_std,
        model_source,
    )
    if result is not None:
        return result

    # 降级到 ONNX Runtime（CPU 推理加速）
    algo_id = getattr(algorithm, "algorithm_id", "unknown")
    bvid = video_data.get("bvid", "")
    window_val = window
    in_features_val = len(feats) + 5 if feats else 15
    onnx_result = _try_onnx_predict(
        algo_id,
        bvid,
        x_arr if x_arr is not None else _build_torch_input(video_data, feats, window)[0],
        window_val,
        in_features_val,
        v_mean,
        v_std,
        algorithm,
        video_data,
        threshold,
        model_source,
    )
    if onnx_result is not None:
        return onnx_result

    logger.warning("[%s] torch/ONNX 推理均失败，降级 numpy: %s", algo_id, error)
    return fallback_fn(video_data, threshold)


def try_torch_predict(
    algorithm,
    video_data: Dict[str, Any],
    threshold: int,
    model_cls: type,
    fallback_fn: Callable,
    model_kwargs: Optional[Dict[str, Any]] = None,
    features: Optional[List[str]] = None,
    window: int = DEFAULT_WINDOW,
    horizon: int = DEFAULT_HORIZON,
):
    """统一的预测入口：ONNX(NPU) → torch → ONNX(CPU) → numpy 降级。

    推理优先级：
        1. ONNX Runtime + DirectML（NPU/GPU 加速）
        2. PyTorch（CUDA / DirectML）
        3. ONNX Runtime CPU
        4. numpy 降级

    降级条件：
    - ONNX Runtime 不可用 / 模型未导出
    - PyTorch 不可用 / CUDA OOM
    - 无可用的 checkpoint
    - 历史数据不足（< 3 条）
    - 推理过程抛出异常

    Args:
        algorithm: 算法实例（需有 `_ckpt`, `_device`, `_cached_torch_model` 属性，name/algorithm_id）
        video_data: 视频数据字典，需含 view_count, history_data, bvid 等字段
        threshold: 目标播放量阈值
        model_cls: 该算法对应的 torch 模型类（如 LSTMTorchModel）
        fallback_fn: 失败时调用的 numpy predict 函数，签名为 (video_data, threshold) -> PredictionResult
        model_kwargs: 实例化 model_cls 时的额外参数字典
        features: 输入特征列表（默认使用 DEFAULT_FEATURES）
        window: 输入窗口长度
        horizon: 预测步数

    Returns:
        PredictionResult 预测结果对象
    """
    if not _torch_available or model_cls is None:
        return fallback_fn(video_data, threshold)

    # 懒加载 checkpoint manager + device
    _initialize_torch_runtime(algorithm)

    # 优先加载视频微调 checkpoint，回退到全局
    from algorithms.training.checkpoint_manager import load_best_checkpoint, checkpoint_signature

    algo_id = getattr(algorithm, "algorithm_id", "unknown")
    bvid = video_data.get("bvid", "")

    # 缓存优先：已缓存该 bvid 的 torch 模型且 checkpoint 签名未变时，
    # 跳过 load_best_checkpoint（其内部 torch.load 是最重的磁盘 I/O）。
    state, model_source, cache_ok = _load_prediction_checkpoint(
        algorithm, algo_id, bvid, checkpoint_signature, load_best_checkpoint
    )
    if not cache_ok and state is None:
        return fallback_fn(video_data, threshold)

    gpu_key = f"{algo_id}@{bvid}" if bvid else algo_id
    feats = features or DEFAULT_FEATURES
    x_arr = v_mean = v_std = None  # 初始化，供 except 中使用

    # ── Phase 1: ONNX Runtime（NPU/CPU 优先）──────────
    from algorithms.training.device import get_preferred_device

    prefer = get_preferred_device()
    skip_onnx = prefer == "cuda"
    skip_torch = prefer == "onnx_dml" or prefer == "cpu"

    x_arr, v_mean, v_std = _build_torch_input(video_data, feats, window)
    if x_arr is not None:
        result = _try_preferred_backend_predict(
            prefer,
            skip_onnx,
            algo_id,
            bvid,
            x_arr,
            window,
            len(feats) + 5,
            v_mean,
            v_std,
            algorithm,
            video_data,
            threshold,
            model_source,
            model_cls,
            model_kwargs,
            feats,
            horizon,
            state,
        )
        if result is not None:
            return result
    elif x_arr is None and not _torch_available:
        return fallback_fn(video_data, threshold)

    # ── Phase 2: PyTorch（GPU/CPU）──────────────────────
    if skip_torch:
        # 直接走 numpy 降级（ONNX 前面已试过）
        return fallback_fn(video_data, threshold)

    # ── Phase 2: PyTorch（GPU/CPU）──────────────────────
    try:

        return _run_torch_prediction(
            algorithm,
            video_data,
            threshold,
            algo_id,
            bvid,
            gpu_key,
            model_cls,
            model_kwargs,
            state,
            window,
            len(feats) + 5,
            horizon,
            x_arr,
            v_mean,
            v_std,
            model_source,
        )

    except Exception as e:
        return _fallback_after_torch_error(
            e,
            algorithm,
            video_data,
            threshold,
            model_cls,
            fallback_fn,
            model_kwargs,
            features,
            window,
            horizon,
            algo_id,
            bvid,
            feats,
            state,
            x_arr,
            v_mean,
            v_std,
            model_source,
        )
