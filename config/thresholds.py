"""Headless threshold configuration state shared by core and UI layers."""

from collections.abc import Callable
from typing import Any

THRESHOLDS: list[int] = []
THRESHOLD_NAMES: list[str] = []
_reload_listeners: list[Callable[[], None]] = []


def auto_threshold_name(value: int) -> str:
    """Return the display name for a threshold value."""
    if value >= 100_000_000:
        return f"{value / 100_000_000:.0f}亿"
    if value >= 10_000:
        wan = value / 10_000
        if wan == int(wan):
            return f"{int(wan)}万"
        return f"{wan}万"
    return str(value)


def _load_threshold_entries() -> list[Any]:
    """Load configured threshold entries, falling back to configuration defaults."""
    try:
        from config import DEFAULT_CONFIG, load_config

        configured = load_config().get("prediction", {}).get("thresholds", [])
        if configured:
            return configured
        return DEFAULT_CONFIG["prediction"]["thresholds"]
    except Exception:
        from config import DEFAULT_CONFIG

        return DEFAULT_CONFIG["prediction"]["thresholds"]


def reload_thresholds() -> None:
    """Reload threshold values and names while preserving exported list identities."""
    raw = _load_threshold_entries()
    values: list[int] = []
    names: list[str] = []
    if raw and isinstance(raw[0], (list, tuple)):
        for item in raw:
            value = int(item[0])
            name = str(item[1]) if len(item) > 1 else auto_threshold_name(value)
            values.append(value)
            names.append(name)
    else:
        values = [int(value) for value in raw]
        names = [auto_threshold_name(value) for value in values]

    pairs = sorted(zip(values, names), key=lambda pair: pair[0])
    THRESHOLDS[:] = [value for value, _name in pairs]
    THRESHOLD_NAMES[:] = [name for _value, name in pairs]
    for listener in _reload_listeners:
        listener()


def add_reload_listener(listener: Callable[[], None]) -> None:
    """Register a non-UI-specific observer of in-place threshold reloads."""
    _reload_listeners.append(listener)


reload_thresholds()
