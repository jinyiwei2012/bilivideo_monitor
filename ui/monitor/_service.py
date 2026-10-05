"""集中拉取 + 单飞预测任务 + 生命周期管理 + 公开 API — PyQt6 版

架构：
    - 每 75s 集中拉取所有视频数据（单一定时器）
    - 每个视频一个 supervisor 单飞预测 lane，由拉取完成后分发触发、回调更新 UI
"""

import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

from PyQt6.QtCore import QTimer

# 线程安全的主线程调度 — 从共享模块导入，消除 _service.py 中的重复实现
from ui.invoker import invoke

from core import MonitorRecord, get_bilibili_api, get_db
from utils.ntp_time import record_now
from utils.time_utils import format_ts
from ui.helpers import _parse_viewer_count
from ui.monitor._lifecycle import (
    accepts_tasks,
    admit_runtime_creation,
    begin_stopping,
    drain_registered_tasks,
    start_registered_task,
    use_video_db,
)
from ui.monitor._supervisor import get_task_supervisor

logger = logging.getLogger(__name__)

bilibili_api = get_bilibili_api()
db = get_db()

DEFAULT_FETCH_INTERVAL = 75  # 集中拉取间隔（秒）


@dataclass(frozen=True)
class ObservationTiming:
    """一次播放量观测在 API 响应边界处捕获的时间信息。"""

    observed_at: datetime
    request_started_at: datetime
    rtt_s: float

    @property
    def observed_at_us(self) -> int:
        return round(self.observed_at.timestamp() * 1_000_000)

    @property
    def request_start_us(self) -> int:
        return round(self.request_started_at.timestamp() * 1_000_000)

    @property
    def rtt_us(self) -> int:
        return round(max(0.0, self.rtt_s) * 1_000_000)


# ── 模块级状态 ──
_merged_from_db: set[str] = set()
_merged_from_db_lock = threading.Lock()
_central_fetch_running = False
_central_fetch_lock = threading.Lock()
_central_stop_event = threading.Event()  # 可中断的间隔等待（替代逐秒 sleep）
_precision_watch_manager = None


def _start_runtime_task(gui, target, args=(), name=None):
    """Start a shutdown-aware registered task."""
    return start_registered_task(gui, target, args, name)


# ══════════════════════════════════════════════
#  集中拉取核心
# ══════════════════════════════════════════════


def _log_fetch_route(gui, bvid):
    try:
        proxy_hint = bilibili_api.proxy_manager.peek_proxy()
        if proxy_hint:
            gui.log_panel.add_log("INFO", f"[{bvid}] 通过代理 {proxy_hint} 拉取数据…")
        else:
            gui.log_panel.add_log("INFO", f"[{bvid}] 直连拉取数据…")
    except Exception:
        pass


def _get_video_info(gui, bvid):
    try:
        info = bilibili_api.get_video_info(bvid)
        if not info:
            gui.log_panel.add_log("WARNING", f"[{bvid}] 获取视频信息失败（返回 None）")
            return None
        return info
    except Exception as e:
        gui.log_panel.add_log("ERROR", f"[{bvid}] 获取视频信息异常: {e}")
        return None


def _update_video_fields(gui, video, info, stat):
    owner = info.get("owner", {})
    video["title"] = info.get("title", video.get("title", ""))
    video["author"] = owner.get("name", video.get("author", ""))
    video["pic"] = info.get("pic", video.get("pic", ""))
    video["_cid"] = info.get("cid", 0)
    owner_id = owner.get("mid", 0)
    if owner_id:
        from ui.monitor._prediction import _save_up_data

        _save_up_data(owner_id)
    video["view_count"] = stat.get("view", video.get("view_count", 0))
    video["like_count"] = stat.get("like", video.get("like_count", 0))
    video["coin_count"] = stat.get("coin", video.get("coin_count", 0))
    video["share_count"] = stat.get("share", video.get("share_count", 0))
    video["favorite_count"] = stat.get("favorite", video.get("favorite_count", 0))
    video["danmaku_count"] = stat.get("danmaku", video.get("danmaku_count", 0))
    video["reply_count"] = stat.get("reply", video.get("reply_count", 0))


def _retain_viewer_counts(video):
    video["viewers_total"] = video.get("viewers_total", 0)
    video["viewers_web"] = video.get("viewers_web", 0)
    video["viewers_app"] = video.get("viewers_app", 0)


