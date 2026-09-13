"""训练数据加载模块
==================

从 core/data/<BVID>/<BVID>.db 的 monitor_records 表读取时序数据，
构造 (input_window, target_horizon) 监督学习样本。

数据流程：
---------
1. 扫描 core/data/ 目录下所有合法 BVID 的视频数据库
2. 从每个视频的 monitor_records 表读取时序特征（播放量、点赞、投币等）
3. 对原始累计值计算一阶差分得到速度序列（更符合预测任务语义）
4. 构造衍生特征（滚动均值、滚动标准差、加速度、相对位置、生命周期阶段）
5. 对每个视频独立做 z-score 归一化
6. 生成滑动窗口样本：(x=过去 window 步, y=未来 horizon 步)

公开类：
-------
    VideoTimeSeriesDataset(torch.utils.data.Dataset)
        - 模式 1: bvids=None       → 扫描 core/data/ 下所有视频（全局预训练）
        - 模式 2: bvids=['BV1xxx'] → 只用指定视频（视频微调）

输出样本格式：
    x: Tensor[window, n_features + n_derived]  — 输入窗口（已 z-score 归一化）
    y: Tensor[horizon]                          — 目标窗口（view_count 一阶差分，z-score）

注意事项：
---------
- 仅在 PyTorch 可用时启用。无 torch 时类降级为 object 占位，import 不报错。
- view_count 是累计值，训练目标是其一阶差分（速度），更符合预测任务语义。
- 有 min_timestamp 参数支持增量训练（只加载新数据）。
"""

import os
import re
import logging
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple
from utils import project_path

import numpy as np

# 模块级日志记录器
logger = logging.getLogger(__name__)

# ── PyTorch 可用性检测 ─────────────────────────────────
_torch_available = True
try:
    import torch
    from torch.utils.data import Dataset
except ImportError:
    _torch_available = False
    # 无 torch 时用 object 占位，保证模块可导入
    Dataset = object  # type: ignore

# BV 号格式正则：与 core/database/models.py 保持一致的校验规则
_BVID_PATTERN = re.compile(r"^BV[A-Za-z0-9]{10,12}$")

# 核心数据目录路径
_DATA_ROOT = project_path("core", "data")

# 默认使用的特征列（与数据库 monitor_records 表字段对应）
_DEFAULT_FEATURES = ("view_count", "like_count", "coin_count", "favorite_count", "share_count")


def _robust_increments(target: np.ndarray) -> np.ndarray:
    """将累计播放量序列转为稳健增量序列（剔除 API 冻结伪迹）。

    与 registry 精度改造同口径（D1/A1）：B站计数 API 常见"冻结"（连续多点为 0 增量，
    随后一次性补量）。原始 np.diff 把冻结 0 当真实停滞、把补量当爆发 → 训练标签被
    噪声污染。处理：对增量做 MAD 剪除（单发补量离群），连续 0 保留（可能真停滞）。

    返回与 target 等长的逐点增量序列（首位为 0，语义同 np.diff(prepend=target[0])）。
    """
    velocity = np.diff(target, prepend=target[0]).astype(np.float32)
    # 只看有意义的非首段，MAD 剪除补量尖峰（补量 = 单段 >> 邻域中位）
    seg = velocity[1:]
    if len(seg) >= 3:
        med = float(np.median(seg))
        mad = float(np.median(np.abs(seg - med)))
        if mad > 1e-9:
            # 补量剪除阈值：> med + 6*MAD 视为一次性补量尖峰 → 替换为该点近端中位
            upper = med + 6.0 * 1.4826 * mad
            outlier = seg > upper
            if np.any(outlier):
                for i in np.where(outlier)[0]:
                    lo = max(0, i - 3)
                    hi = min(len(seg), i + 4)
                    seg[i] = float(np.median(seg[lo:hi]))
        velocity[1:] = seg
    return velocity


def _safe_bvid(bvid: str) -> bool:
    """校验 BV 号格式是否合法。

    Args:
        bvid: 待校验的 BV 号字符串。

    Returns:
        bool: True 表示格式符合 BV + 10 位字母数字。
    """
    return bool(_BVID_PATTERN.match(bvid))


