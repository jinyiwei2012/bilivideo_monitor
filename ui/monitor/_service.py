"""集中拉取 + 每视频独立预测线程 + 生命周期管理 + 公开 API — PyQt6 版

架构：
    - 每 75s 集中拉取所有视频数据（单一定时器）
    - 每个视频一个独立预测线程，由拉取完成后分发触发、回调更新 UI
"""

import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PyQt6.QtCore import QTimer

# 线程安全的主线程调度 — 从共享模块导入，消除 _service.py 中的重复实现
from ui.invoker import invoke

from core import bilibili_api, db, MonitorRecord
from utils.thread_utils import fire_and_forget
from utils.time_utils import format_ts
from ui.helpers import _parse_viewer_count

logger = logging.getLogger(__name__)

DEFAULT_FETCH_INTERVAL = 75  # 集中拉取间隔（秒）

# ── 模块级状态 ──
_merged_from_db = set()
_merged_from_db_lock = threading.Lock()
_central_fetch_running = False
_central_fetch_lock = threading.Lock()
_central_stop_event = threading.Event()  # 可中断的间隔等待（替代逐秒 sleep）

_predictors: dict = {}  # bvid → VideoPredictor
_predictors_lock = threading.Lock()

# 即弃型工作线程登记（弹幕拉取、手动拉取、集中拉取线程等），
# 退出时统一 join，避免关闭数据库后仍有线程触碰连接/UI
_adhoc_threads: set = set()
_adhoc_lock = threading.Lock()


def _track_thread(t: threading.Thread):
    """登记一个即弃工作线程，退出清理时 join。返回 t 便于链式调用。"""
    with _adhoc_lock:
        _adhoc_threads.add(t)
    return t


def _untrack_thread(t: threading.Thread):
    """线程自然结束后移除登记（由 wrapper 在 finally 中调用）"""
    with _adhoc_lock:
        _adhoc_threads.discard(t)


def _start_tracked_thread(target, args=(), name=None):
    """启动并登记一个守护线程；线程结束时自动注销登记。

    注意: 线程在 t 赋值后才 start(),因此 wrapper 内引用 t 安全（非晚绑定问题）。
    """

    def _wrapper():
        try:
            target(*args)
        finally:
            _untrack_thread(t)

    t = threading.Thread(target=_wrapper, daemon=True, name=name)
    _track_thread(t)
    t.start()
    return t


# ══════════════════════════════════════════════
#  每视频独立预测线程
# ══════════════════════════════════════════════


class VideoPredictor:
    """每视频独立预测线程：由拉取完成后 notify() 唤醒，执行预测后回调 UI。

    threading.Event 驱动，拉取完成后 notify() → 线程被唤醒 → 预测 → 回调。
    若预测进行中又有新数据到达，标记 pending，当前预测结束后立即再预测一次。
    """

    def __init__(self, gui, bvid, video):
        self.gui = gui
        self.bvid = bvid
        self.video = video  # 引用 gui.monitored_videos 中的同一个 dict
        self._event = threading.Event()
        self._running = True
        self._busy = False
        self._pending = False  # 预测进行中又有新数据到达时置 True
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"Predictor-{bvid}")
        self._thread.start()

    def notify(self):
        """拉取完成 → 唤醒预测线程"""
        self._event.set()

    def stop(self):
        """停止预测线程（最多等待 _PREDICT_STOP_TIMEOUT 秒）

        预测本身不可强杀，超时后记录日志，交由守护线程随进程退出；
        正常路径下 Event 唤醒后线程会在下一个循环入口立即退出。
        """
        self._running = False
        self._event.set()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            logger.warning(
                "预测线程 %s 在 %s 秒内未退出（可能卡在长预测/网络调用），转为守护退出",
                self._thread.name,
                3,
            )

    def _loop(self):
        while self._running:
            self._event.wait()
            self._event.clear()
            if not self._running:
                break
            if self._busy:
                self._pending = True  # 标记：新数据到达，等本次预测完后重跑
                continue
            self._busy = True
            self._pending = False
            try:
                from ui.monitor._prediction import _predict_single

                result = _predict_single(self.gui, self.bvid, self.video)
                if result is not None:
                    invoke(lambda r=result: self._on_done(r))
            except Exception as e:
                logger.debug("预测失败 %s: %s", self.bvid, e)
            finally:
                self._busy = False
                if self._pending and self._running:
                    self._event.set()  # 有 pending 数据，立即再触发一次预测

    def _on_done(self, result):
        """预测完成 → 更新预测面板（仅在选中当前视频时）"""
        gui = self.gui
        if result["bvid"] != gui.selected_bvid:
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
            result.get("bias_info"),
            result.get("eta_info"),
        )


def _ensure_predictor(gui, bvid, video):
    """确保视频有对应的预测线程（幂等）"""
    with _predictors_lock:
        if bvid not in _predictors:
            _predictors[bvid] = VideoPredictor(gui, bvid, video)


