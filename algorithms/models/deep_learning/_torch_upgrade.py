"""Compatibility facade for PyTorch model wrappers and prediction runtime."""

from .torch_upgrade.models_sequence import (
    LSTMTorchModel,
    GRUTorchModel,
    BiLSTMTorchModel,
    MLPTorchModel,
    TCNTorchModel,
    CNNLSTMTorchModel,
    AttentionTorchModel,
)
from .torch_upgrade.models_forecasting import (
    DLinearTorchModel,
    NBeatsTorchModel,
    PatchTSTTorchModel,
    InformerTorchModel,
    TFTTorchModel,
    TimessNetTorchModel,
    TIDETorchModel,
    TSMixerTorchModel,
    DeepARTorchModel,
    ChronosTorchModel,
    MambaS6TorchModel,
    ITransformerTorchModel,
    SCINetTorchModel,
    TimesFMTorchModel,
    TimeMoETorchModel,
)
from .torch_upgrade.models_modern import (
    NLinearTorchModel,
    NHiTSTorchModel,
    TimeMixerTorchModel,
    BiTCNTorchModel,
    WPMixerTorchModel,
    KoopaTorchModel,
    SegRNNTorchModel,
)
from .torch_upgrade.models_frequency import (
    FiLMTorchModel,
    FreTSTorchModel,
    AutoformerTorchModel,
    FEDformerTorchModel,
    LightTSTorchModel,
    CrossformerTorchModel,
)
from .torch_upgrade.model_io import (
    _add_derived_features,
    _build_torch_input,
    expand_final_projection,
    load_checkpoint_model,
)
from .torch_upgrade import prediction as _prediction
from .torch_upgrade.context import DEFAULT_HORIZON, DEFAULT_WINDOW, _torch_available
from .torch_upgrade.runtime import release_cached_models


def try_torch_predict(
    algorithm,
    video_data,
    threshold,
    model_cls,
    fallback_fn,
    model_kwargs=None,
    features=None,
    window=DEFAULT_WINDOW,
    horizon=DEFAULT_HORIZON,
):
    """Delegate through the facade while preserving patchable legacy globals."""
    _prediction._torch_available = _torch_available
    _prediction._build_torch_input = _build_torch_input
    return _prediction.try_torch_predict(
        algorithm,
        video_data,
        threshold,
        model_cls,
        fallback_fn,
        model_kwargs,
        features,
        window,
        horizon,
    )


__all__ = [
    "LSTMTorchModel",
    "GRUTorchModel",
    "BiLSTMTorchModel",
    "MLPTorchModel",
    "TCNTorchModel",
    "CNNLSTMTorchModel",
    "AttentionTorchModel",
    "DLinearTorchModel",
    "NBeatsTorchModel",
    "PatchTSTTorchModel",
    "InformerTorchModel",
    "TFTTorchModel",
    "TimessNetTorchModel",
    "TIDETorchModel",
    "TSMixerTorchModel",
    "DeepARTorchModel",
    "ChronosTorchModel",
    "MambaS6TorchModel",
    "ITransformerTorchModel",
    "SCINetTorchModel",
    "TimesFMTorchModel",
    "TimeMoETorchModel",
    "NLinearTorchModel",
    "NHiTSTorchModel",
    "TimeMixerTorchModel",
    "BiTCNTorchModel",
    "WPMixerTorchModel",
    "KoopaTorchModel",
    "SegRNNTorchModel",
    "FiLMTorchModel",
    "FreTSTorchModel",
    "AutoformerTorchModel",
    "FEDformerTorchModel",
    "LightTSTorchModel",
    "CrossformerTorchModel",
    "try_torch_predict",
    "load_checkpoint_model",
    "release_cached_models",
    "expand_final_projection",
    "_add_derived_features",
    "_build_torch_input",
]
