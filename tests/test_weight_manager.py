"""测试 algorithms/weight_manager.py — 权重管理器"""

import os
import json
import tempfile
from algorithms.weight_manager import WeightManager


class TestWeightManager:
    """测试 WeightManager 的核心功能"""

    def setup_method(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.wm = WeightManager(save_dir=self.tmpdir.name)

    def teardown_method(self):
        self.tmpdir.cleanup()

    def test_initial_state(self):
        """初始状态应为空"""
        assert self.wm.user_weights == {}
        assert self.wm.ml_weights == {}
        assert self.wm.accuracy_records == {}

    def test_set_user_weight(self):
        """设置用户权重"""
        self.wm.set_user_weight("algo_a", 2.0)
        assert self.wm.user_weights["algo_a"] == 2.0
        assert self.wm.is_user_weight("algo_a") is True

    def test_set_user_weight_clamps(self):
        """用户权重应在 [0.01, 10.0] 范围内裁剪"""
        self.wm.set_user_weight("algo_a", 0.001)
        assert self.wm.user_weights["algo_a"] == 0.01
        self.wm.set_user_weight("algo_a", 100.0)
        assert self.wm.user_weights["algo_a"] == 10.0

    def test_clear_user_weight(self):
        """清除用户自定义权重"""
        self.wm.set_user_weight("algo_a", 2.0)
        self.wm.clear_user_weight("algo_a")
        assert self.wm.is_user_weight("algo_a") is False

    def test_get_weight_user_override(self):
        """用户自定义权重应覆盖默认权重"""
        self.wm.set_user_weight("algo_a", 3.0)
        assert self.wm.get_weight("algo_a") == 3.0

    def test_get_weight_default(self):
        """未知算法应返回默认权重 1.0"""
        assert self.wm.get_weight("unknown_algo") == 1.0

    def test_update_accuracy(self):
        """更新算法准确率记录"""
        self.wm.update_accuracy("algo_a", 0.8)
        assert "algo_a" in self.wm.accuracy_records
        assert self.wm.accuracy_records["algo_a"] == [0.8]

    def test_multiple_accuracy_updates(self):
        """多次更新准确率应累积记录"""
        for acc in [0.6, 0.7, 0.8, 0.9]:
            self.wm.update_accuracy("algo_a", acc)
        assert len(self.wm.accuracy_records["algo_a"]) == 4

    def test_accuracy_trim_to_100(self):
        """准确率记录最多保留 100 条"""
        for i in range(150):
            self.wm.update_accuracy("algo_a", 0.5)
        assert len(self.wm.accuracy_records["algo_a"]) == 100

    def test_ml_weight_after_accuracy(self):
        """有准确率记录后应产生 ML 权重"""
        self.wm.update_accuracy("algo_a", 0.9)
        w = self.wm.ml_weights.get("algo_a", 0)
        assert 0.5 <= w <= 5.0

    def test_get_algorithm_info_empty(self):
        """空算法列表应返回空列表"""
        info = self.wm.get_algorithm_info([])
        assert info == []

    def test_get_algorithm_info(self):
        """get_algorithm_info 应返回算法的完整信息"""
        self.wm.update_accuracy("algo_a", 0.8)
        info = self.wm.get_algorithm_info(["algo_a"])
        assert len(info) == 1
        assert info[0]["name"] == "algo_a"
        assert info[0]["accuracy"] == 0.8
        assert info[0]["samples"] == 1
        assert info[0]["is_customized"] is False

    def test_get_algorithm_info_with_user_weight(self):
        """用户自定义权重应正确反映在信息中"""
        self.wm.update_accuracy("algo_a", 0.8)
        self.wm.set_user_weight("algo_a", 2.0)
        info = self.wm.get_algorithm_info(["algo_a"])
        assert info[0]["is_customized"] is True
        assert info[0]["user_weight"] == 2.0

    def test_get_all_weights(self):
        """get_all_weights 应返回所有指定算法的权重"""
        self.wm.update_accuracy("algo_a", 0.8)
        self.wm.update_accuracy("algo_b", 0.6)
        weights = self.wm.get_all_weights(["algo_a", "algo_b", "algo_c"])
        assert "algo_a" in weights
        assert "algo_b" in weights
        assert "algo_c" in weights  # 默认权重

    def test_persistence(self):
        """权重数据应能持久化保存和加载"""
        self.wm.set_user_weight("algo_a", 2.5)
        self.wm.update_accuracy("algo_b", 0.75)
        self.wm.sync_save()
        save_dir = self.wm.save_dir

        wm2 = WeightManager(save_dir=save_dir)
        assert wm2.user_weights["algo_a"] == 2.5
        assert wm2.accuracy_records["algo_b"] == [0.75]

    def test_reset_weights(self):
        """重置权重应清空所有记录"""
        self.wm.set_user_weight("algo_a", 2.0)
        self.wm.update_accuracy("algo_b", 0.8)
        self.wm.reset_weights()
        self.wm.sync_save()
        assert self.wm.user_weights == {}
        assert self.wm.ml_weights == {}
        assert self.wm.accuracy_records == {}

    def test_weights_file_created(self):
        """同步保存后应生成权重文件"""
        self.wm.set_user_weight("algo_a", 1.5)
        self.wm.sync_save()
        weight_file = os.path.join(self.tmpdir.name, "default_weights.json")
        assert os.path.exists(weight_file)
        with open(weight_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "user_weights" in data
        assert data["user_weights"]["algo_a"] == 1.5


class TestWeightManagerCustomDir:
    """测试自定义保存目录"""

    def test_custom_save_dir_creates(self):
        """自定义目录应自动创建"""
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "nested", "weights")
            wm = WeightManager(save_dir=sub)
            assert os.path.exists(sub)
            wm.set_user_weight("test", 1.0)
            wm.sync_save()
            assert os.path.exists(os.path.join(sub, "default_weights.json"))
