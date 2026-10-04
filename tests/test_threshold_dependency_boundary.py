"""Regression tests for the headless threshold dependency boundary."""

import ast
from pathlib import Path

import pytest

import config
from config import thresholds as shared_thresholds
from core import threshold_escalation
from ui import helpers

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def restore_shared_thresholds():
    """Keep global threshold state isolated from the rest of the test suite."""
    values = list(shared_thresholds.THRESHOLDS)
    names = list(shared_thresholds.THRESHOLD_NAMES)
    colors = list(helpers.THRESH_COLORS)
    yield
    shared_thresholds.THRESHOLDS[:] = values
    shared_thresholds.THRESHOLD_NAMES[:] = names
    helpers.THRESH_COLORS[:] = colors


def _prediction_config(entries):
    return {"prediction": {"thresholds": entries, "auto_escalate": True, "escalate_factor": 5.0}}


def test_ui_threshold_exports_keep_identity_and_reload_custom_levels(monkeypatch):
    """Legacy UI imports retain shared list identity across reloads."""
    threshold_reference = helpers.THRESHOLDS
    name_reference = helpers.THRESHOLD_NAMES
    color_reference = helpers.THRESH_COLORS
    monkeypatch.setattr(shared_thresholds, "_load_threshold_entries", lambda: [[900000, "90万"], [100000, "十万"]])

    helpers.reload_thresholds()

    assert helpers.THRESHOLDS is shared_thresholds.THRESHOLDS is threshold_reference
    assert helpers.THRESHOLD_NAMES is shared_thresholds.THRESHOLD_NAMES is name_reference
    assert helpers.THRESH_COLORS is color_reference
    assert threshold_reference == [100000, 900000]
    assert name_reference == ["十万", "90万"]
    assert len(color_reference) == len(threshold_reference)


def test_shared_threshold_reload_uses_default_levels_when_config_is_empty(monkeypatch):
    """An empty configured list retains the documented default threshold levels."""
    monkeypatch.setattr(config, "load_config", lambda: _prediction_config([]))
    shared_thresholds.reload_thresholds()

    assert shared_thresholds.THRESHOLDS == [100000, 1000000, 10000000]
    assert shared_thresholds.THRESHOLD_NAMES == ["10万", "100万", "1000万"]


def test_escalation_reloads_shared_thresholds_and_ui_colors(monkeypatch):
    """A core-triggered reload keeps imported UI colors aligned without UI imports."""
    config = _prediction_config([[100000, "10万"]])
    saved = []
    monkeypatch.setattr("config.load_config", lambda: config)
    monkeypatch.setattr("config.save_config", lambda value: saved.append(value) or True)
    monkeypatch.setattr(threshold_escalation, "_send", lambda _title, _body: None)
    monkeypatch.setattr(threshold_escalation, "_log", lambda _gui, _level, _message: None)
    monkeypatch.setattr(shared_thresholds, "_load_threshold_entries", lambda: config["prediction"]["thresholds"])
    shared_thresholds.reload_thresholds()

    threshold_escalation._apply_escalation(None, "BV1test", "test", 100000, 500000)

    assert saved
    assert config["prediction"]["thresholds"] == [[100000, "10万"], [500000, "50万"]]
    assert shared_thresholds.THRESHOLDS == [100000, 500000]
    assert shared_thresholds.THRESHOLD_NAMES == ["10万", "50万"]
    assert len(helpers.THRESH_COLORS) == len(shared_thresholds.THRESHOLDS)


def test_core_modules_do_not_import_ui():
    """Core must remain independent of the PyQt UI package."""
    violations = []
    for path in (PROJECT_ROOT / "core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{path.relative_to(PROJECT_ROOT)}:{alias.name}"
                    for alias in node.names
                    if alias.name == "ui" or alias.name.startswith("ui.")
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (node.module == "ui" or node.module.startswith("ui."))
            ):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.module}")

    assert violations == []
