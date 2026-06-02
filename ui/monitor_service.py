"""
监控业务逻辑模块 — 独立 Worker 线程模型

核心设计: 每个监控视频拥有一个独立的 VideoWorker 线程，
自主管理刷新间隔，不同视频之间互不阻塞、互不干扰。

主要组件:
  - VideoWorker        : 单视频独立后台刷新线程
  - _predict_single    : 对单个视频运行所有预测算法
  - _merge_history     : 合并内存历史与数据库历史
  - _save_predictions_to_db : 将预测结果写入数据库
  - 全局 Worker 管理器 : _start_worker / _stop_worker / _stop_all_workers
  - 公开 API           : fetch_single_video_data / fetch_all_video_data /
                        auto_predict_video / auto_predict_all / load_watch_list

并发控制:
  - _prediction_semaphore: 限制并发预测数为 2，防止 GIL 饥饿
  - _merged_from_db      : 跟踪已从 DB 完成历史合并的视频
  - _workers_lock        : 保护 _active_workers 字典
  - _interval_lock       : 保护每个 Worker 的刷新间隔切换
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

# 限制并发预测数量，防止 GIL 饥饿导致主线程卡顿
_prediction_semaphore = threading.Semaphore(2)

# 已从 DB 完成历史合并的视频集合（后续循环中内存数据始终 >= DB，跳过全量读取）
_merged_from_db = set()
_merged_from_db_lock = threading.Lock()

# UP主数据库实例 & 拉取频率控制（每 UP主 每小时最多拉取一次）
_up_db = None
_last_up_fetch_time = {}  # uid -> time.time


# ──────────────────────────────────────────────
#  内部工具函数
# ──────────────────────────────────────────────


def _save_predictions_to_db(gui, bvid, current_view, results):
    """将各算法的阈值预测结果写入视频数据库。优先使用后端引擎，回退到直接写库。

    遍历所有算法结果（跳过加权集成和错误结果），
    对每个阈值预测创建 PredictionRecord 并写入视频独立数据库。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        current_view: 当前播放量
        results: 算法预测结果字典 {算法名: {prediction, metadata, ...}}
    """
    # Delegate to backend engine when available (avoids duplicating save logic)
    try:
        from backend import get_engine
        engine = get_engine()
        if hasattr(engine, '_save_predictions') and engine._workers:
            engine._save_predictions(bvid, current_view, results)
            return
    except Exception:
        pass

    video_db = gui.video_dbs.get(bvid)
    if not video_db:
        return
    for name, r in results.items():
        # 跳过加权集成结果和错误结果
        if name == "_weighted" or "error" in r:
            continue
        metadata = r.get("metadata", {})
        threshold_preds = metadata.get("threshold_predictions", [])
        confidence = r.get("confidence", 0)

        # 获取额外的元数据
        predicted_hours = metadata.get("predicted_hours", 0)
        velocity = metadata.get("velocity", 0)
        # 将 metadata 字典转换为 JSON 字符串（便于数据库存储和查询）
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


def _fetch_db_history(gui, bvid: str) -> list:
    """从 DB 读取全量历史，供长期期预测算法使用。

    某些预测算法（如 LSTM、TFT）需要较长时间跨度的历史数据，
    此函数直接从数据库读取完整历史记录作为补充。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号

    Returns:
        list: [(timestamp, view_count), ...] 格式，无 DB 时返回空列表
    """
    try:
        if bvid in gui.video_dbs:
            db_records = gui.video_dbs[bvid].get_all_records(limit=0)
            if db_records:
                return [(r["timestamp"], r["view_count"]) for r in db_records]
    except Exception as e:
        logger.debug("读取 DB 全量历史失败 %s: %s", bvid, e)
    return []


def _merge_history(gui, bvid: str) -> list:
    """合并内存历史与数据库历史，同步写回 gui.history_data 确保图表数据完整

    优化策略：首次从 DB 全量合并后，后续循环跳过 DB 读取
    （因为内存数据始终 >= DB 数据，每次拉取都会同时写入两者）。

    合并规则:
      - 基于时间戳去重（相同时间的记录只保留一条）
      - 按时间升序排序
      - 不足 2 条时用当前时间补齐（确保速率计算有效）

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号

    Returns:
        list: 合并后的历史数据列表 [(timestamp, view_count), ...]
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
                    db_rows = [(row["timestamp"], row["view_count"]) for row in db_hist]
                    # Delegate dedup/sort to AlgorithmRegistry to eliminate duplication
                    history = AlgorithmRegistry._merge_history(history, db_rows)
        except Exception as e:
            logger.warning(f"合并历史记录失败 {bvid}: {e}")
        with _merged_from_db_lock:
            _merged_from_db.add(bvid)

    # 按时间序排序（_merge_history 已排序，此处为兜底）
    history.sort(key=lambda x: _to_dt(x[0]))

    # 如果历史不足 2 条，用当前时间补齐（保证速率计算有足够数据点）
    if len(history) < 2:
        now = datetime.now()
        history = [(now, current_view), (now, current_view)]

    # 同步回 gui.history_data，让图表也能看到合并后的完整数据
    with gui._data_lock:
        gui.history_data[bvid] = [(ts, v) for ts, v in history]

    return history


