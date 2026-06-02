"""
全局 tick 循环与周期性维护任务模块

负责应用程序的定时任务调度，包括:
  - global_tick           : 每秒一次的主循环，更新倒计时、模式指示、触发周期性任务
  - do_periodic_sync      : 每小时执行一次数据库同步（后台线程）
  - scan_alerts_background: 后台扫描全量视频的异常，更新状态栏 + 推送通知
  - wal_checkpoint_worker : 后台线程执行 SQLite WAL checkpoint 优化

Tkinter 的单线程模型中，所有定时任务通过 root.after() 排程。
"""

import threading
import time
import logging

from core.smart_alert import AnomalyDetector
from ui.theme import C

logger = logging.getLogger(__name__)


def start_global_tick(gui):
    """启动全局 tick 循环（每秒一次）

    使用 Tkinter 的 after() 方法排程，每次 tick 完成后自动排程下一次。

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    if gui._global_tick_job:
        gui.root.after_cancel(gui._global_tick_job)
    gui._global_tick_job = gui.root.after(1000, lambda: global_tick(gui))


def stop_global_tick(gui):
    """停止全局 tick 循环

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    if gui._global_tick_job:
        gui.root.after_cancel(gui._global_tick_job)
        gui._global_tick_job = None


def global_tick(gui):
    """每秒一次的全局 tick：更新倒计时、模式指示、周期性维护

    每 tick 执行:
      1. 遍历所有视频定时器，计算各视频上次刷新后经过的时间
      2. 更新倒计时徽章（显示距离下次刷新的最短剩余秒数）
      3. 更新模式指示器（正常模式 / 快速模式 / 已暂停）
      4. 周期性任务:
         - 每 3600 秒（1小时）：do_periodic_sync（数据库同步）
         - 每 300 秒（5分钟）：WAL checkpoint + 异常告警扫描

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    try:
        if not gui.auto_refresh_enabled.get():
            gui._global_tick_job = None
            return

        now = time.time()
        fast_count = 0  # 快速模式视频计数
        min_remaining = float("inf")  # 距离下次刷新的最短剩余时间

        # 遍历所有视频定时器
        for bvid, timer in list(gui._video_timers.items()):
            remaining = timer["next"] - now
            if timer["interval"] == gui.FAST_INTERVAL:
                fast_count += 1
            if remaining < min_remaining:
                min_remaining = remaining

        # 更新倒计时徽章
        if min_remaining == float("inf"):
            badge_text = "— s"
        else:
            badge_text = f"{int(max(0, min_remaining)):02d} s"
        gui._countdown_badge.config(text=badge_text)

        # 更新模式指示器
        if fast_count > 0:
            gui._mode_pill.config(text=f"⚡ {fast_count}个快速", fg=C["danger"])
        else:
            gui._mode_pill.config(text="● 正常模式", fg=C["success"])

        gui._sb("interval", f"正常{gui.DEFAULT_INTERVAL}s / 快速{gui.FAST_INTERVAL}s")

        # 周期性维护任务
        gui._tick_counter = (gui._tick_counter + 1) % 3600  # 0~3599 循环计数
        if gui._tick_counter == 0:
            do_periodic_sync(gui)  # 每小时数据库同步
        elif gui._tick_counter % 300 == 0:
            # 每 5 分钟: WAL checkpoint + 异常告警（后台线程执行）
            threading.Thread(target=lambda: wal_checkpoint_worker(gui), daemon=True).start()
            threading.Thread(target=lambda: scan_alerts_background(gui), daemon=True).start()
    except Exception:
        logger.exception("_global_tick 异常，继续调度")
    # 排程下一次 tick
    gui._global_tick_job = gui.root.after(1000, lambda: global_tick(gui))


def do_periodic_sync(gui):
    """每小时执行一次数据库同步（不阻塞主线程）

    同步流程:
      1. 遍历所有视频独立数据库，同步到中央数据库
      2. 同步到备份目录（data/）
      3. 记录同步结果日志

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    logger.info("开始每小时数据同步…")

    def _sync_worker():
        try:
            from core import db

            # 同步每个视频的独立库 → 中央库
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
            # 同步到备份目录
            try:
                db.sync_per_video_dbs_to_backup()
            except Exception as e:
                logger.debug("忽略异常: %s", e)
        except Exception as e:
            logger.warning("每小时同步异常: %s", e)

    threading.Thread(target=_sync_worker, daemon=True).start()


def scan_alerts_background(gui):
    """后台扫描全量视频的异常，更新状态栏 + 推送通知

    流程:
      1. 遍历所有监控视频，从各自数据库中读取最近 20 条记录
      2. 使用 AnomalyDetector 检测异常（播放量异常、互动率异常等）
      3. 如果有异常，更新状态栏并推送通知到 QQ/Windows

    Args:
        gui: BilibiliMonitorGUI 实例
    """
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
            continue  # 数据不足，无法进行有意义的异常检测
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
    """后台线程执行 SQLite WAL checkpoint，避免阻塞主线程

    WAL (Write-Ahead Log) 模式下，checkpoint 将 WAL 文件内容合并回主数据库文件，
    释放磁盘空间并优化读取性能。对中央数据库和所有视频独立数据库执行。

    Args:
        gui: BilibiliMonitorGUI 实例
    """
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
