"""Human-in-the-loop breakpoints for sandbox execution."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)


@dataclass
class Breakpoint:
    id: str
    sandbox_id: str
    pattern: str  # regex pattern to match against commands
    action: str = "pause"  # pause, notify, block
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


class BreakpointManager:
    """Manages HITL breakpoints for sandboxes."""

    def __init__(self) -> None:
        self._breakpoints: dict[str, Breakpoint] = {}

    def add_breakpoint(
        self,
        sandbox_id: str,
        pattern: str,
        action: str = "pause",
    ) -> Breakpoint:
        """Add a breakpoint to a sandbox."""
        bp_id = f"bp_{int(time.time() * 1000)}"
        bp = Breakpoint(
            id=bp_id,
            sandbox_id=sandbox_id,
            pattern=pattern,
            action=action,
        )
        self._breakpoints[bp_id] = bp
        logger.info("Breakpoint %s added to sandbox %s: %s", bp_id, sandbox_id, pattern)
        return bp

    def check_exec(self, sandbox_id: str, cmd: str) -> Breakpoint | None:
        """Check if a command triggers any breakpoint."""
        for bp in self._breakpoints.values():
            if bp.sandbox_id == sandbox_id:
                if re.search(bp.pattern, cmd):
                    bp.hit_count += 1
                    logger.info("Breakpoint %s hit (count=%d)", bp.id, bp.hit_count)
                    return bp
        return None

    def remove_breakpoint(self, bp_id: str) -> bool:
        """Remove a breakpoint."""
        if bp_id in self._breakpoints:
            del self._breakpoints[bp_id]
            return True
        return False

    def list_breakpoints(self, sandbox_id: str | None = None) -> list[Breakpoint]:
        """List breakpoints, optionally filtered by sandbox."""
        bps = list(self._breakpoints.values())
        if sandbox_id:
            bps = [bp for bp in bps if bp.sandbox_id == sandbox_id]
        return bps
