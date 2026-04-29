"""
因果推断模块 — 识别影响播放量的关键因素

核心方法：
1. Granger 因果检验（OLS 简化实现） — 检验各指标是否「领先于」播放量变化
2. 滑动窗口相关性分析 — 短期动态相关性
3. 偏相关分析 — 排除其他变量后的净效应

不依赖 statsmodels，纯 numpy 实现。
"""

import threading
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import math


# 可检验的指标名称
CAUSAL_FEATURES = [
    'like_count',
    'coin_count',
    'share_count',
    'favorite_count',
    'danmaku_count',
    'reply_count',
    'viewers_total',
    'viewers_app',
    'viewers_web',
]

# 中文标签映射
FEATURE_LABELS = {
    'like_count': '点赞',
    'coin_count': '投币',
    'share_count': '分享',
    'favorite_count': '收藏',
    'danmaku_count': '弹幕',
    'reply_count': '评论',
    'viewers_total': '在线人数',
    'viewers_app': 'APP观看',
    'viewers_web': '网页观看',
}


def _normalize(series: List[float]) -> Tuple[List[float], float, float]:
    """Z-Score 标准化"""
    n = len(series)
    if n == 0:
        return series, 0.0, 1.0
    mean = sum(series) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in series) / max(n - 1, 1))
    if std < 1e-12:
        return [0.0] * n, mean, 1.0
    return [(x - mean) / std for x in series], mean, std


def _ols_residuals(X: List[float], Y: List[float]) -> List[float]:
    """简单线性回归 Y ~ X 的残差列表"""
    n = len(X)
    if n < 3:
        return Y
    mx = sum(X) / n
    my = sum(Y) / n
    cov = sum((X[i] - mx) * (Y[i] - my) for i in range(n))
    var_x = sum((X[i] - mx) ** 2 for i in range(n))
    if abs(var_x) < 1e-15:
        return [y - my for y in Y]
    beta = cov / var_x
    alpha = my - beta * mx
    return [Y[i] - (alpha + beta * X[i]) for i in range(n)]


def _ss(residuals: List[float]) -> float:
    """残差平方和"""
    return sum(r * r for r in residuals)


def _granger_test(
    target: List[float],
    cause: List[float],
    max_lag: int = 3,
) -> Tuple[float, int]:
    """简化的 Granger 因果检验。

    对每个 lag k 检验：
    - 受限模型：target[t] = α + Σ β_j * target[t-j]     (j=1..k)
    - 无限制模型：target[t] = α + Σ β_j * target[t-j] + Σ γ_j * cause[t-j]

    用 F 统计量衡量因果强度。

    Returns:
        (f_stat, best_lag)  — best_lag = -1 表示不显著
    """
    n = len(target)
    if n < max_lag + 5:
        return 0.0, -1

    best_f = 0.0
    best_lag = -1

    for lag in range(1, max_lag + 1):
        # 构建样本（跳过前 lag 个无法构成滞后向量的点）
        sample_size = n - lag
        if sample_size < 5:
            continue

        # 受限模型：仅用 target 滞后
        # target[t] ≈ a0 + a1*target[t-1] + ... + a_lag*target[t-lag]
        # 用线性代数求解（正规方程）
        rss_r_model = _rss_multi_regression(
            target, [target], lag_range=(1, lag)
        )
        # 无限制模型：target 滞后 + cause 滞后
        rss_u = _rss_multi_regression(
            target, [target, cause], lag_range=(1, lag)
        )

        if rss_r_model < 1e-15:
            continue

        p = lag          # 额外参数个数
        n_eff = sample_size
        df1 = p
        df2 = n_eff - 2 * lag - 1
        if df2 <= 0:
            continue

        f_stat = ((rss_r_model - rss_u) / df1) / (rss_u / df2) if rss_u > 1e-15 else 0.0
        if f_stat > best_f:
            best_f = f_stat
            best_lag = lag

    return best_f, best_lag


