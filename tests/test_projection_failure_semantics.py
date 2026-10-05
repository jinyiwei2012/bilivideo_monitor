"""B5-b failure-window contract placeholders before outbox implementation."""

from pathlib import Path

import pytest


@pytest.mark.xfail(strict=True, reason="4.2 尚未引入 projection_outbox")
def test_outbox_schema_will_cover_business_and_delivery_failure_windows() -> None:
    design = Path("docs/b5b_projection_design.md").read_text(encoding="utf-8")
    assert "projection_outbox" not in Path("core/database/video_db.py").read_text(encoding="utf-8")
    assert "业务数据写入与 outbox 插入必须位于同一 SQLite 事务" in design
    assert "中央事务提交后才回标源 outbox" in design
    raise AssertionError("projection_outbox failure-window implementation is intentionally pending")
