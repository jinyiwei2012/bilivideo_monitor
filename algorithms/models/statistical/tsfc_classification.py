"""TSFC — Time Series Feature Classification（基于特征工程的时序分类预测）

思路（AAAI 2024 思路启发）：
1. 从历史速度序列抽取统计特征（均值/方差/趋势/自相关/谱熵/峰度/偏度）
2. 用 sklearn RandomForestClassifier 将视频分类到若干"增长模式"桶（低速/匀速/爆发/衰减/震荡）
3. 用桶内历史平均速度作为预测速度

为什么不用 torch：分类是低维问题，RF/GBM 足够，且能在 CPU 上即时训练，无 checkpoint 即用即跑。

降级链：sklearn 训练分类 → 直接取近期均值。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

_sklearn_available = True
try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:
    _sklearn_available = False


class TsfcClassificationAlgorithm(BaseAlgorithm):
    """TSFC 时序特征分类预测算法。"""

    name = "TSFC特征分类"
    algorithm_id = "tsfc_classification"
    description = "基于统计特征的时序分类预测（RandomForest 桶映射）"
    category = "统计模型"
    default_weight = 1.1

    # 增长模式桶：(标签, 速度倍数 vs 近期均值)
    _BUCKETS = [
        ("decay", 0.3),  # 衰减期
        ("slow", 0.7),  # 慢速
        ("steady", 1.0),  # 稳定
        ("growing", 1.4),  # 上升
        ("viral", 2.2),  # 爆发
    ]

    def __init__(self):
        super().__init__()
        self._min_seq_len = 6
        self._clf: Optional[RandomForestClassifier] = None
        self._clf_fitted = False

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = int(video_data.get("view_count", 0))
        history = video_data.get("history_data", [])
        if len(history) < self._min_seq_len:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", None)

        views, ts = self._extract_series(history)
        velocities = self._calc_velocity(views, ts)
        if len(velocities) < self._min_seq_len:
            v = float(velocities[-1]) if len(velocities) else 0.0
            return self._make_result(current_views, threshold, v, 0.35, "short_series", None)

        feats = self._extract_features(velocities)
        recent_mean = float(np.mean(velocities[-3:]))

        if _sklearn_available:
            try:
                bucket_label, bucket_idx = self._classify(feats, velocities)
                multiplier = self._BUCKETS[bucket_idx][1]
                predicted = max(0.0, recent_mean * multiplier)
                return self._make_result(
                    current_views,
                    threshold,
                    predicted,
                    0.65,
                    "tsfc_rf",
                    {"bucket": bucket_label, "multiplier": multiplier, "features": feats.tolist()},
                )
            except Exception as e:
                logger.warning("[%s] RF 分类异常，降级: %s", self.algorithm_id, e)

        # 降级：直接用近期均值
        return self._make_result(current_views, threshold, recent_mean, 0.4, "mean_fallback", None)

    # ── 内部 ──────────────────────────────────────────

    def _classify(self, feats: np.ndarray, velocities: np.ndarray) -> Tuple[str, int]:
        """启发式生成训练样本并训练 RF，再用 RF 预测当前桶。

        为什么这样做：没有外部标签数据，但我们能用历史窗口自己生成弱标签
        （window 内末端速度相对于均值的比例 → 桶索引），再 fit/predict 一次。
        每次调用都是新拟合，相当于"在线少样本学习"，开销很低。
        """
        # 生成弱标签：滑窗 + 末端速度 / 全段均值 → 桶索引
        W = min(8, len(velocities) // 2)
        if W < 3:
            return "steady", 2
        X_list, y_list = [], []
        for i in range(W, len(velocities)):
            window = velocities[i - W : i]
            f = self._extract_features(window)
            cur_mean = float(np.mean(window))
            next_v = float(velocities[i])
            ratio = next_v / (cur_mean + 1e-6)
            bucket_idx = self._ratio_to_bucket(ratio)
            X_list.append(f)
            y_list.append(bucket_idx)
        if len(set(y_list)) < 2:
            return self._BUCKETS[y_list[0]][0], y_list[0]
        X = np.array(X_list, dtype=np.float32)
        y = np.array(y_list, dtype=np.int64)
        clf = RandomForestClassifier(n_estimators=20, max_depth=5, n_jobs=1, random_state=42)
        clf.fit(X, y)
        pred = int(clf.predict(feats.reshape(1, -1))[0])
        pred = max(0, min(len(self._BUCKETS) - 1, pred))
        return self._BUCKETS[pred][0], pred

    @staticmethod
    def _ratio_to_bucket(ratio: float) -> int:
        if ratio < 0.5:
            return 0
        if ratio < 0.85:
            return 1
        if ratio < 1.15:
            return 2
        if ratio < 1.75:
            return 3
        return 4

    @staticmethod
    def _extract_features(velocities: np.ndarray) -> np.ndarray:
        """抽取 7 个时序统计特征。"""
        v = np.asarray(velocities, dtype=np.float32)
        if len(v) == 0:
            return np.zeros(7, dtype=np.float32)
        mean = float(np.mean(v))
        std = float(np.std(v)) if len(v) > 1 else 0.0
        # 斜率
        x = np.arange(len(v))
        slope = float(np.polyfit(x, v, 1)[0]) if len(v) > 1 else 0.0
        # 滞后 1 自相关
        if len(v) > 2 and std > 1e-6:
            ac1 = float(np.corrcoef(v[:-1], v[1:])[0, 1])
            if not np.isfinite(ac1):
                ac1 = 0.0
        else:
            ac1 = 0.0
        # 谱熵
        if len(v) > 4:
            psd = np.abs(np.fft.rfft(v - mean)) ** 2
            psd_n = psd / (np.sum(psd) + 1e-8)
            spec_entropy = float(-np.sum(psd_n * np.log(psd_n + 1e-8)))
        else:
            spec_entropy = 0.0
        # 偏度 / 峰度（简化）
        if std > 1e-6 and len(v) > 2:
            centered = (v - mean) / std
            skew = float(np.mean(centered**3))
            kurt = float(np.mean(centered**4) - 3.0)
        else:
            skew = 0.0
            kurt = 0.0
        return np.array([mean, std, slope, ac1, spec_entropy, skew, kurt], dtype=np.float32)

    @staticmethod
    def _extract_series(history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        views, ts = [], []
        for e in history:
            v = e.get("view_count", e.get("view", 0))
            t = e.get("timestamp", 0)
            if hasattr(t, "timestamp"):
                t = t.timestamp()
            elif isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()
                except Exception:
                    continue
            if v and v > 0 and t and t > 0:
                views.append(float(v))
                ts.append(float(t))
        if len(views) > 1:
            order = np.argsort(ts)
            views = [views[i] for i in order]
            ts = [ts[i] for i in order]
        return np.array(views), np.array(ts)

    @staticmethod
    def _calc_velocity(views: np.ndarray, ts: np.ndarray) -> np.ndarray:
        if len(views) < 2:
            return np.array([])
        vs = []
        for i in range(1, len(views)):
            dt = (ts[i] - ts[i - 1]) / 3600.0
            if dt <= 0:
                continue
            vs.append((views[i] - views[i - 1]) / dt)
        return np.array(vs, dtype=np.float32)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            predicted_hours = 0 if remaining <= 0 else remaining / velocity
            if remaining <= 0:
                confidence = 1.0
        metadata = {"reason": reason, "method": "tsfc_classification"}
        if extra:
            metadata.update(extra)
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=int(current_views),
            current_velocity=float(velocity),
            metadata=metadata,
            timestamp=datetime.now(),
        )
