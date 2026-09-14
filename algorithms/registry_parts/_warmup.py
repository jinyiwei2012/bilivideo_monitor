"""WarmupMixin extracted from algorithms.registry."""

import threading
from typing import Any, Callable, List, TYPE_CHECKING

from numpy.typing import NDArray

from ..base import BaseAlgorithm

from ._shared import get_weight_manager, logger


class WarmupMixin:
    _history_lock: threading.Lock
    _backtest_warmed: set[str]
    _algorithms: dict[str, BaseAlgorithm]

    if TYPE_CHECKING:

        @classmethod
        def get_algorithm_names(cls) -> List[str]:
            raise NotImplementedError

    @classmethod
    def _make_backtest_predict_fn(cls, algo: BaseAlgorithm, np: Any) -> Callable[[NDArray[Any]], float]:
        def fn(train: NDArray[Any]) -> float:
            if len(train) < 3:
                return float(train[-1]) if len(train) > 0 else 0.0
            try:
                hist_list = []
                # 回测用索引时间（等间隔假设），构造 video_data
                base_ts = 1_700_000_000.0
                for _i, _v in enumerate(train):
                    hist_list.append({"view_count": float(_v), "timestamp": base_ts + _i * 75.0})
                vd = {
                    "view_count": float(train[-1]),
                    "history_data": hist_list,
                    "_sorted": True,
                    "timestamp": base_ts + len(train) * 75.0,
                }
                res = algo.predict(vd, threshold=1_000_000)
                if res is None or getattr(res, "predicted_hours", None) in (None, float("inf")):
                    vel = getattr(res, "current_velocity", 0) if res is not None else 0
                    if vel > 0:
                        return float(train[-1]) + vel * (75.0 / 3600.0)
                    return float(train[-1]) * 1.005
                vel = getattr(res, "current_velocity", 0)
                if vel > 0:
                    return float(train[-1]) + vel * (75.0 / 3600.0)
                return float(train[-1]) * 1.01
            except Exception:
                return float(train[-1]) if len(train) > 0 else 0.0

        return fn

    @classmethod
    def _backtest_algorithm_accuracy(
        cls, name: str, algo: BaseAlgorithm, backtester: Any, series: NDArray[Any], np: Any
    ):
        """回测该算法，返回初始 accuracy；不可评估时返回 None（不写权重）。"""
        try:
            # 复刻回测面板的 predict_fn：滚动窗口喂 video_data，取 1 步预测
            result = backtester.backtest(series, cls._make_backtest_predict_fn(algo, np))
            if result.get("n_tests", 0) >= 3 and result["mape"] != float("inf"):
                # MAPE → 初始准确率（0.9 封顶，回测非真实验证，保留学习空间）
                return max(0.3, min(0.9, 1.0 - result["mape"]))
        except Exception as e:
            logger.debug("预热算法 %s 失败: %s", name, e)
        return None

    @classmethod
    def warmup_weights_from_backtest(cls, bvid: str, history: List) -> int:
        """B3: 冷启动加速 —— 用离线滚动回测的 1 步 MAPE 预热算法权重。

        背景：WeightManager.accuracy_records 需真实预测反馈累积，冷启动期所有算法
        weight 恒为 1.0（无差别）。而 RollingBacktester 可离线评估各算法在该视频
        历史数据上的表现 —— 用回测 MAPE 写 1 条初始 accuracy，让 ML 权重立即区分好坏。

        写权重走 **批量接口**：整批只重算一次 ML 权重、只落盘一次
        （原先逐条 ``update_accuracy`` = 40 次全量重算 + 40 次 JSON 写盘）。

        Args:
            bvid: 视频 BV 号
            history: [(timestamp, view_count), ...] 历史数据

        Returns:
            成功预热的算法数量
        """
        try:
            if not bvid or not history or len(history) < 15:
                return 0
            # 每视频只预热一次（启动后历史相对稳定，重复回测浪费 CPU）
            with cls._history_lock:
                warmed: set[str] = getattr(cls, "_backtest_warmed", set())
                cls._backtest_warmed = warmed
                if bvid in warmed:
                    return 0
                warmed.add(bvid)

            import numpy as np
            from algorithms.rollout_backtest import RollingBacktester

            series = np.array([v for _, v in history], dtype=float)
            if len(series) < 15:
                return 0

            backtester = RollingBacktester(min_train=8, step=4, horizon=1)
            pairs: List[Any] = []
            # 限制算法数避免启动过慢（每个算法一次完整回测）
            names = cls.get_algorithm_names()
            sample = names[:40]

            for name in sample:
                algo = cls._algorithms.get(name)
                if algo is None:
                    continue
                acc = cls._backtest_algorithm_accuracy(name, algo, backtester, series, np)
                if acc is not None:
                    pairs.append((name, acc))
            if pairs:
                get_weight_manager().update_accuracy_batch(pairs)
                logger.info("[%s] 回测预热 %d 个算法权重", bvid, len(pairs))
            return len(pairs)
        except Exception as e:
            logger.debug("权重预热失败 %s: %s", bvid, e)
            return 0

    @classmethod
    def prewarm_algorithms(cls, bvid: str) -> int:
        """预热各算法的**首触初始化**（模型加载 / 库一次性初始化），结果丢弃。

        与 ``warmup_weights_from_backtest`` 的区别：**不写权重、不触碰任何全局反馈状态**
        （不调 ``_record_ensemble_feedback`` / bias / conformal / 降频缓存），
        只把「首次 predict 的懒加载」从真实首轮预测挪到启动后台线程。

        适用场景：启动时**尚无监控视频**（不会有预测马上跑）→ 预热不与真实预测抢 CPU，
        用户随后添加视频时首次预测即可命中已加载的模型与已初始化的库。

        Args:
            bvid: 用于 torch 模型按 bvid 缓存的有效 BV 号（无效 BV 会让 torch 走底模，
                  起不到预热效果）

        Returns:
            成功预热的算法数量
        """
        try:
            if not bvid:
                return 0
            base_ts = 1_700_000_000.0
            hist = [{"view_count": 1000.0 + i * 60.0, "timestamp": base_ts + i * 75.0} for i in range(15)]
            vd = {
                "view_count": hist[-1]["view_count"],
                "history_data": hist,
                "_sorted": True,
                "bvid": bvid,
                "derived_features": {},
                "timestamp": base_ts + len(hist) * 75.0,
            }
            warmed = 0
            for name, algo in cls._algorithms.items():
                try:
                    algo.predict(vd, threshold=100000)
                    warmed += 1
                except Exception as e:
                    logger.debug("首触预热跳过 %s: %s", name, e)
            logger.info("算法首触预热完成 %d/%d 个", warmed, len(cls._algorithms))
            return warmed
        except Exception as e:
            logger.debug("算法首触预热失败: %s", e)
            return 0
