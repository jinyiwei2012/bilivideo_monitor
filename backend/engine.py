"""独立监控引擎 —— 视频数据拉取、预测、入库，无 GUI 依赖"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

from core import db as central_db
from core.bilibili_api import get_bilibili_api
from core.database.models import VideoInfo, MonitorRecord, PredictionRecord
from algorithms.registry import AlgorithmRegistry
from config import load_config

logger = logging.getLogger("backend.engine")

THRESHOLD_DEFAULTS = [100000, 1000000, 10000000]
THRESHOLD_NAMES_DEFAULTS = ["10万", "100万", "1000万"]

_prediction_semaphore = threading.Semaphore(2)


def get_thresholds():
    cfg = load_config()
    raw = cfg.get("prediction", {}).get("thresholds", [])
    if raw and isinstance(raw[0], (list, tuple)):
        return [int(item[0]) for item in raw], [str(item[1]) for item in raw]
    return THRESHOLD_DEFAULTS, THRESHOLD_NAMES_DEFAULTS


class MonitorEngine:
    """独立监控引擎 —— 管理所有视频的拉取、预测和数据库写入"""

    def __init__(self):
        self._data_lock = threading.Lock()
        self._videos: Dict[str, dict] = {}
        self._workers: Dict[str, "VideoWorker"] = {}
        self._workers_lock = threading.Lock()
        self._history: Dict[str, List[tuple]] = {}
        self._listeners: List[Callable] = []
        self._running = False

    @property
    def video_count(self) -> int:
        return len(self._videos)

    @property
    def video_ids(self) -> List[str]:
        return list(self._videos.keys())

    def add_listener(self, callback: Callable[[str, dict], None]):
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, event: str, data: Any = None):
        for cb in self._listeners:
            try:
                cb(event, data)
            except Exception as e:
                logger.debug("监听回调异常: %s", e)

    def add_video(self, bvid: str, interval: int = 300, fast_interval: int = 10) -> bool:
        bvid = bvid.strip()
        if not bvid:
            return False

        with self._workers_lock:
            if bvid in self._workers:
                return False

            info = central_db.get_video(bvid)
            if not info:
                try:
                    api = get_bilibili_api()
                    data = api.get_video_info(bvid)
                    if not data or data.get("code") != 0:
                        logger.warning("无法获取视频信息: %s", bvid)
                        return False
                    vdata = data.get("data", {})
                    video = VideoInfo.from_api_data(bvid, vdata)
                    central_db.add_video(video)
                    info = video
                except Exception as e:
                    logger.exception("添加视频失败 %s", bvid)
                    return False

            video_data = self._info_to_dict(info)
            worker = VideoWorker(self, bvid, video_data, interval, fast_interval)
            worker.start()
            self._workers[bvid] = worker
            self._videos[bvid] = video_data
            logger.info("已添加监控: %s (间隔 %ds)", bvid, interval)

        self._notify("video_added", {"bvid": bvid})
        return True

    def remove_video(self, bvid: str):
        with self._workers_lock:
            worker = self._workers.pop(bvid, None)
        if worker:
            worker.stop()

        with self._data_lock:
            self._videos.pop(bvid, None)
            self._history.pop(bvid, None)

        self._notify("video_removed", {"bvid": bvid})
        logger.info("已移除监控: %s", bvid)

    def refresh_now(self, bvid: str = None):
        if bvid:
            with self._workers_lock:
                worker = self._workers.get(bvid)
            if worker:
                worker.refresh_now()
        else:
            with self._workers_lock:
                workers = list(self._workers.values())
            for w in workers:
                w.refresh_now()

    def stop_all(self):
        self._running = False
        with self._workers_lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for w in workers:
            w.stop()
        logger.info("所有监控已停止")

    def get_video_data(self, bvid: str) -> Optional[dict]:
        with self._data_lock:
            return self._videos.get(bvid, {}).copy()

    def get_all_videos(self) -> List[dict]:
        with self._data_lock:
            return [v.copy() for v in self._videos.values()]

    def get_history(self, bvid: str) -> List[tuple]:
        with self._data_lock:
            return list(self._history.get(bvid, []))

    def _info_to_dict(self, info) -> dict:
        if info is None:
            return {}
        if hasattr(info, "view_count"):
            return {
                "bvid": info.bvid,
                "title": info.title,
                "view_count": info.view_count,
                "like_count": info.like_count,
                "coin_count": info.coin_count,
                "share_count": info.share_count,
                "favorite_count": info.favorite_count,
                "danmaku_count": info.danmaku_count,
                "reply_count": info.reply_count,
                "author": info.owner_name,
                "owner_name": info.owner_name,
                "owner_id": info.owner_id,
                "pubdate": info.pubdate,
                "duration": info.duration,
                "pic": info.pic,
            }
        return info if isinstance(info, dict) else {}

    def _run_prediction(self, bvid: str, current_view: int) -> dict:
        history = self.get_history(bvid)
        history_data = [(h[0], h[1]) for h in history if h]
        db_history = self._fetch_db_history(bvid)
        results = self._do_run_prediction(bvid, current_view, history_data, db_history)
        self._save_predictions(bvid, current_view, results)
        return self._build_prediction_result(bvid, current_view, results)

    def _fetch_db_history(self, bvid: str) -> list:
        try:
            video_db = central_db.get_video_db(bvid)
            db_records = video_db.get_all_records(limit=0)
            if db_records:
                return [(r["timestamp"], r["view_count"]) for r in db_records]
        except Exception as e:
            logger.debug("读取 DB 全量历史失败 %s: %s", bvid, e)
        return []

    @staticmethod
    def _do_run_prediction(bvid: str, current_view: int, history_data: list,
                           db_history: list = None) -> dict:
        thresholds, threshold_names = get_thresholds()
        with _prediction_semaphore:
            return AlgorithmRegistry.predict_all(
                history_data, current_view,
                bvid=bvid, thresholds=thresholds, threshold_names=threshold_names,
                db_history=db_history,
            )

    @staticmethod
    def _build_prediction_result(bvid: str, current_view: int, results: dict) -> dict:
        weighted = results.get("_weighted", {})
        w_pred = weighted.get("prediction", current_view)
        success_list = []
        for name, r in results.items():
            if name == "_weighted" or "error" in r:
                continue
            success_list.append({
                "algorithm": name,
                "prediction": r.get("prediction", 0),
                "weight": r.get("weight", 0),
                "confidence": r.get("confidence", 0),
            })
        return {
            "bvid": bvid,
            "prediction": w_pred,
            "current_view": current_view,
            "growth": max(0, w_pred - current_view),
            "success_list": success_list,
            "fail_list": [(n, r["error"]) for n, r in results.items() if n != "_weighted" and "error" in r],
            "valid": weighted.get("valid_algorithms", 0),
            "total": weighted.get("total_algorithms", 0),
        }

    def _save_predictions(self, bvid: str, current_view: int, results: dict):
        video_db = central_db.get_video_db(bvid)
        for name, r in results.items():
            if name == "_weighted" or "error" in r:
                continue
            metadata = r.get("metadata", {})
            threshold_preds = metadata.get("threshold_predictions", [])
            confidence = r.get("confidence", 0)
            predicted_hours = metadata.get("predicted_hours", 0)
            velocity = metadata.get("velocity", 0)
            metadata_str = json.dumps(metadata, ensure_ascii=False)

            for tp in threshold_preds:
                minutes = tp.get("minutes", 0)
                rec = PredictionRecord(
                    bvid=bvid, algorithm=name, algorithm_id=name,
                    target_threshold=tp.get("threshold", 0),
                    predicted_seconds=int(minutes * 60) if minutes else 0,
                    predicted_time=tp.get("name", ""),
                    confidence=confidence, current_views=current_view,
                    metadata=metadata_str, predicted_hours=predicted_hours,
                    current_velocity=velocity,
                )
                try:
                    video_db.add_prediction(rec)
                    central_db.add_prediction(rec)
                except Exception as e:
                    logger.debug("保存预测失败 %s/%s: %s", bvid, name, e)


class VideoWorker:
    """单个视频的独立 Worker 线程"""

    def __init__(self, engine: MonitorEngine, bvid: str, video: dict,
                 interval: int = 300, fast_interval: int = 10):
        self.engine = engine
        self.bvid = bvid
        self.video = video
        self.interval = interval
        self.fast_interval = fast_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._interval_lock = threading.Lock()
        self._fetching_lock = threading.Lock()
        self._fetching = False
        self._is_fast = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"EngineWorker-{self.bvid}")
        self._thread.start()
        logger.info("[%s] Worker 启动 (间隔 %ds)", self.bvid, self.interval)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[%s] Worker 已停止", self.bvid)

    def update_interval(self, new_interval: int):
        with self._interval_lock:
            self.interval = new_interval

    def refresh_now(self):
        t = threading.Thread(target=self._fetch_and_predict, daemon=True,
                             name=f"EngineWorker-{self.bvid}-immediate")
        t.start()

    def _run(self):
        while not self._stop_event.is_set():
            with self._interval_lock:
                interval = self.interval

            self._fetch_and_predict()

            waited = 0
            step = 1.0
            while waited < interval and not self._stop_event.is_set():
                time.sleep(min(step, interval - waited))
                waited += step

    def _fetch_and_predict(self):
        with self._fetching_lock:
            if self._fetching:
                return
            self._fetching = True

        try:
            if not self._do_fetch():
                return

            result = self.engine._run_prediction(self.bvid, self.video.get("view_count", 0))
            if result:
                self.engine._notify("fetch_done", {"bvid": self.bvid, "video": self.video, "result": result})

                new_view = self.video.get("view_count", 0)
                near_threshold = new_view > 0 and (new_view % 100000 < 5000)
                if near_threshold != self._is_fast:
                    self._is_fast = near_threshold
                    with self._interval_lock:
                        self.interval = self.fast_interval if near_threshold else 300
        finally:
            with self._fetching_lock:
                self._fetching = False

    def _do_fetch(self) -> bool:
        bvid = self.bvid
        try:
            info = get_bilibili_api().get_video_info(bvid)
            if not info:
                logger.warning("[%s] 获取视频信息失败", bvid)
                return False
        except Exception as e:
            logger.error("[%s] 获取视频信息异常: %s", bvid, e)
            return False

        stat = info.get("stat", {})
        owner = info.get("owner", {})

        with self.engine._data_lock:
            self.video["title"] = info.get("title", self.video.get("title", ""))
            self.video["author"] = owner.get("name", self.video.get("author", ""))
            self.video["view_count"] = stat.get("view", self.video.get("view_count", 0))
            self.video["like_count"] = stat.get("like", self.video.get("like_count", 0))
            self.video["coin_count"] = stat.get("coin", self.video.get("coin_count", 0))
            self.video["share_count"] = stat.get("share", self.video.get("share_count", 0))
            self.video["favorite_count"] = stat.get("favorite", self.video.get("favorite_count", 0))
            self.video["danmaku_count"] = stat.get("danmaku", self.video.get("danmaku_count", 0))
            self.video["reply_count"] = stat.get("reply", self.video.get("reply_count", 0))
            self.video["view_token"] = stat.get("vt", self.video.get("view_token", 0))
            self.video["tid"] = info.get("tid", self.video.get("tid", 0))
            self.video["tname"] = info.get("tname", self.video.get("tname", ""))

            try:
                cid = info.get("cid", 0)
                if cid:
                    viewers = get_bilibili_api().get_video_viewers(bvid, cid)
                    if viewers:
                        total = int(viewers.get("total", 0) or 0)
                        web = int(viewers.get("count", 0) or 0)
                        self.video["viewers_total"] = total
                        self.video["viewers_web"] = web
                        self.video["viewers_app"] = max(0, total - web)
            except Exception:
                pass

        ts = datetime.now()
        with self.engine._data_lock:
            if bvid not in self.engine._history:
                self.engine._history[bvid] = []
            self.engine._history[bvid].append((ts, self.video["view_count"]))
            if len(self.engine._history[bvid]) > 3000:
                self.engine._history[bvid] = self.engine._history[bvid][-2800:]

        self._save_record(ts)

        try:
            central_db.sync_video_info(bvid, self.video)
        except Exception as e:
            logger.debug("[%s] 同步视频信息失败: %s", bvid, e)

        return True

    def _save_record(self, ts: datetime):
        bvid = self.bvid
        video = self.video
        try:
            video_db = central_db.get_video_db(bvid)
            rec = MonitorRecord(
                bvid=bvid, timestamp=ts.isoformat(),
                view_count=video.get("view_count", 0),
                like_count=video.get("like_count", 0),
                coin_count=video.get("coin_count", 0),
                share_count=video.get("share_count", 0),
                favorite_count=video.get("favorite_count", 0),
                danmaku_count=video.get("danmaku_count", 0),
                reply_count=video.get("reply_count", 0),
                viewers_total=video.get("viewers_total", 0),
                viewers_web=video.get("viewers_web", 0),
                viewers_app=video.get("viewers_app", 0),
            )
            video_db.add_monitor_record(rec)
            central_db.sync_monitor_record(bvid, {
                "timestamp": ts.isoformat(),
                "view_count": video.get("view_count", 0),
                "like_count": video.get("like_count", 0),
                "coin_count": video.get("coin_count", 0),
                "share_count": video.get("share_count", 0),
                "favorite_count": video.get("favorite_count", 0),
                "danmaku_count": video.get("danmaku_count", 0),
                "reply_count": video.get("reply_count", 0),
                "viewers_total": video.get("viewers_total", 0),
                "viewers_web": video.get("viewers_web", 0),
                "viewers_app": video.get("viewers_app", 0),
            })
        except Exception as e:
            logger.warning("[%s] 写DB失败: %s", bvid, e)


_engine_instance: Optional[MonitorEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> MonitorEngine:
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = MonitorEngine()
        return _engine_instance


def load_watch_list_from_db() -> list:
    """从数据库加载所有视频 BVid（当配置的 watch_list 为空时兜底）"""
    import os
    from core import db as cdb

    db_path = os.path.join(os.path.dirname(cdb.db_path), "bilibili_monitor.db")
    try:
        with cdb._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT bvid FROM videos ORDER BY updated_at DESC")
            bvids = [r[0] for r in cur.fetchall() if r[0]]
            if bvids:
                logger.info("从数据库加载 %d 个视频作为 watch_list 兜底", len(bvids))
            return bvids
    except Exception as e:
        logger.debug("从数据库加载 watch_list 失败: %s", e)
        return []
