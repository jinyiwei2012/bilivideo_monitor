"""
独立监控引擎 —— 视频数据拉取、预测、入库，无 GUI 依赖

MonitorEngine 是后端核心组件，负责：
1. 视频数据周期性拉取（通过 Bilibili API）
2. 调用全部算法进行播放量预测
3. 监控记录和预测结果持久化到 SQLite
4. 多视频并发独立 Worker 线程管理

每个被监控的视频拥有独立的 VideoWorker 线程，
互不阻塞，各自管理拉取间隔和预测周期。
接近阈值时自动提升拉取频率（fast_interval）以获得更高精度。
"""

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

# ── 阈值默认配置 ──────────────────────────────────
# 默认监控的三个播放量阈值（对应对应的中文标签）
THRESHOLD_DEFAULTS = [100000, 1000000, 10000000]
THRESHOLD_NAMES_DEFAULTS = ["10万", "100万", "1000万"]

# 预测计算信号量：限制同时执行的预测数量，防止资源争抢
_prediction_semaphore = threading.Semaphore(2)


def get_thresholds():
    """
    从配置文件读取用户自定义的播放量阈值列表。
    
    Returns:
        tuple: (thresholds列表, threshold_names列表)
    """
    cfg = load_config()
    raw = cfg.get("prediction", {}).get("thresholds", [])
    if raw and isinstance(raw[0], (list, tuple)):
        return [int(item[0]) for item in raw], [str(item[1]) for item in raw]
    return THRESHOLD_DEFAULTS, THRESHOLD_NAMES_DEFAULTS


