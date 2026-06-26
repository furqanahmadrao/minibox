"""Execution API endpoints — REST exec + WebSocket terminal."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import struct

try:
    import fcntl
    import pty
    import termios
except ImportError:
    fcntl = None
    pty = None
    termios = None

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from src.api.deps import get_breakpoint_manager, get_event_bus, get_registry
from src.config import get_config
from src.core.executor import exec_batch, exec_command, exec_command_stream
from src.core.sandbox import SandboxHandle
from src.models.sandbox import ExecBatchRequest, ExecRequest, ExecResponse
from src.orchestration.events import Event

router = APIRouter(prefix="/api/sandbox", tags=["exec"])
logger = logging.getLogger(__name__)

# Track active terminal sessions for cleanup
_active_terminals: dict[str, int] = {}  # sandbox_id -> child pid


def _get_handle(sandbox_id: str, state) -> SandboxHandle:
    config = get_config()
    return SandboxHandle(
        sandbox_id=sandbox_id,
        pid=state.pid or 0,
        workspace=config.sandbox.sandbox_dir(sandbox_id),
    )


def _build_terminal_bwrap_args(state, workspace) -> list[str]:
    """Build bwrap args for interactive terminal using per-sandbox security config."""
    sec = state.security or {}
    net = state.network_config or {}

    args = ["bwrap"]
    args.extend(["--ro-bind", "/", "/"])
    args.extend(["--bind", str(workspace), "/workspace"])
    args.extend(["--tmpfs", "/tmp"])
    args.extend(["--tmpfs", "/root"])
    args.extend(["--dev", "/dev"])
    args.extend(["--proc", "/proc"])

    # Namespace isolation
    network_mode = net.get("mode", state.network_mode or "egress-only")
    if network_mode != "full":
        args.append("--unshare-net")
    args.append("--unshare-pid")
    args.append("--unshare-user")
    args.append("--unshare-uts")

    args.extend(["--hostname", f"sandbox-{state.sandbox_id}"])
    args.append("--die-with-parent")
    args.extend(["--cap-drop", "ALL"])
    args.extend(["--new-session"])
    args.extend(["--chdir", "/workspace"])
    args.extend(["--setenv", "HOME", "/root"])
    args.extend(["--setenv", "TERM", "xterm-256color"])

    # Inject sandbox environment variables
    if state.env:
        import re
        for k, v in state.env.items():
            if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k):
                args.extend(["--setenv", k, v])

    # Mask paths
    mask_paths = sec.get("mask_paths", [])
    for path in mask_paths:
        args.extend(["--bind", "/dev/null", path])

    # Read-only paths
    readonly_paths = sec.get("readonly_paths", [])
    for path in readonly_paths:
        args.extend(["--ro-bind", path, path])

    # Seccomp
    seccomp_profile_name = sec.get("seccomp_profile", "default")
    if seccomp_profile_name == "disabled":
        pass  # No seccomp
    elif seccomp_profile_name == "custom":
        from src.core.seccomp import compile_custom_profile

        blocked = sec.get("blocked_syscalls", [])
        profile = compile_custom_profile(blocked_syscalls=blocked)
        seccomp_fd = _write_seccomp(profile)
        if seccomp_fd is not None:
            args.extend(["--seccomp", str(seccomp_fd)])
    else:
        # Default profile
        from src.core.sandbox import _load_default_seccomp_profile, _write_seccomp_bpf

        profile = _load_default_seccomp_profile()
        if profile:
            fd = _write_seccomp_bpf(profile)
            if fd is not None:
                args.extend(["--seccomp", str(fd)])

    args.append("--")
    args.extend(["/bin/bash", "--login"])
    return args


def _write_seccomp(profile: dict) -> int | None:
    """Compile and write seccomp profile, return fd."""
    from src.core.seccomp import compile_profile_to_bpf

    try:
        bpf_bytes = compile_profile_to_bpf(profile)
        tmp = __import__("tempfile").NamedTemporaryFile(
            mode="wb", suffix=".seccomp", prefix="minibox-term-", delete=False
        )
        tmp.write(bpf_bytes)
        tmp.flush()
        fd = os.dup(tmp.fileno())
        path = tmp.name
        tmp.close()
        os.register_at_fork(
            after_in_child=lambda p=path: os.unlink(p) if os.path.exists(p) else None
        )
        return fd
    except Exception as e:
        logger.warning("Failed to compile seccomp for terminal: %s", e)
        return None


@router.post("/{sandbox_id}/exec", response_model=ExecResponse)
async def exec_endpoint(sandbox_id: str, req: ExecRequest) -> ExecResponse:
    registry = get_registry()
    breakpoint_mgr = get_breakpoint_manager()

    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if state.status != "running":
        raise HTTPException(status_code=400, detail=f"Sandbox is {state.status}")

    bp = breakpoint_mgr.check_exec(sandbox_id, req.cmd)
    if bp:
        event_bus = get_event_bus()
        await event_bus.publish(
            Event(
                sandbox_id=sandbox_id,
                event_type="breakpoint",
                data={
                    "breakpoint_id": bp.id,
                    "pattern": bp.pattern,
                    "cmd": req.cmd,
                    "action": bp.action,
                },
            )
        )

        if bp.action == "pause":
            from src.core.cgroups import CGROUP_BASE, freeze_cgroup

            cgroup_path = CGROUP_BASE / sandbox_id
            if cgroup_path.exists():
                freeze_cgroup(cgroup_path)
            await registry.update(sandbox_id, status="paused")
            raise HTTPException(status_code=409, detail=f"Breakpoint {bp.id} triggered (paused)")
        elif bp.action == "block":
            raise HTTPException(status_code=409, detail=f"Breakpoint {bp.id} blocked command")
        # action == "notify": emit event but continue execution

    handle = _get_handle(sandbox_id, state)
    env = {}
    if state.env:
        env.update(state.env)
    if req.env:
        env.update(req.env)
    result = await exec_command(handle, req.cmd, req.workdir, req.timeout, env)
    await registry.update(sandbox_id, exec_count=state.exec_count + 1)

    event_bus = get_event_bus()
    await event_bus.publish(
        Event(
            sandbox_id=sandbox_id,
            event_type="exec",
            data={
                "cmd": req.cmd,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            },
        )
    )

    return ExecResponse(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        sandbox_id=sandbox_id,
    )


@router.post("/{sandbox_id}/exec/batch")
async def exec_batch_endpoint(sandbox_id: str, req: ExecBatchRequest) -> list[ExecResponse]:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if state.status != "running":
        raise HTTPException(status_code=400, detail=f"Sandbox is {state.status}")

    handle = _get_handle(sandbox_id, state)
    results = await exec_batch(handle, req.commands, req.workdir, req.timeout)

    event_bus = get_event_bus()
    for cmd, r in zip(req.commands, results):
        await event_bus.publish(
            Event(
                sandbox_id=sandbox_id,
                event_type="exec",
                data={
                    "cmd": cmd,
                    "exit_code": r.exit_code,
                    "duration_ms": r.duration_ms,
                    "batch": True,
                },
            )
        )

    return [
        ExecResponse(
            stdout=r.stdout,
            stderr=r.stderr,
            exit_code=r.exit_code,
            duration_ms=r.duration_ms,
            sandbox_id=sandbox_id,
        )
        for r in results
    ]


@router.post("/{sandbox_id}/exec/stream")
async def exec_stream_endpoint(sandbox_id: str, req: ExecRequest):
    """Stream command output via Server-Sent Events.

    Returns a text/event-stream response with events:
      - type: "stdout", data: "..."
      - type: "stderr", data: "..."
      - type: "exit", exit_code: 0
    """
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if state.status != "running":
        raise HTTPException(status_code=400, detail=f"Sandbox is {state.status}")

    handle = _get_handle(sandbox_id, state)
    env = {}
    if state.env:
        env.update(state.env)
    if req.env:
        env.update(req.env)

    async def event_generator():
        async for event in exec_command_stream(handle, req.cmd, req.workdir, req.timeout, env):
            payload = {"type": event.type, "data": event.data}
            if event.exit_code is not None:
                payload["exit_code"] = event.exit_code
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/{sandbox_id}/terminal")
async def terminal_websocket(websocket: WebSocket, sandbox_id: str):
    """WebSocket terminal — real bidirectional PTY relay.

    Client sends:
      - text: keyboard input (UTF-8)
      - text JSON {"type":"resize","cols":80,"rows":24}: terminal resize

    Server sends:
      - bytes: PTY output data
    """
    await websocket.accept()
    if fcntl is None or pty is None or termios is None:
        await websocket.send_json({"type": "error", "data": "Interactive terminal is not supported on Windows"})
        await websocket.close()
        return

    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        await websocket.send_json({"type": "error", "data": "Sandbox not found"})
        await websocket.close()
        return

    if state.status != "running":
        await websocket.send_json({"type": "error", "data": f"Sandbox is {state.status}"})
        await websocket.close()
        return

    config = get_config()
    workspace = config.sandbox.sandbox_dir(sandbox_id)

    # Create PTY pair
    master_fd, slave_fd = pty.openpty()

    # Set slave to raw mode (no echo, no line buffering)
    attrs = termios.tcgetattr(slave_fd)
    attrs[3] &= ~termios.ECHO  # type: ignore[operator]
    attrs[6][termios.VMIN] = 1
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

    # Make master non-blocking for async reads
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Build bwrap args with per-sandbox security config
    bwrap_args = _build_terminal_bwrap_args(state, workspace)

    pid = None
    try:
        # Fork with PTY as stdio
        pid = os.fork()
        if pid == 0:
            # Child: redirect stdio to PTY slave, exec bwrap
            os.close(master_fd)
            os.dup2(slave_fd, 0)  # stdin
            os.dup2(slave_fd, 1)  # stdout
            os.dup2(slave_fd, 2)  # stderr
            if slave_fd > 2:
                os.close(slave_fd)
            os.execvp("bwrap", bwrap_args)
        else:
            # Parent: relay WebSocket ↔ PTY master
            os.close(slave_fd)
            _active_terminals[sandbox_id] = pid

            loop = asyncio.get_event_loop()

            async def read_pty():
                """Read PTY output → send to WebSocket as bytes."""
                while True:
                    try:
                        data = await loop.run_in_executor(None, lambda: os.read(master_fd, 4096))
                        if not data:
                            break
                        await websocket.send_bytes(data)
                    except (OSError, BlockingIOError):
                        await asyncio.sleep(0.005)
                    except Exception:
                        break

            async def read_ws():
                """Read WebSocket input → write to PTY."""
                while True:
                    try:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.receive":
                            if "bytes" in msg and msg["bytes"]:
                                os.write(master_fd, msg["bytes"])
                            elif "text" in msg:
                                # Check for control messages (resize)
                                text = msg["text"]
                                try:
                                    data = json.loads(text)
                                    if data.get("type") == "resize":
                                        rows = data.get("rows", 24)
                                        cols = data.get("cols", 80)
                                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                                        continue
                                except (json.JSONDecodeError, KeyError, TypeError):
                                    pass
                                # Regular keyboard input
                                os.write(master_fd, text.encode("utf-8"))
                        elif msg["type"] == "websocket.disconnect":
                            break
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        break

            # Run both relays concurrently
            t1 = asyncio.create_task(read_pty())
            t2 = asyncio.create_task(read_ws())

            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            # Cleanup
            os.close(master_fd)
            _active_terminals.pop(sandbox_id, None)
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, os.WNOHANG)
            except (ProcessLookupError, ChildProcessError, OSError):
                pass

    except WebSocketDisconnect:
        os.close(master_fd)
        _active_terminals.pop(sandbox_id, None)
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError, OSError):
                pass
    except Exception as e:
        logger.warning("Terminal WebSocket error: %s", e)
        try:
            os.close(master_fd)
        except OSError:
            pass
        _active_terminals.pop(sandbox_id, None)
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, os.WNOHANG)
            except (ProcessLookupError, ChildProcessError, OSError):
                pass


@router.get("/{sandbox_id}/events")
async def events_sse(sandbox_id: str):
    event_bus = get_event_bus()

    async def generate():
        async for event in event_bus.subscribe(sandbox_id):
            yield f"data: {event.to_json()}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Breakpoint management ────────────────────────────────────────────────


class BreakpointCreateRequest(BaseModel):
    pattern: str
    action: str = "pause"  # pause, notify, block


class BreakpointResponse(BaseModel):
    id: str
    sandbox_id: str
    pattern: str
    action: str
    created_at: float
    hit_count: int


@router.post("/{sandbox_id}/breakpoints", response_model=BreakpointResponse)
async def add_breakpoint_endpoint(
    sandbox_id: str, req: BreakpointCreateRequest
) -> BreakpointResponse:
    """Add a HITL breakpoint to a sandbox."""
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    breakpoint_mgr = get_breakpoint_manager()
    bp = breakpoint_mgr.add_breakpoint(sandbox_id, req.pattern, req.action)
    return BreakpointResponse(
        id=bp.id,
        sandbox_id=bp.sandbox_id,
        pattern=bp.pattern,
        action=bp.action,
        created_at=bp.created_at,
        hit_count=bp.hit_count,
    )


@router.get("/{sandbox_id}/breakpoints", response_model=list[BreakpointResponse])
async def list_breakpoints_endpoint(sandbox_id: str) -> list[BreakpointResponse]:
    """List breakpoints for a sandbox."""
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    breakpoint_mgr = get_breakpoint_manager()
    bps = breakpoint_mgr.list_breakpoints(sandbox_id)
    return [
        BreakpointResponse(
            id=bp.id,
            sandbox_id=bp.sandbox_id,
            pattern=bp.pattern,
            action=bp.action,
            created_at=bp.created_at,
            hit_count=bp.hit_count,
        )
        for bp in bps
    ]


@router.delete("/{sandbox_id}/breakpoints/{bp_id}")
async def remove_breakpoint_endpoint(sandbox_id: str, bp_id: str) -> dict:
    """Remove a breakpoint from a sandbox."""
    breakpoint_mgr = get_breakpoint_manager()
    removed = breakpoint_mgr.remove_breakpoint(bp_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Breakpoint not found")
    return {"ok": True, "removed": bp_id}
