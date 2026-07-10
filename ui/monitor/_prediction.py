"""预测工具函数"""
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
import json
import numpy as np
from algorithms.registry import AlgorithmRegistry
from algorithms.base import BaseAlgorithm as BA


class _SurgeDetector(BA):
    """模块级单例推流检测器，避免重复创建类对象。"""

    def predict(self, video_data=None, threshold=100000):
        pass


_SURGE_DETECTOR = _SurgeDetector()
from core import bilibili_api, db, MonitorRecord, PredictionRecord
from ui.helpers import THRESHOLDS, THRESHOLD_NAMES, _parse_viewer_count
from utils.time_utils import safe_datetime, normalize_timestamp

# ── 模块级状态 ──
_up_db = None
_last_up_fetch_time: dict = {}


def _sync_predictions_to_central(bvid, rows, ensemble_data, coherence_rows):
    """将预测数据同步到中央库（预测 + 集成 + 共识度）"""
    try:
        from core import db
        db.sync_predictions(bvid, rows)
        if ensemble_data:
            db.sync_prediction_ensemble(bvid, datetime.now().isoformat(), ensemble_data)
        if coherence_rows:
            db.sync_algorithm_coherence(bvid, datetime.now().isoformat(), coherence_rows)
    except Exception as e:
        logger.debug("同步预测数据到中央库失败 %s: %s", bvid, e)


def _json_default(obj):
    """JSON 序列化辅助：将 numpy 类型转为 Python 原生类型"""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _save_predictions_to_db(gui, bvid, current_view, results):
    """将预测结果写入视频库，并返回数据供中央库同步"""
    video_db = gui.video_dbs.get(bvid)
    rows = []
    ensemble_data = None
    coherence_rows = []

    if video_db:
        import json
        for name, r in results.items():
            if name == "_weighted" or "error" in r:
                continue
            metadata = r.get("metadata", {})
            threshold_preds = metadata.get("threshold_predictions", [])
            if not threshold_preds:
                continue
            confidence = r.get("confidence", 0)
            predicted_hours = metadata.get("predicted_hours", 0)
            velocity = metadata.get("velocity", 0)
            metadata_str = json.dumps(metadata, ensure_ascii=False, default=_json_default)

            for tp in threshold_preds:
                row = {
                    "algorithm": name,
                    "algorithm_id": name,
                    "target_threshold": tp.get("threshold", 0),
                    "predicted_seconds": int(tp.get("minutes", 0) * 60) if tp.get("minutes") else 0,
                    "predicted_time": tp.get("name", ""),
                    "confidence": confidence,
                    "current_views": current_view,
                    "predicted_views": int(r.get("prediction", current_view)),
                    "metadata": metadata_str,
                    "predicted_hours": predicted_hours,
                    "current_velocity": velocity,
                }
                rows.append(row)

        if rows:
            try:
                video_db.add_predictions_batch(rows)
            except Exception as e:
                gui.log_panel.add_log("WARNING", f"批量保存预测记录失败 {bvid}: {e}")

    return rows, ensemble_data, coherence_rows


def _merge_history(gui, bvid: str) -> list:
    """合并内存历史与数据库历史，同步写回 gui.history_data 确保图表数据完整

    优化：首次从 DB 全量合并后，后续循环跳过 DB 读取（内存数据始终 >= DB）。
    """
    with gui._data_lock:
        current_view = next((v.get("view_count", 0) for v in gui.monitored_videos if v.get("bvid") == bvid), 0)
        history = list(gui.history_data.get(bvid, []))
        vdb = gui.video_dbs.get(bvid)  # 在锁内获取引用，防止主线程并发删除

    # 检查是否已从 DB 合并过
    from ui.monitor._service import _merged_from_db_lock, _merged_from_db
    with _merged_from_db_lock:
        if bvid in _merged_from_db:
            already_merged = True
        else:
            already_merged = False
    if not already_merged:
        try:
            if vdb is not None:
                db_hist = vdb.get_all_records(limit=500)
                if db_hist:

                    existing_ts = {normalize_timestamp(h[0])[2] for h in history}
                    for row in db_hist:
                        ts_str = normalize_timestamp(row["timestamp"])[2]
                        if ts_str not in existing_ts:
                            history.append((row["timestamp"], row["view_count"]))
        except Exception as e:
            logger.warning("合并历史记录失败 %s: %s", bvid, e)
        with _merged_from_db_lock:
            _merged_from_db.add(bvid)

    history.sort(key=lambda x: safe_datetime(x[0]))

    # 如果历史不足 2 条，用当前时间补齐
    if len(history) < 2:
        now = datetime.now()
        history = [(now, current_view), (now, current_view)]

    # 同步回 gui.history_data，让图表也能看到合并后的完整数据
    with gui._data_lock:
        gui.history_data[bvid] = [(ts, v) for ts, v in history]

    return history


def _get_up_db():
    """获取 UP主 数据库单例"""
    global _up_db
    if _up_db is None:
        from core.up_database import UpDatabase

        _up_db = UpDatabase()
    return _up_db


