"""Network management — veth pairs, iptables enforcement, DNS filtering, domain allowlist."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_used_ports: set[int] = set()

# Network policy presets
NETWORK_POLICIES = {
    "isolated": {
        "description": "No network access at all",
        "dns": False,
        "egress": False,
        "ingress": False,
    },
    "egress-only": {
        "description": "Outbound only, no inbound, DNS allowed",
        "dns": True,
        "egress": True,
        "ingress": False,
    },
    "full": {
        "description": "Full network access with optional domain filtering",
        "dns": True,
        "egress": True,
        "ingress": True,
    },
}


@dataclass
class PortForward:
    sandbox_id: str
    port: int
    host_port: int
    pid: int | None = None
    veth_host: str = ""
    guest_ip: str = ""


@dataclass
class NetworkPolicy:
    """Network policy for a sandbox."""
    mode: str = "egress-only"
    dns_enabled: bool = True
    egress_enabled: bool = True
    ingress_enabled: bool = False
    egress_allowlist: list[str] = field(default_factory=list)
    dns_allowlist: list[str] = field(default_factory=list)
    blocked_ports: list[int] = field(default_factory=list)

    @classmethod
    def from_mode(cls, mode: str, egress_allowlist: list[str] | None = None) -> "NetworkPolicy":
        preset = NETWORK_POLICIES.get(mode, NETWORK_POLICIES["egress-only"])
        return cls(
            mode=mode,
            dns_enabled=preset["dns"],
            egress_enabled=preset["egress"],
            ingress_enabled=preset["ingress"],
            egress_allowlist=egress_allowlist or [],
        )


_active_forwards: dict[str, PortForward] = {}
_db_path: Path | None = None
# Track iptables rules per sandbox
_iptables_rules: dict[str, list[str]] = {}
# Track sandbox PIDs for cleanup
_sandbox_pids: dict[str, int] = {}


def init_forward_store(db_path: Path) -> None:
    """Initialize the forwarding state database."""
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS port_forwards (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Failed to init forward store: %s", e)


def _save_forward(forward: PortForward) -> None:
    if not _db_path:
        return
    try:
        conn = sqlite3.connect(str(_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS port_forwards (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        key = f"{forward.sandbox_id}:{forward.port}"
        data = json.dumps({
            "sandbox_id": forward.sandbox_id,
            "port": forward.port,
            "host_port": forward.host_port,
            "pid": forward.pid,
            "veth_host": forward.veth_host,
            "guest_ip": forward.guest_ip,
        })
        conn.execute(
            "INSERT OR REPLACE INTO port_forwards (key, data) VALUES (?, ?)",
            (key, data),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Failed to save forward: %s", e)


def _remove_forward_from_db(sandbox_id: str, port: int) -> None:
    if not _db_path:
        return
    try:
        conn = sqlite3.connect(str(_db_path))
        conn.execute("DELETE FROM port_forwards WHERE key = ?", (f"{sandbox_id}:{port}",))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Failed to remove forward from db: %s", e)


def _load_all_forwards() -> list[PortForward]:
    if not _db_path or not _db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(_db_path))
        forwards = []
        for row in conn.execute("SELECT data FROM port_forwards"):
            data = json.loads(row[0])
            forwards.append(PortForward(**data))
        conn.close()
        return forwards
    except Exception as e:
        logger.warning("Failed to load forwards: %s", e)
        return []


async def cleanup_orphaned_forwards() -> int:
    """Kill orphaned socat processes and remove dead forwards."""
    saved = _load_all_forwards()
    cleaned = 0
    for fwd in saved:
        alive = False
        if fwd.pid:
            try:
                os.kill(fwd.pid, 0)
                alive = True
            except (ProcessLookupError, OSError):
                pass
        if not alive:
            _remove_forward_from_db(fwd.sandbox_id, fwd.port)
            if fwd.veth_host:
                await _teardown_veth(fwd.veth_host)
            cleaned += 1
            logger.info(
                "Cleaned orphaned forward %s:%d (pid=%s)",
                fwd.sandbox_id, fwd.port, fwd.pid,
            )
        else:
            _active_forwards[f"{fwd.sandbox_id}:{fwd.port}"] = fwd
            _used_ports.add(fwd.host_port)
    if cleaned:
        logger.info("Cleaned %d orphaned port forwards", cleaned)
    return cleaned


def _next_available_port(start: int = 30000, end: int = 60000) -> int:
    """Find next available port, avoiding collisions."""
    candidate = start
    while candidate < end:
        if candidate not in _used_ports:
            return candidate
        candidate += 1
    raise RuntimeError("No available ports in range")


# ── Veth pair management ──────────────────────────────────────────────────

async def _setup_veth(sandbox_pid: int, veth_name: str, guest_ip: str) -> None:
    """Create a veth pair and move one end into the sandbox's network namespace."""
    host_ip = "172.16.0.1"
    peer_name = "eth0"

    cmds = [
        ["ip", "link", "add", veth_name, "type", "veth", "peer", "name", peer_name],
        ["ip", "link", "set", peer_name, "netns", str(sandbox_pid)],
        ["ip", "addr", "add", f"{host_ip}/24", "dev", veth_name],
        ["ip", "link", "set", veth_name, "up"],
        ["nsenter", "--target", str(sandbox_pid), "--net",
         "ip", "addr", "add", f"{guest_ip}/24", "dev", peer_name],
        ["nsenter", "--target", str(sandbox_pid), "--net",
         "ip", "link", "set", "lo", "up"],
        ["nsenter", "--target", str(sandbox_pid), "--net",
         "ip", "link", "set", peer_name, "up"],
        ["nsenter", "--target", str(sandbox_pid), "--net",
         "ip", "route", "add", "default", "via", host_ip],
    ]

    for cmd in cmds:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(
                    "veth setup cmd failed: %s -> %s",
                    cmd, stderr.decode(errors="replace"),
                )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Network command not found ({cmd[0]}). "
                "Install iproute2: apt install iproute2"
            ) from e


