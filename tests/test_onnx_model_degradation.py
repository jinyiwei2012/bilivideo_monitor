"""ONNX 按模型降级测试（5.5）。

冻结「单模型导出失败不得关闭全进程 ONNX 能力」这一事实。
全部使用替身，不依赖真实 GPU / ONNX Runtime / 大型模型。
"""

import os
from unittest.mock import Mock

import pytest

from algorithms.training import onnx_exporter


@pytest.fixture
def exporter_env(monkeypatch, tmp_path):
    """隔离 ONNX exporter 的全局状态，注入可控目录与 runtime。"""
    monkeypatch.setattr(onnx_exporter, "_onnx_available", True)
    monkeypatch.setattr(onnx_exporter, "_onnx_export_failures", set())
    monkeypatch.setattr(onnx_exporter, "_ONNX_DIR", str(tmp_path))
    monkeypatch.setattr(onnx_exporter, "_get_onnx_dir", lambda: str(tmp_path))
    return tmp_path


def _make_failing_module(monkeypatch, exc):
    """让 torch.onnx.export 在调用时抛 exc；torch 的其余接口保持最小可用。"""
    torch_mod = Mock()

    class _Param:
        def device(self):
            return "cpu"

    fake_model = Mock()
    fake_model.parameters.side_effect = lambda: iter([_Param()])
    fake_model.eval.return_value = None

    def _boom(*_a, **_k):
        raise exc

    torch_mod.onnx = Mock()
    torch_mod.onnx.export = _boom
    torch_mod.randn = lambda *a, **k: object()
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)
    return fake_model


def test_single_model_failure_does_not_block_other_models(exporter_env, monkeypatch):
    """模型 A 失败后，模型 B 的导出仍会被尝试并成功。"""
    from algorithms.training import onnx_exporter as oe

    calls = {"n": 0}

    def _export(model, dummy, path, **_k):
        calls["n"] += 1
        if "algo_A" in os.path.basename(path):
            raise RuntimeError("A boom")
        with open(path, "w", encoding="utf-8") as f:
            f.write("onnx")

    torch_mod = Mock()
    torch_mod.onnx = Mock()
    torch_mod.onnx.export = _export
    torch_mod.randn = lambda *a, **k: object()
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)

    class _Param:
        def device(self):
            return "cpu"

    model = Mock()
    model.parameters.side_effect = lambda: iter([_Param()])
    model.eval.return_value = None

    assert oe.export_to_onnx(model, "algo_A") is None
    result_b = oe.export_to_onnx(model, "algo_B")
    assert result_b is not None
    assert os.path.exists(result_b)
    assert calls["n"] == 2


def test_export_failure_does_not_disable_onnx_inference(exporter_env, monkeypatch):
    """导出失败不得使 is_onnx_available() 变假，已有 ONNX 仍可加载。"""
    from algorithms.training import onnx_exporter as oe

    model = _make_failing_module(monkeypatch, RuntimeError("boom"))
    assert oe.export_to_onnx(model, "algo_fail") is None
    assert oe.is_onnx_available() is True


def test_forward_attribute_error_degrades_only_that_model(exporter_env, monkeypatch):
    """模型 forward() 抛 AttributeError 只降级当前模型，不产生进程级 broken。"""
    from algorithms.training import onnx_exporter as oe

    model = _make_failing_module(monkeypatch, AttributeError("forward attr"))
    assert oe.export_to_onnx(model, "algo_attr") is None
    assert oe.is_onnx_available() is True
    assert not hasattr(oe, "_onnx_export_broken")


def test_failed_model_does_not_retry_without_force(exporter_env, monkeypatch):
    """同一模型非强制调用不应重复尝试导出。"""
    from algorithms.training import onnx_exporter as oe

    attempts = {"n": 0}

    def _boom(*_a, **_k):
        attempts["n"] += 1
        raise RuntimeError("boom")

    torch_mod = Mock()
    torch_mod.onnx = Mock()
    torch_mod.onnx.export = _boom
    torch_mod.randn = lambda *a, **k: object()
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)

    class _Param:
        def device(self):
            return "cpu"

    model = Mock()
    model.parameters.side_effect = lambda: iter([_Param()])
    model.eval.return_value = None

    assert oe.export_to_onnx(model, "algo_cache") is None
    assert oe.export_to_onnx(model, "algo_cache") is None
    assert attempts["n"] == 1


def test_force_allows_recovery_and_clears_failure(exporter_env, monkeypatch):
    """force=True 可绕过失败缓存；成功后清除该 key 的失败记录。"""
    from algorithms.training import onnx_exporter as oe

    state = {"fail": True}

    def _export(model, dummy, path, **_k):
        if state["fail"]:
            raise RuntimeError("boom")
        with open(path, "w", encoding="utf-8") as f:
            f.write("onnx")

    torch_mod = Mock()
    torch_mod.onnx = Mock()
    torch_mod.onnx.export = _export
    torch_mod.randn = lambda *a, **k: object()
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)

    class _Param:
        def device(self):
            return "cpu"

    model = Mock()
    model.parameters.side_effect = lambda: iter([_Param()])
    model.eval.return_value = None

    assert oe.export_to_onnx(model, "algo_rec") is None
    assert ("algo_rec", "") in oe._onnx_export_failures

    state["fail"] = False
    recovered = oe.export_to_onnx(model, "algo_rec", force=True)
    assert recovered is not None
    assert ("algo_rec", "") not in oe._onnx_export_failures


def test_global_model_and_finetuned_model_are_independent(exporter_env, monkeypatch):
    """同名全局模型与视频微调模型的失败 key 必须独立。"""
    from algorithms.training import onnx_exporter as oe

    def _export(model, dummy, path, **_k):
        if "__BV" in path:
            raise RuntimeError("finetune boom")
        with open(path, "w", encoding="utf-8") as f:
            f.write("onnx")

    torch_mod = Mock()
    torch_mod.onnx = Mock()
    torch_mod.onnx.export = _export
    torch_mod.randn = lambda *a, **k: object()
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)

    class _Param:
        def device(self):
            return "cpu"

    model = Mock()
    model.parameters.side_effect = lambda: iter([_Param()])
    model.eval.return_value = None

    assert oe.export_to_onnx(model, "algo_x", bvid="BV123") is None
    assert ("algo_x", "BV123") in oe._onnx_export_failures
    assert ("algo_x", "") not in oe._onnx_export_failures
    assert oe.export_to_onnx(model, "algo_x") is not None


def test_incomplete_onnx_artifact_is_removed_on_failure(exporter_env, monkeypatch):
    """导出中途失败须删除残缺 .onnx，避免被后续误当作已有产物。"""
    from algorithms.training import onnx_exporter as oe

    def _export(model, dummy, path, **_k):
        with open(path, "w", encoding="utf-8") as f:
            f.write("partial")
        raise RuntimeError("mid boom")

    torch_mod = Mock()
    torch_mod.onnx = Mock()
    torch_mod.onnx.export = _export
    torch_mod.randn = lambda *a, **k: object()
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)

    class _Param:
        def device(self):
            return "cpu"

    model = Mock()
    model.parameters.side_effect = lambda: iter([_Param()])
    model.eval.return_value = None

    assert oe.export_to_onnx(model, "algo_partial") is None
    assert not os.path.exists(oe.get_onnx_path("algo_partial"))
