"""
监控业务逻辑模块 - 独立 Worker 线程模型

每个视频一个独立线程，自主管理刷新间隔，互不阻塞、互不干扰。
"""

import threading
import time
import logging
from datetime import datetime
from algorithms.registry import AlgorithmRegistry
from core import bilibili_api, db, MonitorRecord, PredictionRecord
from ui.helpers import (
    THRESHOLDS,
    THRESHOLD_NAMES,
    _parse_viewer_count,
)

logger = logging.getLogger(__name__)

# 已从 DB 完成历史合并的视频集合（后续循环中内存数据始终 >= DB，跳过全量读取）
_merged_from_db = set()
_merged_from_db_lock = threading.Lock()

# UP主数据库实例 & 拉取频率控制（每 UP主 每小时最多拉取一次）
_up_db = None
_last_up_fetch_time = {}  # uid -> time.time

# ──────────────────────────────────────────────
#  内部工具函数
# ──────────────────────────────────────────────


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

    # 检查是否已从 DB 合并过
    with _merged_from_db_lock:
        if bvid in _merged_from_db:
            already_merged = True
        else:
            already_merged = False
    if not already_merged:
        try:
            if bvid in gui.video_dbs:
                db_hist = gui.video_dbs[bvid].get_all_records(limit=500)
                if db_hist:

                    def _norm(ts):
                        """统一时间戳格式用于去重比较"""
                        if isinstance(ts, datetime):
                            return ts.strftime("%Y-%m-%d %H:%M:%S")
                        dt = (
                            datetime.fromisoformat(str(ts))
                            if isinstance(ts, str)
                            else datetime.fromtimestamp(float(ts))
                        )
                        return dt.strftime("%Y-%m-%d %H:%M:%S")

                    existing_ts = {_norm(h[0]) for h in history}
                    for row in db_hist:
                        ts_str = _norm(row["timestamp"])
                        if ts_str not in existing_ts:
                            history.append((row["timestamp"], row["view_count"]))
        except Exception as e:
            logger.warning(f"合并历史记录失败 {bvid}: {e}")
        with _merged_from_db_lock:
            _merged_from_db.add(bvid)

    history.sort(key=lambda x: _to_dt(x[0]))

    # 如果历史不足 2 条，用当前时间补齐
    if len(history) < 2:
        now = datetime.now()
        history = [(now, current_view), (now, current_view)]

    # 同步回 gui.history_data，让图表也能看到合并后的完整数据
    with gui._data_lock:
        gui.history_data[bvid] = [(ts, v) for ts, v in history]

    return history


def _to_dt(t):
    """统一时间戳转为 datetime"""
    return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))


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
        first_ts, first_v = _to_dt(history[0][0]), history[0][1]
        last_ts, last_v = _to_dt(history[-1][0]), history[-1][1]
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

        class _SurgeDetector(BA):
            def predict(self, video_data=None, threshold=100000):
                pass

        detector = _SurgeDetector()
        surge_info = detector.detect_surge(video_data)

        if surge_info.get("is_surging"):
            surge_mag = surge_info["surge_magnitude"]
            surge_type = surge_info["surge_type"]
            adj_vel = surge_info.get("adjusted_velocity", 0)
            surge_vel = surge_info.get("surge_velocity", raw_rate * 3600)

            if surge_vel > 0 and adj_vel > 0:
                correction = adj_vel / surge_vel
                correction = max(0.4, min(1.0, correction))
                return raw_rate * correction
    except Exception:
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

        class _SurgeDetector(BA):
            def predict(self, video_data=None, threshold=100000):
                pass

        detector = _SurgeDetector()
        si = detector.detect_surge(video_data)

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
    except Exception:
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
        _update_video_graph(gui, bvid, video)
        rows, ensemble, coherence = _save_predictions_to_db(gui, bvid, current_view, results)
        _sync_predictions_to_central(bvid, rows, ensemble, coherence)

    threading.Thread(target=_save_all, daemon=True).start()

    # 每批次预测后释放模型缓存 + 强制 GC
    _maybe_release_memory()

    return result


# 批处理计数器：每 N 次预测后清理内存
_predict_count = 0
_PREDICT_CLEANUP_INTERVAL = 3


