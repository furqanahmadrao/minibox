"""Authentication system — JWT + scoped API keys + rate limiting + audit logging."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Scope definitions
# ---------------------------------------------------------------------------

SCOPES = {
    # Sandboxes
    "sandbox:create": "Create sandboxes",
    "sandbox:read": "View sandbox status and list",
    "sandbox:update": "Update sandbox config (TTL, CPU, memory)",
    "sandbox:destroy": "Destroy sandboxes",
    "sandbox:pause": "Pause/resume sandboxes",
    # Execution
    "exec:run": "Execute commands in sandboxes",
    "exec:terminal": "Open interactive terminals",
    # Filesystem
    "fs:read": "Read files from sandboxes",
    "fs:write": "Write/create files in sandboxes",
    "fs:delete": "Delete files from sandboxes",
    # Snapshots
    "snapshot:create": "Create snapshots/checkpoints",
    "snapshot:restore": "Restore/fork from snapshots",
    # Network
    "network:expose": "Expose ports from sandboxes",
    # Agent
    "agent:manage": "Configure agent providers and models",
    "agent:connect": "Connect to ACP agents",
    # MCP
    "mcp:tools": "Use MCP tools (create/exec/read/write)",
    # Admin
    "admin:users": "Manage users",
    "admin:keys": "Manage API keys",
    "admin:config": "View/modify server configuration",
}

# Predefined scope groups
SCOPE_GROUPS = {
    "read-only": ["sandbox:read", "fs:read", "exec:run"],
    "developer": [
        "sandbox:create", "sandbox:read", "sandbox:update", "sandbox:destroy",
        "exec:run", "exec:terminal",
        "fs:read", "fs:write", "fs:delete",
        "snapshot:create", "snapshot:restore",
        "network:expose",
        "mcp:tools",
    ],
    "admin": list(SCOPES.keys()),
    "mcp": [
        "sandbox:create", "sandbox:read", "sandbox:destroy",
        "exec:run",
        "fs:read", "fs:write", "fs:delete",
        "snapshot:create", "snapshot:restore",
        "network:expose",
        "mcp:tools",
    ],
}


def resolve_scopes(scope_strs: list[str]) -> list[str]:
    """Resolve scope strings, expanding groups into individual scopes."""
    resolved = []
    for s in scope_strs:
        if s in SCOPE_GROUPS:
            resolved.extend(SCOPE_GROUPS[s])
        elif s in SCOPES:
            resolved.append(s)
        else:
            raise ValueError(f"Unknown scope: {s}")
    return list(set(resolved))


def check_scope(required: str, granted: list[str]) -> bool:
    """Check if required scope is in granted scopes. Admin bypasses all."""
    if "admin:config" in granted:
        return True
    return required in granted


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with salt using PBKDF2-SHA256."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    try:
        salt_hex, dk_hex = hashed.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT helpers (no PyJWT dependency)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    import base64
    padding = 4 - len(s) % 4
    s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_jwt_token(
    payload: dict[str, Any],
    secret: str,
    algorithm: str = "HS256",
    expires_minutes: int = 60,
    refresh_expires_minutes: int | None = None,
) -> str:
    """Create a JWT token with optional refresh window."""
    header = {"alg": algorithm, "typ": "JWT"}
    now = int(time.time())
    payload["iat"] = now
    payload["exp"] = now + (expires_minutes * 60)
    payload["jti"] = secrets.token_urlsafe(16)

    # If refresh window specified, include refresh_exp
    if refresh_expires_minutes is not None:
        payload["refresh_exp"] = now + (refresh_expires_minutes * 60)

    header_b64 = _b64url_encode(json.dumps(header).encode())
    payload_b64 = _b64url_encode(json.dumps(payload).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verify_jwt_token(token: str, secret: str) -> dict | None:
    """Verify and decode a JWT token. Returns None if invalid."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        expected_sig = hmac.new(
            secret.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        actual_sig = _b64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64))

        # Check expiration
        exp = payload.get("exp", 0)
        if exp < time.time():
            return None

        return payload
    except Exception:
        return None