def _to_dt(t):
    """统一时间戳转为 datetime 对象

    Args:
        t: 时间戳（datetime/str/float）

    Returns:
        datetime: 标准化的 datetime 对象
    """
    return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))


def _get_up_db():
    """获取 UP主 数据库单例（延迟初始化）"""
    global _up_db
    if _up_db is None:
        from core.up_database import UpDatabase

        _up_db = UpDatabase()
    return _up_db


def _save_up_data(uid: int):
    """拉取 UP主信息+统计数据，保存到数据库（每 UP主 每小时最多拉取一次）

    频率控制: 使用 _last_up_fetch_time 记录每个 UP主 的最后拉取时间，
    避免在短时间内重复请求 Bilibili API。

    Args:
        uid: UP主 用户 ID
    """
    import time

    now = time.time()
    last = _last_up_fetch_time.get(uid, 0)
    if now - last < 3600:
        return  # 一小时内已拉取过，跳过
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
    """根据历史数据计算播放量增长速率（播放量/秒）

    使用最早和最新记录的时间差和播放量差计算平均增速。

    Args:
        history: [(timestamp, view_count), ...] 历史数据列表

    Returns:
        float: 每秒播放量增长，计算失败返回 0.0
    """
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


def _predict_single(gui, bvid, video) -> dict:
    """在 worker 线程中对单个视频运行预测，优先使用后端引擎

    预测流程:
      1. 尝试使用后端引擎的 _run_prediction
      2. 回退到 AlgorithmRegistry.predict_all
      3. 合并评分、筛选成功/失败列表
      4. 写入数据库 + 在线学习反馈 + 更新视频关系图

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        video: 视频数据字典

    Returns:
        dict: 预测结果 {
            bvid, prediction, current_view, growth, rate_per_sec,
            success_list, fail_list, valid, total
        }
    """
    current_view = video.get("view_count", 0)

    try:
        from backend import get_engine
        engine = get_engine()
        result = engine._run_prediction(bvid, current_view)
    except Exception:
        # 回退到直接使用 AlgorithmRegistry
        history = _merge_history(gui, bvid)
        db_history = _fetch_db_history(gui, bvid)
        with _prediction_semaphore:
            results = AlgorithmRegistry.predict_all(
                history, current_view, bvid=bvid,
                thresholds=THRESHOLDS, threshold_names=THRESHOLD_NAMES,
                db_history=db_history,
            )
        weighted = results.get("_weighted", {})
        w_pred = weighted.get("prediction", current_view)
        success_list, fail_list = [], []
        for name, r in results.items():
            if name == "_weighted":
                continue
            if "error" in r:
                fail_list.append((name, r["error"]))
            else:
                success_list.append((name, r["prediction"], r["weight"], r["confidence"], r.get("predicted_hours", 0)))
        result = {
            "bvid": bvid, "prediction": w_pred, "current_view": current_view,
            "growth": max(0, w_pred - current_view),  # 预测增长量
            "rate_per_sec": _calc_growth_rate(history),
            "success_list": success_list, "fail_list": fail_list,
            "valid": weighted.get("valid_algorithms", 0),
            "total": weighted.get("total_algorithms", 0),
        }
        _save_predictions_to_db(gui, bvid, current_view, results)

    # 更新预测缓存（线程安全）
    with gui._data_lock:
        prev_result = gui.prediction_results.get(bvid)
        gui.prediction_results[bvid] = result
    # 在线学习：比较上次预测与实际结果的偏差
    _online_learning_feedback(bvid, {}, current_view, prev_result)
    # 更新视频关系图
    _update_video_graph(bvid, video)

    return result


