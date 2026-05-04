# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
python main.py

# Or with environment checks
python run.py

# Lint & format
black --line-length=120 .
flake8 .
mypy core/ algorithms/base.py ui/ utils/ || true
bandit -r . -c pyproject.toml -ll
radon cc -a .

# Pre-commit hooks
pre-commit run --all-files

# Install dependencies
pip install -r requirements.txt
```

## Architecture Overview

B站视频监控与播放量预测系统 — a Tkinter desktop app for monitoring Bilibili videos and predicting view counts using 55 algorithms.

### Module Layout

```
main.py / run.py           — Entry points (run.py checks conda env + inits algorithms)
├── algorithms/             — Prediction engine (55 algorithms)
│   ├── base.py             — BaseAlgorithm: predict(video_data, threshold)->PredictionResult
│   ├── model_adapter.py    — ModelAlgorithmAdapter: bridges models/ algorithms to registry
│   ├── registry.py         — AlgorithmRegistry: auto-scans models/ dir, trains weighted ensemble
│   ├── weight_manager.py   — WeightManager: ML-driven per-algorithm weight adjustment
│   ├── online_learner.py   — Online learning module (Hedge algorithm)
│   ├── causal_inference.py — Causal analysis
│   ├── graph_neural.py     — Graph neural network for video relationships
│   └── models/             — Algorithm implementations by category
│       ├── simple/         — Linear velocity, weighted velocity
│       ├── growth/         — Logistic, Gompertz, Richards, Weibull, Bass diffusion, power law
│       ├── time_series/    — ARIMA, exponential smoothing, Holt-Winters, seasonal decomposition
│       ├── statistical/    — SVR, random forest, Gaussian process, Bayesian regression
│       ├── ensemble/       — Voting, stacking, weighted, gradient boost, XGBoost, CatBoost
│       ├── deep_learning/  — MLP, LSTM, neural network, attention, N-BEATS, TFT, Informer, DLinear, PatchTST
│       └── advanced/       — Kalman filter, change point detection, viral potential, quality score
├── core/
│   ├── database.py         — SQLite: per-video DB (data/<BV>/<BV>.db) + central DB (data/bilibili_monitor.db)
│   ├── bilibili_api.py     — Bilibili API wrapper with 412 retry, proxy rotation, UA rotation
│   └── notification.py     — Windows toast + QQ Bot (OneBot protocol) notifications
├── ui/                     — Tkinter GUI panels
│   ├── main_gui.py         — Main window, 3-column layout controller
│   ├── monitor_service.py  — Business logic: per-video worker threads for independent data fetching
│   ├── theme.py            — Dark/light theme system with design tokens
│   ├── chart.py            — Canvas-based trend chart with threshold lines
│   ├── video_list_panel.py — Left sidebar: video cards
│   ├── detail_panel.py     — Center: video details + chart
│   ├── prediction_panel.py — Right: prediction results
│   └── ...                 — dialogs, comparison, milestones, search, settings, etc.
├── config/                 — Settings (JSON) load/save with defaults
└── utils/                  — File logger (time-split log rotation)
```

### Key Design Decisions

1. **Single algorithm base class**: All algorithms inherit from `BaseAlgorithm` in `algorithms/base.py` with `predict(video_data, threshold) -> PredictionResult`. `ModelAlgorithmAdapter` bridges the two historic interfaces for the `AlgorithmRegistry`.

2. **Algorithm registration**: `AlgorithmRegistry` auto-discovers models by scanning the `models/` directory tree at import time. New algorithms just need to be a `.py` file with a class ending in `Algorithm` that inherits from `BaseAlgorithm` — no manual registration needed.

3. **Per-video worker threads**: `monitor_service.py` spawns one thread per monitored video. Each thread independently manages its fetch interval, so slow API responses for one video don't block others.

4. **Database split**: Each video gets its own SQLite DB at `data/<BV>/<BV>.db` with monitor records, predictions, weekly/yearly scores. A central `data/bilibili_monitor.db` mirrors summaries and stores milestones. `Database.sync_from_video_db()` consolidates per-video data upward.

5. **412 error mitigation**: `BilibiliAPI` implements exponential backoff, User-Agent rotation, proxy rotation, and request interval throttling to handle Bilibili's rate limiting.

6. **Weighted ensemble prediction**: `AlgorithmRegistry.predict_all()` runs every algorithm, weights results by ML-adjusted confidence, and produces a `_weighted` ensemble prediction.

### Algorithm Category Labels

When adding algorithms to `models/<category>/`, use the `category` class attribute to group them. Existing categories: "速度类", "时间衰减", "扩散模型", "时间序列", "统计模型", "集成学习", "深度学习", "高级分析", "基础", "其他".
