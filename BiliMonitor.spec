# -*- mode: python ; coding: utf-8 -*-
"""
BiliMonitor PyInstaller spec
=============================
Known issues & solutions:
  1. 97 algorithm modules are dynamically discovered (os.walk + importlib)
     → all listed in hiddenimports
  2. torch is ~2.5GB → use onedir mode, exclude unused backends
  3. curl_cffi bundles libcurl DLLs → binaries=[] auto-detects .pyd/.dll
  4. Tcl/Tk must be bundled for customtkinter → Tree + collect_all
  5. scipy/sklearn/statsmodels have C extensions → collect_all
  6. matplotlib backend → 'matplotlib.backends.backend_tkagg'
  7. Bilibili API async submodules → 'bilibili_api' collect_all
  8. Runtime data/ directory created on first run → not bundled
"""

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

PROJECT_ROOT = os.path.dirname(os.path.abspath("main.py"))

# ── Excluded packages (torch is huge; keep only what we use) ──────────────
EXCLUDES = [
    "IPython",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    "nbformat",
    "nbconvert",
    "notebook",
    "qtconsole",
    "ipykernel",
    "torchvision",
    "torchaudio",
    "torchtext",
    "torch.distributed",
    "torch.testing",
    "torch.profiler",
    "torch.onnx",
    "torch._dynamo",
    "tensorflow",
    "tensorboard",
    "matplotlib.test",
    "matplotlib.tests",
    "plotly",
    "dash",
    "sphinx",
    "sphinxcontrib",
    "docutils",
]

# ── Binary / data discovery ───────────────────────────────────────────────
datas = []
binaries = []
hiddenimports = [
    # ── Standard library (frozen apps miss these) ──
    "encodings",
    "asyncio",
    "sqlite3",
    "queue",
    "concurrent",
    "concurrent.futures",
    "xml.etree.ElementTree",
    "xml.etree",
    "http.cookies",
    "http",
    "json",
    "base64",
    "hashlib",
    "hmac",
    "uuid",
    "datetime",
    "copy",
    "io",
    "csv",
    "tempfile",
    "shutil",
    "fnmatch",
    "glob",
    "pathlib",
    "importlib",
    "importlib.metadata",
    "importlib.resources",
    "threading",
    "subprocess",
    "platform",
    "socket",
    "ssl",
    "struct",
    "textwrap",
    "webbrowser",
]

# ── GUI & notification (tkinter + plyer) ──
hiddenimports += [
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.filedialog",
    "tkinter.scrolledtext",
    "_tkinter",
    "PIL",
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageFilter",
    "PIL.ImageOps",
    "plyer",
    "plyer.platforms.win.notification",
    "plyer.platforms.win",
    "plyer.platforms",
]

# ── HTTP & network (Bilibili API + curl_cffi + WS) ──
hiddenimports += [
    "bilibili_api",
    "bilibili_api.video",
    "bilibili_api.user",
    "bilibili_api.search",
    "bilibili_api.credential",
    "bilibili_api.exceptions",
    "bilibili_api.network",
    "bilibili_api.article",
    "bilibili_api.live",
    "bilibili_api.relation",
    "bilibili_api.dynamic",
    "curl_cffi",
    "curl_cffi.requests",
    "requests",
    "requests.adapters",
    "urllib3",
    "urllib3.util",
    "urllib3.connectionpool",
    "urllib3.response",
    "websockets",
    "websockets.sync",
    "aiohttp",
    "aiohttp.web",
    "schedule",
    "asyncio_mqtt",
    "PySocks",
]

# ── Data science & ML ──
hiddenimports += [
    "numpy",
    "numpy.core._methods",
    "numpy.lib.format",
    "scipy",
    "scipy.integrate",
    "scipy.optimize",
    "scipy.special",
    "scipy.stats",
    "scipy.spatial",
    "scipy.spatial.distance",
    "scipy.interpolate",
    "scipy.linalg",
    "scipy.signal",
    "scipy.ndimage",
    "scipy.cluster",
    "scipy.fft",
    "scipy.sparse",
    "pandas",
    "pandas._libs",
    "pandas.io.formats",
    "sklearn",
    "sklearn.ensemble",
    "sklearn.svm",
    "sklearn.preprocessing",
    "sklearn.model_selection",
    "sklearn.metrics",
    "sklearn.utils",
    "sklearn.gaussian_process",
    "sklearn.neighbors",
    "statsmodels",
    "statsmodels.api",
    "statsmodels.tsa.api",
    "statsmodels.tsa.arima.model",
    "statsmodels.tsa.statespace",
    "statsmodels.tsa.holtwinters",
    "statsmodels.tsa.seasonal",
    "statsmodels.regression",
    "statsmodels.nonparametric",
    "statsmodels.stats",
    "xgboost",
    "lightgbm",
    "catboost",
    "prophet",
    "prophet.forecaster",
    "ngboost",
    "ngboost.distns",
    "ngboost.scores",
    "ngboost.learners",
]

