# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = os.path.dirname(os.path.abspath('main.py'))

datas = []
binaries = []
hiddenimports = [
    'plyer.platforms.win.notification',
    'PIL._tkinter_finder',
    'pandas', 'sklearn', 'scipy', 'statsmodels',
    'xgboost', 'lightgbm', 'prophet',
]

# Collect packages with auto-discovery
for pkg in ('customtkinter', 'bilibili_api', 'ui'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# Include runtime directories alongside the EXE (mirror project layout)
for dir_name in ('config',):
    src = os.path.join(PROJECT_ROOT, dir_name)
    if os.path.isdir(src):
        for root, dirs, files in os.walk(src):
            for f in files:
                src_file = os.path.join(root, f)
                rel_path = os.path.relpath(os.path.dirname(src_file), PROJECT_ROOT)
                datas.append((src_file, rel_path))


a = Analysis(
    ['main.py'],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BiliMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
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
    upx=False,
    upx_exclude=[],
    name='BiliMonitor',
)
