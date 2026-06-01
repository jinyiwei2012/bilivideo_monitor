"""
B站视频监控与播放量预测系统
主入口文件
"""

import sys
import os
import hashlib

# 添加项目根目录到Python路径（兼容 PyInstaller 打包）
if getattr(sys, "frozen", False):
    project_root = os.path.dirname(sys.executable)
else:
    project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# ── 源码完整性校验 ──────────────────────────
# 校验必须在 from ui import main 之前执行，防止篡改代码先于检查加载
# SHA-256 哈希列表，在发布前通过 python scripts/update_hashes.py 更新
# 开发时创建 .devmode 文件（内容 SHA-256 须匹配 _DEVMODE_HASH）可跳过校验
# main.py 不参与自校验（SHA256(self)=H 数学上不可解），由 git 版本控制保证
_INTEGRITY_HASHES: dict[str, str] = {
    "core/bilibili_api.py": "DEF54F55A27B50369F1612CBBC7B8BFB8C766962734424D812E07CB995DFBF5D",
    "algorithms/registry.py": "3617705AB71B573BF05C3ACACBF7B32C0DFF6AA6BBD73C8B249DAE147CB89EE0",
    "algorithms/base.py": "0B40B1355723B00EFC95CB19778451231B8DEB0764358FD70E6765A98CDCCDCF",
    "core/notification.py": "01FC9B3671F4A364E679368FCB1ECA02361892C85FD47C35F79A5E2EB89C8488",
}
# .devmode 文件内容的期望 SHA-256（去除首尾空白后）
_DEVMODE_HASH = "40175C25B9517A906FCF778E50387017BB8FA6121D28EBD0720474E85EE7ECA8"


# ── 源码完整性校验 ──────────────────────────


def _verify_devmode() -> bool:
    """校验 .devmode 文件是否存在且内容哈希匹配。"""
    devmode = os.path.join(project_root, ".devmode")
    devmode2 = os.path.join(project_root, "devmode")
    for path in (devmode, devmode2):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                h = hashlib.sha256(content.encode()).hexdigest().upper()
                if h == _DEVMODE_HASH:
                    return True
            except Exception:
                pass
    return False


def _verify_source_integrity() -> None:
    """使用 SHA-256 校验核心源文件完整性。

    开发环境（_verify_devmode 通过 或 frozen 打包）跳过校验。
    哈希不匹配时给出清晰的错误指引。
    """
    if getattr(sys, "frozen", False):
        return
    if _verify_devmode():
        return
    if not _INTEGRITY_HASHES:
        return

    for rel_path, expected_hash in _INTEGRITY_HASHES.items():
        filepath = os.path.join(project_root, rel_path)
        if not os.path.isfile(filepath):
            raise RuntimeError(
                f"文件缺失: {rel_path}\n\n"
                f"请执行 git restore 还原源文件，或创建 .devmode 文件跳过校验。\n"
                f"参考 README.md 文件"
            )
        with open(filepath, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest().upper()
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"文件已被篡改: {rel_path}\n"
                f"  预期: {expected_hash}\n"
                f"  实际: {actual_hash}\n\n"
                f"请执行 git restore 还原源文件，或创建 .devmode 文件跳过校验。\n"
                f"参考 README.md 文件"
            )


_verify_source_integrity()

from ui import main


def _start_backend_engine():
    """启动后端监控引擎，从 watch_list 加载视频"""
    import logging
    logger = logging.getLogger("main")

    from config import load_config
    from backend import get_engine

    engine = get_engine()
    cfg = load_config()
    watch_list = cfg.get("watch_list", [])
    monitor_cfg = cfg.get("monitor", {})
    interval = monitor_cfg.get("check_interval", 300)

    logger.info("后端引擎启动，加载 %d 个监控视频", len(watch_list))
    for bvid in watch_list:
        engine.add_video(bvid, interval=interval)
    return engine


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="B站视频监控与播放量预测系统")
    parser.add_argument("--web-only", action="store_true", help="仅启动 Web 服务")
    parser.add_argument("--web-port", type=int, default=None, help="Web 服务端口")
    parser.add_argument("--web-host", default="0.0.0.0", help="Web 服务地址")
    parser.add_argument("--gui-only", action="store_true", help="仅启动 GUI")
    parser.add_argument("--no-engine", action="store_true", help="不启动后端监控引擎")
    args, _ = parser.parse_known_args()

    if not args.no_engine:
        _start_backend_engine()

    if args.web_only:
        from web_entry import start_api_server
        port = args.web_port or 8800
        start_api_server(host=args.web_host, port=port)
    elif args.gui_only:
        main()
    else:
        from config import load_config
        cfg = load_config()
        web_cfg = cfg.get("web", {})
        port = args.web_port or web_cfg.get("port", 8800)
        host = web_cfg.get("host", "0.0.0.0")

        if web_cfg.get("enabled", True):
            from web_entry import start_in_background
            start_in_background(host=host, port=port)
        main()
