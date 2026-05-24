"""多版本 Checkpoint 管理

目录结构：
    algorithms/checkpoints/
    └── <algo_id>/                       # 全局 checkpoint
        ├── v1_20260520_1430.pt
        ├── v2_20260521_0900.pt
        ├── active.json                  # {"active_version": "v2_..."}
        └── metadata.json                # {"v1_...": {created_at, ...}, ...}
    └── <algo_id>/_video/<BVID>/         # 视频微调 checkpoint
        └── v1_*.pt ...

公开 API：
    ckpt = CheckpointManager(algo_id="knf")             # 全局
    ckpt = CheckpointManager(algo_id="knf", bvid="BV1") # 视频微调
    ckpt.has_checkpoint()
    ckpt.list_versions() → [{"version", "created_at", "data_count", "val_loss", "active"}]
    ckpt.save(state_dict, metadata) → version_name
    ckpt.load(version="active") → state_dict
    ckpt.activate(version)
    ckpt.delete(version)
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from utils import project_path

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
except ImportError:
    _torch_available = False

_CKPT_ROOT = project_path("algorithms", "checkpoints")


class CheckpointManager:
    """单算法（或单算法+单视频）的 checkpoint 管理器。"""

    def __init__(self, algo_id: str, bvid: Optional[str] = None):
        self.algo_id = algo_id
        self.bvid = bvid
        if bvid:
            self._dir = os.path.join(_CKPT_ROOT, algo_id, "_video", bvid)
        else:
            self._dir = os.path.join(_CKPT_ROOT, algo_id)
        self._active_file = os.path.join(self._dir, "active.json")
        self._meta_file = os.path.join(self._dir, "metadata.json")

    # ── 查询接口 ─────────────────────────────────────

    def has_checkpoint(self) -> bool:
        """是否有可用的 active checkpoint。"""
        if not os.path.exists(self._dir):
            return False
        active = self._read_active()
        if not active:
            return False
        path = os.path.join(self._dir, f"{active}.pt")
        return os.path.exists(path)

    def list_versions(self) -> List[Dict[str, Any]]:
        """返回 [{version, created_at, data_count, val_loss, active}]，按 created_at 倒序。"""
        if not os.path.exists(self._dir):
            return []
        meta = self._read_metadata()
        active_version = self._read_active() or ""
        versions = []
        for fname in os.listdir(self._dir):
            if not fname.endswith(".pt"):
                continue
            version = fname[:-3]
            m = meta.get(version, {})
            versions.append(
                {
                    "version": version,
                    "created_at": m.get("created_at", ""),
                    "data_count": m.get("data_count", 0),
                    "val_loss": m.get("val_loss", -1.0),
                    "active": version == active_version,
                }
            )
        versions.sort(key=lambda x: x["created_at"], reverse=True)
        return versions

    def active_version(self) -> Optional[str]:
        return self._read_active()

    # ── 持久化接口 ────────────────────────────────────

    def save(self, state_dict: Dict, metadata: Optional[Dict] = None) -> str:
        """保存 state_dict，自动命名 v<N>_<YYYYMMDD_HHMM>，并激活。返回 version 名。"""
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法保存 checkpoint")
        os.makedirs(self._dir, exist_ok=True)
        existing = self.list_versions()
        next_num = len(existing) + 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        version = f"v{next_num}_{ts}"
        path = os.path.join(self._dir, f"{version}.pt")
        torch.save(state_dict, path)

        meta = self._read_metadata()
        meta[version] = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_count": (metadata or {}).get("data_count", 0),
            "val_loss": (metadata or {}).get("val_loss", -1.0),
            "epochs": (metadata or {}).get("epochs", 0),
            "device": (metadata or {}).get("device", "unknown"),
        }
        self._write_metadata(meta)
        self._write_active(version)
        logger.info("[%s] 保存 checkpoint: %s", self.algo_id, version)
        return version

    def load(self, version: str = "active") -> Optional[Dict]:
        """加载 state_dict。version='active' 表示当前激活版本。"""
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
            return torch.load(path, map_location="cpu", weights_only=False)
        except Exception as e:
            logger.error("[%s] 加载 checkpoint 失败: %s", self.algo_id, e)
            return None

    def activate(self, version: str) -> bool:
        path = os.path.join(self._dir, f"{version}.pt")
        if not os.path.exists(path):
            return False
        self._write_active(version)
        logger.info("[%s] 激活 checkpoint: %s", self.algo_id, version)
        return True

    def delete(self, version: str) -> bool:
        path = os.path.join(self._dir, f"{version}.pt")
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
        except OSError as e:
            logger.error("[%s] 删除 checkpoint 失败: %s", self.algo_id, e)
            return False
        meta = self._read_metadata()
        meta.pop(version, None)
        self._write_metadata(meta)
        if self._read_active() == version:
            remaining = self.list_versions()
            self._write_active(remaining[0]["version"] if remaining else "")
        return True

    def delete_all(self) -> int:
        """删除此路径下的所有 checkpoint 并重置元数据。返回删除的文件数。"""
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

    # ── 内部辅助 ─────────────────────────────────────

    def _read_active(self) -> Optional[str]:
        if not os.path.exists(self._active_file):
            return None
        try:
            with open(self._active_file, "r", encoding="utf-8") as f:
                return json.load(f).get("active_version", "")
        except Exception:
            return None

    def _write_active(self, version: str):
        os.makedirs(self._dir, exist_ok=True)
        with open(self._active_file, "w", encoding="utf-8") as f:
            json.dump({"active_version": version}, f, ensure_ascii=False, indent=2)

    def _read_metadata(self) -> Dict:
        if not os.path.exists(self._meta_file):
            return {}
        try:
            with open(self._meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_metadata(self, meta: Dict):
        os.makedirs(self._dir, exist_ok=True)
        with open(self._meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


def list_video_finetune_bvids(algo_id: str) -> List[str]:
    """返回该算法有视频微调 checkpoint 的 bvid 列表。"""
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


def load_best_checkpoint(algo_id: str, bvid: Optional[str] = None) -> Optional[Dict]:
    """加载最佳可用 checkpoint：优先视频微调，其次全局。

    预测管线用：让已微调的算法在推理时自动使用视频专属权重，
    未微调的视频自动回退到全局 checkpoint。
    """
    if bvid:
        video_ckpt = CheckpointManager(algo_id, bvid=bvid)
        if video_ckpt.has_checkpoint():
            state = video_ckpt.load()
            if state is not None:
                logger.debug("[%s] 使用视频微调 checkpoint (bvid=%s)", algo_id, bvid)
                return state
    global_ckpt = CheckpointManager(algo_id)
    if global_ckpt.has_checkpoint():
        state = global_ckpt.load()
        if state is not None:
            return state
    return None


def list_all_trained_algorithms() -> List[str]:
    """扫描 checkpoints/ 目录，返回有 active checkpoint 的 algo_id 列表。"""
    if not os.path.exists(_CKPT_ROOT):
        return []
    result = []
    for name in os.listdir(_CKPT_ROOT):
        sub = os.path.join(_CKPT_ROOT, name)
        if not os.path.isdir(sub) or name.startswith("_"):
            continue
        if CheckpointManager(name).has_checkpoint():
            result.append(name)
    return result


def get_all_activation_status() -> Dict[str, Dict]:
    """返回所有有 checkpoint 的算法的版本激活状态。

    Returns:
        {algo_id: {
            "name": str,
            "active_version": str,
            "latest_version": str,
            "needs_activation": bool,
        }}
    """
    all_aids = list_all_trained_algorithms()
    status = {}
    for aid in all_aids:
        ckpt = CheckpointManager(aid)
        versions = ckpt.list_versions()
        if not versions:
            continue
        latest_v = versions[0]["version"]
        active_v = ckpt.active_version() or ""
        # try to extract display name from checkpoints metadata
        status[aid] = {
            "name": aid,
            "active_version": active_v,
            "latest_version": latest_v,
            "needs_activation": latest_v != active_v,
        }
    return status


def activate_latest_for_all() -> Dict[str, str]:
    """将所有有 checkpoint 的算法切换到最新版本。

    Returns:
        {algo_id: version}  — 实际被切换的算法及其激活的版本号
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
    return switched
