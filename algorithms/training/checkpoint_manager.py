"""多版本 Checkpoint 管理模块
=========================

本模块提供训练过程中模型参数的版本化保存与恢复功能。
支持全局预训练 checkpoint 和按视频微调 checkpoint 两种模式。

目录结构：
---------
    algorithms/checkpoints/
    ├── <algo_id>/                           # 全局 checkpoint 目录
    │   ├── v1_20260520_1430.pt              # 版本化模型参数文件
    │   ├── v2_20260521_0900.pt
    │   ├── active.json                      # 当前激活版本记录 {"active_version": "v2_..."}
    │   └── metadata.json                    # 各版本元数据 {"v1_...": {created_at, ...}, ...}
    └── <algo_id>/_video/<BVID>/             # 视频微调 checkpoint 目录
        └── v1_*.pt ...

公开 API：
---------
    # 全局 checkpoint 管理
    ckpt = CheckpointManager(algo_id="knf")

    # 视频微调 checkpoint 管理
    ckpt = CheckpointManager(algo_id="knf", bvid="BV1")

    # 基本操作
    ckpt.has_checkpoint()                    # 是否有可用的 active checkpoint
    ckpt.list_versions()                     # 列出所有版本 → [{version, created_at, ...}]
    ckpt.save(state_dict, metadata)          # 保存并激活新版本 → version_name
    ckpt.load(version="active")              # 加载指定版本 → state_dict
    ckpt.activate(version)                   # 激活指定版本
    ckpt.delete(version)                     # 删除指定版本
    ckpt.delete_all()                        # 删除所有版本
    ckpt.active_version()                    # 获取当前激活版本名

工具函数：
---------
    load_best_checkpoint(algo_id, bvid)      # 优先视频微调，其次全局
    list_all_trained_algorithms()            # 扫描所有已训练算法
    list_video_finetune_bvids(algo_id)       # 列出有微调数据的视频
    get_all_activation_status()              # 获取所有算法激活状态
    activate_latest_for_all()                # 全量激活最新版本
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from utils import project_path

# 模块级日志记录器
logger = logging.getLogger(__name__)

# ── PyTorch 可用性检测 ─────────────────────────────────
# 在不安装 PyTorch 的环境中也能正常导入本模块
_torch_available = True
try:
    import torch
except ImportError:
    _torch_available = False

# Checkpoint 根目录路径
_CKPT_ROOT = project_path("algorithms", "checkpoints")


class CheckpointManager:
    """单算法（或单算法+单视频）的 checkpoint 管理器。

    职责：
    - 管理模型参数的版本化保存（.pt 文件）
    - 维护 active.json 记录当前激活版本
    - 维护 metadata.json 记录各版本元信息
    - 支持增删改查、激活切换、批量清理等操作

    使用方式：
        ckpt = CheckpointManager(algo_id="kalman_filter")       # 全局
        ckpt = CheckpointManager(algo_id="kalman_filter", bvid="BV1xxx")  # 视频微调
    """

    def __init__(self, algo_id: str, bvid: Optional[str] = None):
        """初始化 Checkpoint 管理器。

        Args:
            algo_id: 算法标识符，对应 algorithms/checkpoints/<algo_id>/ 目录。
            bvid:    B站视频 BV 号。为 None 表示全局 checkpoint；
                     不为 None 表示该视频的微调 checkpoint，存储于 _video/<bvid>/ 子目录。
        """
        self.algo_id = algo_id
        self.bvid = bvid
        if bvid:
            # 校验 BV 号格式合法性：BV + 10~12 位字母数字
            if not re.match(r"^BV[A-Za-z0-9]{10,12}$", bvid):
                raise ValueError(f"无效的 BV 号: {bvid!r}")
            # 视频微调目录：algorithms/checkpoints/<algo_id>/_video/<bvid>/
            self._dir = os.path.join(_CKPT_ROOT, algo_id, "_video", bvid)
        else:
            # 全局 checkpoint 目录：algorithms/checkpoints/<algo_id>/
            self._dir = os.path.join(_CKPT_ROOT, algo_id)
        # 激活版本记录文件路径
        self._active_file = os.path.join(self._dir, "active.json")
        # 元数据文件路径
        self._meta_file = os.path.join(self._dir, "metadata.json")

    # ── 查询接口 ─────────────────────────────────────

    def has_checkpoint(self) -> bool:
        """检查是否有可用的激活 checkpoint。

        Returns:
            bool: True 表示 active.json 中有激活版本且对应 .pt 文件存在。
        """
        if not os.path.exists(self._dir):
            return False
        active = self._read_active()
        if not active:
            return False
        path = os.path.join(self._dir, f"{active}.pt")
        return os.path.exists(path)

    def list_versions(self) -> List[Dict[str, Any]]:
        """列出所有 checkpoint 版本，按创建时间倒序。

        Returns:
            List[Dict]: 每个版本的详细信息字典，包含：
                - version: 版本名称（如 v1_20260520_1430）
                - created_at: 创建时间字符串
                - data_count: 训练数据量
                - val_loss: 验证集损失（-1.0 表示未记录）
                - learning_rate: 学习率（-1.0 表示未记录）
                - completed_epochs: 已完成训练轮数
                - data_trained_until: 已训练到的时间戳（增量训练用）
                - scheduler_state: 调度器状态
                - active: 是否为当前激活版本
        """
        if not os.path.exists(self._dir):
            return []
        meta = self._read_metadata()
        active_version = self._read_active() or ""
        versions = []
        for fname in os.listdir(self._dir):
            if not fname.endswith(".pt"):
                continue
            # 去掉 .pt 后缀得到版本名
            version = fname[:-3]
            m = meta.get(version, {})
            versions.append(
                {
                    "version": version,
                    "created_at": m.get("created_at", ""),
                    "data_count": m.get("data_count", 0),
                    "val_loss": m.get("val_loss", -1.0),
                    "learning_rate": m.get("learning_rate", -1.0),
                    "completed_epochs": m.get("completed_epochs", 0),
                    "data_trained_until": m.get("data_trained_until", 0.0),
                    "scheduler_state": m.get("scheduler_state"),
                    "active": version == active_version,
                }
            )
        # 按创建时间倒序排列，最新版本在前
        versions.sort(key=lambda x: x["created_at"], reverse=True)
        return versions

    def active_version(self) -> Optional[str]:
        """获取当前激活的版本名。

        Returns:
            Optional[str]: 激活版本名，无激活版本时返回 None。
        """
        return self._read_active()

    # ── 持久化接口 ────────────────────────────────────

    def save(self, state_dict: Dict, metadata: Optional[Dict] = None) -> str:
        """保存 state_dict 为新的 checkpoint 版本，自动命名并激活。

        命名规则：v<序号>_<YYYYMMDD_HHMMSS>
        保存后自动将此版本设为 active。

        Args:
            state_dict: PyTorch 模型的 state_dict，可包含 float32/float16/参数。
            metadata:   附加元数据字典，可包含：
                - data_count: 训练数据量
                - val_loss: 验证损失
                - epochs: 训练轮数
                - device: 训练设备
                - learning_rate: 学习率
                - completed_epochs: 已完成轮数
                - data_trained_until: 已训练数据截止时间戳
                - scheduler_state: 调度器状态

        Returns:
            str: 新创建的版本名称。

        Raises:
            RuntimeError: PyTorch 未安装时无法保存。
        """
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法保存 checkpoint")
        # 确保目录存在
        os.makedirs(self._dir, exist_ok=True)
        # 序号递增：下一个版本号为当前版本数 + 1
        existing = self.list_versions()
        next_num = len(existing) + 1
        # 生成时间戳版本名
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        version = f"v{next_num}_{ts}"
        path = os.path.join(self._dir, f"{version}.pt")
        # 保存模型参数到磁盘
        torch.save(state_dict, path)

        # 更新元数据
        meta = self._read_metadata()
        meta[version] = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_count": (metadata or {}).get("data_count", 0),
            "val_loss": (metadata or {}).get("val_loss", -1.0),
            "epochs": (metadata or {}).get("epochs", 0),
            "device": (metadata or {}).get("device", "unknown"),
            "learning_rate": (metadata or {}).get("learning_rate", -1.0),
            "completed_epochs": (metadata or {}).get("completed_epochs", 0),
            "data_trained_until": (metadata or {}).get("data_trained_until", 0.0),
            "scheduler_state": (metadata or {}).get("scheduler_state"),
        }
        self._write_metadata(meta)
        # 自动激活新保存的版本
        self._write_active(version)
        logger.info("[%s] 保存 checkpoint: %s", self.algo_id, version)
        return version

    def load(self, version: str = "active") -> Optional[Dict]:
        """加载指定版本的 state_dict。

        Args:
            version: 版本名，"active" 表示加载当前激活版本。

        Returns:
            Optional[Dict]: state_dict 字典，加载失败或 PyTorch 不可用时返回 None。
        """
        if not _torch_available:
            return None
        if version == "active":
            version = self._read_active() or ""
        if not version:
            return None
        path = os.path.join(self._dir, f"{version}.pt")
        if not os.path.exists(path):
            logger.warning("[%s] checkpoint 不存在: %s", self.algo_id, path)
            return None
        try:
            # 使用 CPU 加载以确保兼容性（即使训练用 GPU）
            return torch.load(path, map_location="cpu", weights_only=True)
        except Exception as e:
            logger.error("[%s] 加载 checkpoint 失败: %s", self.algo_id, e)
            return None

    def activate(self, version: str) -> bool:
        """激活指定版本为当前使用版本。

        Args:
            version: 要激活的版本名。

        Returns:
            bool: True 表示激活成功，False 表示版本文件不存在。
        """
        path = os.path.join(self._dir, f"{version}.pt")
        if not os.path.exists(path):
            return False
        self._write_active(version)
        logger.info("[%s] 激活 checkpoint: %s", self.algo_id, version)
        return True

    def delete(self, version: str) -> bool:
        """删除指定版本的 checkpoint 文件及元数据。

        如果删除的是激活版本，则自动激活剩余的（第一个）版本。

        Args:
            version: 要删除的版本名。

        Returns:
            bool: True 表示删除成功。
        """
        path = os.path.join(self._dir, f"{version}.pt")
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
        except OSError as e:
            logger.error("[%s] 删除 checkpoint 失败: %s", self.algo_id, e)
            return False
        # 从元数据中移除该版本
        meta = self._read_metadata()
        meta.pop(version, None)
        self._write_metadata(meta)
        # 如果删除的是当前激活版本，自动切换到剩余的第一个版本
        if self._read_active() == version:
            remaining = self.list_versions()
            self._write_active(remaining[0]["version"] if remaining else "")
        return True

    def delete_all(self) -> int:
        """删除此路径下的所有 checkpoint 文件并重置元数据。

        清理步骤：
        1. 逐个删除所有版本（含 .pt 文件和元数据）
        2. 删除 active.json 和 metadata.json
        3. 如果目录为空则删除目录

        Returns:
            int: 实际删除的 checkpoint 文件数量。
        """
        if not os.path.exists(self._dir):
            return 0
        count = 0
        for v in self.list_versions():
            if self.delete(v["version"]):
                count += 1
        # 清理残留的元数据文件
        for fname in ("active.json", "metadata.json"):
            fpath = os.path.join(self._dir, fname)
            try:
                if os.path.exists(fpath):
                    os.remove(fpath)
            except OSError:
                pass
        # 如果目录空了则移除
        try:
            if os.path.isdir(self._dir) and not os.listdir(self._dir):
                os.rmdir(self._dir)
        except OSError:
            pass
        return count

    # ── 内部辅助方法 ─────────────────────────────────────

    def _read_active(self) -> Optional[str]:
        """从 active.json 读取当前激活的版本名。

        Returns:
            Optional[str]: 激活版本名，文件不存在或格式异常时返回 None。
        """
        if not os.path.exists(self._active_file):
            return None
        try:
            with open(self._active_file, "r", encoding="utf-8") as f:
                return json.load(f).get("active_version", "")
        except Exception:
            return None

    def _write_active(self, version: str):
        """将指定版本写入 active.json。

        Args:
            version: 要设为激活的版本名。
        """
        os.makedirs(self._dir, exist_ok=True)
        with open(self._active_file, "w", encoding="utf-8") as f:
            json.dump({"active_version": version}, f, ensure_ascii=False, indent=2)

    def _read_metadata(self) -> Dict:
        """从 metadata.json 读取所有版本的元数据。

        Returns:
            Dict: 元数据字典 {version_name: {...}}，文件不存在或异常时返回空字典。
        """
        if not os.path.exists(self._meta_file):
            return {}
        try:
            with open(self._meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_metadata(self, meta: Dict):
        """将元数据字典写入 metadata.json。

        Args:
            meta: 包含所有版本元数据的完整字典，会覆盖写入。
        """
        os.makedirs(self._dir, exist_ok=True)
        with open(self._meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


# ── 工具函数 ──────────────────────────────────────────


def list_video_finetune_bvids(algo_id: str) -> List[str]:
    """列出该算法有视频微调 checkpoint 的所有 bvid。

    扫描 algorithms/checkpoints/<algo_id>/_video/ 目录，
    检查每个子目录是否有可用的 active checkpoint。

    Args:
        algo_id: 算法标识符。

    Returns:
        List[str]: 排序后的 bvid 列表。
    """
    video_root = os.path.join(_CKPT_ROOT, algo_id, "_video")
    if not os.path.exists(video_root):
        return []
    result = []
    for name in os.listdir(video_root):
        bvid_dir = os.path.join(video_root, name)
        if not os.path.isdir(bvid_dir):
            continue
        if CheckpointManager(algo_id, bvid=name).has_checkpoint():
            result.append(name)
    return sorted(result)


def _try_load_checkpoint(algo_id: str, bvid: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str]]:
    """尝试用指定的 algo_id 加载 checkpoint（不进行 fallback）。

    内部函数，由 load_best_checkpoint() 调用。

    Args:
        algo_id: 算法标识符。
        bvid:    BV 号，不为 None 时优先加载视频微调 checkpoint。

    Returns:
        Tuple[Optional[Dict], Optional[str]]: (state_dict, 来源描述)
            - state_dict 为 None 表示无可用 checkpoint
            - 来源描述如 "微调模型(v3)", "底模(v1)", None
    """
    if bvid:
        # 优先尝试视频微调 checkpoint
        video_ckpt = CheckpointManager(algo_id, bvid=bvid)
        if video_ckpt.has_checkpoint():
            state = video_ckpt.load()
            if state is not None:
                ver = video_ckpt.active_version() or "?"
                logger.info("[模型] [%s] 使用视频微调模型 (bvid=%s, %s)", algo_id, bvid, ver)
                return state, f"微调模型({ver})"
            else:
                logger.debug("[模型] [%s] 视频微调模型加载失败，降级到全局 (bvid=%s)", algo_id, bvid)
    # 降级到全局 checkpoint
    global_ckpt = CheckpointManager(algo_id)
    if global_ckpt.has_checkpoint():
        state = global_ckpt.load()
        if state is not None:
            ver = global_ckpt.active_version() or "?"
            logger.info("[模型] [%s] 使用全局预训练模型 (%s)", algo_id, ver)
            return state, f"底模({ver})"
    return None, None


def load_best_checkpoint(algo_id: str, bvid: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str]]:
    """加载最佳可用的 checkpoint，按优先级回退。

    加载优先级：
    1. 视频微调 checkpoint（algorithms/checkpoints/<algo_id>/_video/<bvid>/）
    2. 全局预训练 checkpoint（algorithms/checkpoints/<algo_id>/）
    3. 适配器包装名 fallback（如 chronos_base → [Model] Chronos零样本）
    4. 无可用 checkpoint

    Args:
        algo_id: 算法标识符（支持 registry 中的原始 algo_id 和包装名）。
        bvid:    BV 号，为 None 时跳过视频微调层级。

    Returns:
        Tuple[Optional[Dict], Optional[str]]:
            - state_dict 为 None 时表示无可用 checkpoint，需使用 numpy 降级
            - 来源描述如 "微调模型(v3)", "底模(v2)", None
    """
    state, info = _try_load_checkpoint(algo_id, bvid)
    if state is not None:
        return state, info

    # 尝试 registry 包装名（适配器包装的算法，checkpoint 存于 [Model] X/ 下）
    try:
        from algorithms.registry import AlgorithmRegistry
        mapped = AlgorithmRegistry.get_registry_key(algo_id)
        if mapped and mapped != algo_id:
            state, info = _try_load_checkpoint(mapped, bvid)
            if state is not None:
                return state, info
    except Exception as e:
        logger.debug("忽略异常: %s", e)

    logger.info("[模型] [%s] 无可用 checkpoint，使用 numpy 降级", algo_id)
    return None, None


def list_all_trained_algorithms() -> List[str]:
    """扫描 checkpoints/ 目录，返回有 active checkpoint 的算法标识符列表。

    Returns:
        List[str]: 排序后的 algo_id 列表。
    """
    if not os.path.exists(_CKPT_ROOT):
        return []
    result = []
    for name in os.listdir(_CKPT_ROOT):
        sub = os.path.join(_CKPT_ROOT, name)
        # 跳过非目录和以下划线开头的特殊目录（如 _video）
        if not os.path.isdir(sub) or name.startswith("_"):
            continue
        if CheckpointManager(name).has_checkpoint():
            result.append(name)
    return result


def get_all_activation_status() -> Dict[str, Dict]:
    """返回所有有 checkpoint 的算法的版本激活状态。

    用于 UI 显示训练状态面板。

    Returns:
        Dict[str, Dict]: {
            algo_id: {
                "name": str,              # 算法显示名
                "active_version": str,    # 当前激活版本
                "latest_version": str,    # 最新版本
                "needs_activation": bool, # 是否需要激活最新版本
            }
        }
    """
    all_aids = list_all_trained_algorithms()
    status = {}
    for aid in all_aids:
        ckpt = CheckpointManager(aid)
        versions = ckpt.list_versions()
        if not versions:
            continue
        # 列表已按时间倒序，第一个即为最新版本
        latest_v = versions[0]["version"]
        active_v = ckpt.active_version() or ""
        status[aid] = {
            "name": aid,
            "active_version": active_v,
            "latest_version": latest_v,
            "needs_activation": latest_v != active_v,
        }
    return status


def activate_latest_for_all() -> Dict[str, str]:
    """将所有有 checkpoint 的算法切换到最新版本。

    遍历所有已训练算法的 checkpoint 目录，将每个算法的最新版本
    设为 active。仅在有训练模型的 PC 上生效。

    Returns:
        Dict[str, str]: {algo_id: version} — 实际被切换的算法及其激活的版本号。
    """
    switched = {}
    for aid in list_all_trained_algorithms():
        ckpt = CheckpointManager(aid)
        versions = ckpt.list_versions()
        if not versions:
            continue
        latest = versions[0]["version"]
        active = ckpt.active_version()
        if latest != active:
            ckpt.activate(latest)
            switched[aid] = latest
            logger.info("[模型] [%s] 激活最新 checkpoint: %s", aid, latest)
        else:
            logger.debug("[模型] [%s] checkpoint 已是最新: %s", aid, active)
    if switched:
        logger.info("[模型] 共激活 %d 个算法的最新 checkpoint", len(switched))
    else:
        trained = list_all_trained_algorithms()
        if trained:
            logger.info("[模型] 所有 %d 个有 checkpoint 的算法均为最新版本", len(trained))
        else:
            logger.info("[模型] 无已训练的算法 checkpoint，将使用底模或 numpy 降级")
    return switched