def _scan_all_bvids(data_root: str = _DATA_ROOT) -> List[str]:
    """扫描 data_root 目录下所有合法的 BVID 目录。

    只收集同时存在目录和对应 .db 文件的 BVID。

    Args:
        data_root: 数据根目录路径，默认为 core/data/。

    Returns:
        List[str]: 排序后的合法 BVID 列表。
    """
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
    """将 timestamp 值转换为 Unix epoch 浮点数秒。

    支持多种输入格式：ISO 字符串、纯数字（int/float）。

    Args:
        val: 时间戳值，可为 ISO 格式字符串、int、float 或 None。

    Returns:
        float: Unix 时间戳（秒），解析失败返回 0.0。
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    # 尝试按 ISO 格式解析
    try:
        return datetime.fromisoformat(str(val)).timestamp()
    except (ValueError, TypeError):
        # 再尝试直接转浮点（兜底）
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0


def _ts_to_iso(ts: float) -> str:
    """将 Unix epoch float 转换为 ISO 格式字符串，用于数据库 SQL 比较。

    Args:
        ts: Unix 时间戳（秒）。

    Returns:
        str: ISO 8601 格式的日期时间字符串。
    """
    return datetime.fromtimestamp(ts).isoformat()


def _load_records(
    bvid: str, features: Tuple[str, ...], data_root: str = _DATA_ROOT, min_timestamp: Optional[float] = None
) -> Tuple[Optional[np.ndarray], float]:
    """从单个视频的 SQLite 数据库读取 monitor_records 表。

    返回按 timestamp 升序排列的 numpy 数组。

    Args:
        bvid:          BV 号。
        features:      要读取的特征列名元组。
        data_root:     数据根目录。
        min_timestamp: 不为 None 时，只加载 timestamp > 该值的记录（增量训练）。

    Returns:
        Tuple[Optional[np.ndarray], float]:
            - arr: shape [N, len(features)] 的 float32 数组，无数据时为 None
            - max_timestamp: 该视频记录中的最大时间戳，无数据时为 0.0
    """
    if not _safe_bvid(bvid):
        return (None, 0.0)
    db_path = os.path.join(data_root, bvid, f"{bvid}.db")
    if not os.path.exists(db_path):
        return (None, 0.0)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # 按列名访问
        # WAL 模式提高并发读取性能，busy_timeout 防止写锁冲突
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        cursor = conn.cursor()
        cols = ", ".join(features)
        if min_timestamp is not None:
            # 数据库存储 ISO 字符串，需要转换后比较
            _iso = _ts_to_iso(min_timestamp)
            cursor.execute(
                f"SELECT {cols}, timestamp FROM monitor_records WHERE timestamp > ? ORDER BY timestamp ASC", (_iso,)
            )
        else:
            cursor.execute(f"SELECT {cols}, timestamp FROM monitor_records ORDER BY timestamp ASC")
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning("[dataset] 读取 %s 失败: %s", bvid, e)
        return (None, 0.0)
    if not rows:
        return (None, 0.0)
    # 构建 numpy 数组
    arr = np.zeros((len(rows), len(features)), dtype=np.float32)
    max_ts = 0.0
    for i, row in enumerate(rows):
        for j, feat in enumerate(features):
            v = row[feat]
            # None 值填充为 0.0
            arr[i, j] = float(v) if v is not None else 0.0
        ts = _parse_ts(row["timestamp"])
        if ts > max_ts:
            max_ts = ts
    return (arr, max_ts)


class VideoTimeSeriesDataset(Dataset):
    """时序滑动窗口数据集，用于 PyTorch DataLoader。

    对每个视频的时序数据生成固定窗口大小的 (输入, 目标) 样本对。
    支持全局预训练（扫描所有视频）和单视频微调两种模式。

    数据增强：
    - 衍生特征：滚动均值(5)、滚动标准差(5)、加速度、相对位置、生命周期阶段
    - z-score 归一化：按视频独立归一化，消除不同视频之间的量级差异
    - 一阶差分目标：将累计 view_count 转为速度（增量），更符合预测语义

    Args:
        window:         输入窗口长度（时间步数），默认 10。
        horizon:        预测的未来时间步数，默认 3。
        bvids:          限定使用哪些 BVID；None 表示扫描全部视频。
        features:       使用的特征列，默认取播放量/点赞/投币/收藏/分享。
        data_root:      数据根目录覆盖（主要用于测试）。
        min_records:    单个视频至少需要多少条记录才纳入（< window+horizon 直接跳过）。
        target_feature: 预测目标特征名（必须在 features 中），默认为 "view_count"。
        normalize:      是否对每个视频独立做 z-score 归一化（推荐 True）。
        min_timestamp:  不为 None 时只加载 timestamp 后的数据（增量训练用）。

    输出样本：
        (x, y)
        x: Tensor[window, n_features + n_derived]  — 输入窗口特征
        y: Tensor[horizon]                          — target_feature 的一阶差分（速度）
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
        device: Optional["torch.device"] = None,
        long_window: int = 48,
    ):
        """初始化时序数据集。

        会根据 bvids 参数决定是全局模式（扫描全部视频）还是微调模式（指定视频）。
        数据加载完成后内部以索引列表方式存储，每个元素指向 (series_idx, start_offset)。

        Args:
            device: 不为 None 且为 CUDA 时，将全部时序数据预载入 GPU 显存，
                    消除训练时的逐 batch CPU→GPU 传输开销。
            long_window: 长期监督窗（步数, 默认 48 ≈ 1h）。目标 y = [horizon 步稳健增量
                          ⊕ 未来 long_window 步平均速率 log 值]，使模型同时学短期轨迹与
                         长期速率（A+B 双尺度）。

        Raises:
            RuntimeError: PyTorch 未安装。
            ValueError: target_feature 不在 features 中。
        """
        if not _torch_available:
            raise RuntimeError("torch 未安装，无法构造数据集")
        self.window = int(window)
        self.horizon = int(horizon)
        # 长期监督窗（步数，75s/步）：目标 = 未来 horizon 步稳健增量 ⊕ 未来 long_window
        # 步平均速率的 log 值（A+B 双尺度）。默认 48 步 ≈ 1 小时真实未来均值。
        self.long_window = int(long_window)
        self.features = tuple(features) if features else _DEFAULT_FEATURES
        self.data_root = data_root or _DATA_ROOT
        # 最少需要 window + horizon + 1 条记录才能生成一个有效样本
        self.min_records = int(min_records) if min_records else self.window + self.horizon + 1
        if target_feature not in self.features:
            raise ValueError(f"target_feature={target_feature!r} 不在 features={self.features} 中")
        # 目标特征在特征列表中的索引位置
        self.target_idx = self.features.index(target_feature)
        self.normalize = bool(normalize)
        self.max_timestamp = 0.0  # 本次训练用到的最大时间戳（所有视频中）

        # ── 衍生特征定义 ─────────────────────────────
        self._derived_feature_names = ["roll_mean_5", "roll_std_5", "acceleration", "relative_pos", "lifecycle_phase"]
        self._n_derived = len(self._derived_feature_names)  # 衍生特征数（5个）

        # 确定要处理的 BVID 列表
        if bvids is None:
            bvids = _scan_all_bvids(self.data_root)
        else:
            bvids = [b for b in bvids if _safe_bvid(b)]

        # ── 数据结构 ─────────────────────────────────
        self._series: List[np.ndarray] = []  # 每个视频归一化后的特征矩阵 [N, F + n_derived]
        self._velocity: List[np.ndarray] = []  # 每个视频的目标速度序列 [N-1]
        self._long_rate: List[np.ndarray] = []  # 每个视频的长期平均速率序列 [N]（A+B 长期段）
        self._index: List[Tuple[int, int]] = []  # 样本索引: (series_idx, start_offset)
        self._global_max_ts = 0.0  # 所有视频中的最大 timestamp

        # 遍历每个视频加载数据并生成样本
        for bvid in bvids:
            arr, max_ts = _load_records(bvid, self.features, self.data_root, min_timestamp=min_timestamp)
            if arr is None or arr.shape[0] < self.min_records:
                continue

            # ── 稳健增量目标序列（A+B 短期段）───────────
            # 累计值差分后做 MAD 补量剪除（API 冻结伪迹），与 registry increment_75s 同口径
            target = arr[:, self.target_idx]
            velocity = _robust_increments(target)

            # ── 长期平均速率序列（A+B 长期段）───────────
            # long_rate[i] = target 在 [i+1, i+long_window] 的真实平均增量（每 75s/步）；
            # 样本未来不足 long_window 时，用可用段均值（尾部样本仍可监督）
            N_total = arr.shape[0]
            long_rate = np.zeros(N_total, dtype=np.float32)
            lw = max(1, self.long_window)
            for i in range(N_total - 1):
                hi = min(N_total, i + 1 + lw)
                if hi > i + 1:
                    long_rate[i] = float((target[hi - 1] - target[i]) / (hi - 1 - i))
            # 尾部无未来：填充 0（对应样本会被 horizon 索引保护，实际取不到）
            long_rate[N_total - 1] = 0.0

            # ── 衍生特征 ─────────────────────────────
            N = arr.shape[0]

            # 滚动均值（窗口大小=5）：使用卷积代替循环
            if N >= 5:
                kernel = np.ones(5, dtype=np.float32) / 5
                roll_mean = np.convolve(target, kernel, mode="same")
            else:
                # 数据量不足时使用全局均值填充
                roll_mean = np.full(N, float(target.mean()))

            # 滚动标准差（窗口大小=5）：揭示局部波动程度
            if N >= 5:
                roll_std = np.array(
                    [float(np.std(target[max(0, i - 2) : min(N, i + 3)])) for i in range(N)], dtype=np.float32
                )
            else:
                # 数据量不足时使用全局标准差填充
                roll_std = np.full(N, float(target.std() or 1.0))

            # 加速度：速度的二阶差分，揭示增长趋势变化
            accel = np.diff(velocity, prepend=velocity[0]).astype(np.float32)

            # 相对时间位置 [0, 1]：归一化时间轴
            rel_pos = np.arange(N, dtype=np.float32) / max(N - 1, 1)

            # 生命周期阶段：0=早期(前20%), 1=增长期(20-60%), 2=成熟期(后40%)
            lifecycle_phase = np.where(rel_pos < 0.2, 0.0, np.where(rel_pos < 0.6, 1.0, 2.0)).astype(np.float32)

            # 拼接原始特征和衍生特征
            extras = np.column_stack([roll_mean, roll_std, accel, rel_pos, lifecycle_phase])  # [N, 5]
            arr_ext = np.column_stack([arr, extras])  # [N, F + 5]

            # ── z-score 归一化（按视频独立） ──────────
            # 关键：长期平均速率与短期速度必须共用同一缩放器（mean/std 取自 velocity 序列），
            # 否则推理端 _build_torch_input 只能拿到 velocity 的 v_mean/v_std，无法反归一化
            # 模型输出的第 H+1 维（长期目标）。二者同量纲（播放量/步），共用缩放是自洽的。
            if self.normalize:
                arr_n = _zscore(arr_ext)
                _v_mean = float(np.mean(velocity))
                _v_std = float(np.std(velocity))
                if _v_std < 1e-8:
                    _v_std = 1.0
                vel_n = ((velocity - _v_mean) / _v_std).astype(np.float32)
                long_n = ((long_rate - _v_mean) / _v_std).astype(np.float32)
            else:
                arr_n = arr_ext
                vel_n = velocity
                long_n = long_rate

            # 更新全局最大时间戳
            if max_ts > self._global_max_ts:
                self._global_max_ts = max_ts
            # 存储归一化后的数据
            sidx = len(self._series)
            self._series.append(arr_n)
            self._velocity.append(vel_n)
            self._long_rate.append(long_n)
            # 生成所有有效滑动窗口的索引
            # 每个起点 s 满足 s + window + horizon <= N（长期段在 __getitem__ 内裁剪）
            max_start = arr.shape[0] - self.window - self.horizon
            for s in range(max_start + 1):
                self._index.append((sidx, s))

        self.max_timestamp = self._global_max_ts
        # ── 预转为 torch Tensor，避免 __getitem__ 中重复 numpy→torch 转换 ──
        # .copy() 断开与原始 numpy 数组的共享内存，确保 DataLoader 多进程安全
        self._series = [torch.from_numpy(s.copy()) for s in self._series]
        self._velocity = [torch.from_numpy(v.copy()) for v in self._velocity]
        self._long_rate = [torch.from_numpy(l.copy()) for l in self._long_rate]
        # ── VRAM 预载：将全部时序数据提前移入 GPU 显存 ──
        # 消除训练时逐 batch 的 CPU→GPU 传输，但会占用显存
        # 仅 CUDA 设备启用（DirectML/NPU 不适合此模式）
        self._on_device = device is not None and str(device).startswith("cuda")
        if self._on_device:
            self._series = [s.to(device) for s in self._series]
            self._velocity = [v.to(device) for v in self._velocity]
            self._long_rate = [l.to(device) for l in self._long_rate]
        n_feat = len(self.features) + self._n_derived
        logger.info(
            "[dataset] 加载完成: %d 视频, %d 样本 (window=%d, horizon=%d, features=%d, derived=%d, max_ts=%.0f)",
            len(self._series),
            len(self._index),
            self.window,
            self.horizon,
            len(self.features),
            self._n_derived,
            self.max_timestamp,
        )

    def __len__(self) -> int:
        """返回数据集的样本总数。

        Returns:
            int: 所有视频的滑动窗口样本数量。
        """
        return len(self._index)

    def __getitem__(self, idx: int):
        """根据索引返回一个训练样本 (x, y)。

        Args:
            idx: 样本索引。

        Returns:
            Tuple[Tensor, Tensor]:
                x: shape [window, n_features + n_derived] 的输入特征矩阵
                y: shape [horizon + 1] 的目标向量 —— 前 horizon 步 = 稳健增量（短期轨迹），
                   最后 1 维 = 样本点后 long_window 步的真实平均速率（长期均值, A+B 双尺度）。
        """
        sidx, s = self._index[idx]
        series = self._series[sidx]
        velocity = self._velocity[sidx]
        long_rate = self._long_rate[sidx]
        # 切片 → clone() 确保返回独立副本（DataLoader 多进程安全，连续内存）
        x = series[s : s + self.window].clone()  # [W, F]
        y_short = velocity[s + self.window : s + self.window + self.horizon].clone()  # [H] 稳健增量
        # 长期监督：样本起点后未来 long_window 步的平均速率（真实未来均值）
        # 长期目标锚定在窗口末端位置；越界时用该视频已有序列保证索引有效（long_rate 已 pad）
        _anchor = s + self.window  # 窗口末端 = 预测起点
        _hi = min(len(long_rate), _anchor + self.long_window)
        _lo = min(_anchor + 1, len(long_rate) - 1)
        if _hi > _lo:
            y_long = long_rate[_lo:_hi].mean().reshape(1)
        else:
            y_long = long_rate[_anchor].reshape(1)
        return x, torch.cat([y_short, y_long])

    def n_features(self) -> int:
        """返回特征总数（原始特征 + 衍生特征）。

        Returns:
            int: 特征维度。
        """
        return len(self.features) + self._n_derived

    def n_videos(self) -> int:
        """返回有效视频数量。

        Returns:
            int: 数据量满足要求的视频数量。
        """
        return len(self._series)


