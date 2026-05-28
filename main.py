"""
B站视频监控与播放量预测系统
主入口文件
"""

import sys
import os

# 添加项目根目录到Python路径（兼容 PyInstaller 打包）
if getattr(sys, "frozen", False):
    project_root = os.path.dirname(sys.executable)
else:
    project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ui import main

# ── 启动安全校验 — 校验 3/3：源码完整性 ──────
if not getattr(sys, "frozen", False):
    try:
        import inspect as _i
        from utils.update_checker import _x_strict as _xs
        _s = _i.getsource(_xs)
        _m = chr(104)+chr(97)+chr(115)+chr(104)+chr(108)+chr(105)+chr(98)+chr(46)+chr(109)+chr(100)+chr(53)  # hashlib.md5
        assert _m in _s
        del _i, _xs, _s, _m
    except Exception:
        raise RuntimeError(
            chr(20445)+chr(25252)+chr(27169)+chr(22359)+chr(23436)+chr(28304)+chr(30721)+chr(34987)+chr(34987)+chr(34945)+chr(24050)+chr(34987)+chr(24050)+chr(34987)+chr(26524)+chr(65292)+chr(31243)+chr(32456)+chr(32447)+chr(25298)+chr(32477)+chr(21551)+chr(12290)+chr(10)
            +chr(35831)+chr(36890)+chr(32)+chr(103)+chr(105)+chr(116)+chr(32)+chr(114)+chr(101)+chr(115)+chr(116)+chr(111)+chr(114)+chr(101)+chr(32)+chr(24674)+chr(22797)+chr(25991)+chr(20214)+chr(25991)+chr(21581)+chr(35797)+chr(12290)
            +chr(10)+chr(10)+chr(22914)+chr(38656)+chr(33719)+chr(21462)+chr(23436)+chr(25972)+chr(32)+chr(100)+chr(101)+chr(118)+chr(109)+chr(111)+chr(100)+chr(101)+chr(32)+chr(21151)+chr(33021)+chr(65292)+chr(35831)+chr(20180)+chr(32454)+chr(38405)+chr(35835)+chr(32)+chr(82)+chr(69)+chr(65)+chr(68)+chr(77)+chr(69)+chr(46)+chr(109)+chr(100)+chr(32)+chr(25991)+chr(20214)
        )

if __name__ == "__main__":
    main()
