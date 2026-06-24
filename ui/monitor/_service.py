"""集中拉取 + 每视频独立预测线程 + 生命周期管理 + 公开 API — PyQt6 版

架构：
    - 每 75s 集中拉取所有视频数据（单一定时器）
    - 每个视频一个独立预测线程，由拉取完成后分发触发、回调更新 UI
"""
import threading
import time
import logging
from datetime import datetime

from PyQt6.QtCore import QTimer

logger = logging.getLogger(__name__)

# 线程安全的主线程调度 — 从共享模块导入，消除 _service.py 中的重复实现
from ui.invoker import invoke

from core import bilibili_api, db, MonitorRecord
from ui.helpers import _parse_viewer_count

DEFAULT_FETCH_INTERVAL = 75  # 集中拉取间隔（秒）

# ── 模块级状态 ──
_merged_from_db = set()
_merged_from_db_lock = threading.Lock()
_central_fetch_running = False
_central_fetch_lock = threading.Lock()

_predictors: dict = {}          # bvid → VideoPredictor
_predictors_lock = threading.Lock()


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
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"Predictor-{bvid}"
        )
        self._thread.start()

    def notify(self):
        """拉取完成 → 唤醒预测线程"""
        self._event.set()

    def stop(self):
        """停止预测线程"""
        self._running = False
        self._event.set()
        self._thread.join(timeout=3)

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
        )


def _ensure_predictor(gui, bvid, video):
    """确保视频有对应的预测线程（幂等）"""
    with _predictors_lock:
        if bvid not in _predictors:
            _predictors[bvid] = VideoPredictor(gui, bvid, video)


def _stop_all_predictors():
    """停止所有预测线程"""
    with _predictors_lock:
        for predictor in list(_predictors.values()):
            predictor.stop()
        _predictors.clear()


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
        gui.log_panel.add_log("WARNING", f"[{bvid}] 写数据库失败: {e}")

    # 同步中央库
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
        gui.log_panel.add_log("WARNING", f"[{bvid}] 同步中央监控记录失败: {e}")

    # 同步视频信息到中央库
    try:
        db.sync_video_info(bvid, video)
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"[{bvid}] 同步中央视频信息失败: {e}")

    # 后台拉取弹幕
    cid = video.get("_cid", 0)
    if cid:
        threading.Thread(
            target=_fetch_danmaku_bg, args=(gui, bvid, cid), daemon=True, name=f"dm-{bvid}"
        ).start()

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
        if gui.detail.current_tab == "📈 播放量趋势":
            if hasattr(gui, "_chart_debounce") and gui._chart_debounce:
                gui._chart_debounce.stop()
            else:
                gui._chart_debounce = QTimer(gui)
                gui._chart_debounce.setSingleShot(True)
                gui._chart_debounce.timeout.connect(lambda: gui.detail._auto_render_chart())
            gui._chart_debounce.start(100)
        elif gui.detail.current_tab == "📋 详细数据":
            gui.detail._fill_detail_text(video)
        elif gui.detail.current_tab == "💬 弹幕":
            gui.detail._refresh_danmaku_display()
    gui._register_video_timer(bvid)


def _update_status_bar(gui):
    """统一状态栏刷新（去抖 200ms）"""
    now = time.time()
    last_sb = getattr(gui, "_last_sb_update", 0)
    if now - last_sb > 0.2:
        gui._last_sb_update = now
        gui._sb("last_ref", f"上次刷新: {datetime.now().strftime('%H:%M:%S')}")
        gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")


def _fetch_danmaku_bg(gui, bvid, cid):
    """后台拉取新弹幕段并存库。"""
    try:
        from core.bilibili_danmaku import get_danmaku_monitor
        monitor = get_danmaku_monitor()
        video_db = gui.video_dbs.get(bvid)
        new_count = monitor.fetch_new_danmaku(bvid, cid, video_db)
        if new_count > 0:
            gui.log_panel.add_log("INFO", f"[{bvid}] 新增弹幕 {new_count} 条")
    except Exception as e:
        gui.log_panel.add_log("DEBUG", f"[{bvid}] 弹幕拉取跳过: {e}")


