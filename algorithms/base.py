"""
预测算法基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import time


@dataclass
class PredictionResult:
    """预测结果"""
    algorithm_name: str
    algorithm_id: str
    target_threshold: int  # 目标阈值 (100000, 1000000, 10000000)
    predicted_hours: float  # 预测所需小时数
    confidence: float  # 置信度 0-1
    current_views: int  # 当前播放量
    current_velocity: float  # 当前速度 (播放/小时)
    metadata: Dict[str, Any]  # 额外元数据
    timestamp: datetime  # 预测时间

    def to_dict(self) -> Dict[str, Any]:
        return {
            'algorithm_name': self.algorithm_name,
            'algorithm_id': self.algorithm_id,
            'target_threshold': self.target_threshold,
            'predicted_hours': self.predicted_hours,
            'confidence': self.confidence,
            'current_views': self.current_views,
            'current_velocity': self.current_velocity,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat()
        }


class BaseAlgorithm(ABC):
    """预测算法基类

    提供 4 个公共辅助方法供子类调用：
    - calculate_velocity(video_data)
    - get_engagement_rate(video_data)
    - get_quality_score(video_data)
    - get_video_age_hours(video_data)
    """

    # 算法标识
    name: str = "基类算法"
    description: str = "预测算法基类"
    category: str = "基础"

    def __init__(self):
        pass

    @abstractmethod
    def predict(
        self,
        current_views: int,
        target_views: int,
        history_data: List[Dict[str, Any]],
        video_info: Dict[str, Any]
    ) -> Optional[tuple]:
        """执行预测

        Args:
            current_views: 当前播放量
            target_views: 目标播放量
            history_data: 历史数据列表
            video_info: 视频信息

        Returns:
            (预测秒数, 置信度) 或 None
        """
        pass

    # ── 公共辅助方法 ───────────────────────────────

    def calculate_velocity(self, video_data: Dict[str, Any]) -> float:
        """根据历史数据计算当前播放速度（播放量/小时）。

        优先使用 video_data['history_data']，取最近两个有效数据点；
        若只有单条数据或无历史则返回 0。
        """
        history = video_data.get('history_data', [])
        if len(history) < 2:
            return 0.0
        try:
            recent = history[-2:]
            v0 = float(recent[0].get('view_count', 0))
            v1 = float(recent[-1].get('view_count', 0))
            t0 = recent[0].get('timestamp', 0)
            t1 = recent[-1].get('timestamp', 0)
            # timestamp 可能是 float（Unix时间戳）或 datetime 对象
            if hasattr(t0, 'timestamp'):
                t0 = t0.timestamp()
            elif not isinstance(t0, (int, float)):
                t0 = 0
            if hasattr(t1, 'timestamp'):
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
        """计算综合互动率 = (点赞+投币+收藏+分享) / 播放量，范围 [0, 1]。"""
        views = max(video_data.get('view_count', 0), 1)
        likes = video_data.get('like_count', 0) or 0
        coins = video_data.get('coin_count', 0) or 0
        favorites = video_data.get('favorite_count', 0) or 0
        shares = video_data.get('share_count', 0) or 0
        return min(1.0, (likes + coins + favorites + shares) / views)

    def get_quality_score(self, video_data: Dict[str, Any]) -> float:
        """计算内容质量评分 [0, 1]。

        综合考虑互动率、弹幕密度、投币/点赞比。
        """
        engagement = self.get_engagement_rate(video_data)
        views = max(video_data.get('view_count', 0), 1)
        danmaku = video_data.get('danmaku_count', 0) or 0
        likes = video_data.get('like_count', 0) or 0
        coins = video_data.get('coin_count', 0) or 0

        # 弹幕密度（每万播放弹幕数，上限1.0）
        danmaku_density = min(1.0, danmaku / max(views, 1) * 10000)
        # 投币/点赞比（越高表示认可度越高）
        coin_like_ratio = min(1.0, coins / max(likes, 1))

        score = 0.4 * engagement + 0.3 * danmaku_density + 0.3 * coin_like_ratio
        return min(1.0, max(0.0, score))

    def get_video_age_hours(self, video_data: Dict[str, Any]) -> float:
        """计算视频发布至今的小时数。

        优先从 history_data 推算（最早记录 → 现在）；
        若无历史则用 video_data['timestamp']（datetime）。
        """
        history = video_data.get('history_data', [])
        now = datetime.now()
        if len(history) >= 1:
            t = history[0].get('timestamp', None)
            if t is not None:
                if hasattr(t, 'timestamp'):
                    t = t.timestamp()
                elif isinstance(t, (int, float)):
                    pass
                elif isinstance(t, str):
                    try:
                        t = datetime.fromisoformat(t).timestamp()
                    except Exception:
                        t = time.time()
                else:
                    t = time.time()
                return max(0.0, (time.time() - t) / 3600.0)
        # 回退：用 video_data 自身的 timestamp
        ts = video_data.get('timestamp')
        if ts is not None:
            if hasattr(ts, 'timestamp'):
                return max(0.0, (now - ts).total_seconds() / 3600.0)
            if isinstance(ts, (int, float)):
                return max(0.0, (time.time() - ts) / 3600.0)
        return 0.0
