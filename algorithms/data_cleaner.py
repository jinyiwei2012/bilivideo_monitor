"""
数据预处理：异常值检测 + Savitzky-Golay 平滑滤波

独立模块，可被 monitor_service 和 engine 调用：
- 播放量倒退检测 (view_count_reversal)
- Z-score 跳变过滤 (zscore_jump)
- Savitzky-Golay 去噪平滑
"""

import numpy as np
from typing import List, Tuple


def detect_view_reversal(views: np.ndarray) -> np.ndarray:
    """检测并标记播放量倒退异常点，返回布尔掩码"""
    if len(views) < 3:
        return np.zeros(len(views), dtype=bool)
    diffs = np.diff(views)
    mask = np.zeros(len(views), dtype=bool)
    for i in range(1, len(diffs)):
        if diffs[i] < 0 and abs(diffs[i]) > 0.05 * views[i]:
            mask[i + 1] = True
    return mask


def zscore_filter(series: np.ndarray, window: int = 10, threshold: float = 3.0) -> np.ndarray:
    """Z-score 滑动窗口异常检测，返回布尔掩码"""
    if len(series) < window:
        return np.zeros(len(series), dtype=bool)
    mask = np.zeros(len(series), dtype=bool)
    for i in range(window, len(series)):
        local = series[max(0, i - window): i]
        mu, sigma = np.mean(local), np.std(local)
        if sigma > 1e-8:
            z = abs(series[i] - mu) / sigma
            if z > threshold:
                mask[i] = True
    return mask


def savitzky_golay_smooth(series: np.ndarray, window: int = 5, order: int = 2) -> np.ndarray:
    """Savitzky-Golay 平滑滤波"""
    if len(series) < window or window < 3:
        return series.copy()
    half = window // 2
    smoothed = series.copy().astype(float)
    for i in range(half, len(series) - half):
        x = np.arange(-half, half + 1)
        A = np.vstack([x ** k for k in range(order + 1)]).T
        y = series[i - half: i + half + 1]
        try:
            coeff = np.linalg.lstsq(A, y, rcond=None)[0]
            smoothed[i] = coeff[0]
        except np.linalg.LinAlgError:
            pass
    return smoothed


def interpolate_outliers(series: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """对异常点用前后有效值线性插值"""
    result = series.copy().astype(float)
    outlier_idx = np.where(mask)[0]
    for idx in outlier_idx:
        prev_idx = idx - 1
        next_idx = idx + 1
        while prev_idx >= 0 and mask[prev_idx]:
            prev_idx -= 1
        while next_idx < len(mask) and mask[next_idx]:
            next_idx += 1
        if prev_idx >= 0 and next_idx < len(mask):
            result[idx] = result[prev_idx] + (result[next_idx] - result[prev_idx]) * (idx - prev_idx) / (next_idx - prev_idx)
        elif prev_idx >= 0:
            result[idx] = result[prev_idx]
        elif next_idx < len(mask):
            result[idx] = result[next_idx]
    return result


def clean_history(history: List[Tuple], smooth: bool = True) -> List[Tuple]:
    """完整清洗流程：倒退检测 → Z-score过滤 → S-G平滑 → 插值
    
    Args:
        history: [(timestamp, view_count), ...]
        smooth: 是否应用 Savitzky-Golay 平滑
        
    Returns:
        清洗后的历史列表
    """
    if len(history) < 5:
        return list(history)

    views = np.array([h[1] for h in history], dtype=float)

    # 播放量倒退检测
    reversal_mask = detect_view_reversal(views)

    # Z-score 跳变检测（在去倒退的数据上）
    views_no_reversal = views.copy()
    views_no_reversal[reversal_mask] = np.interp(
        np.where(reversal_mask)[0],
        np.where(~reversal_mask)[0],
        views[~reversal_mask],
    )
    jump_mask = zscore_filter(views_no_reversal, window=10, threshold=3.5)

    # 合并异常掩码
    outlier_mask = reversal_mask | jump_mask

    # 插值修复
    cleaned = interpolate_outliers(views, outlier_mask)

    # S-G 平滑
    if smooth and len(cleaned) >= 5:
        cleaned = savitzky_golay_smooth(cleaned, window=min(5, len(cleaned) // 2 * 2 + 1), order=2)

    # 重建历史
    cleaned_history = []
    for i, (ts, _) in enumerate(history):
        cleaned_history.append((ts, float(cleaned[i])))

    return cleaned_history
