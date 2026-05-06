"""
智能预警模块 — 异常增长检测、趋势反转、在线人数异常
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 记录上次预警时间，避免重复推送
_last_alert_time: Dict[str, datetime] = {}
_ALERT_COOLDOWN_MINUTES = 30  # 同类预警冷却时间


def _fmt_count(n: int) -> str:
    if n >= 1_0000_0000:
        return f"{n / 1_0000_0000:.2f}亿"
    if n >= 1_0000:
        return f"{n / 1_0000:.1f}万"
    return str(n)


def _should_alert(alert_key: str) -> bool:
    now = datetime.now()
    last = _last_alert_time.get(alert_key)
    if last and (now - last).total_seconds() < _ALERT_COOLDOWN_MINUTES * 60:
        return False
    _last_alert_time[alert_key] = now
    return True


class AnomalyDetector:
    """异常检测器，判断各种异常模式"""

    @staticmethod
    def detect_growth_spike(records: List[Dict]) -> Optional[str]:
        """
        检测播放增速异常飙升
        2小时内播放增速 > 平均增速的3倍
        """
        if len(records) < 4:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-4:]  # 最近4条

        try:
            now_ts = datetime.fromisoformat(recent[-1]["timestamp"])
            old_ts = datetime.fromisoformat(recent[0]["timestamp"])
        except Exception:
            return None

        hours_span = (now_ts - old_ts).total_seconds() / 3600
        if hours_span < 0.5:
            return None

        # 整体平均增速
        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        avg_rate = total_growth / hours_span if hours_span > 0 else 0

        # 最近一段增速（最后一小时）
        last_growth = recent[-1].get("view_count", 0) - recent[-2].get("view_count", 0)
        last_hours = 0
        try:
            last_hours = (
                datetime.fromisoformat(recent[-1]["timestamp"]) - datetime.fromisoformat(recent[-2]["timestamp"])
            ).total_seconds() / 3600
        except Exception as e:
            logger.debug("计算最近增速时间间隔失败: %s", e)
        last_rate = last_growth / last_hours if last_hours > 0 else 0

        if avg_rate > 10 and last_rate > avg_rate * 3:
            views = recent[-1].get("view_count", 0)
            return (
                f"⚡ 播放飙升！最近增速 {last_rate:.0f}/h，"
                f"是平均 {avg_rate:.0f}/h 的 {last_rate / avg_rate:.1f}倍 "
                f"(当前 {_fmt_count(views)})"
            )
        return None

    @staticmethod
    def detect_trend_reversal(records: List[Dict]) -> Optional[str]:
        """检测趋势反转（连续3个点增速递减后反弹）"""
        if len(records) < 6:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-6:]

        # 计算每段增速
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

        # 最近3段增速 vs 之前
        recent_g = sum(growths[-2:]) / 2
        prev_g = sum(growths[:-2]) / max(len(growths) - 2, 1) if len(growths) > 2 else 0

        if prev_g > 100 and recent_g < prev_g * 0.3:
            views = recent[-1].get("view_count", 0)
            return f"🔻 增长放缓！增速从 {prev_g:.0f}/h " f"降至 {recent_g:.0f}/h (当前 {_fmt_count(views)})"
        return None

    @staticmethod
    def detect_stall(records: List[Dict]) -> Optional[str]:
        """检测播放停滞（连续多时段增速极低）"""
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
            return None

        total_growth = recent[-1].get("view_count", 0) - recent[0].get("view_count", 0)
        rate = total_growth / span_h if span_h > 0 else 0

        if rate < 5 and total_growth < 100:
            views = recent[-1].get("view_count", 0)
            return (
                f"💤 播放停滞！近 {span_h:.1f}h 仅增长 {_fmt_count(total_growth)}，"
                f"增速 {rate:.1f}/h (当前 {_fmt_count(views)})"
            )
        return None

    @staticmethod
    def detect_viewer_surge(records: List[Dict]) -> Optional[str]:
        """检测在线人数短时飙升"""
        if len(records) < 3:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-3:]

        viewers = [r.get("viewers_total", 0) for r in recent]
        if max(viewers) < 50:
            return None

        avg_viewers = sum(viewers[:-1]) / max(len(viewers) - 1, 1)
        last_viewers = viewers[-1]

        if avg_viewers > 0 and last_viewers > avg_viewers * 3 and last_viewers > 50:
            recent[-1].get("bvid", "")
            return (
                f"🔥 在线人数飙升！当前 {last_viewers} 人在线，" f"是之前的 {last_viewers / max(avg_viewers, 1):.1f}倍"
            )
        return None

    @staticmethod
    def detect_viewer_crash(records: List[Dict]) -> Optional[str]:
        """检测在线人数断崖下跌"""
        if len(records) < 3:
            return None
        sorted_recs = sorted(records, key=lambda r: r.get("timestamp", ""))
        recent = sorted_recs[-3:]

        viewers = [r.get("viewers_total", 0) for r in recent]
        if max(viewers) < 100:
            return None

        prev_viewers = viewers[0]
        last_viewers = viewers[-1]

        if prev_viewers > 0 and last_viewers < prev_viewers * 0.3 and (prev_viewers - last_viewers) > 100:
            return (
                f"📉 在线人数骤降！从 {prev_viewers} 人降至 {last_viewers} 人，"
                f"降幅 {(1 - last_viewers / prev_viewers) * 100:.0f}%"
            )
        return None

    @staticmethod
    def detect_all(records: List[Dict], bvid: str = "") -> List[str]:
        """运行所有检测，返回预警消息列表"""
        alerts = []
        detectors = [
            ("growth_spike", AnomalyDetector.detect_growth_spike),
            ("trend_reversal", AnomalyDetector.detect_trend_reversal),
            ("stall", AnomalyDetector.detect_stall),
            ("viewer_surge", AnomalyDetector.detect_viewer_surge),
            ("viewer_crash", AnomalyDetector.detect_viewer_crash),
        ]
        for key, detector in detectors:
            alert_key = f"{bvid}:{key}" if bvid else key
            if _should_alert(alert_key):
                try:
                    msg = detector(records)
                    if msg:
                        alerts.append(msg)
                except Exception as e:
                    logger.debug(f"检测 {key} 异常: {e}")
        return alerts
