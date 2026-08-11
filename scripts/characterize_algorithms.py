"""特征化测试 —— 锁定 136 个算法的预测输出, 用于重构等价性验证。

用法:
    python scripts/characterize_algorithms.py run [--out data/characterize_baseline.json]
        跑全部算法, 输出快照 JSON (默认 stdout)

    python scripts/characterize_algorithms.py diff data/characterize_baseline.json [--tol 1e-6]
        对比当前输出与基线, 打印差异, 有差异返回退出码 1

设计:
    - 固定样本: 40 个历史点 (确定性随机, seed 固定), 时间间隔 6h
    - 逐算法调用 predict(): 自动识别旧签名 (current_views, target_views, history_data, video_info)
      与新签名 (video_data, threshold), 统一规范化输出
    - 规范化: 元组 (seconds, confidence) → predicted_hours = seconds/3600
      (与 model_adapter._parse_result 语义一致)
    - predict_all 全管线快照 (含 _weighted 集成结果)
    - 非确定性算法 (随机种子) 由调用前固定 seed 保证可复现
"""
from __future__ import annotations

import inspect
import json
import random
import sys
import os
import time
from datetime import datetime, timedelta

import numpy as np

# 确保项目根目录可导入 (脚本位于 scripts/ 子目录)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def build_sample_history(n: int = 40, base: int = 12000, growth: int = 800, seed: int = 7):
    """构造确定性样本历史: [(datetime, view), ...], 时间间隔 6 小时。"""
    rng = np.random.default_rng(seed)
    now = datetime(2026, 8, 1, 12, 0, 0)
    history = []
    views = base
    for i in range(n):
        views += growth + int(rng.integers(-200, 400))
        views = max(views, 100)
        ts = now - timedelta(hours=(n - i) * 6)
        history.append((ts, int(views)))
    return history


def build_video_data(history, current_value: int, bvid: str = "BV1GJ411x7hQ"):
    """用 registry 的 _prepare_video_data 构造标准 video_data (与生产一致)。"""
    from algorithms.registry import AlgorithmRegistry

    return AlgorithmRegistry._prepare_video_data(history, current_value, bvid=bvid)


def normalize(raw):
    """把 predict() 原始返回规范化为 {predicted_hours, confidence, velocity, null}。

    约定: None 与 PredictionResult(predicted_hours=-1, confidence=0.0) 均视为
    "无效预测" (null=True), 使旧签名 None 返回迁移到新签名后可比对。
    """
    if raw is None:
        return {"predicted_hours": -1, "confidence": 0.0, "current_velocity": 0, "null": True}
    if hasattr(raw, "to_dict"):
        d = raw.to_dict()
        norm = {
            "predicted_hours": d["predicted_hours"],
            "confidence": round(d["confidence"], 10),
            "current_velocity": d["current_velocity"],
        }
        if d["predicted_hours"] == -1 and d["confidence"] == 0.0:
            norm["null"] = True
        return norm
    if isinstance(raw, tuple) and len(raw) == 2:
        seconds, conf = raw
        ph = None
        if seconds is not None and seconds != float("inf"):
            ph = seconds / 3600.0
        return {"predicted_hours": ph, "confidence": round(conf, 10), "tuple": True}
    return {"raw": repr(raw)}


def iter_algorithms():
    """返回 (registry_key, raw_algo) 列表。"""
    from algorithms.registry import AlgorithmRegistry

    AlgorithmRegistry.initialize()
    for key, adapter in AlgorithmRegistry._algorithms.items():
        algo = getattr(adapter, "algo", adapter)
        yield key, algo


