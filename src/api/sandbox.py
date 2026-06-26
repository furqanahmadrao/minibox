"""Sandbox lifecycle API endpoints."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException

from src.api.deps import get_event_bus, get_registry
from src.config import get_config
from src.core.acp import ACP_AGENTS
from src.core.cgroups import (
    CGROUP_BASE,
    ResourceLimits,
    add_pid_to_cgroup,
    create_cgroup,
    freeze_cgroup,
    get_usage,
    set_limits,
    unfreeze_cgroup,
)
from src.core.executor import exec_command
from src.core.sandbox import (
    SandboxConfig,
    SandboxHandle,
    create_sandbox,
    destroy_sandbox,
    install_template_packages,
)
from src.core.templates import get_template
from src.models.sandbox import SandboxCreate, SandboxResponse, SandboxStats, SandboxUpdate
from src.orchestration.events import Event
from src.orchestration.registry import SandboxState

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])
logger = logging.getLogger(__name__)


@router.post("/create", response_model=SandboxResponse)
async def create_sandbox_endpoint(req: SandboxCreate) -> SandboxResponse:
    config = get_config()
    registry = get_registry()
    event_bus = get_event_bus()

    running = await registry.count_running()
    if running >= config.sandbox.max_concurrent:
        raise HTTPException(
            status_code=429,
            detail=f"Max concurrent ({config.sandbox.max_concurrent}) reached",
        )

    sandbox_id = str(uuid.uuid4())

    # Resolve template
    template = get_template(req.template)
    if template is None:
        raise HTTPException(status_code=400, detail=f"Template '{req.template}' not found")

    # Merge network config (network_config overrides network/egress_allowlist)
    net_mode = req.network
    egress_allowlist = req.egress_allowlist
    network_cfg = {}
    if req.network_config:
        net_mode = req.network_config.mode
        egress_allowlist = req.network_config.egress_allowlist or egress_allowlist
        network_cfg = req.network_config.model_dump()

    unshare_net = net_mode != "full"

    # For egress-only mode, start a filtering proxy
    import os
    host_path = os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    sandbox_path = f"/workspace/.npm-global/bin:/workspace/bin:{host_path}"
    env = {
        "PATH": sandbox_path,
        "NPM_CONFIG_PREFIX": "/workspace/.npm-global",
        **template.env,
        **req.env,
        "MINIBOX_TEMPLATE": req.template,
    }

    agent_cfg_data = req.agent_config.model_dump() if req.agent_config else {}
    agent_provider = agent_cfg_data.get("provider", "")
    if agent_provider and agent_provider in ACP_AGENTS:
        from src.core.agent_setup import get_agent_env_vars
        agent_env = get_agent_env_vars(
            agent_provider,
            api_key=agent_cfg_data.get("api_key", ""),
            base_url=agent_cfg_data.get("base_url", ""),
            model=agent_cfg_data.get("model", ""),
        )
        env.update(agent_env)

    egress_port = None
    if net_mode == "egress-only":
        from src.core.egress import EgressManager
        egress_mgr = getattr(create_sandbox_endpoint, "_egress_mgr", None)
        if egress_mgr is None:
            egress_mgr = EgressManager()
            create_sandbox_endpoint._egress_mgr = egress_mgr  # type: ignore[attr-defined]
        allowlist = egress_allowlist or config.network.default_egress_allowlist
        egress_port = await egress_mgr.start_for_sandbox(sandbox_id, allowlist)
        env["MINIBOX_EGRESS_PROXY"] = f"127.0.0.1:{egress_port}"
        env["http_proxy"] = f"http://127.0.0.1:{egress_port}"
        env["https_proxy"] = f"http://127.0.0.1:{egress_port}"
        env["no_proxy"] = "localhost,127.0.0.1"

    # Build per-sandbox security config
    sec_cfg = req.security.model_dump()

    sb_config = SandboxConfig(
        sandbox_id=sandbox_id,
        isolation_level=sec_cfg.get("isolation_level", "standard"),
        unshare_net=unshare_net,
        needs_network_setup=unshare_net,
        read_only_rootfs=sec_cfg.get("read_only_rootfs", True),
        no_new_privs=True,
        mask_paths=sec_cfg.get("mask_paths", []),
        readonly_paths=sec_cfg.get("readonly_paths", []),
        env=env,
        command=template.command,
        cpu_cores=req.cpu_cores,
        memory_mb=req.memory_mb,
        max_processes=sec_cfg.get("max_processes", 64),
        max_open_files=sec_cfg.get("max_open_files", 1024),
    )

    # Handle seccomp profile
    seccomp_profile_name = sec_cfg.get("seccomp_profile", "default")
    if seccomp_profile_name == "disabled":
        sb_config.seccomp_profile = None
    elif seccomp_profile_name == "custom":
        from src.core.seccomp import compile_custom_profile
        blocked = sec_cfg.get("blocked_syscalls", [])
        sb_config.seccomp_profile = compile_custom_profile(blocked_syscalls=blocked)

    try:
        handle = await create_sandbox(sb_config, config.sandbox.workspace_root)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Sandbox runtime not available: {e}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create sandbox: {e}")
    except Exception as e:
        logger.error("Unexpected error creating sandbox %s: %s", sandbox_id, e)
        raise HTTPException(status_code=500, detail=f"Sandbox creation failed: {e}")

    # Install template packages
    if template.packages:
        asyncio.create_task(
            _install_template_packages(handle.sandbox_id, handle.pid, template.packages)
        )

    # Apply network policy
    if net_mode != "full" and config.network.enforce_iptables and handle.pid:
        from src.core.network import (
            NetworkPolicy,
            apply_network_policy,
            enforce_dns_filtering,
            setup_sandbox_veth,
        )
        try:
            policy = NetworkPolicy.from_mode(net_mode, egress_allowlist)
            policy.blocked_ports = network_cfg.get("blocked_ports", config.network.blocked_ports)
            guest_ip = await setup_sandbox_veth(handle.sandbox_id, handle.pid)
            await apply_network_policy(handle.sandbox_id, handle.pid, policy, guest_ip)
            # Apply DNS filtering if configured
            dns_servers = network_cfg.get("dns_servers", config.network.dns_servers)
            if dns_servers:
                await enforce_dns_filtering(handle.pid, dns_servers)
        except Exception as e:
            logger.warning("Failed to apply network policy: %s", e)

    cgroup_path = None
    try:
        cgroup_path = create_cgroup(handle.sandbox_id)
        limits = ResourceLimits.from_cores_and_mb(req.cpu_cores, req.memory_mb)
        set_limits(cgroup_path, limits)
        add_pid_to_cgroup(cgroup_path, handle.pid)
    except Exception as e:
        logger.warning("Cgroup failed: %s", e)

    state = SandboxState(
        sandbox_id=handle.sandbox_id,
        template=req.template,
        status="running",
        label=req.label,
        ttl=req.ttl,
        cpu_cores=req.cpu_cores,
        memory_mb=req.memory_mb,
        network_mode=net_mode,
        egress_allowlist=egress_allowlist,
        env=env,
        pid=handle.pid,
        agent_config=agent_cfg_data,
        security=sec_cfg,
        network_config=network_cfg,
    )
    state.touch()
    await registry.register(state)
    handle.cgroup_path = cgroup_path

    await event_bus.publish(Event(
        sandbox_id=handle.sandbox_id,
        event_type="created",
        data={"template": req.template},
    ))

    # Install agent if specified
    agent_provider = agent_cfg_data.get("provider", "")
    if agent_provider and agent_provider in ACP_AGENTS:
        agent_cfg = ACP_AGENTS[agent_provider]
        install_cmd = agent_cfg.get("install", "")
        if install_cmd:
            asyncio.create_task(
                _install_agent(
                    handle.sandbox_id, handle.pid,
                    install_cmd, agent_provider,
                )
            )

        # Inject agent workspace config (MCP, settings, instructions, skills)
        from src.core.agent_setup import get_agent_env_vars, setup_agent_workspace
        workspace = config.sandbox.sandbox_dir(handle.sandbox_id)

        # Agent environment variables are already injected in the early env setup

        # Write config files into workspace
        try:
            setup_agent_workspace(
                workspace=workspace,
                agent_type=agent_provider,
                api_key=agent_cfg_data.get("api_key", ""),
                base_url=agent_cfg_data.get("base_url", ""),
                model=agent_cfg_data.get("model", ""),
                mcp_servers=agent_cfg_data.get("mcp_servers") or None,
                instructions=agent_cfg_data.get("instructions", ""),
                skills=agent_cfg_data.get("skills") or None,
            )
        except Exception as e:
            logger.warning("Failed to set up agent workspace: %s", e)

    from src.models.sandbox import AgentConfig, SandboxNetworkConfig, SandboxSecurityConfig

    return SandboxResponse(
        sandbox_id=handle.sandbox_id,
        status="running",
        template=req.template,
        label=req.label,
        created_at=state.created_at,
        last_activity=state.last_activity,
        ttl=req.ttl,
        ttl_remaining=state.ttl_remaining,
        cpu_cores=req.cpu_cores,
        memory_mb=req.memory_mb,
        network_mode=net_mode,
        egress_allowlist=egress_allowlist,
        pid=handle.pid,
        exec_count=0,
        agent_config=(
            AgentConfig(**agent_cfg_data) if agent_cfg_data else AgentConfig()
        ),
        env=req.env,
        security=SandboxSecurityConfig(**sec_cfg),
        network_config=(
            SandboxNetworkConfig(**network_cfg)
            if network_cfg
            else SandboxNetworkConfig(
                mode=net_mode, egress_allowlist=egress_allowlist
            )
        ),
    )


@router.delete("/{sandbox_id}")
async def destroy_sandbox_endpoint(sandbox_id: str) -> dict:
    registry = get_registry()
    event_bus = get_event_bus()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if state.pid:
        handle = SandboxHandle(
            sandbox_id=sandbox_id,
            pid=state.pid,
            workspace=get_config().sandbox.sandbox_dir(sandbox_id),
        )
        # Clean up network policy before destroying sandbox
        from src.core.network import remove_network_policy, remove_sandbox_veth
        try:
            await remove_network_policy(sandbox_id)
            await remove_sandbox_veth(sandbox_id)
        except Exception as e:
            logger.warning("Failed to clean up network policy: %s", e)
        await destroy_sandbox(handle)

    # Stop egress proxy if active
    egress_mgr = getattr(create_sandbox_endpoint, "_egress_mgr", None)
    if egress_mgr:
        await egress_mgr.stop_for_sandbox(sandbox_id)

    await registry.update(sandbox_id, status="destroyed")
    await event_bus.publish(Event(sandbox_id=sandbox_id, event_type="destroyed"))
    return {"sandbox_id": sandbox_id, "status": "destroyed"}


@router.post("/{sandbox_id}/pause")
async def pause_sandbox_endpoint(sandbox_id: str) -> dict:
    registry = get_registry()
    event_bus = get_event_bus()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if state.pid:
        cgroup_path = CGROUP_BASE / sandbox_id
        if cgroup_path.exists():
            freeze_cgroup(cgroup_path)

    await registry.update(sandbox_id, status="paused")
    await event_bus.publish(Event(sandbox_id=sandbox_id, event_type="paused"))
    return {"sandbox_id": sandbox_id, "status": "paused"}


@router.post("/{sandbox_id}/resume")
async def resume_sandbox_endpoint(sandbox_id: str) -> dict:
    registry = get_registry()
    event_bus = get_event_bus()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if state.pid:
        cgroup_path = CGROUP_BASE / sandbox_id
        if cgroup_path.exists():
            unfreeze_cgroup(cgroup_path)

    await registry.update(sandbox_id, status="running")
    await event_bus.publish(Event(sandbox_id=sandbox_id, event_type="resumed"))
    return {"sandbox_id": sandbox_id, "status": "running"}


@router.patch("/{sandbox_id}")
async def update_sandbox_endpoint(sandbox_id: str, req: SandboxUpdate) -> dict:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    updates = req.model_dump(exclude_none=True)
    await registry.update(sandbox_id, **updates)
    return {"sandbox_id": sandbox_id, "updated": list(updates.keys())}


@router.get("/list", response_model=list[SandboxResponse])
async def list_sandboxes_endpoint() -> list[SandboxResponse]:
    registry = get_registry()
    states = await registry.list_all()
    return [_state_to_response(s) for s in states]


@router.get("/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox_endpoint(sandbox_id: str) -> SandboxResponse:
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return _state_to_response(state)


@router.get("/{sandbox_id}/stats", response_model=SandboxStats)
async def sandbox_stats_endpoint(sandbox_id: str) -> SandboxStats:
    registry = get_registry()
    config = get_config()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Calculate disk usage
    sandbox_dir = config.sandbox.sandbox_dir(sandbox_id)
    disk_bytes = 0
    if sandbox_dir.exists():
        for f in sandbox_dir.rglob("*"):
            if f.is_file():
                try:
                    disk_bytes += f.stat().st_size
                except OSError:
                    pass

    # Read real CPU and memory stats from cgroup
    cpu_percent = 0.0
    memory_mb = 0.0
    cgroup_path = CGROUP_BASE / sandbox_id
    if cgroup_path.exists():
        usage = get_usage(cgroup_path)

        # Calculate CPU percent from usage_usec / elapsed time
        if "cpu_stat" in usage:
            try:
                for line in usage["cpu_stat"].splitlines():
                    if line.startswith("usage_usec "):
                        usage_usec = int(line.split()[1])
                        elapsed = time.time() - state.created_at
                        if elapsed > 0:
                            cpu_percent = round((usage_usec / 1_000_000) / elapsed * 100, 1)
                        break
            except (ValueError, IndexError):
                pass

        # Read memory from cgroup
        if "memory_current" in usage:
            memory_mb = round(usage["memory_current"] / (1024 * 1024), 1)

    return SandboxStats(
        sandbox_id=sandbox_id,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
        memory_limit_mb=state.memory_mb,
        disk_mb=round(disk_bytes / (1024 * 1024), 1),
        uptime_seconds=round(time.time() - state.created_at, 0),
        exec_count=state.exec_count,
        ttl_remaining=round(state.ttl_remaining, 0),
        status=state.status,
    )


def _state_to_response(s: SandboxState) -> SandboxResponse:
    from src.models.sandbox import AgentConfig, SandboxNetworkConfig, SandboxSecurityConfig
    agent_cfg = AgentConfig(**s.agent_config) if s.agent_config else AgentConfig()
    sec_cfg = SandboxSecurityConfig(**s.security) if s.security else SandboxSecurityConfig()
    net_cfg = (
        SandboxNetworkConfig(**s.network_config)
        if s.network_config
        else SandboxNetworkConfig(
            mode=s.network_mode, egress_allowlist=s.egress_allowlist
        )
    )
    return SandboxResponse(
        sandbox_id=s.sandbox_id,
        status=s.status,
        template=s.template,
        label=s.label,
        created_at=s.created_at,
        last_activity=s.last_activity,
        ttl=s.ttl,
        ttl_remaining=s.ttl_remaining,
        cpu_cores=s.cpu_cores,
        memory_mb=s.memory_mb,
        network_mode=s.network_mode,
        egress_allowlist=s.egress_allowlist,
        pid=s.pid,
        exec_count=s.exec_count,
        port_forwards=s.port_forwards,
        agent_config=agent_cfg,
        env=s.env,
        security=sec_cfg,
        network_config=net_cfg,
    )


async def _install_agent(sandbox_id: str, pid: int, install_cmd: str, agent_type: str) -> None:
    """Install an ACP agent inside a sandbox."""
    config = get_config()
    event_bus = get_event_bus()

    try:
        await event_bus.publish(Event(
            sandbox_id=sandbox_id,
            event_type="agent_install",
            data={"agent": agent_type, "status": "installing"},
        ))

        handle = SandboxHandle(
            sandbox_id=sandbox_id,
            pid=pid or 0,
            workspace=config.sandbox.sandbox_dir(sandbox_id),
        )

        result = await exec_command(handle, install_cmd, "/", timeout=120)

        if result.exit_code == 0:
            await event_bus.publish(Event(
                sandbox_id=sandbox_id,
                event_type="agent_install",
                data={"agent": agent_type, "status": "installed"},
            ))
            logger.info("Agent %s installed in sandbox %s", agent_type, sandbox_id)
        else:
            await event_bus.publish(Event(
                sandbox_id=sandbox_id,
                event_type="agent_install",
                data={"agent": agent_type, "status": "failed", "error": result.stderr},
            ))
            logger.error("Agent install failed in sandbox %s: %s", sandbox_id, result.stderr)
    except Exception as e:
        await event_bus.publish(Event(
            sandbox_id=sandbox_id,
            event_type="agent_install",
            data={"agent": agent_type, "status": "error", "error": str(e)},
        ))
        logger.error("Agent install error in sandbox %s: %s", sandbox_id, e)


async def _install_template_packages(sandbox_id: str, pid: int, packages: list[str]) -> None:
    """Install template packages inside a sandbox."""
    config = get_config()
    event_bus = get_event_bus()

    try:
        await event_bus.publish(Event(
            sandbox_id=sandbox_id,
            event_type="template_install",
            data={"packages": packages, "status": "installing"},
        ))

        handle = SandboxHandle(
            sandbox_id=sandbox_id,
            pid=pid or 0,
            workspace=config.sandbox.sandbox_dir(sandbox_id),
        )

        await install_template_packages(handle, packages)

        await event_bus.publish(Event(
            sandbox_id=sandbox_id,
            event_type="template_install",
            data={"packages": packages, "status": "installed"},
        ))
    except Exception as e:
        await event_bus.publish(Event(
            sandbox_id=sandbox_id,
            event_type="template_install",
            data={"packages": packages, "status": "error", "error": str(e)},
        ))
        logger.error("Template install error in sandbox %s: %s", sandbox_id, e)
