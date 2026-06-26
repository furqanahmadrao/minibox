# syntax=docker/dockerfile:1.7

# ── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline
COPY frontend/ .
RUN npm run build


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
# Ubuntu 24.04 — needed because bubblewrap does --ro-bind / / which exposes
# this container's filesystem into every sandbox. iproute2, iptables, git,
# node, and the ACP agent binaries all end up available inside sandboxes.
FROM ubuntu:24.04

LABEL org.opencontainers.image.title="Minibox"
LABEL org.opencontainers.image.description="Self-hosted agent sandbox"
LABEL org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3-pip \
    bubblewrap \
    iproute2 util-linux iptables ipset \
    socat \
    git \
    nodejs npm \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --no-cache-dir --ignore-installed pip --break-system-packages

# ACP agent binaries — visible inside every sandbox via --ro-bind / /
RUN npm install -g --no-fund --no-audit \
    @anthropic-ai/claude-code \
    @openai/codex \
    @earendil-works/pi-coding-agent \
 && npm cache clean --force

RUN groupadd --system minibox \
 && useradd --system --gid minibox --home /app --shell /bin/bash minibox

WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --break-system-packages ".[cli]"

COPY src/     src/
COPY cli/     cli/
COPY seccomp/ seccomp/
COPY --from=frontend-build /build/dist src/static/

RUN mkdir -p /data/workspaces /data/snapshots \
 && chown -R minibox:minibox /app /data

USER minibox

ENV MINIBOX_HOST=0.0.0.0 \
    MINIBOX_PORT=8080 \
    MINIBOX_WORKSPACE_ROOT=/data/workspaces \
    MINIBOX_SNAPSHOT_PATH=/data/snapshots \
    MINIBOX_AUTH_ENABLED=true \
    MINIBOX_DEFAULT_TTL=1800 \
    MINIBOX_NETWORK_MODE=egress-only \
    MINIBOX_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost:8080/health | grep -q '"status":"ok"' || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
