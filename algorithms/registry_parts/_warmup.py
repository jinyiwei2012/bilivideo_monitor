"""WarmupMixin extracted from algorithms.registry."""

from typing import List

from ._shared import get_weight_manager, logger


class WarmupMixin:
    @classmethod
    def _make_backtest_predict_fn(cls, algo, np):
        def fn(train: np.ndarray) -> float:
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
    def _warmup_algorithm_weight(cls, name, algo, backtester, series, np):
        try:
            # 复刻回测面板的 predict_fn：滚动窗口喂 video_data，取 1 步预测
            result = backtester.backtest(series, cls._make_backtest_predict_fn(algo, np))
            if result.get("n_tests", 0) >= 3 and result["mape"] != float("inf"):
                mape = result["mape"]
                # MAPE → 初始准确率（0.9 封顶，回测非真实验证，保留学习空间）
                init_acc = max(0.3, min(0.9, 1.0 - mape))
                # 用轻量路径写 accuracy（不触发 algo.update_accuracy 内部状态）
                get_weight_manager().update_accuracy(name, init_acc)
                return 1
        except Exception as e:
            logger.debug("预热算法 %s 失败: %s", name, e)
        return 0

    @classmethod
    def warmup_weights_from_backtest(cls, bvid: str, history: List) -> int:
        """B3: 冷启动加速 —— 用离线滚动回测的 1 步 MAPE 预热算法权重。

        背景：WeightManager.accuracy_records 需真实预测反馈累积，冷启动期所有算法
        weight 恒为 1.0（无差别）。而 RollingBacktester 可离线评估各算法在该视频
        历史数据上的表现 —— 用回测 MAPE 写 1 条初始 accuracy，让 ML 权重立即区分好坏。

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
                warmed = getattr(cls, "_backtest_warmed", set())
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
            warmed_count = 0
            # 限制算法数避免启动过慢（每个算法一次完整回测）
            names = cls.get_algorithm_names()
            sample = names[:40]

            for name in sample:
                algo = cls._algorithms.get(name)
                if algo is None:
                    continue
                warmed_count += cls._warmup_algorithm_weight(name, algo, backtester, series, np)
            if warmed_count:
                logger.info("[%s] 回测预热 %d 个算法权重", bvid, warmed_count)
            return warmed_count
        except Exception as e:
            logger.debug("权重预热失败 %s: %s", bvid, e)
            return 0
