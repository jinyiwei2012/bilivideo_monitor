"""Read-only per-video prediction and score queries with caller-owned caches."""

from typing import Any

from core.database.connection import open_readonly_connection


class PredictionRepository:
    """Load prediction and score supplements without retaining cursors."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path

    def load_extra_data(self, timestamp: str, cache: dict[str, dict] | None = None) -> dict[str, Any]:
        """Return cached prediction rows and nearest prior weekly/yearly scores."""
        connection = None if cache is None else cache["conns"].get(self._database_path)
        owns_connection = cache is None
        if connection is None:
            connection = open_readonly_connection(self._database_path)
            if connection is None:
                return {}
            if cache is not None:
                cache["conns"][self._database_path] = connection
                owns_connection = False
        try:
            if cache is not None:
                prediction_rows = cache["preds"].get(self._database_path)
                if prediction_rows is None:
                    prediction_rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT * FROM predictions ORDER BY algorithm ASC, created_at DESC"
                        )
                    ]
                    cache["preds"][self._database_path] = prediction_rows
            else:
                prediction_rows = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM predictions WHERE created_at <= ? ORDER BY algorithm, created_at DESC",
                        (timestamp,),
                    )
                ]
            return self._build_extra_data(connection, prediction_rows, timestamp)
        finally:
            if owns_connection:
                connection.close()

    @staticmethod
    def _build_extra_data(connection: Any, prediction_rows: list[dict[str, Any]], timestamp: str) -> dict[str, Any]:
        extra: dict[str, Any] = {"_predictions": _dedupe_latest_per_algo(prediction_rows, timestamp)}
        PredictionRepository._add_score(
            extra,
            connection.execute(
                "SELECT * FROM weekly_scores WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1", (timestamp,)
            ).fetchone(),
            "weekly",
            [
                "total_score",
                "view_score",
                "interaction_score",
                "favorite_score",
                "coin_score",
                "like_score",
                "correction_a",
                "correction_b",
                "correction_c",
                "correction_d",
                "base_view_score",
            ],
        )
        PredictionRepository._add_score(
            extra,
            connection.execute(
                "SELECT * FROM yearly_scores WHERE timestamp <= ? ORDER BY timestamp DESC LIMIT 1", (timestamp,)
            ).fetchone(),
            "yearly",
            [
                "total_score",
                "view_score",
                "interaction_score",
                "favorite_score",
                "coin_score",
                "like_score",
                "correction_a",
                "correction_b",
                "correction_c",
            ],
        )
        return extra

    @staticmethod
    def _add_score(extra: dict[str, Any], row: Any, prefix: str, fields: list[str]) -> None:
        if row is None:
            return
        values = dict(row)
        for field in fields:
            extra[f"{prefix}_{field}"] = values.get(field, "")


def _dedupe_latest_per_algo(prediction_rows: list[dict[str, Any]], timestamp: str) -> list[dict[str, Any]]:
    """Select each algorithm's latest prediction at or before one observation."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in prediction_rows:
        created_at = row.get("created_at")
        algorithm = row.get("algorithm")
        if created_at is None or created_at > timestamp or not isinstance(algorithm, str) or algorithm in seen:
            continue
        seen.add(algorithm)
        result.append(row)
    return result
