"""
集成输出系统性偏差校准 — B3

背景：
    权重管理器按"算法个体历史准确率"调权，但从未纠正集成输出的系统性偏差。
    若某视频整体高估（所有算法预测增速都偏乐观），权重不变，集成结果持续偏高。

方案：
    维护 per-bvid 的「预测增长 vs 实际增长」比例误差窗口：
        observed_ratio = actual_growth / predicted_growth
    样本充足（>= _MIN_SAMPLES）时，对 _weighted 输出的增长部分施加中位数乘数修正。

约束：
    - 只修正 growth（预测值 - 当前值），不动 current_value 本身
    - 修正系数限幅 [_MAX_CORRECTION, 1/_MAX_CORRECTION]，避免单个极端误差过度影响
    - 修正后仍 clamp 到 >= current_value（播放量不回退）
    - 内存态，随进程生命周期；不做磁盘持久化（重启后重新累积）
"""

import logging
import threading
from collections import deque
from typing import Dict, Deque, Optional

logger = logging.getLogger(__name__)

# 启用修正所需的最小样本数（太少时统计不可靠，宁可不修正）
_MIN_SAMPLES = 10
# 保留的最大误差窗口（超出丢最旧）
_MAX_WINDOW = 30
# 单次样本允许的最大比例跨度（过滤脏数据：翻 5 倍以上的样本不参与）
_MAX_SAMPLE_RATIO = 5.0
# 修正系数限幅范围 [0.5, 2.0]（对称 ±100%）
_MAX_CORRECTION = 2.0


class BiasCorrector:
    """按 bvid 维护预测增长偏差并输出中位数修正系数。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._samples: Dict[str, Deque[float]] = {}

    # ── 记录 ──

    def record(self, bvid: str, predicted_growth: float, actual_growth: float):
        """记录一次预测增长 vs 实际增长。

        Args:
            bvid: 视频 BV 号
            predicted_growth: 上一轮预测的增长量（>0 才有意义）
            actual_growth: 实际发生的增长量（>=0）
        """
        if not bvid:
            return
        if predicted_growth is None or predicted_growth <= 0:
            return  # 预测无增长，偏差无定义
        if actual_growth is None or actual_growth < 0:
            return
        try:
            ratio = actual_growth / predicted_growth
        except (ZeroDivisionError, TypeError):
            return
        # 过滤极端脏样本（e.g. 预测 1 实际 1e6）
        if ratio > _MAX_SAMPLE_RATIO or ratio < 1.0 / _MAX_SAMPLE_RATIO:
            ratio = _MAX_SAMPLE_RATIO if ratio > _MAX_SAMPLE_RATIO else 1.0 / _MAX_SAMPLE_RATIO
        with self._lock:
            q = self._samples.setdefault(bvid, deque(maxlen=_MAX_WINDOW))
            q.append(float(ratio))

    # ── 查询 ──

    def get_correction(self, bvid: str) -> dict:
        """返回当前建议的修正信息。

        Returns:
            dict: {"factor": 修正乘数(1.0=不修正), "samples": 样本数,
                   "enabled": 是否启用修正}
        """
        with self._lock:
            q = self._samples.get(bvid)
            if not q or len(q) < _MIN_SAMPLES:
                return {"factor": 1.0, "samples": len(q) if q else 0, "enabled": False}
            vals = sorted(q)
            n = len(vals)
            if n % 2 == 1:
                median = vals[n // 2]
            else:
                median = (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        # ratio > 1 → 实际增长超过预测 → 之前低估 → 上调
        # ratio < 1 → 实际增长低于预测 → 之前高估 → 下调
        factor = median
        factor = max(1.0 / _MAX_CORRECTION, min(_MAX_CORRECTION, factor))
        return {"factor": round(factor, 3), "samples": len(q), "enabled": True}

    def reset_bvid(self, bvid: str):
        """删除某视频的样本（删除监控时调用）"""
        with self._lock:
            self._samples.pop(bvid, None)


# 模块级单例
_corrector = None
_corrector_lock = threading.Lock()


def get_bias_corrector() -> BiasCorrector:
    """获取全局 BiasCorrector 单例（双检锁）。"""
    global _corrector
    if _corrector is None:
        with _corrector_lock:
            if _corrector is None:
                _corrector = BiasCorrector()
    return _corrector
