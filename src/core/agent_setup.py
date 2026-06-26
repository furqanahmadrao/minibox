"""Per-agent workspace injection — config files, MCP, skills, provider env vars.

Each agent gets its own workspace structure:
  - Claude Code:  .claude/settings.json, .mcp.json, CLAUDE.md
  - OpenCode:     opencode.json, .opencode/, AGENTS.md
  - Codex:        .codex/config.toml, AGENTS.md
  - Pi:           .pi/agent/settings.json, .pi/agent/mcp.json, AGENTS.md

Provider API keys and base URLs are injected as environment variables at
sandbox creation time. MCP servers and skills are written to the agent's
native config format.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _skill_content(skill_name: str) -> str:
    """Generate minimal but useful skill content."""
    return (
        f"# {skill_name}\n\n"
        f"This skill provides {skill_name} capabilities within the sandbox.\n\n"
        f"## Usage\n\n"
        f"Use the {skill_name} tool to perform related tasks.\n"
    )


# ── Agent definitions ──────────────────────────────────────────────────────

AGENT_DEFINITIONS: dict[str, dict] = {
    "claude-code": {
        "name": "Claude Code",
        "install": "npm install -g @anthropic-ai/claude-code",
        "env_keys": {
            "api_key": "ANTHROPIC_API_KEY",
            "base_url": "ANTHROPIC_BASE_URL",
            "model": "ANTHROPIC_MODEL",
        },
        "run_cmd": ["claude"],
    },
    "opencode": {
        "name": "OpenCode",
        "install": "npm install -g opencode",
        "env_keys": {
            "api_key": "OPENAI_API_KEY",
            "base_url": "OPENAI_BASE_URL",
            "model": "OPENCODE_MODEL",
        },
        "run_cmd": ["opencode"],
    },
    "codex": {
        "name": "Codex",
        "install": "npm install -g @openai/codex",
        "env_keys": {
            "api_key": "OPENAI_API_KEY",
            "base_url": "OPENAI_BASE_URL",
            "model": "CODEX_MODEL",
        },
        "run_cmd": ["codex"],
    },
    "pi": {
        "name": "Pi",
        "install": "npm install -g @earendil-works/pi-coding-agent",
        "env_keys": {
            "api_key": "ANTHROPIC_API_KEY",
            "base_url": "ANTHROPIC_BASE_URL",
            "model": "PI_MODEL",
        },
        "run_cmd": ["pi"],
    },
}


def get_agent_env_vars(
    agent_type: str,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
) -> dict[str, str]:
    """Build environment variables for the configured agent/provider."""
    agent_def = AGENT_DEFINITIONS.get(agent_type)
    if not agent_def:
        return {}

    env: dict[str, str] = {}
    keys = agent_def["env_keys"]

    if api_key and keys.get("api_key"):
        env[keys["api_key"]] = api_key
    if base_url and keys.get("base_url"):
        env[keys["base_url"]] = base_url
    if model and keys.get("model"):
        env[keys["model"]] = model

    return inject_agent_workspace_config(agent_type, env)


def inject_agent_workspace_config(agent_type: str, env: dict[str, str]) -> dict[str, str]:
    """Inject agent-specific workspace config (MCP, settings) into env."""
    if agent_type == "claude-code":
        env["CLAUDE_CODE_ENABLE_TELEMETRY"] = "0"
    elif agent_type == "opencode":
        env["OPENCODE_DISABLE_CLAUDE_CODE"] = "1"
    elif agent_type == "codex":
        env["CODEX_HOME"] = "/workspace/.codex"
    elif agent_type == "pi":
        env["PI_CODING_AGENT_DIR"] = "/workspace/.pi/agent"
    return env


def setup_agent_workspace(
    workspace: Path,
    agent_type: str,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    mcp_servers: dict | None = None,
    instructions: str = "",
    skills: list[str] | None = None,
) -> None:
    """Write agent config files into the sandbox workspace."""
    if agent_type not in AGENT_DEFINITIONS:
        logger.warning("Unknown agent type: %s", agent_type)
        return

    writer = _WRITERS.get(agent_type)
    if writer:
        writer(workspace, api_key, base_url, model, mcp_servers, instructions, skills)
        logger.info("Set up %s workspace in %s", agent_type, workspace)


# ── Claude Code workspace ──────────────────────────────────────────────────

def _write_claude_code(
    workspace: Path,
    api_key: str,
    base_url: str,
    model: str,
    mcp_servers: dict | None,
    instructions: str,
    skills: list[str] | None,
) -> None:
    # .claude/settings.json
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    settings: dict = {
        "permissions": {"allow": [], "deny": []},
        "env": {},
    }
    if model:
        settings["env"]["ANTHROPIC_MODEL"] = model

    (claude_dir / "settings.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )

    # .mcp.json (project-level MCP)
    if mcp_servers:
        mcp_config = {"mcpServers": mcp_servers}
        (workspace / ".mcp.json").write_text(
            json.dumps(mcp_config, indent=2), encoding="utf-8"
        )

    # CLAUDE.md (project instructions)
    if instructions:
        (workspace / "CLAUDE.md").write_text(instructions, encoding="utf-8")

    # Skills
    if skills:
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_name in skills:
            skill_dir = skills_dir / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                _skill_content(skill_name),
                encoding="utf-8",
            )


# ── OpenCode workspace ─────────────────────────────────────────────────────

def _write_opencode(
    workspace: Path,
    api_key: str,
    base_url: str,
    model: str,
    mcp_servers: dict | None,
    instructions: str,
    skills: list[str] | None,
) -> None:
    # opencode.json
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
    }
    if model:
        config["model"] = model

    # Provider config
    if api_key or base_url:
        provider_cfg: dict = {}
        if api_key:
            provider_cfg["apiKey"] = api_key
        if base_url:
            provider_cfg["baseURL"] = base_url
        # Detect provider from base_url or default to anthropic
        provider_name = "anthropic"
        if base_url:
            if "openai" in base_url.lower():
                provider_name = "openai"
            elif "google" in base_url.lower() or "gemini" in base_url.lower():
                provider_name = "google"
            elif "anthropic" in base_url.lower():
                provider_name = "anthropic"
            else:
                provider_name = "custom"
        config["provider"] = {provider_name: {"options": provider_cfg}}

    # MCP servers
    if mcp_servers:
        mcp_cfg: dict = {}
        for name, srv in mcp_servers.items():
            if "command" in srv:
                mcp_cfg[name] = {
                    "type": "local",
                    "command": srv.get("command", []),
                    "environment": srv.get("env", {}),
                    "enabled": True,
                }
            elif "url" in srv:
                mcp_cfg[name] = {
                    "type": "remote",
                    "url": srv["url"],
                    "enabled": True,
                }
        config["mcp"] = mcp_cfg

    (workspace / "opencode.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    # .opencode/ directory
    opencode_dir = workspace / ".opencode"
    opencode_dir.mkdir(parents=True, exist_ok=True)

    # AGENTS.md (project instructions)
    if instructions:
        (workspace / "AGENTS.md").write_text(instructions, encoding="utf-8")

    # Skills
    if skills:
        skills_dir = opencode_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_name in skills:
            skill_dir = skills_dir / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                _skill_content(skill_name),
                encoding="utf-8",
            )


# ── Codex workspace ────────────────────────────────────────────────────────

def _write_codex(
    workspace: Path,
    api_key: str,
    base_url: str,
    model: str,
    mcp_servers: dict | None,
    instructions: str,
    skills: list[str] | None,
) -> None:
    # .codex/config.toml
    codex_dir = workspace / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)

    config: dict = {}
    if model:
        config["model"] = model

    # Custom provider
    if api_key or base_url:
        provider: dict = {}
        if base_url:
            provider["base_url"] = base_url
        if api_key:
            provider["env_key"] = "OPENAI_API_KEY"
        config["model_providers"] = {"custom": provider}

    # MCP servers (TOML format)
    if mcp_servers:
        mcp_cfg: dict = {}
        for name, srv in mcp_servers.items():
            if "command" in srv:
                server_cfg: dict = {
                    "command": srv.get("command", ["npx"]),
                    "args": srv.get("args", []),
                    "enabled": True,
                }
                if "env" in srv:
                    server_cfg["env"] = srv["env"]
                mcp_cfg[name] = server_cfg
            elif "url" in srv:
                mcp_cfg[name] = {
                    "url": srv["url"],
                    "enabled": True,
                }
        config["mcp_servers"] = mcp_cfg

    (codex_dir / "config.toml").write_text(
        _dict_to_toml(config), encoding="utf-8"
    )

    # AGENTS.md
    if instructions:
        (workspace / "AGENTS.md").write_text(instructions, encoding="utf-8")

    # Skills
    if skills:
        skills_dir = codex_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_name in skills:
            skill_dir = skills_dir / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                _skill_content(skill_name),
                encoding="utf-8",
            )


# ── Pi workspace ───────────────────────────────────────────────────────────

def _write_pi(
    workspace: Path,
    api_key: str,
    base_url: str,
    model: str,
    mcp_servers: dict | None,
    instructions: str,
    skills: list[str] | None,
) -> None:
    # .pi/agent/settings.json
    pi_dir = workspace / ".pi" / "agent"
    pi_dir.mkdir(parents=True, exist_ok=True)

    settings: dict = {}
    if model:
        settings["defaultModel"] = model
    if base_url:
        # Pi uses models.json for custom providers
        models_cfg: dict = {
            "providers": {
                "custom": {
                    "baseUrl": base_url,
                    "api": "anthropic-messages",
                    "apiKey": api_key or "",
                    "models": [],
                }
            }
        }
        (pi_dir / "models.json").write_text(
            json.dumps(models_cfg, indent=2), encoding="utf-8"
        )

    (pi_dir / "settings.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )

    # .pi/agent/mcp.json
    if mcp_servers:
        mcp_cfg: dict = {"mcpServers": {}}
        for name, srv in mcp_servers.items():
            if "command" in srv:
                mcp_cfg["mcpServers"][name] = {
                    "command": srv.get("command", ["npx"]),
                    "args": srv.get("args", []),
                }
            elif "url" in srv:
                mcp_cfg["mcpServers"][name] = {"url": srv["url"]}
        (pi_dir / "mcp.json").write_text(
            json.dumps(mcp_cfg, indent=2), encoding="utf-8"
        )

    # AGENTS.md
    if instructions:
        (workspace / "AGENTS.md").write_text(instructions, encoding="utf-8")

    # Skills
    if skills:
        skills_dir = workspace / ".pi" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_name in skills:
            skill_dir = skills_dir / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                _skill_content(skill_name),
                encoding="utf-8",
            )


# ── TOML writer (minimal, no external deps) ────────────────────────────────

def _dict_to_toml(d: dict, prefix: str = "") -> str:
    """Convert a nested dict to TOML string. Handles str, int, float, bool, list, dict."""
    lines: list[str] = []
    for key, value in d.items():
        if isinstance(value, dict):
            section = f"{prefix}.{key}" if prefix else key
            lines.append(f"\n[{section}]")
            lines.append(_dict_to_toml(value, section))
        elif isinstance(value, bool):
            lines.append(f'{key} = {"true" if value else "false"}')
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
        elif isinstance(value, list):
            items = ", ".join(
                f'"{v}"' if isinstance(v, str) else str(v) for v in value
            )
            lines.append(f"{key} = [{items}]")
    return "\n".join(lines)


# ── Writer dispatch ────────────────────────────────────────────────────────

_WRITERS = {
    "claude-code": _write_claude_code,
    "opencode": _write_opencode,
    "codex": _write_codex,
    "pi": _write_pi,
}
