"""UI database boundaries must remain delegated to repository classes."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("relative_path", ["ui/database_query.py", "ui/online_viewers_panel.py"])
def test_ui_modules_do_not_embed_persistence_statements(relative_path: str) -> None:
    source = Path(relative_path).read_text(encoding="utf-8")
    forbidden = ("import sqlite3", "sqlite3.connect", "CREATE TABLE", "DELETE FROM", "INSERT INTO", "SELECT ")
    assert not [statement for statement in forbidden if statement in source]
