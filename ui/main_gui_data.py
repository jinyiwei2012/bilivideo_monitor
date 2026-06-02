"""
数据操作模块

负责监控列表持久化、视频注册、数据同步等核心数据操作。
所有函数以 gui 实例作为第一个参数，方便在多个调用上下文中使用。

主要功能:
  - map_api_to_video_dict  : 将 B站 API 响应或 VideoInfo 对象映射为统一视频字典
  - load_watch_list        : 启动时从配置文件加载监控列表
  - save_watch_list        : 保存当前监控列表到配置文件
  - register_video_to_monitor : 注册新视频到监控系统（DB + 卡片 + Worker）
  - restore_video          : 从 watch_list 恢复视频到界面
  - save_weekly_score      : 计算并保存周刊分数
  - save_yearly_score      : 计算并保存年刊分数
  - prompt_backup_sync     : 数据目录差异弹窗
"""

from tkinter import messagebox
import logging
from datetime import datetime
from dataclasses import asdict

logger = logging.getLogger(__name__)


def _engine_running() -> bool:
    """检查后端引擎是否已在运行（有活跃的 Worker）

    Returns:
        bool: 后端引擎是否有视频在处理
    """
    try:
        from backend import get_engine
        return get_engine().video_count > 0
    except Exception:
        return False


def map_api_to_video_dict(bvid: str, info: dict = None, video_info=None) -> dict:
    """将 B站 API 数据或 VideoInfo 对象映射为统一的视频字典格式

    优先使用 video_info 对象（数据库读取），回退到 API 返回的 info 字典。
    映射包含播放量、点赞、投币、收藏、分享、弹幕、评论等完整字段。

    Args:
        bvid:     视频 BV 号
        info:     B站 API 返回的视频信息字典
        video_info: 数据库中的 VideoInfo 对象（优先使用）

    Returns:
        dict: 标准化的视频数据字典，包含所有统计字段
    """
    if video_info is not None:
        # 从 VideoInfo 对象映射
        return {
            "bvid": video_info.bvid or bvid,
            "title": video_info.title or "未知标题",
            "author": video_info.owner_name or "未知UP主",
            "pic": video_info.pic or "",
            "view_count": video_info.view_count or 0,
            "like_count": video_info.like_count or 0,
            "coin_count": video_info.coin_count or 0,
            "share_count": video_info.share_count or 0,
            "favorite_count": video_info.favorite_count or 0,
            "danmaku_count": video_info.danmaku_count or 0,
            "reply_count": video_info.reply_count or 0,
            "duration": video_info.duration or 0,
            "pubdate": video_info.pubdate or 0,
            "desc": "",
            "aid": 0,
            "viewers_total": video_info.viewers_total or 0,
            "viewers_web": video_info.viewers_web or 0,
            "viewers_app": video_info.viewers_app or 0,
            "owner_name": video_info.owner_name or "",
            "owner_id": video_info.owner_id or 0,
        }

    # 从 API 返回字典映射
    fb = {}  # fallback 空字典
    stat = info.get("stat", {}) if info else {}
    owner = info.get("owner", {}) if info else {}
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
    """延迟导入 weekly_score 的 calculate_from_dict（避免循环依赖）

    Args:
        video: 视频数据字典

    Returns:
        WeeklyScore 或 None
    """
    from utils.weekly_score import calculate_from_dict

    return calculate_from_dict(video)


def _calc_ys(video):
    """延迟导入 yearly_score 的 calculate_yearly_from_dict（避免循环依赖）

    Args:
        video: 视频数据字典

    Returns:
        YearlyScore 或 None
    """
    from utils.yearly_score import calculate_yearly_from_dict

    return calculate_yearly_from_dict(video)


def refresh_data(gui):
    """手动刷新数据（触发拉取）

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    gui._do_fetch()


def load_watch_list(gui):
    """加载监控列表（从配置文件和数据库）

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    from ui.monitor_service import load_watch_list as _load

    _load(gui)


def save_watch_list(gui):
    """保存监控列表到配置文件

    将当前 monitored_videos 中所有视频的 bvid 写入 config["watch_list"]。

    Args:
        gui: BilibiliMonitorGUI 实例
    """
    from config import load_config, save_config

    config = load_config()
    config["watch_list"] = [v.get("bvid", "") for v in gui.monitored_videos]
    save_config(config)


