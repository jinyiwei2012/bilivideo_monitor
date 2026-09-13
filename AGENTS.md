# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Commands

```bash
# Run the application
python main.py

# Or with environment checks + algorithm init
python run.py

# Lint & format（所有命令须在 conda 环境 bili 中运行）
black --line-length=120 .
flake8 .
python scripts/lint_gate.py       # flake8 + 复杂度棘轮（基线 .lint-baseline.json，当前 0 项 CC>=16）
python scripts/type_gate.py       # mypy 棘轮（基线 .mypy-baseline.json，当前为空 = 零容忍）
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
│   ├── registry.py         — AlgorithmRegistry 门面（126 行）；方法按职责拆入 registry_parts/
│   ├── registry_parts/     — 混入包：_features(特征准备) _ensemble(集成预测)
│   │                         _warmup(回测预热) _models(模型加载) _shared
│   ├── weight_manager.py   — ML-driven per-algorithm weight adjustment
│   ├── online_learner.py   — Hedge online learning + global accuracy aggregation
│   ├── causal_inference.py — Granger causality between metrics
│   ├── bias_correction.py  — Prediction bias correction
│   ├── graph_neural.py     — GCN for video relationship modeling
│   ├── rollout_backtest.py — Time-series cross-validation / rollout backtest
│   ├── data_cleaner.py     — Data cleaning (drop-back, z-score outliers, interpolation)
│   ├── conformal.py        — Conformal prediction for uncertainty intervals (log-domain)
│   ├── training/           — PyTorch training pipeline (trainer, trainer_io, dataset, checkpoint,
│   │                       hf_loader, npu_inference, onnx_exporter, schedulers, device)
│   └── models/             — Algorithm implementations by category
│       ├── simple/         — Linear velocity, weighted velocity
│       ├── growth/         — Logistic, Gompertz, Richards, Weibull, Bass, power law
│       ├── time_series/    — ARIMA, SARIMA, Holt-Winters, Prophet, Kalman, etc.
│       ├── statistical/    — SVR, random forest, Gaussian process, Bayesian, etc.
│       ├── ensemble/       — Voting, stacking, XGBoost, LightGBM, CatBoost, etc.
│       ├── deep_learning/  — LSTM, GRU, TCN, N-BEATS, TimesNet, DLinear, PatchTST, etc.
│       │   └── torch_upgrade/ — 36 个 *TorchModel + runtime/backends/prediction/
│       │                        model_io/layers 子模块（`_torch_upgrade.py` 仅 126 行门面，
│       │                        41 个对外名字保持不变）
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
│   ├── smart_alert.py      — 8 anomaly detectors, confidence-graded (high/medium/low)
│   ├── threshold_escalation.py — Auto threshold escalation after milestone alerts
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
│   ├── main_gui_events.py  — 事件处理器门面（96 行，41 个对外名字保持）
│   ├── main_gui_events_monitor.py — 监控增删/选择/详情
│   ├── main_gui_events_runtime.py — 拉取/定时器/模型/训练/推送/导航
│   ├── main_gui_events_update.py  — 更新对话框/通道切换/下载进度
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
│   ├── training_panel.py   — 训练面板门面（43 行）；逻辑拆入 training_{base,batch,events,
│   │                         jobs,logging,monitoring,refresh,runner,ui_build}.py
│   ├── finetune_panel.py   — 微调面板（472 行）；拆出 finetune_{jobs,progress}.py
│   ├── settings_*.py       — Settings tabs (general/monitor/notif/proxy/account/advanced)
│   └── ...                 — 30+ panels: dialogs, search, training, comparison, etc.
├── utils/                   — Utilities
│   ├── ai_qa.py            — LLM API client (multi-provider)
│   ├── cover_manager.py    — Cover image cache (MD5 dedup, local fallback)
│   ├── crypto.py           — Cookie encryption (Fernet + XOR fallback)
│   ├── file_logger.py      — Time-split log rotation
│   ├── report_exporter.py  — HTML/CSV export + optional AI insight paragraph
│   ├── alert_review.py     — HTML alert review cards (details + mini trend)
│   └── ...
├── scripts/                 — lint_gate.py(flake8+复杂度棘轮) type_gate.py(mypy 棘轮)
│                              sign.py / update_hashes.py / characterize_algorithms.py 等
├── tests/                   — pytest 回归测试（258 passed），核心在 test_refactor_regressions.py
├── config/                  — JSON config load/save with deep-merge defaults
└── data/                    — Runtime data (settings, DBs, covers, logs)
```