# ── 归一化工具函数 ────────────────────────────────────


def _zscore(arr: np.ndarray) -> np.ndarray:
    """对 2D 数组按列（特征维度）做 z-score 归一化。

    公式：x' = (x - mean) / std
    当标准差接近 0 时（如常数特征），std 替换为 1.0 避免除零。

    Args:
        arr: shape [N, F] 的 numpy 数组。

    Returns:
        np.ndarray: 归一化后的同形状 float32 数组。
    """
    mean = arr.mean(axis=0, keepdims=True)
    std = arr.std(axis=0, keepdims=True)
    # 防止除以极小的标准差
    std = np.where(std < 1e-8, 1.0, std)
    return ((arr - mean) / std).astype(np.float32)


def _zscore_1d(arr: np.ndarray) -> np.ndarray:
    """对 1D 数组做 z-score 归一化。

    公式：x' = (x - mean) / std
    当标准差接近 0 时，std 替换为 1.0 避免除零。

    Args:
        arr: shape [N] 的 numpy 数组。

    Returns:
        np.ndarray: 归一化后的同形状 float32 数组。
    """
    mean = float(arr.mean())
    std = float(arr.std())
    if std < 1e-8:
        std = 1.0
    return ((arr - mean) / std).astype(np.float32)


# ── 数据集规模估算 ──────────────────────────────────