def _online_learning_feedback(bvid, results, actual_view, prev_result):
    """在线学习反馈：使用 Hedge 算法根据预测偏差调整算法权重

    比较「上次预测的增长量」与「实际增长量」的偏差，
    避免静止期 100% 准确率的虚假提升。

    Args:
        bvid: 视频 BV 号
        results: 本次预测结果（未使用，保留接口兼容性）
        actual_view: 实际当前播放量
        prev_result: 上次的预测结果缓存
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


def _update_video_graph(bvid, video):
    """更新视频关系图节点和边（图神经网络辅助）

    将视频信息更新到视频关系图中，当节点数 >= 2 时自动构建边关系。

    Args:
        bvid: 视频 BV 号
        video: 视频数据字典
    """
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
    """独立的后台刷新线程，每个监控视频一个实例。

    设计原则:
      - 每个 Worker 完全自主管理刷新间隔，不与其他视频共享状态
      - 使用分段睡眠（每 1 秒检查一次停止信号），支持快速停止
      - 通过 _fetching_lock 防止同一个视频的并发拉取
      - 支持运行时动态调整刷新间隔（通过 update_interval）
      - 支持立即刷新（通过 refresh_now）

    Attributes:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        video: 视频数据字典引用（共享的）
        interval: 正常刷新间隔（秒）
        fast_interval: 接近阈值时的快速刷新间隔（秒）
    """

    def __init__(self, gui, bvid, video, interval, fast_interval=None):
        """
        Args:
            gui: BilibiliMonitorGUI 实例
            bvid: 视频 BV 号
            video: 视频数据字典
            interval: 正常刷新间隔（秒）
            fast_interval: 快速刷新间隔（秒，可选）
        """
        self.gui = gui
        self.bvid = bvid
        self.video = video
        self.interval = interval  # 正常刷新间隔（秒）
        self.fast_interval = fast_interval  # 接近阈值时的快速间隔（秒）
        self._stop_event = threading.Event()  # 线程停止信号
        self._thread = None
        self._interval_lock = threading.Lock()  # 保护 interval 切换的并发安全
        self._fetching_lock = threading.Lock()  # 防止并发拉取
        self._fetching = False  # 当前是否正在拉取
        self._refresh_in_flight = False  # 立即刷新防重入
        self._log = gui.log_panel.add_log  # 快捷日志引用

    # ── 公开 API ────────────────────────────────

    def start(self):
        """启动独立刷新线程

        如果已有线程在运行则跳过（防重复启动）。
        """
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"VideoWorker-{self.bvid}")
        self._thread.start()
        self._log("INFO", f"[{self.bvid}] Worker 线程已启动（间隔 {self.interval}s）")

    def stop(self):
        """安全停止线程

        设置停止信号，等待最多 3 秒让线程自然退出。
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._log("INFO", f"[{self.bvid}] Worker 线程已停止")

    def update_interval(self, new_interval):
        """运行时更新刷新间隔（主线程调用，线程安全）

        Args:
            new_interval: 新的刷新间隔（秒）
        """
        with self._interval_lock:
            self.interval = new_interval

    def refresh_now(self):
        """立即执行一次拉取+预测（主线程调用，即时触发一次）"""
        if self._refresh_in_flight:
            self._log("DEBUG", f"[{self.bvid}] 刷新正在进行中，跳过本次请求")
            return
        self._refresh_in_flight = True
        self._log("INFO", f"[{self.bvid}] 立即刷新触发")
        threading.Thread(target=self._run_refresh_now, daemon=True, name=f"VideoWorker-{self.bvid}-immediate").start()

    def _run_refresh_now(self):
        """立即刷新的包装：执行拉取并重置标志"""
        try:
            self._fetch_and_predict()
        finally:
            self._refresh_in_flight = False

    # ── 内部循环 ─────────────────────────────────

    def _run(self):
        """Worker 主循环：睡眠 → 拉取+预测 → 更新间隔 → 循环

        使用分段睡眠（每 1 秒醒来检查 stop 信号），确保停止响应在 1 秒内。
        """
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
        """在 worker 线程中执行一次完整的拉取 + 预测

        通过 _fetching_lock 防止并发拉取（如果上次还没完成就跳过）。
        流程: 拉取数据 → 运行预测 → 更新 UI 回调
        """
        bvid = self.bvid
        video = self.video
        gui = self.gui

        # 防重复：如果上次拉取还没完成，跳过本次
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
        """拉取视频数据：获取 info → 更新字段 → 在线人数 → 历史记录 → 写DB

        完整的数据获取流水线:
          1. 调用 Bilibili API 获取视频基本信息（info）
          2. 更新内存中的视频字段（title, author, 各项计数等）
          3. 获取在线观看人数
          4. 保存 UP主 数据
          5. 追加历史记录到内存
          6. 写入视频独立数据库
          7. 同步到中央数据库

        Args:
            bvid: 视频 BV 号
            video: 视频数据字典
            gui: BilibiliMonitorGUI 实例

        Returns:
            bool: 拉取是否成功
        """
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

        # 更新内存中的视频字段（线程安全）
        with gui._data_lock:
            owner = info.get("owner", {})
            video["title"] = info.get("title", video.get("title", ""))
            video["author"] = owner.get("name", video.get("author", ""))
            video["pic"] = info.get("pic", video.get("pic", ""))
            owner_id = owner.get("mid", 0)
            if owner_id:
                _save_up_data(owner_id)  # 后台保存 UP主 数据
            video["view_count"] = stat.get("view", video.get("view_count", 0))
            video["like_count"] = stat.get("like", video.get("like_count", 0))
            video["coin_count"] = stat.get("coin", video.get("coin_count", 0))
            video["share_count"] = stat.get("share", video.get("share_count", 0))
            video["favorite_count"] = stat.get("favorite", video.get("favorite_count", 0))
            video["danmaku_count"] = stat.get("danmaku", video.get("danmaku_count", 0))
            video["reply_count"] = stat.get("reply", video.get("reply_count", 0))

        # 获取在线观看人数
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

        # 追加历史记录到内存
        ts = datetime.now()
        with gui._data_lock:
            if bvid not in gui.history_data:
                gui.history_data[bvid] = []
            gui.history_data[bvid].append((ts, video["view_count"]))
            # 历史数据超过 3000 条时裁剪到 2800 条（防止内存无限增长）
            if len(gui.history_data[bvid]) > 3000:
                gui.history_data[bvid] = gui.history_data[bvid][-2800:]

        # 写入视频独立数据库
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

        # 同步到中央数据库
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
        """执行播放量预测（调用 _predict_single）

        Args:
            gui: BilibiliMonitorGUI 实例
            bvid: 视频 BV 号
            video: 视频数据字典

        Returns:
            dict 或 None: 预测结果字典
        """
        try:
            return _predict_single(gui, bvid, video)
        except Exception as e:
            self._log("ERROR", f"[{bvid}] 预测失败: {e}")
            return None

    def _do_post_fetch(self, bvid, video, gui, result):
        """预测完成后的日志、同步和 UI 回调

        在主线程中执行:
          - 更新视频卡片
          - 如果是选中视频，触发防抖后的完整 UI 刷新
          - 更新状态栏

        Args:
            bvid: 视频 BV 号
            video: 视频数据字典
            gui: BilibiliMonitorGUI 实例
            result: 预测结果字典
        """
        self._log(
            "DEBUG", f"[{bvid}] 拉取完成 播放:{video.get('view_count', 0):,} 预测:{result.get('prediction', 0):,}"
        )

        try:
            db.sync_video_info(bvid, video)
        except Exception as e:
            self._log("WARNING", f"[{bvid}] 同步中央数据库失败: {e}")

        # 调度到主线程执行 UI 更新
        gui.root.after(0, lambda r=result, v=video: self._on_fetch_done(r, v))

    def _on_fetch_done(self, result, video):
        """在主线程回调：更新 UI（仅当前选中视频触发完整刷新）

        使用防抖机制（50ms），避免高频率刷新时 UI 闪烁。

        Args:
            result: 预测结果字典
            video: 视频数据字典
        """
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

        # 刷新状态栏（上次刷新时间、视频计数）
        now_str = datetime.now().strftime("%H:%M:%S")
        gui._sb("last_ref", f"上次刷新: {now_str}")
        gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
        # 重新注册定时器，使倒计时正常显示
        gui._register_video_timer(bvid)

    def _apply_selected_update(self, result, video):
        """对当前选中视频执行完整的预测+详情+图表更新

        防抖结束后执行:
          - 更新预测面板（英雄卡 + 算法列表）
          - 更新视频详情状态栏
          - 根据当前标签页自动渲染图表或详情文本

        Args:
            result: 预测结果字典
            video: 视频数据字典
        """
        gui = self.gui
        bvid = result["bvid"]
        if bvid != gui.selected_bvid:
            return  # 选中视频已变更，跳过
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
        gui.detail.update_stat_bar(video)
        # 根据当前标签页渲染对应内容
        if gui.detail.current_tab == "📈 播放量趋势":
            if hasattr(gui, "_chart_debounce") and gui._chart_debounce:
                gui.root.after_cancel(gui._chart_debounce)
            gui._chart_debounce = gui.root.after(100, lambda: gui.detail._auto_render_chart())
        elif gui.detail.current_tab == "📋 详细数据":
            gui.detail._fill_detail_text(video)


