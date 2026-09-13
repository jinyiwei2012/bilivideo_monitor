"""FeaturePrepMixin extracted from algorithms.registry."""

import threading
from typing import Any, Dict, List, Tuple
from datetime import datetime

from ._shared import _LRUDict


class FeaturePrepMixin:
    _cache_lock: threading.Lock
    _derived_cache: _LRUDict

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
            return hashlib.blake2b(ts_arr.tobytes() + v_arr.tobytes(), digest_size=16).hexdigest()
        except Exception:
            return str(len(history_list))

    @classmethod
    def _normalize_history(cls, history: List[Tuple]) -> List:
        history_list = []

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
        return history_list

    @classmethod
    def _populate_velocity_features(cls, derived, v_arr, ts_arr, n, np):
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

    @classmethod
    def _populate_freeze_recovery(cls, derived, _dv, _valid_dt, _seg_ts, _seg_v, _ceil, np):
        _win_dv = _dv[_valid_dt]
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

    @classmethod
    def _populate_mad_velocity(cls, derived, _rates, _med, np):
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

    @classmethod
    def _populate_robust_velocity(cls, derived, v_arr, ts_arr, n, np):
        if n < 4:
            return
        _k = min(12, n - 1)
        _seg_ts = ts_arr[-_k - 1 :]
        _seg_v = v_arr[-_k - 1 :]
        _dt = np.diff(_seg_ts)
        _dv = np.diff(_seg_v)
        _valid_dt = _dt > 0
        if not np.any(_valid_dt):
            return
        _rates = _dv[_valid_dt] / _dt[_valid_dt] * 3600.0
        # 剔除负速率(回跳)与超物理上限的脏段
        _ceil = max(float(_seg_v[-1]) * 60.0, 1e6)
        _rates = _rates[(_rates >= 0) & (_rates <= _ceil)]
        if len(_rates) < 2:
            return
        _med = float(np.median(_rates))
        # 冻结恢复分支: 大量 0(冻结) + 单发大补量 → 用"补量/冻结时长"恢复真实速率
        # 判定: median≈0 且存在 >6×median 的显著正点(补量)且 0 占多数
        _nz = _rates[_rates > 0]
        _zero_frac = 1.0 - len(_nz) / max(len(_rates), 1)
        if _med < 1e-9 and len(_nz) >= 1 and _zero_frac >= 0.5:
            # 冻结恢复速率 = 冻结窗口总增长 / 总时长（含冻结的 0 段）
            # 窗口起点：从末段反向扫描，找最后一个正增量段(补量)之前
            # 连续 0 串的起点；窗口 = [冻结起点, 末段]。
            cls._populate_freeze_recovery(derived, _dv, _valid_dt, _seg_ts, _seg_v, _ceil, np)
        else:
            cls._populate_mad_velocity(derived, _rates, _med, np)

    @classmethod
    def _populate_lifecycle_features(cls, derived, v_arr, ts_arr, n, np):
        if n < 288:  # ≥6 小时才有意义
            return
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

    @classmethod
    def _populate_lag_and_rolling_features(cls, derived, view_values, v_arr, n, np):
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

    @classmethod
    def _compute_derived_features(cls, view_values, history_list):
        derived: Dict[str, Any] = {}
        import numpy as np

        n = len(view_values)
        # 时间戳必须用 float64：unix 秒级时间戳 ~1.78e9，float32 的 ulp=128s，
        # 大于 75s 采样间隔 → 相邻点被舍入为相同值，polyfit 斜率系统性失真。
        v_arr = np.array(view_values, dtype=np.float64)
        ts_arr = np.array([h["timestamp"] for h in history_list], dtype=np.float64)

        if n >= 2:
            cls._populate_velocity_features(derived, v_arr, ts_arr, n, np)
            # ── 稳健增量速率（抗噪，用于 75s 增量预测）──
            # 实证修订：简单"剔除 0 增量"会把真实停滞误当 API 伪迹 → 停滞视频速率被
            # 补量点拉高（实测高估 300x）。正确做法：不预剔除，对全速率(含 0)取 median，
            # 仅用 MAD 剪除单发大补量离群 —— median 天然对 0 稳健(停滞→0)，
            # MAD 剪除只移除"假爆发"补量点，两类噪声同时防御。
            cls._populate_robust_velocity(derived, v_arr, ts_arr, n, np)
            # ── 全历史生命周期特征（实证驱动，供长程 ETA / 算法消费）──
            # 实证(lifecycle_test3)：早期爆发视频(<5天)全历史会把爆发初速当常态 → 误差 +443%，
            # 平稳/衰退视频全历史衰减修正胜出 +53%~63%。故单独输出"生命周期阶段"信号，
            # 不进 increment_75s(短窗动量保持纯净)，由 log-ETA / 校准逻辑按阶段自适应加权。
            cls._populate_lifecycle_features(derived, v_arr, ts_arr, n, np)
        cls._populate_lag_and_rolling_features(derived, view_values, v_arr, n, np)
        return derived

    @classmethod
    def _prepare_video_data(cls, history: List[Tuple], current_value: float, bvid: str = "") -> Dict:
        """将 (timestamp, view_count) 历史元组统一转为 video_data 字典。

        避免每个 adapter 重复做同样的类型转换，集中处理可提升约 30% 性能。
        """
        now = datetime.now()
        history_list = cls._normalize_history(history)
        view_values = [v for _, v in history]

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
            derived = cls._compute_derived_features(view_values, history_list)
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
