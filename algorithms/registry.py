"""
算法注册器
管理所有预测算法（自动扫描models目录下的所有算法）
"""

from typing import Dict, List, Tuple
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.time_utils import normalize_timestamp

logger = logging.getLogger(__name__)

try:
    from .weight_manager import weight_manager
except ImportError:
    weight_manager = None


class AlgorithmRegistry:
    """算法注册器"""

    _algorithms: Dict = {}
    _initialized = False
    _model_adapters = {}

    @classmethod
    def initialize(cls):
        """初始化注册所有算法"""
        if cls._initialized:
            return

        # 加载models目录下的所有算法（包括子目录）
        cls._load_model_algorithms()

        cls._initialized = True
        logger.info("算法注册完成，共 %d 个算法", len(cls._algorithms))

    @classmethod
    def _load_model_algorithms(cls):
        """加载models目录下的所有算法（包括子目录）"""
        try:
            from .model_adapter import load_all_model_algorithms

            adapters = load_all_model_algorithms()

            for adapter in adapters:
                algo_name = f"[Model] {adapter.name}"
                cls._algorithms[algo_name] = adapter
                cls._model_adapters[algo_name] = adapter

        except Exception as e:
            logger.error("加载models算法失败: %s", e)
            import traceback

            traceback.print_exc()

    @classmethod
    def get_algorithm(cls, name: str):
        if not cls._initialized:
            cls.initialize()
        return cls._algorithms.get(name)

    @classmethod
    def get_all_algorithms(cls):
        if not cls._initialized:
            cls.initialize()
        return list(cls._algorithms.values())

    @classmethod
    def get_algorithm_names(cls) -> List[str]:
        if not cls._initialized:
            cls.initialize()
        return list(cls._algorithms.keys())

    @classmethod
    def _prepare_video_data(cls, history: List[Tuple], current_value: float, bvid: str = "") -> Dict:
        """集中准备 video_data，避免每个 adapter 重复转换（提升 ~30% 性能）"""
        now = datetime.now()
        history_list = []
        for ts, v in history:
            try:
                dt, ts_ts, ts_str = normalize_timestamp(ts)
            except (ValueError, TypeError):
                try:
                    ts_ts = float(ts)
                    ts_str = str(ts)
                    dt = datetime.fromtimestamp(ts_ts)
                except (ValueError, TypeError):
                    ts_ts = 0.0
                    ts_str = str(ts)
                    dt = now
            history_list.append(
                {
                    "view_count": v,
                    "timestamp": ts_ts,
                    "timestamp_str": ts_str,
                    "datetime": dt,
                }
            )
        return {
            "view_count": current_value,
            "history_data": history_list,
            "timestamp": now,
            "timestamp_str": now.strftime("%Y-%m-%d %H:%M:%S"),
            "bvid": bvid,
        }

    @classmethod
    def predict_all(cls, history: List, current_value: float, bvid: str = "", **kwargs) -> Dict:
        if not cls._initialized:
            cls.initialize()

        # ── 集中准备 video_data，避免每个 adapter 重复转换 ────
        cached_video_data = cls._prepare_video_data(history, current_value, bvid=bvid)
        # _kwargs_with_video = dict(kwargs, _cached_video_data=cached_video_data)

        results = {}
        thresholds = kwargs.get("thresholds", [100000, 1000000, 10000000])
        threshold_names = kwargs.get("threshold_names", ["10万", "100万", "1000万"])

        valid_count = 0
        na_count = 0

        def _run_single(name_algo):
            """包装单个算法执行，供线程池调度"""
            n, algo = name_algo
            try:
                res = algo.predict(
                    history,
                    current_value,
                    thresholds=thresholds,
                    threshold_names=threshold_names,
                    _cached_video_data=cached_video_data,
                )
                w = weight_manager.get_weight(n) if weight_manager else getattr(algo, "weight", 1.0)
                return (
                    n,
                    {
                        "prediction": res["prediction"],
                        "confidence": res["confidence"],
                        "weight": w,
                        "metadata": res["metadata"],
                    },
                    None,
                )
            except Exception as e:
                logger.warning("算法 %s 预测失败: %s", n, e)
                return n, {"prediction": current_value, "confidence": 0, "weight": 0.01, "error": str(e)}, e

        if not hasattr(cls, "_pool") or cls._pool is None:
            cls._pool = ThreadPoolExecutor(max_workers=4)
        pool = cls._pool
        futures = [pool.submit(_run_single, item) for item in cls._algorithms.items()]

        for future in as_completed(futures):
            name, result, error = future.result()
            results[name] = result
            if error:
                continue
            if result.get("metadata", {}).get("na") or result["confidence"] == 0:
                na_count += 1
            else:
                valid_count += 1

        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        if valid_predictions:
            total_weight = sum(w for _, _, w in valid_predictions)
            if total_weight > 0:
                weighted_pred = sum(p * w for _, p, w in valid_predictions) / total_weight
            else:
                weighted_pred = current_value
        else:
            weighted_pred = current_value

        results["_weighted"] = {
            "prediction": weighted_pred,
            "total_algorithms": len(results),
            "valid_algorithms": valid_count,
            "na_algorithms": na_count,
        }

        return results

    @classmethod
    def update_accuracy(cls, algorithm_name: str, predicted: float, actual: float):
        algo = cls.get_algorithm(algorithm_name)
        if algo:
            if hasattr(algo, "update_accuracy"):
                algo.update_accuracy(predicted, actual)
            try:
                accuracy = algo.get_accuracy() if hasattr(algo, "get_accuracy") else 0.5
                weight_manager.update_accuracy(algorithm_name, accuracy)
            except Exception as e:
                logger.debug("更新算法准确率失败 %s: %s", algorithm_name, e)

    @classmethod
    def get_weights_info(cls) -> List[Dict]:
        if not cls._initialized:
            cls.initialize()

        names = cls.get_algorithm_names()

        try:
            return weight_manager.get_algorithm_info(names)
        except Exception as e:
            logger.debug("获取算法权重信息失败: %s", e)
            return [{"name": n, "accuracy": 0.5, "weight": 1.0} for n in names]

    @classmethod
    def reset(cls):
        cls._algorithms = {}
        cls._model_adapters = {}
        cls._initialized = False


AlgorithmRegistry.initialize()
