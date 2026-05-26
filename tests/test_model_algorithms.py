"""Tests for model algorithms — one per category"""

from datetime import datetime
import pytest


def _make_history(n=15):
    base = datetime(2026, 1, 1, 0, 0, 0)
    return [(datetime.fromtimestamp(base.timestamp() + i * 3600), 1000 + i * 1000) for i in range(n)]


def _make_video_data(history, current_views=15000):
    from datetime import datetime as dt

    history_list = []
    for ts, v in history:
        if hasattr(ts, "timestamp"):
            epoch = ts.timestamp()
        else:
            epoch = float(ts)
        history_list.append(
            {
                "view_count": v,
                "timestamp": epoch,
                "timestamp_str": dt.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S"),
                "datetime": dt.fromtimestamp(epoch),
            }
        )
    return {
        "view_count": current_views,
        "history_data": history_list,
        "timestamp": dt.now(),
        "like_count": current_views // 10,
        "coin_count": current_views // 50,
        "favorite_count": current_views // 20,
        "share_count": current_views // 100,
        "danmaku_count": current_views // 200,
    }


# Algorithms that still use the old 4-arg interface (predict(cv, tv, hd, vi))
# These need to be tested via ModelAlgorithmAdapter
_OLD_INTERFACE = {
    "LogisticGrowthAlgorithm",
    "WeibullGrowthAlgorithm",
    "HoltWintersAlgorithm",
    "SVRPredictorAlgorithm",
    "GaussianProcessAlgorithm",
    "HuberRegressionAlgorithm",
    "MLPPredictorAlgorithm",
    "KalmanFilterAlgorithm",
}


def _via_adapter(module_path, cls_name, video_data, threshold=100000):
    import importlib
    from algorithms.model_adapter import ModelAlgorithmAdapter

    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    algo = ModelAlgorithmAdapter(cls())
    # Build history tuples from video_data
    history = []
    for h in video_data.get("history_data", []):
        dt = h.get("datetime", h.get("timestamp", 0))
        v = h.get("view_count", 0)
        if hasattr(dt, "timestamp"):
            history.append((dt, v))
        else:
            history.append((float(dt), v))
    result = algo.predict_dict(
        history,
        video_data.get("view_count", 0),
        thresholds=[threshold],
        threshold_names=["test"],
        _cached_video_data=video_data,
    )
    # Convert dict result to PredictionResult-like checks
    return result


class TestSimpleCategory:
    def test_linear_velocity(self):
        from algorithms.models.simple.linear_velocity import LinearVelocityAlgorithm

        algo = LinearVelocityAlgorithm()
        video_data = _make_video_data(_make_history(5), 5000)
        result = algo.predict(video_data, 100000)
        assert result.target_threshold == 100000
        assert result.current_views == 5000


class TestGrowthCategory:
    @pytest.mark.parametrize(
        "module_path,cls_name",
        [
            ("algorithms.models.growth.exponential_growth", "ExponentialGrowthAlgorithm"),
            ("algorithms.models.growth.gompertz", "GompertzAlgorithm"),
            ("algorithms.models.growth.logistic_growth", "LogisticGrowthAlgorithm"),
            ("algorithms.models.growth.power_law", "PowerLawAlgorithm"),
            ("algorithms.models.growth.weibull_growth", "WeibullGrowthAlgorithm"),
        ],
    )
    def test_growth_algorithm(self, module_path, cls_name):
        video_data = _make_video_data(_make_history(15), 15000)
        if cls_name in _OLD_INTERFACE:
            result = _via_adapter(module_path, cls_name, video_data)
            assert result.get("prediction", 0) > 0
        else:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            algo = cls()
            result = algo.predict(video_data, 100000)
            assert result.target_threshold == 100000
            assert result.confidence >= 0


class TestTimeSeriesCategory:
    @pytest.mark.parametrize(
        "module_path,cls_name",
        [
            ("algorithms.models.time_series.moving_average", "MovingAverageAlgorithm"),
            ("algorithms.models.time_series.exponential_smoothing", "ExponentialSmoothingAlgorithm"),
            ("algorithms.models.time_series.holt_winters", "HoltWintersAlgorithm"),
            ("algorithms.models.time_series.linear_growth", "LinearGrowthAlgorithm"),
            ("algorithms.models.time_series.trend_regression", "TrendRegressionAlgorithm"),
        ],
    )
    def test_time_series_algorithm(self, module_path, cls_name):
        video_data = _make_video_data(_make_history(20), 20000)
        if cls_name in _OLD_INTERFACE:
            result = _via_adapter(module_path, cls_name, video_data)
            assert result.get("prediction", 0) > 0
        else:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            algo = cls()
            result = algo.predict(video_data, 100000)
            assert result.target_threshold == 100000
            assert result.confidence >= 0


