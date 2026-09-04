"""
阈值阶梯自动扩档 — A1

职责：
    1. 视频每次 fetch 后检查是否首次突破任一阈值（记录 + 通知一次）
    2. 当前播放量已超过配置的最高阈值时，按用户预设阶梯因子自动追加一档
    3. 达标记录持久化在 data/threshold_progress.json，重启不重复通知

设计：
    - 与全局 THRESHOLDS/THRESHOLD_NAMES 联动（ui.helpers 加载自 config）
    - 追加档位仅写 config + reload_thresholds()，不触碰算法内部
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

from config import DATA_DIR

_PROGRESS_FILE = os.path.join(DATA_DIR, "threshold_progress.json")
_lock = threading.Lock()

# bvid -> {"reached": [threshold, ...], "auto_appended": [threshold, ...]}
_progress: dict = {}


def _load():
    """加载达标记录（幂等，仅在内存为空时读取一次）"""
    global _progress
    if _progress:
        return
    try:
        if os.path.exists(_PROGRESS_FILE):
            with open(_PROGRESS_FILE, "r", encoding="utf-8") as f:
                _progress = json.load(f)
    except Exception as e:
        logger.debug("加载达标进度失败: %s", e)
    _progress.setdefault("_videos", {})


def _save():
    """持久化达标记录"""
    try:
        os.makedirs(os.path.dirname(_PROGRESS_FILE), exist_ok=True)
        with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(_progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("保存达标进度失败: %s", e)


def _fmt_threshold(t: int) -> str:
    """格式化阈值（万/亿）"""
    if t >= 100_000_000:
        v = t / 100_000_000
        return f"{v:.0f}亿" if v == int(v) else f"{v:.1f}亿"
    if t >= 10_000:
        v = t / 10_000
        return f"{v:.0f}万" if v == int(v) else f"{v:.1f}万"
    return str(t)


def _fmt_count(n) -> str:
    if n >= 100_000_000:
        return f"{n / 100_000_000:.2f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def _load_current_thresholds():
    """读取当前生效的阈值列表（从 helpers 或 config 兜底）"""
    try:
        from ui.helpers import THRESHOLDS, THRESHOLD_NAMES

        if THRESHOLDS:
            return list(THRESHOLDS), list(THRESHOLD_NAMES)
    except Exception as e:
        logger.debug("读取 helpers 阈值失败: %s", e)
    try:
        from config import load_config

        raw = load_config().get("prediction", {}).get("thresholds", [])
        values, names = [], []
        if raw and isinstance(raw[0], (list, tuple)):
            for item in raw:
                values.append(int(item[0]))
                names.append(str(item[1]) if len(item) > 1 else _fmt_threshold(int(item[0])))
        else:
            values = [int(v) for v in raw]
            names = [_fmt_threshold(v) for v in raw]
        if values:
            pairs = sorted(zip(values, names), key=lambda x: x[0])
            return [p[0] for p in pairs], [p[1] for p in pairs]
    except Exception as e:
        logger.debug("读取 config 阈值失败: %s", e)
    return [100000, 1000000, 10000000], ["10万", "100万", "1000万"]


def _log(gui, level: str, msg: str):
    """写日志（gui 可能为 None）"""
    try:
        if gui is not None and getattr(gui, "log_panel", None) is not None:
            gui.log_panel.add_log(level, msg)
    except Exception:
        pass


def _send(title: str, body: str):
    """发送通知（全部渠道: Windows + QQ + Webhook）"""
    try:
        from core.notification import notification_manager

        notification_manager.send_windows_notification(title, body)
        qq_msg = f"{title}\n{body}"
        notification_manager.send_qq_private(qq_msg)
        notification_manager.send_qq_group(qq_msg)
        notification_manager.send_webhook(f"{title}\n{body}")
    except Exception as e:
        logger.debug("通知发送失败: %s", e)


def check_thresholds(gui, bvid: str, video: dict, current_views: int) -> dict:
    """在每次 fetch 后调用：检查阈值突破 + 自动扩档。

    Args:
        gui: 主窗口（用于状态栏/日志/阈值重载）
        bvid: 视频 BV 号
        video: 视频 dict（含 title）
        current_views: 当前播放量

    Returns:
        dict: {"notified": [str,...], "escalated": bool, "new_threshold": int|None}
    """
    result = {"notified": [], "escalated": False, "new_threshold": None}
    if not current_views or current_views <= 0:
        return result

    title = ((video.get("title") if isinstance(video, dict) else None) or "")[:20] or bvid

    with _lock:
        thresholds, names = _load_current_thresholds()
        if not thresholds:
            return result

        state = _load_or_create(bvid)
        reached = set(state["reached"])
        newly = []
        for t, name in sorted(zip(thresholds, names), key=lambda x: x[0]):
            if current_views >= t and t not in reached:
                newly.append((t, name))
                reached.add(t)
        state["reached"] = sorted(reached)

        max_threshold = max(thresholds)
        escalated = False
        new_t = None
        if current_views >= max_threshold:
            auto, factor = _escalate_config()
            auto_appended = set(state.get("auto_appended", []))
            if auto and factor >= 1.5:
                candidate = int(max_threshold * factor)
                if candidate > max_threshold and candidate <= 100_000_000_000 and candidate not in auto_appended:
                    new_t = candidate
                    auto_appended.add(candidate)
                    state["auto_appended"] = sorted(auto_appended)
                    escalated = True

        if newly or escalated:
            _save()

    # 锁外动作：通知 + 扩档落地
    for t, name in newly:
        msg = (
            f"♪ 追到光啦! 《{title}》播放量突破 {_fmt_threshold(t)}！\n"
            f"当前播放量: {_fmt_count(current_views)}   BV号: {bvid}"
        )
        result["notified"].append(msg)
        _send("♪ 播放量突破提醒", msg)
        _log(gui, "INFO", f"[{bvid}] 播放量突破 {_fmt_threshold(t)} 啦!♪")

    if escalated and new_t is not None:
        _apply_escalation(gui, bvid, title, max_threshold, new_t)
        result["escalated"] = True
        result["new_threshold"] = new_t

    return result


def _load_or_create(bvid: str) -> dict:
    """获取单个视频进度状态（调用方需已持锁）"""
    _load()
    vids = _progress.setdefault("_videos", {})
    state = vids.setdefault(bvid, {"reached": [], "auto_appended": []})
    return state


def _escalate_config() -> tuple:
    """读取扩档配置: (auto_enabled, factor)"""
    try:
        from config import load_config

        cfg = load_config().get("prediction", {})
        return bool(cfg.get("auto_escalate", True)), float(cfg.get("escalate_factor", 5.0))
    except Exception as e:
        logger.debug("读取扩档配置失败: %s", e)
        return True, 5.0


def _apply_escalation(gui, bvid: str, title: str, old_max: int, new_t: int):
    """将新档位写入 config 并重载全局阈值"""
    try:
        from config import load_config, save_config
        from ui.helpers import reload_thresholds

        cfg = load_config()
        th = cfg.setdefault("prediction", {}).setdefault("thresholds", [])
        values, names = [], []
        for x in th:
            if isinstance(x, (list, tuple)) and x:
                values.append(int(x[0]))
                names.append(str(x[1]) if len(x) > 1 else _fmt_threshold(int(x[0])))
            elif x:
                values.append(int(x))
                names.append(_fmt_threshold(int(x)))
        if not values:
            values, names = [100000, 1000000, 10000000], ["10万", "100万", "1000万"]
        if new_t not in values:
            values.append(new_t)
            names.append(_fmt_threshold(new_t))
            cfg["prediction"]["thresholds"] = [
                [v, n] for v, n in sorted(zip(values, names), key=lambda x: x[0])
            ]
            save_config(cfg)
            reload_thresholds()
            esc_msg = (
                f"♪ 阶梯已扩展! 《{title}》已达最高档 {_fmt_threshold(old_max)}，\n"
                f"天依自动设定了新目标: {_fmt_threshold(new_t)}！继续追光吧~"
            )
            _send("♪ 监控目标已自动升级", esc_msg)
            _log(
                gui, "INFO",
                f"[{bvid}] 已自动追加监控目标 {_fmt_threshold(new_t)}（原最高 {_fmt_threshold(old_max)}）",
            )
    except Exception as e:
        logger.debug("自动扩档落地失败: %s", e)


def reset_bvid_progress(bvid: str):
    """重置单个视频的达标记录（重新添加监控时调用）"""
    with _lock:
        _load()
        vids = _progress.setdefault("_videos", {})
        if bvid in vids:
            del vids[bvid]
            _save()