class MonitorEngine:
    """
    独立监控引擎 —— 管理所有视频的拉取、预测和数据库写入。
    
    职责：
    - 维护视频注册表（_videos）和 Worker 线程映射（_workers）
    - 通过 add_video / remove_video 管理监控生命周期
    - 提供视频数据、历史记录、预测结果的查询接口
    - 通过监听器回调（_listeners）向外推送事件
    """

    def __init__(self):
        """初始化引擎：创建空的数据容器和锁对象。"""
        self._data_lock = threading.Lock()  # 保护 _videos 和 _history 的读写
        self._videos: Dict[str, dict] = {}  # bvid → 视频数据字典
        self._workers: Dict[str, "VideoWorker"] = {}  # bvid → Worker 线程
        self._workers_lock = threading.Lock()  # 保护 _workers 的增删
        self._history: Dict[str, List[tuple]] = {}  # bvid → 内存中的历史记录
        self._listeners: List[Callable] = []  # 事件监听回调列表
        self._running = False

    @property
    def video_count(self) -> int:
        """当前被监控的视频总数。"""
        return len(self._videos)

    @property
    def video_ids(self) -> List[str]:
        """所有被监控视频的 BV 号列表。"""
        return list(self._videos.keys())

    def add_listener(self, callback: Callable[[str, dict], None]):
        """
        注册事件监听器。
        
        Args:
            callback: 回调函数，签名为 callback(event_name: str, data: dict)
                      事件名包括: "video_added", "video_removed", "fetch_done"
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """
        移除已注册的事件监听器。
        
        Args:
            callback: 之前注册的回调函数对象
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, event: str, data: Any = None):
        """
        向所有监听器广播事件。
        
        Args:
            event: 事件名称字符串
            data: 事件携带的数据（通常为字典）
        """
        for cb in self._listeners:
            try:
                cb(event, data)
            except Exception as e:
                logger.debug("监听回调异常: %s", e)

    def add_video(self, bvid: str, interval: int = 300, fast_interval: int = 10) -> bool:
        """
        添加视频到监控列表，启动独立 Worker 线程。
        
        如果视频信息尚未入库，会先通过 API 获取再存入中央数据库。
        已存在的视频不会被重复添加（返回 False）。
        
        Args:
            bvid: 视频 BV 号
            interval: 正常拉取间隔（秒），默认 300 秒（5分钟）
            fast_interval: 接近阈值时的加速拉取间隔（秒），默认 10 秒
            
        Returns:
            bool: 是否添加成功
        """
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

        with self._workers_lock:
            if bvid in self._workers:
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
        """
        移除视频监控：停止 Worker 线程，清理内存数据。
        
        Args:
            bvid: 要移除的视频 BV 号
        """
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
        """
        立即对指定视频（或全部视频）执行一次数据拉取和预测。
        
        Args:
            bvid: 指定视频 BV 号，为 None 时刷新全部视频
        """
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
        """停止所有 Worker 线程，清理全部监控状态。"""
        self._running = False
        with self._workers_lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for w in workers:
            w.stop()
        logger.info("所有监控已停止")

    def get_video_data(self, bvid: str) -> Optional[dict]:
        """
        获取指定视频的当前数据（返回副本，避免外部修改）。
        
        Args:
            bvid: 视频 BV 号
            
        Returns:
            dict: 视频数据字典，不存在时返回空字典
        """
        with self._data_lock:
            return self._videos.get(bvid, {}).copy()

    def get_all_videos(self) -> List[dict]:
        """
        获取全部视频的当前数据列表（返回副本）。
        
        Returns:
            list[dict]: 所有视频数据字典的列表
        """
        with self._data_lock:
            return [v.copy() for v in self._videos.values()]

    def get_history(self, bvid: str) -> List[tuple]:
        """
        获取指定视频的内存历史记录（timestamp, view_count）元组列表。
        
        Args:
            bvid: 视频 BV 号
            
        Returns:
            list[tuple]: 历史记录列表
        """
        with self._data_lock:
            return list(self._history.get(bvid, []))

    def _info_to_dict(self, info) -> dict:
        """
        将 VideoInfo 对象或字典统一转换为标准字典格式。
        
        Args:
            info: VideoInfo 对象或字典
            
        Returns:
            dict: 标准化的视频数据字典
        """
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
        """
        执行一次完整的预测流程：收集历史 → 调用算法 → 保存结果 → 返回聚合。
        
        Args:
            bvid: 视频 BV 号
            current_view: 当前播放量
            
        Returns:
            dict: 聚合后的预测结果
        """
        history = self.get_history(bvid)
        history_data = [(h[0], h[1]) for h in history if h]
        db_history = self._fetch_db_history(bvid)  # 补充数据库中的全量历史
        results = self._do_run_prediction(bvid, current_view, history_data, db_history)
        self._save_predictions(bvid, current_view, results)
        return self._build_prediction_result(bvid, current_view, results)

    def _fetch_db_history(self, bvid: str) -> list:
        """
        从视频专属数据库获取全量历史记录（不限制条数）。
        
        Args:
            bvid: 视频 BV 号
            
        Returns:
            list: [(timestamp, view_count), ...] 格式的历史记录
        """
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
        """
        调用 AlgorithmRegistry 执行所有算法的并行预测。
        
        Args:
            bvid: 视频 BV 号
            current_view: 当前播放量
            history_data: 内存中的历史记录
            db_history: 数据库中的全量历史（可选）
            
        Returns:
            dict: 所有算法的预测结果，包含 _weighted 加权聚合
        """
        thresholds, threshold_names = get_thresholds()
        with _prediction_semaphore:  # 限制并行预测数量
            return AlgorithmRegistry.predict_all(
                history_data, current_view,
                bvid=bvid, thresholds=thresholds, threshold_names=threshold_names,
                db_history=db_history,
            )

    @staticmethod
    def _build_prediction_result(bvid: str, current_view: int, results: dict) -> dict:
        """
        将 AlgorithmRegistry 的原始结果构建为前端友好的聚合格式。
        
        包含：
        - 加权预测值和增长值
        - 成功/失败算法明细列表
        - 有效/总算法计数
        
        Args:
            bvid: 视频 BV 号
            current_view: 当前播放量
            results: AlgorithmRegistry.predict_all() 的原始返回
            
        Returns:
            dict: 聚合后的预测结果
        """
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
        """
        将预测结果持久化到视频专属数据库和中央数据库。
        
        每条预测记录包含：
        - 算法名称和 ID
        - 目标阈值和预计到达时间
        - 置信度和元数据
        
        Args:
            bvid: 视频 BV 号
            current_view: 当前播放量
            results: 算法预测结果字典
        """
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
    """
    单个视频的独立 Worker 线程。
    
    每个 VideoWorker 负责一个视频的周期性数据拉取和预测计算。
    通过独立的线程和 stop_event 实现可控启停，与引擎通过事件回调通信。
    
    特性：
    - 正常模式：按 interval 间隔拉取（默认 300 秒）
    - 快速模式：当播放量接近阈值时，切换到 fast_interval（默认 10 秒）
    - 立即刷新：refresh_now() 启动临时线程执行立即拉取
    """

    def __init__(self, engine: MonitorEngine, bvid: str, video: dict,
                 interval: int = 300, fast_interval: int = 10):
        """
        初始化 Worker。
        
        Args:
            engine: 所属的 MonitorEngine 实例
            bvid: 视频 BV 号
            video: 初始视频数据字典
            interval: 正常拉取间隔（秒）
            fast_interval: 快速拉取间隔（秒）
        """
        self.engine = engine
        self.bvid = bvid
        self.video = video
        self.interval = interval
        self.fast_interval = fast_interval
        self._stop_event = threading.Event()  # 停止信号
        self._thread: Optional[threading.Thread] = None
        self._interval_lock = threading.Lock()  # 保护 interval 修改
        self._fetching_lock = threading.Lock()  # 防止重复拉取
        self._fetching = False  # 当前是否正在拉取
        self._is_fast = False  # 是否处于快速模式

    def start(self):
        """启动 Worker 线程（daemon 模式）。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"EngineWorker-{self.bvid}")
        self._thread.start()
        logger.info("[%s] Worker 启动 (间隔 %ds)", self.bvid, self.interval)

    def stop(self):
        """
        停止 Worker 线程。
        
        设置 stop_event，等待线程在 5 秒内退出。若超时则强制放弃。
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[%s] Worker 已停止", self.bvid)

    def update_interval(self, new_interval: int):
        """
        更新拉取间隔（秒），线程安全。
        
        Args:
            new_interval: 新的间隔秒数
        """
        with self._interval_lock:
            self.interval = new_interval

    def refresh_now(self):
        """
        立即执行一次数据拉取和预测（在临时线程中运行）。

        不打断当前主循环，启动一个新的 daemon 线程执行拉取。
        若正在拉取中则跳过（防止重复拉取）。
        """
        if self._fetching:
            return
        t = threading.Thread(target=self._fetch_and_predict, daemon=True,
                             name=f"EngineWorker-{self.bvid}-immediate")
        t.start()

    def _run(self):
        """
        Worker 主循环。
        
        在 stop_event 未触发时循环执行：
        1. 拉取最新数据
        2. 执行预测
        3. 等待 interval 秒后继续
        """
        while not self._stop_event.is_set():
            with self._interval_lock:
                interval = self.interval

            self._fetch_and_predict()

            # 分段等待，以便能够及时响应停止信号
            waited = 0
            step = 1.0
            while waited < interval and not self._stop_event.is_set():
                time.sleep(min(step, interval - waited))
                waited += step

    def _fetch_and_predict(self):
        """
        执行一次拉取和预测（线程安全，同时只允许一次执行）。
        
        流程：
        1. 拉取 API 最新数据
        2. 调用引擎执行预测
        3. 触发 fetch_done 事件通知
        4. 判断是否接近阈值，自动切换快速/正常模式
        """
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

                # 自动切换快速模式：当前播放量在最近的整数万关卡 5000 以内
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
        """
        通过 Bilibili API 拉取视频最新数据并更新到内存。
        
        拉取内容包括：
        - 基本播放量统计数据（views, likes, coins 等）
        - 在线观看人数（需要额外 API 调用）
        - 视频分区信息
        
        Returns:
            bool: 拉取是否成功
        """
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
            # 更新视频基本信息
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
                # 拉取在线观看人数（需要 cid 参数）
                cid = info.get("cid", 0)
                if cid:
                    viewers = get_bilibili_api().get_video_viewers(bvid, cid)
                    if viewers:
                        total = int(viewers.get("total", 0) or 0)
                        web = int(viewers.get("count", 0) or 0)
                        self.video["viewers_total"] = total
                        self.video["viewers_web"] = web
                        self.video["viewers_app"] = max(0, total - web)  # APP 观看 = 总数 - WEB
            except Exception:
                pass

        # 追加到内存历史记录（最多保留 3000 条）
        ts = datetime.now()
        with self.engine._data_lock:
            if bvid not in self.engine._history:
                self.engine._history[bvid] = []
            self.engine._history[bvid].append((ts, self.video["view_count"]))
            if len(self.engine._history[bvid]) > 3000:
                self.engine._history[bvid] = self.engine._history[bvid][-2800:]

        self._save_record(ts)

        # 同步视频信息到中央数据库
        try:
            central_db.sync_video_info(bvid, self.video)
        except Exception as e:
            logger.debug("[%s] 同步视频信息失败: %s", bvid, e)

        return True

    def _save_record(self, ts: datetime):
        """
        将当前视频数据写入视频专属数据库和中央数据库。
        
        Args:
            ts: 当前时间戳（datetime 对象）
        """
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


# ── 全局单例 ────────────────────────────────────────
_engine_instance: Optional[MonitorEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> MonitorEngine:
    """
    获取全局 MonitorEngine 单例（双检锁惰性初始化）。
    
    Returns:
        MonitorEngine: 全局唯一的监控引擎实例
    """
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = MonitorEngine()
        return _engine_instance


def load_watch_list_from_db() -> list:
    """
    从数据库加载所有视频 BVid（当配置的 watch_list 为空时兜底）。
    
    遍历中央数据库中的 videos 表，按更新时间倒序返回所有 BV 号。
    用于在配置文件中 watch_list 为空时自动恢复监控列表。
    
    Returns:
        list[str]: BV 号列表，数据库读取失败时返回空列表
    """
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
