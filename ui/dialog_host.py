"""统一弹窗呈现层 —— 所有弹出界面的**唯一**显示入口。

背景（实测）：`ui/dialogs.py` 的 `open_*` 原先只构造弹窗对象，从不调用
`show()` / `exec()`；而 `DialogBase.__init__` 也不会显示自身。Qt 的 QDialog/QWidget
在显式调用 show/exec/setVisible(True) 之前始终隐藏 —— 实测探针确认：
`DialogBase(...)` 与组合式包装（如 `RankingPanel(...)`）构造后 `isVisible()` 均为 False，
手动 `show()` 后才为 True。因此原先约 20 个弹窗（含系统设置、数据库查询、排行榜等）
点开后不会出现。

本模块收口为单一呈现路径，保证：
1. **一定被显示**（`show()` 之前不再漏调）；
2. **保活引用**，避免组合式包装对象被 GC 后其信号回调失效；
3. **同类去重**：同一类窗口已在前台时只前置，不再新建（沿用 score_center 既有语义）；
4. **置前**（`raise_` + `activateWindow`），并在必要时居中显示。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# 类 -> 存活实例（保活 + 同类去重）
_registry: Dict[type, Any] = {}
_lock = threading.Lock()


def resolve_window(window: Any) -> Optional[QWidget]:
    """取出可显示的 QWidget。

    兼容两种既有写法：组合式（窗口类持有 ``.dlg``）与子类式（自身即 QWidget/QDialog）。
    """
    if isinstance(window, QWidget):
        return window
    dlg = getattr(window, "dlg", None)
    return dlg if isinstance(dlg, QWidget) else None


def center_on_parent(widget: QWidget) -> None:
    """把窗口居中到父窗口；无父窗口则居中到屏幕。仅在该窗口尚无位置时调用。"""
    try:
        parent = widget.parentWidget()
        screen = None
        if parent is not None:
            screen = parent.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        fg = widget.frameGeometry()
        fg.moveCenter(avail.center())
        widget.move(fg.topLeft())
    except Exception as e:  # 居中失败不应影响显示
        logger.debug("弹窗居中失败: %s", e)


def present(window: Any, *, singleton: bool = True, center: bool = False) -> Any:
    """显示弹窗（唯一入口）。

    Args:
        window: 已构造的弹窗对象（子类式或组合式包装）
        singleton: True 时同类窗口已在前台则只前置，不再新建
        center: True 时若窗口尚无父窗口定位则居中显示

    Returns:
        实际被呈现的对象（可能是复用到的旧实例）
    """
    widget = resolve_window(window)
    if widget is None:
        logger.warning("present() 收到无法显示的弹窗对象: %r", type(window))
        return window

    if singleton:
        with _lock:
            previous = _registry.get(type(window))
        if previous is not None and previous is not window:
            prev_widget = resolve_window(previous)
            if prev_widget is not None and prev_widget.isVisible():
                try:
                    widget.close()  # 丢弃本次新建的，前置已有窗口
                except Exception as e:
                    logger.debug("关闭重复弹窗失败: %s", e)
                prev_widget.raise_()
                prev_widget.activateWindow()
                return previous

    with _lock:
        _registry[type(window)] = window  # 保活：防止包装对象被 GC

    if center:
        center_on_parent(widget)
    widget.show()
    widget.raise_()
    widget.activateWindow()
    return window


def forget(window_cls: type) -> None:
    """解除某类窗口的保活引用（关闭/销毁时调用，避免长期持有已关闭窗口）。"""
    with _lock:
        _registry.pop(window_cls, None)


def alive_count() -> int:
    """当前被保活的窗口类数量（供测试与诊断）。"""
    with _lock:
        return len(_registry)
