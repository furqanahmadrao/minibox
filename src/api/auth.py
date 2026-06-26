"""Authentication API endpoints — login, token refresh, scoped API keys, audit."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from src.auth import (
    SCOPE_GROUPS,
    SCOPES,
    APIKeyStore,
    UserStore,
    audit_log,
    can_refresh_token,
    create_jwt_token,
    rate_limiter,
    resolve_scopes,
    verify_jwt_token,
)
from src.config import get_config
from src.models.sandbox import (
    APIKeyCreateRequest,
    APIKeyResponse,
    LoginRequest,
    LoginResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserCreateRequest,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_user_store: UserStore | None = None
_api_key_store: APIKeyStore | None = None


def _get_user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        config = get_config()
        db_path = config.sandbox.workspace_root.parent / "users.json"
        _user_store = UserStore(db_path)
    return _user_store


def _get_api_key_store() -> APIKeyStore:
    global _api_key_store
    if _api_key_store is None:
        config = get_config()
        db_path = config.sandbox.workspace_root.parent / "api_keys.json"
        _api_key_store = APIKeyStore(db_path)
    return _api_key_store


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/status")
async def auth_status() -> dict:
    """Check auth status — tells frontend whether to show login or setup."""
    config = get_config()
    store = _get_user_store()
    users = store.list_users()
    has_users = len(users) > 0
    has_env_creds = bool(config.auth.username and config.auth.password)
    has_api_key = bool(config.auth.api_key)

    needs_setup = config.auth.enabled and not has_users and not has_env_creds and not has_api_key

    return {
        "auth_enabled": config.auth.enabled,
        "has_users": has_users,
        "has_env_credentials": has_env_creds,
        "has_api_key": has_api_key,
        "needs_setup": needs_setup,
    }


@router.post("/setup")
async def setup(req: UserCreateRequest) -> dict:
    """Initial setup — create first admin user."""
    store = _get_user_store()
    existing = store.list_users()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Users already exist. Use /api/auth/users instead.",
        )

    config = get_config()
    if len(req.password) < config.security.min_password_length:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {config.security.min_password_length} characters",
        )

    try:
        user = store.create_user(req.username, req.password, role="admin")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    audit_log.log("user_created", user=req.username, details={"role": "admin"})
    return {"message": "Admin user created", "user": user}


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    """Login and get JWT + refresh token."""
    config = get_config()
    client_ip = _get_client_ip(request)

    # Rate limit login attempts
    if not rate_limiter.check_login_rate(client_ip):
        audit_log.log("login_rate_limited", user=req.username, ip=client_ip, success=False)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in 60 seconds.",
        )

    user = None

    # 1) Try env-based credentials first
    if config.auth.username and config.auth.password:
        if req.username == config.auth.username and req.password == config.auth.password:
            user = {"username": req.username, "role": "admin"}

    # 2) Try user store
    if user is None:
        store = _get_user_store()
        user = store.authenticate(req.username, req.password)

    if not user:
        audit_log.log("login_failed", user=req.username, ip=client_ip, success=False)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create access token
    admin_scopes = resolve_scopes(["admin"])
    dev_scopes = resolve_scopes(["developer"])
    user_scopes = admin_scopes if user["role"] == "admin" else dev_scopes
    access_token = create_jwt_token(
        payload={
            "sub": user["username"],
            "role": user["role"],
            "scopes": user_scopes,
        },
        secret=config.auth.jwt_secret,
        algorithm=config.auth.jwt_algorithm,
        expires_minutes=config.auth.jwt_expire_minutes,
        refresh_expires_minutes=config.auth.jwt_refresh_minutes,
    )

    # Create refresh token (separate, longer-lived)
    refresh_token = create_jwt_token(
        payload={
            "sub": user["username"],
            "role": user["role"],
            "type": "refresh",
            "scopes": user_scopes,
        },
        secret=config.auth.jwt_secret,
        algorithm=config.auth.jwt_algorithm,
        expires_minutes=config.auth.jwt_refresh_minutes,
    )

    audit_log.log("login_success", user=req.username, ip=client_ip)

    return LoginResponse(
        token=access_token,
        refresh_token=refresh_token,
        expires_in=config.auth.jwt_expire_minutes * 60,
        refresh_expires_in=config.auth.jwt_refresh_minutes * 60,
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(req: TokenRefreshRequest, request: Request) -> TokenRefreshResponse:
    """Refresh an expired access token using a refresh token."""
    config = get_config()
    client_ip = _get_client_ip(request)

    # Verify the refresh token
    payload = verify_jwt_token(req.refresh_token, config.auth.jwt_secret)
    if not payload:
        # Check if it's within the refresh window
        if can_refresh_token(req.refresh_token, config.auth.jwt_secret):
            try:
                import base64

                parts = req.refresh_token.split(".")
                _, payload_b64, _ = parts
                padding = 4 - len(payload_b64) % 4
                payload_b64 += "=" * padding
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            except Exception:
                payload = None

        if not payload:
            audit_log.log("refresh_failed", ip=client_ip, success=False)
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token is not a refresh token")

    # Create new access token
    scopes = payload.get("scopes", resolve_scopes(["developer"]))
    access_token = create_jwt_token(
        payload={
            "sub": payload["sub"],
            "role": payload.get("role", "user"),
            "scopes": scopes,
        },
        secret=config.auth.jwt_secret,
        algorithm=config.auth.jwt_algorithm,
        expires_minutes=config.auth.jwt_expire_minutes,
        refresh_expires_minutes=config.auth.jwt_refresh_minutes,
    )

    # Create new refresh token (rotate)
    new_refresh_token = create_jwt_token(
        payload={
            "sub": payload["sub"],
            "role": payload.get("role", "user"),
            "type": "refresh",
            "scopes": scopes,
        },
        secret=config.auth.jwt_secret,
        algorithm=config.auth.jwt_algorithm,
        expires_minutes=config.auth.jwt_refresh_minutes,
    )

    audit_log.log("token_refreshed", user=payload["sub"], ip=client_ip)

    return TokenRefreshResponse(
        token=access_token,
        refresh_token=new_refresh_token,
        expires_in=config.auth.jwt_expire_minutes * 60,
    )


@router.get("/me")
async def get_me(request: Request) -> dict:
    """Get current user info with scopes."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "sub": user.get("sub", ""),
        "role": user.get("role", ""),
        "scopes": user.get("scopes", []),
        "auth_method": getattr(request.state, "auth_method", "unknown"),
    }


