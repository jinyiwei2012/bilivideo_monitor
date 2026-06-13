"""
历史数据缓冲区 — numpy 结构化数组后端，tuple 兼容前端

将 gui.history_data[bvid] 从 list-of-tuples 替换为固定容量的
numpy structured array 环形缓冲区。

内存对比（1000 条/视频）：
    list[(datetime, int)]  ≈ 300 KB/视频
    HistoryBuffer          ≈  16 KB/视频  (18x 节省)

设计：
    - 内部 dtype=[('ts','f8'), ('view','i8')]，连续内存
    - 对外兼容 tuple 迭代/索引/切片，现有代码无需改动
    - 提供 .ts_array / .view_array 属性供优化消费者零拷贝读取
"""

import numpy as np
from datetime import datetime
from typing import Tuple, Iterator, Union


class HistoryBuffer:
    """固定容量 numpy 结构化数组环形缓冲区。

    存储 (timestamp, view_count) 对，对外表现为 tuple 列表。
    超容量时自动丢弃最旧条目（保留尾部 80%）。

    Usage:
        buf = HistoryBuffer(capacity=2000)
        buf.append((datetime.now(), 12345))
        for ts, v in buf:            # tuple 迭代（兼容旧代码）
            print(ts, v)
        views = buf.view_array       # numpy int64 数组（零拷贝）
        ts_arr = buf.ts_array        # numpy float64 数组（零拷贝）
        last5 = buf[-5:]             # 切片 → [(datetime, int), ...]
    """

    __slots__ = ("_data", "_len", "_cap")

    def __init__(self, capacity: int = 2000):
        self._cap = max(8, capacity)
        self._data = np.empty(self._cap, dtype=[("ts", "f8"), ("view", "i8")])
        self._len = 0

    # ── 零拷贝 numpy 访问（供 registry 等优化路径）─────

    @property
    def view_array(self) -> np.ndarray:
        """播放量 int64 数组（零拷贝视图）。"""
        return self._data["view"][: self._len]

    @property
    def ts_array(self) -> np.ndarray:
        """Unix 时间戳 float64 数组（零拷贝视图）。"""
        return self._data["ts"][: self._len]

    @property
    def view_f32(self) -> np.ndarray:
        """播放量 float32 数组（供派生特征计算）。"""
        return self._data["view"][: self._len].astype(np.float32, copy=False)

    # ── 写入 ───────────────────────────────────────

    def append(self, item: Tuple):
        """追加一条 (timestamp, view_count)。

        timestamp 支持 datetime / int / float / str。
        超容量时自动丢弃最旧的 20% 条目。
        """
        ts, v = item
        ts_val = self._to_ts(ts)

        if self._len >= self._cap:
            # 保留尾部 80%，丢弃最旧 20%
            keep = max(self._cap // 2, self._cap * 4 // 5)
            shift = self._len - keep
            self._data[:keep] = self._data[shift : self._len].copy()  # .copy() 必须，重叠赋值未定义行为
            self._len = keep

        self._data[self._len] = (ts_val, int(v))
        self._len += 1

    # ── 读取（兼容 tuple 接口）──────────────────────

    def __len__(self) -> int:
        return self._len

    def __getitem__(self, idx) -> Union[Tuple, list]:
        if isinstance(idx, slice):
            start, stop, step = idx.indices(self._len)
            indices = range(start, stop, step)
            return [(self._idx_to_tuple(i)) for i in indices]
        if idx < 0:
            idx += self._len
        if idx < 0 or idx >= self._len:
            raise IndexError(f"index {idx} out of range [0, {self._len})")
        return self._idx_to_tuple(idx)

    def __iter__(self) -> Iterator[Tuple]:
        for i in range(self._len):
            yield self._idx_to_tuple(i)

    def __contains__(self, item) -> bool:
        # 仅用于兼容性，不推荐频繁使用
        return False

    # ── 排序 ───────────────────────────────────────

    def sort_by_time(self):
        """按时间戳升序排序（原地）。"""
        if self._len < 2:
            return
        idx = np.argsort(self._data["ts"][: self._len])
        self._data[: self._len] = self._data[idx]

    # ── 内部工具 ────────────────────────────────────

    @staticmethod
    def _to_ts(ts) -> float:
        if isinstance(ts, datetime):
            return ts.timestamp()
        if isinstance(ts, (int, float)):
            return float(ts)
        try:
            return datetime.fromisoformat(str(ts)).timestamp()
        except (ValueError, TypeError):
            return 0.0

    def _idx_to_tuple(self, i: int) -> Tuple:
        row = self._data[i]
        return (datetime.fromtimestamp(row["ts"]), int(row["view"]))

    def to_list(self) -> list:
        """导出为 [(datetime, int), ...] 列表（供 DB/导出使用）。"""
        return [(self._idx_to_tuple(i)) for i in range(self._len)]

    def __repr__(self) -> str:
        return f"HistoryBuffer(len={self._len}, cap={self._cap})"


# ── 工厂函数 ───────────────────────────────────────


def create_history_buffer(capacity: int = 2000) -> HistoryBuffer:
    """创建历史数据缓冲区（工厂函数，隔离 numpy 导入时机）。"""
    return HistoryBuffer(capacity)