def estimate_dataset_size(
    bvids: Optional[List[str]] = None,
    window: int = 10,
    horizon: int = 3,
    data_root: Optional[str] = None,
) -> dict:
    """轻量估算可训练样本数量，不读取完整记录（只做 COUNT(*))。

    用于在开始训练前向用户展示预估的训练规模和时间。

    Args:
        bvids:     限定视频列表，None 表示扫描全部。
        window:    输入窗口长度。
        horizon:   预测步数。
        data_root: 数据根目录。

    Returns:
        dict: {
            "total_videos": int,     # 总视频数
            "valid_videos": int,     # 数据量满足要求的视频数
            "total_records": int,    # 总记录数
            "total_samples": int,    # 可生成的样本数
        }
    """
    root = data_root or _DATA_ROOT
    if bvids is None:
        bvids = _scan_all_bvids(root)
    total_videos = len(bvids)
    valid = 0
    total_records = 0
    total_samples = 0
    min_records = window + horizon + 1  # 最少需要这么多记录
    for bvid in bvids:
        if not _safe_bvid(bvid):
            continue
        db_path = os.path.join(root, bvid, f"{bvid}.db")
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # 只查行数，不读具体数据（轻量操作）
            cursor.execute("SELECT COUNT(*) FROM monitor_records")
            n = cursor.fetchone()[0]
            conn.close()
        except sqlite3.Error:
            continue
        total_records += n
        if n >= min_records:
            valid += 1
            # 滑动窗口可生成样本数 = N - window - horizon + 1
            total_samples += n - window - horizon + 1
    return {
        "total_videos": total_videos,
        "valid_videos": valid,
        "total_records": total_records,
        "total_samples": total_samples,
    }