def call_predict(algo, video_data, current_value, history):
    """按算法签名正确调用 predict, 返回 (规范化结果, 耗时秒)。"""
    sig = inspect.signature(algo.predict)
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name != "self"
    ]
    # 固定随机种子, 保证可复现
    random.seed(42)
    np.random.seed(42)
    t0 = time.perf_counter()
    if len(positional) >= 4:  # 旧签名 predict(current_views, target_views, history_data, video_info)
        history_data = [
            {"view": v, "like": max(0, v // 100), "coin": max(0, v // 1000),
             "favorite": max(0, v // 500), "share": max(0, v // 2000)}
            for _, v in history
        ]
        raw = algo.predict(current_value, 100000, history_data, video_data)
    else:  # 新签名 predict(video_data, threshold)
        raw = algo.predict(video_data, 100000)
    elapsed = time.perf_counter() - t0
    return normalize(raw), elapsed


def run_all() -> dict:
    from algorithms.registry import AlgorithmRegistry

    history = build_sample_history()
    current_value = history[-1][1]
    video_data = build_video_data(history, current_value)

    out = {}
    t_total0 = time.perf_counter()
    for key, algo in iter_algorithms():
        name = getattr(algo, "name", key)
        try:
            norm, elapsed = call_predict(algo, video_data, current_value, history)
            out[key] = {"name": name, "result": norm, "elapsed": round(elapsed, 4)}
        except Exception as e:  # noqa: BLE001
            out[key] = {"name": name, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    out["__per_algo_total__"] = round(time.perf_counter() - t_total0, 3)

    # ── predict_all 全管线快照 ──
    try:
        AlgorithmRegistry.reset()
        AlgorithmRegistry.initialize()
        t_pa0 = time.perf_counter()
        res = AlgorithmRegistry.predict_all(history, current_value, bvid="BV1GJ411x7hQ")
        out["__predict_all_elapsed__"] = round(time.perf_counter() - t_pa0, 3)
        allres = {}
        for k, r in res.items():
            if k == "_weighted":
                allres["_weighted"] = {
                    "prediction": round(r.get("prediction", 0), 6),
                    "ensemble_confidence": r.get("ensemble_confidence"),
                    "surge_correction_applied": r.get("surge_correction_applied", False),
                }
            else:
                allres[k] = {
                    "prediction": round(r.get("prediction", 0), 6),
                    "confidence": round(r.get("confidence", 0), 6),
                    "predicted_hours": r.get("predicted_hours"),
                    "na": r.get("metadata", {}).get("na", False),
                    "error": r.get("error"),
                }
        out["__predict_all__"] = allres
    except Exception as e:  # noqa: BLE001
        out["__predict_all__"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        AlgorithmRegistry.reset()
    return out


def _clean(value):
    """递归清洗 NaN/Inf/numpy 标量为可 JSON 序列化表示。"""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, tuple):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (np.ndarray,)):
        return [_clean(v) for v in value.tolist()]
    if isinstance(value, float):
        if value != value:  # NaN
            return "NaN"
        if value == float("inf"):
            return "Inf"
        if value == float("-inf"):
            return "-Inf"
        return value
    return value


def run_cmd(out_path: str | None) -> int:
    out = _clean(run_all())
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"✅ 已保存基线: {out_path} ({len(out)} 项)")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


def diff_cmd(baseline_path: str, tol: float) -> int:
    with open(baseline_path, encoding="utf-8") as fh:
        baseline = json.load(fh)
    current = _clean(run_all())

    mismatches = []
    all_keys = set(baseline) | set(current)
    for key in sorted(all_keys):
        if key.startswith("__"):
            continue  # 元数据键 (计时/汇总) 单独处理
        b, c = baseline.get(key), current.get(key)
        if b is None or c is None:
            mismatches.append((key, "缺失", b is None, c is None))
            continue
        if "error" in b or "error" in c:
            if b.get("error") != c.get("error"):
                mismatches.append((key, "错误", b.get("error"), c.get("error")))
            continue
        br, cr = b.get("result"), c.get("result")
        if br is None or cr is None:
            mismatches.append((key, "result缺失", br, cr))
            continue
        for field in ("predicted_hours", "confidence", "current_velocity"):
            bv, cv = br.get(field), cr.get(field)
            if bv is None or cv is None:
                if bv != cv:
                    mismatches.append((key, f"{field}空值", bv, cv))
                continue
            if isinstance(bv, (int, float)) and isinstance(cv, (int, float)):
                if abs(bv - cv) > tol * max(1.0, abs(bv)):
                    mismatches.append((key, field, bv, cv))
            elif bv != cv:
                mismatches.append((key, field, bv, cv))
        if br.get("null") != cr.get("null"):
            mismatches.append((key, "null标志", br, cr))

    # predict_all 快照对比 (宽松: 仅 prediction 关键值)
    bp, cp = baseline.get("__predict_all__", {}), current.get("__predict_all__", {})
    if "error" not in bp and "error" not in cp:
        if bp.get("_weighted", {}).get("prediction") != cp.get("_weighted", {}).get("prediction"):
            mismatches.append(("__predict_all__/_weighted.prediction",
                               bp.get("_weighted", {}).get("prediction"),
                               cp.get("_weighted", {}).get("prediction")))
        for k in set(bp) - set(cp) | set(cp) - set(bp):
            if k != "_weighted":
                mismatches.append((f"__predict_all__/{k}", "存在性差异", k in bp, k in cp))
    else:
        if bp.get("error") != cp.get("error"):
            mismatches.append(("__predict_all__", "错误", bp.get("error"), cp.get("error")))

    # ── 性能对比: predict_all 耗时不得劣化 3 倍以上, 且必须 < 75s ──
    be = baseline.get("__predict_all_elapsed__", 0) or 0
    ce = current.get("__predict_all_elapsed__", 0) or 0
    print(f"性能: predict_all 基线={be}s 当前={ce}s")
    if ce > 75:
        mismatches.append(("__predict_all_elapsed__", "超过75s预算", be, ce))
    elif be > 0 and ce > be * 3 and ce > be + 1.0:
        mismatches.append(("__predict_all_elapsed__", "性能劣化>3x", be, ce))

    if mismatches:
        print(f"❌ 发现 {len(mismatches)} 处差异 (tol={tol}):")
        for key, field, bv, cv in mismatches[:40]:
            print(f"  {key} [{field}]: 基线={bv!r} 当前={cv!r}")
        if len(mismatches) > 40:
            print(f"  ... 共 {len(mismatches)} 处")
        return 1
    print(f"✅ 无差异 (tol={tol})")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    mode = args[0]
    if mode == "run":
        out_path = None
        if "--out" in args:
            out_path = args[args.index("--out") + 1]
        return run_cmd(out_path)
    if mode == "diff":
        if len(args) < 2:
            print("用法: python scripts/characterize_algorithms.py diff <baseline.json> [--tol 1e-6]")
            return 1
        tol = 1e-6
        if "--tol" in args:
            tol = float(args[args.index("--tol") + 1])
        return diff_cmd(args[1], tol)
    print(f"未知模式: {mode}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
