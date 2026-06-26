"""Scheduler API endpoints."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, HTTPException

from src.api.deps import get_event_bus, get_registry
from src.config import get_config
from src.core.executor import exec_command
from src.core.sandbox import SandboxHandle
from src.models.sandbox import ExecResponse
from src.orchestration.events import Event

router = APIRouter(prefix="/api/sandbox", tags=["scheduler"])
logger = logging.getLogger(__name__)


def _get_store():
    from src.main import _scheduler_store
    return _scheduler_store


@router.post("/{sandbox_id}/schedules")
async def create_schedule(
    sandbox_id: str,
    name: str = Body(...),
    command: str = Body(...),
    cron: str = Body(...),
) -> dict:
    store = _get_store()
    if store is None:
        raise HTTPException(503, "Scheduler not initialized")

    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(404, "Sandbox not found")

    from src.core.scheduler import Schedule, _parse_cron_interval
    if _parse_cron_interval(cron) is None:
        raise HTTPException(
            400,
            "Invalid cron expression. Use: */N * * * *, * * * * *, or every N",
        )

    sched = Schedule(
        id=f"sch_{uuid.uuid4().hex[:12]}",
        sandbox_id=sandbox_id,
        name=name,
        command=command,
        cron=cron,
    )
    await store.add(sched)
    return {
        "schedule_id": sched.id,
        "name": name,
        "cron": cron,
        "enabled": True,
        "next_run": sched.next_run,
    }


@router.get("/{sandbox_id}/schedules")
async def list_schedules(sandbox_id: str) -> list[dict]:
    store = _get_store()
    if store is None:
        raise HTTPException(503, "Scheduler not initialized")

    scheds = await store.list_for_sandbox(sandbox_id)
    return [
        {
            "id": s.id,
            "name": s.name,
            "command": s.command,
            "schedule": s.cron,
            "enabled": s.enabled,
            "last_run": s.last_run,
            "next_run": s.next_run,
        }
        for s in scheds
    ]


@router.patch("/{sandbox_id}/schedules/{schedule_id}")
async def update_schedule(
    sandbox_id: str,
    schedule_id: str,
    enabled: bool | None = Body(None),
    name: str | None = Body(None),
    command: str | None = Body(None),
    cron: str | None = Body(None),
) -> dict:
    store = _get_store()
    if store is None:
        raise HTTPException(503, "Scheduler not initialized")

    sched = await store.get(schedule_id)
    if sched is None or sched.sandbox_id != sandbox_id:
        raise HTTPException(404, "Schedule not found")

    updates = {}
    if enabled is not None:
        updates["enabled"] = enabled
    if name is not None:
        updates["name"] = name
    if command is not None:
        updates["command"] = command
    if cron is not None:
        from src.core.scheduler import _parse_cron_interval
        if _parse_cron_interval(cron) is None:
            raise HTTPException(400, "Invalid cron expression")
        updates["cron"] = cron

    await store.update(schedule_id, **updates)
    return {"schedule_id": schedule_id, "updated": list(updates.keys())}


@router.delete("/{sandbox_id}/schedules/{schedule_id}")
async def delete_schedule(sandbox_id: str, schedule_id: str) -> dict:
    store = _get_store()
    if store is None:
        raise HTTPException(503, "Scheduler not initialized")

    sched = await store.get(schedule_id)
    if sched is None or sched.sandbox_id != sandbox_id:
        raise HTTPException(404, "Schedule not found")

    await store.remove(schedule_id)
    return {"schedule_id": schedule_id, "deleted": True}


@router.post("/{sandbox_id}/schedules/{schedule_id}/run")
async def run_schedule_now(sandbox_id: str, schedule_id: str) -> ExecResponse:
    """Manually trigger a scheduled command."""
    store = _get_store()
    if store is None:
        raise HTTPException(503, "Scheduler not initialized")

    sched = await store.get(schedule_id)
    if sched is None or sched.sandbox_id != sandbox_id:
        raise HTTPException(404, "Schedule not found")

    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(404, "Sandbox not found")
    if state.status != "running":
        raise HTTPException(400, f"Sandbox is {state.status}")

    config = get_config()
    handle = SandboxHandle(
        sandbox_id=sandbox_id,
        pid=state.pid or 0,
        workspace=config.sandbox.sandbox_dir(sandbox_id),
    )

    try:
        result = await exec_command(handle, sched.command)
    except Exception as e:
        logger.error("Manual schedule run failed for %s: %s", schedule_id, e)
        raise HTTPException(500, f"Command execution failed: {e}")

    event_bus = get_event_bus()
    await event_bus.publish(Event(
        sandbox_id=sandbox_id,
        event_type="schedule_run",
        data={
            "schedule_id": schedule_id,
            "cmd": sched.command,
            "exit_code": result.exit_code,
            "manual": True,
        },
    ))

    await store.mark_done(schedule_id)

    return ExecResponse(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        sandbox_id=sandbox_id,
    )
