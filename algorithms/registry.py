"""
算法注册器
管理所有预测算法（包含models目录下的算法）
"""
from typing import Dict, List, Optional
import os
import importlib


class AlgorithmRegistry:
    """算法注册器"""
    
    _algorithms: Dict = {}
    _initialized = False
    _model_adapters = {}
    
    @classmethod
    def initialize(cls):
        """初始化注册所有算法"""
        if cls._initialized:
            return
        
        # 加载基础目录下的算法
        cls._load_base_algorithms()
        
        # 加载models目录下的所有算法
        cls._load_model_algorithms()
        
        cls._initialized = True
        print(f"算法注册完成，共 {len(cls._algorithms)} 个算法")
    
    @classmethod
    def _load_base_algorithms(cls):
        """加载基础算法"""
        try:
            from .prediction_base import BasePredictionAlgorithm
            from .linear_growth import LinearGrowthAlgorithm
            from .exponential_smoothing import ExponentialSmoothingAlgorithm
            from .gompertz import GompertzAlgorithm
            from .trend_extrapolation import TrendExtrapolationAlgorithm
            from .moving_average import MovingAverageAlgorithm
            from .weighted_moving_average import WeightedMovingAverageAlgorithm
            
            algorithms = [
                LinearGrowthAlgorithm(),
                ExponentialSmoothingAlgorithm(),
                GompertzAlgorithm(),
                TrendExtrapolationAlgorithm(),
                MovingAverageAlgorithm(),
                WeightedMovingAverageAlgorithm(),
            ]
            
            for algo in algorithms:
                cls._algorithms[algo.name] = algo
        except Exception as e:
            print(f"加载基础算法失败: {e}")
    
    @classmethod
    def _load_model_algorithms(cls):
        """加载models目录下的所有算法"""
        try:
            from .model_adapter import load_all_model_algorithms
            
            adapters = load_all_model_algorithms()
            
            for adapter in adapters:
                algo_name = f"[Model] {adapter.name}"
                cls._algorithms[algo_name] = adapter
                cls._model_adapters[algo_name] = adapter
                
        except Exception as e:
            print(f"加载models算法失败: {e}")
            import traceback
            traceback.print_exc()
    
    @classmethod
    def get_algorithm(cls, name: str):
        if not cls._initialized:
            cls.initialize()
        return cls._algorithms.get(name)
    
    @classmethod
    def get_all_algorithms(cls):
        if not cls._initialized:
            cls.initialize()
        return list(cls._algorithms.values())
    
    @classmethod
    def get_algorithm_names(cls) -> List[str]:
        if not cls._initialized:
            cls.initialize()
        return list(cls._algorithms.keys())
    
    @classmethod
    def predict_all(cls, history: List, current_value: float, **kwargs) -> Dict:
        if not cls._initialized:
            cls.initialize()
        
        try:
            from .weight_manager import weight_manager
        except ImportError:
            weight_manager = None
        
        results = {}
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        valid_count = 0
        na_count = 0
        
        for name, algo in cls._algorithms.items():
            try:
                result = algo.predict(history, current_value, 
                                     thresholds=thresholds, 
                                     threshold_names=threshold_names)
                
                if weight_manager:
                    weight = weight_manager.get_weight(name)
                else:
                    weight = getattr(algo, 'weight', 1.0)
                
                results[name] = {
                    'prediction': result['prediction'],
                    'confidence': result['confidence'],
                    'weight': weight,
                    'metadata': result['metadata']
                }
                
                if result.get('metadata', {}).get('na') or result['confidence'] == 0:
                    na_count += 1
                else:
                    valid_count += 1
                    
            except Exception as e:
                print(f"算法 {name} 预测失败: {e}")
                results[name] = {
                    'prediction': current_value,
                    'confidence': 0,
                    'weight': 0.01,
                    'error': str(e)
                }
        
        valid_predictions = [(name, r['prediction'], r['weight']) 
                           for name, r in results.items() 
                           if r['weight'] > 0 and r['prediction'] > 0]
        
        if valid_predictions:
            total_weight = sum(w for _, _, w in valid_predictions)
            if total_weight > 0:
                weighted_pred = sum(p * w for _, p, w in valid_predictions) / total_weight
            else:
                weighted_pred = current_value
        else:
            weighted_pred = current_value
        
        results['_weighted'] = {
            'prediction': weighted_pred,
            'total_algorithms': len(results),
            'valid_algorithms': valid_count,
            'na_algorithms': na_count
        }
        
        return results
    
    @classmethod
    def update_accuracy(cls, algorithm_name: str, predicted: float, actual: float):
        algo = cls.get_algorithm(algorithm_name)
        if algo:
            if hasattr(algo, 'update_accuracy'):
                algo.update_accuracy(predicted, actual)
            try:
                from .weight_manager import weight_manager
                accuracy = algo.get_accuracy() if hasattr(algo, 'get_accuracy') else 0.5
                weight_manager.update_accuracy(algorithm_name, accuracy)
            except ImportError:
                pass
    
    @classmethod
    def get_weights_info(cls) -> List[Dict]:
        if not cls._initialized:
            cls.initialize()
        
        names = cls.get_algorithm_names()
        
        try:
            from .weight_manager import weight_manager
            return weight_manager.get_algorithm_info(names)
        except ImportError:
            return [{'name': n, 'accuracy': 0.5, 'weight': 1.0} for n in names]
    
    @classmethod
    def reset(cls):
        cls._algorithms = {}
        cls._model_adapters = {}
        cls._initialized = False


AlgorithmRegistry.initialize()
