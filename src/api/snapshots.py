"""Snapshot API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import get_registry
from src.config import get_config
from src.core.sandbox import SandboxConfig, create_sandbox
from src.core.snapshots import (
    create_snapshot,
    delete_snapshot,
    fork_sandbox,
    list_snapshots,
    restore_snapshot,
)
from src.models.sandbox import ForkRequest, SnapshotRequest
from src.orchestration.registry import SandboxState

router = APIRouter(prefix="/api/sandbox", tags=["snapshots"])


@router.post("/{sandbox_id}/snapshot")
async def snapshot_endpoint(sandbox_id: str, req: SnapshotRequest) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    config = get_config()
    workspace = config.sandbox.sandbox_dir(sandbox_id)
    return await create_snapshot(sandbox_id, workspace, config.storage.snapshot_path, req.label)


@router.post("/{sandbox_id}/restore/{snapshot_id}")
async def restore_endpoint(sandbox_id: str, snapshot_id: str) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    config = get_config()
    workspace = config.sandbox.sandbox_dir(sandbox_id)
    return await restore_snapshot(sandbox_id, workspace, config.storage.snapshot_path, snapshot_id)


@router.post("/{sandbox_id}/fork")
async def fork_endpoint(sandbox_id: str, req: ForkRequest) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    import uuid

    config = get_config()
    new_id = str(uuid.uuid4())
    sb_config = SandboxConfig(sandbox_id=new_id)
    handle = await create_sandbox(sb_config, config.sandbox.workspace_root)

    # If a snapshot_id was provided, restore from snapshot first, then fork
    if req.snapshot_id:
        await restore_snapshot(
            sandbox_id,
            config.sandbox.sandbox_dir(sandbox_id),
            config.storage.snapshot_path,
            req.snapshot_id,
        )

    await fork_sandbox(
        sandbox_id, handle.sandbox_id, config.sandbox.workspace_root, config.storage.snapshot_path
    )

    fork_state = SandboxState(
        sandbox_id=handle.sandbox_id,
        template=state.template,
        status="running",
        label=req.label or f"fork of {sandbox_id}",
        ttl=state.ttl,
        cpu_cores=state.cpu_cores,
        memory_mb=state.memory_mb,
        network_mode=state.network_mode,
        egress_allowlist=list(state.egress_allowlist),
        env=dict(state.env),
        pid=handle.pid,
    )
    fork_state.touch()
    await registry.register(fork_state)

    return {"sandbox_id": handle.sandbox_id, "source": sandbox_id, "status": "running"}


@router.get("/{sandbox_id}/snapshots")
async def list_snapshots_endpoint(sandbox_id: str) -> list[dict]:
    return await list_snapshots(sandbox_id, get_config().storage.snapshot_path)


@router.delete("/{sandbox_id}/snapshots/{snapshot_id}")
async def delete_snapshot_endpoint(sandbox_id: str, snapshot_id: str) -> dict:
    deleted = await delete_snapshot(sandbox_id, get_config().storage.snapshot_path, snapshot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"deleted": True}
