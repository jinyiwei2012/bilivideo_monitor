"""
监控业务逻辑模块 - 独立 Worker 线程模型
每个视频一个独立线程，自主管刷新间隔，互不阻塞、互不干扰。
"""

import threading
import time
import logging
from datetime import datetime
from algorithms.registry import AlgorithmRegistry
from core import bilibili_api, db, MonitorRecord, PredictionRecord, notification_manager
from utils.time_utils import normalize_timestamp, safe_datetime
from ui.helpers import (
    THRESHOLDS,
    THRESHOLD_NAMES,
    _parse_viewer_count,
)

logger = logging.getLogger(__name__)

# 限制并发预测数量，防止 GIL 饥饿导致主线程卡顿
_prediction_semaphore = threading.Semaphore(2)

# 已从 DB 完成历史合并的视频集合（后续循环中内存数据始终 >= DB，跳过全量读取）
_merged_from_db = set()

# UP主数据库实例 & 拉取频率控制（每 UP主 每小时最多拉取一次）
_up_db = None
_last_up_fetch_time = {}  # uid -> time.time

# 已通知的阈值追踪，防止同一阈值的重复推送
_notified_thresholds = {}  # bvid -> set of threshold values

# ──────────────────────────────────────────────
#  内部工具
# ──────────────────────────────────────────────


def _save_predictions_to_db(gui, bvid, current_view, results):
    """将各算法的阈值预测结果写入视频数据库"""
    video_db = gui.video_dbs.get(bvid)
    if not video_db:
        return
    for name, r in results.items():
        if name == "_weighted" or "error" in r:
            continue
        metadata = r.get("metadata", {})
        threshold_preds = metadata.get("threshold_predictions", [])
        confidence = r.get("confidence", 0)

        # 获取额外的元数据
        predicted_hours = metadata.get("predicted_hours", 0)
        velocity = metadata.get("velocity", 0)
        # 将 metadata 字典转换为 JSON 字符串
        import json

        metadata_str = json.dumps(metadata, ensure_ascii=False)

        for tp in threshold_preds:
            minutes = tp.get("minutes", 0)
            pred_seconds = int(minutes * 60) if minutes else 0
            pred_time = tp.get("name", "")

            rec = PredictionRecord(
                bvid=bvid,
                algorithm=name,
                algorithm_id=name,
                target_threshold=tp.get("threshold", 0),
                predicted_seconds=pred_seconds,
                predicted_time=pred_time,
                confidence=confidence,
                current_views=current_view,
                metadata=metadata_str,  # 存储 JSON 字符串
                predicted_hours=predicted_hours,
                current_velocity=velocity,
            )
            try:
                video_db.add_prediction(rec)
            except Exception as e:
                gui.log_panel.add_log("WARNING", f"保存预测记录失败 {bvid}/{name}: {e}")


def _merge_history(gui, bvid: str) -> list:
    """合并内存历史与数据库历史，同步写回 gui.history_data 确保图表数据完整

    优化：首次从 DB 全量合并后，后续循环跳过 DB 读取（内存数据始终 >= DB）。
    """
    current_view = next((v.get("view_count", 0) for v in gui.monitored_videos if v.get("bvid") == bvid), 0)
    with gui._data_lock:
        history = list(gui.history_data.get(bvid, []))

    if bvid not in _merged_from_db:
        try:
            if bvid in gui.video_dbs:
                db_hist = gui.video_dbs[bvid].get_all_records()
                if db_hist:

                    def _norm(ts):
                        """统一时间戳格式用于去重比较"""
                        _, _, ts_str = normalize_timestamp(ts)
                        return ts_str

                    existing_ts = {_norm(h[0]) for h in history}
                    for row in db_hist:
                        ts_str = _norm(row["timestamp"])
                        if ts_str not in existing_ts:
                            history.append((row["timestamp"], row["view_count"]))
        except Exception as e:
            logger.warning(f"合并历史记录失败 {bvid}: {e}")
        _merged_from_db.add(bvid)

    history.sort(key=lambda x: _to_dt(x[0]))

    if len(history) < 2:
        now = datetime.now()
        history = [(now, current_view), (now, current_view)]

    # 同步回 gui.history_data，让图表也能看到合并后的完整数据
    with gui._data_lock:
        gui.history_data[bvid] = [(ts, v) for ts, v in history]

    return history


