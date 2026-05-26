"""训练数据加载

从 core/data/<BVID>/<BVID>.db 的 monitor_records 表读取时序数据，
构造 (input_window, target_horizon) 监督样本。

公开类：
    VideoTimeSeriesDataset(torch.utils.data.Dataset)
        - 模式 1: bvids=None       → 扫描 core/data/ 下所有视频（全局预训练）
        - 模式 2: bvids=['BV1xxx'] → 只用指定视频（视频微调）

输出：
    x: Tensor[window, n_features] —— 输入窗口（已 z-score 归一化）
    y: Tensor[horizon]            —— 目标窗口（view_count 增量速率，z-score）

注意：
- 仅在 torch 可用时启用。无 torch 时类降级为 object 占位，import 不报错。
- view_count 是累计值，训练目标是其一阶差分（速度），更符合预测任务语义。
"""

import os
import re
import logging
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
from utils import project_path

import numpy as np

logger = logging.getLogger(__name__)

_torch_available = True
try:
    import torch
    from torch.utils.data import Dataset
except ImportError:
    _torch_available = False
    Dataset = object  # type: ignore

_BVID_PATTERN = re.compile(r"^BV[0-9A-Za-z]{10}$")

_DATA_ROOT = project_path("core", "data")


_DEFAULT_FEATURES = ("view_count", "like_count", "coin_count", "favorite_count", "share_count")


def _safe_bvid(bvid: str) -> bool:
    return bool(_BVID_PATTERN.match(bvid))


def _scan_all_bvids(data_root: str = _DATA_ROOT) -> List[str]:
    """扫描 core/data/ 下所有合法 BVID 目录。"""
    if not os.path.isdir(data_root):
        return []
    result = []
    for name in os.listdir(data_root):
        if not _safe_bvid(name):
            continue
        db_path = os.path.join(data_root, name, f"{name}.db")
        if os.path.exists(db_path):
            result.append(name)
    return result


def _parse_ts(val) -> float:
    """将 timestamp 转换为 unix epoch float，支持 ISO 字符串和数字。"""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return datetime.fromisoformat(str(val)).timestamp()
    except (ValueError, TypeError):
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0


def _ts_to_iso(ts: float) -> str:
    """将 unix epoch float 转换为 ISO 字符串，用于 SQL 比较。"""
    return datetime.fromtimestamp(ts).isoformat()


def _load_records(bvid: str, features: Tuple[str, ...], data_root: str = _DATA_ROOT,
                  min_timestamp: Optional[float] = None) -> Tuple[Optional[np.ndarray], float]:
    """读取单个视频的 monitor_records，返回 (arr, max_timestamp)（按 timestamp 升序）。

    Args:
        min_timestamp: 不为 None 时只加载 timestamp > 该值的记录。
    Returns:
        (arr, max_timestamp) — 无数据时 arr=None, max_timestamp=0。
    """
    if not _safe_bvid(bvid):
        return (None, 0.0)
    db_path = os.path.join(data_root, bvid, f"{bvid}.db")
    if not os.path.exists(db_path):
        return (None, 0.0)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        cursor = conn.cursor()
        cols = ", ".join(features)
        if min_timestamp is not None:
            # 数据库存储 ISO 字符串，需要转换比较
            _iso = _ts_to_iso(min_timestamp)
            cursor.execute(f"SELECT {cols}, timestamp FROM monitor_records WHERE timestamp > ? ORDER BY timestamp ASC",
                           (_iso,))
        else:
            cursor.execute(f"SELECT {cols}, timestamp FROM monitor_records ORDER BY timestamp ASC")
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning("[dataset] 读取 %s 失败: %s", bvid, e)
        return (None, 0.0)
    if not rows:
        return (None, 0.0)
    arr = np.zeros((len(rows), len(features)), dtype=np.float32)
    max_ts = 0.0
    for i, row in enumerate(rows):
        for j, feat in enumerate(features):
            v = row[feat]
            arr[i, j] = float(v) if v is not None else 0.0
        ts = _parse_ts(row["timestamp"])
        if ts > max_ts:
            max_ts = ts
    return (arr, max_ts)


