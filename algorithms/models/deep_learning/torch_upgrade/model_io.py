"""Extracted torch-upgrade helpers."""

import numpy as np

from .context import _torch_available, nn, torch


def _add_derived_features(arr: np.ndarray) -> np.ndarray:
    """为 [N, F] 的特征数组追加 5 个衍生特征，返回 [N, F+5]。

    衍生特征（与 dataset.VideoTimeSeriesDataset 保持一致）：
        - roll_mean_5: 5 步滑动均值
        - roll_std_5: 5 步滑动标准差
        - acceleration: 播放量二阶差分（加速度）
        - relative_pos: 相对时间位置 [0, 1]
        - lifecycle_phase: 生命周期阶段（0=早期, 1=中期, 2=晚期）

    Args:
        arr: 原始特征数组 [N, F]

    Returns:
        扩充后的特征数组 [N, F+5]
    """
    target = arr[:, 0]  # view_count 作为目标列计算衍生特征
    N = arr.shape[0]
    # rolling mean (window=5)
    if N >= 5:
        kernel = np.ones(5, dtype=np.float32) / 5
        roll_mean = np.convolve(target, kernel, mode="same")
    else:
        roll_mean = np.full(N, float(target.mean()))
    # rolling std (window=5)
    if N >= 5:
        roll_std = np.array([float(np.std(target[max(0, i - 2) : min(N, i + 3)])) for i in range(N)], dtype=np.float32)
    else:
        roll_std = np.full(N, float(target.std() or 1.0))
    # 加速度（view_count 的二阶差分）
    velocity = np.diff(target, prepend=target[0]).astype(np.float32)
    accel = np.diff(velocity, prepend=velocity[0]).astype(np.float32)
    # 相对时间位置 [0, 1]
    rel_pos = np.arange(N, dtype=np.float32) / max(N - 1, 1)
    # 生命周期阶段（前20%早期、中间40%中期、后40%晚期）
    lifecycle_phase = np.where(rel_pos < 0.2, 0.0, np.where(rel_pos < 0.6, 1.0, 2.0)).astype(np.float32)
    extras = np.column_stack([roll_mean, roll_std, accel, rel_pos, lifecycle_phase])
    return np.column_stack([arr, extras])


def _build_torch_input(video_data, features, window):
    """构造 z-score 归一化的 [W, F+5] 输入（含衍生特征），并返回速度的均值/方差用于反归一化。

    处理流程：
    1. 从 history_data 提取最近 window 步的特征值
    2. 追加 5 个衍生特征（_add_derived_features）
    3. z-score 归一化（mean/std）
    4. 计算历史速度序列的均值和标准差（用于反归一化预测结果）

    结果按 (history 长度, 末条时间戳, features, window) 缓存在 ``video_data`` 上：
    同一轮预测内 40+ 个 DL 算法共用同一段历史时只构建一次，历史变化即自动失效。

    Args:
        video_data: 视频数据字典
        features: 基础特征列表
        window: 窗口长度

    Returns:
        (归一化数组 [W, F+5], 速度均值, 速度标准差)
        若历史数据不足 3 条则返回 (None, 0.0, 1.0)
    """
    history = video_data.get("history_data", [])
    if len(history) < 3:
        return None, 0.0, 1.0

    last = history[-1]
    memo_key = (
        len(history),
        last.get("timestamp") if isinstance(last, dict) else None,
        tuple(features),
        int(window),
    )
    memo = video_data.get("_torch_input_memo")
    if isinstance(memo, tuple) and memo[0] == memo_key:
        cached_arr, cached_mean, cached_std = memo[1]
        # 返回副本：避免调用方就地改写污染缓存
        return cached_arr.copy(), cached_mean, cached_std

    n = window
    arr = np.zeros((n, len(features)), dtype=np.float32)
    recent = history[-n:] if len(history) >= n else history
    offset = n - len(recent)
    for i, e in enumerate(recent):
        for j, f in enumerate(features):
            arr[offset + i, j] = float(e.get(f, 0) or 0)

    arr_ext = _add_derived_features(arr)
    mean = arr_ext.mean(axis=0, keepdims=True)
    std = arr_ext.std(axis=0, keepdims=True)
    std = np.where(std < 1e-8, 1.0, std)  # 防除零
    arr_n = ((arr_ext - mean) / std).astype(np.float32)

    velocities = _velocity_series(history)
    v_mean = float(np.mean(velocities)) if velocities else 0.0
    v_std = float(np.std(velocities)) if len(velocities) > 1 else 1.0
    if v_std < 1e-8:
        v_std = 1.0
    video_data["_torch_input_memo"] = (memo_key, (arr_n, v_mean, v_std))
    return arr_n, v_mean, v_std


