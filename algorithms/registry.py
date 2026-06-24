"""
算法注册器

集中管理所有预测算法。在首次使用时自动扫描 models/ 目录下的所有
算法文件（通过 ModelAlgorithmAdapter 桥接），并为每个视频运行
全量算法预测，产生带权重加权的集成预测结果（ensemble prediction）。
"""

from typing import Dict, List, Tuple
import logging
import math
from collections import OrderedDict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from .weight_manager import get_weight_manager

logger = logging.getLogger(__name__)

# ── LRU 缓存工具 ───────────────────────────────
_MAX_CACHE_SIZE = 200


class _LRUDict(OrderedDict):
    """固定容量的 LRU 字典，超出容量时自动淘汰最久未使用的条目。"""
    __slots__ = ("maxsize",)

    def __init__(self, maxsize=_MAX_CACHE_SIZE, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)

    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)

# ── 模块级单例：surge detector（避免每轮预测重复创建类） ──
_surge_detector = None


def _get_surge_detector():
    """获取 surge detector 模块级单例，延迟初始化。"""
    global _surge_detector
    if _surge_detector is None:
        from algorithms.base import BaseAlgorithm as BA

        class _SurgeDetector(BA):
            def predict(self, video_data=None, threshold=100000):
                pass

        _surge_detector = _SurgeDetector()
    return _surge_detector


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
    _history_lock = threading.Lock()
    _cache_lock = threading.Lock()  # 保护 _derived_cache 并发读写
    _derived_cache: _LRUDict = _LRUDict(maxsize=_MAX_CACHE_SIZE)

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
        view_values = [v for _, v in history]

        for ts, v in history:
            if isinstance(ts, datetime):
                ts_ts = ts.timestamp()
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                try:
                    dt = datetime.fromisoformat(str(ts))
                    ts_ts = dt.timestamp()
                    ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    try:
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

        # ── 派生特征 ──────────────────────────
        n = len(view_values)
        cache_key = (bvid, n, current_value)
        with cls._cache_lock:
            derived = cls._derived_cache.get(cache_key)
        if derived is None:
            derived = {}
            # ── 用 numpy float32 加速，精度足够 ──
            import numpy as np
            v_arr = np.array(view_values, dtype=np.float32)
            ts_arr = np.array([h["timestamp"] for h in history_list], dtype=np.float32)

            if n >= 2:
                diffs = np.diff(v_arr).astype(np.float32)
                derived["velocity_mean"] = float(np.mean(diffs))
                derived["velocity_std"] = float(np.std(diffs)) if n > 2 else 0.0
                derived["velocity_cv"] = derived["velocity_std"] / max(abs(derived["velocity_mean"]), 1e-10)
                derived["velocity_median"] = float(np.median(diffs))
                # ── 预计算 velocity（polyfit），消除 100+ 算法各自重复计算 ──
                if n >= 5:
                    k = min(10, n)
                    slope = np.polyfit(ts_arr[-k:], v_arr[-k:], 1)[0]
                    derived["velocity_polyfit"] = max(0.0, float(slope / 3600.0))
                elif n >= 2:
                    dt = ts_arr[-1] - ts_arr[-2]
                    if dt > 0:
                        derived["velocity_polyfit"] = max(
                            0.0, float((v_arr[-1] - v_arr[-2]) / max(dt, 1e-8) * 3600.0)
                        )
                    else:
                        derived["velocity_polyfit"] = 0.0
                else:
                    derived["velocity_polyfit"] = 0.0
                # ── 加速度 / 急动度 ──
                if n >= 3:
                    accels = np.diff(diffs)
                    derived["acceleration"] = float(np.mean(accels)) if len(accels) > 0 else 0.0
                if n >= 4 and len(diffs) >= 3:
                    accels = np.diff(diffs)
                    jerks = np.diff(accels) if len(accels) >= 2 else np.array([0.0])
                    derived["jerk"] = float(np.mean(jerks)) if len(jerks) > 0 else 0.0
            if n >= 5:
                derived["velocity_ratio"] = derived.get("velocity_mean", 0) / max(v_arr[-min(5, n)], 1)
            # ── 滞后特征 ──────────────────────────
            if n >= 2:
                derived["lag_1"] = view_values[-1] - view_values[-2]
            if n >= 4:
                derived["lag_3"] = view_values[-1] - view_values[-4] if n >= 4 else 0
            if n >= 8:
                derived["lag_7"] = view_values[-1] - view_values[-8] if n >= 8 else 0
            # ── 滚动统计（float32 向量化） ──
            for win in [3, 7, 14]:
                if n >= win:
                    win_vals = v_arr[-win:]
                    derived[f"roll_mean_{win}"] = float(np.mean(win_vals))
                    derived[f"roll_std_{win}"] = float(np.std(win_vals))
                    derived[f"roll_cv_{win}"] = derived[f"roll_std_{win}"] / max(derived[f"roll_mean_{win}"], 1e-10)
            with cls._cache_lock:
                cls._derived_cache[cache_key] = derived

        return {
            "view_count": current_value,
            "history_data": history_list,
            "_sorted": True,                # history_list 已按时间升序，算法无需再次排序
            "_velocity": derived.get("velocity_polyfit", 0.0),  # 预计算速度，避免各算法重复 compute
            "velocity": derived.get("velocity_polyfit", 0.0),    # 兼容直接访问
            "timestamp": now,
            "timestamp_str": now.strftime("%Y-%m-%d %H:%M:%S"),
            "bvid": bvid,
            "hour_of_day": now.hour,
            "day_of_week": now.weekday(),
            "is_weekend": 1 if now.weekday() >= 5 else 0,
            "data_points": len(history_list),
            "derived_features": derived,
        }

    @classmethod
    def _merge_history(cls, memory_history: List, db_history: List) -> List:
        """合并内存历史与 DB 全量历史，按时间戳去重。

        DB 历史可覆盖更早的区间，确保长期期模型获得完整数据。
        """
        from utils.time_utils import safe_datetime, normalize_timestamp

        def _ts_str(ts_val):
            try:
                return normalize_timestamp(ts_val)[2]
            except Exception:
                return str(ts_val)

        existing = {_ts_str(h[0]) for h in memory_history}
        merged = list(memory_history)
        for h in db_history:
            if _ts_str(h[0]) not in existing:
                merged.append(h)
                existing.add(_ts_str(h[0]))

        def _ts_dt(t):
            try:
                return safe_datetime(t)
            except Exception:
                from datetime import datetime as dt
                return dt.min

        merged.sort(key=lambda x: _ts_dt(x[0]))
        return merged

    @classmethod
    def _run_parallel_predictions(cls, history, current_value, bvid, cached_video_data, thresholds, threshold_names):
        results = {}
        valid_count = 0
        na_count = 0

        # 预取全部权重（避免 100+ 线程争抢 WeightManager._lock）
        _weights = {name: get_weight_manager().get_weight(name) for name in cls._algorithms}

        def _run_single(name_algo):
            n, algo = name_algo
            try:
                import warnings
                import numpy as np
                # 抑制 polyfit/LAPACK 数值稳定性噪音警告（数据不足时常见）
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")
                    with np.errstate(invalid="ignore", divide="ignore"):
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
                w = _weights.get(n, 1.0)
                pred = res["prediction"]
                meta = res.get("metadata", {})
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
                logger.warning(
                    "[%s] 视频(%s),使用'底模'预测失败 降级原因: %s",
                    n, bvid, e,
                )
                return n, {"prediction": current_value, "confidence": 0, "weight": 0.01, "error": str(e)}, e

        with cls._pool_lock:
            if cls._pool is None:
                from utils.memory_guard import get_safe_workers
                workers = get_safe_workers()
                cls._pool = ThreadPoolExecutor(max_workers=workers)
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

        return results, valid_count, na_count

    @classmethod
    def _apply_window_weights(cls, results, valid_predictions, current_value):
        if len(valid_predictions) < 3:
            return

        with cls._history_lock:
            _window_weight_history = getattr(cls, "_window_weight_history", {})
            cls._window_weight_history = _window_weight_history

            decay = 0.85
            for name, pred, w in valid_predictions:
                rel_dev = abs(pred - current_value) / max(current_value, 1)
                hist = _window_weight_history.get(name, [])
                hist.append(rel_dev)
                if len(hist) > 10:
                    hist = hist[-10:]
                _window_weight_history[name] = hist

                window_error = (
                    sum(h * (decay ** (len(hist) - i)) for i, h in enumerate(hist))
                    / max(sum(decay ** (len(hist) - i) for i in range(len(hist))), 1e-10)
                )
                window_factor = max(0.2, 1.0 / (1.0 + window_error * 5))
                results[name]["weight"] = w * (0.5 + 0.5 * window_factor)

    @classmethod
    def _detect_surge_from_cached(cls, cached_video_data: Dict) -> Dict:
        """从缓存的 video_data 检测是否处于大推流状态。

        使用 BaseAlgorithm.detect_surge() 进行多窗口速度分析。
        结果被缓存到类变量中以避免重复计算。

        Returns:
            surge_info dict，同 BaseAlgorithm.detect_surge() 返回值
        """
        try:
            from algorithms.base import BaseAlgorithm as BA

            bvid = cached_video_data.get("bvid", "")
            n_points = len(cached_video_data.get("history_data", []))
            cache_key = (bvid, n_points, cached_video_data.get("view_count", 0))

            with cls._history_lock:
                if not hasattr(cls, "_surge_cache"):
                    cls._surge_cache = _LRUDict(maxsize=100)
                if cache_key in cls._surge_cache:
                    return cls._surge_cache[cache_key]

            # 复用模块级单例，避免每次创建新类和实例
            detector = _get_surge_detector()
            surge_info = detector.detect_surge(cached_video_data)

            with cls._history_lock:
                cls._surge_cache[cache_key] = surge_info

            return surge_info
        except Exception as e:
            logger.debug("_detect_surge_from_cached 失败: %s", e)
            return {"is_surging": False, "surge_magnitude": 1.0}

    @classmethod
    def _apply_coherence_weights(cls, results, valid_predictions):
        """基于算法间共识度（coherence）调整权重。

        核心思想：偏离中位数越远的算法其权重应越低。
        但在推流场景下适当放宽此约束，允许部分算法预测更高值。
        """
        if len(valid_predictions) < 3:
            return

        values = sorted(p for _, p, _ in valid_predictions)
        median_val = values[len(values) // 2]
        if not median_val > 0:
            return

        # ── 检测是否处于推流状态 ──────────────────
        is_surging = False
        surge_mag = 1.0
        try:
            # 用预测值离散度作为推流代理指标
            # 推流时算法预测值差异大（部分算法检测到激增，部分未检测到）
            if len(values) >= 5:
                mean_v = sum(values) / len(values)
                if mean_v > 0:
                    cv = (sum((v - mean_v) ** 2 for v in values) / len(values)) ** 0.5 / mean_v
                    # CV > 0.3 提示算法间存在显著分歧 → 可能推流
                    if cv > 0.3:
                        is_surging = True
                        surge_mag = min(5.0, 1.0 + cv * 3)
        except Exception as e:
            logger.debug("推流检测计算失败: %s", e)

        for name, pred, w in valid_predictions:
            coherence = min(pred, median_val) / max(pred, median_val)
            # 推流时放宽一致性惩罚：让高预测算法保留更多权重
            if is_surging:
                coherence_factor = 0.8 + 0.2 * coherence
            else:
                coherence_factor = 0.5 + 0.5 * coherence
            results[name]["coherence"] = round(coherence, 4)
            results[name]["weight"] = w * coherence_factor

    @classmethod
    def _compute_ensemble(cls, results, valid_predictions, current_value, valid_count, na_count):
        if valid_predictions:
            total_weight = sum(w for _, _, w in valid_predictions)
            if total_weight > 0:
                weighted_pred = sum(p * w for _, p, w in valid_predictions) / total_weight
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

        results["_weighted"] = {
            "prediction": weighted_pred,
            "total_algorithms": len(results),
            "valid_algorithms": valid_count,
            "na_algorithms": na_count,
            "ensemble_confidence": round(ensemble_conf, 4),
        }

        try:
            from .conformal import get_conformal_predictor

            cp = get_conformal_predictor()
            interval = cp.predict_interval(weighted_pred)
            results["_weighted"]["prediction_interval"] = interval
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        return weighted_pred

    @classmethod
    def predict_all(cls, history: List, current_value: float, bvid: str = "",
                    db_history: List = None, **kwargs) -> Dict:
        """对所有注册算法发起并行预测，返回加权集成结果。

        Args:
            history: [(timestamp, view_count), ...] 格式的历史数据（内存缓冲）
            current_value: 当前播放量
            bvid: 视频 BV 号（仅用于日志）
            db_history: [(timestamp, view_count), ...] 从 DB 读取的全量历史，与内存
                        history 合并后送入算法，确保长期期模型获得完整数据
            **kwargs: 可包含 thresholds / threshold_names

        Returns:
            dict: 每个算法 name -> {prediction, confidence, weight, ...}
                   以及 "_weighted" 键存储集成预测结果
        """
        if not cls._initialized:
            cls.initialize()

        if db_history:
            history = cls._merge_history(history, db_history)

        cached_video_data = cls._prepare_video_data(history, current_value, bvid=bvid)

        thresholds = kwargs.get("thresholds", [100000, 1000000, 10000000])
        threshold_names = kwargs.get("threshold_names", ["10万", "100万", "1000万"])

        results, valid_count, na_count = cls._run_parallel_predictions(
            history, current_value, bvid, cached_video_data, thresholds, threshold_names
        )

        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        cls._apply_window_weights(results, valid_predictions, current_value)

        cls._apply_coherence_weights(results, valid_predictions)

        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        weighted_pred = cls._compute_ensemble(results, valid_predictions, current_value, valid_count, na_count)

        # ── 推流校正：检测到大推流时对集成预测值进行衰减调整 ──
        surge_info = cls._detect_surge_from_cached(cached_video_data)
        if surge_info.get("is_surging"):
            surge_mag = surge_info["surge_magnitude"]
            surge_type = surge_info["surge_type"]
            surge_adj_vel = surge_info.get("adjusted_velocity", 0)

            # 计算推流校正因子
            # 核心思路：推流期间的增速不可持续，需要向下修正预测值
            if surge_adj_vel > 0:
                raw_velocity = max(surge_info.get("surge_velocity", 0), 0.01)
                correction_ratio = surge_adj_vel / raw_velocity
                correction_ratio = max(0.4, min(1.0, correction_ratio))
            else:
                correction_ratio = 0.6 if surge_type == "strong" else 0.8

            # 对超出当前值的增长部分应用校正
            growth = weighted_pred - current_value
            if growth > 0:
                corrected_growth = growth * correction_ratio
                corrected_pred = current_value + corrected_growth
                results["_weighted"]["prediction"] = max(current_value, corrected_pred)
                results["_weighted"]["surge_correction_applied"] = True
                results["_weighted"]["surge_magnitude"] = surge_mag
                results["_weighted"]["surge_type"] = surge_type
                results["_weighted"]["correction_ratio"] = round(correction_ratio, 3)
                weighted_pred = results["_weighted"]["prediction"]

        interval_width = 0
        if results["_weighted"].get("prediction_interval"):
            try:
                interval_width = round(results["_weighted"]["prediction_interval"].get("interval_width_ratio", 0) * 100)
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
            return [
                {
                    "name": n, "accuracy": 0.5, "final_weight": 1.0,
                    "ml_weight": 1.0, "user_weight": None,
                    "is_customized": False, "samples": 0,
                }
                for n in names
            ]

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
        cls._derived_cache = _LRUDict(maxsize=_MAX_CACHE_SIZE)
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