def save_weekly_score(gui, bvid, video, timestamp):
    """保存周刊分数到数据库

    计算当前视频的周刊分数，写入 video_db 的 weekly_scores 表。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        video: 视频数据字典
        timestamp: 记录时间戳（ISO 格式）
    """
    try:
        ws = _calc_ws(video)
        if ws:
            from core import db
            video_db = db.get_video_db(bvid)
            video_db.add_weekly_score(timestamp, asdict(ws))
    except Exception as e:
        logger.warning("保存周刊分数失败 %s: %s", bvid, e)


def save_yearly_score(gui, bvid, video, timestamp):
    """保存年刊分数到数据库

    计算当前视频的年刊分数，写入 video_db 的 yearly_scores 表。

    Args:
        gui: BilibiliMonitorGUI 实例
        bvid: 视频 BV 号
        video: 视频数据字典
        timestamp: 记录时间戳（ISO 格式）
    """
    try:
        ys = _calc_ys(video)
        if ys:
            from core import db
            video_db = db.get_video_db(bvid)
            video_db.add_yearly_score(timestamp, asdict(ys))
    except Exception as e:
        logger.warning("保存年刊分数失败 %s: %s", bvid, e)


def restore_video(gui, video):
    """从 watch_list 恢复视频到界面（不初始化数据库，仅创建卡片 + 启动 Worker）

    Args:
        gui: BilibiliMonitorGUI 实例
        video: 视频数据字典
    """
    from core import db, MonitorRecord
    from ui.monitor_service import _start_worker

    bvid = video.get("bvid", "")
    # 防重复：已存在则跳过
    if bvid in gui._video_index:
        return
    gui.monitored_videos.append(video)
    gui._video_index[bvid] = video
    gui.video_list.make_card(video)
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    gui._register_video_timer(bvid)


def register_video_to_monitor(gui, video):
    """注册视频到监控系统：初始化数据库 + 创建卡片 + 启动 Worker

    完整流程:
      1. 为视频创建独立 SQLite 数据库（video_db）
      2. 写入视频基本信息
      3. 加载历史记录到 memory
      4. 如果是新视频，写入首条 MonitorRecord
      5. 计算并写入周刊/年刊分数
      6. 追加到 monitored_videos 列表
      7. 更新 UI 卡片和视频计数
      8. 启动独立 Worker 线程

    Args:
        gui: BilibiliMonitorGUI 实例
        video: 视频数据字典
    """
    from core import db, MonitorRecord
    from ui.monitor_service import _start_worker

    bvid = video["bvid"]
    try:
        # 初始化独立视频数据库
        video_db = db.get_video_db(bvid)
        gui.video_dbs[bvid] = video_db
        video_db.save_video_info(video)
        # 加载历史记录
        history = video_db.get_all_records()
        if history:
            gui.history_data[bvid] = [(row["timestamp"], row["view_count"]) for row in history]
        else:
            # 无历史记录：用当前数据创建首条记录
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

    # 更新 UI 状态
    gui.monitored_videos.append(video)
    gui._video_index[bvid] = video
    gui.video_list.make_card(video)
    gui.video_list.update_video_count()
    gui._sb("videos", f"监控: {len(gui.monitored_videos)} 个")
    gui._register_video_timer(bvid)

    # 只有后端引擎未运行时才启动 GUI Worker（否则复用引擎数据）
    if not _engine_running():
        interval = gui._get_video_interval(video)
        _start_worker(gui, bvid, video, interval, gui.FAST_INTERVAL)


def prompt_backup_sync(gui, diffs, db):
    """数据目录差异弹窗，让用户选择保留哪边的数据（必须在主线程调用）

    比较 core/data/ 和 data/ 两个目录中的数据差异，
    显示差异详情，让用户决定是否将 core/data/ 同步到 data/。

    Args:
        gui: BilibiliMonitorGUI 实例
        diffs: 差异数据列表 [{bvid, primary_records, backup_records}, ...]
        db: 数据库对象
    """
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
