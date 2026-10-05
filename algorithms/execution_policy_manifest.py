"""137 个注册算法的执行策略清单（穷尽、自洽）。

键 = ``module_path.ClassName``（稳定类身份，非 UI 展示名）。
本清单由 ``tests/test_algorithm_execution_policy.py`` 守卫：
- 137 个注册算法全部命中；
- 无幽灵条目；
- 已知有可变状态/锁的模型不得标为 ``STATELESS_SHARED``。

归置原则：
- ``stateless_shared``：无可变实例状态、纯公式/无缓存计算。
- ``locked_shared``：持可变实例状态（缓存/模型）且已有实例锁保护。
- ``per_video``：需按 BVID 独享实例（当前仅声明，未生效）。
不确定者保守取 ``locked_shared`` 并标注 ``需人工复核``。
"""

from typing import Any, Dict

_STATELESS = "stateless_shared"
_LOCKED = "locked_shared"
_PER_VIDEO = "per_video"


def _entry(strategy: str, reason: str, mutable_fields: str = "", current_lock: str = "") -> Dict[str, Any]:
    return {
        "strategy": strategy,
        "reason": reason,
        "mutable_fields": mutable_fields,
        "current_lock": current_lock,
        "audit_status": "reviewed",
    }


EXECUTION_POLICY_MANIFEST: Dict[str, Dict[str, Any]] = {}


def _register(prefix: str, names: Dict[str, Dict[str, Any]]) -> None:
    for class_name, entry in names.items():
        EXECUTION_POLICY_MANIFEST[f"{prefix}.{class_name}"] = entry


# ── simple：无可变状态的速度/热度公式 ──────────────────────────────
_register(
    "algorithms.models.simple",
    {
        "linear_velocity.LinearVelocityAlgorithm": _entry(_STATELESS, "两点速度公式，无实例可变状态"),
        "short_term_hotness.ShortTermHotnessAlgorithm": _entry(_STATELESS, "短期热度公式，无实例可变状态"),
    },
)

# ── growth：增长曲线公式 ──────────────────────────────────────────
_register(
    "algorithms.models.growth",
    {
        "bass_diffusion.BassDiffusionAlgorithm": _entry(_STATELESS, "Bass 扩散曲线拟合，无实例可变状态"),
        "exponential_growth.ExponentialGrowthAlgorithm": _entry(_STATELESS, "指数增长公式"),
        "gompertz.GompertzAlgorithm": _entry(_STATELESS, "Gompertz 曲线公式"),
        "gompertz_growth.GompertzGrowthAlgorithm": _entry(_STATELESS, "Gompertz 增长公式"),
        "logarithmic_growth.LogarithmicGrowthAlgorithm": _entry(_STATELESS, "对数增长公式"),
        "logistic_growth.LogisticGrowthAlgorithm": _entry(_STATELESS, "Logistic 曲线公式"),
        "power_law.PowerLawAlgorithm": _entry(_STATELESS, "幂律公式"),
        "richards_curve.RichardsCurveAlgorithm": _entry(_STATELESS, "Richards 曲线公式"),
        "weibull_growth.WeibullGrowthAlgorithm": _entry(_STATELESS, "Weibull 增长公式"),
    },
)

# ── statistical：回归/统计拟合（每次新建模型对象，无长期实例状态）────
_register(
    "algorithms.models.statistical",
    {
        "bayesian_regression.BayesianRegressionAlgorithm": _entry(_STATELESS, "回归拟合，模型局部构造"),
        "dtw_knn.DtwKnnAlgorithm": _entry(_STATELESS, "DTW-KNN 局部计算"),
        "elasticnet_regression.ElasticNetRegressionAlgorithm": _entry(_STATELESS, "ElasticNet 局部拟合"),
        "gaussian_process.GaussianProcessAlgorithm": _entry(_STATELESS, "高斯过程局部拟合"),
        "huber_regression.HuberRegressionAlgorithm": _entry(_STATELESS, "Huber 回归局部拟合"),
        "poisson_regression.PoissonRegressionAlgorithm": _entry(_STATELESS, "泊松回归局部拟合"),
        "quantile_regression.QuantileRegressionAlgorithm": _entry(_STATELESS, "分位数回归局部拟合"),
        "random_forest_simple.RandomForestSimpleAlgorithm": _entry(_STATELESS, "随机森林局部拟合"),
        "svr_predictor.SVRPredictorAlgorithm": _entry(_STATELESS, "SVR 局部拟合"),
        "theil_sen_regression.TheilSenRegressionAlgorithm": _entry(_STATELESS, "Theil-Sen 局部拟合"),
        "tsfc_classification.TsfcClassificationAlgorithm": _entry(_STATELESS, "TSFC 分类局部计算"),
        "upcaster_history_bayesian.UpcasterHistoryBayesianAlgorithm": _entry(_STATELESS, "历史贝叶斯局部计算"),
    },
)

