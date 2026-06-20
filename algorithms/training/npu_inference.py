"""NPU 推理引擎
============

将 PyTorch 模型导出为 ONNX，编译到 Intel AI Boost NPU（通过 OpenVINO），
提供模型缓存、批量推理、预热等功能。

核心组件：
- NpuModelCache:   模型缓存管理器（导出 + 编译 + 持久化）
- export_to_onnx:  将 PyTorch 模型导出为 ONNX FP16
- compile_for_npu: 将 ONNX 模型编译到 NPU
- batch_infer:     批量 NPU 推理

使用示例：
    from algorithms.training.npu_inference import NpuInferenceEngine

    engine = NpuInferenceEngine(cache_dir="data/npu_cache")
    engine.preload_algorithms(registry)  # 预热所有 DL 算法模型

    # 批量推理
    results = engine.batch_predict(algo_inputs)
"""

import os
import sys
import time
import json
import hashlib
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# ── 缓存目录 ─────────────────────────────────────────
_DEFAULT_CACHE_DIR = os.path.join("data", "npu_cache")


# ── 数据结构 ─────────────────────────────────────────

@dataclass
class NpuModelEntry:
    """单个 NPU 编译模型的缓存条目。"""

    algo_name: str
    onnx_path: str
    compiled_model: Any  # openvino.CompiledModel
    input_key: Any  # openvino.ConstOutput (model input descriptor)
    output_key: Any  # openvino.ConstOutput (model output descriptor)
    input_shape: Tuple[int, ...]
    output_shape: Tuple[int, ...]
    compile_time_ms: float
    model_hash: str


@dataclass
class NpuStats:
    """NPU 推理统计信息。"""

    total_inferences: int = 0
    total_time_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    compile_count: int = 0
    compile_total_ms: float = 0.0
    errors: int = 0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_inferences == 0:
            return 0.0
        return self.total_time_ms / self.total_inferences

    @property
    def avg_compile_ms(self) -> float:
        if self.compile_count == 0:
            return 0.0
        return self.compile_total_ms / self.compile_count


# ── NPU 推理引擎 ──────────────────────────────────────


