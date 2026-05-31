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
    gui._global_tick_job = gui.root.after(1000, lambda: global_tick(gui))


def stop_global_tick(gui):
    """停止全局 tick 循环"""
    if gui._global_tick_job:
        gui.root.after_cancel(gui._global_tick_job)
        gui._global_tick_job = None


def global_tick(gui):
    """每秒一次的全局 tick：更新倒计时、模式指示、周期性维护"""
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

        if min_remaining == float("inf"):
            badge_text = "— s"
        else:
            badge_text = f"{int(max(0, min_remaining)):02d} s"
        gui._countdown_badge.config(text=badge_text)

        if fast_count > 0:
            gui._mode_pill.config(text=f"⚡ {fast_count}个快速", fg=C["danger"])
        else:
            gui._mode_pill.config(text="● 正常模式", fg=C["success"])

        gui._sb("interval", f"正常{gui.DEFAULT_INTERVAL}s / 快速{gui.FAST_INTERVAL}s")

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
        except Exception as e:
            logger.warning("每小时同步异常: %s", e)

    threading.Thread(target=_sync_worker, daemon=True).start()


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