def _save_up_data(uid: int):
    """拉取 UP主信息+统计数据，保存到数据库（每 UP主 每小时最多一次）"""
    import time

    now = time.time()
    last = _last_up_fetch_time.get(uid, 0)
    if now - last < 3600:
        return
    _last_up_fetch_time[uid] = now

    try:
        info = bilibili_api.get_up_info(uid)
        if not info:
            logger.debug("获取UP主信息失败 UID:%s", uid)
            return

        stat = bilibili_api.get_up_stat(uid)
        if stat:
            info["total_views"] = stat.get("total_views", 0)
            info["total_likes"] = stat.get("total_likes", 0)
            if stat.get("follower_count"):
                info["follower_count"] = stat["follower_count"]

        up_db = _get_up_db()
        up_db.upsert_up(info)
        up_db.add_history(
            uid,
            follower_count=info.get("follower_count", 0),
            video_count=info.get("video_count", 0),
            total_views=info.get("total_views", 0),
        )
        logger.info("UP主数据已保存 UID:%s %s", uid, info.get("name", ""))
    except Exception as e:
        logger.warning("保存UP主数据失败 UID:%s: %s", uid, e)


def _calc_growth_rate(history: list) -> float:
    """根据历史数据计算播放量增长速率（播放量/秒）"""
    try:
        if len(history) < 2:
            return 0.0
        first_ts, first_v = safe_datetime(history[0][0]), history[0][1]
        last_ts, last_v = safe_datetime(history[-1][0]), history[-1][1]
        dt_sec = (last_ts - first_ts).total_seconds()
        if dt_sec > 0 and last_v > first_v:
            return (last_v - first_v) / dt_sec
    except Exception as e:
        logger.debug("计算增长率失败: %s", e)
    return 0.0


def _calc_surge_aware_growth_rate(history: list) -> float:
    """计算考虑大推流衰减后的播放量增长速率。

    检测到推流时，使用指数衰减模型调整速率，避免 ETA 过于乐观。
    无推流时等价于 _calc_growth_rate()。
    """
    raw_rate = _calc_growth_rate(history)
    if raw_rate <= 0:
        return 0.0

    if len(history) < 8:
        return raw_rate

    try:
        from algorithms.base import BaseAlgorithm as BA

        # 构建临时 video_data 用于推流检测
        history_list = []
        for ts, v in history:
            if isinstance(ts, datetime):
                ts_ts = ts.timestamp()
            else:
                try:
                    ts_ts = float(ts)
                except (ValueError, TypeError):
                    ts_ts = 0.0
            history_list.append({"view_count": v, "timestamp": ts_ts})

        video_data = {"history_data": history_list, "view_count": history[-1][1]}

        surge_info = _SURGE_DETECTOR.detect_surge(video_data)

        if surge_info.get("is_surging"):
            surge_mag = surge_info["surge_magnitude"]
            surge_type = surge_info["surge_type"]
            adj_vel = surge_info.get("adjusted_velocity", 0)
            surge_vel = surge_info.get("surge_velocity", raw_rate * 3600)

            if surge_vel > 0 and adj_vel > 0:
                correction = adj_vel / surge_vel
                correction = max(0.4, min(1.0, correction))
                return raw_rate * correction
    except Exception as e:
        logger.debug("推流感知速率计算失败: %s", e)
        pass

    return raw_rate


def _detect_surge_for_ui(history: list) -> dict:
    """检测推流状态并返回 UI 友好格式的信息。

    Returns:
        dict with: is_surging, surge_type, surge_label, surge_magnitude,
                   baseline_velocity, surge_velocity, daily_velocity,
                   velocity_history, decay_half_life_hours
    """
    try:
        from algorithms.base import BaseAlgorithm as BA

        if len(history) < 8:
            return {"is_surging": False, "surge_type": "none"}

        history_list = []
        for ts, v in history:
            if isinstance(ts, datetime):
                ts_ts = ts.timestamp()
            else:
                try:
                    ts_ts = float(ts)
                except (ValueError, TypeError):
                    ts_ts = 0.0
            history_list.append({"view_count": v, "timestamp": ts_ts})

        video_data = {"history_data": history_list, "view_count": history[-1][1]}

        si = _SURGE_DETECTOR.detect_surge(video_data)

        # 构建 UI 友好的标签
        type_labels = {"strong": "🔥 强推流", "moderate": "📈 推流中", "mild": "📊 轻度推流", "none": ""}
        surge_label = type_labels.get(si.get("surge_type", "none"), "") if si.get("is_surging") else ""

        return {
            "is_surging": si.get("is_surging", False),
            "surge_type": si.get("surge_type", "none"),
            "surge_label": surge_label,
            "surge_magnitude": si.get("surge_magnitude", 1.0),
            "surge_confidence": si.get("surge_confidence", 0.0),
            "baseline_velocity": round(si.get("baseline_velocity", 0)),
            "surge_velocity": round(si.get("surge_velocity", 0)),
            "daily_velocity": si.get("velocity_history", {}).get("daily_same_period"),
            "velocity_history": si.get("velocity_history", {}),
            "period_comparison": si.get("period_comparison", {}),
            "decay_half_life_hours": si.get("decay_half_life_hours", 6.0),
        }
    except Exception as e:
        logger.debug("推流检测失败: %s", e)
        return {"is_surging": False, "surge_type": "none"}


