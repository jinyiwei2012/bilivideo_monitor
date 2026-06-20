"""
因果推断模块 — 识别影响播放量的关键驱动因素

核心分析方法：
    1. Granger 因果检验（OLS 简化实现）—— 检验各指标是否「领先于」播放量变化
    2. Pearson 相关性分析 —— 各指标与播放量的线性相关程度
    3. Lead-Lag 分析（交叉相关） —— 识别指标领先/滞后于播放量的方向

所有计算均基于纯 Python + math 实现，不依赖 statsmodels 或 numpy。

应用场景：
- 识别哪些互动指标（点赞、投币、分享等）对播放量有预测性影响
- 发现指标之间的时序关系（例如：点赞领先于播放量几天）
- 辅助算法选择：优先选用与播放量因果关联强的特征
"""

import threading
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import math

# 可检验的指标名称（对应 Bilibili API 返回字段）
# 这些字段会从监控记录中提取，用于因果分析
CAUSAL_FEATURES = [
    "like_count",
    "coin_count",
    "share_count",
    "favorite_count",
    "danmaku_count",
    "reply_count",
    "viewers_total",
    "viewers_app",
    "viewers_web",
]

# 字段 → 中文可读标签映射（用于结果展示）
FEATURE_LABELS = {
    "like_count": "点赞",
    "coin_count": "投币",
    "share_count": "分享",
    "favorite_count": "收藏",
    "danmaku_count": "弹幕",
    "reply_count": "评论",
    "viewers_total": "在线人数",
    "viewers_app": "APP观看",
    "viewers_web": "网页观看",
}


def _granger_test(
    target: List[float],
    cause: List[float],
    max_lag: int = 3,
) -> Tuple[float, int]:
    """简化版 Granger 因果检验。

    对每个滞后阶数 k 做 F 检验：
        H0: cause 不 Granger 引起 target
        受限模型（R）：仅用 target 自身滞后预测
        无限制模型（U）：在 R 基础上加入 cause 的滞后项

    Args:
        target: 被预测变量时间序列（播放量）
        cause:  候选因变量时间序列（点赞/投币等）
        max_lag: 最大滞后阶数（默认 3）

    Returns:
        (f_stat, best_lag) —— best_lag = -1 表示不显著
    """
    n = len(target)
    if n < max_lag + 5:
        return 0.0, -1

    best_f = 0.0
    best_lag = -1

    for lag in range(1, max_lag + 1):
        # 跳过首 lag 个无法构造滞后向量的样本点
        sample_size = n - lag
        if sample_size < 5:
            continue

        # 受限模型：仅用 target 的滞后项预测 target
        rss_r_model = _rss_multi_regression(target, [target], lag_range=(1, lag))
        # 无限制模型：target 滞后 + cause 滞后
        rss_u = _rss_multi_regression(target, [target, cause], lag_range=(1, lag))

        if rss_r_model < 1e-15:
            continue

        # 计算自由度
        p = lag  # 额外参数个数（cause 的 lag 个系数）
        n_eff = sample_size  # 有效样本量
        df1 = p
        df2 = n_eff - 2 * lag - 1  # 残差自由度
        if df2 <= 0:
            continue

        # F = (RSS_R - RSS_U) / p  /  (RSS_U / df2)
        # F 值越大 = 加入 cause 后模型改善越显著
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
    """多元线性回归残差平方和（使用正规方程求解）。

    模型形式：
        Y[t] ≈ β0 + Σ_{X in Xs} Σ_{lag} β_{X,lag} · X[t - lag]

    Args:
        Y: 被解释变量（目标序列）
        Xs: 解释变量列表（每个都是长度与 Y 相同的列表）
        lag_range: (min_lag, max_lag) 滞后范围

    Returns:
        残差平方和 RSS（值越小 = 拟合越好）
    """
    n = len(Y)
    min_lag, max_lag = lag_range
    sample_start = max_lag
    sample_size = n - sample_start
    if sample_size < 3:
        mean_y = sum(Y) / n
        return sum((y - mean_y) ** 2 for y in Y)

    # 构建设计矩阵 X 和响应向量 Y
    X_design: List[List[float]] = []
    Y_design: List[float] = []

    for t in range(sample_start, n):
        row = [1.0]  # 截距项（β0）
        for xs in Xs:
            for lag in range(min_lag, max_lag + 1):
                row.append(float(xs[t - lag]))  # 滞后特征
        X_design.append(row)
        Y_design.append(float(Y[t]))

    k = len(X_design[0])  # 参数个数（含截距）
    # 计算 X^T X 和 X^T Y（正规方程矩阵）
    XtX = [[0.0] * k for _ in range(k)]
    XtY = [0.0] * k
    for i in range(sample_size):
        for j in range(k):
            XtY[j] += X_design[i][j] * Y_design[i]
            for col in range(k):
                XtX[j][col] += X_design[i][j] * X_design[i][col]

    # 高斯消元求解正规方程 XtX · β = XtY
    aug = [XtX[j][:] + [XtY[j]] for j in range(k)]
    beta = _gauss_solve(aug, k)
    if beta is None:
        # 矩阵奇异：返回总方差作为 RSS（等价于无效模型）
        my = sum(Y_design) / sample_size
        return sum((Y_design[i] - my) ** 2 for i in range(sample_size))

    # 计算残差平方和：RSS = Σ(y_i - ŷ_i)²
    rss = 0.0
    for i in range(sample_size):
        pred = sum(beta[j] * X_design[i][j] for j in range(k))
        rss += (Y_design[i] - pred) ** 2
    return rss


