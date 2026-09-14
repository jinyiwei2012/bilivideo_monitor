"""
事件处理器 - PyQt6 版

更新检查、下载、退出、监控管理、推送等回调函数。
所有函数接收 gui (BilibiliMonitorGUI) 作为第一个参数。
"""

import math
import time
import logging
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QMessageBox,
    QApplication,
)
from PyQt6.QtCore import QTimer

from ui.theme import C
from ui.invoker import invoke, invoke_later
from ui.main_gui_events_monitor import get_video
from ui.helpers import (
    THRESHOLD_NAMES,
    fmt_num,
    nearest_threshold_gap,
    fmt_eta,
)
from ui.lty_voice import (
    success,
    warning,
    no_video,
)
from utils.time_utils import safe_timestamp
from utils.thread_utils import fire_and_forget

logger = logging.getLogger(__name__)


def on_exit(gui):
    """应用退出时的清理工作"""
    from ui.main_gui_data import save_watch_list

    save_watch_list(gui)
    gui.log_panel.cleanup()
    from ui.main_gui_tick import stop_global_tick

    stop_global_tick(gui)
    gui._stop_export_schedule()
    gui._file_logger.cancel_midnight_checker()
    gui._file_logger.close()
    from ui.monitor import _stop_all_workers

    _stop_all_workers()
    from core import db, bilibili_api

    for bvid in gui.video_dbs:
        try:
            gui.video_dbs[bvid].close()
        except Exception as e:
            logger.debug("关闭视频数据库失败 %s: %s", bvid, e)
    db.close()
    bilibili_api.close()
    try:
        from ui.video_list_panel import _cover_session

        _cover_session.close()
    except Exception as e:
        logger.debug("关闭封面 Session 失败: %s", e)
    from algorithms.registry import AlgorithmRegistry

    AlgorithmRegistry.shutdown()
    try:
        from core.notification import notification_manager

        notification_manager.shutdown()
    except Exception as e:
        logger.debug("关闭 NotificationManager 失败: %s", e)

    try:
        from algorithms.online_learner import get_online_learner
        from ui.helpers import project_path

        learner = get_online_learner()
        learner.save(project_path("data", "online_learner_state.json"))
    except Exception as e:
        logger.debug("保存在线学习状态失败: %s", e)

    try:
        from core.database.connection import close_http_session

        close_http_session()
    except Exception as e:
        logger.debug("关闭 HTTP Session 失败: %s", e)

    QApplication.quit()


# ── 模型激活 ─────────────────────────────────


def refresh_model_status(gui):
    """刷新模型激活状态显示"""
    try:
        from algorithms.training.checkpoint_manager import get_all_activation_status

        status = get_all_activation_status()
        pending = [aid for aid, s in status.items() if s["needs_activation"]]
        trained = len(status)
    except Exception as e:
        logger.debug("刷新模型状态失败: %s", e)
        gui._model_act_status.setText("")
        return
    if pending:
        gui._model_act_status.setText(f"⚡ {len(pending)}/{trained} 个还等着激活哦 ♪")
        gui._model_act_status.setStyleSheet(f"color: {C['danger']}; font-size: 9pt;")
    elif trained > 0:
        gui._model_act_status.setText(f"✓ {trained} 个都是最新旋律啦 ♪")
        gui._model_act_status.setStyleSheet(f"color: {C['success']}; font-size: 9pt;")
    else:
        gui._model_act_status.setText("")


def activate_models(gui):
    """手动激活所有算法的最新 checkpoint"""
    from algorithms.training.checkpoint_manager import activate_latest_for_all

    switched = activate_latest_for_all()
    if not switched:
        gui._sb("status", "所有模型都已是最新旋律啦 ♪ 天依可以唱得更准了~", C["success"])
        refresh_model_status(gui)
        return
    names = ", ".join(switched.keys())
    gui._sb("status", f"已激活 {len(switched)} 个模型啦!♪ 天依的歌声准备好了: {names}", C["success"])
    refresh_model_status(gui)
    gui.log_panel.add_log("INFO", f"手动激活模型: {switched}")


