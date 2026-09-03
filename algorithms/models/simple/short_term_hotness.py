"""
短期热度感知预测算法模块（网络调研落地：在线人数 + 自激励动量）

研究背景（Front.Physics 2022 B站专项 / Infocom'15 Pop-Forecast）：
    - 弹幕量/在线人数是短期热度的直接代理，可显著改善"下一个时间窗增量"预测
    - 自激励过程（Hawkes）：爆发后短期仍倾向继续增长，而非立即回归基线
    - 但本项目监控目标是"到达 10万/100万/1000万 的长程小时数"，在线人数只能
      反映"此刻热度"，不能假设其可持续到远阈值 —— 故采用保守调制：

核心逻辑：
    1. 基线：稳健速率外推（calculate_velocity 已优先返回 velocity_robust_hourly）
    2. 在线人数调制：viewers_total 与近期播放速率的比值衡量"转化热度"——
       比值稳定（正常区间）→ 不额外调整；比值异常高（可疑直播/买量）→ 置信降低
    3. 自激励动量：若近 1h 处于推流状态（detect_surge is_surging），
       短期速率按衰减半衰期适度上调（不假设永恒爆发，仅修正"立即回归"的过度保守）
    4. 置信度反映数据可得性：无 viewers → 中等置信；有 viewers 且比率正常 → 高置信

适用场景：有实时在线人数数据的视频（监控拉取自带）
局限性：在线人数非可持续性指标，仅做 ±20% 以内的保守调制，不做激进外推。

所属分类：基础速度类
"""

from datetime import datetime
from typing import Dict, Any
from algorithms.base import BaseAlgorithm, PredictionResult


class ShortTermHotnessAlgorithm(BaseAlgorithm):
    """短期热度感知预测算法（在线人数 + 自激励动量，保守调制）"""

    name = "短期热度感知"
    algorithm_id = "short_term_hotness"
    description = "融合在线人数与自激励动量的速度调制预测"
    category = "基础速度"
    default_weight = 1.0

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = video_data.get("view_count", 0)
        # 基线稳健速率（registry 已优先返回抗噪的 velocity_robust_hourly）
        velocity = self.calculate_velocity(video_data)
        if velocity <= 0:
            return self._std_result(float("inf"), 0.0, current_views, threshold,
                                    velocity=0.0, method="short_term_hotness")

        live = video_data.get("live_features", {}) or {}
        viewers_total = live.get("viewers_total", 0) or 0
        conf_bonus = 0.0
        meta = {"method": "short_term_hotness", "base_velocity": round(velocity, 2)}

        # ── 在线人数：异常热度识别 + 温和调制 ──
        if viewers_total > 0:
            # 用"在线人数占当前累计播放的比例"识别伪热度（直播/买量：在线/播放异常高）
            pop_ratio = viewers_total / max(current_views, 1)  # 每播放的在在线比例
            meta["viewers_pop_ratio"] = round(pop_ratio, 5)
            # 真实视频在线占比通常 <1%（1万播放视频 0~100 在线）
            if pop_ratio > 0.02:  # 在线 > 2% 播放量 → 可疑（直播/买量）
                meta["hotness_flag"] = "suspicious"
                conf_bonus -= 0.15
            else:
                # 正常在线热度 → 温和提速（在线是即时信号,非长程可持续,封顶 8%）
                # 归一化：0.5% 在线占比 → 满幅；低于 0.05% 几乎无信息
                hot_factor = min(0.08, max(0.02, pop_ratio / 0.005) * 0.08)
                velocity *= 1.0 + hot_factor
                meta["hotness_factor"] = round(hot_factor, 4)
                conf_bonus += 0.05

        # ── 自激励动量：近 1h 推流 → 短期速率按半衰期保守上调 ──
        try:
            surge = self.detect_surge(video_data)
            if surge.get("is_surging"):
                meta["surge_type"] = surge.get("surge_type", "")
                # 用推流检测的 adjusted_velocity（已含衰减）作为上限，避免双算
                adj = surge.get("adjusted_velocity", 0)
                if adj > 0 and adj < velocity:
                    # 推流已计入衰减的速率若低于纯动量 → 纯动量过于乐观,取中
                    velocity = 0.5 * velocity + 0.5 * max(adj, velocity * 0.5)
                meta["surge_adjusted"] = round(velocity, 2)
        except Exception:
            pass

        remaining = threshold - current_views
        if remaining <= 0:
            return self._std_result(0.0, 1.0, current_views, threshold,
                                    velocity=velocity, method="short_term_hotness")

        predicted_hours = remaining / velocity
        # 置信：年龄衰减基准 + 数据可得性调制
        age_hours = self.get_video_age_hours(video_data)
        confidence = min(1.0, max(0.3, 1 - age_hours / 168))
        confidence = max(0.2, min(0.95, confidence + conf_bonus))

        return self._std_result(predicted_hours, confidence, current_views, threshold,
                                velocity=velocity, metadata=meta)
