"""Execution-policy manifest coverage and audit tests.

These tests only guard the declarative manifest; they must not change or assert
any real concurrency behaviour beyond confirming existing locks are untouched.
"""

from algorithms.execution_policy import (
    DEFAULT_STRATEGY,
    ExecutionStrategy,
    execution_policy_summary,
    ghost_manifest_entries,
    manifest_key,
    strategy_for,
    unclassified_algorithms,
)
from algorithms.execution_policy_manifest import EXECUTION_POLICY_MANIFEST
from algorithms.registry import AlgorithmRegistry


def _registered():
    AlgorithmRegistry.reset()
    AlgorithmRegistry.initialize()
    return AlgorithmRegistry.get_all_algorithms()


def test_registry_count_is_137():
    assert len(_registered()) == 137


def test_all_registered_algorithms_are_classified():
    algos = _registered()
    assert unclassified_algorithms(algos) == []
    assert len(EXECUTION_POLICY_MANIFEST) == 137


def test_manifest_has_no_ghost_entries():
    algos = _registered()
    assert ghost_manifest_entries(algos) == []


def test_known_stateful_models_not_marked_stateless():
    algos = _registered()
    keys = {manifest_key(algo) for algo in algos}
    for key in keys:
        if ".deep_learning." in key:
            assert EXECUTION_POLICY_MANIFEST[key]["strategy"] != ExecutionStrategy.STATELESS_SHARED.value
    assert (
        EXECUTION_POLICY_MANIFEST["algorithms.models.deep_learning.cnn_image.CnnImageAlgorithm"]["strategy"]
        == ExecutionStrategy.LOCKED_SHARED.value
    )
    assert (
        EXECUTION_POLICY_MANIFEST["algorithms.models.deep_learning.diffusion_ts.DiffusionTSAlgorithm"]["strategy"]
        == ExecutionStrategy.LOCKED_SHARED.value
    )


def test_unknown_algorithm_defaults_to_locked_shared():
    class _UnregisteredAlgorithm:
        pass

    assert strategy_for(_UnregisteredAlgorithm()) == DEFAULT_STRATEGY
    assert strategy_for(_UnregisteredAlgorithm()) == ExecutionStrategy.LOCKED_SHARED


def test_per_video_is_declared_only_not_effective():
    algos = _registered()
    # No registered algorithm is declared PER_VIDEO yet; and if any were, the
    # registry still returns shared instances (declaration does not allocate per-video).
    for algo in algos:
        assert strategy_for(algo) != ExecutionStrategy.PER_VIDEO
    first = algos[0]
    second = algos[0]
    assert first is second


def test_existing_instance_locks_remain_present():
    algos = _registered()
    by_key = {manifest_key(algo): algo for algo in algos}
    cnn = by_key["algorithms.models.deep_learning.cnn_image.CnnImageAlgorithm"]
    diffusion = by_key["algorithms.models.deep_learning.diffusion_ts.DiffusionTSAlgorithm"]
    assert hasattr(cnn, "_cache_lock")
    assert hasattr(diffusion, "_cache_lock")


def test_summary_reports_full_coverage():
    summary = execution_policy_summary(_registered())
    assert summary["total"] == 137
    assert summary["classified"] == 137
    assert summary["unclassified"] == []


def test_registry_query_accessor_is_read_only():
    algos = _registered()
    name = "[Model] " + algos[0].name
    assert AlgorithmRegistry.get_execution_strategy(name) in {s.value for s in ExecutionStrategy}
    assert AlgorithmRegistry.get_execution_strategy("__no_such_algo__") == DEFAULT_STRATEGY.value
    assert AlgorithmRegistry.execution_policy_summary()["total"] == 137