def auto_activate_on_startup(gui):
    """启动时自动激活所有算法的最新 checkpoint（后台线程）"""

    def _worker():
        try:
            from algorithms.training.checkpoint_manager import activate_latest_for_all

            switched = activate_latest_for_all()
            if switched:
                names = ", ".join(switched.keys())
                invoke(lambda: gui.log_panel.add_log("INFO", f"启动自动激活模型: {switched}"))
                invoke(
                    lambda: gui._sb(
                        "status", f"自动激活了 {len(switched)} 个模型哦 ♪ 天依记得它们啦: {names}", C["success"]
                    )
                )
            invoke(lambda: refresh_model_status(gui))
        except Exception as e:
            logger.debug("自动激活模型失败: %s", e)
            invoke(lambda: refresh_model_status(gui))

    fire_and_forget(_worker, name="auto-activate")


# ── 初始化 ─────────────────────────────────────


def preload_algorithms(gui):
    """后台线程预加载 AlgorithmRegistry"""

    def _worker():
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        n = len(AlgorithmRegistry.get_algorithm_names())
        logger.info("后台算法预加载完成，共 %d 个算法", n)

    fire_and_forget(_worker, name="algo-preload")


# ── 视频间隔 / 定时器 ──────────────────────────


def get_video_interval(gui, video):
    """根据视频播放量确定刷新间隔"""
    views = video.get("view_count", 0)
    gap, _ = nearest_threshold_gap(views)
    if 0 < gap < gui.THRESHOLD_GAP:
        return gui.FAST_INTERVAL
    return gui.DEFAULT_INTERVAL


def register_video_timer(gui, bvid):
    """注册视频定时器"""
    video = get_video(gui, bvid)
    if not video:
        return
    interval = get_video_interval(gui, video)
    gui._video_timers[bvid] = {"next": time.time() + interval, "interval": interval}


def start_auto_refresh(gui):
    """启动自动刷新"""
    if gui.auto_refresh_enabled:
        from ui.main_gui_tick import start_global_tick

        start_global_tick(gui)


# ── 刷新 / 拉取 ────────────────────────────────


def toggle_auto_refresh(gui):
    """切换自动刷新开关（QCheckBox.toggled 已携带新状态，勿再取反）"""
    cur = gui.auto_refresh_enabled
    if cur:
        from ui.main_gui_tick import start_global_tick

        start_global_tick(gui)
        gui._sb("status", "自动刷新已启用啦!♪ 天依会一直守着,等数据发光的那一刻~", C["success"])
    else:
        from ui.main_gui_tick import stop_global_tick

        stop_global_tick(gui)
        gui._countdown_badge.setText("已暂停 ♪")
        gui._mode_pill.setText("已暂停 ♪")
        gui._mode_pill.setStyleSheet(f"color: {C['text_3']}; font-weight: bold; font-size: 9pt;")
        gui._sb("status", "自动刷新暂停啦…像歌的间奏一样,天依随时可以继续哦 ♪", C["warning"])


def do_fetch(gui):
    """执行数据拉取"""
    from ui.monitor import fetch_all_video_data

    fetch_all_video_data(gui)


def post_fetch(gui):
    """拉取完成后的回调处理"""
    now_str = datetime.now().strftime("%H:%M:%S")
    gui._sb("status", success("刷新"), C["success"])
    gui._sb("last_ref", f"上次刷新: {now_str} ♪")
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个视频 ♪")
    for video in gui.monitored_videos:
        bvid = video.get("bvid", "")
        gui.video_list.update_card(video)
        register_video_timer(gui, bvid)
    if gui.selected_bvid:
        video = get_video(gui, gui.selected_bvid)
        if video:
            gui.detail.update_stat_bar(video)
            if gui.detail.current_tab == "↗ 播放量趋势":
                gui.detail._auto_render_chart()
    from ui.monitor import auto_predict_all

    auto_predict_all(gui)


