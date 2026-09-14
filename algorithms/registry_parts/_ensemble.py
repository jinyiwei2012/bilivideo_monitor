"""EnsembleMixin extracted from algorithms.registry."""

import threading
import importlib
from typing import Any, cast, Dict, List, Optional, Set, Tuple, TYPE_CHECKING
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from ._shared import _LRUDict, _get_surge_detector, get_weight_manager, logger
from ..base import BaseAlgorithm


class EnsembleMixin:
    _algorithms: Dict[str, BaseAlgorithm]
    _pool_lock: threading.RLock
    _pool: Optional[ThreadPoolExecutor]
    _history_lock: threading.Lock
    _window_weight_history: Dict[str, List[float]]
    _surge_cache: _LRUDict
    _initialized: bool

    if TYPE_CHECKING:

        @classmethod
        def initialize(cls) -> None:
            raise NotImplementedError

        @classmethod
        def _prepare_video_data(cls, history: List, current_value: float, bvid: str = "") -> Dict:
            raise NotImplementedError

        @classmethod
        def _record_ensemble_feedback(cls, bvid: str, current_value: float) -> None:
            raise NotImplementedError

        # ── ScheduleMixin 提供（重算法降频调度）──
        @classmethod
        def _should_run_heavy(cls, bvid: str, anchor_idx: Optional[int], cached_video_data: Dict) -> Tuple[bool, str]:
            raise NotImplementedError

        @classmethod
        def _heavy_names(cls) -> Set[str]:
            raise NotImplementedError

        @classmethod
        def _inject_reused(
            cls,
            bvid: str,
            results: Dict,
            current_value: float,
            thresholds: List,
            threshold_names: List,
            anchor_idx: Optional[int],
        ) -> List[str]:
            raise NotImplementedError

        @classmethod
        def _record_sched_stat(cls, key: str) -> None:
            raise NotImplementedError

        @classmethod
        def _store_heavy(cls, bvid: str, results: Dict, anchor_idx: Optional[int]) -> None:
            raise NotImplementedError

        @staticmethod
        def _is_reused(result: Any) -> bool:
            raise NotImplementedError

    @classmethod
    def _merge_history(cls, memory_history: List, db_history: List) -> List:
        """合并内存历史与 DB 全量历史，按时间戳去重。

        DB 历史可覆盖更早的区间，确保长期期模型获得完整数据。
        """
        time_utils = importlib.import_module("utils.time_utils")
        safe_datetime = time_utils.safe_datetime
        normalize_timestamp = time_utils.normalize_timestamp

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
    def _to_registry_result(cls, prediction_result, current_value, thresholds, threshold_names, weight) -> Dict:
        """把算法返回的 PredictionResult 转换为 registry 标准结果 dict。

        语义: prediction = 下一短期窗口(75s)的预测播放量; metadata 含阈值预测明细。
        """
        pred_hours = prediction_result.predicted_hours
        confidence = prediction_result.confidence
        velocity = getattr(prediction_result, "current_velocity", 0)

        SHORT_TERM_SECONDS = 75  # 与 DEFAULT_INTERVAL 对齐
        short_hours = SHORT_TERM_SECONDS / 3600.0
        if velocity > 0:
            prediction = current_value + velocity * short_hours
        elif pred_hours == float("inf") or pred_hours < 0:
            prediction = current_value + current_value * 0.01
        else:
            if pred_hours > 0:
                # anchor = 首个未达阈值（算法预测的真实对象），非固定 thresholds[0]
                _anchor_t = next((t for t in thresholds if current_value < t), thresholds[0])
                avg_velocity = (_anchor_t - current_value) / max(pred_hours, 1) if _anchor_t > current_value else 0
                prediction = current_value + avg_velocity * short_hours
            else:
                prediction = current_value * 1.01

        threshold_preds = []
        MIN_VELOCITY = 1e-8  # ≈ 1 播放/11,000 年, 避免 predicted_seconds 溢出 SQLite INTEGER
        for thresh, name_th in zip(thresholds, threshold_names):
            if thresh > current_value:
                hours_needed = (thresh - current_value) / velocity if velocity > MIN_VELOCITY else float("inf")
                if hours_needed != float("inf"):
                    threshold_preds.append(
                        {
                            "threshold": thresh,
                            "name": name_th,
                            "periods_needed": int(hours_needed),
                            "minutes": hours_needed * 60,
                        }
                    )

        return {
            "prediction": max(prediction, current_value),
            "confidence": min(max(confidence, 0), 1),
            "weight": weight,
            "predicted_hours": pred_hours,
            "metadata": {
                "predicted_hours": pred_hours,
                "velocity": velocity,
                "threshold_predictions": threshold_preds,
                "data_points": 0,
            },
        }

    @classmethod
    def _make_na_result(cls, current_value, weight) -> Dict:
        """返回 N/A 结果 (保守估计 ~1%/小时 增长)。"""
        short_hours = 75 / 3600.0
        return {
            "prediction": current_value + current_value * 0.01 * short_hours,
            "confidence": 0.3,
            "weight": weight,
            "predicted_hours": 0,
            "metadata": {"na": True, "threshold_predictions": []},
        }

    @staticmethod
    def _is_valid_result(result: Dict) -> bool:
        """结果是否计入「有效算法」（非 N/A 且置信度 > 0）。"""
        return not (result.get("metadata", {}).get("na") or result.get("confidence", 0) == 0)

    @classmethod
    def _collect_future_results(cls, futures, results: Dict) -> Tuple[int, int]:
        """回收线程池结果写入 results，返回 (有效数, NA 数)。"""
        valid_count = 0
        na_count = 0
        for future in as_completed(futures):
            name, result, error = future.result()
            results[name] = result
            if error:
                continue
            if cls._is_valid_result(result):
                valid_count += 1
            else:
                na_count += 1
        return valid_count, na_count

    @classmethod
    def _count_results(cls, results: Dict, names: List[str]) -> Tuple[int, int]:
        """统计指定算法名的 (有效数, NA 数)。"""
        valid_count = 0
        na_count = 0
        for name in names:
            if cls._is_valid_result(results[name]):
                valid_count += 1
            else:
                na_count += 1
        return valid_count, na_count

    @classmethod
    def _run_parallel_predictions(
        cls,
        current_value,
        bvid,
        cached_video_data,
        thresholds,
        threshold_names,
        anchor_threshold=None,
        anchor_idx=None,
    ):
        results: Dict[str, Any] = {}
        valid_count = 0
        na_count = 0

        # 重算法降频：无事件轮次跳过重算法，改用上一轮结果按当前播放量重投影
        run_heavy, sched_reason = cls._should_run_heavy(bvid, anchor_idx, cached_video_data)
        skip_names = set() if run_heavy else cls._heavy_names()
        cls._record_sched_stat("run_rounds" if run_heavy else "skip_rounds")

        # 预取全部权重（避免 100+ 线程争抢 WeightManager._lock）
        _weights = {name: get_weight_manager().get_weight(name) for name in cls._algorithms}

        # B2: 在线学习全局分数 → 权重修正因子（跨视频聚合的算法级实时表现）
        # 注意 tracker key 存的是裸算法名(带"[Model] "前缀)，registry key 同名；
        # 分数 rel 落在 1.0 附近，clip [0.3, 3.0] 防单算法过冲
        try:
            from ..online_learner import get_online_learner

            _ol_scores = get_online_learner().get_global_algorithm_scores(min_samples=3)
            if _ol_scores:
                for _name in _weights:
                    _base = _name
                    _rel = _ol_scores.get(_base)
                    if _rel is None:
                        continue
                    _factor = max(0.3, min(3.0, _rel))
                    _weights[_name] = _weights.get(_name, 1.0) * _factor
        except Exception as e:
            logger.debug("在线学习权重修正跳过: %s", e)

        def _run_single(name_algo):
            n, algo = name_algo
            try:
                import warnings
                import numpy as np

                # 抑制 polyfit/LAPACK 数值稳定性噪音警告（数据不足时常见）
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")
                    with np.errstate(invalid="ignore", divide="ignore"):
                        # anchor 阈值：当前值之上的首个未达目标（原固定 thresholds[0]，
                        # 视频超过 10万 后算法的 predicted_hours 全部退化）
                        prediction_result = algo.predict(cached_video_data, anchor_threshold or thresholds[0])
                w = _weights.get(n, 1.0)
                if prediction_result is None:
                    res = cls._make_na_result(current_value, w)
                else:
                    res = cls._to_registry_result(prediction_result, current_value, thresholds, threshold_names, w)
                return (
                    n,
                    {
                        "prediction": res["prediction"],
                        "confidence": res["confidence"],
                        "weight": res["weight"],
                        "predicted_hours": res.get("predicted_hours", 0),
                        "metadata": res.get("metadata", {}),
                    },
                    None,
                )
            except Exception as e:
                logger.warning(
                    "[%s] 视频(%s),使用'底模'预测失败 降级原因: %s",
                    n,
                    bvid,
                    e,
                )
                return n, {"prediction": current_value, "confidence": 0, "weight": 0.01, "error": str(e)}, e

        with cls._pool_lock:
            if cls._pool is None:
                memory_guard = importlib.import_module("utils.memory_guard")
                workers = memory_guard.get_safe_workers()
                cls._pool = ThreadPoolExecutor(max_workers=workers)
            pool = cls._pool
        items = [(name, algo) for name, algo in cls._algorithms.items() if name not in skip_names]
        futures = [pool.submit(_run_single, item) for item in items]

        valid_count, na_count = cls._collect_future_results(futures, results)

        # 降频轮次：注入上一轮重算法结果（按当前播放量重投影）并计入有效/NA 统计
        if skip_names:
            reused = cls._inject_reused(bvid, results, current_value, thresholds, threshold_names, anchor_idx)
            r_valid, r_na = cls._count_results(results, reused)
            valid_count += r_valid
            na_count += r_na
            if reused:
                cls._record_sched_stat("reuse_rounds")
            logger.debug("[%s] 重算法降频(%s): 实算 %d 个, 复用 %d 个", bvid, sched_reason, len(items), len(reused))

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
                if cls._is_reused(results.get(name)):
                    # 降频复用项：不计入「算法表现」历史，否则缓存年龄会被当成算法连续表现
                    continue
                rel_dev = abs(pred - current_value) / max(current_value, 1)
                hist = _window_weight_history.get(name, [])
                hist.append(rel_dev)
                if len(hist) > 10:
                    hist = hist[-10:]
                _window_weight_history[name] = hist

                window_error = sum(h * (decay ** (len(hist) - i)) for i, h in enumerate(hist)) / max(
                    sum(decay ** (len(hist) - i) for i in range(len(hist))), 1e-10
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

            bvid = cached_video_data.get("bvid", "")
            n_points = len(cached_video_data.get("history_data", []))
            cache_key = (bvid, n_points, cached_video_data.get("view_count", 0))

            with cls._history_lock:
                if not hasattr(cls, "_surge_cache"):
                    cls._surge_cache = _LRUDict(maxsize=100)
                if cache_key in cls._surge_cache:
                    return cast(Dict[Any, Any], cls._surge_cache[cache_key])

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
        except Exception as e:
            logger.debug("推流检测计算失败: %s", e)

        for name, pred, w in valid_predictions:
            if cls._is_reused(results.get(name)):
                # 降频复用项：沿用缓存内的最终权重，不重复套一次共识折扣
                continue
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
                    cv = (variance**0.5) / mean_v
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
            from ..conformal import get_conformal_predictor

            cp = get_conformal_predictor()
            interval = cp.predict_interval(weighted_pred)
            results["_weighted"]["prediction_interval"] = interval
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        return weighted_pred

    @classmethod
    def _compute_log_eta(cls, results, current_value, thresholds, threshold_names, anchor_idx):
        """log-ETA 集成：算法对 anchor 阈值的 predicted_hours → log 空间加权中位数。

        背景：各算法的 current_velocity 高度共享 polyfit（D1），75s prediction 几乎同质，
        但 predicted_hours（到达目标阈值的小时数）编码了曲线/模型差异（实测 p10~p90 近 3 倍）。
        此前 hours 只进 metadata 不参与集成 —— 此处让模型多样性真正进入 ETA 决策。

        权重使用权重计算后的 results[name]["weight"]（已含 window + coherence 修正），
        加权中位数对离群 hours 稳健，log 空间避免长尾小时数主导。

        Returns:
            dict: {"eta_hours": ..., "eta_log_cv": ..., "eta_n": ...} 写入 _weighted.eta
        """
        hours_w = cls._collect_log_hours(results)
        if len(hours_w) < 3:
            return None

        total_w = sum(w for w, _ in hours_w)
        median_log = cls._weighted_median_log(hours_w, total_w)
        mean_log = sum(w * lh for w, lh in hours_w) / total_w
        var_log = sum(w * (lh - mean_log) ** 2 for w, lh in hours_w) / total_w
        log_cv = (var_log**0.5) / max(abs(mean_log), 1e-9)

        eta_hours = math.exp(median_log)
        return {
            "eta_hours": round(eta_hours, 2),
            "eta_log_cv": round(log_cv, 4),
            "eta_n": len(hours_w),
            "eta_threshold": thresholds[anchor_idx] if anchor_idx is not None else None,
            "eta_threshold_name": threshold_names[anchor_idx] if anchor_idx is not None else None,
        }

    @staticmethod
    def _collect_log_hours(results):
        hours_w = []
        for name, r in results.items():
            if name == "_weighted" or "error" in r:
                continue
            w = r.get("weight", 0)
            h = r.get("predicted_hours", 0)
            if w <= 0:
                continue
            if h is None or h == float("inf") or h <= 0:
                continue
            # 截断离群：>100年 或 <1分钟 视为脏数据
            if h > 876000 or h < 1 / 60.0:
                continue
            hours_w.append((w, math.log(h)))
        return hours_w

    @staticmethod
    def _weighted_median_log(hours_w, total_w):
        hours_w.sort(key=lambda x: x[1])
        acc = 0.0
        median_log = None
        for w, lh in hours_w:
            acc += w
            if acc >= total_w * 0.5:
                median_log = lh
                break
        if median_log is None:
            median_log = hours_w[-1][1]
        return median_log

    @classmethod
    def _inject_live_features(cls, cached_video_data, kwargs):
        # 实时信号注入（研究补进）：viewers 在线人数/hour 等经 extra_features 传入，
        # 挂到 video_data["live_features"] 供算法读取 —— 此前已拉取但从不被任何算法消费
        live_feats = kwargs.get("live_features") or {}
        if live_feats:
            cached_video_data["live_features"] = dict(live_feats)
            # 兼容直接字段访问（部分算法可能直接读 video_data["viewers_total"]）
            for _k, _v in live_feats.items():
                if _k not in cached_video_data:
                    cached_video_data[_k] = _v

    @classmethod
    def _find_anchor_idx(cls, thresholds, current_value):
        # anchor 阈值：当前值之上的首个未达目标（算法真实预测的对象）
        # 若全部阈值都已达成 → 无 anchor，算法预测无意义（保持旧行为退化为最大阈值）
        anchor_idx = None
        for _i, _t in enumerate(thresholds):
            if current_value < _t:
                anchor_idx = _i
                break
        return anchor_idx

    @classmethod
    def _get_valid_predictions(cls, results):
        return [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

    @classmethod
    def _apply_log_eta(cls, results, cached_video_data, current_value, thresholds, threshold_names, anchor_idx):
        # ── log-ETA 集成 + C1 共识置信 ──
        # 各算法 predicted_hours(到 anchor 阈值) log 空间加权中位 → _weighted.eta
        # 置信改为 log 空间离散度：算法对"到达时间"分歧越小置信越高（替换 75s 同质 cv）
        try:
            eta_info = cls._compute_log_eta(results, current_value, thresholds, threshold_names, anchor_idx)
            if eta_info:
                results["_weighted"]["eta"] = eta_info
                # C1: 用 log-ETA 共识度覆盖 ensemble_confidence（≥3 算法有效时）
                if eta_info["eta_n"] >= 5 and eta_info["eta_log_cv"] > 0:
                    eta_conf = max(0.0, min(1.0, math.exp(-eta_info["eta_log_cv"] * 1.5)))
                    # 生命周期调制（实证驱动）：early 阶段曲线未定型 → 置信打折；
                    # steady/declining → 全历史衰减信息可靠 → 置信加成
                    _stage = cached_video_data.get("derived_features", {}).get("lifecycle_stage", "")
                    if _stage == "early":
                        eta_conf *= 0.75
                    elif _stage in ("steady", "declining"):
                        eta_conf = min(1.0, eta_conf * 1.1)
                    results["_weighted"]["ensemble_confidence"] = round(eta_conf, 4)
                    results["_weighted"]["confidence_basis"] = "log_eta"
        except Exception as e:
            logger.debug("log-ETA 集成失败: %s", e)

    @classmethod
    def _apply_surge_correction(cls, results, cached_video_data, current_value, weighted_pred):
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
        return weighted_pred

    @classmethod
    def _apply_bias_correction(cls, results, bvid, current_value, weighted_pred):
        # ── 系统性偏差校准 (B3)：样本充足时对 growth 分量施加中位数修正 ──
        try:
            if bvid:
                from ..bias_correction import get_bias_corrector

                bias_info = get_bias_corrector().get_correction(bvid)
                if bias_info.get("enabled") and bias_info.get("factor") != 1.0:
                    growth = weighted_pred - current_value
                    if growth > 0:
                        factor = bias_info["factor"]
                        corrected_pred = current_value + growth * factor
                        results["_weighted"]["prediction"] = max(current_value, corrected_pred)
                        results["_weighted"]["bias_correction_applied"] = True
                        results["_weighted"]["bias_factor"] = factor
                        results["_weighted"]["bias_samples"] = bias_info["samples"]
                        weighted_pred = results["_weighted"]["prediction"]
        except Exception as e:
            logger.debug("集成偏差校准失败: %s", e)
        return weighted_pred

    @classmethod
    def _log_ensemble_result(cls, results, bvid, weighted_pred, valid_count):
        interval_width = 0
        if results["_weighted"].get("prediction_interval"):
            try:
                interval_width = round(results["_weighted"]["prediction_interval"].get("interval_width_ratio", 0) * 100)
            except Exception:
                interval_width = 0
        logger.info(
            "[%s] 综合预测: %.0f (有效 %d/%d, 区间 ±%d%%)",
            bvid,
            weighted_pred,
            valid_count,
            len(results) - 1,
            interval_width,
        )

    @classmethod
    def predict_all(
        cls,
        history: List,
        current_value: float,
        bvid: str = "",
        db_history: Optional[List] = None,
        **kwargs: Any,
    ) -> Dict:
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
        cls._inject_live_features(cached_video_data, kwargs)

        thresholds = kwargs.get("thresholds", [100000, 1000000, 10000000])
        threshold_names = kwargs.get("threshold_names", ["10万", "100万", "1000万"])

        anchor_idx = cls._find_anchor_idx(thresholds, current_value)
        anchor_threshold = thresholds[anchor_idx] if anchor_idx is not None else thresholds[-1]

        # B3: 用本轮实际值验证上一轮集成预测的 growth 偏差（延迟一帧）
        try:
            cls._record_ensemble_feedback(bvid, current_value)
        except Exception as e:
            logger.debug("集成偏差反馈记录失败: %s", e)

        results, valid_count, na_count = cls._run_parallel_predictions(
            current_value,
            bvid,
            cached_video_data,
            thresholds,
            threshold_names,
            anchor_threshold=anchor_threshold,
            anchor_idx=anchor_idx,
        )

        valid_predictions = cls._get_valid_predictions(results)

        cls._apply_window_weights(results, valid_predictions, current_value)

        # 重建 valid_predictions：window 权重已写入 results，若继续用旧列表，
        # coherence 阶段会用原始权重覆盖掉 window 调整（window 权重白算）。
        valid_predictions = cls._get_valid_predictions(results)

        cls._apply_coherence_weights(results, valid_predictions)

        valid_predictions = cls._get_valid_predictions(results)

        weighted_pred = cls._compute_ensemble(results, valid_predictions, current_value, valid_count, na_count)

        cls._apply_log_eta(results, cached_video_data, current_value, thresholds, threshold_names, anchor_idx)
        weighted_pred = cls._apply_surge_correction(results, cached_video_data, current_value, weighted_pred)
        weighted_pred = cls._apply_bias_correction(results, bvid, current_value, weighted_pred)
        cls._log_ensemble_result(results, bvid, weighted_pred, valid_count)

        # 降频调度：保存本轮重算法的最终结果，作为下一轮跳过时的复用来源
        cls._store_heavy(bvid, results, anchor_idx)

        return cast(Dict[Any, Any], results)
