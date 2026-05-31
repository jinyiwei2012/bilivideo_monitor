"""
数据操作：监控列表持久化、视频注册、数据同步
"""

from tkinter import messagebox
import logging
from datetime import datetime
from dataclasses import asdict

logger = logging.getLogger(__name__)


def map_api_to_video_dict(bvid: str, info: dict, fallback: dict = None) -> dict:
    """将 B站 API 返回的数据映射为统一的视频字典格式"""
    fb = fallback or {}
    stat = info.get("stat", {})
    owner = info.get("owner", {})
    return {
        "bvid": bvid,
        "title": info.get("title", fb.get("title", "未知标题")),
        "author": owner.get("name", fb.get("author", "未知UP主")),
        "pic": info.get("pic", fb.get("pic", "")),
        "view_count": stat.get("view", fb.get("play", 0)),
        "like_count": stat.get("like", fb.get("like", 0)),
        "coin_count": stat.get("coin", 0),
        "share_count": stat.get("share", 0),
        "favorite_count": stat.get("favorite", 0),
        "danmaku_count": stat.get("danmaku", 0),
        "reply_count": stat.get("reply", 0),
        "duration": info.get("duration", 0),
        "pubdate": info.get("pubdate", 0),
        "desc": info.get("desc", ""),
        "aid": info.get("aid", 0),
        "viewers_total": 0,
        "viewers_web": 0,
        "viewers_app": 0,
    }


def _calc_ws(video):
    """延迟导入 weekly_score"""
    from utils.weekly_score import calculate_from_dict

    return calculate_from_dict(video)


def _calc_ys(video):
    """延迟导入 yearly_score"""
    from utils.yearly_score import calculate_yearly_from_dict

    return calculate_yearly_from_dict(video)


def refresh_data(gui):
    """手动刷新数据"""
    gui._do_fetch()


def load_watch_list(gui):
    """加载监控列表"""
    from ui.monitor_service import load_watch_list as _load

    _load(gui)


def save_watch_list(gui):
    """保存监控列表到配置"""
    from config import load_config, save_config

    config = load_config()
    config["watch_list"] = [v.get("bvid", "") for v in gui.monitored_videos]
    save_config(config)


def save_weekly_score(gui, bvid, video, timestamp):
    """保存周刊分数到数据库"""
    try:
        ws = _calc_ws(video)
        if ws and bvid in gui.video_dbs:
            score_data = asdict(ws)
            gui.video_dbs[bvid].add_weekly_score(timestamp, score_data)
    except Exception as e:
        logger.warning("保存周刊分数失败 %s: %s", bvid, e)


def save_yearly_score(gui, bvid, video, timestamp):
    """保存年刊分数到数据库"""
    try:
        ys = _calc_ys(video)
        if ys and bvid in gui.video_dbs:
            score_data = asdict(ys)
            gui.video_dbs[bvid].add_yearly_score(timestamp, score_data)
    except Exception as e:
        logger.warning("保存年刊分数失败 %s: %s", bvid, e)


def restore_video(gui, video):
    """从 watch_list 恢复视频到界面"""
    from core import db, MonitorRecord
    from ui.monitor_service import _start_worker

    bvid = video.get("bvid", "")
    if bvid in gui._video_index:
        return
    gui.monitored_videos.append(video)
    gui._video_index[bvid] = video
    gui.video_list.make_card(video)
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    gui._register_video_timer(bvid)


def register_video_to_monitor(gui, video):
    """注册视频到监控系统：初始化数据库 + 创建卡片 + 启动 Worker"""
    from core import db, MonitorRecord
    from ui.monitor_service import _start_worker

    bvid = video["bvid"]
    try:
        video_db = db.get_video_db(bvid)
        gui.video_dbs[bvid] = video_db
        video_db.save_video_info(video)
        history = video_db.get_all_records()
        if history:
            gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
        else:
            now = datetime.now()
            gui.history_data[bvid] = [(now, video["view_count"])]
            rec = MonitorRecord(
                bvid=bvid,
                timestamp=now.isoformat(),
                view_count=video["view_count"],
                like_count=video["like_count"],
                coin_count=video["coin_count"],
                share_count=video["share_count"],
                favorite_count=video["favorite_count"],
                danmaku_count=video["danmaku_count"],
                reply_count=video["reply_count"],
            )
            video_db.add_monitor_record(rec)
            save_weekly_score(gui, bvid, video, now.isoformat())
            save_yearly_score(gui, bvid, video, now.isoformat())
    except Exception as e:
        gui.log_panel.add_log("WARNING", f"数据库初始化失败: {bvid}: {e}")
    gui.monitored_videos.append(video)
    gui._video_index[bvid] = video
    gui.video_list.make_card(video)
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    gui._register_video_timer(bvid)
    interval = gui._get_video_interval(video)
    _start_worker(gui, bvid, video, interval, gui.FAST_INTERVAL)


def prompt_backup_sync(gui, diffs, db):
    """数据目录差异弹窗，让用户选择保留哪边的数据"""
    msg = [f"检测到 {len(diffs)} 个视频在 core/data/ 与 data/ 中存在数据差异：", ""]
    for d in diffs[:10]:
        dir_label = "主库更多" if d["primary_records"] > d["backup_records"] else "备份更多"
        msg.append(f"  {d['bvid']}: core/data/={d['primary_records']}条  data/={d['backup_records']}条 ({dir_label})")
    if len(diffs) > 10:
        msg.append(f"  ... 等 {len(diffs)} 个")
    msg.append("")
    msg.append("是否将 core/data/ 的数据同步到 data/？")
    choice = messagebox.askyesno(
        "数据库差异检测",
        "\n".join(msg),
        icon="warning",
        parent=gui.root,
    )
    if choice:
        db.sync_per_video_dbs_to_backup()
        gui.log_panel.add_log("INFO", f"已同步 {len(diffs)} 个视频独立库到 data/")
    else:
        gui.log_panel.add_log("INFO", "用户跳过数据同步")