def _maybe_release_memory():
    """每 N 次预测后释放 PyTorch 模型缓存并强制 GC。"""
    global _predict_count
    _predict_count += 1
    if _predict_count % _PREDICT_CLEANUP_INTERVAL == 0:
        import gc
        try:
            from algorithms.models.deep_learning._torch_upgrade import release_cached_models
            release_cached_models()
        except Exception:
            pass
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


class VideoWorker:
    """
    独立的后台刷新线程，每个监控视频一个实例。
    完全自主管理刷新间隔，不与其他视频共享状态。
    """

    def __init__(self, gui, bvid, video, interval, fast_interval=None):
        self.gui = gui
        self.bvid = bvid
        self.video = video
        self.interval = interval  # 正常刷新间隔（秒）
        self.fast_interval = fast_interval  # 接近阈值时的快速间隔（秒）
        self._stop_event = threading.Event()
        self._thread = None
        self._interval_lock = threading.Lock()  # 保护 interval 切换
        self._fetching_lock = threading.Lock()
        self._fetching = False
        self._log = gui.log_panel.add_log

    # ── 公开 API ────────────────────────────────

    def start(self):
        """启动独立刷新线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"VideoWorker-{self.bvid}")
        self._thread.start()
        self._log("INFO", f"[{self.bvid}] Worker 线程已启动（间隔 {self.interval}s）")

    def stop(self):
        """安全停止线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._log("INFO", f"[{self.bvid}] Worker 线程已停止")

    def update_interval(self, new_interval):
        """运行时更新刷新间隔（主线程调用）"""
        with self._interval_lock:
            self.interval = new_interval

    def refresh_now(self):
        """立即执行一次拉取+预测（主线程调用，立即触发一次）"""
        self._log("INFO", f"[{self.bvid}] 立即刷新触发")
        threading.Thread(target=self._fetch_and_predict, daemon=True, name=f"VideoWorker-{self.bvid}-immediate").start()

    # ── 内部循环 ─────────────────────────────────

    def _run(self):
        """Worker 主循环：睡眠 → 拉取+预测 → 更新间隔 → 循环"""
        while not self._stop_event.is_set():
            # 获取当前 interval（可能由主线程动态调整）
            with self._interval_lock:
                interval = self.interval

            self._fetch_and_predict()

            # 分段睡眠，支持中途停止检查
            waited = 0
            step = 1.0  # 每步最多睡 1 秒，便于及时响应 stop
            while waited < interval and not self._stop_event.is_set():
                sleep_for = min(step, interval - waited)
                time.sleep(sleep_for)
                waited += sleep_for

    def _fetch_and_predict(self):
        """在 worker 线程中执行一次完整的拉取 + 预测"""
        bvid = self.bvid
        video = self.video
        gui = self.gui

        with self._fetching_lock:
            if self._fetching:
                self._log("DEBUG", f"[{bvid}] 上次拉取尚未完成，跳过本次")
                return
            self._fetching = True

        if not self._do_fetch(bvid, video, gui):
            with self._fetching_lock:
                self._fetching = False
            return

        result = self._do_predict(gui, bvid, video)
        if result is None:
            with self._fetching_lock:
                self._fetching = False
            return

        self._do_post_fetch(bvid, video, gui, result)

        with self._fetching_lock:
            self._fetching = False

    def _do_fetch(self, bvid, video, gui):
        """拉取视频数据：获取 info → 更新字段 → 在线人数 → 历史记录 → 写DB"""
        self._log("DEBUG", f"[{bvid}] 开始拉取数据…")
        proxy_hint = bilibili_api.proxy_manager.peek_proxy()
        if proxy_hint:
            self._log("INFO", f"[{bvid}] 开始通过代理 {proxy_hint} 拉取数据…")
        else:
            self._log("INFO", f"[{bvid}] 开始直连拉取数据…")
        try:
            info = bilibili_api.get_video_info(bvid)
            if not info:
                self._log("WARNING", f"[{bvid}] 获取视频信息失败（返回 None）")
                return False
        except Exception as e:
            self._log("ERROR", f"[{bvid}] 获取视频信息异常: {e}")
            return False

        stat = info.get("stat", {})
        self._log(
            "DEBUG",
            f"[{bvid}] API响应 播放:{stat.get('view', 0)} 点赞:{stat.get('like', 0)} "
            f"投币:{stat.get('coin', 0)} 收藏:{stat.get('favorite', 0)} "
            f"弹幕:{stat.get('danmaku', 0)} 评论:{stat.get('reply', 0)}",
        )

        with gui._data_lock:
            owner = info.get("owner", {})
            video["title"] = info.get("title", video.get("title", ""))
            video["author"] = owner.get("name", video.get("author", ""))
            video["pic"] = info.get("pic", video.get("pic", ""))
            video["_cid"] = info.get("cid", 0)  # 存 cid 供弹幕拉取使用
            owner_id = owner.get("mid", 0)
            if owner_id:
                _save_up_data(owner_id)
            video["view_count"] = stat.get("view", video.get("view_count", 0))
            video["like_count"] = stat.get("like", video.get("like_count", 0))
            video["coin_count"] = stat.get("coin", video.get("coin_count", 0))
            video["share_count"] = stat.get("share", video.get("share_count", 0))
            video["favorite_count"] = stat.get("favorite", video.get("favorite_count", 0))
            video["danmaku_count"] = stat.get("danmaku", video.get("danmaku_count", 0))
            video["reply_count"] = stat.get("reply", video.get("reply_count", 0))

        with gui._data_lock:
            try:
                cid = info.get("cid", 0)
                if cid:
                    viewers = bilibili_api.get_video_viewers(bvid, cid)
                    if viewers:
                        self._log(
                            "DEBUG",
                            f"[{bvid}] 在线响应 总:{viewers.get('total', '0')} 网页:{viewers.get('count', '0')}",
                        )
                        video["viewers_total_raw"] = viewers.get("total", "0")
                        video["viewers_web_raw"] = viewers.get("count", "0")
                        video["viewers_total"] = _parse_viewer_count(viewers.get("total", "0"))
                        video["viewers_web"] = _parse_viewer_count(viewers.get("count", "0"))
                        video["viewers_app"] = max(0, video["viewers_total"] - video["viewers_web"])
                    else:
                        video["viewers_total"] = video.get("viewers_total", 0)
                        video["viewers_web"] = video.get("viewers_web", 0)
                        video["viewers_app"] = video.get("viewers_app", 0)
                else:
                    video["viewers_total"] = video.get("viewers_total", 0)
                    video["viewers_web"] = video.get("viewers_web", 0)
                    video["viewers_app"] = video.get("viewers_app", 0)
            except Exception as e:
                self._log("WARNING", f"[{bvid}] 获取在线人数失败: {e}")
                video["viewers_total"] = video.get("viewers_total", 0)
                video["viewers_web"] = video.get("viewers_web", 0)
                video["viewers_app"] = video.get("viewers_app", 0)

        ts = datetime.now()
        with gui._data_lock:
            if bvid not in gui.history_data:
                gui.history_data[bvid] = []
            gui.history_data[bvid].append((ts, video["view_count"]))
            if len(gui.history_data[bvid]) > 1000:
                gui.history_data[bvid] = gui.history_data[bvid][-800:]

        try:
            if bvid in gui.video_dbs:
                rec = MonitorRecord(
                    bvid=bvid,
                    timestamp=ts.isoformat(),
                    view_count=video["view_count"],
                    like_count=video["like_count"],
                    coin_count=video["coin_count"],
                    share_count=video["share_count"],
                    favorite_count=video["favorite_count"],
                    danmaku_count=video["danmaku_count"],
                    reply_count=video["reply_count"],
                    viewers_total=video.get("viewers_total", 0),
                    viewers_web=video.get("viewers_web", 0),
                    viewers_app=video.get("viewers_app", 0),
                )
                gui.video_dbs[bvid].add_monitor_record(rec)
                gui._save_weekly_score(bvid, video, ts.isoformat())
                gui._save_yearly_score(bvid, video, ts.isoformat())
        except Exception as e:
            self._log("WARNING", f"[{bvid}] 写数据库失败: {e}")

        try:
            db.sync_monitor_record(
                bvid,
                {
                    "timestamp": ts.isoformat(),
                    "view_count": video["view_count"],
                    "like_count": video["like_count"],
                    "coin_count": video["coin_count"],
                    "share_count": video["share_count"],
                    "favorite_count": video["favorite_count"],
                    "danmaku_count": video["danmaku_count"],
                    "reply_count": video["reply_count"],
                    "viewers_total": video.get("viewers_total", 0),
                    "viewers_web": video.get("viewers_web", 0),
                    "viewers_app": video.get("viewers_app", 0),
                },
            )
        except Exception as e:
            self._log("WARNING", f"[{bvid}] 同步中央监控记录失败: {e}")

        return True

    def _do_predict(self, gui, bvid, video):
        """执行播放量预测"""
        try:
            return _predict_single(gui, bvid, video)
        except Exception as e:
            self._log("ERROR", f"[{bvid}] 预测失败: {e}")
            return None

    def _do_post_fetch(self, bvid, video, gui, result):
        """预测完成后的日志、同步和 UI 回调"""
        self._log(
            "DEBUG", f"[{bvid}] 拉取完成 播放:{video.get('view_count', 0):,} 预测:{result.get('prediction', 0):,}"
        )

        try:
            db.sync_video_info(bvid, video)
        except Exception as e:
            self._log("WARNING", f"[{bvid}] 同步中央数据库失败: {e}")

        # 后台：增量拉取弹幕（段式 API，只拉新段）
        cid = video.get("_cid", 0)
        if cid:
            threading.Thread(
                target=self._fetch_danmaku_bg, args=(bvid, cid), daemon=True, name=f"dm-{bvid}"
            ).start()

        gui.root.after(0, lambda r=result, v=video: self._on_fetch_done(r, v))

    def _fetch_danmaku_bg(self, bvid, cid):
        """后台拉取新弹幕段并存库。"""
        try:
            from core.bilibili_danmaku import get_danmaku_monitor
            monitor = get_danmaku_monitor()
            video_db = self.gui.video_dbs.get(bvid)
            new_count = monitor.fetch_new_danmaku(bvid, cid, video_db)
            if new_count > 0:
                self._log("INFO", f"[{bvid}] 新增弹幕 {new_count} 条")
        except Exception as e:
            self._log("DEBUG", f"[{bvid}] 弹幕拉取跳过: {e}")

    def _on_fetch_done(self, result, video):
        """在主线程回调：更新 UI（仅当前选中视频触发完整刷新）"""
        gui = self.gui
        bvid = result["bvid"]
        gui.video_list.update_card(video)
        if bvid == gui.selected_bvid:
            # 防抖：50ms 内多次触发只执行最后一次选中视频的完整重绘
            if hasattr(gui, "_selected_debounce") and gui._selected_debounce:
                gui.root.after_cancel(gui._selected_debounce)
            gui._selected_debounce = gui.root.after(
                50,
                lambda r=result, v=video: self._apply_selected_update(r, v),
            )

        # 刷新状态栏（去抖：200ms 内多次触发只更新一次，避免 13 个 worker 同时刷屏）
        now = time.time()
        last_sb = getattr(gui, "_last_sb_update", 0)
        if now - last_sb > 0.2:
            gui._last_sb_update = now
            now_str = datetime.now().strftime("%H:%M:%S")
            gui._sb("last_ref", f"上次刷新: {now_str}")
            gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
        # 重新注册定时器，使倒计时正常显示
        gui._register_video_timer(bvid)

    def _apply_selected_update(self, result, video):
        """对当前选中视频执行完整的预测+详情+图表更新"""
        gui = self.gui
        bvid = result["bvid"]
        if bvid != gui.selected_bvid:
            return
        gui._prediction_done(
            result["prediction"],
            result["current_view"],
            result["growth"],
            result["rate_per_sec"],
            result["success_list"],
            result["fail_list"],
            result["valid"],
            result["total"],
            result.get("surge_info"),
        )
        gui.detail.update_stat_bar(video)
        if gui.detail.current_tab == "📈 播放量趋势":
            if hasattr(gui, "_chart_debounce") and gui._chart_debounce:
                gui.root.after_cancel(gui._chart_debounce)
            gui._chart_debounce = gui.root.after(100, lambda: gui.detail._auto_render_chart())
        elif gui.detail.current_tab == "📋 详细数据":
            gui.detail._fill_detail_text(video)
        elif gui.detail.current_tab == "💬 弹幕":
            gui.detail._refresh_danmaku_display()


