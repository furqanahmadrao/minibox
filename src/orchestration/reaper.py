"""Background reaper that destroys expired sandboxes."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from src.orchestration.registry import Registry

logger = logging.getLogger(__name__)


class Reaper:
    """Periodically checks for expired sandboxes and destroys them."""

    def __init__(
        self,
        registry: Registry,
        check_interval: float = 30.0,
        on_destroy: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._registry = registry
        self._check_interval = check_interval
        self._on_destroy = on_destroy
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_commit_times: dict[str, float] = {}

    async def start(self) -> None:
        """Start the reaper background task."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Reaper started (interval=%.1fs)", self._check_interval)

    async def stop(self) -> None:
        """Stop the reaper."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Reaper stopped")

    async def _loop(self) -> None:
        """Main reaper loop."""
        import time
        from pathlib import Path
        while self._running:
            try:
                expired = await self._registry.get_expired()
                for sandbox_id in expired:
                    logger.info("Reaping expired sandbox %s", sandbox_id)
                    await self._registry.update(sandbox_id, status="destroyed")
                    if self._on_destroy:
                        try:
                            await self._on_destroy(sandbox_id)
                        except Exception as e:
                            logger.error("Failed to destroy sandbox %s: %s", sandbox_id, e)
                
                # Clean up destroyed sandboxes older than 24 hours
                all_sandboxes = await self._registry.list_all()
                for state in all_sandboxes:
                    if state.status == "destroyed":
                        if time.time() - state.last_activity >= 86400:
                            logger.info("Purging old destroyed sandbox %s from registry", state.sandbox_id)
                            await self._registry.remove(state.sandbox_id)

                # Periodic Git Auto-Commit for active sandboxes
                from src.config import get_config
                cfg = get_config()
                commit_interval = cfg.sandbox.git_commit_interval
                
                for state in all_sandboxes:
                    if state.status == "running":
                        sandbox_id = state.sandbox_id
                        last_time = self._last_commit_times.get(sandbox_id, state.created_at)
                        if time.time() - last_time >= commit_interval:
                            workspace_path = cfg.sandbox.sandbox_dir(sandbox_id)
                            if workspace_path.exists():
                                committed = await _run_git_auto_commit(workspace_path)
                                if committed:
                                    logger.info("Created Git auto-commit for sandbox %s", sandbox_id)
                            self._last_commit_times[sandbox_id] = time.time()
            except Exception as e:
                logger.error("Reaper loop error: %s", e)

            await asyncio.sleep(self._check_interval)


async def _run_git_auto_commit(workspace_path: Path) -> bool:
    """Check for dirty files in the workspace and commit them asynchronously."""
    import subprocess
    import datetime

    def _git_commit():
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=str(workspace_path), capture_output=True, text=True)
        if status_res.returncode == 0 and status_res.stdout.strip():
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subprocess.run(["git", "add", "."], cwd=str(workspace_path), capture_output=True)
            subprocess.run(["git", "commit", "-m", f"Auto-commit: {timestamp}"], cwd=str(workspace_path), capture_output=True)
            return True
        return False

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _git_commit)

