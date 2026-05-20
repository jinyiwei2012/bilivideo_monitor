"""MOIRAI — Salesforce 通用时序基础模型（HuggingFace 零样本预测）

MOIRAI 是 2024 Salesforce 的 Time Series Foundation Model，在大量公开时序数据上预训练，
支持任意多变量时序的零样本预测（无需视频侧训练）。

公开模型：Salesforce/moirai-1.1-R-small

降级链：HF 加载 + zero-shot → 历史均值 + 趋势外推 → velocity 兜底
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.training.hf_loader import get_moirai_model, is_hf_available

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class MoiraiAlgorithm(BaseAlgorithm):
    name = "MOIRAI基础模型"
    algorithm_id = "moirai"
    description = "Salesforce MOIRAI 时序基础模型（HuggingFace 零样本）"
    category = "Transformer模型"
    default_weight = 1.5  # 基础模型权重稍高

    def __init__(self):
        super().__init__()
        self._cached_model = None
        self._tried_load = False
        self._available = is_hf_available()

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        current_views = int(video_data.get("view_count", 0))
        if self._available:
            try:
                v, conf, meta = self._torch_predict(video_data)
                return self._make_result(current_views, threshold, v, conf, "moirai_hf", meta)
            except Exception as e:
                # 首次失败记 warning，后续整条 HF 路径关闭，避免日志刷屏
                if not self._tried_load or self._cached_model is not None:
                    logger.warning("[moirai] HF 推理失败，降级: %s", e)
                else:
                    logger.debug("[moirai] HF 路径已禁用，走 numpy: %s", e)
                if self._cached_model is None:
                    self._available = False
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 8:
            raise RuntimeError("MOIRAI 至少需要 8 步历史")
        if self._cached_model is None and not self._tried_load:
            self._tried_load = True
            model, ok, reason = get_moirai_model()
            if not ok:
                raise RuntimeError(f"模型加载失败: {reason}")
            self._cached_model = model
        if self._cached_model is None:
            raise RuntimeError("MOIRAI 模型不可用")

        x = torch.tensor(velocities, dtype=torch.float32).reshape(1, -1, 1)  # [1, L, 1]
        try:
            with torch.no_grad():
                if hasattr(self._cached_model, "generate"):
                    out = self._cached_model.generate(x, max_new_tokens=3)
                elif hasattr(self._cached_model, "forecast"):
                    out = self._cached_model.forecast(x, horizon=3)
                else:
                    # MoiraiModule.forward() 在 uni2ts>=2.0 需要 6 个额外参数
                    # (observed_mask, sample_id, time_id, variate_id, prediction_mask, patch_size)
                    # 用 MoiraiForecast 包装器处理内部数据转换
                    from uni2ts.model.moirai import MoiraiForecast

                    context_length = x.shape[1]
                    prediction_length = 3

                    forecast_model = MoiraiForecast(
                        prediction_length=prediction_length,
                        target_dim=1,
                        feat_dynamic_real_dim=0,
                        past_feat_dynamic_real_dim=0,
                        context_length=context_length,
                        module=self._cached_model,
                        patch_size=8,
                    )
                    forecast_model.eval()

                    past_observed_target = torch.ones_like(x, dtype=torch.bool)
                    past_is_pad = torch.zeros(1, context_length, dtype=torch.bool)

                    out = forecast_model(
                        past_target=x,
                        past_observed_target=past_observed_target,
                        past_is_pad=past_is_pad,
                    )
                    # out: [1, num_samples, prediction_length, 1]
        except Exception as e:
            raise RuntimeError(f"MOIRAI forward 异常: {e}")

        # 提取预测均值
        if isinstance(out, torch.Tensor):
            if out.ndim >= 3:
                # MoiraiForecast: [batch, num_samples, pred_len, dim] → mean over samples
                pred_arr = out.mean(dim=1).detach().cpu().numpy().reshape(-1)
            else:
                pred_arr = out.detach().cpu().numpy().reshape(-1)
        elif hasattr(out, "mean") and not callable(out.mean):
            # Distribution.mean property
            pred_arr = out.mean.detach().cpu().numpy().reshape(-1)
        elif isinstance(out, (tuple, list)):
            pred_arr = torch.as_tensor(out[0]).detach().cpu().numpy().reshape(-1)
        else:
            pred_arr = torch.as_tensor(out).detach().cpu().numpy().reshape(-1)
        predicted = max(0.0, float(pred_arr[0]))
        return predicted, 0.8, {"horizon_pred": pred_arr.tolist(), "method": "moirai_zeroshot"}

    def _numpy_predict(self, video_data, current_views, threshold) -> PredictionResult:
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 3:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})
        v = np.array(velocities, dtype=np.float32)
        # 简化"基础模型"行为：趋势 + 季节 + 残差均值
        if len(v) >= 4:
            slope = float(np.polyfit(np.arange(len(v)), v, 1)[0])
        else:
            slope = 0.0
        # 简单"季节性"：如果有规律的周期，取最近 1/2/3 步均值
        recent = float(np.mean(v[-3:]))
        predicted = max(0.0, recent + slope * 0.5)
        return self._make_result(
            current_views,
            threshold,
            predicted,
            0.5,
            "moirai_numpy_fallback",
            {"slope": slope, "recent_mean": recent, "method": "trend_plus_recent"},
        )

    @staticmethod
    def _velocity_series(history: List[Dict]) -> List[float]:
        vs = []
        for i in range(1, len(history)):
            t0 = history[i - 1].get("timestamp", 0)
            t1 = history[i].get("timestamp", 0)
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            dt = (float(t1) - float(t0)) / 3600.0
            if dt <= 0:
                continue
            v0 = float(history[i - 1].get("view_count", 0) or 0)
            v1 = float(history[i].get("view_count", 0) or 0)
            vs.append((v1 - v0) / dt)
        return vs

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        if velocity <= 0:
            predicted_hours = float("inf")
            confidence = 0.0
        else:
            remaining = threshold - current_views
            predicted_hours = 0 if remaining <= 0 else remaining / velocity
            if remaining <= 0:
                confidence = 1.0
        metadata = {"reason": reason}
        metadata.update(extra or {})
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
