# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Minibox Is

Minibox is a **self-hosted sandbox runtime for AI coding agents**. It gives AI agents (Claude Code, Codex, OpenCode, Pi) an isolated Linux workspace — private filesystem, terminal, network policy, and resource limits — without paying per-sandbox-minute to a cloud provider.

The core value proposition: **one command, one port, zero SaaS tax**. A developer runs `docker run -p 8080:8080 minibox`, and they get a dashboard, REST API, and MCP server — all at `:8080`.

### Who It's For

- **Developers** running AI coding agents locally who want a dashboard with real controls (pause, take over terminal, inspect files, snapshot state).
- **Agents** that need isolated workspaces via MCP or REST API to write code, run tests, and experiment safely.
- **Admins** who manage multi-agent setups and need user/key management, audit trails, and resource governance.

### How We Win vs Alternatives

| Advantage over | Why we win |
|---|---|
| E2B / Daytona | Self-hosted, no per-minute cost, startup in ~50ms (bwrap) vs 2-5s (microVM) |
| Plain Docker | Agent-native API, built-in MCP server, HITL UI, isolation without a daemon |
| Manual setup | Everything packaged: auth, snapshots, cron, breakpoints, network policies — not DIY |

---

## Commands

### Backend (Python 3.11+)

```bash
# Dev server with hot reload
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

# Lint & format
ruff check src/ cli/
ruff format src/ cli/

# Tests (pytest — currently no tests/ directory exists, this is a gap)
pytest tests/ -v
```

### Frontend (React + Vite + TypeScript)

```bash
cd frontend
npm install
npm run dev          # Vite dev server with HMR, proxies to :8080
npm run build        # Compiles to ../src/static/ (served by FastAPI in production)
npm run lint         # ESLint
```

### Docker

```bash
docker build -t minibox .           # Multi-stage: Node build → Ubuntu runtime
docker run -d -p 8080:8080 --cap-add SYS_ADMIN -v minibox-data:/data minibox
```

---

## Architecture

Everything runs in a **single process on port 8080**. There are no separate services, no message queues, no external databases.

```
Port 8080
├── /           → React dashboard (static files from src/static/)
├── /api/*      → FastAPI REST + WebSocket endpoints
├── /mcp/sse    → MCP server (FastMCP, SSE + Streamable HTTP transports)
└── /docs       → Swagger UI
```

### The Isolation Stack (per sandbox)

Each sandbox wraps a shell process in layers of Linux isolation:

1. **Bubblewrap (bwrap)** — read-only host filesystem, writable `/workspace` mount
2. **Linux namespaces** — PID, mount, network, user, UTS, IPC
3. **Cgroups v2** — CPU, memory, and process count limits
4. **Seccomp-bpf** — blocks dangerous syscalls (ptrace, mount, io_uring, etc.)

This is what makes Minibox fast (~50ms startup) — no VM, no container daemon, just kernel primitives.

### Storage Layout

All state lives in `/data` (a Docker volume):

```
/data/
├── config.json          Runtime config overrides (editable from dashboard)
├── templates.json       Custom sandbox templates
├── api_keys.json        Scoped API keys
├── users.json           User accounts
├── port_forwards.db     SQLite — active port mappings
├── schedules.db         SQLite — cron schedules
├── workspaces/{id}/     Each sandbox's writable directory (git repo)
└── snapshots/           tar.gz workspace checkpoints
```

### Key Backend Modules

| Module | Purpose |
|---|---|
| `src/core/sandbox.py` | Bubblewrap invocation, namespace flags, git init |
| `src/core/executor.py` | Command execution (sync, batch, SSE stream) |
| `src/core/network.py` | veth pairs, iptables, port forwarding, DNS filtering |
| `src/core/acp.py` | ACP JSON-RPC bridge — runs Claude Code/OpenCode/Codex inside sandboxes |
| `src/orchestration/registry.py` | SQLite-backed sandbox state (status, TTL, resources) |
| `src/orchestration/reaper.py` | Background loop: TTL cleanup + git auto-commit every ~10 min |
| `src/orchestration/events.py` | SSE event bus for real-time dashboard updates |
| `src/mcp/server.py` | 18 MCP tools for sandbox lifecycle (create, exec, read/write files, snapshot, fork, etc.) |
| `src/auth.py` | JWT (access + refresh), scoped API keys, rate limiting, audit logging |
| `src/config.py` | Pydantic Settings — env vars → `Config` singleton, with `config.json` overlay |

### Frontend Structure

React SPA built with Zustand for state, xterm.js for the terminal, Tailwind for styling.

- **Dashboard** — sandbox card grid, create modal
- **SandboxPanel** — 11 tabs per sandbox: Overview, Usage, Terminal, Workspace, Diff, Logs, Snapshots, Schedules, Breakpoints, Agent, Settings
- **Auth** — Login, Setup (first-run admin creation), token management

The frontend talks to the backend via a typed REST client (`frontend/src/api/client.ts`) and receives real-time updates via SSE.

---

## Key Concepts

**Templates** — Predefined sandbox environments (python-dev, node-dev, rust-dev, etc.) that install packages on creation. Custom templates are stored in `templates.json`.

**Snapshots & Forks** — Checkpoint a workspace as tar.gz, restore it later, or fork it into a new sandbox for parallel exploration.

**HITL Breakpoints** — Regex patterns on exec commands or file write paths. When a command matches, execution pauses and waits for human approval in the dashboard.

**MCP vs ACP** — MCP is how external tools *manage* sandboxes (create, exec, read files). ACP is how coding agents *run inside* sandboxes (Claude Code gets a terminal in an isolated workspace).

---

## Configuration

All settings have sane defaults. Override via environment variables at container start, or live-patch from the dashboard (`PATCH /api/admin/config` — persists to `/data/config.json`).

Critical env vars:
- `MINIBOX_API_KEY` — admin API key (auto-generated if unset)
- `MINIBOX_JWT_SECRET` — set this for persistent tokens across restarts
- `MINIBOX_USERNAME` / `MINIBOX_PASSWORD` — bootstrap admin without the UI
- `MINIBOX_AUTH_ENABLED` — set to `false` to disable auth (dev only)

---

## Project Status

The core product is feature-complete at v0.1.0. **The main gap is testing and CI/CD** — there is no `tests/` directory and no GitHub Actions workflow. Before adding features, the project needs:

1. API tests (pytest + httpx AsyncClient, mocking bwrap/cgroups)
2. CI pipeline (lint, test, Docker build)
3. Edge case hardening (path traversal, concurrent access, error recovery)

See `PLAN.md` for the ranked feature roadmap (CRIU checkpoints, GPU passthrough, multi-host orchestration, TypeScript SDK, OCI template layers).
