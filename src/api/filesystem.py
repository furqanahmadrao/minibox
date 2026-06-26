"""Filesystem API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import get_registry
from src.config import get_config
from src.core.filesystem import read_file, write_file, list_tree, delete_file, glob_files
from src.models.sandbox import FileWriteRequest, FileResponse

router = APIRouter(prefix="/api/sandbox", tags=["filesystem"])


def _workspace(sandbox_id: str):
    return get_config().sandbox.sandbox_dir(sandbox_id)


@router.post("/{sandbox_id}/fs/write", response_model=FileResponse)
async def write_file_endpoint(sandbox_id: str, req: FileWriteRequest) -> FileResponse:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    result = await write_file(_workspace(sandbox_id), req.path, req.content)
    return FileResponse(**result)


@router.get("/{sandbox_id}/fs/read")
async def read_file_endpoint(sandbox_id: str, path: str) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return await read_file(_workspace(sandbox_id), path)


@router.get("/{sandbox_id}/fs/tree")
async def tree_endpoint(sandbox_id: str, path: str = "/") -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return await list_tree(_workspace(sandbox_id), path)


@router.delete("/{sandbox_id}/fs/delete")
async def delete_file_endpoint(sandbox_id: str, path: str) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return await delete_file(_workspace(sandbox_id), path)


@router.get("/{sandbox_id}/fs/glob")
async def glob_endpoint(sandbox_id: str, pattern: str) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return await glob_files(_workspace(sandbox_id), pattern)