# ──────────────────────────────────────────────
#  全局 Worker 管理器（替代旧的 _fetching_set 方案）
# ──────────────────────────────────────────────

# 所有活跃 Worker 实例，key = bvid
_active_workers: dict = {}
_workers_lock = threading.Lock()  # 保护 _active_workers 的并发访问


def _start_worker(gui, bvid, video, interval, fast_interval=None) -> VideoWorker:
    """启动一个视频的独立 Worker

    如果该 bvid 已有运行的 Worker，先停止旧的再启动新的。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        video: 视频数据字典
        interval: 正常刷新间隔（秒）
        fast_interval: 快速刷新间隔（秒，可选）

    Returns:
        VideoWorker: 新创建的 Worker 实例
    """
    with _workers_lock:
        if bvid in _active_workers:
            _active_workers[bvid].stop()
        worker = VideoWorker(gui, bvid, video, interval, fast_interval)
        worker.start()
        _active_workers[bvid] = worker
        return worker


def _stop_worker(bvid):
    """停止并移除指定视频的 Worker

    Args:
        bvid: 视频 BV 号
    """
    with _workers_lock:
        worker = _active_workers.pop(bvid, None)
    if worker:
        worker.stop()
    # 清理合并状态标记
    with _merged_from_db_lock:
        _merged_from_db.discard(bvid)


