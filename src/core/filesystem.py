"""File operations inside sandboxes — with strict path validation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import HTTPException


def validate_path(requested: str, workspace: Path) -> Path:
    """Validate path stays inside workspace. Blocks symlinks, traversal.

    Returns resolved host path.
    Raises HTTPException on violation.
    """
    # Normalize the path — strip leading slashes, resolve .. components
    rel = requested.lstrip("/")
    if not rel:
        return workspace.resolve()

    target = (workspace / rel).resolve()
    workspace_resolved = workspace.resolve()

    # Check it's inside workspace
    if not target.is_relative_to(workspace_resolved):
        raise HTTPException(status_code=403, detail="Path outside workspace")

    # Block symlinks — check each component from workspace up to target
    # to ensure nothing is a symlink pointing outside
    parts = target.relative_to(workspace_resolved).parts
    current = workspace_resolved
    for part in parts:
        next_path = current / part
        if next_path.is_symlink():
            # Resolve the symlink target
            link_target = os.readlink(str(next_path))
            # If it's absolute and outside workspace, block
            if os.path.isabs(link_target):
                resolved_link = Path(link_target).resolve()
                if not resolved_link.is_relative_to(workspace_resolved):
                    raise HTTPException(
                        status_code=403,
                        detail="Symlink escape detected",
                    )
            else:
                # Relative symlink — resolve it
                resolved_link = (next_path.parent / link_target).resolve()
                if not resolved_link.is_relative_to(workspace_resolved):
                    raise HTTPException(
                        status_code=403,
                        detail="Symlink escape detected",
                    )
        current = next_path

    return target


def validate_no_symlink(requested: str, workspace: Path) -> Path:
    """Stricter validation: reject if ANY component is a symlink."""
    rel = requested.lstrip("/")
    if not rel:
        return workspace.resolve()

    target = (workspace / rel).resolve()
    workspace_resolved = workspace.resolve()

    if not target.is_relative_to(workspace_resolved):
        raise HTTPException(status_code=403, detail="Path outside workspace")

    # Walk from workspace to target, reject any symlink
    parts = target.relative_to(workspace_resolved).parts
    current = workspace_resolved
    for part in parts:
        next_path = current / part
        if next_path.is_symlink():
            raise HTTPException(
                status_code=403,
                detail=f"Symlink not allowed: {'/'.join(parts[:len(current.relative_to(workspace_resolved).parts) + 1])}",
            )
        current = next_path

    return target


async def write_file(workspace: Path, path: str, content: str) -> dict:
    target = validate_no_symlink(path, workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "size": len(content)}


async def read_file(workspace: Path, path: str) -> dict:
    target = validate_path(path, workspace)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    content = target.read_text(encoding="utf-8")
    return {"path": path, "content": content, "size": len(content)}


async def list_tree(workspace: Path, path: str = "/", max_depth: int = 8) -> dict:
    if path == "/":
        target = workspace
    else:
        target = validate_path(path, workspace)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path}")

    def _build(p: Path, depth: int = 0) -> dict:
        name = p.name if p != workspace else "/"
        entry: dict = {"name": name, "type": "directory" if p.is_dir() else "file"}
        if p.is_dir() and depth < max_depth:
            children = []
            try:
                for child in sorted(p.iterdir()):
                    # Skip hidden files (except .gitignore)
                    if child.name.startswith(".") and child.name != ".gitignore":
                        continue
                    # Skip symlinks in listing (security)
                    if child.is_symlink():
                        continue
                    children.append(_build(child, depth + 1))
            except PermissionError:
                pass
            entry["children"] = children
        elif p.is_file():
            try:
                entry["size"] = p.stat().st_size
            except OSError:
                entry["size"] = 0
        return entry

    return _build(target)


async def delete_file(workspace: Path, path: str) -> dict:
    target = validate_no_symlink(path, workspace)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path}")
    if target.resolve() == workspace.resolve():
        raise HTTPException(status_code=403, detail="Cannot delete workspace root")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"path": path, "deleted": True}


async def glob_files(workspace: Path, pattern: str) -> dict:
    matches = set()
    for p in workspace.glob(f"**/{pattern}"):
        if p.is_file() and not p.is_symlink():
            matches.add(str(p.relative_to(workspace)))
    for p in workspace.glob(pattern):
        if p.is_file() and not p.is_symlink():
            matches.add(str(p.relative_to(workspace)))
    return {"pattern": pattern, "matches": sorted(matches)}
