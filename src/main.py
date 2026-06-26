"""Minibox — FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.acp import router as acp_router
from src.api.agent import router as agent_router
from src.api.auth import router as auth_router
from src.api.deps import get_registry
from src.api.exec import router as exec_router
from src.api.filesystem import router as fs_router
from src.api.network import router as network_router
from src.api.sandbox import router as sandbox_router
from src.api.schedules import router as schedules_router
from src.api.snapshots import router as snapshots_router
from src.api.templates import router as templates_router
from src.api.admin_config import router as admin_config_router
from src.auth import APIKeyStore, AuthMiddleware, rate_limiter
from src.config import get_config
from src.logging import setup_logging
from src.orchestration.reaper import Reaper

logger = logging.getLogger(__name__)

_reaper: Reaper | None = None
_scheduler_store = None
_scheduler_task = None


from src.api.auth import _get_api_key_store as get_api_key_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _reaper
    config = get_config()
    setup_logging(
        level=config.logging.level,
        fmt=config.logging.format,
        log_file=config.logging.file,
    )

    config.sandbox.workspace_root.mkdir(parents=True, exist_ok=True)
    config.storage.snapshot_path.mkdir(parents=True, exist_ok=True)

    from src.core.network import cleanup_orphaned_forwards, init_forward_store

    fwd_db = config.sandbox.workspace_root.parent / "port_forwards.db"
    init_forward_store(fwd_db)
    await cleanup_orphaned_forwards()

    registry = get_registry()
    await registry.initialize()

    async def on_destroy(sandbox_id: str):
        import shutil

        from src.core.sandbox import SandboxHandle, destroy_sandbox

        state = await registry.get(sandbox_id)
        if state and state.pid:
            handle = SandboxHandle(
                sandbox_id=sandbox_id,
                pid=state.pid,
                workspace=config.sandbox.sandbox_dir(sandbox_id),
            )
            await destroy_sandbox(handle)
        workspace = config.sandbox.sandbox_dir(sandbox_id)
        if workspace.exists():
            try:
                shutil.rmtree(workspace, ignore_errors=True)
            except Exception as e:
                logger.warning("Failed to remove workspace %s: %s", workspace, e)

    _reaper = Reaper(registry, check_interval=30.0, on_destroy=on_destroy)
    await _reaper.start()

    global _scheduler_store, _scheduler_task
    from src.core.scheduler import SchedulerStore

    sched_db = config.sandbox.workspace_root.parent / "schedules.db"
    _scheduler_store = SchedulerStore(sched_db)
    await _scheduler_store.initialize()

    async def _scheduler_runner():
        from src.core.executor import exec_command
        from src.core.sandbox import SandboxHandle as SH

        while True:
            try:
                due = await _scheduler_store.claim_due()
                for sched in due:
                    try:
                        state = await registry.get(sched.sandbox_id)
                        if state is None or state.status != "running":
                            await _scheduler_store.mark_done(sched.id)
                            continue
                        handle = SH(
                            sandbox_id=sched.sandbox_id,
                            pid=state.pid or 0,
                            workspace=config.sandbox.sandbox_dir(sched.sandbox_id),
                        )
                        result = await exec_command(handle, sched.command, timeout=60.0)
                        if result.exit_code != 0:
                            logger.warning(
                                "Schedule %s command exited %d: %s",
                                sched.id,
                                result.exit_code,
                                result.stderr[:200],
                            )
                        await _scheduler_store.mark_done(sched.id)
                    except Exception as e:
                        logger.error("Schedule %s execution failed: %s", sched.id, e)
                        await _scheduler_store.release(sched.id)
            except Exception as e:
                logger.warning("Scheduler tick error: %s", e)
            await asyncio.sleep(10)

    _scheduler_task = asyncio.create_task(_scheduler_runner())

    # Run MCP server lifespan inside parent lifespan to ensure its async task group is initialized
    logger.info("Minibox started on %s:%d", config.server.host, config.server.port)
    yield

    if _scheduler_task:
        _scheduler_task.cancel()
    if _reaper:
        await _reaper.stop()
    logger.info("Minibox stopped")


def create_app() -> FastAPI:
    config = get_config()

    from src.mcp.server import get_mcp_http_app
    mcp_app = get_mcp_http_app()

    from fastmcp.utilities.lifespan import combine_lifespans
    combined_lifespan = combine_lifespans(lifespan, mcp_app.lifespan)

    app = FastAPI(title="Minibox", version="0.1.0", lifespan=combined_lifespan)

    # Configure rate limiter from settings
    rate_limiter._rpm = config.security.rate_limit_rpm
    rate_limiter._burst = config.security.rate_limit_burst

    # CORS — use configured origins instead of wildcard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.security.cors_origins,
        allow_credentials=config.security.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    # Auth middleware — MCP is NOT exempt anymore
    app.add_middleware(
        AuthMiddleware,
        api_key_store=get_api_key_store(),
        allowed_origins=config.security.cors_origins,
    )

    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(acp_router)
    app.include_router(sandbox_router)
    app.include_router(schedules_router)
    app.include_router(exec_router)
    app.include_router(fs_router)
    app.include_router(network_router)
    app.include_router(snapshots_router)
    app.include_router(templates_router)
    app.include_router(admin_config_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Mount MCP server at /mcp
    from src.mcp.transport import mount_mcp

    try:
        mount_mcp(app)
    except Exception as e:
        logger.warning("MCP server could not be mounted: %s", e)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