def _stop_all_workers():
    """停止所有 Worker（应用退出时调用）"""
    with _workers_lock:
        bvids = list(_active_workers.keys())
    for bvid in bvids:
        _stop_worker(bvid)


def _refresh_worker_now(bvid):
    """让指定 Worker 立即执行一次拉取（用于"立即刷新"按钮）

    Args:
        bvid: 视频 BV 号
    """
    with _workers_lock:
        worker = _active_workers.get(bvid)
    if worker:
        worker.refresh_now()


def _update_worker_interval(bvid, new_interval):
    """运行时更新 Worker 的刷新间隔

    Args:
        bvid: 视频 BV 号
        new_interval: 新的刷新间隔（秒）
    """
    with _workers_lock:
        worker = _active_workers.get(bvid)
    if worker:
        worker.update_interval(new_interval)


# ──────────────────────────────────────────────
#  公开 API（保留旧接口，底层接入新 Worker 模型）
# ──────────────────────────────────────────────


def fetch_single_video_data(gui, bvid, callback=None):
    """立即触发一次拉取（绕过等待间隔），用于"单视频立即刷新"场景。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        callback: 可选的完成回调函数 callback(bvid)
    """
    _refresh_worker_now(bvid)
    if callback:
        gui.root.after(0, lambda: callback(bvid))


