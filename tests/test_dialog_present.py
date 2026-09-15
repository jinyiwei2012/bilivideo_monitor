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
    """保证测试前后保活表与单例表都为空，避免测试间互相影响。"""

    def _clear() -> None:
        with dialog_host._lock:
            dialog_host._keep_alive.clear()
            dialog_host._singletons.clear()

    _clear()
    yield
    _clear()


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
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        dialog_host.present(_Wrapper(dlg))
        assert dialog_host.alive_count() == 1

        # 用 deleteLater + 显式处理 DeferredDelete 做**确定性**销毁；
        # 不用 WA_DeleteOnClose + close()（销毁时机与事件循环耦合，Linux 上曾段错误）
        dlg.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
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

    def test_non_qdialog_is_rejected_and_not_shown(self, qapp, clean_registry):
        """没有 exec() 的纯 QWidget：不得被显示（原先会降级为非模态显示）。"""
        from PyQt6.QtWidgets import QDialog, QWidget

        widget = QWidget()
        assert dialog_host.present_modal(widget) == int(QDialog.DialogCode.Rejected)
        assert widget.isVisible() is False
        assert dialog_host.alive_count() == 0

    def test_exec_exception_propagates(self, qapp, clean_registry, monkeypatch):
        """exec() 自身的异常必须向上抛，不得伪装成「用户取消」。"""
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(dlg, "exec", _boom)
        with pytest.raises(RuntimeError):
            dialog_host.present_modal(dlg)
        assert dialog_host.alive_count() == 0, "异常路径也必须回收保活"

    def test_releases_keepalive_after_exec(self, qapp, clean_registry):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        QTimer.singleShot(0, dlg.reject)
        dialog_host.present_modal(dlg)
        assert dialog_host.alive_count() == 0, "模态结束后不应继续保活"

    def test_center_is_applied_before_exec(self, qapp, clean_registry, monkeypatch):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialog

        seen = []
        monkeypatch.setattr(dialog_host, "center_on_parent", lambda w: seen.append(w))
        dlg = QDialog()
        QTimer.singleShot(0, dlg.reject)
        dialog_host.present_modal(dlg, center=True)
        assert seen == [dlg]

    def test_accepts_reserved_kwargs(self, qapp, clean_registry):
        """**kwargs 为签面对齐保留，不得因未知参数抛异常。"""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialog

        dlg = QDialog()
        QTimer.singleShot(0, dlg.reject)
        assert dialog_host.present_modal(dlg, singleton=True) == int(QDialog.DialogCode.Rejected)


class TestSingleDisplayFunnel:
    """T5：score_center 与 report_scheduler 接入单一显示漏斗。"""

    def test_open_score_center_is_singleton_and_visible(self, qapp):
        import ui.score_center as sc

        try:
            w1 = sc.open_score_center(None)
            w2 = sc.open_score_center(None)
            assert w1 is w2, "重复调用应复用同一窗口"
            assert w1.dlg.isVisible() is True, "open_score_center 后窗口必须可见"

            w1.dlg.close()
            assert w1.dlg.isVisible() is False
            w3 = sc.open_score_center(None)
            assert w3 is w1
            assert w3.dlg.isVisible() is True, "关闭后再次调用应能重新显示（不被保活残留挡住）"
        finally:
            sc._window_ref = None
            import ui.dialog_host as dh

            dh.forget(dh.QDialog)

    def test_score_center_show_order_preserved(self, qapp, monkeypatch):
        """show() 仍为 _reload_videos → _on_selection_changed → 显示。"""
        import ui.dialog_host as dh
        import ui.score_center as sc

        calls = []
        real_present = dh.present
        monkeypatch.setattr(sc.ScoreCenterWindow, "_reload_videos", lambda self: calls.append("reload"))
        monkeypatch.setattr(sc.ScoreCenterWindow, "_on_selection_changed", lambda self: calls.append("selection"))

        def fake_present(window, **kwargs):
            calls.append("present")
            return real_present(window, **kwargs)

        monkeypatch.setattr(sc, "present", fake_present)

        window = sc.ScoreCenterWindow(None, None)
        calls.clear()
        window.show()

        assert calls == ["reload", "selection", "present"], calls
        window.dlg.close()

    def test_report_scheduler_constructor_is_pure(self, qapp, clean_registry):
        """构造函数只做初始化：不显示、不登记保活（显示由 open_report_scheduler 的 present 负责）。"""
        import ui.dialog_host as dh
        import ui.report_scheduler as rs

        window = rs.ReportSchedulerWindow(None, gui=None)
        try:
            assert window.isVisible() is False, "构造函数不应自行显示弹窗"
            assert dh.alive_count() == 0, "构造函数不应登记保活引用"
        finally:
            window.close()

    def test_report_scheduler_open_path_uses_present(self):
        """源码级：唯一打开路径必须经统一层显示（否则该窗口将不再出现）。"""
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "ui" / "dialogs.py").read_text(encoding="utf-8")
        assert "present(ReportSchedulerWindow(" in src


