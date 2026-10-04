"""Regression coverage for shared deep-learning algorithm caches."""

from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any
from types import SimpleNamespace

import numpy as np
import pytest

from algorithms.models.deep_learning import cnn_image
from algorithms.models.deep_learning.torch_upgrade import runtime
from algorithms.models.deep_learning.torch_upgrade import prediction

torch = pytest.importorskip("torch")


def _video_data(bvid: str, offset: int) -> dict[str, Any]:
    """Build deterministic history sufficient for CNN input normalization."""
    history = []
    for index in range(12):
        history.append(
            {
                "timestamp": 3600 * index,
                "view_count": offset + index * 100,
                "like_count": offset + index * 10,
                "coin_count": offset + index,
                "favorite_count": offset + index * 2,
                "share_count": offset + index * 3,
            }
        )
    return {"bvid": bvid, "view_count": history[-1]["view_count"], "history_data": history}


class _FakeModel:
    """Small per-video model surrogate that exposes its cache identity."""

    _dual_output = False

    def __init__(self, bvid: str):
        self.bvid = bvid


class _EvictionModel:
    """CPU-only model fake that records eviction attempts."""

    def __init__(self) -> None:
        self.cpu_calls = 0

    def cpu(self) -> None:
        self.cpu_calls += 1


def test_cnn_cache_switch_is_atomic_across_videos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent cache replacements must use the model selected for that request."""
    algorithm = cnn_image.CnnImageAlgorithm()

    def load_checkpoint(_algorithm_id: str, bvid: str = "") -> tuple[dict[str, str], None]:
        return {"bvid": bvid}, None

    def load_model(*args: Any, **kwargs: Any) -> _FakeModel:
        state = args[2]
        return _FakeModel(state["bvid"])

    def infer(model: _FakeModel, _input: Any, **kwargs: Any) -> Any:
        value = 1.0 if model.bvid == "BV_A" else 2.0
        return torch.tensor([[value]], dtype=torch.float32)

    monkeypatch.setattr(cnn_image, "load_best_checkpoint", load_checkpoint)
    monkeypatch.setattr("algorithms.models.deep_learning._torch_upgrade.load_checkpoint_model", load_model)
    monkeypatch.setattr(algorithm, "_npu_infer", infer)

    video_a = _video_data("BV_A", 1000)
    video_b = _video_data("BV_B", 2000)
    expected_a = algorithm._torch_predict(video_a)[0]
    expected_b = algorithm._torch_predict(video_b)[0]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(algorithm._torch_predict, video) for _ in range(20) for video in (video_a, video_b)]
        results = [future.result()[0] for future in futures]

    assert results[::2] == [expected_a] * 20
    assert results[1::2] == [expected_b] * 20
    assert algorithm._cached_bvid in {"BV_A", "BV_B"}


def test_lru_eviction_skips_model_owned_by_active_prediction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eviction must skip a busy model and evict an idle one without CUDA."""
    busy_model = _EvictionModel()
    idle_model = _EvictionModel()
    busy_lock = threading.RLock()
    idle_lock = threading.RLock()
    prediction_started = threading.Barrier(2)
    release_prediction = threading.Event()

    def hold_prediction_lock() -> None:
        with busy_lock:
            prediction_started.wait(timeout=5)
            release_prediction.wait(timeout=5)

    owner = threading.Thread(target=hold_prediction_lock)
    owner.start()
    prediction_started.wait(timeout=5)
    monkeypatch.setattr(runtime.torch.cuda, "empty_cache", lambda: None)
    with runtime._GPU_LRU_LOCK:
        runtime._GPU_MODEL_LRU.clear()
        runtime._GPU_MODEL_LRU["busy"] = (busy_model, 1, 0.0, busy_lock)
        runtime._GPU_MODEL_LRU["idle"] = (idle_model, 1, 1.0, idle_lock)

    try:
        assert runtime._evict_lru_gpu_model()
        assert busy_model.cpu_calls == 0
        assert idle_model.cpu_calls == 1
        with runtime._GPU_LRU_LOCK:
            assert list(runtime._GPU_MODEL_LRU) == ["busy"]
    finally:
        release_prediction.set()
        owner.join(timeout=5)
        with runtime._GPU_LRU_LOCK:
            runtime._GPU_MODEL_LRU.clear()


def test_persistent_cuda_oom_retries_once_and_releases_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persistent CUDA OOM performs one retry before the normal fallback chain."""
    algorithm = SimpleNamespace(
        algorithm_id="oom_test",
        _device=SimpleNamespace(type="cuda"),
        _prediction_lock=threading.RLock(),
        _gpu_use_lock=threading.Lock(),
    )
    attempts = 0
    fallback_calls = 0

    def load_checkpoint(*args: Any, **kwargs: Any) -> tuple[dict[str, str], str, bool]:
        return {"state": "fake"}, "test", False

    def persistent_oom(*args: Any, **kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("CUDA out of memory")

    def fallback(*args: Any, **kwargs: Any) -> str:
        nonlocal fallback_calls
        fallback_calls += 1
        return "numpy-fallback"

    def can_acquire(lock: Any) -> bool:
        acquired = lock.acquire(timeout=1)
        if acquired:
            lock.release()
        return acquired

    monkeypatch.setattr(prediction, "_load_prediction_checkpoint", load_checkpoint)
    monkeypatch.setattr(prediction, "_build_torch_input", lambda *args: (np.zeros((1, 1)), 0.0, 1.0))
    monkeypatch.setattr(prediction, "_try_preferred_backend_predict", lambda *args: None)
    monkeypatch.setattr(prediction, "_run_torch_prediction", persistent_oom)
    monkeypatch.setattr(prediction, "_try_npu_fallback", lambda *args: None)
    monkeypatch.setattr(prediction, "_try_onnx_predict", lambda *args: None)
    monkeypatch.setattr(prediction, "_evict_lru_gpu_model", lambda: False)
    monkeypatch.setattr(prediction.torch.cuda, "empty_cache", lambda: None)
    monkeypatch.setattr("algorithms.training.device.get_preferred_device", lambda: "cuda")

    result = prediction.try_torch_predict(algorithm, {"bvid": "BV_OOM"}, 100, object, fallback)

    assert result == "numpy-fallback"
    assert attempts == 2
    assert fallback_calls == 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert all(executor.map(can_acquire, (algorithm._prediction_lock, algorithm._gpu_use_lock)))
