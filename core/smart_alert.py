"""
智能预警模块 (Smart Alert / AnomalyDetector)
==============================================

本模块提供视频数据的异常检测和智能预警功能，自动发现数据中的异常模式。

检测能力（8 大维度）：
  1. 播放增速飙升           — 最近增速远超历史均值（自适应阈值，大视频容错更严）
  2. 增长趋势反转           — 增速从正常逐步降至低于 30%（可能进入衰退期）
  3. 播放停滞               — 长时间几乎零增长（小视频用绝对阈值，大视频用比例阈值）
  4. 在线人数飙升           — 即时在线人数突然远高于历史均值
  5. 在线人数断崖下跌       — 在线人数在短时间内大幅下降
  6. 深夜异常在线           — 凌晨时段在线人数异常高于日间均值
  7. 直播联动检测           — 检测 UP 主是否正在直播（直播期间视频数据波动属正常）
  8. 疑似买量/付费推广      — 7 维综合评分检测（播放量高但互动率异常低）

设计原则：
  - 自适应阈值：根据视频当前播放量级动态调整检测灵敏度
  - 告警冷却：同一类型告警 30 分钟内不重复触发（防止告警风暴）
  - 内存防泄漏：定期清理过期的告警冷却记录

阈值优化说明：
  使用相对百分比替代绝对播放量作为检测阈值，确保不同量级视频
  （从几千播放到几百万播放）都能得到合理的异常判断。
"""
import logging
import threading
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 全局告警冷却时间记录（防止同一类型告警短时间内重复触发）
_last_alert_time: Dict[str, datetime] = {}
_last_alert_lock = threading.Lock()
_ALERT_COOLDOWN_MINUTES = 30  # 告警冷却时间（分钟）
_STALE_ALERT_CUTOFF_MINUTES = _ALERT_COOLDOWN_MINUTES * 2  # 过期记录清理阈值


def _cleanup_stale_alerts():
    """清理过期的告警冷却记录，防止内存泄漏

    遍历 _last_alert_time 字典，删除超过 _STALE_ALERT_CUTOFF_MINUTES 的记录。
    每次 _should_alert 被调用时自动触发清理。
    """
    now = datetime.now()
    cutoff = timedelta(minutes=_STALE_ALERT_CUTOFF_MINUTES)
    with _last_alert_lock:
        stale = [k for k, v in _last_alert_time.items() if now - v > cutoff]
        for k in stale:
            del _last_alert_time[k]


def _fmt_count(n: int) -> str:
    """将大数字格式化为中文万/亿单位，增强可读性

    示例：
      12000    → "1.2万"
      150000   → "15.0万"
      120000000 → "1.20亿"

    Args:
        n: 原始数字

    Returns:
        格式化后的字符串
    """
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)


def _should_alert(alert_key: str) -> bool:
    """判断指定类型的告警是否允许触发（基于冷却时间控制）

    如果该告警键名在冷却时间内（默认 30 分钟），返回 False 阻止触发。
    否则记录当前时间并返回 True 允许触发。

    冷却时间用线程锁保护，保证多线程环境下的数据一致性。

    Args:
        alert_key: 告警的唯一标识键名（推荐格式为 "bvid:类型"）

    Returns:
        True=可以触发告警, False=冷却中
    """
    now = datetime.now()
    _cleanup_stale_alerts()  # 每次检查前先清理过期记录
    with _last_alert_lock:
        last = _last_alert_time.get(alert_key)
        if last and (now - last).total_seconds() < _ALERT_COOLDOWN_MINUTES * 60:
            return False  # 冷却中，不触发
        _last_alert_time[alert_key] = now
    return True


