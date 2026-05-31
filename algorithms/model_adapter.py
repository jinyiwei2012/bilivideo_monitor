"""
models 算法适配器

将 models/ 目录下具有不同参数签名的算法统一适配到注册器系统。
核心适配逻辑：
    - 自动检测算法 predict() 方法的参数签名
    - 将 registry 传入的 (history, current_value) 格式转换为
      各算法所需的 video_data dict 格式
    - 解析算法原始返回结果，统一为 registry 所需的 dict 格式
"""

from typing import Dict, List, Tuple, Any
from datetime import datetime
import importlib
import os
import logging

from algorithms.base import PredictionResult

logger = logging.getLogger(__name__)


class ModelAlgorithmAdapter:
    """模型算法适配器 —— 桥接 models/ 中的算法与 AlgorithmRegistry。

    通过反射检测底层算法的 predict() 方法签名，自动适配参数传递方式。
    """

    def __init__(self, algo_instance):
        """包装一个算法实例。

        Args:
            algo_instance: models/ 下某个算法的实例对象
        """
        self.algo = algo_instance
        self.name = getattr(algo_instance, "name", algo_instance.__class__.__name__)
        self.algorithm_id = getattr(algo_instance, "algorithm_id", self.name)
        self.description = getattr(algo_instance, "description", "")
        self.category = getattr(algo_instance, "category", "其他")
        self.default_weight = getattr(algo_instance, "default_weight", 1.0)

        # 检测算法 predict() 方法的参数接口类型
        self._detect_interface()

    def _detect_interface(self):
        """检测算法 predict() 方法的参数签名，确定接口类型。

        类型 1 — "video_data":  predict(video_data, threshold)
        类型 2 — "full_params": predict(current_views, target_views, history_data, video_info)
        类型 3 — "unknown":     其他签名
        """
        import inspect

        sig = inspect.signature(self.algo.predict)
        params = list(sig.parameters.keys())

        if len(params) == 2 and "video_data" in params:
            self.interface_type = "video_data"
        elif len(params) == 4:
            self.interface_type = "full_params"
        else:
            self.interface_type = "unknown"

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """统一预测接口，与 BaseAlgorithm.predict() 签名一致。

        Args:
            video_data: 包含视频所有数据的字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 对象
        """
        try:
            if self.interface_type == "video_data":
                # 直接透传
                return self.algo.predict(video_data, threshold)
            else:
                # 拆解 video_data 为旧接口所需的四个参数
                current_value = video_data.get("view_count", 0)
                history_data = video_data.get("history_data", [])
                history_list = [
                    {
                        "view": d.get("view_count", 0),
                        "view_count": d.get("view_count", 0),
                        "timestamp": d.get("timestamp_str", ""),
                    }
                    for d in history_data
                ]
                return self.algo.predict(current_value, threshold, history_list, video_data)
        except Exception:
            # 预测失败时返回一个"无置信度"的结果
            current_views = video_data.get("view_count", 0)
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=0,
                metadata={"error": True},
                timestamp=datetime.now(),
            )

    def predict_dict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """返回 Dict 格式的预测结果，供 registry 的并行预测流程调用。

        Args:
            history: [(timestamp, view_count), ...]
            current_value: 当前播放量
            **kwargs: 可包含 thresholds, threshold_names, _cached_video_data

        Returns:
            dict: {prediction, confidence, metadata, ...}
        """
        thresholds = kwargs.get("thresholds", [100000, 1000000, 10000000])
        threshold_names = kwargs.get("threshold_names", ["10万", "100万", "1000万"])

        try:
            # 优先使用 registry 缓存的 video_data 以提升性能
            video_data = kwargs.get("_cached_video_data")
            if video_data is None:
                video_data = self._prepare_video_data(history, current_value)

            prediction_result = self.predict(video_data, thresholds[0])
            if prediction_result is None:
                return self._make_na_result(current_value)

            return self._parse_result(prediction_result, current_value, thresholds, threshold_names, history)

        except Exception as e:
            return self._make_error_result(current_value, str(e))

    def _prepare_video_data(self, history: List[Tuple], current_value: float, bvid: str = "") -> Dict:
        """将 (timestamp, view_count) 元组列表统一转为 video_data 字典。"""
        history_list = []
        for ts, v in history:
            if isinstance(ts, datetime):
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                ts_ts = ts.timestamp()
            else:
                try:
                    dt = datetime.fromisoformat(str(ts))
                    ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    ts_ts = dt.timestamp()
                except (ValueError, TypeError):
                    ts_str = str(ts)
                    try:
                        ts_ts = float(ts)
                    except (ValueError, TypeError):
                        ts_ts = datetime.now().timestamp()

            history_list.append(
                {
                    "view_count": v,
                    "timestamp": ts_ts,
                    "timestamp_str": ts_str,
                    "datetime": ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts_ts),
                }
            )

        return {
            "view_count": current_value,
            "history_data": history_list,
            "timestamp": datetime.now(),
            "timestamp_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "bvid": bvid,
        }

    def _parse_result(
        self, result, current_value: float, thresholds: List, threshold_names: List, history: List[Tuple] = None
    ) -> Dict:
        """解析算法原始返回结果，统一为 registry 需要的 dict 格式。

        models 算法原始返回的是「达到阈值所需时间」；
        这里转换为「下一短期窗口的预测播放量」以保持语义一致。

        支持解析两种返回格式：
            1. PredictionResult 对象（含 predicted_hours / confidence / velocity）
            2. (seconds, confidence) 元组
        """
        history_list = []
        if history:
            history_list = [{"view_count": v, "timestamp": t} for t, v in history]

        # 短期预测窗口（秒），与 DEFAULT_INTERVAL（75 秒）对齐
        SHORT_TERM_SECONDS = 75

        # ── 格式 1：PredictionResult 对象 ────────────────
        if hasattr(result, "predicted_hours"):
            pred_hours = result.predicted_hours
            confidence = result.confidence
            velocity = getattr(result, "current_velocity", 0)

            # 统一语义：prediction = 下一周期的预测播放量
            short_hours = SHORT_TERM_SECONDS / 3600.0
            if velocity > 0:
                # 有速度信息：直接用速度推算短期增长
                prediction = current_value + velocity * short_hours
            elif pred_hours == float("inf") or pred_hours < 0:
                prediction = current_value + current_value * 0.01
            else:
                # 用 predicted_hours 反推平均速度，缩放到短期
                if pred_hours > 0:
                    avg_velocity = (
                        (thresholds[0] - current_value) / max(pred_hours, 1) if thresholds[0] > current_value else 0
                    )
                    prediction = current_value + avg_velocity * short_hours
                else:
                    prediction = current_value * 1.01

            # 计算各阈值所需时间
            threshold_preds = []
            for thresh, name in zip(thresholds, threshold_names):
                if thresh > current_value:
                    if velocity > 0:
                        hours_needed = (thresh - current_value) / velocity
                    else:
                        hours_needed = float("inf")

                    if hours_needed != float("inf"):
                        threshold_preds.append(
                            {
                                "threshold": thresh,
                                "name": name,
                                "periods_needed": int(hours_needed),
                                "minutes": hours_needed * 60,
                            }
                        )

            return {
                "prediction": max(prediction, current_value),
                "confidence": min(max(confidence, 0), 1),
                "metadata": {
                    "predicted_hours": pred_hours,
                    "velocity": velocity,
                    "threshold_predictions": threshold_preds,
                    "data_points": len(history_list),
                },
            }

        # ── 格式 2：(seconds, confidence) 元组 ──────────
        elif isinstance(result, tuple) and len(result) == 2:
            seconds, confidence = result
            short_hours = SHORT_TERM_SECONDS / 3600.0

            if seconds is None or seconds == float("inf"):
                prediction = current_value * 1.01
                pred_hours = float("inf")
            else:
                pred_hours = seconds / 3600
                # 用历史数据估算短期速率
                if len(history_list) > 1:
                    dt_hours = (history_list[-1]["timestamp"] - history_list[0]["timestamp"]) / 3600.0
                    if dt_hours > 0:
                        velocity = (current_value - history_list[0]["view_count"]) / dt_hours
                    else:
                        velocity = current_value * 0.01
                else:
                    velocity = current_value * 0.01
                prediction = current_value + velocity * short_hours

            return {
                "prediction": max(prediction, current_value),
                "confidence": min(max(confidence, 0), 1),
                "metadata": {"predicted_hours": pred_hours, "threshold_predictions": []},
            }

        # 无法识别的返回格式，走 NA 兜底
        return self._make_na_result(current_value)

    def _make_na_result(self, current_value: float) -> Dict:
        """返回 N/A（不可用）结果，保守估计 ~1%/h 的增长。"""
        short_hours = 75 / 3600.0
        return {
            "prediction": current_value + current_value * 0.01 * short_hours,
            "confidence": 0.3,
            "metadata": {"na": True, "threshold_predictions": []},
        }

    def _make_error_result(self, current_value: float, error: str) -> Dict:
        """返回错误结果（预测值为当前播放量，置信度为 0）。"""
        return {
            "prediction": current_value,
            "confidence": 0,
            "metadata": {"error": error, "threshold_predictions": []},
        }

    def update_accuracy(self, predicted: float, actual: float):
        """向上游算法对象传递准确率更新。"""
        if hasattr(self.algo, "update_accuracy"):
            self.algo.update_accuracy(predicted, actual)

    def get_accuracy(self) -> float:
        """获取上游算法对象的准确率，默认为 0.5。"""
        if hasattr(self.algo, "get_accuracy"):
            return self.algo.get_accuracy()
        return 0.5

    def set_weight(self, weight: float):
        """设置上游算法对象的权重。"""
        if hasattr(self.algo, "set_weight"):
            self.algo.set_weight(weight)
        self.algo.weight = weight

    @property
    def weight(self):
        return getattr(self.algo, "weight", self.default_weight)

    @weight.setter
    def weight(self, value):
        self.algo.weight = value

    @property
    def build_model(self):
        return getattr(self.algo, "build_model", None)

    def get_info(self) -> Dict:
        """获取算法元信息。"""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "weight": self.weight,
            "accuracy": self.get_accuracy(),
        }