def _velocity_series(history):
    """从历史数据中提取速度序列（每小时播放量增量）。

    逐对计算相邻记录的播放量差除以时间间隔（小时）。

    Args:
        history: 历史数据列表，每项含 view_count 和 timestamp

    Returns:
        速度列表（每小时播放量增量）
    """
    vs = []
    for i in range(1, len(history)):
        t0 = history[i - 1].get("timestamp", 0)
        t1 = history[i].get("timestamp", 0)
        if hasattr(t0, "timestamp"):
            t0 = t0.timestamp()
        if hasattr(t1, "timestamp"):
            t1 = t1.timestamp()
        dt = (float(t1) - float(t0)) / 3600.0  # 转换为小时
        if dt <= 0:
            continue
        v0 = float(history[i - 1].get("view_count", 0) or 0)
        v1 = float(history[i].get("view_count", 0) or 0)
        vs.append((v1 - v0) / dt)  # 每小时增量
    return vs


def _replace_module_by_path(model: "nn.Module", path: str, new_module: "nn.Module"):
    """按点分路径替换子模块（支持 Sequential/ModuleList 的数字索引属性）。"""
    parts = path.split(".")
    parent = model
    for p in parts[:-1]:
        parent = getattr(parent, p)
    setattr(parent, parts[-1], new_module)


def expand_final_projection(model: "nn.Module", horizon: int) -> bool:
    """将模型最终投影 Linear 的输出维从 H 扩到 H+1（A+B 双尺度，forward 零改动）。

    背景：训练目标重构为 y = [短期 H 步稳健增量 ⊕ 长期 1 维平均速率]。模型 head
    输出维由构造参数 horizon 决定 —— 在训练与推理两侧于构造后调用本函数，把唯一的
    out_features == horizon 的 Linear 换成 out_features == horizon + 1 并拷贝原权重，
    模型即可输出 [B, H+1]，无需改任何 forward。

    仅当模型存在**唯一** out_features==horizon 的 Linear（最终预测头）时执行；
    歧义/无该层（DeepAR 双头、NLinear 残差、N-BEATS 块累加等特殊结构）返回 False，
    保持短期单输出（H），由 trainer/推理端对目标/结果按单输出兼容处理。

    Args:
        model: PyTorch 模型实例。
        horizon: 短期预测步数 H（模型原输出宽）。

    Returns:
        bool: True=已扩为 H+1 双输出；False=保持 H 单输出。
    """
    if not _torch_available:
        return False
    import torch.nn as nn

    cand = []
    for path, mod in model.named_modules():
        if isinstance(mod, nn.Linear) and mod.out_features == horizon:
            cand.append((path, mod))
    if len(cand) != 1:
        return False
    path, lin = cand[0]
    new_lin = nn.Linear(lin.in_features, horizon + 1)
    with torch.no_grad():
        new_lin.weight[:horizon] = lin.weight
        new_lin.bias[:horizon] = lin.bias
        # 新增长期维初始化为 0（零初始化避免破坏已有短期预测头）
        nn.init.zeros_(new_lin.weight[horizon:])
        nn.init.zeros_(new_lin.bias[horizon:])
    _replace_module_by_path(model, path, new_lin)
    try:
        setattr(model, "_dual_output", True)
    except Exception:
        pass
    return True


