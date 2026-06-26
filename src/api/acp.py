"""ACP (Agent Client Protocol) API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.api.deps import get_registry
from src.core.acp import ACP_AGENTS, get_acp_bridge

router = APIRouter(prefix="/api/sandbox", tags=["acp"])
logger = logging.getLogger(__name__)


class ACPStartRequest(BaseModel):
    agent_type: str
    cwd: str = "/"
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class ACPPromptRequest(BaseModel):
    session_id: str
    prompt: str


class ACPStatusResponse(BaseModel):
    session_id: str
    agent_type: str
    status: str
    capabilities: dict = {}


@router.get("/acp/agents")
async def list_acp_agents():
    """List available ACP agents with their install status."""
    get_acp_bridge()
    agents = []
    for agent_id, cfg in ACP_AGENTS.items():
        agents.append({
            "id": agent_id,
            "cmd": cfg["cmd"][0],
            "install_cmd": cfg["install"],
            "env_keys": cfg["env_keys"],
        })
    return agents


@router.post("/{sandbox_id}/acp/start", response_model=ACPStatusResponse)
async def start_acp_session(sandbox_id: str, req: ACPStartRequest) -> ACPStatusResponse:
    """Start an ACP agent session in a sandbox."""
    registry = get_registry()
    state = await registry.get(sandbox_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if state.status != "running":
        raise HTTPException(status_code=400, detail=f"Sandbox is {state.status}")

    bridge = get_acp_bridge()
    try:
        session = await bridge.start_session(
            sandbox_id=sandbox_id,
            agent_type=req.agent_type,
            cwd=req.cwd,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
        )
        return ACPStatusResponse(
            session_id=session.session_id,
            agent_type=session.agent_type,
            status=session.status,
            capabilities=session.capabilities,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to start ACP session: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to start agent: {str(e)}")


@router.post("/{sandbox_id}/acp/stop")
async def stop_acp_session(sandbox_id: str, session_id: str) -> dict:
    """Stop an ACP agent session."""
    bridge = get_acp_bridge()
    await bridge.stop_session(session_id)
    return {"status": "stopped"}


@router.get("/{sandbox_id}/acp/status", response_model=ACPStatusResponse)
async def get_acp_status(sandbox_id: str, session_id: str) -> ACPStatusResponse:
    """Get ACP session status."""
    bridge = get_acp_bridge()
    session = bridge._sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ACPStatusResponse(
        session_id=session.session_id,
        agent_type=session.agent_type,
        status=session.status,
        capabilities=session.capabilities,
    )


@router.post("/{sandbox_id}/acp/prompt")
async def acp_prompt(sandbox_id: str, req: ACPPromptRequest) -> dict:
    """Send a prompt to an ACP agent (non-streaming)."""
    bridge = get_acp_bridge()
    updates = []
    async for update in bridge.send_prompt(req.session_id, req.prompt):
        updates.append(update)
    return {"updates": updates}


@router.websocket("/{sandbox_id}/acp/ws")
async def acp_websocket(websocket: WebSocket, sandbox_id: str):
    """WebSocket endpoint for streaming ACP agent interaction."""
    await websocket.accept()

    bridge = get_acp_bridge()
    session_id = None

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "start":
                # Start a new session
                agent_type = data.get("agent_type", "opencode")
                cwd = data.get("cwd", "/")
                api_key = data.get("api_key", "")
                base_url = data.get("base_url", "")
                model = data.get("model", "")

                try:
                    session = await bridge.start_session(
                        sandbox_id=sandbox_id,
                        agent_type=agent_type,
                        cwd=cwd,
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                    )
                    session_id = session.session_id
                    await websocket.send_json({
                        "type": "started",
                        "session_id": session_id,
                        "status": session.status,
                        "capabilities": session.capabilities,
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "data": f"Failed to start: {str(e)}",
                    })

            elif data.get("type") == "prompt":
                # Send a prompt
                prompt = data.get("prompt", "")
                if not session_id:
                    await websocket.send_json({"type": "error", "data": "No active session"})
                    continue

                try:
                    async for update in bridge.send_prompt(session_id, prompt):
                        await websocket.send_json({
                            "type": "update",
                            "data": update,
                        })
                    await websocket.send_json({"type": "done"})
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "data": str(e),
                    })

            elif data.get("type") == "stop":
                # Stop the session
                if session_id:
                    await bridge.stop_session(session_id)
                    await websocket.send_json({"type": "stopped"})
                    session_id = None

    except WebSocketDisconnect:
        if session_id:
            await bridge.stop_session(session_id)
    except Exception as e:
        logger.error("ACP WebSocket error: %s", e)
        if session_id:
            await bridge.stop_session(session_id)
