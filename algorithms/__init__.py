"""
预测算法模块

包含多种播放量预测算法、在线学习（Hedge 算法权重调节）、
因果推断（Granger 检验）、图神经网络（视频关联关系建模）
以及保形预测（分布无关预测区间）等高级子模块。
"""

# 算法基类 —— 所有预测算法的抽象接口
from .base import BaseAlgorithm

# 权重管理器 —— ML 驱动的算法权重自动调节
from .weight_manager import WeightManager, get_weight_manager

# 算法注册器 —— 自动扫描并注册 models/ 目录下的所有算法
from .registry import AlgorithmRegistry

# ── 新增高级模块 ──────────────────────────────────

# 在线学习 —— 基于 Hedge 算法的指数权重专家混合
from .online_learner import OnlineLearner, get_online_learner

# 因果推断 —— Granger 因果检验 + 滑动窗口相关分析
from .causal_inference import CausalAnalyzer, get_causal_analyzer

# 图神经网络 —— 构建视频关联图并计算图嵌入特征
from .graph_neural import VideoGraph, get_video_graph

# 保形预测 —— 提供有覆盖率保证的预测区间
from .conformal import ConformalPredictor, get_conformal_predictor

__all__ = [
    # 基类
    "BaseAlgorithm",
    # 管理器
    "WeightManager",
    "get_weight_manager",
    "AlgorithmRegistry",
    # 高级模块
    "OnlineLearner",
    "get_online_learner",
    "CausalAnalyzer",
    "get_causal_analyzer",
    "VideoGraph",
    "get_video_graph",
]