# ──────────────────────────────────────────────
#  全局 Worker 管理器（替代旧的 _fetching_set 方案）
# ──────────────────────────────────────────────

# 所有活跃 Worker 实例，key = bvid
_active_workers: dict = {}
_workers_lock = threading.Lock()


def _start_worker(gui, bvid, video, interval, fast_interval=None) -> VideoWorker:
    """启动一个视频的独立 Worker"""
    with _workers_lock:
        if bvid in _active_workers:
            _active_workers[bvid].stop()
        worker = VideoWorker(gui, bvid, video, interval, fast_interval)
        worker.start()
        _active_workers[bvid] = worker
        return worker


def _stop_worker(bvid):
    """停止并移除指定视频的 Worker"""
    with _workers_lock:
        worker = _active_workers.pop(bvid, None)
    if worker:
        worker.stop()
    with _merged_from_db_lock:
        _merged_from_db.discard(bvid)
    # 清理该视频的 OnlineLearner 追踪器，释放内存
    try:
        from algorithms.online_learner import get_online_learner
        get_online_learner().remove_by_prefix(bvid + "/")
    except Exception:
        pass


def _stop_all_workers():
    """停止所有 Worker（应用退出时调用）"""
    with _workers_lock:
        bvids = list(_active_workers.keys())
    for bvid in bvids:
        _stop_worker(bvid)
    # 取消悬而未决的 after ID
    for bvid in bvids:
        worker = _active_workers.get(bvid) if bvid in _active_workers else None
        if worker:
            gui = worker.gui
            if hasattr(gui, "_selected_debounce") and gui._selected_debounce:
                try:
                    gui.root.after_cancel(gui._selected_debounce)
                except Exception:
                    pass
            if hasattr(gui, "_chart_debounce") and gui._chart_debounce:
                try:
                    gui.root.after_cancel(gui._chart_debounce)
                except Exception:
                    pass
            break  # 所有 debounce 共用同一个 gui，只需一次


