"""
算法管理器
负责加载、注册和管理所有预测算法
"""

import os
import sys
import importlib
import inspect
from typing import Dict, List, Type, Optional, Any
from pathlib import Path

from .base import BaseAlgorithm


class AlgorithmManager:
    """算法管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.algorithms: Dict[str, BaseAlgorithm] = {}
        self.algorithm_classes: Dict[str, Type[BaseAlgorithm]] = {}
        self._initialized = True
        
        # 自动加载所有算法
        self._load_all_algorithms()
    
    def _load_all_algorithms(self):
        """加载所有算法模块（包括子目录）"""
        models_dir = Path(__file__).parent / "models"
        
        if not models_dir.exists():
            print(f"算法模型目录不存在: {models_dir}")
            return
        
        # 递归查找所有Python文件（包括子目录）
        model_files = []
        for subdir in models_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("_"):
                # 扫描子目录中的所有 .py 文件
                model_files.extend(subdir.glob("*.py"))
        
        # 也加载 models 根目录下的算法（如果有）
        model_files.extend([f for f in models_dir.glob("*.py") if not f.name.startswith("_")])
        
        for model_file in model_files:
            try:
                self._load_algorithm_from_file(model_file)
            except Exception as e:
                print(f"加载算法文件失败 {model_file.name}: {e}")
    
    def _load_algorithm_from_file(self, file_path: Path):
        """从文件加载算法"""
        module_name = f"algorithms.models.{file_path.stem}"
        
        try:
            # 导入模块
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            
            # 查找算法类
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, BaseAlgorithm) and 
                    obj is not BaseAlgorithm and
                    hasattr(obj, 'name')):
                    
                    # 实例化算法
                    algorithm = obj()
                    algorithm_id = file_path.stem
                    
                    self.algorithms[algorithm_id] = algorithm
                    self.algorithm_classes[algorithm_id] = obj
                    
        except Exception as e:
            print(f"加载算法失败 {file_path.name}: {e}")
    
    def get_algorithm(self, algorithm_id: str) -> Optional[BaseAlgorithm]:
        """获取算法实例"""
        return self.algorithms.get(algorithm_id)
    
    def get_all_algorithms(self) -> Dict[str, BaseAlgorithm]:
        """获取所有算法"""
        return self.algorithms.copy()
    
    def get_algorithm_info(self) -> List[Dict[str, Any]]:
        """获取所有算法信息"""
        info = []
        for alg_id, algorithm in self.algorithms.items():
            info.append({
                'id': alg_id,
                'name': algorithm.name,
                'description': algorithm.description,
                'category': algorithm.category
            })
        return info
    
    def get_algorithms_by_category(self, category: str) -> Dict[str, BaseAlgorithm]:
        """按类别获取算法"""
        return {
            k: v for k, v in self.algorithms.items()
            if v.category == category
        }
    
    def get_categories(self) -> List[str]:
        """获取所有类别"""
        categories = set()
        for algorithm in self.algorithms.values():
            categories.add(algorithm.category)
        return sorted(list(categories))
    
    def count(self) -> int:
        """获取算法数量"""
        return len(self.algorithms)


# 全局算法管理器实例
algorithm_manager = AlgorithmManager()
