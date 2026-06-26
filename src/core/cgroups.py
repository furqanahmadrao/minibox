"""Cgroups v2 resource limiting."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CGROUP_BASE = Path("/sys/fs/cgroup/minibox")


@dataclass
class ResourceLimits:
    cpu_max: str = "200000 100000"
    memory_max: int = 536870912
    memory_high: int = 402653184
    pids_max: int = 64

    @classmethod
    def from_cores_and_mb(cls, cores: float, memory_mb: int) -> ResourceLimits:
        cpu_quota = cores * 100000
        return cls(
            cpu_max=f"{cpu_quota} 100000",
            memory_max=memory_mb * 1024 * 1024,
            memory_high=int(memory_mb * 1024 * 1024 * 0.8),
            pids_max=64,
        )


def create_cgroup(sandbox_id: str) -> Path:
    """Create a cgroup for a sandbox."""
    cgroup_path = CGROUP_BASE / sandbox_id
    cgroup_path.mkdir(parents=True, exist_ok=True)

    # Write cgroup type (if needed for cgroups v2)
    try:
        (cgroup_path / "cgroup.type").write_text("domain")
    except (PermissionError, OSError):
        pass

    return cgroup_path


def set_limits(cgroup_path: Path, limits: ResourceLimits) -> None:
    """Apply resource limits to a cgroup."""
    try:
        (cgroup_path / "cpu.max").write_text(limits.cpu_max)
    except (PermissionError, OSError) as e:
        logger.warning("Failed to set cpu.max: %s", e)

    try:
        (cgroup_path / "memory.max").write_text(str(limits.memory_max))
    except (PermissionError, OSError) as e:
        logger.warning("Failed to set memory.max: %s", e)

    try:
        (cgroup_path / "memory.high").write_text(str(limits.memory_high))
    except (PermissionError, OSError) as e:
        logger.warning("Failed to set memory.high: %s", e)

    try:
        (cgroup_path / "pids.max").write_text(str(limits.pids_max))
    except (PermissionError, OSError) as e:
        logger.warning("Failed to set pids.max: %s", e)


def add_pid_to_cgroup(cgroup_path: Path, pid: int) -> None:
    """Add a process to a cgroup."""
    try:
        (cgroup_path / "cgroup.procs").write_text(str(pid))
    except (PermissionError, OSError) as e:
        logger.warning("Failed to add pid %d to cgroup: %s", pid, e)


def get_usage(cgroup_path: Path) -> dict:
    """Get resource usage from a cgroup."""
    usage = {}
    try:
        usage["memory_current"] = int((cgroup_path / "memory.current").read_text().strip())
    except Exception:
        pass
    try:
        usage["cpu_stat"] = (cgroup_path / "cpu.stat").read_text().strip()
    except Exception:
        pass
    try:
        usage["pids_current"] = int((cgroup_path / "pids.current").read_text().strip())
    except Exception:
        pass
    return usage


def destroy_cgroup(cgroup_path: Path) -> None:
    """Destroy a cgroup."""
    try:
        if cgroup_path.exists():
            cgroup_path.rmdir()
    except OSError as e:
        logger.warning("Failed to destroy cgroup %s: %s", cgroup_path, e)


def freeze_cgroup(cgroup_path: Path) -> bool:
    """Freeze all processes in the cgroup (cgroups v2). Returns True on success."""
    try:
        (cgroup_path / "cgroup.freeze").write_text("1")
        return True
    except (PermissionError, OSError) as e:
        logger.warning("Failed to freeze cgroup %s: %s", cgroup_path, e)
        return False


def unfreeze_cgroup(cgroup_path: Path) -> bool:
    """Unfreeze all processes in the cgroup (cgroups v2). Returns True on success."""
    try:
        (cgroup_path / "cgroup.freeze").write_text("0")
        return True
    except (PermissionError, OSError) as e:
        logger.warning("Failed to unfreeze cgroup %s: %s", cgroup_path, e)
        return False