class TestDeadApiGuards:
    """T6：源码级防误删基线 —— 仍被使用的 API 必须有真实调用点。"""

    @staticmethod
    def _ui_dir():
        import pathlib

        return pathlib.Path(__file__).resolve().parents[1] / "ui"

    def _callers(self, needle):
        hits = []
        for path in sorted(self._ui_dir().rglob("*.py")):
            if path.name == "dialog_base.py":
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if needle in line:
                    hits.append(f"{path.name}:{lineno}")
        return hits

    def test_content_area_still_has_callers(self):
        hits = self._callers("content_area(")
        assert len(hits) >= 8, f"content_area 调用点基线为 8，实际 {len(hits)}: {hits}"

    def test_button_row_still_has_callers(self):
        hits = self._callers("button_row(")
        assert len(hits) >= 4, f"button_row 调用点基线为 4，实际 {len(hits)}: {hits}"

    def test_header_and_section_still_have_callers(self):
        assert len(self._callers(".header(")) >= 5
        assert len(self._callers(".section(")) >= 10

    def test_close_no_crash_after_show(self, qapp):
        """回归：close() 不得因 rejected→reject 自反连接而栈溢出（原 0xC00000FD）。"""
        from ui.dialog_base import DialogBase

        dlg = DialogBase(None, "t", "400x300")
        dlg.show()
        assert dlg.isVisible() is True
        dlg.close()
        assert dlg.isVisible() is False
        dlg.close()  # 重复关闭同样不得崩溃


class TestNoBareExecInUi:
    """T4 守卫：ui/ 下除 dialog_host（统一入口）与应用事件循环外，不得再出现裸 .exec()。"""

    def test_no_direct_exec_outside_host_and_app(self):
        import pathlib

        ui_dir = pathlib.Path(__file__).resolve().parents[1] / "ui"
        allowed = {"dialog_host.py", "main_gui.py"}
        offenders = []
        for path in sorted(ui_dir.rglob("*.py")):
            if path.name in allowed:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if ".exec()" in line:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        assert not offenders, f"应改用 present_modal(): {offenders}"


class TestDialogBaseHardening:
    """T3：geometry 校验 / 字号缓存 / 死 API 处置（不破坏仍被使用的 API）。"""

    def test_geometry_string_parsed(self, qapp):
        from ui.dialog_base import DialogBase

        dlg = DialogBase(None, "t", "512x384")
        assert (dlg.width(), dlg.height()) == (512, 384)
        dlg.close()

    @pytest.mark.parametrize("bad", ["abc", "12x", "", "x300", None, (1, 2, 3), "0x0", "999999999999999999999x1"])
    def test_invalid_geometry_falls_back_without_crash(self, qapp, bad):
        from ui.dialog_base import DialogBase

        dlg = DialogBase(None, "t", bad)
        assert dlg.width() >= 300 and dlg.height() >= 200
        dlg.close()

    def test_geometry_parse_contract(self, qapp):
        """_parse_geometry 的精确契约：合法即原样返回，非法/越界/非二元一律回退 (480, 360)。"""
        from ui.dialog_base import DialogBase

        assert DialogBase._parse_geometry("800x600") == (800, 600)
        assert DialogBase._parse_geometry((640, 480)) == (640, 480)
        assert DialogBase._parse_geometry((1, 2, 3)) == (480, 360)
        assert DialogBase._parse_geometry("0x0") == (480, 360)
        assert DialogBase._parse_geometry("-1x5") == (480, 360)
        assert DialogBase._parse_geometry("999999999999999999999x1") == (480, 360)

    def test_font_cache_is_equivalent_and_isolated(self, qapp):
        """缓存返回等价但**独立**的副本：调用方改动不得污染缓存，原型仍被复用。"""
        from ui.dialog_base import DialogBase

        first = DialogBase._font(9, bold=True)
        second = DialogBase._font(9, bold=True)
        assert first == second
        assert first is not second, "必须返回独立副本（缓存原型 + 隐式共享副本）"
        assert DialogBase._font(9) != DialogBase._font(9, bold=True)

        proto = DialogBase._FONT_CACHE[(9, True)]
        assert DialogBase._font(9, bold=True) == proto, "缓存原型应被复用"

        mutated = DialogBase._font(6)
        mutated.setPointSize(33)
        assert DialogBase._font(6).pointSize() == 6, "缓存被调用方改动污染"
        assert DialogBase._FONT_CACHE[(6, False)].pointSize() == 6, "缓存原型被污染"

    def test_dead_field_row_removed(self):
        from ui.dialog_base import DialogBase

        assert not hasattr(DialogBase, "field_row"), "0 调用者的 field_row 应已删除"

    def test_used_apis_preserved(self):
        """防误删：content_area(8 处调用) 与 button_row(4 处调用) 必须保留。"""
        from ui.dialog_base import DialogBase

        assert hasattr(DialogBase, "content_area")
        assert hasattr(DialogBase, "button_row")
        assert hasattr(DialogBase, "header")
        assert hasattr(DialogBase, "section")


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
        calls["cls"] = _Stub
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
        assert isinstance(calls["presented"], calls["cls"]), f"{method}() 呈现的对象类型不符"


