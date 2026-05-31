"""
权重管理器

管理每个算法的权重，支持三级权重体系：
    1. 用户自定义权重（优先级最高）
    2. 机器学习计算的权重（基于历史准确率，使用 softmax 归一化）
    3. 默认权重（base_weight 兜底）

权重持久化到 JSON 文件，支持多视频隔离存储。
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
    """权重管理器

    维护 user_weights / ml_weights / accuracy_records 三张表，
    通过互斥锁 _lock 保证线程安全，权重变更后异步写盘。
    """

    def __init__(self, save_dir: str = None):
        """初始化权重管理器。

        Args:
            save_dir: 权重文件保存目录，默认 algorithms/weights/
        """
        if save_dir is None:
            save_dir = project_path("algorithms", "weights")

        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

        # 线程锁，保护所有内部状态的并发读写
        self._lock = threading.Lock()

        # 用户自定义权重（优先级最高）
        self.user_weights: Dict[str, float] = {}

        # 机器学习计算的权重（基于准确率历史）
        self.ml_weights: Dict[str, float] = {}

        # 算法准确率记录（每项是一个列表，保存历次准确率）
        self.accuracy_records: Dict[str, List[float]] = {}

        # 从磁盘加载已有权重
        self._load_weights()

    def _get_weights_file(self, bvid: str = None) -> str:
        """获取权重文件路径。

        bvid 不为 None 时返回视频专属权重文件，否则返回默认权重文件。
        """
        if bvid:
            return os.path.join(self.save_dir, f"{bvid}_weights.json")
        return os.path.join(self.save_dir, "default_weights.json")

    def _load_weights(self):
        """从默认权重文件加载持久化的权重数据。"""
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
        """在 _lock 外组装数据快照，然后委托 _write_weights_file 落盘。"""
        try:
            with self._lock:
                data = {
                    "user_weights": dict(self.user_weights),
                    "ml_weights": dict(self.ml_weights),
                    "accuracy_records": {k: list(v) for k, v in self.accuracy_records.items()},
                    "updated_at": datetime.now().isoformat(),
                }
            self._write_weights_file(data, bvid)
        except Exception as e:
            logger.warning("保存权重失败: %s", e)

    @staticmethod
    def _write_weights_file(data: dict, bvid: str = None):
        """执行实际的文件写入（静态方法，可在后台线程中调用）。"""
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
        """设置用户自定义权重（覆盖 ML 权重，限制范围 [0.01, 10.0]）。"""
        with self._lock:
            self.user_weights[algorithm_name] = max(0.01, min(10.0, weight))
        self._save_weights_sync()

    def clear_user_weight(self, algorithm_name: str):
        """清除指定算法的用户自定义权重，恢复为 ML 权重。"""
        with self._lock:
            if algorithm_name in self.user_weights:
                del self.user_weights[algorithm_name]
        self._save_weights_sync()

    def is_user_weight(self, algorithm_name: str) -> bool:
        """检查指定算法是否有用户自定义权重。"""
        return algorithm_name in self.user_weights

    def update_accuracy(self, algorithm_name: str, accuracy: float):
        """更新算法准确率记录（线程安全）。

        准确率列表最多保留最近 100 条。更新后立即触发 ML 重算和异步写盘。
        """
        with self._lock:
            if algorithm_name not in self.accuracy_records:
                self.accuracy_records[algorithm_name] = []
            self.accuracy_records[algorithm_name].append(accuracy)
            # 限制记录长度，防止无限增长
            if len(self.accuracy_records[algorithm_name]) > 100:
                self.accuracy_records[algorithm_name] = self.accuracy_records[algorithm_name][-100:]

        # 锁外执行：ML 重算 + 写盘，避免长时间持锁阻塞其他算法
        self._recalculate_ml_weights()
        self._save_weights_sync()

    def _recalculate_ml_weights(self):
        """重新计算机器学习权重。

        过程：
            1. 从 accuracy_records 读取快照（不持锁，减少锁竞争）
            2. 对每个算法：较新记录权重略高（时间衰减加权平均）
            3. softmax 归一化，使权重总和 ≈ 算法个数
            4. 写入 self.ml_weights
        """
        with self._lock:
            records_snapshot = {k: list(v) for k, v in self.accuracy_records.items()}

        new_weights = {}
        for algo_name, records in records_snapshot.items():
            if not records:
                new_weights[algo_name] = 1.0
                continue

            # 时间加权：越晚的记录权重越大（递增加权）
            weights = []
            for i, acc in enumerate(records):
                w = (i + 1) / len(records) * 0.5 + 0.5
                weights.append(w * acc)

            avg_accuracy = sum(weights) / len(weights) if weights else 0.5
            # 将 [0, 1] 准确率映射到 [0.5, 2.0] 的原始权重范围
            new_weights[algo_name] = 0.5 + avg_accuracy * 1.5

        # softmax 归一化，避免个别算法权重过高
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
        """获取算法的最终权重。

        优先级：user_weights > ml_weights > base_weight
        """
        with self._lock:
            if algorithm_name in self.user_weights:
                return self.user_weights[algorithm_name]
            if algorithm_name in self.ml_weights:
                return self.ml_weights[algorithm_name]
        return base_weight

    def get_all_weights(self, algorithm_names: List[str]) -> Dict[str, float]:
        """批量获取多个算法的最终权重。"""
        result = {}
        for name in algorithm_names:
            result[name] = self.get_weight(name)
        return result

    def get_algorithm_info(self, algorithm_names: List[str]) -> List[Dict]:
        """获取多个算法的详细信息（名称、用户权重、ML 权重、准确率等）。"""
        info = []
        for name in algorithm_names:
            with self._lock:
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
        """重置所有权重和准确率记录到初始状态。"""
        with self._lock:
            self.user_weights = {}
            self.ml_weights = {}
            self.accuracy_records = {}
        self._save_weights_sync()

    def sync_save(self):
        """立即同步写盘（供测试用，确保文件已落盘）。"""
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
_weight_manager_lock = threading.Lock()


def get_weight_manager():
    """获取全局 WeightManager 单例（双检锁惰性初始化）。"""
    global _weight_manager
    if _weight_manager is None:
        with _weight_manager_lock:
            if _weight_manager is None:
                _weight_manager = WeightManager()
    return _weight_manager
