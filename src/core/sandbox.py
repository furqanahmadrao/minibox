"""Bubblewrap sandbox wrapper — with configurable isolation and cgroups."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_SECCOMP_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "seccomp" / "default.json"


class IsolationLevel:
    """Isolation level presets for sandbox security."""
    MINIMAL = "minimal"     # Basic namespace isolation
    STANDARD = "standard"   # Standard isolation (default)
    STRICT = "strict"       # Maximum isolation

    PRESETS = {
        "minimal": {
            "unshare_net": True,
            "unshare_pid": True,
            "unshare_user": True,
            "read_only_rootfs": False,
            "no_new_privs": False,
            "mask_paths": [],
            "readonly_paths": [],
        },
        "standard": {
            "unshare_net": True,
            "unshare_pid": True,
            "unshare_user": True,
            "read_only_rootfs": True,
            "no_new_privs": True,
            "mask_paths": ["/proc/acpi", "/proc/kcore", "/proc/keys", "/proc/sched_debug"],
            "readonly_paths": [
                "/proc/asound", "/proc/bus", "/proc/fs",
                "/proc/irq", "/proc/sys", "/proc/sysrq-trigger",
            ],
        },
        "strict": {
            "unshare_net": True,
            "unshare_pid": True,
            "unshare_user": True,
            "read_only_rootfs": True,
            "no_new_privs": True,
            "mask_paths": [
                "/proc/acpi", "/proc/kcore", "/proc/keys", "/proc/sched_debug",
                "/proc/timer_list", "/proc/timer_stats", "/proc/wakelocks",
                "/dev/fd", "/dev/core", "/dev/mqueue", "/dev/shm",
            ],
            "readonly_paths": [
                "/proc", "/sys", "/dev",
            ],
        },
    }


@dataclass
class SandboxConfig:
    sandbox_id: str = ""
    workspace: Path | None = None
    hostname: str = ""
    isolation_level: str = "standard"
    unshare_net: bool = True
    unshare_pid: bool = True
    unshare_user: bool = True
    die_with_parent: bool = True
    needs_network_setup: bool = False
    read_only_rootfs: bool = True
    no_new_privs: bool = True
    mask_paths: list[str] = field(default_factory=list)
    readonly_paths: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    command: str = "/bin/bash"
    seccomp_profile: dict | None = None
    # Resource limits (0 = unlimited)
    cpu_cores: float = 0
    memory_mb: int = 0
    max_processes: int = 0
    max_open_files: int = 0

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = f"sandbox-{self.sandbox_id}"

        # Apply isolation level preset (explicit fields override)
        preset = IsolationLevel.PRESETS.get(self.isolation_level, {})
        if preset:
            # Only apply defaults — don't override explicit settings
            if not self.mask_paths:
                self.mask_paths = preset.get("mask_paths", [])
            if not self.readonly_paths:
                self.readonly_paths = preset.get("readonly_paths", [])


@dataclass
class SandboxHandle:
    sandbox_id: str
    pid: int
    workspace: Path
    created_at: float = field(default_factory=time.time)
    cgroup_path: Path | None = None


def _build_bwrap_args(config: SandboxConfig, workspace: Path) -> tuple[list[str], list[int]]:
    args: list[str] = []
    extra_fds: list[int] = []

    # Bind host root read-only, and workspace to /workspace
    args.extend(["--ro-bind", "/", "/"])
    args.extend(["--bind", str(workspace), "/workspace"])

    # Mask sensitive paths BEFORE mounting /dev, /proc, etc.
    # (bind /dev/null to paths before they become directories)
    for path in config.mask_paths:
        args.extend(["--bind", "/dev/null", path])

    # Mount tmpfs, dev, proc AFTER masks so masked paths stay as files
    args.extend(["--tmpfs", "/tmp"])
    args.extend(["--tmpfs", "/root"])
    args.extend(["--dev", "/dev"])
    args.extend(["--proc", "/proc"])

    # Read-only bind host paths that exist
    for path in config.readonly_paths:
        if Path(path).exists():
            args.extend(["--ro-bind", path, path])

    # Namespace isolation
    if config.unshare_net:
        args.append("--unshare-net")
    if config.unshare_pid:
        args.append("--unshare-pid")
    if config.unshare_user and not config.needs_network_setup:
        args.append("--unshare-user")
    # --hostname requires --unshare-uts
    args.append("--unshare-uts")
    args.extend(["--hostname", config.hostname])

    if config.die_with_parent:
        args.append("--die-with-parent")

    # Drop all capabilities
    args.extend(["--cap-drop", "ALL"])

    # Prevent privilege escalation
    if config.no_new_privs:
        args.append("--new-session")

    # Chdir to /workspace
    args.extend(["--chdir", "/workspace"])

    # Seccomp — fd must be kept open via pass_fds
    seccomp_profile = config.seccomp_profile
    if seccomp_profile is None:
        seccomp_profile = _load_default_seccomp_profile()
    if seccomp_profile is not None:
        seccomp_fd = _write_seccomp_bpf(seccomp_profile)
        if seccomp_fd is not None:
            args.extend(["--seccomp", str(seccomp_fd)])
            extra_fds.append(seccomp_fd)

    # Environment variables
    for key, value in config.env.items():
        args.extend(["--setenv", key, value])

    args.extend(["--setenv", "HOME", "/root"])
    args.append("--")
    return args, extra_fds


def _load_default_seccomp_profile() -> dict | None:
    """Load the default seccomp profile from seccomp/default.json."""
    if not _SECCOMP_DEFAULT_PATH.exists():
        logger.debug("No default seccomp profile at %s", _SECCOMP_DEFAULT_PATH)
        return None
    try:
        return json.loads(_SECCOMP_DEFAULT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load seccomp profile: %s", exc)
        return None


def _write_seccomp_bpf(profile: dict) -> int | None:
    """Compile a seccomp profile to BPF bytecode and write to a temp file."""
    from src.core.seccomp import compile_profile_to_bpf
    try:
        bpf_bytes = compile_profile_to_bpf(profile)
        tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".seccomp", prefix="minibox-", delete=False
        )
        tmp.write(bpf_bytes)
        tmp.flush()
        fd = os.dup(tmp.fileno())
        path = tmp.name
        tmp.close()
        atexit.register(lambda p=path: os.unlink(p) if os.path.exists(p) else None)
        logger.debug("Wrote %d bytes of BPF bytecode to fd %d", len(bpf_bytes), fd)
        return fd
    except Exception as exc:
        logger.warning("Failed to compile seccomp profile: %s", exc)
        return None


def _apply_cgroup_limits(handle: SandboxHandle, config: SandboxConfig) -> None:
    """Apply cgroup resource limits to the sandbox process."""
    if not config.cpu_cores and not config.memory_mb and not config.max_processes:
        return

    from src.core.cgroups import (
        ResourceLimits,
        add_pid_to_cgroup,
        create_cgroup,
        set_limits,
    )

    try:
        cgroup_path = create_cgroup(config.sandbox_id)
        limits = ResourceLimits.from_cores_and_mb(
            cores=config.cpu_cores or 2.0,
            memory_mb=config.memory_mb or 512,
        )
        if config.max_processes:
            limits.pids_max = config.max_processes
        set_limits(cgroup_path, limits)
        add_pid_to_cgroup(cgroup_path, handle.pid)
        handle.cgroup_path = cgroup_path
        logger.info(
            "Applied cgroup limits to %s: cpu=%s mem=%dMB pids=%d",
            config.sandbox_id,
            limits.cpu_max,
            config.memory_mb or 512,
            limits.pids_max,
        )
    except Exception as e:
        logger.warning("Failed to apply cgroup limits: %s", e)


async def _try_start_bwrap(
    config: SandboxConfig, workspace: Path,
) -> tuple[asyncio.subprocess.Process, list[int]]:
    """Attempt to start bwrap. Retries without seccomp if kernel lacks support."""
    bwrap_args, extra_fds = _build_bwrap_args(config, workspace)
    bwrap_args.extend(["/bin/bash", "--login", "-c", config.command])

    try:
        proc = await asyncio.create_subprocess_exec(
            "bwrap", *bwrap_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=True,
            pass_fds=tuple(extra_fds) if extra_fds else (),
        )
    except FileNotFoundError:
        raise FileNotFoundError("bwrap not found. Install: apt install bubblewrap")

    try:
        await asyncio.wait_for(proc.wait(), timeout=0.5)
        stderr = await proc.stderr.read() if proc.stderr else b""
        stderr_text = stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        return proc, extra_fds

    # If seccomp caused the failure, retry without it
    if "seccomp" in stderr_text.lower() or "SECCOMP" in stderr_text:
        logger.warning("Kernel lacks seccomp support, retrying without --seccomp")
        for fd in extra_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        config.seccomp_profile = None
        bwrap_args, extra_fds = _build_bwrap_args(config, workspace)
        bwrap_args.extend(["/bin/bash", "--login", "-c", config.command])
        try:
            proc = await asyncio.create_subprocess_exec(
                "bwrap", *bwrap_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                close_fds=True,
                pass_fds=tuple(extra_fds) if extra_fds else (),
            )
        except FileNotFoundError:
            raise FileNotFoundError("bwrap not found. Install: apt install bubblewrap")
        try:
            await asyncio.wait_for(proc.wait(), timeout=0.5)
            stderr = await proc.stderr.read() if proc.stderr else b""
            raise RuntimeError(
                f"Sandbox exited immediately (code {proc.returncode}): "
                f"{stderr.decode(errors='replace')}"
            )
        except asyncio.TimeoutError:
            return proc, extra_fds

    raise RuntimeError(
        f"Sandbox exited immediately (code {proc.returncode}): {stderr_text}"
    )


def _init_git_workspace(workspace: Path, username: str, email: str) -> None:
    """Initialize a git repository inside the sandbox workspace directory."""
    import subprocess
    try:
        # Run git init
        subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True, check=True)
        # Set config local
        subprocess.run(["git", "config", "user.name", username], cwd=str(workspace), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", email], cwd=str(workspace), capture_output=True, check=True)
        # Create an initial commit with a basic .gitignore
        gitignore = workspace / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".minibox.json\n")
        subprocess.run(["git", "add", "."], cwd=str(workspace), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(workspace), capture_output=True, check=True)
        logger.info("Initialized Git workspace for sandbox with identity %s <%s>", username, email)
    except Exception as e:
        logger.warning("Failed to initialize git repository in workspace %s: %s", workspace, e)


async def create_sandbox(config: SandboxConfig, workspace_root: Path) -> SandboxHandle:
    workspace = workspace_root / config.sandbox_id
    workspace.mkdir(parents=True, exist_ok=True)

    # Initialize Git repository
    from src.config import get_config
    cfg = get_config()
    _init_git_workspace(workspace, cfg.sandbox.git_username, cfg.sandbox.git_email)

    logger.info("Starting sandbox %s (isolation=%s)", config.sandbox_id, config.isolation_level)

    proc, extra_fds = await _try_start_bwrap(config, workspace)

    if proc.pid is None:
        raise RuntimeError("Failed to start bwrap")

    handle = SandboxHandle(sandbox_id=config.sandbox_id, pid=proc.pid, workspace=workspace)

    # Apply cgroup resource limits
    _apply_cgroup_limits(handle, config)

    # Write sandbox metadata
    (workspace / ".minibox.json").write_text(json.dumps({
        "sandbox_id": config.sandbox_id,
        "hostname": config.hostname,
        "isolation_level": config.isolation_level,
        "created_at": handle.created_at,
    }, indent=2))

    logger.info("Sandbox %s started (pid=%d)", config.sandbox_id, proc.pid)
    return handle


async def install_template_packages(
    handle: SandboxHandle,
    packages: list[str],
    timeout: float = 120.0,
) -> None:
    """Bypasses runtime apt-get since runtimes are pre-installed in the Docker image."""
    if not packages:
        return
    logger.info("Template packages are pre-installed in Docker image: %s", " ".join(packages))


async def destroy_sandbox(handle: SandboxHandle, timeout: float = 5.0) -> None:
    from src.core.network import remove_all_forwards, remove_network_policy, remove_sandbox_veth
    await remove_all_forwards(handle.sandbox_id)
    try:
        await remove_network_policy(handle.sandbox_id)
        await remove_sandbox_veth(handle.sandbox_id)
    except Exception:
        pass

    try:
        os.kill(handle.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    for _ in range(int(timeout * 10)):
        try:
            os.kill(handle.pid, 0)
            await asyncio.sleep(0.1)
        except ProcessLookupError:
            break
    else:
        try:
            os.kill(handle.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    if handle.cgroup_path and handle.cgroup_path.exists():
        try:
            from src.core.cgroups import destroy_cgroup
            destroy_cgroup(handle.cgroup_path)
        except Exception:
            pass


