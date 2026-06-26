"""ACP (Agent Client Protocol) bridge for running coding agents in sandboxes.

Implements the JSON-RPC over stdio protocol used by OpenCode, Claude Code, Codex, etc.
Reference: https://agentclientprotocol.com/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# ACP agent commands — env_keys match each agent's native env vars
ACP_AGENTS: dict[str, dict[str, Any]] = {
    "opencode": {
        "cmd": ["opencode"],
        "install": "npm install -g opencode",
        "env_keys": {
            "api_key": "OPENAI_API_KEY",
            "base_url": "OPENAI_BASE_URL",
            "model": "OPENCODE_MODEL",
        },
    },
    "claude-code": {
        "cmd": ["claude"],
        "install": "npm install -g @anthropic-ai/claude-code",
        "env_keys": {
            "api_key": "ANTHROPIC_API_KEY",
            "base_url": "ANTHROPIC_BASE_URL",
            "model": "ANTHROPIC_MODEL",
        },
    },
    "codex": {
        "cmd": ["codex"],
        "install": "npm install -g @openai/codex",
        "env_keys": {
            "api_key": "OPENAI_API_KEY",
            "base_url": "OPENAI_BASE_URL",
            "model": "CODEX_MODEL",
        },
    },
    "pi": {
        "cmd": ["pi"],
        "install": "npm install -g @earendil-works/pi-coding-agent",
        "env_keys": {
            "api_key": "ANTHROPIC_API_KEY",
            "base_url": "ANTHROPIC_BASE_URL",
            "model": "PI_MODEL",
        },
    },
}


@dataclass
class ACPMessage:
    jsonrpc: str = "2.0"
    method: str = ""
    params: dict | None = None
    id: int | str | None = None
    result: Any = None
    error: dict | None = None

    def to_json(self) -> str:
        msg: dict[str, Any] = {"jsonrpc": self.jsonrpc}
        if self.method:
            msg["method"] = self.method
        if self.params is not None:
            msg["params"] = self.params
        if self.id is not None:
            msg["id"] = self.id
        if self.result is not None:
            msg["result"] = self.result
        if self.error is not None:
            msg["error"] = self.error
        return json.dumps(msg) + "\n"

    @classmethod
    def from_json(cls, line: str) -> ACPMessage:
        data = json.loads(line)
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            method=data.get("method", ""),
            params=data.get("params"),
            id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
        )


@dataclass
class ACPSession:
    session_id: str
    sandbox_id: str
    agent_type: str
    cwd: str
    status: str = "initializing"  # initializing, ready, running, closed
    capabilities: dict = field(default_factory=dict)
    process: asyncio.subprocess.Process | None = None
    _msg_id: int = 0
    _pending: dict[int, asyncio.Future] = field(default_factory=dict)
    _updates: asyncio.Queue = field(default_factory=asyncio.Queue)

    def next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id


class ACPBridge:
    """Manages ACP agent sessions inside sandboxes."""

    def __init__(self) -> None:
        self._sessions: dict[str, ACPSession] = {}

    async def start_session(
        self,
        sandbox_id: str,
        agent_type: str,
        cwd: str = "/",
        api_key: str = "",
        base_url: str = "",
        model: str = "",
    ) -> ACPSession:
        """Start an ACP agent session in a sandbox."""
        if agent_type not in ACP_AGENTS:
            raise ValueError(f"Unknown agent type: {agent_type}")

        agent_cfg = ACP_AGENTS[agent_type]
        session_id = f"{sandbox_id}_{agent_type}_{id(cwd)}"

        # Build environment - strict isolation (only specified provider keys and sandbox-configured env vars)
        env = {}
        if api_key and "api_key" in agent_cfg["env_keys"]:
            env[agent_cfg["env_keys"]["api_key"]] = api_key
        if base_url and "base_url" in agent_cfg["env_keys"]:
            env[agent_cfg["env_keys"]["base_url"]] = base_url
        if model and "model" in agent_cfg["env_keys"]:
            env[agent_cfg["env_keys"]["model"]] = model

        try:
            from src.api.deps import get_registry
            registry = get_registry()
            state = await registry.get(sandbox_id)
            if state and state.env:
                env.update(state.env)
        except Exception as e:
            logger.warning("Failed to fetch sandbox env vars for ACP session: %s", e)

        # Start subprocess inside bubblewrap sandbox
        from src.core.sandbox import SandboxHandle as SH
        from src.core.executor import _build_exec_bwrap_args, _sanitize_workdir
        from src.config import get_config

        config_srv = get_config()
        workspace = config_srv.sandbox.sandbox_dir(sandbox_id)
        handle = SH(
            sandbox_id=sandbox_id,
            pid=0,
            workspace=workspace,
        )

        bwrap_args = _build_exec_bwrap_args(handle, env)
        safe_cwd = _sanitize_workdir(cwd)
        cmd = agent_cfg["cmd"]
        # Execute inside the sandbox via bash
        bwrap_args.extend(["/bin/bash", "-c", f"cd {safe_cwd} && " + " ".join(cmd)])

        logger.info("Starting ACP agent inside sandbox: %s (cwd=%s)", cmd, cwd)

        process = await asyncio.create_subprocess_exec(
            *bwrap_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        session = ACPSession(
            session_id=session_id,
            sandbox_id=sandbox_id,
            agent_type=agent_type,
            cwd=cwd,
            process=process,
        )

        self._sessions[session_id] = session

        # Start reader tasks
        asyncio.create_task(self._read_stdout(session))
        asyncio.create_task(self._read_stderr(session))

        # Send initialize
        try:
            result = await self._send_request(session, "initialize", {
                "clientInfo": {"name": "minibox", "version": "0.1.0"},
                "capabilities": {},
            })
            session.capabilities = result or {}
            session.status = "ready"

            # Send initialized notification
            await self._send_notification(session, "initialized", {})
        except Exception as e:
            logger.error("Failed to initialize ACP session: %s", e)
            session.status = "error"

        return session

    async def stop_session(self, session_id: str) -> None:
        """Stop an ACP agent session."""
        session = self._sessions.get(session_id)
        if not session:
            return

        session.status = "closed"
        if session.process and session.process.returncode is None:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                session.process.kill()

        # Cancel pending requests
        for future in session._pending.values():
            if not future.done():
                future.cancel()

        del self._sessions[session_id]

    async def send_prompt(self, session_id: str, prompt: str) -> AsyncIterator[dict]:
        """Send a prompt to an agent and stream updates."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status not in ("ready", "running"):
            raise ValueError(f"Session not ready: {session.status}")

        session.status = "running"

        # Send prompt request
        msg_id = session.next_id()
        request = ACPMessage(
            method="session/prompt",
            params={"sessionId": session.session_id, "prompt": prompt},
            id=msg_id,
        )

        # Put request in pending
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        session._pending[msg_id] = future

        # Send to process
        if session.process and session.process.stdin:
            data = request.to_json().encode()
            session.process.stdin.write(data)
            await session.process.stdin.drain()

        # Stream updates from queue
        try:
            while True:
                update = await asyncio.wait_for(session._updates.get(), timeout=300)
                if update is None:  # Sentinel for end of stream
                    break
                yield update
                if update.get("type") == "result":
                    break
        except asyncio.TimeoutError:
            yield {"type": "error", "data": "Timeout waiting for agent response"}
        finally:
            session.status = "ready"

    async def _send_request(self, session: ACPSession, method: str, params: dict, timeout: float = 30) -> Any:
        """Send a JSON-RPC request and wait for response."""
        msg_id = session.next_id()
        request = ACPMessage(method=method, params=params, id=msg_id)

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        session._pending[msg_id] = future

        if session.process and session.process.stdin:
            data = request.to_json().encode()
            session.process.stdin.write(data)
            await session.process.stdin.drain()

        return await asyncio.wait_for(future, timeout=timeout)

    async def _send_notification(self, session: ACPSession, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        notification = ACPMessage(method=method, params=params)
        if session.process and session.process.stdin:
            data = notification.to_json().encode()
            session.process.stdin.write(data)
            await session.process.stdin.drain()

    async def _read_stdout(self, session: ACPSession) -> None:
        """Read stdout from agent process and dispatch messages."""
        if not session.process or not session.process.stdout:
            return

        try:
            while True:
                line = await session.process.stdout.readline()
                if not line:
                    break

                text = line.decode().strip()
                if not text:
                    continue

                try:
                    msg = ACPMessage.from_json(text)
                    await self._dispatch_message(session, msg)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from ACP agent: %s", text[:200])
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error reading ACP stdout: %s", e)

    async def _read_stderr(self, session: ACPSession) -> None:
        """Read stderr from agent process for logging."""
        if not session.process or not session.process.stderr:
            return

        try:
            while True:
                line = await session.process.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    logger.debug("ACP stderr [%s]: %s", session.agent_type, text)
        except asyncio.CancelledError:
            pass

    async def _dispatch_message(self, session: ACPSession, msg: ACPMessage) -> None:
        """Dispatch a received JSON-RPC message."""
        # Response to a request
        if msg.id is not None and msg.id in session._pending:
            future = session._pending.pop(msg.id)
            if msg.error:
                future.set_exception(Exception(msg.error.get("message", "ACP error")))
            else:
                future.set_result(msg.result)
            return

        # Server notification
        if msg.method:
            update = {"type": msg.method, "data": msg.params}
            await session._updates.put(update)


# Global singleton
_acp_bridge: ACPBridge | None = None


def get_acp_bridge() -> ACPBridge:
    global _acp_bridge
    if _acp_bridge is None:
        _acp_bridge = ACPBridge()
    return _acp_bridge
