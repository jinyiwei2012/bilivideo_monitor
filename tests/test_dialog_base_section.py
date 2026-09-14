"""`DialogBase.section(parent=...)` 归属回归测试。

背景（实证）：`section(parent=...)` 原先把 `parent` 仅当作 QFrame 的 Qt 父对象，
仍固定 `self._main_layout.addWidget(sec)`；而 `ui/health_probe.py:267/277` 传
`parent=bottom`（`bottom` 定义于 `:261`、其布局 `bottom_layout` 于 `:263`、
`bottom` 自身到 `:286` 才加入主布局）→ 分段归属与顺序都错。

修复语义：有 parent 且 parent 有布局 → 挂到 parent 的布局；无 parent 或 parent 无布局 → 退回主布局。
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _dlg():
    from ui.dialog_base import DialogBase

    return DialogBase(None, "section-probe", "400x300")


class TestSectionParentLayout:
    def test_section_goes_into_parent_layout(self, qapp):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        dlg = _dlg()
        host = QWidget()
        host_layout = QVBoxLayout(host)

        sec = dlg.section(parent=host, title="分段", padding=6)

        assert sec.parent() is host
        assert host_layout.indexOf(sec) >= 0, "section 应挂到 parent 自己的布局"
        assert dlg._main_layout.indexOf(sec) < 0, "不应再挂到主布局"
        dlg.close()

    def test_section_without_parent_uses_main_layout(self, qapp):
        dlg = _dlg()
        sec = dlg.section(title="分段")
        assert dlg._main_layout.indexOf(sec) >= 0
        dlg.close()

    def test_section_with_bare_parent_falls_back(self, qapp):
        """parent 无布局时不抛异常，退回主布局。"""
        from PyQt6.QtWidgets import QWidget

        dlg = _dlg()
        bare = QWidget()
        sec = dlg.section(parent=bare, title="分段")
        assert dlg._main_layout.indexOf(sec) >= 0
        dlg.close()

    def test_health_probe_bottom_sections_land_in_bottom_layout(self, qapp):
        """复刻 health_probe 的用法：两个 section 必须落在 bottom_layout 内。"""
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        dlg = _dlg()
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)

        s1 = dlg.section(parent=bottom, title="异常", padding=8)
        s2 = dlg.section(parent=bottom, title="建议", padding=8)
        dlg._main_layout.addWidget(bottom)  # health_probe.py:286 的顺序

        assert bottom_layout.indexOf(s1) >= 0
        assert bottom_layout.indexOf(s2) >= 0
        assert bottom_layout.count() >= 2
        assert dlg._main_layout.indexOf(s1) < 0
        dlg.close()
