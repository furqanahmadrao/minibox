# Minibox — Product Requirements Document

> **Self-hosted agent sandbox.** Give AI coding agents an isolated Linux workspace — filesystem, terminal, network, resource limits — without the SaaS tax or the microVM overhead.

---

## What Minibox Is

Minibox is a lightweight sandbox runtime you run on your own Linux machine. Every AI agent gets its own isolated workspace: a private filesystem, a PTY terminal, a configurable network policy, and hard resource caps. You control everything from a single web dashboard, connect agents directly over MCP or ACP, and never pay per-sandbox-minute to a cloud provider.

**The gap we fill:**

| | Minibox | E2B / Daytona | Plain Docker |
|---|---|---|---|
| Startup time | ~50 ms | 2–5 s | 1–3 s |
| Self-hostable | ✅ | ❌ SaaS | ✅ |
| Agent-native API | ✅ Built-in | ✅ | ❌ Roll your own |
| MCP server | ✅ Built-in | ❌ | ❌ |
| Human-in-the-loop UI | ✅ Built-in | ❌ | ❌ |
| Cost | Your hardware | $0.10+/hr/sandbox | Your hardware |
| Root daemon required | ❌ | ✅ Firecracker | ✅ dockerd |

**Pick Minibox when:** you own a Linux box, you run one or several agents at a time, you want a dashboard with real controls, and you don't need hypervisor-grade multi-tenant isolation.

---

## Core Principles

1. **One command, one port.** `docker run -p 8080:8080 minibox` — the dashboard, the REST API, and the MCP server all live at `:8080`. Nothing else to configure.
2. **Agent-first.** Every capability is a first-class API endpoint or MCP tool. No human-only workflows.
3. **You own the data.** All state lives in `/data` on a volume you mount. Delete the container; your sandboxes, snapshots, and config survive.
4. **Human in the loop by design.** Agents run autonomously by default, but you can pause at any point, take over the terminal, inspect files, and resume.
5. **Secure by default.** Auth on, namespaces on, seccomp on, resource limits on — everything locked down unless you explicitly open it.

---

## User Stories

### Developer running an agent
- I can create a sandbox from a template (Python, Node, Rust, minimal) and have an agent working inside it in under a second.
- I can watch the agent's terminal live, pause it if something looks wrong, edit files manually, and resume.
- I can snapshot the sandbox state, fork it into two parallel branches, compare outcomes, and discard the loser.
- I can set cron schedules to run commands inside a sandbox automatically (e.g. `pytest` every 5 minutes).
- I can set HITL breakpoints — regex patterns like `rm -rf` or `git push` — that pause execution and notify me.

### Agent (via MCP or REST)
- I can create an isolated sandbox, install dependencies, write code, run tests, expose a port, and check the result — all through tool calls.
- I can snapshot my state before a risky step and fork if I want to explore two approaches in parallel.
- I can read and write files in my workspace without touching the host filesystem.

### Admin
- I can manage users, scoped API keys, and auth settings from the dashboard without touching env files.
- I can define custom sandbox templates with pre-installed packages and default env vars.
- I can watch live server logs and audit trails from the dashboard.
- I can configure resource defaults, network policies, and Git identity from the UI — settings persist across restarts.

---

## Features

### Sandbox Isolation
Each sandbox is a bubblewrap-wrapped Linux environment with:
- **Private filesystem** — host root is read-only; `/workspace` is the agent's writable directory.
- **PID isolation** — the agent sees only its own processes.
- **Network policies** — `isolated` (no network), `egress-only` (allowlisted domains only), or `full` (open internet).
- **Resource caps** — CPU cores, memory (MB), and max processes enforced via cgroups v2.
- **Seccomp filtering** — dangerous syscalls (`ptrace`, `mount`, `io_uring`, terminal injection) are blocked by default.

### Agent Interfaces
- **REST API** — full CRUD and streaming over HTTP for any language or tool.
- **MCP Server** — sandboxes exposed as MCP tools; plug directly into Claude Code, Cursor, Claude.ai.
- **ACP Bridge** — runs coding agents (Claude Code, OpenCode, Codex, Pi) inside the isolated sandbox using stdio JSON-RPC; the dashboard's Agent tab is a full chat interface connected over WebSocket.

### Workspace Management
- **Git-by-default** — every workspace is a git repo; background daemon auto-commits changes (configurable interval, default 10 min) for a full audit trail.
- **Snapshots** — checkpoint the workspace as a `.tar.gz`; restore or fork into a new sandbox at any point.
- **File explorer + editor** — browse, create, edit, and delete files directly from the dashboard.
- **Port exposure** — map a port inside the sandbox to a host port and get a URL back.

### Human-in-the-loop Controls
- **Pause / Resume** — freeze the sandbox process group at any moment.
- **Terminal takeover** — interactive PTY in the browser; type commands directly into the running shell.
- **Breakpoints** — define regex patterns on exec commands or file write paths; matching calls pause and wait for manual approval or rejection.
- **Cron schedules** — create, edit, enable/disable, and manually trigger recurring commands per sandbox.

### Dashboard
- Glassmorphic dark UI built with React, Vite, and TypeScript.
- Per-sandbox panel with tabs: Terminal · Workspace · Diff · Logs · Snapshots · Schedules · Breakpoints · Agent · Settings.
- Server-wide Settings panel: Users · API Keys · Templates · Configuration · Logs & Audit.

### Auth & Security
- **JWT + Refresh tokens** — short-lived access tokens, long-lived refresh tokens, token rotation.
- **Scoped API keys** — create keys with specific permission scopes (`sandbox:create`, `sandbox:write`, `admin:config`, etc.).
- **First-run setup flow** — `/api/auth/status` tells the frontend whether to show login or initial admin setup.
- **Env-var credentials** — set `MINIBOX_USERNAME` + `MINIBOX_PASSWORD` to bootstrap without the UI.
- **Rate limiting** — login attempts and API requests are rate-limited independently.