# ── ensemble：集成组合（多为局部聚合）─────────────────────────────
_register(
    "algorithms.models.ensemble",
    {
        "adaptive_boosting.AdaBoostAlgorithm": _entry(_STATELESS, "AdaBoost 局部拟合"),
        "bagging_simple.BaggingSimpleAlgorithm": _entry(_STATELESS, "Bagging 局部拟合"),
        "bayesian_averaging.BayesianModelAveragingAlgorithm": _entry(_STATELESS, "贝叶斯平均聚合"),
        "blending_ensemble.BlendingEnsembleAlgorithm": _entry(_STATELESS, "Blending 聚合"),
        "cascade_ensemble.CascadeEnsembleAlgorithm": _entry(_STATELESS, "级联聚合"),
        "catboost_simple.CatBoostSimpleAlgorithm": _entry(_STATELESS, "CatBoost 局部拟合"),
        "coin_boost.CoinBoostAlgorithm": _entry(_STATELESS, "投币加权聚合"),
        "dynamic_ensemble.DynamicEnsembleAlgorithm": _entry(_STATELESS, "动态权重聚合"),
        "ensemble_average.EnsembleAverageAlgorithm": _entry(_STATELESS, "算术平均聚合"),
        "ensemble_stacking.EnsembleStackingAlgorithm": _entry(_STATELESS, "Stacking 聚合"),
        "ensemble_voting.EnsembleVotingAlgorithm": _entry(_STATELESS, "投票聚合"),
        "ensemble_weighted.EnsembleWeightedAlgorithm": _entry(_STATELESS, "加权聚合"),
        "extra_trees_simple.ExtraTreesSimpleAlgorithm": _entry(_STATELESS, "ExtraTrees 局部拟合"),
        "gradient_boost_simple.GradientBoostSimpleAlgorithm": _entry(_STATELESS, "GradientBoost 局部拟合"),
        "lightgbm_simple.LightGBMSimpleAlgorithm": _entry(_STATELESS, "LightGBM 局部拟合"),
        "ngboost_simple.NgboostAlgorithm": _entry(_STATELESS, "NGBoost 局部拟合"),
        "quantile_ensemble.QuantileEnsembleAlgorithm": _entry(_STATELESS, "分位数集成聚合"),
        "residual_correction.ResidualCorrectionAlgorithm": _entry(_STATELESS, "残差修正局部计算"),
        "stacking_ensemble.StackingEnsembleAlgorithm": _entry(_STATELESS, "Stacking 聚合"),
        "tabnet_simple.TabnetSimpleAlgorithm": _entry(_STATELESS, "TabNet 局部拟合"),
        "weighted_velocity.WeightedVelocityAlgorithm": _entry(_STATELESS, "加权速度聚合"),
        "xgboost_simple.XGBoostSimpleAlgorithm": _entry(_STATELESS, "XGBoost 局部拟合"),
    },
)

