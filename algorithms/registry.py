"""
算法注册器

集中管理所有预测算法。在首次使用时自动扫描 models/ 目录下的所有
算法文件（BaseAlgorithm 直接实例），并为每个视频运行全量算法预测，
产生带权重加权的集成预测结果（ensemble prediction）。
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
            # 不能用 popitem(last=False)：CPython 中其内部会经子类 __getitem__
            # 访问被淘汰的 key，而该 key 已从 dict 移除 → move_to_end 抛 KeyError。
            # 改为手动取最旧键删除，绕开该调用链。
            try:
                oldest = next(iter(self))
            except StopIteration:
                return
            del self[oldest]

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
    _pool_lock = threading.RLock()  # RLock to allow reentrant pool access
    _pool = None
    _init_lock = threading.Lock()
    _history_lock = threading.Lock()
    _cache_lock = threading.Lock()  # 保护 _derived_cache 并发读写
    _derived_cache: _LRUDict = _LRUDict(maxsize=_MAX_CACHE_SIZE)

    # B3: 集成偏差校准 —— 记录每个 bvid 上一次集成预测 (prediction, current_value)
    # 下次预测时用新的 current_value 作"实际值"验证 growth 偏差
    _prev_ensemble_pred: Dict = {}
    _prev_ensemble_lock = threading.Lock()

    @classmethod
    def _record_ensemble_feedback(cls, bvid: str, current_value: float):
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
    def reset_ensemble_bias(cls, bvid: str):
        """删除某视频的偏差样本（删除监控时调用）。"""
        with cls._prev_ensemble_lock:
            cls._prev_ensemble_pred.pop(bvid, None)
        try:
            from .bias_correction import get_bias_corrector

            get_bias_corrector().reset_bvid(bvid)
        except Exception:
            pass

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
        """扫描 models/ 目录, 直接实例化并注册所有算法 (不再经 ModelAlgorithmAdapter 包装)。"""
        try:
            import importlib
            import os

            current_dir = os.path.dirname(__file__)
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
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and attr_name.endswith("Algorithm"):
                            if "BaseAlgorithm" not in {c.__name__ for c in attr.__mro__}:
                                continue
                            try:
                                instance = attr()
                            except Exception as e:
                                logger.debug("忽略算法 %s.%s: %s", module_path, attr_name, e)
                                continue
                            algo_name = f"[Model] {instance.name}"
                            cls._algorithms[algo_name] = instance

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
        for key, algo in cls._algorithms.items():
            raw_id = getattr(algo, "algorithm_id", None)
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
    def _content_digest(cls, history_list: List) -> str:
        """派生特征缓存键的内容摘要：全量时间戳+播放量的轻量 md5。

        派生特征（velocity_mean 等）依赖全部历史点，因此摘要需覆盖全部点；
        单次 predict_all 只计算一次（结果被 120+ 算法共享），开销可忽略。
        """
        try:
            import hashlib
            import numpy as np

            ts_arr = np.array([h["timestamp"] for h in history_list], dtype=np.float64)
            v_arr = np.array([h["view_count"] for h in history_list], dtype=np.float64)
            return hashlib.md5(ts_arr.tobytes() + v_arr.tobytes()).hexdigest()
        except Exception:
            return str(len(history_list))

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
        # 缓存键加入内容摘要：仅用 (bvid, n, current_value) 会在历史内容变化但
        # 长度/当前值不变时命中陈旧特征（含 bvid="" 跨视频串键）。
        cache_key = (bvid, n, current_value, cls._content_digest(history_list))
        with cls._cache_lock:
            try:
                derived = cls._derived_cache[cache_key]
            except KeyError:
                derived = None
        if derived is None:
            derived = {}
            import numpy as np

            # 时间戳必须用 float64：unix 秒级时间戳 ~1.78e9，float32 的 ulp=128s，
            # 大于 75s 采样间隔 → 相邻点被舍入为相同值，polyfit 斜率系统性失真。
            v_arr = np.array(view_values, dtype=np.float64)
            ts_arr = np.array([h["timestamp"] for h in history_list], dtype=np.float64)

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
                    # slope 单位 views/秒 → views/小时 应 ×3600（与下方 2 点分支一致）
                    derived["velocity_polyfit"] = max(0.0, float(slope * 3600.0))
                elif n >= 2:
                    dt = ts_arr[-1] - ts_arr[-2]
                    if dt > 0:
                        derived["velocity_polyfit"] = max(0.0, float((v_arr[-1] - v_arr[-2]) / max(dt, 1e-8) * 3600.0))
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
                # ── 稳健增量速率（抗噪，用于 75s 增量预测）──
                # 实证修订：简单"剔除 0 增量"会把真实停滞误当 API 伪迹 → 停滞视频速率被
                # 补量点拉高（实测高估 300x）。正确做法：不预剔除，对全速率(含 0)取 median，
                # 仅用 MAD 剪除单发大补量离群 —— median 天然对 0 稳健(停滞→0)，
                # MAD 剪除只移除"假爆发"补量点，两类噪声同时防御。
                if n >= 4:
                    _k = min(12, n - 1)
                    _seg_ts = ts_arr[-_k - 1 :]
                    _seg_v = v_arr[-_k - 1 :]
                    _dt = np.diff(_seg_ts)
                    _dv = np.diff(_seg_v)
                    _valid_dt = _dt > 0
                    if np.any(_valid_dt):
                        _rates = _dv[_valid_dt] / _dt[_valid_dt] * 3600.0
                        # 剔除负速率(回跳)与超物理上限的脏段
                        _ceil = max(float(_seg_v[-1]) * 60.0, 1e6)
                        _rates = _rates[(_rates >= 0) & (_rates <= _ceil)]
                        if len(_rates) >= 2:
                            _med = float(np.median(_rates))
                            # 冻结恢复分支: 大量 0(冻结) + 单发大补量 → 用"补量/冻结时长"恢复真实速率
                            # 判定: median≈0 且存在 >6×median 的显著正点(补量)且 0 占多数
                            _nz = _rates[_rates > 0]
                            _zero_frac = 1.0 - len(_nz) / max(len(_rates), 1)
                            if _med < 1e-9 and len(_nz) >= 1 and _zero_frac >= 0.5:
                                # 冻结恢复速率 = 冻结窗口总增长 / 总时长（含冻结的 0 段）
                                # 窗口起点：从末段反向扫描，找最后一个正增量段(补量)之前
                                # 连续 0 串的起点；窗口 = [冻结起点, 末段]。
                                _win_dv = _dv[_valid_dt]
                                _win_dt = _dt[_valid_dt]
                                # 反向找补量段：最后一个正增量段下标
                                _pos_i = np.where(_win_dv > 0)[0]
                                if len(_pos_i) > 0:
                                    _last_pos = int(_pos_i[-1])
                                    # 冻结起点 = 补量段前连续 0 段的起点
                                    _fz_start = _last_pos
                                    while _fz_start > 0 and _win_dv[_fz_start - 1] == 0:
                                        _fz_start -= 1
                                    # 窗口覆盖 [起点段, 末段] 的真实时间与增长
                                    _t_start = _seg_ts[_fz_start]
                                    _t_end = _seg_ts[-1]
                                    _rec_dt = float(_t_end - _t_start)
                                    _rec_dv = float(_seg_v[-1] - _seg_v[_fz_start])
                                    if _rec_dt > 0:
                                        _rec_vel = max(0.0, _rec_dv / _rec_dt * 3600.0)
                                        _rec_vel = min(_rec_vel, _ceil)
                                        derived["velocity_robust_hourly"] = float(max(0.0, _rec_vel))
                                        derived["increment_75s"] = derived["velocity_robust_hourly"] * 75.0 / 3600.0
                                        derived["velocity_freeze_recovered"] = True
                            else:
                                # MAD 剪除单发补量离群：|x - med| > 3 * 1.4826 * MAD
                                _mad = float(np.median(np.abs(_rates - _med))) if len(_rates) >= 3 else 0.0
                                if _mad > 1e-9:
                                    _thr = 3.0 * 1.4826 * _mad
                                    _clean = _rates[np.abs(_rates - _med) <= _thr]
                                    if len(_clean) >= 2:
                                        _rates = _clean
                                        _med = float(np.median(_rates))
                                # 近端加权均值（对剩余速率；若与 median 分歧大则信 median）
                                _w = 0.8 ** np.arange(len(_rates))[::-1]
                                _w = _w / max(np.sum(_w), 1e-9)
                                _wlr = float(np.sum(_rates * _w))
                                if abs(_med - _wlr) / max(_med, 1e-9) > 0.3:
                                    _robust = _med
                                else:
                                    _robust = 0.5 * _med + 0.5 * _wlr
                                derived["velocity_robust_hourly"] = float(max(0.0, _robust))
                                derived["increment_75s"] = derived["velocity_robust_hourly"] * 75.0 / 3600.0
                # ── 全历史生命周期特征（实证驱动，供长程 ETA / 算法消费）──
                # 实证(lifecycle_test3)：早期爆发视频(<5天)全历史会把爆发初速当常态 → 误差 +443%，
                # 平稳/衰退视频全历史衰减修正胜出 +53%~63%。故单独输出"生命周期阶段"信号，
                # 不进 increment_75s(短窗动量保持纯净)，由 log-ETA / 校准逻辑按阶段自适应加权。
                if n >= 288:  # ≥6 小时才有意义
                    _age_hours = float(ts_arr[-1] - ts_arr[0]) / 3600.0 if ts_arr[-1] > ts_arr[0] else 0.0
                    # 早期基准段(前1/4)与近期段(末1/4)的正速率中位 → 生命周期衰减比
                    _q = max(4, n // 4)
                    _early_diff = np.diff(v_arr[: _q + 2])
                    _recent_diff = np.diff(v_arr[-_q - 1 :])
                    _early_pos = _early_diff[_early_diff > 0]
                    _recent_pos = _recent_diff[_recent_diff > 0]
                    _early_rate = float(np.median(_early_pos)) if len(_early_pos) >= 3 else 0.0
                    _recent_rate = float(np.median(_recent_pos)) if len(_recent_pos) >= 3 else 0.0
                    _decay = (_recent_rate / _early_rate) if _early_rate > 0 else 1.0
                    derived["history_age_hours"] = round(_age_hours, 1)
                    derived["lifecycle_decay"] = round(float(min(2.0, max(0.0, _decay))), 4)
                    # 阶段: early(<5天 或 无明显衰减) / steady / declining
                    if _age_hours < 120 or _decay >= 0.85:
                        derived["lifecycle_stage"] = "early"
                    elif _decay >= 0.5:
                        derived["lifecycle_stage"] = "steady"
                    else:
                        derived["lifecycle_stage"] = "declining"
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
            "_sorted": True,  # history_list 已按时间升序，算法无需再次排序
            "_velocity": derived.get("velocity_polyfit", 0.0),  # 预计算速度，避免各算法重复 compute
            "velocity": derived.get("velocity_polyfit", 0.0),  # 兼容直接访问
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

    @classmethod
    def _run_parallel_predictions(
        cls, current_value, bvid, cached_video_data, thresholds, threshold_names, anchor_threshold=None
    ):
        results = {}
        valid_count = 0
        na_count = 0

        # 预取全部权重（避免 100+ 线程争抢 WeightManager._lock）
        _weights = {name: get_weight_manager().get_weight(name) for name in cls._algorithms}

        # B2: 在线学习全局分数 → 权重修正因子（跨视频聚合的算法级实时表现）
        # 注意 tracker key 存的是裸算法名(带"[Model] "前缀)，registry key 同名；
        # 分数 rel 落在 1.0 附近，clip [0.3, 3.0] 防单算法过冲
        try:
            from .online_learner import get_online_learner

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
            from .conformal import get_conformal_predictor

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
        hours_w = []  # (weight, log_hours)
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
        if len(hours_w) < 3:
            return None

        # 加权中位数（log 空间）
        total_w = sum(w for w, _ in hours_w)
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

        # log 空间加权离散度 → 共识置信（算法对到达时间分歧越小越可信）
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

    @classmethod
    def predict_all(
        cls, history: List, current_value: float, bvid: str = "", db_history: List = None, **kwargs
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

        # 实时信号注入（研究补进）：viewers 在线人数/hour 等经 extra_features 传入，
        # 挂到 video_data["live_features"] 供算法读取 —— 此前已拉取但从不被任何算法消费
        live_feats = kwargs.get("live_features") or {}
        if live_feats:
            cached_video_data["live_features"] = dict(live_feats)
            # 兼容直接字段访问（部分算法可能直接读 video_data["viewers_total"]）
            for _k, _v in live_feats.items():
                if _k not in cached_video_data:
                    cached_video_data[_k] = _v

        thresholds = kwargs.get("thresholds", [100000, 1000000, 10000000])
        threshold_names = kwargs.get("threshold_names", ["10万", "100万", "1000万"])

        # anchor 阈值：当前值之上的首个未达目标（算法真实预测的对象）
        # 若全部阈值都已达成 → 无 anchor，算法预测无意义（保持旧行为退化为最大阈值）
        anchor_idx = None
        for _i, _t in enumerate(thresholds):
            if current_value < _t:
                anchor_idx = _i
                break
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
        )

        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        cls._apply_window_weights(results, valid_predictions, current_value)

        # 重建 valid_predictions：window 权重已写入 results，若继续用旧列表，
        # coherence 阶段会用原始权重覆盖掉 window 调整（window 权重白算）。
        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        cls._apply_coherence_weights(results, valid_predictions)

        valid_predictions = [
            (name, r["prediction"], r["weight"])
            for name, r in results.items()
            if r["weight"] > 0 and r["prediction"] > 0
        ]

        weighted_pred = cls._compute_ensemble(results, valid_predictions, current_value, valid_count, na_count)

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

        # ── 系统性偏差校准 (B3)：样本充足时对 growth 分量施加中位数修正 ──
        try:
            if bvid:
                from .bias_correction import get_bias_corrector

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

        return results

    @classmethod
    def update_accuracy(
        cls, algorithm_name: str, predicted: float = None, actual: float = None, accuracy: float = None
    ):
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
    def update_accuracy_batch(cls, items):
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
    def warmup_weights_from_backtest(cls, bvid: str, history: List) -> int:
        """B3: 冷启动加速 —— 用离线滚动回测的 1 步 MAPE 预热算法权重。

        背景：WeightManager.accuracy_records 需真实预测反馈累积，冷启动期所有算法
        weight 恒为 1.0（无差别）。而 RollingBacktester 可离线评估各算法在该视频
        历史数据上的表现 —— 用回测 MAPE 写 1 条初始 accuracy，让 ML 权重立即区分好坏。

        Args:
            bvid: 视频 BV 号
            history: [(timestamp, view_count), ...] 历史数据

        Returns:
            成功预热的算法数量
        """
        try:
            if not bvid or not history or len(history) < 15:
                return 0
            # 每视频只预热一次（启动后历史相对稳定，重复回测浪费 CPU）
            with cls._history_lock:
                warmed = getattr(cls, "_backtest_warmed", set())
                cls._backtest_warmed = warmed
                if bvid in warmed:
                    return 0
                warmed.add(bvid)

            import numpy as np
            from algorithms.rollout_backtest import RollingBacktester

            series = np.array([v for _, v in history], dtype=float)
            if len(series) < 15:
                return 0

            backtester = RollingBacktester(min_train=8, step=4, horizon=1)
            warmed_count = 0
            # 限制算法数避免启动过慢（每个算法一次完整回测）
            names = cls.get_algorithm_names()
            sample = names[:40]

            for name in sample:
                algo = cls._algorithms.get(name)
                if algo is None:
                    continue
                try:
                    # 复刻回测面板的 predict_fn：滚动窗口喂 video_data，取 1 步预测
                    def _make_fn(algo_inst=algo):
                        def fn(train: np.ndarray) -> float:
                            if len(train) < 3:
                                return float(train[-1]) if len(train) > 0 else 0.0
                            try:
                                hist_list = []
                                # 回测用索引时间（等间隔假设），构造 video_data
                                base_ts = 1_700_000_000.0
                                for _i, _v in enumerate(train):
                                    hist_list.append({"view_count": float(_v), "timestamp": base_ts + _i * 75.0})
                                vd = {
                                    "view_count": float(train[-1]),
                                    "history_data": hist_list,
                                    "_sorted": True,
                                    "timestamp": base_ts + len(train) * 75.0,
                                }
                                res = algo_inst.predict(vd, threshold=1_000_000)
                                if res is None or getattr(res, "predicted_hours", None) in (None, float("inf")):
                                    vel = getattr(res, "current_velocity", 0) if res is not None else 0
                                    if vel > 0:
                                        return float(train[-1]) + vel * (75.0 / 3600.0)
                                    return float(train[-1]) * 1.005
                                vel = getattr(res, "current_velocity", 0)
                                if vel > 0:
                                    return float(train[-1]) + vel * (75.0 / 3600.0)
                                return float(train[-1]) * 1.01
                            except Exception:
                                return float(train[-1]) if len(train) > 0 else 0.0

                        return fn

                    result = backtester.backtest(series, _make_fn())
                    if result.get("n_tests", 0) >= 3 and result["mape"] != float("inf"):
                        mape = result["mape"]
                        # MAPE → 初始准确率（0.9 封顶，回测非真实验证，保留学习空间）
                        init_acc = max(0.3, min(0.9, 1.0 - mape))
                        # 用轻量路径写 accuracy（不触发 algo.update_accuracy 内部状态）
                        get_weight_manager().update_accuracy(name, init_acc)
                        warmed_count += 1
                except Exception as e:
                    logger.debug("预热算法 %s 失败: %s", name, e)
            if warmed_count:
                logger.info("[%s] 回测预热 %d 个算法权重", bvid, warmed_count)
            return warmed_count
        except Exception as e:
            logger.debug("权重预热失败 %s: %s", bvid, e)
            return 0

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
        cls._derived_cache = _LRUDict(maxsize=_MAX_CACHE_SIZE)
        cls._initialized = False
        with cls._prev_ensemble_lock:
            cls._prev_ensemble_pred.clear()

    @classmethod
    def get_trainable_info(cls) -> List[Dict]:
        """获取所有支持训练的算法的检查点信息。"""
        from algorithms.training.checkpoint_manager import CheckpointManager

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
    def get_trainable_algorithms(cls) -> List:
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


# 不再模块级初始化，改为按需（Lazy）初始化 —— 所有公开方法都已检查 _initialized 标志