### Templates
- Built-in: `python-dev`, `node-dev`, `rust-dev`, `research`, `data-science`, `minimal`.
- Custom templates: define name, description, pre-installed packages, and default env vars — saved to `templates.json`, CRUD via API and dashboard.

---

## Architecture Overview

```
Port 8080 (single process)
├── /               → React dashboard (static assets)
├── /api/*          → FastAPI REST + WebSocket routes
│   ├── /api/sandbox/*    sandbox lifecycle, exec, fs, network, snapshots, schedules
│   ├── /api/templates/*  template CRUD
│   ├── /api/agent/*      agent/provider metadata
│   ├── /api/auth/*       login, tokens, API keys, users, audit
│   └── /api/admin/*      config PATCH, live log stream
├── /mcp/sse        → MCP server (SSE transport)
├── /mcp/message    → MCP message endpoint
└── /docs           → Swagger UI
```

**Isolation stack (per sandbox):**
```
bubblewrap (bwrap)
  └── Linux namespaces: PID · mount · network · user · UTS · IPC
        └── cgroups v2: CPU · memory · PIDs
              └── seccomp-bpf: syscall allowlist
```

**Storage (mounted volume `/data`):**
```
/data/
├── config.json         global configuration overrides
├── templates.json      custom template definitions
├── api_keys.json       scoped API key store
├── users.json          user account store
├── port_forwards.db    active port forward mappings
├── schedules.db        cron schedule definitions
├── workspaces/
│   └── {sandbox_id}/   → mounted as /workspace inside bwrap
│       └── .git/       auto-initialized; background commits every N minutes
└── snapshots/
    └── snap_{id}_{ts}.tar.gz
```

---

## Configuration

All settings have sane defaults and can be overridden by environment variables or, at runtime, by `PATCH /api/admin/config` (persisted to `/data/config.json`).

| Setting | Env var | Default |
|---|---|---|
| Server host | `MINIBOX_HOST` | `0.0.0.0` |
| Server port | `MINIBOX_PORT` | `8080` |
| Workspace root | `MINIBOX_WORKSPACE_ROOT` | `/data/workspaces` |
| Default TTL (s) | `MINIBOX_DEFAULT_TTL` | `1800` |
| Max concurrent sandboxes | `MINIBOX_MAX_CONCURRENT` | `20` |
| Default CPU cores | `MINIBOX_DEFAULT_CPU_CORES` | `2.0` |
| Default memory (MB) | `MINIBOX_DEFAULT_MEMORY_MB` | `512` |
| Git commit interval (s) | `MINIBOX_GIT_COMMIT_INTERVAL` | `600` |
| Git identity | `MINIBOX_GIT_USERNAME` / `MINIBOX_GIT_EMAIL` | `Agent / agent@minibox.local` |
| Auth enabled | `MINIBOX_AUTH_ENABLED` | `true` |
| Admin API key | `MINIBOX_API_KEY` | auto-generated |
| JWT secret | `MINIBOX_JWT_SECRET` | auto-generated (rotate on restart if unset) |
| Bootstrap admin | `MINIBOX_USERNAME` / `MINIBOX_PASSWORD` | — |
| Default network mode | `MINIBOX_NETWORK_MODE` | `egress-only` |
| Snapshot path | `MINIBOX_SNAPSHOT_PATH` | `/data/snapshots` |

---

## MCP Tools Reference

Agents connecting via MCP have access to the full sandbox lifecycle:

| Tool | What it does |
|---|---|
| `create_sandbox` | Spin up an isolated sandbox from a template |
| `exec` | Run a shell command; returns stdout, stderr, exit code |
| `exec_batch` | Run multiple commands sequentially |
| `write_file` | Write a file into the sandbox workspace |
| `read_file` | Read a file from the sandbox workspace |
| `list_files` | Get the directory tree as JSON |
| `delete_file` | Delete a file or directory |
| `expose_port` | Forward a sandbox port to the host; returns URL |
| `snapshot` | Checkpoint workspace state |
| `fork` | Create a new sandbox from a snapshot |
| `destroy_sandbox` | Destroy the sandbox and wipe its workspace |
| `list_sandboxes` | List all running sandboxes |
| `get_sandbox_status` | Get full sandbox metadata and status |
| `pause_sandbox` | Freeze the sandbox (HITL takeover) |
| `resume_sandbox` | Resume after a pause |

**Connecting Claude Code (stdio):**
```json
// ~/.claude/config.json
{
  "mcpServers": {
    "minibox": { "command": "minibox", "args": ["mcp", "--transport", "stdio"] }
  }
}
```

**Connecting Claude.ai / Cursor (SSE):**
```json
{
  "mcpServers": {
    "minibox": { "url": "http://your-host:8080/mcp/sse", "transport": "sse" }
  }
}
```

---

## What's Next

These are the meaningful next steps — not a timeline, just a ranked list of what would make Minibox meaningfully better:

1. **CRIU checkpoints** — save and restore live process memory, not just files. True instant-resume for long-running agent sessions.
2. **GPU passthrough** — map `/dev/nvidia*` into namespaces for local model inference inside sandboxes.
3. **Multi-host orchestration** — distribute sandboxes across machines with a lightweight central registry.
4. **TypeScript/Node SDK** — NPM package matching the Python client for Node/Bun agent authors.
5. **Sandbox templates as OCI layers** — pull and cache template environments as container image layers for faster cold starts.