# ── time_series：经典时序公式/局部拟合 ────────────────────────────
_register(
    "algorithms.models.time_series",
    {
        "arima_simple.ArimaSimpleAlgorithm": _entry(_STATELESS, "ARIMA 局部拟合"),
        "comment_trend.CommentTrendAlgorithm": _entry(_STATELESS, "评论趋势局部计算"),
        "exponential_decay.ExponentialDecayAlgorithm": _entry(_STATELESS, "指数衰减公式"),
        "exponential_smoothing.ExponentialSmoothingAlgorithm": _entry(_STATELESS, "指数平滑局部拟合"),
        "garch_simple.GarchSimpleAlgorithm": _entry(_STATELESS, "GARCH 局部拟合"),
        "holt_winters.HoltWintersAlgorithm": _entry(_STATELESS, "Holt-Winters 局部拟合"),
        "linear_growth.LinearGrowthAlgorithm": _entry(_STATELESS, "线性增长公式"),
        "markov_switching.MarkovSwitchingAlgorithm": _entry(_STATELESS, "马尔可夫切换局部拟合"),
        "moving_average.MovingAverageAlgorithm": _entry(_STATELESS, "移动平均公式"),
        "mstl_decomposition.MstlDecompositionAlgorithm": _entry(_STATELESS, "MSTL 分解局部计算"),
        "multi_seasonal_decomposition.MultiSeasonalDecompositionAlgorithm": _entry(_STATELESS, "多季分解局部计算"),
        "narx_simple.NarxSimpleAlgorithm": _entry(_STATELESS, "NARX 局部拟合"),
        "prophet_simple.ProphetSimpleAlgorithm": _entry(_STATELESS, "Prophet 局部拟合"),
        "sarima_simple.SARIMASimpleAlgorithm": _entry(_STATELESS, "SARIMA 局部拟合"),
        "seasonal_decomposition.SeasonalDecompositionAlgorithm": _entry(_STATELESS, "季节分解局部计算"),
        "tbats_simple.TbatsSimpleAlgorithm": _entry(_STATELESS, "TBATS 局部拟合"),
        "theta_forecast.ThetaForecastAlgorithm": _entry(_STATELESS, "Theta 预测公式"),
        "theta_method.ThetaMethodAlgorithm": _entry(_STATELESS, "Theta 方法公式"),
        "trend_extrapolation.TrendExtrapolationAlgorithm": _entry(_STATELESS, "趋势外推局部计算"),
        "trend_regression.TrendRegressionAlgorithm": _entry(_STATELESS, "趋势回归局部拟合"),
        "weighted_moving_average.WeightedMovingAverageAlgorithm": _entry(_STATELESS, "加权移动平均公式"),
    },
)

# ── advanced：高级分析（局部计算）─────────────────────────────────
_register(
    "algorithms.models.advanced",
    {
        "bass_diffusion.BassDiffusionAlgorithm": _entry(_STATELESS, "Bass 扩散局部拟合"),
        "causal_impact.CausalImpactAlgorithm": _entry(_STATELESS, "因果影响局部计算"),
        "change_point_detection.ChangePointDetectionAlgorithm": _entry(_STATELESS, "变点检测局部计算"),
        "conformal_prediction.ConformalPredictionAlgorithm": _entry(_STATELESS, "保形预测局部计算"),
        "distdf_align.DistdfAlignAlgorithm": _entry(_STATELESS, "分布对齐局部计算"),
        "engagement_rate.EngagementRateAlgorithm": _entry(_STATELESS, "互动率公式"),
        "fourier_wavelet.FourierWaveletAlgorithm": _entry(_STATELESS, "傅里叶小波局部计算"),
        "hawkes_process.HawkesProcessAlgorithm": _entry(_STATELESS, "Hawkes 过程局部拟合"),
        "hierarchical_bayes.HierarchicalBayesAlgorithm": _entry(_STATELESS, "层次贝叶斯局部计算"),
        "kalman_filter.KalmanFilterAlgorithm": _entry(_STATELESS, "卡尔曼滤波局部计算"),
        "lifecycle_modeling.LifecycleModelAlgorithm": _entry(_STATELESS, "生命周期建模局部计算"),
        "like_momentum.LikeMomentumAlgorithm": _entry(_STATELESS, "点赞动量公式"),
        "multi_step_fusion.MultiStepFusionAlgorithm": _entry(_STATELESS, "多步融合局部计算"),
        "multi_task_simple.MultiTaskSimpleAlgorithm": _entry(_STATELESS, "多任务局部计算"),
        "prob_calibration.ProbabilityCalibrationAlgorithm": _entry(_STATELESS, "概率校准局部计算"),
        "quality_score.QualityScoreAlgorithm": _entry(_STATELESS, "质量评分公式"),
        "share_velocity.ShareVelocityAlgorithm": _entry(_STATELESS, "分享速度公式"),
        "sird_model.SirdModelAlgorithm": _entry(_STATELESS, "SIRD 模型局部计算"),
        "survival_analysis.SurvivalAnalysisAlgorithm": _entry(_STATELESS, "生存分析局部计算"),
        "viral_potential.ViralPotentialAlgorithm": _entry(_STATELESS, "病毒潜力公式"),
    },
)

