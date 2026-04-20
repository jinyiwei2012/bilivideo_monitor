"""
监控业务逻辑模块 - 数据拉取、预测、监控管理
"""
import threading
import time
from datetime import datetime
from algorithms.registry import AlgorithmRegistry
from core import bilibili_api, MonitorRecord
from ui.helpers import (
    THRESHOLDS, THRESHOLD_NAMES, THRESH_COLORS,
    fmt_num, _parse_viewer_count, fmt_eta,
)


def fetch_all_video_data(gui):
    """在后台线程中拉取所有视频数据"""
    if not gui.monitored_videos:
        return
    gui._sb("status", f"正在刷新 {len(gui.monitored_videos)} 个视频…", C=None)
    gui.log_panel.add_log("INFO", f"开始刷新 {len(gui.monitored_videos)} 个视频")

    def _worker():
        for video in gui.monitored_videos:
            bvid = video.get("bvid", "")
            if not bvid:
                continue
            info = bilibili_api.get_video_info(bvid)
            if info:
                stat  = info.get("stat", {})
                owner = info.get("owner", {})
                video["title"]          = info.get("title",    video.get("title",""))
                video["author"]         = owner.get("name",    video.get("author",""))
                video["pic"]            = info.get("pic",      video.get("pic",""))
                video["view_count"]     = stat.get("view",     video.get("view_count",0))
                video["like_count"]     = stat.get("like",     video.get("like_count",0))
                video["coin_count"]     = stat.get("coin",     video.get("coin_count",0))
                video["share_count"]    = stat.get("share",    video.get("share_count",0))
                video["favorite_count"] = stat.get("favorite", video.get("favorite_count",0))
                video["danmaku_count"]  = stat.get("danmaku",  video.get("danmaku_count",0))
                video["reply_count"]    = stat.get("reply",    video.get("reply_count",0))

                # 获取在线人数
                try:
                    viewers = bilibili_api.get_video_viewers(
                        bvid, info.get("cid", 0))
                    if viewers:
                        video["viewers_total_raw"] = viewers.get("total", "0")
                        video["viewers_web_raw"]   = viewers.get("count", "0")
                        video["viewers_total"] = _parse_viewer_count(viewers.get("total", "0"))
                        video["viewers_web"]   = _parse_viewer_count(viewers.get("count", "0"))
                        video["viewers_app"]   = max(0,
                            video["viewers_total"] - video["viewers_web"])
                    else:
                        video["viewers_total"] = video.get("viewers_total", 0)
                        video["viewers_web"]   = video.get("viewers_web", 0)
                        video["viewers_app"]   = video.get("viewers_app", 0)
                except Exception as e:
                    print(f"获取在线人数失败 {bvid}: {e}")

                # 记录历史
                if bvid not in gui.history_data:
                    gui.history_data[bvid] = []
                ts = datetime.now()
                gui.history_data[bvid].append((ts, video["view_count"]))

                # 写数据库
                if bvid in gui.video_dbs:
                    try:
                        rec = MonitorRecord(
                            bvid=bvid, timestamp=ts.isoformat(),
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
                        print(f"写数据库失败 {bvid}: {e}")
                        gui.log_panel.add_log("WARNING", f"写数据库失败 {bvid}: {e}")
            time.sleep(0.2)

        gui.root.after(0, gui._post_fetch)

    threading.Thread(target=_worker, daemon=True).start()


def predict_single(gui, bvid, video, callback=None):
    """对单个视频运行预测"""
    from ui.theme import C
    current_view = video.get("view_count", 0)
    history      = merge_history(gui, bvid)

    results = AlgorithmRegistry.predict_all(
        history, current_view,
        thresholds=THRESHOLDS,
        threshold_names=THRESHOLD_NAMES,
    )

    weighted     = results.get("_weighted", {})
    w_pred       = weighted.get("prediction", current_view)
    success_list = []
    fail_list    = []
    for name, r in results.items():
        if name == "_weighted":
            continue
        if "error" in r:
            fail_list.append((name, r["error"]))
        else:
            success_list.append((name, r["prediction"], r["weight"], r["confidence"]))

    growth       = w_pred - current_view
    rate_per_sec = calc_growth_rate(history)

    result = {
        "bvid":         bvid,
        "prediction":   w_pred,
        "current_view": current_view,
        "growth":       max(0, growth),
        "rate_per_sec": rate_per_sec,
        "success_list": success_list,
        "fail_list":    fail_list,
        "valid":        weighted.get("valid_algorithms", 0),
        "total":        weighted.get("total_algorithms", 0),
    }
    gui.prediction_results[bvid] = result

    if callback:
        callback(result)


def merge_history(gui, bvid: str) -> list:
    """合并内存历史与数据库历史"""
    current_view = next(
        (v.get("view_count", 0) for v in gui.monitored_videos
         if v.get("bvid") == bvid), 0)
    history = list(gui.history_data.get(bvid, []))

    try:
        if bvid in gui.video_dbs:
            db_hist = gui.video_dbs[bvid].get_all_records()
            if db_hist:
                existing = {v for _, v in history}
                for row in db_hist:
                    if row["view_count"] not in existing:
                        history.append((row["timestamp"], row["view_count"]))
    except Exception:
        pass

    def _to_dt(t):
        return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))

    history.sort(key=lambda x: _to_dt(x[0]))

    if len(history) < 2:
        now = datetime.now()
        history = [(now, current_view), (now, current_view)]

    return history


