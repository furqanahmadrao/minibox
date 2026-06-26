"""CLI client — talks to Minibox REST API with persistent credentials."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx


CREDENTIALS_DIR = Path.home() / ".minibox"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"


class MiniboxClient:
    """HTTP client for the Minibox API with TLS + auth + auto-refresh."""

    def __init__(
        self,
        host: str | None = None,
        api_key: str | None = None,
        token: str | None = None,
        refresh_token: str | None = None,
        verify_ssl: bool = True,
        cert_path: str | None = None,
    ) -> None:
        self.host = (host or os.environ.get("MINIBOX_HOST", "https://localhost:8080")).rstrip("/")
        self.api_key = api_key or os.environ.get("MINIBOX_API_KEY", "")
        self.token = token or os.environ.get("MINIBOX_TOKEN", "")
        self.refresh_token = refresh_token or os.environ.get("MINIBOX_REFRESH_TOKEN", "")
        self._cert_path = cert_path
        self._verify_ssl = verify_ssl
        self._token_expires_at: float | None = None

        # Try to load persisted credentials if no explicit ones provided
        if not self.api_key and not self.token:
            self._load_credentials()

        # Build headers
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.api_key:
            headers["X-API-Key"] = self.api_key

        # SSL verification
        verify = True
        if not verify_ssl:
            verify = False
        elif cert_path:
            verify = cert_path

        self._client = httpx.Client(
            base_url=self.host,
            headers=headers,
            timeout=30.0,
            verify=verify,
        )

    def _load_credentials(self) -> None:
        """Load persisted credentials from ~/.minibox/credentials.json."""
        if CREDENTIALS_FILE.exists():
            try:
                data = json.loads(CREDENTIALS_FILE.read_text())
                # Match host
                if data.get("host") == self.host:
                    self.token = data.get("token", "")
                    self.refresh_token = data.get("refresh_token", "")
                    self.api_key = data.get("api_key", "")
                    self._token_expires_at = data.get("expires_at")
                    if self.token:
                        self._client.headers["Authorization"] = f"Bearer {self.token}"
                    elif self.api_key:
                        self._client.headers["X-API-Key"] = self.api_key
            except Exception:
                pass

    def _save_credentials(self) -> None:
        """Persist credentials to ~/.minibox/credentials.json."""
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "host": self.host,
            "token": self.token,
            "refresh_token": self.refresh_token,
            "api_key": self.api_key,
            "expires_at": self._token_expires_at,
        }
        CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))
        # Restrict permissions on Unix
        try:
            import stat
            CREDENTIALS_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
        except Exception:
            pass

    def clear_credentials(self) -> None:
        """Remove persisted credentials."""
        if CREDENTIALS_FILE.exists():
            CREDENTIALS_FILE.unlink()

    def _handle_error(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            print(f"Error ({response.status_code}): {detail}", file=sys.stderr)
            sys.exit(1)

    def _try_refresh_token(self) -> bool:
        """Try to refresh the access token using the refresh token."""
        if not self.refresh_token:
            return False

        try:
            # Direct POST without auth header
            resp = httpx.post(
                f"{self.host}/api/auth/refresh",
                json={"refresh_token": self.refresh_token},
                timeout=10.0,
                verify=self._cert_path or (False if not self._verify_ssl else True),
            )
            if resp.status_code == 200:
                data = resp.json()
                self.token = data["token"]
                self.refresh_token = data.get("refresh_token", self.refresh_token)
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                self._client.headers["Authorization"] = f"Bearer {self.token}"
                self._save_credentials()
                return True
        except Exception:
            pass
        return False

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make a request with auto-refresh on 401."""
        resp = self._client.request(method, path, **kwargs)

        # If 401 and we have a refresh token, try refreshing
        if resp.status_code == 401 and self.refresh_token:
            if self._try_refresh_token():
                # Retry the request with new token
                resp = self._client.request(method, path, **kwargs)

        return resp

    def login(self, username: str, password: str) -> dict:
        """Login and get JWT + refresh token. Persists credentials."""
        resp = self._client.post("/api/auth/login", json={
            "username": username,
            "password": password,
        })
        self._handle_error(resp)
        data = resp.json()

        # Update client with new tokens
        self.token = data["token"]
        self.refresh_token = data.get("refresh_token", "")
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        self._client.headers["Authorization"] = f"Bearer {self.token}"

        # Persist credentials
        self._save_credentials()

        return data

    def create(
        self,
        template: str = "python-dev",
        ttl: int = 1800,
        network: str = "egress-only",
        memory_mb: int = 512,
        label: str = "",
    ) -> dict:
        resp = self._request("POST", "/api/sandbox/create", json={
            "template": template,
            "ttl": ttl,
            "network": network,
            "memory_mb": memory_mb,
            "label": label,
        })
        self._handle_error(resp)
        return resp.json()

    def list(self) -> list[dict]:
        resp = self._request("GET", "/api/sandbox/list")
        self._handle_error(resp)
        return resp.json()

    def get(self, sandbox_id: str) -> dict:
        resp = self._request("GET", f"/api/sandbox/{sandbox_id}")
        self._handle_error(resp)
        return resp.json()

    def exec(self, sandbox_id: str, cmd: str, workdir: str = "/", timeout: float = 30) -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/exec", json={
            "cmd": cmd, "workdir": workdir, "timeout": timeout,
        })
        self._handle_error(resp)
        return resp.json()

    def exec_batch(self, sandbox_id: str, commands: list[str], workdir: str = "/") -> list[dict]:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/exec/batch", json={
            "commands": commands, "workdir": workdir,
        })
        self._handle_error(resp)
        return resp.json()

    def read(self, sandbox_id: str, path: str) -> dict:
        resp = self._request("GET", f"/api/sandbox/{sandbox_id}/fs/read", params={"path": path})
        self._handle_error(resp)
        return resp.json()

    def write(self, sandbox_id: str, path: str, content: str) -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/fs/write", json={
            "path": path, "content": content,
        })
        self._handle_error(resp)
        return resp.json()

    def tree(self, sandbox_id: str, path: str = "/") -> dict:
        resp = self._request("GET", f"/api/sandbox/{sandbox_id}/fs/tree", params={"path": path})
        self._handle_error(resp)
        return resp.json()

    def delete_file(self, sandbox_id: str, path: str) -> dict:
        resp = self._request("DELETE", f"/api/sandbox/{sandbox_id}/fs/delete", params={"path": path})
        self._handle_error(resp)
        return resp.json()

    def snapshot(self, sandbox_id: str, label: str = "") -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/snapshot", json={"label": label})
        self._handle_error(resp)
        return resp.json()

    def fork(self, sandbox_id: str, snapshot_id: str, label: str = "") -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/fork", json={
            "snapshot_id": snapshot_id, "label": label,
        })
        self._handle_error(resp)
        return resp.json()

    def snapshots(self, sandbox_id: str) -> list[dict]:
        resp = self._request("GET", f"/api/sandbox/{sandbox_id}/snapshots")
        self._handle_error(resp)
        return resp.json()

    def destroy(self, sandbox_id: str) -> dict:
        resp = self._request("DELETE", f"/api/sandbox/{sandbox_id}")
        self._handle_error(resp)
        return resp.json()

    def pause(self, sandbox_id: str) -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/pause")
        self._handle_error(resp)
        return resp.json()

    def resume(self, sandbox_id: str) -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/resume")
        self._handle_error(resp)
        return resp.json()

    def expose_port(self, sandbox_id: str, port: int) -> dict:
        resp = self._request("POST", f"/api/sandbox/{sandbox_id}/port/expose", json={"port": port})
        self._handle_error(resp)
        return resp.json()

    def templates(self) -> list[dict]:
        resp = self._request("GET", "/api/templates")
        self._handle_error(resp)
        return resp.json()

    def health(self) -> dict:
        resp = self._client.get("/health")
        return resp.json()

    def me(self) -> dict:
        """Get current user info with scopes."""
        resp = self._request("GET", "/api/auth/me")
        self._handle_error(resp)
        return resp.json()

    def scopes(self) -> dict:
        """List available scopes."""
        resp = self._request("GET", "/api/auth/scopes")
        self._handle_error(resp)
        return resp.json()

    def audit_log(self, limit: int = 50) -> list[dict]:
        """Get audit log."""
        resp = self._request("GET", "/api/auth/audit", params={"limit": limit})
        self._handle_error(resp)
        return resp.json()
