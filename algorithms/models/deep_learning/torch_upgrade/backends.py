"""Extracted torch-upgrade helpers."""

import threading
from typing import Dict, List

import numpy as np

from .context import logger, torch
from .model_io import _generic_result, load_checkpoint_model

_AUTO_BACKEND_RANK: Dict[str, List[str]] = {}
_AUTO_BENCHMARKED: set = set()
_BENCHMARK_LOCK = threading.Lock()


def _benchmark_torch_backend(x_arr, window, in_features, model_cls, model_kwargs, horizon, state_, _time):
    """基准测试已加载 checkpoint 的 torch 后端。"""
    mk = dict(model_kwargs or {})
    model_t = load_checkpoint_model(model_cls, mk, state_, window, in_features, horizon)
    model_t.eval()

    x_t = torch.from_numpy(x_arr).unsqueeze(0)
    for _ in range(3):  # warmup
        with torch.no_grad():
            _ = model_t(x_t)

    t0 = _time.perf_counter()
    for _ in range(10):
        with torch.no_grad():
            _ = model_t(x_t)
    return (_time.perf_counter() - t0) / 10 * 1000


def _benchmark_npu_backend(algo_id, x_arr, window, in_features, model_cls, model_kwargs, horizon, state_, _time):
    """基准测试 NPU 后端，无法测试时返回 None。"""
    from algorithms.training.npu_inference import get_npu_engine

    engine = get_npu_engine()
    if not engine.is_available or state_ is None:
        return None

    model_n = load_checkpoint_model(model_cls, model_kwargs, state_, window, in_features, horizon)
    # Prepare (compile once, cached on disk)
    engine.prepare_model(algo_id, model_n, torch.from_numpy(x_arr).unsqueeze(0))
    x_npu = np.asarray(x_arr, dtype=np.float16)
    if x_npu.ndim == 2:
        x_npu = x_npu[np.newaxis, :, :]
    for _ in range(3):  # warmup
        engine.infer(algo_id, x_npu)

    t0 = _time.perf_counter()
    for _ in range(10):
        engine.infer(algo_id, x_npu)
    return (_time.perf_counter() - t0) / 10 * 1000


def _benchmark_onnx_backend(algo_id, x_arr, bvid_, window, in_features, _time):
    """基准测试 ONNX 后端，不可用时返回 None。"""
    from algorithms.training.onnx_exporter import get_onnx_session, is_onnx_available

    if not is_onnx_available():
        return None

    session = get_onnx_session()
    for _ in range(3):  # warmup
        _ = session.predict(algo_id, x_arr, bvid_, window, in_features)

    t0 = _time.perf_counter()
    for _ in range(10):
        _ = session.predict(algo_id, x_arr, bvid_, window, in_features)
    return (_time.perf_counter() - t0) / 10 * 1000


def _append_backend_latency(rankings, backend, latency, algo_id):
    """记录成功的后端基准结果。"""
    if latency is None:
        return
    rankings.append((backend, latency))
    if backend == "torch":
        logger.debug("[%s] benchmark torch: %.3f ms", algo_id, latency)
    elif backend == "npu":
        logger.debug("[%s] benchmark npu: %.3f ms", algo_id, latency)
    else:
        logger.debug("[%s] benchmark onnx: %.3f ms", algo_id, latency)