def _batch_fetch_all(gui):
    """拉取所有监控视频的数据（并发）"""
    videos = list(gui.monitored_videos)
    if not videos:
        return
    gui.log_panel.add_log("INFO", f"开始集中拉取 {len(videos)} 个视频…")
    threads = []
    for video in videos:
        bvid = video.get("bvid", "")
        if not bvid:
            continue
        t = threading.Thread(
            target=_fetch_one_video, args=(gui, bvid, video),
            daemon=True, name=f"fetch-{bvid}"
        )
        t.start()
        threads.append(t)
        time.sleep(0.2)
    for t in threads:
        t.join(timeout=60)
    gui._sb("last_ref", f"上次刷新: {datetime.now().strftime('%H:%M:%S')}")


def _start_central_fetcher(gui):
    """启动集中拉取定时器（每 75s 触发一次）"""
    global _central_fetch_running
    with _central_fetch_lock:
        if _central_fetch_running:
            return
        _central_fetch_running = True

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
            for _ in range(DEFAULT_FETCH_INTERVAL):
                with _central_fetch_lock:
                    if not _central_fetch_running:
                        break
                time.sleep(1)

    threading.Thread(target=_loop, daemon=True, name="CentralFetcher").start()


def _stop_central_fetcher():
    """停止集中拉取"""
    global _central_fetch_running
    with _central_fetch_lock:
        _central_fetch_running = False


def _stop_all_workers():
    """停止集中拉取 + 所有预测线程（应用退出时调用）"""
    _stop_central_fetcher()
    _stop_all_predictors()


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
        threading.Thread(
            target=_fetch_one_video, args=(gui, bvid, video),
            daemon=True, name=f"fetch-now-{bvid}"
        ).start()
    if callback:
        QTimer.singleShot(0, lambda: callback(bvid))


def fetch_all_video_data(gui, callback=None):
    """立即触发所有视频的数据拉取"""
    threading.Thread(target=_batch_fetch_all, args=(gui,), daemon=True, name="fetch-all-now").start()


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
        invoke(lambda: gui._sb("status", f"初始预测完成（{len(gui.monitored_videos)} 个视频）", color=C["success"]))
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
    """启动时加载监控列表，创建每视频预测线程，启动集中拉取"""
    from ui.theme import C
    from config import load_config
    from core import db, bilibili_api
    from ui.helpers import _parse_viewer_count

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
            with gui._data_lock:
                if any(v.get("bvid") == bvid for v in gui.monitored_videos):
                    continue
            try:
                info = bilibili_api.get_video_info(bvid)
                if not info:
                    continue
                video = gui._map_api_to_video_dict(bvid, info)

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

                try:
                    video_db = db.get_video_db(bvid)
                    gui.video_dbs[bvid] = video_db
                    video_db.save_video_info(video)
                    history = video_db.get_all_records()
                    if history:
                        gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
                except Exception as e:
                    logger.debug("初始化视频数据库失败 %s: %s", bvid, e)

                invoke(lambda v=video: gui._restore_video(v))
                loaded += 1
                time.sleep(0.15)
            except Exception as e:
                gui.log_panel.add_log("ERROR", f"加载视频 {bvid} 失败: {e}")

        # ── 所有视频加载完成 → 创建每视频预测线程 + 启动集中拉取 ──
        for video in gui.monitored_videos:
            bvid = video.get("bvid", "")
            if bvid:
                _ensure_predictor(gui, bvid, video)

        invoke(lambda: _start_central_fetcher(gui))

        from ui.theme import C as C2
        invoke(lambda: gui._sb("status", f"已加载 {len(gui.monitored_videos)} 个监控视频", color=C2["success"]))

        gui.log_panel.add_log(
            "INFO",
            f"系统就绪，{len(gui.monitored_videos)} 个视频监控中"
            f"（拉取 {DEFAULT_FETCH_INTERVAL}s，每视频独立预测线程）",
        )

        # 启动后立即运行一次初始预测（后续由每视频线程在拉取完成后接管）
        invoke(lambda: QTimer.singleShot(100, lambda: auto_predict_all(gui)))

    threading.Thread(target=_worker, daemon=True).start()
