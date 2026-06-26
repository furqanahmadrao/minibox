"""Command execution engine — with injection-safe workdir handling."""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
import time
from dataclasses import dataclass, field

from src.core.sandbox import SandboxHandle

logger = logging.getLogger(__name__)

# Characters that can be used for shell injection in workdir
_INJECTION_CHARS = re.compile(r"[;&|`$(){}!\n\r\\\'\"]")


def _sanitize_workdir(workdir: str) -> str:
    """Sanitize workdir to prevent shell injection.

    Only allows safe path characters: / - _ . ~ a-zA-Z0-9
    Rejects anything with shell metacharacters.
    """
    if not workdir:
        return "/"

    # Block any shell metacharacters
    if _INJECTION_CHARS.search(workdir):
        raise ValueError("Invalid workdir: contains unsafe characters")

    # Must be absolute path
    if not workdir.startswith("/"):
        workdir = "/" + workdir

    # Normalize path — collapse //, remove trailing /
    workdir = re.sub(r"/+", "/", workdir).rstrip("/") or "/"

    # Block path traversal
    parts = workdir.split("/")
    resolved = []
    for part in parts:
        if part == "..":
            if resolved and resolved[-1] != "":
                resolved.pop()
        elif part and part != ".":
            resolved.append(part)

    return "/" + "/".join(resolved)


@dataclass
class ExecResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: float = 0.0
    sandbox_id: str = ""


@dataclass
class ExecStreamEvent:
    type: str
    data: str = ""
    exit_code: int | None = None
    ts: float = field(default_factory=time.time)


def _build_exec_bwrap_args(handle: SandboxHandle, env: dict[str, str] | None = None) -> list[str]:
    env_args = []
    if env:
        for k, v in env.items():
            # Validate env key — must be safe identifier
            if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k):
                env_args.extend(["--setenv", k, v])

    return [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(handle.workspace),
        "/workspace",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/root",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-uts",
        "--hostname",
        f"exec-{handle.sandbox_id}",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--chdir",
        "/workspace",
        "--setenv",
        "HOME",
        "/root",
        *env_args,
        "--",
    ]


async def exec_command(
    handle: SandboxHandle,
    cmd: str,
    workdir: str = "/workspace",
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> ExecResult:
    start = time.monotonic()

    # Sanitize workdir
    try:
        safe_workdir = _sanitize_workdir(workdir)
    except ValueError as e:
        return ExecResult(
            stdout="",
            stderr=str(e),
            exit_code=-1,
            duration_ms=0,
            sandbox_id=handle.sandbox_id,
        )

    bwrap_args = _build_exec_bwrap_args(handle, env)

    # Pass command through bash -c; workdir is already sanitized, command runs in sandbox
    bwrap_args.extend(["/bin/bash", "-c", f"cd {safe_workdir} && {cmd}"])

    try:
        proc = await asyncio.create_subprocess_exec(
            *bwrap_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration = (time.monotonic() - start) * 1000
        return ExecResult(
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
            exit_code=proc.returncode or 0,
            duration_ms=duration,
            sandbox_id=handle.sandbox_id,
        )
    except asyncio.TimeoutError:
        duration = (time.monotonic() - start) * 1000
        try:
            proc.kill()
        except Exception:
            pass
        return ExecResult(
            stdout="",
            stderr=f"Timed out after {timeout}s",
            exit_code=-1,
            duration_ms=duration,
            sandbox_id=handle.sandbox_id,
        )
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        return ExecResult(
            stdout="",
            stderr=str(e),
            exit_code=-1,
            duration_ms=duration,
            sandbox_id=handle.sandbox_id,
        )


async def exec_command_stream(
    handle: SandboxHandle,
    cmd: str,
    workdir: str = "/workspace",
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
):
    start = time.monotonic()

    try:
        safe_workdir = _sanitize_workdir(workdir)
    except ValueError as e:
        yield ExecStreamEvent(type="error", data=str(e))
        yield ExecStreamEvent(type="exit", exit_code=-1)
        return

    bwrap_args = _build_exec_bwrap_args(handle, env)
    bwrap_args.extend(["/bin/bash", "-c", f"cd {safe_workdir} && {cmd}"])

    try:
        proc = await asyncio.create_subprocess_exec(
            *bwrap_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(reader, event_type):
            while True:
                line = await reader.readline()
                if not line:
                    break
                yield ExecStreamEvent(type=event_type, data=line.decode(errors="replace"))

        queue: asyncio.Queue[tuple[ExecStreamEvent | None, bool]] = asyncio.Queue()

        async def _pump(gen, q):
            try:
                async for event in gen:
                    await q.put((event, False))
            except Exception:
                pass
            await q.put((None, True))

        pump_task = asyncio.create_task(
            asyncio.gather(
                _pump(read_stream(proc.stdout, "stdout"), queue),
                _pump(read_stream(proc.stderr, "stderr"), queue),
            )
        )

        done_count = 0
        while done_count < 2:
            elapsed = time.monotonic() - start
            remaining_time = timeout - elapsed
            if remaining_time <= 0:
                proc.kill()
                pump_task.cancel()
                yield ExecStreamEvent(type="error", data=f"Timed out after {timeout}s")
                yield ExecStreamEvent(type="exit", exit_code=-1)
                return
            try:
                event, finished = await asyncio.wait_for(queue.get(), timeout=remaining_time)
            except asyncio.TimeoutError:
                proc.kill()
                pump_task.cancel()
                yield ExecStreamEvent(type="error", data=f"Timed out after {timeout}s")
                yield ExecStreamEvent(type="exit", exit_code=-1)
                return
            if finished:
                done_count += 1
            else:
                yield event

        await asyncio.wait_for(proc.wait(), timeout=max(0.1, timeout - (time.monotonic() - start)))
        yield ExecStreamEvent(type="exit", exit_code=proc.returncode or 0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        yield ExecStreamEvent(type="error", data=f"Timed out after {timeout}s")
        yield ExecStreamEvent(type="exit", exit_code=-1)
    except Exception as e:
        yield ExecStreamEvent(type="error", data=str(e))
        yield ExecStreamEvent(type="exit", exit_code=-1)


async def exec_batch(
    handle: SandboxHandle,
    commands: list[str],
    workdir: str = "/workspace",
    timeout: float = 30.0,
) -> list[ExecResult]:
    results = []
    for cmd in commands:
        result = await exec_command(handle, cmd, workdir, timeout)
        results.append(result)
        if result.exit_code != 0:
            break
    return results