def _rss_multi_regression(
    Y: List[float],
    Xs: List[List[float]],
    lag_range: Tuple[int, int] = (1, 3),
) -> float:
    """多元线性回归的残差平方和（简化版正规方程）。

    Y[t] ≈ β0 + Σ_{X} Σ_{lag} β_{X,lag} * X[t-lag]
    """
    n = len(Y)
    min_lag, max_lag = lag_range
    sample_start = max_lag
    sample_size = n - sample_start
    if sample_size < 3:
        return sum((y - sum(Y) / n) ** 2 for y in Y)

    # 构建设计矩阵
    num_features = len(Xs) * (max_lag - min_lag + 1)
    # X_design[sample_idx][feat_idx]
    X_design: List[List[float]] = []
    Y_design: List[float] = []

    for t in range(sample_start, n):
        row = [1.0]  # 截距项
        for xs in Xs:
            for lag in range(min_lag, max_lag + 1):
                row.append(float(xs[t - lag]))
        X_design.append(row)
        Y_design.append(float(Y[t]))

    # 正规方程: β = (X^T X)^{-1} X^T Y
    k = len(X_design[0])  # 参数个数（含截距）
    # X^T X
    XtX = [[0.0] * k for _ in range(k)]
    XtY = [0.0] * k
    for i in range(sample_size):
        for j in range(k):
            XtY[j] += X_design[i][j] * Y_design[i]
            for l in range(k):
                XtX[j][l] += X_design[i][j] * X_design[i][l]

    # 高斯消元求解
    aug = [XtX[j][:] + [XtY[j]] for j in range(k)]
    beta = _gauss_solve(aug, k)
    if beta is None:
        # 退化：返回总方差
        my = sum(Y_design) / sample_size
        return sum((Y_design[i] - my) ** 2 for i in range(sample_size))

    # 计算残差
    rss = 0.0
    for i in range(sample_size):
        pred = sum(beta[j] * X_design[i][j] for j in range(k))
        rss += (Y_design[i] - pred) ** 2
    return rss


def _gauss_solve(aug: List[List[float]], n: int) -> Optional[List[float]]:
    """高斯消元（部分主元），返回解向量。"""
    for col in range(n):
        # 选主元
        max_row = col
        for row in range(col + 1, n):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]
        if abs(aug[col][col]) < 1e-15:
            return None
        pivot = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= pivot
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


