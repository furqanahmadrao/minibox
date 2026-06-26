"""Configuration from environment variables and config file."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ServerConfig(BaseSettings):
    host: str = Field(default="0.0.0.0", alias="MINIBOX_HOST")
    port: int = Field(default=8080, alias="MINIBOX_PORT")
    workers: int = Field(default=1, alias="MINIBOX_WORKERS")
    model_config = {"env_prefix": "", "populate_by_name": True}


class SandboxConfig(BaseSettings):
    workspace_root: Path = Field(default=Path("/workspaces"), alias="MINIBOX_WORKSPACE_ROOT")
    default_ttl: int = Field(default=1800, alias="MINIBOX_DEFAULT_TTL")
    max_concurrent: int = Field(default=20, alias="MINIBOX_MAX_CONCURRENT")
    default_cpu_cores: float = Field(default=2.0, alias="MINIBOX_DEFAULT_CPU_CORES")
    default_memory_mb: int = Field(default=512, alias="MINIBOX_DEFAULT_MEMORY_MB")
    # Isolation: minimal, standard, strict
    default_isolation_level: str = Field(default="standard", alias="MINIBOX_ISOLATION_LEVEL")
    # Symlink policy: block (reject any symlink), follow (allow symlinks inside workspace)
    symlink_policy: str = Field(default="block", alias="MINIBOX_SYMLINK_POLICY")
    # Max processes per sandbox (0 = use system default, cgroup pids.max)
    max_processes: int = Field(default=64, alias="MINIBOX_MAX_PROCESSES")
    # Max open files per sandbox
    max_open_files: int = Field(default=1024, alias="MINIBOX_MAX_OPEN_FILES")
    # Read-only root filesystem (prevents writes to /tmp, /root, etc.)
    read_only_rootfs: bool = Field(default=True, alias="MINIBOX_READ_ONLY_ROOTFS")
    # Customizable Git settings inside sandbox workspaces
    git_username: str = Field(default="Agent", alias="MINIBOX_GIT_USERNAME")
    git_email: str = Field(default="agent@minibox.local", alias="MINIBOX_GIT_EMAIL")
    git_commit_interval: int = Field(default=600, alias="MINIBOX_GIT_COMMIT_INTERVAL")
    # Block dangerous paths
    mask_paths: list[str] = Field(
        default_factory=lambda: [
            "/proc/acpi",
            "/proc/kcore",
            "/proc/keys",
            "/proc/sched_debug",
            "/proc/timer_list",
            "/proc/timer_stats",
            "/proc/wakelocks",
        ],
        alias="MINIBOX_MASK_PATHS",
    )
    model_config = {"env_prefix": "", "populate_by_name": True}

    def sandbox_dir(self, sandbox_id: str) -> Path:
        """Host path: /workspaces/{sandbox_id}/"""
        return self.workspace_root / sandbox_id


class AuthConfig(BaseSettings):
    enabled: bool = Field(default=True, alias="MINIBOX_AUTH_ENABLED")
    api_key: str = Field(default="", alias="MINIBOX_API_KEY")
    jwt_secret: str = Field(default="", alias="MINIBOX_JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="MINIBOX_JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="MINIBOX_JWT_EXPIRE_MINUTES")
    jwt_refresh_minutes: int = Field(default=10080, alias="MINIBOX_JWT_REFRESH_MINUTES")
    # Optional env-based credentials (if set, no signup needed)
    username: str = Field(default="", alias="MINIBOX_USERNAME")
    password: str = Field(default="", alias="MINIBOX_PASSWORD")
    model_config = {"env_prefix": "", "populate_by_name": True}

    @model_validator(mode="after")
    def _generate_secrets(self) -> "AuthConfig":
        if not self.api_key:
            self.api_key = secrets.token_urlsafe(32)
            logger.warning("No MINIBOX_API_KEY set — generated random key: %s", self.api_key)
        if not self.jwt_secret:
            self.jwt_secret = secrets.token_urlsafe(64)
            logger.warning(
                "No MINIBOX_JWT_SECRET set — tokens will be INVALID on restart. "
                "Set MINIBOX_JWT_SECRET env var for persistent tokens."
            )
        return self


class SecurityConfig(BaseSettings):
    """Security hardening settings."""

    # Rate limiting
    rate_limit_rpm: int = Field(default=120, alias="MINIBOX_RATE_LIMIT_RPM")
    rate_limit_burst: int = Field(default=20, alias="MINIBOX_RATE_LIMIT_BURST")
    login_rate_limit: int = Field(default=5, alias="MINIBOX_LOGIN_RATE_LIMIT")
    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], alias="MINIBOX_CORS_ORIGINS")
    cors_allow_credentials: bool = Field(default=True, alias="MINIBOX_CORS_CREDENTIALS")
    # Password policy
    min_password_length: int = Field(default=8, alias="MINIBOX_MIN_PASSWORD_LENGTH")
    # API key defaults
    default_key_expiry_days: int | None = Field(default=None, alias="MINIBOX_KEY_EXPIRY_DAYS")
    model_config = {"env_prefix": "", "populate_by_name": True}


class StorageConfig(BaseSettings):
    snapshot_path: Path = Field(default=Path("/data/snapshots"), alias="MINIBOX_SNAPSHOT_PATH")
    model_config = {"env_prefix": "", "populate_by_name": True}


class LogConfig(BaseSettings):
    level: str = Field(default="INFO", alias="MINIBOX_LOG_LEVEL")
    format: Literal["json", "text"] = Field(default="text", alias="MINIBOX_LOG_FORMAT")
    file: str = Field(default="", alias="MINIBOX_LOG_FILE")
    model_config = {"env_prefix": "", "populate_by_name": True}


class NetworkConfig(BaseSettings):
    port_range_start: int = Field(default=30000, alias="MINIBOX_PORT_RANGE_START")
    port_range_end: int = Field(default=60000, alias="MINIBOX_PORT_RANGE_END")
    default_egress_allowlist: list[str] = Field(
        default_factory=list, alias="MINIBOX_EGRESS_ALLOWLIST"
    )
    # Default network mode: isolated, egress-only, full
    default_mode: str = Field(default="egress-only", alias="MINIBOX_NETWORK_MODE")
    # DNS filtering
    dns_filtering: bool = Field(default=True, alias="MINIBOX_DNS_FILTERING")
    dns_servers: list[str] = Field(
        default_factory=lambda: ["8.8.8.8", "8.8.4.4"],
        alias="MINIBOX_DNS_SERVERS",
    )
    # Blocked ports (outbound)
    blocked_ports: list[int] = Field(default_factory=list, alias="MINIBOX_BLOCKED_PORTS")
    # Enforce iptables rules
    enforce_iptables: bool = Field(default=True, alias="MINIBOX_ENFORCE_IPTABLES")
    model_config = {"env_prefix": "", "populate_by_name": True}


class Config(BaseSettings):
    server: ServerConfig = Field(default_factory=ServerConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LogConfig = Field(default_factory=LogConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    model_config = {"populate_by_name": True}

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            server=ServerConfig(),
            sandbox=SandboxConfig(),
            auth=AuthConfig(),
            security=SecurityConfig(),
            storage=StorageConfig(),
            logging=LogConfig(),
            network=NetworkConfig(),
        )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        cfg = Config.from_env()
        # Look for config.json overrides in the database directory (parent of workspace_root)
        db_dir = cfg.sandbox.workspace_root.parent
        json_path = db_dir / "config.json"
        if json_path.exists():
            try:
                import json
                data = json.loads(json_path.read_text(encoding="utf-8"))
                # Re-instantiate Config with the saved JSON overrides
                cfg = Config(**data)
            except Exception as e:
                logger.warning("Failed to load config overrides from %s: %s", json_path, e)
        _config = cfg
    return _config


def save_config(updates: dict) -> None:
    """Update the global config instance and write changes to config.json."""
    global _config
    cfg = get_config()
    db_dir = cfg.sandbox.workspace_root.parent
    json_path = db_dir / "config.json"

    existing_data = {}
    if json_path.exists():
        try:
            import json
            existing_data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Deep merge updates into existing_data
    for section, values in updates.items():
        if isinstance(values, dict):
            if section not in existing_data:
                existing_data[section] = {}
            existing_data[section].update(values)
        else:
            existing_data[section] = values

    # Save back to file
    try:
        import json
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(existing_data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to save config overrides to %s: %s", json_path, e)

    # Invalidate and reload global configuration
    _config = None
    get_config()
