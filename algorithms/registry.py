"""
算法注册器

集中管理所有预测算法。在首次使用时自动扫描 models/ 目录下的所有
算法文件（BaseAlgorithm 直接实例），并为每个视频运行全量算法预测，
产生带权重加权的集成预测结果（ensemble prediction）。
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
import threading

from .base import BaseAlgorithm
from . import weight_manager as _weight_manager
from .registry_parts import EnsembleMixin, FeaturePrepMixin, ModelLoadMixin, WarmupMixin
from .registry_parts._shared import _LRUDict, _MAX_CACHE_SIZE, logger

get_weight_manager = _weight_manager.get_weight_manager


class AlgorithmRegistry(FeaturePrepMixin, EnsembleMixin, WarmupMixin, ModelLoadMixin):
    """算法注册器 —— 单例风格的类方法容器。

    职责：
        - 延迟初始化、自动发现 models/ 下的算法
        - 为每个视频发起并行预测，收集结果
        - 基于算法间共识度（coherence）调整权重
        - 输出加权集成预测 + 保形预测区间
    """

    _algorithms: Dict[str, BaseAlgorithm] = {}
    _initialized = False
    _pool_lock = threading.RLock()  # RLock to allow reentrant pool access
    _pool: Optional[ThreadPoolExecutor] = None
    _init_lock = threading.Lock()
    _history_lock = threading.Lock()
    _cache_lock = threading.Lock()  # 保护 _derived_cache 并发读写
    _derived_cache: _LRUDict = _LRUDict(maxsize=_MAX_CACHE_SIZE)

    # B3: 集成偏差校准 —— 记录每个 bvid 上一次集成预测 (prediction, current_value)
    # 下次预测时用新的 current_value 作"实际值"验证 growth 偏差
    _prev_ensemble_pred: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    _prev_ensemble_lock = threading.Lock()

    @classmethod
    def _record_ensemble_feedback(cls, bvid: str, current_value: float) -> None:
        """用上一轮集成预测验证本轮实际增长，记录系统性偏差样本 (B3)。"""
        if not bvid:
            return
        with cls._prev_ensemble_lock:
            prev = cls._prev_ensemble_pred.get(bvid)
            if prev is None:
                cls._prev_ensemble_pred[bvid] = (current_value, current_value)
                return
            prev_pred, prev_current = prev
            cls._prev_ensemble_pred[bvid] = (current_value, current_value)
        if prev_pred is None or prev_current is None:
            return
        try:
            pred_growth = float(prev_pred) - float(prev_current)
            actual_growth = float(current_value) - float(prev_current)
            if pred_growth > 0:
                from .bias_correction import get_bias_corrector

                get_bias_corrector().record(bvid, pred_growth, actual_growth)
        except Exception as e:
            logger.debug("记录集成偏差样本失败: %s", e)

    @classmethod
    def reset_ensemble_bias(cls, bvid: str) -> None:
        """删除某视频的偏差样本（删除监控时调用）。"""
        with cls._prev_ensemble_lock:
            cls._prev_ensemble_pred.pop(bvid, None)
        try:
            from .bias_correction import get_bias_corrector

            get_bias_corrector().reset_bvid(bvid)
        except Exception:
            pass

    @classmethod
    def initialize(cls) -> None:
        """初始化：自动加载并注册所有算法（双检锁线程安全）

        只会执行一次，之后的重复调用被忽略。
        """
        if cls._initialized:
            return
        with cls._init_lock:
            if cls._initialized:
                return

            # 加载 models 目录下的所有算法（含子目录）
            cls._load_model_algorithms()

            cls._initialized = True
            logger.info("算法注册完成，共 %d 个算法", len(cls._algorithms))

    @classmethod
    def get_algorithm(cls, name: str) -> Optional[BaseAlgorithm]:
        """按名称获取已注册的算法实例。"""
        if not cls._initialized:
            cls.initialize()
        return cls._algorithms.get(name)

    @classmethod
    def get_registry_key(cls, algorithm_id: str) -> str:
        """根据原始 algorithm_id 查找注册表中存储的完整 key。

        注册表 key 格式通常为 "[Model] <name>"，此方法做反向映射。
        """
        if not cls._initialized:
            cls.initialize()
        for key, algo in cls._algorithms.items():
            raw_id = getattr(algo, "algorithm_id", None)
            if raw_id == algorithm_id:
                return str(key)
        return algorithm_id

    @classmethod
    def get_all_algorithms(cls) -> List[BaseAlgorithm]:
        """获取所有已注册算法实例的列表。"""
        if not cls._initialized:
            cls.initialize()
        return list(cls._algorithms.values())

    @classmethod
    def get_algorithm_names(cls) -> List[str]:
        """获取所有已注册算法的名称列表。"""
        if not cls._initialized:
            cls.initialize()
        return list(cls._algorithms.keys())

    @classmethod
    def shutdown(cls) -> None:
        """关闭线程池，释放资源（应用退出时调用）。"""
        with cls._pool_lock:
            pool = cls._pool
            cls._pool = None
        if pool is not None:
            pool.shutdown(wait=False)

    @classmethod
    def reset(cls) -> None:
        """重置注册器：清空所有已注册算法并关闭线程池。"""
        cls.shutdown()
        cls._algorithms = {}
        cls._derived_cache = _LRUDict(maxsize=_MAX_CACHE_SIZE)
        cls._initialized = False
        with cls._prev_ensemble_lock:
            cls._prev_ensemble_pred.clear()


# 不再模块级初始化，改为按需（Lazy）初始化 —— 所有公开方法都已检查 _initialized 标志
