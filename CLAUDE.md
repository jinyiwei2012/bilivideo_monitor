# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Commands

```bash
# Run the application
python main.py

# Or with environment checks + algorithm init
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

B站视频监控与播放量预测系统 — a **PyQt6** desktop app for monitoring Bilibili videos and predicting view counts using **120+ algorithms**.

### Module Layout

```
main.py / run.py           — Entry points
├── algorithms/             — Prediction engine (120+ algorithms)
│   ├── base.py             — BaseAlgorithm: predict(video_data, threshold) → PredictionResult
│   ├── registry.py         — AlgorithmRegistry: auto-scans models/, parallel predict_all()
│   ├── model_adapter.py    — Bridges old/new predict() interfaces
│   ├── weight_manager.py   — ML-driven per-algorithm weight adjustment
│   ├── online_learner.py   — Hedge online learning
│   ├── causal_inference.py — Granger causality between metrics
│   ├── graph_neural.py     — GCN for video relationship modeling
│   ├── training/           — PyTorch training pipeline (trainer, dataset, checkpoint, hf_loader)
│   ├── conformal.py        — Conformal prediction for uncertainty intervals
│   └── models/             — Algorithm implementations by category
│       ├── simple/         — Linear velocity, weighted velocity
│       ├── growth/         — Logistic, Gompertz, Richards, Weibull, Bass, power law
│       ├── time_series/    — ARIMA, SARIMA, Holt-Winters, Prophet, Kalman, etc.
│       ├── statistical/    — SVR, random forest, Gaussian process, Bayesian, etc.
│       ├── ensemble/       — Voting, stacking, XGBoost, LightGBM, CatBoost, etc.
│       ├── deep_learning/  — LSTM, GRU, TCN, N-BEATS, TimesNet, DLinear, PatchTST, etc.
│       ├── advanced/       — Kalman filter, change point, viral potential, quality score
│       ├── content/        — Content-based algorithms
│       ├── event/          — Event-driven prediction
│       └── frequency/      — Frequency domain algorithms
├── core/                    — Core infrastructure
│   ├── bilibili_api.py     — Bilibili API (Mixin: request + auth + video + up + danmaku)
│   ├── bilibili_request.py — HTTP core: curl_cffi impersonation, UA/proxy rotation
│   ├── bilibili_auth.py    — QR login, password login, cookie management
│   ├── bilibili_video.py   — Video info + danmaku XML parsing
│   ├── bilibili_up.py      — UP主 info fetching
│   ├── notification.py     — Windows toast + QQ Bot (OneBot WS→HTTP fallback)
│   ├── proxy_manager.py    — Proxy rotation, auto-discovery, health checking
│   ├── smart_alert.py      — 8 anomaly detectors with cooldown
│   ├── up_database.py      — UP主 data storage
│   └── database/           — SQLite (per-video DB + central DB)
│       ├── connection.py   — Thread-safe connection context manager
│       ├── video_db.py     — Per-video DB: monitor, predictions, scores, danmaku
│       ├── central_db.py   — Central DB facade
│       ├── central_crud.py — CRUD operations
│       ├── central_query.py— Query interface with parameterized SQL
│       └── central_backup.py— Backup sync + diff detection
├── ui/                      — PyQt6 GUI panels (QWidget + QGraphicsView + QSS)
│   ├── main_gui.py         — Main window, titlebar, navigation, 3-column splitter
│   ├── main_gui_events.py  — Event handlers (add/remove/push/update)
│   ├── main_gui_tick.py    — 1s global tick: countdown, periodic sync, alerts
│   ├── main_gui_data.py    — Data ops (load/save/restore)
│   ├── theme.py            — Dark theme design tokens (C dict)
│   ├── chart.py            — QGraphicsView trend chart with area/line/dots/annotations
│   ├── video_list_panel.py — Left sidebar: QListWidget + custom delegate + async covers
│   ├── detail_panel.py     — Center: header, stat bar, QTabWidget (chart/detail/ratio/danmaku)
│   ├── prediction_panel.py — Right: hero card, interaction rates, history rows, algo stats
│   ├── dashboard_mode.py   — Full-screen rotating dashboard
│   ├── bottom_bar.py       — Status bar + action buttons
│   ├── monitor/            — Monitor service
│   │   ├── _service.py     — Per-video worker threads, fetch+sleep loop
│   │   └── _prediction.py  — Prediction dispatch + surge detection
│   ├── settings_*.py       — Settings tabs (general/monitor/notif/proxy/account/advanced)
│   └── ...                 — 30+ panels: dialogs, search, training, comparison, etc.
├── utils/                   — Utilities
│   ├── ai_qa.py            — LLM API client (multi-provider)
│   ├── cover_manager.py    — Cover image cache (MD5 dedup, local fallback)
│   ├── crypto.py           — Cookie encryption (Fernet + XOR fallback)
│   ├── file_logger.py      — Time-split log rotation
│   └── ...
├── config/                  — JSON config load/save with deep-merge defaults
└── data/                    — Runtime data (settings, DBs, covers, logs)
```

### Key Design Decisions

1. **Single algorithm base class**: All algorithms inherit `BaseAlgorithm` with `predict(video_data, threshold) → PredictionResult`. `ModelAlgorithmAdapter` bridges legacy interfaces.

2. **Algorithm auto-discovery**: `AlgorithmRegistry` scans `models/` at import time. Any `.py` file with a class ending in `Algorithm` is auto-registered.

3. **Per-video worker threads**: `ui/monitor/_service.py` spawns one thread per monitored video. Each thread manages its own fetch interval independently.

4. **Per-video SQLite databases**: `data/<BV>/<BV>.db` per video with `monitor_records`, `predictions`, `weekly_scores`, `yearly_scores`, `danmaku`. A central `data/bilibili_monitor.db` mirrors summaries. `sync_from_video_db()` consolidates data.

5. **412 error mitigation**: `BilibiliAPI` implements exponential backoff, curl_cffi TLS impersonation (chrome131), UA rotation, proxy rotation, buvid3/buvid4 generation, bilibili-api-python fallback, and Playwright headless browser last-resort.

6. **Weighted ensemble**: `predict_all()` runs all algorithms in parallel via `ThreadPoolExecutor`, applies coherence-based weight adjustment (deviation from median reduces weight), and produces a `_weighted` ensemble prediction.

7. **Layout reuse pattern**: `_clear_header()` and similar methods clear child widgets from layouts but preserve the `QLayout` object for reuse, avoiding `deleteLater()` + recreate cycles that cause `"QLayout already has a layout"` errors.

8. **Incremental UI updates**: Prediction panels use cached widget references to call `setText()` on existing QLabel objects rather than rebuilding widget trees. Stat bar values update without destroying card frames.

### Algorithm Category Labels

Existing categories: `"速度类"`, `"时间衰减"`, `"扩散模型"`, `"时间序列"`, `"统计模型"`, `"集成学习"`, `"深度学习"`, `"高级分析"`, `"基础"`, `"其他"`.

### Important Notes

- The app uses **PyQt6**, not tkinter/CustomTkinter. All UI code uses QWidget/QLabel/QGraphicsView.
- Theme colors are centralized in `ui/theme.py` → `C` dict. Always reference `C["key"]` rather than hardcoding hex values.
- Database operations use **parameterized queries** — never f-string SQL except for validated column/table name injection.
- `defusedxml` is a **hard dependency** for XXE-safe XML parsing. No fallback to `xml.etree.ElementTree`.
- Background threads dispatch UI updates via `ui/invoker.py` → `invoke()` for thread-safe QWidget operations.
- `cryptography` is required for cookie encryption. XOR fallback logs a warning.