@router.get("/users")
async def list_users(request: Request) -> list[dict]:
    """List all users."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _get_user_store().list_users()


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(req: APIKeyCreateRequest, request: Request) -> APIKeyResponse:
    """Create a new API key with scopes."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    config = get_config()
    store = _get_api_key_store()

    # Validate scopes
    try:
        resolved = resolve_scopes(req.scopes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    key = store.create_key(
        name=req.name,
        scopes=req.scopes,
        role=req.role,
        expires_in_days=req.expires_in_days or config.security.default_key_expiry_days,
    )

    audit_log.log(
        "api_key_created",
        user=user.get("sub", ""),
        details={"key_name": req.name, "scopes": resolved},
    )

    from datetime import datetime, timezone

    return APIKeyResponse(
        key=key,
        name=req.name,
        role=req.role,
        scopes=resolved,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/api-keys")
async def list_api_keys(request: Request) -> list[dict]:
    """List all API keys."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _get_api_key_store().list_keys()


@router.delete("/api-keys/{key}")
async def revoke_api_key(key: str, request: Request) -> dict:
    """Revoke an API key."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=400, detail="Not authenticated")

    store = _get_api_key_store()
    if store.revoke_key(key):
        audit_log.log(
            "api_key_revoked",
            user=user.get("sub", ""),
            details={"key_prefix": key[:12] + "..."},
        )
        return {"revoked": True}
    raise HTTPException(status_code=404, detail="Key not found")


@router.get("/scopes")
async def list_scopes() -> dict:
    """List all available scopes and groups."""
    return {"scopes": SCOPES, "groups": SCOPE_GROUPS}


@router.get("/audit")
async def get_audit_log(request: Request, limit: int = 50) -> list[dict]:
    """Get recent audit log entries."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return audit_log.get_recent(limit)
