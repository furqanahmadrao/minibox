# Minibox

Minibox is a self-hosted sandbox runtime for AI coding agents. Give an agent an isolated Linux workspace — private filesystem, terminal, network policy, and resource limits — in under 50 ms. Control everything from a single web dashboard. Zero SaaS costs, one port, one container.

See [PLAN.md](./PLAN.md) for the full product spec.

---

## Features

### 🛡️ Secure Sandboxing
- **Bubblewrap + Linux namespaces** — PID, mount, network, user, UTS, and IPC isolation per sandbox
- **Read-only root filesystem** — host OS is read-only; only `/workspace` is writable by the agent
- **Seccomp filtering** — dangerous syscalls blocked by default (`ptrace`, `mount`, `io_uring`, etc.)
- **Cgroups v2 resource limits** — CPU, memory, and max process caps per sandbox
- **Network policies** — `isolated`, `egress-only` (allowlist), or `full` per sandbox

### 🤖 Agent Integration
- **ACP Bridge** — runs Claude Code, OpenCode, Codex, and Pi agents inside the sandbox; dashboard Agent tab is a chat interface over WebSocket
- **MCP Server** — built-in FastMCP server at `/mcp/sse`; plug into Claude Code, Claude.ai, Cursor without any custom code
- **Dynamic config injection** — agent settings, model config, and project instructions written to workspace automatically

### ⚙️ Management & Controls
- **Git-by-default workspaces** — auto-initialized git repo with background auto-commits for full audit history
- **Snapshots & forks** — checkpoint workspace state; fork into multiple sandboxes from any snapshot
- **Cron schedules** — create recurring commands per sandbox; enable/disable/trigger from dashboard
- **HITL breakpoints** — regex patterns on exec commands or file paths that pause and require manual approval
- **Settings panel** — manage users, API keys, templates, and server config from the UI; persists across restarts

---

## Project Structure

```
minibox/
├── src/
│   ├── main.py              # FastAPI app entrypoint (REST + MCP + static)
│   ├── config.py            # Settings (env vars + config.json overrides)
│   ├── auth.py              # JWT, scoped API keys, auth middleware
│   ├── api/                 # REST and WebSocket route handlers
│   │   ├── sandbox.py       # Sandbox lifecycle (create, pause, resume, destroy)
│   │   ├── exec.py          # Command execution + PTY terminal WebSocket
│   │   ├── filesystem.py    # File read/write/tree/delete
│   │   ├── snapshots.py     # Snapshot + fork
│   │   ├── schedules.py     # Cron schedule CRUD
│   │   ├── templates.py     # Template CRUD
│   │   ├── acp.py           # ACP agent session control
│   │   ├── agent.py         # Agent/provider metadata
│   │   ├── auth.py          # Login, tokens, API keys, users, audit
│   │   └── admin_config.py  # Config PATCH + live log stream
│   ├── core/                # Low-level sandboxing logic
│   │   ├── sandbox.py       # Bubblewrap wrapper
│   │   ├── executor.py      # Shell execution engine
│   │   ├── cgroups.py       # Cgroup v2 limits
│   │   ├── seccomp.py       # Seccomp profile compiler
│   │   ├── filesystem.py    # Traversal-safe file operations
│   │   ├── snapshots.py     # Tar-based checkpoints
│   │   ├── templates.py     # Built-in + custom template library
│   │   ├── acp.py           # ACP agent JSON-RPC bridge
│   │   └── scheduler.py     # Cron schedule store
│   ├── mcp/
│   │   ├── server.py        # FastMCP tool definitions
│   │   └── transport.py     # SSE mount + auth wrapper
│   ├── orchestration/
│   │   ├── registry.py      # Sandbox state registry (SQLite)
│   │   ├── reaper.py        # TTL auto-destroy loop
│   │   └── events.py        # SSE event bus
│   └── static/              # Compiled React dashboard assets
├── frontend/                # React SPA (Vite + TypeScript)
├── cli/                     # Python client SDK + CLI
├── seccomp/                 # Default seccomp syscall profiles
├── Dockerfile
├── pyproject.toml
├── README.md
└── PLAN.md                  # Product spec
```

---

## Quick Start

### Prerequisites
- Linux (bubblewrap sandbox features require Linux; API layer works on any OS)
- `bubblewrap` (`bwrap`), Python 3.10+, Node.js 20+

### Run the Backend
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m uvicorn src.main:app --host 0.0.0.0 --port 8080
```

### Run the Frontend (dev mode)
```bash
cd frontend
npm install
npm run dev        # Vite dev server with HMR
```

### Production (pre-compiled)
```bash
cd frontend && npm run build   # outputs to src/static/
python -m uvicorn src.main:app --host 0.0.0.0 --port 8080
# Dashboard served at http://localhost:8080
```

### Docker
```bash
docker run -d \
  -p 8080:8080 \
  -v minibox-data:/data \
  --cap-add SYS_ADMIN \
  minibox:latest
```