### Quality Gates (CI 强制，见 `.github/workflows/code-quality.yml`)

| 门禁 | 命令 | 当前状态 |
|---|---|---|
| 格式 | `black --check --line-length=120 .` | 340 文件全部通过 |
| Lint | `python scripts/lint_gate.py` | flake8 **0 项**；复杂度基线 **0**（无 CC>=16 函数） |
| 类型 | `python scripts/type_gate.py` | mypy **0 错误**（基线为空 = 零容忍） |
| 安全 | `bandit -r . -c pyproject.toml -ll` | Medium/High = 0（137 项均为 Low 严重度，被 `-ll` 过滤） |
| 测试 | `python -m pytest tests/ -q` | **258 passed** |

- **复杂度棘轮**（`.lint-baseline.json`）：按「函数名」记录，新增超标函数即失败；重构后用
  `python scripts/lint_gate.py --update-baseline` 收紧。
- **类型棘轮**（`.mypy-baseline.json`）：按「文件|错误码|消息」记录（**不含行号**，避免重构导致基线失配），
  新增类型错误即失败；当前基线为空。
- **抑制标签政策**：禁止新增 `# type: ignore` 与 `# noqa`。仅以下视为有意设计并被允许：
  第三方可用性探测的 `F401`（torch / transformers / huggingface_hub / socks / intel_extension_for_pytorch /
  torch_directml）、Qt 命名约定覆写的 `N802`（`boundingRect` / `paint` / `paintEvent`）、
  torch 惰性导入守卫块的 `C901`（`if _torch_available or TYPE_CHECKING:`）、CLI 脚本刻意的 `BLE001`。

### Key Design Decisions

1. **Single algorithm base class**: All algorithms inherit `BaseAlgorithm` with `predict(video_data, threshold) → PredictionResult`.

2. **Algorithm auto-discovery**: `AlgorithmRegistry` scans `models/` at import time. Any `.py` file with a class ending in `Algorithm` is auto-registered. Legacy `ModelAlgorithmAdapter` indirection was removed — registry holds algorithm instances directly.

3. **Per-video worker threads**: `ui/monitor/_service.py` spawns one thread per monitored video. Each thread manages its own fetch interval independently.

4. **Per-video SQLite databases**: `data/<BV>/<BV>.db` per video with `monitor_records`, `predictions`, `weekly_scores`, `yearly_scores`, `danmaku`. A central `data/bilibili_monitor.db` mirrors summaries. `sync_from_video_db()` consolidates data.

5. **412 error mitigation**: `BilibiliAPI` implements exponential backoff, curl_cffi TLS impersonation (chrome131), UA rotation, proxy rotation, buvid3/buvid4 generation, bilibili-api-python fallback, and Playwright headless browser last-resort.

6. **Weighted ensemble**: `predict_all()` runs all algorithms in parallel via `ThreadPoolExecutor`, applies coherence-based weight adjustment (deviation from median reduces weight), and produces a `_weighted` ensemble prediction. Its `eta` field comes from a log-space median of per-algorithm ETA forecasts (anchor-threshold aware).