# ── torch (keep only what we use) ──
hiddenimports += [
    "torch",
    "torch._C",
    "torch._C._nn",
    "torch._C._fft",
    "torch._C._linalg",
    "torch._C._sparse",
    "torch.utils",
    "torch.utils.data",
    "torch.optim",
    "torch.nn",
    "torch.nn.modules",
    "torch.nn.functional",
    "torch.distributions",
    "torch.cuda",
    "torch.backends",
    "torch.backends.cuda",
    "torch.backends.mps",
    "torch.backends.mkl",
]

# ── HuggingFace (MOIRAI / Lag-Llama) ──
hiddenimports += [
    "transformers",
    "transformers.models",
    "huggingface_hub",
    "huggingface_hub.hf_api",
    "torchmetrics",
    "gluonts",
    "gluonts.model",
    "gluonts.transform",
    "uni2ts",
]

# ── All 97 algorithm modules (dynamically discovered at runtime, must be listed) ──
ALGORITHM_MODULES = [
    "algorithms.models.advanced.bass_diffusion",
    "algorithms.models.advanced.causal_impact",
    "algorithms.models.advanced.change_point_detection",
    "algorithms.models.advanced.distdf_align",
    "algorithms.models.advanced.engagement_rate",
    "algorithms.models.advanced.fourier_wavelet",
    "algorithms.models.advanced.hawkes_process",
    "algorithms.models.advanced.hierarchical_bayes",
    "algorithms.models.advanced.kalman_filter",
    "algorithms.models.advanced.lifecycle_modeling",
    "algorithms.models.advanced.like_momentum",
    "algorithms.models.advanced.multi_task_simple",
    "algorithms.models.advanced.quality_score",
    "algorithms.models.advanced.share_velocity",
    "algorithms.models.advanced.sird_model",
    "algorithms.models.advanced.survival_analysis",
    "algorithms.models.advanced.viral_potential",
    "algorithms.models.deep_learning.attention_mechanism",
    "algorithms.models.deep_learning.bilstm_simple",
    "algorithms.models.deep_learning.chronos_base",
    "algorithms.models.deep_learning.cnn_image",
    "algorithms.models.deep_learning.cnn_lstm_hybrid",
    "algorithms.models.deep_learning.deepar_simple",
    "algorithms.models.deep_learning.diffusion_ts",
    "algorithms.models.deep_learning.dlinear_simple",
    "algorithms.models.deep_learning.gru_simple",
    "algorithms.models.deep_learning.informer_simple",
    "algorithms.models.deep_learning.itransformer_simple",
    "algorithms.models.deep_learning.knf",
    "algorithms.models.deep_learning.lag_llama",
    "algorithms.models.deep_learning.lstm_simple",
    "algorithms.models.deep_learning.mamba_s6_simple",
    "algorithms.models.deep_learning.mar_bilstm",
    "algorithms.models.deep_learning.mlp_predictor",
    "algorithms.models.deep_learning.moirai",
    "algorithms.models.deep_learning.n_beats_simple",
    "algorithms.models.deep_learning.neural_network_simple",
    "algorithms.models.deep_learning.patch_tst_simple",
    "algorithms.models.deep_learning.scinet_simple",
    "algorithms.models.deep_learning.tcn_simple",
    "algorithms.models.deep_learning.tft_simple",
    "algorithms.models.deep_learning.tide_simple",
    "algorithms.models.deep_learning.time_moe_simple",
    "algorithms.models.deep_learning.timesfm_simple",
    "algorithms.models.deep_learning.timess_net_simple",
    "algorithms.models.deep_learning.tsmixer_simple",
    "algorithms.models.deep_learning._torch_upgrade",
    "algorithms.models.ensemble.adaptive_boosting",
    "algorithms.models.ensemble.bagging_simple",
    "algorithms.models.ensemble.cascade_ensemble",
    "algorithms.models.ensemble.catboost_simple",
    "algorithms.models.ensemble.coin_boost",
    "algorithms.models.ensemble.ensemble_average",
    "algorithms.models.ensemble.ensemble_stacking",
    "algorithms.models.ensemble.ensemble_voting",
    "algorithms.models.ensemble.ensemble_weighted",
    "algorithms.models.ensemble.extra_trees_simple",
    "algorithms.models.ensemble.gradient_boost_simple",
    "algorithms.models.ensemble.lightgbm_simple",
    "algorithms.models.ensemble.ngboost_simple",
    "algorithms.models.ensemble.tabnet_simple",
    "algorithms.models.ensemble.weighted_velocity",
    "algorithms.models.ensemble.xgboost_simple",
    "algorithms.models.growth.exponential_growth",
    "algorithms.models.growth.gompertz",
    "algorithms.models.growth.gompertz_growth",
    "algorithms.models.growth.logarithmic_growth",
    "algorithms.models.growth.logistic_growth",
    "algorithms.models.growth.power_law",
    "algorithms.models.growth.richards_curve",
    "algorithms.models.growth.weibull_growth",
    "algorithms.models.simple.linear_velocity",
    "algorithms.models.statistical.bayesian_regression",
    "algorithms.models.statistical.dtw_knn",
    "algorithms.models.statistical.elasticnet_regression",
    "algorithms.models.statistical.gaussian_process",
    "algorithms.models.statistical.huber_regression",
    "algorithms.models.statistical.poisson_regression",
    "algorithms.models.statistical.quantile_regression",
    "algorithms.models.statistical.random_forest_simple",
    "algorithms.models.statistical.svr_predictor",
    "algorithms.models.statistical.theil_sen_regression",
    "algorithms.models.statistical.tsfc_classification",
    "algorithms.models.statistical.upcaster_history_bayesian",
    "algorithms.models.time_series.arima_simple",
    "algorithms.models.time_series.comment_trend",
    "algorithms.models.time_series.exponential_decay",
    "algorithms.models.time_series.exponential_smoothing",
    "algorithms.models.time_series.garch_simple",
    "algorithms.models.time_series.holt_winters",
    "algorithms.models.time_series.linear_growth",
    "algorithms.models.time_series.markov_switching",
    "algorithms.models.time_series.moving_average",
    "algorithms.models.time_series.mstl_decomposition",
    "algorithms.models.time_series.multi_seasonal_decomposition",
    "algorithms.models.time_series.narx_simple",
    "algorithms.models.time_series.prophet_simple",
    "algorithms.models.time_series.sarima_simple",
    "algorithms.models.time_series.seasonal_decomposition",
    "algorithms.models.time_series.tbats_simple",
    "algorithms.models.time_series.theta_forecast",
    "algorithms.models.time_series.trend_extrapolation",
    "algorithms.models.time_series.trend_regression",
    "algorithms.models.time_series.weighted_moving_average",
]
hiddenimports += ALGORITHM_MODULES

