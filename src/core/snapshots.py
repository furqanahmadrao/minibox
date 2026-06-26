"""Snapshot management — tar-based checkpoint/restore/fork."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tarfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def create_snapshot(
    sandbox_id: str,
    workspace: Path,
    snapshot_path: Path,
    label: str = "",
) -> dict:
    """Create a tar snapshot of sandbox workspace."""
    snapshot_id = f"sn_{int(time.time() * 1000)}"
    snapshot_dir = snapshot_path / sandbox_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    tar_path = snapshot_dir / f"{snapshot_id}.tar.gz"

    # Create tar archive
    def _create_tar():
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(str(workspace), arcname="workspace")

    await asyncio.get_event_loop().run_in_executor(None, _create_tar)

    # Save metadata sidecar with label
    meta_path = snapshot_dir / f"{snapshot_id}.json"
    meta_path.write_text(json.dumps({"label": label, "created_at": time.time()}))

    size = tar_path.stat().st_size if tar_path.exists() else 0
    logger.info("Snapshot %s created for sandbox %s (%d bytes)", snapshot_id, sandbox_id, size)

    return {
        "snapshot_id": snapshot_id,
        "sandbox_id": sandbox_id,
        "label": label,
        "size": size,
        "created_at": time.time(),
    }


async def restore_snapshot(
    sandbox_id: str,
    workspace: Path,
    snapshot_path: Path,
    snapshot_id: str,
) -> dict:
    """Restore a snapshot into sandbox workspace."""
    tar_path = snapshot_path / sandbox_id / f"{snapshot_id}.tar.gz"
    if not tar_path.exists():
        raise FileNotFoundError(f"Snapshot {snapshot_id} not found")

    # Clear workspace
    for item in workspace.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    # Extract tar — archive has arcname="workspace", so extract to parent to
    # recreate workspace/ inside the sandbox directory.  However, to avoid
    # confusion with similarly-named siblings, we extract directly into the
    # workspace (which was already cleared above) and rename during extraction.
    def _extract_tar():
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.name.startswith("workspace/"):
                    continue
                # Strip "workspace/" prefix
                member.name = member.name[len("workspace/") :]
                # Security: reject paths that escape workspace
                resolved = (workspace / member.name).resolve()
                if not resolved.is_relative_to(workspace.resolve()):
                    logger.warning("Skipping malicious tar member: %s", member.name)
                    continue
                # Reject absolute paths and symlinks pointing outside
                if member.name.startswith(("/", "..")):
                    logger.warning("Skipping malicious tar member: %s", member.name)
                    continue
                try:
                    tar.extract(member, path=str(workspace), filter="data")
                except TypeError:
                    tar.extract(member, path=str(workspace))

    await asyncio.get_event_loop().run_in_executor(None, _extract_tar)

    logger.info("Snapshot %s restored to sandbox %s", snapshot_id, sandbox_id)
    return {"snapshot_id": snapshot_id, "sandbox_id": sandbox_id, "restored": True}


async def fork_sandbox(
    source_id: str,
    target_id: str,
    workspace_root: Path,
    snapshot_path: Path,
) -> dict:
    """Fork a sandbox by creating a new workspace from source."""
    source_workspace = workspace_root / source_id
    target_workspace = workspace_root / target_id

    if not source_workspace.exists():
        raise FileNotFoundError(f"Source sandbox {source_id} not found")

    target_workspace.mkdir(parents=True, exist_ok=True)

    # Copy workspace
    def _copy():
        shutil.copytree(str(source_workspace), str(target_workspace), dirs_exist_ok=True)

    await asyncio.get_event_loop().run_in_executor(None, _copy)

    logger.info("Forked sandbox %s -> %s", source_id, target_id)
    return {"source": source_id, "target": target_id}


async def list_snapshots(sandbox_id: str, snapshot_path: Path) -> list[dict]:
    """List all snapshots for a sandbox."""
    snapshot_dir = snapshot_path / sandbox_id
    if not snapshot_dir.exists():
        return []

    snapshots = []
    for tar_file in sorted(snapshot_dir.glob("*.tar.gz")):
        snapshot_id = tar_file.name[:-7]  # strip ".tar.gz"
        # Read label from metadata sidecar if it exists
        label = ""
        meta_path = snapshot_dir / f"{snapshot_id}.json"
        if meta_path.exists():
            try:
                label = json.loads(meta_path.read_text()).get("label", "")
            except Exception:
                pass
        snapshots.append(
            {
                "snapshot_id": snapshot_id,
                "sandbox_id": sandbox_id,
                "label": label,
                "size": tar_file.stat().st_size,
                "created_at": tar_file.stat().st_mtime,
            }
        )

    return snapshots


async def delete_snapshot(sandbox_id: str, snapshot_path: Path, snapshot_id: str) -> bool:
    """Delete a specific snapshot."""
    tar_path = snapshot_path / sandbox_id / f"{snapshot_id}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
        return True
    return False