def _refresh_worker_now(bvid):
    """让指定 Worker 立即执行一次拉取（用于"立即刷新"）"""
    with _workers_lock:
        worker = _active_workers.get(bvid)
    if worker:
        worker.refresh_now()


def _update_worker_interval(bvid, new_interval):
    """运行时更新 Worker 的刷新间隔"""
    with _workers_lock:
        worker = _active_workers.get(bvid)
    if worker:
        worker.update_interval(new_interval)


# ──────────────────────────────────────────────
#  公开 API（保留旧接口，底层接入新 Worker 模型）
# ──────────────────────────────────────────────


def fetch_single_video_data(gui, bvid, callback=None):
    """
    立即触发一次拉取（绕过等待间隔）。
    对应"单视频立即刷新"场景。
    """
    _refresh_worker_now(bvid)
    if callback:
        gui.root.after(0, lambda: callback(bvid))


def fetch_all_video_data(gui, callback=None):
    """
    立即触发所有监控视频的一次拉取。
    对应"立即刷新全部"按钮。
    """
    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        if bvid:
            _refresh_worker_now(bvid)


def auto_predict_video(gui, bvid, callback=None):
    """手动触发单视频预测（由主线程按钮调用）"""
    video = next((v for v in gui.monitored_videos if v.get("bvid") == bvid), None)
    if not video:
        return

    def _worker():
        result = _predict_single(gui, bvid, video)
        gui.root.after(
            0,
            lambda r=result: (
                callback(r)
                if callback
                else gui._prediction_done(
                    r["prediction"],
                    r["current_view"],
                    r["growth"],
                    r["rate_per_sec"],
                    r["success_list"],
                    r["fail_list"],
                    r["valid"],
                    r["total"],
                )
            ),
        )

    threading.Thread(target=_worker, daemon=True).start()