def _update_video_viewers(gui, bvid, video, info):
    try:
        cid = info.get("cid", 0)
        if not cid:
            _retain_viewer_counts(video)
            return
        viewers = bilibili_api.get_video_viewers(bvid, cid)
        if not viewers:
            _retain_viewer_counts(video)
            return
        gui.log_panel.add_log(
            "DEBUG",
            f"[{bvid}] 在线响应 总:{viewers.get('total', '0')} 网页:{viewers.get('count', '0')}",
        )
        video["viewers_total_raw"] = viewers.get("total", "0")
        video["viewers_web_raw"] = viewers.get("count", "0")
        video["viewers_total"] = _parse_viewer_count(viewers.get("total", "0"))
        video["viewers_web"] = _parse_viewer_count(viewers.get("count", "0"))
        video["viewers_app"] = max(0, video["viewers_total"] - video["viewers_web"])
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 获取在线人数失败: {e}")
        _retain_viewer_counts(video)


def _coerce_observation_timing(timing: ObservationTiming | datetime) -> ObservationTiming:
    if isinstance(timing, ObservationTiming):
        return timing
    return ObservationTiming(timing, timing, 0.0)


def _append_history(gui, bvid, video, timing: ObservationTiming | datetime):
    timing = _coerce_observation_timing(timing)
    if bvid not in gui.history_data:
        gui.history_data[bvid] = []
    gui.history_data[bvid].append((timing.observed_at, video["view_count"]))
    if len(gui.history_data[bvid]) > 1000:
        gui.history_data[bvid] = gui.history_data[bvid][-800:]


def _monitor_record(bvid, video, timing: ObservationTiming | datetime):
    timing = _coerce_observation_timing(timing)
    return MonitorRecord(
        bvid=bvid,
        timestamp=format_ts(timing.observed_at),
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
        observed_at_us=timing.observed_at_us,
        request_start_us=timing.request_start_us,
        rtt_us=timing.rtt_us,
    )


def _save_monitor_record(gui, bvid, video, timing: ObservationTiming | datetime):
    try:
        use_video_db(gui, bvid, lambda video_db: video_db.add_monitor_record(_monitor_record(bvid, video, timing)))
        # 分数改为惰性物化（utils.score_materializer.ensure_scores），不再每抓取写入
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 写数据库失败: {e}")


def _sync_monitor_record(gui, bvid, video, timing: ObservationTiming | datetime):
    from config.runtime_mode import legacy_central_writes_enabled

    if not legacy_central_writes_enabled():
        return
    timing = _coerce_observation_timing(timing)
    try:
        db.sync_monitor_record(
            bvid,
            {
                "timestamp": format_ts(timing.observed_at),
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
                "observed_at_us": timing.observed_at_us,
                "request_start_us": timing.request_start_us,
                "rtt_us": timing.rtt_us,
            },
        )
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 同步中央监控记录失败: {e}")


def _sync_video_info(gui, bvid, video):
    try:
        db.sync_video_info(bvid, video)
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 同步中央视频信息失败: {e}")


def _start_danmaku_fetch(gui, bvid, video):
    cid = video.get("_cid", 0)
    if cid:
        _start_runtime_task(gui, _fetch_danmaku_bg, args=(gui, bvid, cid), name=f"dm-{bvid}")


def _check_video_thresholds(gui, bvid, video):
    try:
        from core.threshold_escalation import check_thresholds

        check_thresholds(gui, bvid, video, video["view_count"])
    except Exception as e:
        logger.debug("阈值检查失败 %s: %s", bvid, e)


def _notify_predictor(gui, bvid, video):
    from ui.monitor._prediction import _predict_single

    get_task_supervisor(gui).submit_prediction(gui, bvid, video, _predict_single)


def _precision_fetch(bvid):
    info = bilibili_api.get_video_info(bvid)
    return info or {}


def _precision_persist(gui, bvid, event):
    use_video_db(gui, bvid, lambda video_db: video_db.insert_crossing_event(dict(event)))


def _start_precision_watch_manager(gui):
    def create() -> None:
        global _precision_watch_manager
        if _precision_watch_manager is not None:
            return
        from config import load_config
        from ui.monitor._precision_watch import PrecisionWatchManager

        cfg = load_config().get("precision_watch", {})
        _precision_watch_manager = PrecisionWatchManager(
            _precision_fetch,
            lambda bvid, event: _precision_persist(gui, bvid, event),
            **cfg,
        )

    admit_runtime_creation(gui, create)


def _offer_precision_watch(bvid, current_views):
    manager = _precision_watch_manager
    if manager is None:
        return
    try:
        from ui.helpers import THRESHOLDS

        for threshold in sorted(THRESHOLDS):
            if current_views < threshold:
                manager.offer(bvid, current_views, threshold)
                break
    except Exception as e:
        logger.debug("精确过线监视派发失败 %s: %s", bvid, e)


