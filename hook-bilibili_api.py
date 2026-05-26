"""
PyInstaller hook for bilibili-api-python.

bilibili_api ships JSON data files (API endpoints, partition data, geetest HTML, etc.)
that must be bundled alongside the executable. This hook ensures they are collected.

Reference: https://github.com/Nemo2011/bilibili-api/issues/39
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("bilibili_api")