class TestStatisticalCategory:
    @pytest.mark.parametrize(
        "module_path,cls_name",
        [
            ("algorithms.models.statistical.svr_predictor", "SVRPredictorAlgorithm"),
            ("algorithms.models.statistical.gaussian_process", "GaussianProcessAlgorithm"),
            ("algorithms.models.statistical.bayesian_regression", "BayesianRegressionAlgorithm"),
            ("algorithms.models.statistical.huber_regression", "HuberRegressionAlgorithm"),
        ],
    )
    def test_statistical_algorithm(self, module_path, cls_name):
        video_data = _make_video_data(_make_history(20), 20000)
        if cls_name in _OLD_INTERFACE:
            result = _via_adapter(module_path, cls_name, video_data)
            assert result.get("prediction", 0) > 0
        else:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            algo = cls()
            result = algo.predict(video_data, 100000)
            assert result.target_threshold == 100000
            assert result.confidence >= 0


class TestEnsembleCategory:
    @pytest.mark.parametrize(
        "module_path,cls_name",
        [
            ("algorithms.models.ensemble.ensemble_average", "EnsembleAverageAlgorithm"),
            ("algorithms.models.ensemble.ensemble_voting", "EnsembleVotingAlgorithm"),
            ("algorithms.models.ensemble.ensemble_weighted", "EnsembleWeightedAlgorithm"),
            ("algorithms.models.ensemble.weighted_velocity", "WeightedVelocityAlgorithm"),
        ],
    )
    def test_ensemble_algorithm(self, module_path, cls_name):
        video_data = _make_video_data(_make_history(10), 10000)
        if cls_name in _OLD_INTERFACE:
            result = _via_adapter(module_path, cls_name, video_data)
            assert result.get("prediction", 0) > 0
        else:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            algo = cls()
            result = algo.predict(video_data, 100000)
            assert result.target_threshold == 100000
            assert result.confidence >= 0


class TestDeepLearningCategory:
    @pytest.mark.parametrize(
        "module_path,cls_name",
        [
            ("algorithms.models.deep_learning.neural_network_simple", "NeuralNetworkSimpleAlgorithm"),
            ("algorithms.models.deep_learning.mlp_predictor", "MLPPredictorAlgorithm"),
            ("algorithms.models.deep_learning.gru_simple", "GRUSimpleAlgorithm"),
        ],
    )
    def test_dl_algorithm(self, module_path, cls_name):
        video_data = _make_video_data(_make_history(15), 15000)
        if cls_name in _OLD_INTERFACE:
            result = _via_adapter(module_path, cls_name, video_data)
            assert result.get("prediction", 0) > 0
        else:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            algo = cls()
            result = algo.predict(video_data, 100000)
            assert result.target_threshold == 100000


class TestAdvancedCategory:
    @pytest.mark.parametrize(
        "module_path,cls_name",
        [
            ("algorithms.models.advanced.kalman_filter", "KalmanFilterAlgorithm"),
            ("algorithms.models.advanced.quality_score", "QualityScoreAlgorithm"),
            ("algorithms.models.advanced.viral_potential", "ViralPotentialAlgorithm"),
            ("algorithms.models.advanced.engagement_rate", "EngagementRateAlgorithm"),
            ("algorithms.models.advanced.like_momentum", "LikeMomentumAlgorithm"),
            ("algorithms.models.advanced.share_velocity", "ShareVelocityAlgorithm"),
        ],
    )
    def test_advanced_algorithm(self, module_path, cls_name):
        video_data = _make_video_data(_make_history(10), 10000)
        if cls_name in _OLD_INTERFACE:
            result = _via_adapter(module_path, cls_name, video_data)
            assert result.get("prediction", 0) > 0
        else:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            algo = cls()
            result = algo.predict(video_data, 100000)
            assert result.target_threshold == 100000
            assert result.confidence >= 0


class TestEdgeCases:
    def test_empty_history(self):
        from algorithms.models.simple.linear_velocity import LinearVelocityAlgorithm

        algo = LinearVelocityAlgorithm()
        video_data = _make_video_data([], 100)
        result = algo.predict(video_data, 100000)
        assert result.predicted_hours == float("inf") or result.predicted_hours > 0

    def test_already_reached_threshold(self):
        from algorithms.models.simple.linear_velocity import LinearVelocityAlgorithm

        algo = LinearVelocityAlgorithm()
        video_data = _make_video_data(_make_history(5), 200000)
        result = algo.predict(video_data, 100000)
        assert result.predicted_hours == 0

    def test_single_data_point(self):
        from algorithms.models.growth.logarithmic_growth import LogarithmicGrowthAlgorithm

        algo = LogarithmicGrowthAlgorithm()
        video_data = _make_video_data([(datetime(2026, 1, 1, 0, 0, 0), 1000)], 1000)
        result = algo.predict(video_data, 100000)
        assert result.confidence >= 0

    def test_fallback_on_low_data(self):
        from algorithms.registry import AlgorithmRegistry

        history = [(datetime(2026, 1, 1, 0, 0, 0), 100)]
        results = AlgorithmRegistry.predict_all(history, 100, bvid="BV1test_edge")
        weighted = results.get("_weighted", {})
        assert weighted.get("total_algorithms", 0) > 0
        assert weighted.get("prediction", 0) > 0