def can_refresh_token(token: str, secret: str) -> bool:
    """Check if a token is expired but within the refresh window."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False

        _, payload_b64, _ = parts
        payload = json.loads(_b64url_decode(payload_b64))

        now = time.time()
        exp = payload.get("exp", 0)
        refresh_exp = payload.get("refresh_exp")

        # Token is expired but refresh window is still open
        if exp < now and refresh_exp and refresh_exp > now:
            return True

        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

class AuditLog:
    """In-memory audit log for auth events."""

    def __init__(self, max_entries: int = 1000) -> None:
        self._entries: list[dict] = []
        self._max = max_entries

    def log(
        self,
        event: str,
        user: str = "",
        ip: str = "",
        details: dict | None = None,
        success: bool = True,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "user": user,
            "ip": ip,
            "success": success,
            "details": details or {},
        }
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]

    def get_recent(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._entries[-limit:]))


# Global audit log instance
audit_log = AuditLog()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token bucket rate limiter per IP."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        burst: int = 10,
    ) -> None:
        self._rpm = requests_per_minute
        self._burst = burst
        self._buckets: dict[str, dict] = {}
        self._login_attempts: dict[str, list[float]] = defaultdict(list)

    def _get_bucket(self, key: str) -> dict:
        now = time.time()
        if key not in self._buckets:
            self._buckets[key] = {"tokens": self._burst, "last_refill": now}
        bucket = self._buckets[key]
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(self._burst, bucket["tokens"] + elapsed * (self._rpm / 60))
        bucket["last_refill"] = now
        return bucket

    def allow(self, key: str) -> bool:
        bucket = self._get_bucket(key)
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        return False

    def check_login_rate(self, ip: str) -> bool:
        """Check if login attempt is allowed (5 attempts per minute)."""
        now = time.time()
        attempts = self._login_attempts[ip]
        # Remove attempts older than 60s
        self._login_attempts[ip] = [t for t in attempts if now - t < 60]
        if len(self._login_attempts[ip]) >= 5:
            return False
        self._login_attempts[ip].append(now)
        return True

    def get_retry_after(self, key: str) -> float:
        """Seconds until next token available."""
        bucket = self._get_bucket(key)
        if bucket["tokens"] >= 1:
            return 0
        return max(0, (1 - bucket["tokens"]) / (self._rpm / 60))


# Global rate limiter
rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# API key management (scoped)
# ---------------------------------------------------------------------------

class APIKeyStore:
    """API key store with scope support and persistence."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._keys: dict[str, dict] = {}
        self._db_path = db_path
        if db_path:
            self._load()

    def _load(self) -> None:
        if self._db_path and self._db_path.exists():
            try:
                data = json.loads(self._db_path.read_text())
                self._keys = data.get("keys", {})
            except Exception:
                pass

    def _save(self) -> None:
        if self._db_path:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path.write_text(json.dumps({"keys": self._keys}, indent=2))

    def create_key(
        self,
        name: str,
        scopes: list[str] | None = None,
        role: str = "user",
        expires_in_days: int | None = None,
    ) -> str:
        """Create a new API key. Returns the plaintext key (shown once)."""
        key = f"mb_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        # Resolve scopes (expand groups)
        if scopes:
            resolved = resolve_scopes(scopes)
        else:
            resolved = resolve_scopes(["developer"])

        entry: dict[str, Any] = {
            "name": name,
            "role": role,
            "scopes": resolved,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used": None,
            "use_count": 0,
        }
        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            entry["expires_at"] = expires_at.isoformat()
        self._keys[key_hash] = entry
        self._save()
        return key

    def validate_key(self, key: str) -> dict | None:
        """Validate an API key. Returns key info with scopes or None."""
        self._load()
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        info = self._keys.get(key_hash)
        if not info:
            return None
        expires_at = info.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    return None
            except (ValueError, TypeError):
                pass
        info["last_used"] = datetime.now(timezone.utc).isoformat()
        info["use_count"] = info.get("use_count", 0) + 1
        self._save()
        return info

    def revoke_key(self, key: str) -> bool:
        """Revoke an API key."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        if key_hash in self._keys:
            del self._keys[key_hash]
            self._save()
            return True
        return False

    def list_keys(self) -> list[dict]:
        """List all API keys (without the actual key values)."""
        return [
            {
                "name": v["name"],
                "role": v["role"],
                "scopes": v.get("scopes", []),
                "created_at": v["created_at"],
                "expires_at": v.get("expires_at"),
                "last_used": v.get("last_used"),
                "use_count": v.get("use_count", 0),
            }
            for v in self._keys.values()
        ]


# ---------------------------------------------------------------------------
# User management (simple, file-backed)
# ---------------------------------------------------------------------------

class UserStore:
    """Simple user store backed by a JSON file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._users: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._db_path.exists():
            try:
                self._users = json.loads(self._db_path.read_text())
            except Exception:
                pass

    def _save(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.write_text(json.dumps(self._users, indent=2))

    def create_user(self, username: str, password: str, role: str = "admin") -> dict:
        """Create a new user."""
        if username in self._users:
            raise ValueError(f"User '{username}' already exists")
        # Validate password strength
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        user = {
            "username": username,
            "password_hash": hash_password(password),
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._users[username] = user
        self._save()
        return {"username": username, "role": role, "created_at": user["created_at"]}

    def authenticate(self, username: str, password: str) -> dict | None:
        """Authenticate a user. Returns user info or None."""
        user = self._users.get(username)
        if user and verify_password(password, user["password_hash"]):
            return {"username": username, "role": user["role"]}
        return None

    def get_user(self, username: str) -> dict | None:
        """Get user info."""
        user = self._users.get(username)
        if user:
            return {"username": username, "role": user["role"]}
        return None

    def list_users(self) -> list[dict]:
        """List all users."""
        return [
            {"username": v["username"], "role": v["role"], "created_at": v["created_at"]}
            for v in self._users.values()
        ]


# ---------------------------------------------------------------------------
# Auth middleware (scopes, rate limiting, security headers, audit)
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware with scope enforcement, rate limiting, and audit."""

    EXEMPT_PATHS = {
        "/docs", "/openapi.json", "/redoc", "/health", "/",
        "/api/auth/login", "/api/auth/setup", "/api/auth/refresh",
        "/api/auth/status",
    }

    # Paths that require specific scopes
    SCOPE_MAP: dict[str, str] = {
        "POST /api/sandbox/create": "sandbox:create",
        "GET /api/sandbox/list": "sandbox:read",
        "GET /api/sandbox/{sandbox_id}": "sandbox:read",
        "GET /api/sandbox/{sandbox_id}/stats": "sandbox:read",
        "GET /api/sandbox/{sandbox_id}/events": "sandbox:read",
        "GET /api/sandbox/{sandbox_id}/terminal": "exec:terminal",
        "PATCH /api/sandbox/{sandbox_id}": "sandbox:update",
        "DELETE /api/sandbox/{sandbox_id}": "sandbox:destroy",
        "POST /api/sandbox/{sandbox_id}/pause": "sandbox:pause",
        "POST /api/sandbox/{sandbox_id}/resume": "sandbox:pause",
        "POST /api/sandbox/{sandbox_id}/exec": "exec:run",
        "POST /api/sandbox/{sandbox_id}/exec/batch": "exec:run",
        "GET /api/sandbox/{sandbox_id}/fs/read": "fs:read",
        "GET /api/sandbox/{sandbox_id}/fs/tree": "fs:read",
        "GET /api/sandbox/{sandbox_id}/fs/glob": "fs:read",
        "POST /api/sandbox/{sandbox_id}/fs/write": "fs:write",
        "DELETE /api/sandbox/{sandbox_id}/fs/delete": "fs:delete",
        "GET /api/sandbox/{sandbox_id}/snapshots": "sandbox:read",
        "POST /api/sandbox/{sandbox_id}/snapshot": "snapshot:create",
        "DELETE /api/sandbox/{sandbox_id}/snapshots/{snapshot_id}": "snapshot:restore",
        "POST /api/sandbox/{sandbox_id}/restore/{snapshot_id}": "snapshot:restore",
        "POST /api/sandbox/{sandbox_id}/fork": "snapshot:restore",
        "GET /api/sandbox/{sandbox_id}/ports": "sandbox:read",
        "POST /api/sandbox/{sandbox_id}/port/expose": "network:expose",
        "DELETE /api/sandbox/{sandbox_id}/port/{port}": "network:expose",
        "GET /api/sandbox/{sandbox_id}/schedules": "sandbox:read",
        "POST /api/sandbox/{sandbox_id}/schedules": "sandbox:update",
        "PATCH /api/sandbox/{sandbox_id}/schedules/{schedule_id}": "sandbox:update",
        "DELETE /api/sandbox/{sandbox_id}/schedules/{schedule_id}": "sandbox:update",
        "POST /api/sandbox/{sandbox_id}/schedules/{schedule_id}/run": "exec:run",
        "GET /api/templates": "sandbox:read",
        "GET /api/templates/{template_id}": "sandbox:read",
        "POST /api/templates": "sandbox:create",
        "GET /api/agent/providers": "agent:manage",
        "GET /api/agent/providers/{provider_id}": "agent:manage",
        "GET /api/agent/list": "agent:manage",
        "GET /api/agent/{agent_id}": "agent:manage",
        "POST /api/agent/fetch-models": "agent:manage",
        "GET /api/sandbox/acp/agents": "agent:connect",
        "POST /api/sandbox/{sandbox_id}/acp/start": "agent:connect",
        "POST /api/sandbox/{sandbox_id}/acp/stop": "agent:connect",
        "GET /api/sandbox/{sandbox_id}/acp/status": "agent:connect",
        "POST /api/sandbox/{sandbox_id}/acp/prompt": "agent:connect",
        "GET /api/sandbox/{sandbox_id}/acp/ws": "agent:connect",
        "GET /api/auth/users": "admin:users",
        "POST /api/auth/users": "admin:users",
        "GET /api/auth/api-keys": "admin:keys",
        "POST /api/auth/api-keys": "admin:keys",
        "DELETE /api/auth/api-keys/{key}": "admin:keys",
        "GET /api/auth/audit": "admin:users",
        "GET /api/admin/config": "admin:config",
        "PATCH /api/admin/config": "admin:config",
        "GET /api/admin/logs": "admin:config",
    }

    def __init__(
        self,
        app,
        api_key_store: APIKeyStore | None = None,
        allowed_origins: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.api_key_store = api_key_store
        self._allowed_origins = allowed_origins or ["*"]

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _match_scope_key(self, method: str, path: str) -> str | None:
        """Match request to a scope map key."""
        # Exact match first
        key = f"{method} {path}"
        if key in self.SCOPE_MAP:
            return self.SCOPE_MAP[key]

        # Pattern match (strip path params)
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "sandbox":
            pattern_key = f"{method} /api/sandbox/{{sandbox_id}}/{'/'.join(parts[3:])}"
            if pattern_key in self.SCOPE_MAP:
                return pattern_key
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        from src.config import get_config

        config = get_config()
        client_ip = self._get_client_ip(request)

        # Rate limit check
        if not rate_limiter.allow(client_ip):
            retry_after = rate_limiter.get_retry_after(client_ip)
            audit_log.log("rate_limited", ip=client_ip, details={"path": request.url.path})
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        # Skip auth if disabled, but inject a mock Admin user so that endpoints (like /api/auth/me) work
        if not config.auth.enabled:
            request.state.user = {
                "sub": "admin",
                "role": "admin",
                "scopes": resolve_scopes(["admin"]),
            }
            request.state.auth_method = "disabled"
            response = await call_next(request)
            return self._add_security_headers(request, response)

        # Skip auth for non-API/non-MCP routes (like frontend static assets, index.html)
        path = request.url.path
        if not (path.startswith("/api/") or path.startswith("/mcp")):
            response = await call_next(request)
            return self._add_security_headers(request, response)

        # Skip auth for exempt paths
        if path in self.EXEMPT_PATHS:
            response = await call_next(request)
            return self._add_security_headers(request, response)

        # Skip auth for static assets starting with /assets/
        if path.startswith("/assets/"):
            response = await call_next(request)
            return self._add_security_headers(request, response)

        # Parse auth
        user_info = None
        auth_method = None

        # Try Authorization: Bearer <jwt>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            # Try valid JWT first
            payload = verify_jwt_token(token, config.auth.jwt_secret)
            if payload:
                user_info = payload
                auth_method = "jwt"

            # If expired but within refresh window, decode payload without expiry check
            if not user_info and can_refresh_token(token, config.auth.jwt_secret):
                audit_log.log("token_refresh_needed", ip=client_ip)
                try:
                    parts = token.split(".")
                    _, payload_b64, _ = parts
                    payload = json.loads(_b64url_decode(payload_b64))
                except Exception:
                    payload = None

                if payload:
                    user_info = payload
                    auth_method = "jwt_refresh"

        # Try X-API-Key header or query parameter
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if api_key and not user_info:
            if api_key == config.auth.api_key:
                user_info = {"sub": "api_key", "role": "admin", "scopes": resolve_scopes(["admin"])}
                auth_method = "api_key_builtin"
            elif self.api_key_store:
                info = self.api_key_store.validate_key(api_key)
                if info:
                    user_info = {
                        "sub": info["name"],
                        "role": info["role"],
                        "scopes": info.get("scopes", []),
                    }
                    auth_method = "api_key"
                    audit_log.log(
                        "api_key_used",
                        user=info["name"],
                        ip=client_ip,
                        details={"path": request.url.path},
                    )

        # Try token from query parameter (for WebSocket/EventSource connections)
        if not user_info:
            token_param = request.query_params.get("token", "")
            if token_param:
                payload = verify_jwt_token(token_param, config.auth.jwt_secret)
                if payload:
                    user_info = payload
                    auth_method = "jwt_query"

        if not user_info:
            audit_log.log(
                "auth_failed",
                ip=client_ip,
                details={"path": request.url.path, "method": request.method},
                success=False,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized — provide X-API-Key or Authorization: Bearer <token>"},
            )

        # Scope check
        scopes = user_info.get("scopes", [])
        scope_key = self._match_scope_key(request.method, request.url.path)
        if scope_key and not check_scope(scope_key, scopes):
            audit_log.log(
                "scope_denied",
                user=user_info.get("sub", ""),
                ip=client_ip,
                details={"required": scope_key, "path": request.url.path},
                success=False,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": f"Insufficient scope: {scope_key} required"},
            )

        # Attach user info to request
        request.state.user = user_info
        request.state.auth_method = auth_method

        # Run route execution
        response = await call_next(request)
        return self._add_security_headers(request, response)

    def _add_security_headers(self, request: Request, response: Response) -> Response:
        """Helper to add security headers to any response."""
        if hasattr(response, "headers"):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

            # HSTS for HTTPS
            if request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )

            # CSP header
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self' data:;"
            )
        return response

