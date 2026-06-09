"""
TSFC — Time Series Feature Classification（基于特征工程的时序分类预测）
======================================================================

从历史速度序列抽取统计特征，使用随机森林分类器将视频映射到增长模式桶。

核心原理（AAAI 2024 思路启发）：
  1. 从历史速度序列抽取 7 个时序统计特征：
     - 均值 (mean): 平均增长速率
     - 标准差 (std): 增长速度的波动性
     - 斜率 (slope): 增长趋势方向（上升/下降）
     - 滞后 1 自相关 (ac1): 短期前后关联性
     - 谱熵 (spec_entropy): 频域的规则性/混沌程度
     - 偏度 (skew): 分布不对称性（爆发偏向正偏）
     - 峰度 (kurt): 分布的肥尾程度（极端事件频率）

  2. 用滑窗生成弱标签：窗口末端速度相对于窗口均值的比例 → 桶索引

  3. 增长模式桶 (5 个):
     - decay (0.3×): 衰减期 — 播放增速持续下降
     - slow (0.7×): 慢速 — 低于平均增速
     - steady (1.0×): 稳定 — 接近平均增速
     - growing (1.4×): 上升 — 高于平均增速
     - viral (2.2×): 爆发 — 远高于平均增速（病毒式传播）

  4. RandomForestClassifier 分类后，用桶的速度倍数 × 近期均值作为预测速度

为什么不用 torch：分类是低维问题，RF 足够，且能在 CPU 上即时训练。

降级链：sklearn 训练分类 → 直接取近期均值。

适用场景：历史记录 >= 6 条，希望区分增长阶段
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult

logger = logging.getLogger(__name__)

# sklearn 可用性标记
_sklearn_available = True
try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:
    _sklearn_available = False


class TsfcClassificationAlgorithm(BaseAlgorithm):
    """
    TSFC 时序特征分类预测算法

    从历史速度序列抽取 7 个统计特征，使用 RandomForestClassifier
    将视频分类到 5 个增长模式桶，用桶的速度倍数 × 近期均值作为预测。

    属性:
        _BUCKETS (List[Tuple]): 增长模式桶定义列表
            [(标签, 速度倍数)]
        _min_seq_len (int): 最小序列长度，默认 6
        _clf (Optional[RandomForestClassifier]): sklearn 分类器实例
        _clf_fitted (bool): 分类器是否已拟合
        default_weight (float): 默认集成权重 1.1
    """

    name = "TSFC特征分类"
    algorithm_id = "tsfc_classification"
    description = "基于统计特征的时序分类预测（RandomForest 桶映射）"
    category = "统计模型"
    default_weight = 1.1

    # 增长模式桶：(标签, 速度倍数 vs 近期均值)
    _BUCKETS = [
        ("decay", 0.3),  # 衰减期：增量约为均值的 30%
        ("slow", 0.7),  # 慢速：增量约为均值的 70%
        ("steady", 1.0),  # 稳定：增量为均值
        ("growing", 1.4),  # 上升：增量约为均值的 1.4 倍
        ("viral", 2.2),  # 爆发：增量约为均值的 2.2 倍
    ]

    def __init__(self):
        """初始化 TSFC 分类器"""
        super().__init__()
        self._min_seq_len = 6  # 最少需要 6 个数据点才能有效提取特征
        self._clf: Optional[RandomForestClassifier] = None  # sklearn 分类器
        self._clf_fitted = False  # 拟合标记

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """
        执行 TSFC 分类预测

        流程:
          1. 从历史记录提取播放量和时间戳序列
          2. 计算速度序列（播放量增量 / 时间增量）
          3. 提取 7 个统计特征
          4. 若 sklearn 可用：训练 RF 分类器 → 预测桶 → 用桶倍数 × 近期均值
          5. 若不可用：直接使用近期均值

        参数:
            video_data (Dict): 视频数据
            threshold (int): 目标播放量阈值

        返回:
            PredictionResult: 包含桶类别等元数据的预测结果
        """
        current_views = int(video_data.get("view_count", 0))
        history = video_data.get("history_data", [])
        # 数据不足
        if len(history) < self._min_seq_len:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", None)

        # 提取播放量和时间戳序列
        views, ts = self._extract_series(history)
        # 计算速度序列
        velocities = self._calc_velocity(views, ts)
        if len(velocities) < self._min_seq_len:
            v = float(velocities[-1]) if len(velocities) else 0.0
            return self._make_result(current_views, threshold, v, 0.35, "short_series", None)

        # 提取 7 个统计特征
        feats = self._extract_features(velocities)
        # 近期均值（最近 3 个速度值的均值）作为基础预测
        recent_mean = float(np.mean(velocities[-3:]))

        if _sklearn_available:
            try:
                # 分类获取增长模式桶
                bucket_label, bucket_idx = self._classify(feats, velocities)
                multiplier = self._BUCKETS[bucket_idx][1]  # 桶的速度倍数
                # 预测速度 = 近期均值 × 桶倍数
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

    # ── 内部方法 ──────────────────────────────────────────

    def _classify(self, feats: np.ndarray, velocities: np.ndarray) -> Tuple[str, int]:
        """
        启发式生成训练样本并训练 RF，再用 RF 预测当前桶

        为什么这样做：没有外部标签数据，但我们能用历史窗口自己生成弱标签
        （window 内末端速度相对于均值的比例 → 桶索引），再 fit/predict 一次。
        每次调用都是新拟合，相当于"在线少样本学习"，开销很低。

        流程:
          1. 对速度序列滑窗（窗口 W=min(8, N/2)）
          2. 对每个窗口，计算窗口内特征的均值，下一个时刻的速度
          3. ratio = next_v / cur_mean → 映射到桶索引
          4. 用 X(clf) 和 y(clf) 训练 RandomForestClassifier
          5. 用训练好的分类器预测当前特征所属的桶

        参数:
            feats (np.ndarray): 当前速度序列的 7 维特征向量
            velocities (np.ndarray): 完整速度序列

        返回:
            Tuple[str, int]: (桶标签, 桶索引)
        """
        # 窗口大小 W = min(8, N/2) 但至少 3
        W = min(8, len(velocities) // 2)
        if W < 3:
            return "steady", 2  # 默认稳定桶

        # 生成弱标签
        X_list, y_list = [], []
        for i in range(W, len(velocities)):
            window = velocities[i - W : i]  # 当前窗口
            f = self._extract_features(window)  # 窗口特征
            cur_mean = float(np.mean(window))  # 窗口内均值
            next_v = float(velocities[i])  # 下一时刻的速度
            ratio = next_v / (cur_mean + 1e-6)  # 速度比
            bucket_idx = self._ratio_to_bucket(ratio)  # 映射到桶
            X_list.append(f)
            y_list.append(bucket_idx)

        # 所有样本属于同一桶 → 无需训练分类器
        if len(set(y_list)) < 2:
            return self._BUCKETS[y_list[0]][0], y_list[0]

        # 训练 RF 分类器
        X = np.array(X_list, dtype=np.float32)
        y = np.array(y_list, dtype=np.int64)
        # 20 棵树，max_depth=5：轻量级分类器，快速训练
        clf = RandomForestClassifier(n_estimators=20, max_depth=5, n_jobs=1, random_state=42)
        clf.fit(X, y)
        # 预测当前特征所属桶
        pred = int(clf.predict(feats.reshape(1, -1))[0])
        pred = max(0, min(len(self._BUCKETS) - 1, pred))  # 边界保护
        return self._BUCKETS[pred][0], pred

    @staticmethod
    def _ratio_to_bucket(ratio: float) -> int:
        """
        将速度比映射到增长模式桶索引

        映射规则:
          ratio < 0.5    → 0 (decay: 衰减)
          ratio < 0.85   → 1 (slow: 慢速)
          ratio < 1.15   → 2 (steady: 稳定)
          ratio < 1.75   → 3 (growing: 上升)
          ratio >= 1.75  → 4 (viral: 爆发)

        参数:
            ratio (float): 下一时刻速度 / 窗口均值速度

        返回:
            int: 桶索引 [0-4]
        """
        if ratio < 0.5:
            return 0  # 衰减
        if ratio < 0.85:
            return 1  # 慢速
        if ratio < 1.15:
            return 2  # 稳定
        if ratio < 1.75:
            return 3  # 上升
        return 4  # 爆发

    @staticmethod
    def _extract_features(velocities: np.ndarray) -> np.ndarray:
        """
        抽取 7 个时序统计特征

        特征列表:
          0. mean: 平均速度 — 反映整体增长水平
          1. std: 标准差 — 反映速度波动性
          2. slope: 线性拟合斜率 — 反映趋势方向
          3. ac1: 滞后 1 自相关 — 反映短期前后依赖
          4. spec_entropy: 谱熵 — 反映频域复杂性
          5. skew: 偏度 — 反映分布不对称性（正偏=有爆发脉冲）
          6. kurt: 峰度 (excess kurtosis) — 反映极端事件频率

        参数:
            velocities (np.ndarray): 速度序列

        返回:
            np.ndarray: 7 维特征向量
        """
        v = np.asarray(velocities, dtype=np.float32)
        if len(v) == 0:
            return np.zeros(7, dtype=np.float32)

        mean = float(np.mean(v))  # 特征 0: 均值
        std = float(np.std(v)) if len(v) > 1 else 0.0  # 特征 1: 标准差

        # 特征 2: 线性拟合斜率（1 次多项式拟合）
        x = np.arange(len(v))
        slope = float(np.polyfit(x, v, 1)[0]) if len(v) > 1 else 0.0

        # 特征 3: 滞后 1 自相关（σ > 1e-6 防止除零/常量序列）
        if len(v) > 2 and std > 1e-6:
            with np.errstate(invalid="ignore"):  # 常量序列可能导致 NaN
                ac1 = float(np.corrcoef(v[:-1], v[1:])[0, 1])
            if not np.isfinite(ac1):  # NaN 保护
                ac1 = 0.0
        else:
            ac1 = 0.0

        # 特征 4: 谱熵（频域能量分布的熵）
        if len(v) > 4:
            # 计算功率谱密度
            psd = np.abs(np.fft.rfft(v - mean)) ** 2  # 去均值后 FFT + 幅值平方
            psd_n = psd / (np.sum(psd) + 1e-8)  # 归一化功率谱
            spec_entropy = float(-np.sum(psd_n * np.log(psd_n + 1e-8)))  # 信息熵
        else:
            spec_entropy = 0.0

        # 特征 5&6: 偏度和峰度（标准化三阶/四阶矩，减 3 得 excess kurtosis）
        if std > 1e-6 and len(v) > 2:
            centered = (v - mean) / std  # Z-score 标准化
            skew = float(np.mean(centered**3))  # 偏度 (三阶矩)
            kurt = float(np.mean(centered**4) - 3.0)  # 超额峰度 (减正态分布的 3)
        else:
            skew = 0.0
            kurt = 0.0

        return np.array([mean, std, slope, ac1, spec_entropy, skew, kurt], dtype=np.float32)

    @staticmethod
    def _extract_series(history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        从历史记录中提取播放量和时间戳序列

        自动处理多种时间戳格式，按时间升序排列。

        参数:
            history (List[Dict]): 历史数据列表

        返回:
            Tuple[np.ndarray, np.ndarray]: (播放量数组, 时间戳数组)
        """
        views, ts = [], []
        for e in history:
            v = e.get("view_count", e.get("view", 0))
            t = e.get("timestamp", 0)
            # 处理多种时间戳格式
            if hasattr(t, "timestamp"):
                t = t.timestamp()  # datetime 对象
            elif isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()  # ISO 字符串
                except Exception:
                    continue  # 解析失败跳过
            if v and v > 0 and t and t > 0:  # 过滤无效数据
                views.append(float(v))
                ts.append(float(t))
        # 按时间升序排列
        if len(views) > 1:
            order = np.argsort(ts)
            views = [views[i] for i in order]
            ts = [ts[i] for i in order]
        return np.array(views), np.array(ts)

    @staticmethod
    def _calc_velocity(views: np.ndarray, ts: np.ndarray) -> np.ndarray:
        """
        计算速度序列

        速度 = (播放量增量) / (时间增量/3600) = 每小时新增播放量

        参数:
            views (np.ndarray): 播放量序列
            ts (np.ndarray): 时间戳序列（秒）

        返回:
            np.ndarray: 速度序列（每小时增量），长度 = len(views) - 1
        """
        if len(views) < 2:
            return np.array([])
        vs = []
        for i in range(1, len(views)):
            dt = (ts[i] - ts[i - 1]) / 3600.0  # 时间差转换为小时
            if dt <= 0:
                continue  # 跳过时间倒退或零间隔
            vs.append((views[i] - views[i - 1]) / dt)  # 每小时增量
        return np.array(vs, dtype=np.float32)

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        """
        构造 PredictionResult

        参数:
            current_views (int): 当前播放量
            threshold (int): 目标阈值
            velocity (float): 预测速度
            confidence (float): 置信度
            reason (str): 预测方法原因标识
            extra (Dict | None): 额外元数据

        返回:
            PredictionResult
        """
        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            predicted_hours = 0 if remaining <= 0 else remaining / velocity
            if remaining <= 0:
                confidence = 1.0
        # 构建元数据
        metadata = {"reason": reason, "method": "tsfc_classification"}
        if extra:
            metadata.update(extra)  # 合并额外数据（桶标签、倍数等）
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
