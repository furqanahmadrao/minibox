"""Persistent scheduler -- SQLite-backed cron with background runner."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Schedule:
    id: str
    sandbox_id: str
    name: str
    command: str
    cron: str  # simple: "*/5 * * * *" or "every 300"
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    created_at: float = field(default_factory=time.time)


def _parse_cron_interval(expr: str) -> float | None:
    """Parse simple cron expressions. Returns interval in seconds or None."""
    m = re.match(r"every\s+(\d+)", expr)
    if m:
        return float(m.group(1))

    m = re.match(r"\*/(\d+)\s+\*\s+\*\s+\*\s+\*", expr)
    if m:
        return float(m.group(1)) * 60

    if expr.strip() == "* * * * *":
        return 60.0

    return None


class SchedulerStore:
    """SQLite-backed schedule storage with execution locking."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._schedules: dict[str, Schedule] = {}
        self._executing: set[str] = set()
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path), check_same_thread=False,
            )
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            self._conn.commit()
        return self._conn

    async def initialize(self) -> None:
        try:
            conn = self._get_conn()
            for row in conn.execute("SELECT id, data FROM schedules"):
                data = json.loads(row[1])
                sched = Schedule(**data)
                self._schedules[sched.id] = sched
            logger.info("Loaded %d schedules", len(self._schedules))
        except Exception as e:
            logger.warning("Failed to load schedules: %s", e)

    async def _save(self) -> None:
        try:
            conn = self._get_conn()
            for sid, sched in self._schedules.items():
                data = {
                    "id": sched.id,
                    "sandbox_id": sched.sandbox_id,
                    "name": sched.name,
                    "command": sched.command,
                    "cron": sched.cron,
                    "enabled": sched.enabled,
                    "last_run": sched.last_run,
                    "next_run": sched.next_run,
                    "created_at": sched.created_at,
                }
                conn.execute(
                    "INSERT OR REPLACE INTO schedules (id, data) VALUES (?, ?)",
                    (sid, json.dumps(data)),
                )
            conn.commit()
        except Exception as e:
            logger.warning("Failed to save schedules: %s", e)

    async def add(self, schedule: Schedule) -> None:
        interval = _parse_cron_interval(schedule.cron)
        if interval:
            schedule.next_run = time.time() + interval
        self._schedules[schedule.id] = schedule
        await self._save()

    async def get(self, schedule_id: str) -> Schedule | None:
        return self._schedules.get(schedule_id)

    async def list_for_sandbox(self, sandbox_id: str) -> list[Schedule]:
        return [s for s in self._schedules.values() if s.sandbox_id == sandbox_id]

    async def list_all(self) -> list[Schedule]:
        return list(self._schedules.values())

    async def update(self, schedule_id: str, **kwargs) -> bool:
        sched = self._schedules.get(schedule_id)
        if not sched:
            return False
        for key, value in kwargs.items():
            if hasattr(sched, key):
                setattr(sched, key, value)
        if "cron" in kwargs:
            interval = _parse_cron_interval(sched.cron)
            if interval:
                sched.next_run = time.time() + interval
        await self._save()
        return True

    async def remove(self, schedule_id: str) -> bool:
        if schedule_id in self._schedules:
            del self._schedules[schedule_id]
            try:
                conn = self._get_conn()
                conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
                conn.commit()
            except Exception as e:
                logger.warning("Failed to delete schedule %s: %s", schedule_id, e)
            return True
        return False

    async def claim_due(self) -> list[Schedule]:
        """Atomically return due schedules and mark them as executing.

        Uses _executing set to prevent double-execution across ticks.
        """
        now = time.time()
        claimed: list[Schedule] = []
        for s in list(self._schedules.values()):
            if s.enabled and s.next_run <= now and s.id not in self._executing:
                self._executing.add(s.id)
                claimed.append(s)
        return claimed

    async def mark_done(self, schedule_id: str) -> None:
        """Mark a schedule as run, remove from executing set, compute next_run."""
        self._executing.discard(schedule_id)
        sched = self._schedules.get(schedule_id)
        if sched:
            sched.last_run = time.time()
            interval = _parse_cron_interval(sched.cron)
            if interval:
                sched.next_run = time.time() + interval
            else:
                sched.next_run = time.time() + 3600
            await self._save()

    async def release(self, schedule_id: str) -> None:
        """Release executing lock without marking as run (on error)."""
        self._executing.discard(schedule_id)