class AnomalyDetector:
    """异常检测器

    所有检测方法均为静态方法，不维护任何实例状态。
    可直接通过 `AnomalyDetector.detect_growth_spike(records)` 调用。
    使用相对阈值适配不同量级的视频。
    """

    @staticmethod
    def detect_growth_spike(records: List[Dict]) -> Optional[str]:
        """检测播放增速异常飙升

        基于最近 4 条记录计算平均增速和最近一段的增速。
        如果最近增速超过平均增速的 multiplier 倍，触发告警。

        自适应阈值策略：
          - >1亿 播放：1.5 倍（大视频增速稳定，微小波动即告警）
          - >100万 播放：2.0 倍
          - >10万  播放：2.5 倍
          - ≤10万  播放：3.0 倍（小视频波动大，阈值放宽）

        Args:
            records: 历史监控记录列表，每条含 view_count 和 timestamp 字段

        Returns:
            告警消息字符串，无异常返回 None
        """
        if len(records) < 4:
            return None  # 数据不足，无法判断
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-4:]  # 取最近 4 条记录

        try:
            now_ts = datetime.fromisoformat(recent[-1]["timestamp"])
            old_ts = datetime.fromisoformat(recent[0]["timestamp"])
        except Exception:
            return None  # 时间戳格式异常

        hours_span = (now_ts - old_ts).total_seconds() / 3600
        if hours_span < 0.5:
            return None  # 时间跨度太短，不具备统计意义

        # 计算整体平均增速
        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        avg_rate = total_growth / hours_span if hours_span > 0 else 0

        # 计算最近一段的增速
        last_growth = recent[-1].get("view_count", 0) - recent[-2].get("view_count", 0)
        try:
            last_hours = (
                datetime.fromisoformat(recent[-1]["timestamp"]) - datetime.fromisoformat(recent[-2]["timestamp"])
            ).total_seconds() / 3600
        except Exception:
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

        # 最低增速要求：大视频门槛更高（至少万分之一）
        min_rate = max(10, current_views * 0.0001)

        if avg_rate > min_rate and last_rate > avg_rate * multiplier:
            return (
                f"⚡ 播放飙升！最近增速 {last_rate:.0f}/h，"
                f"是平均 {avg_rate:.0f}/h 的 {last_rate / avg_rate:.1f}倍 "
                f"(当前 {_fmt_count(current_views)})"
            )
        return None

    @staticmethod
    def detect_trend_reversal(records: List[Dict]) -> Optional[str]:
        """检测增长放缓（基于增速比例，无绝对值门槛）

        比较最近两段增速与之前各段的平均增速：
        如果之前增速 > 1/h 且最近增速降至 30% 以下，触发告警。

        Args:
            records: 历史记录列表

        Returns:
            告警消息，无异常返回 None
        """
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

        # 之前增速需至少 1/h（排除本来就不动的视频），且降至 30% 以下
        if prev_g > 1 and recent_g < prev_g * 0.3:
            views = recent[-1].get("view_count", 0)
            return f"🔻 增长放缓！增速从 {prev_g:.0f}/h 降至 {recent_g:.0f}/h (当前 {_fmt_count(views)})"
        return None

    @staticmethod
    def detect_stall(records: List[Dict]) -> Optional[str]:
        """检测播放停滞（基于视频量级的比例阈值）

        自适应策略：
          - 播放量 < 1万：用绝对阈值（增速 < 5/h 且总增长 < 100）——小视频本就增长慢
          - 播放量 ≥ 1万：用相对阈值（增速 < 当前播放量的十万分之五/小时）

        Args:
            records: 历史记录列表

        Returns:
            告警消息，无异常返回 None
        """
        if len(records) < 4:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-4:]

        try:
            span_h = (
                datetime.fromisoformat(recent[-1]["timestamp"]) - datetime.fromisoformat(recent[0]["timestamp"])
            ).total_seconds() / 3600
        except Exception:
            return None

        if span_h < 2:
            return None  # 时间跨度不足 2 小时，不判定停滞

        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        rate = total_growth / span_h if span_h > 0 else 0
        current_views = recent[-1].get("view_count", 0)

        # 自适应：播放量 < 1万用绝对阈值，>1万用相对阈值
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
        """检测在线人数短时飙升

        取最近 3 条记录，比较最新的在线人数与前两条的均值。
        触发条件：最新在线人数 > 历史均值 × 2.5 且绝对值 > 30。

        Args:
            records: 历史记录列表（含 viewers_total 字段）

        Returns:
            告警消息，无异常返回 None
        """
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
                f"🔥 在线人数飙升！当前 {last_viewers} 人在线，"
                f"是之前的 {last_viewers / max(avg_viewers, 1):.1f}倍"
            )
        return None

    @staticmethod
    def detect_night_surge(records: List[Dict]) -> Optional[str]:
        """检测深夜/凌晨时段（23:00-7:00）的异常在线人数

        夜间在线人数通常远低于白天。如果夜间在线人数达到日间均值的 40% 以上，
        可能为机器人刷量行为。

        算法：
        1. 确认当前时段为深夜（7:00-23:00 之间不检测）
        2. 收集历史记录中日间（9:00-22:00）的在线人数
        3. 如果夜间在线 > 日间均值 × 0.4 且日间均值 > 10，触发告警

        Args:
            records: 历史记录列表

        Returns:
            告警消息，无异常返回 None
        """
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
        """检测在线人数断崖下跌

        比较最近 3 条记录中的在线人数变化。
        触发条件：当前人数降至初始的 30% 以下且绝对下降超过 50 人。

        Args:
            records: 历史记录列表

        Returns:
            告警消息，无异常返回 None
        """
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
        """检测 UP 主是否正在直播

        直播期间视频数据波动属于正常现象（UP 主正在引流）。
        如果检测到 UP 主正在直播，返回通知消息而非异常告警。
        监控系统可据此暂停其他类型的异常检测。

        Args:
            _video: 视频信息字典（暂时未使用，预留参数）
            up_info: UP 主信息字典（含 live_room 字段）

        Returns:
            直播通知消息，未在直播返回 None
        """
        if up_info:
            lr = up_info.get("live_room")
            if lr and lr.get("live_status", 0) == 1:  # live_status=1 表示正在直播
                title = lr.get("live_title", "未命名直播")
                roomid = lr.get("roomid", 0)
                return f"🔴 UP主正在直播！「{title[:30]}」 (房间 {roomid})，视频数据可能受推流影响"
        return None

    @staticmethod
    def detect_paid_promotion(records: List[Dict], video: Dict = None) -> Optional[str]:
        """综合检测疑似买必火/付费推广（7 维评分系统）

        评分维度：
          S1. 点赞率低（<2% → +1分，<1% → +2分）
          S2. 投币率低（<1% → +1分，<0.3% → +2分）
          S3. 弹幕率低（<0.1% → +1分）
          S4. 收藏率低（<2% → +1分）
          S5. 分享率低（<0.1% → +1分）
          S6. 播放突增无互动（增速快但 S1-S5 都低 → +2分）
          S7. 夜间异常播放时段（凌晨时段播放量异常增长 → +1分）

        总分判定：
          >= 3 分 → 疑似买量
          >= 5 分 → 高度疑似买量

        核心逻辑：刷量行为通常只买播放量，互动指标（点赞/投币/收藏/弹幕）
        远低于正常水平，且播放增长曲线异常。

        Args:
            records: 历史监控记录列表
            video: 视频信息字典（含 view_count, like_count, coin_count 等）

        Returns:
            多行告警消息（含评分和各项比率），无异常返回 None
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

        # 计算各项互动指标的比率（基于当前总播放量）
        like_rate = likes / views
        coin_rate = coins / views
        fav_rate = favorites / views
        share_rate = shares / views
        danmaku_rate = danmaku / views

        score = 0
        reasons = []

        # S1: 点赞率检测
        if like_rate < 0.01:
            score += 2
            reasons.append("点赞率极低")
        elif like_rate < 0.02:
            score += 1
            reasons.append("点赞率偏低")

        # S2: 投币率检测
        if coin_rate < 0.003:
            score += 2
            reasons.append("投币率极低")
        elif coin_rate < 0.01:
            score += 1
            reasons.append("投币率偏低")

        # S3: 弹幕率检测
        if danmaku_rate < 0.001:
            score += 1
            reasons.append("弹幕率极低")

        # S4: 收藏率检测
        if fav_rate < 0.02:
            score += 1
            reasons.append("收藏率偏低")

        # S5: 分享率检测
        if share_rate < 0.001:
            score += 1
            reasons.append("分享率极低")

        # S6: 近期播放突增且互动低（使用增量而非累积值）
        if len(records) >= 7:
            sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
            growths = []
            for i in range(1, len(sorted_recs)):
                growths.append(sorted_recs[i].get("view_count", 0) - sorted_recs[i-1].get("view_count", 0))
            recent_growth = sum(growths[-3:]) / 3 if len(growths) >= 3 else 0
            older_growth = sum(growths[-6:-3]) / 3 if len(growths) >= 6 else 0
            if older_growth > 0 and recent_growth > older_growth * 1.5:
                if score >= 2:  # 播放突增 + 已有互动率低
                    score += 2
                    reasons.append("播放突增但互动低迷")

        # S7: 夜间时段异常播放（23:00-7:00）
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
            f"  点赞率{like_rate*100:.1f}% 投币率{coin_rate*100:.1f}%"
            f" 收藏率{fav_rate*100:.1f}% 弹幕率{danmaku_rate*100:.2f}%\n"
            f"  异常项: {detail}"
        )

    @staticmethod
    def detect_all(records: List[Dict], bvid: str = "", video: Dict = None, up_info: Dict = None) -> List[str]:
        """运行所有检测器，返回所有触发的告警消息列表

        每个检测器都通过 _should_alert 检查冷却时间，防止同一视频的
        同一类型告警在 30 分钟内重复触发。

        Args:
            records: 历史监控记录列表
            bvid: 视频 BV 号（用于构建告警键名）
            video: 当前视频信息字典
            up_info: UP 主信息字典

        Returns:
            告警消息字符串列表（按检测顺序排列）
        """
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