def _to_dt(t):
    """统一时间戳转为 datetime"""
    return safe_datetime(t)


def _get_up_db():
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
        last_ts, last_v = _to_dt(history[-1][0]), history[-1][1]
        dt_sec = (last_ts - first_ts).total_seconds()
        if dt_sec > 0 and last_v > first_v:
            return (last_v - first_v) / dt_sec
    except Exception as e:
        logger.debug("计算增长率失败: %s", e)
    return 0.0


def _predict_single(gui, bvid, video) -> dict:
    """在 worker 线程中对单个视频运行预测（纯函数，无 UI 调用）"""
    with _prediction_semaphore:
        current_view = video.get("view_count", 0)
        history = _merge_history(gui, bvid)

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
                meta = r.get("metadata", {})
                predicted_hours = meta.get("predicted_hours", 0)
                success_list.append(
                    (
                        name,
                        r["prediction"],
                        r["weight"],
                        r["confidence"],
                        predicted_hours,
                    )
                )

        growth = w_pred - current_view
        rate_per_sec = _calc_growth_rate(history)

        # 在线学习反馈
        _online_learning_feedback(gui, bvid, results, current_view)
        # 图神经网络更新（内部缓存边，无变更时跳过重建）
        _update_video_graph(gui, bvid, video)
        # 写数据库
        _save_predictions_to_db(gui, bvid, current_view, results)

        result = {
            "bvid": bvid,
            "prediction": w_pred,
            "current_view": current_view,
            "growth": max(0, growth),
            "rate_per_sec": rate_per_sec,
            "success_list": success_list,
            "fail_list": fail_list,
            "valid": weighted.get("valid_algorithms", 0),
            "total": weighted.get("total_algorithms", 0),
        }
        with gui._data_lock:
            gui.prediction_results[bvid] = result
        return result


def _online_learning_feedback(gui, bvid, results, actual_view):
    try:
        from algorithms.online_learner import get_online_learner

        prev = gui.prediction_results.get(bvid)
        # 仅在播放量实际发生变化时才反馈，避免静止期虚高准确率
        if prev and actual_view > 0 and actual_view != prev.get("current_view", actual_view):
            learner = get_online_learner()
            learner.register(bvid + "/_weighted")
            learner.update(bvid + "/_weighted", predicted=prev["prediction"], actual=actual_view)
            for name, pred_val, _, _, _ in prev.get("success_list", []):
                algo_key = bvid + "/" + name
                learner.register(algo_key)
                learner.update(algo_key, predicted=pred_val, actual=actual_view)
    except Exception as e:
        logger.debug("在线学习反馈失败: %s", e)


