"""搜索→导入监控路径回归测试。

背景（实测）：`Dialogs.import_search_results` 的 `_worker` 里原先用
`QTimer.singleShot(0, cb)` 回主线程，而普通 `threading.Thread` 没有事件循环 →
**回调永不执行**（本地探针：worker 线程注册的 singleShot 触发=False，主线程=True）。
后果：视频不注册进监控、watch_list 不保存、完成提示不弹，只有日志写「导入完成：成功 N」，
表现为「点了导入没反应 / 路径中断」。

修复：改用项目统一的 `ui.invoker.invoke`（同 `ui/invoker.py` 文档所要求的做法）。
本测试跑真实导入路径（打桩 API 与消息框），断言注册与保存确实发生。
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class _Log:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def add_log(self, level: str, msg: str) -> None:
        self.lines.append((level, msg))


class _Gui:
    def __init__(self) -> None:
        self.monitored_videos: list[dict] = []
        self.log_panel = _Log()
        self.registered: list[str] = []
        self.saved = 0

    def _map_api_to_video_dict(self, bvid, info, fallback=None):
        return {
            "bvid": bvid,
            "title": "探针视频",
            "view_count": 1,
            "like_count": 0,
            "coin_count": 0,
            "share_count": 0,
            "favorite_count": 0,
            "danmaku_count": 0,
            "reply_count": 0,
        }

    def _register_video_to_monitor(self, video):
        self.registered.append(video["bvid"])

    def _save_watch_list(self):
        self.saved += 1


class _Api:
    def get_video_info(self, bvid):
        return {"title": "探针视频", "stat": {"view": 1}, "owner": {"name": "UP"}}


def _pump(qapp, seconds: float, stop_when=None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)
        if stop_when is not None and stop_when():
            return


def test_import_search_results_registers_and_saves(qapp, monkeypatch):
    """导入搜索结果的视频 → 必须注册进监控并保存 watch_list（修复前两者都不会发生）。"""
    import core
    from PyQt6.QtWidgets import QMessageBox

    from ui.dialogs import Dialogs

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(core, "get_bilibili_api", lambda: _Api())

    gui = _Gui()
    Dialogs(gui).import_search_results([{"bvid": "BV1TESTPROBE"}])
    _pump(qapp, 6.0, stop_when=lambda: bool(gui.registered) and gui.saved >= 1)

    assert gui.registered == ["BV1TESTPROBE"], "视频必须被注册进监控（跨线程回调失效时为 []）"
    assert gui.saved >= 1, "导入后必须保存 watch_list"


def test_worker_threads_do_not_use_qtimer_singleshot():
    """静态守卫：`_worker` 后台线程里禁止直接 QTimer.singleShot（应经 ui.invoker.invoke）。

    允许的写法是 `invoke(lambda: QTimer.singleShot(ms, cb))`——QTimer 实际由主线程创建；
    因此按行判定：同一行已出现 `invoke(` 的调用点跳过。
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "ui"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if func.name != "_worker":
                continue
            for node in ast.walk(func):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "singleShot"
                ):
                    continue
                if "invoke(" in lines[node.lineno - 1]:
                    continue  # 已在 invoke 回调内，QTimer 由主线程创建
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"后台线程内不得直接 QTimer.singleShot（请用 invoke）: {offenders}"