def calc_growth_rate(history: list) -> float:
    """根据历史数据计算播放量增长速率（播放量/秒）"""
    try:
        if len(history) < 2:
            return 0.0

        def _to_dt(t):
            return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))

        first_ts, first_v = _to_dt(history[0][0]),  history[0][1]
        last_ts,  last_v  = _to_dt(history[-1][0]), history[-1][1]
        dt_sec = (last_ts - first_ts).total_seconds()
        if dt_sec > 0 and last_v > first_v:
            return (last_v - first_v) / dt_sec
    except Exception:
        pass
    return 0.0


def auto_predict_all(gui):
    """数据拉取完成后自动对所有视频预测"""
    from ui.theme import C
    if not gui.monitored_videos:
        return

    if not gui.selected_bvid and gui.monitored_videos:
        first_bvid = gui.monitored_videos[0].get("bvid", "")
        if first_bvid:
            gui.root.after(0, lambda b=first_bvid: gui._select_video(b))

    def _worker():
        count = len(gui.monitored_videos)
        for i, video in enumerate(gui.monitored_videos):
            bvid = video.get("bvid", "")
            if not bvid:
                continue

            predict_single(gui, bvid, video)
            if bvid == gui.selected_bvid:
                result = gui.prediction_results.get(bvid)
                if result:
                    gui.root.after(0, lambda r=result: gui._prediction_done(
                        r["prediction"], r["current_view"],
                        r["growth"], r["rate_per_sec"],
                        r["success_list"], r["fail_list"],
                        r["valid"], r["total"],
                    ))
            time.sleep(0.05)

        gui.root.after(0, lambda: gui._sb(
            "status", f"自动预测完成 ({count} 个视频)", C["success"]))
        gui.log_panel.add_log("INFO", f"自动预测完成 ({count} 个视频)")

    threading.Thread(target=_worker, daemon=True).start()


def load_watch_list(gui):
    """启动时从 settings.json 加载监控列表"""
    from ui.theme import C
    from config import load_config
    from core import db

    config = load_config()
    watch_list = config.get("watch_list", [])
    if not watch_list:
        return

    gui._sb("status", f"正在加载 {len(watch_list)} 个监控视频…", C["accent"])

    def _worker():
        for bvid in watch_list:
            if any(v.get("bvid") == bvid for v in gui.monitored_videos):
                continue
            try:
                info = bilibili_api.get_video_info(bvid)
                if not info:
                    continue
                video = gui._map_api_to_video_dict(bvid, info)

                try:
                    video_db = db.get_video_db(bvid)
                    gui.video_dbs[bvid] = video_db
                    video_db.save_video_info(video)
                    history = video_db.get_all_records()
                    if history:
                        gui.history_data[bvid] = [
                            (row["timestamp"], row["view_count"])
                            for row in history
                        ]
                except Exception:
                    pass

                gui.root.after(0, lambda v=video: gui._restore_video(v))
                time.sleep(0.15)
            except Exception as e:
                gui.log_panel.add_log("ERROR", f"加载视频 {bvid} 失败: {e}")
                continue

        gui.root.after(0, lambda: gui._sb(
            "status",
            f"已加载 {len(gui.monitored_videos)} 个监控视频",
            C["success"]))

        if gui.monitored_videos:
            gui.root.after(500, lambda: auto_predict_all(gui))

    threading.Thread(target=_worker, daemon=True).start()
