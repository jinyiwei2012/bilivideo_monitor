"""Durable outbox delivery from video authority databases to central projections."""

from dataclasses import dataclass
import json
import threading
from typing import Any, Callable

from utils.time_utils import now_ts


@dataclass(frozen=True)
class ProjectionEvent:
    event_id: int
    stream: str
    entity_key: str
    source_row_id: int | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProjectionRunResult:
    delivered: int = 0
    failed: int = 0
    already_running: bool = False


class CentralProjector:
    """Project pending outbox rows while keeping central and local commits separate."""

    def __init__(self, central_db: Any, batch_size: int = 100, clock: Callable[[], str] = now_ts) -> None:
        self._central_db = central_db
        self._batch_size = batch_size
        self._clock = clock
        self._run_lock = threading.Lock()

    def project_video(self, video_db: Any) -> ProjectionRunResult:
        with video_db._get_connection() as conn:
            rows = conn.execute(
                "SELECT event_id, stream, entity_key, source_row_id, payload FROM projection_outbox "
                "WHERE delivered_at IS NULL ORDER BY event_id LIMIT ?",
                (self._batch_size,),
            ).fetchall()
        if not rows:
            return ProjectionRunResult()
        events = [ProjectionEvent(row[0], row[1], row[2], row[3], json.loads(row[4] or "{}")) for row in rows]
        try:
            self._central_db.apply_projection_batch(video_db.bvid, events)
        except Exception as error:
            with video_db._get_connection() as conn:
                conn.execute(
                    "UPDATE projection_outbox SET attempt_count=attempt_count+1, last_error=? WHERE event_id=?",
                    (str(error), events[0].event_id),
                )
            return ProjectionRunResult(failed=1)
        event_ids = [event.event_id for event in events]
        placeholders = ",".join("?" for _ in event_ids)
        with video_db._get_connection() as conn:
            conn.execute(
                f"UPDATE projection_outbox SET delivered_at=? WHERE event_id IN ({placeholders}) AND delivered_at IS NULL",
                (self._clock(), *event_ids),
            )
        return ProjectionRunResult(delivered=len(events))

    def project_pending(self, video_dbs: list[Any], max_videos: int | None = None) -> ProjectionRunResult:
        if not self._run_lock.acquire(blocking=False):
            return ProjectionRunResult(already_running=True)
        try:
            delivered = failed = 0
            for video_db in video_dbs[:max_videos]:
                result = self.project_video(video_db)
                delivered += result.delivered
                failed += result.failed
            return ProjectionRunResult(delivered, failed)
        finally:
            self._run_lock.release()