class CausalAnalyzer:
    """因果分析器 — 对单个视频的监控数据做因果推断。

    Usage
    -----
    >>> analyzer = CausalAnalyzer()
    >>> # 喂入结构化记录
    >>> analyzer.feed(record_dicts)
    >>> # 运行分析
    >>> results = analyzer.analyze()
    >>> for feature, score in results['granger_ranking']:
    ...     print(f'{feature}: F={score:.2f}')
    """

    def __init__(self, max_history: int = 500, max_lag: int = 3):
        self._max_history = max_history
        self._max_lag = max_lag
        self._lock = threading.Lock()
        # 每个指标的时间序列
        self._series: Dict[str, List[float]] = {}
        self._timestamps: List[float] = []

    def feed(self, records: List[Dict]):
        """喂入监控记录。

        Parameters
        ----------
        records : list[dict]
            每条记录需包含 view_count 及可选的 like_count 等字段。
            至少需要 'timestamp'（ISO 字符串或 datetime）和 'view_count'。
        """
        with self._lock:
            for rec in records:
                ts = rec.get('timestamp', None)
                if ts is None:
                    continue
                if hasattr(ts, 'timestamp'):
                    ts_float = ts.timestamp()
                elif isinstance(ts, (int, float)):
                    ts_float = float(ts)
                elif isinstance(ts, str):
                    try:
                        ts_float = datetime.fromisoformat(ts).timestamp()
                    except Exception:
                        continue
                else:
                    continue

                self._timestamps.append(ts_float)
                self._series.setdefault('view_count', []).append(
                    float(rec.get('view_count', 0))
                )
                for feat in CAUSAL_FEATURES:
                    val = rec.get(feat, 0)
                    if val is not None:
                        self._series.setdefault(feat, []).append(float(val))

            # 裁剪到最大长度
            if len(self._timestamps) > self._max_history:
                excess = len(self._timestamps) - self._max_history
                self._timestamps = self._timestamps[excess:]
                for key in self._series:
                    self._series[key] = self._series[key][excess:]

    def analyze(self) -> Dict:
        """运行完整因果分析。

        Returns
        -------
        dict : {
            'granger_ranking': [(feature, f_stat, best_lag, label), ...]  # 降序
            'correlation':    {feature: pearson_r, ...},
            'lead_lag':       {feature: best_shift, ...},   # 正=领先，负=滞后
            'key_drivers':    [feature, ...],                # F > threshold 的
            'sample_size':    int,
        }
        """
        with self._lock:
            if len(self._series.get('view_count', [])) < 10:
                return {
                    'granger_ranking': [],
                    'correlation': {},
                    'lead_lag': {},
                    'key_drivers': [],
                    'sample_size': len(self._series.get('view_count', [])),
                }

            target = self._series['view_count']
            n = len(target)

            # 1) Granger 因果检验
            granger_results = []
            for feat in CAUSAL_FEATURES:
                cause = self._series.get(feat, [])
                if len(cause) != n or len(cause) < self._max_lag + 10:
                    continue
                # 检查方差
                c_var = sum((x - sum(cause) / len(cause)) ** 2 for x in cause) / len(cause)
                if c_var < 1e-10:
                    continue
                f_stat, best_lag = _granger_test(target, cause, self._max_lag)
                label = FEATURE_LABELS.get(feat, feat)
                granger_results.append((feat, f_stat, best_lag, label))
            granger_results.sort(key=lambda x: x[1], reverse=True)

            # 2) Pearson 相关性
            correlations = {}
            t_mean = sum(target) / n
            t_std = math.sqrt(sum((x - t_mean) ** 2 for x in target) / max(n - 1, 1))
            if t_std > 1e-10:
                for feat in CAUSAL_FEATURES:
                    cause = self._series.get(feat, [])
                    if len(cause) != n:
                        continue
                    c_mean = sum(cause) / n
                    c_std = math.sqrt(sum((x - c_mean) ** 2 for x in cause) / max(n - 1, 1))
                    if c_std < 1e-10:
                        continue
                    cov = sum((target[i] - t_mean) * (cause[i] - c_mean) for i in range(n)) / n
                    correlations[feat] = cov / (t_std * c_std)

            # 3) Lead-Lag 分析（交叉相关，shift ∈ [-5, 5]）
            lead_lag = {}
            for feat in CAUSAL_FEATURES:
                cause = self._series.get(feat, [])
                if len(cause) != n:
                    continue
                best_shift = 0
                best_corr = 0.0
                for shift in range(-5, 6):
                    if shift >= 0:
                        y = target[shift:]
                        x = cause[:n - shift] if shift > 0 else cause
                    else:
                        x = cause[-shift:]
                        y = target[:n + shift]
                    if len(x) < 5:
                        continue
                    mx = sum(x) / len(x)
                    my = sum(y) / len(y)
                    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / max(len(x) - 1, 1))
                    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / max(len(y) - 1, 1))
                    if sx < 1e-10 or sy < 1e-10:
                        continue
                    c = sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / (sx * sy * len(x))
                    if abs(c) > abs(best_corr):
                        best_corr = c
                        best_shift = shift
                lead_lag[feat] = best_shift

            # 4) 关键驱动因素：F > 3.0 视为显著
            key_drivers = [
                feat for feat, f, lag, _ in granger_results
                if f > 3.0 and lag > 0
            ]

            return {
                'granger_ranking': granger_results,
                'correlation': correlations,
                'lead_lag': lead_lag,
                'key_drivers': key_drivers,
                'sample_size': n,
            }

    @property
    def sample_count(self) -> int:
        with self._lock:
            return len(self._timestamps)

    def clear(self):
        with self._lock:
            self._series.clear()
            self._timestamps.clear()


# ── 全局单例（按 bvid 隔离）───────────────────────
_analyzers: Dict[str, CausalAnalyzer] = {}
_analyzer_lock = threading.Lock()


def get_causal_analyzer(bvid: str) -> CausalAnalyzer:
    """获取指定视频的因果分析器（懒创建）。"""
    with _analyzer_lock:
        if bvid not in _analyzers:
            _analyzers[bvid] = CausalAnalyzer()
        return _analyzers[bvid]