# ── 推送 ──────────────────────────────────────


def push_single(gui, bvid):
    """推送单个视频状态"""
    video = get_video(gui, bvid)
    if not video:
        QMessageBox.warning(gui, warning(""), f"呜…没找到视频 {bvid} 呢,天依再帮你找找别的光吧 ♪")
        return

    msg = build_push_msg(gui, [video])
    title = video.get("title", bvid)[:30]

    # 推送是阻塞网络 IO（单渠道 timeout=8s，4 渠道串行）→ 移出主线程避免 UI 冻结
    def _worker():
        from core.notification import notification_manager

        notification_manager.send_qq_private(msg)
        notification_manager.send_qq_group(msg)
        notification_manager.send_webhook(f"◧ B站监控 — {title[:20]}\n{msg}")
        notification_manager.send_windows_notification(f"◧ B站监控 — {title[:20]}", msg[:256])
        invoke(lambda: gui._sb("status", f"已把「{title[:20]}」的歌声传给大家啦 ♪", C["success"]))

    fire_and_forget(_worker, name="push-single")


def manual_push(gui):
    """手动推送所有监控视频状态"""
    videos = gui.monitored_videos
    if not videos:
        QMessageBox.warning(gui, warning(""), no_video())
        return

    msg = build_push_msg(gui, videos)
    now_str = datetime.now().strftime("%H:%M")
    video_count = len(videos)

    # 推送是阻塞网络 IO → 移出主线程，结果分支在 worker 内判定后回主线程刷状态栏
    def _worker():
        from core.notification import notification_manager

        ok_qq_private = notification_manager.send_qq_private(msg)
        ok_qq_group = notification_manager.send_qq_group(msg)
        ok_webhook = notification_manager.send_webhook(f"◧ B站监控报告 ({now_str})\n{msg}")
        ok_win = notification_manager.send_windows_notification(f"◧ B站监控报告 ({now_str})", msg[:256])

        if ok_qq_private or ok_qq_group or ok_webhook:
            status, color = f"已把 {video_count} 首歌的现状唱给大家听啦 ♪", C["success"]
        elif ok_win:
            status, color = "这次只有 Windows 通知送达哦…QQ 那边天依够不到 ♪", C["warning"]
        else:
            status, color = "呜…推送失败了,天依的声音没传出去,请检查通知设置哦 ♪", C["danger"]
        invoke(lambda: gui._sb("status", status, color))

    fire_and_forget(_worker, name="push-all")


# ── 训练完成回调 ──────────────────────────────


def on_training_completed(gui, mode="训练", count=0, detail="", trained_ids=None):
    """训练/微调完成后自动刷新预测 + 推送通知 + 更新权重"""
    now_str = datetime.now().strftime("%H:%M")
    if count > 0 and detail:
        msg = f"◉ {mode}完成 ({now_str})\n{count} 个算法: {detail}"
    elif count > 0:
        msg = f"◉ {mode}完成 ({now_str})\n共 {count} 个算法已更新"
    else:
        msg = f"◉ {mode}完成 ({now_str})"

    # 推送是阻塞网络 IO → 移出主线程（4 渠道串行，异常时最长可冻结数十秒）
    def _notify_worker():
        try:
            from core.notification import notification_manager

            notification_manager.send_qq_private(msg)
            notification_manager.send_qq_group(msg)
            notification_manager.send_webhook(f"◉ {mode}完成 ({now_str})\n{msg}")
            notification_manager.send_windows_notification(f"◉ {mode}完成", msg[:256])
        except Exception as e:
            logger.debug("训练推送异常: %s", e)

    try:
        fire_and_forget(_notify_worker, name="train-notify")
    except Exception as e:
        logger.debug("启动训练完成推送失败: %s", e)

    if trained_ids:
        try:
            update_trained_weights(gui, trained_ids)
        except Exception as e:
            logger.debug("更新训练算法权重失败: %s", e)

    try:
        fire_and_forget(lambda: run_post_training_predict(gui), name="post-train-predict")
    except Exception as e:
        logger.debug("启动训练后预测失败: %s", e)


