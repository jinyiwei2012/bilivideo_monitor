"""Process-lifetime projection routing; configuration changes require restart."""

import logging
import threading

_lock = threading.Lock()
_effective_mode: str | None = None
logger = logging.getLogger(__name__)


def resolve_projection_mode(mode: str) -> str:
    """Validate the configured mode and map unsupported shadow writes safely."""
    if mode == "shadow":
        logger.warning("projection.mode=shadow maps to projector; independent shadow target is not implemented")
        return "projector"
    if mode not in ("legacy", "projector"):
        raise ValueError(f"Invalid projection.mode: {mode!r}")
    return mode


def effective_projection_mode() -> str:
    """Freeze the effective routing policy on first runtime creation/use."""
    global _effective_mode
    with _lock:
        if _effective_mode is None:
            from config import load_config

            section = load_config().get("projection", {})
            _effective_mode = resolve_projection_mode(section.get("mode", "projector"))
        return _effective_mode


def legacy_central_writes_enabled() -> bool:
    return effective_projection_mode() == "legacy"


def projector_enabled() -> bool:
    return effective_projection_mode() == "projector"
