"""ModelLoadMixin extracted from algorithms.registry."""

from typing import Any, cast, Dict, Iterable, List, Optional, TYPE_CHECKING, Tuple
import importlib

from ..base import BaseAlgorithm

from ._shared import get_weight_manager, logger


class ModelLoadMixin:
    _algorithms: Dict[str, BaseAlgorithm]
    _initialized: bool

    if TYPE_CHECKING:

        @classmethod
        def initialize(cls) -> None:
            raise NotImplementedError

        @classmethod
        def get_registry_key(cls, algorithm_id: str) -> str:
            raise NotImplementedError

        @classmethod
        def get_algorithm_names(cls) -> List[str]:
            raise NotImplementedError

    @classmethod
    def _load_model_algorithms(cls) -> None:
        """扫描 models/ 目录, 直接实例化并注册所有算法 (不再经 ModelAlgorithmAdapter 包装)。"""
        try:
            import importlib
            import os

            current_dir = os.path.dirname(os.path.dirname(__file__))
            models_dir = os.path.join(current_dir, "models")
            if not os.path.exists(models_dir):
                logger.warning("models目录不存在: %s", models_dir)
                return

            for root, dirs, files in os.walk(models_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for filename in sorted(files):
                    if not filename.endswith(".py") or filename.startswith("_"):
                        continue
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, models_dir)
                    module_path = rel_path[:-3].replace("\\", ".").replace("/", ".")
                    try:
                        module = importlib.import_module(f".models.{module_path}", package="algorithms")
                    except Exception as e:
                        logger.warning("加载算法 %s 失败: %s", module_path, e)
                        continue
                    cls._register_module_algorithms(module, module_path)

        except Exception as e:
            logger.error("加载models算法失败: %s", e)
            import traceback

            traceback.print_exc()

    @classmethod
    def _register_module_algorithms(cls, module: Any, module_path: str) -> None:
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not isinstance(attr, type) or not attr_name.endswith("Algorithm"):
                continue
            if "BaseAlgorithm" not in {c.__name__ for c in attr.__mro__}:
                continue
            try:
                instance = attr()
            except Exception as e:
                logger.debug("忽略算法 %s.%s: %s", module_path, attr_name, e)
                continue
            algo_name = f"[Model] {instance.name}"
            cls._algorithms[algo_name] = instance

    @classmethod
    def update_accuracy(
        cls,
        algorithm_name: str,
        predicted: Optional[float] = None,
        actual: Optional[float] = None,
        accuracy: Optional[float] = None,
    ) -> None:
        """更新单个算法的准确率记录并同步到权重管理器（B1 修复）。

        统一入口，两种调用方式：
        1) update_accuracy(name, predicted, actual) —— 生产回路：预测值/实际值，自动换算准确率
        2) update_accuracy(name, accuracy=acc) —— 训练完成/外部直接给 0~1 准确率

        旧签名错配修复：main_gui_events 曾调 update_accuracy(algo_id, 1.0, accuracy)，
        把 predicted=1.0/actual=accuracy 硬塞，导致误差恒为 |1-acc| —— 已改由 accuracy 关键字正确传入。
        """
        if algorithm_name not in cls._algorithms:
            # 反向映射：可能传入了裸 algorithm_id
            algorithm_name = cls.get_registry_key(algorithm_name)
        algo = cls._algorithms.get(algorithm_name)
        if accuracy is None:
            if predicted is not None and actual is not None and actual > 0:
                # 相对误差 → 准确率（对称度量，避免播放量量级影响）
                _base = max(abs(predicted), actual, 1.0)
                rel_err = abs(predicted - actual) / _base
                accuracy = max(0.0, min(1.0, 1.0 - rel_err))
            else:
                accuracy = 0.5
        try:
            if algo is not None and hasattr(algo, "update_accuracy"):
                algo.update_accuracy(accuracy)
        except Exception as e:
            logger.debug("算法内部准确率更新失败 %s: %s", algorithm_name, e)
        try:
            get_weight_manager().update_accuracy(algorithm_name, max(0.0, min(1.0, accuracy)))
        except Exception as e:
            logger.debug("更新算法准确率失败 %s: %s", algorithm_name, e)

    @classmethod
    def update_accuracy_batch(cls, items: Iterable[Tuple[str, Optional[float], Optional[float]]]) -> None:
        """批量更新多个算法的准确率记录（整批仅重算/落盘一次）。

        与逐条 update_accuracy 语义等价，但把 WeightManager 的全量 ML 重算与
        JSON 写盘从 N 次降为 1 次（生产回路 ~120 算法/轮）。

        Args:
            items: 可迭代的 (algorithm_name, predicted, actual) 三元组；
                   predicted/actual 用于换算准确率（actual<=0 时记 0.5）。
        """
        collected = []
        for item in items:
            try:
                name, predicted, actual = item
            except Exception:
                continue
            if not name:
                continue
            if name not in cls._algorithms:
                name = cls.get_registry_key(name)
            algo = cls._algorithms.get(name)
            if predicted is not None and actual is not None and actual > 0:
                _base = max(abs(predicted), actual, 1.0)
                rel_err = abs(predicted - actual) / _base
                accuracy = max(0.0, min(1.0, 1.0 - rel_err))
            else:
                accuracy = 0.5
            try:
                if algo is not None and hasattr(algo, "update_accuracy"):
                    algo.update_accuracy(accuracy)
            except Exception as e:
                logger.debug("算法内部准确率更新失败 %s: %s", name, e)
            collected.append((name, accuracy))
        if collected:
            try:
                get_weight_manager().update_accuracy_batch(collected)
            except Exception as e:
                logger.debug("批量更新算法准确率失败: %s", e)

    @classmethod
    def update_ensemble_accuracy(cls, predicted: float, actual: float) -> None:
        """用集成预测值与实际值更新保形预测器的校准集。"""
        try:
            from ..conformal import get_conformal_predictor

            get_conformal_predictor().update(predicted, actual)
        except Exception as e:
            logger.debug("更新集成预测准确率失败: %s", e)

    @classmethod
    def get_weights_info(cls) -> List[Dict[str, Any]]:
        """获取所有算法的权重信息（供 UI 展示）。"""
        if not cls._initialized:
            cls.initialize()

        names = cls.get_algorithm_names()

        try:
            return cast(List[Dict[str, Any]], get_weight_manager().get_algorithm_info(names))
        except Exception as e:
            logger.debug("获取算法权重信息失败: %s", e)
            return [
                {
                    "name": n,
                    "accuracy": 0.5,
                    "final_weight": 1.0,
                    "ml_weight": 1.0,
                    "user_weight": None,
                    "is_customized": False,
                    "samples": 0,
                }
                for n in names
            ]

    @classmethod
    def get_trainable_info(cls) -> List[Dict[str, Any]]:
        """获取所有支持训练的算法的检查点信息。"""
        CheckpointManager = importlib.import_module("algorithms.training.checkpoint_manager").CheckpointManager

        if not cls._initialized:
            cls.initialize()
        result = []
        for aid, algo in cls._algorithms.items():
            build_model_fn = getattr(algo, "build_model", None)
            if build_model_fn is None:
                continue
            ckpt = CheckpointManager(aid)
            versions = ckpt.list_versions()
            active = ckpt.active_version()
            result.append(
                {
                    "algorithm_id": aid,
                    "name": getattr(algo, "name", aid),
                    "category": getattr(algo, "category", ""),
                    "has_ckpt": ckpt.has_checkpoint(),
                    "active_version": active or "",
                    "version_count": len(versions),
                }
            )
        return result

    @classmethod
    def get_trainable_algorithms(cls) -> List[Tuple[str, BaseAlgorithm, BaseAlgorithm]]:
        """获取所有支持训练的算法列表（供训练调度使用）。"""
        if not cls._initialized:
            cls.initialize()
        result = []
        for aid, algo in cls._algorithms.items():
            build_model_fn = getattr(algo, "build_model", None)
            if build_model_fn is None:
                continue
            result.append((aid, algo, algo))
        return result