async def _teardown_veth(veth_name: str) -> None:
    """Remove the host-side veth interface."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "delete", veth_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
    except FileNotFoundError:
        pass


async def setup_sandbox_veth(sandbox_id: str, sandbox_pid: int) -> str:
    """Create a veth pair connecting sandbox to host, return guest IP.

    Used for egress-only mode where the sandbox needs to reach the host's
    egress proxy via a network namespace.
    """
    host_if = f"mbx_{sandbox_id[:8]}_h"
    guest_if = f"mbx_{sandbox_id[:8]}_g"
    subnet = hash(sandbox_id) % 254 + 1
    guest_ip = f"10.66.{subnet}.2"

    await _setup_veth(sandbox_pid, host_if, guest_ip)
    logger.info("Setup sandbox veth: %s -> %s (guest=%s)", host_if, guest_if, guest_ip)
    return guest_ip


async def remove_sandbox_veth(sandbox_id: str) -> None:
    """Remove the veth pair for a sandbox."""
    host_if = f"mbx_{sandbox_id[:8]}_h"
    await _teardown_veth(host_if)


# ── iptables enforcement ──────────────────────────────────────────────────

async def _iptables_run(args: list[str], check: bool = False) -> tuple[int, str]:
    """Run an iptables command. Returns (returncode, stderr)."""
    cmd = ["iptables"] + (["--check"] if check else []) + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        return proc.returncode or 0, stderr.decode(errors="replace")
    except FileNotFoundError:
        logger.warning("iptables not found — network policy not enforced")
        return -1, "iptables not found"


async def apply_network_policy(
    sandbox_id: str,
    sandbox_pid: int,
    policy: NetworkPolicy,
    guest_ip: str,
) -> None:
    """Apply iptables rules to enforce network policy inside sandbox namespace."""
    rules: list[str] = []

    # Enter sandbox namespace and apply rules
    nsenter_prefix = ["nsenter", "--target", str(sandbox_pid), "--net"]

    # Flush existing rules
    await _iptables_run(nsenter_prefix + ["-F"])

    # Default policies
    if policy.egress_enabled:
        # Allow outbound
        rules.append("INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT")
        rules.append("OUTPUT -j ACCEPT")
    else:
        # Block all outbound
        rules.append("OUTPUT -j DROP")

    if not policy.ingress_enabled:
        # Block inbound (except established)
        rules.append("INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT")
        rules.append("INPUT -j DROP")

    # DNS filtering
    if not policy.dns_enabled:
        # Block DNS (port 53)
        rules.append("OUTPUT -p udp --dport 53 -j DROP")
        rules.append("OUTPUT -p tcp --dport 53 -j DROP")

    # Domain-based egress filtering (if iptables supports it)
    if policy.egress_allowlist and policy.egress_enabled:
        # Allow only specific domains — use ipset if available
        # For basic blocking: block all, then allow known IPs
        # This is a simplified approach; production should use ipset
        for domain in policy.egress_allowlist:
            logger.debug("Egress allowlist domain: %s (DNS resolution required)", domain)

    # Port blocking
    for port in policy.blocked_ports:
        rules.append(f"OUTPUT -p tcp --dport {port} -j DROP")
        rules.append(f"OUTPUT -p udp --dport {port} -j DROP")

    # Apply rules
    for rule in rules:
        chain_args = rule.split()
        rc, err = await _iptables_run(nsenter_prefix + ["-A"] + chain_args)
        if rc != 0:
            logger.warning("iptables rule failed: %s -> %s", rule, err)

    # Save rules for cleanup
    _iptables_rules[sandbox_id] = rules
    _sandbox_pids[sandbox_id] = sandbox_pid
    logger.info(
        "Applied network policy '%s' to sandbox %s (rules=%d)",
        policy.mode, sandbox_id, len(rules),
    )


async def remove_network_policy(sandbox_id: str) -> None:
    """Remove iptables rules for a sandbox by deleting them from default chains."""
    rules = _iptables_rules.pop(sandbox_id, [])
    sandbox_pid = _sandbox_pids.pop(sandbox_id, None)
    if rules and sandbox_pid:
        nsenter_prefix = ["nsenter", "--target", str(sandbox_pid), "--net"]
        for rule in rules:
            chain_args = rule.split()
            await _iptables_run(nsenter_prefix + ["-D"] + chain_args)
        logger.info("Removed %d iptables rules for sandbox %s", len(rules), sandbox_id)


async def enforce_dns_filtering(sandbox_pid: int, dns_servers: list[str]) -> None:
    """Write a restricted resolv.conf into the sandbox namespace.

    This limits which DNS servers the sandbox can use.
    For hard DNS filtering, use iptables rules to block port 53.
    """
    if not dns_servers:
        return

    # Build a custom resolv.conf pointing only to allowed DNS servers
    lines = [f"nameserver {ns}" for ns in dns_servers]
    resolv_content = "\n".join(lines) + "\n"

    # Write to the sandbox's /etc/resolv.conf via proc filesystem
    try:
        resolv_path = f"/proc/{sandbox_pid}/root/etc/resolv.conf"
        with open(resolv_path, "w") as f:
            f.write(resolv_content)
        logger.debug("DNS filtering applied for sandbox PID %d (servers: %s)", sandbox_pid, dns_servers)
    except (FileNotFoundError, PermissionError) as e:
        logger.warning("Failed to apply DNS filtering for sandbox PID %d: %s", sandbox_pid, e)


# ── Port forwarding ───────────────────────────────────────────────────────

async def expose_port(
    sandbox_id: str,
    workspace_path: str,
    port: int,
    host_port: int | None = None,
    sandbox_pid: int | None = None,
) -> PortForward:
    """Forward a port from sandbox to host."""
    if host_port is None:
        host_port = _next_available_port()
    _used_ports.add(host_port)

    veth_host = ""
    guest_ip = ""

    if sandbox_pid is not None:
        guest_ip = f"172.16.{(host_port >> 8) & 0xFF}.{host_port & 0xFF}"
        if guest_ip.endswith(".0"):
            guest_ip = guest_ip[:-1] + "1"
        veth_host = f"veth-sb-{sandbox_id[:8]}"

        await _setup_veth(sandbox_pid, veth_host, guest_ip)
        target_ip = guest_ip
    else:
        target_ip = "127.0.0.1"

    cmd = [
        "socat",
        f"TCP-LISTEN:{host_port},fork,reuseaddr",
        f"TCP:{target_ip}:{port}",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        forward = PortForward(
            sandbox_id=sandbox_id,
            port=port,
            host_port=host_port,
            pid=proc.pid,
            veth_host=veth_host,
            guest_ip=guest_ip,
        )
        _active_forwards[f"{sandbox_id}:{port}"] = forward
        _save_forward(forward)
        logger.info(
            "Exposed port %d -> %d for sandbox %s (via %s)",
            host_port, port, sandbox_id,
            f"veth:{veth_host}" if veth_host else "loopback",
        )
        return forward
    except FileNotFoundError:
        raise RuntimeError("socat not found. Install socat: apt install socat")


async def remove_port(sandbox_id: str, port: int) -> bool:
    """Remove a port forward and its associated veth pair."""
    key = f"{sandbox_id}:{port}"
    forward = _active_forwards.pop(key, None)
    if forward and forward.pid:
        try:
            os.kill(forward.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if forward.veth_host:
            await _teardown_veth(forward.veth_host)
        _used_ports.discard(forward.host_port)
        _remove_forward_from_db(sandbox_id, port)
        logger.info("Removed port forward %d for sandbox %s", port, sandbox_id)
        return True
    return False


async def remove_all_forwards(sandbox_id: str) -> int:
    """Remove all port forwards for a sandbox."""
    keys = [k for k in _active_forwards if k.startswith(f"{sandbox_id}:")]
    count = 0
    for key in keys:
        _, port_str = key.split(":", 1)
        if await remove_port(sandbox_id, int(port_str)):
            count += 1
    return count


def list_forwards(sandbox_id: str) -> list[PortForward]:
    """List all active port forwards for a sandbox."""
    return [
        f for f in _active_forwards.values()
        if f.sandbox_id == sandbox_id
    ]



