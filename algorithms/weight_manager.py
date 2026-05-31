"""
权重管理器
使用机器学习自动调整算法权重
"""

import os
import json
import math
import threading
import logging
from typing import Dict, List
from datetime import datetime
from utils import project_path

logger = logging.getLogger(__name__)


class WeightManager:
    """权重管理器"""

    def __init__(self, save_dir: str = None):
        if save_dir is None:
            save_dir = project_path("algorithms", "weights")

        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

        # 线程锁，保护并发读写
        self._lock = threading.Lock()

        # 用户自定义权重（优先级最高）
        self.user_weights: Dict[str, float] = {}

        # 机器学习计算的权重
        self.ml_weights: Dict[str, float] = {}

        # 算法准确率记录
        self.accuracy_records: Dict[str, List[float]] = {}

        # 加载已有权重
        self._load_weights()

    def _get_weights_file(self, bvid: str = None) -> str:
        """获取权重文件路径"""
        if bvid:
            return os.path.join(self.save_dir, f"{bvid}_weights.json")
        return os.path.join(self.save_dir, "default_weights.json")

    def _load_weights(self):
        """加载权重"""
        # 加载默认权重
        default_file = self._get_weights_file()
        if os.path.exists(default_file):
            try:
                with open(default_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.user_weights = data.get("user_weights", {})
                    self.ml_weights = data.get("ml_weights", {})
                    self.accuracy_records = data.get("accuracy_records", {})
            except Exception as e:
                logger.warning("加载权重失败: %s", e)

    def _save_weights_sync(self, bvid: str = None):
        """同步保存权重到文件"""
        try:
            data = {
                "user_weights": dict(self.user_weights),
                "ml_weights": dict(self.ml_weights),
                "accuracy_records": {k: list(v) for k, v in self.accuracy_records.items()},
                "updated_at": datetime.now().isoformat(),
            }
            self._write_weights_file(data, bvid)
        except Exception as e:
            logger.warning("调度异步保存权重失败: %s", e)

    @staticmethod
    def _write_weights_file(data: dict, bvid: str = None):
        """在后台线程中执行实际文件写入"""
        try:
            from utils import project_path

            if bvid:
                fpath = os.path.join(project_path("algorithms", "weights"), f"{bvid}_weights.json")
            else:
                fpath = os.path.join(project_path("algorithms", "weights"), "default_weights.json")
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存权重失败: %s", e)

    def set_user_weight(self, algorithm_name: str, weight: float):
        """设置用户自定义权重"""
        with self._lock:
            self.user_weights[algorithm_name] = max(0.01, min(10.0, weight))
        self._save_weights_sync()
    
    def clear_user_weight(self, algorithm_name: str):
        """清除用户自定义权重"""
        with self._lock:
            if algorithm_name in self.user_weights:
                del self.user_weights[algorithm_name]
        self._save_weights_sync()
    
    def is_user_weight(self, algorithm_name: str) -> bool:
        """检查是否有用户自定义权重"""
        return algorithm_name in self.user_weights

    def update_accuracy(self, algorithm_name: str, accuracy: float):
        """更新算法准确率（线程安全，写盘异步）"""
        with self._lock:
            if algorithm_name not in self.accuracy_records:
                self.accuracy_records[algorithm_name] = []
            self.accuracy_records[algorithm_name].append(accuracy)
            if len(self.accuracy_records[algorithm_name]) > 100:
                self.accuracy_records[algorithm_name] = self.accuracy_records[algorithm_name][-100:]

        # 锁外执行：ML 重算 + 异步写盘，不阻塞其他算法
        self._recalculate_ml_weights()
        self._save_weights_sync()
    
    def _recalculate_ml_weights(self):
        """重新计算机器学习权重（调用方无需持锁 —— 内部使用快照）"""
        with self._lock:
            records_snapshot = {k: list(v) for k, v in self.accuracy_records.items()}

        new_weights = {}
        for algo_name, records in records_snapshot.items():
            if not records:
                new_weights[algo_name] = 1.0
                continue

            weights = []
            for i, acc in enumerate(records):
                w = (i + 1) / len(records) * 0.5 + 0.5
                weights.append(w * acc)

            avg_accuracy = sum(weights) / len(weights) if weights else 0.5
            new_weights[algo_name] = 0.5 + avg_accuracy * 1.5

        algo_names = list(new_weights.keys())
        if algo_names:
            wlist = [new_weights[an] for an in algo_names]
            max_w = max(wlist)
            softmax_sum = sum(math.exp(w - max_w) for w in wlist)
            if softmax_sum > 0:
                for an, w in zip(algo_names, wlist):
                    nw = math.exp(w - max_w) / softmax_sum * len(algo_names)
                    new_weights[an] = max(0.01, min(10.0, nw))

        with self._lock:
            self.ml_weights = new_weights

    def get_weight(self, algorithm_name: str, base_weight: float = 1.0) -> float:
        """获取最终权重"""
        # 用户自定义权重优先级最高
        if algorithm_name in self.user_weights:
            return self.user_weights[algorithm_name]

        # 使用ML计算的权重
        if algorithm_name in self.ml_weights:
            return self.ml_weights[algorithm_name]

        # 返回基础权重
        return base_weight

    def get_all_weights(self, algorithm_names: List[str]) -> Dict[str, float]:
        """获取所有算法的权重"""
        result = {}
        for name in algorithm_names:
            result[name] = self.get_weight(name)
        return result

    def get_algorithm_info(self, algorithm_names: List[str]) -> List[Dict]:
        """获取所有算法信息"""
        info = []
        for name in algorithm_names:
            accuracy = self.accuracy_records.get(name, [])
            avg_acc = sum(accuracy) / len(accuracy) if accuracy else 0.5

            info.append(
                {
                    "name": name,
                    "user_weight": self.user_weights.get(name),
                    "ml_weight": self.ml_weights.get(name, 1.0),
                    "final_weight": self.get_weight(name),
                    "accuracy": avg_acc,
                    "is_customized": name in self.user_weights,
                    "samples": len(accuracy),
                }
            )
        return info

    def reset_weights(self):
        """重置所有权重"""
        with self._lock:
            self.user_weights = {}
            self.ml_weights = {}
            self.accuracy_records = {}
        self._save_weights_sync()
    
    def sync_save(self):
        """同步写盘（供测试用，确保文件已落盘）"""
        try:
            with self._lock:
                data = {
                    "user_weights": dict(self.user_weights),
                    "ml_weights": dict(self.ml_weights),
                    "accuracy_records": {k: list(v) for k, v in self.accuracy_records.items()},
                    "updated_at": datetime.now().isoformat(),
                }
            self._write_weights_file(data)
        except Exception as e:
            logger.warning("同步保存权重失败: %s", e)


# 全局权重管理器实例（惰性初始化）
_weight_manager = None


def get_weight_manager():
    """获取全局 WeightManager 单例（惰性初始化）"""
    global _weight_manager
    if _weight_manager is None:
        _weight_manager = WeightManager()
    return _weight_manager