def fetch_all_video_data(gui, callback=None):
    """立即触发所有监控视频的一次拉取。

    优先使用后端引擎，否则使用 GUI Worker。

    Args:
        gui: BilibiliMonitorGUI 实例
        callback: 可选的回调函数
    """
    try:
        from backend import get_engine
        engine = get_engine()
        if engine.video_count > 0:
            engine.refresh_now()
            return
    except Exception:
        pass

    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        if bvid:
            _refresh_worker_now(bvid)


def auto_predict_video(gui, bvid, callback=None):
    """手动触发单视频预测（由主线程按钮调用）

    在后台线程中运行预测，完成后通过 root.after 回调。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        callback: 可选的完成回调函数 callback(result_dict)
    """
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
    """对所有已加载视频运行初始预测（启动完成后自动调用）

    在后台线程中逐个视频执行预测，完成后更新状态栏。
    """

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
    """启动时从数据库加载监控列表并恢复 UI 卡片。

    数据优先从配置文件 watch_list 读取，回退到后端引擎加载。
    每个视频从数据库读取完整信息后创建 UI 卡片。

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    from ui.theme import C
    from config import load_config
    from core import db

    config = load_config()
    watch_list = config.get("watch_list", [])
    if not watch_list:
        try:
            from backend.engine import load_watch_list_from_db
            watch_list = load_watch_list_from_db()
        except Exception:
            pass
    if not watch_list:
        return

    gui._sb("status", f"正在加载 {len(watch_list)} 个监控视频…", color=C["accent"])

    def _worker():
        loaded = 0
        for bvid in watch_list:
            with gui._data_lock:
                if any(v.get("bvid") == bvid for v in gui.monitored_videos):
                    continue  # 已加载，跳过
            try:
                video_info = db.get_video(bvid)
                if not video_info:
                    gui.log_panel.add_log("WARNING", f"数据库无视频 {bvid}，等待引擎加载")
                    continue

                video = gui._map_api_to_video_dict(bvid, None, video_info)
                video_db = db.get_video_db(bvid)
                gui.video_dbs[bvid] = video_db
                history = video_db.get_all_records()
                if history:
                    gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]

                gui.root.after(0, lambda v=video: gui._restore_video(v))
                loaded += 1
                time.sleep(0.05)  # 短暂延迟，避免 UI 卡顿
            except Exception as e:
                gui.log_panel.add_log("ERROR", f"加载视频 {bvid} 失败: {e}")

        from ui.theme import C as C2
        gui.root.after(
            0, lambda: gui._sb("status", f"已加载 {len(gui.monitored_videos)} 个监控视频", color=C2["success"])
        )
        gui.root.after(100, lambda: auto_predict_all(gui))

    threading.Thread(target=_worker, daemon=True).start()


def _start_all_workers(gui):
    """为 gui.monitored_videos 中所有视频启动独立 Worker。

    如果后端引擎已有活跃 Worker，则跳过以避免重复拉取。

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    try:
        from backend import get_engine
        engine = get_engine()
        if engine.video_count > 0:
            gui.log_panel.add_log("INFO", f"后端引擎已运行 ({engine.video_count} 个视频)，GUI 复用引擎数据")
            return
    except Exception:
        pass

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
