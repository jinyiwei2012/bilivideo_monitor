"""Read-only application state snapshots for future panel migration.

This module deliberately observes the existing main-window state contract without
owning or mutating it.  Panels can later receive an ``AppState`` instead of a
main-window reference while the current UI remains unchanged.
"""

from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Tuple, TypeVar

from PyQt6.QtCore import QObject, pyqtSignal

T = TypeVar("T")


def _freeze_snapshot(value: Any) -> Any:
    """Recursively copy ordinary data containers into immutable equivalents.

    Application records are dictionaries, lists, tuples, and sets of scalar
    values.  Non-container values deliberately remain unchanged: copying Qt
    objects, prediction-domain objects, or database resources is unsafe and is
    outside this skeleton's data-snapshot boundary.
    """
    if isinstance(value, dict):
        return MappingProxyType({_freeze_snapshot(key): _freeze_snapshot(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_snapshot(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_snapshot(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_snapshot(item) for item in value)
    return value


class AppState(QObject):
    """Expose read-only snapshots of the main window's shared data containers."""

    video_updated = pyqtSignal(str)
    selection_changed = pyqtSignal(str)
    prediction_updated = pyqtSignal(str)

    def __init__(self, host: object) -> None:
        super().__init__()
        self._host = host

    def _read_data_locked(self, reader: Callable[[], T]) -> T:
        """Read a state field while respecting the host's existing data lock."""
        data_lock = getattr(self._host, "_data_lock", None)
        if data_lock is None:
            return reader()
        with data_lock:
            return reader()

    def _data_snapshot(self, field_name: str) -> Any:
        """Capture and recursively freeze one ordinary shared-data field."""
        return self._read_data_locked(lambda: _freeze_snapshot(getattr(self._host, field_name)))

    @property
    def monitored_videos(self) -> Tuple[Any, ...]:
        """Return a snapshot of the monitored-video sequence."""
        return self._data_snapshot("monitored_videos")

    @property
    def history_data(self) -> Mapping[str, Any]:
        """Return a read-only snapshot of history data keyed by BVID."""
        return self._data_snapshot("history_data")

    @property
    def prediction_results(self) -> Mapping[str, Any]:
        """Return a read-only snapshot of prediction results keyed by BVID."""
        return self._data_snapshot("prediction_results")

    @property
    def video_dbs(self) -> Mapping[str, Any]:
        """Return a compatibility membership snapshot of opaque database handles.

        The mapping membership is captured under the lifecycle DB lock after the
        data lock, which matches the documented lock ordering.  Its values are
        existing mutable resource handles, not immutable resources; future
        panels must use a repository/accessor rather than this compatibility
        property for database work.
        """

        def capture_membership() -> Mapping[str, Any]:
            video_db_lock = getattr(self._host, "_video_db_lock", None)
            if video_db_lock is None:
                return MappingProxyType(dict(getattr(self._host, "video_dbs")))
            with video_db_lock:
                return MappingProxyType(dict(getattr(self._host, "video_dbs")))

        return self._read_data_locked(capture_membership)

    @property
    def selected_bvid(self) -> Optional[str]:
        """Return the currently selected BVID, if a video is selected."""
        selected_bvid = self._read_data_locked(lambda: getattr(self._host, "selected_bvid"))
        return selected_bvid if isinstance(selected_bvid, str) else None

    @property
    def _video_index(self) -> Mapping[str, Any]:
        """Return a read-only snapshot of the existing O(1) BVID index."""
        return self._data_snapshot("_video_index")

    @property
    def video_index(self) -> Mapping[str, Any]:
        """Provide a public alias for the main window's private index contract."""
        return self._video_index

    def notify_video_updated(self, bvid: str) -> None:
        """Publish a future video-update notification without changing state."""
        self.video_updated.emit(bvid)

    def notify_selection_changed(self) -> None:
        """Publish the current selection, using an empty string for no selection."""
        self.selection_changed.emit(self.selected_bvid or "")

    def notify_prediction_updated(self, bvid: str) -> None:
        """Publish a future prediction-update notification without changing state."""
        self.prediction_updated.emit(bvid)