def load_all_model_algorithms() -> List[ModelAlgorithmAdapter]:
    """遍历 models/ 目录树，动态导入并实例化所有算法。

    扫描规则：
        - 仅加载 .py 文件，跳过 __pycache__ 和 _ 开头的文件
        - 仅加载类名以 Algorithm 结尾、且继承 BaseAlgorithm 的类
        - 每个算法实例被包装为 ModelAlgorithmAdapter 返回

    Returns:
        ModelAlgorithmAdapter 列表
    """
    adapters = []

    current_dir = os.path.dirname(__file__)
    models_dir = os.path.join(current_dir, "models")

    if not os.path.exists(models_dir):
        logger.warning("models目录不存在: %s", models_dir)
        return adapters

    # 递归遍历 models 目录下的所有子目录
    for root, dirs, files in os.walk(models_dir):
        # 跳过 __pycache__ 目录
        dirs[:] = [d for d in dirs if d != "__pycache__"]

        for filename in files:
            # 只处理 .py 文件，跳过 __init__.py 等私有文件
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            # 计算相对于 models 的模块路径（如 "simple/linear_velocity"）
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, models_dir)
            module_path = rel_path.replace("\\", "/").replace("/", ".")[:-3]

            try:
                # 动态导入模块
                module = importlib.import_module(f".models.{module_path}", package="algorithms")

                # 在模块中查找算法类
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)

                    # 匹配条件：是类、类名以 Algorithm 结尾、是 BaseAlgorithm 子类
                    if isinstance(attr, type) and attr_name.endswith("Algorithm"):
                        try:
                            base_names = [c.__name__ for c in attr.__mro__]
                            if "BaseAlgorithm" in base_names or "BasePredictionAlgorithm" in base_names:
                                instance = attr()
                                adapter = ModelAlgorithmAdapter(instance)
                                adapters.append(adapter)
                        except Exception as e:
                            logger.debug("忽略异常: %s", e)

            except Exception as e:
                logger.warning("加载算法 %s 失败: %s", module_path, e)

    return adapters