class VideoTimeSeriesDataset(Dataset):
    """时序滑动窗口数据集。

    Args:
        window: 输入窗口长度（时间步数）。
        horizon: 预测的未来时间步数。
        bvids: 限定使用哪些 BVID；None 表示扫描全部。
        features: 使用的特征列。
        data_root: core/data/ 路径覆盖（测试用）。
        min_records: 单个视频至少要有多少条记录才纳入（< window+horizon 直接跳过）。
        target_feature: 预测目标特征名（必须在 features 内），默认为 view_count。
        normalize: 是否对每个视频独立做 z-score 归一化（推荐 True）。

    输出样本：
        (x, y)
        x: Tensor[window, n_features]
        y: Tensor[horizon]   —— target_feature 的一阶差分（速度）
    """

    def __init__(
        self,
        window: int = 10,
        horizon: int = 3,
        bvids: Optional[List[str]] = None,
        features: Optional[List[str]] = None,
        data_root: Optional[str] = None,
        min_records: Optional[int] = None,
        target_feature: str = "view_count",
        normalize: bool = True,
        min_timestamp: Optional[float] = None,
    ):
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法构造数据集")
        self.window = int(window)
        self.horizon = int(horizon)
        self.features = tuple(features) if features else _DEFAULT_FEATURES
        self.data_root = data_root or _DATA_ROOT
        self.min_records = int(min_records) if min_records else self.window + self.horizon + 1
        if target_feature not in self.features:
            raise ValueError(f"target_feature={target_feature!r} 不在 features={self.features} 中")
        self.target_idx = self.features.index(target_feature)
        self.normalize = bool(normalize)
        self.max_timestamp = 0.0  # 本次训练用到的最大时间戳

        if bvids is None:
            bvids = _scan_all_bvids(self.data_root)
        else:
            bvids = [b for b in bvids if _safe_bvid(b)]

        self._series: List[np.ndarray] = []  # 每个视频归一化后的 [N, F]
        self._velocity: List[np.ndarray] = []  # 每个视频的目标速度 [N-1]
        self._index: List[Tuple[int, int]] = []  # (series_idx, start_offset)
        self._global_max_ts = 0.0  # 所有视频中的最大 timestamp

        for bvid in bvids:
            arr, max_ts = _load_records(bvid, self.features, self.data_root, min_timestamp=min_timestamp)
            if arr is None or arr.shape[0] < self.min_records:
                continue
            # 一阶差分得到速度序列；首位补 0
            velocity = np.diff(arr[:, self.target_idx], prepend=arr[0, self.target_idx]).astype(np.float32)
            if self.normalize:
                arr_n = _zscore(arr)
                vel_n = _zscore_1d(velocity)
            else:
                arr_n = arr
                vel_n = velocity
            if max_ts > self._global_max_ts:
                self._global_max_ts = max_ts
            sidx = len(self._series)
            self._series.append(arr_n)
            self._velocity.append(vel_n)
            # 每个起点 s 满足 s + window + horizon <= N
            max_start = arr.shape[0] - self.window - self.horizon
            for s in range(max_start + 1):
                self._index.append((sidx, s))

        self.max_timestamp = self._global_max_ts
        logger.info(
            "[dataset] 加载完成: %d 视频, %d 样本 (window=%d, horizon=%d, features=%d, max_ts=%.0f)",
            len(self._series),
            len(self._index),
            self.window,
            self.horizon,
            len(self.features),
            self.max_timestamp,
        )

    def __len__(self) -> int:
        return len(self._index)

    def __getitem__(self, idx: int):
        sidx, s = self._index[idx]
        series = self._series[sidx]
        velocity = self._velocity[sidx]
        x = series[s : s + self.window]  # [W, F]
        y = velocity[s + self.window : s + self.window + self.horizon]  # [H]
        return torch.from_numpy(np.ascontiguousarray(x)), torch.from_numpy(np.ascontiguousarray(y))

    def n_features(self) -> int:
        return len(self.features)

    def n_videos(self) -> int:
        return len(self._series)


def _zscore(arr: np.ndarray) -> np.ndarray:
    mean = arr.mean(axis=0, keepdims=True)
    std = arr.std(axis=0, keepdims=True)
    std = np.where(std < 1e-8, 1.0, std)
    return ((arr - mean) / std).astype(np.float32)


def _zscore_1d(arr: np.ndarray) -> np.ndarray:
    mean = float(arr.mean())
    std = float(arr.std())
    if std < 1e-8:
        std = 1.0
    return ((arr - mean) / std).astype(np.float32)


def estimate_dataset_size(
    bvids: Optional[List[str]] = None,
    window: int = 10,
    horizon: int = 3,
    data_root: Optional[str] = None,
) -> dict:
    """轻量估算：扫描 DB 行数计算可生成样本数，不读完整记录。

    Returns:
        {total_videos, valid_videos, total_records, total_samples}
    """
    root = data_root or _DATA_ROOT
    if bvids is None:
        bvids = _scan_all_bvids(root)
    total_videos = len(bvids)
    valid = 0
    total_records = 0
    total_samples = 0
    min_records = window + horizon + 1
    for bvid in bvids:
        if not _safe_bvid(bvid):
            continue
        db_path = os.path.join(root, bvid, f"{bvid}.db")
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM monitor_records")
            n = cursor.fetchone()[0]
            conn.close()
        except sqlite3.Error:
            continue
        total_records += n
        if n >= min_records:
            valid += 1
            total_samples += n - window - horizon + 1
    return {
        "total_videos": total_videos,
        "valid_videos": valid,
        "total_records": total_records,
        "total_samples": total_samples,
    }
