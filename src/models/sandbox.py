"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.core.templates import list_templates


class AgentConfig(BaseModel):
    """Configuration for AI agent runtime."""

    provider: str = ""  # claude-code, opencode, codex, pi (empty = no agent)
    base_url: str = ""  # custom API base URL for the provider
    api_key: str = ""  # API key for the provider
    model: str = ""  # specific model to use
    mode: str = "interactive"  # interactive or headless
    prompt: str = ""  # initial prompt for headless mode
    extra: dict[str, str] = Field(default_factory=dict)  # provider-specific config
    mcp_servers: dict[str, dict] = Field(default_factory=dict)  # MCP servers to inject
    instructions: str = ""  # project-level instructions (CLAUDE.md / AGENTS.md)
    skills: list[str] = Field(default_factory=list)  # skills to install


class SandboxSecurityConfig(BaseModel):
    """Per-sandbox security isolation settings."""

    # Isolation level: minimal, standard, strict
    isolation_level: str = "standard"
    # Symlink policy: block (reject symlinks), follow (allow symlinks in workspace)
    symlink_policy: str = "block"
    # Read-only root filesystem (prevents writes outside /tmp)
    read_only_rootfs: bool = True
    # Max processes (pids.max in cgroup, 0 = use default)
    max_processes: int = 64
    # Max open files per process
    max_open_files: int = 1024
    # Paths masked to /dev/null (e.g., /proc/acpi, /proc/kcore)
    mask_paths: list[str] = Field(default_factory=list)
    # Paths mounted read-only
    readonly_paths: list[str] = Field(default_factory=list)
    # Seccomp profile: default, custom, disabled
    seccomp_profile: str = "default"
    # Additional blocked syscalls (when seccomp_profile = custom)
    blocked_syscalls: list[str] = Field(default_factory=list)


class SandboxNetworkConfig(BaseModel):
    """Per-sandbox network settings."""

    # Network mode: isolated, egress-only, full
    mode: str = "egress-only"
    # Domain allowlist (for egress-only mode)
    egress_allowlist: list[str] = Field(default_factory=list)
    # Enable DNS filtering
    dns_filtering: bool = True
    # DNS servers (override global)
    dns_servers: list[str] = Field(default_factory=list)
    # Ports blocked outbound
    blocked_ports: list[int] = Field(default_factory=list)
    # Enforce iptables rules
    enforce_iptables: bool = True


class SandboxCreate(BaseModel):
    template: str = "python-dev"
    label: str = ""
    ttl: int = 1800
    cpu_cores: float = 2.0
    memory_mb: int = 512
    network: str = "egress-only"
    egress_allowlist: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    agent_config: AgentConfig = Field(default_factory=AgentConfig)
    headless: bool = False
    # Per-sandbox security config
    security: SandboxSecurityConfig = Field(default_factory=SandboxSecurityConfig)
    # Per-sandbox network config (overrides network + egress_allowlist if provided)
    network_config: SandboxNetworkConfig | None = None

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        valid = [t.id for t in list_templates()]
        if v not in valid:
            raise ValueError(f"Template must be one of: {', '.join(valid)}")
        return v


class SandboxResponse(BaseModel):
    sandbox_id: str
    status: str
    template: str = ""
    label: str = ""
    created_at: float = 0
    last_activity: float = 0
    ttl: int = 1800
    ttl_remaining: float = 0
    cpu_cores: float = 2.0
    memory_mb: int = 512
    network_mode: str = "egress-only"
    egress_allowlist: list[str] = Field(default_factory=list)
    pid: int | None = None
    exec_count: int = 0
    port_forwards: list[dict] = Field(default_factory=list)
    agent_config: AgentConfig = Field(default_factory=AgentConfig)
    env: dict[str, str] = Field(default_factory=dict)
    # Per-sandbox security config
    security: SandboxSecurityConfig = Field(default_factory=SandboxSecurityConfig)
    network_config: SandboxNetworkConfig = Field(default_factory=SandboxNetworkConfig)


class SandboxUpdate(BaseModel):
    ttl: int | None = None
    cpu_cores: float | None = None
    memory_mb: int | None = None
    network: str | None = None
    egress_allowlist: list[str] | None = None
    env: dict[str, str] | None = None
    agent_config: AgentConfig | None = None
    security: SandboxSecurityConfig | None = None
    network_config: SandboxNetworkConfig | None = None


class SandboxStats(BaseModel):
    sandbox_id: str
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_limit_mb: int = 512
    disk_mb: float = 0.0
    uptime_seconds: float = 0.0
    exec_count: int = 0
    ttl_remaining: float = 0.0
    status: str = "unknown"


class ExecRequest(BaseModel):
    cmd: str
    workdir: str = "/"
    timeout: float = 30.0
    env: dict[str, str] | None = None


class ExecBatchRequest(BaseModel):
    commands: list[str]
    workdir: str = "/"
    timeout: float = 30.0


class ExecResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: float = 0
    sandbox_id: str = ""


class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileResponse(BaseModel):
    path: str = ""
    content: str = ""
    size: int = 0
    deleted: bool = False


class PortExposeRequest(BaseModel):
    port: int
    host_port: int | None = None


class SnapshotRequest(BaseModel):
    label: str = ""


class ForkRequest(BaseModel):
    snapshot_id: str = ""
    label: str = ""


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    packages: list[str] = Field(default_factory=list)
    is_custom: bool = False


class TemplateRegisterRequest(BaseModel):
    id: str
    name: str
    description: str
    packages: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_in: int = 3600
    refresh_expires_in: int = 604800


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class TokenRefreshResponse(BaseModel):
    token: str
    refresh_token: str
    expires_in: int


class APIKeyCreateRequest(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["developer"])
    role: str = "user"
    expires_in_days: int | None = None


class APIKeyResponse(BaseModel):
    key: str
    name: str
    role: str
    scopes: list[str] = Field(default_factory=list)
    created_at: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "admin"
