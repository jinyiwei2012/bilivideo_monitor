"""
B站视频监控与播放量预测系统

版本号规则（语义化版本）：
  X.Y.Z
  Z = patch — 小更新/小 commit（bug 修复、日志调整、文档）
  Y = minor — 大更新/必要修复（新功能、架构变更、API 修改）
  X = major — 重大更新（架构重写、不兼容变更）

版本: 3.0.0
功能:
- 103 种预测算法（含 7 大类别）
- 实时监控视频数据
- 阈值突破推送通知
- Windows原生通知 + QQ Bot
- 数据导出功能（含预测vs实际对比）
- 视频封面展示
- 播放量增长趋势图
- 算法权重自定义 + ML 动态调整
- 播放量交叉计算
- 多关键词视频搜索
- 系统设置配置
- 异常检测自动推送（8 种检测器）
- 视频标签管理 + 排行榜 + 预测回测
- 弹幕时间分布热力图
- AI 智能问答（预设模板）
- 412 限流绕过（curl_cffi TLS 指纹 / 多源兜底 / 代理自动发现 / Playwright）

项目结构:
- core/: 核心模块（数据库、API、通知）
- ui/: 界面模块（GUI界面）
- algorithms/: 预测算法模块
- utils/: 工具模块
- config/: 配置模块
- data/: 数据目录
- exports/: 导出目录
"""

__version__ = "3.0.0"
__author__ = "Bilibili Monitor Team"

from config import PROJECT_ROOT, DATA_DIR, COVER_DIR, EXPORT_DIR

__all__ = ["__version__", "__author__", "PROJECT_ROOT", "DATA_DIR", "COVER_DIR", "EXPORT_DIR"]


# ── 启动安全校验 — 校验 1/3：基础导入校验 ──────
def _startup_integrity_check():
    """启动完整性校验 — 导入时校验保护模块基础完整性"""
    try:
        from utils.update_checker import _hard, _x_strict, _confirm_risky, _x

        assert callable(_hard)
        assert callable(_x_strict)
        assert callable(_confirm_risky)
        assert callable(_x)
        assert isinstance(_hard(), str)
        assert isinstance(_x_strict(), bool)
    except AssertionError:
        raise RuntimeError(
            chr(23433)
            + chr(20840)
            + chr(20445)
            + chr(25252)
            + chr(27169)
            + chr(22359)
            + chr(23436)
            + chr(24050)
            + chr(34987)
            + chr(34987)
            + chr(34945)
            + chr(25913)
            + chr(25110)
            + chr(19981)
            + chr(23436)
            + chr(25972)
            + chr(65292)
            + chr(31243)
            + chr(32456)
            + chr(32447)
            + chr(25298)
            + chr(32477)
            + chr(21551)
            + chr(12290)
            + chr(10)
            + chr(35831)
            + chr(36890)
            + chr(32)
            + chr(103)
            + chr(105)
            + chr(116)
            + chr(32)
            + chr(114)
            + chr(101)
            + chr(115)
            + chr(116)
            + chr(111)
            + chr(114)
            + chr(101)
            + chr(32)
            + chr(24674)
            + chr(22797)
            + chr(25991)
            + chr(20214)
            + chr(25991)
            + chr(21581)
            + chr(35797)
            + chr(12290)
            + chr(10)
            + chr(10)
            + chr(22914)
            + chr(38656)
            + chr(33719)
            + chr(21462)
            + chr(23436)
            + chr(25972)
            + chr(32)
            + chr(100)
            + chr(101)
            + chr(118)
            + chr(109)
            + chr(111)
            + chr(100)
            + chr(101)
            + chr(32)
            + chr(21151)
            + chr(33021)
            + chr(65292)
            + chr(35831)
            + chr(20180)
            + chr(32454)
            + chr(38405)
            + chr(35835)
            + chr(32)
            + chr(82)
            + chr(69)
            + chr(65)
            + chr(68)
            + chr(77)
            + chr(69)
            + chr(46)
            + chr(109)
            + chr(100)
            + chr(32)
            + chr(25991)
            + chr(20214)
        )
    except ImportError:
        raise RuntimeError(
            chr(23433)
            + chr(20840)
            + chr(20445)
            + chr(25252)
            + chr(27169)
            + chr(22359)
            + chr(23436)
            + chr(27169)
            + chr(32570)
            + chr(65292)
            + chr(31243)
            + chr(32456)
            + chr(32447)
            + chr(25298)
            + chr(32477)
            + chr(21551)
            + chr(12290)
            + chr(10)
            + chr(35831)
            + chr(36890)
            + chr(32)
            + chr(103)
            + chr(105)
            + chr(116)
            + chr(32)
            + chr(114)
            + chr(101)
            + chr(115)
            + chr(116)
            + chr(111)
            + chr(114)
            + chr(101)
            + chr(32)
            + chr(24674)
            + chr(22797)
            + chr(25991)
            + chr(20214)
            + chr(25991)
            + chr(21581)
            + chr(35797)
            + chr(12290)
            + chr(10)
            + chr(10)
            + chr(22914)
            + chr(38656)
            + chr(33719)
            + chr(21462)
            + chr(23436)
            + chr(25972)
            + chr(32)
            + chr(100)
            + chr(101)
            + chr(118)
            + chr(109)
            + chr(111)
            + chr(100)
            + chr(101)
            + chr(32)
            + chr(21151)
            + chr(33021)
            + chr(65292)
            + chr(35831)
            + chr(20180)
            + chr(32454)
            + chr(38405)
            + chr(35835)
            + chr(32)
            + chr(82)
            + chr(69)
            + chr(65)
            + chr(68)
            + chr(77)
            + chr(69)
            + chr(46)
            + chr(109)
            + chr(100)
            + chr(32)
            + chr(25991)
            + chr(20214)
        )


_startup_integrity_check()
