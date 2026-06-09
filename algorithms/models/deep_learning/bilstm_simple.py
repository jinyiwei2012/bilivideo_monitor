"""
BiLSTM双向长短期记忆网络预测模型 (Bidirectional Long Short-Term Memory)
前后双向处理时序，同时捕获历史和未来的上下文依赖。

核心思路：
1. 正向 LSTM：按时间顺序从过去到当前，捕捉因果性趋势
2. 反向 LSTM：逆时间顺序从当前回到过去，捕捉远期的"后见"信息
3. 双向合并：正向隐藏状态 + 反向隐藏状态 = 综合表示
4. 正反互补：正向擅长预测增长、反向擅长识别拐点和修正过拟合

与单向 LSTM 的区别：
- 单向 LSTM：只能看到"历史"
- BiLSTM：同时看到"历史"和"未来视角"，在序列预测中通常优于单向
"""

import math
import numpy as np
from typing import Dict
from datetime import datetime
from algorithms.base import BaseAlgorithm, PredictionResult
from algorithms.models.deep_learning._torch_upgrade import BiLSTMTorchModel, try_torch_predict


class BiLSTMSimpleAlgorithm(BaseAlgorithm):
    """BiLSTM 双向长短期记忆网络算法

    同时从正向和反向处理时间序列，能捕获更丰富的时序模式。
    在播放量预测中，双向处理可以更好地识别趋势拐点。

    正向LSTM: 从过去看到现在
    反向LSTM: 从现在看到过去（重建过去的状态）
    最终输出 = 正向隐藏状态 + 反向隐藏状态

    降级链：torch checkpoint → numpy 双向 LSTM → velocity 兜底
    """

    name = "BiLSTM双向预测"
    algorithm_id = "bilstm_simple"
    description = "双向长短期记忆网络，同时捕获正反向时序依赖"
    category = "深度学习"
    default_weight = 1.25

    def _lstm_cell(self, x: float, h_prev: float, c_prev: float, params: Dict[str, float]) -> tuple:
        """单个 LSTM 单元的前向计算（numpy 简化版）。

        实现标准 LSTM 门控公式：
        - 遗忘门 f：决定丢弃多少旧的记忆
        - 输入门 i：决定写入多少新的信息
        - 候选记忆 c_tilde：创建候选记忆值
        - 输出门 o：决定输出多少记忆信息

        Args:
            x: 当前输入值
            h_prev: 上一个隐藏状态
            c_prev: 上一个细胞状态（记忆）
            params: LSTM 参数字典，含 wf, xf, bf, wi, xi, bi, wc, xc, bc, wo, xo, bo

        Returns:
            (h, c): 新的隐藏状态和细胞状态
        """
        # 遗忘门
        f = 1.0 / (1.0 + math.exp(-(params["wf"] * h_prev + params["xf"] * x + params["bf"])))
        # 输入门
        i = 1.0 / (1.0 + math.exp(-(params["wi"] * h_prev + params["xi"] * x + params["bi"])))
        # 候选记忆
        c_tilde = math.tanh(params["wc"] * h_prev + params["xc"] * x + params["bc"])
        # 记忆更新：遗忘 + 写入
        c = f * c_prev + i * c_tilde
        # 输出门
        o = 1.0 / (1.0 + math.exp(-(params["wo"] * h_prev + params["xo"] * x + params["bo"])))
        # 隐藏状态：输出门 × 激活的记忆
        h = o * math.tanh(c)
        return h, c

    training_window = 10
    """训练窗口长度（时间步数）"""
    training_horizon = 3
    """预测步数"""

    def predict(self, video_data, threshold=100000):
        """预测到达目标播放量所需时间。

        优先使用 torch 模型推理，失败降级到 numpy。

        Args:
            video_data: 视频数据字典，含 view_count, history_data, bvid 等字段
            threshold: 目标播放量阈值，默认 100000

        Returns:
            PredictionResult 预测结果对象
        """
        return try_torch_predict(
            self,
            video_data,
            threshold,
            BiLSTMTorchModel,
            self._numpy_predict,
            window=self.training_window,
            horizon=self.training_horizon,
        )

    def build_model(self):
        """构建训练用的 PyTorch 模型。

        Returns:
            BiLSTMTorchModel 实例
        """
        return BiLSTMTorchModel(in_features=getattr(self, '_training_n_features', 5), horizon=self.training_horizon)

    def get_training_features(self):
        """获取训练使用的特征列表。

        Returns:
            特征名称列表
        """
        return ["view_count", "like_count", "coin_count", "favorite_count", "share_count"]

    def _numpy_predict(self, video_data, threshold=100000):
        """numpy 降级预测 - 双向 LSTM 核心实现。

        流程：
        1. 数据预处理 → 2. 正向 LSTM → 3. 反向 LSTM → 4. 双向合并 →
        5. 趋势估计 → 6. 逐日外推预测 → 7. 构造结果

        Args:
            video_data: 视频数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
        current_views = video_data.get("view_count", 0)
        history = video_data.get("history_data", [])
        velocity = self.calculate_velocity(video_data)

        remaining = threshold - current_views
        if remaining <= 0:
            return self._make_result(0, 1.0, current_views, velocity, {"method": "bilstm"}, threshold)

        if len(history) < 4 or velocity <= 0:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.3,
                current_views,
                velocity,
                {"method": "bilstm", "notes": "insufficient_data"},
                threshold,
            )

        views_sorted = self._extract_views(history)
        if views_sorted is None or len(views_sorted) < 4:
            return self._make_result(
                remaining / velocity,
                0.3,
                current_views,
                velocity,
                {"method": "bilstm_fallback"},
                threshold,
            )

        try:
            return self._predict_impl(views_sorted, current_views, velocity, remaining, threshold, video_data)
        except Exception as e:
            predicted_hours = remaining / velocity if velocity > 0 else float("inf")
            return self._make_result(
                predicted_hours,
                0.0,
                current_views,
                velocity,
                {"error": str(e)},
                threshold,
            )

    def _extract_views(self, history):
        """从历史记录中提取并按时间戳排序播放量序列。

        Args:
            history: 历史数据列表

        Returns:
            排序后的播放量数组，数据不足时返回 None
        """
        timestamps, views_vals = [], []
        for h in history:
            ts = h.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts = ts.timestamp()
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(str(ts)[:19].replace("T", " ")).timestamp()
                except Exception:
                    continue
            timestamps.append(float(ts))
            views_vals.append(float(h.get("view_count", 0)))
        if len(views_vals) < 4:
            return None
        order = np.argsort(timestamps)  # 按时间排序
        return np.array(views_vals, dtype=float)[order]

    def _predict_impl(self, views_sorted, current_views, velocity, remaining, threshold, video_data):
        """执行 BiLSTM 核心预测逻辑。

        正向 LSTM 和反向 LSTM 的参数有细微差异：
        - 正向：基础参数，融入 quality 和 engagement 辅助信号
        - 反向：参数乘以 quality 修正因子，融入 engagement 辅助信号

        逐日外推时：
        - 正向贡献 (fwd_contrib)：速度驱动的指数衰减增长
        - 反向贡献 (rev_contrib)：基于 hidden 状态的修正项，防止过度外推

        Args:
            views_sorted: 排序后的播放量数组
            current_views: 当前播放量
            velocity: 当前速度
            remaining: 剩余播放量
            threshold: 目标阈值
            video_data: 视频数据字典

        Returns:
            PredictionResult 预测结果
        """
        n = len(views_sorted)

        # ── 特征工程 ──────────────────────────────
        self.get_video_age_hours(video_data)
        quality = self.get_quality_score(video_data)
        engagement = self.get_engagement_rate(video_data)

        # 标准化播放量序列（Min-Max 归一化）
        max_val = max(views_sorted)
        min_val = min(views_sorted)
        rng = max_val - min_val if max_val > min_val else 1
        normalized = (views_sorted - min_val) / rng

        # 差分序列（增长率），z-score 标准化
        diffs = np.diff(normalized)
        diff_mean = np.mean(diffs) if len(diffs) > 0 else 0
        diff_std = max(np.std(diffs), 1e-6) if len(diffs) > 0 else 1
        norm_diffs = (diffs - diff_mean) / diff_std if len(diffs) > 0 else np.array([0])

        # ── LSTM参数初始化（正向） ──────────────────
        # 硬编码参数为简化的 numpy forward pass（模拟 PyTorch LSTM 的核心运算）
        fwd_params = {
            "wf": 0.3,
            "xf": 0.2,
            "bf": 0.1,
            "wi": 0.4,
            "xi": 0.3,
            "bi": 0.0,
            "wc": 0.2,
            "xc": 0.1,
            "bc": 0.0,
            "wo": 0.3,
            "xo": 0.2,
            "bo": 0.0,
        }

        # ── 正向LSTM处理 ──────────────────────────
        h_fwd, c_fwd = 0.0, 0.0
        fwd_states = []
        growth_rate = quality * 0.3 + engagement * 0.2  # 辅助增长信号

        for i, x in enumerate(normalized):
            # 将辅助特征融入输入（增强信号）
            x_enhanced = x * (1.0 + growth_rate * 0.1)
            if i > 0:
                x_enhanced += norm_diffs[min(i - 1, len(norm_diffs) - 1)] * 0.05  # 差分修正
            h_fwd, c_fwd = self._lstm_cell(x_enhanced, h_fwd, c_fwd, fwd_params)
            fwd_states.append(h_fwd)

        # ── 反向LSTM处理 ─────────────────────────
        # 反向参数略微调整（乘以 quality 校正因子）
        rev_params = {k: v * (1.0 + 0.1 * quality) for k, v in fwd_params.items()}
        h_rev, c_rev = 0.0, 0.0
        rev_states = []

        for i in range(len(normalized) - 1, -1, -1):  # 逆序处理
            x = normalized[i] * (1.0 + engagement * 0.1)  # 融入互动率信号
            h_rev, c_rev = self._lstm_cell(x, h_rev, c_rev, rev_params)
            rev_states.append(h_rev)
        rev_states.reverse()  # 翻转回正序对齐

        # ── 双向合并 ─────────────────────────────
        combined_states = [f + r for f, r in zip(fwd_states, rev_states)]  # 正反向状态相加
        final_hidden = combined_states[-1] if combined_states else 0

        # ── 趋势速度估计 ──────────────────────────
        # 基于 BiLSTM 隐藏状态的加权（final_hidden ∈ R，反映综合趋势信号）
        trend_signal = 0.5 + final_hidden * 0.3  # 压缩到合理范围
        adjusted_velocity = velocity * max(0.3, trend_signal)

        # ── 逐日外推预测 ─────────────────────────────────
        if adjusted_velocity <= 0:
            adjusted_velocity = velocity * 0.5

        growth_per_day = adjusted_velocity * 24  # 日增长量
        forecast_days = min(365, max(10, int((threshold - current_views) / max(growth_per_day, 1)) + 5))

        # 用双向状态同时预测（考虑正向趋势和反向修正）
        pred_views = float(current_views)
        target_day = None

        for day in range(1, forecast_days + 1):
            # 正向成分: 速度驱动（指数衰减模式）
            fwd_contrib = adjusted_velocity * 24 * (1.0 - math.exp(-day / 14.0))
            # 反向成分: 修正项，防止过度外推（如 hidden 显示衰退则减缓增长）
            rev_contrib = -0.02 * (1.0 - final_hidden) * day * adjusted_velocity * 0.5
            # 综合日增长（正向贡献 + 反向修正，保底为 0）
            daily_growth = fwd_contrib + rev_contrib
            pred_views += max(0, daily_growth)

            if pred_views >= threshold:
                target_day = day
                break

        if target_day is not None and target_day <= 365:
            predicted_hours = target_day * 24
            # 置信度 = 数据量权重 + 隐藏状态权重 + 质量分数
            data_points_conf = min(1.0, n / 15)
            hidden_conf = min(1.0, abs(final_hidden) * 2)
            conf = min(0.9, 0.3 + 0.3 * data_points_conf + 0.2 * hidden_conf + 0.1 * quality)
        else:
            predicted_hours = remaining / adjusted_velocity
            conf = 0.35

        return self._make_result(
            predicted_hours,
            conf,
            current_views,
            adjusted_velocity,
            {
                "method": "bilstm",
                "fwd_hidden": round(float(h_fwd), 4),
                "rev_hidden": round(float(h_rev), 4),
                "combined_hidden": round(float(final_hidden), 4),
                "forecast_horizon": forecast_days,
                "data_points": n,
            },
            threshold,
        )

    def _make_result(self, predicted_hours, confidence, current_views, velocity, metadata, threshold):
        """构造 PredictionResult 预测结果对象。

        Args:
            predicted_hours: 预测的小时数
            confidence: 置信度 [0, 1]
            current_views: 当前播放量
            velocity: 当前速度（每小时播放量）
            metadata: 元数据字典
            threshold: 目标播放量阈值

        Returns:
            PredictionResult 预测结果对象
        """
        metadata.setdefault("method", "bilstm")
        return PredictionResult(
            algorithm_name=self.name,
            algorithm_id=self.algorithm_id,
            target_threshold=threshold,
            predicted_hours=predicted_hours,
            confidence=confidence,
            current_views=current_views,
            current_velocity=velocity,
            metadata=metadata,
            timestamp=datetime.now(),
        )