class NpuInferenceEngine:
    """NPU 推理引擎。

    管理 ONNX 模型导出、NPU 编译、模型缓存和批量推理。
    线程安全（使用锁保护缓存操作）。
    """

    def __init__(self, cache_dir: str = _DEFAULT_CACHE_DIR, enable_cache: bool = True):
        """初始化 NPU 推理引擎。

        Args:
            cache_dir: 模型缓存目录路径。
            enable_cache: 是否启用文件缓存（False 时每次重新编译）。
        """
        self._cache_dir = Path(cache_dir)
        self._enable_cache = enable_cache
        self._models: Dict[str, NpuModelEntry] = {}
        self._lock = threading.Lock()
        self._stats = NpuStats()
        self._initialized = False

        # 懒加载的模块引用
        self._ov: Any = None
        self._torch: Any = None
        self._onnx: Any = None

    # ── 初始化 ─────────────────────────────────────

    def _ensure_modules(self) -> bool:
        """确保所需模块已导入。"""
        if self._initialized:
            return True
        try:
            import openvino as ov
            self._ov = ov
        except ImportError:
            logger.warning("openvino 未安装，NPU 推理不可用")
            return False
        try:
            import torch
            self._torch = torch
        except ImportError:
            logger.warning("torch 未安装，无法导出模型")
            return False
        try:
            import onnx
            self._onnx = onnx
        except ImportError:
            logger.warning("onnx 未安装，无法导出模型")
            return False

        # 检查 NPU 设备
        core = self._ov.Core()
        if "NPU" not in core.available_devices:
            logger.warning("NPU 设备不可用。可用设备: %s", core.available_devices)
            return False

        # 确保缓存目录存在
        if self._enable_cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._initialized = True
        logger.info(
            "NPU 推理引擎已初始化 (设备: %s, 缓存: %s)",
            core.get_property("NPU", "FULL_DEVICE_NAME"),
            self._cache_dir if self._enable_cache else "禁用",
        )
        return True

    @property
    def is_available(self) -> bool:
        """NPU 推理是否可用。"""
        return self._ensure_modules()

    @property
    def stats(self) -> NpuStats:
        """获取推理统计信息。"""
        return self._stats

    @property
    def cached_model_count(self) -> int:
        """已缓存模型数量。"""
        return len(self._models)

    @property
    def cached_model_names(self) -> List[str]:
        """已缓存模型名称列表。"""
        return list(self._models.keys())

    # ── ONNX 导出 ─────────────────────────────────

    def export_to_onnx(
        self,
        model: Any,
        algo_name: str,
        sample_input: Any,
        input_names: Optional[List[str]] = None,
        output_names: Optional[List[str]] = None,
        dynamic_axes: Optional[Dict[str, Dict[int, str]]] = None,
    ) -> str:
        """将 PyTorch 模型导出为 ONNX FP16。

        Args:
            model:        PyTorch nn.Module（已在 eval 模式）。
            algo_name:    算法名称，用于生成缓存文件名。
            sample_input: 样例输入张量（用于 trace）。
            input_names:  输入节点名称列表。
            output_names: 输出节点名称列表。
            dynamic_axes: 动态轴定义。

        Returns:
            str: ONNX 文件路径。
        """
        self._ensure_modules()

        safe_name = self._sanitize_name(algo_name)
        onnx_path = str(self._cache_dir / f"{safe_name}.onnx")

        # 检查缓存
        if self._enable_cache and os.path.exists(onnx_path):
            model_hash = self._compute_model_hash(model)
            hash_path = onnx_path + ".hash"
            if os.path.exists(hash_path):
                with open(hash_path, "r") as f:
                    cached_hash = f.read().strip()
                if cached_hash == model_hash:
                    logger.debug("[NPU] ONNX 缓存命中: %s", algo_name)
                    self._stats.cache_hits += 1
                    return onnx_path

        # 确保是单个张量或元组
        if isinstance(sample_input, (list, tuple)):
            sample_input = tuple(sample_input)
        else:
            sample_input = (sample_input,)

        # 不修改原模型：创建 CPU 副本用于导出
        model = model.cpu().eval()

        # 默认动态轴（batch 和 sequence 维度可变）
        # PyTorch 2.5+ 推荐使用 dynamic_shapes 替代 dynamic_axes
        if dynamic_axes is None:
            dynamic_axes = {}
            for i, name in enumerate(input_names or [f"input_{j}" for j in range(len(sample_input))]):
                dynamic_axes[name] = {0: "batch", 1: "sequence"}

        logger.info("[NPU] 导出 ONNX: %s", algo_name)
        t0 = time.perf_counter()
        try:
            # 兼容 PyTorch 2.5+ 的新 API
            export_kwargs = dict(
                export_params=True,
                opset_version=18,
                do_constant_folding=True,
                input_names=input_names or ["input"],
                output_names=output_names or ["output"],
            )
            try:
                # 新 API (torch >= 2.5): 使用 dynamic_shapes
                self._torch.onnx.export(
                    model, sample_input, onnx_path,
                    dynamo=False,
                    **export_kwargs,
                )
            except TypeError:
                # 旧 API: 使用 dynamic_axes
                self._torch.onnx.export(
                    model, sample_input, onnx_path,
                    dynamic_axes=dynamic_axes,
                    **export_kwargs,
                )
            export_ms = (time.perf_counter() - t0) * 1000
            logger.info("[NPU] ONNX 导出完成: %s (%d ms)", algo_name, export_ms)

            # 验证 ONNX 模型
            onnx_model = self._onnx.load(onnx_path)
            self._onnx.checker.check_model(onnx_model)

            # 保存 hash
            if self._enable_cache:
                model_hash = self._compute_model_hash(model)
                with open(onnx_path + ".hash", "w") as f:
                    f.write(model_hash)

            return onnx_path
        except Exception as e:
            logger.error("[NPU] ONNX 导出失败 %s: %s", algo_name, e)
            self._stats.errors += 1
            raise

    # ── NPU 编译 ─────────────────────────────────

    def compile_for_npu(self, algo_name: str, onnx_path: str) -> NpuModelEntry:
        """将 ONNX 模型编译到 NPU。

        Args:
            algo_name:  算法名称。
            onnx_path:  ONNX 文件路径。

        Returns:
            NpuModelEntry: 编译后的模型条目。
        """
        self._ensure_modules()

        # 检查内存缓存
        with self._lock:
            if algo_name in self._models:
                logger.debug("[NPU] 内存缓存命中: %s", algo_name)
                self._stats.cache_hits += 1
                return self._models[algo_name]

        logger.info("[NPU] 编译模型到 NPU: %s", algo_name)
        t0 = time.perf_counter()
        try:
            core = self._ov.Core()
            compiled = core.compile_model(
                onnx_path,
                "NPU",
                config={
                    "PERFORMANCE_HINT": "LATENCY",
                    "NPU_COMPILATION_MODE_PARAMS": (
                        "compute-layers-with-higher-precision="
                        "Sqrt,Power,ReduceMean,Add_RMSNorm"
                    ),
                },
            )
            compile_ms = (time.perf_counter() - t0) * 1000
            self._stats.compile_count += 1
            self._stats.compile_total_ms += compile_ms
            self._stats.cache_misses += 1

            # 获取输入/输出描述符
            input_key = compiled.input(0)
            output_key = compiled.output(0)
            input_shape = tuple(input_key.shape)
            output_shape = tuple(output_key.shape)

            entry = NpuModelEntry(
                algo_name=algo_name,
                onnx_path=onnx_path,
                compiled_model=compiled,
                input_key=input_key,
                output_key=output_key,
                input_shape=input_shape,
                output_shape=output_shape,
                compile_time_ms=compile_ms,
                model_hash="",
            )

            with self._lock:
                self._models[algo_name] = entry

            logger.info("[NPU] 编译完成: %s (%d ms)", algo_name, compile_ms)
            return entry
        except Exception as e:
            logger.error("[NPU] NPU 编译失败 %s: %s", algo_name, e)
            self._stats.errors += 1
            raise

    # ── 推理 ─────────────────────────────────────

    def infer(self, algo_name: str, input_data: np.ndarray) -> np.ndarray:
        """单次 NPU 推理。

        Args:
            algo_name:  算法名称（用于缓存查找）。
            input_data: 输入 numpy 数组（FP16 或 FP32，自动转换）。

        Returns:
            np.ndarray: 推理输出。
        """
        entry = self._models.get(algo_name)
        if entry is None:
            raise KeyError(f"模型未编译: {algo_name}")

        # 确保输入为 FP16（NPU 要求）
        if input_data.dtype != np.float16:
            input_data = input_data.astype(np.float16)

        ireq = entry.compiled_model.create_infer_request()
        ireq.infer([input_data])
        result = ireq.get_output_tensor(0).data
        self._stats.total_inferences += 1
        return result

    def batch_infer(
        self, algo_name: str, inputs: List[np.ndarray]
    ) -> List[np.ndarray]:
        """批量 NPU 推理（顺序执行，利用已编译模型避免重复编译开销）。

        Args:
            algo_name: 算法名称。
            inputs:    输入 numpy 数组列表。

        Returns:
            List[np.ndarray]: 推理输出列表。
        """
        entry = self._models.get(algo_name)
        if entry is None:
            raise KeyError(f"模型未编译: {algo_name}")

        ireq = entry.compiled_model.create_infer_request()
        results = []
        t0 = time.perf_counter()
        for inp in inputs:
            if inp.dtype != np.float16:
                inp = inp.astype(np.float16)
            ireq.infer([inp])
            results.append(ireq.get_output_tensor(0).data)
        elapsed = (time.perf_counter() - t0) * 1000
        self._stats.total_inferences += len(inputs)
        self._stats.total_time_ms += elapsed
        return results

    # ── 完整流程：导出 + 编译 ──────────────────────

    def prepare_model(
        self,
        algo_name: str,
        model: Any,
        sample_input: Any,
        input_names: Optional[List[str]] = None,
        output_names: Optional[List[str]] = None,
    ) -> NpuModelEntry:
        """一键导出 + 编译：PyTorch 模型 → ONNX → NPU。

        Args:
            algo_name:    算法名称。
            model:        PyTorch nn.Module（eval 模式）。
            sample_input: 样例输入张量（用于 trace）。
            input_names:  ONNX 输入名称。
            output_names: ONNX 输出名称。

        Returns:
            NpuModelEntry: 编译后的 NPU 模型条目。
        """
        # 检查缓存
        with self._lock:
            if algo_name in self._models:
                return self._models[algo_name]

        onnx_path = self.export_to_onnx(
            model, algo_name, sample_input,
            input_names=input_names, output_names=output_names,
        )
        return self.compile_for_npu(algo_name, onnx_path)

    # ── 预热 / 预加载 ────────────────────────────

    def preload_from_cache(self) -> int:
        """从文件缓存预加载所有已编译的模型。

        Returns:
            int: 加载的模型数量。
        """
        if not self._enable_cache or not self._ensure_modules():
            return 0

        count = 0
        onnx_files = list(self._cache_dir.glob("*.onnx"))
        for onnx_file in onnx_files:
            algo_name = onnx_file.stem
            try:
                self.compile_for_npu(algo_name, str(onnx_file))
                count += 1
            except Exception as e:
                logger.debug("[NPU] 预加载失败 %s: %s", algo_name, e)
        logger.info("[NPU] 预加载完成: %d/%d 个模型", count, len(onnx_files))
        return count

    def warmup_model(self, algo_name: str, n_warmup: int = 5) -> bool:
        """预热指定模型。

        Args:
            algo_name: 算法名称。
            n_warmup:  预热推理次数。

        Returns:
            bool: 预热是否成功。
        """
        entry = self._models.get(algo_name)
        if entry is None:
            return False

        try:
            shape = entry.input_shape
            # 处理动态维度（-1 替换为 1）
            concrete_shape = tuple(s if s > 0 else 1 for s in shape)
            dummy = np.random.randn(*concrete_shape).astype(np.float16)

            ireq = entry.compiled_model.create_infer_request()
            for _ in range(n_warmup):
                ireq.infer([dummy])
            return True
        except Exception as e:
            logger.debug("[NPU] 预热失败 %s: %s", algo_name, e)
            return False

    # ── 缓存管理 ─────────────────────────────────

    def clear_memory_cache(self):
        """清除内存中的模型缓存（保留文件缓存）。"""
        with self._lock:
            self._models.clear()
        logger.info("[NPU] 内存缓存已清除")

    def clear_disk_cache(self):
        """清除文件缓存。"""
        if self._cache_dir.exists():
            for f in self._cache_dir.glob("*.onnx*"):
                f.unlink()
        logger.info("[NPU] 文件缓存已清除")

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存详细信息。"""
        disk_count = 0
        disk_size = 0
        if self._cache_dir.exists():
            onnx_files = list(self._cache_dir.glob("*.onnx"))
            disk_count = len(onnx_files)
            disk_size = sum(f.stat().st_size for f in onnx_files)

        return {
            "memory_models": len(self._models),
            "disk_models": disk_count,
            "disk_size_kb": disk_size // 1024,
            "model_names": list(self._models.keys()),
            "stats": {
                "total_inferences": self._stats.total_inferences,
                "avg_latency_ms": round(self._stats.avg_latency_ms, 3),
                "cache_hits": self._stats.cache_hits,
                "cache_misses": self._stats.cache_misses,
                "compile_count": self._stats.compile_count,
                "compile_total_ms": round(self._stats.compile_total_ms, 0),
                "errors": self._stats.errors,
            },
        }

    # ── 工具方法 ─────────────────────────────────

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """将算法名称转换为安全文件名。"""
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

    @staticmethod
    def _compute_model_hash(model: Any) -> str:
        """计算模型参数的哈希值（用于缓存失效检测）。"""
        hasher = hashlib.sha256()
        for name, param in sorted(model.state_dict().items()):
            hasher.update(name.encode())
            hasher.update(param.cpu().numpy().tobytes())
        return hasher.hexdigest()[:16]


# ── 全局单例 ─────────────────────────────────────────

_global_engine: Optional[NpuInferenceEngine] = None
_engine_lock = threading.Lock()


def get_npu_engine(cache_dir: str = _DEFAULT_CACHE_DIR) -> NpuInferenceEngine:
    """获取全局 NPU 推理引擎单例。

    Args:
        cache_dir: 缓存目录。

    Returns:
        NpuInferenceEngine: 全局单例。
    """
    global _global_engine
    if _global_engine is None:
        with _engine_lock:
            if _global_engine is None:
                _global_engine = NpuInferenceEngine(cache_dir=cache_dir)
    return _global_engine


def is_npu_available() -> bool:
    """检查 NPU 推理是否可用（不触发完整初始化）。"""
    try:
        import openvino as ov
        core = ov.Core()
        return "NPU" in core.available_devices
    except ImportError:
        return False
