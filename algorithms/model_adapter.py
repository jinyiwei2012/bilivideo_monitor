"""
models算法适配器
将不同接口的models算法统一适配到注册器系统
"""
from typing import Dict, List, Tuple, Any
from datetime import datetime
import importlib
import os


class ModelAlgorithmAdapter:
    """模型算法适配器"""
    
    def __init__(self, algo_instance):
        self.algo = algo_instance
        self.name = getattr(algo_instance, 'name', algo_instance.__class__.__name__)
        self.algorithm_id = getattr(algo_instance, 'algorithm_id', self.name)
        self.description = getattr(algo_instance, 'description', '')
        self.category = getattr(algo_instance, 'category', '其他')
        self.default_weight = getattr(algo_instance, 'default_weight', 1.0)
        
        # 检查算法接口类型
        self._detect_interface()
    
    def _detect_interface(self):
        """检测算法接口类型"""
        import inspect
        sig = inspect.signature(self.algo.predict)
        params = list(sig.parameters.keys())
        
        # 类型1: predict(video_data, threshold)
        if len(params) == 2 and 'video_data' in params:
            self.interface_type = 'video_data'
        # 类型2: predict(current_views, target_views, history_data, video_info)
        elif len(params) == 4:
            self.interface_type = 'full_params'
        else:
            self.interface_type = 'unknown'
    
    def predict(self, history: List[Tuple], current_value: float, **kwargs) -> Dict:
        """统一预测接口"""
        thresholds = kwargs.get('thresholds', [100000, 1000000, 10000000])
        threshold_names = kwargs.get('threshold_names', ['10万', '100万', '1000万'])
        
        try:
            # 准备video_data格式
            video_data = self._prepare_video_data(history, current_value)
            
            # 根据接口类型调用
            if self.interface_type == 'video_data':
                result = self.algo.predict(video_data, thresholds[0])
            else:
                # full_params接口，需要转换数据格式
                history_data = []
                for t, v in history:
                    if isinstance(t, datetime):
                        ts_str = t.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        ts_str = str(t)
                    history_data.append({
                        'view': v,
                        'view_count': v,
                        'timestamp': ts_str  # 必须是字符串格式
                    })
                
                result = self.algo.predict(
                    current_value, 
                    thresholds[0], 
                    history_data,
                    video_data
                )
            
            # 解析结果
            if result is None:
                return self._make_na_result(current_value)
            
            return self._parse_result(result, current_value, thresholds, threshold_names)
            
        except Exception as e:
            return self._make_error_result(current_value, str(e))
    
    def _prepare_video_data(self, history: List[Tuple], current_value: float) -> Dict:
        """准备video_data"""
        history_list = []
        for ts, v in history:
            if isinstance(ts, datetime):
                # 转换为字符串格式供某些算法使用
                ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
                ts_ts = ts.timestamp()
            else:
                ts_str = str(ts)
                ts_ts = float(ts)
            
            history_list.append({
                'view_count': v,
                'timestamp': ts_ts,
                'timestamp_str': ts_str,  # 添加字符串格式
                'datetime': ts if isinstance(ts, datetime) else datetime.fromtimestamp(float(ts))
            })
        
        return {
            'view_count': current_value,
            'history_data': history_list,
            'timestamp': datetime.now(),
            'timestamp_str': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def _parse_result(self, result, current_value: float, 
                     thresholds: List, threshold_names: List) -> Dict:
        """解析预测结果
        
        models 算法原始返回的是「达到阈值所需时间」，
        但为了和基础算法的 prediction 语义一致（下一周期播放量），
        这里统一转换为基于当前速率的短期预测值。
        """
        history_list = []
        
        # 短期预测窗口（秒），与 DEFAULT_INTERVAL(75s) 对齐
        SHORT_TERM_SECONDS = 75
        
        # PredictionResult对象
        if hasattr(result, 'predicted_hours'):
            pred_hours = result.predicted_hours
            confidence = result.confidence
            velocity = getattr(result, 'current_velocity', 0)
            
            # 统一语义：prediction = 下一周期的预测播放量
            # velocity 单位是 播放量/小时，短期窗口 = 75秒
            short_hours = SHORT_TERM_SECONDS / 3600.0
            if velocity > 0:
                prediction = current_value + velocity * short_hours
            elif pred_hours == float('inf') or pred_hours < 0:
                prediction = current_value * 1.01
            else:
                # 无速度信息，用 predicted_hours 反推一个短期估算
                if pred_hours > 0:
                    # 用预测的总增长量按比例缩放到短期
                    avg_velocity = (thresholds[0] - current_value) / max(pred_hours, 1) if thresholds[0] > current_value else 0
                    prediction = current_value + avg_velocity * short_hours
                else:
                    prediction = current_value * 1.01
            
            threshold_preds = []
            for thresh, name in zip(thresholds, threshold_names):
                if thresh > current_value:
                    if velocity > 0:
                        hours_needed = (thresh - current_value) / velocity
                    else:
                        hours_needed = float('inf')
                    
                    if hours_needed != float('inf'):
                        threshold_preds.append({
                            'threshold': thresh,
                            'name': name,
                            'periods_needed': int(hours_needed),
                            'minutes': hours_needed * 60
                        })
            
            return {
                'prediction': max(prediction, current_value),
                'confidence': min(max(confidence, 0), 1),
                'metadata': {
                    'predicted_hours': pred_hours,
                    'velocity': velocity,
                    'threshold_predictions': threshold_preds,
                    'data_points': len(history_list)
                }
            }
        
        # 元组格式 (seconds, confidence)
        elif isinstance(result, tuple) and len(result) == 2:
            seconds, confidence = result
            short_hours = SHORT_TERM_SECONDS / 3600.0
            
            if seconds is None or seconds == float('inf'):
                prediction = current_value * 1.01
                pred_hours = float('inf')
            else:
                pred_hours = seconds / 3600
                # 用历史数据估算短期速率
                if len(history_list) > 1:
                    velocity = (current_value - history_list[0]['view_count']) / max(len(history_list) - 1, 1)
                else:
                    velocity = current_value * 0.01
                # 统一语义：短期预测
                prediction = current_value + velocity * short_hours
            
            return {
                'prediction': max(prediction, current_value),
                'confidence': min(max(confidence, 0), 1),
                'metadata': {
                    'predicted_hours': pred_hours,
                    'threshold_predictions': []
                }
            }
        
        return self._make_na_result(current_value)
    
    def _make_na_result(self, current_value: float) -> Dict:
        """返回N/A结果"""
        short_hours = 75 / 3600.0  # 75秒，与 DEFAULT_INTERVAL 一致
        return {
            'prediction': current_value + current_value * 0.01 * short_hours,  # ~1%/h 的保守估计
            'confidence': 0.3,
            'metadata': {
                'na': True,
                'threshold_predictions': []
            }
        }
    
    def _make_error_result(self, current_value: float, error: str) -> Dict:
        """返回错误结果"""
        return {
            'prediction': current_value,  # 错误时不做预测
            'confidence': 0,
            'metadata': {
                'error': error,
                'threshold_predictions': []
            }
        }
    
    def update_accuracy(self, predicted: float, actual: float):
        """更新准确率"""
        if hasattr(self.algo, 'update_accuracy'):
            self.algo.update_accuracy(predicted, actual)
    
    def get_accuracy(self) -> float:
        """获取准确率"""
        if hasattr(self.algo, 'get_accuracy'):
            return self.algo.get_accuracy()
        return 0.5
    
    def set_weight(self, weight: float):
        """设置权重"""
        if hasattr(self.algo, 'set_weight'):
            self.algo.set_weight(weight)
        self.algo.weight = weight
    
    @property
    def weight(self):
        return getattr(self.algo, 'weight', self.default_weight)
    
    @weight.setter
    def weight(self, value):
        self.algo.weight = value
    
    def get_info(self) -> Dict:
        """获取算法信息"""
        return {
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'weight': self.weight,
            'accuracy': self.get_accuracy(),
        }


def load_all_model_algorithms() -> List[ModelAlgorithmAdapter]:
    """加载所有models目录下的算法（包括子目录）"""
    adapters = []
    
    # 确保是models目录
    current_dir = os.path.dirname(__file__)
    models_dir = os.path.join(current_dir, 'models')
    
    if not os.path.exists(models_dir):
        print(f"models目录不存在: {models_dir}")
        return adapters
    
    # 递归遍历models目录下的所有子目录
    for root, dirs, files in os.walk(models_dir):
        # 跳过 __pycache__ 目录
        dirs[:] = [d for d in dirs if d != '__pycache__']
        
        for filename in files:
            if not filename.endswith('.py') or filename.startswith('_'):
                continue
            
            # 计算相对路径，用于构建模块路径
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, models_dir)
            module_path = rel_path.replace('\\', '/').replace('/', '.')[:-3]  # 移除.py
            
            try:
                # 动态导入模块
                module = importlib.import_module(f'.models.{module_path}', package='algorithms')
                
                # 查找算法类
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    
                    # 是类且是BaseAlgorithm的子类
                    if (isinstance(attr, type) and 
                        attr_name.endswith('Algorithm')):
                        
                        try:
                            base_names = [b.__name__ for b in attr.__bases__]
                            if 'BaseAlgorithm' in base_names:
                                instance = attr()
                                adapter = ModelAlgorithmAdapter(instance)
                                adapters.append(adapter)
                        except Exception as e:
                            pass
                            
            except Exception as e:
                print(f"加载算法 {module_path} 失败: {e}")
    
    return adapters
