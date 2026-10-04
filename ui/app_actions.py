"""Injectable action facade for a future AppState/AppActions panel boundary.

The facade delegates to existing main-window handlers.  It is intentionally not
wired into panels yet, so adding it cannot change current application behavior.
"""

from typing import Any, Optional


class AppActions:
    """Delegate user intents to the established main-window event handlers."""

    def __init__(self, host: object) -> None:
        self._host = host

    def add_monitor(self) -> None:
        """Open the existing add-monitor flow."""
        from ui import main_gui_events_monitor

        main_gui_events_monitor.add_monitor(self._host)

    def remove_monitor(self) -> None:
        """Run the existing remove-selected-monitor flow."""
        from ui import main_gui_events_monitor

        main_gui_events_monitor.remove_monitor(self._host)

    def refresh(self) -> None:
        """Run the existing manual fetch flow."""
        from ui import main_gui_events_runtime

        main_gui_events_runtime.do_fetch(self._host)

    def select_video(self, bvid: str) -> None:
        """Select a video through the existing selection handler."""
        from ui import main_gui_events_monitor

        main_gui_events_monitor.select_video(self._host, bvid)

    def get_video(self, bvid: str) -> Any:
        """Look up a video through the existing O(1) monitor index helper."""
        from ui import main_gui_events_monitor

        return main_gui_events_monitor.get_video(self._host, bvid)

    def push(self, bvid: Optional[str] = None) -> None:
        """Push one selected BVID or all monitored videos using current handlers."""
        from ui import main_gui_events_runtime

        if bvid is None:
            main_gui_events_runtime.manual_push(self._host)
            return
        main_gui_events_runtime.push_single(self._host, bvid)

    def copy_bvid(self, bvid: str) -> None:
        """Copy a BVID through the existing main-window event handler."""
        from ui import main_gui_events_monitor

        main_gui_events_monitor.copy_bvid(self._host, bvid)

    def set_finetune_status(self, text: str, color: Optional[str] = None) -> None:
        """Delegate finetune status rendering to the host's established method."""
        set_status = getattr(self._host, "set_finetune_status")
        set_status(text, color)
