"""FastAPI dependency injection."""

from __future__ import annotations


from src.config import get_config
from src.orchestration.breakpoints import BreakpointManager
from src.orchestration.events import EventBus
from src.orchestration.registry import Registry

_registry: Registry | None = None
_event_bus: EventBus | None = None
_breakpoint_manager: BreakpointManager | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        config = get_config()
        db_path = config.sandbox.workspace_root.parent / "minibox.db"
        _registry = Registry(db_path=db_path)
    return _registry


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def get_breakpoint_manager() -> BreakpointManager:
    global _breakpoint_manager
    if _breakpoint_manager is None:
        _breakpoint_manager = BreakpointManager()
    return _breakpoint_manager
