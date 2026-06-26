"""In-memory + SQLite sandbox registry."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SandboxState:
    def __init__(
        self,
        sandbox_id: str,
        template: str = "minimal",
        status: str = "pending",
        label: str = "",
        ttl: int = 1800,
        cpu_cores: float = 2.0,
        memory_mb: int = 512,
        network_mode: str = "egress-only",
        egress_allowlist: list[str] | None = None,
        env: dict[str, str] | None = None,
        pid: int | None = None,
        exec_count: int = 0,
        port_forwards: list[dict] | None = None,
        agent_config: dict | None = None,
        created_at: float | None = None,
        last_activity: float | None = None,
        # Per-sandbox security config
        security: dict | None = None,
        network_config: dict | None = None,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.template = template
        self.status = status
        self.label = label
        self.ttl = ttl
        self.cpu_cores = cpu_cores
        self.memory_mb = memory_mb
        self.network_mode = network_mode
        self.egress_allowlist = egress_allowlist or []
        self.env = env or {}
        self.pid = pid
        self.exec_count = exec_count
        self.port_forwards = port_forwards or []
        self.agent_config = agent_config or {}
        self.created_at = created_at or time.time()
        self.last_activity = last_activity or time.time()
        self.security = security or {}
        self.network_config = network_config or {}

    @property
    def ttl_remaining(self) -> float:
        return max(0, self.ttl - (time.time() - self.last_activity))

    def touch(self) -> None:
        self.last_activity = time.time()

    def to_dict(self) -> dict:
        return {
            "sandbox_id": self.sandbox_id,
            "template": self.template,
            "status": self.status,
            "label": self.label,
            "ttl": self.ttl,
            "cpu_cores": self.cpu_cores,
            "memory_mb": self.memory_mb,
            "network_mode": self.network_mode,
            "egress_allowlist": self.egress_allowlist,
            "env": self.env,
            "pid": self.pid,
            "exec_count": self.exec_count,
            "port_forwards": self.port_forwards,
            "agent_config": self.agent_config,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "security": self.security,
            "network_config": self.network_config,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SandboxState:
        valid = {k: v for k, v in data.items() if k in cls.__init__.__code__.co_varnames}
        return cls(**valid)


class Registry:
    def __init__(self, db_path: Path | None = None) -> None:
        self._states: dict[str, SandboxState] = {}
        self._db_path = db_path

    async def initialize(self) -> None:
        if self._db_path and self._db_path.exists():
            try:
                import sqlite3

                conn = sqlite3.connect(str(self._db_path))
                for row in conn.execute("SELECT data FROM sandboxes"):
                    state = SandboxState.from_dict(json.loads(row[0]))
                    self._states[state.sandbox_id] = state
                conn.close()
            except Exception as e:
                logger.warning("Failed to load registry: %s", e)

    async def _save(self) -> None:
        if not self._db_path:
            return
        try:
            import sqlite3

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("CREATE TABLE IF NOT EXISTS sandboxes (id TEXT PRIMARY KEY, data TEXT)")
            for sid, state in self._states.items():
                conn.execute(
                    "INSERT OR REPLACE INTO sandboxes (id, data) VALUES (?, ?)",
                    (sid, json.dumps(state.to_dict())),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to save registry: %s", e)

    async def register(self, state: SandboxState) -> None:
        self._states[state.sandbox_id] = state
        await self._save()

    async def get(self, sandbox_id: str) -> SandboxState | None:
        return self._states.get(sandbox_id)

    async def update(self, sandbox_id: str, **kwargs) -> None:
        state = self._states.get(sandbox_id)
        if state:
            for key, value in kwargs.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            state.touch()
            await self._save()

    async def remove(self, sandbox_id: str) -> bool:
        if sandbox_id in self._states:
            del self._states[sandbox_id]
            if self._db_path:
                try:
                    import sqlite3
                    conn = sqlite3.connect(str(self._db_path))
                    conn.execute("DELETE FROM sandboxes WHERE id = ?", (sandbox_id,))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.warning("Failed to delete sandbox %s from database: %s", sandbox_id, e)
            return True
        return False

    async def list_all(self, status: str | None = None) -> list[SandboxState]:
        states = list(self._states.values())
        if status:
            states = [s for s in states if s.status == status]
        return states

    async def count_running(self) -> int:
        return len([s for s in self._states.values() if s.status == "running"])

    async def get_expired(self) -> list[str]:
        return [
            sid for sid, s in self._states.items() if s.status == "running" and s.ttl_remaining <= 0
        ]
