# -*- mode: python ; coding: utf-8 -*-
"""
BiliMonitor PyInstaller spec
=============================
Known issues & solutions:
  1. 算法模块由 registry 运行时动态发现 (os.walk + importlib)
     → 全部列入 hiddenimports 以确保冻结包内可导入
   2. torch 约 2.5GB → onefile 模式 + 排除未用后端
  3. curl_cffi 自带 libcurl DLL → binaries=[] 自动探测 .pyd/.dll
  4. GUI 为 PyQt6 → collect_all("ui") + 显式 PyQt6 子模块
  5. scipy/sklearn/statsmodels 含 C 扩展 → collect_all
  6. bilibili_api 异步子模块 → collect_all("bilibili_api")
  7. 运行时 data/ 目录首次启动创建 → 不打入
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

# ── GUI (PyQt6) & notification (plyer) ──
hiddenimports += [
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PIL",
    "PIL.Image",
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

# ── Dynamically discovered algorithms ──────────────────────────────────────
# The registry imports algorithm modules at runtime.  Keep this discovery in
# sync with the source tree rather than maintaining a manually counted list.
# It includes deep_learning.torch_upgrade; registry_parts is discovered outside
# algorithms.models and therefore needs its own collection.
hiddenimports += collect_submodules("algorithms.models")
hiddenimports += collect_submodules("algorithms.registry_parts")

# ── Application packages (auto-collect) ──
for pkg in ("ui", "core", "utils"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# Extra safety: bilibili_api data files (hook-bilibili_api.py also handles this)
from PyInstaller.utils.hooks import collect_data_files
datas += collect_data_files("bilibili_api")

# ── Extra data: matplotlib mpl-data ──
datas += collect_data_files("matplotlib", include_py_files=True)

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
    a.binaries,
    a.datas,
    exclude_binaries=False,
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