def _rank_backends(
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
    model_cls,
    model_kwargs,
    features,
    horizon,
) -> List[str]:
    """基准测试各推理后端速度，返回按速度排序的后端列表（最快优先）。

    首次调用时对 torch / NPU / ONNX 各执行 warmup + 10 次推理取均值，
    排序后缓存结果。后续调用直接返回缓存。
    """
    if algo_id in _AUTO_BACKEND_RANK:
        return _AUTO_BACKEND_RANK[algo_id]

    with _BENCHMARK_LOCK:
        if algo_id in _AUTO_BACKEND_RANK:  # double-check
            return _AUTO_BACKEND_RANK[algo_id]

        import time as _time

        rankings = []  # [(backend_name, avg_latency_ms), ...]

        # ── Benchmark torch ─────────────────────
        try:
            from algorithms.training.checkpoint_manager import load_best_checkpoint

            bvid_ = video_data.get("bvid", "")
            state_, _ = load_best_checkpoint(algo_id, bvid=bvid_)
            if state_ is not None:
                lat = _benchmark_torch_backend(
                    x_arr, window, in_features, model_cls, model_kwargs, horizon, state_, _time
                )
                _append_backend_latency(rankings, "torch", lat, algo_id)
        except Exception as e:
            logger.debug("[%s] benchmark torch failed: %s", algo_id, e)

        # ── Benchmark NPU ───────────────────────
        try:
            lat = _benchmark_npu_backend(
                algo_id,
                x_arr,
                window,
                in_features,
                model_cls,
                model_kwargs,
                horizon,
                state_ if "state_" in dir() else None,
                _time,
            )
            _append_backend_latency(rankings, "npu", lat, algo_id)
        except Exception as e:
            logger.debug("[%s] benchmark npu failed: %s", algo_id, e)

        # ── Benchmark ONNX ──────────────────────
        try:
            lat = _benchmark_onnx_backend(algo_id, x_arr, bvid_, window, in_features, _time)
            _append_backend_latency(rankings, "onnx", lat, algo_id)
        except Exception as e:
            logger.debug("[%s] benchmark onnx failed: %s", algo_id, e)

        # 排序：按实际基准速度排序，不再假设 torch/CUDA 一定最快
        sorted_rankings = sorted(rankings, key=lambda x: x[1])
        result = [name for name, _ in sorted_rankings]
        if not result:
            result = ["torch"]
        _AUTO_BACKEND_RANK[algo_id] = result
        logger.info("[%s] 后端排序: %s", algo_id, " > ".join(f"{n}({l:.2f}ms)" for n, l in sorted_rankings))
        return result


def _try_onnx_predict(
    algo_id, bvid, x_arr, window, in_features, v_mean, v_std, algorithm, video_data, threshold, model_source
):
    """ONNX Runtime 推理尝试，成功返回 PredictionResult，失败返回 None。"""
    try:
        from algorithms.training.onnx_exporter import get_onnx_session, is_onnx_available

        if not is_onnx_available():
            return None

        session = get_onnx_session()
        y = session.predict(algo_id, x_arr, bvid, window, in_features)
        if y is None:
            return None
        predicted_velocity = max(0.0, float(y[0]) * v_std + v_mean)
        # ONNX 导出自双宽模型时输出为 H+1；无法直接读模型标志，用长度判断
        horizon = int(getattr(algorithm, "training_horizon", 3))
        long_velocity = None
        if len(y) > horizon:
            long_velocity = max(0.0, float(y[horizon]) * v_std + v_mean)
        return _generic_result(
            algorithm,
            video_data,
            threshold,
            predicted_velocity,
            y,
            model_source=f"{model_source}+ONNX",
            long_velocity=long_velocity,
        )
    except Exception:
        return None


def _try_npu_predict(
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
    model_cls=None,
    model_kwargs=None,
    feats=None,
    horizon=None,
    state=None,
):
    """NPU 推理尝试，成功返回 PredictionResult，失败返回 None。"""
    try:
        from algorithms.training.npu_inference import get_npu_engine

        engine = get_npu_engine()
        if not engine.is_available:
            return None

        model = getattr(algorithm, "_cached_torch_model", None)
        if model is None or (bvid and not getattr(algorithm, "_cached_bvid", "") == bvid):
            if model_cls is None or state is None:
                return None
            model = load_checkpoint_model(model_cls, model_kwargs, state, window, in_features, int(horizon or 3))
            algorithm._cached_torch_model = model
            algorithm._cached_bvid = bvid or ""

        y = algorithm._npu_infer(model, x_arr, algo_name=algo_id)
        y_np = y.cpu().numpy().reshape(-1)
        predicted_velocity = max(0.0, float(y_np[0]) * v_std + v_mean)
        long_velocity = None
        if bool(getattr(model, "_dual_output", False)) and len(y_np) > int(horizon or 3):
            long_velocity = max(0.0, float(y_np[int(horizon or 3)]) * v_std + v_mean)
        return _generic_result(
            algorithm,
            video_data,
            threshold,
            predicted_velocity,
            y_np,
            model_source=f"{model_source}+NPU",
            long_velocity=long_velocity,
        )
    except Exception:
        return None
