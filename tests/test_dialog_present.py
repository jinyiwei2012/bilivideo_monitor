"""统一弹窗呈现层（ui.dialog_host）回归测试。

关键回归点：`ui/dialogs.py` 的 `open_*` 原先只构造弹窗、从不 show()，导致弹窗不显示。
这里用两道守卫锁住：
1. `present()` 一定让窗口可见，并保活引用、同类去重；
2. 每个 `open_*` 都必须经由 `present()`（否则将来又会漏调 show）。
"""

from __future__ import annotations

from typing import Any, List

import pytest

from ui import dialog_host


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def clean_registry():
    """清理保活表，避免测试间互相影响。"""
    yield
    while dialog_host.alive_count():
        with dialog_host._lock:
            dialog_host._registry.clear()


class _Wrapper:
    """组合式弹窗替身：持有 .dlg。"""

    def __init__(self, dlg: Any) -> None:
        self.dlg = dlg

    def show(self) -> None:  # 包装自身的 show 不应被 present 依赖
        raise AssertionError("present() 必须调用 .dlg.show()，而不是包装的 show()")


class TestPresent:
    def test_shows_dialog_and_keeps_alive(self, qapp, clean_registry):
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        wrapped = _Wrapper(dlg)
        returned = dialog_host.present(wrapped)
        assert returned is wrapped
        assert dlg.isVisible() is True
        assert dialog_host.alive_count() == 1
        dlg.close()

    def test_accepts_bare_widget(self, qapp, clean_registry):
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        dialog_host.present(dlg)
        assert dlg.isVisible() is True
        dlg.close()

    def test_dedupes_same_class(self, qapp, clean_registry):
        from PyQt6.QtWidgets import QDialog

        first_dlg = QDialog()
        first = _Wrapper(first_dlg)
        dialog_host.present(first)

        second_dlg = QDialog()
        second = _Wrapper(second_dlg)
        returned = dialog_host.present(second)

        assert returned is first, "同类窗口已在前台时应复用旧实例"
        assert second_dlg.isVisible() is False, "重复新建的窗口应被关闭"
        assert first_dlg.isVisible() is True
        first_dlg.close()

    def test_new_instance_after_old_closed(self, qapp, clean_registry):
        from PyQt6.QtWidgets import QDialog

        first_dlg = QDialog()
        first = _Wrapper(first_dlg)
        dialog_host.present(first)
        first_dlg.close()
        assert first_dlg.isVisible() is False

        second_dlg = QDialog()
        second = _Wrapper(second_dlg)
        assert dialog_host.present(second) is second
        assert second_dlg.isVisible() is True
        second_dlg.close()

    def test_forget_releases_reference(self, qapp, clean_registry):
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        dialog_host.present(_Wrapper(dlg))
        assert dialog_host.alive_count() == 1
        dialog_host.forget(_Wrapper)
        assert dialog_host.alive_count() == 0
        dlg.close()

    def test_unshowable_object_is_reported(self, clean_registry):
        class _NotAWindow:
            pass

        obj = _NotAWindow()
        assert dialog_host.present(obj) is obj  # 不抛异常，仅告警
        assert dialog_host.alive_count() == 0

    def test_destroyed_releases_keepalive(self, qapp, clean_registry):
        """窗口被 Qt 销毁后应自动解除保活引用（避免长期持有已销毁对象）。"""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog_host.present(_Wrapper(dlg))
        assert dialog_host.alive_count() == 1

        dlg.close()
        qapp.processEvents()
        assert dialog_host.alive_count() == 0


class TestPresentModal:
    """模态分支：阻塞执行并透传 DialogCode（原先各弹窗各自 exec()）。"""

    def test_returns_accepted_code(self, qapp, clean_registry):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        QTimer.singleShot(0, dlg.accept)
        assert dialog_host.present_modal(dlg) == int(QDialog.DialogCode.Accepted)

    def test_returns_rejected_code(self, qapp, clean_registry):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        QTimer.singleShot(0, dlg.reject)
        assert dialog_host.present_modal(dlg) == int(QDialog.DialogCode.Rejected)

    def test_non_window_returns_rejected(self, clean_registry):
        from PyQt6.QtWidgets import QDialog

        class _NotAWindow:
            pass

        assert dialog_host.present_modal(_NotAWindow()) == int(QDialog.DialogCode.Rejected)


class TestDialogBaseClose:
    """回归：DialogBase 原先 `rejected → reject` 自反连接，关闭窗口即无限递归。

    实测表现为进程栈溢出崩溃（exit 0xC00000FD），因此这些用例一旦跑通本身就说明没崩。
    """

    def test_close_does_not_stack_overflow(self, qapp):
        from ui.dialog_base import DialogBase

        dlg = DialogBase(None, "probe", "300x200")
        dlg.show()
        dlg.close()  # 修复前：此处栈溢出
        assert dlg.isVisible() is False

    def test_reject_is_reentrant_safe(self, qapp):
        from ui.dialog_base import DialogBase

        dlg = DialogBase(None, "probe", "300x200")
        dlg.show()
        dlg.reject()  # ESC 语义（QDialog 原生 → reject），不得递归
        assert dlg.isVisible() is False
        assert dlg.result() == 0


class TestOpenPathsGoThroughPresent:
    """防线：open_* 必须经由 present()，否则又会退化成"构造即丢弃"。"""

    class _Gui:
        def __init__(self) -> None:
            self.monitored_videos: List[dict] = []
            self.history_data: dict = {}
            self.video_dbs: dict = {}
            self.DEFAULT_INTERVAL = 75
            self._import_search_results = lambda *a, **k: None  # noqa: E731

    def _patch(self, monkeypatch, module: str, cls_name: str) -> dict:
        import importlib

        calls: dict = {}

        class _Stub:
            def __init__(self, *a, **k) -> None:
                calls["args"] = a
                calls["kwargs"] = k

        mod = importlib.import_module(module)
        monkeypatch.setattr(mod, cls_name, _Stub)
        monkeypatch.setattr("ui.dialogs.present", lambda w, **k: calls.setdefault("presented", w))
        return calls

    @pytest.mark.parametrize(
        "method,module,cls_name",
        [
            ("open_ranking", "ui.ranking_panel", "RankingPanel"),
            ("open_settings", "ui.settings_window", "SettingsWindow"),
            ("open_tag_manager", "ui.tag_manager", "TagManagerWindow"),
            ("open_anomaly_detection", "ui.anomaly_panel", "AnomalyPanel"),
            ("open_backtest", "ui.backtest_panel", "BacktestPanel"),
        ],
    )
    def test_open_calls_present(self, monkeypatch, method, module, cls_name):
        from ui.dialogs import Dialogs

        calls = self._patch(monkeypatch, module, cls_name)
        getattr(Dialogs(self._Gui()), method)()
        assert "presented" in calls, f"{method}() 未经过 present()，弹窗不会显示"
        assert isinstance(calls["presented"], type(calls["presented"]))