def _gauss_solve(aug: List[List[float]], n: int) -> Optional[List[float]]:
    """高斯消元法求解线性方程组（部分主元 + 列消去）。

    使用列主元高斯-约当消元（Gauss-Jordan），
    将增广矩阵化为简化行阶梯形后直接读取解。

    Args:
        aug: 增广矩阵 [A | b]，size = n × (n+1)
        n: 变量个数

    Returns:
        解向量（长度为 n），矩阵奇异时返回 None
    """
    for col in range(n):
        # 选主元：找到当前列中绝对值最大的行（提高数值稳定性）
        max_row = col
        for row in range(col + 1, n):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]
        if abs(aug[col][col]) < 1e-15:
            return None  # 矩阵接近奇异，无法求解
        # 主元归一化
        pivot = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= pivot
        # 消去其他行的当前列（使该列其余元素为 0）
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


class CausalAnalyzer:
    """因果分析器 —— 对单个视频的监控数据做因果推断。

    接收结构化监控记录，维护各指标的时间序列，
    提供 Granger 因果检验、Pearson 相关性和 Lead-Lag 分析。

    用法
    ----
    >>> analyzer = CausalAnalyzer()
    >>> analyzer.feed(record_dicts)
    >>> results = analyzer.analyze()
    """

    def __init__(self, max_history: int = 500, max_lag: int = 3):
        """初始化因果分析器。

        Args:
            max_history: 最多保留的记录条数（超过后从头部裁剪）
            max_lag: Granger 检验最大滞后阶数
        """
        self._max_history = max_history
        self._max_lag = max_lag
        self._lock = threading.Lock()  # 线程安全锁
        self._series: Dict[str, List[float]] = {}  # 各指标时间序列
        self._timestamps: List[float] = []          # 时间戳列表

    def feed(self, records: List[Dict]):
        """喂入监控记录，追加到内部时间序列。

        Parameters
        ----------
        records : list[dict]
            每条记录需包含 'timestamp' 和 'view_count'，
            可选 like_count、coin_count 等 CAUSAL_FEATURES 中定义的字段。
        """
        with self._lock:
            for rec in records:
                # 解析时间戳（支持 datetime / float / ISO 字符串三种格式）
                ts = rec.get("timestamp", None)
                if ts is None:
                    continue
                if hasattr(ts, "timestamp"):
                    ts_float = ts.timestamp()
                elif isinstance(ts, (int, float)):
                    ts_float = float(ts)
                elif isinstance(ts, str):
                    try:
                        ts_float = datetime.fromisoformat(ts).timestamp()
                    except Exception as e:
                        import logging; logging.getLogger(__name__).debug("因果推断数据点跳过: %s", e)
                        continue
                else:
                    continue

                self._timestamps.append(ts_float)
                self._series.setdefault("view_count", []).append(float(rec.get("view_count", 0)))
                for feat in CAUSAL_FEATURES:
                    val = rec.get(feat, 0)
                    if val is not None:
                        self._series.setdefault(feat, []).append(float(val))

            # 超过最大长度时从头部裁剪（保留最新数据）
            if len(self._timestamps) > self._max_history:
                excess = len(self._timestamps) - self._max_history
                self._timestamps = self._timestamps[excess:]
                for key in self._series:
                    self._series[key] = self._series[key][excess:]

    def analyze(self) -> Dict:
        """运行完整因果分析，返回分析报告。

        Returns
        -------
        dict: {
            'granger_ranking': [(feature, f_stat, best_lag, label), ...],  # F 值降序
            'correlation':     {feature: pearson_r, ...},                  # Pearson 相关系数
            'lead_lag':        {feature: best_shift, ...},                  # 最佳位移（正=领先）
            'key_drivers':     [feature, ...],                              # 关键驱动因素（F>3）
            'sample_size':     int,                                        # 样本量
        }
        """
        with self._lock:
            if len(self._series.get("view_count", [])) < 10:
                # 样本不足时返回空结果
                return {
                    "granger_ranking": [],
                    "correlation": {},
                    "lead_lag": {},
                    "key_drivers": [],
                    "sample_size": len(self._series.get("view_count", [])),
                }

            target = self._series["view_count"]
            n = len(target)

            # 1) Granger 因果检验：检验各指标是否"领先于"播放量变化
            granger_results = self._analyze_granger(target, n)

            # 2) Pearson 相关性：各指标与播放量的线性相关程度
            correlations = self._analyze_correlation(target, n)

            # 3) Lead-Lag 分析（交叉相关，shift ∈ [-5, 5]）
            lead_lag = self._analyze_lead_lag(target, n)

            # 4) 关键驱动因素：F > 3.0 且 lag > 0 视为显著（经验阈值）
            key_drivers = [feat for feat, f, lag, _ in granger_results if f > 3.0 and lag > 0]

            return {
                "granger_ranking": granger_results,
                "correlation": correlations,
                "lead_lag": lead_lag,
                "key_drivers": key_drivers,
                "sample_size": n,
            }

    def _analyze_granger(self, target, n):
        """对所有候选指标执行 Granger 因果检验，按 F 值降序排列。"""
        granger_results = []
        for feat in CAUSAL_FEATURES:
            cause = self._series.get(feat, [])
            if len(cause) != n or len(cause) < self._max_lag + 10:
                continue
            # 跳过无变化序列（方差 < 1e-10）：无信息的常量序列
            c_var = sum((x - sum(cause) / len(cause)) ** 2 for x in cause) / len(cause)
            if c_var < 1e-10:
                continue
            f_stat, best_lag = _granger_test(target, cause, self._max_lag)
            label = FEATURE_LABELS.get(feat, feat)
            granger_results.append((feat, f_stat, best_lag, label))
        # 按 F 值降序排列：F 越大 = Granger 因果越显著
        granger_results.sort(key=lambda x: x[1], reverse=True)
        return granger_results

    def _analyze_correlation(self, target, n):
        """计算各指标与播放量的 Pearson 相关系数。

        r = Cov(X,Y) / (σ_X · σ_Y)，范围 [-1, 1]
        """
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
                cov = sum((target[i] - t_mean) * (cause[i] - c_mean) for i in range(n)) / max(n - 1, 1)
                correlations[feat] = cov / (t_std * c_std)
        return correlations

    def _analyze_lead_lag(self, target, n):
        """对每个指标做滑动交叉相关，找到使相关系数绝对值最大的位移量。

        正 shift → 指标领先于播放量（cause → effect）；
        负 shift → 指标滞后于播放量（effect first）。
        位移范围 [-5, 5]，即最多领先/滞后 5 个时间步。
        """
        lead_lag = {}
        for feat in CAUSAL_FEATURES:
            cause = self._series.get(feat, [])
            if len(cause) != n:
                continue
            best_shift = 0
            best_corr = 0.0
            for shift in range(-5, 6):
                if shift >= 0:
                    y = target[shift:]      # 播放量前移
                    x = cause[: n - shift] if shift > 0 else cause
                else:
                    x = cause[-shift:]      # 因变量前移
                    y = target[: n + shift]
                if len(x) < 5:
                    continue
                # 计算 Pearson 相关系数
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
        return lead_lag

    @property
    def sample_count(self) -> int:
        """当前已记录的时间点数量。"""
        with self._lock:
            return len(self._timestamps)

    def clear(self):
        """清空所有内部时间序列数据（重置分析器）。"""
        with self._lock:
            self._series.clear()
            self._timestamps.clear()


# ── 全局单例（按 bvid 隔离）───────────────────────
# 每个视频拥有独立的 CausalAnalyzer 实例，
# 避免不同视频的监控数据相互混淆
_analyzers: Dict[str, CausalAnalyzer] = {}
_analyzer_lock = threading.Lock()


def get_causal_analyzer(bvid: str) -> CausalAnalyzer:
    """获取指定视频的因果分析器（惰性创建，每个 bvid 独立实例）。"""
    with _analyzer_lock:
        if bvid not in _analyzers:
            _analyzers[bvid] = CausalAnalyzer()
        return _analyzers[bvid]
