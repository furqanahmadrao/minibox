"""MCP Server — tool registration and dispatch using FastMCP."""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)

_mcp_instance = None
_mcp_http_app = None


def get_mcp():
    global _mcp_instance
    if _mcp_instance is None:
        from fastmcp import FastMCP

        _mcp_instance = FastMCP(
            "minibox",
            version="0.1.0",
            instructions="Minibox sandbox management for AI coding agents. Create, run, and manage isolated sandboxes.",
        )
    return _mcp_instance


def get_mcp_http_app():
    global _mcp_http_app
    if _mcp_http_app is None:
        mcp = get_mcp()
        _mcp_http_app = mcp.http_app(path="/")
    return _mcp_http_app


mcp = get_mcp()


@mcp.tool()
async def create_sandbox(
    template: str = "minimal",
    label: str = "",
    ttl: int = 1800,
    network: str = "egress-only",
    memory_mb: int = 512,
    cpu_cores: float = 2.0,
) -> str:
    """Create an isolated sandbox environment for running code.

    Args:
        template: Sandbox template (python-dev, node-dev, rust-dev, research, minimal)
        label: Human-readable label for the sandbox
        ttl: Time-to-live in seconds (default 30min)
        network: Network mode (isolated, egress-only, full)
        memory_mb: Memory limit in MB
        cpu_cores: CPU cores limit

    Returns:
        JSON with sandbox_id and status
    """
    from src.api.deps import get_registry
    from src.config import get_config
    from src.core.sandbox import SandboxConfig
    from src.core.sandbox import create_sandbox as create_sb
    from src.orchestration.registry import SandboxState

    config = get_config()
    registry = get_registry()

    running = await registry.count_running()
    if running >= config.sandbox.max_concurrent:
        return json.dumps(
            {"error": f"Max concurrent sandboxes ({config.sandbox.max_concurrent}) reached"}
        )

    sandbox_id = str(uuid.uuid4())
    sb_config = SandboxConfig(
        sandbox_id=sandbox_id,
        cpu_cores=cpu_cores,
        memory_mb=memory_mb,
        env={"MINIBOX_TEMPLATE": template},
    )
    handle = await create_sb(sb_config, config.sandbox.workspace_root)

    state = SandboxState(
        sandbox_id=handle.sandbox_id,
        template=template,
        status="running",
        label=label,
        ttl=ttl,
        cpu_cores=cpu_cores,
        memory_mb=memory_mb,
        network_mode=network,
        pid=handle.pid,
    )
    state.touch()
    await registry.register(state)

    return json.dumps({"sandbox_id": handle.sandbox_id, "status": "running"})


@mcp.tool()
async def exec(
    sandbox_id: str,
    cmd: str,
    workdir: str = "/",
    timeout: float = 30.0,
) -> str:
    """Run a shell command inside a sandbox.

    Args:
        sandbox_id: The sandbox ID to run in
        cmd: Shell command to execute
        workdir: Working directory (default: /)
        timeout: Timeout in seconds

    Returns:
        JSON with stdout, stderr, and exit_code
    """
    from src.api.deps import get_registry
    from src.config import get_config
    from src.core.executor import exec_command
    from src.core.sandbox import SandboxHandle

    config = get_config()
    registry = get_registry()

    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    handle = SandboxHandle(
        sandbox_id=state.sandbox_id,
        pid=state.pid or 0,
        workspace=config.sandbox.sandbox_dir(state.sandbox_id),
    )
    result = await exec_command(handle, cmd, workdir, timeout)

    return json.dumps(
        {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
        }
    )


@mcp.tool()
async def exec_batch(
    sandbox_id: str,
    commands: list[str],
    workdir: str = "/",
    timeout: float = 30.0,
) -> str:
    """Run multiple commands sequentially in a sandbox.

    Args:
        sandbox_id: The sandbox ID
        commands: List of commands to run
        workdir: Working directory
        timeout: Timeout per command in seconds

    Returns:
        JSON array of results
    """
    from src.api.deps import get_registry
    from src.config import get_config
    from src.core.executor import exec_batch as exec_b
    from src.core.sandbox import SandboxHandle

    config = get_config()
    registry = get_registry()

    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    handle = SandboxHandle(
        sandbox_id=state.sandbox_id,
        pid=state.pid or 0,
        workspace=config.sandbox.sandbox_dir(state.sandbox_id),
    )
    results = await exec_b(handle, commands, workdir, timeout)

    return json.dumps(
        [{"stdout": r.stdout, "stderr": r.stderr, "exit_code": r.exit_code} for r in results]
    )


