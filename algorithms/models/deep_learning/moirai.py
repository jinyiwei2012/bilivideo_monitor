"""
MOIRAI — Salesforce通用时序基础模型（HuggingFace零样本预测）
=============================================================

基于Salesforce 2024年发布的MOIRAI时序基础模型进行B站视频播放量预测。
MOIRAI在大量公开时序数据（10亿+时间点）上预训练，支持任意多变量时序的零样本预测。

核心原理:
    1. 通用预训练：在多个领域（金融、天气、交通、医疗等）的时序数据上预训练
    2. 零样本预测：无需针对特定视频做微调，直接输入历史速度序列
    3. 多步预测：输入过去L个时间步，输出未来H步的预测
    4. 适配层：使用MoiraiForecast包装器处理内部数据格式转换

公开模型：Salesforce/moirai-1.1-R-small（via HuggingFace）

降级链：HF加载 + zero-shot推理 → 历史趋势+季节分解 → velocity兜底

参考论文：
    "MOIRAI: A Unified Approach to Time Series Forecasting" (Salesforce AI Research, 2024)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np

from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.training.hf_loader import get_moirai_model, is_hf_available

logger = logging.getLogger(__name__)

# 尝试导入PyTorch
_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class MoiraiAlgorithm(BaseAlgorithm):
    """MOIRAI基础模型算法

    利用Salesforce预训练的MOIRAI时序基础模型进行零样本预测。
    首次加载模型后缓存以供后续使用，加载失败后降级到numpy实现。
    """

    name = "MOIRAI基础模型"
    algorithm_id = "moirai"
    description = "Salesforce MOIRAI 时序基础模型（HuggingFace 零样本）"
    category = "Transformer模型"
    default_weight = 1.5    # 基础模型权重稍高（预训练优势）

    def __init__(self):
        """初始化MOIRAI算法

        设置模型缓存、加载尝试标记，并检查HuggingFace环境是否可用。
        """
        super().__init__()
        self._cached_model = None      # 缓存已加载的MOIRAI模型
        self._tried_load = False       # 是否已尝试加载模型
        self._available = is_hf_available()  # HuggingFace环境是否可用

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测

        优先使用HuggingFace MOIRAI模型进行零样本推理，
        失败则降级到numpy实现的趋势+季节分解。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = int(video_data.get("view_count", 0))
        if self._available:
            try:
                v, conf, meta = self._torch_predict(video_data)
                return self._make_result(current_views, threshold, v, conf, "moirai_hf", meta)
            except Exception as e:
                # 首次失败记warning，后续整条HF路径关闭，避免日志刷屏
                if not self._tried_load or self._cached_model is not None:
                    logger.warning("[moirai] HF 推理失败，降级: %s", e)
                else:
                    logger.debug("[moirai] HF 路径已禁用，走 numpy: %s", e)
                if self._cached_model is None:
                    self._available = False  # 永久关闭HF路径
        return self._numpy_predict(video_data, current_views, threshold)

    def _torch_predict(self, video_data: Dict[str, Any]) -> Tuple[float, float, Dict]:
        """MOIRAI Torch推理路径

        步骤：
        1. 计算历史速度序列（至少8个点）
        2. 尝试加载/获取缓存的MOIRAI模型
        3. 将速度序列reshape为[1, L, 1]输入模型
        4. 根据不同的uni2ts版本调用对应的推理接口（generate/forecast/forward）
        5. 提取预测均值并返回

        Args:
            video_data: 视频数据字典

        Returns:
            (预测速度, 置信度, 元数据)

        Raises:
            RuntimeError: 数据不足或模型加载失败
        """
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 8:
            raise RuntimeError("MOIRAI 至少需要 8 步历史")
        # 尝试加载模型（仅首次）
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
                # 根据模型类型选择推理方式（兼容不同版本的uni2ts）
                if hasattr(self._cached_model, "generate"):
                    out = self._cached_model.generate(x, max_new_tokens=3)
                elif hasattr(self._cached_model, "forecast"):
                    out = self._cached_model.forecast(x, horizon=3)
                else:
                    # MoiraiModule.forward() 在 uni2ts>=2.0 需要 6 个额外参数
                    # (observed_mask, sample_id, time_id, variate_id, prediction_mask, patch_size)
                    # 使用MoiraiForecast包装器处理内部数据转换
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

                    # 构建辅助输入张量
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

        # 提取预测均值：兼容多种输出格式（Tensor/Distribution/tuple）
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
        """NumPy回退预测：趋势+季节+残差均值的简化基础模型

        模拟时序基础模型的行为：用一阶多项式提取趋势斜率，
        取最近3步均值作为"近期季节性"信号，最终预测=近期均值 + 趋势外推。

        Args:
            video_data: 视频数据字典
            current_views: 当前播放量
            threshold: 目标阈值

        Returns:
            PredictionResult: 预测结果
        """
        history = video_data.get("history_data", [])
        velocities = self._velocity_series(history)
        if len(velocities) < 3:
            v = self.calculate_velocity(video_data)
            return self._make_result(current_views, threshold, v, 0.3, "insufficient_data", {})
        v = np.array(velocities, dtype=np.float32)
        # 简化"基础模型"行为：趋势 + 季节 + 残差均值
        if len(v) >= 4:
            slope = float(np.polyfit(np.arange(len(v)), v, 1)[0])  # 一阶趋势斜率
        else:
            slope = 0.0
        # 简单"季节性"：如果有规律的周期，取最近3步均值
        recent = float(np.mean(v[-3:]))
        predicted = max(0.0, recent + slope * 0.5)  # 趋势外推半步
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
        """从历史记录中计算速度序列

        Args:
            history: 历史数据记录列表

        Returns:
            List[float]: 每秒播放量变化
        """
        vs = []
        for i in range(1, len(history)):
            t0 = history[i - 1].get("timestamp", 0)
            t1 = history[i].get("timestamp", 0)
            if hasattr(t0, "timestamp"):
                t0 = t0.timestamp()
            if hasattr(t1, "timestamp"):
                t1 = t1.timestamp()
            dt = (float(t1) - float(t0)) / 3600.0  # 转换为小时
            if dt <= 0:
                continue
            v0 = float(history[i - 1].get("view_count", 0) or 0)
            v1 = float(history[i].get("view_count", 0) or 0)
            vs.append((v1 - v0) / dt)
        return vs

    def _make_result(self, current_views, threshold, velocity, confidence, reason, extra):
        """构造统一的PredictionResult对象

        Args:
            current_views: 当前播放量
            threshold: 目标阈值
            velocity: 预测速度
            confidence: 置信度 [0, 1]
            reason: 预测来源标识
            extra: 额外元数据字典

        Returns:
            PredictionResult: 标准化的预测结果
        """
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