def auto_predict_all(gui):
    """对所有已加载视频运行预测（启动完成后调用一次）"""

    def _worker():
        for video in gui.monitored_videos:
            bvid = video.get("bvid", "")
            if not bvid:
                continue
            _predict_single(gui, bvid, video)

        from ui.theme import C

        gui.root.after(
            0, lambda: gui._sb("status", f"初始预测完成（{len(gui.monitored_videos)} 个视频）", color=C["success"])
        )
        gui.log_panel.add_log("INFO", f"初始预测完成（{len(gui.monitored_videos)} 个视频）")

    threading.Thread(target=_worker, daemon=True).start()


def _load_watch_list_from_db():
    """从数据库加载所有视频 BVid（当配置的 watch_list 为空时兜底）"""
    try:
        from config import DATA_DIR as _data_dir
        import os
        import sqlite3

        db_path = os.path.join(_data_dir, "bilibili_monitor.db")
        if not os.path.exists(db_path):
            return []
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT bvid FROM videos ORDER BY updated_at DESC")
            bvids = [r[0] for r in cur.fetchall() if r[0]]
            if bvids:
                logger.info("从数据库加载 %d 个视频作为 watch_list 兜底", len(bvids))
            return bvids
        finally:
            conn.close()
    except Exception as e:
        logger.debug("从数据库加载 watch_list 失败: %s", e)
        return []