@mcp.tool()
async def write_file(
    sandbox_id: str,
    path: str,
    content: str,
) -> str:
    """Write content to a file inside the sandbox.

    Args:
        sandbox_id: The sandbox ID
        path: File path (absolute, relative to /)
        content: File content to write

    Returns:
        JSON with path and size
    """
    from src.config import get_config
    from src.core.filesystem import write_file as wf

    config = get_config()
    result = await wf(config.sandbox.sandbox_dir(sandbox_id), path, content)
    return json.dumps(result)


@mcp.tool()
async def read_file(
    sandbox_id: str,
    path: str,
) -> str:
    """Read a file from the sandbox.

    Args:
        sandbox_id: The sandbox ID
        path: File path to read

    Returns:
        JSON with path, content, and size
    """
    from src.config import get_config
    from src.core.filesystem import read_file as rf

    config = get_config()
    result = await rf(config.sandbox.sandbox_dir(sandbox_id), path)
    return json.dumps(result)


@mcp.tool()
async def list_files(
    sandbox_id: str,
    path: str = "/",
) -> str:
    """List directory tree in the sandbox.

    Args:
        sandbox_id: The sandbox ID
        path: Directory path to list

    Returns:
        JSON with directory tree
    """
    from src.config import get_config
    from src.core.filesystem import list_tree

    config = get_config()
    result = await list_tree(config.sandbox.sandbox_dir(sandbox_id), path)
    return json.dumps(result)


@mcp.tool()
async def delete_file(
    sandbox_id: str,
    path: str,
) -> str:
    """Delete a file or directory from the sandbox.

    Args:
        sandbox_id: The sandbox ID
        path: File or directory path to delete

    Returns:
        JSON with deletion status
    """
    from src.config import get_config
    from src.core.filesystem import delete_file as df

    config = get_config()
    result = await df(config.sandbox.sandbox_dir(sandbox_id), path)
    return json.dumps(result)


@mcp.tool()
async def expose_port(
    sandbox_id: str,
    port: int,
) -> str:
    """Forward a port from sandbox to host.

    Args:
        sandbox_id: The sandbox ID
        port: Port number to expose

    Returns:
        JSON with port mapping and URL
    """
    from src.api.deps import get_registry
    from src.config import get_config
    from src.core.network import expose_port as ep

    config = get_config()
    registry = get_registry()

    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    forward = await ep(sandbox_id, str(config.sandbox.sandbox_dir(sandbox_id)), port)
    return json.dumps(
        {
            "port": forward.port,
            "host_port": forward.host_port,
            "url": f"http://localhost:{forward.host_port}",
        }
    )


@mcp.tool()
async def snapshot(
    sandbox_id: str,
    label: str = "",
) -> str:
    """Checkpoint sandbox state for later restore or fork.

    Args:
        sandbox_id: The sandbox ID
        label: Optional label for the snapshot

    Returns:
        JSON with snapshot_id and metadata
    """
    from src.config import get_config
    from src.core.snapshots import create_snapshot as cs

    config = get_config()
    result = await cs(
        sandbox_id,
        config.sandbox.sandbox_dir(sandbox_id),
        config.storage.snapshot_path,
        label,
    )
    return json.dumps(result)


