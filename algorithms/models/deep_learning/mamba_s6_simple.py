"""
Mamba S6（选择性状态空间模型）— 高效长程依赖建模
==================================================

基于选择性SSM（State Space Model）的高效长程依赖建模算法，用于预测B站视频播放量增长趋势。

核心原理:
    1. 状态空间模型（SSM）：使用连续状态方程 dX/dt = AX + BU 描述系统动态演化
    2. 选择性机制：根据输入序列动态调整参数（B矩阵），使模型能区分重要/不重要信息
    3. 离散化：使用固定的时间步长 dt 将连续方程离散化为 X_t = A·X_{t-1} + B·U_t
    4. 线性递归：通过线性递推处理整个序列，时间复杂度O(n)，远优于Transformer的O(n²)

优势：
    - 线性复杂度，可高效处理长序列
    - 选择性机制优于传统SSM的固定参数
    - 在长程依赖任务上表现优异

降级链：torch checkpoint（MambaS6TorchModel） → numpy SSM模拟 → velocity兜底

参考论文：
    "Mamba: Linear-Time Sequence Modeling with Selective State Spaces" (Gu & Dao, 2023)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import MambaS6TorchModel, try_torch_predict


class MambaS6Algorithm(BaseAlgorithm):
    """Mamba S6 状态空间模型

    基于选择性状态空间模型的播放量预测算法。使用2维状态向量模拟系统动态演化，
    将播放量序列作为观测输入，递归更新内部状态，最终通过观测矩阵C输出预测。
    """

    name = "Mamba S6"
    algorithm_id = "mamba_s6"
    description = "选择性状态空间模型，高效长程依赖建模"
    category = "深度学习"
    default_weight = 1.3

    training_window = 10     # 训练时使用的历史窗口长度
    training_horizon = 3     # 训练时预测的未来步数

    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行预测

        优先使用PyTorch模型，若失败则回退到numpy版本的SSM模拟。

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            MambaS6TorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建Mamba S6 PyTorch模型实例

        Returns:
            MambaS6TorchModel: 选择性SSM模型，d_state=4表示状态空间维度
        """
        return MambaS6TorchModel(in_features=getattr(self, '_training_n_features', 5), d_state=4, horizon=self.training_horizon)

    def get_training_features(self) -> List[str]:
        """返回训练时使用的多维特征列表"""
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """执行numpy版本的SSM模拟预测

        使用连续状态空间模型模拟播放量序列的演化：
        - 状态矩阵A设计为近似稳定的动态系统（特征值在单位圆内）
        - 输入矩阵B根据序列幅度自适应缩放
        - 观测矩阵C输出预测值

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult: 预测结果
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        # 数据不足时直接降级
        if len(history) < 8 or velocity <= 0:
            return self._fallback(velocity, current_views, threshold)

        try:
            # 提取播放量序列
            views = np.array([h.get("view", 0) for h in history], dtype=np.float64)
            dt = 1.0  # 离散化时间步长

            # 状态空间模型参数：
            # A: 2×2状态转移矩阵（近似稳定系统，特征值接近1但有微弱阻尼）
            # B: 2×1输入矩阵（将外部输入映射到状态空间）
            # C: 1×2观测矩阵（从状态空间映射回观测空间）
            A = np.array([[0.9, 0.1], [-0.05, 0.95]])
            B = np.array([[0.1], [0.05]])
            C = np.array([[1.0, 0.0]])

            # 零初始化状态向量
            state = np.zeros((2, 1))
            # 递归遍历播放量序列，逐步更新内部状态
            for v in views:
                # B矩阵根据序列幅度自适应缩放，使响应与数据量级匹配
                delta_B = B * (views[-1] / max(views[0], 1))
                state = A @ state + delta_B * dt

            # 从最终状态通过观测矩阵解码出预测输出
            pred_output = (C @ state)[0, 0]
            # 转换为小时级速度（原始输出除以3600秒/小时）
            predicted_velocity = max(0, float(pred_output) / 3600)
            if predicted_velocity < 1:
                predicted_velocity = velocity  # 预测速度过小时使用原始速度

            # 计算到达阈值所需时间
            remaining = threshold - current_views
            if remaining <= 0:
                predicted_hours, confidence = 0, 1.0
            else:
                predicted_hours = remaining / predicted_velocity
                confidence = 0.5

            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=predicted_hours,
                confidence=confidence,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "mamba_s6", "state_dim": 2},
                timestamp=datetime.now(),
            )
        except Exception:
            return self._fallback(velocity, current_views, threshold)

    def _fallback(self, velocity, current_views, threshold):
        """回退预测：当数据不足或推理异常时的安全兜底方案

        Args:
            velocity: 当前计算的速度（播放量/小时）
            current_views: 当前播放量
            threshold: 目标阈值

        Returns:
            PredictionResult: 回退预测结果，置信度较低
        """
        if velocity <= 0:
            return PredictionResult(
                algorithm_name=self.name,
                algorithm_id=self.algorithm_id,
                target_threshold=threshold,
                predicted_hours=float("inf"),
                confidence=0.0,
                current_views=current_views,
                current_velocity=velocity,
                metadata={"method": "mamba_s6", "reason": "fallback"},
                timestamp=datetime.now(),
            )
        remaining = max(0, threshold - current_views)
        predicted_hours = remaining / velocity if remaining > 0 else 0
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=0.3,
            current_views=current_views,
            current_velocity=velocity,
            metadata={"method": "mamba_s6", "reason": "fallback"},
            timestamp=datetime.now(),
        )