def load_watch_list(gui):
    """启动时加载监控列表，并为每个视频启动独立 Worker"""
    from ui.theme import C
    from config import load_config
    from core import db

    config = load_config()
    watch_list = config.get("watch_list", [])
    if not watch_list:
        watch_list = _load_watch_list_from_db()
    if not watch_list:
        return

    gui._sb("status", f"正在加载 {len(watch_list)} 个监控视频…", color=C["accent"])

    def _worker():
        loaded = 0
        for bvid in watch_list:
            # 去重检查
            with gui._data_lock:
                if any(v.get("bvid") == bvid for v in gui.monitored_videos):
                    continue
            try:
                info = bilibili_api.get_video_info(bvid)
                if not info:
                    continue
                video = gui._map_api_to_video_dict(bvid, info)

                # 获取在线人数
                try:
                    viewers = bilibili_api.get_video_viewers(bvid, info.get("cid", 0))
                    if viewers:
                        video["viewers_total_raw"] = viewers.get("total", "0")
                        video["viewers_web_raw"] = viewers.get("count", "0")
                        video["viewers_total"] = _parse_viewer_count(viewers.get("total", "0"))
                        video["viewers_web"] = _parse_viewer_count(viewers.get("count", "0"))
                        video["viewers_app"] = max(0, video["viewers_total"] - video["viewers_web"])
                except Exception as e:
                    logger.debug("获取视频在线人数失败 %s: %s", bvid, e)

                # 初始化数据库和历史
                try:
                    video_db = db.get_video_db(bvid)
                    gui.video_dbs[bvid] = video_db
                    video_db.save_video_info(video)
                    history = video_db.get_all_records()
                    if history:
                        gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
                except Exception as e:
                    logger.debug("初始化视频数据库失败 %s: %s", bvid, e)

                gui.root.after(0, lambda v=video: gui._restore_video(v))
                loaded += 1
                time.sleep(0.15)
            except Exception as e:
                gui.log_panel.add_log("ERROR", f"加载视频 {bvid} 失败: {e}")

        # 所有视频加载完成后，批量启动独立 Worker
        gui.root.after(0, lambda: _start_all_workers(gui))

        from ui.theme import C as C2

        gui.root.after(
            0, lambda: gui._sb("status", f"已加载 {len(gui.monitored_videos)} 个监控视频", color=C2["success"])
        )

        # 所有视频加载完成后，立即运行初始预测（无需等待首次 API 拉取）
        gui.root.after(100, lambda: auto_predict_all(gui))

    threading.Thread(target=_worker, daemon=True).start()


def _start_all_workers(gui):
    """为 gui.monitored_videos 中所有视频启动独立 Worker"""
    default_interval = getattr(gui, "DEFAULT_INTERVAL", 75)
    fast_interval = getattr(gui, "FAST_INTERVAL", 10)
    get_video_interval = getattr(gui, "_get_video_interval", None)

    gui.log_panel.add_log("INFO", f"系统就绪，{len(gui.monitored_videos)} 个视频监控中（{default_interval}s 刷新间隔）")

    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        if not bvid:
            continue
        # 根据视频当前播放量计算合适的刷新间隔
        interval = get_video_interval(video) if get_video_interval else default_interval
        _start_worker(gui, bvid, video, interval, fast_interval)