class TestRegistryIdentity:
    """F2 复现用例：保活按**身份**回收，同类多实例可共存。"""

    def test_destroying_older_instance_keeps_newer(self, qapp, clean_registry):
        """旧实例销毁时的 destroyed 回调不得删掉同类新实例的保活。"""
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QDialog

        old, new = QDialog(), QDialog()
        dialog_host.present(old, singleton=False)
        dialog_host.present(new, singleton=False)
        assert dialog_host.alive_count() == 2

        # 确定性销毁旧实例（避免 WA_DeleteOnClose + close() 的时机耦合）
        old.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert dialog_host.alive_count() == 1, "旧实例销毁误删了同类新实例的保活"
        new.close()

    def test_closed_singleton_is_released_when_replaced(self, qapp, clean_registry):
        """关闭后重新打开：旧单例必须解除保活，否则成为 forget() 也回收不掉的强引用。"""
        from PyQt6.QtWidgets import QDialog

        class _W(QDialog):
            pass

        first = _W()
        dialog_host.present(first)
        assert dialog_host.alive_count() == 1

        first.close()  # QDialog.close() 只隐藏、不销毁
        second = _W()
        dialog_host.present(second)
        assert dialog_host.alive_count() == 1, "被替换的已关闭单例应已解除保活"

        dialog_host.forget(_W)
        assert dialog_host.alive_count() == 0

    def test_two_non_singletons_both_kept(self, qapp, clean_registry):
        from PyQt6.QtWidgets import QDialog

        first, second = QDialog(), QDialog()
        dialog_host.present(first, singleton=False)
        dialog_host.present(second, singleton=False)
        assert dialog_host.alive_count() == 2, "singleton=False 时同类多实例都应被保活"
        first.close()
        second.close()


class TestModalMigrationBehavior:
    """T4 要求：13 个调用点在**行为/AST** 两层都确实经过 present_modal()。"""

    EXPECTED_SITES = {
        "ui/dialogs.py": 2,
        "ui/detail_panel.py": 1,
        "ui/main_gui_events_monitor.py": 1,
        "ui/main_gui_events_update.py": 1,
        "ui/settings_account.py": 4,
        "ui/settings_proxy.py": 1,
        "ui/training_batch.py": 1,
        "ui/training_version.py": 1,
        "ui/video_search.py": 1,
    }

    def test_all_sites_call_present_modal_ast(self):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        for rel, expected in self.EXPECTED_SITES.items():
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
            calls = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "present_modal"
            )
            assert calls == expected, f"{rel}: present_modal 调用 {calls} 次，期望 {expected} 次"
            imported = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "ui.dialog_host"
                and any(alias.name == "present_modal" for alias in node.names)
                for node in ast.walk(tree)
            )
            assert imported, f"{rel}: 未从 ui.dialog_host 导入 present_modal"

    def test_interval_settings_goes_through_present_modal(self, qapp, monkeypatch):
        """行为级：open_interval_settings() 必须经 present_modal 显示（原先 bar 裸 dialog.exec()）。"""
        from PyQt6.QtWidgets import QDialog, QWidget

        from ui.dialogs import Dialogs

        class _Gui(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.monitored_videos: list = []
                self.DEFAULT_INTERVAL = 75
                self.FAST_INTERVAL = 30
                self._video_timers: dict = {}

        seen = []

        def _fake_modal(window, **kwargs):
            seen.append(window)
            return int(QDialog.DialogCode.Rejected)

        monkeypatch.setattr("ui.dialogs.present_modal", _fake_modal)
        Dialogs(_Gui()).open_interval_settings()

        assert len(seen) == 1, "间隔设置弹窗必须经 present_modal 显示"
        assert seen[0].windowTitle() == "刷新间隔设置 ♪"

    @pytest.mark.parametrize(
        "method,cls_attr",
        [
            ("_import_cookie_editor", "_CookieEditorDialog"),
            ("_password_login", "_PasswordLoginDialog"),
            ("_qrcode_login", "_QRCodeLoginDialog"),
            ("_add_account_dialog", "_AddAccountDialog"),
        ],
    )
    def test_rejected_modal_skips_account_writes(self, monkeypatch, method, cls_attr):
        """Rejected（用户取消）时账号类分支不得写入 cookie/配置。"""
        from unittest.mock import MagicMock

        from PyQt6.QtWidgets import QDialog

        import ui.settings_account as sa

        monkeypatch.setattr(sa, cls_attr, lambda *a, **k: MagicMock())
        monkeypatch.setattr(sa, "present_modal", lambda *a, **k: int(QDialog.DialogCode.Rejected))
        api = MagicMock()
        monkeypatch.setattr(sa, "get_bilibili_api", lambda: api)

        stub = MagicMock()
        stub._net_cfg = {"cookies": {"SESSDATA": "keep-me"}}

        getattr(sa.SettingsAccountMixin, method)(stub)

        assert stub._net_cfg == {"cookies": {"SESSDATA": "keep-me"}}, "Rejected 时不得改写账号配置"
        stub._save_net_config.assert_not_called()
        stub._refresh_account_list.assert_not_called()
        api.add_account.assert_not_called()
