"""
预测算法模块
包含多种播放量预测算法 + 在线学习 / 因果推断 / 图神经网络
"""

# 算法基类
from .prediction_base import BasePredictionAlgorithm

# 权重管理器
from .weight_manager import WeightManager, weight_manager

# 算法注册器
from .registry import AlgorithmRegistry

# ── 新增高级模块 ──────────────────────────────────

# 在线学习
from .online_learner import OnlineLearner, get_online_learner

# 因果推断
from .causal_inference import CausalAnalyzer, get_causal_analyzer

# 图神经网络
from .graph_neural import VideoGraph, get_video_graph

__all__ = [
    # 基类
    'BasePredictionAlgorithm',

    # 管理器
    'WeightManager',
    'weight_manager',
    'AlgorithmRegistry',

    # 高级模块
    'OnlineLearner',
    'get_online_learner',
    'CausalAnalyzer',
    'get_causal_analyzer',
    'VideoGraph',
    'get_video_graph',
]