def _stop_precision_watch_manager(timeout: float = 0.0):
    global _precision_watch_manager
    manager = _precision_watch_manager
    if manager is not None:
        manager.stop()
        alive = manager.join(timeout)
        if not alive:
            _precision_watch_manager = None
        return alive
    return []


def _fetch_one_video(gui, bvid, video):
    """拉取单个视频数据：API → 更新字段 → 在线人数 → 历史记录 → 写DB → UI 回调 → 分发预测"""
    if not accepts_tasks(gui):
        return
    _log_fetch_route(gui, bvid)
    t0_mono = time.monotonic()
    t0_wall = record_now()
    info = _get_video_info(gui, bvid)
    t1_mono = time.monotonic()
    observed_at = record_now()
    if info is None:
        return
    timing = ObservationTiming(observed_at, t0_wall, t1_mono - t0_mono)
    stat = info.get("stat", {})

    with gui._data_lock:
        _update_video_fields(gui, video, info, stat)

    # 获取在线人数（使用独立 _viewers_lock，减少 _data_lock 争用）
    with gui._viewers_lock:
        _update_video_viewers(gui, bvid, video, info)

    # 写入历史记录
    with gui._data_lock:
        _append_history(gui, bvid, video, timing)

    # 写入视频库
    _save_monitor_record(gui, bvid, video, timing)

    # 同步中央库
    _sync_monitor_record(gui, bvid, video, timing)

    # 同步视频信息到中央库
    use_video_db(gui, bvid, lambda video_db: video_db.save_video_info(video.copy()))
    _sync_video_info(gui, bvid, video)

    # 后台拉取弹幕（登记线程,退出时统一 join）
    _start_danmaku_fetch(gui, bvid, video)

    # 阈值突破检测 + 自动扩档（仅在播放量有效时执行；A1）
    _check_video_thresholds(gui, bvid, video)
    _offer_precision_watch(bvid, video["view_count"])

    # 主线程 UI 更新（通过 _invoker 跨线程安全调用）
    invoke(lambda v=video.copy(), b=bvid: _on_fetch_done(gui, b, v))

    # ── 分发到预测线程 ──
    _notify_predictor(gui, bvid, video)


def _on_fetch_done(gui, bvid, video):
    """单个视频拉取完成 → 更新卡片 + 详情视图"""
    gui.video_list.update_card(video)
    _update_status_bar(gui)
    if bvid == gui.selected_bvid:
        gui.detail.update_stat_bar(video)
        if gui.detail.current_tab == "↗ 播放量趋势":
            if hasattr(gui, "_chart_debounce") and gui._chart_debounce:
                gui._chart_debounce.stop()
            else:
                gui._chart_debounce = QTimer(gui)
                gui._chart_debounce.setSingleShot(True)
                gui._chart_debounce.timeout.connect(lambda: gui.detail._auto_render_chart())
            gui._chart_debounce.start(100)
        elif gui.detail.current_tab == "☰ 详细数据":
            gui.detail._fill_detail_text(video)
        elif gui.detail.current_tab == "♬ 弹幕":
            gui.detail._refresh_danmaku_display()
    gui._register_video_timer(bvid)


def _update_status_bar(gui):
    """统一状态栏刷新（去抖 200ms）"""
    now = time.time()
    last_sb = getattr(gui, "_last_sb_update", 0)
    if now - last_sb > 0.2:
        gui._last_sb_update = now
    invoke(lambda: gui._sb("last_ref", f"上次刷新啦: {datetime.now().strftime('%H:%M:%S')} ♪"))


def _fetch_danmaku_bg(gui, bvid, cid):
    """后台拉取新弹幕段并存库。"""
    try:
        from core.bilibili_danmaku import get_danmaku_monitor

        monitor = get_danmaku_monitor()
        new_count = use_video_db(gui, bvid, lambda video_db: monitor.fetch_new_danmaku(bvid, cid, video_db)) or 0
        if new_count > 0:
            gui.log_panel.add_log("INFO", f"[{bvid}] 新增弹幕 {new_count} 条")
            # A3: 有新增弹幕时更新情绪侧写（同一后台线程, 不阻塞拉取）
            try:
                from ui.danmaku_sentiment import analyze_recent

                analyze_recent(gui, bvid)
            except Exception as e:
                logger.debug("弹幕情绪侧写失败 %s: %s", bvid, e)
    except Exception as e:
        gui.log_panel.add_log("DEBUG", f"[{bvid}] 弹幕拉取跳过: {e}")