@mcp.tool()
async def fork(
    sandbox_id: str,
    snapshot_id: str,
    label: str = "",
) -> str:
    """Create a new sandbox from a snapshot.

    Args:
        sandbox_id: Source sandbox ID
        snapshot_id: Snapshot to fork from
        label: Label for the new sandbox

    Returns:
        JSON with new sandbox_id
    """
    from src.api.deps import get_registry
    from src.config import get_config
    from src.core.sandbox import SandboxConfig
    from src.core.sandbox import create_sandbox as create_sb
    from src.core.snapshots import fork_sandbox as fork_sb
    from src.orchestration.registry import SandboxState

    config = get_config()
    registry = get_registry()

    source_state = await registry.get(sandbox_id)
    if source_state is None:
        return json.dumps({"error": "Source sandbox not found"})

    new_id = str(uuid.uuid4())
    sb_config = SandboxConfig(sandbox_id=new_id)
    handle = await create_sb(sb_config, config.sandbox.workspace_root)
    await fork_sb(
        sandbox_id, handle.sandbox_id, config.sandbox.workspace_root, config.storage.snapshot_path
    )

    state = SandboxState(
        sandbox_id=handle.sandbox_id,
        template=source_state.template,
        status="running",
        label=label or f"fork of {sandbox_id}",
        ttl=source_state.ttl,
        memory_mb=source_state.memory_mb,
        network_mode=source_state.network_mode,
        pid=handle.pid,
    )
    state.touch()
    await registry.register(state)

    return json.dumps({"sandbox_id": handle.sandbox_id, "status": "running"})


@mcp.tool()
async def destroy_sandbox(sandbox_id: str) -> str:
    """Destroy sandbox and wipe filesystem.

    Args:
        sandbox_id: The sandbox ID to destroy

    Returns:
        JSON with destruction status
    """
    from src.api.deps import get_registry
    from src.config import get_config
    from src.core.sandbox import SandboxHandle
    from src.core.sandbox import destroy_sandbox as destroy_sb

    config = get_config()
    registry = get_registry()

    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    if state.pid:
        handle = SandboxHandle(
            sandbox_id=state.sandbox_id,
            pid=state.pid,
            workspace=config.sandbox.sandbox_dir(state.sandbox_id),
        )
        await destroy_sb(handle)

    await registry.update(sandbox_id, status="destroyed")
    return json.dumps({"sandbox_id": sandbox_id, "status": "destroyed"})


@mcp.tool()
async def list_sandboxes() -> str:
    """List all running sandboxes.

    Returns:
        JSON array of sandbox summaries
    """
    from src.api.deps import get_registry

    registry = get_registry()
    states = await registry.list_all()

    return json.dumps(
        [
            {
                "sandbox_id": s.sandbox_id,
                "status": s.status,
                "template": s.template,
                "label": s.label,
                "agent": s.agent_config.get("provider", "") if s.agent_config else "",
            }
            for s in states
        ]
    )


@mcp.tool()
async def get_sandbox_status(sandbox_id: str) -> str:
    """Get sandbox status and metadata.

    Args:
        sandbox_id: The sandbox ID

    Returns:
        JSON with full sandbox state
    """
    from src.api.deps import get_registry

    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    return json.dumps(state.to_dict())


@mcp.tool()
async def pause_sandbox(sandbox_id: str) -> str:
    """Pause sandbox execution.

    Args:
        sandbox_id: The sandbox ID

    Returns:
        JSON with pause status
    """
    from src.api.deps import get_registry

    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    if state.pid:
        try:
            from src.core.cgroups import CGROUP_BASE, freeze_cgroup

            cg = CGROUP_BASE / sandbox_id
            if cg.exists():
                freeze_cgroup(cg)
        except Exception as e:
            logger.warning("Failed to freeze cgroup: %s", e)

    await registry.update(sandbox_id, status="paused")
    return json.dumps({"sandbox_id": sandbox_id, "status": "paused"})


@mcp.tool()
async def resume_sandbox(sandbox_id: str) -> str:
    """Resume sandbox after pause.

    Args:
        sandbox_id: The sandbox ID

    Returns:
        JSON with resume status
    """
    from src.api.deps import get_registry

    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        return json.dumps({"error": "Sandbox not found"})

    if state.pid:
        try:
            from src.core.cgroups import CGROUP_BASE, unfreeze_cgroup

            cg = CGROUP_BASE / sandbox_id
            if cg.exists():
                unfreeze_cgroup(cg)
        except Exception as e:
            logger.warning("Failed to unfreeze cgroup: %s", e)

    await registry.update(sandbox_id, status="running")
    return json.dumps({"sandbox_id": sandbox_id, "status": "running"})