def update_trained_weights(gui, algo_ids):
    """训练完成后提升算法 ML 权重"""
    from algorithms.registry import AlgorithmRegistry
    from ui.helpers import load_algo_confidence

    for algo_id in algo_ids:
        conf = load_algo_confidence(algo_id)
        accuracy = max(0.5, conf)
        # B1: 旧调用 update_accuracy(algo_id, 1.0, accuracy) 把 1.0 当 predicted 硬塞 → 语义错乱
        # 现改为 accuracy 关键字显式传递（registry 已统一两种调用入口）
        AlgorithmRegistry.update_accuracy(algo_id, accuracy=accuracy)
    logger.info("已更新 %d 个训练完成算法的权重", len(algo_ids))


def run_post_training_predict(gui):
    """后台并行重跑所有监控视频的预测"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ui.monitor import _predict_single

    bvids = [v.get("bvid", "") for v in gui.monitored_videos if v.get("bvid")]
    if not bvids:
        return

    video_map = {v.get("bvid"): v for v in gui.monitored_videos if v.get("bvid")}

    logger.info("训练完成，开始并行预测 %d 个视频…", len(bvids))

    def _predict_one(bvid):
        video = video_map.get(bvid)
        if not video:
            return bvid, None
        try:
            result = _predict_single(gui, bvid, video)
            return bvid, result
        except Exception as e:
            logger.debug("训练后预测 %s 失败: %s", bvid, e)
            return bvid, None

    max_workers = min(len(bvids), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_predict_one, bvid): bvid for bvid in bvids}
        for future in as_completed(futures):
            bvid, result = future.result()
            if result:
                logger.debug("训练后预测 %s 完成: %.0f", bvid, result.get("prediction", 0))

    total_videos = len(gui.monitored_videos)
    status_msg = f"训练后预测完成啦!♪ 天依把 {total_videos} 首歌重新听了一遍"
    try:
        from algorithms.training.npu_inference import get_npu_engine

        engine = get_npu_engine()
        stats = engine.stats
        if stats.total_inferences > 0:
            cache = engine.get_cache_info()
            status_msg += (
                f" | NPU: {stats.total_inferences}次推理"
                f" {stats.avg_latency_ms:.2f}ms/次"
                f" 缓存{cache['memory_models']}模型"
            )
            logger.info(
                "NPU 推理统计: %d次 平均%.3fms 缓存命中%d 编译%d次(%.0fms)",
                stats.total_inferences,
                stats.avg_latency_ms,
                stats.cache_hits,
                stats.compile_count,
                stats.compile_total_ms,
            )
    except Exception:
        pass
    invoke(lambda: gui._sb("status", status_msg, C["success"]))
    if gui.selected_bvid:
        if gui.selected_bvid in gui.prediction_results:
            r = gui.prediction_results[gui.selected_bvid]
            invoke(
                lambda: prediction_done(
                    gui,
                    r["prediction"],
                    r["current_view"],
                    r["growth"],
                    r["rate_per_sec"],
                    r.get("success_list", []),
                    r.get("fail_list", []),
                    r["valid"],
                    r["total"],
                    r.get("surge_info"),
                ),
            )
        invoke_later(100, lambda: gui.detail._manual_render_chart())
    logger.info("训练后预测完成 (%d 个视频)", len(bvids))


# ── 每日推送 ──────────────────────────────────


def schedule_daily_push(gui):
    """计算到下次 23:50 的秒数，用 QTimer.singleShot 排程"""
    now = datetime.now()
    target = now.replace(hour=23, minute=50, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    delay_ms = int((target - now).total_seconds() * 1000)
    QTimer.singleShot(delay_ms, lambda: daily_push(gui))
    logger.info("已安排每日推送: %s", target.strftime("%Y-%m-%d %H:%M"))


def daily_push(gui):
    """每日 23:50 自动推送日报"""
    from core.notification import notification_manager

    try:
        msg = build_daily_push_msg(gui)
        notification_manager.send_qq_private(msg)
        notification_manager.send_qq_group(msg)
        notification_manager.send_webhook(f"◧ B站监控日报 ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n{msg}")
        notification_manager.send_windows_notification("◧ B站监控日报", msg[:256])
        logger.info("每日推送完成")
    except Exception as e:
        logger.error("每日推送异常: %s", e)
    finally:
        schedule_daily_push(gui)


def build_daily_push_msg(gui):
    """构建每日日报消息"""
    from datetime import date
    from utils.yearly_score import calculate_yearly_from_dict as _calc_ys

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = date.today()
    lines = [f"◧ B站监控日报 ({now_str})", f"监控 {len(gui.monitored_videos)} 个视频：", "─" * 30]

    for i, v in enumerate(gui.monitored_videos, 1):
        bvid = v.get("bvid", "")
        title = v.get("title", bvid)[:30]
        views = v.get("view_count", 0)
        likes = v.get("like_count", 0)
        coins = v.get("coin_count", 0)

        with gui._data_lock:
            history = list(gui.history_data.get(bvid, []))
        history = sorted(history, key=lambda x: safe_timestamp(x[0]))
        daily_incr = 0
        first_today = None
        for ts, vc in history:
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                if ts.date() == today:
                    if first_today is None:
                        first_today = vc
                    daily_incr = max(0, vc - first_today)
            except Exception as e:
                logger.debug("忽略异常: %s", e)

        ys_text = "—"
        try:
            ys = _calc_ys(v)
            if ys:
                ys_text = f"{ys.total_score:,.0f}"
        except Exception:
            pass

        pred_info = ""
        cached = gui.prediction_results.get(bvid)
        if cached:
            w_pred = cached.get("prediction", 0)
            growth = cached.get("growth", 0)
            valid = cached.get("valid", 0)
            total = cached.get("total", 0)
            if w_pred > 0:
                pred_info = f"  预测: {fmt_num(int(w_pred))} (+{fmt_num(int(growth))})  有效: {valid}/{total}"

        lines.append(f"\n{i}. 《{title}》")
        lines.append(f"   播放: {fmt_num(views)}  (+{fmt_num(daily_incr)} 今天)")
        lines.append(f"   ✓ {fmt_num(likes)}  ◎ {fmt_num(coins)}")
        lines.append(f"   年刊: {ys_text}{pred_info}")

    return "\n".join(lines)


def build_push_msg(gui, videos):
    """构建手动推送消息文本"""
    from utils.yearly_score import calculate_yearly_from_dict as _calc_ys

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"◧ B站监控报告 ({now_str})", f"监控 {len(videos)} 个视频：", "─" * 20]

    for i, v in enumerate(videos, 1):
        bvid = v.get("bvid", "?")
        title = v.get("title", bvid)[:30]
        views = v.get("view_count", 0)
        likes = v.get("like_count", 0)
        coins = v.get("coin_count", 0)

        ys_text = ""
        try:
            ys = _calc_ys(v)
            if ys:
                ys_text = f"  年刊: {ys.total_score:,.0f}"
        except Exception:
            pass

        with gui._data_lock:
            history = list(gui.history_data.get(bvid, []))
        velocity = 0
        if len(history) >= 2:
            t1, c1 = history[-2]
            t0, c0 = history[-1]
            t0 = safe_timestamp(t0)
            t1 = safe_timestamp(t1)
            dt = (t0 - t1) / 3600
            if dt > 0:
                velocity = max(0, (c0 - c1)) / dt if isinstance(c0, (int, float)) else 0

        gap, idx = nearest_threshold_gap(views)
        eta = ""
        if gap > 0 and velocity > 0:
            eta_min = gap / velocity * 60
            eta = f"  预计达{THRESHOLD_NAMES[idx]}: {fmt_eta(eta_min)}"

        algo_lines = []
        cached = gui.prediction_results.get(bvid)
        if cached:
            succ = cached.get("success_list", [])
            sorted_algos = sorted(succ, key=lambda x: x[3], reverse=True)[:3]
            for name, pv, _, conf, ph in sorted_algos:
                if ph > 0:
                    eta_str = fmt_eta(ph * 60)
                    conf_pct = f"{conf * 100:.0f}%" if conf > 0 else "—"
                    algo_lines.append(f"     {name}: {fmt_num(int(pv))} ({eta_str}, {conf_pct})")

        lines.append(f"{i}. 《{title}》")
        lines.append(f"   播放: {fmt_num(views)}  |  ✓ {fmt_num(likes)}  |  ◎ {fmt_num(coins)}")
        lines.append(f"   增速: {math.ceil(velocity)}/h{eta}{ys_text}")
        if algo_lines:
            lines.extend(algo_lines)

    return "\n".join(lines)


# ── 预测结果回调 ──────────────────────────────


def prediction_done(
    gui,
    w_pred,
    current_view,
    growth,
    rate_per_sec,
    success_list,
    fail_list,
    valid,
    total,
    surge_info=None,
    bias_info=None,
    eta_info=None,
):
    """预测完成回调"""
    gui.prediction.build_pred_hero(w_pred, current_view, rate_per_sec, surge_info, bias_info, eta_info)
    gui.prediction._update_algo_list(success_list, fail_list)
    gui._sb("algo", f"算法: {valid}/{total}")
    status = "预测完成啦!♪ 天依听见了未来的旋律~"
    # C2: log-ETA 可用时状态栏补充到达时间估计
    if eta_info and eta_info.get("eta_hours"):
        _th = eta_info.get("eta_threshold_name") or ""
        _h = eta_info["eta_hours"]
        if _h < 24:
            _eta_str = f"{_h:.1f}小时"
        elif _h < 24 * 30:
            _eta_str = f"{_h / 24:.1f}天"
        else:
            _eta_str = f"{_h / 24 / 30:.1f}月"
        _n = eta_info.get("eta_n", 0)
        status = f"预测完成啦!♪ 按 {_n} 个算法共识, 到达 {_th} 约需 {_eta_str}"
    if bias_info and bias_info.get("applied"):
        factor = bias_info.get("factor", 1.0)
        samples = bias_info.get("samples", 0)
        if factor < 1.0:
            pct = (1.0 - factor) * 100
            status = f"校准 {pct:.0f}%↓ (近 {samples} 次集成高估修正) ♪"
        elif factor > 1.0:
            pct = (factor - 1.0) * 100
            status = f"校准 {pct:.0f}%↑ (近 {samples} 次集成低估修正) ♪"
        else:
            status = f"集成偏差已校准 (样本 {samples}) ♪"
        gui._sb("status", status, C["warning"])
    else:
        gui._sb("status", status, C["success"])


# ── 弹窗透传 ──────────────────────────────────


def open_interval_settings(gui):
    gui._dialogs.open_interval_settings()


def open_database_query(gui):
    gui._dialogs.open_database_query()


def open_video_search(gui):
    gui._dialogs.open_video_search()


def open_data_comparison(gui):
    gui._dialogs.open_data_comparison()


def open_crossover_analysis(gui):
    gui._dialogs.open_crossover_analysis()


def open_weekly_score(gui):
    gui._dialogs.open_weekly_score()


def open_milestone_stats(gui):
    gui._dialogs.open_milestone_stats()


def import_search_results(gui, videos: list):
    gui._dialogs.import_search_results(videos)
