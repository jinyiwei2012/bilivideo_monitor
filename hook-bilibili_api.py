"""
PyInstaller hook for bilibili-api-python.

bilibili_api ships JSON data files (API endpoints, partition data, geetest HTML, etc.)
that must be bundled alongside the executable. This hook ensures they are collected.

This hook is automatically used by PyInstaller when building the executable.
It tells PyInstaller to include bilibili_api's data files in the bundled package.

参考: https://github.com/Nemo2011/bilibili-api/issues/39

用法（PyInstaller 会自动发现并执行此文件）:
    pyinstaller main.py --additional-hooks-dir=. --onefile
"""
from PyInstaller.utils.hooks import collect_data_files

# 收集 bilibili_api 包的所有非 Python 数据文件
# 包括 API 端点 JSON、分区数据、GeeTest HTML 模板等
datas = collect_data_files("bilibili_api")
