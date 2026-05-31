"""
预测算法基类

定义所有预测算法的统一抽象接口（BaseAlgorithm）和预测结果数据结构（PredictionResult）。
子类需实现 predict() 方法，并可复用基类提供的辅助方法计算播放速度、互动率等。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any
from datetime import datetime
import time
from utils.time_utils import safe_timestamp


@dataclass
class PredictionResult:
    """预测结果 —— 存储单个算法对单个视频的预测产出。

    Attributes:
        algorithm_name: 算法可读名称
        algorithm_id:   算法唯一标识
        target_threshold: 目标播放量阈值（如 100000、1000000、10000000）
        predicted_hours:  预测达到目标阈值所需小时数
        confidence:       置信度，取值范围 [0, 1]
        current_views:    当前播放量
        current_velocity: 当前播放速度（播放量/小时）
        metadata:         额外元数据字典（如算法内部状态、特征值等）
        timestamp:        预测时间戳
    """

    algorithm_name: str
    algorithm_id: str
    target_threshold: int
    predicted_hours: float
    confidence: float
    current_views: int
    current_velocity: float
    metadata: Dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        """将预测结果序列化为字典（timestamp 转为 ISO 格式字符串）。"""
        return {
            "algorithm_name": self.algorithm_name,
            "algorithm_id": self.algorithm_id,
            "target_threshold": self.target_threshold,
            "predicted_hours": self.predicted_hours,
            "confidence": self.confidence,
            "current_views": self.current_views,
            "current_velocity": self.current_velocity,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class BaseAlgorithm(ABC):
    """预测算法抽象基类

    所有具体预测算法必须继承此类并实现 predict() 方法。
    基类提供以下公共辅助方法：
        - calculate_velocity()   根据历史数据计算播放速度
        - get_engagement_rate()  计算综合互动率
        - get_quality_score()    计算内容质量评分
        - get_video_age_hours()  计算视频已发布时长
    """

    # 算法元信息 —— 子类应覆盖这些类属性
    name: str = "基类算法"
    description: str = "预测算法基类"
    category: str = "基础"

    def __init__(self):
        pass

    @abstractmethod
    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测 —— 子类必须实现此方法。

        Args:
            video_data: 包含视频所有数据的字典，包括：
                - view_count: 当前播放量
                - history_data: 历史数据列表（每项含 view_count 和 timestamp）
                - timestamp: 当前时间戳
                - 其他视频信息字段（like_count、coin_count 等）
            threshold: 目标播放量阈值（默认 10 万）

        Returns:
            PredictionResult 对象，包含算法名称、预测结果、置信度等
        """

    # ── 质量评分权重常量 ───────────────────────────
    _W_ENGAGEMENT = 0.4   # 互动率权重
    _W_DANMAKU = 0.3      # 弹幕密度权重
    _W_COIN_LIKE = 0.3    # 投币/点赞比权重

    # ── 公共辅助方法 ───────────────────────────────

    def calculate_velocity(self, video_data: Dict[str, Any]) -> float:
        """根据历史数据计算当前播放速度（播放量/小时）。

        优先取 video_data['history_data'] 中最近的**两个**有效数据点
        计算速度；若数据不足两则返回 0.0。
        """
        history = video_data.get("history_data", [])
        if len(history) < 2:
            return 0.0
        try:
            # 按时间戳排序，确保取到最新的两个数据点
            def _sort_key(x):
                ts = x.get("timestamp", 0)
                if isinstance(ts, (int, float)):
                    return ts
                if hasattr(ts, "timestamp"):
                    return ts.timestamp()
                try:
                    return datetime.fromisoformat(str(ts)).timestamp()
                except Exception:
                    return 0
            sorted_hist = sorted(history, key=_sort_key)
            recent = sorted_hist[-2:]
            v0 = float(recent[0].get("view_count", 0))
            v1 = float(recent[-1].get("view_count", 0))
            t0 = recent[0].get("timestamp", 0)
            t1 = recent[-1].get("timestamp", 0)
            # timestamp 字段可能是 float（Unix 时间戳）或 datetime 对象，统一转为秒
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            elif not isinstance(t0, (int, float)):
                t0 = 0
            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            elif not isinstance(t1, (int, float)):
                t1 = 0
            dt_hours = (t1 - t0) / 3600.0
            if dt_hours <= 0:
                return 0.0
            return max(0.0, (v1 - v0) / dt_hours)
        except Exception:
            return 0.0

    def get_engagement_rate(self, video_data: Dict[str, Any]) -> float:
        """计算综合互动率。

        公式：(点赞 + 投币 + 收藏 + 分享) / 播放量，结果限制在 [0, 1]。
        """
        views = max(video_data.get("view_count", 0), 1)
        likes = video_data.get("like_count", 0) or 0
        coins = video_data.get("coin_count", 0) or 0
        favorites = video_data.get("favorite_count", 0) or 0
        shares = video_data.get("share_count", 0) or 0
        return min(1.0, (likes + coins + favorites + shares) / views)

    def get_quality_score(self, video_data: Dict[str, Any]) -> float:
        """计算内容质量评分，取值范围 [0, 1]。

        综合考虑三个维度：
            - 互动率（engagement）
            - 弹幕密度（每万播放弹幕数）
            - 投币/点赞比（硬币认可度）
        各维度通过预设权重加权求和。
        """
        engagement = self.get_engagement_rate(video_data)
        views = max(video_data.get("view_count", 0), 1)
        danmaku = video_data.get("danmaku_count", 0) or 0
        likes = video_data.get("like_count", 0) or 0
        coins = video_data.get("coin_count", 0) or 0

        # 弹幕密度：每万播放的弹幕数量，上限 1.0
        danmaku_density = min(1.0, danmaku / views * 10000)
        # 投币/点赞比：比值越高表示用户认可度越高
        coin_like_ratio = min(1.0, coins / max(likes, 1))
        score = self._W_ENGAGEMENT * engagement + self._W_DANMAKU * danmaku_density + self._W_COIN_LIKE * coin_like_ratio
        return min(1.0, max(0.0, score))

    def get_video_age_hours(self, video_data: Dict[str, Any]) -> float:
        """计算视频发布至今的小时数。

        优先级：
            1. 从 history_data 中最旧记录的 timestamp 推算
            2. 回退到 video_data['timestamp']（可为 datetime 或 Unix 时间戳）
            3. 均不可用时返回 0.0
        """
        history = video_data.get("history_data", [])
        now = datetime.now()
        if len(history) >= 1:
            sorted_history = sorted(
                history,
                key=lambda x: (
                    x.get("timestamp", 0).timestamp()
                    if hasattr(x.get("timestamp", 0), "timestamp")
                    else float(x.get("timestamp", 0))
                ),
            )
            t = sorted_history[0].get("timestamp", None)
            if t is not None:
                try:
                    ts_val = safe_timestamp(t)
                except Exception:
                    ts_val = time.time()
                return max(0.0, (time.time() - ts_val) / 3600.0)
        # 回退：用 video_data 自身的 timestamp
        ts = video_data.get("timestamp")
        if ts is not None:
            if hasattr(ts, "timestamp"):
                return max(0.0, (now - ts).total_seconds() / 3600.0)
            if isinstance(ts, (int, float)):
                return max(0.0, (time.time() - ts) / 3600.0)
        return 0.0
