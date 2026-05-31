"""
算法注册器

集中管理所有预测算法。在首次使用时自动扫描 models/ 目录下的所有
算法文件（通过 ModelAlgorithmAdapter 桥接），并为每个视频运行
全量算法预测，产生带权重加权的集成预测结果（ensemble prediction）。
"""

from typing import Dict, List, Tuple
import logging
import math
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from .weight_manager import get_weight_manager

logger = logging.getLogger(__name__)


class AlgorithmRegistry:
    """算法注册器 —— 单例风格的类方法容器。

    职责：
        - 延迟初始化、自动发现 models/ 下的算法
        - 为每个视频发起并行预测，收集结果
        - 基于算法间共识度（coherence）调整权重
        - 输出加权集成预测 + 保形预测区间
    """

    _algorithms: Dict = {}
    _initialized = False
    _model_adapters = {}
    _pool_lock = threading.Lock()
    _pool = None
    _init_lock = threading.Lock()

    @classmethod
    def initialize(cls):
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
    def _load_model_algorithms(cls):
        """加载 models/ 目录下的所有算法。

        委托给 model_adapter.load_all_model_algorithms() 扫描文件系统，
        将每个算法包装为 ModelAlgorithmAdapter 后存入内部字典。
        """
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
        for key, adapter in cls._algorithms.items():
            raw_id = getattr(adapter, "algorithm_id", None)
            if raw_id is None:
                raw_id = getattr(adapter, "algo", None)
            if hasattr(raw_id, "algorithm_id"):
                raw_id = raw_id.algorithm_id
            if raw_id == algorithm_id:
                return key
        return algorithm_id

    @classmethod
    def get_all_algorithms(cls):
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
    def _prepare_video_data(cls, history: List[Tuple], current_value: float, bvid: str = "") -> Dict:
        """将 (timestamp, view_count) 历史元组统一转为 video_data 字典。

        避免每个 adapter 重复做同样的类型转换，集中处理可提升约 30% 性能。
        """
        now = datetime.now()
        history_list = []
        for ts, v in history:
            if isinstance(ts, datetime):
                ts_ts = ts.timestamp()
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                try:
                    # 尝试 ISO 格式字符串解析（如 2026-04-21T23:48:17.189827）
                    dt = datetime.fromisoformat(str(ts))
                    ts_ts = dt.timestamp()
                    ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    try:
                        # 回退：将 ts 直接视为 float（Unix 时间戳）
                        ts_ts = float(ts)
                        ts_str = str(ts)
                    except (ValueError, TypeError):
                        ts_ts = 0.0
                        ts_str = str(ts)
            history_list.append(
                {
                    "view_count": v,
                    "timestamp": ts_ts,
                    "timestamp_str": ts_str,
                    "datetime": ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts_ts),
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
        """对所有注册算法发起并行预测，返回加权集成结果。

        Args:
            history: [(timestamp, view_count), ...] 格式的历史数据
            current_value: 当前播放量
            bvid: 视频 BV 号（仅用于日志）
            **kwargs: 可包含 thresholds / threshold_names

        Returns:
            dict: 每个算法 name -> {prediction, confidence, weight, ...}
                 以及 "_weighted" 键存储集成预测结果
        """
        if not cls._initialized:
            cls.initialize()

        # ── 集中准备 video_data，避免每个 adapter 重复转换 ────
        cached_video_data = cls._prepare_video_data(history, current_value, bvid=bvid)

        results = {}
        thresholds = kwargs.get("thresholds", [100000, 1000000, 10000000])
        threshold_names = kwargs.get("threshold_names", ["10万", "100万", "1000万"])

        valid_count = 0
        na_count = 0

        def _run_single(name_algo):
            """在线程池中执行单个算法的预测包装。

            优先调用适配器的 predict_dict() 接口（接受 dict 参数）；
            否则回退到原始 predict() 接口。
            """
            n, algo = name_algo
            try:
                # 如果适配器有 predict_dict 方法，走统一的 dict 参数路径
                if hasattr(algo, "predict_dict"):
                    res = algo.predict_dict(
                        history,
                        current_value,
                        thresholds=thresholds,
                        threshold_names=threshold_names,
                        _cached_video_data=cached_video_data,
                    )
                else:
                    res = algo.predict(
                        history,
                        current_value,
                        thresholds=thresholds,
                        threshold_names=threshold_names,
                        _cached_video_data=cached_video_data,
                    )
                w = get_weight_manager().get_weight(n)
                pred = res["prediction"]
                meta = res.get("metadata", {})
                model_source = meta.get("model_source", "底模")
                logger.debug(
                    "[%s] 视频(%s),使用'%s'预测成功 预测结果: %.0f",
                    n, bvid, model_source, pred,
                )
                return (
                    n,
                    {
                        "prediction": pred,
                        "confidence": res["confidence"],
                        "weight": w,
                        "predicted_hours": res.get("predicted_hours", 0),
                        "metadata": meta,
                    },
                    None,
                )
            except Exception as e:
                # 单个算法失败不阻断整体，降级返回保守值
                logger.warning(
                    "[%s] 视频(%s),使用'底模'预测失败 降级原因: %s",
                    n, bvid, e,
                )
                return n, {"prediction": current_value, "confidence": 0, "weight": 0.01, "error": str(e)}, e

        # 使用线程池并发运行所有算法（最多 4 个 worker）
        with cls._pool_lock:
            if cls._pool is None:
                cls._pool = ThreadPoolExecutor(max_workers=4)
            pool = cls._pool
        futures = [pool.submit(_run_single, item) for item in cls._algorithms.items()]

        for future in as_completed(futures):
            name, result, error = future.result()
            results[name] = result
            if error:
                continue
            # 统计有效 / NA 结果数量
            if result.get("metadata", {}).get("na") or result["confidence"] == 0:
                na_count += 1
            else:
                valid_count += 1

        # 筛选出有权重且预测值 > 0 的有效结果
        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        # ── 基于算法间共识度（coherence）调整权重 ────────────
        # 核心思想：偏离中位数越远的算法其权重应越低
        if len(valid_predictions) >= 3:
            values = sorted(p for _, p, _ in valid_predictions)
            median_val = values[len(values) // 2]
            if median_val > 0:
                for name, pred, w in valid_predictions:
                    coherence = min(pred, median_val) / max(pred, median_val)
                    coherence_factor = 0.5 + 0.5 * coherence
                    results[name]["coherence"] = round(coherence, 4)
                    results[name]["weight"] = w * coherence_factor

        # 重新读取调整后的有效预测
        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        # ── 加权集成预测 ──────────────────────────────
        if valid_predictions:
            total_weight = sum(w for _, _, w in valid_predictions)
            if total_weight > 0:
                weighted_pred = sum(p * w for _, p, w in valid_predictions) / total_weight
                # 集成置信度：基于预测离散度（CV 越低 → 共识越高 → 置信度越高）
                valid_vals = [p for _, p, _ in valid_predictions]
                mean_v = sum(valid_vals) / len(valid_vals)
                if mean_v > 0:
                    variance = sum((p - mean_v) ** 2 for p in valid_vals) / len(valid_vals)
                    cv = (variance ** 0.5) / mean_v
                    ensemble_conf = max(0.0, min(1.0, math.exp(-cv * 2)))
                else:
                    ensemble_conf = 0.0
            else:
                weighted_pred = current_value
                ensemble_conf = 0.0
        else:
            weighted_pred = current_value
            ensemble_conf = 0.0

        # 存储集成结果
        results["_weighted"] = {
            "prediction": weighted_pred,
            "total_algorithms": len(results),
            "valid_algorithms": valid_count,
            "na_algorithms": na_count,
            "ensemble_confidence": round(ensemble_conf, 4),
        }

        # ── 保形预测区间（Conformal Prediction）─────────
        try:
            from .conformal import get_conformal_predictor

            cp = get_conformal_predictor()
            interval = cp.predict_interval(weighted_pred)
            results["_weighted"]["prediction_interval"] = interval
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        interval_width = 0
        if results["_weighted"].get("prediction_interval"):
            try:
                interval_width = round(interval.get("interval_width_ratio", 0) * 100)
            except Exception:
                interval_width = 0
        logger.info(
            "[%s] 综合预测: %.0f (有效 %d/%d, 区间 ±%d%%)",
            bvid, weighted_pred, valid_count, len(results) - 1, interval_width,
        )

        return results

    @classmethod
    def update_accuracy(cls, algorithm_name: str, predicted: float, actual: float):
        """更新单个算法的准确率记录并同步到权重管理器。"""
        algo = cls.get_algorithm(algorithm_name)
        if algo:
            if hasattr(algo, "update_accuracy"):
                algo.update_accuracy(predicted, actual)
            try:
                accuracy = algo.get_accuracy() if hasattr(algo, "get_accuracy") else 0.5
                get_weight_manager().update_accuracy(algorithm_name, accuracy)
            except Exception as e:
                logger.debug("更新算法准确率失败 %s: %s", algorithm_name, e)

    @classmethod
    def update_ensemble_accuracy(cls, predicted: float, actual: float):
        """用集成预测值与实际值更新保形预测器的校准集。"""
        try:
            from .conformal import get_conformal_predictor

            get_conformal_predictor().update(predicted, actual)
        except Exception as e:
            logger.debug("更新集成预测准确率失败: %s", e)

    @classmethod
    def get_weights_info(cls) -> List[Dict]:
        """获取所有算法的权重信息（供 UI 展示）。"""
        if not cls._initialized:
            cls.initialize()

        names = cls.get_algorithm_names()

        try:
            return get_weight_manager().get_algorithm_info(names)
        except Exception as e:
            logger.debug("获取算法权重信息失败: %s", e)
            return [{"name": n, "accuracy": 0.5, "final_weight": 1.0, "ml_weight": 1.0, "user_weight": None, "is_customized": False, "samples": 0} for n in names]

    @classmethod
    def shutdown(cls):
        """关闭线程池，释放资源（应用退出时调用）。"""
        with cls._pool_lock:
            pool = cls._pool
            cls._pool = None
        if pool is not None:
            pool.shutdown(wait=False)

    @classmethod
    def reset(cls):
        """重置注册器：清空所有已注册算法并关闭线程池。"""
        cls.shutdown()
        cls._algorithms = {}
        cls._model_adapters = {}
        cls._initialized = False

    @classmethod
    def get_trainable_info(cls) -> List[Dict]:
        """获取所有支持训练的算法的检查点信息。"""
        from algorithms.training.checkpoint_manager import CheckpointManager
        if not cls._initialized:
            cls.initialize()
        result = []
        for aid, adapter in cls._algorithms.items():
            build_model_fn = getattr(adapter, "build_model", None)
            if build_model_fn is None:
                continue
            ckpt = CheckpointManager(aid)
            versions = ckpt.list_versions()
            active = ckpt.active_version()
            result.append({
                "algorithm_id": aid,
                "name": getattr(adapter, "name", aid),
                "category": getattr(adapter, "category", ""),
                "has_ckpt": ckpt.has_checkpoint(),
                "active_version": active or "",
                "version_count": len(versions),
            })
        return result

    @classmethod
    def get_trainable_algorithms(cls) -> List:
        """获取所有支持训练的算法列表（供训练调度使用）。"""
        if not cls._initialized:
            cls.initialize()
        result = []
        for aid, adapter in cls._algorithms.items():
            build_model_fn = getattr(adapter, "build_model", None)
            if build_model_fn is None:
                continue
            result.append((aid, adapter.algo if hasattr(adapter, "algo") else adapter, adapter))
        return result


# 不再模块级初始化，改为按需（Lazy）初始化 —— 所有公开方法都已检查 _initialized 标志