# ── Application packages (auto-collect) ──
for pkg in ("customtkinter", "bilibili_api", "ui", "core", "algorithms", "utils"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# Extra safety: bilibili_api data files (hook-bilibili_api.py also handles this)
from PyInstaller.utils.hooks import collect_data_files
datas += collect_data_files("bilibili_api")

# ── Extra data: matplotlib mpl-data ──
datas += collect_data_files("matplotlib", include_py_files=True)

# ── Tcl/Tk runtime data (required for frozen customtkinter) ──
import tkinter

tk_root = os.path.dirname(tkinter.__file__)
for d in ("tcl", "tk"):
    src = os.path.join(tk_root, d)
    if os.path.isdir(src):
        for root, dirs, files in os.walk(src):
            for f in files:
                src_file = os.path.join(root, f)
                rel_path = os.path.relpath(os.path.dirname(src_file), os.path.dirname(tk_root))
                datas.append((src_file, rel_path))

# ── config/ directory (mirror project layout) ──
for dir_name in ("config",):
    src = os.path.join(PROJECT_ROOT, dir_name)
    if os.path.isdir(src):
        for root, dirs, files in os.walk(src):
            for f in files:
                src_file = os.path.join(root, f)
                rel_path = os.path.relpath(os.path.dirname(src_file), PROJECT_ROOT)
                datas.append((src_file, rel_path))

# ── cryptography OpenSSL DLLs ──
try:
    import cryptography
except ImportError:
    pass

# ── PyInstaller Analysis ─────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[PROJECT_ROOT],  # uses hook-bilibili_api.py from project root
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BiliMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["*.pyd", "*.dll"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["*.pyd", "*.dll"],
    name="BiliMonitor",
)
