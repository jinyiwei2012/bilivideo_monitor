# AGENTS.md

B站视频监控与播放量预测系统 — CustomTkinter desktop app.

## Commands

```bash
# Run
python main.py                          # direct
python run.py                           # conda env check + algorithm init

# Install (order matters!)
python install_torch.py                 # MUST run first (auto-detects CUDA)
pip install -r requirements.txt         # then install everything else

# Lint & format (run before commit)
black --line-length=120 .
flake8 .
mypy core/ algorithms/base.py ui/ utils/ || true
bandit -r . -c pyproject.toml -ll
radon cc -a .
pre-commit run --all-files

# Test
python -m pytest tests/ -v                          # 68 unit tests
```

## Architecture

- **83 prediction algorithms** (auto-discovered from `algorithms/models/` — just drop a `.py` with a class ending in `Algorithm` that inherits `BaseAlgorithm`, no registration needed)
- **Entry point**: `ui/main_gui.py:BilibiliMonitorGUI`. `main.py` imports `from ui import main` and calls `main()`.
- **Database**: `core/database/` is a package (not a single file). Per-video SQLite at `data/<BV>/<BV>.db`, central DB at `data/bilibili_monitor.db`. `Database.sync_from_video_db()` consolidates upward.
- **Per-video worker threads** in `monitor_service.py`: one thread per video, independent fetch intervals.
- **412 mitigation** in `bilibili_api.py`: exponential backoff, UA/proxy rotation, WBI signing, cookie persistence.
- **Weighted ensemble**: `AlgorithmRegistry.predict_all()` runs all algorithms, weights by ML-adjusted confidence, produces `_weighted` result.
- **Conda env**: `bilibili` or `bili` (run.py checks for both). `start.bat` uses `bili`.
- **Settings**: All config in `settings_window.py` (not scattered). Stored as `data/settings.json` + `data/network_config.json`.

## Known Bugs (DO NOT REINTRODUCE)

See `CODE_REVIEW.md` for full report. Critical ones:

| File | Issue | Fix |
|------|-------|-----|
| `core/database/video_db.py:408` | `record.bvid` → `prediction.bvid` | Unused variable in exception handler, causes `NameError` on write failure |
| `core/bilibili_api.py:645` | Calls `_apply_request_interval()` (doesn't exist) → `_ensure_min_interval()` | `get_video_comments` always fails with `AttributeError` |
| `core/central_db.py:194` | `VideoDatabase` never closed after sync | Connection leak: ~11k/day per video |
| `monitor_service.py:161-162` | Online learning compares *previous* prediction vs *current* actual | Inflates accuracy of high-frequency algorithms |

## Category Labels (for new algorithms)

Use `category` class attribute: "速度类", "时间衰减", "扩散模型", "时间序列", "统计模型", "集成学习", "深度学习", "高级分析", "基础", "其他".

## PyInstaller Build

- `BiliMonitor.spec` in root; CI builds on `releases` branch via `.github/workflows/build-exe.yml`
- Hidden imports required: `plyer.platforms.win.notification`, `PIL._tkinter_finder`, `pandas`, `sklearn`, `scipy`, `statsmodels`, `xgboost`, `lightgbm`, `prophet`

## CI

`code-quality.yml` runs on push/PR to `main`/`develop`: black --check, flake8, mypy (allow failure), bandit, radon cc.

## Environment

- Python 3.10+, Windows 10/11 recommended
- Torch NOT in requirements.txt — run `install_torch.py` first (auto-detects CUDA version or falls back to CPU)
- Prophet is optional (known to fail on Windows; `pip install -r requirements.txt --ignore-installed prophet` to skip)
