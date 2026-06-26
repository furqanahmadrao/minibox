"""Network API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import get_registry
from src.config import get_config
from src.core.network import expose_port, list_forwards, remove_port
from src.models.sandbox import PortExposeRequest

router = APIRouter(prefix="/api/sandbox", tags=["network"])


@router.post("/{sandbox_id}/port/expose")
async def expose_port_endpoint(sandbox_id: str, req: PortExposeRequest) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    forward = await expose_port(
        sandbox_id=sandbox_id,
        workspace_path=str(get_config().sandbox.sandbox_dir(sandbox_id)),
        port=req.port,
        host_port=req.host_port,
        sandbox_pid=state.pid,
    )
    return {
        "sandbox_id": sandbox_id,
        "port": forward.port,
        "host_port": forward.host_port,
        "url": f"http://localhost:{forward.host_port}",
    }


@router.delete("/{sandbox_id}/port/{port}")
async def remove_port_endpoint(sandbox_id: str, port: int) -> dict:
    removed = await remove_port(sandbox_id, port)
    if not removed:
        raise HTTPException(status_code=404, detail="Port forward not found")
    return {"removed": True, "port": port}


@router.get("/{sandbox_id}/ports")
async def list_ports_endpoint(sandbox_id: str) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    forwards = list_forwards(sandbox_id)
    return {
        "sandbox_id": sandbox_id,
        "forwards": [
            {"port": f.port, "host_port": f.host_port}
            for f in forwards
        ],
    }
