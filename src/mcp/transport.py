"""MCP transport — mounts FastMCP on FastAPI with auth."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def mount_mcp(app: FastAPI) -> None:
    """Mount FastMCP server on the FastAPI app with auth middleware.

    MCP tools require either:
      - X-API-Key header with mcp:tools scope
      - Authorization: Bearer <jwt> with mcp:tools scope

    Endpoints:
      - POST /mcp          (Streamable HTTP transport — recommended)
      - GET  /mcp/sse      (SSE transport — legacy clients)
      - POST /mcp/messages (SSE message endpoint)
    """
    try:
        from src.mcp.server import get_mcp_http_app

        mcp_app = get_mcp_http_app()

        # Wrap MCP endpoints with auth check
        async def mcp_auth_middleware(request: Request, call_next):
            """Authenticate MCP requests before forwarding."""
            from src.auth import (
                audit_log,
                check_scope,
                rate_limiter,
                resolve_scopes,
                verify_jwt_token,
            )
            from src.config import get_config

            config = get_config()

            if not config.auth.enabled:
                return await call_next(request)

            # Rate limit
            client_ip = request.client.host if request.client else "unknown"
            if not rate_limiter.allow(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                )

            # Parse auth
            user_info = None

            # Try X-API-Key (header or query param)
            api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if api_key:
                if api_key == config.auth.api_key:
                    user_info = {
                        "sub": "api_key",
                        "role": "admin",
                        "scopes": resolve_scopes(["admin"]),
                    }
                else:
                    # Check scoped API keys
                    from src.api.auth import _get_api_key_store
                    store = _get_api_key_store()
                    info = store.validate_key(api_key)
                    if info:
                        user_info = {
                            "sub": info["name"],
                            "role": info["role"],
                            "scopes": info.get("scopes", []),
                        }

            # Try Bearer token (header or query param)
            if not user_info:
                auth_header = request.headers.get("Authorization", "")
                token = ""
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                else:
                    token = request.query_params.get("token", "")
                
                if token:
                    payload = verify_jwt_token(token, config.auth.jwt_secret)
                    if payload:
                        user_info = payload

            if not user_info:
                audit_log.log("mcp_auth_failed", ip=client_ip, success=False)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "MCP requires authentication — provide X-API-Key or Bearer token"},
                )

            # Check mcp:tools scope
            scopes = user_info.get("scopes", [])
            if not check_scope("mcp:tools", scopes):
                audit_log.log(
                    "mcp_scope_denied",
                    user=user_info.get("sub", ""),
                    ip=client_ip,
                    success=False,
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Insufficient scope: mcp:tools required"},
                )

            # Attach user info for downstream
            request.state.user = user_info
            return await call_next(request)

        # Add auth middleware to MCP sub-app
        from starlette.middleware import Middleware
        from starlette.middleware.base import BaseHTTPMiddleware

        class MCPAuthWrapper(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                return await mcp_auth_middleware(request, call_next)

        # Add auth middleware to MCP sub-app
        mcp_app.add_middleware(MCPAuthWrapper)

        # Mount on main app
        app.mount("/mcp", mcp_app)

        logger.info("MCP server mounted at /mcp with auth (requires mcp:tools scope)")

    except ImportError:
        logger.warning("FastMCP not available, skipping MCP server")
    except Exception as e:
        logger.error("Failed to mount MCP server: %s", e)