def load_checkpoint_model(model_cls, model_kwargs, state, window, in_features, horizon):
    """按 checkpoint 实际 head 宽度构建模型：兼容 H 宽（旧）与 H+1 宽（A+B 双尺度）。

    策略：
    1. 先以训练 horizon=H 构造模型并直接 load_state_dict —— 命中旧 H 宽 checkpoint 或
       不可扩展模型（H 宽）时成功；
    2. 若因 head 形状不匹配失败，说明 checkpoint 是 H+1 双宽（由训练侧 expand 产生），
       则调用 expand_final_projection 将 head 扩到 H+1 后重载；
    3. 两次都失败则抛出原始异常，由上层按后端降级处理。

    Args:
        model_cls:      PyTorch 模型类。
        model_kwargs:   构造参数（不含 in_features/window/horizon 覆盖）。
        state:          checkpoint state_dict（含可能的 _orig_mod. 前缀）。
        window:         输入窗口。
        in_features:    输入特征数。
        horizon:        短期预测步数 H。

    Returns:
        nn.Module: 加载好权重的模型（head 可能为 H 或 H+1，用 model._dual_output 判断）。
    """
    import inspect

    mk = dict(model_kwargs or {})
    mk["in_features"] = in_features
    sig_params = set(inspect.signature(model_cls).parameters.keys())
    for k, v in (("window", window), ("horizon", horizon)):
        if k in sig_params and k not in mk:
            mk[k] = v

    if isinstance(state, (tuple, list)):
        state = state[0]
    if not isinstance(state, dict):
        raise TypeError(f"checkpoint 格式异常 (type={type(state).__name__})")
    state = {k[len("_orig_mod.") :] if k.startswith("_orig_mod.") else k: v for k, v in state.items()}

    model = model_cls(**mk)
    try:
        model.load_state_dict(state)  # 旧 H 宽 / 不可扩展模型
    except Exception as first_err:
        dual = expand_final_projection(model, horizon)  # 尝试扩为 H+1
        if not dual:
            raise first_err
        try:
            model.load_state_dict(state)
        except Exception:
            raise first_err
    return model


def _generic_result(algorithm, video_data, threshold, velocity, y, model_source=None, long_velocity=None):
    """构造通用的 PredictionResult。

    根据预测速度和剩余播放量计算预测时间及置信度。

    A+B 双尺度：双输出模型的 y 为 [短期 H 步 ⊕ 长期 1 维]。ETA（predicted_hours）
    优先用长期平均速率 long_velocity（更稳，不受短期补量/骤变干扰）；未提供时
    回退短期 velocity。current_velocity 始终报短期 velocity（当前即时速度）。

    Args:
        algorithm: 算法实例
        video_data: 视频数据字典
        threshold: 目标播放量阈值
        velocity: 预测速度（每小时播放量，短期）
        y: 模型原始输出 [H] 或 [H+1]（用于记录元数据）
        model_source: 模型来源标识（global / video_finetune 等）
        long_velocity: 长期平均速率（每小时播放量），双输出模型提供

    Returns:
        PredictionResult 预测结果对象
    """
    from datetime import datetime
    from algorithms.base import PredictionResult

    current_views = int(video_data.get("view_count", 0))
    eta_velocity = long_velocity if (long_velocity is not None and long_velocity > 0) else velocity
    if eta_velocity <= 0:
        predicted_hours = float("inf")
        confidence = 0.0
    else:
        remaining = threshold - current_views
        predicted_hours = 0 if remaining <= 0 else remaining / eta_velocity
        confidence = 0.75 if remaining > 0 else 1.0
    horizon_pred = y.tolist() if hasattr(y, "tolist") else list(y)
    metadata = {
        "reason": "torch_inference",
        "horizon_pred": horizon_pred,
        "method": getattr(algorithm, "algorithm_id", "?") + "_torch",
        "dual_output": long_velocity is not None and long_velocity > 0,
    }
    if model_source:
        metadata["model_source"] = model_source
    return PredictionResult(
        algorithm_name=getattr(algorithm, "name", "?"),
        algorithm_id=getattr(algorithm, "algorithm_id", "?"),
        target_threshold=threshold,
        predicted_hours=predicted_hours,
        confidence=confidence,
        current_views=current_views,
        current_velocity=float(velocity),
        metadata=metadata,
        timestamp=datetime.now(),
    )