# ── content / event / frequency：局部计算 ─────────────────────────
_register(
    "algorithms.models.content",
    {
        "engagement_decay.EngagementDecayAlgorithm": _entry(_STATELESS, "互动衰减公式"),
        "quality_decay.QualityDecayAlgorithm": _entry(_STATELESS, "质量衰减公式"),
        "virality_score.ViralityScoreAlgorithm": _entry(_STATELESS, "传播评分公式"),
    },
)
_register(
    "algorithms.models.event",
    {
        "anomaly_spike.AnomalySpikeAlgorithm": _entry(_STATELESS, "异常尖峰局部计算"),
        "hot_trend.HotTrendAlgorithm": _entry(_STATELESS, "热点趋势局部计算"),
        "momentum_breakout.MomentumBreakoutAlgorithm": _entry(_STATELESS, "动量突破局部计算"),
    },
)
_register(
    "algorithms.models.frequency",
    {
        "hilbert_huang.HilbertHuangAlgorithm": _entry(_STATELESS, "希尔伯特-黄局部计算"),
        "spectral_residual.SpectralResidualAlgorithm": _entry(_STATELESS, "谱残差局部计算"),
        "wavelet_decomp.WaveletDecompositionAlgorithm": _entry(_STATELESS, "小波分解局部计算"),
    },
)

# ── deep_learning：全部持可变模型/缓存，已有实例锁保护 ─────────────
_DEEP_LEARNING_NAMES = [
    "attention_mechanism.AttentionMechanismAlgorithm",
    "autoformer.AutoformerAlgorithm",
    "bilstm_simple.BiLSTMSimpleAlgorithm",
    "bitcn.BiTCNAlgorithm",
    "chronos_base.ChronosBaseAlgorithm",
    "cnn_lstm_hybrid.CNNLSTMHybridAlgorithm",
    "crossformer.CrossformerAlgorithm",
    "deepar_simple.DeeparSimpleAlgorithm",
    "dlinear_simple.DLinearSimpleAlgorithm",
    "fedformer.FEDformerAlgorithm",
    "film.FiLMAlgorithm",
    "frets.FreTSAlgorithm",
    "gru_simple.GRUSimpleAlgorithm",
    "informer_simple.InformerSimpleAlgorithm",
    "itransformer_simple.ITransformerSimpleAlgorithm",
    "knf.KnfAlgorithm",
    "koopa.KoopaAlgorithm",
    "lag_llama.LagLlamaAlgorithm",
    "lightts.LightTSAlgorithm",
    "lstm_simple.LSTMSimpleAlgorithm",
    "mamba_s6_simple.MambaS6Algorithm",
    "mar_bilstm.MarBilstmAlgorithm",
    "mlp_predictor.MLPPredictorAlgorithm",
    "moirai.MoiraiAlgorithm",
    "n_beats_simple.NBeatsSimpleAlgorithm",
    "neural_network_simple.NeuralNetworkSimpleAlgorithm",
    "nhits.NHitsAlgorithm",
    "nlinear.NLinearAlgorithm",
    "patch_tst_simple.PatchTSTSimpleAlgorithm",
    "scinet_simple.ScinetSimpleAlgorithm",
    "segrnn.SegRNNAlgorithm",
    "tcn_simple.TCNSimpleAlgorithm",
    "tft_simple.TFTSimpleAlgorithm",
    "tide_simple.TideSimpleAlgorithm",
    "time_mixer.TimeMixerAlgorithm",
    "time_moe_simple.TimeMoeSimpleAlgorithm",
    "timesfm_simple.TimesfmSimpleAlgorithm",
    "timess_net_simple.TimesNetSimpleAlgorithm",
    "tsmixer_simple.TsmixerSimpleAlgorithm",
    "wpmixer.WPMixerAlgorithm",
]
_DEEP_LEARNING_ENTRIES = {
    name: _entry(
        _LOCKED,
        "torch 模型持可变权重/缓存，运行时经 _prediction_lock/_gpu_use_lock 保护",
        mutable_fields="_model/_cached_*",
        current_lock="_prediction_lock/_gpu_use_lock",
    )
    for name in _DEEP_LEARNING_NAMES
}
# 这两个算法显式持有自己的 _cache_lock
_DEEP_LEARNING_ENTRIES["cnn_image.CnnImageAlgorithm"] = _entry(
    _LOCKED,
    "持 _cached_model 并已加 _cache_lock",
    mutable_fields="_cached_model/_cached_bvid",
    current_lock="_cache_lock",
)
_DEEP_LEARNING_ENTRIES["diffusion_ts.DiffusionTSAlgorithm"] = _entry(
    _LOCKED,
    "持 _cached_model 并已加 _cache_lock",
    mutable_fields="_cached_model/_cached_bvid/_cached_model_for_training",
    current_lock="_cache_lock",
)
_register("algorithms.models.deep_learning", _DEEP_LEARNING_ENTRIES)