7. **A+B dual-scale training target**: `dataset.py` builds targets `y = [H robust-increment steps ⊕ 1 long-term rate]` — short segment is the robust per-75s increments (MAD-clipped against API freeze/catch-up artifacts), final dim is the real mean rate over the next `long_window` (default 48 ≈ 1h). Both segments share one z-score scaler (velocity's) so inference can denormalize with `v_mean/v_std`. `_torch_upgrade.expand_final_projection()` widens the single final Linear head from H → H+1 (zero-init new dim) for models with a unique projection layer; non-expandable models (N-BEATS/DeepAR/NLinear…) stay single-output and the trainer truncates the target. Inference (`load_checkpoint_model`) auto-detects the checkpoint head width (H or H+1) and expands on demand; the ETA consumes the long-term head when dual, else falls back to the short head.

8. **Layout reuse pattern**: `_clear_header()` and similar methods clear child widgets from layouts but preserve the `QLayout` object for reuse, avoiding `deleteLater()` + recreate cycles that cause `"QLayout already has a layout"` errors.

9. **Incremental UI updates**: Prediction panels use cached widget references to call `setText()` on existing QLabel objects rather than rebuilding widget trees. Stat bar values update without destroying card frames.

10. **巨型模块拆分 + 门面再导出**: 拆分巨型模块时，原模块退化为「门面」，用显式
    `from ... import ...` 或 `__all__` 保持**对外导入面零变**——`algorithms/registry_parts/`（原
    `registry.py` 1333→126 行）、`algorithms/models/deep_learning/torch_upgrade/`（原 `_torch_upgrade.py`
    3051→126 行，41 个对外名字保持）、`ui/main_gui_events_{monitor,runtime,update}.py`（原 1262→96 行，
    41 个名字保持）、`ui/training_*.py`（原 1375→43 行）、`ui/finetune_{jobs,progress}.py`。
    每次拆分都必须通过「导入面校验 + 全量测试」，注册表算法数（**137**）不得变化。

11. **主题令牌中心化**: 所有颜色集中在 `ui/theme.py` 的 `C` 字典（**78 个令牌**：数据系列
    `series`/`series_light`、大屏 `dash_*`、预测投影 `pred_*`、阈值调色板 `thresh_palette`、等级
    `grade_colors`、情感 `sentiment_*`、时段 `period_colors`、热力 `heatmap`、告警框 `warn_*`、
    `on_accent`/`accent_pressed`/`brand_pink`/`probe_fill` 等）。`THEME_LIGHT` 与 `THEME_DARK`
    的键集合必须一致（有守卫测试），`ui/` 内不得再出现硬编码色值。

12. **质量棘轮而非一次性清零**: 复杂度用 `scripts/lint_gate.py`（按函数名），类型用
    `scripts/type_gate.py`（按 文件|错误码|消息）；两者都由 CI 硬性执行，且都支持
    `--update-baseline` 在改善后收紧。`mypy.ini` 额外设置 `explicit_package_bases = True` 与
    `mypy_path = .`，避免「同一文件被识别为两个模块名」而中止检查。

### Algorithm Category Labels

Existing categories: `"速度类"`, `"时间衰减"`, `"扩散模型"`, `"时间序列"`, `"统计模型"`, `"集成学习"`, `"深度学习"`, `"高级分析"`, `"基础"`, `"其他"`.

### Important Notes

- The app uses **PyQt6**, not tkinter/CustomTkinter. All UI code uses QWidget/QLabel/QGraphicsView.
- Theme colors are centralized in `ui/theme.py` → `C` dict. Always reference `C["key"]` rather than hardcoding hex values.
- Database operations use **parameterized queries** — never f-string SQL except for validated column/table name injection.
- `defusedxml` is a **hard dependency** for XXE-safe XML parsing. No fallback to `xml.etree.ElementTree`.
- Background threads dispatch UI updates via `ui/invoker.py` → `invoke()` for thread-safe QWidget operations.
- `cryptography` is required for cookie encryption. XOR fallback logs a warning.
- **禁止抑制**：不要新增 `# type: ignore` / `# noqa`。类型问题要真修（补注解、`cast` 到明确类型、
  `isinstance` 收窄、对动态值显式标注 `Any`），复杂度问题要抽函数而不是忽略。
- 提交前至少跑：`python scripts/lint_gate.py`、`python scripts/type_gate.py`、`python -m pytest tests/ -q`。