def _batch_fetch_all(gui):
    """拉取所有监控视频的数据（有界并发，避免"每视频一个 OS 线程"）"""
    if not accepts_tasks(gui):
        return
    data_lock = getattr(gui, "_data_lock", None)
    if data_lock is None:
        videos = [v for v in list(gui.monitored_videos) if v.get("bvid", "")]
    else:
        with data_lock:
            videos = [v for v in gui.monitored_videos if v.get("bvid", "")]
    if not videos:
        return
    gui.log_panel.add_log("INFO", f"开始集中拉取 {len(videos)} 个视频…")
    try:
        from utils.memory_guard import get_safe_workers

        workers = max(1, min(get_safe_workers(), len(videos)))
    except Exception:
        workers = max(1, min(8, len(videos)))
    supervisor = get_task_supervisor(gui)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch") as pool:
        futures = {pool.submit(_wait_for_coalesced_fetch, supervisor, gui, v["bvid"], v): v["bvid"] for v in videos}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                logger.debug("抓取失败 %s: %s", futures.get(fut, ""), e)
    # 此处在后台线程（fire_and_forget(_loop)）→ 必须经 invoke 回主线程改控件
    invoke(lambda: gui._sb("last_ref", f"上次刷新啦: {datetime.now().strftime('%H:%M:%S')} ♪"))


def _wait_for_coalesced_fetch(supervisor, gui, bvid, video):
    """Submit one BVID fetch and wait for its shared completion signal."""
    completion = supervisor.coalesce_fetch(gui, bvid, video, _fetch_one_video)
    if completion is not None:
        completion.result()


def _start_central_fetcher(gui):
    """启动集中拉取定时器（每 75s 触发一次）"""

    def _loop():
        while True:
            with _central_fetch_lock:
                if not _central_fetch_running:
                    break
            try:
                _batch_fetch_all(gui)
            except Exception as e:
                logger.error("集中拉取出错: %s", e)
            # 可中断等待：停止时立即唤醒，无需逐秒 sleep
            if _central_stop_event.wait(DEFAULT_FETCH_INTERVAL):
                break

    def create() -> None:
        global _central_fetch_running
        with _central_fetch_lock:
            if _central_fetch_running:
                return
            _central_fetch_running = True
        _central_stop_event.clear()
        _start_precision_watch_manager(gui)
        if _start_runtime_task(gui, _loop, name="CentralFetcher") is None:
            with _central_fetch_lock:
                _central_fetch_running = False
            _central_stop_event.set()
            return
        gui.log_panel.add_log("INFO", f"集中拉取已启动，每 {DEFAULT_FETCH_INTERVAL}s 拉取所有视频")

    admit_runtime_creation(gui, create)


def _stop_central_fetcher():
    """停止集中拉取"""
    global _central_fetch_running
    with _central_fetch_lock:
        _central_fetch_running = False
    _central_stop_event.set()  # 唤醒正在等待的拉取循环，立即退出


def _stop_all_workers(gui=None):
    """停止集中拉取和精确监视（应用退出时调用）

    主线程只做零等待存活轮询，避免多个慢任务累计阻塞 Qt 事件循环。未退出的
    owner 保留在各自容器中，由 ``on_exit`` 的后续轮询持续报告并延后资源关闭。
    """
    if gui is not None:
        begin_stopping(gui)
    # Shutdown polls must not accumulate an N × timeout GUI-thread stall.  All
    # owners remain registered until a later zero-wait poll observes completion.
    timeout = 0.0
    if gui is not None:
        gui._workers_stop_requested = True
    _stop_central_fetcher()
    alive = _stop_precision_watch_manager(timeout)
    if gui is not None:
        alive.extend(drain_registered_tasks(gui))
    if alive:
        logger.warning("以下运行时任务未在截止时间内退出: %s", ", ".join(alive))
    return alive


# ══════════════════════════════════════════════
#  公开 API
# ══════════════════════════════════════════════


def fetch_single_video_data(gui, bvid, callback=None):
    """立即触发单个视频的数据拉取"""
    if not accepts_tasks(gui):
        return
    video = None
    if hasattr(gui, "_video_index"):
        video = gui._video_index.get(bvid)
    if video is None:
        with gui._data_lock:
            videos = list(gui.monitored_videos)
        for v in videos:
            if v.get("bvid") == bvid:
                video = v
                break
    if video:
        get_task_supervisor(gui).coalesce_fetch(gui, bvid, video, _fetch_one_video)
    if callback:
        # 用跨线程桥调度回主线程(而非 QTimer.singleShot, 后者在无事件循环的后台线程不触发)
        invoke(lambda: callback(bvid))