def _stop_all_predictors():
    """停止所有预测线程（先收集再锁外 join，避免主线程持锁阻塞 3N 秒）"""
    with _predictors_lock:
        predictors = list(_predictors.values())
        _predictors.clear()
    for predictor in predictors:
        predictor.stop()


def _stop_predictor(bvid):
    """停止单个视频的预测线程（删除视频时调用，避免线程泄漏）"""
    with _predictors_lock:
        predictor = _predictors.pop(bvid, None)
    if predictor is not None:
        predictor.stop()


# ══════════════════════════════════════════════
#  集中拉取核心
# ══════════════════════════════════════════════


def _fetch_one_video(gui, bvid, video):
    """拉取单个视频数据：API → 更新字段 → 在线人数 → 历史记录 → 写DB → UI 回调 → 分发预测"""
    try:
        proxy_hint = bilibili_api.proxy_manager.peek_proxy()
        if proxy_hint:
            gui.log_panel.add_log("INFO", f"[{bvid}] 通过代理 {proxy_hint} 拉取数据…")
        else:
            gui.log_panel.add_log("INFO", f"[{bvid}] 直连拉取数据…")
    except Exception:
        pass

    try:
        info = bilibili_api.get_video_info(bvid)
        if not info:
            gui.log_panel.add_log("WARNING", f"[{bvid}] 获取视频信息失败（返回 None）")
            return
    except Exception as e:
        gui.log_panel.add_log("ERROR", f"[{bvid}] 获取视频信息异常: {e}")
        return

    stat = info.get("stat", {})

    with gui._data_lock:
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

    # 获取在线人数（使用独立 _viewers_lock，减少 _data_lock 争用）
    with gui._viewers_lock:
        try:
            cid = info.get("cid", 0)
            if cid:
                viewers = bilibili_api.get_video_viewers(bvid, cid)
                if viewers:
                    gui.log_panel.add_log(
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
            gui.log_panel.add_log("WARNING", f"[{bvid}] 获取在线人数失败: {e}")
            video["viewers_total"] = video.get("viewers_total", 0)
            video["viewers_web"] = video.get("viewers_web", 0)
            video["viewers_app"] = video.get("viewers_app", 0)

    # 写入历史记录
    ts = datetime.now()
    with gui._data_lock:
        if bvid not in gui.history_data:
            gui.history_data[bvid] = []
        gui.history_data[bvid].append((ts, video["view_count"]))
        if len(gui.history_data[bvid]) > 1000:
            gui.history_data[bvid] = gui.history_data[bvid][-800:]

    # 写入视频库
    try:
        if bvid in gui.video_dbs:
            rec = MonitorRecord(
                bvid=bvid,
                timestamp=format_ts(ts),
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
            # 分数改为惰性物化（utils.score_materializer.ensure_scores），不再每抓取写入
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 写数据库失败: {e}")

    # 同步中央库
    try:
        db.sync_monitor_record(
            bvid,
            {
                "timestamp": format_ts(ts),
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
        gui.log_panel.add_log("WARNING", f"[{bvid}] 同步中央监控记录失败: {e}")

    # 同步视频信息到中央库
    try:
        db.sync_video_info(bvid, video)
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 同步中央视频信息失败: {e}")

    # 后台拉取弹幕（登记线程,退出时统一 join）
    cid = video.get("_cid", 0)
    if cid:
        _start_tracked_thread(_fetch_danmaku_bg, args=(gui, bvid, cid), name=f"dm-{bvid}")

    # 阈值突破检测 + 自动扩档（仅在播放量有效时执行；A1）
    try:
        from core.threshold_escalation import check_thresholds

        check_thresholds(gui, bvid, video, video["view_count"])
    except Exception as e:
        logger.debug("阈值检查失败 %s: %s", bvid, e)

    # 主线程 UI 更新（通过 _invoker 跨线程安全调用）
    invoke(lambda v=video.copy(), b=bvid: _on_fetch_done(gui, b, v))

    # ── 分发到预测线程 ──
    _ensure_predictor(gui, bvid, video)
    with _predictors_lock:
        predictor = _predictors.get(bvid)
    if predictor:
        predictor.notify()


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
        video_db = gui.video_dbs.get(bvid)
        new_count = monitor.fetch_new_danmaku(bvid, cid, video_db)
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
    videos = [v for v in list(gui.monitored_videos) if v.get("bvid", "")]
    if not videos:
        return
    gui.log_panel.add_log("INFO", f"开始集中拉取 {len(videos)} 个视频…")
    try:
        from utils.memory_guard import get_safe_workers

        workers = max(1, min(get_safe_workers(), len(videos)))
    except Exception:
        workers = max(1, min(8, len(videos)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch") as pool:
        futures = {pool.submit(_fetch_one_video, gui, v["bvid"], v): v["bvid"] for v in videos}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                logger.debug("抓取失败 %s: %s", futures.get(fut, ""), e)
    gui._sb("last_ref", f"上次刷新啦: {datetime.now().strftime('%H:%M:%S')} ♪")


def _start_central_fetcher(gui):
    """启动集中拉取定时器（每 75s 触发一次）"""
    global _central_fetch_running
    with _central_fetch_lock:
        if _central_fetch_running:
            return
        _central_fetch_running = True
    _central_stop_event.clear()

    gui.log_panel.add_log("INFO", f"集中拉取已启动，每 {DEFAULT_FETCH_INTERVAL}s 拉取所有视频")

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

    fire_and_forget(_loop, name="CentralFetcher")


def _stop_central_fetcher():
    """停止集中拉取"""
    global _central_fetch_running
    with _central_fetch_lock:
        _central_fetch_running = False
    _central_stop_event.set()  # 唤醒正在等待的拉取循环，立即退出


def _stop_all_workers():
    """停止集中拉取 + 所有预测线程 + 登记的即弃线程（应用退出时调用）

    每类线程有界 join：预测线程 3s、即弃线程 2s；超时记录日志，
    由守护线程属性保证进程可正常退出，避免数据库关闭后线程越界访问。
    """
    _stop_central_fetcher()
    _stop_all_predictors()

    # join 登记的即弃线程（弹幕拉取、fetch-now）
    with _adhoc_lock:
        threads = list(_adhoc_threads)
    alive = []
    for t in threads:
        t.join(timeout=2)
        if t.is_alive():
            alive.append(t.name)
    if alive:
        logger.warning("以下工作线程未在 2s 内退出,转为守护退出: %s", ", ".join(alive))
    with _adhoc_lock:
        _adhoc_threads.clear()


# ══════════════════════════════════════════════
#  公开 API
# ══════════════════════════════════════════════


def fetch_single_video_data(gui, bvid, callback=None):
    """立即触发单个视频的数据拉取"""
    video = None
    if hasattr(gui, "_video_index"):
        video = gui._video_index.get(bvid)
    if video is None:
        for v in gui.monitored_videos:
            if v.get("bvid") == bvid:
                video = v
                break
    if video:
        _start_tracked_thread(_fetch_one_video, args=(gui, bvid, video), name=f"fetch-now-{bvid}")
    if callback:
        # 用跨线程桥调度回主线程(而非 QTimer.singleShot, 后者在无事件循环的后台线程不触发)
        invoke(lambda: callback(bvid))


def fetch_all_video_data(gui, callback=None):
    """立即触发所有视频的数据拉取"""
    fire_and_forget(_batch_fetch_all, gui, name="fetch-all-now")


def auto_predict_all(gui):
    """对所有已加载视频运行预测（启动后调用一次，后续由每视频预测线程接管）"""

    def _worker():
        from ui.monitor._prediction import _predict_single

        for video in gui.monitored_videos:
            bvid = video.get("bvid", "")
            if not bvid:
                continue
            _predict_single(gui, bvid, video)

        from ui.theme import C

        invoke(
            lambda: gui._sb(
                "status", f"初始预测完成啦!♪ 天依聆听了 {len(gui.monitored_videos)} 个视频的歌声", color=C["success"]
            )
        )
        gui.log_panel.add_log("INFO", f"初始预测完成（{len(gui.monitored_videos)} 个视频）")

    fire_and_forget(_worker, name="auto-predict")


def _load_watch_list_from_db():
    """从数据库加载所有视频 BVid（当配置的 watch_list 为空时兜底）"""
    try:
        from config import DATA_DIR as _data_dir
        import os
        import sqlite3

        db_path = os.path.join(_data_dir, "bilibili_monitor.db")
        if not os.path.exists(db_path):
            return []
        conn = sqlite3.connect(db_path, check_same_thread=False)
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
        gui.video_dbs[bvid] = video_db
        video_db.save_video_info(video)
        history = video_db.get_all_records()
        if history:
            gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
    except Exception as e:
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
    """启动时加载监控列表，创建每视频预测线程，启动集中拉取"""
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

        # ── 所有视频加载完成 → 创建每视频预测线程 + 启动集中拉取 ──
        for video in gui.monitored_videos:
            bvid = video.get("bvid", "")
            if bvid:
                _ensure_predictor(gui, bvid, video)

        invoke(lambda: _start_central_fetcher(gui))

        from ui.theme import C as C2

        invoke(
            lambda: gui._sb(
                "status", f"加载完成啦!♪ {len(gui.monitored_videos)} 个视频都在天依身边了", color=C2["success"]
            )
        )

        gui.log_panel.add_log(
            "INFO",
            f"系统就绪，{len(gui.monitored_videos)} 个视频监控中"
            f"（拉取 {DEFAULT_FETCH_INTERVAL}s，每视频独立预测线程）",
        )

        # 启动后立即运行一次初始预测（后续由每视频线程在拉取完成后接管）
        invoke(lambda: QTimer.singleShot(100, lambda: auto_predict_all(gui)))

    fire_and_forget(_worker, name="auto-predict")