def _update_video_graph(gui, bvid, video):
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

            try:
                self._fetch_and_predict()
            except Exception as e:
                logger.exception("[%s] _fetch_and_predict 异常: %s", self.bvid, e)
                with self._fetching_lock:
                    self._fetching = False

            # 分段睡眠，支持中途停止检查
            waited = 0
            step = 1.0  # 每步最多睡 1 秒，便于及时响应 stop
            while waited < interval and not self._stop_event.is_set():
                sleep_for = min(step, interval - waited)
                time.sleep(sleep_for)
                waited += sleep_for

    def _fetch_and_predict(self):  # noqa: C901
        """在 worker 线程中执行一次完整的拉取 + 预测"""
        bvid = self.bvid
        video = self.video
        gui = self.gui

        # 防止同一视频的并发拉取
        with self._fetching_lock:
            if self._fetching:
                self._log("DEBUG", f"[{bvid}] 上次拉取尚未完成，跳过本次")
                return
            self._fetching = True

        self._log("DEBUG", f"[{bvid}] 开始拉取数据…")
        # 记录当前使用的代理（脱敏显示协议+IP前3位）
        proxy_hint = bilibili_api.proxy_manager.peek_proxy()
        if proxy_hint:
            self._log("INFO", f"[{bvid}] 开始通过代理 {proxy_hint} 拉取数据…")
        else:
            self._log("INFO", f"[{bvid}] 开始直连拉取数据…")
        try:
            info = bilibili_api.get_video_info(bvid)
            if not info:
                self._log("WARNING", f"[{bvid}] 获取视频信息失败（返回 None）")
                with self._fetching_lock:
                    self._fetching = False
                return
        except Exception as e:
            self._log("ERROR", f"[{bvid}] 获取视频信息异常: {e}")
            with self._fetching_lock:
                self._fetching = False
            return

        # ── 网络响应日志 ────────────────────────────
        stat = info.get("stat", {})
        self._log(
            "DEBUG",
            f"[{bvid}] API响应 播放:{stat.get('view', 0)} 点赞:{stat.get('like', 0)} "
            f"投币:{stat.get('coin', 0)} 收藏:{stat.get('favorite', 0)} "
            f"弹幕:{stat.get('danmaku', 0)} 评论:{stat.get('reply', 0)}",
        )

        # ── 更新视频字段 ──────────────────────────
        owner = info.get("owner", {})
        video["title"] = info.get("title", video.get("title", ""))
        video["author"] = owner.get("name", video.get("author", ""))
        video["pic"] = info.get("pic", video.get("pic", ""))
        # 自动保存 UP主 数据到数据库（每小时最多一次）
        owner_id = owner.get("mid", 0)
        if owner_id:
            _save_up_data(owner_id)
        old_views = video.get("view_count", 0)
        video["view_count"] = stat.get("view", video.get("view_count", 0))
        video["like_count"] = stat.get("like", video.get("like_count", 0))
        video["coin_count"] = stat.get("coin", video.get("coin_count", 0))
        video["share_count"] = stat.get("share", video.get("share_count", 0))
        video["favorite_count"] = stat.get("favorite", video.get("favorite_count", 0))
        video["danmaku_count"] = stat.get("danmaku", video.get("danmaku_count", 0))
        video["reply_count"] = stat.get("reply", video.get("reply_count", 0))

        # ── 在线人数 ─────────────────────────────
        try:
            cid = info.get("cid", 0)
            if cid:
                viewers = bilibili_api.get_video_viewers(bvid, cid)
                if viewers:
                    self._log(
                        "DEBUG", f"[{bvid}] 在线响应 总:{viewers.get('total', '0')} 网页:{viewers.get('count', '0')}"
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

        # ── 阈值突破检测 ──────────────────────────
        new_views = video["view_count"]
        if new_views > old_views:
            try:
                if bvid not in _notified_thresholds:
                    _notified_thresholds[bvid] = set()
                # 首次拉取（old_views=0）时，标记所有已超越的阈值，避免首次加载爆通知
                if old_views == 0:
                    for thr in THRESHOLDS:
                        if thr <= new_views:
                            _notified_thresholds[bvid].add(thr)
                else:
                    for i, thr in enumerate(THRESHOLDS):
                        if old_views < thr <= new_views and thr not in _notified_thresholds[bvid]:
                            _notified_thresholds[bvid].add(thr)
                            name = THRESHOLD_NAMES[i] if i < len(THRESHOLD_NAMES) else f"{thr:,}"
                            title = video.get("title", bvid)[:30]
                            notification_manager.send_threshold_notification(bvid, title, thr, new_views)
                            self._log("INFO", f"[{bvid}] 阈值突破 {name}！当前播放量: {new_views:,}")
            except Exception as e:
                logger.debug("阈值突破检测失败: %s", e)

        # ── 历史记录 ─────────────────────────────
        ts = datetime.now()
        with gui._data_lock:
            if bvid not in gui.history_data:
                gui.history_data[bvid] = []
            gui.history_data[bvid].append((ts, video["view_count"]))
            # 防止内存无界增长，超过 3000 时保留最近 2800 条（缓降，避免一次丢掉 1000 条）
            if len(gui.history_data[bvid]) > 3000:
                gui.history_data[bvid] = gui.history_data[bvid][-2800:]

        # ── 写数据库 ─────────────────────────────
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

        # 同步当前监控记录到中央数据库（避免全量扫描）
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

        # ── 预测 ─────────────────────────────────
        try:
            result = _predict_single(gui, bvid, video)
        except Exception as e:
            self._log("ERROR", f"[{bvid}] 预测失败: {e}")
            with self._fetching_lock:
                self._fetching = False
            return

        self._log(
            "DEBUG", f"[{bvid}] 拉取完成 播放:{video.get('view_count', 0):,} 预测:{result.get('prediction', 0):,}"
        )

        # 同步视频信息到中央数据库（从内存直接写入，避免新建 DB 连接 + 重复读盘）
        try:
            db.sync_video_info(bvid, video)
        except Exception as e:
            self._log("WARNING", f"[{bvid}] 同步中央数据库失败: {e}")

        # ── 回调主线程更新 UI ─────────────────────
        #    仅在选中该视频时触发完整 UI 更新；其他视频静默后台更新
        gui.root.after(0, lambda r=result, v=video: self._on_fetch_done(r, v))

        with self._fetching_lock:
            self._fetching = False

    def _on_fetch_done(self, result, video):
        """在主线程回调：更新 UI（仅当前选中视频触发完整刷新）"""
        gui = self.gui
        bvid = result["bvid"]
        if bvid == gui.selected_bvid:
            gui._prediction_done(
                result["prediction"],
                result["current_view"],
                result["growth"],
                result["rate_per_sec"],
                result["success_list"],
                result["fail_list"],
                result["valid"],
                result["total"],
            )
        gui.video_list.update_card(video)
        if bvid == gui.selected_bvid:
            gui.detail.update_stat_bar(video)
            if gui.detail.current_tab == "📈 播放量趋势":
                # 防抖：100ms 内多次触发只重绘一次
                if hasattr(gui, "_chart_debounce") and gui._chart_debounce:
                    gui.root.after_cancel(gui._chart_debounce)

                gui._chart_debounce = gui.root.after(100, lambda: gui.detail._auto_render_chart())
            elif gui.detail.current_tab == "📋 详细数据":
                gui.detail._fill_detail_text(video)

        # 刷新状态栏（上次刷新时间、视频计数）
        now_str = datetime.now().strftime("%H:%M:%S")
        gui._sb("last_ref", f"上次刷新: {now_str}")
        gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
        # 重新注册定时器，使倒计时正常显示
        gui._register_video_timer(bvid)


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


def _stop_all_workers():
    """停止所有 Worker（应用退出时调用）"""
    with _workers_lock:
        bvids = list(_active_workers.keys())
    for bvid in bvids:
        _stop_worker(bvid)


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


def load_watch_list(gui):
    """启动时加载监控列表，并为每个视频启动独立 Worker"""
    from ui.theme import C
    from config import load_config
    from core import db

    config = load_config()
    watch_list = config.get("watch_list", [])
    if not watch_list:
        return

    gui._sb("status", f"正在加载 {len(watch_list)} 个监控视频…", color=C["accent"])

    def _worker():
        loaded = 0
        for bvid in watch_list:
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
        interval = get_video_interval(video) if get_video_interval else default_interval
        _start_worker(gui, bvid, video, interval, fast_interval)
