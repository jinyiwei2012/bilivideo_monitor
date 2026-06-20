"""
智能预警模块 — 异常增长检测、趋势反转、在线人数异常
阈值优化：使用相对百分比替代绝对值，适配不同量级视频
"""

import logging
import threading
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_last_alert_time: Dict[str, datetime] = {}
_last_alert_lock = threading.Lock()
_ALERT_COOLDOWN_MINUTES = 30  # 告警冷却时间（分钟），同一类型告警在此时间内不重复触发
_STALE_ALERT_CUTOFF_MINUTES = _ALERT_COOLDOWN_MINUTES * 2  # 清理超过此时间的过期记录


def _cleanup_stale_alerts():
    """清理过期的告警冷却记录，防止内存泄漏"""
    now = datetime.now()
    cutoff = timedelta(minutes=_STALE_ALERT_CUTOFF_MINUTES)
    with _last_alert_lock:
        stale = [k for k, v in _last_alert_time.items() if now - v > cutoff]
        for k in stale:
            del _last_alert_time[k]


def _fmt_count(n: int) -> str:
    """将大数字格式化为中文万/亿单位，增强可读性"""
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)


def _should_alert(alert_key: str) -> bool:
    """判断指定类型的告警是否允许触发（基于冷却时间控制）"""
    now = datetime.now()
    _cleanup_stale_alerts()
    with _last_alert_lock:
        last = _last_alert_time.get(alert_key)
        if last and (now - last).total_seconds() < _ALERT_COOLDOWN_MINUTES * 60:
            return False  # 冷却中，不触发
        _last_alert_time[alert_key] = now
    return True


