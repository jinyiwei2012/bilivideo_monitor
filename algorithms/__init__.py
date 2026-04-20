"""
预测算法模块
包含多种播放量预测算法
"""

# 算法基类
from .prediction_base import BasePredictionAlgorithm

# 权重管理器
from .weight_manager import WeightManager, weight_manager

# 算法注册器
from .registry import AlgorithmRegistry

# 各预测算法
from .linear_growth import LinearGrowthAlgorithm
from .exponential_smoothing import ExponentialSmoothingAlgorithm
from .gompertz import GompertzAlgorithm
from .trend_extrapolation import TrendExtrapolationAlgorithm
from .moving_average import MovingAverageAlgorithm
from .weighted_moving_average import WeightedMovingAverageAlgorithm

__all__ = [
    # 基类
    'BasePredictionAlgorithm',
    
    # 管理器
    'WeightManager',
    'weight_manager',
    'AlgorithmRegistry',
    
    # 算法
    'LinearGrowthAlgorithm',
    'ExponentialSmoothingAlgorithm',
    'GompertzAlgorithm',
    'TrendExtrapolationAlgorithm',
    'MovingAverageAlgorithm',
    'WeightedMovingAverageAlgorithm',
]
