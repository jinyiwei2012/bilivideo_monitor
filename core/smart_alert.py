"""
智能预警模块 — 异常增长检测、趋势反转、在线人数异常
阈值优化：使用相对百分比替代绝对值，适配不同量级视频

v2 (确定度重构):
    - 每个检测器同时给出告警消息与确定度 confidence ∈ [0, 1]
    - detect_*_scored 返回 AlertHit(message, confidence, level)，detect_* 保持返回 str 兼容旧调用方
    - 修复: 冷却时间在"确实触发"后才记录(P0)；样本窗口适配 5min 扫描节奏(P1)；
          在线人数检测改用稳健基线避免单点抖动(P2)
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_last_alert_time: Dict[str, datetime] = {}
_last_alert_lock = threading.Lock()
_ALERT_COOLDOWN_MINUTES = 30  # 告警冷却时间（分钟），同一类型告警在此时间内不重复触发
_STALE_ALERT_CUTOFF_MINUTES = _ALERT_COOLDOWN_MINUTES * 2  # 清理超过此时间的过期记录


@dataclass
class AlertHit:
    """一条告警命中：消息 + 确定度 + 等级"""

    key: str  # 检测器标识（growth_spike / trend_reversal / ...）
    message: str
    confidence: float  # 0~1，越高越确定
    level: str = field(default="medium")  # high / medium / low

    def __post_init__(self):
        if self.confidence >= 0.75:
            self.level = "high"
        elif self.confidence >= 0.5:
            self.level = "medium"
        else:
            self.level = "low"


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
    """判断指定类型的告警是否允许触发（基于冷却时间控制）。仅在命中后调用。"""
    now = datetime.now()
    _cleanup_stale_alerts()
    with _last_alert_lock:
        last = _last_alert_time.get(alert_key)
        if last and (now - last).total_seconds() < _ALERT_COOLDOWN_MINUTES * 60:
            return False  # 冷却中，不触发
        _last_alert_time[alert_key] = now  # P0: 命中后立即占用冷却槽
    return True


def _record_hit(alert_key: str) -> bool:
    """命中后占用冷却槽；返回 True 表示本次允许推送"""
    return _should_alert(alert_key)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _parse_dt(ts) -> Optional[datetime]:
    """稳健解析时间戳（str / datetime / float）"""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts)
        except Exception:
            return None
    try:
        return datetime.fromisoformat(str(ts)[:19])
    except Exception:
        return None


def _sorted_records(records: List[Dict], max_n: Optional[int] = None) -> List[Dict]:
    """按时间排序记录，过滤无法解析时间戳的行，可选截断到最近 max_n 条"""
    valid = []
    for r in records:
        dt = _parse_dt(r.get("timestamp") or r.get("time"))
        if dt is None:
            continue
        valid.append((dt, r))
    valid.sort(key=lambda x: x[0])
    rows = [r for _, r in valid]
    if max_n and len(rows) > max_n:
        rows = rows[-max_n:]
    return rows


def _recent_window(records: List[Dict], hours: float) -> List[Dict]:
    """取最近 hours 小时内的记录（用于 5min 扫描节奏下的样本聚合）"""
    if not records:
        return []
    last_dt = _parse_dt(records[-1].get("timestamp") or records[-1].get("time"))
    if last_dt is None:
        return records
    cutoff = last_dt - timedelta(hours=hours)
    out = []
    for r in records:
        dt = _parse_dt(r.get("timestamp") or r.get("time"))
        if dt is not None and dt >= cutoff:
            out.append(r)
    return out


def _median(vals: List[float]) -> float:
    """稳健中位数"""
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ══════════════════════════════════════════════
#  检测器：播放增速
# ══════════════════════════════════════════════


class AnomalyDetector:
    """异常检测器，使用相对阈值适配不同量级视频"""

    # ── 播放增速飙升 ──────────────────────────

    @staticmethod
    def detect_growth_spike(records: List[Dict]) -> Optional[str]:
        hit = AnomalyDetector.detect_growth_spike_scored(records)
        return hit.message if hit else None

    @staticmethod
    def detect_growth_spike_scored(records: List[Dict]) -> Optional[AlertHit]:
        """检测播放增速异常飙升（大视频阈值更严，小视频更宽）。

        样本窗口修复(P1)：不再固定取最近 4 条（5min 扫描节奏下 4 条仅覆盖 ~20min），
        改为用全部传入记录（scan 传入最近 20~200 条），对比
        「最近段 vs 此前中位速率」，停滞→爆发这类信号也能被捕获。
        """
        if len(records) < 5:
            return None
        rows = _sorted_records(records)
        if len(rows) < 5:
            return None

        # 计算每段小时速率
        rates = []
        for i in range(1, len(rows)):
            dt0 = _parse_dt(rows[i - 1].get("timestamp") or rows[i - 1].get("time"))
            dt1 = _parse_dt(rows[i].get("timestamp") or rows[i].get("time"))
            if dt0 is None or dt1 is None:
                continue
            hours = (dt1 - dt0).total_seconds() / 3600
            if hours <= 0 or hours > 6:
                continue  # 跳过异常大间隔，避免把跨天增长当作单段速率
            dv = rows[i].get("view_count", 0) - rows[i - 1].get("view_count", 0)
            if dv >= 0:
                rates.append(dv / hours)  # 保留 0 增速段，使停滞→爆发有历史基线
        if len(rates) < 4:
            return None

        # 最近 1 段 vs 前段中位（稳健基线：不被单点噪声干扰）
        last_rate = rates[-1]
        prev_rates = rates[:-1]
        base_rate = max(_median(prev_rates), 1e-9)
        current_views = rows[-1].get("view_count", 0)

        # 自适应倍数：大视频增速更稳定，用更小倍数
        if current_views > 1_0000_0000:
            multiplier = 1.5
        elif current_views > 100_0000:
            multiplier = 2.0
        elif current_views > 10_0000:
            multiplier = 2.5
        else:
            multiplier = 3.0

        # 停滞→爆发特判：基线 ≈ 0 且最近速率超过量级门槛，是极强信号
        min_rate = max(10, current_views * 0.0001)
        # 判定条件分两支：
        #   a) 正常基线（中位 > 0）：last 超基线 mult 倍
        #   b) 停滞基线（中位 == 0，持续低速/零增速后突增）：
        #      要求 last 显著高于量级门槛，且前一正增速段也在爬升（连续两段加速）
        median_base = _median(prev_rates)
        if median_base > 0:
            over = last_rate / (median_base * multiplier)
            triggered = last_rate > median_base * multiplier
            conf = _clamp(0.45 + (over - 1.0) * 0.35)
        else:
            # 停滞后爆发：最近速率超过 min_rate 的数倍才视为"飙升"
            if last_rate > min_rate * 4 and len(prev_rates) >= 2:
                over = last_rate / max(min_rate, 1e-9)
                triggered = True
                conf = _clamp(0.5 + min(over / 10.0, 1.0) * 0.35)
            else:
                triggered = False
                conf = 0.0
        # 大视频出现爆发信号通常噪声更少 → 微增
        if triggered and current_views > 100_0000:
            conf = _clamp(conf + 0.05)
        if triggered:
            base_disp = median_base if median_base > 0 else min_rate
            return AlertHit(
                key="growth_spike",
                message=(
                    f"⚡ 播放飙升！最近增速 {last_rate:.0f}/h，"
                    f"是此前中位 {base_disp:.0f}/h 的 {last_rate / max(base_disp, 1e-9):.1f}倍 "
                    f"(当前 {_fmt_count(current_views)})"
                ),
                confidence=round(conf, 2),
            )
        return None

    # ── 增长放缓 ──────────────────────────────

    @staticmethod
    def detect_trend_reversal(records: List[Dict]) -> Optional[str]:
        hit = AnomalyDetector.detect_trend_reversal_scored(records)
        return hit.message if hit else None

    @staticmethod
    def detect_trend_reversal_scored(records: List[Dict]) -> Optional[AlertHit]:
        """检测增长放缓（基于比例，无绝对值门槛）"""
        if len(records) < 8:
            return None
        rows = _sorted_records(records)
        recent = rows[-8:]

        growths = []
        for i in range(1, len(recent)):
            dt0 = _parse_dt(recent[i - 1].get("timestamp") or recent[i - 1].get("time"))
            dt1 = _parse_dt(recent[i].get("timestamp") or recent[i].get("time"))
            if dt0 is None or dt1 is None:
                continue
            h = (dt1 - dt0).total_seconds() / 3600
            if h > 0:
                g = (recent[i].get("view_count", 0) - recent[i - 1].get("view_count", 0)) / h
                growths.append(g)

        if len(growths) < 5:
            return None

        recent_g = sum(growths[-2:]) / 2
        prev_g = sum(growths[:-2]) / max(len(growths) - 2, 1)

        # 之前增速需至少 1/h（排除静止视频），且降至 30% 以下
        if prev_g > 1 and recent_g < prev_g * 0.3:
            views = recent[-1].get("view_count", 0)
            drop_ratio = 1.0 - recent_g / max(prev_g, 1e-9)
            conf = _clamp(0.4 + drop_ratio * 0.5)  # 降幅越大越确定
            if views > 10_0000:
                conf = _clamp(conf + 0.05)  # 大视频放缓更值得信
            return AlertHit(
                key="trend_reversal",
                message=f"△ 增长放缓呢…增速从 {prev_g:.0f}/h 降到 {recent_g:.0f}/h 了 (当前 {_fmt_count(views)}) ♪",
                confidence=round(conf, 2),
            )
        return None

    # ── 播放停滞 ──────────────────────────────

    @staticmethod
    def detect_stall(records: List[Dict]) -> Optional[str]:
        hit = AnomalyDetector.detect_stall_scored(records)
        return hit.message if hit else None

    @staticmethod
    def detect_stall_scored(records: List[Dict]) -> Optional[AlertHit]:
        """检测播放停滞（基于视频量级的比例阈值）"""
        if len(records) < 6:
            return None
        rows = _sorted_records(records)
        # 取最近 24h 样本（5min 节奏需足够窗口判断"停滞"）
        recent = _recent_window(rows, 24.0)
        if len(recent) < 4:
            return None

        span_h = 0.0
        dt0 = _parse_dt(recent[0].get("timestamp") or recent[0].get("time"))
        dt1 = _parse_dt(recent[-1].get("timestamp") or recent[-1].get("time"))
        if dt0 is not None and dt1 is not None:
            span_h = (dt1 - dt0).total_seconds() / 3600
        if span_h < 2:
            return None  # 时间跨度不足 2 小时，不判定停滞

        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        rate = total_growth / span_h if span_h > 0 else 0
        current_views = recent[-1].get("view_count", 0)

        # 自适应：播放量 < 1万 用绝对阈值，>1万 用相对阈值
        if current_views < 1_0000:
            if rate < 5 and total_growth < max(50, current_views * 0.01):
                conf = _clamp(0.55 + (5 - max(rate, 0)) * 0.05)
                return AlertHit(
                    key="stall",
                    message=f"♪ 播放停下来啦…近 {span_h:.1f}h 只涨了 {_fmt_count(max(total_growth, 0))} (当前 {_fmt_count(current_views)})",
                    confidence=round(conf, 2),
                )
        else:
            min_expected = current_views * 0.00005  # 期望至少十万分之五/小时
            if rate < min_expected:
                shortfall = min_expected / max(rate, 1e-9)  # 差多少倍
                conf = _clamp(0.5 + (shortfall - 1.0) * 0.15)
                return AlertHit(
                    key="stall",
                    message=(
                        f"♪ 播放几乎停住啦…近 {span_h:.1f}h 增速只有 {rate:.1f}/h"
                        f" (预期 >{min_expected:.1f}/h，当前 {_fmt_count(current_views)})"
                    ),
                    confidence=round(conf, 2),
                )
        return None

    # ── 在线人数飙升 ──────────────────────────

    @staticmethod
    def detect_viewer_surge(records: List[Dict]) -> Optional[str]:
        hit = AnomalyDetector.detect_viewer_surge_scored(records)
        return hit.message if hit else None

    @staticmethod
    def detect_viewer_surge_scored(records: List[Dict]) -> Optional[AlertHit]:
        """检测在线人数短时飙升（中位数稳健基线 + 样本量门槛）"""
        if len(records) < 5:
            return None
        rows = _sorted_records(records)
        recent = rows[-5:]
        viewers = [r.get("viewers_total", 0) or 0 for r in recent]
        if max(viewers) < 30:
            return None  # 最大值不足 30 人，不触发告警

        # 中位数基线（前 4 点），避免单点高值误判
        baseline = _median(viewers[:-1])
        last_viewers = viewers[-1]

        if baseline > 0 and last_viewers > baseline * 2.5 and last_viewers > 30:
            ratio = last_viewers / baseline
            conf = _clamp(0.45 + (ratio - 2.5) * 0.1)
            if len(rows) >= 8:
                conf = _clamp(conf + 0.05)
            return AlertHit(
                key="viewer_surge",
                message=f"♨ 在线人数飙升啦!♪ 当前 {last_viewers} 人在线，是之前中位 {baseline:.0f} 的 {ratio:.1f}倍",
                confidence=round(conf, 2),
            )
        return None

    # ── 深夜异常在线 ──────────────────────────

    @staticmethod
    def detect_night_surge(records: List[Dict]) -> Optional[str]:
        hit = AnomalyDetector.detect_night_surge_scored(records)
        return hit.message if hit else None

    @staticmethod
    def detect_night_surge_scored(records: List[Dict]) -> Optional[AlertHit]:
        """检测深夜/凌晨时段异常在线人数（降低触发门槛）"""
        if len(records) < 5:
            return None
        rows = _sorted_records(records)
        now = datetime.now()
        hour = now.hour
        if 7 <= hour < 23:
            return None  # 白天时段不做深夜检测

        recent = rows[-4:]
        viewers = [r.get("viewers_total", 0) or 0 for r in recent]
        current_v = viewers[-1] if viewers else 0
        if current_v < 10:
            return None  # 夜间在线人数过少，忽略

        # 收集日间（9:00-22:00）的在线人数做基准
        day_viewers = []
        for r in rows:
            dt = _parse_dt(r.get("timestamp") or r.get("time"))
            if dt is not None and 9 <= dt.hour <= 22:
                day_viewers.append(r.get("viewers_total", 0) or 0)
        if len(day_viewers) < 4:
            return None  # 日间数据不足，无法比较

        avg_day = sum(day_viewers) / max(len(day_viewers), 1)

        # 夜间在线达到日间均值的 40% 以上，视为异常
        if avg_day > 10 and current_v > avg_day * 0.4:
            ratio = current_v / max(avg_day, 1e-9)
            conf = _clamp(0.5 + ratio * 0.3)  # 超过日间越多越确定
            return AlertHit(
                key="night_surge",
                message=(
                    f"♪ 深夜还有人在线呢…当前 {current_v} 人在线"
                    f"（时段:{hour}:00，日间均{avg_day:.0f}人），"
                    f"可能是机器人刷量哦"
                ),
                confidence=round(conf, 2),
            )
        return None

    # ── 在线人数断崖 ──────────────────────────

    @staticmethod
    def detect_viewer_crash(records: List[Dict]) -> Optional[str]:
        hit = AnomalyDetector.detect_viewer_crash_scored(records)
        return hit.message if hit else None

    @staticmethod
    def detect_viewer_crash_scored(records: List[Dict]) -> Optional[AlertHit]:
        """检测在线人数断崖下跌（中位数稳健基线）"""
        if len(records) < 5:
            return None
        rows = _sorted_records(records)
        recent = rows[-5:]
        viewers = [r.get("viewers_total", 0) or 0 for r in recent]
        if max(viewers) < 50:
            return None  # 在线峰值不足 50 人，不判定为断崖

        baseline = _median(viewers[:-1])  # 前 4 点中位
        last_viewers = viewers[-1]

        # 当前人数降至中位基线的 30% 以下且绝对下降超过 50 人
        if baseline > 0 and last_viewers < baseline * 0.3 and (baseline - last_viewers) > 50:
            drop_ratio = 1.0 - last_viewers / baseline
            conf = _clamp(0.45 + drop_ratio * 0.4)
            return AlertHit(
                key="viewer_crash",
                message=f"↘ 在线人数骤降呢…从中位 {baseline:.0f} 人降到 {last_viewers} 人，降幅 {drop_ratio * 100:.0f}% ♪",
                confidence=round(conf, 2),
            )
        return None

    # ── UP主 直播上下文 ───────────────────────

    @staticmethod
    def detect_live_streaming(_video: Dict = None, up_info: Dict = None) -> Optional[str]:
        hit = AnomalyDetector.detect_live_streaming_scored(_video, up_info)
        return hit.message if hit else None

    @staticmethod
    def detect_live_streaming_scored(_video: Dict = None, up_info: Dict = None) -> Optional[AlertHit]:
        """检测 UP 主是否正在直播（直播期间视频数据异常属于正常现象）"""
        if up_info:
            lr = up_info.get("live_room")
            if lr and lr.get("live_status", 0) == 1:  # live_status=1 表示正在直播
                title = lr.get("live_title", "未命名直播")
                roomid = lr.get("roomid", 0)
                return AlertHit(
                    key="live_stream",
                    message=f"🔴 UP主正在直播哦!♪「{title[:30]}」 (房间 {roomid})，视频数据可能受推流影响",
                    confidence=0.8,  # 状态本身是确定的，但属上下文提示非异常
                )
        return None

    # ── 疑似买量 ──────────────────────────────

    @staticmethod
    def detect_paid_promotion(records: List[Dict], video: Dict = None) -> Optional[str]:
        hit = AnomalyDetector.detect_paid_promotion_scored(records, video)
        return hit.message if hit else None

    @staticmethod
    def detect_paid_promotion_scored(records: List[Dict], video: Dict = None) -> Optional[AlertHit]:
        """
        综合检测疑似买必火/付费推广（7 维评分 + 播放量分级）
        评分 >= 3 → 疑似买量；>= 5 → 高度疑似买量；确定度由评分折算
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
            rows = _sorted_records(records)
            growths = []
            for i in range(1, len(rows)):
                growths.append(rows[i].get("view_count", 0) - rows[i - 1].get("view_count", 0))
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
                rows = _sorted_records(records)
                recent = rows[-4:]
                total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
                span_h = 0.0
                dt0 = _parse_dt(recent[0].get("timestamp") or recent[0].get("time"))
                dt1 = _parse_dt(recent[-1].get("timestamp") or recent[-1].get("time"))
                if dt0 is not None and dt1 is not None:
                    span_h = (dt1 - dt0).total_seconds() / 3600
                night_rate = total_growth / span_h if span_h > 0 else 0
                if night_rate > views * 0.001:
                    score += 1
                    reasons.append("夜间播放异常增长")

        if score < 3:
            return None

        level = "‼ 高度疑似买量" if score >= 5 else "♪ 疑似买量"
        detail = "、".join(reasons[:4])
        if len(reasons) > 4:
            detail += f"等{len(reasons)}项"
        conf = _clamp(0.4 + (score - 3) * 0.15)  # 3→0.4, 5→0.7, 9→1.0
        return AlertHit(
            key="paid_promo",
            message=(
                f"{level}！综合评分 {score}/9\n"
                f"  点赞率{like_rate * 100:.1f}% 投币率{coin_rate * 100:.1f}%"
                f" 收藏率{fav_rate * 100:.1f}% 弹幕率{danmaku_rate * 100:.2f}%\n"
                f"  异常项: {detail}"
            ),
            confidence=round(conf, 2),
        )

    # ── 全检测器调度 ──────────────────────────

    @staticmethod
    def detect_all(records: List[Dict], bvid: str = "", video: Dict = None, up_info: Dict = None) -> List[str]:
        """运行所有检测器，返回触发的告警消息列表（兼容旧 API，返回 str）"""
        hits = AnomalyDetector.detect_all_scored(records, bvid=bvid, video=video, up_info=up_info)
        return [h.message for h in hits]

    @staticmethod
    def detect_all_scored(
        records: List[Dict], bvid: str = "", video: Dict = None, up_info: Dict = None
    ) -> List[AlertHit]:
        """运行所有检测器，返回含确定度的结构化告警列表。

        冷却策略修复(P0)：先运行检测器得到命中，仅对真正命中的 key 占用冷却槽，
        避免"每次扫描都在冷却、真异常被压制"的缺陷。
        """
        hits = []
        detectors = [
            ("growth_spike", lambda: AnomalyDetector.detect_growth_spike_scored(records)),
            ("trend_reversal", lambda: AnomalyDetector.detect_trend_reversal_scored(records)),
            ("stall", lambda: AnomalyDetector.detect_stall_scored(records)),
            ("viewer_surge", lambda: AnomalyDetector.detect_viewer_surge_scored(records)),
            ("viewer_crash", lambda: AnomalyDetector.detect_viewer_crash_scored(records)),
            ("night_surge", lambda: AnomalyDetector.detect_night_surge_scored(records)),
            ("paid_promo", lambda: AnomalyDetector.detect_paid_promotion_scored(records, video=video)),
            ("live_stream", lambda: AnomalyDetector.detect_live_streaming_scored(video=video, up_info=up_info)),
        ]
        for key, detector in detectors:
            try:
                hit = detector()
            except Exception as e:
                logger.debug("检测 %s 异常: %s", key, e)
                continue
            if not hit:
                continue
            alert_key = f"{bvid}:{key}" if bvid else key
            if _record_hit(alert_key):  # 真正命中才记录冷却
                hits.append(hit)
        return hits

    @staticmethod
    def detect_all_min_confidence(
        records: List[Dict], bvid: str = "", video: Dict = None, up_info: Dict = None, min_conf: float = 0.0
    ) -> List[AlertHit]:
        """按最低确定度过滤后的告警（供通知分级使用）"""
        return [
            h
            for h in AnomalyDetector.detect_all_scored(records, bvid=bvid, video=video, up_info=up_info)
            if h.confidence >= min_conf
        ]
