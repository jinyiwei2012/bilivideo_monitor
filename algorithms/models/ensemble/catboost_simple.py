"""
CatBoost风格梯度提升
基于有序提升的梯度提升算法简化版
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from algorithms.base import BaseAlgorithm


class CatBoostSimpleAlgorithm(BaseAlgorithm):
    """
    Simplified CatBoost-style Gradient Boosting
    
    使用有序提升策略的梯度提升
    对类别特征友好，减少过拟合
    """
    
    name = "CatBoost风格提升"
    description = "有序提升梯度提升，减少过拟合"
    category = "机器学习"
    
    def __init__(self):
        super().__init__()
        self.n_trees = 20
        self.learning_rate = 0.1
        self.max_depth = 4
        self.trees = []
        
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
            
            # 训练模型
            self._train(X, y)
            
            if current_views >= target_views:
                return (0, 1.0)
            
            # 预测
            last_features = X[-1].reshape(1, -1)
            predicted_growth = self._predict_single(last_features[0])
            
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
            print(f"CatBoost预测失败: {e}")
            return None
    
    def _prepare_data(
        self, 
        history_data: List[Dict[str, Any]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备数据
        
        特征: [播放量, 点赞, 投币, 分享, 评论, 粉丝数, 时间特征]
        """
        X = []
        y = []
        
        for i in range(len(history_data) - 1):
            current = history_data[i]
            next_data = history_data[i + 1]
            
            # 时间特征 (星期几)
            ts = current.get('timestamp', '')
            try:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                day_of_week = dt.weekday() / 7.0
            except:
                day_of_week = 0.5
            
            features = [
                current.get('view', 0) / 10000,
                current.get('like', 0) / 1000,
                current.get('coin', 0) / 100,
                current.get('share', 0) / 100,
                current.get('reply', 0) / 100,
                current.get('follower', 1000) / 10000,
                day_of_week
            ]
            
            growth = next_data.get('view', 0) - current.get('view', 0)
            
            X.append(features)
            y.append(growth)
        
        return np.array(X), np.array(y)
    
    def _train(self, X: np.ndarray, y: np.ndarray):
        """训练梯度提升模型"""
        n_samples = len(X)
        
        # 初始化预测值为均值
        self.base_prediction = np.mean(y)
        predictions = np.full(n_samples, self.base_prediction)
        
        self.trees = []
        
        for _ in range(self.n_trees):
            # 计算残差 (负梯度)
            residuals = y - predictions
            
            # 构建决策树桩 (简化版)
            tree = self._build_tree(X, residuals, depth=0)
            self.trees.append(tree)
            
            # 更新预测
            for i in range(n_samples):
                predictions[i] += self.learning_rate * self._tree_predict(tree, X[i])
    
    def _build_tree(
        self, 
        X: np.ndarray, 
        y: np.ndarray, 
        depth: int
    ) -> Dict:
        """构建决策树 (简化版)"""
        n_samples = len(X)
        
        if n_samples < 2 or depth >= self.max_depth:
            return {'leaf': True, 'value': np.mean(y)}
        
        # 找到最佳分裂
        best_gain = -float('inf')
        best_feature = 0
        best_threshold = 0
        
        n_features = X.shape[1]
        
        for feature in range(n_features):
            values = X[:, feature]
            thresholds = np.percentile(values, [25, 50, 75])
            
            for threshold in thresholds:
                left_mask = values <= threshold
                right_mask = ~left_mask
                
                if np.sum(left_mask) < 2 or np.sum(right_mask) < 2:
                    continue
                
                left_y = y[left_mask]
                right_y = y[right_mask]
                
                # 计算方差减少
                gain = np.var(y) - (
                    np.sum(left_mask) * np.var(left_y) +
                    np.sum(right_mask) * np.var(right_y)
                ) / n_samples
                
                if gain > best_gain:
                    best_gain = gain
                    best_feature = feature
                    best_threshold = threshold
        
        if best_gain <= 0:
            return {'leaf': True, 'value': np.mean(y)}
        
        # 分裂
        left_mask = X[:, best_feature] <= best_threshold
        right_mask = ~left_mask
        
        left_tree = self._build_tree(X[left_mask], y[left_mask], depth + 1)
        right_tree = self._build_tree(X[right_mask], y[right_mask], depth + 1)
        
        return {
            'leaf': False,
            'feature': best_feature,
            'threshold': best_threshold,
            'left': left_tree,
            'right': right_tree
        }
    
    def _tree_predict(self, tree: Dict, x: np.ndarray) -> float:
        """使用树进行预测"""
        if tree['leaf']:
            return tree['value']
        
        if x[tree['feature']] <= tree['threshold']:
            return self._tree_predict(tree['left'], x)
        else:
            return self._tree_predict(tree['right'], x)
    
    def _predict_single(self, x: np.ndarray) -> float:
        """预测单个样本"""
        prediction = self.base_prediction
        
        for tree in self.trees:
            prediction += self.learning_rate * self._tree_predict(tree, x)
        
        return prediction
    
    def _calculate_confidence(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算置信度"""
        n = len(X)
        base_conf = min(0.85, 0.3 + n * 0.02)
        
        # 计算拟合误差
        if n >= 5:
            predictions = np.array([self._predict_single(X[i]) for i in range(n)])
            mape = np.mean(np.abs((y - predictions) / (np.abs(y) + 1)))
            fit_quality = max(0, 1 - mape)
            base_conf = 0.5 * base_conf + 0.5 * fit_quality
        
        return min(0.9, base_conf)
