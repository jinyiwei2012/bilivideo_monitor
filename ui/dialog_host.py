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

from PyQt6.QtWidgets import QApplication, QDialog, QWidget

logger = logging.getLogger(__name__)

# 保活表：id(对象) -> 对象。按**身份**索引，允许同类多实例共存，且某个实例销毁时
# 只会回收它自己那一份（早期按类索引会让旧实例的 destroyed 误删同类新实例的登记）。
_keep_alive: Dict[int, Any] = {}
# 单例表：窗口类 -> 当前前台实例。仅 present(singleton=True) 参与同类去重。
_singletons: Dict[type, Any] = {}
# 用 RLock：`destroyed` 信号可能在同线程内同步回调 _release()（例如清空保活表时
# 释放最后一个引用导致 C++ 对象析构），非重入锁会在同线程内自锁死。
_lock = threading.RLock()


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
            previous = _singletons.get(type(window))
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

    _keep(window, singleton=singleton)

    if center:
        center_on_parent(widget)
    widget.show()
    widget.raise_()
    widget.activateWindow()
    return window


def _keep(window: Any, *, singleton: bool = False) -> int:
    """保活引用并返回身份令牌；窗口被 Qt 销毁时只回收自己那一份。

    ``singleton=True`` 时额外登记为同类前台实例（参与 :func:`present` 的同类去重）。
    同一对象重复登记不会重复连接 ``destroyed``（令牌已在表中则跳过）。
    """
    cls = type(window)
    token = id(window)
    with _lock:
        already = token in _keep_alive
        _keep_alive[token] = window
        if singleton:
            _singletons[cls] = window
    widget = resolve_window(window)
    if widget is None or already:
        return token
    try:
        widget.destroyed.connect(lambda *_a, _t=token: _release(_t))
    except Exception as e:  # 注册回收失败不应影响显示
        logger.debug("注册弹窗销毁回收失败: %s", e)
    return token


def _release(token: int) -> None:
    """按身份令牌回收保活（Qt ``destroyed`` 回调与模态结束都走这里）。"""
    with _lock:
        obj = _keep_alive.pop(token, None)
        if obj is None:
            return
        for cls, current in list(_singletons.items()):
            if current is obj:
                _singletons.pop(cls, None)


def present_modal(window: Any, *, center: bool = False, **kwargs: Any) -> int:
    """以**模态**方式显示弹窗：阻塞到关闭，返回 ``int(QDialog.DialogCode)``。

    Args:
        window: 已构造的 ``QDialog``（或持有 ``.dlg`` 的包装对象）
        center: True 时先居中到父窗口再 ``exec()``
        **kwargs: 为与 :func:`present` 保持调用面一致而接受；当前无其他生效参数

    模态天生串行，故不参与同类去重，也不调 ``raise_``/``activateWindow``。
    取不到窗口、或目标不是 ``QDialog``（没有 ``exec()``）时记 warning 并返回 ``Rejected``，
    且**不显示**该窗口；``exec()`` 自身抛出的异常按原样向上抛（与直接 ``dlg.exec()`` 一致，
    避免把程序缺陷伪装成"用户取消"）。
    """
    widget = resolve_window(window)
    if widget is None:
        logger.warning("present_modal() 收到无法显示的弹窗对象: %r", type(window))
        return int(QDialog.DialogCode.Rejected)
    if not isinstance(widget, QDialog):
        logger.warning("present_modal() 目标不是 QDialog（无 exec()），已拒绝显示: %r", type(window))
        return int(QDialog.DialogCode.Rejected)
    token = _keep(window)
    try:
        if center:
            center_on_parent(widget)
        return int(widget.exec())
    finally:
        _release(token)  # 模态结束后不再保活，避免长期持有已关闭窗口


def forget(window_cls: type) -> None:
    """按**类**解除单例登记（并回收该实例的保活），供关闭/销毁时调用。"""
    with _lock:
        obj = _singletons.pop(window_cls, None)
    if obj is not None:
        _release(id(obj))


def alive_count() -> int:
    """当前被保活的**实例**数（供测试与诊断）。"""
    with _lock:
        return len(_keep_alive)
