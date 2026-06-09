"""
数据预处理：异常值检测 + Savitzky-Golay 平滑滤波

独立模块，可被 monitor_service 和 engine 调用：
- 播放量倒退检测 (detect_view_reversal): 识别播放量异常下降
- Z-score 跳变过滤 (zscore_filter): 滑动窗口异常跳变检测
- Savitzky-Golay 去噪平滑 (savitzky_golay_smooth): 多项式拟合局部平滑
- 异常点线性插值 (interpolate_outliers): 用前后有效值填充异常点
- 完整清洗流程 (clean_history): 组合以上步骤的一键清洗

应用场景：
    B 站 API 可能返回不精确/波动/倒退的播放量数据，
    清洗后数据使预测算法更稳定可靠。
"""

import numpy as np
from typing import List, Tuple


def detect_view_reversal(views: np.ndarray) -> np.ndarray:
    """检测并标记播放量倒退异常点，返回布尔掩码。

    播放量理论上不应递减，所以当检测到显著下降（超过当前值的 5%）
    时将该点标记为异常。

    Args:
        views: 播放量数组（按时间排序）

    Returns:
        np.ndarray: 布尔掩码，True 表示异常倒退
    """
    if len(views) < 3:
        return np.zeros(len(views), dtype=bool)
    diffs = np.diff(views)  # 一阶差分
    mask = np.zeros(len(views), dtype=bool)
    for i in range(1, len(diffs)):
        # 连续两次下降 且 降幅 > 当前值的 5% → 标记为异常
        if diffs[i] < 0 and abs(diffs[i]) > 0.05 * views[i]:
            mask[i + 1] = True
    return mask


def zscore_filter(series: np.ndarray, window: int = 10, threshold: float = 3.0) -> np.ndarray:
    """Z-score 滑动窗口异常检测，返回布尔掩码。

    对每个点计算其在滑动窗口内的 Z-score = |x - μ| / σ，
    Z-score > threshold 的点视为跳变异常。

    Args:
        series: 数值序列
        window: 滑动窗口大小（默认 10）
        threshold: Z-score 阈值（默认 3.0）

    Returns:
        np.ndarray: 布尔掩码，True 表示异常跳变
    """
    if len(series) < window:
        return np.zeros(len(series), dtype=bool)
    mask = np.zeros(len(series), dtype=bool)
    for i in range(window, len(series)):
        local = series[max(0, i - window): i]  # 局部窗口
        mu, sigma = np.mean(local), np.std(local)
        if sigma > 1e-8:  # 方差太小不判断
            z = abs(series[i] - mu) / sigma
            if z > threshold:
                mask[i] = True
    return mask


def savitzky_golay_smooth(series: np.ndarray, window: int = 5, order: int = 2) -> np.ndarray:
    """Savitzky-Golay 平滑滤波。

    对每个点取局部窗口，用 order 阶多项式拟合窗口内的数据，
    取拟合值作为平滑后的值。比简单移动平均更好地保留趋势特征。

    Args:
        series: 输入序列
        window: 窗口大小（奇数，默认 5）
        order: 多项式阶数（默认 2，即二次拟合）

    Returns:
        np.ndarray: 平滑后的序列（长度不变）
    """
    if len(series) < window or window < 3:
        return series.copy()
    half = window // 2
    smoothed = series.copy().astype(float)
    for i in range(half, len(series) - half):
        x = np.arange(-half, half + 1)  # [-2, -1, 0, 1, 2] for window=5
        A = np.vstack([x ** k for k in range(order + 1)]).T  # Vandermonde 矩阵
        y = series[i - half: i + half + 1]
        try:
            coeff = np.linalg.lstsq(A, y, rcond=None)[0]  # 最小二乘拟合
            smoothed[i] = coeff[0]  # 取常数项作为平滑值
        except np.linalg.LinAlgError:
            pass
    return smoothed


def interpolate_outliers(series: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """对异常点用前后有效值线性插值。

    遇到连续的异常点时，向外扩展搜索第一个有效值，
    然后用线性插值填充中间的异常点。

    Args:
        series: 原始数值序列
        mask: 布尔掩码，True 表示异常点

    Returns:
        np.ndarray: 插值修复后的序列
    """
    result = series.copy().astype(float)
    outlier_idx = np.where(mask)[0]
    for idx in outlier_idx:
        # 向前搜索第一个非异常点
        prev_idx = idx - 1
        next_idx = idx + 1
        while prev_idx >= 0 and mask[prev_idx]:
            prev_idx -= 1
        while next_idx < len(mask) and mask[next_idx]:
            next_idx += 1
        if prev_idx >= 0 and next_idx < len(mask):
            # 线性插值在两个有效点之间
            result[idx] = result[prev_idx] + (result[next_idx] - result[prev_idx]) * (idx - prev_idx) / (next_idx - prev_idx)
        elif prev_idx >= 0:
            result[idx] = result[prev_idx]
        elif next_idx < len(mask):
            result[idx] = result[next_idx]
    return result


def clean_history(history: List[Tuple], smooth: bool = True) -> List[Tuple]:
    """完整清洗流程：倒退检测 → Z-score过滤 → S-G平滑 → 插值 → 重建历史。

    一站式数据清洗，处理 B 站 API 返回数据中常见的：
    - 播放量倒退（API 缓存不一致）
    - 跳变异常（数据采集异常抖动）
    - 噪声（随机波动）

    Args:
        history: [(timestamp, view_count), ...] 格式的历史数据
        smooth: 是否应用 Savitzky-Golay 平滑（默认 True）

    Returns:
        清洗后的历史列表（保持 (timestamp, view_count) 格式）
    """
    if len(history) < 5:
        return list(history)

    views = np.array([h[1] for h in history], dtype=float)

    # 1. 播放量倒退检测
    reversal_mask = detect_view_reversal(views)

    # 2. Z-score 跳变检测（在去倒退的数据上检测，避免倒退数据干扰）
    views_no_reversal = views.copy()
    views_no_reversal[reversal_mask] = np.interp(
        np.where(reversal_mask)[0],
        np.where(~reversal_mask)[0],
        views[~reversal_mask],
    )
    jump_mask = zscore_filter(views_no_reversal, window=10, threshold=3.5)

    # 3. 合并异常掩码
    outlier_mask = reversal_mask | jump_mask

    # 4. 插值修复异常点
    cleaned = interpolate_outliers(views, outlier_mask)

    # 5. S-G 平滑（进一步去除随机噪声）
    if smooth and len(cleaned) >= 5:
        cleaned = savitzky_golay_smooth(cleaned, window=min(5, len(cleaned) // 2 * 2 + 1), order=2)

    # 6. 重建历史（保持原始的 timestamp，只替换 view_count）
    cleaned_history = []
    for i, (ts, _) in enumerate(history):
        cleaned_history.append((ts, float(cleaned[i])))

    return cleaned_history