def fetch_all_video_data(gui, callback=None):
    """立即触发所有视频的数据拉取"""
    _start_runtime_task(gui, _batch_fetch_all, args=(gui,), name="fetch-all-now")


def auto_predict_all(gui):
    """对所有已加载视频运行预测。"""

    def _worker():
        from ui.monitor._prediction import _predict_single

        with gui._data_lock:
            videos = list(gui.monitored_videos)
        for video in videos:
            if not accepts_tasks(gui):
                return
            bvid = video.get("bvid", "")
            if not bvid:
                continue
            get_task_supervisor(gui).submit_prediction(gui, bvid, video, _predict_single)

        from ui.theme import C

        invoke(
            lambda: gui._sb(
                "status", f"初始预测完成啦!♪ 天依聆听了 {len(gui.monitored_videos)} 个视频的歌声", color=C["success"]
            )
        )
        gui.log_panel.add_log("INFO", f"初始预测完成（{len(gui.monitored_videos)} 个视频）")

    _start_runtime_task(gui, _worker, name="auto-predict")


def _load_watch_list_from_db():
    """从数据库加载所有视频 BVid（当配置的 watch_list 为空时兜底）"""
    try:
        from core.repositories import ReadModelRepository

        bvids = ReadModelRepository().load_watch_bvids()
        if bvids:
            logger.info("从数据库加载 %d 个视频作为 watch_list 兜底", len(bvids))
        return bvids
    except Exception as e:
        logger.debug("从数据库加载 watch_list 失败: %s", e)
        return []


def _attach_viewers(video: dict, bvid: str, info: dict) -> None:
    """补充视频在线人数（失败仅记日志）。"""
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


def _attach_history(gui, bvid: str, video: dict) -> None:
    """初始化视频库并挂载历史数据（失败仅记日志）。"""
    try:
        video_db = db.get_video_db(bvid)
        from ui.monitor._lifecycle import set_video_db

        if not set_video_db(gui, bvid, video_db):
            video_db.close()
            return
        video_db.save_video_info(video)
        history = video_db.get_all_records()
        if history:
            gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
    except Exception as e:
        try:
            from ui.monitor._lifecycle import remove_video_db

            detached_db = remove_video_db(gui, bvid)
            if detached_db is not None:
                detached_db.close()
        except Exception as cleanup_error:
            logger.debug("清理初始化失败的视频数据库 %s 时出错: %s", bvid, cleanup_error)
        logger.debug("初始化视频数据库失败 %s: %s", bvid, e)


def _load_one_monitor(gui, bvid: str) -> bool:
    """加载单个监控视频（元数据 + 在线人数 + 历史）。

    Returns:
        True 表示已加载并注册；False 表示已存在 / 无数据 / 失败
    """
    with gui._data_lock:
        if any(v.get("bvid") == bvid for v in gui.monitored_videos):
            return False
    try:
        info = bilibili_api.get_video_info(bvid)
        if not info:
            return False
        video = gui._map_api_to_video_dict(bvid, info)
        _attach_viewers(video, bvid, info)
        _attach_history(gui, bvid, video)
        invoke(lambda v=video: gui._restore_video(v))
        return True
    except Exception as e:
        gui.log_panel.add_log("ERROR", f"加载视频 {bvid} 失败: {e}")
        return False


def load_watch_list(gui):
    """启动时加载监控列表并启动集中拉取。"""
    from ui.theme import C
    from config import load_config

    config = load_config()
    watch_list = config.get("watch_list", [])
    if not watch_list:
        watch_list = _load_watch_list_from_db()
    if not watch_list:
        return

    gui._sb("status", f"天依正在加载 {len(watch_list)} 个监控视频…像在银河里收集星星 ♪", color=C["accent"])

    def _worker():
        for bvid in watch_list:
            if _load_one_monitor(gui, bvid):
                time.sleep(0.15)

        invoke(lambda: _start_central_fetcher(gui))

        from ui.theme import C as C2

        invoke(
            lambda: gui._sb(
                "status", f"加载完成啦!♪ {len(gui.monitored_videos)} 个视频都在天依身边了", color=C2["success"]
            )
        )

        gui.log_panel.add_log(
            "INFO",
            f"系统就绪，{len(gui.monitored_videos)} 个视频监控中" f"（拉取 {DEFAULT_FETCH_INTERVAL}s，按视频单飞预测）",
        )

        # 启动后立即运行一次初始预测，后续由拉取完成后的单飞任务接管
        invoke(lambda: QTimer.singleShot(100, lambda: auto_predict_all(gui)))

    _start_runtime_task(gui, _worker, name="auto-predict")
