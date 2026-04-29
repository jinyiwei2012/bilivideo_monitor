"""
自适应提升 (AdaBoost)
通过组合多个弱学习器提高预测精度
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class AdaBoostAlgorithm(BaseAlgorithm):
    """
    Adaptive Boosting for View Prediction
    
    组合多个弱学习器，重点关注难预测样本
    """
    
    name = "自适应提升"
    description = "AdaBoost集成学习，提高预测精度"
    category = "集成学习"
    
    def __init__(self):
        super().__init__()
        self.n_estimators = 15
        self.estimators = []
        self.estimator_weights = []
        
    def predict(
        self,
        current_views: int,
        target_views: int,
        history_data: List[Dict[str, Any]],
        video_info: Dict[str, Any]
    ) -> Optional[Tuple[int, float]]:
        """
        预测到达目标播放量所需时间
        """
        if not history_data or len(history_data) < 10:
            return None
            
        try:
            # 准备数据
            X, y = self._prepare_data(history_data)
            
            if len(X) < 8:
                return None
            
            # 训练AdaBoost
            self._train(X, y)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测
            last_features = X[-1]
            predicted_growth = self._predict_single(last_features)
            
            if predicted_growth <= 0:
                views = [d['view'] for d in history_data]
                predicted_growth = max(1, np.mean([views[i] - views[i-1] 
                                                   for i in range(1, len(views))]))
            
            remaining = target_views - current_views
            days_needed = remaining / predicted_growth
            
            if days_needed < 0 or days_needed > 3650:
                return None
            
            seconds_needed = int(days_needed * 86400)
            confidence = self._calculate_confidence(X, y)
            
            return (seconds_needed, confidence)
            
        except Exception as e:
            print(f"AdaBoost预测失败: {e}")
            return None
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """准备数据"""
        X = []
        y = []
        
        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]
            
            features = [
                current.get('view', 0) / 10000,
                current.get('like', 0) / 1000,
                current.get('coin', 0) / 100,
                current.get('share', 0) / 100,
                current.get('reply', 0) / 100,
                i / 10
            ]
            
            growth = next_data.get('view', 0) - current.get('view', 0)
            
            X.append(features)
            y.append(growth)
        
        return np.array(X), np.array(y)
    
    def _build_stump(
        self, 
        X: np.ndarray, 
        y: np.ndarray, 
        weights: np.ndarray
    ) -> Tuple[Dict, float]:
        """
        构建决策树桩
        
        Returns:
            (树桩, 误差)
        """
        n_samples, n_features = X.shape
        
        best_error = float('inf')
        best_stump = {}
        
        for feature in range(n_features):
            values = X[:, feature]
            thresholds = np.percentile(values, [30, 50, 70])
            
            for threshold in thresholds:
                for polarity in [1, -1]:
                    predictions = np.ones(n_samples) * np.mean(y)
                    mask = values <= threshold
                    
                    if polarity == 1:
                        predictions[mask] = np.mean(y[mask]) if np.sum(mask) > 0 else np.mean(y)
                    else:
                        predictions[~mask] = np.mean(y[~mask]) if np.sum(~mask) > 0 else np.mean(y)
                    
                    error = np.sum(weights * np.abs(y - predictions))
                    
                    if error < best_error:
                        best_error = error
                        best_stump = {
                            'feature': feature,
                            'threshold': threshold,
                            'polarity': polarity,
                            'prediction_left': np.mean(y[mask]) if np.sum(mask) > 0 else np.mean(y),
                            'prediction_right': np.mean(y[~mask]) if np.sum(~mask) > 0 else np.mean(y)
                        }
        
        return best_stump, best_error
    
    def _train(self, X: np.ndarray, y: np.ndarray):
        """训练AdaBoost"""
        n_samples = len(X)
        
        # 初始化样本权重
        weights = np.ones(n_samples) / n_samples
        
        self.estimators = []
        self.estimator_weights = []
        
        for _ in range(self.n_estimators):
            # 构建弱学习器
            stump, error = self._build_stump(X, y, weights)
            
            if error >= 0.5 or error == 0:
                break
            
            # 计算学习器权重
            alpha = 0.5 * np.log((1 - error) / (error + 1e-10))
            
            # 更新样本权重
            predictions = self._stump_predict(stump, X)
            weights *= np.exp(-alpha * np.sign(y - predictions) * np.abs(y - predictions) / 1000)
            weights /= np.sum(weights)
            
            self.estimators.append(stump)
            self.estimator_weights.append(alpha)
    
    def _stump_predict(self, stump: Dict, X: np.ndarray) -> np.ndarray:
        """使用树桩预测"""
        values = X[:, stump['feature']]
        mask = values <= stump['threshold']
        
        predictions = np.zeros(len(X))
        predictions[mask] = stump['prediction_left']
        predictions[~mask] = stump['prediction_right']
        
        return predictions
    
    def _predict_single(self, x: np.ndarray) -> float:
        """预测单个样本"""
        prediction = 0
        total_weight = 0
        
        for stump, weight in zip(self.estimators, self.estimator_weights):
            value = x[stump['feature']]
            if value <= stump['threshold']:
                pred = stump['prediction_left']
            else:
                pred = stump['prediction_right']
            
            prediction += weight * pred
            total_weight += weight
        
        return prediction / total_weight if total_weight > 0 else 0
    
    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算置信度"""
        n = len(X)
        base_conf = min(0.85, 0.3 + n * 0.02)
        
        if n >= 5 and len(self.estimators) > 0:
            predictions = np.array([self._predict_single(X[i]) for i in range(n)])
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        
        return min(0.9, base_conf)
