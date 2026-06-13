"""
全局 tick 循环与周期性维护任务
"""

import threading
import time
import logging

from core.smart_alert import AnomalyDetector
from ui.theme import C

logger = logging.getLogger(__name__)


def start_global_tick(gui):
    """启动全局 tick 循环"""
    if gui._global_tick_job:
        gui.root.after_cancel(gui._global_tick_job)
    # 缓存上一次显示的倒计时文本，避免无变更时的无效 .config() 调用
    gui._last_countdown_text = ""
    gui._last_mode_text = ""
    gui._last_interval_text = ""
    gui._global_tick_job = gui.root.after(1000, lambda: global_tick(gui))


def stop_global_tick(gui):
    """停止全局 tick 循环"""
    if gui._global_tick_job:
        gui.root.after_cancel(gui._global_tick_job)
        gui._global_tick_job = None


def global_tick(gui):
    """每秒一次的全局 tick：更新倒计时、模式指示、周期性维护。
    值未变时跳过 Tkinter .config() 调用，避免无效重绘。"""
    try:
        if not gui.auto_refresh_enabled.get():
            gui._global_tick_job = None
            return

        now = time.time()
        fast_count = 0
        min_remaining = float("inf")

        for bvid, timer in list(gui._video_timers.items()):
            remaining = timer["next"] - now
            if timer["interval"] == gui.FAST_INTERVAL:
                fast_count += 1
            if remaining < min_remaining:
                min_remaining = remaining

        # 只在文本变更时才调用 .config()（Tkinter .config 会触发 widget 重绘）
        if min_remaining == float("inf"):
            badge_text = "— s"
        else:
            badge_text = f"{int(max(0, min_remaining)):02d} s"
        if badge_text != getattr(gui, "_last_countdown_text", ""):
            gui._countdown_badge.config(text=badge_text)
            gui._last_countdown_text = badge_text

        mode_text = f"⚡ {fast_count}个快速" if fast_count > 0 else "● 正常模式"
        mode_fg = C["danger"] if fast_count > 0 else C["success"]
        if mode_text != getattr(gui, "_last_mode_text", ""):
            gui._mode_pill.config(text=mode_text, fg=mode_fg)
            gui._last_mode_text = mode_text

        interval_text = f"正常{gui.DEFAULT_INTERVAL}s / 快速{gui.FAST_INTERVAL}s"
        if interval_text != getattr(gui, "_last_interval_text", ""):
            gui._sb("interval", interval_text)
            gui._last_interval_text = interval_text

        gui._tick_counter = (gui._tick_counter + 1) % 3600
        if gui._tick_counter == 0:
            do_periodic_sync(gui)
        elif gui._tick_counter % 300 == 0:
            threading.Thread(target=lambda: wal_checkpoint_worker(gui), daemon=True).start()
            threading.Thread(target=lambda: scan_alerts_background(gui), daemon=True).start()
    except Exception:
        logger.exception("_global_tick 异常，继续调度")
    gui._global_tick_job = gui.root.after(1000, lambda: global_tick(gui))


def do_periodic_sync(gui):
    """每小时执行一次数据库同步（不阻塞主线程）"""
    logger.info("开始每小时数据同步…")

    def _sync_worker():
        try:
            from core import db

            for bvid in list(gui.video_dbs.keys()):
                try:
                    db.sync_from_video_db(bvid)
                except Exception as e:
                    logger.debug("同步视频库 %s 失败: %s", bvid, e)
            result = db.sync_to_central()
            logger.info(
                "每小时同步完成: %d视频 %d记录 %d瑕疵",
                result.get("synced_videos", 0),
                result.get("synced_records", 0),
                result.get("fixed_flaws", 0),
            )
            try:
                db.sync_per_video_dbs_to_backup()
            except Exception as e:
                logger.debug("忽略异常: %s", e)

            # 每15天清理一次 predictions 历史重复行
            _maybe_cleanup_predictions(gui)

            # 每24小时清理一次 OnlineLearner 过期追踪器
            _maybe_cleanup_online_learner(gui)
        except Exception as e:
            logger.warning("每小时同步异常: %s", e)

    threading.Thread(target=_sync_worker, daemon=True).start()


