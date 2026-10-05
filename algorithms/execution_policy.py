"""声明式算法执行策略（仅声明与审计，不改变任何现有并发行为）。

三态语义：

- ``STATELESS_SHARED``：无可变实例状态，可跨视频安全共享同一实例。
- ``LOCKED_SHARED``：有可变实例状态，但已有实例锁保护；共享安全性由锁保证。
- ``PER_VIDEO``：需按 BVID 生命周期独享实例。当前仅声明，注册表仍返回共享实例。

未知算法一律按 ``LOCKED_SHARED`` 处理——安全默认，绝不默认为无状态共享。
"""

from enum import Enum
from typing import Any, Dict, Iterable, List


class ExecutionStrategy(str, Enum):
    """Declarative concurrency strategy for one algorithm class."""

    STATELESS_SHARED = "stateless_shared"
    LOCKED_SHARED = "locked_shared"
    PER_VIDEO = "per_video"


DEFAULT_STRATEGY = ExecutionStrategy.LOCKED_SHARED


def manifest_key(algorithm: Any) -> str:
    """Return the stable manifest key ``module_path.ClassName`` for an instance/class."""
    cls = algorithm if isinstance(algorithm, type) else type(algorithm)
    return f"{cls.__module__}.{cls.__name__}"


def strategy_for(algorithm: Any) -> ExecutionStrategy:
    """Resolve the declared strategy; unknown algorithms fall back to LOCKED_SHARED."""
    from .execution_policy_manifest import EXECUTION_POLICY_MANIFEST

    entry = EXECUTION_POLICY_MANIFEST.get(manifest_key(algorithm))
    if entry is None:
        return DEFAULT_STRATEGY
    return ExecutionStrategy(entry["strategy"])


def unclassified_algorithms(algorithms: Iterable[Any]) -> List[str]:
    """Return manifest keys of algorithms that are absent from the manifest."""
    from .execution_policy_manifest import EXECUTION_POLICY_MANIFEST

    return sorted(manifest_key(algo) for algo in algorithms if manifest_key(algo) not in EXECUTION_POLICY_MANIFEST)


def ghost_manifest_entries(algorithms: Iterable[Any]) -> List[str]:
    """Return manifest keys with no matching registered algorithm."""
    from .execution_policy_manifest import EXECUTION_POLICY_MANIFEST

    registered = {manifest_key(algo) for algo in algorithms}
    return sorted(key for key in EXECUTION_POLICY_MANIFEST if key not in registered)


def execution_policy_summary(algorithms: Iterable[Any]) -> Dict[str, Any]:
    """Summarize declared coverage for the given registered algorithms."""
    from .execution_policy_manifest import EXECUTION_POLICY_MANIFEST

    keys = [manifest_key(algo) for algo in algorithms]
    counts: Dict[str, int] = {strategy.value: 0 for strategy in ExecutionStrategy}
    for key in keys:
        entry = EXECUTION_POLICY_MANIFEST.get(key)
        strategy = ExecutionStrategy(entry["strategy"]) if entry else DEFAULT_STRATEGY
        counts[strategy.value] += 1
    return {
        "total": len(keys),
        "classified": sum(1 for key in keys if key in EXECUTION_POLICY_MANIFEST),
        "unclassified": unclassified_algorithms(algorithms),
        "counts": counts,
    }