class AnomalyDetector:
    """异常检测器，使用相对阈值适配不同量级视频"""

    @staticmethod
    def detect_growth_spike(records: List[Dict]) -> Optional[str]:
        """
        检测播放增速异常飙升
        大视频(>100万)用1.5倍阈值，小视频用3倍阈值
        """
        if len(records) < 4:
            return None  # 数据不足，无法判断
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-4:]  # 取最近 4 条记录

        try:
            now_ts = datetime.fromisoformat(recent[-1]["timestamp"])
            old_ts = datetime.fromisoformat(recent[0]["timestamp"])
        except Exception as e:
            logger.debug("时间戳解析异常: %s", e)
            return None  # 时间戳格式异常

        hours_span = (now_ts - old_ts).total_seconds() / 3600
        if hours_span < 0.5:
            return None  # 时间跨度太短，不具备统计意义

        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        avg_rate = total_growth / hours_span if hours_span > 0 else 0

        last_growth = recent[-1].get("view_count", 0) - recent[-2].get("view_count", 0)
        try:
            last_hours = (
                datetime.fromisoformat(recent[-1]["timestamp"]) - datetime.fromisoformat(recent[-2]["timestamp"])
            ).total_seconds() / 3600
        except Exception as e:
            logger.debug("最近间隔时间解析失败: %s", e)
            last_hours = 0
        last_rate = last_growth / last_hours if last_hours > 0 else 0

        current_views = recent[-1].get("view_count", 0)

        # 自适应阈值：大视频增速更稳定，用更小的倍数
        if current_views > 1_0000_0000:
            multiplier = 1.5
        elif current_views > 100_0000:
            multiplier = 2.0
        elif current_views > 10_0000:
            multiplier = 2.5
        else:
            multiplier = 3.0

        # 最低增速要求：大视频门槛更高
        min_rate = max(10, current_views * 0.0001)  # 至少万分之一

        if avg_rate > min_rate and last_rate > avg_rate * multiplier:
            return (
                f"⚡ 播放飙升！最近增速 {last_rate:.0f}/h，"
                f"是平均 {avg_rate:.0f}/h 的 {last_rate / avg_rate:.1f}倍 "
                f"(当前 {_fmt_count(current_views)})"
            )
        return None

    @staticmethod
    def detect_trend_reversal(records: List[Dict]) -> Optional[str]:
        """检测增长放缓（基于比例，无绝对值门槛）"""
        if len(records) < 6:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-6:]

        # 逐段计算每小时的播放增速
        growths = []
        for i in range(1, len(recent)):
            try:
                h = (
                    datetime.fromisoformat(recent[i]["timestamp"]) - datetime.fromisoformat(recent[i - 1]["timestamp"])
                ).total_seconds() / 3600
                if h > 0:
                    g = (recent[i].get("view_count", 0) - recent[i - 1].get("view_count", 0)) / h
                    growths.append(g)
            except Exception as e:
                logger.debug("计算历史增速失败: %s", e)

        if len(growths) < 4:
            return None

        # 近期平均增速（最近两段） vs 历史平均增速（之前各段）
        recent_g = sum(growths[-2:]) / 2
        prev_g = sum(growths[:-2]) / max(len(growths) - 2, 1)

        # 之前增速需至少 1/h（排除静止视频），且降至 30% 以下
        if prev_g > 1 and recent_g < prev_g * 0.3:
            views = recent[-1].get("view_count", 0)
            return f"🔻 增长放缓！增速从 {prev_g:.0f}/h 降至 {recent_g:.0f}/h (当前 {_fmt_count(views)})"
        return None

    @staticmethod
    def detect_stall(records: List[Dict]) -> Optional[str]:
        """检测播放停滞（基于视频量级的比例阈值）"""
        if len(records) < 4:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-4:]

        try:
            span_h = (
                datetime.fromisoformat(recent[-1]["timestamp"]) - datetime.fromisoformat(recent[0]["timestamp"])
            ).total_seconds() / 3600
        except Exception as e:
            logger.debug("停滞检测时间解析失败: %s", e)
            return None

        if span_h < 2:
            return None  # 时间跨度不足 2 小时，不判定停滞

        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        rate = total_growth / span_h if span_h > 0 else 0
        current_views = recent[-1].get("view_count", 0)

        # 自适应：播放量 < 1万 用绝对阈值，>1万 用相对阈值
        if current_views < 1_0000:
            if rate < 5 and total_growth < 100:
                return f"💤 播放停滞！近 {span_h:.1f}h 仅增长 {_fmt_count(total_growth)} (当前 {_fmt_count(current_views)})"
        else:
            min_expected = current_views * 0.00005  # 期望至少十万分之五/小时
            if rate < min_expected:
                return (
                    f"💤 播放近乎停滞！近 {span_h:.1f}h 增速 {rate:.1f}/h"
                    f" (预期 >{min_expected:.1f}/h，当前 {_fmt_count(current_views)})"
                )
        return None

    @staticmethod
    def detect_viewer_surge(records: List[Dict]) -> Optional[str]:
        """检测在线人数短时飙升（降低触发门槛）"""
        if len(records) < 3:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-3:]

        viewers = [r.get("viewers_total", 0) for r in recent]
        if max(viewers) < 30:
            return None  # 最大值不足 30 人，不触发告警

        avg_viewers = sum(viewers[:-1]) / max(len(viewers) - 1, 1)
        last_viewers = viewers[-1]

        # 当前在线人数超过历史均值 2.5 倍且绝对值 > 30
        if avg_viewers > 0 and last_viewers > avg_viewers * 2.5 and last_viewers > 30:
            return (
                f"🔥 在线人数飙升！当前 {last_viewers} 人在线，" f"是之前的 {last_viewers / max(avg_viewers, 1):.1f}倍"
            )
        return None

    @staticmethod
    def detect_night_surge(records: List[Dict]) -> Optional[str]:
        """检测深夜/凌晨时段异常在线人数（降低触发门槛）"""
        if len(records) < 4:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        now = datetime.now()
        hour = now.hour
        if 7 <= hour < 23:
            return None  # 白天时段不做深夜检测

        viewers = [r.get("viewers_total", 0) for r in sorted_recs[-4:]]
        current_v = viewers[-1] if viewers else 0
        if current_v < 10:
            return None  # 夜间在线人数过少，忽略

        # 收集日间（9:00-22:00）的在线人数做基准
        day_viewers = []
        for r in sorted_recs:
            try:
                ts = r.get("timestamp", "")
                h = datetime.fromisoformat(ts).hour if isinstance(ts, str) else now.hour
                if 9 <= h <= 22:
                    day_viewers.append(r.get("viewers_total", 0))
            except Exception as e:
                logger.debug("解析日间时段失败: %s", e)
        if len(day_viewers) < 3:
            return None  # 日间数据不足，无法比较

        avg_day = sum(day_viewers) / max(len(day_viewers), 1)

        # 夜间在线达到日间均值的 40% 以上，视为异常
        if avg_day > 10 and current_v > avg_day * 0.4:
            return (
                f"🌙 深夜异常在线！当前 {current_v} 人在线"
                f"（时段:{hour}:00，日间均{avg_day:.0f}人），"
                f"可能为机器人刷量"
            )
        return None

    @staticmethod
    def detect_viewer_crash(records: List[Dict]) -> Optional[str]:
        """检测在线人数断崖下跌（降低门槛）"""
        if len(records) < 3:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-3:]

        viewers = [r.get("viewers_total", 0) for r in recent]
        if max(viewers) < 50:
            return None  # 在线峰值不足 50 人，不判定为断崖

        prev_viewers = viewers[0]
        last_viewers = viewers[-1]

        # 当前人数降至初始的 30% 以下且绝对下降超过 50 人
        if prev_viewers > 0 and last_viewers < prev_viewers * 0.3 and (prev_viewers - last_viewers) > 50:
            return (
                f"📉 在线人数骤降！从 {prev_viewers} 人降至 {last_viewers} 人，"
                f"降幅 {(1 - last_viewers / prev_viewers) * 100:.0f}%"
            )
        return None

    @staticmethod
    def detect_live_streaming(_video: Dict = None, up_info: Dict = None) -> Optional[str]:
        """检测 UP 主是否正在直播（直播期间视频数据异常属于正常现象）"""
        if up_info:
            lr = up_info.get("live_room")
            if lr and lr.get("live_status", 0) == 1:  # live_status=1 表示正在直播
                title = lr.get("live_title", "未命名直播")
                roomid = lr.get("roomid", 0)
                return f"🔴 UP主正在直播！「{title[:30]}」 (房间 {roomid})，视频数据可能受推流影响"
        return None

    @staticmethod
    def detect_paid_promotion(records: List[Dict], video: Dict = None) -> Optional[str]:
        """
        综合检测疑似买必火/付费推广（7 维评分 + 播放量分级）

        评分维度：
        S1. 点赞率低（<2% → +1分，<1% → +2分）
        S2. 投币率低（<1% → +1分，<0.3% → +2分）
        S3. 弹幕率低（<0.1% → +1分）
        S4. 收藏率低（<2% → +1分）
        S5. 分享率低（<0.1% → +1分）
        S6. 夜间播放突增（近2h增量 > 历史均值3x → +2分）
        S7. 播放突增无互动（增速快但 S1-S5 都低 → +1分）

        总分 >= 3 → 疑似买量；>= 5 → 高度疑似买量
        """
        if not video:
            return None
        views = max(video.get("view_count", 0), 1)
        if views < 3000:
            return None  # 播放量太低，数据不足以判断

        likes = video.get("like_count", 0) or 0
        coins = video.get("coin_count", 0) or 0
        favorites = video.get("favorite_count", 0) or 0
        shares = video.get("share_count", 0) or 0
        danmaku = video.get("danmaku_count", 0) or 0

        # 计算各项互动指标的比率
        like_rate = likes / views
        coin_rate = coins / views
        fav_rate = favorites / views
        share_rate = shares / views
        danmaku_rate = danmaku / views

        score = 0
        reasons = []

        # S1: 点赞率
        if like_rate < 0.01:
            score += 2
            reasons.append("点赞率极低")
        elif like_rate < 0.02:
            score += 1
            reasons.append("点赞率偏低")

        # S2: 投币率
        if coin_rate < 0.003:
            score += 2
            reasons.append("投币率极低")
        elif coin_rate < 0.01:
            score += 1
            reasons.append("投币率偏低")

        # S3: 弹幕率
        if danmaku_rate < 0.001:
            score += 1
            reasons.append("弹幕率极低")

        # S4: 收藏率
        if fav_rate < 0.02:
            score += 1
            reasons.append("收藏率偏低")

        # S5: 分享率
        if share_rate < 0.001:
            score += 1
            reasons.append("分享率极低")

        # S6: 近期播放突增且互动低（使用增量而非累积值）
        if len(records) >= 7:
            sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
            growths = []
            for i in range(1, len(sorted_recs)):
                growths.append(sorted_recs[i].get("view_count", 0) - sorted_recs[i - 1].get("view_count", 0))
            recent_growth = sum(growths[-3:]) / 3 if len(growths) >= 3 else 0
            older_growth = sum(growths[-6:-3]) / 3 if len(growths) >= 6 else 0
            if older_growth > 0 and recent_growth > older_growth * 1.5:
                if score >= 2:  # 播放突增 + 已有互动率低
                    score += 2
                    reasons.append("播放突增但互动低迷")

        # S7: 夜间时段异常播放
        hour = datetime.now().hour
        if hour < 7 or hour >= 23:
            if len(records) >= 4:
                sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
                recent = sorted_recs[-4:]
                total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
                try:
                    span_h = (
                        datetime.fromisoformat(recent[-1]["timestamp"]) - datetime.fromisoformat(recent[0]["timestamp"])
                    ).total_seconds() / 3600
                    night_rate = total_growth / span_h if span_h > 0 else 0
                    if night_rate > views * 0.001:
                        score += 1
                        reasons.append("夜间播放异常增长")
                except Exception as e:
                    logger.debug("计算夜间增长率失败: %s", e)

        if score < 3:
            return None

        level = "🚨 高度疑似买量" if score >= 5 else "📢 疑似买量"
        detail = "、".join(reasons[:4])
        if len(reasons) > 4:
            detail += f"等{len(reasons)}项"
        return (
            f"{level}！综合评分 {score}/9\n"
            f"  点赞率{like_rate * 100:.1f}% 投币率{coin_rate * 100:.1f}%"
            f" 收藏率{fav_rate * 100:.1f}% 弹幕率{danmaku_rate * 100:.2f}%\n"
            f"  异常项: {detail}"
        )

    @staticmethod
    def detect_all(records: List[Dict], bvid: str = "", video: Dict = None, up_info: Dict = None) -> List[str]:
        """运行所有检测器，返回所有触发的告警消息列表"""
        alerts = []
        # 注册所有检测器及其唯一标识键名
        detectors = [
            ("growth_spike", lambda: AnomalyDetector.detect_growth_spike(records)),
            ("trend_reversal", lambda: AnomalyDetector.detect_trend_reversal(records)),
            ("stall", lambda: AnomalyDetector.detect_stall(records)),
            ("viewer_surge", lambda: AnomalyDetector.detect_viewer_surge(records)),
            ("viewer_crash", lambda: AnomalyDetector.detect_viewer_crash(records)),
            ("night_surge", lambda: AnomalyDetector.detect_night_surge(records)),
            ("paid_promo", lambda: AnomalyDetector.detect_paid_promotion(records, video=video)),
            ("live_stream", lambda: AnomalyDetector.detect_live_streaming(video=video, up_info=up_info)),
        ]
        for key, detector in detectors:
            alert_key = f"{bvid}:{key}" if bvid else key
            if _should_alert(alert_key):  # 未在冷却期，可以触发
                try:
                    msg = detector()
                    if msg:
                        alerts.append(msg)
                except Exception as e:
                    logger.debug(f"检测 {key} 异常: {e}")
        return alerts