def _maybe_cleanup_predictions(gui):
    """每15天清理一次预测表中的历史重复行（保留综合预测数据，清理多算法详细预测的重复）"""
    import time

    now = time.time()
    last = getattr(gui, "_last_prediction_cleanup", 0)
    fifteen_days = 15 * 24 * 3600
    if now - last < fifteen_days:
        return
    gui._last_prediction_cleanup = now

    try:
        from core import db

        # 清理中央库
        central_result = db.cleanup_duplicate_predictions()
        # 清理各视频独立库
        total_deleted = central_result.get("deleted", 0)
        total_mirror_deleted = central_result.get("mirror_deleted", 0) if "mirror_deleted" in central_result else 0
        for bvid, video_db in list(gui.video_dbs.items()):
            try:
                vr = video_db.cleanup_duplicate_predictions()
                total_deleted += vr.get("deleted", 0)
                total_mirror_deleted += vr.get("mirror_deleted", 0)
            except Exception as e:
                logger.debug("清理视频库预测失败 %s: %s", bvid, e)

        if total_deleted > 0:
            logger.info(
                "15天预测清理完成: 共删除 %d 行重复数据 (镜像 %d 行)",
                total_deleted, total_mirror_deleted,
            )
    except Exception as e:
        logger.warning("预测清理异常: %s", e)


def _maybe_cleanup_online_learner(gui):
    """每24小时清理一次 OnlineLearner 中过期（超过48小时未更新）的追踪器。"""
    import time

    now = time.time()
    last = getattr(gui, "_last_learner_cleanup", 0)
    if now - last < 86400:  # 24 hours
        return
    gui._last_learner_cleanup = now
    try:
        from algorithms.online_learner import get_online_learner
        get_online_learner().cleanup_stale(max_age_seconds=172800)  # 48h
    except Exception as e:
        logger.debug("OnlineLearner 清理失败: %s", e)


def scan_alerts_background(gui):
    """后台扫描全量视频的异常，更新状态栏 + 推送通知"""
    from core.notification import notification_manager

    alerts = []
    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        records = []
        try:
            video_db = gui.video_dbs.get(bvid)
            if video_db:
                raw = video_db.get_all_records(limit=20)
                for r in raw:
                    records.append(
                        {
                            "timestamp": r["timestamp"],
                            "view_count": r["view_count"],
                            "like_count": r.get("like_count", 0),
                            "coin_count": r.get("coin_count", 0),
                            "viewers_total": r.get("viewers_total", 0),
                        }
                    )
        except Exception as e:
            logger.debug("从DB获取记录失败 %s: %s", bvid, e)
        if len(records) < 3:
            continue
        try:
            for msg in AnomalyDetector.detect_all(records, bvid=bvid, video=video):
                alerts.append((bvid, video.get("title", bvid)[:20], msg))
        except Exception as e:
            logger.debug("忽略异常: %s", e)

    if alerts:
        n = len(alerts)
        gui.root.after(0, lambda: gui._sb("alert", f"🚨 {n} 条异常", C["danger"]))
        title = f"🚨 B站监控异常告警 ({n} 条)"
        msg_lines = [title, "─" * 20]
        for bvid, t, a in alerts[:5]:
            msg_lines.append(f"  [{bvid}] {t}")
            msg_lines.append(f"    {a}")
        if n > 5:
            msg_lines.append(f"  … 还有 {n - 5} 条")
        msg = "\n".join(msg_lines)
        try:
            notification_manager.send_qq_private(msg)
            notification_manager.send_qq_group(msg)
            notification_manager.send_windows_notification(title, msg[:256])
            gui.log_panel.add_log("INFO", f"异常告警已推送 ({n} 条)")
        except Exception as e:
            logger.debug("推送异常告警失败: %s", e)
    else:
        gui.root.after(0, lambda: gui._sb("alert", ""))


def wal_checkpoint_worker(gui):
    """后台线程执行 WAL checkpoint，避免阻塞主线程"""
    try:
        from core import db

        db.wal_checkpoint()
        for vdb in list(gui.video_dbs.values()):
            try:
                with vdb._get_connection() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.debug("忽略异常: %s", e)
    except Exception as e:
        logger.debug("忽略异常: %s", e)