def _predict_single(gui, bvid, video) -> dict:
    """在 worker 线程中对单个视频运行预测（纯函数，无 UI 调用）"""
    current_view = video.get("view_count", 0)
    history = _merge_history(gui, bvid)

    # 运行所有算法进行预测
    results = AlgorithmRegistry.predict_all(
        history,
        current_view,
        bvid=bvid,
        thresholds=THRESHOLDS,
        threshold_names=THRESHOLD_NAMES,
    )

    weighted = results.get("_weighted", {})
    w_pred = weighted.get("prediction", current_view)
    success_list = []
    fail_list = []
    for name, r in results.items():
        if name == "_weighted":
            continue
        if "error" in r:
            fail_list.append((name, r["error"]))
        else:
            success_list.append((name, r["prediction"], r["weight"], r["confidence"], r.get("predicted_hours", 0)))

    growth = w_pred - current_view
    rate_per_sec = _calc_surge_aware_growth_rate(history)

    # ── 推流检测信息（供 UI 展示）──────────────────
    surge_info = _detect_surge_for_ui(history)

    result = {
        "bvid": bvid,
        "prediction": w_pred,
        "current_view": current_view,
        "growth": max(0, growth),
        "rate_per_sec": rate_per_sec,
        "surge_info": surge_info,
        "success_list": success_list,
        "fail_list": fail_list,
        "valid": weighted.get("valid_algorithms", 0),
        "total": weighted.get("total_algorithms", 0),
        # ── 传递给中央库同步的额外数据 ──
        "ensemble": {
            "prediction": w_pred,
            "confidence": weighted.get("ensemble_confidence", 0),
            "valid_algos": weighted.get("valid_algorithms", 0),
            "total_algos": weighted.get("total_algorithms", 0),
            "prediction_interval": weighted.get("prediction_interval"),
            "surge_correction_applied": weighted.get("surge_correction_applied", False),
            "surge_magnitude": weighted.get("surge_magnitude"),
            "surge_type": weighted.get("surge_type", ""),
        },
        "coherence_list": [
            (name, r.get("coherence", 0)) for name, r in results.items()
            if name != "_weighted" and "error" not in r and r.get("coherence")
        ],
    }
    # 在线学习反馈
    with gui._data_lock:
        prev_result = gui.prediction_results.get(bvid)
        gui.prediction_results[bvid] = result
    _online_learning_feedback(gui, bvid, results, current_view, prev_result)

    # 后台：图更新 + 视频库保存 + 中央库同步
    def _save_all():
        try:
            _update_video_graph(gui, bvid, video)
            rows, ensemble, coherence = _save_predictions_to_db(gui, bvid, current_view, results)
            _sync_predictions_to_central(bvid, rows, ensemble, coherence)
        except Exception:
            logger.exception("后台保存预测数据失败 %s", bvid)

    threading.Thread(target=_save_all, daemon=True).start()

    # 每批次预测后释放模型缓存 + 强制 GC
    _maybe_release_memory()

    return result


# 批处理计数器：每 N 次预测后清理内存
_predict_count = 0
_PREDICT_CLEANUP_INTERVAL = 3


def _maybe_release_memory():
    """每 N 次预测后强制 GC 释放内存。"""
    global _predict_count
    _predict_count += 1
    if _predict_count % _PREDICT_CLEANUP_INTERVAL == 0:
        import gc
        gc.collect()


def _online_learning_feedback(gui, bvid, results, actual_view, prev_result):
    """在线学习反馈：使用速度偏差替代绝对值比较

    比较「上次预测的增长量」与「实际增长量」，避免静止期 100% 准确率的虚假提升。
    """
    if prev_result is None or actual_view <= 0:
        return
    try:
        from algorithms.online_learner import get_online_learner

        prev_prediction = prev_result.get("prediction", 0)
        if prev_prediction > 0:
            learner = get_online_learner()
            learner.register(bvid + "/_weighted")
            learner.update(bvid + "/_weighted", predicted=prev_prediction, actual=actual_view)

        learner = get_online_learner()
        for name, pred_val, _, _ in prev_result.get("success_list", []):
            if pred_val > 0:
                algo_key = bvid + "/" + name
                learner.register(algo_key)
                learner.update(algo_key, predicted=pred_val, actual=actual_view)
    except Exception as e:
        logger.debug("在线学习反馈失败: %s", e)


def _update_video_graph(gui, bvid, video):
    """更新视频关系图节点和边"""
    try:
        from algorithms.graph_neural import get_video_graph

        graph = get_video_graph()
        graph.update_node(bvid, video)
        if graph.get_graph_stats()["num_nodes"] >= 2:
            graph.build_edges()
    except Exception as e:
        logger.debug("更新视频关系图失败: %s", e)


# ──────────────────────────────────────────────
#  核心：每个视频一个独立 Worker 线程
# ──────────────────────────────────────────────


