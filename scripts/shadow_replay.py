"""重算法降频调度的影子回放验证（开发工具，不参与运行时）。

对比两条路径在**同一输入**上的输出漂移：
  · full      —— 禁用调度，每轮 137 个算法全部实算（基线）
  · scheduled —— 启用调度，无事件轮次复用上一轮重算法结果（按当前播放量重投影）

两条路径在**独立子进程**中各自从零状态运行相同的轮数，避免权重/窗口历史等
共享状态互相污染。任一「分进程」模式下打印该路径的最终结果 JSON。

用法::

    python scripts/shadow_replay.py            # 驱动：跑全部场景并报告漂移（超阈值则退出码 1）
    python scripts/shadow_replay.py --one full S1
    python scripts/shadow_replay.py --max-drift 0.5

判定阈值（默认，可按需放宽）：prediction 相对漂移 ≤ 0.5%、ETA log 比率 ≤ 2%、confidence 绝对差 ≤ 0.02。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BVID = "BV1Bfjq6LEDi"
ROUNDS = 4
SCENARIOS = ("S1_smooth_1000", "S2_short_30", "S3_burst_500")


def build_history(scenario: str, n: int) -> List[Tuple[Any, int]]:
    """确定性合成历史（与性能实测同一套生成口径，保证可复现）。"""
    import numpy as np
    from datetime import datetime, timedelta

    t0 = datetime.now() - timedelta(seconds=n * 75)
    rng = np.random.default_rng(42)
    burst_at = int(n * 0.55) if scenario == "S3_burst_500" else -1
    ts: List[Any] = []
    vs: List[int] = []
    v = 1000.0
    pend = 0.0
    for i in range(n):
        d = t0 + timedelta(seconds=i * 75)
        daily = 1.0 + 0.35 * np.sin(2 * np.pi * d.hour / 24)
        base = 60.0 * (0.9995**i) * daily
        if 0 <= burst_at <= i < burst_at + 8:  # 历史中段的一次爆发（末点增量恢复正常）
            base *= 12.0
        inc = max(0.0, base + rng.normal(0, base * 0.25))
        if rng.random() < 0.01:
            inc = 0.0
            pend += base
        elif pend > 0 and rng.random() < 0.3:
            inc += pend
            pend = 0.0
        v += inc
        ts.append(d)
        vs.append(int(v))
    return list(zip(ts, vs))


def _scenario_n(scenario: str, round_idx: int) -> int:
    base = {"S1_smooth_1000": 1000, "S2_short_30": 30, "S3_burst_500": 500}[scenario]
    return base + round_idx


def run_one(variant: str, scenario: str) -> Dict[str, Any]:
    """在子进程中运行一条路径，返回最后一轮的输出与耗时。"""
    logging.disable(logging.CRITICAL)

    from algorithms.registry import AlgorithmRegistry as R

    enabled = variant == "scheduled"
    # 间隔设大：模拟「固定时间未到」的连续轮次，从而走复用路径
    R.configure_schedule(enabled=enabled, interval_seconds=3600.0)
    R.initialize()

    thr = [100000, 1000000, 10000000]
    names = ["10万", "100万", "1000万"]
    last_out: Dict[str, Any] = {}
    walls: List[float] = []

    for r in range(ROUNDS):
        history = build_history(scenario, _scenario_n(scenario, r))
        current = history[-1][1]
        t0 = time.perf_counter()
        res = R.predict_all(history, current, BVID, thresholds=thr, threshold_names=names)
        walls.append(time.perf_counter() - t0)
        if r == ROUNDS - 1:
            w = res["_weighted"]
            last_out = {
                "variant": variant,
                "scenario": scenario,
                "prediction": float(w.get("prediction", 0)),
                "current": float(current),
                "eta_hours": (w.get("eta") or {}).get("eta_hours"),
                "eta_n": (w.get("eta") or {}).get("eta_n"),
                "confidence": float(w.get("ensemble_confidence", 0)),
                "valid": int(w.get("valid_algorithms", 0)),
                "na": int(w.get("na_algorithms", 0)),
                "heavy_reused": sum(
                    1
                    for k, v in res.items()
                    if k != "_weighted" and isinstance(v, dict) and (v.get("metadata") or {}).get("scheduled_reuse")
                ),
                "wall_last": round(walls[-1], 3),
                "wall_total": round(sum(walls), 3),
                "stats": R.schedule_stats(),
            }
    return last_out


def _pct(new: float, base: float) -> float:
    return (new - base) / base * 100.0 if base else 0.0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="重算法降频调度的影子回放验证")
    parser.add_argument("--one", nargs=2, metavar=("VARIANT", "SCENARIO"), help="子进程模式：只跑一条路径")
    parser.add_argument("--max-drift", type=float, default=0.5, help="prediction 相对漂移上限(%%), 默认 0.5")
    parser.add_argument("--max-eta-drift", type=float, default=2.0, help="ETA 漂移上限(%%), 默认 2.0")
    parser.add_argument("--max-conf-drift", type=float, default=0.02, help="confidence 绝对差上限, 默认 0.02")
    args = parser.parse_args(argv)

    if args.one:
        variant, scenario = args.one
        print(json.dumps(run_one(variant, scenario), ensure_ascii=False))
        return 0

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    rows: List[Dict[str, Any]] = []
    failed = False
    for scenario in SCENARIOS:
        outs = {}
        for variant in ("full", "scheduled"):
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--one", variant, scenario],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
            if proc.returncode != 0:
                print(f"[FAIL] {scenario}/{variant} 子进程失败:\n{proc.stderr[-2000:]}")
                return 2
            outs[variant] = json.loads(proc.stdout.strip().splitlines()[-1])
        b, s = outs["full"], outs["scheduled"]
        eta_drift = _pct(s["eta_hours"] or 0.0, b["eta_hours"] or 1.0) if b.get("eta_hours") else 0.0
        row = {
            "scenario": scenario,
            "pred_drift_pct": round(_pct(s["prediction"], b["prediction"]), 4),
            "eta_drift_pct": round(eta_drift, 4),
            "conf_drift": round(s["confidence"] - b["confidence"], 4),
            "valid_full": b["valid"],
            "valid_sched": s["valid"],
            "eta_n_full": b["eta_n"],
            "eta_n_sched": s["eta_n"],
            "heavy_reused": s["heavy_reused"],
            "wall_full_s": b["wall_last"],
            "wall_sched_s": s["wall_last"],
        }
        bad = (
            abs(row["pred_drift_pct"]) > args.max_drift
            or abs(row["eta_drift_pct"]) > args.max_eta_drift
            or abs(row["conf_drift"]) > args.max_conf_drift
        )
        row["verdict"] = "FAIL" if bad else "OK"
        failed = failed or bad
        rows.append(row)

    print("=" * 108)
    print("重算法降频 —— 影子回放漂移（full=全量实算基线 vs scheduled=无事件轮次复用重投影）")
    print("=" * 108)
    print(
        f"{'场景':<18}{'pred漂移%':>11}{'ETA漂移%':>10}{'conf差':>9}"
        f"{'有效(full/sched)':>18}{'eta_n(f/s)':>13}{'复用数':>8}{'末轮耗时(full→sched)':>24}{'判定':>7}"
    )
    for r in rows:
        print(
            f"{r['scenario']:<18}{r['pred_drift_pct']:>+11.4f}{r['eta_drift_pct']:>+10.4f}{r['conf_drift']:>+9.4f}"
            f"{r['valid_full']:>9}/{r['valid_sched']:<8}{r['eta_n_full']:>6}/{r['eta_n_sched']:<6}"
            f"{r['heavy_reused']:>8}{r['wall_full_s']:>12.3f}s →{r['wall_sched_s']:>8.3f}s{r['verdict']:>7}"
        )
    print("=" * 108)
    print(f"阈值: pred ≤{args.max_drift}%  ETA ≤{args.max_eta_drift}%  conf ≤{args.max_conf_drift}")
    print("结论: " + ("存在超出阈值的漂移，需人工复核" if failed else "全部场景漂移在阈值内"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
